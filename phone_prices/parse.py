"""Find products and prices in a shop page.

Shops change their HTML often, so instead of one hand-written parser per
shop, the 'auto' parser tries several general ways to find products and
keeps whatever it finds:

1. JSON-LD (<script type="application/ld+json">): Product and ItemList data
   that many shops publish for search engines.
2. JSON embedded in the page (Next.js __NEXT_DATA__ and other JSON scripts):
   any object with a product name and a price.
3. Product cards in the HTML: a link with a product name near a "₫" price.

A shop can also give CSS selectors to read its cards directly, or use a
named parser from PARSERS (for example 'tiki' for Tiki's JSON API).
To support a new kind of page, write a function (html, base_url, shop) ->
list of Product and add it to PARSERS.
"""
import json
import re
from dataclasses import dataclass, asdict
from urllib.parse import urljoin

from bs4 import BeautifulSoup

# Prices in Vietnam are whole đồng; anything outside this range is not a
# phone or tablet price (it is a monthly instalment, a points value, a typo).
MIN_PRICE = 500_000
MAX_PRICE = 200_000_000

PRICE_TEXT_RE = re.compile(r"(\d{1,3}(?:[.,]\d{3}){1,3})\s*(?:₫|đ|Đ|vnđ|VNĐ|VND|vnd)(?![A-Za-zÀ-ỹ])")
NAME_KEYS = ("name", "productName", "product_name", "title", "displayName")
PRICE_KEYS = ("price", "salePrice", "sale_price", "finalPrice", "final_price", "specialPrice",
              "special_price", "priceSale", "price_sale", "currentPrice", "current_price",
              "lowPrice", "promotionPrice", "sellingPrice")
OLD_PRICE_KEYS = ("originalPrice", "original_price", "listPrice", "list_price", "oldPrice",
                  "old_price", "marketPrice", "market_price", "regularPrice", "highPrice")
URL_KEYS = ("url", "link", "href", "url_path", "urlPath", "slug", "canonical")
# Words that show a "product" is an accessory, a service or a used item, not
# a new phone or tablet.
NOT_DEVICE_RE = re.compile(
    r"\b(ốp|op lung|bao da|cường lực|dán màn|miếng dán|sạc|cáp|cable|tai nghe|adapter|"
    r"pencil|bàn phím|keyboard|case|củ sạc|giá đỡ|gậy|thẻ nhớ|bảo hành|"
    r"gói cước|trả góp|cũ|like new|đã kích hoạt)\b",
    re.IGNORECASE,
)


@dataclass
class Product:
    name: str
    price: int
    url: str = ""
    old_price: int | None = None
    image: str = ""

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}


def parse_price(value):
    """Turn '29.990.000₫', '29,990,000', 29990000 or '29990000.0' into an int, else None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
    else:
        text = str(value).strip()
        m = PRICE_TEXT_RE.search(text)
        if m:
            text = m.group(1)
        text = re.sub(r"[^\d.,]", "", text)
        if not text:
            return None
        if re.fullmatch(r"\d+[.,]\d{1,2}", text):  # '29990000.00'
            text = re.split(r"[.,]", text)[0]
        n = int(re.sub(r"[.,]", "", text) or 0)
    return n if MIN_PRICE <= n <= MAX_PRICE else None


def clean_name(name):
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    return name[:160]


def looks_like_device(name):
    return bool(name) and len(name) >= 4 and not NOT_DEVICE_RE.search(name)


# ---------------------------------------------------------------- JSON-LD

def _walk(obj):
    """Every dict inside obj (depth first)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            yield cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _types(d):
    t = d.get("@type")
    return {t} if isinstance(t, str) else set(t or [])


def _offer_price(offers):
    for d in _walk(offers):
        for k in ("price", "lowPrice"):
            p = parse_price(d.get(k))
            if p:
                return p
    return None


def from_json_ld(soup, base_url):
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (ValueError, TypeError):
            continue
        for d in _walk(data):
            if "Product" not in _types(d):
                continue
            price = _offer_price(d.get("offers"))
            name = clean_name(d.get("name"))
            if price and name:
                image = d.get("image")
                if isinstance(image, list):
                    image = image[0] if image else ""
                out.append(Product(name, price, urljoin(base_url, str(d.get("url") or "")),
                                   image=str(image or "") if isinstance(image, str) else ""))
    return out


# ------------------------------------------------------- embedded JSON data

def _first(d, keys):
    for k in keys:
        if k in d and d[k] not in (None, "", 0):
            return d[k]
    return None


def products_from_json(data, base_url):
    """Objects anywhere in data that have a product name and a sensible price."""
    out = []
    for d in _walk(data):
        name = _first(d, NAME_KEYS)
        if not isinstance(name, str):
            continue
        price_val = _first(d, PRICE_KEYS)
        if isinstance(price_val, dict):  # {"price": {"value": ...}}
            price_val = _first(price_val, ("value", "amount", "price", "final"))
        price = parse_price(price_val)
        if not price:
            continue
        url = _first(d, URL_KEYS)
        old = parse_price(_first(d, OLD_PRICE_KEYS))
        out.append(Product(clean_name(name), price,
                           urljoin(base_url, url) if isinstance(url, str) else "",
                           old_price=old if old and old > price else None))
    return out


