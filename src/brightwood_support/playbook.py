"""The offline assistant: a rule-based model that plugs into the same agent loop as Gemini.

It is not an LLM. It reads the conversation, decides which tool to call next, and writes the
final reply from the tool results. It exists so the site keeps working when the real model is
unavailable (no key, free quota used up, provider down): the gateway falls back to it, and the
page says which one answered.

It speaks the same protocol as a real model (messages in, tool calls or text out), so every
protection around it (validation, approval gate, masking, tracing) is exercised exactly the same.
"""
from __future__ import annotations

import json
import re

from .agent import Reply, ToolCall

ORDER_ID = re.compile(r"\bO\d{4}\b", re.I)
AMOUNT = re.compile(r"\$\s?(\d+(?:\.\d{1,2})?)")
from .guardrails import looks_like_injection  # noqa
MIN_MATCH = 0.18


def _turn(messages: list[dict]) -> tuple[str, list[dict], list[str]]:
    """The latest customer message, the tool calls made since (name, args, result), and earlier customer messages."""
    last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
    earlier = [m["content"] for m in messages[:last_user] if m["role"] == "user"]
    names: dict[str, tuple[str, dict]] = {}
    done: list[dict] = []
    for m in messages[last_user + 1:]:
        if m["role"] == "assistant":
            for c in m.get("tool_calls", []):
                names[c.id] = (c.name, c.args)
        elif m["role"] == "tool":
            name, args = names[m["tool_call_id"]]
            done.append({"name": name, "args": args, "result": m["content"]})
    return messages[last_user]["content"], done, earlier


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _top_citation(done: list[dict]) -> tuple[str | None, str | None, float]:
    for d in done:
        if d["name"] == "search_help" and d["result"].startswith("["):
            m = re.match(r"\[([^\]]+)\] \(match ([\d.]+)\) (.*)", d["result"].splitlines()[0])
            if m:
                return m.group(1), m.group(3), float(m.group(2))
    return None, None, 0.0


