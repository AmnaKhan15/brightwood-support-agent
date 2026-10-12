import hashlib
import hmac
import json
import time
import unittest

from fastapi.testclient import TestClient

from brightwood_support import catalog
from brightwood_support.server import create_app
from brightwood_support.service import Service
from brightwood_support.shop import PolicyError

DEMO = {"DEMO_STAFF_LOGIN": "true"}


class FakeStripe:
    """Stands in for Stripe's API: checkout sessions, their status, payment intents and refunds."""

    def __init__(self):
        self.sessions, self.calls = {}, []

    def __call__(self, url, headers, form):
        self.calls.append((url, form))
        if url.endswith("/checkout/sessions"):
            sid = f"cs_test_{len(self.sessions) + 1}"
            self.sessions[sid] = {"id": sid, "client_reference_id": form["client_reference_id"], "payment_status": "unpaid",
                                  "payment_intent": f"pi_test_{len(self.sessions) + 1}"}
            return {"id": sid, "url": f"https://checkout.stripe.com/c/pay/{sid}"}
        if "/checkout/sessions/" in url:
            return self.sessions[url.rsplit("/", 1)[1]]
        if url.endswith("/refunds"):
            return {"id": "re_test_1", "status": "succeeded"}
        raise AssertionError(url)

    def pay(self, session_id):
        self.sessions[session_id]["payment_status"] = "paid"


def sign(payload: bytes, secret: str) -> str:
    t = int(time.time())
    return f"t={t},v1=" + hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()


class CatalogTests(unittest.TestCase):
    def test_prices_and_shipping_follow_the_policy(self):
        self.assertEqual(catalog.product("table").public()["shipping_cents"], 0)   # $129 > $75: free shipping
        self.assertEqual(catalog.product("cushion").public()["shipping_cents"], 600)
        self.assertTrue(catalog.product("mug").final_sale)

    def test_product_mentions(self):
        self.assertEqual(catalog.mentioned("What is your return policy for the linen cushion cover set?").id, "cushion")
        self.assertEqual(catalog.mentioned("can I return the oak side table").id, "table")
        self.assertIsNone(catalog.mentioned("Where is my order?"))
        self.assertEqual(catalog.without_product("return policy for the oak side table?", catalog.product("table")), "return policy for the ?")


class SimulatedCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.svc = Service(env=DEMO, per_minute=100)
        self.sid = self.svc.create_session()

    def test_buy_then_cancel_refunds_that_purchase(self):
        out = self.svc.checkout(self.sid, "C1", "table")
        self.assertEqual(out["mode"], "simulated")
        order_id = out["order_id"]
        st = self.svc.state(self.sid, "C1")
        bought = next(o for o in st["orders"] if o["order_id"] == order_id)
        self.assertEqual((bought["status"], bought["total"]), ("processing", "$129.00"))
        self.assertIn(order_id, st["messages"][-1]["text"])  # the chat confirms the purchase
        r = self.svc.chat(self.sid, "C1", f"Cancel order {order_id}")
        self.assertIn("cancel", r["reply"].lower())
        refund = next(x for x in self.svc.state(self.sid)["refunds"] if x["order_id"] == order_id)
        self.assertEqual((refund["amount_cents"], refund["via"]), (12900, "cancellation"))

    def test_deliver_then_refund_needs_a_manager_over_50(self):
        order_id = self.svc.checkout(self.sid, "C2", "lamp")["order_id"]   # $100 + free shipping
        early = self.svc.chat(self.sid, "C2", f"Refund order {order_id}")  # not delivered yet: the store's rules refuse it
        self.assertEqual(early["state"], "blocked")
        self.assertFalse([x for x in self.svc.state(self.sid)["refunds"] if x["order_id"] == order_id])
        self.svc.advance_order(self.sid, "C2", order_id)
        self.assertEqual(self.svc.advance_order(self.sid, "C2", order_id)["status"], "delivered")
        r = self.svc.chat(self.sid, "C2", f"Refund order {order_id}")
        self.assertEqual(r["state"], "waiting")
        with self.assertRaises(PolicyError):
            self.svc.advance_order(self.sid, "C2", order_id)  # delivered is the last step

    def test_unknown_product_and_customer(self):
        with self.assertRaises(ValueError):
            self.svc.checkout(self.sid, "C1", "free-table")
        with self.assertRaises(KeyError):
            self.svc.checkout(self.sid, "C9", "table")

    def test_orders_are_per_sandbox(self):
        self.svc.checkout(self.sid, "C1", "towels")
        other = self.svc.create_session()
        self.assertEqual(len(self.svc.state(other, "C1")["orders"]), 3)


class StripeCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.svc = Service(env={**DEMO, "STRIPE_SECRET_KEY": "sk_test_abc", "STRIPE_WEBHOOK_SECRET": "whsec_x"}, per_minute=100)
        self.stripe = FakeStripe()
        self.svc.payments._post = self.stripe
        self.sid = self.svc.create_session()

    def test_checkout_uses_catalogue_prices_and_creates_the_order_once(self):
        out = self.svc.checkout(self.sid, "C3", "cushion")
        self.assertEqual(out["mode"], "stripe")
        form = self.stripe.calls[0][1]
        self.assertEqual((form["line_items[0][price_data][unit_amount]"], form["line_items[1][price_data][unit_amount]"]), (3200, 600))
        session_id = out["url"].rsplit("/", 1)[1]
        self.assertEqual(self.svc.confirm_checkout(self.sid, session_id), {"status": "unpaid"})
        self.stripe.pay(session_id)
        first = self.svc.confirm_checkout(self.sid, session_id)
        # Stripe's webhook arrives too; it must not create a second order.
        session = self.stripe.sessions[session_id]
        payload = json.dumps({"type": "checkout.session.completed", "data": {"object": {**session, "object": "checkout.session"}}}).encode()
        hook = self.svc.handle_webhook(payload, sign(payload, "whsec_x"))
        self.assertEqual(hook["order_id"], first["order_id"])
        orders = [o for o in self.svc.state(self.sid, "C3")["orders"] if o["order_id"] == first["order_id"]]
        self.assertEqual(len(orders), 1)

    def test_another_sandbox_cannot_claim_your_checkout(self):
        session_id = self.svc.checkout(self.sid, "C3", "cushion")["url"].rsplit("/", 1)[1]
        self.stripe.pay(session_id)
        with self.assertRaises(ValueError):
            self.svc.confirm_checkout(self.svc.create_session(), session_id)

    def test_refund_goes_to_the_real_payment(self):
        session_id = self.svc.checkout(self.sid, "C1", "towels")["url"].rsplit("/", 1)[1]
        self.stripe.pay(session_id)
        order_id = self.svc.confirm_checkout(self.sid, session_id)["order_id"]
        self.svc.advance_order(self.sid, "C1", order_id)
        self.svc.advance_order(self.sid, "C1", order_id)
        self.svc.chat(self.sid, "C1", f"Refund order {order_id}")  # $18, within the assistant's limit
        refund_call = next(form for url, form in self.stripe.calls if url.endswith("/refunds"))
        self.assertEqual(refund_call["payment_intent"], self.stripe.sessions[session_id]["payment_intent"])


class HttpCheckoutTests(unittest.TestCase):
    def test_endpoints(self):
        client = TestClient(create_app(Service(env=DEMO)))
        h = {"X-Session": client.post("/api/session").json()["session"]}
        products = client.get("/api/products").json()
        self.assertEqual(len(products), len(catalog.PRODUCTS))
        r = client.post("/api/checkout", json={"customer": "C1", "product_id": "throw"}, headers=h)
        self.assertEqual(r.json()["mode"], "simulated")
        order_id = r.json()["order_id"]
        self.assertEqual(client.post(f"/api/orders/{order_id}/advance", json={"customer": "C1"}, headers=h).json()["status"], "shipped")
        self.assertEqual(client.post("/api/orders/O2001/advance", json={"customer": "C1"}, headers=h).status_code, 404)  # not yours
        self.assertEqual(client.post("/api/checkout", json={"customer": "C1", "product_id": "nope"}, headers=h).status_code, 400)


if __name__ == "__main__":
    unittest.main()
