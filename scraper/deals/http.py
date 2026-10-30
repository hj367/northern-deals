"""Polite HTTP client.

Uses curl_cffi (Chrome TLS fingerprint) when installed, because several SA
retailers sit behind bot protection that rejects plain python-requests.
Falls back to requests otherwise.
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any

log = logging.getLogger(__name__)

try:  # pragma: no cover - depends on environment
    from curl_cffi import requests as _cffi

    _HAVE_CFFI = True
except Exception:  # pragma: no cover
    _HAVE_CFFI = False
import requests as _requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "en-ZA,en;q=0.9",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}


class BlockedError(RuntimeError):
    """The site answered, but with a bot wall / 403 / captcha page."""


class Http:
    def __init__(self, min_delay: float = 1.5, max_delay: float = 3.5, timeout: int = 30):
        self.min_delay, self.max_delay, self.timeout = min_delay, max_delay, timeout
        self._last = 0.0
        if _HAVE_CFFI:
            self.s = _cffi.Session(impersonate="chrome")
        else:
            self.s = _requests.Session()
        self.s.headers.update(HEADERS)
        self.requests_made = 0

    def _wait(self) -> None:
        gap = random.uniform(self.min_delay, self.max_delay)
        elapsed = time.monotonic() - self._last
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last = time.monotonic()

    def request(self, method: str, url: str, *, retries: int = 2, **kw: Any):
        kw.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            self._wait()
            try:
                r = self.s.request(method, url, **kw)
                self.requests_made += 1
            except Exception as e:  # network error
                last_exc = e
                log.warning("%s %s failed (%s), attempt %d", method, url, e, attempt + 1)
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code in (403, 429, 503) or _looks_blocked(r):
                last_exc = BlockedError(f"{r.status_code} from {url}")
                log.warning("blocked/throttled: %s %s", r.status_code, url)
                time.sleep(5 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        raise last_exc or RuntimeError(f"failed: {url}")

    def get(self, url: str, **kw: Any):
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any):
        return self.request("POST", url, **kw)

    def get_json(self, url: str, **kw: Any):
        return self.get(url, **kw).json()

    def get_text(self, url: str, **kw: Any) -> str:
        return self.get(url, **kw).text


def _looks_blocked(r) -> bool:
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype:
        return False
    head = r.text[:3000].lower()
    return any(
        m in head
        for m in ("cf-challenge", "just a moment...", "attention required!", "px-captcha", "access denied")
    )
