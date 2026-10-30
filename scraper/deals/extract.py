"""Generic product extraction.

Retailer sites change markup often. Instead of relying only on CSS selectors,
we look for product-shaped data wherever sites usually put it:
  * schema.org JSON-LD (<script type="application/ld+json">)
  * embedded app state (__NEXT_DATA__, window.__INITIAL_STATE__, etc.)
  * JSON in data-* attributes (e.g. Checkers' data-product-ga)
  * plain JSON API responses
and then walk the JSON for dicts that look like products.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterable, Iterator, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import ProductObs, parse_rand

NAME_KEYS = ("name", "displayName", "productName", "title", "productTitle")
ID_KEYS = ("code", "sku", "productId", "id", "catalogRefId", "productCode", "itemId")
PRICE_KEYS = (
    "promoPrice", "salePrice", "specialPrice", "finalPrice", "sellingPrice",
    "currentPrice", "price", "priceValue", "lowPrice",
)
WAS_KEYS = (
    "wasPrice", "oldPrice", "regularPrice", "originalPrice", "beforePrice",
    "strikePrice", "strikeThroughPrice", "listPrice", "basePrice", "previousPrice",
)
MEMBER_KEYS = ("loyaltyPrice", "memberPrice", "smartShopperPrice", "xtraSavingsPrice", "clubCardPrice")
BARCODE_KEYS = ("gtin13", "gtin", "ean", "barcode", "gtin14", "upc")
URL_KEYS = ("url", "productUrl", "link", "pdpUrl", "href")
IMG_KEYS = ("image", "imageUrl", "img", "thumbnail", "images", "imageURL")
BRAND_KEYS = ("brand", "brandName", "manufacturer")
SIZE_KEYS = ("size", "packSize", "netContent", "unitOfMeasure", "weight", "volume")
PROMO_KEYS = (
    "promotionText", "promoText", "promotionTextMessage", "promotion", "promotions",
    "potentialPromotions", "badges", "offerText", "dealText", "promoDescription",
)
VALID_KEYS = ("priceValidUntil", "validUntil", "promotionEndDate", "endDate", "loyaltyValidTo")


def _first(d: dict, keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def _money(v: Any) -> Optional[float]:
    """Price values come as 49.99, "R49.99", {"value": 49.99}, {"formattedValue": "R49.99"}..."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2) if v > 0 else None
    if isinstance(v, str):
        p = parse_rand(v)
        return p if p and p > 0 else None
    if isinstance(v, dict):
        for k in ("value", "amount", "price", "formattedValue", "displayValue", "current"):
            if k in v:
                m = _money(v[k])
                if m:
                    return m
    if isinstance(v, list) and v:
        return _money(v[0])
    return None


def _text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, str):
        t = re.sub(r"<[^>]+>", " ", v)
        t = re.sub(r"\s+", " ", t).strip()
        return t or None
    if isinstance(v, dict):
        return _text(_first(v, ("name", "description", "promotionTextMessage", "text", "title", "label")))
    if isinstance(v, list):
        parts = [p for p in (_text(x) for x in v) if p]
        return "; ".join(dict.fromkeys(parts)) or None
    return str(v)


def _img(v: Any) -> Optional[str]:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return _img(_first(v, ("url", "src", "contentUrl", "large", "medium")))
    if isinstance(v, list) and v:
        return _img(v[0])
    return None


def looks_like_product(d: dict) -> bool:
    if not isinstance(d, dict):
        return False
    name = _first(d, NAME_KEYS)
    if not isinstance(name, str) or len(name) < 3:
        return False
    price = _money(_first(d, PRICE_KEYS)) or _money(d.get("offers"))
    return price is not None


def product_from_dict(d: dict, store: str, base_url: str = "") -> Optional[ProductObs]:
    if not looks_like_product(d):
        return None
    offers = d.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    offers = offers if isinstance(offers, dict) else {}

    name = _text(_first(d, NAME_KEYS))
    price = _money(_first(d, PRICE_KEYS)) or _money(_first(offers, PRICE_KEYS))
    was = _money(_first(d, WAS_KEYS)) or _money(_first(offers, WAS_KEYS))
    if not was and isinstance(d.get("price"), dict):  # Hybris (Pick n Pay): price.oldPrice
        was = _money(_first(d["price"], WAS_KEYS + ("oldPrice",)))
    if was and price and was <= price:
        was = None
    member = _money(_first(d, MEMBER_KEYS))
    pid = _first(d, ID_KEYS) or _first(offers, ("sku",)) or name
    url = _first(d, URL_KEYS) or offers.get("url")
    if isinstance(url, str) and base_url:
        url = urljoin(base_url, url)
    image = _img(_first(d, IMG_KEYS))
    if image and base_url:
        image = urljoin(base_url, image)
    brand = _first(d, BRAND_KEYS)
    promo = _text(_first(d, PROMO_KEYS))
    if promo and len(promo) > 160:
        promo = promo[:157] + "..."
    valid = _first(d, VALID_KEYS) or offers.get("priceValidUntil")
    promos = d.get("potentialPromotions")
    if not valid and isinstance(promos, list) and promos and isinstance(promos[0], dict):
        valid = promos[0].get("endDate")
    if not valid and promo:
        valid = _valid_from_text(promo)
    barcode = _text(_first(d, BARCODE_KEYS))
    if not barcode and image:  # Pick n Pay image names carry the EAN
        m = re.search(r"-(\d{13})-", image)
        barcode = m.group(1) if m else None

    return ProductObs(
        store=store,
        store_sku=str(pid),
        name=name or "",
        price=price,  # type: ignore[arg-type]
        was_price=was,
        promo_text=promo,
        member_price=member if member and member < (price or 1e9) else None,
        barcode=barcode,
        brand=_text(brand),
        size_text=_text(_first(d, SIZE_KEYS)) if not isinstance(_first(d, SIZE_KEYS), (int, float)) else None,
        url=url if isinstance(url, str) else None,
        image=image,
        category=_text(d.get("category")) if isinstance(d.get("category"), (str, list)) else None,
        valid_until=str(valid)[:10] if valid else None,
    )