def from_embedded_json(soup, base_url):
    out = []
    for tag in soup.find_all("script"):
        kind = (tag.get("type") or "").lower()
        if tag.get("id") != "__NEXT_DATA__" and kind not in ("application/json",):
            continue
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (ValueError, TypeError):
            continue
        out.extend(products_from_json(data, base_url))
    return out


# ------------------------------------------------------------ HTML cards

def _card_name(card, link):
    for sel in ("h3", "h2", "h4", "[class*=name]", "[class*=title]"):
        el = card.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(" ", strip=True)
    if link is not None:
        if link.get("title"):
            return link["title"]
        if link.get_text(strip=True):
            return link.get_text(" ", strip=True)
    img = card.find("img", alt=True)
    return img["alt"] if img else ""


def _card_prices(card):
    """Prices printed in a card. Gifts, vouchers and monthly instalments
    ("Quà 500.000₫") are far below the device price, so amounts under 40%
    of the highest one are dropped."""
    prices = [parse_price(m.group(0)) for m in PRICE_TEXT_RE.finditer(card.get_text(" ", strip=True))]
    prices = [p for p in prices if p]
    return [p for p in prices if p >= 0.4 * max(prices)] if prices else []


def _card_image(card, base_url):
    img = card.find("img")
    if not img:
        return ""
    src = img.get("data-src") or img.get("data-original") or img.get("src") or ""
    return "" if src.startswith("data:") else urljoin(base_url, src)


def from_cards(soup, base_url, selectors=None):
    """Product cards: with selectors if the shop gives them, else by looking
    for the smallest element that holds one product link and a price."""
    out = []
    if selectors and selectors.get("card"):
        for card in soup.select(selectors["card"]):
            link = card.select_one(selectors.get("link") or "a[href]")
            name_el = card.select_one(selectors["name"]) if selectors.get("name") else None
            name = name_el.get_text(" ", strip=True) if name_el else _card_name(card, link)
            price_el = card.select_one(selectors["price"]) if selectors.get("price") else None
            prices = [parse_price(price_el.get_text())] if price_el else _card_prices(card)
            prices = [p for p in prices if p]
            if name and prices:
                out.append(Product(clean_name(name), prices[0],
                                   urljoin(base_url, link["href"]) if link and link.get("href") else "",
                                   image=_card_image(card, base_url)))
        return out

    seen = set()
    for text_node in soup.find_all(string=PRICE_TEXT_RE):
        el = text_node.parent
        # Climb until the element also holds a product link (that is the card).
        for _ in range(7):
            if el is None or el.name in ("body", "html"):
                el = None
                break
            links = [a for a in el.find_all("a", href=True) if not a["href"].startswith(("#", "javascript"))]
            if links:
                break
            el = el.parent
        if el is None or id(el) in seen:
            continue
        hrefs = {a["href"] for a in links}
        if len(hrefs) > 2:  # climbed past the card into a grid of products
            continue
        seen.add(id(el))
        prices = _card_prices(el)
        name = _card_name(el, links[0])
        if not prices or not name:
            continue
        # The price to pay is the lowest one; a higher one is the crossed-out price.
        price, old = min(prices), max(prices)
        out.append(Product(clean_name(name), price, urljoin(base_url, links[0]["href"]),
                           old_price=old if old > price else None, image=_card_image(el, base_url)))
    return out


# ----------------------------------------------------------- the parsers

def parse_auto(html, base_url, shop=None):
    soup = BeautifulSoup(html, "html.parser")
    selectors = (shop or {}).get("selectors")
    found = []
    for step in (from_json_ld, from_embedded_json):
        found.extend(step(soup, base_url))
    found.extend(from_cards(soup, base_url, selectors))
    return dedupe(found)


def parse_tiki(text, base_url, shop=None):
    """Tiki listing API: {"data": [{"name", "price", "list_price", "url_path", "thumbnail_url"}]}."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for d in data.get("data") or []:
        price = parse_price(d.get("price"))
        if not price or not d.get("name"):
            continue
        old = parse_price(d.get("list_price") or d.get("original_price"))
        url = d.get("url_path") or d.get("url_key") or ""
        out.append(Product(clean_name(d["name"]), price, urljoin("https://tiki.vn/", url),
                           old_price=old if old and old > price else None,
                           image=d.get("thumbnail_url") or ""))
    return dedupe(out)


PARSERS = {
    "auto": parse_auto,
    "tiki": parse_tiki,
}


def dedupe(products):
    """One entry per product: same link (or same name when there is no link),
    keeping the lowest price seen for it on the page."""
    best = {}
    for p in products:
        if not looks_like_device(p.name):
            continue
        key = p.url or p.name.lower()
        if key not in best or p.price < best[key].price:
            if key in best and not p.image:
                p.image = best[key].image
            best[key] = p
    return list(best.values())
