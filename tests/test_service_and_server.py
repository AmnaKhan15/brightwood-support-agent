import types
import unittest

from fastapi.testclient import TestClient

from brightwood_support.auth import AuthError, Forbidden
from brightwood_support.server import create_app
from brightwood_support.service import NoSuchSession, RateLimited, Service
from brightwood_support.state import AiBudget

DEMO = {"DEMO_STAFF_LOGIN": "true"}


def down():
    return types.SimpleNamespace(next=lambda *a: (_ for _ in ()).throw(ConnectionError("down")))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.svc = Service(env=DEMO, per_minute=3)
        self.sid = self.svc.create_session()

    def test_reply_is_recorded_in_the_database(self):
        r = self.svc.chat(self.sid, "C1", "How long is the return window?")
        self.assertIn("30 days", r["reply"])
        st = self.svc.state(self.sid, "C1")
        self.assertEqual([m["role"] for m in st["messages"]], ["customer", "assistant"])
        self.assertEqual(st["runs"][0]["tools"], "search_help")
        self.assertEqual(st["runs"][0]["agent"], "policy")
        self.assertTrue(r["inspect"]["retrieved"])

    def test_the_supervisor_picks_a_specialist_and_it_shows_in_the_inspector(self):
        r = self.svc.chat(self.sid, "C2", "Refund order O2001")
        self.assertEqual(r["inspect"]["agent"], "billing")
        self.assertIn("billing agent", r["inspect"]["steps"][0]["title"])

    def test_history_carries_across_turns(self):
        self.svc.chat(self.sid, "C1", "Where is order O1002?")
        self.svc.chat(self.sid, "C1", "Cancel it please")
        self.assertEqual(self.svc.state(self.sid, "C1")["orders"][0]["status"], "cancelled")

    def test_end_to_end_approval_with_roles(self):
        self.svc.chat(self.sid, "C2", "Refund order O2001")
        self.assertEqual(self.svc.state(self.sid)["pending"], 1)
        agent = self.svc.staff_login("agent")
        with self.assertRaises(Forbidden):
            self.svc.decide(self.sid, agent, 1, True)
        with self.assertRaises(AuthError):
            self.svc.decide(self.sid, "not-a-token", 1, True)
        out = self.svc.decide(self.sid, self.svc.staff_login("support_manager"), 1, True)
        self.assertEqual(out["status"], "approved")
        st = self.svc.state(self.sid, "C2")
        self.assertEqual((st["refunds"][0]["amount_cents"], st["refunds"][0]["via"]), (18900, "manager"))
        self.assertIn("approved your refund", st["messages"][-1]["text"])
        self.assertEqual([a["action"] for a in st["audit"]][:2], ["approved", "denied_approve"])
        with self.assertRaises(ValueError):  # already decided
            self.svc.decide(self.sid, self.svc.staff_login("support_manager"), 1, False)

    def test_approval_workflow_waits_in_the_checkpointer(self):
        self.svc.chat(self.sid, "C2", "Refund order O2001")
        snap = self.svc.approvals.get_state({"configurable": {"thread_id": f"approval:{self.sid}:1"}})
        self.assertEqual(snap.next, ("wait_for_manager",))

    def test_voice_flag_adds_the_spoken_style_instruction(self):
        r = self.svc.chat(self.sid, "C1", "hi", voice=True)
        self.assertIn("will hear your answer read aloud", r["inspect"]["prompt"][0]["text"])
        r = self.svc.chat(self.sid, "C1", "hi again")
        self.assertNotIn("read aloud", r["inspect"]["prompt"][0]["text"])

    def test_sessions_are_isolated(self):
        other = self.svc.create_session()
        self.svc.chat(self.sid, "C1", "Cancel order O1002")
        self.assertEqual(self.svc.state(other, "C1")["orders"][0]["status"], "processing")

    def test_rate_limit_and_empty_message(self):
        for _ in range(3):
            self.svc.chat(self.sid, "C1", "hi")
        with self.assertRaises(RateLimited):
            self.svc.chat(self.sid, "C1", "hi")
        with self.assertRaises(ValueError):
            self.svc.chat(self.svc.create_session(), "C1", "  ")

    def test_unknown_session_and_customer(self):
        with self.assertRaises(NoSuchSession):
            self.svc.chat("nope", "C1", "hi")
        with self.assertRaises(KeyError):
            self.svc.chat(self.sid, "C9", "hi")

    def test_session_expiry_and_cleanup(self):
        t = [1000.0]
        svc = Service(env=DEMO, ttl=60, clock=lambda: t[0])
        sid = svc.create_session()
        t[0] += 61
        with self.assertRaises(NoSuchSession):
            svc.session(sid)
        self.assertEqual(svc.registry.count(), 0)

    def test_reset_gives_fresh_orders(self):
        self.svc.chat(self.sid, "C1", "Cancel order O1002")
        self.svc.reset(self.sid)
        self.assertEqual(self.svc.state(self.sid, "C1")["orders"][0]["status"], "processing")

    def test_daily_cap_on_real_model_calls(self):
        b = AiBudget(2)
        self.assertEqual([b.take(), b.take(), b.take()], [True, True, False])
        self.assertEqual(b.used, 2)

    def test_real_model_down_falls_back_to_offline(self):
        svc = Service(env={"GEMINI_API_KEY": "k", "GEMINI_MODEL": "m", "SEMANTIC_SEARCH": "off"})
        svc.gateway.tiers["fast"][0].model._model = down()
        svc.gateway.tiers["strong"][0].model._model = down()
        svc.router._model = down()
        r = svc.chat(svc.create_session(), "C1", "How long is the return window?")
        self.assertEqual(r["inspect"]["provider"], "offline-assistant")
        self.assertEqual(r["inspect"]["agent"], "policy")  # the keyword rules took over routing
        self.assertGreaterEqual(svc.gateway.fallbacks, 1)
        self.assertEqual(svc.metrics()["fallback_rate"], 1.0)

    def test_metrics_and_targets(self):
        self.svc.chat(self.sid, "C1", "How long is the return window?")
        self.svc.chat(self.sid, "C2", "Refund order O2001")
        self.svc.chat(self.sid, "C2", "The lamp in O2001 arrived broken")
        m = self.svc.metrics()
        self.assertEqual(m["conversations"], 3)
        self.assertAlmostEqual(m["containment_rate"], 1 / 3, places=3)
        self.assertAlmostEqual(m["approval_rate"], 1 / 3, places=3)
        self.assertAlmostEqual(m["escalation_rate"], 1 / 3, places=3)
        self.assertEqual(m["by_agent"], {"billing": 1, "orders": 1, "policy": 1})
        self.assertIn("containment_rate", [t["metric"] for t in m["targets"]])


