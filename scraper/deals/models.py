"""Shared data shapes for the scraper."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class ProductObs:
    """One price observation of one product at one store, on one day."""

    store: str                      # "Pick n Pay", "Checkers", "Woolworths", "Dis-Chem", "Clicks"
    store_sku: str                  # the store's own product id
    name: str
    price: float                    # what you pay today (promo price if on promo)
    was_price: Optional[float] = None   # the "was"/regular price the store claims
    promo_text: Optional[str] = None    # e.g. "Buy 2 for R50", "Smart Shopper R39.99"
    member_price: Optional[float] = None  # loyalty price (Smart Shopper / Xtra Savings / WRewards / ClubCard)
    barcode: Optional[str] = None
    brand: Optional[str] = None
    size_text: Optional[str] = None     # e.g. "2.5 kg", "6 x 1 l"
    url: Optional[str] = None
    image: Optional[str] = None
    category: Optional[str] = None
    valid_until: Optional[str] = None   # ISO date if the store says when the promo ends
    local: Optional[bool] = None        # True for small local businesses
    suburb: Optional[str] = None

    @property
    def on_promo(self) -> bool:
        return bool(
            (self.was_price and self.was_price > self.price + 0.009)
            or self.promo_text
            or (self.member_price and self.member_price < self.price - 0.009)
        )

    @property
    def key(self) -> str:
        """Stable id for price history: store + store sku."""
        return f"{slug(self.store)}:{self.store_sku}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        d["on_promo"] = self.on_promo
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class RestaurantSpecial:
    title: str
    restaurant: Optional[str]
    suburb: Optional[str]
    price: Optional[float]
    days: list[str] = field(default_factory=list)   # ["Tuesday", ...]
    source: str = ""
    url: str = ""
    published: Optional[str] = None   # ISO date
    modified: Optional[str] = None    # ISO date
    summary: Optional[str] = None
    image: Optional[str] = None
    address: Optional[str] = None

    @property
    def key(self) -> str:
        base = (self.restaurant or "") + "|" + norm_text(self.title)
        return "rest:" + hashlib.sha1(base.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return {k: v for k, v in d.items() if v not in (None, [], "")}


_slug_re = re.compile(r"[^a-z0-9]+")


def slug(s: str) -> str:
    return _slug_re.sub("-", s.lower()).strip("-")


def norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


_price_re = re.compile(r"R\s?(\d{1,3}(?:[ ,]\d{3})*(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)", re.I)


def parse_rand(text: str | None) -> Optional[float]:
    """'R1 299.99' / 'R 49,99' / '49.99' -> float. Returns the first amount found."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    t = str(text).strip()
    m = _price_re.search(t)
    raw = m.group(1) if m else None
    if raw is None:
        m2 = re.search(r"\d+(?:[.,]\d{1,2})?", t)
        if not m2:
            return None
        raw = m2.group(0)
    raw = raw.replace(" ", "")
    # "1,299.99" -> thousands comma; "49,99" -> decimal comma
    if "," in raw and "." in raw:
        raw = raw.replace(",", "")
    elif "," in raw:
        head, _, tail = raw.rpartition(",")
        raw = head.replace(",", "") + ("." + tail if len(tail) == 2 else tail)
    try:
        return round(float(raw), 2)
    except ValueError:
        return None
