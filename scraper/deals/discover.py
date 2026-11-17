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
from .geo import OVERPASS_ENDPOINTS, UA
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
    parts = []
    for s, w, n, e in AREA:
        bb = f"({s},{w},{n},{e})"
        parts.append(f'nwr["amenity"~"^({FOOD_AMENITY})$"][~"^(contact:)?website$"~"."]{bb};')
        parts.append(f'nwr["shop"~"^({FOOD_SHOP})$"][~"^(contact:)?website$"~"."]{bb};')
    q = "[out:json][timeout:180];\n(\n" + "\n".join(parts) + "\n);"
    q += """
out center tags;"""
    data = None
    for ep in OVERPASS_ENDPOINTS:
        try:
            r = http.post(ep, data={"data": q}, timeout=240, retries=1)
            data = r.json()
            log.info("OSM: %d places with websites from %s", len(data.get("elements", [])), ep.split("/")[2])
            break
        except Exception as ex:
            log.warning("OSM lookup via %s failed: %s", ep.split("/")[2], str(ex)[:160])
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


# Northern suburbs as two boxes (south, west, north, east): Milnerton/Century City/Edgemead strip,
# and Goodwood–Parow–Bellville–Durbanville–Brackenfell–Kraaifontein–Kuils River. Excludes the City Bowl,
# Observatory, Salt River, Pinelands and the southern suburbs.
AREA = [(-33.915, 18.48, -33.76, 18.56), (-33.965, 18.56, -33.74, 18.80)]
SUBURB_CENTRES = {
    "Durbanville": (-33.832, 18.648), "Bellville": (-33.900, 18.630), "Tyger Valley": (-33.874, 18.634),
    "Brackenfell": (-33.873, 18.693), "Kraaifontein": (-33.847, 18.718), "Kuils River": (-33.924, 18.685),
    "Parow": (-33.900, 18.590), "Goodwood": (-33.909, 18.553), "Milnerton": (-33.875, 18.497),
    "Century City": (-33.890, 18.512), "Edgemead": (-33.873, 18.545), "Bothasig": (-33.857, 18.540),
    "Plattekloof": (-33.868, 18.583), "Panorama": (-33.879, 18.578), "Welgemoed": (-33.872, 18.618),
    "Sonstraal": (-33.840, 18.672), "Protea Heights": (-33.851, 18.680), "Belhar": (-33.940, 18.626),
    "Eversdal": (-33.855, 18.632), "Bloubergrant": (-33.805, 18.540), "Monte Vista": (-33.885, 18.553),
    "Burgundy Estate": (-33.840, 18.552), "Fisantekraal": (-33.780, 18.725), "Blue Downs": (-33.995, 18.700),
}
CHAIN_DOMAINS = re.compile(
    r"panarottis|spur\.co|oceanbasket|wimpy|debonairs|steers|nandos|kfc\.|mcdonalds|muggandbean|colcacchio|"
    r"rocomamas|johndorys|fishaways|burgerking|romanspizza|pizzahut|dominos|starbucks|vidaecaffe|seattle|"
    r"newscafe|cappello|primi|tashas|kauai|simplyasia|chickenlicken|hungrylion|galitos|famousbrands|"
    r"ninosonline|europa|sausage-saloon|hussar|bossa|turn-n-tender|beefmaster|piatto", re.I)


def in_area(b: dict) -> bool:
    if b.get("lat") is None or b.get("lng") is None:
        return b.get("found_via") == "Google Maps"  # kit rows came from northern-suburbs searches
    return any(s <= b["lat"] <= n and w <= b["lng"] <= e for s, w, n, e in AREA)


def nearest_suburb(lat: float, lng: float) -> Optional[str]:
    import math
    best, best_km = None, 99.0
    for name, (y, x) in SUBURB_CENTRES.items():
        km = math.hypot((lat - y) * 111, (lng - x) * 92)
        if km < best_km:
            best, best_km = name, km
    return best if best_km <= 6 else None