class StaffLoginTests(unittest.TestCase):
    def test_off_by_default(self):
        with self.assertRaises(Forbidden):
            Service(env={}).staff_login("support_manager")

    def test_access_code_and_lockout(self):
        svc = Service(env={"STAFF_ACCESS_CODE": "s3cret-code"})
        self.assertTrue(svc.staff_login("support_manager", code="s3cret-code", client="a"))
        for _ in range(5):  # five attempts per client per five minutes
            with self.assertRaises(AuthError):
                svc.staff_login("support_manager", code="guess", client="b")
        with self.assertRaises(RateLimited):
            svc.staff_login("support_manager", code="s3cret-code", client="b")

    def test_demo_mode(self):
        self.assertTrue(Service(env=DEMO).staff_login("support_manager"))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(create_app(Service(env=DEMO)))

    def session(self):
        return {"X-Session": self.client.post("/api/session").json()["session"]}

    def test_flow(self):
        h = self.session()
        r = self.client.post("/api/chat", json={"customer": "C1", "message": "Where is order O1003?"}, headers=h)
        self.assertEqual(r.status_code, 200)
        self.assertIn("shipped", r.json()["reply"])
        self.assertTrue(r.headers["X-Request-ID"])
        self.assertEqual(self.client.post("/api/chat", json={"customer": "C1", "message": "hi"}, headers={"X-Session": "bad"}).json()["error"], "session_expired")
        self.assertEqual(self.client.post("/api/chat", json={"customer": "C1"}, headers=h).status_code, 400)
        self.assertEqual(self.client.post("/api/approvals/1", json={"decision": "approve"}, headers=h).status_code, 401)
        self.assertEqual(self.client.post("/api/approvals/1", json={"decision": "maybe"}, headers=h).status_code, 400)
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_approval_over_http(self):
        h = self.session()
        self.client.post("/api/chat", json={"customer": "C2", "message": "Refund order O2001"}, headers=h)
        token = self.client.post("/api/staff/login", json={"role": "support_manager"}).json()["token"]
        r = self.client.post("/api/approvals/1", json={"decision": "approve"}, headers={**h, "Authorization": f"Bearer {token}"})
        self.assertEqual((r.status_code, r.json()["status"]), (200, "approved"))

    def test_unknown_table_and_paths(self):
        h = self.session()
        self.assertEqual(self.client.get("/api/table/payments", headers=h).status_code, 400)
        self.assertEqual(self.client.get("/api/table/messages", headers=h).status_code, 200)
        self.assertEqual(self.client.get("/../../src/brightwood_support/server.py").status_code, 404)

    def test_oversized_body_rejected(self):
        h = self.session()
        r = self.client.post("/api/chat", json={"customer": "C1", "message": "x" * 9000}, headers=h)
        self.assertEqual(r.status_code, 400)

    def test_metrics_and_openapi(self):
        self.assertIn("targets", self.client.get("/api/metrics").json())
        self.assertIn("/api/chat", self.client.get("/api/openapi.json").json()["paths"])


if __name__ == "__main__":
    unittest.main()
