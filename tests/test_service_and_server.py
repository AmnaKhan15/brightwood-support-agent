import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from brightwood_support.auth import AuthError, Forbidden
from brightwood_support.server import make_handler
from brightwood_support.service import AiBudget, NoSuchSession, RateLimited, Service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.svc = Service(env={}, per_minute=3)
        self.sid = self.svc.create_session()

    def test_reply_is_recorded_in_the_database(self):
        r = self.svc.chat(self.sid, "C1", "How long is the return window?")
        self.assertIn("30 days", r["reply"])
        st = self.svc.state(self.sid, "C1")
        self.assertEqual([m["role"] for m in st["messages"]], ["customer", "assistant"])
        self.assertEqual(st["runs"][0]["tools"], "search_help")
        self.assertTrue(r["inspect"]["retrieved"])

    def test_end_to_end_approval_with_roles(self):
        self.svc.chat(self.sid, "C2", "Refund order O2001")
        self.assertEqual(self.svc.state(self.sid)["pending"], 1)
        agent = self.svc.staff_login("agent")
        with self.assertRaises(Forbidden):
            self.svc.decide(self.sid, agent, 1, True)
        with self.assertRaises(AuthError):
            self.svc.decide(self.sid, "not-a-token", 1, True)
        self.svc.decide(self.sid, self.svc.staff_login("support_manager"), 1, True)
        st = self.svc.state(self.sid, "C2")
        self.assertEqual(st["refunds"][0]["amount_cents"], 18900)
        self.assertIn("approved your refund", st["messages"][-1]["text"])
        self.assertEqual([a["action"] for a in st["audit"]][:2], ["approved", "denied_approve"])

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

    def test_session_expiry(self):
        t = [1000.0]
        svc = Service(env={}, ttl=60, clock=lambda: t[0])
        sid = svc.create_session()
        t[0] += 61
        with self.assertRaises(NoSuchSession):
            svc.session(sid)

    def test_daily_cap_on_real_model_calls(self):
        b = AiBudget(2)
        self.assertEqual([b.take(), b.take(), b.take()], [True, True, False])

    def test_real_model_down_falls_back_to_offline(self):
        svc = Service(env={"GEMINI_API_KEY": "k", "GEMINI_MODEL": "m"})  # no network in tests: the call fails
        svc.gateway.tiers["fast"][0].model._model._post = lambda *a: (_ for _ in ()).throw(ConnectionError("down"))
        svc.gateway.tiers["strong"][0].model._model._post = lambda *a: (_ for _ in ()).throw(ConnectionError("down"))
        r = svc.chat(svc.create_session(), "C1", "How long is the return window?")
        self.assertEqual(r["inspect"]["provider"], "offline-assistant")
        self.assertGreaterEqual(svc.gateway.fallbacks, 1)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Service(env={})))
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def req(self, method, path, body=None, headers=None):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, data=json.dumps(body).encode() if body is not None else None, headers=headers or {})
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_flow(self):
        _, b = self.req("POST", "/api/session", {})
        sid = json.loads(b)["session"]
        h = {"X-Session": sid}
        code, b = self.req("POST", "/api/chat", {"customer": "C1", "message": "Where is order O1003?"}, h)
        self.assertEqual(code, 200)
        self.assertIn("shipped", json.loads(b)["reply"])
        self.assertEqual(self.req("POST", "/api/chat", {"customer": "C1", "message": "hi"}, {"X-Session": "bad"})[0], 401)
        self.assertEqual(self.req("POST", "/api/chat", {"customer": "C1"}, h)[0], 400)
        self.assertEqual(self.req("POST", "/api/approvals/1", {"decision": "approve"}, h)[0], 401)  # no token
        self.assertEqual(self.req("GET", "/api/health")[0], 200)

    def test_static_files_cannot_escape_the_site_folder(self):
        code, body = self.req("GET", "/../../src/brightwood_support/server.py")
        self.assertNotIn(b"MAX_BODY", body)

    def test_oversized_body_rejected(self):
        _, b = self.req("POST", "/api/session", {})
        code, _ = self.req("POST", "/api/chat", {"customer": "C1", "message": "x" * 9000}, {"X-Session": json.loads(b)["session"]})
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
