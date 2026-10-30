"""Specials published on a restaurant's own website — as text or as a poster image.

Config (sources.json -> "restaurant_sites"):
  {"name": "Corner Deck", "url": "https://cornerdeck.co.za", "suburb": "Brackenfell",
   "address": "Cape Gate Lifestyle Centre, Okavango Road, Brackenfell",
   "poster_search": "special"}            # WordPress media search for the poster (optional)
   "poster_urls": [...]                   # or explicit image URLs (optional)
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Http
from ..models import RestaurantSpecial
from ..ocr import ocr_lines, parse_weekly_specials
from .retail import SourceResult

log = logging.getLogger(__name__)


def scrape_restaurant_site(cfg: dict, http: Http) -> SourceResult:
    name, base = cfg["name"], cfg["url"].rstrip("/")
    res = SourceResult(name=f"{name} (website)", ok=False, method="site")
    found: list[tuple[dict, dict]] = []   # (special, origin info)
    errors = []

    # 1. Specials written as text on the site
    page_html = ""
    for path in cfg.get("pages", ["/"]):
        try:
            page_html = http.get_text(urljoin(base + "/", path.lstrip("/")), retries=1)
            text_lines = BeautifulSoup(page_html, "html.parser").get_text("\n", strip=True).splitlines()
            specials, footer = parse_weekly_specials(text_lines)
            for sp in specials:
                found.append((sp, {"url": urljoin(base + "/", path.lstrip("/")), "footer": footer, "date": None}))
        except Exception as e:
            errors.append(f"page {path}: {e}")

    # 2. Specials as a poster image
    for img in _poster_candidates(cfg, base, http, page_html, errors)[:2]:
        try:
            raw = http.get(img["url"], retries=1).content
            specials, footer = parse_weekly_specials(ocr_lines(raw))
            res.method = "site+poster"
            for sp in specials:
                found.append((sp, {"url": img["url"], "footer": footer, "date": img.get("date"),
                                   "modified": img.get("modified")}))
            if specials:
                break  # newest poster that has specials wins
        except Exception as e:
            errors.append(f"poster {img['url']}: {type(e).__name__} {e}")

    seen = set()
    for sp, origin in found:
        key = (sp["day"], sp["text"].lower())
        if key in seen:
            continue
        seen.add(key)
        summary = " · ".join(x for x in (sp.get("note"), origin.get("footer")) if x)
        res.items.append(RestaurantSpecial(
            title=sp["text"],
            restaurant=name,
            suburb=cfg.get("suburb"),
            price=sp.get("price"),
            days=[sp["day"]],
            source=f"{name} website",
            url=cfg.get("link") or base,
            published=origin.get("date"),
            modified=origin.get("modified") or origin.get("date"),
            summary=summary or None,
            address=cfg.get("address"),
            own_site=True,
            poster=origin["url"] if origin["url"].lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else None,
        ))
    res.ok = bool(res.items)
    res.error = "" if res.ok else ("; ".join(errors) or "No weekly specials recognised on the site or its posters")
    return res


def _poster_candidates(cfg: dict, base: str, http: Http, page_html: str, errors: list) -> list[dict]:
    out: list[dict] = [{"url": u} for u in cfg.get("poster_urls", [])]
    term = cfg.get("poster_search")
    if term:
        try:
            media = http.get_json(f"{base}/wp-json/wp/v2/media",
                                  params={"search": term, "per_page": 10, "orderby": "date", "order": "desc",
                                          "_fields": "source_url,date,modified,mime_type"}, retries=1)
            for m in media:
                if str(m.get("mime_type", "")).startswith("image/"):
                    out.append({"url": m["source_url"], "date": (m.get("date") or "")[:10] or None,
                                "modified": (m.get("modified") or "")[:10] or None})
        except Exception as e:
            errors.append(f"media search: {e}")
    if page_html:  # images on the page whose file name or alt text says "special"
        soup = BeautifulSoup(page_html, "html.parser")
        for tag in soup.find_all(["img", "a"]):
            u = tag.get("href") or tag.get("data-src") or tag.get("src") or ""
            label = f"{u} {tag.get('alt', '')} {tag.get('title', '')}"
            if re.search(r"special|promo|deal", label, re.I) and re.search(r"\.(jpe?g|png|webp)", u, re.I):
                out.append({"url": urljoin(base + "/", u)})
    uniq, seen = [], set()
    for o in out:
        if o["url"] not in seen:
            seen.add(o["url"])
            uniq.append(o)
    return uniq
