#!/usr/bin/env python3
"""Phone & tablet prices from many Vietnamese shops -> one email.

    python phone_tablet_price_emailer.py check     # fetch every shop and show what was found
    python phone_tablet_price_emailer.py generate  # fetch, update history, write email/ and docs/
    python phone_tablet_price_emailer.py send      # send email/ with Gmail

Shops are listed in shops.json and the models you care about in
watchlist.json; neither needs a code change to edit. See README.md.

Environment variables (all optional except the Gmail ones for "send"):
    GMAIL_ADDRESS, GMAIL_APP_PASSWORD   Gmail account and app password
    PHONE_RECIPIENT                     who gets the email (default: GMAIL_ADDRESS)
    SHOPS                               only these shop ids, e.g. "tgdd,cellphones"
    FETCH_WORKERS                       pages fetched at the same time (default 8)
    SEND_ONLY_ON_CHANGE                 "true": no email when no price changed
    MIN_DROP_PCT                        smallest drop listed in the email (default 3)
    TIMEZONE                            default Asia/Ho_Chi_Minh
"""
import hashlib
import json
import os
import shutil
import smtplib
import ssl
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

from phone_prices import collect, history, report

EMAIL_DIR = "email"
HISTORY_FILE = os.environ.get("PRICE_HISTORY_FILE", "state/price_history.json")
HASH_FILE = os.environ.get("STATE_FILE", "state/last_hash.txt")


def now_local():
    return datetime.now(ZoneInfo(os.environ.get("TIMEZONE", "Asia/Ho_Chi_Minh")))


def dashboard_url():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return None
    owner, name = repo.split("/", 1)
    return f"https://{owner}.github.io/{name}/"


def run_collect():
    shops = collect.load_shops(os.environ.get("SHOPS_FILE", "shops.json"), os.environ.get("SHOPS"))
    snap = collect.collect(shops, workers=int(os.environ.get("FETCH_WORKERS") or "8"))
    return snap, collect.group_by_model(snap["items"])


def cmd_check():
    snap, groups = run_collect()
    for h in snap["shops"]:
        print(f"{h['status']:8} {h['name']:22} {h['count']:4} items  {'; '.join(h['errors'])}")
        for it in [i for i in snap["items"] if i["shop"] == h["id"]][:3]:
            print(f"           {report.vnd(it['price']):>14}  {it['name']}")
    print(f"\n{len(snap['items'])} items, {len(groups)} models, "
          f"{sum(1 for g in groups.values() if len(g['offers']) > 1)} found in more than one shop")


def cmd_generate():
    snap, groups = run_collect()
    shutil.rmtree(EMAIL_DIR, ignore_errors=True)
    if not snap["items"]:
        print("No prices found in any shop; nothing to send.")
        print(json.dumps(snap["shops"], ensure_ascii=False, indent=1))
        return
    now = now_local()
    today = now.date().isoformat()
    hist = history.load(HISTORY_FILE)
    changes = history.update(hist, snap, groups, today)
    history.save(hist, HISTORY_FILE)

    ctx = {
        "snapshot": snap, "groups": groups, "changes": changes, "history": hist, "today": today,
        "watchlist": report.load_watchlist(os.environ.get("WATCHLIST_FILE", "watchlist.json")),
        "now_label": now.strftime("%H:%M %d/%m/%Y"), "date_label": now.strftime("%d/%m/%Y"),
        "dashboard_url": dashboard_url(),
    }
    report.write_dashboard(ctx)

    fingerprint = hashlib.sha256(json.dumps(sorted((i["shop"], i.get("url") or i["name"], i["price"])
                                                   for i in snap["items"])).encode()).hexdigest()
    try:
        with open(HASH_FILE, encoding="utf-8") as f:
            unchanged = f.read().strip() == fingerprint
    except OSError:
        unchanged = False
    if unchanged and os.environ.get("SEND_ONLY_ON_CHANGE", "false").lower() == "true":
        print("No price changed since the last email; not sending.")
        return
    os.makedirs(os.path.dirname(HASH_FILE) or ".", exist_ok=True)
    with open(HASH_FILE, "w", encoding="utf-8") as f:
        f.write(fingerprint)

    subject, body_html, body_text = report.build_email(ctx)
    os.makedirs(EMAIL_DIR)
    for name, content in (("subject.txt", subject), ("body.html", body_html), ("body.txt", body_text)):
        with open(os.path.join(EMAIL_DIR, name), "w", encoding="utf-8") as f:
            f.write(content)
    print(f"Email written: {subject} ({len(snap['items'])} items, {len(changes)} price changes)")


def cmd_send():
    if not os.path.exists(os.path.join(EMAIL_DIR, "subject.txt")):
        print("No email to send.")
        return
    sender = os.environ.get("GMAIL_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender or not password:
        sys.exit("GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set to send.")
    recipient = os.environ.get("PHONE_RECIPIENT") or sender
    read = lambda n: open(os.path.join(EMAIL_DIR, n), encoding="utf-8").read()  # noqa: E731
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = read("subject.txt"), sender, recipient
    msg.attach(MIMEText(read("body.txt"), "plain", "utf-8"))
    msg.attach(MIMEText(read("body.html"), "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as server:
        server.login(sender, password)
        server.sendmail(sender, [r.strip() for r in recipient.split(",") if r.strip()], msg.as_string())
    print(f"Sent to {recipient}")


def main():
    commands = {"check": cmd_check, "generate": cmd_generate, "send": cmd_send}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: {sys.argv[0]} {'|'.join(commands)}")
    commands[sys.argv[1]]()


if __name__ == "__main__":
    main()
