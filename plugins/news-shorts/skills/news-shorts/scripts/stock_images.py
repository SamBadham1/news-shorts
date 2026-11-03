#!/usr/bin/env python3
"""Search freely licensed photos and add them to a project, with credits.

Usage:
    python stock_images.py <project_dir> --query "Jacinda Ardern" --query "Wellington harbour"
                           [--source wikimedia|pexels|both] [--per-query 3]

Sources:
  wikimedia  Wikimedia Commons. No key needed. Best for named people, places, landmarks,
             buildings, events. Only free licences (public domain, CC0, CC BY, CC BY-SA).
  pexels     Pexels. Free API key (pexels.com/api) in PEXELS_API_KEY or
             ~/.news-shorts/config.json {"pexels_api_key": "..."}. Best for generic scenes
             (courtroom, hospital ward, traffic, rain). Free to use, credit appreciated.

Each photo is saved as images/NN.jpg and recorded in images/images.json with
kind="licensed", author, licence and source page, so build.py can credit it.
"""
import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imagestore import ImageStore, make_session  # noqa: E402

UA = "news-shorts/1.2 (https://github.com/SamBadham1/news-shorts)"
DATA_DIR = Path(os.environ.get("NEWS_SHORTS_HOME", Path.home() / ".news-shorts"))
FREE_LICENCES = re.compile(r"^(public domain|pd|cc0|cc[ -]by([ -]sa)?([ -][\d.]+)?|cc[ -]by[ -]sa)", re.I)


def strip_html(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def pexels_key():
    if os.environ.get("PEXELS_API_KEY"):
        return os.environ["PEXELS_API_KEY"]
    cfg = DATA_DIR / "config.json"
    if cfg.exists():
        try:
            return json.loads(cfg.read_text()).get("pexels_api_key")
        except Exception:
            pass
    return None


def search_wikimedia(session, query, n):
    params = {
        "action": "query", "format": "json", "formatversion": "2",
        "generator": "search", "gsrsearch": f"{query} filetype:bitmap", "gsrnamespace": "6",
        "gsrlimit": str(max(n * 4, 10)),
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "1600",
    }
    r = session.get("https://commons.wikimedia.org/w/api.php", params=params, timeout=30)
    r.raise_for_status()
    pages = sorted(r.json().get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        lic = strip_html(meta.get("LicenseShortName", {}).get("value", ""))
        if not FREE_LICENCES.match(lic) or re.search(r"\b(nc|nd)\b", lic, re.I) or info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        if info.get("width", 0) < 800:
            continue
        out.append({
            "url": info.get("thumburl") or info.get("url"),
            "author": strip_html(meta.get("Artist", {}).get("value", ""))[:80] or "Unknown",
            "license": lic,
            "license_url": meta.get("LicenseUrl", {}).get("value", ""),
            "source_page": info.get("descriptionurl", ""),
            "caption": strip_html(meta.get("ImageDescription", {}).get("value", ""))[:200],
            "alt": p.get("title", "").replace("File:", ""),
            "found_in": "Wikimedia Commons",
        })
    return out


def search_pexels(session, query, n, key):
    r = session.get("https://api.pexels.com/v1/search", timeout=30,
                    params={"query": query, "per_page": str(max(n * 2, 6))},
                    headers={"Authorization": key})
    r.raise_for_status()
    out = []
    for ph in r.json().get("photos", []):
        src = ph.get("src", {})
        out.append({
            "url": src.get("large2x") or src.get("large") or src.get("original"),
            "author": ph.get("photographer", "Unknown"),
            "license": "Pexels License",
            "license_url": "https://www.pexels.com/license/",
            "source_page": ph.get("url", ""),
            "caption": ph.get("alt", ""),
            "alt": ph.get("alt", ""),
            "found_in": "Pexels",
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--query", action="append", required=True, help="repeat for several searches")
    ap.add_argument("--source", choices=["wikimedia", "pexels", "both"], default="both")
    ap.add_argument("--per-query", type=int, default=3)
    a = ap.parse_args()

    store = ImageStore(a.project, min_width=700)
    session = make_session(UA)
    key = pexels_key()
    sources = ["wikimedia", "pexels"] if a.source == "both" else [a.source]
    if "pexels" in sources and not key:
        print("Pexels skipped: no API key (free at https://www.pexels.com/api/; "
              "save with: setup.py --pexels-key YOUR_KEY)")
        sources = [s for s in sources if s != "pexels"]

    total = 0
    for q in a.query:
        for src in sources:
            try:
                results = (search_wikimedia(session, q, a.per_query) if src == "wikimedia"
                           else search_pexels(session, q, a.per_query, key))
            except Exception as e:
                print(f"  {src} search failed for '{q}': {e}", file=sys.stderr)
                continue
            added = 0
            for item in results:
                if added >= a.per_query:
                    break
                if not item["url"] or store.seen(item["url"]):
                    continue
                try:
                    resp = session.get(item["url"], timeout=30)
                    resp.raise_for_status()
                except Exception as e:
                    print(f"  skip {item['url'][:70]}: {e.__class__.__name__}", file=sys.stderr)
                    continue
                entry, why = store.add(resp.content, {**item, "kind": "licensed"})
                if entry:
                    added += 1
                    print(f"  {entry['file']}  {entry['width']}x{entry['height']}  {src:9s} "
                          f"[{entry['license']}] {entry['alt'][:50]}")
            total += added
            if not results:
                print(f"  {src}: nothing for '{q}'")
    store.save()
    print(f"Added {total} licensed photo(s)")
    if total == 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
