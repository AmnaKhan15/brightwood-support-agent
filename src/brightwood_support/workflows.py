"""The manager-approval workflow: a LangGraph graph that pauses until a person decides.

    START -> wait_for_manager (interrupt) -> carry_out -> END

When the assistant asks for a refund above its limit, the service starts one workflow per request.
It runs to `interrupt()` and stops; the checkpointer (Postgres in production) keeps it paused for as
long as it takes, across restarts. A manager's decision resumes it with `Command(resume=...)`, and
`carry_out` runs the decision through the approval queue, which checks the role again before any
money moves. If the payment provider fails, the workflow stays at `carry_out` and is retried.
"""
from __future__ import annotations

from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt


class ApprovalState(TypedDict, total=False):
    sid: str
    customer: str
    approval_id: int
    decision: dict | None  # {"approve": bool, "by": str, "role": str}
    outcome: str | None


def build_approval_graph(carry_out: Callable[[ApprovalState, dict], str], checkpointer):
    def wait_for_manager(state: ApprovalState) -> dict:
        decision = interrupt({"approval_id": state["approval_id"], "customer": state["customer"]})
        return {"decision": decision}

    def run(state: ApprovalState) -> dict:
        return {"outcome": carry_out(state, state["decision"])}

    g = StateGraph(ApprovalState)
    g.add_node("wait_for_manager", wait_for_manager)
    g.add_node("carry_out", run)
    g.add_edge(START, "wait_for_manager")
    g.add_edge("wait_for_manager", "carry_out")
    g.add_edge("carry_out", END)
    return g.compile(checkpointer=checkpointer)


def thread(sid: str, approval_id: int) -> dict:
    return {"configurable": {"thread_id": f"approval:{sid}:{approval_id}"}}


def start(graph, sid: str, customer: str, approval_id: int) -> None:
    """Run the workflow up to the pause."""
    graph.invoke({"sid": sid, "customer": customer, "approval_id": approval_id, "decision": None, "outcome": None},
                 thread(sid, approval_id))


def resume(graph, sid: str, customer: str, approval_id: int, decision: dict) -> str:
    """Deliver a decision and run it. Safe to call again after a failure: it re-runs `carry_out` with this decision."""
    config = thread(sid, approval_id)
    snap = graph.get_state(config)
    if not snap.next:
        if snap.values.get("outcome"):
            return snap.values["outcome"]
        start(graph, sid, customer, approval_id)  # a request from before workflows existed, or lost in memory mode
        snap = graph.get_state(config)
    if snap.next == ("wait_for_manager",):
        out = graph.invoke(Command(resume=decision), config)
    else:  # an earlier attempt failed inside carry_out: record the latest decision and run it again
        graph.update_state(config, {"decision": decision}, as_node="wait_for_manager")
        out = graph.invoke(None, config)
    return out["outcome"]
