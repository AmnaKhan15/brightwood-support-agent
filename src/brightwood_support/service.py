"""The service: visitor sandboxes, the chat turn, manager decisions, metrics and health.

Each visitor gets a private sandbox (their own copy of the store database) that is deleted after
30 minutes without use. Inside it, the three invented customers can each chat with the assistant,
and staff can approve or reject refunds.

Where things live:
  - Sandboxes: a Postgres schema each (or an in-memory SQLite database without DATABASE_URL).
  - Conversation history and paused approval workflows: the LangGraph checkpointer (Postgres).
  - Which sandboxes exist, rate limits, the daily AI budget: Redis (or an in-process fake).
  - Every turn and decision, for metrics: the run log (runlog.py).

Everything the assistant does is also returned in an "inspector" block, so the page can show
exactly what happened: what was stored, what was searched, what the AI was shown, which agent
handled it and which tools ran.
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from . import catalog, jobs, workflows
from .agent import GENERALIST, SPECIALISTS, KeywordRouter, LLMRouter, run_agent
from .approvals import ROLE_RANK, ApprovalQueue, ShopApprovals
from .auth import AuthError, Forbidden, role_of, verify_token
from .checkout import Checkouts
from .config import env_flag
from .db import Backend, backend_from_env
from .gateway import Gateway, Provider
from .guardrails import looks_like_injection, mask_private
from .idp import AUDIENCE, ISSUER, BuiltInIdP
from .payments import PaymentError, payments_from_env, verify_webhook
from .playbook import PlaybookModel
from .providers import GeminiModel, gemini_configured
from .rag import HashingEmbedder, load_corpus, semantic_from_env
from .runlog import RunLog
from .shop import Shop
from .speech import Speech, SpeechUnavailable, spoken_text
from .state import AiBudget, RateLimiter, SandboxRegistry, ping, redis_from_env
from .telemetry import run_latency, runs_counter, tokens_counter, tool_counter
from .tools import build_toolbox
from .tracing import Tracer

log = logging.getLogger(__name__)

HELP_DIR = Path(__file__).resolve().parents[2] / "data" / "help"
MAX_MESSAGE_CHARS = 500
VOICE_SUFFIX = (" The customer is speaking and will hear your answer read aloud: use one to three short, natural sentences, "
                "no lists, no markdown, no passage ids in brackets, and say amounts and dates the way a person would.")
SERDE = JsonPlusSerializer(allowed_msgpack_modules=[("brightwood_support.agent", "ToolCall")])


class RateLimited(Exception):
    pass


class NoSuchSession(Exception):
    pass


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
    if gemini_configured(env):
        fast.append(Provider("gemini-fast", CappedModel(GeminiModel(env["GEMINI_MODEL"], env), budget), timeout=15))
        strong_id = env.get("GEMINI_STRONG_MODEL") or env["GEMINI_MODEL"]
        strong.append(Provider("gemini-strong", CappedModel(GeminiModel(strong_id, env, timeout=25), budget), timeout=25))
    return Gateway({"fast": fast + [offline()], "strong": strong + [offline()]})


def build_router(budget: AiBudget, env=os.environ):
    if gemini_configured(env):
        return LLMRouter(CappedModel(GeminiModel(env["GEMINI_MODEL"], env, timeout=8), budget))
    return KeywordRouter()


def chat_thread(sid: str, cid: str) -> str:
    return f"chat:{sid}:{cid}"


def deciding_key(sid: str, approval_id: int) -> str:
    """Redis marker that a decision on this approval is being carried out (blocks double submits)."""
    return f"bw:deciding:{sid}:{approval_id}"


def _last(spans: list[dict], key: str):
    return next((sp["attrs"].get(key) for sp in reversed(spans) if sp["attrs"].get(key)), None)


class Session:
    def __init__(self, sid: str, shop: Shop, help_store) -> None:
        self.id = sid
        self.shop = shop
        self.help_store = help_store
        self.customers = shop.customers()  # fixed seed data: read once per sandbox
        self.names = {c["id"]: c["name"] for c in self.customers}
        self.queues: dict[str, ApprovalQueue] = {}
        self.toolboxes: dict[str, object] = {}
        self.inspect: dict[str, dict] = {}
        self.lock = threading.RLock()

    def customer(self, cid: str):
        if cid not in self.names:
            raise KeyError(cid)
        if cid not in self.toolboxes:
            tb = build_toolbox(self.help_store, self.shop, cid)
            self.toolboxes[cid] = tb
            self.queues[cid] = ApprovalQueue(tb.executors(), store=ShopApprovals(self.shop, cid))
        return self.toolboxes[cid], self.queues[cid]

    def find_queue(self, approval_id: int):
        row = self.shop.approval(approval_id)
        if row is None:
            raise KeyError(approval_id)
        _, queue = self.customer(row["customer_id"])
        return row["customer_id"], queue


class Service:
    def __init__(self, *, daily_ai_calls: int = 150, ttl: float = 1800, max_sessions: int = 300, per_minute: int = 12,
                 env=os.environ, clock: Callable[[], float] = time.time, backend: Backend | None = None, redis=None) -> None:
        self.env = env
        self.backend = backend or backend_from_env(env)
        self.redis = redis if redis is not None else redis_from_env(env)
        self.registry = SandboxRegistry(self.redis)
        self.limiter = RateLimiter(self.redis, clock)
        self.help_store = self.backend.help_store(HashingEmbedder(), semantic_from_env(env))
        self.help_store.add(load_corpus(HELP_DIR))
        self.budget = AiBudget(daily_ai_calls, r=self.redis)
        self.gateway = build_gateway(self.budget, env)
        self.router = build_router(self.budget, env)
        self.checkpointer = self.backend.checkpointer(SERDE)
        self.approvals = workflows.build_approval_graph(self._carry_out, self.checkpointer)
        self.runlog = RunLog(self.backend.main)
        self.checkouts = Checkouts(self.backend.main)
        self.site_url = env.get("SITE_URL", "http://localhost:3000").rstrip("/")
        self.idp = BuiltInIdP()
        self.payments = payments_from_env(env)
        self.webhook_secret = env.get("STRIPE_WEBHOOK_SECRET", "")
        self.speech = Speech(env)
        self.live_model = gemini_configured(env)
        self.price_per_1k = float(env["MODEL_PRICE_PER_1K_TOKENS"]) if env.get("MODEL_PRICE_PER_1K_TOKENS") else None
        self.demo_staff = env_flag(env, "DEMO_STAFF_LOGIN")
        self.staff_code = env.get("STAFF_ACCESS_CODE", "")
        self.version = (env.get("RENDER_GIT_COMMIT") or env.get("GIT_COMMIT") or "dev")[:12]
        self.sessions: dict[str, Session] = {}
        self.ttl, self.max_sessions, self.per_minute, self._clock = ttl, max_sessions, per_minute, clock
        self.started = clock()
        self._lock = threading.RLock()
        jobs.configure(self, env.get("REDIS_URL", ""))

    # --- sandboxes ------------------------------------------------------------------
    def _open(self, sid: str, create: bool) -> Session | None:
        db = self.backend.open_sandbox(sid, create=create)
        if db is None:
            return None
        return Session(sid, Shop(db, payments=self.payments, seed=create), self.help_store)

    def _drop(self, sid: str) -> None:
        s = self.sessions.pop(sid, None) or self._open(sid, create=False)
        threads = []
        if s is not None:  # the sandbox's conversations and approval workflows live in the checkpointer
            threads = [chat_thread(sid, c["id"]) for c in s.customers]
            threads += [workflows.thread(sid, a["id"])["configurable"]["thread_id"] for a in s.shop.approvals()]
        for t in threads:
            try:
                self.checkpointer.delete_thread(t)
            except Exception:  # noqa: BLE001 - leftover checkpoints are harmless
                pass
        self.registry.remove(sid)
        self.backend.drop_sandbox(sid)

    def _sweep(self, now: float) -> None:
        for sid in self.registry.idle_since(now - self.ttl):
            self._drop(sid)
        for sid in self.registry.oldest(self.registry.count() - self.max_sessions + 1):
            self._drop(sid)

    def create_session(self, sid: str | None = None) -> str:
        with self._lock:
            now = self._clock()
            self._sweep(now)
            sid = sid or secrets.token_urlsafe(16)
            self.sessions[sid] = self._open(sid, create=True)
            self.registry.touch(sid, now)
            return sid

    def session(self, sid: str | None) -> Session:
        with self._lock:
            now = self._clock()
            last = self.registry.last_used(sid) if sid else None
            if last is None or now - last > self.ttl:
                if sid and last is not None:
                    self._drop(sid)
                raise NoSuchSession(sid)
            s = self.sessions.get(sid)
            if s is None:  # a sandbox from before a restart: reopen it from Postgres
                s = self._open(sid, create=False)
                if s is None:
                    self.registry.remove(sid)
                    raise NoSuchSession(sid)
                self.sessions[sid] = s
            self.registry.touch(sid, now)
            return s

    def reset(self, sid: str) -> None:
        with self._lock:
            self._drop(sid)
        self.create_session(sid)

    # --- chat ---------------------------------------------------------------------
    def speak(self, sid: str, text: str) -> bytes:
        """A natural-voice WAV of an answer. Repeats come from the cache and cost nothing;
        new audio counts against the same per-minute limit and daily AI budget as chat."""
        self.session(sid)
        words = spoken_text(text or "")
        if not words:
            raise ValueError("nothing to say")
        if self.speech.cached(words) is None:
            # An answer is voiced in up to six short pieces, so allow several per message.
            if not self.limiter.allow(f"tts:{sid}", self.per_minute * 4):
                raise RateLimited("too many voice requests; wait a few seconds")
            if not self.budget.take():
                raise SpeechUnavailable("daily AI call cap reached")
        return self.speech.wav(words)

    def chat(self, sid: str, cid: str, text: str, voice: bool = False) -> dict:
        s = self.session(sid)
        text = (text or "").strip()[:MAX_MESSAGE_CHARS]
        if not text:
            raise ValueError("message is empty")
        if not self.limiter.allow(f"chat:{sid}", self.per_minute):
            raise RateLimited("too many messages; wait a few seconds")

        with s.lock:
            toolbox, queue = s.customer(cid)
            customer_email = s.shop.customer_email(cid)
            masker = lambda t: mask_private(t, keep_emails={customer_email})  # noqa: E731
            masked = masker(text)
            injected = looks_like_injection(text)
            before = {i.id for i in queue.pending()}

            started = time.perf_counter()
            tracer = Tracer()
            result = run_agent(
                self.gateway, toolbox, queue, text, mask=masker, max_steps=6, max_tokens=12_000, tracer=tracer,
                system_suffix=VOICE_SUFFIX if voice else "", router=self.router,
                checkpointer=self.checkpointer, thread_id=chat_thread(sid, cid), price_per_1k_tokens=self.price_per_1k,
            )
            millis = round((time.perf_counter() - started) * 1000)

            final = result.final_text or self._fallback_text(result.stopped)
            spans = [sp for sp in result.trace if sp["name"] == "model_call"]
            provider, route = _last(spans, "provider"), _last(spans, "route")
            fell_back = any(sp["attrs"].get("fell_back") for sp in spans)
            new_items = [item for item in queue.pending() if item.id not in before]

            with s.shop.batch():  # the turn's record in one transaction
                run_id = s.shop.log_run(cid, result.stopped, result.steps, result.tokens,
                                        ",".join(t["tool"] for t in result.tool_log), provider, route, millis, result.agent)
                m1 = s.shop.log_message(cid, "customer", masked, run_id)
                m2 = s.shop.log_message(cid, "assistant", final, run_id)
                if injected:
                    s.shop.log_audit("guardrail", "system", "rule_change_attempt", f"customer {cid} message flagged: {masked[:120]}")
                for item in new_items:
                    s.shop.log_audit("ai-assistant", "agent", "refund_requested",
                                     f"approval #{item.id}: refund ${float(item.args['amount']):.2f} on {item.args['order_id']} needs {item.approver}")
            for item in new_items:
                workflows.start(self.approvals, sid, cid, item.id)

            inspect = self._inspect(s, cid, text, masked, injected, result, final, run_id, (m1, m2), provider, route, millis, fell_back)
            s.inspect[cid] = inspect

        self.runlog.record_run(sid, cid, result.agent, inspect["state"], result.stopped, result.steps, result.tokens, millis,
                               provider, result.tool_log, injected, fell_back)
        labels = {"agent": result.agent or "none", "stopped": result.stopped, "provider": provider or "none"}
        runs_counter.add(1, labels)
        run_latency.record(millis, labels)
        tokens_counter.add(result.tokens, {"provider": provider or "none"})
        for t in result.tool_log:
            tool_counter.add(1, {"tool": t["tool"], "status": t["status"]})
        log.info("chat turn", extra={"ctx": {"run_id": run_id, "agent": result.agent, "state": inspect["state"], "stopped": result.stopped,
                                             "provider": provider, "millis": millis, "tokens": result.tokens,
                                             "tools": [f"{t['tool']}:{t['status']}" for t in result.tool_log]}})
        return {"reply": final, "state": inspect["state"], "steps": inspect["steps"], "inspect": inspect,
                "pending": len(queue.pending())}

    @staticmethod
    def _fallback_text(stopped: str) -> str:
        return {
            "step_cap": "I'm having trouble finishing that. I've stopped so nothing goes wrong. Please ask for a person and they'll take over.",
            "cost_cap": "That conversation used more than I'm allowed to spend. A person on the team can continue it.",
            "model_error": "I can't answer right now. Please try again in a moment, or ask for a person.",
        }.get(stopped, "Sorry, something went wrong.")

    def _inspect(self, s, cid, raw, masked, injected, result, final, run_id, message_ids, provider, route, millis, fell_back) -> dict:
        names = {"search_help": "Searched the help articles", "list_orders": "Listed your orders", "get_order": "Looked up an order",
                 "cancel_order": "Cancelled an order", "send_return_label": "Created a return label", "request_refund": "Requested a refund",
                 "escalate_to_human": "Handed over to a person"}
        pairs, calls = [], {}
        for m in result.messages:
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
        for (call, output), entry in zip(pairs, result.tool_log):
            kind = {"ok": "ok", "pending_approval": "wait"}.get(entry["status"], "no")
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
            if entry["status"] == "pending_approval":
                title = "Waiting for a manager"
            elif entry["status"] == "refused":
                title = f"{title}: refused by the store's rules"
            elif entry["status"] == "rejected":
                title = f"{title}: not allowed for this agent or bad arguments"
            steps.append({"kind": kind, "title": title, "detail": detail, "data": output[:600], "status": entry["status"], "tool": call.name})
        state = "ok"
        if result.stopped != "final":
            state = "stopped"
        elif any(t["status"] == "pending_approval" for t in result.tool_log):
            state = "waiting"
        elif injected:
            state = "refused"
        elif any(t["status"] in ("refused", "error", "rejected") for t in result.tool_log):
            state = "blocked"
        prompt = [{"role": m["role"], "text": m["content"] if m.get("content") else "; ".join(f"call {c.name}({json.dumps(c.args)})" for c in m.get("tool_calls", []))}
                  for m in result.messages]
        routing = None
        if result.agent:
            routing = {"agent": result.agent, "reason": result.route_reason or "",
                       "tools": list(SPECIALISTS.get(result.agent, GENERALIST).tools)}
        return {
            "run_id": run_id, "customer": cid, "state": state, "stopped": result.stopped, "provider": provider, "route": route,
            "agent": result.agent, "route_reason": result.route_reason, "routing": routing, "fell_back": fell_back,
            "millis": millis, "tokens": result.tokens, "typed": raw, "masked": masked,
            "stored": [{"table": "messages", "id": message_ids[0], "role": "customer"}, {"table": "messages", "id": message_ids[1], "role": "assistant"},
                       {"table": "runs", "id": run_id}],
            "retrieved": retrieved, "steps": steps, "prompt": prompt, "tools": list(result.trace),
            "summary": result.trace_summary,
            "gateway": self.gateway.report(), "retrieval": self.help_store.mode,
        }

    # --- staff ---------------------------------------------------------------------
    def staff_login(self, role: str, name: str = "visitor", code: str | None = None, client: str = "local") -> str:
        """Demo mode lets anyone try either role. Otherwise an access code is required, with a lockout on repeated failures."""
        if role not in ROLE_RANK:
            raise ValueError("unknown role")
        if not self.demo_staff:
            if not self.staff_code:
                raise Forbidden("staff sign-in is turned off on this server")
            if not (self.limiter.allow(f"login:{client}", 5, 300) and self.limiter.allow("login:all", 30, 300)):
                raise RateLimited("too many sign-in attempts; wait five minutes")
            if not hmac.compare_digest((code or "").encode(), self.staff_code.encode()):
                raise AuthError("wrong access code")
        return self.idp.mint(name, role)

    def decide(self, sid: str, token: str | None, approval_id: int, approve: bool) -> dict:
        """Check who is deciding, then hand the decision to the approval workflow (a background job)."""
        s = self.session(sid)
        claims = verify_token(token, self.idp.keys, audience=AUDIENCE, issuer=ISSUER)
        role = role_of(claims) or "none"
        who = claims["sub"]
        with s.lock:
            try:
                _, queue = s.find_queue(approval_id)
            except KeyError:
                raise ValueError("no such approval") from None
            try:
                queue.check(approval_id, role)
            except PermissionError as error:
                self._deny(s, who, role, approve, approval_id, error)
        if not self.redis.set(deciding_key(sid, approval_id), who, nx=True, ex=300):
            raise ValueError("this approval is already being processed")
        try:
            status = jobs.enqueue(jobs.decide_approval, sid, approval_id, approve, who, role, now=self.finish_decision)
        except PaymentError as error:
            raise ValueError(f"The payment provider did not complete the refund, so nothing was refunded and the request is still waiting. {error}") from None
        except Exception:
            self.redis.delete(deciding_key(sid, approval_id))  # could not even queue it
            raise
        return {"id": approval_id, "status": status or "processing", "by": who, "role": role}

    @staticmethod
    def _deny(s: Session, who: str, role: str, approve: bool, approval_id: int, error: Exception):
        s.shop.log_audit(who, role, "denied_" + ("approve" if approve else "reject"), f"approval #{approval_id}: {error}")
        raise Forbidden(str(error)) from None

    def finish_decision(self, sid: str, approval_id: int, approve: bool, who: str, role: str) -> str:
        """The job body: resume the paused workflow with this decision.

        The in-progress marker is released when the decision is done or has failed for good. While a queued
        job waits to retry a payment failure, the marker stays (it expires on its own), so nobody can decide twice.
        """
        try:
            s = self.session(sid)
            cid, _ = s.find_queue(approval_id)
            outcome = workflows.resume(self.approvals, sid, cid, approval_id, {"approve": approve, "by": who, "role": role})
        except (PaymentError, ConnectionError, TimeoutError):
            if jobs.inline():
                self.redis.delete(deciding_key(sid, approval_id))
            raise
        except Exception:
            self.redis.delete(deciding_key(sid, approval_id))
            raise
        self.redis.delete(deciding_key(sid, approval_id))
        return outcome

    def _carry_out(self, state: workflows.ApprovalState, decision: dict) -> str:
        """The workflow's last step. The queue checks the role again before any money moves."""
        sid, approval_id = state["sid"], state["approval_id"]
        approve, who, role = decision["approve"], decision["by"], decision["role"]
        s = self.session(sid)
        with s.lock:
            cid, queue = s.find_queue(approval_id)
            try:
                queue.approve(approval_id, role, who) if approve else queue.reject(approval_id, role, who)
            except PaymentError as error:
                s.shop.log_audit(who, role, "refund_failed", f"approval #{approval_id}: {error}")
                raise
            except PermissionError as error:
                self._deny(s, who, role, approve, approval_id, error)
            item = queue.get(approval_id)
            verb = "approved" if approve else "rejected"
            s.shop.log_audit(who, role, verb, f"approval #{approval_id}: refund ${float(item.args['amount']):.2f} on {item.args['order_id']}")
            note = (f"Update: a support manager approved your refund of ${float(item.args['amount']):.2f} for order {item.args['order_id']}." if approve
                    else f"Update: a support manager reviewed your refund request for order {item.args['order_id']} and could not approve it.")
            s.shop.log_message(cid, "system", note)
            row = s.shop.approval(approval_id)
        stamp = lambda t: datetime.strptime(t, "%Y-%m-%d %H:%M:%S")  # noqa: E731
        self.runlog.record_decision(sid, approval_id, verb, role, (stamp(row["decided_at"]) - stamp(row["created_at"])).total_seconds())
        log.info("approval decided", extra={"ctx": {"approval_id": approval_id, "decision": verb, "role": role}})
        return item.status

    # --- reading state for the pages ------------------------------------------------
    def state(self, sid: str, cid: str | None = None) -> dict:
        s = self.session(sid)
        with s.lock:
            rows = s.shop.approvals()
            pipe = self.redis.pipeline()
            for a in rows:
                pipe.exists(deciding_key(sid, a["id"]))
            deciding = pipe.execute() if rows else []
            approvals = []
            for a, busy in zip(rows, deciding):
                busy = busy and a["status"] == "pending"
                approvals.append({"id": a["id"], "customer": s.names.get(a["customer_id"], a["customer_id"]), "order_id": a["args"].get("order_id"),
                                  "amount": a["args"].get("amount"), "reason": a["args"].get("reason"), "needs": a["approver"],
                                  "status": "processing" if busy else a["status"], "decided_by": a["decided_by"]})
            out = {
                "customers": s.customers, "approvals": approvals,
                "tickets": s.shop.table("tickets"), "refunds": s.shop.refunds()[::-1],  # newest first, like the other tables
                "audit": s.shop.table("audit"), "runs": s.shop.table("runs", 20),
                "pending": sum(1 for a in approvals if a["status"] == "pending"),
            }
            if cid:
                if cid not in s.names:
                    raise KeyError(cid)
                out["orders"] = s.shop.list_orders(cid)
                out["messages"] = s.shop.messages(cid)
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
        return {"query": query, "mode": self.help_store.mode,
                "hits": [{"id": c.id, "heading": c.heading, "text": c.text, "score": round(sc, 3)} for c, sc in self.help_store.search(query, k=3)]}

    def articles(self) -> list[dict]:
        docs: dict[str, list] = {}
        for c in self.help_store.chunks:
            docs.setdefault(c.doc, []).append({"id": c.id, "heading": c.heading, "text": c.text})
        return [{"doc": d, "chunks": cs} for d, cs in docs.items()]

    # --- buying ---------------------------------------------------------------------------
    def products(self) -> list[dict]:
        return [p.public() for p in catalog.PRODUCTS]

    def _peek(self, sid: str) -> Session | None:
        """A sandbox without counting as a visit (its idle timer is left alone)."""
        with self._lock:
            if self.registry.last_used(sid) is None:
                return None
            return self.sessions.get(sid) or self._open(sid, create=False)

    def checkout(self, sid: str, cid: str, product_id: str) -> dict:
        """Start a purchase. With Stripe: a Checkout page to send the customer to. Without: a simulated, instant payment."""
        s = self.session(sid)
        if cid not in s.names:
            raise KeyError(cid)
        try:
            product = catalog.product(product_id)
        except KeyError:
            raise ValueError("unknown product") from None
        if not self.limiter.allow(f"checkout:{sid}", 10):
            raise RateLimited("too many checkouts; wait a minute")
        reference = self.checkouts.start(sid, cid, product.id)
        if hasattr(self.payments, "create_checkout"):
            session = self.payments.create_checkout(
                product, catalog.shipping_for(product.price_cents), reference,
                success_url=f"{self.site_url}/orders?checkout=done&session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{self.site_url}/?checkout=cancelled")
            self.checkouts.attach_session(reference, session["id"])
            return {"mode": "stripe", "url": session["url"]}
        order_id = self._fulfil(reference, f"sim_pay_{reference}")
        return {"mode": "simulated", "order_id": order_id}

    def confirm_checkout(self, sid: str, session_id: str) -> dict:
        """The success page asks: is this checkout paid? The server checks with Stripe itself before creating anything."""
        self.session(sid)
        if not hasattr(self.payments, "get_checkout"):
            raise ValueError("checkout confirmation needs Stripe")
        info = self.payments.get_checkout(session_id)
        row = self.checkouts.get(info["reference"] or "")
        if row is None or row["sid"] != sid:
            raise ValueError("this checkout does not belong to your sandbox")
        if not info["paid"]:
            return {"status": "unpaid"}
        return {"status": "paid", "order_id": self._fulfil(info["reference"], info["payment_intent"])}

    def _fulfil(self, reference: str, payment_ref: str) -> str | None:
        """Create the order for a paid purchase, exactly once (webhook and success page may both arrive)."""
        row = self.checkouts.claim(reference)
        if row is None:  # already done (or unknown): report what exists
            done = self.checkouts.get(reference)
            return done["order_id"] if done else None
        s = self._peek(row["sid"])
        if s is None:  # the sandbox expired before payment completed; nothing to attach the order to
            self.checkouts.release(reference)
            return None
        product = catalog.product(row["product_id"])
        try:
            with s.lock:
                order_id = s.shop.create_order(row["customer_id"], product, self.payments.name, payment_ref)
                s.shop.log_audit("checkout", "system", "order_placed", f"{order_id}: {product.name} paid via {self.payments.name}")
                s.shop.log_message(row["customer_id"], "system", f"Thanks! Order {order_id} for the {product.name} is confirmed. "
                                   "Ask me here if you need to track, cancel or return it.")
        except Exception:
            self.checkouts.release(reference)
            raise
        self.checkouts.finish(reference, order_id)
        log.info("order placed", extra={"ctx": {"order_id": order_id, "product": product.id, "payments": self.payments.name}})
        return order_id

    def advance_order(self, sid: str, cid: str, order_id: str) -> dict:
        """Demo control: ship or deliver an order now, so returns and refunds can be tried without waiting days."""
        s = self.session(sid)
        if cid not in s.names:
            raise KeyError(cid)
        with s.lock:
            order = s.shop.advance_order(cid, order_id)
            s.shop.log_audit("demo", "system", f"order_{order['status']}", f"{order_id} marked {order['status']} with the demo control")
        return order

    # --- payments webhooks ------------------------------------------------------------
    def handle_webhook(self, payload: bytes, signature: str | None) -> dict:
        """Verify a Stripe event, then apply it: a paid checkout creates its order, a refund update changes its status."""
        if not self.webhook_secret:
            raise PaymentError("webhooks are not enabled on this server")
        event = verify_webhook(payload, signature, self.webhook_secret)
        obj = (event.get("data") or {}).get("object") or {}
        if event.get("type") == "checkout.session.completed" and obj.get("payment_status") == "paid" and obj.get("client_reference_id"):
            return {"queued": False, "order_id": self._fulfil(obj["client_reference_id"], obj.get("payment_intent") or "")}
        if obj.get("object") != "refund" or "id" not in obj:
            return {"queued": False, "updated": 0}
        updated = jobs.enqueue(jobs.apply_refund_event, obj["id"], obj.get("status", "unknown"), now=self.apply_refund_status)
        return {"queued": True, "updated": updated}

    def apply_refund_status(self, provider_refund_id: str, status: str) -> int:
        updated = 0
        for sid in self.registry.all():
            with self._lock:  # a look, not a visit: the sandbox's idle timer is left alone
                s = self.sessions.get(sid) or self._open(sid, create=False)
            if s is None:
                continue
            with s.lock:
                if s.shop.update_refund_status(provider_refund_id, status):
                    updated += 1
                    s.shop.log_audit("stripe", "system", "refund_" + status, f"refund {provider_refund_id} reported {status}")
        return updated

    # --- operations ---------------------------------------------------------------------
    def metrics(self, days: int = 7) -> dict:
        return self.runlog.summary(max(1, min(days, 90)), self.price_per_1k)

    def health(self) -> dict:
        return {
            "ok": True, "version": self.version, "uptime_s": round(self._clock() - self.started),
            "mode": "gemini+offline-fallback" if self.live_model else "offline-assistant",
            "agents": "llm-supervisor" if isinstance(self.router, LLMRouter) else "keyword-supervisor",
            "database": self.backend.main.dialect, "redis": ping(self.redis), "jobs": "inline" if jobs.inline() else "redis-queue",
            "payments": self.payments.name, "retrieval": self.help_store.mode, "help_chunks": len(self.help_store),
            "staff_login": "demo" if self.demo_staff else ("access-code" if self.staff_code else "off"),
            "speech": "gemini" if self.speech.available else "browser",
            "sessions": self.registry.count(), "ai_calls_today": self.budget.used, "ai_daily_cap": self.budget.cap,
            "gateway": self.gateway.report(),
        }

