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
