import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brightwood_support.shop import NotFound, PolicyError, Shop  # noqa: E402

TODAY = date(2026, 10, 12)


def shop():
    return Shop(today=lambda: TODAY)


class IdentityTests(unittest.TestCase):
    def test_a_customer_sees_only_their_own_orders(self):
        s = shop()
        self.assertEqual({o["order_id"] for o in s.list_orders("C1")}, {"O1001", "O1002", "O1003"})

    def test_someone_elses_order_looks_like_a_missing_order(self):
        s = shop()
        with self.assertRaises(NotFound) as other:
            s.get_order("C1", "O2001")
        with self.assertRaises(NotFound) as missing:
            s.get_order("C1", "O9999")
        self.assertEqual(str(other.exception).replace("O2001", "X"), str(missing.exception).replace("O9999", "X"))

    def test_every_action_is_scoped_to_the_customer(self):
        s = shop()
        for call in (lambda: s.cancel_order("C1", "O3002"), lambda: s.send_return_label("C1", "O2001"),
                     lambda: s.issue_refund("C1", "O2001", 10, "x"), lambda: s.create_ticket("C1", "hi", "O2001")):
            with self.assertRaises(NotFound):
                call()
        self.assertEqual(s.refunds(), [])


class CancelTests(unittest.TestCase):
    def test_processing_order_can_be_cancelled_and_is_refunded_in_full(self):
        s = shop()
        result = s.cancel_order("C1", "O1002")
        self.assertEqual((result["status"], result["refund"]), ("cancelled", "$129.00"))
        self.assertEqual(s.get_order("C1", "O1002")["status"], "cancelled")

    def test_shipped_or_delivered_order_cannot_be_cancelled(self):
        s = shop()
        for oid in ("O1003", "O1001"):
            with self.assertRaises(PolicyError):
                s.cancel_order("C1", oid)

    def test_cancelling_twice_fails(self):
        s = shop()
        s.cancel_order("C1", "O1002")
        with self.assertRaises(PolicyError):
            s.cancel_order("C1", "O1002")


class ReturnLabelTests(unittest.TestCase):
    def test_label_for_a_recent_delivery(self):
        label = shop().send_return_label("C1", "O1001")
        self.assertEqual(label["valid_until"], "2026-10-26")

    def test_not_after_30_days(self):
        with self.assertRaises(PolicyError) as e:
            shop().send_return_label("C2", "O2002")
        self.assertIn("30 days", str(e.exception))

    def test_not_for_final_sale(self):
        with self.assertRaises(PolicyError) as e:
            shop().send_return_label("C2", "O2003")
        self.assertIn("final-sale", str(e.exception))

    def test_not_before_delivery(self):
        with self.assertRaises(PolicyError):
            shop().send_return_label("C1", "O1003")


class RefundTests(unittest.TestCase):
    def test_refund_up_to_the_item_total(self):
        s = shop()
        result = s.issue_refund("C1", "O1001", 32.00, "changed mind")
        self.assertEqual(result["amount"], "$32.00")
        self.assertEqual(s.get_order("C1", "O1001")["refunded"], "$32.00")

    def test_shipping_is_not_refunded(self):
        s = shop()
        with self.assertRaises(PolicyError) as e:
            s.issue_refund("C1", "O1001", 38.00, "x")  # total 38.00 includes 6.00 shipping
        self.assertIn("$32.00", str(e.exception))

    def test_only_one_refund_per_order(self):
        s = shop()
        s.issue_refund("C2", "O2001", 50, "x")
        with self.assertRaises(PolicyError) as e:
            s.issue_refund("C2", "O2001", 20, "x")
        self.assertIn("one refund", str(e.exception))

    def test_amount_must_be_positive(self):
        for bad in (0, -5):
            with self.assertRaises(PolicyError):
                shop().issue_refund("C1", "O1001", bad, "x")

    def test_rules_for_window_and_final_sale_apply_to_refunds_too(self):
        s = shop()
        for cid, oid in (("C2", "O2002"), ("C2", "O2003"), ("C1", "O1003")):
            with self.assertRaises(PolicyError):
                s.issue_refund(cid, oid, 5, "x")

    def test_money_is_exact_in_cents(self):
        s = shop()
        s.issue_refund("C1", "O1001", 19.99, "x")
        self.assertEqual(s.refunds()[0]["amount_cents"], 1999)


class TicketTests(unittest.TestCase):
    def test_ticket_is_saved_and_listed(self):
        s = shop()
        s.create_ticket("C3", "Parcel not moving", "O3001")
        self.assertEqual(s.tickets()[0]["summary"], "Parcel not moving")

    def test_ticket_text_is_cut_to_500_characters(self):
        s = shop()
        s.create_ticket("C3", "x" * 900)
        self.assertEqual(len(s.tickets()[0]["summary"]), 500)

    def test_nothing_in_the_shop_can_delete_a_row(self):
        public = [n for n in dir(Shop) if not n.startswith("_")]
        self.assertFalse([n for n in public if "delete" in n or "remove" in n or "drop" in n])


if __name__ == "__main__":
    unittest.main()
