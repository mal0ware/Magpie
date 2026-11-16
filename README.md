# Magpie

**Your Instagram saved videos as a camera roll, with transcripts you can paste into an LLM.**

Magpies hoard shiny things and never look at them again. I do the same with Instagram's Saved tab. Magpie pulls those saved videos onto your own machine, shows them as a grid like a phone's photo app, and transcribes each one so you can hand the text to Claude.

It is the Instagram sibling of [ytmerge](https://github.com/mal0ware/ytmerge) and uses the same banner format.

## What you get

- A local page with every saved video as a thumbnail, newest saved first. Click one to play it and read its caption and transcript.
- One button, or one command, that copies the merged transcripts of your last 30 saves.
- The post's caption and creator in every header. On Instagram the caption often holds the real information, like the steps or the links.

Everything stays on your machine. Transcription runs locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## Setup

You need Python 3.12, [uv](https://docs.astral.sh/uv/) and ffmpeg. An NVIDIA GPU makes transcription fast, but it falls back to the CPU without one.

```bash
git clone https://github.com/mal0ware/Magpie.git
cd Magpie
uv sync
```

Then load the browser extension. Magpie never logs in to Instagram. The extension sits in the browser where you are already logged in and asks for your Saved posts the same way the site does.

1. Open your browser and log in to instagram.com.
2. Go to the extensions page (`opera://extensions`, `chrome://extensions`) and turn on Developer mode.
3. Click **Load unpacked** and pick the `extension` folder.
4. Leave the browser open.

More detail, and what to do when it stops, is in [extension/README.md](extension/README.md).

## Use

```bash
uv run magpie sync              # list new saves into the library
uv run magpie pull              # download and transcribe the last 30
uv run magpie copy --last 30    # merged transcripts to the clipboard
uv run magpie web               # the camera roll, at http://127.0.0.1:8766
```

The page has Sync, Pull, Last 30 and Copy buttons that do the same things.

The first `sync` may say the extension is not connected. It checks in every 30 seconds, so wait a moment and run it again.

| Command | What it does |
| --- | --- |
| `sync` | Lists saves until it reaches one it already has. `--limit N` looks at the newest N. `--all` walks your whole saved history, slowly. |
| `pull` | Downloads then transcribes. `--last N` (default 30), `--retry` for items that failed before. |
| `fetch`, `transcribe` | The two halves of `pull`, on their own. |
| `copy` | Puts the merged text on the clipboard. `--stdout` prints it too. |
| `import saved_posts.json` | Adds saves from an Instagram data export, no browser needed. |
| `add URL...` | Adds post links by hand. |
| `bridge --status` | Shows whether the extension is connected. |

Whisper uses the `small.en` model by default. Change it with `--model` or `$MAGPIE_WHISPER_MODEL`, and force the CPU with `--device cpu`.

## The output

```
================================================================================
CREATOR: @handle
URL:     https://www.instagram.com/reel/...
CAPTION: the caption, as written
================================================================================

[0:00] first line of the transcript
[0:04] next line
```

A video with no speech gets `(no speech)` as its body. Photo posts keep their caption and have nothing to transcribe.

## Where things live

Data goes in `~/.magpie` (set `MAGPIE_HOME` to move it):

```
magpie.db
library/<shortcode>/video.mp4
library/<shortcode>/thumb.jpg
library/<shortcode>/transcript.txt
```

## Going easy on Instagram

Magpie only reads. It makes one request per page of saves, waits between pages, and stops at the first post it already has. If Instagram answers with a rate limit, a login page or a checkpoint, it stops and tells you which. It does not retry.

## Limits

- Built and tested on Windows 11 with Opera GX. `copy` uses the Windows clipboard.
- A carousel that mixes photos and videos only gets its first video.
- Instagram does not say when you saved something, so the order is the order of the Saved tab.
- The saved-feed call is Instagram's private web API. It can change without notice.

## Development

```bash
uv run pytest
```

The design and the layout of the code are in [docs/PLAN.md](docs/PLAN.md).

## License

MIT
