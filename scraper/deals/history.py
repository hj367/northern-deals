"""Price history kept as one compact JSON file (lives in the data repo)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .models import ProductObs, RestaurantSpecial

KEEP_DAYS = 180


class History:
    def __init__(self, data: dict | None = None):
        data = data or {}
        self.products: dict[str, dict] = data.get("products", {})
        self.restaurants: dict[str, dict] = data.get("restaurants", {})
        self.geo: dict = data.get("geo", {})

    # ---------- io ----------
    @classmethod
    def load(cls, path: Path) -> "History":
        if path.exists():
            return cls(json.loads(path.read_text()))
        return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"version": 1, "products": self.products, "restaurants": self.restaurants, "geo": self.geo},
            separators=(",", ":"), ensure_ascii=False,
        ))

    # ---------- products ----------
    def record(self, p: ProductObs, day: str) -> None:
        rec = self.products.setdefault(p.key, {"n": p.name, "s": p.store, "obs": []})
        rec["n"] = p.name
        if p.barcode:
            rec["b"] = p.barcode
        obs = rec["obs"]
        row = [day, p.price, p.was_price, 1 if p.on_promo else 0]
        if obs and obs[-1][0] == day:
            obs[-1] = row          # re-run on the same day replaces
        else:
            obs.append(row)

    def series(self, key: str, before: str | None = None, days: int = 90) -> list[list]:
        """Observations for a product within `days`, excluding `before` (normally today)."""
        rec = self.products.get(key)
        if not rec:
            return []
        start = (date.fromisoformat(before) - timedelta(days=days)).isoformat() if before else "0000"
        return [o for o in rec["obs"] if o[0] >= start and (before is None or o[0] < before)]

    # ---------- restaurants ----------
    def record_special(self, s: RestaurantSpecial, day: str) -> dict:
        rec = self.restaurants.setdefault(s.key, {"first_seen": day, "sources": []})
        rec["last_seen"] = day
        if s.source not in rec["sources"]:
            rec["sources"].append(s.source)
        return rec

    # ---------- housekeeping ----------
    def prune(self, today: str) -> None:
        cutoff = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS)).isoformat()
        for k in list(self.products):
            obs = [o for o in self.products[k]["obs"] if o[0] >= cutoff]
            if obs:
                self.products[k]["obs"] = obs
            else:
                del self.products[k]
        for k in list(self.restaurants):
            if self.restaurants[k].get("last_seen", today) < cutoff:
                del self.restaurants[k]
