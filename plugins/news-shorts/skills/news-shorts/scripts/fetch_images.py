#!/usr/bin/env python3
"""Download the photos from a news article page.

Usage:
    python fetch_images.py <article_url> <project_dir> [--max 10] [--min-width 600]
    python fetch_images.py --html saved_page.html <project_dir>   # offline / paywalled pages

Writes <project_dir>/images/NN.<ext> and <project_dir>/images/images.json with
size, alt text, figure caption and photo credit (when the page provides them).
"""
import argparse
import hashlib
import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
SKIP_WORDS = ("logo", "icon", "avatar", "sprite", "placeholder", "pixel", "tracking",
              "badge", "author", "byline", "advert", "banner-ad", "1x1", "spacer")


def small_pixels(im):
    """16x16 greyscale pixel values (for duplicate detection)."""
    return list(im.convert("L").resize((16, 16)).tobytes())


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


def collect_candidates(soup: BeautifulSoup, base: str):
    """Return candidate dicts in priority order: hero/social image first, then in-article photos."""
    out = []

    def add(url, alt="", caption="", credit="", source=""):
        if not url or url.startswith("data:"):
            return
        url = urljoin(base, url.strip())
        if url.lower().split("?")[0].endswith((".svg", ".gif")):
            return
        if any(w in url.lower() for w in SKIP_WORDS):
            return
        out.append({"url": url, "alt": alt.strip(), "caption": caption.strip(),
                    "credit": credit.strip(), "found_in": source})

    for prop in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
        for tag in soup.find_all("meta", attrs={"property": prop}) + soup.find_all("meta", attrs={"name": prop}):
            add(tag.get("content"), source="social")

    # JSON-LD NewsArticle images
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict) and "@graph" in item:
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
                        caption=caption if isinstance(caption, str) else "",
                        credit=credit, source="json-ld")

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
        if fig:
            fc = fig.find("figcaption")
            if fc:
                caption = fc.get_text(" ", strip=True)
                m = re.search(r"(?:Photo|Image|Picture|Credit)\s*[:/]\s*(.+)$", caption, re.I)
                if m:
                    credit = m.group(1)
        add(url, alt=img.get("alt", ""), caption=caption, credit=credit, source="article")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="article URL")
    ap.add_argument("project", help="project directory")
    ap.add_argument("--html", help="use a saved HTML file instead of downloading the page")
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--min-width", type=int, default=600)
    a = ap.parse_args()

    project = Path(a.project)
    img_dir = project / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-NZ,en;q=0.9"})

    if a.html:
        html = Path(a.html).read_text(encoding="utf-8", errors="ignore")
        base = a.url or ""
    else:
        if not a.url:
            sys.exit("Give an article URL or --html")
        r = session.get(a.url, timeout=30)
        r.raise_for_status()
        html, base = r.text, r.url

    soup = BeautifulSoup(html, "html.parser")
    def meta_content(prop):
        tag = soup.find("meta", property=prop)
        return tag.get("content", "") if tag else ""

    page_title = meta_content("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else "")
    site = meta_content("og:site_name") or urlparse(base).netloc

    seen_urls, seen_hashes, results = set(), set(), []
    for c in collect_candidates(soup, base):
        if len(results) >= a.max:
            break
        key = re.sub(r"[?#].*$", "", c["url"])
        if key in seen_urls:
            continue
        seen_urls.add(key)
        try:
            resp = session.get(c["url"], timeout=30, headers={"Referer": base or c["url"]})
            resp.raise_for_status()
            im = Image.open(io.BytesIO(resp.content))
            im.load()
        except Exception as e:
            print(f"  skip {c['url'][:90]}: {e}", file=sys.stderr)
            continue
        if im.width < a.min_width or im.height < 300:
            continue
        ratio = im.width / im.height
        if ratio > 3.5 or ratio < 0.3:  # banners / strips
            continue
        # dedupe the same photo served at different sizes via a tiny perceptual hash
        px = small_pixels(im)
        avg = sum(px) / len(px)
        phash = hashlib.md5(bytes(1 if p > avg else 0 for p in px)).hexdigest()
        if phash in seen_hashes:
            continue
        seen_hashes.add(phash)
        n = len(results) + 1
        path = img_dir / f"{n:02d}.jpg"
        im.convert("RGB").save(path, quality=93)
        results.append({"file": f"images/{path.name}", "width": im.width, "height": im.height, **c})
        print(f"  {path.name}  {im.width}x{im.height}  {c['found_in']:8s} {(c['caption'] or c['alt'])[:70]}")

    meta = {"article_url": a.url, "page_title": page_title, "site": site, "images": results}
    (img_dir / "images.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"Saved {len(results)} image(s) to {img_dir}")
    if not results:
        sys.exit(2)


if __name__ == "__main__":
    main()
