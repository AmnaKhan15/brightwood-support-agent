"""Postgres + pgvector integration tests. They run when TEST_DATABASE_URL is set (CI starts a pgvector container).

    TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres python -m unittest tests.test_postgres
"""
import os
import unittest

import fakeredis

from brightwood_support.db import PostgresBackend, schema_for
from brightwood_support.rag import (
    HashingEmbedder,
    InMemoryStore,
    PgVectorStore,
    load_corpus,
)
from brightwood_support.service import HELP_DIR, Service
from brightwood_support.shop import PolicyError, Shop
from brightwood_support.state import AiBudget, PgRedis, RateLimiter, SandboxRegistry

URL = os.environ.get("TEST_DATABASE_URL", "")
ENV = {"DEMO_STAFF_LOGIN": "true", "DATABASE_URL": URL}


@unittest.skipUnless(URL, "set TEST_DATABASE_URL to run the Postgres tests")
class PostgresTests(unittest.TestCase):
    def test_everything_survives_a_restart(self):
        redis = fakeredis.FakeRedis(decode_responses=True)  # Redis outlives the web process too
        first = Service(env=ENV, redis=redis)
        sid = first.create_session()
        first.chat(sid, "C1", "Where is order O1002?")
        first.chat(sid, "C2", "Refund order O2001")
        first.backend.close()

        second = Service(env=ENV, redis=redis)  # a new process: nothing in memory
        st = second.state(sid, "C2")
        self.assertEqual(st["pending"], 1)
        self.assertEqual([m["role"] for m in st["messages"]], ["customer", "assistant"])
        # Conversation memory came back from the LangGraph checkpoint: "it" means O1002.
        second.chat(sid, "C1", "Cancel it please")
        self.assertEqual(second.state(sid, "C1")["orders"][0]["status"], "cancelled")
        # The paused approval workflow resumes from Postgres.
        out = second.decide(sid, second.staff_login("support_manager"), st["approvals"][0]["id"], True)
        self.assertEqual(out["status"], "approved")
        self.assertEqual(second.state(sid)["refunds"][0]["amount_cents"], 18900)
        self.assertGreaterEqual(second.metrics()["conversations"], 3)
        second.backend.close()

    def test_buying_and_shipping_on_postgres(self):
        svc = Service(env=ENV)
        sid = svc.create_session()
        order_id = svc.checkout(sid, "C1", "shelf")["order_id"]
        self.assertEqual(svc.advance_order(sid, "C1", order_id)["status"], "shipped")
        self.assertEqual(svc.advance_order(sid, "C1", order_id)["status"], "delivered")
        self.assertIn(order_id, [o["order_id"] for o in svc.state(sid, "C1")["orders"]])
        self.assertEqual(svc.checkouts.get(svc.checkouts.db.execute("SELECT reference FROM checkouts WHERE order_id=?", (order_id,)).fetchone()["reference"])["status"], "done")
        svc.backend.close()

    def test_sandbox_is_a_schema_and_is_dropped(self):
        svc = Service(env=ENV)
        sid = svc.create_session()
        exists = "SELECT 1 AS x FROM information_schema.schemata WHERE schema_name=?"
        self.assertTrue(svc.backend.main.execute(exists, (schema_for(sid),)).rows)
        svc.reset(sid)
        self.assertTrue(svc.backend.main.execute(exists, (schema_for(sid),)).rows)
        svc._drop(sid)
        self.assertFalse(svc.backend.main.execute(exists, (schema_for(sid),)).rows)
        svc.backend.close()

    def test_store_rules_hold_on_postgres(self):
        backend = PostgresBackend(URL)
        shop = Shop(backend.open_sandbox("rules-test", create=True))
        shop.issue_refund("C1", "O1001", 19.99, "x")
        self.assertEqual(shop.refunds()[0]["amount_cents"], 1999)
        with self.assertRaises(PolicyError):
            shop.issue_refund("C1", "O1001", 5, "x")
        self.assertEqual(shop.get_order("C1", "O1001")["refunded"], "$19.99")
        shop.send_return_label("C1", "O1001")
        shop.send_return_label("C1", "O1001")  # upsert, not a duplicate
        backend.drop_sandbox("rules-test")
        backend.close()

    def test_pgvector_ranks_like_the_in_memory_store(self):
        backend = PostgresBackend(URL)
        chunks = load_corpus(HELP_DIR)
        pg, mem = PgVectorStore(backend.main, HashingEmbedder()), InMemoryStore(HashingEmbedder())
        pg.add(chunks)
        mem.add(chunks)
        for q in ("How many days do I have to return?", "Is shipping free?", "My parcel is lost", "zzz"):
            self.assertEqual([c.id for c, _ in pg.search(q)], [c.id for c, _ in mem.search(q)], q)
        backend.close()


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(URL, "set TEST_DATABASE_URL to run the Postgres tests")
class PostgresSharedStateTests(unittest.TestCase):
    """With no Redis, shared state lives in Postgres, so separate serverless copies of the API agree."""

    def setUp(self):
        self.backend = PostgresBackend(URL)
        self.now = [1000.0]
        self.store = PgRedis(self.backend.main, clock=lambda: self.now[0])
        self.backend.main.script("DELETE FROM kv; DELETE FROM kv_zset; DELETE FROM kv_ttl")

    def tearDown(self):
        self.backend.close()

    def test_two_api_copies_share_a_visitor_sandbox(self):
        a = Service(env=ENV)  # no redis passed and no REDIS_URL: Postgres holds the shared state
        b = Service(env=ENV)
        self.assertIsInstance(a.redis, PgRedis)
        sid = a.create_session()
        r = b.chat(sid, "C2", "Refund order O2001")  # the next request lands on the other copy
        self.assertEqual(r["state"], "waiting")
        self.assertEqual(a.state(sid, "C2")["pending"], 1)
        a.backend.close()
        b.backend.close()

    def test_rate_limit_is_shared_and_slides(self):
        first, second = RateLimiter(self.store, lambda: self.now[0]), RateLimiter(self.store, lambda: self.now[0])
        self.assertEqual([first.allow("chat:x", 2), second.allow("chat:x", 2), first.allow("chat:x", 2)], [True, True, False])
        self.now[0] += 61
        self.assertTrue(second.allow("chat:x", 2))

    def test_registry_orders_and_expires_sandboxes(self):
        reg = SandboxRegistry(self.store)
        reg.touch("old", 10)
        reg.touch("new", 20)
        self.assertEqual((reg.count(), reg.oldest(1), reg.idle_since(15), reg.last_used("new")), (2, ["old"], ["old"], 20.0))
        reg.remove("old")
        self.assertEqual(reg.all(), ["new"])

    def test_budget_counter_and_markers(self):
        budget = AiBudget(2, r=self.store)
        self.assertEqual([budget.take(), budget.take(), budget.take(), budget.used], [True, True, False, 2])
        self.assertTrue(self.store.set("deciding", "sam", nx=True, ex=300))
        self.assertIsNone(self.store.set("deciding", "alex", nx=True, ex=300))  # someone is already deciding
        self.assertEqual(self.store.exists("deciding"), 1)
        self.now[0] += 301  # the marker expires on its own
        self.assertTrue(self.store.set("deciding", "alex", nx=True, ex=300))
        self.store.delete("deciding")
        self.assertEqual(self.store.exists("deciding"), 0)
