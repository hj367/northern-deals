from datetime import date, timedelta

from deals.extract import products_from_html, products_from_json
from deals.history import History
from deals.match import group_same_products, size_key
from deals.models import ProductObs, parse_rand
from deals.run import build_output
from deals.sources.wordpress import special_from_post
from deals.verify import effective_price, verify_product

SUBURBS = ["Bellville", "Durbanville", "Tygervalley", "Brackenfell"]

CHECKERS_HTML = """
<html><body>
<div class="item-product" data-product-ga='{"id":"10133585EA","name":"Nescafe Gold Instant Coffee 200g","price":"139.99","brand":"Nescafe"}'>
  <a href="/All-Departments/Food/Coffee/Nescafe-Gold-200g/p/10133585EA"><img data-src="/medias/nes.jpg"></a>
  <div class="special-price__price"><span class="now">R139.99</span><span class="before-price">R189.99</span></div>
  <div class="item-product__promotion">Xtra Savings</div>
</div>
<div class="item-product" data-product-ga='{"id":"1000PNPMILK","name":"Clover Full Cream Milk 6 x 1L","price":"104.99","brand":"Clover"}'>
  <a href="/p/1000PNPMILK"></a>
</div>
</body></html>
"""

PNP_JSON = {
    "pagination": {"totalResults": 2},
    "products": [
        {"code": "000000000000349246_EA", "name": "Nescafe Gold Instant Coffee 200g",
         "price": {"value": 129.99, "formattedValue": "R129.99"},
         "potentialPromotions": [{"promotionTextMessage": "Smart Shopper Deal"}],
         "images": [{"url": "/medias/a.jpg"}], "url": "/nescafe/p/000000000000349246_EA"},
        {"code": "000000000000111_EA", "name": "PnP Brown Sugar 2.5kg",
         "price": {"value": 54.99}, "potentialPromotions": [{"promotionTextMessage": "Buy 2 for R100"}]},
    ],
}

JSONLD_HTML = """<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Panado Tablets 24s","sku":"DC123",
 "gtin13":"6001234567890","offers":{"@type":"Offer","price":"39.95","priceValidUntil":"2026-11-15"}}
</script>"""


def test_parse_rand():
    assert parse_rand("R1 299.99") == 1299.99
    assert parse_rand("R 49,99") == 49.99
    assert parse_rand("R1,299.99") == 1299.99
    assert parse_rand("Now only R55!") == 55.0


def test_checkers_tiles():
    ps = products_from_html(CHECKERS_HTML, "Checkers", "https://www.checkers.co.za")
    assert len(ps) == 2
    nes = ps[0]
    assert nes.price == 139.99 and nes.was_price == 189.99
    assert nes.promo_text == "Xtra Savings"
    assert nes.url.startswith("https://www.checkers.co.za/All-Departments")
    assert nes.on_promo and not ps[1].on_promo


def test_pnp_json():
    ps = products_from_json(PNP_JSON, "Pick n Pay", "https://www.pnp.co.za/p/")
    assert [p.price for p in ps] == [129.99, 54.99]
    assert ps[0].promo_text == "Smart Shopper Deal"
    assert effective_price(ps[1]) == (50.0, "when you buy 2")


def test_jsonld():
    (p,) = products_from_html(JSONLD_HTML, "Dis-Chem", "https://www.dischem.co.za")
    assert p.price == 39.95 and p.barcode == "6001234567890" and p.valid_until == "2026-11-15"


def test_size_and_matching():
    assert size_key("Clover Milk 6 x 1L") == "w6000"
    assert size_key("Nescafe Gold 200g") == "w200"
    assert size_key("Panado Tablets 24s") == "c24"
    a = ProductObs("Checkers", "1", "Nescafe Gold Instant Coffee 200g", 139.99)
    b = ProductObs("Pick n Pay", "2", "NESCAFE Gold Instant Coffee (200g)", 129.99)
    c = ProductObs("Woolworths", "3", "Nescafe Gold Instant Coffee 100g", 79.99)
    d = ProductObs("Woolworths", "4", "Jacobs Gold Instant Coffee 200g", 99.99)
    groups = group_same_products([a, b, c, d])
    assert len(groups) == 1 and {p.store for p in groups[0]} == {"Checkers", "Pick n Pay"}


def _hist(prices, today="2026-10-30"):
    t = date.fromisoformat(today)
    n = len(prices)
    return [[(t - timedelta(days=n - i)).isoformat(), p, None, 0] for i, p in enumerate(prices)]


