"""Fetch web pages with Crawl4AI (real headless browser, so Wix/Squarespace/JS sites work).

Falls back to plain HTTP when Crawl4AI isn't installed, so tests and the daily scan
don't depend on a browser.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)
os.environ.setdefault("CRAWL4AI_NO_CLOUD_NOTICE", "1")


@dataclass
class Page:
    url: str
    ok: bool
    text: str = ""                                    # readable text / markdown
    links: list[tuple[str, str]] = field(default_factory=list)   # (absolute url, link text)
    images: list[tuple[str, str]] = field(default_factory=list)  # (absolute url, alt/title)
    html: str = ""
    error: str = ""


def fetch_pages(urls: list[str], concurrency: int = 4, timeout_s: int = 40) -> dict[str, Page]:
    urls = list(dict.fromkeys(u for u in urls if u))
    if not urls:
        return {}
    try:
        import crawl4ai  # noqa: F401
    except ImportError:
        return _fetch_plain(urls)
    return asyncio.run(_fetch_c4a(urls, concurrency, timeout_s))


async def _fetch_c4a(urls: list[str], concurrency: int, timeout_s: int) -> dict[str, Page]:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=timeout_s * 1000,
        wait_until="domcontentloaded",
        delay_before_return_html=1.5,       # let JS-built menus render
        remove_overlay_elements=True,
        remove_consent_popups=True,
        scan_full_page=True,                # lazy-loaded images (posters)
        max_scroll_steps=8,
        verbose=False,
    ) if _accepts(CrawlerRunConfig, "remove_consent_popups") else CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS, page_timeout=timeout_s * 1000, delay_before_return_html=1.5)
    out: dict[str, Page] = {}
    sem = asyncio.Semaphore(concurrency)
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as crawler:
        async def one(url: str) -> None:
            async with sem:
                try:
                    r = await asyncio.wait_for(crawler.arun(url, config=run_cfg), timeout_s + 30)
                except Exception as e:  # timeouts, DNS, TLS…
                    out[url] = Page(url, False, error=f"{type(e).__name__}: {str(e)[:120]}")
                    return
                if not getattr(r, "success", False):
                    out[url] = Page(url, False, error=str(getattr(r, "error_message", "failed"))[:160])
                    return
                base = getattr(r, "redirected_url", None) or getattr(r, "url", None) or url
                md = getattr(r, "markdown", "")
                text = getattr(md, "raw_markdown", None) or str(md or "")
                links = [(urljoin(base, x.get("href", "")), (x.get("text") or "").strip())
                         for x in (r.links or {}).get("internal", []) + (r.links or {}).get("external", [])
                         if x.get("href")]
                # Crawl4AI scores images and drops "unimportant" ones (often exactly the specials
                # poster), so read every image from the rendered HTML too.
                from_html = page_from_html(base, r.html or "") if r.html else Page(base, True)
                imgs = [(urljoin(base, i.get("src", "")), " ".join(filter(None, [i.get("alt"), i.get("desc")])))
                        for i in (r.media or {}).get("images", []) if i.get("src")]
                imgs = list(dict.fromkeys(imgs + from_html.images))
                links = list(dict.fromkeys(links + from_html.links))
                out[url] = Page(base, True, text=text or from_html.text, links=links, images=imgs, html=r.html or "")
        await asyncio.gather(*(one(u) for u in urls))
    return out


def _fetch_plain(urls: list[str]) -> dict[str, Page]:
    from .http import Http

    http = Http(min_delay=0.5, max_delay=1.0)
    out = {}
    for u in urls:
        try:
            html = http.get_text(u, retries=0)
        except Exception as e:
            out[u] = Page(u, False, error=f"{type(e).__name__}: {str(e)[:120]}")
            continue
        out[u] = page_from_html(u, html)
    return out


def page_from_html(url: str, html: str) -> Page:
    soup = BeautifulSoup(html, "html.parser")
    links = [(urljoin(url, a["href"]), a.get_text(" ", strip=True)) for a in soup.find_all("a", href=True)]
    imgs = [(urljoin(url, i.get("data-src") or i.get("src") or ""), " ".join(filter(None, [i.get("alt"), i.get("title")])))
            for i in soup.find_all("img") if i.get("data-src") or i.get("src")]
    for s in soup(["script", "style", "noscript"]):
        s.decompose()
    return Page(url, True, text=soup.get_text("\n", strip=True), links=links, images=imgs, html=html)


def same_site(a: str, b: str) -> bool:
    ha, hb = urlparse(a).netloc.lower().removeprefix("www."), urlparse(b).netloc.lower().removeprefix("www.")
    return bool(ha) and ha == hb


def _accepts(cls, name: str) -> bool:
    import inspect
    try:
        return name in inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):
        return False
