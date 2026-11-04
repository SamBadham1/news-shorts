#!/usr/bin/env python3
"""One-time setup: venv, Python packages, Kokoro voice model, ffmpeg check.

Run with any Python 3.10+:  python scripts/setup.py

The venv and model live in ~/.news-shorts (override with NEWS_SHORTS_HOME), outside
the skill folder, so plugin updates don't wipe them or re-download 350 MB.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("NEWS_SHORTS_HOME", Path.home() / ".news-shorts"))
VENV = DATA / ".venv"
MODELS = DATA / "models"
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
FILES = ["kokoro-v1.0.onnx", "voices-v1.0.bin"]


def venv_python():
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def download(url, dest):
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {dest.name}: {done * 100 // total}%", end="", flush=True)
    print()
    tmp.replace(dest)


BROWSER_CHECK = r"""
import os, sys
from playwright.sync_api import sync_playwright
chans = (["msedge"] if os.name == "nt" else []) + ["chrome", None]
with sync_playwright() as p:
    for ch in chans:
        try:
            b = p.chromium.launch(channel=ch, headless=True) if ch else p.chromium.launch(headless=True)
            print(ch or "chromium"); b.close(); sys.exit(0)
        except Exception:
            pass
sys.exit(1)
"""


def check_browser():
    """Find a browser Playwright can drive (Edge/Chrome already installed, else download Chromium)."""
    py = str(venv_python())
    r = subprocess.run([py, "-c", BROWSER_CHECK], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"browser: {r.stdout.strip()} (for sites that block plain downloads)")
        return
    print("Downloading a browser for sites that block plain downloads (~150 MB)...")
    if subprocess.run([py, "-m", "playwright", "install", "chromium"]).returncode != 0:
        print("browser: could not install; photo fetching will use plain downloads only")


def save_setting(key, value, label):
    cfg = DATA / "config.json"
    data = json.loads(cfg.read_text()) if cfg.exists() else {}
    data[key] = value.strip()
    DATA.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(data, indent=2))
    print(f"{label} saved to {cfg}")


def main():
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is required.")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pexels-key", help="save a free Pexels API key for stock photo search")
    ap.add_argument("--font", help="save a default caption font (see scripts/fonts.py list)")
    a = ap.parse_args()
    if a.pexels_key:
        save_setting("pexels_api_key", a.pexels_key, "Pexels key")
    if a.font:
        save_setting("font", a.font, f"Default font '{a.font}'")
    if (a.font or a.pexels_key) and venv_python().exists():
        return  # just changing settings on an existing install

    if not venv_python().exists():
        print("Creating virtual environment...")
        venv.create(VENV, with_pip=True)
    print("Installing packages...")
    subprocess.check_call([str(venv_python()), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([str(venv_python()), "-m", "pip", "install", "-q", "-r",
                           str(ROOT / "requirements.txt")])

    MODELS.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dest = MODELS / name
        if dest.exists() and dest.stat().st_size > 1_000_000:
            continue
        print(f"Downloading {name}...")
        download(MODEL_URL + name, dest)

    if shutil.which("ffmpeg"):
        print("ffmpeg: found")
    else:
        print("ffmpeg: NOT FOUND. Install it, then you're ready:\n"
              "  Windows: winget install ffmpeg\n  macOS:   brew install ffmpeg\n"
              "  Linux:   sudo apt install ffmpeg")
        sys.exit(1)
    check_browser()
    if not (DATA / "config.json").exists() and not os.environ.get("PEXELS_API_KEY"):
        print("optional: free Pexels key for stock photos -> setup.py --pexels-key YOUR_KEY "
              "(get one at https://www.pexels.com/api/)")
    print(f"Setup complete. Use {venv_python()} to run the scripts.")


if __name__ == "__main__":
    main()
