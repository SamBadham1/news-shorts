#!/usr/bin/env python3
"""Download the photos from a news article page.

Usage:
    python fetch_images.py <article_url> <project_dir> [--max 10] [--min-images 3]
    python fetch_images.py --html saved_page.html <project_dir>   # offline / paywalled pages

Tries a plain download first (fast). If that fails or finds fewer than --min-images
photos, it opens the page in a real browser (Playwright: installed Edge/Chrome, else
bundled Chromium), scrolls to trigger lazy-loading, and keeps the photos exactly as the
page loaded them, which gets past most JavaScript-only pages and hotlink protection.

Results go to <project_dir>/images/NN.jpg and images/images.json (with captions and
credits). Exit code 2 = no usable photos; then try stock_images.py or ask the user.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imagestore import ImageStore, make_session  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")
SKIP_WORDS = ("logo", "icon", "avatar", "sprite", "placeholder", "pixel", "tracking",
              "badge", "author", "byline", "advert", "banner-ad", "1x1", "spacer")
CONSENT = re.compile(r"^\s*(accept( all)?( cookies)?|agree|i agree|allow all|ok|okay|got it|continue)\s*$", re.I)


# ----------------------------------------------------------------------------- page parsing

def best_from_srcset(srcset: str):
    best, best_w = None, -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0
        if len(bits) > 1:
            m = re.match(r"(\d+(?:\.\d+)?)([wx])", bits[1])
            if m:
                w = float(m.group(1)) * (1000 if m.group(2) == "x" else 1)
        if w >= best_w:
            best, best_w = bits[0], w
    return best


def page_info(soup, base):
    def meta_content(prop):
        tag = soup.find("meta", property=prop)
        return tag.get("content", "") if tag else ""
    title = meta_content("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
    site = meta_content("og:site_name") or urlparse(base).netloc
    return title, site


def collect_candidates(soup: BeautifulSoup, base: str):
    """Candidate dicts in priority order: hero/social image first, then in-article photos."""
    out = []

    def add(url, alt="", caption="", credit="", source=""):
        if not url or url.startswith("data:"):
            return
        url = urljoin(base, url.strip())
        if url.lower().split("?")[0].endswith((".svg", ".gif")):
            return
        if any(w in url.lower() for w in SKIP_WORDS):
            return
        out.append({"url": url, "alt": alt, "caption": caption, "credit": credit, "found_in": source})

    for prop in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
        for tag in soup.find_all("meta", attrs={"property": prop}) + soup.find_all("meta", attrs={"name": prop}):
            add(tag.get("content"), source="social")

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in list(items):
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                items.extend(item["@graph"])
        for item in items:
            if not isinstance(item, dict):
                continue
            imgs = item.get("image")
            for img in imgs if isinstance(imgs, list) else [imgs]:
                if isinstance(img, str):
                    add(img, source="json-ld")
                elif isinstance(img, dict):
                    holder = img.get("copyrightHolder") or img.get("author") or ""
                    if isinstance(holder, dict):
                        holder = holder.get("name", "")
                    credit = img.get("creditText") or (holder if isinstance(holder, str) else "")
                    caption = img.get("caption") or ""
                    add(img.get("url") or img.get("contentUrl"),
                        caption=caption if isinstance(caption, str) else "", credit=credit, source="json-ld")

    body = soup.find("article") or soup.find("main") or soup
    for img in body.find_all("img"):
        url = None
        for attr in ("srcset", "data-srcset"):
            if img.get(attr):
                url = best_from_srcset(img[attr])
                break
        if not url:
            pic = img.find_parent("picture")
            if pic:
                for src in pic.find_all("source"):
                    if src.get("srcset"):
                        url = best_from_srcset(src["srcset"])
                        break
        url = url or img.get("data-src") or img.get("data-original") or img.get("data-lazy-src") or img.get("src")
        caption, credit = "", ""
        fig = img.find_parent("figure")
        if fig and fig.find("figcaption"):
            caption = fig.find("figcaption").get_text(" ", strip=True)
        m = re.search(r"(?:Photo|Image|Picture|Credit)\s*[:/]\s*(.+)$", caption, re.I)
        if m:
            credit = m.group(1)
        add(url, alt=img.get("alt", ""), caption=caption, credit=credit, source="article")
    return out


def credit_from_caption(caption):
    m = re.search(r"(?:Photo|Image|Picture|Credit)\s*[:/]\s*(.+)$", caption or "", re.I)
    return m.group(1).strip() if m else ""


# ----------------------------------------------------------------------------- fetching

def save_candidates(store, cands, get_bytes, limit, label):
    added = 0
    for c in cands:
        if added >= limit:
            break
        if store.seen(c["url"]):
            continue
        try:
            data = get_bytes(c["url"])
        except Exception as e:
            print(f"  skip {c['url'][:80]}: {e.__class__.__name__}", file=sys.stderr)
            continue
        if not data:
            continue
        entry, why = store.add(data, {**c, "kind": "article"})
        if entry:
            added += 1
            print(f"  {entry['file']}  {entry['width']}x{entry['height']}  {label:7s} "
                  f"{(entry['caption'] or entry['alt'])[:60]}")
    return added


def plain_fetch(url, html_path, store, limit):
    session = make_session(UA)
    if html_path:
        html, base = Path(html_path).read_text(encoding="utf-8", errors="ignore"), url or ""
    else:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        html, base = r.text, r.url
    soup = BeautifulSoup(html, "html.parser")
    title, site = page_info(soup, base)

    def get(u):
        resp = session.get(u, timeout=30, headers={"Referer": base or u})
        resp.raise_for_status()
        return resp.content

    added = save_candidates(store, collect_candidates(soup, base), get, limit, "direct")
    return added, title, site


def launch_browser(p):
    channels = (["msedge"] if os.name == "nt" else []) + ["chrome", None]
    last = None
    for ch in channels:
        try:
            if ch:
                return p.chromium.launch(channel=ch, headless=True), ch
            return p.chromium.launch(headless=True), "chromium"
        except Exception as e:
            last = e
    raise RuntimeError(f"no browser could start ({last}). Run setup.py again.")


DOM_IMAGES_JS = """() => Array.from(document.images).map(i => {
  const fig = i.closest('figure'); const fc = fig ? fig.querySelector('figcaption') : null;
  return {src: i.currentSrc || i.src, alt: i.alt || '', w: i.naturalWidth, h: i.naturalHeight,
          caption: fc ? fc.innerText.trim() : '', inArticle: !!i.closest('article, main, [role=main]')};
})"""


def browser_fetch(url, store, limit):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  browser fallback unavailable (playwright not installed; run setup.py)", file=sys.stderr)
        return 0, "", ""
    with sync_playwright() as p:
        browser, which = launch_browser(p)
        print(f"  opening page in {which}...")
        ctx = browser.new_context(user_agent=UA, locale="en-NZ", viewport={"width": 1280, "height": 1800})
        page = ctx.new_page()
        responses = []
        page.on("response", lambda r: responses.append(r) if r.request.resource_type == "image" else None)
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            print(f"  browser could not load page: {e.__class__.__name__}", file=sys.stderr)
            browser.close()
            return 0, "", ""
        try:  # dismiss a cookie/consent banner if there is an obvious button
            page.get_by_role("button", name=CONSENT).first.click(timeout=2500)
        except Exception:
            pass
        for _ in range(14):  # scroll to trigger lazy-loaded photos
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(350)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        captured = {}
        for r in responses:
            try:
                if r.ok and (r.headers.get("content-type", "").startswith("image/")):
                    captured[r.url] = r.body()
            except Exception:
                pass
        by_key = {ImageStore._key(u): b for u, b in captured.items()}

        html, base = page.content(), page.url
        soup = BeautifulSoup(html, "html.parser")
        title, site = page_info(soup, base)
        cands = collect_candidates(soup, base)
        for d in page.evaluate(DOM_IMAGES_JS):
            if d["src"] and d["inArticle"] and d["w"] >= store.min_width:
                cands.append({"url": d["src"], "alt": d["alt"], "caption": d["caption"],
                              "credit": credit_from_caption(d["caption"]), "found_in": "article"})

        def get(u):
            if u in captured:
                return captured[u]
            if ImageStore._key(u) in by_key:
                return by_key[ImageStore._key(u)]
            resp = ctx.request.get(u, headers={"Referer": base}, timeout=30000)
            return resp.body() if resp.ok else None

        added = save_candidates(store, cands, get, limit, "browser")
        browser.close()
    return added, title, site


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="article URL")
    ap.add_argument("project", help="project directory")
    ap.add_argument("--html", help="use a saved HTML file instead of downloading the page")
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--min-images", type=int, default=3, help="use the browser if fewer are found")
    ap.add_argument("--min-width", type=int, default=600)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--browser-only", action="store_true")
    a = ap.parse_args()
    if not a.url and not a.html:
        sys.exit("Give an article URL or --html")

    store = ImageStore(a.project, min_width=a.min_width)
    if a.url:
        store.meta["article_url"] = a.url
    total, title, site = 0, "", ""

    if not a.browser_only:
        try:
            total, title, site = plain_fetch(a.url, a.html, store, a.max)
            print(f"Direct download: {total} photo(s)")
        except Exception as e:
            print(f"Direct download failed: {e}", file=sys.stderr)

    if a.url and not a.html and not a.no_browser and total < a.min_images:
        print("Trying a real browser...")
        try:
            n, t2, s2 = browser_fetch(a.url, store, a.max - total)
            total += n
            title, site = title or t2, site or s2
            print(f"Browser: {n} photo(s)")
        except Exception as e:
            print(f"Browser fallback failed: {e}", file=sys.stderr)

    store.meta["page_title"] = store.meta.get("page_title") or title
    store.meta["site"] = store.meta.get("site") or site
    store.save()
    print(f"Saved {total} new photo(s); {len(store.meta['images'])} in {store.dir}")
    if not store.meta["images"]:
        print("No usable photos. Next: stock_images.py (Wikimedia/Pexels) or ask the user for photos.")
        sys.exit(2)


if __name__ == "__main__":
    main()