# ---------------------------------------------------------------- reading specials
_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_DAY_HEAD = re.compile(r"^(" + "|".join(_DAY_NAMES) + r")s?\b[\s:–-]*(.*)$", re.I)
_PRICE = re.compile(r"(?<![A-Za-z\d])R\s?(\d{2,4})(?:[.,]\d{2})?(?!\d|\s*[Oo][Ff][Ff])")
_JUNK = re.compile(r"add to (?:cart|basket)|website by|designed by|copyright|©|all rights|@\w|https?://|www\.|"
                   r"\bsku\b|out of stock|read more|view (?:menu|more)|sign up|log ?in|^\d+\.\s", re.I)
EXTRA_NOT_DEAL = re.compile(r"only availab|subject to|rental|hire\b|per person deposit|tickets?\b|"
                            r"\bcourse\b|class\b|workshop|function|wedding|year[- ]end", re.I)


def _clean_md(ln: str) -> str:
    ln = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", ln)            # images: drop
    ln = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", ln)          # links: keep text
    ln = re.sub(r"[*_`#>|]+", " ", ln)
    return re.sub(r"\s+", " ", ln).strip(" -•·:")


def _words(ln: str) -> int:
    return len(re.findall(r"[A-Za-z]{2,}", ln))


def rule_specials(text: str) -> list[dict]:
    """Free pattern rules. A line counts as a special when it reads like an offer:
    - under a day heading (within 3 lines), with a price or offer words, or
    - anywhere, with clear offer words (special, half price, 2 for 1, % off, happy hour…)."""
    out, seen = [], set()
    day, since_day = None, 99
    for raw in text.splitlines():
        ln = _clean_md(raw)
        if not ln:
            continue
        m = _DAY_HEAD.match(ln)
        if m:
            day, since_day = m.group(1).capitalize(), 0
            ln = m.group(2).strip(" :-–")
            if not ln:
                continue
        else:
            since_day += 1
        if since_day > 3:
            day = None
        if not (8 <= len(ln) <= 160) or _words(ln) < (2 if day else 3) or _JUNK.search(ln):
            continue
        if NOT_A_DEAL.search(ln) or EXTRA_NOT_DEAL.search(ln):
            continue
        offer = SPECIAL_LINE.search(ln)
        price = _PRICE.search(ln)
        inline = next((x for x in _DAY_NAMES if re.search(rf"\b{x}s?\b", ln, re.I)), None)
        if not (offer or ((day or inline) and price)):
            continue
        if not offer and not re.search(r"\band\b|\bwith\b|\+|&|\bor\b|\bany\b|\ball\b|\bfree\b|\bincl", ln, re.I):
            continue  # a dish name and a price is a menu line, not a special
        d = inline or day
        if re.search(r"every ?day|daily|7 days", ln, re.I):
            d = "Daily"
        key = re.sub(r"\W+", " ", ln.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        val = float(price.group(1)) if price else None
        out.append({"day": d, "text": ln[:140], "price": val if val and 10 <= val <= 3000 else None})
    return out[:8]


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
        if not site or SKIP_DOMAINS.search(site) or CHAIN_DOMAINS.search(site) or not in_area(b):
            continue
        k = site_key(site)
        if not k:
            continue
        rec = known.setdefault(k, {"checked": None})
        for f in ("name", "website", "category", "kind", "suburb", "address", "lat", "lng", "found_via"):
            if b.get(f) not in (None, "") and (rec.get(f) in (None, "") or f in ("lat", "lng") and b["found_via"] == "Google Maps"):
                rec[f] = b[f]
    for k in [k for k, r in known.items() if not in_area(r) or CHAIN_DOMAINS.search(r.get("website", ""))]:
        del known[k]  # outside the northern suburbs (area rules may have changed)
    northern = set(SUBURB_CENTRES)
    for r in known.values():
        if r.get("lat") is not None and r.get("suburb") not in northern:
            r["suburb"] = nearest_suburb(r["lat"], r["lng"]) or r.get("suburb")
    if os.environ.get("RECHECK_ALL") == "1":
        for r in known.values():
            r["checked"] = None
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
