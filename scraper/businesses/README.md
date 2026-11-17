# Business lists from the Google Maps scraper kit

Drop CSV files here and the weekly discovery adds those businesses (uploading a CSV also starts a discovery run).
Only the name, website, category, address and coordinates columns are used — phone numbers and emails are ignored.

The kit is run on your own PC (Google blocks it from GitHub's servers). It is against Google's terms of service; use it sparingly.

## Run it (PC, Python 3.9+ and Chrome installed)

```
git clone https://github.com/Mahanaicoach/google-maps-scraper-kit.git
cd google-maps-scraper-kit
python scripts/engine.py start
python scripts/scrape.py "restaurants in Durbanville" -33.832 18.648 --depth 2 --full --no-socials
```

`--full` adds the coordinates the app needs for "near me". Repeat for the searches below (pause a minute between them),
then upload the CSVs it saves into this folder on GitHub (Add file → Upload files).

| Search | lat | lng |
|---|---|---|
| restaurants in Durbanville | -33.832 | 18.648 |
| restaurants in Bellville | -33.900 | 18.630 |
| restaurants in Brackenfell | -33.873 | 18.693 |
| restaurants in Kraaifontein | -33.847 | 18.718 |
| restaurants in Kuils River | -33.924 | 18.685 |
| restaurants in Parow | -33.900 | 18.590 |
| restaurants in Milnerton | -33.875 | 18.497 |
| butchery in Northern Suburbs Cape Town | -33.880 | 18.640 |
| bakery in Northern Suburbs Cape Town | -33.880 | 18.640 |
| liquor store in Northern Suburbs Cape Town | -33.880 | 18.640 |
| deli in Northern Suburbs Cape Town | -33.880 | 18.640 |
| farm stall near Durbanville | -33.832 | 18.648 |

Any CSV with at least a name and a website column works, so a list you build by hand is fine too.
