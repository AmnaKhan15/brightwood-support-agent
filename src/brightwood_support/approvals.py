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
from typing import Any, Callable, Protocol

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


class ApprovalStore(Protocol):
    """Where the queue keeps its items. The default keeps them in memory; the service keeps them in the store's database."""

    def add(self, tool: str, args: dict, approver: str) -> int: ...
    def set(self, approval_id: int, status: str, decided_by: str | None, role: str | None) -> None: ...
    def load(self) -> list[PendingApproval]: ...


class MemoryApprovals:
    def __init__(self, ids: Any = None) -> None:
        self._ids = ids if ids is not None else itertools.count(1)

    def add(self, tool: str, args: dict, approver: str) -> int:
        return next(self._ids)

    def set(self, approval_id: int, status: str, decided_by: str | None, role: str | None) -> None:
        pass

    def load(self) -> list[PendingApproval]:
        return []


class ShopApprovals:
    """Approvals saved in the store's `approvals` table, so a pending refund survives a restart."""

    def __init__(self, shop, customer_id: str) -> None:
        self._shop, self._customer = shop, customer_id

    def add(self, tool: str, args: dict, approver: str) -> int:
        return self._shop.add_approval(self._customer, tool, args, approver)

    def set(self, approval_id: int, status: str, decided_by: str | None, role: str | None) -> None:
        self._shop.set_approval(approval_id, status, decided_by, role)

    def load(self) -> list[PendingApproval]:
        return [PendingApproval(r["id"], r["tool"], r["args"], r["approver"], r["status"])
                for r in self._shop.approvals(self._customer)]


class ApprovalQueue:
    def __init__(self, executors: dict[str, Callable[..., Any]], ids: Any = None, store: ApprovalStore | None = None) -> None:
        self._executors = executors
        self._store = store or MemoryApprovals(ids)
        self._items: dict[int, PendingApproval] = {i.id: i for i in self._store.load()}

    def request(self, tool: str, args: dict, approver: str) -> PendingApproval:
        item = PendingApproval(id=self._store.add(tool, dict(args), approver), tool=tool, args=dict(args), approver=approver)
        self._items[item.id] = item
        return item

    def pending(self) -> list[PendingApproval]:
        return [i for i in self._items.values() if i.status == "pending"]

    def has(self, approval_id: int) -> bool:
        return approval_id in self._items

    def get(self, approval_id: int) -> PendingApproval:
        return self._items[approval_id]

    def all(self) -> list[PendingApproval]:
        return list(self._items.values())

    def check(self, approval_id: int, by_role: str) -> PendingApproval:
        """Raise unless `by_role` may decide this item now. Safe to call before queueing the decision."""
        item = self._items[approval_id]
        if item.status != "pending":
            raise ValueError(f"approval {approval_id} is already {item.status}")
        if ROLE_RANK.get(by_role, -1) < ROLE_RANK[item.approver]:
            raise PermissionError(f"{by_role!r} cannot decide; {item.approver!r} or higher is required")
        return item

    def approve(self, approval_id: int, by_role: str, by: str | None = None) -> Any:
        item = self.check(approval_id, by_role)
        item.result = self._executors[item.tool](**item.args)
        item.status = "approved"
        self._store.set(approval_id, "approved", by, by_role)
        return item.result

    def reject(self, approval_id: int, by_role: str, by: str | None = None) -> None:
        item = self.check(approval_id, by_role)
        item.status = "rejected"
        self._store.set(approval_id, "rejected", by, by_role)