def walk(obj: Any, depth: int = 0) -> Iterator[dict]:
    """Yield every dict in a JSON tree that looks like a product (outermost match only)."""
    if depth > 25:
        return
    if isinstance(obj, dict):
        if looks_like_product(obj) and not _is_container(obj):
            yield obj
            return
        for v in obj.values():
            yield from walk(v, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v, depth + 1)


def _is_container(d: dict) -> bool:
    """A page/category object can have name+price-ish keys but also hold a product list."""
    for v in d.values():
        if isinstance(v, list) and len(v) >= 2 and sum(isinstance(x, dict) and looks_like_product(x) for x in v) >= 2:
            return True
    return False


def products_from_json(obj: Any, store: str, base_url: str = "") -> list[ProductObs]:
    out, seen = [], set()
    for d in walk(obj):
        p = product_from_dict(d, store, base_url)
        if p and p.key not in seen:
            seen.add(p.key)
            out.append(p)
    return out


_STATE_RE = re.compile(
    r"(?:window\.__(?:INITIAL_STATE|PRELOADED_STATE|NUXT|APOLLO_STATE)__|window\.dataLayerProducts)\s*=\s*({.*?});?\s*</script>",
    re.S,
)


def embedded_json_blobs(html: str) -> list[Any]:
    soup = BeautifulSoup(html, "html.parser")
    blobs: list[Any] = []
    for s in soup.find_all("script"):
        t = (s.get("type") or "").lower()
        txt = s.string or s.get_text() or ""
        if t == "application/ld+json" or s.get("id") == "__NEXT_DATA__" or t == "application/json":
            try:
                blobs.append(json.loads(txt))
            except Exception:
                pass
    for m in _STATE_RE.finditer(html):
        try:
            blobs.append(json.loads(m.group(1)))
        except Exception:
            pass
    # JSON stored in attributes, e.g. data-product-ga='{"name":..,"price":..}'
    for el in soup.find_all(attrs=True):
        for attr, val in el.attrs.items():
            if attr.startswith("data-") and isinstance(val, str) and val[:1] in "{[" and "price" in val.lower():
                try:
                    blob = json.loads(val)
                except Exception:
                    continue
                if isinstance(blob, dict):
                    blob.setdefault("_tile_html", None)
                    _enrich_from_tile(blob, el)
                blobs.append(blob)
    return blobs


def _enrich_from_tile(blob: dict, el) -> None:
    """Attribute JSON often lacks the 'was' price and link, which sit in the tile markup."""
    tile = el
    for _ in range(4):  # climb to the product tile
        if tile.parent is None:
            break
        if tile.find("a", href=True):
            break
        tile = tile.parent
    text = tile.get_text(" ", strip=True)
    if "wasPrice" not in blob:
        was_el = tile.select_one(
            ".before-price, .was-price, .price--was, .old-price, del, s, [class*='strike'], [class*='before']"
        )
        if was_el:
            blob["wasPrice"] = was_el.get_text(" ", strip=True)
    if "promotionText" not in blob:
        promo_el = tile.select_one("[class*='promotion'], [class*='promo'], [class*='deal'], [class*='badge']")
        if promo_el:
            blob["promotionText"] = promo_el.get_text(" ", strip=True)
    if "url" not in blob:
        a = tile.find("a", href=True)
        if a:
            blob["url"] = a["href"]
    if "image" not in blob:
        img = tile.find("img")
        if img:
            blob["image"] = img.get("data-src") or img.get("src")
    blob.pop("_tile_html", None)
    _ = text


def products_from_html(html: str, store: str, base_url: str) -> list[ProductObs]:
    out: list[ProductObs] = []
    seen: set[str] = set()
    for blob in embedded_json_blobs(html):
        for p in products_from_json(blob, store, base_url):
            if p.key not in seen:
                seen.add(p.key)
                out.append(p)
    return out


_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def _valid_from_text(text: str) -> Optional[str]:
    """'... Valid until 24 December 2026' -> '2026-12-24'."""
    m = re.search(r"(?:valid until|ends?|until)\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text, re.I)
    if not m or m.group(2).lower() not in _MONTHS:
        return None
    return f"{int(m.group(3)):04d}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
