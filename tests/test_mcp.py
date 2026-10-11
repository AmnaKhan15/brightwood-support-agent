import asyncio
import unittest

from brightwood_support.mcp_server import default_server


class McpTests(unittest.TestCase):
    def test_tools_listed_and_rules_hold(self):
        server, shop, queue = default_server("C2")
        tools = asyncio.run(server.list_tools())
        self.assertEqual({t.name for t in tools}, {"search_help", "list_orders", "get_order", "cancel_order", "send_return_label", "request_refund", "escalate_to_human"})
        out = asyncio.run(server.call_tool("request_refund", {"order_id": "O2001", "amount": 189, "reason": "x"}))
        self.assertIn("PENDING_APPROVAL", str(out))
        self.assertEqual(shop.refunds(), [])
        self.assertEqual(len(queue.pending()), 1)


if __name__ == "__main__":
    unittest.main()
