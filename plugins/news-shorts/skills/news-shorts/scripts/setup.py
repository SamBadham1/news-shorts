#!/usr/bin/env python3
"""One-time setup: venv, Python packages, Kokoro voice model, ffmpeg check.

Run with any Python 3.10+:  python scripts/setup.py

The venv and model live in ~/.news-shorts (override with NEWS_SHORTS_HOME), outside
the skill folder, so plugin updates don't wipe them or re-download 350 MB.
"""
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


def main():
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10 or newer is required.")

    if not venv_python().exists():
        print("Creating virtual environment...")
        venv.create(VENV, with_pip=True)
    print("Installing packages...")
    subprocess.check_call([str(venv_python()), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([str(venv_python()), "-m", "pip", "install", "-q", "-r",
                           str(ROOT / "requirements.txt")])

    MODELS.mkdir(exist_ok=True)
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
    print(f"Setup complete. Use {venv_python()} to run the scripts.")


if __name__ == "__main__":
    main()
