#!/usr/bin/env python3
"""Turn <project>/script.json into a finished 1080x1920 YouTube Short.

Usage:
    python build.py <project_dir> [--music track.mp3] [--fps 30] [--preview]

Steps: Kokoro voiceover per sentence (cached) -> word-level caption timing ->
frames rendered with PIL (photo motion, captions, header, progress bar) ->
piped into ffmpeg with the narration (optionally ducked music), loudness at -14 LUFS.

Outputs in <project_dir>: short.mp4, captions.srt, upload.txt
"""
import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fonts  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("NEWS_SHORTS_HOME", Path.home() / ".news-shorts"))
MODEL = DATA_DIR / "models" / "kokoro-v1.0.onnx"
VOICES = DATA_DIR / "models" / "voices-v1.0.bin"
FONT_BOLD = str(SKILL_DIR / "assets" / "fonts" / "Poppins-ExtraBold.ttf")
FONT_SEMI = str(SKILL_DIR / "assets" / "fonts" / "Poppins-SemiBold.ttf")

W, H = 1080, 1920
SR = 24000
SENTENCE_GAP = 0.14      # silence between sentences (s)
SCENE_GAP = 0.22         # extra silence between scenes (s)
TAIL = 0.8               # hold after the last word (s)
XFADE = 0.25             # crossfade between scenes (s)

CAPTION_Y = 1330         # vertical centre of captions (above the Shorts UI)
CAPTION_MAX_W = 820      # keeps clear of the like/comment buttons on the right
CAPTION_SIZE = 76
ACCENT = (255, 214, 10)  # active-word colour
KICKER_BG = (220, 38, 38)


# ----------------------------------------------------------------------------- text + timing

def split_sentences(text):
    text = re.sub(r"\s+", " ", text.strip())
    parts = re.split(r"(?<=[.!?])\s+(?=[\"'A-Z0-9])", text)
    return [p for p in parts if p.strip()]


def syllables(word):
    w = re.sub(r"[^a-z0-9]", "", word.lower())
    if not w:
        return 0.5
    if w.isdigit():
        return 1.2 * len(w)
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and n > 1 and not w.endswith(("le", "ee")):
        n -= 1
    return max(1, n) + sum(1.2 for _ in re.findall(r"\d", w))


def word_weights(words):
    out = []
    for w in words:
        wt = syllables(w) + 0.35
        if re.search(r"[,;:—-]$", w):
            wt += 1.0
        out.append(wt)
    return out


def trim_silence(audio, thresh=0.01):
    idx = np.where(np.abs(audio) > thresh)[0]
    if len(idx) == 0:
        return audio
    start = max(0, idx[0] - int(0.02 * SR))
    end = min(len(audio), idx[-1] + int(0.06 * SR))
    return audio[start:end]


# ----------------------------------------------------------------------------- voice

def synthesize(project, script):
    from kokoro_onnx import Kokoro
    if not MODEL.exists():
        sys.exit(f"Voice model missing at {MODEL}. Run scripts/setup.py first.")
    voice = script.get("voice", "am_michael")
    speed = float(script.get("speed", 1.1))
    lang = "en-gb" if voice.startswith(("b", "B")) else "en-us"
    cache = project / "build" / "tts"
    cache.mkdir(parents=True, exist_ok=True)
    kokoro = None

    pieces, words, scenes_t = [], [], []
    t = 0.0
    for si, scene in enumerate(script["scenes"]):
        scene_start = t
        for sent in split_sentences(scene["text"]):
            key = hashlib.sha1(f"{voice}|{speed}|{sent}".encode()).hexdigest()[:16]
            wav = cache / f"{key}.wav"
            if wav.exists():
                audio, _ = sf.read(wav, dtype="float32")
            else:
                if kokoro is None:
                    kokoro = Kokoro(str(MODEL), str(VOICES))
                audio, sr = kokoro.create(sent, voice=voice, speed=speed, lang=lang)
                audio = trim_silence(np.asarray(audio, dtype="float32"))
                sf.write(wav, audio, SR)
            dur = len(audio) / SR
            ws = sent.split()
            wts = word_weights(ws)
            total = sum(wts)
            acc = t
            for w, wt in zip(ws, wts):
                d = dur * wt / total
                words.append({"word": w, "start": acc, "end": acc + d, "scene": si})
                acc += d
            pieces.append(audio)
            pieces.append(np.zeros(int(SENTENCE_GAP * SR), dtype="float32"))
            t += dur + SENTENCE_GAP
            print(f"  voice  scene {si + 1}: {dur:4.1f}s  {sent[:60]}")
        pieces.append(np.zeros(int(SCENE_GAP * SR), dtype="float32"))
        t += SCENE_GAP
        scenes_t.append([scene_start, t])
    pieces.append(np.zeros(int(TAIL * SR), dtype="float32"))
    t += TAIL
    scenes_t[-1][1] = t
    narration = np.concatenate(pieces)
    sf.write(project / "build" / "narration.wav", narration, SR)
    return words, scenes_t, len(narration) / SR


