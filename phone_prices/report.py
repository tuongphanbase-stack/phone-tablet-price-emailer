"""The email (HTML and plain text) and the dashboard data files.

The email is built from a list of sections. Each section is a function
(context) -> (title, html, text) or None when it has nothing to show, so a
new section is one function added to SECTIONS.
"""
import csv
import html
import io
import json
import os

from . import history as hist

MIN_DROP_PCT = float(os.environ.get("MIN_DROP_PCT", "3"))
MAX_ROWS = int(os.environ.get("MAX_ROWS_PER_SECTION", "25"))


def vnd(n):
    return f"{n:,.0f}".replace(",", ".") + " ₫" if n is not None else "—"


def esc(s):
    return html.escape(str(s or ""))


def link(item):
    name = esc(item["name"])
    return f'<a href="{esc(item["url"])}" style="color:#1a56db;text-decoration:none">{name}</a>' if item.get("url") else name


def table(headers, rows, align=None):
    align = align or ["left"] * len(headers)
    th = "".join(f'<th style="text-align:{a};padding:6px 8px;border-bottom:2px solid #ddd;font-size:12px;color:#555">{esc(h)}</th>'
                 for h, a in zip(headers, align))
    body = "".join(
        "<tr>" + "".join(f'<td style="text-align:{a};padding:6px 8px;border-bottom:1px solid #eee;font-size:13px;vertical-align:top">{c}</td>'
                         for c, a in zip(r, align)) + "</tr>"
        for r in rows)
    return f'<table style="border-collapse:collapse;width:100%">{th and "<tr>" + th + "</tr>"}{body}</table>'


# ------------------------------------------------------------- watchlist

def load_watchlist(path="watchlist.json"):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("watch", [])
    except (OSError, ValueError):
        return []


def watch_matches(watch, groups):
    """Model groups whose key contains every word of watch["match"] (storage included)."""
    words = watch["match"].lower().replace("|", " ").split()
    hits = []
    for key, g in groups.items():
        name_part, storage = key.split("|")
        tokens = set(name_part.split()) | {storage}
        if all(w in tokens for w in words):
            hits.append(g)
    # "iphone 16 256gb" should not also list the 16 Pro / Pro Max: prefer the
    # groups with the fewest extra words.
    if hits:
        fewest = min(len(g["key"].split("|")[0].split()) for g in hits)
        hits = [g for g in hits if len(g["key"].split("|")[0].split()) == fewest]
    return hits


# --------------------------------------------------------------- sections

def section_watch(ctx):
    rows, text = [], []
    for w in ctx["watchlist"]:
        for g in watch_matches(w, ctx["groups"]):
            best = g["offers"][0]
            target = w.get("target")
            hit = target and best["price"] <= target
            low30 = hist.lowest_since(ctx["history"], g["key"], 30, ctx["today"])
            mark = ' <b style="color:#0a7d32">✓ dưới mức bạn đặt</b>' if hit else ""
            rows.append([f"<b>{esc(g['model'])}</b>{mark}", f"<b>{vnd(best['price'])}</b><br><small>{esc(best['shop_name'])}</small>",
                         vnd(target) if target else "—", vnd(low30), str(len(g["offers"]))])
            text.append(f"- {g['model']}: {vnd(best['price'])} ({best['shop_name']})" + (" — DƯỚI MỨC ĐẶT" if hit else ""))
    if not rows:
        return None
    return ("Máy bạn đang theo dõi",
            table(["Model", "Rẻ nhất", "Mức đặt", "Thấp nhất 30 ngày", "Số shop"], rows,
                  ["left", "right", "right", "right", "center"]),
            "\n".join(text))


def section_drops(ctx):
    drops = [c for c in ctx["changes"] if c["pct"] <= -MIN_DROP_PCT][:MAX_ROWS]
    if not drops:
        return None
    rows = [[link(c["item"]) + f"<br><small>{esc(c['item']['shop_name'])}</small>", vnd(c["before"]),
             f"<b>{vnd(c['after'])}</b>", f'<b style="color:#0a7d32">{c["pct"]:.1f}%</b>'] for c in drops]
    text = "\n".join(f"- {c['item']['name']} ({c['item']['shop_name']}): {vnd(c['before'])} -> {vnd(c['after'])} ({c['pct']:.1f}%)"
                     for c in drops)
    return (f"Giảm giá từ {MIN_DROP_PCT:g}% trở lên",
            table(["Sản phẩm", "Trước", "Bây giờ", "Thay đổi"], rows, ["left", "right", "right", "right"]), text)


