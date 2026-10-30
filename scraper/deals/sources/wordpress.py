"""Restaurant specials from WordPress food sites (WP REST API, RSS fallback)."""
from __future__ import annotations

import html as htmllib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Optional

from bs4 import BeautifulSoup

from ..http import Http
from ..models import RestaurantSpecial, parse_rand
from .retail import SourceResult

log = logging.getLogger(__name__)

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
# Posts that aren't a meal/drink special someone can walk in and get.
NOT_A_SPECIAL = re.compile(
    r"\b(cooking class|class|course|workshop|competition|win a|giveaway|accommodation|bootcamp|"
    r"christmas (?:lunch|lunches|dinner|dinners|day)|new year|nye|festival|market|wedding|function|"
    r"recipe|review|opening|opens|launch|things to do|guide to|best .{0,30} in cape town|"
    r"restaurants? in cape town|where to)\b",
    re.I,
)
SPECIAL_WORDS = re.compile(
    r"\b(special|for only|only R|\d+% off|half[- ]price|two[- ]for[- ]one|2[- ]for[- ]1|bottomless|"
    r"happy hour|free|R\s?\d{2,4})\b",
    re.I,
)


def scrape_wordpress(cfg: dict, http: Http, suburbs: list[str], today: Optional[str] = None) -> SourceResult:
    res = SourceResult(name=cfg["source"], ok=False, method="wp-rest")
    base = cfg["base"].rstrip("/")
    today_d = date.fromisoformat(today) if today else date.today()
    since = (today_d - timedelta(days=cfg.get("since_days", 150))).isoformat() + "T00:00:00"
    posts: dict[str, dict] = {}
    suburb_tag_ids: set[int] = set()
    try:
        tag_ids: set[int] = set()
        for term in cfg.get("tag_search", []):
            for t in http.get_json(f"{base}/wp-json/wp/v2/tags", params={"search": term, "per_page": 100}):
                tag_ids.add(t["id"])
                if any(s.lower() in t.get("name", "").lower() for s in suburbs) or "northern" in t.get("name", "").lower():
                    suburb_tag_ids.add(t["id"])
        fields = "id,date,modified,link,title,content,excerpt,tags,jetpack_featured_media_url"
        ids = sorted(tag_ids)
        for i in range(0, len(ids), 40):
            for page in range(1, 6):
                batch = http.get_json(
                    f"{base}/wp-json/wp/v2/posts",
                    params={"tags": ",".join(map(str, ids[i:i + 40])), "per_page": 50, "page": page,
                            "after": since, "orderby": "date", "_fields": fields},
                )
                for p in batch:
                    posts[str(p["id"])] = p
                if len(batch) < 50:
                    break
        for q in cfg.get("search", []):
            for p in http.get_json(f"{base}/wp-json/wp/v2/posts",
                                   params={"search": q, "per_page": 50, "after": since, "_fields": fields}):
                posts[str(p["id"])] = p
    except Exception as e:
        res.error = f"REST: {type(e).__name__}: {e}"
        log.warning("%s REST failed (%s), trying RSS", cfg["source"], e)
        try:
            for p in rss_posts(cfg, http, base):
                if (p.get("date") or "") >= since[:10]:
                    posts[p["link"]] = p
            res.method = "rss"
        except Exception as e2:
            res.error += f" | RSS: {type(e2).__name__}: {e2}"

    for p in list(posts.values())[: cfg.get("max_posts", 150)]:
        tagged = bool(suburb_tag_ids & set(p.get("tags") or []))
        sp = special_from_post(p, cfg["source"], suburbs, tagged_northern=tagged)
        if sp:
            res.items.append(sp)
    res.ok = bool(res.items)
    if res.ok:
        res.error = ""
    elif not res.error:
        res.error = f"No northern-suburbs specials in {len(posts)} recent posts."
    return res


def rss_posts(cfg: dict, http: Http, base: str) -> list[dict]:
    """WordPress RSS search feeds, shaped like REST posts."""
    out = []
    for q in cfg.get("search", []) + cfg.get("tag_search", []):
        xml = http.get_text(f"{base}/", params={"s": q, "feed": "rss2"}, retries=0)
        root = ET.fromstring(xml.encode("utf-8", "ignore"))
        ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
        for it in root.iter("item"):
            pub = it.findtext("pubDate")
            try:
                d = parsedate_to_datetime(pub).date().isoformat() if pub else None
            except Exception:
                d = None
            content = it.findtext("content:encoded", default="", namespaces=ns) or it.findtext("description", "")
            out.append({
                "date": d, "modified": d, "link": it.findtext("link", ""),
                "title": {"rendered": it.findtext("title", "")},
                "content": {"rendered": content},
                "excerpt": {"rendered": it.findtext("description", "")},
            })
    return out


def special_from_post(p: dict, source: str, suburbs: list[str], tagged_northern: bool = False) -> Optional[RestaurantSpecial]:
    title = _clean(p.get("title", {}).get("rendered", ""))
    content_html = p.get("content", {}).get("rendered", "") or ""
    soup = BeautifulSoup(content_html, "html.parser")
    text = soup.get_text("\n", strip=True)
    if NOT_A_SPECIAL.search(title) or not SPECIAL_WORDS.search(f"{title}\n{text[:1500]}"):
        return None

    # Where is it? Trust the title, the address block, or a suburb tag — not a passing mention.
    address = _address(text)
    suburb = find_suburb(title, suburbs) or find_suburb(address or "", suburbs)
    if not suburb and tagged_northern:
        suburb = find_suburb(text, suburbs)
    if not suburb:
        return None

    price = _price_from(title) or _price_from(text)
    full = f"{title}\n{text}"
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
        address=address,
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
    m = re.search(r"(?:Directions to|Location:|Address:)[^\n]*\n?((?:[^\n]+\n?){1,4})", text)
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
