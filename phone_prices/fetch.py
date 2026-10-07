"""Download shop pages, many at a time.

Plain pages are fetched with requests in a thread pool. Shops marked
"browser": true draw their products with JavaScript, so those pages are
opened in headless Chromium (Playwright) instead; if Playwright is not
installed those shops are reported as failed and the rest still run.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import requests

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}


def fetch_http(url, timeout=25, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            if r.status_code == 200 and r.text:
                r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code in (403, 404, 410):
                break  # retrying will not help
        except requests.RequestException as e:
            last = type(e).__name__
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(last or "no response")


def fetch_browser_pages(urls, timeout_ms=45000):
    """{url: html or Exception} for pages that need JavaScript."""
    results = {}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {u: RuntimeError("needs Playwright (pip install playwright)") for u in urls}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(user_agent=HEADERS["User-Agent"], locale="vi-VN")
        for url in urls:
            page = ctx.new_page()
            try:
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
                page.mouse.wheel(0, 4000)  # some grids load more items on scroll
                page.wait_for_timeout(1500)
                results[url] = page.content()
            except Exception as e:  # noqa: BLE001 - report any browser failure per page
                results[url] = RuntimeError(f"browser: {type(e).__name__}")
            finally:
                page.close()
        browser.close()
    return results


def fetch_all(jobs, workers=8, fetcher=fetch_http, browser_fetcher=fetch_browser_pages):
    """jobs: list of (key, url, needs_browser). Returns {key: text or Exception}."""
    out = {}
    plain = [(k, u) for k, u, b in jobs if not b]
    browser = [(k, u) for k, u, b in jobs if b]

    def one(job):
        key, url = job
        try:
            return key, fetcher(url)
        except Exception as e:  # noqa: BLE001 - one bad shop must not stop the others
            return key, e

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for key, result in pool.map(one, plain):
            out[key] = result
    if browser:
        pages = browser_fetcher([u for _, u in browser])
        for key, url in browser:
            out[key] = pages.get(url, RuntimeError("not fetched"))
    return out
