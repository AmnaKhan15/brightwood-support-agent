"""Human approval gate for money.

Policy (data/help/refunds.md):
  - The assistant may refund up to 50 dollars on its own, per refund.
  - A bigger refund needs a support manager.
  - Small refunds cannot be split to get around the limit: once the assistant has refunded
    100 dollars in one conversation, the next refund needs a manager too.
  - There is no tool that deletes anything.

The gate cannot be skipped because the only code path that runs a gated tool is
ApprovalQueue.approve, and it checks the approver's role first.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any, Callable

AGENT_REFUND_LIMIT_CENTS = 5000
AGENT_SESSION_REFUND_CAP_CENTS = 10000
ROLE_RANK = {"agent": 0, "support_manager": 1}


def cents(amount: float) -> int:
    return round(float(amount) * 100)


def required_approver(tool: str, args: dict, auto_refunded_cents: int = 0) -> str | None:
    """Return the role that must approve this call, or None if the assistant may do it alone."""
    if tool == "request_refund":
        amount = cents(args["amount"])
        if amount > AGENT_REFUND_LIMIT_CENTS or auto_refunded_cents + amount > AGENT_SESSION_REFUND_CAP_CENTS:
            return "support_manager"
    return None


@dataclass
class PendingApproval:
    id: int
    tool: str
    args: dict
    approver: str  # the minimum role that may approve it
    status: str = "pending"  # pending, approved or rejected
    result: Any = None


class ApprovalQueue:
    def __init__(self, executors: dict[str, Callable[..., Any]], ids: Any = None) -> None:
        self._executors = executors
        self._ids = ids if ids is not None else itertools.count(1)
        self._items: dict[int, PendingApproval] = {}

    def request(self, tool: str, args: dict, approver: str) -> PendingApproval:
        item = PendingApproval(id=next(self._ids), tool=tool, args=dict(args), approver=approver)
        self._items[item.id] = item
        return item

    def pending(self) -> list[PendingApproval]:
        return [i for i in self._items.values() if i.status == "pending"]

    def has(self, approval_id: int) -> bool:
        return approval_id in self._items

    def all(self) -> list[PendingApproval]:
        return list(self._items.values())

    def _decidable(self, approval_id: int, by_role: str) -> PendingApproval:
        item = self._items[approval_id]
        if item.status != "pending":
            raise ValueError(f"approval {approval_id} is already {item.status}")
        if ROLE_RANK.get(by_role, -1) < ROLE_RANK[item.approver]:
            raise PermissionError(f"{by_role!r} cannot decide; {item.approver!r} or higher is required")
        return item

    def approve(self, approval_id: int, by_role: str) -> Any:
        item = self._decidable(approval_id, by_role)
        item.result = self._executors[item.tool](**item.args)
        item.status = "approved"
        return item.result

    def reject(self, approval_id: int, by_role: str) -> None:
        self._decidable(approval_id, by_role).status = "rejected"
