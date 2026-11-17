"""Optional: read specials with Google's Gemini free tier when GEMINI_API_KEY is set.

Without a key, the free pattern rules in ocr.parse_weekly_specials are used instead.
Get a free key (no card) at https://aistudio.google.com/apikey and add it as the repo
secret GEMINI_API_KEY. Only public restaurant/shop page text is sent.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger(__name__)
MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Daily"]

PROMPT = """You read a South African restaurant or shop web page and list its CURRENT specials/deals.
Only include real offers a customer can get (a reduced or fixed price, % off, 2-for-1, free item, happy hour,
kids eat free, set menu deal). Ignore normal menu items with normal prices, events, competitions,
gift vouchers, job adverts and anything clearly expired.
Return JSON: {"specials": [{"day": one of %s or null, "text": short description as written,
"price": number in rand or null, "valid_until": "YYYY-MM-DD" or null}]}. Return {"specials": []} if none.

Page: %s
---
%s"""

_calls = 0


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def extract_specials(page_text: str, url: str, http, max_chars: int = 12000) -> Optional[list[dict]]:
    """List of {"day","text","price","valid_until"}; None if the call failed (caller falls back to rules)."""
    global _calls
    key = os.environ.get("GEMINI_API_KEY")
    if not key or not page_text.strip():
        return None
    if _calls >= int(os.environ.get("GEMINI_MAX_CALLS", "200")):  # stay inside the free daily quota
        return None
    _calls += 1
    body = {
        "contents": [{"parts": [{"text": PROMPT % (DAYS, url, page_text[:max_chars])}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }
    for attempt in range(3):
        try:
            r = http.s.post(URL.format(model=MODEL), params={"key": key}, json=body, timeout=60)
            if r.status_code == 429:  # free-tier rate limit: wait and retry
                time.sleep(20 * (attempt + 1))
                continue
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(txt)
            out = []
            for s in data.get("specials", []) if isinstance(data, dict) else []:
                if not isinstance(s, dict) or not s.get("text"):
                    continue
                day = s.get("day") if s.get("day") in DAYS else None
                price = s.get("price")
                out.append({
                    "day": day,
                    "text": str(s["text"]).strip()[:140],
                    "price": float(price) if isinstance(price, (int, float)) and 5 <= price <= 5000 else None,
                    "valid_until": s.get("valid_until"),
                })
            return out
        except Exception as e:
            log.warning("Gemini extraction failed for %s: %s", url, str(e)[:120])
            time.sleep(3)
    return None
