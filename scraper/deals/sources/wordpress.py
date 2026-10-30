"""Restaurant specials from WordPress food sites (WP REST API, HTML fallback)."""
from __future__ import annotations

import html as htmllib
import logging
import re
from typing import Optional

from bs4 import BeautifulSoup

from ..http import Http
from ..models import RestaurantSpecial, parse_rand
from .retail import SourceResult

log = logging.getLogger(__name__)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
NON_FOOD = re.compile(r"\b(wine tasting only|accommodation|bootcamp|competition|win a|giveaway)\b", re.I)


def scrape_wordpress(cfg: dict, http: Http, suburbs: list[str]) -> SourceResult:
    res = SourceResult(name=cfg["source"], ok=False, method="wp-rest")
    base = cfg["base"].rstrip("/")
    posts: dict[int, dict] = {}
    try:
        tag_ids: set[int] = set()
        for term in cfg.get("tag_search", []):
            for t in http.get_json(f"{base}/wp-json/wp/v2/tags", params={"search": term, "per_page": 100}):
                tag_ids.add(t["id"])
        fields = "id,date,modified,link,title,content,excerpt,tags,jetpack_featured_media_url"
        if tag_ids:
            ids = sorted(tag_ids)
            for i in range(0, len(ids), 40):  # keep query strings short
                for page in range(1, 4):
                    batch = http.get_json(
                        f"{base}/wp-json/wp/v2/posts",
                        params={"tags": ",".join(map(str, ids[i:i + 40])), "per_page": 50,
                                "page": page, "orderby": "modified", "_fields": fields},
                    )
                    for p in batch:
                        posts[p["id"]] = p
                    if len(batch) < 50 or len(posts) >= cfg.get("max_posts", 100):
                        break
        for q in cfg.get("search", []):
            for p in http.get_json(f"{base}/wp-json/wp/v2/posts",
                                   params={"search": q, "per_page": 30, "_fields": fields}):
                posts[p["id"]] = p
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
        log.warning("%s REST failed: %s", cfg["source"], res.error)

    for p in list(posts.values())[: cfg.get("max_posts", 100)]:
        sp = special_from_post(p, cfg["source"], suburbs)
        if sp:
            res.items.append(sp)
    res.ok = bool(res.items)
    if not res.ok and not res.error:
        res.error = "No northern-suburbs specials recognised in posts."
    return res


def special_from_post(p: dict, source: str, suburbs: list[str]) -> Optional[RestaurantSpecial]:
    title = _clean(p.get("title", {}).get("rendered", ""))
    content_html = p.get("content", {}).get("rendered", "") or ""
    soup = BeautifulSoup(content_html, "html.parser")
    text = soup.get_text("\n", strip=True)
    full = f"{title}\n{text}"
    if NON_FOOD.search(title):
        return None

    suburb = find_suburb(full, suburbs)
    if not suburb:
        return None  # not in the northern suburbs

    price = _price_from(title) or _price_from(text)
    days = [d for d in DAYS if re.search(rf"\b{d}s?\b", full, re.I)]
    if re.search(r"\b(every ?day|daily|7 days)\b", full, re.I):
        days = ["Daily"]

    img = p.get("jetpack_featured_media_url") or None
    if not img:
        im = soup.find("img")
        img = im.get("src") if im else None

    return RestaurantSpecial(
        title=title,
        restaurant=restaurant_from(title, text),
        suburb=suburb,
        price=price,
        days=days,
        source=source,
        url=p.get("link", ""),
        published=(p.get("date") or "")[:10] or None,
        modified=(p.get("modified") or "")[:10] or None,
        summary=_summary(p, text),
        image=img,
        address=_address(text),
    )


def find_suburb(text: str, suburbs: list[str]) -> Optional[str]:
    hits = []
    for s in suburbs:
        m = re.search(rf"\b{re.escape(s)}\b", text, re.I)
        if m:
            hits.append((m.start(), s))
    if not hits:
        return None
    s = min(hits)[1]
    return {"Tygervalley": "Tyger Valley", "Tyger Waterfront": "Bellville"}.get(s, s)


def _price_from(text: str) -> Optional[float]:
    m = re.search(r"\bR\s?\d{2,4}(?:[.,]\d{2})?\b", text)
    return parse_rand(m.group(0)) if m else None


_AT_RE = re.compile(r"\b(?:at|@)\s+(?:the\s+)?([A-Z][\w'&.\- ]{2,40}?)(?:\s+(?:in|on|this|every|for|with|until|from)\b|[!,.:]|$)")


def restaurant_from(title: str, text: str) -> Optional[str]:
    m = _AT_RE.search(title)
    if m:
        return m.group(1).strip()
    m = re.search(r"Directions to\s+(.{2,50})", text)
    if m:
        return m.group(1).split("\n")[0].strip()
    return None


def _address(text: str) -> Optional[str]:
    m = re.search(r"Directions to[^\n]*\n((?:[^\n]+\n){1,4})", text)
    if not m:
        return None
    lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip() and not re.match(r"^[\d +()]{9,}$", ln)]
    return ", ".join(lines[:3]) or None


def _summary(p: dict, text: str) -> str:
    ex = _clean(p.get("excerpt", {}).get("rendered", "")) if p.get("excerpt") else ""
    s = ex or text
    s = re.sub(r"\s+", " ", s)
    return (s[:220] + "…") if len(s) > 220 else s


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
