---
name: news-shorts
description: Turn a pasted news article (text and/or URL) into a narrated 9:16 YouTube Short using the article's own photos, a free local Kokoro voice, and burned-in word-by-word captions. Use when the user pastes an article or link and asks for a short, reel, or news video.
---

# News Shorts

Paste an article in, get `short.mp4` + upload text out. You (Claude) do the editorial work
(reading, choosing photos, writing the script); the scripts do the media work.

`SKILL_DIR` below means the folder this file is in.
The voice model and Python environment live outside it, in `~/.news-shorts`
(or `$NEWS_SHORTS_HOME`), so plugin updates don't remove them.
Python to use: `~/.news-shorts/.venv/bin/python` (macOS/Linux) or
`%USERPROFILE%\.news-shorts\.venv\Scripts\python.exe` (Windows).

## 0. First run only

If that Python or `~/.news-shorts/models/kokoro-v1.0.onnx` is missing, run
`python SKILL_DIR/scripts/setup.py` (plain system Python 3.10+; `python3` on macOS/Linux).
It creates the venv, installs packages and downloads the ~350 MB voice model. It also
checks for ffmpeg; if ffmpeg is missing, tell the user how to install it
(`winget install ffmpeg`, `brew install ffmpeg`, or `sudo apt install ffmpeg`) and stop.

### Running in a cloud session (Claude app on phone/web)

Cloud sessions start empty and don't see the user's PC. If this skill was loaded as a
plugin, `SKILL_DIR` is already on disk. If not (e.g. the user just said "use my
news-shorts repo"):
1. Clone it: `git clone --depth 1 https://github.com/SamBadham1/news-shorts ~/news-shorts-repo`
   (attach the repo to the session first if the clone is refused). `SKILL_DIR` is then
   `~/news-shorts-repo/plugins/news-shorts/skills/news-shorts`.
2. Run `python3 SKILL_DIR/scripts/setup.py`. ffmpeg is normally preinstalled; the model
   comes from GitHub, which cloud sessions can reach. Takes about a minute.
3. Work in the session's working directory instead of `./shorts/`.
4. News sites are often blocked by the session's network allowlist. If `fetch_images.py`
   fails with a connection/proxy refusal, tell the user in one line to add the news site's
   domain under Settings > Capabilities (allowed domains) in claude.ai on the web, and ask
   them to attach the article's photos for now. Read the article text with the web fetch
   tool if the user only gave a link.
5. Deliver by sending `short.mp4` to the user as a file (they download it on their phone
   and upload to YouTube), and paste the contents of `upload.txt` in the reply so they can
   copy the title and description.

## 1. Set up the project

- Make `./shorts/<YYYY-MM-DD>-<short-slug>/` in the current working directory.
- Save the pasted article text to `article.txt` in it.
- Find the article URL: use the one the user gave; if they pasted only text, search the
  web for the headline to find the original page and confirm it matches. If none can be
  found, ask once for the link or for photos.

## 2. Get the photos

```
<python> SKILL_DIR/scripts/fetch_images.py "<url>" <project>
```

This saves `images/01.jpg ...` and `images/images.json` (alt text, captions, credits, site name).
If it fails (bot block, paywall) or finds nothing useful:
1. Fetch the page HTML another way (e.g. the browser, or ask the user to save the page)
   and run `fetch_images.py --html page.html <project>`.
2. Otherwise ask the user to drop photos into `<project>/images/`.

**Look at every image** (Read each file). Drop ads, author headshots, unrelated promos and
graphics full of small text. Note for each keeper what it shows and where the subject
sits (for `focus`). Too few images is fine: reuse them across scenes with different
`layout`/`focus` so the motion still varies.

## 3. Write `script.json`

```json
{
  "title": "YouTube title, max ~60 chars, factual, no clickbait",
  "headline": "4-7 word on-screen headline",
  "kicker": "BREAKING | NEWS | UPDATE | EXPLAINED (or omit)",
  "source": "Outlet name",
  "article_url": "https://...",
  "image_credit": "Photo credits from images.json, else the outlet name",
  "voice": "am_michael",
  "speed": 1.1,
  "emphasis": ["key", "words", "to", "colour"],
  "description": "2-3 sentence summary for YouTube.",
  "hashtags": ["#news", "#topic", "#shorts"],
  "scenes": [
    {"text": "Narration for this scene.", "image": "images/01.jpg",
     "layout": "fill", "focus": [0.5, 0.4]}
  ]
}
```

Narration rules:
- **Hook first**: sentence one (max ~12 words) states the most surprising concrete fact.
- **Length**: 90-130 words total (~35-50 s at speed 1.1). 4-7 scenes, 1-2 sentences each.
- **Accuracy**: only facts in the article. Attribute claims ("police say", "according to the
  report"). No speculation, no added opinion, nothing more dramatic than the source.
- **Write for the ear**: short sentences, plain words. Write numbers as they should be
  spoken when ambiguous ("4.5 million dollars", not "$4.5m"; "twenty twenty-six" is not
  needed, "2026" reads fine). Expand acronyms the first time unless universally known.
- **Close**: one short line, either the "what happens next" fact or a brief
  "Follow for more news in under a minute." Never both.
- `emphasis`: 3-6 single words (names, numbers, key nouns) that should always be yellow.

Visual rules:
- One photo per scene; match each photo to what is being said.
- `layout`: `fill` (full-screen push-in, best for people and portrait photos),
  `pan` (full-screen slow pan across a wide photo, good for landscapes and crowds),
  `fit` (whole photo on blurred backdrop, use when cropping would cut out what matters).
  Omit it to auto-choose (fit for wide, fill for tall).
- `focus`: `[x, y]` from 0-1 for where the subject is, so `fill` crops toward it.
- Captions sit about 70% down the frame; avoid layouts that put a face right there.

Voices: `am_michael` (default, US male), `af_heart` / `af_bella` (US female),
`bm_george` / `bm_daniel` (UK male), `bf_emma` (UK female). Use the user's preference if known.

## 4. Build

```
<python> SKILL_DIR/scripts/build.py <project>            # full render
<python> SKILL_DIR/scripts/build.py <project> --preview  # first 8 s only, fast check
<python> SKILL_DIR/scripts/build.py <project> --music path/to/track.mp3
```

Voice clips are cached per sentence, so re-building after a text tweak only re-voices
the changed sentences. Only add `--music` when the user supplies a track they have rights to
(e.g. from the YouTube Audio Library); it is auto-ducked under the voice.

## 5. Check, then deliver

Make a contact sheet and look at it:
```
ffmpeg -loglevel error -y -i <project>/short.mp4 -vf "fps=1/5,scale=360:-1,tile=6x2" -frames:v 1 <project>/build/sheet.jpg
```
Check that captions are readable, no face is covered, and every photo matches its line.
Fix `script.json` and rebuild if not.

Tell the user, briefly: the path to `short.mp4`, the duration, the narration text (so they
can proof it), and that `upload.txt` (title, description, credits, hashtags) and
`captions.srt` are next to it. Remind them once per session that news photos usually
belong to the outlet or a photo agency, so credits stay in the description.
