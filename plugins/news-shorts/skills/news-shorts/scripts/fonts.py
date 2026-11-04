#!/usr/bin/env python3
"""Caption / headline fonts for news-shorts.

A font can be given as:
  - a preset name:            "anton"
  - a font file you added:    any .ttf/.otf in ~/.news-shorts/fonts/, by file name without
                              extension ("MyBrandFont-Bold")
  - a full path:              "/path/to/Font.ttf"

Usage:
    python fonts.py list
    python fonts.py sample out.jpg [--text "Tāmaki Makaurau consents up 31%"]
    python fonts.py check <font> "text to check"
"""
import argparse
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SKILL_DIR = Path(__file__).resolve().parent.parent
FONT_DIR = SKILL_DIR / "assets" / "fonts"
DATA_DIR = Path(os.environ.get("NEWS_SHORTS_HOME", Path.home() / ".news-shorts"))
USER_FONT_DIR = DATA_DIR / "fonts"

DEFAULT = "poppins"
PRESETS = {
    "poppins": ("Poppins-ExtraBold.ttf", "Clean, modern and rounded (default)"),
    "anton": ("Anton-Regular.ttf", "Tall and condensed, punchy - the classic Shorts look"),
    "bebas": ("BebasNeue-Regular.ttf", "All capitals, condensed - headline style"),
    "archivo": ("ArchivoBlack-Regular.ttf", "Very heavy and wide - maximum impact"),
    "serif": ("DMSerifDisplay-Regular.ttf", "Newspaper-style serif - more serious tone"),
    "slab": ("AlfaSlabOne-Regular.ttf", "Bold slab serif - editorial but strong"),
}
# narrow fonts look small at the same cap height, so presets can get a size boost
SIZE_BOOST = {"Anton-Regular.ttf": 1.15, "BebasNeue-Regular.ttf": 1.2}
REFERENCE_CAP = None  # cap height of Poppins at 100px, measured lazily


def config_default():
    cfg = DATA_DIR / "config.json"
    try:
        return json.loads(cfg.read_text()).get("font") if cfg.exists() else None
    except Exception:
        return None


def resolve(spec):
    """Return (name, path) for a font spec, or raise ValueError with the choices."""
    spec = (spec or config_default() or DEFAULT).strip()
    key = spec.lower()
    if key in PRESETS:
        return key, FONT_DIR / PRESETS[key][0]
    p = Path(os.path.expanduser(spec))
    if p.suffix.lower() in (".ttf", ".otf") and p.is_file():
        return p.stem, p
    for folder in (USER_FONT_DIR, FONT_DIR):
        for ext in (".ttf", ".otf", ".TTF", ".OTF"):
            cand = folder / f"{spec}{ext}"
            if cand.is_file():
                return cand.stem, cand
    raise ValueError(f"Unknown font '{spec}'. Presets: {', '.join(PRESETS)}; "
                     f"or put a .ttf/.otf in {USER_FONT_DIR} or give a full path.")


def _cap_height(font):
    box = font.getbbox("H")
    return box[3] - box[1]


def load(path, size):
    """Load a font at roughly the visual size Poppins has at `size` (matched by cap height),
    using the boldest weight if it is a variable font."""
    global REFERENCE_CAP
    if REFERENCE_CAP is None:
        REFERENCE_CAP = _cap_height(ImageFont.truetype(str(FONT_DIR / PRESETS[DEFAULT][0]), 100))
    probe = _bold(ImageFont.truetype(str(path), 100))
    scale = REFERENCE_CAP / max(1, _cap_height(probe)) * SIZE_BOOST.get(Path(path).name, 1.0)
    return _bold(ImageFont.truetype(str(path), max(8, round(size * scale))))


def _bold(font):
    try:
        axes = font.get_variation_axes()
        font.set_variation_by_axes([a["maximum"] if str(a.get("name", "")).lower().startswith(("weight", "wght"))
                                    else a["default"] for a in axes])
    except Exception:
        pass
    return font