def caption_chunks(words, max_words=3, max_chars=20):
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text = " ".join(x["word"] for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end_of_phrase = re.search(r"[.!?,;:]$", w["word"]) is not None
        if (len(cur) >= max_words or len(text) >= max_chars or end_of_phrase
                or nxt is None or nxt["scene"] != w["scene"]):
            chunks.append({"words": cur, "start": cur[0]["start"], "end": cur[-1]["end"]})
            cur = []
    # let each chunk stay up until the next one starts (no flicker in small gaps)
    for a, b in zip(chunks, chunks[1:]):
        if b["start"] - a["end"] < 0.45:
            a["end"] = b["start"]
    return chunks


# ----------------------------------------------------------------------------- drawing helpers

def clean_word(w):
    return w.strip()


class CaptionRenderer:
    def __init__(self, emphasis, font_path=FONT_BOLD, scale=1.0):
        size = round(CAPTION_SIZE * scale)
        self.font = fonts.load(font_path, size)
        self.stroke = max(5, round(9 * size / CAPTION_SIZE))
        self.emphasis = {e.lower() for e in emphasis}
        self.cache = {}

    def render(self, chunk, active):
        key = (id(chunk), active)
        if key in self.cache:
            return self.cache[key]
        words = [clean_word(w["word"]) for w in chunk["words"]]
        stroke = self.stroke
        space = self.font.getlength(" ")
        widths = [self.font.getlength(w) for w in words]
        # wrap into lines that fit CAPTION_MAX_W
        lines, line, lw = [], [], 0
        for i, wd in enumerate(widths):
            add = wd + (space if line else 0)
            if line and lw + add > CAPTION_MAX_W:
                lines.append(line)
                line, lw = [], 0
                add = wd
            line.append(i)
            lw += add
        lines.append(line)
        asc, desc = self.font.getmetrics()
        lh = asc + desc
        img_h = lh * len(lines) + stroke * 2 + 10
        img = Image.new("RGBA", (W, img_h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y = stroke
        for ln in lines:
            total = sum(widths[i] for i in ln) + space * (len(ln) - 1)
            x = (W - total) / 2
            for i in ln:
                plain = re.sub(r"[^\w']", "", words[i]).lower()
                color = ACCENT if (i == active or plain in self.emphasis) else (255, 255, 255)
                if i == active:
                    color = ACCENT
                d.text((x, y), words[i], font=self.font, fill=color,
                       stroke_width=stroke, stroke_fill=(0, 0, 0))
                x += widths[i] + space
            y += lh
        self.cache[key] = img
        return img


def cover(im, w, h):
    s = max(w / im.width, h / im.height)
    return im.resize((math.ceil(im.width * s), math.ceil(im.height * s)), Image.LANCZOS)


def make_background(im):
    bg = cover(im.convert("RGB"), W // 4, H // 4)
    bg = bg.crop(((bg.width - W // 4) // 2, (bg.height - H // 4) // 2,
                  (bg.width - W // 4) // 2 + W // 4, (bg.height - H // 4) // 2 + H // 4))
    bg = bg.filter(ImageFilter.GaussianBlur(10)).resize((W, H), Image.BICUBIC)
    return Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.55)


def ease(p):
    return 0.5 - 0.5 * math.cos(math.pi * min(max(p, 0), 1))


class SceneRenderer:
    """Draws the photo layer for one scene at time p (0..1)."""

    def __init__(self, path, layout, focus, direction):
        src = Image.open(path).convert("RGB")
        self.layout = layout or ("fit" if src.width / src.height > 0.9 else "fill")
        self.fx, self.fy = focus or (0.5, 0.42)
        self.dir = direction
        self.bg = make_background(src)
        if self.layout == "fit":
            target_w = W * 1.15
        else:
            target_w = max(W * 1.25, H * 1.25 * src.width / src.height)
        if src.width > target_w * 1.5:
            s = target_w * 1.5 / src.width
            src = src.resize((int(src.width * s), int(src.height * s)), Image.LANCZOS)
        self.src = src

    def frame(self, p):
        e = ease(p)
        src = self.src
        if self.layout == "fit":
            z = 1.0 + 0.10 * (e if self.dir > 0 else 1 - e)
            s = W / src.width * z
            out_h = int(min(H * 0.62, src.height * s))
            cx, cy = src.width * 0.5 + (self.fx - 0.5) * src.width * (z - 1), src.height * 0.5
            data = (1 / s, 0, cx - (W / 2) / s, 0, 1 / s, cy - (out_h / 2) / s)
            fg = src.transform((W, out_h), Image.AFFINE, data, resample=Image.BICUBIC)
            frame = self.bg.copy()
            top = int(860 - out_h / 2)
            frame.paste(fg, (0, top))
            return frame
        base = max(W / src.width, H / src.height)
        if self.layout == "pan":
            z = 1.04
            s = base * z
            view_w = W / s
            span = max(0.0, src.width - view_w)
            frac = e if self.dir > 0 else 1 - e
            cx = view_w / 2 + span * frac
            cy = src.height * self.fy if src.height * s > H else src.height / 2
            view_h = H / s
            cy = min(max(cy, view_h / 2), src.height - view_h / 2)
        else:  # fill: slow push-in toward the focus point
            z = 1.04 + 0.12 * (e if self.dir > 0 else 1 - e)
            s = base * z
            view_w, view_h = W / s, H / s
            cx = min(max(src.width * self.fx, view_w / 2), src.width - view_w / 2)
            cy = min(max(src.height * self.fy, view_h / 2), src.height - view_h / 2)
        data = (1 / s, 0, cx - (W / 2) / s, 0, 1 / s, cy - (H / 2) / s)
        return src.transform((W, H), Image.AFFINE, data, resample=Image.BICUBIC)


def build_overlay(script, headline_font=FONT_BOLD):
    """Static layer: top/bottom shading, kicker pill, headline, source label."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    grad = np.zeros((H, 1), dtype=np.float32)
    ys = np.arange(H)
    grad[:, 0] = np.clip((ys - 1050) / 500, 0, 1) * 0.55 + np.clip((330 - ys) / 330, 0, 1) * 0.45
    alpha = (np.repeat(grad, W, axis=1) * 255).astype(np.uint8)
    ov.putalpha(Image.fromarray(alpha))
    d = ImageDraw.Draw(ov)
    y = 150
    kicker = (script.get("kicker") or "").upper().strip()
    if kicker:
        f = fonts.load(headline_font, 40)
        tw = f.getlength(kicker)
        d.rounded_rectangle((60, y, 60 + tw + 48, y + 66), radius=12, fill=KICKER_BG)
        box = d.textbbox((0, 0), kicker, font=f)
        d.text((60 + 24, y + 33 - (box[1] + box[3]) / 2), kicker, font=f, fill=(255, 255, 255))
        y += 86
    headline = (script.get("headline") or "").strip()
    if headline:
        f = fonts.load(headline_font, 50)
        line_h = round(sum(f.getmetrics()) * 1.05)
        words, line, lines = headline.split(), "", []
        for w in words:
            test = f"{line} {w}".strip()
            if f.getlength(test) > W - 140 and line:
                lines.append(line)
                line = w
            else:
                line = test
        lines.append(line)
        for ln in lines[:3]:
            d.text((60, y), ln, font=f, fill=(255, 255, 255), stroke_width=4, stroke_fill=(0, 0, 0))
            y += line_h
    source = (script.get("source") or "").strip()
    if source:
        f = ImageFont.truetype(FONT_SEMI, 30)
        d.text((62, y + 8), f"Source: {source}", font=f, fill=(235, 235, 235),
               stroke_width=3, stroke_fill=(0, 0, 0))
    return ov


# ----------------------------------------------------------------------------- render

def pick_font(spec, text, what):
    """Resolve a font spec; fall back to the default if it's unknown or can't draw the text
    (e.g. a font without macrons for te reo Maori words)."""
    try:
        name, path = fonts.resolve(spec)
    except ValueError as e:
        print(f"  font: {e} Using {fonts.DEFAULT}.")
        return fonts.FONT_DIR / fonts.PRESETS[fonts.DEFAULT][0]
    miss = fonts.missing_glyphs(path, text)
    if miss:
        print(f"  font: {name} can't draw {''.join(sorted(miss))} in the {what}; using {fonts.DEFAULT}.")
        return fonts.FONT_DIR / fonts.PRESETS[fonts.DEFAULT][0]
    print(f"  font ({what}): {name}")
    return path


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--music", help="optional background music file (ducked under the voice)")
    ap.add_argument("--music-volume", type=float, default=0.18)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--preview", action="store_true", help="first 8 seconds only, for a quick look")
    ap.add_argument("--font", help="caption/headline font: preset name, your font's name, or a "
                                   ".ttf/.otf path (overrides script.json); see fonts.py list")
    a = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found on PATH - install it first (see README).")
    project = Path(a.project).resolve()
    script = json.loads((project / "script.json").read_text(encoding="utf-8"))
    for s in script["scenes"]:
        if not (project / s["image"]).exists():
            sys.exit(f"Missing image: {s['image']}")
    (project / "build").mkdir(exist_ok=True)

    # fonts: --font > script.json > ~/.news-shorts/config.json > poppins
    all_text = " ".join(s["text"] for s in script["scenes"])
    caption_font = pick_font(a.font or script.get("font"), all_text, "captions")
    headline_font = pick_font(script.get("headline_font") or a.font or script.get("font"),
                              f"{script.get('headline', '')} {(script.get('kicker') or '').upper()}",
                              "headline")
    font_scale = float(script.get("font_scale", 1.0))

    t0 = time.time()
    words, scenes_t, total = synthesize(project, script)
    chunks = caption_chunks(words)
    print(f"Voiceover: {total:.1f}s, {len(words)} words, {len(chunks)} caption chunks")
    if total > 60:
        print("  NOTE: over 60s. Shorts allow up to 3 minutes, but 30-55s performs best.")

    # captions.srt for YouTube upload
    with open(project / "captions.srt", "w", encoding="utf-8") as f:
        for i, c in enumerate(chunks, 1):
            f.write(f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n"
                    f"{' '.join(w['word'] for w in c['words'])}\n\n")

    fps = a.fps
    duration = min(total, 8.0) if a.preview else total
    n_frames = int(math.ceil(duration * fps))
    out_path = project / ("preview.mp4" if a.preview else "short.mp4")

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-i", str(project / "build" / "narration.wav")]
    if a.music:
        cmd += ["-stream_loop", "-1", "-i", a.music]
        filt = (f"[1:a]asplit=2[v1][v2];[2:a]volume={a.music_volume}[m];"
                "[m][v2]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[md];"
                "[v1][md]amix=inputs=2:duration=first:normalize=0,"
                "loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        filt = "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    cmd += ["-filter_complex", filt, "-map", "0:v", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{duration:.3f}",
            "-movflags", "+faststart", str(out_path)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    overlay = build_overlay(script, headline_font)
    captions = CaptionRenderer(script.get("emphasis", []), caption_font, font_scale)
    renderers = {}

    def scene_renderer(i):
        if i not in renderers:
            sc = script["scenes"][i]
            renderers[i] = SceneRenderer(project / sc["image"], sc.get("layout"),
                                         sc.get("focus"), 1 if i % 2 == 0 else -1)
        return renderers[i]

    def photo_at(i, t):
        st, en = scenes_t[i]
        en += XFADE
        return scene_renderer(i).frame((t - st) / (en - st))

    ci = 0
    last_progress = -1
    for fi in range(n_frames):
        t = fi / fps
        si = next((i for i, (st, en) in enumerate(scenes_t) if st <= t < en), len(scenes_t) - 1)
        frame = photo_at(si, t)
        since = t - scenes_t[si][0]
        if si > 0 and since < XFADE:
            prev = photo_at(si - 1, t)
            frame = Image.blend(prev, frame, ease(since / XFADE))
        frame = frame.convert("RGBA")
        frame.alpha_composite(overlay)

        # progress bar
        d = ImageDraw.Draw(frame)
        d.rectangle((0, 0, int(W * t / total), 10), fill=ACCENT + (255,))

        # captions
        while ci < len(chunks) - 1 and t >= chunks[ci + 1]["start"]:
            ci += 1
        c = chunks[ci]
        if c["start"] - 0.05 <= t <= c["end"] + 0.15:
            active = 0
            for k, w in enumerate(c["words"]):
                if t >= w["start"]:
                    active = k
            cap = captions.render(c, active)
            age = t - c["start"]
            if 0 <= age < 0.12:  # small pop-in
                sc = 0.86 + 0.14 * ease(age / 0.12)
                cap = cap.resize((int(cap.width * sc), int(cap.height * sc)), Image.BILINEAR)
            frame.alpha_composite(cap, (int((W - cap.width) / 2), int(CAPTION_Y - cap.height / 2)))

        proc.stdin.write(frame.convert("RGB").tobytes())
        pct = int(100 * fi / n_frames)
        if pct % 10 == 0 and pct != last_progress:
            print(f"  render {pct}%", flush=True)
            last_progress = pct
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit("ffmpeg failed")

    # upload notes
    tags = " ".join(script.get("hashtags", []))
    upload = [f"TITLE:\n{script.get('title', '')}\n",
              f"DESCRIPTION:\n{script.get('description', '').strip()}\n"]
    if script.get("article_url"):
        upload.append(f"Source: {script['article_url']}")
    credit_lines, kinds = image_credits(project, script)
    if credit_lines:
        upload.append("Images:\n" + "\n".join(f"- {c}" for c in credit_lines))
    upload.append(f"\n{tags}\n")
    (project / "upload.txt").write_text("\n".join(upload), encoding="utf-8")

    print(f"Done in {time.time() - t0:.0f}s -> {out_path}")
    if kinds:
        print("Image rights: " + ", ".join(f"{n} {k}" for k, n in kinds.items()))
        if kinds.get("from article"):
            print("  Article photos are usually owned by the outlet or a photo agency.")


def image_credits(project, script):
    """Credit lines for the images actually used, plus a count by rights type."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from imagestore import credit_line
    meta_path = project / "images" / "images.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"images": []}
    by_file = {e["file"]: e for e in meta.get("images", [])}
    site = script.get("source") or meta.get("site", "")
    lines, kinds = [], {}
    for f in dict.fromkeys(s["image"] for s in script["scenes"]):
        e = by_file.get(f, {"kind": "user", "file": f})
        line = credit_line(e, site)
        if line not in lines:
            lines.append(line)
        label = {"article": "from article", "licensed": "freely licensed"}.get(e.get("kind"), "supplied")
        kinds[label] = kinds.get(label, 0) + 1
    if script.get("image_credit"):
        lines.append(script["image_credit"])
    return lines, kinds


if __name__ == "__main__":
    main()
