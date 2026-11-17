import json
from pathlib import Path
from unittest import mock

from deals import discover
from deals.crawl import Page, page_from_html
from deals.run import load_discovered

HOME = """<html><body><nav><a href="/">Home</a><a href="/our-menu">Menu</a>
<a href="/weekly-specials">Weekly Specials</a><a href="https://facebook.com/x">FB</a><a href="/contact">Contact</a></nav>
<h1>Welcome to Oom Piet se Kombuis</h1><p>Free delivery on orders over R300</p>
<img src="/wp-content/uploads/logo.png" alt="logo"><img src="/wp-content/uploads/2026/11/weekly-specials.jpg" alt="">
</body></html>"""
SPECIALS = """<html><body><h1>Weekly Specials</h1>
<h3>Monday</h3><p>Burger & chips R79</p>
<h3>Wednesday</h3><p>Half price pizzas</p>
<p>Happy hour 4-6pm: R25 draughts every day</p>
<p>Gift vouchers available – R250</p>
<p>Book a table: 021 555 1234</p></body></html>"""


def test_candidate_pages_and_posters():
    home = page_from_html("https://oompiet.co.za/", HOME)
    assert discover.candidate_pages(home) == ["https://oompiet.co.za/weekly-specials"]
    assert discover.poster_candidates([home]) == ["https://oompiet.co.za/wp-content/uploads/2026/11/weekly-specials.jpg"]


def test_rule_specials():
    got = discover.rule_specials(page_from_html("https://x/s", SPECIALS).text)
    texts = {(s["day"], s["text"], s["price"]) for s in got}
    assert ("Monday", "Burger & chips R79", 79.0) in texts
    assert ("Wednesday", "Half price pizzas", None) in texts
    assert any(s["day"] == "Daily" and "R25 draughts" in s["text"] for s in got)
    assert not any("voucher" in s["text"].lower() or "delivery" in s["text"].lower() for s in got)


def test_kit_csv_import(tmp_path):
    (tmp_path / "durbanville.csv").write_text(
        "Name,Website,Category,Address,Latitude,Longitude,Phone\n"
        "Oom Piet se Kombuis,oompiet.co.za,Restaurant,1 Main Rd Durbanville,-33.83,18.65,0215551234\n"
        "Brackenfell Butchery,https://bbutch.co.za,Butcher shop,,,,\n"
        "No Site Cafe,,Cafe,,,,\n")
    rows = discover.kit_businesses(tmp_path)
    assert [r["name"] for r in rows] == ["Oom Piet se Kombuis", "Brackenfell Butchery"]
    assert rows[0]["website"] == "https://oompiet.co.za" and rows[0]["lat"] == -33.83
    assert rows[0]["kind"] == "restaurant" and rows[1]["kind"] == "shop"
    assert "phone" not in rows[0]


def test_discovery_run_end_to_end(tmp_path):
    osm = [{"name": "Oom Piet se Kombuis", "website": "https://oompiet.co.za/", "category": "restaurant",
            "kind": "restaurant", "suburb": "Durbanville", "address": None, "lat": -33.83, "lng": 18.65,
            "found_via": "OpenStreetMap"},
           {"name": "Insta Only Cafe", "website": "https://instagram.com/insta", "kind": "restaurant",
            "lat": -33.83, "lng": 18.65, "found_via": "OpenStreetMap"},
           {"name": "Far Away", "website": "https://far.co.za", "kind": "restaurant",
            "lat": -34.2, "lng": 18.4, "found_via": "OpenStreetMap"}]
    pages = {"https://oompiet.co.za/": page_from_html("https://oompiet.co.za/", HOME),
             "https://oompiet.co.za/weekly-specials": page_from_html("https://oompiet.co.za/weekly-specials", SPECIALS)}
    with mock.patch.object(discover, "osm_businesses", return_value=osm), \
         mock.patch.object(discover, "kit_businesses", return_value=[]), \
         mock.patch.object(discover, "fetch_pages", side_effect=lambda urls, **k: {u: pages[u] for u in urls if u in pages}), \
         mock.patch.object(discover, "ocr_lines", return_value=["TUESDAY", "Ribs + side R145"]), \
         mock.patch.object(discover.Http, "get", return_value=mock.Mock(content=b"img")), \
         mock.patch.object(discover.llm, "available", return_value=False):
        out = discover.run(tmp_path, 50, "2026-11-17")
    b = out["businesses"]
    assert set(b) == {"oompiet.co.za"}                     # social-only and out-of-area skipped
    sp = {(s["day"], s["text"]) for s in b["oompiet.co.za"]["specials"]}
    assert ("Monday", "Burger & chips R79") in sp and ("Tuesday", "Ribs + side R145") in sp
    # daily scan turns them into verified own-site specials with a location
    d = load_discovered(tmp_path / "discovered.json")
    first = d["specials"][0]
    assert first.own_site and first.restaurant == "Oom Piet se Kombuis" and first.lat == -33.83
    # rechecked only after RECHECK_DAYS
    with mock.patch.object(discover, "osm_businesses", return_value=osm), \
         mock.patch.object(discover, "kit_businesses", return_value=[]), \
         mock.patch.object(discover, "fetch_pages", return_value={}) as fp:
        out2 = discover.run(tmp_path, 50, "2026-11-19")
    assert out2["counts"]["checked_this_run"] == 0