def test_fake_was_price():
    p = ProductObs("Checkers", "1", "Coffee 200g", 129.99, was_price=199.99)
    v = verify_product(p, _hist([139.99] * 30), [], "2026-10-30")
    assert v["verdict"] == "fake"
    assert "never seen" in v["reasons"][0]["text"]


def test_genuine_deal():
    p = ProductObs("Checkers", "1", "Coffee 200g", 129.99, was_price=169.99)
    v = verify_product(p, _hist([169.99] * 30), [], "2026-10-30")
    assert v["verdict"] == "real", v


def test_perpetual_special_is_weak():
    # "Special" price that is just the normal price every day
    p = ProductObs("Checkers", "1", "Coffee 200g", 129.99, promo_text="SPECIAL")
    v = verify_product(p, _hist([129.99] * 30), [], "2026-10-30")
    assert v["verdict"] == "weak"


def test_cheaper_elsewhere_penalised():
    p = ProductObs("Checkers", "1", "Coffee 200g", 139.99, was_price=159.99)
    other = ProductObs("Pick n Pay", "2", "Coffee 200g", 119.99)
    v = verify_product(p, [], [other], "2026-10-30")
    assert v["verdict"] == "weak"
    assert "cheaper at Pick n Pay" in " ".join(r["text"] for r in v["reasons"])


def test_new_item_unverified():
    p = ProductObs("Clicks", "1", "Thing", 10.0, was_price=20.0)
    assert verify_product(p, [], [], "2026-10-30")["verdict"] == "unverified"


def _post(title, content, date_, link="https://x/p"):
    return {"id": 1, "date": date_ + "T09:00:00", "modified": date_ + "T09:00:00", "link": link,
            "title": {"rendered": title}, "content": {"rendered": content}, "excerpt": {"rendered": ""}}


def test_wordpress_special_parsing():
    old = special_from_post(_post(
        "Fish &amp; Chips for only R55 at Hooked",
        "<p>Get fish and chips for only R55.</p><p><strong>Directions to Hooked</strong><br>Tygervalley Shopping Centre<br>Bellville<br>021 914 5360</p>",
        "2017-12-11"), "FoodBlogCT", SUBURBS)
    assert old.price == 55 and old.restaurant == "Hooked" and old.suburb == "Tyger Valley"
    elsewhere = special_from_post(_post("Pizza at Le Pommier", "<p>Stellenbosch, every Wednesday R120</p>", "2026-10-29"),
                                  "FoodBlogCT", SUBURBS)
    assert elsewhere is None  # not northern suburbs


def test_end_to_end_build():
    hist = History()
    today = "2026-10-30"
    # 20 days of Checkers at R169.99, Pick n Pay at R149.99
    for i in range(20, 0, -1):
        d = (date.fromisoformat(today) - timedelta(days=i)).isoformat()
        hist.record(ProductObs("Checkers", "c1", "Nescafe Gold Instant Coffee 200g", 169.99), d)
        hist.record(ProductObs("Pick n Pay", "p1", "Nescafe Gold Instant Coffee 200g", 149.99), d)
    today_items = [
        ProductObs("Checkers", "c1", "Nescafe Gold Instant Coffee 200g", 119.99, was_price=169.99),
        ProductObs("Pick n Pay", "p1", "Nescafe Gold Instant Coffee 200g", 149.99, promo_text="Special"),
    ]
    specials = [
        special_from_post(_post("Half-price burgers at Jackson and Black every Tuesday",
                                "<p>Tyger Waterfront, Bellville. R95 burgers on Tuesdays.</p>",
                                "2026-10-20"), "FoodBlogCT", SUBURBS + ["Tyger Waterfront"]),
        special_from_post(_post("Fish &amp; Chips for only R55 at Hooked",
                                "<p>Directions to Hooked<br>Tygervalley Shopping Centre<br>Bellville</p>",
                                "2017-12-11"), "FoodBlogCT", SUBURBS),
    ]
    out = build_output(today_items, specials, hist, [], today)
    g = {d["store"]: d for d in out["grocery"]}
    assert g["Checkers"]["verdict"] == "real"
    assert g["Pick n Pay"]["verdict"] == "weak"   # "special" at its everyday price, dearer than Checkers
    assert len(g["Checkers"]["history"]) == 21
    r = {d["restaurant"]: d for d in out["restaurants"]}
    assert r["Jackson and Black"]["verdict"] == "verified" and r["Jackson and Black"]["days"] == ["Tuesday"]
    assert r["Hooked"]["verdict"] == "outdated"
    assert out["grocery"][0]["store"] == "Checkers"
