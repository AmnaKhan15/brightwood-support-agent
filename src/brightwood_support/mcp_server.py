"""An MCP server that offers the support tools to any MCP client (for example Claude Desktop).

It reuses `dispatch` from the agent, so a client connecting over MCP gets the same validation,
approval gate, timeout, retry and masking as the website's assistant. One set of rules, not two.
The server acts for one signed-in customer, chosen when it starts (STOREDESK_CUSTOMER, default C1),
because the tools have no customer id parameter by design.

Run it:  PYTHONPATH=src python -m brightwood_support.mcp_server        (stdio transport)
"""
from __future__ import annotations

import os
import time

from mcp.server.mcpserver import MCPServer

from .agent import ToolCall, dispatch
from .approvals import ApprovalQueue
from .guardrails import mask_private
from .rag import HashingEmbedder, InMemoryStore, load_corpus
from .service import HELP_DIR
from .shop import Shop
from .tools import ToolBox, build_toolbox


def build_mcp_server(toolbox: ToolBox, queue: ApprovalQueue) -> MCPServer:
    server = MCPServer("brightwood-support")

    def run(name: str, **args) -> str:
        output = dispatch(ToolCall(id="mcp", name=name, args=args), toolbox, queue, [], [], 5.0, time.sleep)
        return mask_private(output)

    @server.tool()
    def search_help(query: str) -> str:
        """Search the store's help articles. Returns cited passages with match scores."""
        return run("search_help", query=query)

    @server.tool()
    def list_orders() -> str:
        """List the signed-in customer's orders."""
        return run("list_orders")

    @server.tool()
    def get_order(order_id: str) -> str:
        """Look up one of the customer's orders."""
        return run("get_order", order_id=order_id)

    @server.tool()
    def cancel_order(order_id: str) -> str:
        """Cancel an order that is still processing."""
        return run("cancel_order", order_id=order_id)

    @server.tool()
    def send_return_label(order_id: str) -> str:
        """Send a free return label for a delivered order inside the 30 day window."""
        return run("send_return_label", order_id=order_id)

    @server.tool()
    def request_refund(order_id: str, amount: float, reason: str) -> str:
        """Request a refund. Up to $50 is done at once; more waits for a support manager."""
        return run("request_refund", order_id=order_id, amount=amount, reason=reason)

    @server.tool()
    def escalate_to_human(summary: str) -> str:
        """Open a ticket so a person takes over."""
        return run("escalate_to_human", summary=summary)

    return server


def default_server(customer_id: str | None = None) -> tuple[MCPServer, Shop, ApprovalQueue]:
    store = InMemoryStore(HashingEmbedder())
    store.add(load_corpus(HELP_DIR))
    shop = Shop()
    toolbox = build_toolbox(store, shop, customer_id or os.environ.get("STOREDESK_CUSTOMER", "C1"))
    queue = ApprovalQueue(toolbox.executors())
    return build_mcp_server(toolbox, queue), shop, queue


if __name__ == "__main__":
    default_server()[0].run()
