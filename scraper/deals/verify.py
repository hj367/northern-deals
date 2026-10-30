"""Decide whether a special is actually a good deal.

Grocery/retail deals are judged on four things:
  1. Is the store's "was" price honest? (Was it really charged, recently, for a while?)
  2. Is today's price clearly below what this product usually costs?
  3. Is it the lowest price we've seen in 90 days?
  4. Is it cheaper than the same product at the other stores today?

Restaurant specials can't be price-checked the same way, so they're judged on
how recently they were published/confirmed and whether more than one source
lists them.
"""
from __future__ import annotations

import re
import statistics
from datetime import date
from typing import Optional

from .models import ProductObs, RestaurantSpecial

MIN_HISTORY_DAYS = 14        # need this much history before judging "was" prices
MIN_DAYS_AT_WAS = 7          # a real "was" price was charged for at least a week

_MULTI_RE = re.compile(r"\b(?:(?:buy|any)\s*)?(\d+)\s*(?:for|at)\s*(?:R\s?(\d+(?:[.,]\d{1,2})?)|(\d{2,5}(?:[.,]\d{1,2})?)\b)", re.I)
_CHEAPEST_FREE_RE = re.compile(r"\b(?:buy\s*)?(?:any\s*)?(\d)\b.{0,60}?cheapest\s*(?:1|one)?\s*free", re.I)
_SAVE_PCT_RE = re.compile(r"\b(?:buy|any)\s*(?:any\s*)?(\d+)\s*(?:and\s*)?(?:or more\s*(?:and\s*)?)?save\s*(\d{1,2})\s*%", re.I)
_SECOND_RE = re.compile(r"(\d{1,3})\s*%\s*off\s*(?:the\s*)?2nd|2nd\s*(?:one\s*)?(?:at\s*)?half[- ]price|(\d{1,3})%\s*off.{0,20}second", re.I)
_X_FOR_Y_RE = re.compile(r"\b([2-5])\s*for\s*([1-4])\b", re.I)
_SAVE_RE = re.compile(r"\bsave\s*R\s?(\d+(?:[.,]\d{1,2})?)", re.I)


def effective_price(p: ProductObs) -> tuple[float, Optional[str]]:
    """Lowest per-item price available, and what you have to do to get it."""
    best, how = p.price, None
    if p.promo_text:
        m = _MULTI_RE.search(p.promo_text)
        if m:
            n, total = int(m.group(1)), float((m.group(2) or m.group(3)).replace(",", "."))
            if n > 1 and total / n < best:
                best, how = round(total / n, 2), f"when you buy {n}"
        m = _CHEAPEST_FREE_RE.search(p.promo_text)
        if m and int(m.group(1)) > 1:
            n = int(m.group(1))
            eff = round(p.price * (n - 1) / n, 2)
            if eff < best:
                best, how = eff, f"when you buy {n}"
        m = _SAVE_PCT_RE.search(p.promo_text)
        if m and p.price * (1 - int(m.group(2)) / 100) < best:
            best, how = round(p.price * (1 - int(m.group(2)) / 100), 2), f"when you buy {m.group(1)}"
        m = _SECOND_RE.search(p.promo_text)
        if m:
            pct = int(m.group(1) or m.group(2) or 50)
            eff = round(p.price * (1 - pct / 200), 2)
            if eff < best:
                best, how = eff, "when you buy 2"
        m = _X_FOR_Y_RE.search(p.promo_text)
        if m and int(m.group(2)) < int(m.group(1)):
            eff = round(p.price * int(m.group(2)) / int(m.group(1)), 2)
            if eff < best:
                best, how = eff, f"when you buy {m.group(1)}"
    if p.member_price and p.member_price < best:
        best, how = p.member_price, "with the store's loyalty card"
    return best, how


