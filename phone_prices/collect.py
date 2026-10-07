"""Fetch every enabled shop in shops.json and turn the pages into one list
of offers, each tagged with its shop, category and model key."""
import json
from collections import defaultdict
from datetime import datetime, timezone

from . import fetch, models, parse

MAX_ITEMS_PER_PAGE = 200


def load_shops(path="shops.json", only=None):
    with open(path, encoding="utf-8") as f:
        shops = json.load(f)["shops"]
    shops = [s for s in shops if s.get("enabled", True)]
    if only:
        wanted = {x.strip() for x in only.split(",") if x.strip()}
        shops = [s for s in shops if s["id"] in wanted]
    ids = [s["id"] for s in shops]
    if len(ids) != len(set(ids)):
        raise ValueError("shops.json has two shops with the same id")
    for s in shops:
        if s.get("parser", "auto") not in parse.PARSERS:
            raise ValueError(f"shop {s['id']}: unknown parser {s.get('parser')!r}")
    return shops


def collect(shops, workers=8, fetcher=fetch.fetch_http, browser_fetcher=fetch.fetch_browser_pages):
    """Returns {"updated_at", "shops": [health], "items": [offers]}."""
    jobs = []
    for s in shops:
        for category, urls in s.get("pages", {}).items():
            for url in urls:
                jobs.append(((s["id"], category, url), url, bool(s.get("browser"))))
    pages = fetch.fetch_all(jobs, workers=workers, fetcher=fetcher, browser_fetcher=browser_fetcher)

    by_id = {s["id"]: s for s in shops}
    health = {s["id"]: {"id": s["id"], "name": s["name"], "pages": 0, "ok_pages": 0, "count": 0, "errors": []}
              for s in shops}
    items, seen = [], set()
    for (shop_id, category, url), result in pages.items():
        shop = by_id[shop_id]
        h = health[shop_id]
        h["pages"] += 1
        if isinstance(result, Exception):
            h["errors"].append(f"{category}: {result}")
            continue
        try:
            found = parse.PARSERS[shop.get("parser", "auto")](result, url, shop)
        except Exception as e:  # noqa: BLE001 - a parser bug on one page must not stop the run
            h["errors"].append(f"{category}: parse error {type(e).__name__}")
            continue
        if not found:
            h["errors"].append(f"{category}: no products found")
            continue
        h["ok_pages"] += 1
        for p in found[:MAX_ITEMS_PER_PAGE]:
            ident = (shop_id, p.url or p.name)
            if ident in seen or len(models.model_name(p.name)) < 3:  # e.g. a bare "256GB" variant
                continue
            seen.add(ident)
            items.append({
                **p.to_dict(),
                "shop": shop_id,
                "shop_name": shop["name"],
                "category": models.category_of(p.name, category),
                "model": models.display_name(p.name),
                "key": models.model_key(p.name),
            })
            h["count"] += 1

    for h in health.values():
        h["status"] = "ok" if h["ok_pages"] == h["pages"] and h["pages"] else ("partial" if h["ok_pages"] else "failed")
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shops": list(health.values()),
        "items": items,
    }


def group_by_model(items):
    """{key: {"model", "category", "offers": [cheapest first]}}; one offer per shop
    (the shop's cheapest listing of that model)."""
    groups = defaultdict(dict)
    for it in items:
        if not it["key"].split("|")[1]:
            continue  # no storage size: too vague to compare across shops
        cur = groups[it["key"]].get(it["shop"])
        if cur is None or it["price"] < cur["price"]:
            groups[it["key"]][it["shop"]] = it
    out = {}
    for key, per_shop in groups.items():
        offers = sorted(per_shop.values(), key=lambda x: x["price"])
        out[key] = {"key": key, "model": offers[0]["model"], "category": offers[0]["category"], "offers": offers}
    return out
