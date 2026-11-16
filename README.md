# Magpie

**Your Instagram saved videos as a camera roll, with transcripts you can paste into an LLM.**

Magpies hoard shiny things and never look at them again. I do the same with Instagram's Saved tab. Magpie pulls those saved posts onto your own machine, shows them as a grid like a phone's photo app, and transcribes every video so you can hand the text to Claude.

It is the Instagram sibling of [ytmerge](https://github.com/mal0ware/ytmerge) and uses the same banner format.

## What you get

- A local page with everything you have saved as thumbnails, newest saved first. Click one to play it and read its caption and transcript.
- One button that copies the merged transcripts of your last 30 saves, or of any tiles you pick.
- The caption and creator in every header. On Instagram the caption often holds the real information, like the steps or the links.
- An address you can bookmark. Magpie can start at login and stay in the background.

Everything stays on your machine. Transcription runs locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper). The page only listens on `127.0.0.1`, so nothing else on your network can reach it.

## Contents

- [Before you start](#before-you-start)
- [Install](#install)
- [Load the browser extension](#load-the-browser-extension)
- [First run](#first-run)
- [Bookmark it](#bookmark-it)
- [Using the camera roll](#using-the-camera-roll)
- [Tidying up](#tidying-up)
- [Command line](#command-line)
- [The output](#the-output)
- [No extension? Two other ways in](#no-extension-two-other-ways-in)
- [Where things live](#where-things-live)
- [Going easy on Instagram](#going-easy-on-instagram)
- [When something goes wrong](#when-something-goes-wrong)
- [Limits](#limits)
- [Development](#development)

## Before you start

You need three things installed.

| Tool | Why | Windows | macOS | Linux |
| --- | --- | --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | installs Python and Magpie's packages | `winget install astral-sh.uv` | `brew install uv` | see the uv site |
| [ffmpeg](https://ffmpeg.org/) | pulls the audio out of each video | `winget install Gyan.FFmpeg` | `brew install ffmpeg` | `sudo apt install ffmpeg` |
| git | downloads this repo | `winget install Git.Git` | comes with Xcode tools | `sudo apt install git` |

You also need a Chromium browser where you are logged in to Instagram: Opera GX, Chrome, Edge, Brave or Vivaldi.

An NVIDIA graphics card makes transcription fast (a one-minute reel takes about two seconds on an RTX 3080). Without one, Magpie uses the CPU. That works, it is just slower.

Magpie was built and tested on Windows 11 with Opera GX. See [Limits](#limits) for what that means on other systems.

## Install

```bash
git clone https://github.com/mal0ware/Magpie.git
cd Magpie
uv sync
```

`uv sync` downloads Python 3.12 if you do not have it, plus Magpie's packages. The first time takes a few minutes.

Every command below is run from inside the `Magpie` folder.

## Load the browser extension

Magpie never logs in to Instagram and never sees your password. A small extension sits in the browser where you are already logged in. When Magpie asks, it requests your Saved posts the same way the Instagram site does, and hands the answer back.

1. Open your browser and log in to instagram.com.
2. Go to the extensions page: `opera://extensions`, `chrome://extensions`, `edge://extensions` or `brave://extensions`.
3. Turn on **Developer mode**.
4. Click **Load unpacked** and pick the `extension` folder inside `Magpie`.
5. "Magpie Bridge" shows up in the list. Leave the browser open.

Check that it connected:

```bash
uv run magpie bridge --status
```

It should say `Extension: connected`. If it says the extension is not connected, wait half a minute and run it again. The extension checks in every 30 seconds.

What the extension can and cannot do is written up in [extension/README.md](extension/README.md).

## First run

```bash
uv run magpie sync --limit 30
uv run magpie pull
uv run magpie
```

1. `sync --limit 30` lists your 30 most recent saves into the library.
2. `pull` downloads those videos and transcribes them. The first run also downloads the speech model, about 500 MB.
3. `magpie` on its own opens the camera roll at http://127.0.0.1:8766.

When you are happy with it, bring in everything you have ever saved:

```bash
uv run magpie sync --all
uv run magpie pull --all
```

`sync --all` walks your whole Saved history a page at a time with a pause between pages. A few hundred saves takes about a minute. `pull --all` takes longer since it downloads every video. Count on roughly 7 MB of disk per reel.

After that, a plain `sync` only looks for new saves and stops at the first one it already has.

## Bookmark it

On Windows, run this once:

```bash
uv run magpie web install
```

Magpie now starts hidden when you log in, and it is running already. Bookmark **http://127.0.0.1:8766** and it will always be there.

`uv run magpie web uninstall` removes it. All `install` does is put one shortcut in your Startup folder. It needs no admin rights.

On macOS and Linux there is no `install` yet. Run `uv run magpie web` and leave the terminal open, or add that command to your login items yourself.

## Using the camera roll

The page is the main way to use Magpie. You rarely need the command line after setup.

| Button | What it does |
| --- | --- |
| **Sync** | Lists new saves from Instagram. The browser with the extension has to be open. |
| **Pull** | Downloads and transcribes everything in the library that still needs it. |
| **Last 30** | Selects your 30 most recent saves. |
| **Copy merged transcripts** | Copies the selected items as one block of text, ready to paste. |
| **Free old videos…** | Deletes the video files of everything older than your newest N saves. See [Tidying up](#tidying-up). |

Select one or more tiles and three more buttons appear: **Free video**, **Remove** and **Unsave**. They are explained under [Tidying up](#tidying-up).

Each tile has a small dot for its transcript: done, waiting, or nothing to transcribe.

- Click a tile to play the video and read its caption and transcript beside it.
- Click the corner of a tile, or Ctrl-click, to select it. Shift-click selects a range.
- With a tile focused, Enter opens it and Space selects it.
- In the viewer, the left and right arrows move between posts. Escape closes it.

A typical session: open the bookmark, press **Sync**, press **Pull**, press **Last 30**, press **Copy**, paste into Claude.

## Tidying up

Videos are nearly all of the disk space. Transcripts, captions and thumbnails are tiny. There are three ways to take things out, from mild to final. Each one asks before it does anything.

| Button | What happens | Still on Instagram? |
| --- | --- | --- |
| **Free video** | Deletes the video file. The tile, thumbnail, caption and transcript stay, and Copy still works. You just cannot play it in Magpie any more. | Yes |
| **Remove** | Takes the post out of the roll and deletes its files from your computer. Sync will not bring it back. | Yes |
| **Unsave** | Unsaves the post on Instagram, then removes it from the roll. | No |

**Free old videos…** does the first one in bulk: it asks how many of your newest saves should keep their video and frees the rest.

A video that has not been transcribed yet is never freed, because its transcript could not be made afterwards. Run Pull first.

Unsave is the only thing in Magpie that changes your Instagram account. It sends one request per post, a few seconds apart, and stops at the first answer that is not a plain success. If you unsave something by mistake, save it again on Instagram and it comes back on the next Sync as a new save.

None of these can be undone from inside Magpie.

## Command line

Everything the page does is also a command.

```bash
uv run magpie                   # open the camera roll
uv run magpie sync              # list new saves
uv run magpie pull              # download and transcribe the last 30
uv run magpie copy --last 30    # merged transcripts to the clipboard
```

| Command | What it does |
| --- | --- |
| `magpie` or `magpie web` | Opens the camera roll. `--port N` picks another port, `--no-browser` skips opening a tab. |
| `web install`, `web uninstall` | Start at login, or stop doing that (Windows). |
| `sync` | Lists saves until it reaches one it already has. `--limit N` looks at the newest N. `--all` walks your whole saved history. |
| `pull` | Downloads then transcribes the last 30. `--last N` changes the count, `--all` does everything, `--retry` takes items that failed before. |
| `fetch`, `transcribe` | The two halves of `pull`, on their own. With no `--last` they cover everything. |
| `copy` | Puts the merged text of the last 30 on the clipboard. `--last N` changes the count, `--stdout` prints it too. |
| `free SHORTCODE...` | Deletes those posts' video files. `free --keep N` frees every video older than your newest N saves. |
| `remove SHORTCODE...` | Takes posts out of the roll and deletes their files. |
| `unsave SHORTCODE...` | Unsaves posts on Instagram, then removes them from the roll. |
| `import saved_posts.json` | Adds saves from an Instagram data export. |
| `add URL...` | Adds post links by hand. |
| `bridge --status` | Shows whether the extension is connected. `--stop` stops the background bridge. |

Add `--help` to any command for the full list of options.

### Choosing the speech model

Magpie uses Whisper's `small.en` model. It is quick and good for English. For other languages, or for better accuracy at lower speed, pick another:

```bash
uv run magpie transcribe --model medium --retry
```

You can also set `MAGPIE_WHISPER_MODEL` once instead of passing `--model`. `--device cpu` (or `MAGPIE_WHISPER_DEVICE=cpu`) forces the CPU.

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

Items are separated by a blank line. A video with no speech gets `(no speech)` as its body. Photo posts keep their caption and have nothing to transcribe.

## No extension? Two other ways in

**Instagram's data export.** In Instagram go to Accounts Center → Your information and permissions → Download your information, ask for **Saved** in **JSON** format, and unzip what they send you. Then:

```bash
uv run magpie import path/to/your_instagram_activity/saved/saved_posts.json
uv run magpie pull --all
```

This needs no browser. It is only as fresh as your last export, and Instagram can take a while to prepare one.

**Paste links.**

```bash
uv run magpie add https://www.instagram.com/reel/XXXXXXXXXXX/
uv run magpie pull
```

Both of these download through [yt-dlp](https://github.com/yt-dlp/yt-dlp), which works for public posts. Posts from private accounts need the extension.

## Where things live

Data goes in `~/.magpie` (on Windows, `C:\Users\you\.magpie`). Set `MAGPIE_HOME` to put it somewhere else.

```
magpie.db                              the index
library/<shortcode>/video.mp4
library/<shortcode>/thumb.jpg
library/<shortcode>/transcript.txt
library/<shortcode>/transcript.json    the same transcript with exact timings
bridge.log, web.log
```

To start over, close Magpie and delete that folder. Nothing on Instagram changes.

## Going easy on Instagram

Magpie reads your saves. The one thing it can change is unsaving a post, and only when you select it and press **Unsave**. It never saves, likes, follows, comments or posts.

Syncing makes one request per page of saves, waits a few seconds between pages, and stops at the first post it already has. Unsaving makes one request per post with the same kind of pause. If Instagram answers with a rate limit, a login page or a checkpoint, Magpie stops and tells you which. It does not retry.

The requests it makes are Instagram's own private web API, the one the site uses. It is not an official API. Use Magpie on your own account and at your own risk.

## When something goes wrong

| What you see | What to do |
| --- | --- |
| `extension is not connected` | Check the browser is open and the extension is loaded, wait 30 seconds, try again. |
| `Instagram wants a login` | Log in to instagram.com in that browser, then sync again. |
| `rate limiting (HTTP 429)` | Leave it for a few hours. Do not keep trying. |
| `checkpoint or challenge` | Open instagram.com and clear the prompt yourself first. |
| A tile has no thumbnail or will not play | Press **Pull**. If it failed before, run `uv run magpie pull --all --retry`. |
| Downloads fail a day after a sync | Instagram's video links expire within hours. Run `sync --limit N` again to refresh them, then `pull`. |
| Transcription is slow | You are on the CPU. Check your NVIDIA driver is current, or use a smaller model such as `base.en`. |
| `ffmpeg` not found | Install it (see [Before you start](#before-you-start)) and open a new terminal. |
| Unsave says the extension is an older version | On the extensions page, press the reload arrow on the Magpie Bridge card. |
| The bookmark does not load | Run `uv run magpie`. If you used `web install`, look at `~/.magpie/web.log`. |
| Port 8766 is taken | `uv run magpie web --port 8777`, and bookmark that address instead. |

The extension has its own console: on the extensions page, click **Service worker** on the Magpie Bridge card.

## Limits

- Built and tested on Windows 11 with Opera GX. The camera roll, sync, pull and the page's Copy button should work anywhere Python and a Chromium browser do, but I have not run them on macOS or Linux.
- `magpie copy` (the command) and `magpie web install` are Windows-only. On other systems use the page's Copy button, or `copy --stdout` piped to your clipboard tool.
- A carousel that mixes photos and videos only gets its first video.
- Instagram does not say when you saved something, so the order is the order of your Saved tab.
- Named collections are not shown separately. Everything is one roll.
- Instagram can change its private API without notice, which would break sync until Magpie is updated. The data export keeps working either way.

## Development

```bash
uv run pytest
```

The tests never touch Instagram or the GPU. The design and the layout of the code are in [docs/PLAN.md](docs/PLAN.md).

## License

[MIT](LICENSE)
