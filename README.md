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
(`winget install ffmpeg` / `brew install ffmpeg` / `sudo apt install ffmpeg`).

## Use

Paste an article and say *"make a news short from this"* (in Claude Code you can also type
`/news-shorts:news-shorts`). Output goes to `./shorts/<date>-<slug>/`:

| File | What it is |
|---|---|
| `short.mp4` | The finished Short (H.264/AAC, 30 fps, about -14 LUFS) |
| `upload.txt` | Title, description, source link, image credits, hashtags |
| `captions.srt` | Caption file you can upload to YouTube |
| `script.json` | The script; edit it and ask Claude to rebuild |

In cloud sessions (Claude app on phone/web), news sites must be allowed under
Settings > Capabilities (allowed domains) for the photo download to work; otherwise
attach the photos to the chat.

## Layout

```
.claude-plugin/marketplace.json                 marketplace listing
plugins/news-shorts/.claude-plugin/plugin.json  plugin manifest
plugins/news-shorts/skills/news-shorts/
  SKILL.md                instructions Claude follows
  scripts/setup.py        one-time setup (venv + voice model in ~/.news-shorts)
  scripts/fetch_images.py pulls photos + captions/credits from the article page
  scripts/build.py        voice, captions, motion, render
  assets/fonts/           Poppins (SIL Open Font License)
```

To add another skill later, add `plugins/<name>/` with its own `plugin.json` and
`skills/<name>/SKILL.md`, and list it in `marketplace.json`.

## Note on images

Photos on news sites are usually owned by the outlet or a photo agency (AP, Reuters,
Getty). Using them in a monetised channel can lead to Content ID claims or takedowns.
The pipeline always puts credits in `upload.txt`; check the rights for each story.