def section_compare(ctx):
    multi = [g for g in ctx["groups"].values() if len(g["offers"]) >= 2]
    for g in multi:
        lo, hi = g["offers"][0]["price"], g["offers"][-1]["price"]
        g["spread"] = hi - lo
    multi.sort(key=lambda g: (-len(g["offers"]), -g["spread"]))
    multi = multi[:MAX_ROWS]
    if not multi:
        return None
    rows, text = [], []
    for g in multi:
        best, worst = g["offers"][0], g["offers"][-1]
        rows.append([f"<b>{esc(g['model'])}</b>",
                     f'<a href="{esc(best.get("url"))}" style="color:#0a7d32;font-weight:bold;text-decoration:none">{vnd(best["price"])}</a><br><small>{esc(best["shop_name"])}</small>',
                     f"{vnd(worst['price'])}<br><small>{esc(worst['shop_name'])}</small>",
                     vnd(g["spread"]), str(len(g["offers"]))])
        text.append(f"- {g['model']}: rẻ nhất {vnd(best['price'])} ({best['shop_name']}), đắt nhất {vnd(worst['price'])} ({worst['shop_name']})")
    return ("So sánh giá giữa các cửa hàng",
            table(["Model", "Rẻ nhất", "Đắt nhất", "Chênh", "Số shop"], rows, ["left", "right", "right", "right", "center"]),
            "\n".join(text))


def section_shops(ctx):
    rows, text = [], []
    for h in sorted(ctx["snapshot"]["shops"], key=lambda h: (-h["count"], h["name"])):
        status = {"ok": "✓", "partial": "một phần", "failed": "✗ lỗi"}[h["status"]]
        note = esc("; ".join(h["errors"])[:160])
        rows.append([esc(h["name"]), str(h["count"]), status, f"<small>{note}</small>"])
        text.append(f"- {h['name']}: {h['count']} sản phẩm, {status}" + (f" ({'; '.join(h['errors'])})" if h["errors"] else ""))
    return ("Tình trạng các cửa hàng", table(["Cửa hàng", "Sản phẩm", "Trạng thái", "Ghi chú"], rows,
                                             ["left", "right", "center", "left"]), "\n".join(text))


SECTIONS = [section_watch, section_drops, section_compare, section_shops]


def build_email(ctx):
    snap = ctx["snapshot"]
    ok = sum(1 for h in snap["shops"] if h["status"] != "failed")
    intro = (f"{len(snap['items'])} sản phẩm từ {ok}/{len(snap['shops'])} cửa hàng · "
             f"{sum(1 for g in ctx['groups'].values() if len(g['offers']) >= 2)} model có ở từ 2 shop trở lên")
    parts_html = [f'<h1 style="font-size:22px;margin:0 0 4px">Giá điện thoại & máy tính bảng</h1>'
                  f'<p style="color:#666;margin:0 0 18px">{esc(ctx["now_label"])} · {esc(intro)}</p>']
    parts_text = [f"Giá điện thoại & máy tính bảng — {ctx['now_label']}", intro, ""]
    for section in SECTIONS:
        out = section(ctx)
        if not out:
            continue
        title, body_html, body_text = out
        parts_html.append(f'<h2 style="font-size:17px;margin:26px 0 8px;border-left:4px solid #1a56db;padding-left:8px">{esc(title)}</h2>{body_html}')
        parts_text += [title.upper(), body_text, ""]
    dash = ctx.get("dashboard_url")
    if dash:
        parts_html.append(f'<p style="margin-top:24px"><a href="{esc(dash)}">Xem bảng giá đầy đủ và biểu đồ →</a></p>')
        parts_text.append(f"Bảng giá đầy đủ: {dash}")
    body = ('<div style="font-family:Arial,Helvetica,sans-serif;max-width:820px;margin:auto;color:#1d1d1f">'
            + "".join(parts_html) + "</div>")
    drops = sum(1 for c in ctx["changes"] if c["pct"] <= -MIN_DROP_PCT)
    subject = f"Giá điện thoại {ctx['date_label']}" + (f" · {drops} sản phẩm giảm giá" if drops else "")
    return subject, body, "\n".join(parts_text)


# -------------------------------------------------------- dashboard files

def write_dashboard(ctx, docs_dir="docs"):
    os.makedirs(docs_dir, exist_ok=True)
    snap = ctx["snapshot"]
    latest = {
        "repo": "phone-tablet-price-emailer",
        "status": "ok",
        "updated_at": snap["updated_at"],
        "item_count": len(snap["items"]),
        "model_count": len(ctx["groups"]),
        "shops": [{k: h[k] for k in ("id", "name", "count", "status")} for h in snap["shops"]],
    }
    models_out = []
    for key, g in sorted(ctx["groups"].items(), key=lambda kv: kv[1]["model"]):
        models_out.append({
            "key": key, "model": g["model"], "category": g["category"],
            "offers": [{k: o.get(k) for k in ("shop", "shop_name", "price", "old_price", "url", "name")} for o in g["offers"]],
            "history": ctx["history"]["models"].get(key, {}).get("best", []),
        })
    with open(os.path.join(docs_dir, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=1)
    with open(os.path.join(docs_dir, "models.json"), "w", encoding="utf-8") as f:
        json.dump({"updated_at": snap["updated_at"], "models": models_out}, f, ensure_ascii=False, separators=(",", ":"))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["shop", "category", "model", "name", "price", "old_price", "url"])
    for it in sorted(snap["items"], key=lambda x: (x["model"], x["price"])):
        w.writerow([it["shop_name"], it["category"], it["model"], it["name"], it["price"], it.get("old_price") or "", it.get("url") or ""])
    with open(os.path.join(docs_dir, "prices.csv"), "w", encoding="utf-8-sig", newline="") as f:
        f.write(buf.getvalue())
