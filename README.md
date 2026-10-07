# Phone & Tablet Price Emailer

Collects phone and tablet prices from many Vietnamese shops, compares the
same model across shops, remembers the price history and emails you:

- **the models you follow** (`watchlist.json`), with the cheapest shop and a
  mark when the price reaches the target you set;
- **price drops** of 3% or more since the last change;
- **a comparison** of models sold by two or more shops (cheapest, dearest, difference);
- **the state of every shop**, so you can see when a shop's page changed and
  stopped giving prices.

A dashboard (GitHub Pages, `docs/`) shows every model with its offers, a
price chart and a CSV download.

## Shops

`shops.json` lists 18 shops: Thế Giới Di Động, Điện Máy Xanh, CellphoneS,
FPT Shop, Hoàng Hà Mobile, Di Động Việt, Viettel Store, Nguyễn Kim,
MediaMart, 24hStore, ShopDunk, Minh Tuấn Mobile, Hnam Mobile, Clickbuy,
Bạch Long Mobile, Di Động Thông Minh, Phong Vũ and Tiki.

**Adding a shop needs no code**: copy an entry in `shops.json`, give it an
`id`, a `name` and the URLs of its phone and tablet pages. The `auto`
parser finds products in three ways, so it works on most shop pages:

1. JSON-LD product data that shops publish for Google;
2. product data embedded as JSON in the page (e.g. Next.js `__NEXT_DATA__`);
3. product cards in the HTML (a link with a name next to a "₫" price).

If a shop draws its products with JavaScript, add `"browser": true`. If
`auto` picks the wrong things, add CSS `selectors` (see the help at the top
of `shops.json`). For a shop with its own API, write a small parser in
`phone_prices/parse.py` and register it in `PARSERS` (see `parse_tiki`).

The shop URLs could not be tested from where this was written. After the
first run, check the **Tình trạng các cửa hàng** table in the email (or run
the workflow with `command: check`) and fix or disable (`"enabled": false`)
any shop that shows an error.

## How models are matched

`phone_prices/models.py` turns names like "iPhone 16 Pro Max 256GB | Chính
hãng VN/A" and "Điện thoại Apple iPhone 16 Pro Max 256GB - Titan Sa Mạc"
into the same key, dropping colours, RAM and shop wording while keeping the
storage size. Add a brand to `BRANDS` if one is missing.

## Running it

GitHub Actions (`.github/workflows/send-phone-prices.yml`) runs at 07:43 and
19:43 Vietnam time. Add these repository secrets (Settings → Secrets and
variables → Actions):

- `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` (a Gmail app password)
- `PHONE_RECIPIENT` (optional, defaults to `GMAIL_ADDRESS`; several addresses separated by commas)

Without the Gmail secrets the run still updates the dashboard and skips the
email. The price history is kept on the `phone-price-state` branch. With
`SEND_ONLY_ON_CHANGE=true` no email is sent when no price changed.

Locally:

```
pip install -r requirements.txt
python phone_tablet_price_emailer.py check        # what each shop returns
SHOPS=tgdd,tiki python phone_tablet_price_emailer.py check
python phone_tablet_price_emailer.py generate     # writes email/ and docs/
python phone_tablet_price_emailer.py send
```

## Tests

`python -m unittest discover tests` checks the parsers on saved sample
pages, model matching, price history, the email and the dashboard files.

## Files

- `phone_tablet_price_emailer.py` — the commands (check, generate, send)
- `phone_prices/fetch.py` — downloads pages in parallel; Chromium for `browser` shops
- `phone_prices/parse.py` — finds products and prices in a page
- `phone_prices/models.py` — recognises the same model across shops
- `phone_prices/collect.py` — runs all shops and groups offers by model
- `phone_prices/history.py` — price history and drops
- `phone_prices/report.py` — the email sections and the dashboard files
- `docs/` — the dashboard
