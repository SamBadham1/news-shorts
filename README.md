# news-shorts

A Claude Code skill that turns a news article into a YouTube Short: paste the article
(or its link), and Claude pulls the article's photos, writes a ~45-second script, voices
it with a free offline voice (Kokoro), and renders a 1080x1920 video with word-by-word
captions.

## Install

Requires Python 3.10+, ffmpeg and git.

```bash
# personal skill, available in every Claude Code project
git clone https://github.com/SamBadham1/news-shorts ~/.claude/skills/news-shorts
python ~/.claude/skills/news-shorts/scripts/setup.py
```

On Windows the skills folder is `%USERPROFILE%\.claude\skills\`.
`setup.py` creates a private virtualenv in `.venv/` and downloads the voice model
(~350 MB, into `models/`, which is git-ignored). Update later with `git pull`.

### From the Claude app (phone / web)

Start a chat, say *"use my news-shorts repo"* and paste an article. Claude clones this
repo into its cloud workspace, runs setup (~1 minute), and sends back the finished video.
News sites must be allowed under Settings > Capabilities (allowed domains) for the photo
download to work; otherwise attach the photos to the chat.

## Use

In Claude Code, paste an article and say something like *"make a news short from this"*,
or invoke it directly with `/news-shorts`. Output goes to `./shorts/<date>-<slug>/`:

| File | What it is |
|---|---|
| `short.mp4` | The finished Short (H.264/AAC, 30 fps, -14 LUFS) |
| `upload.txt` | Title, description, source link, image credits, hashtags |
| `captions.srt` | Caption file you can upload to YouTube |
| `script.json` | The script; edit it and ask Claude to rebuild |

You can also run the steps yourself:

```bash
PY=~/.claude/skills/news-shorts/.venv/bin/python
$PY ~/.claude/skills/news-shorts/scripts/fetch_images.py "<article-url>" shorts/my-story
# write shorts/my-story/script.json (see SKILL.md for the format)
$PY ~/.claude/skills/news-shorts/scripts/build.py shorts/my-story [--music track.mp3]
```

## Layout

```
SKILL.md              instructions Claude follows
scripts/setup.py      one-time setup
scripts/fetch_images.py   pulls photos + captions/credits from the article page
scripts/build.py      voice, captions, motion, render
assets/fonts/         Poppins (SIL Open Font License)
```

## Note on images

Photos on news sites are usually owned by the outlet or a photo agency (AP, Reuters,
Getty). Using them in a monetised channel can lead to Content ID claims or takedowns.
The pipeline always puts credits in `upload.txt`; check the rights for each story.
