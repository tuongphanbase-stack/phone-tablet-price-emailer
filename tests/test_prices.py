"""Run: python -m unittest discover tests

Shop sites cannot be reached from the tests, so they use saved sample pages
(tests/fixtures) and a fake fetcher.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from phone_prices import collect, history, models, parse, report  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


class ParsePrice(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(parse.parse_price("29.990.000₫"), 29990000)
        self.assertEqual(parse.parse_price("29,990,000 đ"), 29990000)
        self.assertEqual(parse.parse_price(29990000), 29990000)
        self.assertEqual(parse.parse_price("29990000.00"), 29990000)
        self.assertEqual(parse.parse_price("Giá: 8.490.000 VNĐ"), 8490000)

    def test_out_of_range(self):
        self.assertIsNone(parse.parse_price("150.000₫"))   # accessory or instalment
        self.assertIsNone(parse.parse_price(0))
        self.assertIsNone(parse.parse_price(True))
        self.assertIsNone(parse.parse_price("Liên hệ"))


class Parsers(unittest.TestCase):
    def names(self, products):
        return {p.name: p for p in products}

    def test_json_ld(self):
        got = self.names(parse.parse_auto(fixture("jsonld.html"), "https://shop.vn/dtdd"))
        self.assertEqual(got["iPhone 16 Pro Max 256GB | Chính hãng VN/A"].price, 30990000)
        self.assertEqual(got["iPhone 16 Pro Max 256GB | Chính hãng VN/A"].url, "https://shop.vn/iphone-16-pro-max")
        self.assertEqual(got["Samsung Galaxy S24 Ultra 12GB 256GB"].price, 24490000)  # lowPrice
        self.assertFalse(any("Ốp" in n for n in got))  # accessories are dropped

    def test_embedded_json(self):
        got = self.names(parse.parse_auto(fixture("nextdata.html"), "https://shop.vn/"))
        note = got["Xiaomi Redmi Note 13 8GB/128GB"]
        self.assertEqual((note.price, note.old_price), (4290000, 4890000))
        self.assertEqual(got["iPad Air M2 11 inch WiFi 128GB"].price, 15990000)  # {"price": {"value": ...}}
        self.assertEqual(len(got), 2)

    def test_html_cards(self):
        got = self.names(parse.parse_auto(fixture("cards.html"), "https://www.thegioididong.com/dtdd"))
        ip = got["iPhone 16 Pro Max 256GB"]
        # The gift ("Quà 500.000₫") is not the price; the crossed-out price is old_price.
        self.assertEqual((ip.price, ip.old_price), (31490000, 34990000))
        self.assertEqual(ip.url, "https://www.thegioididong.com/dtdd/iphone-16-pro-max")
        self.assertEqual(ip.image, "https://www.thegioididong.com/img/16pm.jpg")
        self.assertEqual(got["Samsung Galaxy S24 Ultra 5G 12GB/256GB"].price, 25990000)
        self.assertEqual(len(got), 3)  # the "Trả góp" footer is not a product

    def test_card_selectors(self):
        shop = {"selectors": {"card": "li.item", "name": "h3", "price": "strong.price"}}
        got = self.names(parse.parse_auto(fixture("cards.html"), "https://x.vn/", shop))
        self.assertEqual(got["OPPO Reno12 F 5G 8GB 256GB"].price, 8490000)

    def test_tiki(self):
        got = self.names(parse.parse_tiki(fixture("tiki.json"), "https://tiki.vn/api"))
        self.assertEqual(got["Apple iPhone 16 Pro Max 256GB"].old_price, 34990000)
        self.assertEqual(len(got), 2)

    def test_promo_banners_dropped(self):
        # 24hStore puts shop and bank offers in its product grid; they are not phones or tablets.
        got = self.names(parse.parse_auto(fixture("promos.html"), "https://24hstore.vn/dien-thoai"))
        self.assertFalse([n for n in got if "đến" in n.split("21.890.000")[0] or "Voucher" in n])
        self.assertEqual(got["iPhone 17 Pro 1TB | Chính hãng Việt Nam"].price, 41490000)
        self.assertEqual(got["Nokia HMD 105 4G"].price, 690000)  # cheap, but a real phone
        # A real product whose card text runs on into its promotion is kept.
        self.assertTrue(any(n.startswith("iPad Air M4 11 inch") for n in got))
        self.assertEqual(len(got), 3)

    def test_promo_names(self):
        for name in ["Apple Watch giảm đến 500.000đ", "Home PayLater giảm đến 500.000đ", "TPBank EVO giảm đến 500.000đ",
                     "VIB giảm đến 1.500.000đ", "VPBank hoàn đến 800.000đ", "Tặng Voucher 4.999.000đ",
                     "Hoàn tiền 10% khi mở thẻ", "Ưu đãi sinh viên", "Khuyến mãi tháng 10"]:
            self.assertFalse(parse.looks_like_device(name), name)
        for name in ["Xiaomi Pad 6 Pro 8GB/128GB giá rẻ", "Nokia 105 4G Pro", "iPad Pro M5 11 inch 2025 Wifi 2TB"]:
            self.assertTrue(parse.looks_like_device(name), name)

    def test_garbage_does_not_crash(self):
        self.assertEqual(parse.parse_auto("<html><p>Hết hàng</p>", "https://x.vn"), [])
        self.assertEqual(parse.parse_tiki("not json", "https://x.vn"), [])


class Models(unittest.TestCase):
    def test_same_device_same_key(self):
        same = ["iPhone 16 Pro Max 256GB | Chính hãng VN/A", "Điện thoại Apple iPhone 16 Pro Max 256GB",
                "iPhone 16 Pro Max 256GB - Titan Sa Mạc", "Apple iPhone 16 Pro Max (256GB) Titan Đen"]
        self.assertEqual(len({models.model_key(n) for n in same}), 1)
        self.assertEqual(models.model_key("Samsung Galaxy S24 Ultra 12GB 256GB"),
                         models.model_key("Galaxy S24 Ultra 5G (12GB/256GB) Xám Titan"))
        self.assertEqual(models.model_key("iPad Air M2 11 inch WiFi 128GB"),
                         models.model_key("iPad Air 11 inch M2 Wi-Fi 128GB"))

    def test_different_devices_differ(self):
        keys = {models.model_key(n) for n in [
            "iPhone 16 128GB", "iPhone 16 256GB", "iPhone 16 Plus 128GB", "iPhone 16 Pro 128GB",
            "iPad Air 11 M2 Wi-Fi 128GB", "iPad Air 11 M2 Wi-Fi + Cellular 128GB", "iPhone 15 1TB"]}
        self.assertEqual(len(keys), 7)

    def test_storage_and_category(self):
        self.assertEqual(models.storage_of("Galaxy A06 4GB 64GB"), 64)
        self.assertEqual(models.storage_of("Redmi 13 8GB/256GB"), 256)
        self.assertEqual(models.storage_of("iPhone 15 1TB"), 1024)
        self.assertIsNone(models.storage_of("Nokia 105 4G"))
        self.assertEqual(models.category_of("Samsung Galaxy Tab S9 FE"), "tablet")
        self.assertEqual(models.category_of("iPad mini 7"), "tablet")
        self.assertEqual(models.category_of("Samsung Galaxy S24"), "phone")
        self.assertEqual(models.display_name("iphone 16 pro max 256gb"), "Apple iPhone 16 Pro Max 256GB")


SHOPS = [
    {"id": "a", "name": "Shop A", "pages": {"phone": ["https://a.vn/dt"]}},
    {"id": "b", "name": "Shop B", "pages": {"phone": ["https://b.vn/dt"], "tablet": ["https://b.vn/mtb"]}},
    {"id": "t", "name": "Tiki", "parser": "tiki", "pages": {"phone": ["https://tiki.vn/api"]}},
    {"id": "down", "name": "Down", "pages": {"phone": ["https://down.vn/dt"]}},
    {"id": "js", "name": "JS shop", "browser": True, "pages": {"phone": ["https://js.vn/dt"]}},
]
PAGES = {
    "https://a.vn/dt": fixture("cards.html"),
    "https://b.vn/dt": fixture("jsonld.html"),
    "https://b.vn/mtb": fixture("nextdata.html"),
    "https://tiki.vn/api": fixture("tiki.json"),
}


def fake_fetch(url):
    if url not in PAGES:
        raise RuntimeError("HTTP 503")
    return PAGES[url]


def fake_browser(urls):
    return {u: fixture("cards.html") for u in urls}


class EndToEnd(unittest.TestCase):
    def run_once(self, pages=None):
        if pages:
            PAGES.update(pages)
        return collect.collect(SHOPS, workers=4, fetcher=fake_fetch, browser_fetcher=fake_browser)

    def test_collect_compare_history_email(self):
        snap = self.run_once()
        health = {h["id"]: h for h in snap["shops"]}
        self.assertEqual(health["down"]["status"], "failed")
        self.assertIn("HTTP 503", health["down"]["errors"][0])
        self.assertEqual(health["a"]["count"], 3)
        self.assertEqual(health["js"]["count"], 3)
        tablets = [i for i in snap["items"] if i["category"] == "tablet"]
        self.assertTrue(tablets and all("iPad" in i["name"] for i in tablets))

        groups = collect.group_by_model(snap["items"])
        g = groups[models.model_key("iPhone 16 Pro Max 256GB")]
        self.assertEqual([o["shop"] for o in g["offers"]][0], "t")  # Tiki is cheapest (30.49m)
        self.assertEqual(len(g["offers"]), 4)  # a, b, t, js

        with tempfile.TemporaryDirectory() as tmp:
            hpath = os.path.join(tmp, "h.json")
            h = history.load(hpath)
            self.assertEqual(history.update(h, snap, groups, "2026-10-01"), [])
            history.save(h, hpath)

            # Next day shop A drops the iPhone price by 10%.
            cheaper = fixture("cards.html").replace("31.490.000₫", "28.341.000₫")
            snap2 = self.run_once({"https://a.vn/dt": cheaper})
            groups2 = collect.group_by_model(snap2["items"])
            h = history.load(hpath)
            changes = history.update(h, snap2, groups2, "2026-10-02")
            self.assertEqual(len(changes), 1)
            self.assertEqual((changes[0]["before"], changes[0]["after"], changes[0]["pct"]), (31490000, 28341000, -10.0))
            key = models.model_key("iPhone 16 Pro Max 256GB")
            self.assertEqual(h["models"][key]["best"][-1], ["2026-10-02", 28341000, "a"])
            self.assertEqual(history.lowest_since(h, key, 30, "2026-10-02"), 28341000)

            ctx = {"snapshot": snap2, "groups": groups2, "changes": changes, "history": h, "today": "2026-10-02",
                   "watchlist": [{"match": "iphone 16 pro max 256gb", "target": 29000000}],
                   "now_label": "08:00 02/10/2026", "date_label": "02/10/2026", "dashboard_url": "https://x.github.io/y/"}
            subject, body, text = report.build_email(ctx)
            self.assertIn("1 sản phẩm giảm giá", subject)
            self.assertIn("dưới mức bạn đặt", body)
            self.assertIn("28.341.000 ₫", body)
            self.assertIn("Down", text)  # failing shops are listed
            self.assertIn("So sánh giá", body)

            report.write_dashboard(ctx, os.path.join(tmp, "docs"))
            with open(os.path.join(tmp, "docs", "models.json"), encoding="utf-8") as f:
                data = json.load(f)
            m = next(x for x in data["models"] if x["key"] == key)
            self.assertEqual(m["offers"][0]["price"], 28341000)
            self.assertEqual(len(m["history"]), 2)
            with open(os.path.join(tmp, "docs", "prices.csv"), encoding="utf-8-sig") as f:
                self.assertTrue(f.readline().startswith("shop,category,model"))
        PAGES["https://a.vn/dt"] = fixture("cards.html")

    def test_watch_match_is_exact_enough(self):
        items = [{"key": models.model_key(n), "model": models.display_name(n), "category": "phone",
                  "shop": "a", "shop_name": "A", "price": p, "name": n}
                 for n, p in [("iPhone 16 128GB", 20e6), ("iPhone 16 Pro 128GB", 26e6), ("iPhone 16 Plus 128GB", 23e6)]]
        groups = collect.group_by_model(items)
        hits = report.watch_matches({"match": "iphone 16 128gb"}, groups)
        self.assertEqual([g["model"] for g in hits], ["Apple iPhone 16 128GB"])


class ShopsFile(unittest.TestCase):
    def test_shops_json_is_valid(self):
        shops = collect.load_shops(os.path.join(ROOT, "shops.json"))
        self.assertGreaterEqual(len(shops), 15)
        for s in shops:
            self.assertTrue(s["pages"].get("phone"), s["id"])
            for urls in s["pages"].values():
                self.assertTrue(all(u.startswith("https://") for u in urls), s["id"])

    def test_history_prunes_old_rows(self):
        h = {"items": {"x": {"prices": [["2024-01-01", 1], ["2026-09-01", 2]]},
                       "gone": {"prices": [["2024-01-01", 1]]}}, "models": {}}
        history.prune(h, "2026-10-02")
        self.assertEqual(h["items"]["x"]["prices"], [["2024-01-01", 1], ["2026-09-01", 2]])
        self.assertNotIn("gone", h["items"])


if __name__ == "__main__":
    unittest.main()
