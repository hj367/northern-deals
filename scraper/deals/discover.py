"""Weekly: find northern-suburbs businesses and the specials on their own websites.

  1. Business list: OpenStreetMap (free) + any CSVs from the Google Maps scraper kit
     dropped into scraper/businesses/ (see README).
  2. Crawl4AI visits each website, follows links to specials/promotions/menu pages,
     reads the text and any specials posters (OCR).
  3. Specials are read with free pattern rules, or Gemini's free tier if GEMINI_API_KEY is set.
  4. Results go to data/discovered.json; the daily scan includes them.

    python -m deals.discover --data ../data [--max-sites 200]
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from . import llm
from .crawl import Page, fetch_pages, same_site
from .geo import BBOX, OVERPASS_ENDPOINTS, UA
from .http import Http
from .ocr import ocr_lines, parse_weekly_specials

log = logging.getLogger("discover")
HERE = Path(__file__).resolve().parent.parent
SA = ZoneInfo("Africa/Johannesburg")
RECHECK_DAYS = 6

FOOD_AMENITY = "restaurant|cafe|pub|bar|fast_food|biergarten|food_court|ice_cream"
FOOD_SHOP = ("butcher|bakery|deli|alcohol|wine|beverages|greengrocer|farm|seafood|cheese|pastry|confectionery|"
             "coffee|tea|pet|garden_centre|frozen_food|health_food|spices|chocolate|nuts|dairy")
# Websites that can't be crawled for specials (social media, booking/delivery platforms, link pages)
SKIP_DOMAINS = re.compile(
    r"(facebook|instagram|fb\.com|twitter|x\.com|tiktok|linktr\.ee|wa\.me|whatsapp|google\.|goo\.gl|"
    r"tripadvisor|dineplan|mrd|ubereats|bolt\.eu|zomato|yelp|wixsite\.com/[^/]*$)", re.I)

SPECIAL_LINK = re.compile(r"special|promo|deal|offer|happy[\s_-]?hour|weekly|what.?s[\s_-]?on|daily|"
                          r"kids[\s_-]?eat|combo|discount|sale|aanbied|spesiale", re.I)
MENU_LINK = re.compile(r"\bmenu|\bmenus\b|food|eat", re.I)
POSTER_HINT = re.compile(r"special|promo|deal|weekly|offer|happy|monday|tuesday|wednesday|thursday|"
                         r"friday|saturday|sunday|spesiale", re.I)
SPECIAL_LINE = re.compile(r"\bspecials?\b|half[- ]price|\d{1,2}\s*%\s*off|\b2\s*for\s*1\b|two for one|"
                          r"buy one|happy hour|kids eat free|\bonly R\s?\d|\bnow R\s?\d|\bcombo\b|"
                          r"\bR\s?\d{2,4}\s*off\b|free (?:dessert|drink|beer|glass|side|coffee|kids)", re.I)
NOT_A_DEAL = re.compile(r"deliver|shipping|voucher|gift card|competition|terms|cookie|privacy|minimum order|"
                        r"subscribe|newsletter|vacanc|booking fee|corkage|deposit|t\s*&\s*c", re.I)


# ---------------------------------------------------------------- business list
def osm_businesses(http: Http) -> list[dict]:
    s, w, n, e = BBOX
    bb = f"({s},{w},{n},{e})"
    q = f"""[out:json][timeout:150];
