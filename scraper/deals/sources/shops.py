"""Small-business online shops: auto-detects Shopify and WooCommerce, falls back to generic HTML.

Both platforms publish structured product data with the regular and the sale
price, which is exactly what the verifier needs.
  Shopify:     /products.json                      (price + compare_at_price)
  WooCommerce: /wp-json/wc/store/v1/products       (regular_price + sale_price)
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urljoin

from ..extract import products_from_html
from ..http import Http
from ..models import ProductObs
from .retail import SourceResult

log = logging.getLogger(__name__)


def scrape_shop(cfg: dict, http: Http) -> SourceResult:
    name, base = cfg["name"], cfg["url"].rstrip("/")
    res = SourceResult(name=name, ok=False)
    errors = []
    platform = cfg.get("platform", "auto")
    tries = [platform] if platform != "auto" else ["shopify", "woocommerce", "html"]
    for kind in tries:
        try:
            items = {"shopify": _shopify, "woocommerce": _woo, "html": _html}[kind](cfg, base, http)
        except Exception as e:
            errors.append(f"{kind}: {type(e).__name__} {str(e)[:80]}")
            continue
        if items:
            for p in items:
                p.category = cfg.get("category") or p.category
                p.local = True
                p.suburb = cfg.get("suburb")
            res.items, res.ok, res.method = items, True, kind
            return res
        errors.append(f"{kind}: no products")
    res.error = "; ".join(errors)
    return res


def _shopify(cfg: dict, base: str, http: Http) -> list[ProductObs]:
    out: list[ProductObs] = []
    for page in range(1, cfg.get("pages", 4) + 1):
        data = http.get_json(f"{base}/products.json", params={"limit": 250, "page": page}, retries=0)
        prods = data.get("products") if isinstance(data, dict) else None
        if not prods:
            break
        for p in prods:
            obs = shopify_product(p, cfg["name"], base)
            if obs:
                out.append(obs)
        if len(prods) < 250:
            break
    return out


def shopify_product(p: dict, store: str, base: str) -> Optional[ProductObs]:
    variants = [v for v in p.get("variants", []) if v.get("available", True)] or p.get("variants", [])
    if not variants:
        return None
    v = min(variants, key=lambda v: float(v.get("price") or 1e9))
    price = float(v.get("price") or 0)
    if price <= 0:
        return None
    cap = v.get("compare_at_price")
    was = float(cap) if cap not in (None, "", "0.00") else None
    imgs = p.get("images") or []
    title = p.get("title", "")
    if v.get("title") and v["title"] != "Default Title":
        title = f"{title} ({v['title']})"
    return ProductObs(
        store=store,
        store_sku=str(p.get("id")),
        name=title,
        price=round(price, 2),
        was_price=round(was, 2) if was and was > price else None,
        brand=p.get("vendor") or None,
        url=f"{base}/products/{p.get('handle')}",
        image=imgs[0].get("src") if imgs else None,
        category=p.get("product_type") or None,
        barcode=v.get("barcode") or None,
    )


def _woo(cfg: dict, base: str, http: Http) -> list[ProductObs]:
    out: list[ProductObs] = []
    for page in range(1, cfg.get("pages", 4) + 1):
        prods = http.get_json(f"{base}/wp-json/wc/store/v1/products",
                              params={"per_page": 100, "page": page}, retries=0)
        if not isinstance(prods, list) or not prods:
            break
        for p in prods:
            obs = woo_product(p, cfg["name"])
            if obs:
                out.append(obs)
        if len(prods) < 100:
            break
    return out


def woo_product(p: dict, store: str) -> Optional[ProductObs]:
    pr = p.get("prices") or {}
    unit = int(pr.get("currency_minor_unit", 2))

    def money(k: str) -> Optional[float]:
        v = pr.get(k)
        return round(int(v) / 10 ** unit, 2) if v not in (None, "", "0") else None

    price = money("price")
    if not price or (p.get("is_in_stock") is False and not p.get("is_purchasable", True)):
        return None
    regular = money("regular_price")
    imgs = p.get("images") or []
    return ProductObs(
        store=store,
        store_sku=str(p.get("id")),
        name=_unhtml(p.get("name", "")),
        price=price,
        was_price=regular if regular and regular > price else None,
        url=p.get("permalink"),
        image=imgs[0].get("src") if imgs else None,
        category=(p.get("categories") or [{}])[0].get("name"),
        barcode=p.get("sku") if str(p.get("sku", "")).isdigit() and len(str(p.get("sku"))) >= 12 else None,
    )


def _html(cfg: dict, base: str, http: Http) -> list[ProductObs]:
    url = cfg.get("specials_url") or base
    html = http.get_text(url, retries=0)
    return products_from_html(html, cfg["name"], urljoin(base + "/", ""))


def _unhtml(s: str) -> str:
    import html
    import re
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
