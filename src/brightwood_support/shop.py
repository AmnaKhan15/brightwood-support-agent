"""The store: customers, orders, refunds, tickets and approvals in a real SQL database.

Every method takes the customer id first and only ever sees that customer's rows.
The customer id comes from the signed-in session, never from the AI, so the AI has no
way to ask about someone else's order. A question about another customer's order gets
the same answer as a question about an order that does not exist.

The policy rules live here, next to the data, so they hold no matter who calls
(an agent, a test, the approval worker or the MCP server):
  - Cancel only while the order is still processing.
  - A return label only for delivered orders within 30 days, never for final-sale items.
  - A refund only for a delivered order within 30 days, never final sale, one per order,
    never more than the item total (shipping is not refunded).
  - Nothing here deletes a row.

The same SQL runs on SQLite (tests, local) and Postgres (production): see db.py.
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Callable, Iterator

from .db import ID_COLUMN, Database, SqliteDatabase, now_text

RETURN_WINDOW_DAYS = 30

SCHEMA = """
CREATE TABLE customers(id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL);
CREATE TABLE orders(
  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id), status TEXT NOT NULL,
  placed_on TEXT NOT NULL, shipped_on TEXT, delivered_on TEXT, last_scan_on TEXT,
  total_cents INTEGER NOT NULL, shipping_cents INTEGER NOT NULL, final_sale INTEGER NOT NULL DEFAULT 0,
  address TEXT NOT NULL, tracking TEXT);
CREATE TABLE order_items(order_id TEXT NOT NULL REFERENCES orders(id), name TEXT NOT NULL, price_cents INTEGER NOT NULL);
CREATE TABLE refunds(id {id}, order_id TEXT NOT NULL, amount_cents INTEGER NOT NULL,
  reason TEXT NOT NULL, created_on TEXT NOT NULL, provider TEXT, provider_refund_id TEXT,
  status TEXT NOT NULL DEFAULT 'succeeded', via TEXT NOT NULL DEFAULT 'assistant');