class PlaybookModel:
    last_provider = "offline-assistant"
    last_route = "fallback"

    def __init__(self) -> None:
        self._n = 0

    def _call(self, name: str, **args) -> Reply:
        self._n += 1
        return Reply(tool_calls=[ToolCall(f"pb-{self._n}", name, args)], tokens=40)

    def next(self, messages: list[dict], tool_specs: list[dict]) -> Reply:
        text, done, earlier = _turn(messages)
        t = text.lower()
        called = {d["name"] for d in done}
        in_text = ORDER_ID.search(text)
        order = in_text.group(0) if in_text else None
        if not order and not re.search(r"\?|\bhow\b|\bwhat\b|window|policy|can i|do you", t):
            for old in reversed(earlier):
                m = ORDER_ID.search(old)
                if m:
                    order = m.group(0)
                    break
        order = order.upper() if order else None
        amount = AMOUNT.search(text)
        cite_id, cite_text, match = _top_citation(done)

        def say(body: str) -> Reply:
            return Reply(text=body, tokens=60)

        def cite() -> str:
            return f" [{cite_id}]" if cite_id else ""

        # 1. a message that tries to change the rules
        if looks_like_injection(text):
            return say("I can't change how I work, but I'm happy to help with your orders, returns or refunds. What do you need?")

        # 2. hand over to a person
        wants_person = re.search(r"human|real person|speak to|talk to (a |an )?(person|someone|agent)|manager", t) and "refund" not in t
        damaged = re.search(r"broke|broken|damag|cracked|faulty|defect|smash|not working|warranty", t)
        lost = re.search(r"lost|never arrived|not arrived|hasn.t arrived|not moving|stuck", t)
        if wants_person or damaged:
            if "search_help" not in called and damaged:
                return self._call("search_help", query="damaged or faulty item report")
            if "escalate_to_human" not in called:
                what = "Customer asked for a person." if wants_person else "Damaged or faulty item reported."
                return self._call("escalate_to_human", summary=f"{what} Order {order or 'not given'}. Customer said: {text[:140]}")
            ticket = _json(done[-1]["result"]) or {}
            extra = f" Damaged items can be replaced or fully refunded if reported within 14 days of delivery{cite()}. Please reply to the email with a photo." if damaged else ""
            return say(f"I've passed this to our support team as ticket #{ticket.get('ticket_id', '?')}, with a summary so you won't have to repeat yourself.{extra}")

        # 3. things that need an order
        action = None
        if re.search(r"cancel", t):
            action = "cancel"
        elif re.search(r"refund|money back|reimburse", t):
            action = "refund"
        elif re.search(r"return|send (it )?back|label", t) and (order or not re.search(r"\?|\bhow\b|\bwhat\b|window|policy|can i|do you", t)):
            action = "return"
        elif lost or re.search(r"\bo\d{4}\b|where|track|status|my order|orders\b|delivery|arrive", t):
            action = "lost" if lost else "status"

        if action:
            if "list_orders" in called and not order:
                orders = _json(next(d for d in done if d["name"] == "list_orders")["result"]) or []
                pool = [o for o in orders if (action == "cancel" and o["status"] == "processing")
                        or (action in ("refund", "return") and o["status"] == "delivered")]
                if action in ("status", "lost"):
                    lines = "\n".join(f"- {o['order_id']}: {o['status']}, {o['total']}" for o in orders)
                    return say(f"Here are your orders:\n{lines}\nTell me an order number and I can look closer.")
                if len(pool) == 1:
                    order = pool[0]["order_id"]
                else:
                    ids = " or ".join(o["order_id"] for o in pool)
                    return say(f"Which order do you mean? You can say {ids}." if pool else "I don't see an order on your account that I can do that for.")
            if not order and "list_orders" not in called:
                return self._call("list_orders")
            if action in ("cancel", "refund", "return") and "search_help" not in called:
                return self._call("search_help", query={"cancel": "cancel an order before it ships", "refund": "refund policy and limits",
                                                        "return": "how to return an item and return window"}[action])
            if "get_order" not in called:
                return self._call("get_order", order_id=order)
            got = next(d for d in done if d["name"] == "get_order")
            if got["result"].startswith("error"):
                return say(f"I can't find order {order} on your account. Could you check the number?")
            info = _json(got["result"])
            tool = {"cancel": "cancel_order", "return": "send_return_label"}.get(action)
            if action == "refund":
                if "request_refund" not in called:
                    item_total = sum(float(i["price"].strip("$")) for i in info["items"])
                    value = float(amount.group(1)) if amount else item_total
                    return self._call("request_refund", order_id=order, amount=value, reason=f"customer asked: {text[:80]}")
                out = done[[d["name"] for d in done].index("request_refund")]["result"]
                if out.startswith("PENDING_APPROVAL"):
                    return say(f"Order {order} is eligible, but refunds above $50 need a support manager's approval, so I've sent it to one. Nothing has been refunded yet; you'll hear back once it's reviewed.{cite()}")
                if out.startswith("error") and re.search(r"stripe|payment provider", out, re.I):
                    return say("I couldn't complete the refund because the payment provider didn't respond. Nothing was refunded. Please try again in a moment, or ask for a person.")
                if out.startswith("error"):
                    return say(f"I can't refund that: {out[7:].strip()}.{cite()}")
                r = _json(out)
                return say(f"Done. I've refunded {r['amount']} for order {order}. It arrives 5 to 7 business days after we receive the returned item.{cite()}")
            if tool and tool not in called:
                return self._call(tool, order_id=order)
            if tool:
                out = done[[d["name"] for d in done].index(tool)]["result"]
                if out.startswith("error"):
                    return say(f"I can't do that: {out[7:].strip()}.{cite()}")
                r = _json(out)
                if action == "cancel":
                    return say(f"Done. Order {order} is cancelled and {r['refund']} will go back to your original payment method within 3 business days.{cite()}")
                return say(f"I've created your free prepaid return label {r['label']}, valid until {r['valid_until']}. Print it, attach it and drop the parcel at any carrier location.{cite()}")
            if action == "lost":
                scan = info.get("last_tracking_scan_on")
                if info["status"] == "shipped" and scan and "escalate_to_human" not in called:
                    from datetime import date
                    if (date.today() - date.fromisoformat(scan)).days >= 7:
                        return self._call("escalate_to_human", summary=f"Parcel for {order} has not moved since {scan}. Replacement or refund needed.")
                if "escalate_to_human" in called:
                    ticket = _json(done[-1]["result"]) or {}
                    return say(f"Your parcel for {order} hasn't moved since {scan}, so I've opened ticket #{ticket.get('ticket_id', '?')} for a replacement or refund.")
            # plain status
            bits = [f"Order {order} is {info['status']}."]
            if info["shipped_on"]:
                bits.append(f"Shipped on {info['shipped_on']}.")
            if info["delivered_on"]:
                bits.append(f"Delivered on {info['delivered_on']}.")
            elif info["last_tracking_scan_on"]:
                bits.append(f"Last tracking update {info['last_tracking_scan_on']}, tracking {info['tracking']}.")
            bits.append(f"Total {info['total']}.")
            scan = info.get("last_tracking_scan_on")
            if info["status"] == "shipped" and scan:
                from datetime import date
                quiet = (date.today() - date.fromisoformat(scan)).days
                if quiet >= 7:
                    bits.append(f"There has been no tracking movement for {quiet} days, which counts as lost. Say 'it hasn't arrived' and I'll open a ticket for a replacement or refund.")
            return say(" ".join(bits))

        # 4. a policy question: answer from the passages the search returned
        if "search_help" not in called:
            return self._call("search_help", query=text[:200])
        if cite_id and match >= MIN_MATCH:
            return say(f"{cite_text}{cite()}")
        if "escalate_to_human" not in called:
            return self._call("escalate_to_human", summary=f"Question the help articles do not answer: {text[:160]}")
        ticket = _json(done[-1]["result"]) or {}
        return say(f"I couldn't find that in our help articles, so I've passed it to the support team as ticket #{ticket.get('ticket_id', '?')}.")
