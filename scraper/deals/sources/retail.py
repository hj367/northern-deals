"""Config-driven retail scrapers (see sources.json)."""
from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import urljoin
from dataclasses import dataclass, field

from ..extract import products_from_html, products_from_json
from ..http import Http
from ..models import ProductObs

log = logging.getLogger(__name__)

APIFY_URL = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"


@dataclass
class SourceResult:
    name: str
    ok: bool
    items: list = field(default_factory=list)
    method: str = ""
    error: str = ""
    pages: int = 0

    def health(self) -> dict:
        return {
            "source": self.name,
            "ok": self.ok,
            "count": len(self.items),
            "method": self.method,
            "pages": self.pages,
            "error": self.error[:300],
        }


def _page_url(cfg: dict, page0: int) -> str:
    env = cfg.get("store_param_env")
    store = (os.environ.get(env) if env else None) or cfg.get("store_default", "")
    return cfg["url"].format(page=page0 + 1, page0=page0, offset=page0 * cfg.get("page_size", 0), store=store)


def scrape_retail(cfg: dict, http: Http) -> SourceResult:
    store = cfg["store"]
    res = SourceResult(name=store, ok=False, method=cfg["strategy"])
    seen: set[str] = set()
    try:
        for page0 in range(cfg.get("pages", 5)):
            url = _page_url(cfg, page0)
            if cfg["strategy"] == "json":
                if cfg.get("method", "GET").upper() == "POST":
                    data = http.post(url, json=cfg.get("json_body", {}),
                                     headers={"Accept": "application/json"}).json()
                else:
                    data = http.get_json(url, headers={"Accept": "application/json"})
                found = products_from_json(data, store, cfg.get("base_url", ""))
            elif cfg["strategy"] == "woolworths":
                found = woolworths_products(http.get_text(url), store, cfg.get("base_url", ""))
            else:
                html = http.get_text(url)
                found = products_from_html(html, store, cfg.get("base_url", ""))
            res.pages += 1
            new = [p for p in found if p.key not in seen]
            for p in new:
                seen.add(p.key)
            res.items.extend(new)
            log.info("%s page %d: %d products (%d new)", store, page0, len(found), len(new))
            if not new:
                break
        res.ok = len(res.items) > 0
        if not res.ok:
            res.error = "Page loaded but no products were recognised (site layout or URL may have changed)."
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
        log.warning("%s failed: %s", store, res.error)

    # Fallback: hosted scraper with SA residential IPs (optional, paid per item).
    if not res.ok and cfg.get("apify_actor") and os.environ.get("APIFY_TOKEN"):
        try:
            items = scrape_apify(cfg, http)
            if items:
                res.items, res.ok, res.method = items, True, "apify"
                res.error = f"direct failed ({res.error}); used Apify fallback"
        except Exception as e:
            res.error += f" | Apify fallback failed: {e}"
    res.items = [p for p in res.items if p.price and p.name]
    return res


_WW_STATE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*({.*?})\s*;?\s*</script>", re.S)


def woolworths_products(html: str, store: str, base_url: str) -> list[ProductObs]:
    """Woolworths embeds listing data in __INITIAL_STATE__: p10 = price, p10_wp = was price, id = barcode."""
    m = _WW_STATE.search(html)
    if not m:
        return []
    state = json.loads(m.group(1))
    out, seen = [], set()

    def walk(o, depth=0):
        if depth > 30:
            return
        if isinstance(o, dict):
            if "p10" in o and "description" in o and "id" in o:
                p = _ww_product(o, store, base_url)
                if p and p.key not in seen:
                    seen.add(p.key)
                    out.append(p)
                return
            for v in o.values():
                walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, depth + 1)

    walk(state)
    return out


def _ww_product(d: dict, store: str, base_url: str):
    price = d.get("p10")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    was = d.get("p10_wp")
    promo = "; ".join(d.get("promo") or []) or None
    pid = str(d["id"])
    return ProductObs(
        store=store,
        store_sku=pid,
        name=d.get("description", ""),
        price=round(float(price), 2),
        was_price=round(float(was), 2) if isinstance(was, (int, float)) and was > price else None,
        promo_text=promo,
        barcode=pid if pid.isdigit() and len(pid) in (8, 12, 13) else None,
        brand=d.get("brand") if d.get("brand") not in ("Woolies Brands", "Other Brands") else None,
        url=urljoin(base_url, d.get("url", "")) if d.get("url") else None,
        image=d.get("image_url"),
    )


def scrape_apify(cfg: dict, http: Http) -> list[ProductObs]:
    url = APIFY_URL.format(actor=cfg["apify_actor"])
    r = http.post(
        url,
        params={"token": os.environ["APIFY_TOKEN"]},
        json=cfg.get("apify_input", {}),
        timeout=300,
        retries=0,
    )
    rows = r.json()
    out = []
    for row in rows if isinstance(rows, list) else []:
        # Apify rows: price = shelf price, promoPrice = promo, loyaltyPrice = member price
        if row.get("promoPrice") and row.get("price") and row["promoPrice"] < row["price"]:
            row = {**row, "wasPrice": row["price"], "price": row["promoPrice"]}
        out.extend(products_from_json(row, cfg["store"], cfg.get("base_url", "")))
    return out