CREATE TABLE payments(order_id TEXT PRIMARY KEY, provider TEXT NOT NULL, ref TEXT NOT NULL, amount_cents INTEGER NOT NULL);
CREATE TABLE tickets(id {id}, customer_id TEXT NOT NULL, order_id TEXT, summary TEXT NOT NULL, created_on TEXT NOT NULL);
CREATE TABLE return_labels(order_id TEXT PRIMARY KEY, code TEXT NOT NULL, expires_on TEXT NOT NULL);
CREATE TABLE approvals(id {id}, customer_id TEXT NOT NULL, tool TEXT NOT NULL, args TEXT NOT NULL, approver TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', decided_by TEXT, decided_role TEXT, created_at TEXT NOT NULL, decided_at TEXT);
CREATE TABLE messages(id {id}, run_id INTEGER, customer_id TEXT NOT NULL, role TEXT NOT NULL,
  text TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE runs(id {id}, customer_id TEXT NOT NULL, stopped TEXT NOT NULL, steps INTEGER NOT NULL,
  tokens INTEGER NOT NULL, tools TEXT NOT NULL, provider TEXT, route TEXT, agent TEXT, millis INTEGER NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE audit(id {id}, actor TEXT NOT NULL, role TEXT NOT NULL, action TEXT NOT NULL,
  detail TEXT NOT NULL, created_at TEXT NOT NULL);
"""

READABLE_TABLES = ("messages", "runs", "audit", "tickets", "refunds", "orders", "return_labels", "approvals")


class NotFound(Exception):
    """No such order for this customer (or no such order at all: the answer is the same)."""


class PolicyError(Exception):
    """The store's rules do not allow this. The message says why, in words the AI can pass on."""


def dollars(cents: int) -> str:
    return f"${cents / 100:.2f}"


def to_cents(amount: float) -> int:
    return round(float(amount) * 100)


class Shop:
    def __init__(self, db: Database | None = None, today: Callable[[], date] = date.today, payments=None, seed: bool = True) -> None:
        from .payments import SimulatedPayments
        self.payments = payments or SimulatedPayments()
        self._today = today
        self._lock = threading.RLock()
        self.db = db or SqliteDatabase()
        if seed:
            with self.db.transaction() as tx:  # one round trip set on Postgres, not dozens
                tx.script(SCHEMA.replace("{id}", ID_COLUMN[self.db.dialect]))
                self._seed(tx)

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Run several writes in one transaction (one connection, one round trip set on Postgres)."""
        with self._lock, self.db.transaction() as tx:
            outer, self.db = self.db, tx
            try:
                yield
            finally:
                self.db = outer

    # --- demo data (invented people and products) ---------------------------
    def _seed(self, db: Database) -> None:
        t = self._today()

        def d(days_ago: int) -> str:
            return (t - timedelta(days=days_ago)).isoformat()

        customers = [("C1", "Sam Rivera", "sam.rivera@example.com"), ("C2", "Priya Nair", "priya.nair@example.com"),
                     ("C3", "Alex Chen", "alex.chen@example.com")]
        for row in customers:
            db.execute("INSERT INTO customers VALUES(?,?,?)", row)
        #            id      cust  status       placed  shipped  delivered scan  total  ship final address                  tracking
        orders = [
            ("O1001", "C1", "delivered", d(12), d(10), d(6), d(6), 3800, 600, 0, "12 Elm Street, Springfield", "TRK1001"),
            ("O1002", "C1", "processing", d(0), None, None, None, 12900, 0, 0, "12 Elm Street, Springfield", None),
            ("O1003", "C1", "shipped", d(4), d(2), None, d(1), 6450, 0, 0, "12 Elm Street, Springfield", "TRK1003"),
            ("O2001", "C2", "delivered", d(18), d(16), d(12), d(12), 18900, 0, 0, "48 Harbor Road, Rivertown", "TRK2001"),
            ("O2002", "C2", "delivered", d(52), d(50), d(45), d(45), 2400, 600, 0, "48 Harbor Road, Rivertown", "TRK2002"),
            ("O2003", "C2", "delivered", d(7), d(5), d(3), d(3), 1900, 600, 1, "48 Harbor Road, Rivertown", "TRK2003"),
            ("O3001", "C3", "shipped", d(14), d(9), None, d(9), 8800, 0, 0, "7 Orchard Lane, Maplewood", "TRK3001"),
            ("O3002", "C3", "processing", d(0), None, None, None, 4200, 600, 0, "7 Orchard Lane, Maplewood", None),
        ]
        for row in orders:
            db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", row)
        items = [
            ("O1001", "Linen cushion cover set", 3200), ("O1002", "Oak side table", 12900), ("O1003", "Ceramic planter (large)", 6450),
            ("O2001", "Wool throw blanket", 8900), ("O2001", "Ceramic table lamp", 10000), ("O2002", "Glass storage jar", 1800),
            ("O2003", "Clearance stoneware mug", 1300), ("O3001", "Walnut bookshelf", 8800), ("O3002", "Cotton tea towels", 3600),
        ]
        for row in items:
            db.execute("INSERT INTO order_items VALUES(?,?,?)", row)

    # --- reading -------------------------------------------------------------
    def _order(self, customer_id: str, order_id: str) -> dict:
        with self._lock:
            row = self.db.execute("SELECT * FROM orders WHERE id=? AND customer_id=?", (order_id, customer_id)).fetchone()
        if row is None:
            raise NotFound(f"no order {order_id} found for this customer")
        return row

    def list_orders(self, customer_id: str) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT id FROM orders WHERE customer_id=? ORDER BY placed_on DESC, id", (customer_id,)).fetchall()
        return [self.get_order(customer_id, r["id"]) for r in rows]

    def get_order(self, customer_id: str, order_id: str) -> dict:
        row = self._order(customer_id, order_id)
        with self._lock:
            items = self.db.execute("SELECT name, price_cents FROM order_items WHERE order_id=?", (order_id,)).fetchall()
            refunded = int(self.db.execute("SELECT COALESCE(SUM(amount_cents),0) AS n FROM refunds WHERE order_id=?", (order_id,)).fetchone()["n"])
            label = self.db.execute("SELECT code, expires_on FROM return_labels WHERE order_id=?", (order_id,)).fetchone()
        return {
            "order_id": row["id"], "status": row["status"], "placed_on": row["placed_on"], "shipped_on": row["shipped_on"],
            "delivered_on": row["delivered_on"], "last_tracking_scan_on": row["last_scan_on"], "tracking": row["tracking"],
            "items": [{"name": i["name"], "price": dollars(i["price_cents"])} for i in items],
            "total": dollars(row["total_cents"]), "shipping_paid": dollars(row["shipping_cents"]),
            "final_sale": bool(row["final_sale"]), "address": row["address"],
            "refunded": dollars(refunded), "return_label": dict(label) if label else None,
        }

    def customer_email(self, customer_id: str) -> str:
        with self._lock:
            row = self.db.execute("SELECT email FROM customers WHERE id=?", (customer_id,)).fetchone()
        if row is None:
            raise KeyError(customer_id)
        return row["email"]

    # --- rules ---------------------------------------------------------------
    def _days_since_delivery(self, row: dict) -> int:
        if not row["delivered_on"]:
            raise PolicyError(f"order {row['id']} has not been delivered yet (status: {row['status']})")
        return (self._today() - date.fromisoformat(row["delivered_on"])).days

    def _check_returnable(self, row: dict) -> None:
        if row["final_sale"]:
            raise PolicyError(f"order {row['id']} is a final-sale item and cannot be returned or refunded")
        days = self._days_since_delivery(row)
        if days > RETURN_WINDOW_DAYS:
            raise PolicyError(f"order {row['id']} was delivered {days} days ago; the return window is {RETURN_WINDOW_DAYS} days")

    def max_refund_cents(self, customer_id: str, order_id: str) -> int:
        row = self._order(customer_id, order_id)
        return row["total_cents"] - row["shipping_cents"]

    def check_refund(self, customer_id: str, order_id: str, amount: float, reason: str = "") -> int:
        """Raise PolicyError or NotFound if this refund is not allowed. Returns the amount in cents."""
        row = self._order(customer_id, order_id)
        cents = to_cents(amount)
        if cents <= 0:
            raise PolicyError("the refund amount must be more than zero")
        self._check_returnable(row)
        with self._lock:
            already = self.db.execute("SELECT 1 AS x FROM refunds WHERE order_id=?", (order_id,)).fetchone()
        if already:
            raise PolicyError(f"order {order_id} has already been refunded; only one refund is allowed per order")
        limit = row["total_cents"] - row["shipping_cents"]
        if cents > limit:
            raise PolicyError(f"the most that can be refunded on {order_id} is {dollars(limit)} (shipping is not refunded)")
        return cents

    # --- doing things ----------------------------------------------------------
    def cancel_order(self, customer_id: str, order_id: str) -> dict:
        row = self._order(customer_id, order_id)
        if row["status"] != "processing":
            raise PolicyError(f"order {order_id} is {row['status']}, so it cannot be cancelled. It can be returned instead")
        with self._lock:
            money = self._money_back(order_id, row["total_cents"], "order cancelled before shipping", "cancellation")
            self.db.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
        return {"order_id": order_id, "status": "cancelled", "refund": dollars(row["total_cents"]), "provider_refund_id": money["provider_refund_id"],
                "note": "refunded in full to the original payment method within 3 business days"}

    def send_return_label(self, customer_id: str, order_id: str) -> dict:
        row = self._order(customer_id, order_id)
        self._check_returnable(row)
        expires = (self._today() + timedelta(days=14)).isoformat()
        code = f"RL-{order_id}"
        with self._lock:
            self.db.execute("INSERT INTO return_labels VALUES(?,?,?) ON CONFLICT(order_id) DO UPDATE SET code=excluded.code, "
                            "expires_on=excluded.expires_on", (order_id, code, expires))
        return {"order_id": order_id, "label": code, "valid_until": expires, "note": "free prepaid label, drop the parcel at any carrier location"}

    def issue_refund(self, customer_id: str, order_id: str, amount: float, reason: str, via: str = "assistant") -> dict:
        """Record the refund. `via` is "assistant" for a refund the assistant made alone, "manager" after an approval
        ("cancellation" is used for the automatic refund of a cancelled order)."""
        cents = self.check_refund(customer_id, order_id, amount, reason)
        with self._lock:
            money = self._money_back(order_id, cents, reason[:200], via)
        return {"refund_id": money["refund_id"], "order_id": order_id, "amount": dollars(cents), "provider": self.payments.name,
                "provider_refund_id": money["provider_refund_id"], "status": money["status"],
                "note": "arrives 5 to 7 business days after the returned item is received"}

    def assistant_refunded_cents(self, customer_id: str) -> int:
        """What the assistant has refunded alone for this customer. Feeds the per-conversation cap."""
        with self._lock:
            row = self.db.execute("SELECT COALESCE(SUM(r.amount_cents),0) AS n FROM refunds r JOIN orders o ON o.id=r.order_id "
                                  "WHERE o.customer_id=? AND r.via='assistant'", (customer_id,)).fetchone()
        return int(row["n"])

    def _money_back(self, order_id: str, cents: int, reason: str, via: str) -> dict:
        """Move the money through the payment provider, then record it. Raises PaymentError if the provider fails,
        and in that case nothing is recorded as refunded."""
        row = self.db.execute("SELECT total_cents FROM orders WHERE id=?", (order_id,)).fetchone()
        pay = self.db.execute("SELECT ref FROM payments WHERE order_id=?", (order_id,)).fetchone()
        if pay is None:  # the seeded order was never really paid: create a test payment for its total first
            ref = self.payments.charge(order_id, row["total_cents"])
            self.db.execute("INSERT INTO payments VALUES(?,?,?,?)", (order_id, self.payments.name, ref, row["total_cents"]))
        else:
            ref = pay["ref"]
        result = self.payments.refund(ref, cents, f"refund-{order_id}-{cents}", order_id, reason)
        new = self.db.execute(
            "INSERT INTO refunds(order_id, amount_cents, reason, created_on, provider, provider_refund_id, status, via) "
            "VALUES(?,?,?,?,?,?,?,?) RETURNING id",
            (order_id, cents, reason, self._today().isoformat(), self.payments.name, result["id"], result["status"], via)).fetchone()
        return {"refund_id": new["id"], "provider_refund_id": result["id"], "status": result["status"]}

    def update_refund_status(self, provider_refund_id: str, status: str) -> bool:
        with self._lock:
            cur = self.db.execute("UPDATE refunds SET status=? WHERE provider_refund_id=?", (status, provider_refund_id))
        return cur.rowcount > 0

    def create_ticket(self, customer_id: str, summary: str, order_id: str | None = None) -> dict:
        if order_id is not None:
            self._order(customer_id, order_id)
        with self._lock:
            new = self.db.execute("INSERT INTO tickets(customer_id, order_id, summary, created_on) VALUES(?,?,?,?) RETURNING id",
                                  (customer_id, order_id, summary[:500], self._today().isoformat())).fetchone()
        return {"ticket_id": new["id"], "note": "a person on the support team will pick this up"}

    # --- approvals (the queue's storage; the rules live in approvals.py) ------------
    def add_approval(self, customer_id: str, tool: str, args: dict, approver: str) -> int:
        with self._lock:
            return self.db.execute("INSERT INTO approvals(customer_id, tool, args, approver, created_at) VALUES(?,?,?,?,?) RETURNING id",
                                   (customer_id, tool, json.dumps(args), approver, now_text())).fetchone()["id"]

    def set_approval(self, approval_id: int, status: str, decided_by: str | None, role: str | None) -> None:
        with self._lock:
            self.db.execute("UPDATE approvals SET status=?, decided_by=?, decided_role=?, decided_at=? WHERE id=?",
                            (status, decided_by, role, now_text(), approval_id))

    def approval(self, approval_id: int) -> dict | None:
        with self._lock:
            row = self.db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        return {**row, "args": json.loads(row["args"])} if row else None

    def approvals(self, customer_id: str | None = None) -> list[dict]:
        sql, params = "SELECT * FROM approvals", ()
        if customer_id is not None:
            sql, params = sql + " WHERE customer_id=?", (customer_id,)
        with self._lock:
            rows = self.db.execute(sql + " ORDER BY id", params).fetchall()
        return [{**r, "args": json.loads(r["args"])} for r in rows]

    # --- for the manager screen ---------------------------------------------------
    def tickets(self) -> list[dict]:
        with self._lock:
            return self.db.execute("SELECT * FROM tickets ORDER BY id").fetchall()

    def refunds(self) -> list[dict]:
        """Every refund, with the customer it belongs to."""
        with self._lock:
            return self.db.execute("SELECT r.*, o.customer_id FROM refunds r JOIN orders o ON o.id = r.order_id ORDER BY r.id").fetchall()

    def customers(self) -> list[dict]:
        with self._lock:
            return [{"id": r["id"], "name": r["name"]} for r in self.db.execute("SELECT id, name FROM customers ORDER BY id").fetchall()]

    # --- the conversation record: what was said, each AI run, and who decided what ----------
    def log_message(self, customer_id: str, role: str, text: str, run_id: int | None = None) -> int:
        with self._lock:
            return self.db.execute("INSERT INTO messages(run_id, customer_id, role, text, created_at) VALUES(?,?,?,?,?) RETURNING id",
                                   (run_id, customer_id, role, text[:2000], now_text())).fetchone()["id"]

    def messages(self, customer_id: str, limit: int = 60) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT id, role, text, created_at FROM messages WHERE customer_id=? ORDER BY id DESC LIMIT ?",
                                   (customer_id, limit)).fetchall()
        return list(reversed(rows))

    def log_run(self, customer_id: str, stopped: str, steps: int, tokens: int, tools: str, provider: str | None,
                route: str | None, millis: int, agent: str | None = None) -> int:
        with self._lock:
            return self.db.execute("INSERT INTO runs(customer_id, stopped, steps, tokens, tools, provider, route, agent, millis, created_at) "
                                   "VALUES(?,?,?,?,?,?,?,?,?,?) RETURNING id",
                                   (customer_id, stopped, steps, tokens, tools, provider, route, agent, millis, now_text())).fetchone()["id"]

    def log_audit(self, actor: str, role: str, action: str, detail: str) -> None:
        with self._lock:
            self.db.execute("INSERT INTO audit(actor, role, action, detail, created_at) VALUES(?,?,?,?,?)",
                            (actor, role, action, detail[:300], now_text()))

    def table(self, name: str, limit: int = 50) -> list[dict]:
        if name not in READABLE_TABLES:
            raise ValueError("unknown table")
        order = "" if name in ("orders", "return_labels") else " ORDER BY id DESC"
        with self._lock:  # name is from the fixed list above, never from the caller
            return self.db.execute(f"SELECT * FROM {name}{order} LIMIT ?", (limit,)).fetchall()
