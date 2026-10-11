"""Pending purchases: the bridge between "the customer clicked Buy" and "Stripe says it's paid".

A row is written before the customer goes to Stripe's checkout page. Stripe then confirms the payment
in one of two ways, and whichever arrives first creates the order:
  - the signed `checkout.session.completed` webhook (production), or
  - the success page asking the server to check the session with Stripe (works without webhooks, e.g. locally).
`claim()` flips the row from pending to done in one statement, so the order is created exactly once.
The sandbox id is stored only here, on the server; Stripe sees an opaque reference.
"""
from __future__ import annotations

import secrets

from .db import Database, now_text


class Checkouts:
    def __init__(self, db: Database) -> None:
        self.db = db
        db.script("""
            CREATE TABLE IF NOT EXISTS checkouts(reference TEXT PRIMARY KEY, sid TEXT NOT NULL, customer_id TEXT NOT NULL,
              product_id TEXT NOT NULL, session_id TEXT, status TEXT NOT NULL, order_id TEXT, created_at TEXT NOT NULL);
        """)

    def start(self, sid: str, customer_id: str, product_id: str) -> str:
        reference = "chk_" + secrets.token_hex(12)
        self.db.execute("INSERT INTO checkouts(reference, sid, customer_id, product_id, status, created_at) VALUES(?,?,?,?,?,?)",
                        (reference, sid, customer_id, product_id, "pending", now_text()))
        return reference

    def attach_session(self, reference: str, session_id: str) -> None:
        self.db.execute("UPDATE checkouts SET session_id=? WHERE reference=?", (session_id, reference))

    def get(self, reference: str) -> dict | None:
        return self.db.execute("SELECT * FROM checkouts WHERE reference=?", (reference,)).fetchone()

    def claim(self, reference: str) -> dict | None:
        """Mark a pending purchase as being fulfilled. Returns it, or None if it was already claimed or unknown."""
        rows = self.db.execute("UPDATE checkouts SET status='fulfilling' WHERE reference=? AND status='pending' RETURNING *",
                               (reference,)).fetchall()
        return rows[0] if rows else None

    def finish(self, reference: str, order_id: str) -> None:
        self.db.execute("UPDATE checkouts SET status='done', order_id=? WHERE reference=?", (order_id, reference))

    def release(self, reference: str) -> None:
        self.db.execute("UPDATE checkouts SET status='pending' WHERE reference=? AND status='fulfilling'", (reference,))
