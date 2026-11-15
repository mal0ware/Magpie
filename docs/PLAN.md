# Magpie — plan

Magpies hoard shiny things and never look at them again. So do Instagram's
Saved posts. Magpie pulls your saved videos onto your own machine, shows them
as a camera roll, and gives you a transcript of each one in the same banner
format as ytmerge, ready to paste into Claude.

## What it has to do

1. Show saved videos as a camera roll: a grid of thumbnails, newest saved first.
2. "Give me the last 30": one command or one button that puts the merged
   transcripts of the N most recently saved videos on the clipboard.
3. Transcripts are the point. Video files are kept because the roll plays them,
   but nothing else is done with them.

Out of scope for v1: named collections UI, posting or unsaving, any platform
other than Instagram, hosting. It is a local tool on `127.0.0.1`.

## Decisions

- **Standalone Python project** (uv, Python 3.12, `src/` layout). Not part of
  ytmerge. It borrows ytmerge's banner format and web UI feel, nothing else.
- **Listing saved posts goes through the logged-in browser**, not cookies.
  A small MV3 extension runs Instagram's own `/api/v1/feed/saved/posts/` call
  from inside an instagram.com tab, the same way `~/.agent-reach/tools/ig-bridge`
  reads profiles. This is the only method that works with Opera GX, and it
  looks like normal site traffic. Instaloader and cookie extraction were
  rejected: Opera GX cookies are awkward to read and a second client logging in
  with your session is what triggers checkpoints.
- **Fallback listing sources** that need no browser: the Instagram data export
  (`saved_posts.json`) and a plain list of pasted URLs.
- **Downloading** uses the CDN `video_url` from the listing when it is fresh,
  and falls back to yt-dlp on the post URL.
- **Transcription is local**: ffmpeg pulls the audio, faster-whisper runs on the
  RTX 3080 (CUDA, `small.en` by default, model is configurable), CPU fallback.
- **Go slow and be incremental.** Listing stops at the first post already in
  the store. Requests are spaced out. A 429 or checkpoint means stop and say
  so, never retry harder.

## Layout and ownership

```
src/magpie/
  models.py, store.py, cli.py     shared contract (already written, change only by agreement)
  sources/    track A             listing: bridge, export import, pasted URLs
  pipeline/   track B             download, transcribe, merge/format
  web/        track C             local server and camera-roll page
extension/    track A             MV3 extension for the browser
tests/                            each track adds test_<track>_*.py
```

Each track only edits its own directory (plus its own tests and its own section
of the README if it writes one). `pyproject.toml` already lists the expected
dependencies; add one if you must and say so in your final report.

Every track exposes its subcommands through `register(sub)` in its `cli.py`.
`magpie/cli.py` already calls all three.

## Shared contract

`models.Item` is the record. `store.Store` is the only thing that touches the
database. Data lives in `$MAGPIE_HOME` (default `~/.magpie`):

```
magpie.db
library/<shortcode>/video.mp4
library/<shortcode>/thumb.jpg
library/<shortcode>/transcript.txt     one "[m:ss] text" line per segment
library/<shortcode>/transcript.json    raw segments (start, end, text)
```

Use `store.video_path()`, `thumb_path()`, `transcript_path()`, never build
paths by hand.

Status fields: `media_status` and `transcript_status` are each
`pending | done | failed | none`. `none` means there is nothing to do (an image
post, or a video with no speech).

Order: `saved_seq`, higher is more recently saved. `Store.recent(limit)` is
the camera-roll order and the definition of "last 30". Sources call
`Store.add_listing(items)` with items newest first; see its docstring for the
sync and backfill rules.

## Track A — sources (`sources/`, `extension/`)

- Extension + local bridge that returns the saved feed from the logged-in
  browser, paginated with `next_max_id`. Model it on ig-bridge
  (`~/.agent-reach/tools/ig-bridge`, read `DESIGN.md` there), but ship it inside
  this repo so Magpie stands alone. Use a port that does not clash with
  ig-bridge (19833) or ytmerge-web (8765).
- Map each feed entry to an `Item`: shortcode, url, kind, author, caption,
  taken_at, duration, `video_url`, `thumb_url`.
- `magpie sync [--limit N] [--all]`: default lists until it meets a known
  shortcode, `--limit N` stops after N posts, `--all` backfills everything,
  page by page with a delay between pages.
- `magpie import <saved_posts.json>` and `magpie add <url>...`.
- Tests run against recorded JSON fixtures, never the live site.

Done when: with Opera GX open and logged in, `magpie sync --limit 30` puts 30
items in the store in the right order, and a second run adds nothing.

## Track B — pipeline (`pipeline/`)

- `fetch`: for items with `media_status = pending`, download the video to
  `video_path()` and a thumbnail to `thumb_path()` (grab the listing thumbnail,
  or cut a frame with ffmpeg). Image posts get `media_status = none`.
- `transcribe`: for items with media done and transcript pending, extract audio
  with ffmpeg, run faster-whisper, write `transcript.txt` and `transcript.json`.
  No speech gives `transcript_status = none`.
- `merge.format_item(item) -> str` and `merge.format_many(items) -> str`,
  the banner below. Track C imports these.
- `magpie fetch [--last N]`, `magpie transcribe [--last N]`,
  `magpie copy [--last 30]` (merged text to the clipboard, and to stdout with
  `--stdout`), `magpie pull [--last 30]` which runs fetch then transcribe.
- One failed item never stops the batch. Record the error on the item.

Banner, one per item, items separated by a blank line:

```
================================================================================
CREATOR: @handle
URL:     https://www.instagram.com/reel/<shortcode>/
CAPTION: the caption, newlines kept
================================================================================

[0:00] transcript line
[0:04] transcript line
```

If there is no speech, the body is `(no speech)`. The caption stays, since on
Instagram it often holds the actual information.

Done when: given items in the store (seed them by hand with post URLs if track
A is not merged yet), `magpie pull --last 5` leaves five videos, thumbnails and
transcripts on disk, and `magpie copy --last 5` puts the merged text on the
clipboard.

## Track C — web (`web/`)

- `magpie web` serves `http://127.0.0.1:8766` (bind to loopback only).
- Camera roll: thumbnail grid in `Store.recent()` order, infinite scroll or
  paging, a badge for transcript status. Click a tile to play the video and
  read its caption and transcript beside it.
- Select tiles, or press "Last 30", then "Copy merged transcripts". The merged
  text comes from `pipeline.merge.format_many`.
- Buttons for "Sync" and "Pull" that run the same functions the CLI does, with
  progress shown. If those functions are not merged yet, build against the
  names in this document and leave the calls behind a clear seam.
- JSON API: `GET /api/items?limit=&offset=`, `GET /api/items/<shortcode>`,
  `GET /media/<shortcode>/video.mp4`, `GET /media/<shortcode>/thumb.jpg`,
  `POST /api/merged` with a list of shortcodes or `{"last": 30}`.
- Plain HTML, CSS and JS, no build step. Dark, quiet, thumbnail-first. It
  should feel like the Photos app, with ytmerge's "copy all merged" habit.
- Tests use a temporary `MAGPIE_HOME` seeded with fake items.

Done when: with a seeded library, the page shows the grid, plays a video,
and "Last 30 → Copy" puts the merged text on the clipboard.

## After the tracks

Merge the three branches into `main`, run the whole thing end to end on the
real account (sync 30, pull 30, open the roll, copy), then write the README.
