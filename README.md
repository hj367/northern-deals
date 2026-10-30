# Northern Deals

Android app that finds specials in Cape Town's northern suburbs and checks whether they're actually good deals.

- **Groceries & retail** — Pick n Pay, Checkers, Woolworths, Dis-Chem, Clicks
- **Restaurants** — specials in Bellville, Durbanville, Brackenfell, Tyger Valley, Parow, Kraaifontein etc. (FoodBlogCT, Cape Town ETC)

## How a deal gets verified

| Check | Real deal if… | Red flag if… |
|---|---|---|
| "Was" price honest | the was-price was charged ≥7 days in the tracked history | it was **never** charged → marked **Fake discount** |
| Below usual price | effective price ≥10% under its 90-day median | it's the same as its normal price (perpetual "special") |
| Lowest in 90 days | at or below the lowest price tracked | — |
| Cross-store | cheapest of the stores carrying it (barcode or name+size match) | cheaper somewhere else today |

Multi-buys ("Buy 2 for R50") and loyalty prices (Smart Shopper, Xtra Savings) are converted to a per-item price and labelled.
Silent price drops (no "special" label but ≥10% under usual) are also listed.

Restaurant specials: **Current** if published/updated in the last 45 days (or listed by 2+ sites), **Probably on** up to 150 days, **Outdated** after that.

> The "was"-price and usual-price checks need about **2 weeks** of daily history before they kick in. Until then, deals are judged on cross-store comparison only, and new items show **Checking…**.

## Layout

```
scraper/               Python: scrape → record history → verify → deals.json
  sources.json         store URLs (edit here when a site changes — no code change)
  deals/               extractors, matching, verification
  tests/               offline tests (pytest)
app/                   Flutter app (lib/ + pubspec; Android project is generated in CI)
.github/workflows/
  scrape.yml           daily 06:17 SAST scan, publishes to the `data` branch
  build-apk.yml        builds the APK on every push to app/
```

## Setup

The repo is public. Deals and price history are saved to the **`data` branch** of this same repo by the scan workflow, using GitHub's built-in token — no extra secrets needed.

1. **Run the first scan:** Actions → *Scrape deals* → Run workflow. Check the log's `SOURCE` lines — each store reports ok / item count / error.
2. **Get the APK:** Actions → *Build APK* → latest run → artifact `northern-deals-apk`.

The app reads `https://raw.githubusercontent.com/hj367/northern-deals/data/deals.json`.

### Optional settings (app repo → Settings → Secrets and variables → Actions)

| Name | Type | What it does |
|---|---|---|
| `APIFY_TOKEN` | secret | If Pick n Pay or Checkers block GitHub's servers, falls back to a hosted scraper that uses SA connections (Apify, ~$5 per 1,000 products). |
| `PNP_STORE_CODE` | variable | Price Pick n Pay at a specific branch instead of the online default. |
| `DEALS_URL` | variable | Feed URL compiled into the APK (also changeable in the app under Sources & settings). |

## When a store shows an error

Store sites change and some block datacentre traffic. The scanner keeps going when one source fails, and the app's **Sources** screen (tune icon) shows which ones worked.

- *"no products were recognised"* → the URL in `scraper/sources.json` probably moved. Open the store's specials page in a browser, copy its URL into `sources.json` (keep the `{page}` placeholder), push.
- *"BlockedError 403"* → bot protection. Add `APIFY_TOKEN` (Pick n Pay / Checkers) or drop that store.

Woolworths, Dis-Chem and Clicks URLs are marked `url_confidence: low` — they were written without live access to the sites and are the most likely to need a one-line fix after the first run.

## Run locally

```bash
cd scraper
pip install -r requirements.txt
python -m pytest -q
python -m deals.run --data ../data   # writes deals.json + history.json locally --only "Checkers,FoodBlogCT"
```

## Notes

- Prices are the stores' online prices; your branch can differ.
- Scraping is rate-limited (1.5–3.5 s between requests) and runs once a day.