(
 nwr["amenity"~"^({FOOD_AMENITY})$"]["website"]{bb};
 nwr["amenity"~"^({FOOD_AMENITY})$"]["contact:website"]{bb};
 nwr["shop"~"^({FOOD_SHOP})$"]["website"]{bb};
 nwr["shop"~"^({FOOD_SHOP})$"]["contact:website"]{bb};
);
out center tags;"""
    data = None
    for ep in OVERPASS_ENDPOINTS:
        try:
            data = http.post(ep, data={"data": q}, timeout=180, retries=0).json()
            break
        except Exception as ex:
            log.warning("Overpass %s failed: %s", ep, str(ex)[:120])
    if data is None:
        return []
    out = []
    for el in data.get("elements", []):
        t = el.get("tags", {})
        if t.get("brand:wikidata") or t.get("brand:wikipedia"):
            continue  # national chains (Spur, KFC, Engen…) — not local specials
        site = t.get("website") or t.get("contact:website")
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        kind = "restaurant" if t.get("amenity") else "shop"
        out.append({
            "name": t.get("name") or "",
            "website": site,
            "category": (t.get("amenity") or t.get("shop") or "").replace("_", " "),
            "kind": kind,
            "suburb": t.get("addr:suburb") or t.get("addr:city"),
            "address": ", ".join(x for x in (
                " ".join(filter(None, [t.get("addr:housenumber"), t.get("addr:street")])),
                t.get("addr:suburb")) if x) or None,
            "lat": round(lat, 5) if lat else None,
            "lng": round(lng, 5) if lng else None,
            "found_via": "OpenStreetMap",
        })
    return out


_COLS = {
    "name": ("name", "title", "business_name", "place_name"),
    "website": ("website", "site", "url", "web", "domain"),
    "category": ("category", "main_category", "type", "categories", "category_name"),
    "address": ("address", "full_address", "street_address"),
    "lat": ("lat", "latitude"),
    "lng": ("lng", "lon", "long", "longitude"),
}
_SHOP_WORDS = re.compile(r"shop|store|butcher|bakery|deli|liquor|bottle|wine|market|farm|grocer|pet|nursery|garden", re.I)


def kit_businesses(folder: Path) -> list[dict]:
    """CSV exports from the Google Maps scraper kit (or any CSV with name + website columns)."""
    out = []
    for f in sorted(folder.glob("*.csv")):
        with f.open(newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        if not rows:
            continue
        lower = {k.lower().strip(): k for k in rows[0].keys() if k}
        col = {field: next((lower[c] for c in cands if c in lower), None) for field, cands in _COLS.items()}
        if not col["name"] or not col["website"]:
            log.warning("%s: needs at least name and website columns (has %s)", f.name, list(lower))
            continue
        for r in rows:
            site = (r.get(col["website"]) or "").strip()
            if not site:
                continue
            cat = (r.get(col["category"]) or "") if col["category"] else ""

            def num(c):
                try:
                    return round(float(r.get(col[c]) or ""), 5)
                except (TypeError, ValueError):
                    return None
            out.append({
                "name": (r.get(col["name"]) or "").strip(),
                "website": site if site.startswith("http") else "https://" + site,
                "category": cat.split(",")[0].strip(),
                "kind": "shop" if _SHOP_WORDS.search(cat) and not re.search(r"restaurant|caf|pub|bar|grill", cat, re.I) else "restaurant",
                "suburb": None,
                "address": (r.get(col["address"]) or "").strip() or None if col["address"] else None,
                "lat": num("lat"),
                "lng": num("lng"),
                "found_via": "Google Maps",
            })
    return out


def site_key(url: str) -> str:
    host = urlparse(url if "//" in url else "https://" + url).netloc.lower().removeprefix("www.")
    return host


def in_area(b: dict) -> bool:
    if b.get("lat") is None or b.get("lng") is None:
        return True  # kit rows without coordinates came from northern-suburbs searches
    s, w, n, e = BBOX
    return s <= b["lat"] <= n and w <= b["lng"] <= e


# ---------------------------------------------------------------- reading specials
def rule_specials(text: str) -> list[dict]:
    """Free pattern rules: weekly day-by-day lists, plus single lines that are clearly a deal."""
    lines = [ln.strip(" #*-•|>").strip() for ln in text.splitlines()]
    lines = [re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", ln) for ln in lines if ln]   # markdown links -> text
    weekly, _ = parse_weekly_specials(lines)
    out = []
    for s in weekly:
        if NOT_A_DEAL.search(s["text"]):
            continue
        day = "Daily" if re.search(r"every ?day|daily|7 days", s["text"], re.I) else s["day"]
        out.append({"day": day, "text": s["text"], "price": s.get("price")})
    seen = {s["text"].lower() for s in out}
    for ln in lines:
        if not (8 <= len(ln) <= 140) or ln.lower() in seen:
            continue
        if SPECIAL_LINE.search(ln) and not NOT_A_DEAL.search(ln) and (re.search(r"R\s?\d", ln) or re.search(
                r"half|%|free|2\s*for\s*1|two for one|buy one", ln, re.I)):
            day = next((d for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
                        if re.search(rf"\b{d}s?\b", ln, re.I)), None)
            if re.search(r"every ?day|daily|7 days", ln, re.I):
                day = "Daily"
            m = re.search(r"R\s?(\d{2,4})(?![\d.]*\s*off)", ln)
            out.append({"day": day, "text": ln, "price": float(m.group(1)) if m else None})
            seen.add(ln.lower())
    return out[:15]


def read_page_specials(page: Page, http: Http) -> list[dict]:
    if llm.available():
        got = llm.extract_specials(page.text, page.url, http)
        if got is not None:
            return got
    return rule_specials(page.text)


def candidate_pages(home: Page) -> list[str]:
    strong, menu = [], []
    for url, txt in home.links:
        if not same_site(url, home.url) or url.rstrip("/") == home.url.rstrip("/"):
            continue
        if re.search(r"\.(pdf|jpe?g|png|zip)(\?|$)", url, re.I):
            continue
        label = f"{txt} {urlparse(url).path}"
        if SPECIAL_LINK.search(label):
            strong.append(url)
        elif MENU_LINK.search(label):
            menu.append(url)
    picks = list(dict.fromkeys(strong))[:3]
    if not picks:
        picks = list(dict.fromkeys(menu))[:1]
    return picks


def poster_candidates(pages: list[Page]) -> list[str]:
    out = []
    for p in pages:
        for url, alt in p.images:
            label = f"{urlparse(url).path} {alt}"
            if POSTER_HINT.search(label) and not re.search(r"logo|icon|favicon|\.svg|\.gif", url, re.I):
                out.append(url)
    return list(dict.fromkeys(out))[:2]


def probe_shop(site: str, http: Http) -> Optional[str]:
    base = site.rstrip("/")
    for platform, path in (("shopify", "/products.json?limit=1"), ("woocommerce", "/wp-json/wc/store/v1/products?per_page=1")):
        try:
            r = http.s.get(base + path, timeout=15)
            if r.status_code == 200 and r.text.lstrip()[:1] in "[{" and (
                    '"products"' in r.text or (r.text.lstrip().startswith("[") and '"prices"' in r.text)):
                return platform
        except Exception:
            pass
    return None


# ---------------------------------------------------------------- main
def run(data_dir: Path, max_sites: int, today: str) -> dict:
    path = data_dir / "discovered.json"
    prev = json.loads(path.read_text()) if path.exists() else {"businesses": {}}
    known: dict[str, dict] = prev.get("businesses", {})

    http = Http(min_delay=0.3, max_delay=0.8)
    http.s.headers["User-Agent"] = UA
    candidates = osm_businesses(http) + kit_businesses(HERE / "businesses")
    for b in candidates:
        site = b.get("website") or ""
        if not site or SKIP_DOMAINS.search(site) or not in_area(b):
            continue
        k = site_key(site)
        if not k:
            continue
        rec = known.setdefault(k, {"checked": None})
        for f in ("name", "website", "category", "kind", "suburb", "address", "lat", "lng", "found_via"):
            if b.get(f) not in (None, "") and (rec.get(f) in (None, "") or f in ("lat", "lng") and b["found_via"] == "Google Maps"):
                rec[f] = b[f]
    log.info("%d candidate businesses (%d known with websites)", len(candidates), len(known))

    cutoff = (date.fromisoformat(today) - timedelta(days=RECHECK_DAYS)).isoformat()
    due = sorted((k for k, r in known.items() if not r.get("checked") or r["checked"] <= cutoff),
                 key=lambda k: known[k].get("checked") or "")[:max_sites]
    log.info("checking %d websites this run", len(due))

    homes = fetch_pages([known[k]["website"] for k in due])
    follow: dict[str, list[str]] = {}
    for k in due:
        home = homes.get(known[k]["website"])
        known[k]["checked"] = today
        if not home or not home.ok:
            known[k]["error"] = (home.error if home else "not fetched")[:160]
            known[k]["specials"] = []
            continue
        known[k].pop("error", None)
        follow[k] = candidate_pages(home)
    subpages = fetch_pages([u for urls in follow.values() for u in urls])

    for k, urls in follow.items():
        rec = known[k]
        home = homes[rec["website"]]
        pages = [home] + [subpages[u] for u in urls if u in subpages and subpages[u].ok]
        specials: list[dict] = []
        for p in pages:
            for s in read_page_specials(p, http):
                s["page"] = p.url
                specials.append(s)
        for img in poster_candidates(pages):
            try:
                weekly, _ = parse_weekly_specials(ocr_lines(http.get(img, retries=0, timeout=30).content))
                for s in weekly:
                    specials.append({"day": s["day"], "text": s["text"], "price": s.get("price"),
                                     "page": img, "poster": img})
            except Exception as e:
                log.info("poster %s: %s", img, str(e)[:100])
        uniq, seen = [], set()
        for s in specials:
            key = (s.get("day"), re.sub(r"\W+", " ", s["text"].lower()).strip())
            if key not in seen:
                seen.add(key)
                uniq.append(s)
        rec["specials"] = uniq[:15]
        rec["specials_pages"] = urls
        if rec.get("kind") == "shop" and not rec.get("shop_platform"):
            rec["shop_platform"] = probe_shop(rec["website"], http)

    with_specials = sum(1 for r in known.values() if r.get("specials"))
    shops = sum(1 for r in known.values() if r.get("shop_platform"))
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reader": "gemini" if llm.available() else "rules",
        "counts": {"businesses": len(known), "checked_this_run": len(due),
                   "with_specials": with_specials, "online_shops": shops},
        "businesses": known,
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=0))
    log.info("DISCOVERY businesses=%d checked=%d with_specials=%d online_shops=%d reader=%s",
             len(known), len(due), with_specials, shops, out["reader"])
    for k in due:
        r = known[k]
        if r.get("specials"):
            log.info("FOUND %-35s %-14s %d specials e.g. %s", (r.get("name") or k)[:35], r.get("suburb") or "",
                     len(r["specials"]), r["specials"][0]["text"][:70])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE.parent / "data"))
    ap.add_argument("--max-sites", type=int, default=int(os.environ.get("MAX_SITES", "200")))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "crawl4ai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    run(Path(args.data), args.max_sites, datetime.now(SA).date().isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
