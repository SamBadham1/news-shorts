"""Shared image store for a project: validates, de-duplicates and records each photo
with where it came from and how to credit it, in <project>/images/images.json.

Entry fields:
  file, width, height, kind ("article" | "licensed" | "user"), url, alt, caption,
  credit, license, license_url, author, source_page, found_in
"""
import hashlib
import io
import json
import re
from pathlib import Path

from PIL import Image


def make_session(user_agent):
    """requests.Session that trusts both a custom CA bundle from the environment
    (corporate/cloud proxies set REQUESTS_CA_BUNDLE or SSL_CERT_FILE) and the standard
    certifi roots. Some proxy bundles omit common roots, which breaks ordinary sites."""
    import os
    import tempfile
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent, "Accept-Language": "en-NZ,en;q=0.9"})
    custom = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if custom and os.path.isfile(custom):
        try:
            import certifi
            combined = Path(tempfile.gettempdir()) / "news-shorts-ca.pem"
            combined.write_bytes(Path(custom).read_bytes() + b"\n" + Path(certifi.where()).read_bytes())
            s.verify = str(combined)
            # requests lets REQUESTS_CA_BUNDLE override session.verify, so point it here too
            # (this process only)
            os.environ["REQUESTS_CA_BUNDLE"] = str(combined)
        except Exception:
            pass
    return s


def _phash(im):
    px = list(im.convert("L").resize((16, 16)).tobytes())
    avg = sum(px) / len(px)
    return hashlib.md5(bytes(1 if p > avg else 0 for p in px)).hexdigest()


class ImageStore:
    def __init__(self, project, min_width=600, min_height=300):
        self.dir = Path(project) / "images"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.dir / "images.json"
        self.min_width, self.min_height = min_width, min_height
        if self.meta_path.exists():
            self.meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        else:
            self.meta = {"article_url": None, "page_title": "", "site": "", "images": []}
        self.seen_urls = {self._key(e.get("url", "")) for e in self.meta["images"] if e.get("url")}
        self.seen_hashes = set()
        for e in self.meta["images"]:
            try:
                self.seen_hashes.add(_phash(Image.open(self.dir.parent / e["file"])))
            except Exception:
                pass

    @staticmethod
    def _key(url):
        return re.sub(r"[?#].*$", "", url or "")

    def seen(self, url):
        return self._key(url) in self.seen_urls

    def next_name(self):
        nums = [int(m.group(1)) for p in self.dir.glob("*.jpg") if (m := re.match(r"(\d+)", p.stem))]
        return f"{max(nums, default=0) + 1:02d}.jpg"

    def add(self, data: bytes, info: dict):
        """Validate and save image bytes. Returns (entry, None) or (None, reason)."""
        url = info.get("url", "")
        if url:
            self.seen_urls.add(self._key(url))
        try:
            im = Image.open(io.BytesIO(data))
            im.load()
        except Exception as e:
            return None, f"not an image ({e.__class__.__name__})"
        if im.width < self.min_width or im.height < self.min_height:
            return None, f"too small ({im.width}x{im.height})"
        ratio = im.width / im.height
        if ratio > 3.5 or ratio < 0.3:
            return None, "banner-shaped"
        h = _phash(im)
        if h in self.seen_hashes:
            return None, "duplicate"
        self.seen_hashes.add(h)
        name = self.next_name()
        im.convert("RGB").save(self.dir / name, quality=93)
        entry = {"file": f"images/{name}", "width": im.width, "height": im.height,
                 "kind": info.get("kind", "article"), "url": url,
                 "alt": (info.get("alt") or "").strip(), "caption": (info.get("caption") or "").strip(),
                 "credit": (info.get("credit") or "").strip(), "license": info.get("license", ""),
                 "license_url": info.get("license_url", ""), "author": info.get("author", ""),
                 "source_page": info.get("source_page", ""), "found_in": info.get("found_in", "")}
        self.meta["images"].append(entry)
        return entry, None

    def save(self):
        self.meta_path.write_text(json.dumps(self.meta, indent=2, ensure_ascii=False), encoding="utf-8")


def credit_line(entry, site=""):
    """Human-readable credit for upload.txt."""
    kind = entry.get("kind", "article")
    if kind == "licensed":
        parts = [entry.get("author") or "Unknown", entry.get("found_in", "")]
        lic = entry.get("license")
        line = " / ".join(p for p in parts if p)
        if lic:
            line += f", {lic}"
        if entry.get("source_page"):
            line += f" ({entry['source_page']})"
        return line
    if kind == "user":
        return entry.get("credit") or "Supplied by creator"
    credit = entry.get("credit") or site or "the original article"
    return f"{credit} (from the article)"
