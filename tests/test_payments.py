import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import parse_qs

from brightwood_support.payments import PaymentError, SimulatedPayments, StripePayments, verify_webhook
from brightwood_support.service import Service
from brightwood_support.shop import Shop


class FakeStripe:
    def __init__(self, fail_refund=False):
        self.calls, self.fail_refund = [], fail_refund

    def __call__(self, url, headers, form):
        self.calls.append((url, headers, form))
        if url.endswith("/payment_intents"):
            return {"id": "pi_test_1", "status": "succeeded"}
        if self.fail_refund:
            raise PaymentError("Stripe returned HTTP 402: card_declined")
        return {"id": "re_test_1", "status": "pending"}


def sign(payload: bytes, secret: str, t: int) -> str:
    return f"t={t},v1=" + hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()


class StripeLayer(unittest.TestCase):
    def test_live_keys_are_refused(self):
        with self.assertRaises(ValueError):
            StripePayments("sk_live_abc")

    def test_charge_then_refund_request_shape(self):
        post = FakeStripe()
        shop = Shop(payments=StripePayments("sk_test_abc", post=post))
        shop.issue_refund("C2", "O2001", 189, "asked")
        (u1, h1, f1), (u2, h2, f2) = post.calls
        self.assertTrue(u1.endswith("/payment_intents") and f1["amount"] == 18900 and f1["payment_method"] == "pm_card_visa")
        self.assertTrue(u2.endswith("/refunds") and f2["payment_intent"] == "pi_test_1" and f2["amount"] == 18900)
        self.assertEqual(h2["Idempotency-Key"], "refund-O2001-18900")
        self.assertTrue(h2["Authorization"].startswith("Basic "))
        row = shop.refunds()[0]
        self.assertEqual((row["provider"], row["provider_refund_id"], row["status"]), ("stripe-test", "re_test_1", "pending"))

    def test_provider_failure_records_nothing(self):
        shop = Shop(payments=StripePayments("sk_test_abc", post=FakeStripe(fail_refund=True)))
        with self.assertRaises(PaymentError):
            shop.issue_refund("C2", "O2001", 189, "asked")
        self.assertEqual(shop.refunds(), [])

    def test_partial_refund_excludes_shipping(self):
        post = FakeStripe()
        shop = Shop(payments=StripePayments("sk_test_abc", post=post))
        shop.issue_refund("C1", "O1001", 32, "asked")  # total $38 includes $6 shipping
        self.assertEqual(post.calls[1][2]["amount"], 3200)
        self.assertEqual(post.calls[0][2]["amount"], 3800)

    def test_cancel_goes_through_the_provider_too(self):
        post = FakeStripe()
        Shop(payments=StripePayments("sk_test_abc", post=post)).cancel_order("C1", "O1002")
        self.assertEqual(len(post.calls), 2)


class Webhooks(unittest.TestCase):
    payload = json.dumps({"type": "refund.updated", "data": {"object": {"object": "refund", "id": "re_test_1", "status": "succeeded"}}}).encode()

    def test_valid_signature(self):
        now = int(time.time())
        self.assertEqual(verify_webhook(self.payload, sign(self.payload, "whsec_x", now), "whsec_x")["type"], "refund.updated")

    def test_bad_signature_old_and_missing(self):
        now = int(time.time())
        with self.assertRaises(PaymentError):
            verify_webhook(self.payload, sign(self.payload, "other", now), "whsec_x")
        with self.assertRaises(PaymentError):
            verify_webhook(self.payload, sign(self.payload, "whsec_x", now - 1000), "whsec_x")
        with self.assertRaises(PaymentError):
            verify_webhook(self.payload, None, "whsec_x")
        with self.assertRaises(PaymentError):
            verify_webhook(self.payload + b" ", sign(self.payload, "whsec_x", now), "whsec_x")

    def test_service_updates_the_refund_status(self):
        svc = Service(env={"STRIPE_SECRET_KEY": "sk_test_abc", "STRIPE_WEBHOOK_SECRET": "whsec_x"})
        svc.payments._post = FakeStripe()
        sid = svc.create_session()
        svc.chat(sid, "C1", "Refund order O1001")  # $32, within the assistant's limit
        self.assertEqual(svc.state(sid)["refunds"][0]["status"], "pending")
        self.assertEqual(svc.handle_webhook(self.payload, sign(self.payload, "whsec_x", int(time.time()))), 1)
        self.assertEqual(svc.state(sid)["refunds"][0]["status"], "succeeded")

    def test_approval_keeps_waiting_if_stripe_fails(self):
        svc = Service(env={"STRIPE_SECRET_KEY": "sk_test_abc"})
        svc.payments._post = FakeStripe(fail_refund=True)
        sid = svc.create_session()
        svc.chat(sid, "C2", "Refund order O2001")
        with self.assertRaises(ValueError):
            svc.decide(sid, svc.staff_login("support_manager"), 1, True)
        st = svc.state(sid)
        self.assertEqual((st["pending"], st["refunds"]), (1, []))
        self.assertIn("refund_failed", [a["action"] for a in st["audit"]])


if __name__ == "__main__":
    unittest.main()
