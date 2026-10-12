"""The store's catalogue: what can be bought, at what price, and the shipping rule.

Prices live here, on the server, and nothing the browser sends can change them: checkout looks the
product up by id and charges the price below. The rules match the help articles:
  - Shipping is free on orders over 75 dollars, otherwise standard shipping is 6 dollars (shipping.md).
  - Clearance items are final sale and cannot be returned or refunded (returns.md).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

FREE_SHIPPING_OVER_CENTS = 7500
STANDARD_SHIPPING_CENTS = 600


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    price_cents: int
    tagline: str
    final_sale: bool = False

    def public(self) -> dict:
        return {**asdict(self), "shipping_cents": shipping_for(self.price_cents)}


PRODUCTS: tuple[Product, ...] = (
    Product("cushion", "Linen cushion cover set", 3200, "Stonewashed linen, set of two"),
    Product("table", "Oak side table", 12900, "Solid oak, oiled finish"),
    Product("planter", "Ceramic planter (large)", 6450, "Hand-glazed, with drainage"),
    Product("throw", "Wool throw blanket", 8900, "Lambswool, 130 x 180 cm"),
    Product("lamp", "Ceramic table lamp", 10000, "Linen shade, braided cord"),
    Product("mug", "Clearance stoneware mug", 1300, "Last pieces. Final sale", final_sale=True),
    Product("shelf", "Walnut bookshelf", 8800, "Four tiers, flat-pack"),
    Product("towels", "Cotton tea towels", 3600, "Set of four, woven cotton"),
)
_BY_ID = {p.id: p for p in PRODUCTS}


def shipping_for(subtotal_cents: int) -> int:
    return 0 if subtotal_cents > FREE_SHIPPING_OVER_CENTS else STANDARD_SHIPPING_CENTS


def product(product_id: str) -> Product:
    """The product with this id, or KeyError. Never trust a price from the browser; use this."""
    return _BY_ID[product_id]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def mentioned(text: str) -> Product | None:
    """The product a message talks about, if any: all of its name's main words appear in the message."""
    said = _words(text)
    best, best_hits = None, 0
    for p in PRODUCTS:
        key = _words(re.sub(r"\(.*?\)", "", p.name)) - {"set", "large"}
        hits = len(key & said)
        if key and hits == len(key) and hits > best_hits:
            best, best_hits = p, hits
    return best


def without_product(text: str, p: Product) -> str:
    """The message with the product's name taken out, so a help-article search sees only the question."""
    out = text
    for word in _words(p.name):
        out = re.sub(rf"\b{word}\b", " ", out, flags=re.I)
    return re.sub(r"\s+", " ", out).strip()
