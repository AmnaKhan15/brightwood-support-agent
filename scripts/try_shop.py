"""Watch the store's rules say yes and no. Nothing here uses AI.

    python scripts/try_shop.py
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brightwood_support.shop import NotFound, PolicyError, Shop  # noqa: E402

shop = Shop(today=lambda: date(2026, 10, 12))


def attempt(label, fn):
    try:
        print(f"{label}\n   YES: {fn()}\n")
    except (NotFound, PolicyError) as error:
        print(f"{label}\n   NO:  {error}\n")


print("Sam (C1) has orders:", [(o["order_id"], o["status"]) for o in shop.list_orders("C1")], "\n")
attempt("Sam asks about Priya's order O2001", lambda: shop.get_order("C1", "O2001"))
attempt("Sam cancels O1003 (already shipped)", lambda: shop.cancel_order("C1", "O1003"))
attempt("Priya asks for a return label on O2002 (delivered 45 days ago)", lambda: shop.send_return_label("C2", "O2002"))
attempt("Priya asks for a return label on O2003 (final sale)", lambda: shop.send_return_label("C2", "O2003"))
attempt("Sam refunds 38.00 on O1001 (includes 6.00 shipping)", lambda: shop.issue_refund("C1", "O1001", 38.00, "changed mind"))
attempt("Sam refunds 32.00 on O1001", lambda: shop.issue_refund("C1", "O1001", 32.00, "changed mind"))
attempt("Sam refunds 5.00 on O1001 again", lambda: shop.issue_refund("C1", "O1001", 5.00, "again"))
attempt("Sam cancels O1002 (still processing)", lambda: shop.cancel_order("C1", "O1002"))