def verify_product(p: ProductObs, history: list[list], others: list[ProductObs], today: str) -> dict:
    eff, condition = effective_price(p)
    reasons: list[dict] = []   # {"ok": True/False/None, "text": ...}
    score = 50
    fake_was = False

    hist_prices = [o[1] for o in history if o[1]]
    hist_days = len({o[0] for o in history})
    enough = hist_days >= MIN_HISTORY_DAYS

    # 1. Claimed discount vs real history
    claimed_pct = None
    if p.was_price and p.was_price > p.price:
        claimed_pct = round(100 * (p.was_price - p.price) / p.was_price)
        if enough:
            highest = max(hist_prices)
            days_at_was = len({o[0] for o in history if o[1] >= p.was_price * 0.98})
            if p.was_price > highest * 1.02:
                fake_was = True
                score -= 40
                reasons.append(_r(False, f"'Was R{p.was_price:.2f}' never seen in {hist_days} days of tracking "
                                         f"(highest was R{highest:.2f}) — inflated discount"))
            elif days_at_was < MIN_DAYS_AT_WAS:
                score -= 15
                reasons.append(_r(False, f"'Was' price was only charged on {days_at_was} of the last {hist_days} days"))
            else:
                score += 15
                reasons.append(_r(True, f"'Was R{p.was_price:.2f}' is genuine — charged on {days_at_was} days recently"))
        else:
            reasons.append(_r(None, f"Store claims {claimed_pct}% off; still building price history to check the 'was' price"))

    # 2 + 3. Compared with its own usual price
    usual = None
    if hist_prices and hist_days >= 3:
        usual = statistics.median(hist_prices)
        drop = (usual - eff) / usual
        if drop >= 0.10:
            score += 20
            reasons.append(_r(True, f"{round(drop * 100)}% below its usual R{usual:.2f}"))
        elif drop >= 0.03:
            score += 5
            reasons.append(_r(None, f"Only {round(drop * 100)}% below its usual R{usual:.2f}"))
        else:
            score -= 20
            reasons.append(_r(False, f"Not cheaper than usual (normally R{usual:.2f})"))
        if enough and eff <= min(hist_prices) + 0.005:
            score += 10
            reasons.append(_r(True, f"Lowest price in {hist_days} days"))

    # 4. Cross-store comparison (same product, same size, today)
    cheapest_elsewhere = None
    if others:
        o_eff = sorted(((effective_price(o)[0], o) for o in others), key=lambda x: x[0])
        best_o, best_store = o_eff[0][0], o_eff[0][1]
        cheapest_elsewhere = {"store": best_store.store, "price": best_o, "url": best_store.url}
        if eff < best_o * 0.98:
            score += 15
            reasons.append(_r(True, f"Cheapest of {len(others) + 1} stores (next best R{best_o:.2f} at {best_store.store})"))
        elif eff <= best_o * 1.02:
            score += 3
            reasons.append(_r(None, f"Same price as {best_store.store}"))
        else:
            score -= 15
            reasons.append(_r(False, f"R{eff - best_o:.2f} cheaper at {best_store.store} (R{best_o:.2f})"))

    if condition:
        reasons.append(_r(None, f"Price R{eff:.2f} applies {condition}"))

    has_evidence = (hist_days >= 3) or bool(others)
    if fake_was:
        verdict = "fake"
    elif not has_evidence:
        verdict = "unverified"
        reasons.append(_r(None, "New to the tracker — no history or other-store match yet"))
    elif score >= 75:
        verdict = "real"
    elif score >= 58:
        verdict = "good"
    else:
        verdict = "weak"

    return {
        "verdict": verdict,
        "score": max(0, min(100, score)),
        "effective_price": eff,
        "condition": condition,
        "claimed_discount_pct": claimed_pct,
        "usual_price": round(usual, 2) if usual else None,
        "history_days": hist_days,
        "cheapest_elsewhere": cheapest_elsewhere,
        "reasons": reasons,
    }


def verify_special(s: RestaurantSpecial, rec: dict, corroborating_sources: int, today: str) -> dict:
    reasons: list[dict] = []
    last = max(filter(None, [s.modified, s.published])) if (s.modified or s.published) else None
    age = (date.fromisoformat(today) - date.fromisoformat(last)).days if last else None

    if s.own_site:
        verdict = "verified"
        reasons.append(_r(True, f"On {s.restaurant}'s own website today"))
        if s.poster and last:
            reasons.append(_r(None, f"From their specials poster, uploaded {_ago(age)}"))
    elif age is None:
        verdict = "unverified"
        reasons.append(_r(None, "No publish date — check with the restaurant"))
    elif age <= 45:
        verdict = "verified"
        reasons.append(_r(True, f"Published/updated {_ago(age)}"))
    elif age <= 150:
        verdict = "likely"
        reasons.append(_r(None, f"Last updated {_ago(age)} — probably still on, worth a quick call"))
    else:
        verdict = "outdated"
        reasons.append(_r(False, f"Last updated {_ago(age)} — likely ended or changed"))

    if corroborating_sources >= 2:
        reasons.append(_r(True, f"Listed by {corroborating_sources} different sites"))
        if verdict == "likely":
            verdict = "verified"
    if s.price:
        reasons.append(_r(True, f"Fixed price R{s.price:.0f} stated"))
    else:
        reasons.append(_r(None, "No price stated in the listing"))
    if not s.days:
        reasons.append(_r(None, "Days not stated"))

    return {"verdict": verdict, "age_days": age, "reasons": reasons,
            "first_seen": rec.get("first_seen"), "sources": rec.get("sources", [])}


def _r(ok: Optional[bool], text: str) -> dict:
    return {"ok": ok, "text": text}


def _ago(days: int) -> str:
    if days <= 1:
        return "today" if days <= 0 else "yesterday"
    if days < 60:
        return f"{days} days ago"
    if days < 730:
        return f"{days // 30} months ago"
    return f"{days // 365} years ago"
