"""Regression tests for the issues found in code review."""
import hashlib
import hmac
import json
import time
import unittest

from fastapi.testclient import TestClient

from brightwood_support.auth import AuthError
from brightwood_support.server import create_app
from brightwood_support.service import RateLimited, Service
from brightwood_support.shop import Shop
from brightwood_support.state import RateLimiter

DEMO = {"DEMO_STAFF_LOGIN": "true"}


class ReviewRegressions(unittest.TestCase):
    def test_a_cancellation_does_not_use_up_the_assistant_refund_cap(self):
        shop = Shop()
        shop.cancel_order("C1", "O1002")  # refunds $129 automatically
        self.assertEqual(shop.assistant_refunded_cents("C1"), 0)
        self.assertEqual(shop.refunds()[0]["via"], "cancellation")

    def test_inline_decisions_run_on_the_service_that_was_asked(self):
        first = Service(env=DEMO)
        sid = first.create_session()
        first.chat(sid, "C2", "Refund order O2001")
        Service(env=DEMO)  # a second service in the same process (tests, evals) must not steal the job
        out = first.decide(sid, first.staff_login("support_manager"), 1, True)
        self.assertEqual(out["status"], "approved")

    def test_a_webhook_does_not_count_as_a_visit(self):
        t = [1000.0]
        svc = Service(env={**DEMO, "STRIPE_WEBHOOK_SECRET": "whsec_x"}, clock=lambda: t[0])
        sid = svc.create_session()
        t[0] += 100
        payload = json.dumps({"type": "refund.updated", "data": {"object": {"object": "refund", "id": "re_1", "status": "succeeded"}}}).encode()
        now = int(time.time())
        sig = hmac.new(b"whsec_x", f"{now}.".encode() + payload, hashlib.sha256).hexdigest()
        svc.handle_webhook(payload, f"t={now},v1={sig}")
        self.assertEqual(svc.registry.last_used(sid), 1000.0)

    def test_chunked_bodies_are_refused(self):
        client = TestClient(create_app(Service(env=DEMO)))
        r = client.post("/api/chat", content=iter([b'{"customer":"C1",', b'"message":"hi"}']), headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 411)

    def test_rate_limiter_never_admits_more_than_the_limit(self):
        import fakeredis
        limiter = RateLimiter(fakeredis.FakeRedis(decode_responses=True), lambda: 5.0)
        self.assertEqual(sum(limiter.allow("k", 3) for _ in range(10)), 3)

    def test_sign_in_has_a_global_cap_across_clients(self):
        svc = Service(env={"STAFF_ACCESS_CODE": "long-secret"})
        for n in range(30):
            with self.assertRaises(AuthError):
                svc.staff_login("support_manager", code="guess", client=f"10.0.0.{n % 6}-{n}")
        with self.assertRaises(RateLimited):
            svc.staff_login("support_manager", code="long-secret", client="fresh-client")


if __name__ == "__main__":
    unittest.main()
