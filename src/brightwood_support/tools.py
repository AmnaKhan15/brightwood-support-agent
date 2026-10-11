"""The tools the support assistant may call.

Design choices:
  - Every tool is already tied to one signed-in customer. The assistant never passes a
    customer id, so it cannot look at or change anyone else's orders.
  - There is no tool that deletes anything and no tool that pays out money directly.
    Money moves only through request_refund, which the approval rules sit in front of.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from .approvals import cents, required_approver
from .rag import InMemoryStore
from .shop import NotFound, PolicyError, Shop


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    params: dict[str, tuple]  # parameter name -> allowed types
    fn: Callable[..., Any]
    precheck: Callable[..., str | None] | None = None  # runs before the approval gate


def _json_type(allowed: tuple) -> str:
    if allowed == (str,):
        return "string"
    if allowed == (int,):
        return "integer"
    return "number"


class ToolBox:
    def __init__(self, tools: list[Tool], policy: Callable[[str, dict], str | None] = required_approver) -> None:
        self._tools = {t.name: t for t in tools}
        self._policy = policy

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def executors(self) -> dict[str, Callable[..., Any]]:
        return {name: t.fn for name, t in self._tools.items()}

    def specs(self) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "params": sorted(t.params),
             "types": {k: _json_type(v) for k, v in t.params.items()}}
            for t in self._tools.values()
        ]

    def approver_for(self, name: str, args: dict) -> str | None:
        return self._policy(name, args)

    def precheck(self, name: str, args: dict) -> str | None:
        check = self._tools[name].precheck
        return check(**args) if check else None

    def validate(self, name: str, args: dict) -> str | None:
        """Return an error message for an unknown tool or bad arguments, else None."""
        if name not in self._tools:
            return f"unknown tool {name!r}; available: {', '.join(self.names())}"
        tool = self._tools[name]
        missing = set(tool.params) - set(args)
        extra = set(args) - set(tool.params)
        if missing or extra:
            return f"bad arguments for {name}: missing {sorted(missing)}, unexpected {sorted(extra)}"
        for key, allowed in tool.params.items():
            value = args[key]
            if isinstance(value, bool) or not isinstance(value, allowed):
                return f"argument {key!r} of {name} must be {' or '.join(t.__name__ for t in allowed)}"
        return None


def build_toolbox(help_store: InMemoryStore, shop: Shop, customer_id: str) -> ToolBox:
    auto_refunded = {"cents": 0}  # what the assistant has refunded alone in this conversation

    def search_help(query: str) -> str:
        hits = help_store.search(query, k=3)
        return "\n".join(f"[{chunk.id}] (match {score:.2f}) {chunk.text}" for chunk, score in hits)

    def list_orders() -> str:
        return json.dumps(shop.list_orders(customer_id))

    def get_order(order_id: str) -> str:
        return json.dumps(shop.get_order(customer_id, order_id))

    def cancel_order(order_id: str) -> str:
        return json.dumps(shop.cancel_order(customer_id, order_id))

    def send_return_label(order_id: str) -> str:
        return json.dumps(shop.send_return_label(customer_id, order_id))

    def request_refund(order_id: str, amount: float, reason: str) -> str:
        # Runs directly for small refunds, or from the approval screen for large ones.
        result = shop.issue_refund(customer_id, order_id, amount, reason)
        if required_approver("request_refund", {"amount": amount}) is None:
            auto_refunded["cents"] += cents(amount)
        return json.dumps(result)

    def refund_precheck(order_id: str, amount: float, reason: str) -> str | None:
        """Refuse a refund the rules would never allow, before it can reach a manager's queue."""
        try:
            shop.check_refund(customer_id, order_id, amount, reason)
        except (NotFound, PolicyError) as error:
            return str(error)
        return None

    def escalate_to_human(summary: str) -> str:
        return json.dumps(shop.create_ticket(customer_id, summary))

    def policy(name: str, args: dict) -> str | None:
        return required_approver(name, args, auto_refunded["cents"])

    return ToolBox([
        Tool("search_help", "Search the store's help articles. Returns passages with their ids. Use it before answering any policy question.",
             {"query": (str,)}, search_help),
        Tool("list_orders", "List the signed-in customer's orders.", {}, list_orders),
        Tool("get_order", "Look up one of the customer's orders by id: status, items, dates, tracking, refunds.",
             {"order_id": (str,)}, get_order),
        Tool("cancel_order", "Cancel an order that is still processing. Shipped orders cannot be cancelled.",
             {"order_id": (str,)}, cancel_order),
        Tool("send_return_label", "Send a free return label for a delivered order inside the 30 day window.",
             {"order_id": (str,)}, send_return_label),
        Tool("request_refund", "Refund part or all of an order's item price. Up to 50 dollars is done at once; more waits for a support manager.",
             {"order_id": (str,), "amount": (int, float), "reason": (str,)}, request_refund, precheck=refund_precheck),
        Tool("escalate_to_human", "Hand the conversation to a person by opening a ticket with a short summary. Use it for damaged goods, lost parcels, warranty claims, or anything you cannot decide.",
             {"summary": (str,)}, escalate_to_human),
    ], policy=policy)
