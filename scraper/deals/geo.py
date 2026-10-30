"""Locations for deals, from OpenStreetMap (free, no key).

* Nominatim geocodes restaurant/shop addresses (max 1 request/second, results cached).
* Overpass lists chain branches (Pick n Pay, Woolworths, Clicks) so the app can show
  the distance to your nearest branch.
Both are cached inside history.json so daily runs barely touch the services.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from .http import Http

log = logging.getLogger(__name__)
UA = "NorthernDeals/1.0 (+https://github.com/hj367/northern-deals)"
# Cape Town northern suburbs, generously: Milnerton/Century City to Kraaifontein/Kuils River
BBOX = (-33.98, 18.45, -33.74, 18.80)   # south, west, north, east
CHAIN_PATTERNS = {"Pick n Pay": "pick n pay", "Woolworths": "woolworths", "Clicks": "clicks"}


class Geo:
    def __init__(self, cache: dict, today: str):
        self.cache = cache                     # lives in history.json
        self.points = cache.setdefault("points", {})
        self.today = today
        self.http = Http(min_delay=1.1, max_delay=1.5)
        self.http.s.headers["User-Agent"] = UA
        self.lookups = 0

    def point(self, query: str) -> Optional[list[float]]:
        key = query.strip().lower()
        hit = self.points.get(key)
        if hit is not None:
            if hit.get("ll") or hit.get("checked", "") > _days_ago(self.today, 30):
                return hit.get("ll")
        if self.lookups >= 60:          # stay well inside Nominatim's usage policy
            return None
        self.lookups += 1
        ll = None
        try:
            s, w, n, e = BBOX
            rows = self.http.get_json(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1, "countrycodes": "za",
                        "viewbox": f"{w - 0.15},{n + 0.1},{e + 0.15},{s - 0.15}", "bounded": 1},
                retries=1,
            )
            if rows:
                ll = [round(float(rows[0]["lat"]), 5), round(float(rows[0]["lon"]), 5)]
        except Exception as ex:
            log.warning("geocode failed for %r: %s", query, ex)
            return None
        self.points[key] = {"ll": ll, "checked": self.today}
        return ll

    def locate(self, address: Optional[str], suburb: Optional[str], name: Optional[str] = None) -> Optional[list[float]]:
        """Most precise first: name+address, address, then the suburb's centre."""
        tries = []
        if name and address:
            tries.append(f"{name}, {address}")
        if address:
            tries.append(f"{address}, Cape Town")
        if suburb:
            tries.append(f"{suburb}, Cape Town")
        for q in tries:
            ll = self.point(q)
            if ll:
                return ll
        return None

    def chain_branches(self) -> dict[str, list]:
        """{store: [[lat, lng, name], ...]} for branches in/near the northern suburbs; refreshed weekly."""
        cached = self.cache.get("branches")
        if cached and cached.get("checked", "") > _days_ago(self.today, 7):
            return cached["stores"]
        s, w, n, e = BBOX
        q = f"""[out:json][timeout:90];
(nwr["brand"~"pick n pay|woolworths|clicks",i]({s},{w},{n},{e});
 nwr["name"~"^(pick n pay|woolworths|clicks)",i]["shop"]({s},{w},{n},{e}););
out center tags;"""
        try:
            data = self.http.post("https://overpass-api.de/api/interpreter", data={"data": q},
                                  timeout=120, retries=1).json()
        except Exception as ex:
            log.warning("Overpass failed: %s", ex)
            return cached["stores"] if cached else {}
        stores: dict[str, list] = {k: [] for k in CHAIN_PATTERNS}
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            label = f"{tags.get('brand', '')} {tags.get('name', '')}".lower()
            if tags.get("shop") in ("clothes", "shoes", "fashion", "boutique") or "clothing" in label:
                continue  # Woolworths/PnP clothing-only stores don't carry the specials
            lat = el.get("lat") or el.get("center", {}).get("lat")
            lng = el.get("lon") or el.get("center", {}).get("lon")
            if lat is None or lng is None:
                continue
            for store, pat in CHAIN_PATTERNS.items():
                if pat in label:
                    stores[store].append([round(lat, 5), round(lng, 5), tags.get("name") or store])
                    break
        self.cache["branches"] = {"checked": self.today, "stores": stores}
        return stores


def _days_ago(today: str, n: int) -> str:
    return (date.fromisoformat(today) - timedelta(days=n)).isoformat()
