# news-shorts

A Claude skill (packaged as a plugin) that turns a news article into a YouTube Short:
paste the article or its link, and Claude pulls the article's photos, writes a ~45-second
script, voices it with a free offline voice (Kokoro), and renders a 1080x1920 video with
word-by-word captions.

## Install

This repo is a plugin marketplace called `sam-skills` containing the `news-shorts` plugin.

**Claude app (desktop / web):** Customize > Plugins > Add marketplace, paste
`https://github.com/SamBadham1/news-shorts`, then install **news-shorts**. Menu names
change from time to time; look for "plugins" or "marketplace" in Customize or Settings.

**Claude Code (terminal):**

```
/plugin marketplace add SamBadham1/news-shorts
/plugin install news-shorts@sam-skills
```

Or from your shell: `claude plugin install news-shorts --marketplace SamBadham1/news-shorts`.
Update later with `/plugin` > Marketplaces > sam-skills > Update marketplace
(or turn on auto-update there).

**First run** (Claude does this for you): installs Python packages and downloads the
~350 MB voice model into `~/.news-shorts`. Requires Python 3.10+ and ffmpeg
(`winget install ffmpeg` / `brew install ffmpeg` / `sudo apt install ffmpeg`). It uses
Edge or Chrome if installed for sites that block plain downloads, otherwise downloads
Chromium (~150 MB).

**Optional, recommended:** a free [Pexels API key](https://www.pexels.com/api/) for stock
photos of generic scenes. Save it once with
`python <skill folder>/scripts/setup.py --pexels-key YOUR_KEY`, or paste it to Claude.

## Fonts

Captions and the headline can use any of six bundled fonts, all free (SIL Open Font
License) and all able to show te reo Māori macrons:

| Name | Look |
|---|---|
| `poppins` | Clean, modern and rounded (default) |
| `anton` | Tall and condensed, punchy - the classic Shorts look |
| `bebas` | All capitals, condensed - headline style |
| `archivo` | Very heavy and wide - maximum impact |
| `serif` | Newspaper-style serif - more serious tone |
| `slab` | Bold slab serif - editorial but strong |

Ask for one in your request ("use anton"), pick one at the review step (Claude shows a
sample sheet), or set a default with `setup.py --font anton` (or just tell Claude "always
use anton"). To use your own brand font, put the .ttf/.otf in `~/.news-shorts/fonts/` (or
attach it in chat) and ask for it by file name. If a font can't draw a character in the
script, such as a macron, the build falls back to Poppins and says so.

## Where the photos come from

Claude works down a chain until it has at least 3 relevant photos:

1. **The article** - plain download, then a real headless browser if the site blocks it
   or loads photos with JavaScript.
2. **Freely licensed photos** - Wikimedia Commons (named people, places, landmarks;
   no key) and Pexels (generic scenes; free key).
3. **Your browser** - if Claude in Chrome or the desktop browser is available.
4. **You** - Claude asks you to attach 2-3 photos.

`upload.txt` lists a credit and licence for every photo used, and the build reports how
many came from the article (outlet-owned, may get Content ID claims) versus freely
licensed (safe to monetise with credit).

## Use

Paste an article and say *"make a news short from this"* (in Claude Code you can also type
`/news-shorts:news-shorts`). Output goes to `./shorts/<date>-<slug>/`:

| File | What it is |
|---|---|
| `short.mp4` | The finished Short (H.264/AAC, 30 fps, about -14 LUFS) |
| `upload.txt` | Title, description, source link, image credits, hashtags |
| `captions.srt` | Caption file you can upload to YouTube |
| `script.json` | The script; edit it and ask Claude to rebuild |

In cloud sessions (Claude app on phone/web), add these under Settings > Capabilities
(allowed domains) in claude.ai: the news sites you use, `commons.wikimedia.org`,
`upload.wikimedia.org`, `api.pexels.com` and `images.pexels.com`. On a Team or
Enterprise plan an admin can set this once for everyone.

## Layout

```
.claude-plugin/marketplace.json                 marketplace listing
plugins/news-shorts/.claude-plugin/plugin.json  plugin manifest
plugins/news-shorts/skills/news-shorts/
  SKILL.md                instructions Claude follows
  scripts/setup.py        one-time setup (venv + voice model in ~/.news-shorts)
  scripts/fetch_images.py pulls photos + captions/credits from the article page
                          (plain download, then headless browser)
  scripts/stock_images.py searches Wikimedia Commons / Pexels, records licences
  scripts/imagestore.py   shared validation, de-duplication and credit lines
  scripts/build.py        voice, captions, motion, render
  assets/fonts/           Poppins (SIL Open Font License)
```

To add another skill later, add `plugins/<name>/` with its own `plugin.json` and
`skills/<name>/SKILL.md`, and list it in `marketplace.json`.

## Note on images

Photos on news sites are usually owned by the outlet or a photo agency (AP, Reuters,
Getty). Using them in a monetised channel can lead to Content ID claims or takedowns.
The pipeline always puts credits in `upload.txt`; check the rights for each story.
