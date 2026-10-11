"""The service: visitor sessions, the chat endpoint's logic, and the manager's decisions.

Each visitor gets a private sandbox (their own copy of the store database, in memory) that is
deleted after 30 minutes without use. Inside it, the three invented customers can each chat
with the assistant, and a staff login can approve or reject refunds.

Everything the assistant does is recorded in the sandbox database (messages, one row per AI
run, an audit log) and returned in an "inspector" block, so the page can show exactly what
happened: what was stored, what was searched, what the AI was shown, which tools ran.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections import deque
from datetime import date
from pathlib import Path
from typing import Callable

from .agent import SYSTEM_PROMPT, run_agent

VOICE_SUFFIX = (" The customer is speaking and will hear your answer read aloud: use one to three short, natural sentences, "
                "no lists, no markdown, no passage ids in brackets, and say amounts and dates the way a person would.")
from .approvals import ApprovalQueue, ROLE_RANK
from .auth import AuthError, Forbidden, role_of, verify_token
from .gateway import Gateway, Provider
from .guardrails import looks_like_injection, mask_private
from .idp import AUDIENCE, ISSUER, BuiltInIdP
from .payments import PaymentError, payments_from_env, verify_webhook
from .playbook import PlaybookModel
from .providers import GeminiModel
from .rag import HashingEmbedder, InMemoryStore, load_corpus
from .shop import Shop
from .tools import build_toolbox
from .tracing import Tracer

HELP_DIR = Path(__file__).resolve().parents[2] / "data" / "help"
MAX_MESSAGE_CHARS = 500


class RateLimited(Exception):
    pass


class NoSuchSession(Exception):
    pass


class AiBudget:
    """A daily cap on real-model calls, so a free quota cannot be used up by one busy day."""

    def __init__(self, calls_per_day: int, today: Callable[[], date] = date.today) -> None:
        self.cap, self._today, self._day, self.used = calls_per_day, today, today(), 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self._today() != self._day:
                self._day, self.used = self._today(), 0
            if self.used >= self.cap:
                return False
            self.used += 1
            return True


class CappedModel:
    """Wraps a real model. When the daily cap is spent it fails like an outage, so the gateway falls back."""

    def __init__(self, model, budget: AiBudget) -> None:
        self._model, self._budget = model, budget

    def next(self, messages, tool_specs):
        if not self._budget.take():
            raise ConnectionError("daily AI call cap reached")
        return self._model.next(messages, tool_specs)


def build_gateway(budget: AiBudget, env=os.environ) -> Gateway:
    offline = lambda: Provider("offline-assistant", PlaybookModel(), timeout=5)  # noqa: E731
    fast, strong = [], []
    if env.get("GEMINI_API_KEY") and env.get("GEMINI_MODEL"):
        fast.append(Provider("gemini-fast", CappedModel(GeminiModel(env["GEMINI_MODEL"], env["GEMINI_API_KEY"]), budget), timeout=15))
        strong_id = env.get("GEMINI_STRONG_MODEL") or env["GEMINI_MODEL"]
        strong.append(Provider("gemini-strong", CappedModel(GeminiModel(strong_id, env["GEMINI_API_KEY"]), budget), timeout=25))
    return Gateway({"fast": fast + [offline()], "strong": strong + [offline()]})


class Session:
    def __init__(self, sid: str, help_store: InMemoryStore, payments=None) -> None:
        self.id = sid
        self.shop = Shop(payments=payments)
        self.help_store = help_store
        self.ids = iter(range(1, 10**6))
        self.queues: dict[str, ApprovalQueue] = {}
        self.toolboxes: dict[str, object] = {}
        self.history: dict[str, list[dict]] = {}
        self.inspect: dict[str, dict] = {}
        self.stamps: deque[float] = deque()
        self.touched = time.time()
        self.lock = threading.Lock()

    def customer(self, cid: str):
        if cid not in {c["id"] for c in self.shop.customers()}:
            raise KeyError(cid)
        if cid not in self.toolboxes:
            tb = build_toolbox(self.help_store, self.shop, cid)
            self.toolboxes[cid] = tb
            self.queues[cid] = ApprovalQueue(tb.executors(), self.ids)
            self.history[cid] = []
        return self.toolboxes[cid], self.queues[cid]

    def find_queue(self, approval_id: int):
        for cid, q in self.queues.items():
            if q.has(approval_id):
                return cid, q
        raise KeyError(approval_id)


class Service:
    def __init__(self, *, daily_ai_calls: int = 150, ttl: float = 1800, max_sessions: int = 300, per_minute: int = 12,
                 env=os.environ, clock: Callable[[], float] = time.time) -> None:
        self.help_store = InMemoryStore(HashingEmbedder())
        self.help_store.add(load_corpus(HELP_DIR))
        self.budget = AiBudget(daily_ai_calls)
        self.gateway = build_gateway(self.budget, env)
        self.idp = BuiltInIdP()
        self.payments = payments_from_env(env)
        self.webhook_secret = env.get("STRIPE_WEBHOOK_SECRET", "")
        self.sessions: dict[str, Session] = {}
        self.ttl, self.max_sessions, self.per_minute, self._clock = ttl, max_sessions, per_minute, clock
        self._lock = threading.Lock()
        self.live_model = bool(env.get("GEMINI_API_KEY") and env.get("GEMINI_MODEL"))

    # --- sessions ---------------------------------------------------------------
    def create_session(self) -> str:
        with self._lock:
            now = self._clock()
            for sid in [s for s, v in self.sessions.items() if now - v.touched > self.ttl]:
                del self.sessions[sid]
            while len(self.sessions) >= self.max_sessions:
                del self.sessions[min(self.sessions, key=lambda s: self.sessions[s].touched)]
            sid = secrets.token_urlsafe(16)
            self.sessions[sid] = Session(sid, self.help_store, self.payments)
            self.sessions[sid].touched = now
            return sid

    def session(self, sid: str | None) -> Session:
        with self._lock:
            s = self.sessions.get(sid or "")
            if s is None or self._clock() - s.touched > self.ttl:
                self.sessions.pop(sid or "", None)
                raise NoSuchSession(sid)
            s.touched = self._clock()
            return s

    def reset(self, sid: str) -> None:
        with self._lock:
            self.sessions[sid] = Session(sid, self.help_store, self.payments)

    # --- chat ---------------------------------------------------------------------
    def chat(self, sid: str, cid: str, text: str, voice: bool = False) -> dict:
        s = self.session(sid)
        text = (text or "").strip()[:MAX_MESSAGE_CHARS]
        if not text:
            raise ValueError("message is empty")
        now = self._clock()
        while s.stamps and now - s.stamps[0] > 60:
            s.stamps.popleft()
        if len(s.stamps) >= self.per_minute:
            raise RateLimited("too many messages; wait a few seconds")
        s.stamps.append(now)

        with s.lock:
            toolbox, queue = s.customer(cid)
            customer_email = s.shop.db.execute("SELECT email FROM customers WHERE id=?", (cid,)).fetchone()["email"]
            masker = lambda t: mask_private(t, keep_emails={customer_email})  # noqa: E731
            masked = masker(text)
            injected = looks_like_injection(text)
            before_pending = len(queue.pending())

            started = time.perf_counter()
            tracer = Tracer()
            result = run_agent(
                self.gateway, toolbox, queue, text, history=list(s.history[cid]), mask=masker,
                max_steps=6, max_tokens=12_000, tracer=tracer,
                system_suffix=VOICE_SUFFIX if voice else "",
            )
            millis = round((time.perf_counter() - started) * 1000)

            final = result.final_text or self._fallback_text(result.stopped)
            spans = [sp for sp in result.trace if sp["name"] == "model_call"]
            provider = next((sp["attrs"].get("provider") for sp in reversed(spans) if sp["attrs"].get("provider")), None)
            route = next((sp["attrs"].get("route") for sp in reversed(spans) if sp["attrs"].get("route")), None)

            run_id = s.shop.log_run(cid, result.stopped, result.steps, result.tokens,
                                    ",".join(t["tool"] for t in result.tool_log), provider, route, millis)
            m1 = s.shop.log_message(cid, "customer", masked, run_id)
            m2 = s.shop.log_message(cid, "assistant", final, run_id)
            if injected:
                s.shop.log_audit("guardrail", "system", "rule_change_attempt", f"customer {cid} message flagged: {masked[:120]}")
            for item in queue.pending()[before_pending:]:
                s.shop.log_audit("ai-assistant", "agent", "refund_requested", f"approval #{item.id}: refund ${float(item.args['amount']):.2f} on {item.args['order_id']} needs {item.approver}")

            s.history[cid] += [{"role": "user", "content": masked}, {"role": "assistant", "content": final}]
            s.history[cid] = s.history[cid][-12:]

            inspect = self._inspect(s, cid, text, masked, injected, result, final, run_id, (m1, m2), provider, route, millis)
            s.inspect[cid] = inspect
            return {"reply": final, "state": inspect["state"], "steps": inspect["steps"], "inspect": inspect,
                    "pending": len(queue.pending())}

    @staticmethod
    def _fallback_text(stopped: str) -> str:
        return {
            "step_cap": "I'm having trouble finishing that. I've stopped so nothing goes wrong. Please ask for a person and they'll take over.",
            "cost_cap": "That conversation used more than I'm allowed to spend. A person on the team can continue it.",
            "model_error": "I can't answer right now. Please try again in a moment, or ask for a person.",
        }.get(stopped, "Sorry, something went wrong.")

    def _inspect(self, s, cid, raw, masked, injected, result, final, run_id, message_ids, provider, route, millis) -> dict:
        names = {"search_help": "Searched the help articles", "list_orders": "Listed your orders", "get_order": "Looked up an order",
                 "cancel_order": "Cancelled an order", "send_return_label": "Created a return label", "request_refund": "Requested a refund",
                 "escalate_to_human": "Handed over to a person"}
        pairs, calls = [], {}
        started = False
        for m in result.messages:
            if m["role"] == "user" and m["content"] == masked and not started:
                started = True
            if not started:
                continue
            if m["role"] == "assistant" and m.get("tool_calls"):
                for c in m["tool_calls"]:
                    calls[c.id] = c
            elif m["role"] == "tool":
                pairs.append((calls[m["tool_call_id"]], m["content"]))
        steps, retrieved = [], []
        if masked != raw:
            steps.append({"kind": "ok", "title": "Hid private details", "detail": "Card numbers, passwords and other people's emails are masked before the AI sees the message.",
                          "data": f"you typed: {masked}"})
        if injected:
            steps.append({"kind": "no", "title": "Message tried to change the rules",
                          "detail": "Flagged and logged. The rules live in the store and the approval gate, so this cannot work even if the AI were fooled.", "data": masked[:140]})
        for (call, output), log in zip(pairs, result.tool_log):
            kind = {"ok": "ok", "pending_approval": "wait"}.get(log["status"], "no")
            title = names.get(call.name, call.name)
            detail = f"{call.name}({', '.join(f'{k}={v!r}' for k, v in call.args.items())})"
            if call.name == "search_help":
                for line in output.splitlines():
                    try:
                        cid_, rest = line[1:].split("]", 1)
                        score = float(rest.split("(match ")[1].split(")")[0])
                        retrieved.append({"id": cid_, "score": score, "text": rest.split(") ", 1)[1]})
                    except (IndexError, ValueError):
                        pass
            if log["status"] == "pending_approval":
                title = "Waiting for a manager"
            elif log["status"] == "refused":
                title = f"{title}: refused by the store's rules"
            steps.append({"kind": kind, "title": title, "detail": detail, "data": output[:600], "status": log["status"]})
        state = "ok"
        if result.stopped != "final":
            state = "stopped"
        elif any(l["status"] == "pending_approval" for l in result.tool_log):
            state = "waiting"
        elif injected:
            state = "refused"
        elif any(l["status"] in ("refused", "error", "rejected") for l in result.tool_log):
            state = "blocked"
        prompt = [{"role": m["role"], "text": m["content"] if m.get("content") else "; ".join(f"call {c.name}({json.dumps(c.args)})" for c in m.get("tool_calls", []))}
                  for m in result.messages]
        return {
            "run_id": run_id, "customer": cid, "state": state, "stopped": result.stopped, "provider": provider, "route": route,
            "millis": millis, "tokens": result.tokens, "typed": raw, "masked": masked,
            "stored": [{"table": "messages", "id": message_ids[0], "role": "customer"}, {"table": "messages", "id": message_ids[1], "role": "assistant"},
                       {"table": "runs", "id": run_id}],
            "retrieved": retrieved, "steps": steps, "prompt": prompt, "tools": [sp for sp in result.trace],
            "summary": result.trace_summary, "system_prompt": SYSTEM_PROMPT,
            "gateway": self.gateway.report(),
        }

    # --- staff ---------------------------------------------------------------------
    def staff_login(self, role: str, name: str = "visitor") -> str:
        if role not in ROLE_RANK:
            raise ValueError("unknown role")
        return self.idp.mint(name, role)

    def decide(self, sid: str, token: str | None, approval_id: int, approve: bool) -> dict:
        s = self.session(sid)
        try:
            claims = verify_token(token, self.idp.keys, audience=AUDIENCE, issuer=ISSUER)
        except AuthError as error:
            raise AuthError(str(error)) from None
        role = role_of(claims) or "none"
        who = claims["sub"]
        with s.lock:
            try:
                cid, queue = s.find_queue(approval_id)
            except KeyError:
                raise ValueError("no such approval") from None
            try:
                if approve:
                    queue.approve(approval_id, role)
                else:
                    queue.reject(approval_id, role)
            except PaymentError as error:
                s.shop.log_audit(who, role, "refund_failed", f"approval #{approval_id}: {error}")
                raise ValueError(f"The payment provider did not complete the refund, so nothing was refunded and the request is still waiting. {error}") from None
            except PermissionError as error:
                s.shop.log_audit(who, role, "denied_" + ("approve" if approve else "reject"), f"approval #{approval_id}: {error}")
                raise Forbidden(str(error)) from None
            item = next(i for i in queue.all() if i.id == approval_id)
            verb = "approved" if approve else "rejected"
            s.shop.log_audit(who, role, verb, f"approval #{approval_id}: refund ${float(item.args['amount']):.2f} on {item.args['order_id']}")
            amount = item.args.get("amount")
            note = (f"Update: a support manager approved your refund of ${float(amount):.2f} for order {item.args['order_id']}." if approve
                    else f"Update: a support manager reviewed your refund request for order {item.args['order_id']} and could not approve it.")
            s.shop.log_message(cid, "system", note)
            return {"id": approval_id, "status": item.status, "by": who, "role": role}

    # --- reading state for the pages ------------------------------------------------
    def state(self, sid: str, cid: str | None = None) -> dict:
        s = self.session(sid)
        with s.lock:
            approvals = []
            names = {c["id"]: c["name"] for c in s.shop.customers()}
            for c, q in s.queues.items():
                for i in q.all():
                    approvals.append({"id": i.id, "customer": names[c], "order_id": i.args.get("order_id"), "amount": i.args.get("amount"),
                                      "reason": i.args.get("reason"), "needs": i.approver, "status": i.status})
            approvals.sort(key=lambda a: a["id"])
            out = {
                "customers": s.shop.customers(), "approvals": approvals,
                "tickets": s.shop.table("tickets"), "refunds": s.shop.table("refunds"),
                "audit": s.shop.table("audit"), "runs": s.shop.table("runs", 20),
                "pending": sum(1 for a in approvals if a["status"] == "pending"),
            }
            if cid:
                out["orders"] = s.shop.list_orders(cid)
                out["messages"] = list(reversed(s.shop.db.execute(
                    "SELECT id, role, text, created_at FROM messages WHERE customer_id=? ORDER BY id DESC LIMIT 60", (cid,)).fetchall()))
                out["messages"] = [dict(m) for m in out["messages"]]
                out["inspect"] = s.inspect.get(cid)
            return out

    def table(self, sid: str, name: str) -> list[dict]:
        s = self.session(sid)
        with s.lock:
            return s.shop.table(name, 100)

    def search_help(self, query: str) -> dict:
        query = query.strip()[:200]
        if not query:
            raise ValueError("type a question")
        return {"query": query, "hits": [{"id": c.id, "heading": c.heading, "text": c.text, "score": round(sc, 3)}
                                         for c, sc in self.help_store.search(query, k=3)]}

    def articles(self) -> list[dict]:
        docs: dict[str, list] = {}
        for c in self.help_store._chunks:
            docs.setdefault(c.doc, []).append({"id": c.id, "heading": c.heading, "text": c.text})
        return [{"doc": d, "chunks": cs} for d, cs in docs.items()]

    def handle_webhook(self, payload: bytes, signature: str | None) -> int:
        """Apply a verified Stripe refund event to every sandbox that holds that refund. Returns rows updated."""
        if not self.webhook_secret:
            raise PaymentError("webhooks are not enabled on this server")
        event = verify_webhook(payload, signature, self.webhook_secret)
        obj = (event.get("data") or {}).get("object") or {}
        if obj.get("object") != "refund" or "id" not in obj:
            return 0
        updated = 0
        with self._lock:
            sessions = list(self.sessions.values())
        for s in sessions:
            with s.lock:
                if s.shop.update_refund_status(obj["id"], obj.get("status", "unknown")):
                    updated += 1
                    s.shop.log_audit("stripe", "system", "refund_" + obj.get("status", "update"), f"refund {obj['id']} reported {obj.get('status')}")
        return updated

    def health(self) -> dict:
        return {"ok": True, "payments": self.payments.name, "mode": "gemini+offline-fallback" if self.live_model else "offline-assistant", "sessions": len(self.sessions),
                "ai_calls_today": self.budget.used, "ai_daily_cap": self.budget.cap, "gateway": self.gateway.report(),
                "help_chunks": len(self.help_store._chunks) if hasattr(self.help_store, "_chunks") else None}
