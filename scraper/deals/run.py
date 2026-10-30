"""Daily run: scrape -> record history -> verify -> write deals.json.

    python -m deals.run --data ../data            # live scrape
    python -m deals.run --data ../data --only Checkers,FoodBlogCT
"""
from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .history import History
from .http import Http
from .match import group_same_products
from .models import ProductObs, RestaurantSpecial, norm_text
from .sources.retail import SourceResult, scrape_retail
from .geo import Geo
from .sources.restaurant_site import scrape_restaurant_site
from .sources.shops import scrape_shop
from .sources.wordpress import scrape_wordpress
from .verify import verify_product, verify_special

log = logging.getLogger("deals")
HERE = Path(__file__).resolve().parent.parent
SA = ZoneInfo("Africa/Johannesburg")


def build_output(products: list[ProductObs], specials: list[RestaurantSpecial], hist: History,
                 health: list[dict], today: str, branches: dict | None = None) -> dict:
    # --- record today's prices first, then judge against the days before today
    for p in products:
        hist.record(p, today)

    groups = group_same_products(products)
    others_of: dict[str, list[ProductObs]] = defaultdict(list)
    for g in groups:
        for p in g:
            others_of[p.key] = [o for o in g if o.store != p.store]

    grocery = []
    for p in products:
        series = hist.series(p.key, before=today)
        v = verify_product(p, series, others_of.get(p.key, []), today)
        usual = v["usual_price"]
        silent_drop = usual and v["effective_price"] <= usual * 0.9
        if not (p.on_promo or silent_drop):
            continue  # not presented as a deal and not actually cheaper -> skip
        d = p.to_dict()
        d.update(v)
        d["history"] = [[o[0], o[1]] for o in hist.series(p.key, days=90)]  # incl. today
        grocery.append(d)

    order = {"real": 0, "good": 1, "unverified": 2, "weak": 3, "fake": 4}
    grocery.sort(key=lambda d: (order[d["verdict"]], -d["score"],
                                -(d.get("claimed_discount_pct") or 0)))

    # --- restaurants: dedupe across sources, count corroboration
    by_rest: dict[str, set[str]] = defaultdict(set)
    for s in specials:
        if s.restaurant:
            by_rest[norm_text(s.restaurant)].add(s.source)
    rest_out, seen = [], set()
    for s in specials:
        if s.key in seen:
            continue
        seen.add(s.key)
        rec = hist.record_special(s, today)
        corr = len(by_rest.get(norm_text(s.restaurant or ""), {s.source}))
        d = s.to_dict()
        d.update(verify_special(s, rec, corr, today))
        rest_out.append(d)
    rorder = {"verified": 0, "likely": 1, "unverified": 2, "outdated": 3}
    rest_out.sort(key=lambda d: (rorder[d["verdict"]], d.get("age_days") or 9999))

    hist.prune(today)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "region": "Cape Town Northern Suburbs",
        "date": today,
        "counts": {
            "grocery": len(grocery),
            "grocery_real": sum(d["verdict"] == "real" for d in grocery),
            "grocery_fake": sum(d["verdict"] == "fake" for d in grocery),
            "restaurants": len(rest_out),
            "products_tracked": len(hist.products),
        },
        "sources": health,
        "branches": branches or {},
        "grocery": grocery,
        "restaurants": rest_out,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE.parent / "data"), help="folder with history.json; deals.json is written here")
    ap.add_argument("--config", default=str(HERE / "sources.json"))
    ap.add_argument("--only", default="", help="comma-separated source names")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = json.loads(Path(args.config).read_text())
    only = {s.strip().lower() for s in args.only.split(",") if s.strip()}
    data_dir = Path(args.data)
    hist = History.load(data_dir / "history.json")
    today = datetime.now(SA).date().isoformat()
    http = Http()

    products: list[ProductObs] = []
    specials: list[RestaurantSpecial] = []
    results: list[SourceResult] = []
    for rc in cfg["retail"]:
        if only and rc["store"].lower() not in only:
            continue
        r = scrape_retail(rc, http)
        results.append(r)
        products += r.items
    for sc in cfg.get("shops", []):
        if only and sc["name"].lower() not in only:
            continue
        r = scrape_shop(sc, http)
        results.append(r)
        products += r.items
    for wc in cfg["restaurants"]:
        if only and wc["source"].lower() not in only:
            continue
        r = scrape_wordpress(wc, http, cfg["suburbs"], today)
        results.append(r)
        specials += r.items
    for rs in cfg.get("restaurant_sites", []):
        if only and rs["name"].lower() not in only:
            continue
        r = scrape_restaurant_site(rs, http)
        results.append(r)
        specials += r.items

    # --- locations (OpenStreetMap; cached in history.json)
    geo = Geo(hist.geo, today)
    shop_cfg = {c["name"]: c for c in cfg.get("shops", [])}
    shop_ll: dict[str, list | None] = {}
    for p in products:
        if p.local:
            if p.store not in shop_ll:
                c = shop_cfg.get(p.store, {})
                shop_ll[p.store] = geo.locate(c.get("address"), c.get("suburb"), p.store)
            if shop_ll[p.store]:
                p.lat, p.lng = shop_ll[p.store]
    for s in specials:
        ll = geo.locate(s.address, s.suburb, s.restaurant)
        if ll:
            s.lat, s.lng = ll
    branches = geo.chain_branches()
    log.info("geocoded with %d new lookups; branches: %s", geo.lookups, {k: len(v) for k, v in branches.items()})

    health = [r.health() for r in results]
    out = build_output(products, specials, hist, health, today, branches)

    data_dir.mkdir(parents=True, exist_ok=True)
    hist.save(data_dir / "history.json")
    (data_dir / "deals.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    for h in health:
        log.info("SOURCE %-14s ok=%-5s items=%-4d via=%s %s", h["source"], h["ok"], h["count"], h["method"], h["error"])
    log.info("Wrote %d grocery deals (%d real, %d fake) and %d restaurant specials",
             out["counts"]["grocery"], out["counts"]["grocery_real"], out["counts"]["grocery_fake"],
             out["counts"]["restaurants"])
    # Fail the workflow only if *everything* failed, so one broken store doesn't block the rest.
    return 0 if any(h["ok"] for h in health) else 1


if __name__ == "__main__":
    raise SystemExit(main())
