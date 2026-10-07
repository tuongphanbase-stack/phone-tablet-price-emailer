"""Price history, kept between runs in state/price_history.json.

  items:  one entry per shop listing, with its price on each day it changed
  models: the lowest price across all shops for each model, per day

The history lets the email show price drops since the last change and the
lowest price in the last 30/90 days.
"""
import json
import os
from datetime import date, timedelta

KEEP_DAYS = 400


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault("items", {})
            data.setdefault("models", {})
            return data
    except (OSError, ValueError):
        pass
    return {"items": {}, "models": {}}


def save(history, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, separators=(",", ":"))


def item_id(item):
    return f"{item['shop']}|{item.get('url') or item['name']}"


def _record(series, day, price, extra=None):
    """Add [day, price, ...] unless the price is unchanged; same day overwrites."""
    row = [day, price] + ([extra] if extra is not None else [])
    if series and series[-1][0] == day:
        series[-1] = row
    elif not series or series[-1][1] != price or (extra is not None and series[-1][2:] != [extra]):
        series.append(row)


def update(history, snapshot, groups, today=None):
    """Adds today's prices. Returns the price changes for listings seen before:
    [{"item", "before", "after", "change", "pct"}], biggest drop first."""
    today = today or date.today().isoformat()
    changes = []
    for it in snapshot["items"]:
        entry = history["items"].setdefault(item_id(it), {"prices": []})
        entry.update(name=it["name"], shop=it["shop"], key=it["key"], category=it["category"])
        prices = entry["prices"]
        previous = next((p for d, p, *_ in reversed(prices) if d != today), None)
        _record(prices, today, it["price"])
        if previous and previous != it["price"]:
            diff = it["price"] - previous
            changes.append({"item": it, "before": previous, "after": it["price"],
                            "change": diff, "pct": round(diff * 100 / previous, 1)})
    for key, g in groups.items():
        entry = history["models"].setdefault(key, {"best": []})
        entry.update(model=g["model"], category=g["category"])
        best = g["offers"][0]
        _record(entry["best"], today, best["price"], best["shop"])
    prune(history, today)
    changes.sort(key=lambda c: c["pct"])
    return changes


def prune(history, today):
    cutoff = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS)).isoformat()
    for section, field in (("items", "prices"), ("models", "best")):
        for k in list(history[section]):
            rows = history[section][k][field]
            # Keep the last row before the cutoff so "the price before" is known.
            old = [r for r in rows if r[0] < cutoff]
            rows[:] = old[-1:] + [r for r in rows if r[0] >= cutoff]
            if rows and rows[-1][0] < cutoff:
                del history[section][k]  # not seen for over a year


def lowest_since(history, key, days, today=None):
    """Lowest best-price of a model in the last `days` days (None if unknown)."""
    today = today or date.today().isoformat()
    start = (date.fromisoformat(today) - timedelta(days=days)).isoformat()
    rows = history["models"].get(key, {}).get("best", [])
    # The price on `start` is the last row on or before it.
    before = [r for r in rows if r[0] <= start][-1:]
    window = before + [r for r in rows if r[0] > start]
    return min((r[1] for r in window), default=None)