def missing_glyphs(path, text):
    """Characters in text the font can't draw (empty set if fontTools isn't installed)."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return set()
    try:
        cmap = TTFont(str(path), fontNumber=0, lazy=True).getBestCmap()
    except Exception:
        return set()
    return {c for c in set(text) if not c.isspace() and ord(c) not in cmap}


def sample(out, text):
    """Grid of every preset (plus fonts in ~/.news-shorts/fonts) in the caption style."""
    names = list(PRESETS)
    if USER_FONT_DIR.is_dir():
        names += sorted(p.stem for p in USER_FONT_DIR.iterdir() if p.suffix.lower() in (".ttf", ".otf"))
    cols, tile_w, tile_h = 2, 540, 330
    rows = (len(names) + cols - 1) // cols
    im = Image.new("RGB", (cols * tile_w, rows * tile_h), (18, 24, 38))
    d = ImageDraw.Draw(im)
    label_font = ImageFont.truetype(str(FONT_DIR / "Poppins-SemiBold.ttf"), 26)
    words = text.split()
    accent = len(words) // 2
    for i, name in enumerate(names):
        x0, y0 = (i % cols) * tile_w, (i // cols) * tile_h
        d.rectangle((x0 + 6, y0 + 6, x0 + tile_w - 6, y0 + tile_h - 6), fill=(32, 44, 70))
        _, path = resolve(name)
        miss = missing_glyphs(path, text)
        d.text((x0 + 24, y0 + 18), f"{name}" + ("   (no macrons)" if miss else ""), font=label_font,
               fill=(255, 140, 140) if miss else (170, 185, 210))
        size = 50
        while True:  # shrink until it fits in two lines
            f = load(path, size)
            lines, line = [], ""
            for w in words:
                t = f"{line} {w}".strip()
                if f.getlength(t) > tile_w - 60 and line:
                    lines.append(line)
                    line = w
                else:
                    line = t
            lines.append(line)
            if len(lines) <= 2 or size <= 30:
                break
            size -= 4
        asc, desc = f.getmetrics()
        y = y0 + 80 + (220 - (asc + desc) * len(lines)) / 2
        k = 0
        for ln in lines:
            lw = f.getlength(ln)
            x = x0 + (tile_w - lw) / 2
            for w in ln.split():
                color = (255, 214, 10) if k == accent else (255, 255, 255)
                d.text((x, y), w, font=f, fill=color, stroke_width=6, stroke_fill=(0, 0, 0))
                x += f.getlength(w + " ")
                k += 1
            y += asc + desc
    im.save(out, quality=92)
    return names


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("sample")
    s.add_argument("out")
    s.add_argument("--text", default="Tāmaki Makaurau consents jump 31% this year")
    c = sub.add_parser("check")
    c.add_argument("font")
    c.add_argument("text")
    a = ap.parse_args()

    if a.cmd == "list":
        current = config_default() or DEFAULT
        for k, (f, desc) in PRESETS.items():
            print(f"  {k:8s} {desc}{'   <- your default' if k == current else ''}")
        if USER_FONT_DIR.is_dir():
            for p in sorted(USER_FONT_DIR.iterdir()):
                if p.suffix.lower() in (".ttf", ".otf"):
                    print(f"  {p.stem:8s} (your font){'   <- your default' if p.stem == current else ''}")
        print(f"Add your own: put .ttf/.otf files in {USER_FONT_DIR}")
    elif a.cmd == "sample":
        names = sample(a.out, a.text)
        print(f"Saved {a.out} ({len(names)} fonts)")
    else:
        name, path = resolve(a.font)
        miss = missing_glyphs(path, a.text)
        print(f"{name}: " + ("can draw everything" if not miss else f"missing {''.join(sorted(miss))}"))
        sys.exit(1 if miss else 0)


if __name__ == "__main__":
    main()
