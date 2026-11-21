# Magpie

**Your Instagram saved videos as a camera roll, with transcripts you can paste into an LLM.**

Magpies hoard shiny things and never look at them again. I do the same with Instagram's Saved tab. Magpie pulls those saved posts onto your own machine, shows them as a grid like a phone's photo app, and transcribes every video so you can hand the text to Claude.

It is the Instagram sibling of [ytmerge](https://github.com/mal0ware/ytmerge) and uses the same banner format.

## What you get

- A local page with everything you have saved as thumbnails, newest saved first. Click one to play it and read its caption and transcript.
- One button that copies the merged transcripts of your last 30 saves, or of any tiles you pick.
- The caption and creator in every header. On Instagram the caption often holds the real information, like the steps or the links.
- An address you can bookmark. Magpie can start at login and stay in the background.
- One command to set it all up, and one to take it all off again.

Everything stays on your machine. Transcription runs locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper). The page only listens on `127.0.0.1`, so nothing else on your network can reach it.

## Contents

- [Before you start](#before-you-start)
- [Install](#install)
- [Load the browser extension](#load-the-browser-extension)
- [Doing setup by hand](#doing-setup-by-hand)
- [Bookmark it](#bookmark-it)
- [Using the camera roll](#using-the-camera-roll)
- [Tidying up](#tidying-up)
- [Command line](#command-line)
- [The output](#the-output)
- [No extension? Two other ways in](#no-extension-two-other-ways-in)
- [Where things live](#where-things-live)
- [What Magpie leaves running](#what-magpie-leaves-running)
- [Uninstall](#uninstall)
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

Magpie was built on Windows 11 with Opera GX and also runs on macOS. See [Limits](#limits) for what differs between systems.

## Install

```bash
git clone https://github.com/mal0ware/Magpie.git
cd Magpie
uv sync
uv run magpie setup
```

`uv sync` downloads Python 3.12 if you do not have it, plus Magpie's packages. The first time takes a few minutes.

`uv run magpie setup` does the rest and finishes by opening your camera roll:

1. Checks that ffmpeg is installed.
2. Starts the local bridge. If the browser extension is not loaded yet, it shows you the steps from the next section and waits until the extension connects.
3. Lists everything you have ever saved and downloads a thumbnail for each. A few hundred saves takes about a minute and about 100 kB each.
4. Downloads no videos. You get those one at a time by clicking a post, or all at once with **Pull**.
5. Makes the camera roll start at login (Windows and macOS), and opens it.

Setup is safe to run again. It picks up where it stopped and never downloads something twice. `--pull 30` also downloads and transcribes your newest 30 straight away. `--no-login` skips the login item and runs the page in the terminal instead, so nothing keeps running after you press Ctrl+C.

Every command below is run from inside the `Magpie` folder.

## Load the browser extension

This is the one step setup cannot do for you: browsers do not let a program install an extension from a folder. Setup waits while you do it.

Magpie never logs in to Instagram and never sees your password. A small extension sits in the browser where you are already logged in. When Magpie asks, it requests your Saved posts the same way the Instagram site does, and hands the answer back.

1. Open your browser and log in to instagram.com.
2. Go to the extensions page: `opera://extensions`, `chrome://extensions`, `edge://extensions` or `brave://extensions`.
3. Turn on **Developer mode**.
4. Click **Load unpacked** and pick the `extension` folder inside `Magpie`.
5. "Magpie Bridge" shows up in the list. Leave the browser open.

The browser has to be open for a sync, but an Instagram tab does not. If there is none, the extension opens one in the background and closes it again when the sync is done. It never closes a tab you opened.

If setup is not running, you can check that it connected:

```bash
uv run magpie bridge --status
```

It should say `Extension: connected`. If it says the extension is not connected, wait half a minute and run it again. The extension checks in every 30 seconds.

What the extension can and cannot do is written up in [extension/README.md](extension/README.md).

## Doing setup by hand

`setup` only runs commands you can run yourself:

```bash
uv run magpie sync
uv run magpie pull
uv run magpie
```

1. `sync` lists your saves into the library and fetches their thumbnails. The first time, that is your whole Saved history, a page at a time with a pause between pages. After that it only looks for new saves and stops at the first one it already has. `sync --limit 30` looks at just the newest 30.
2. `pull` downloads the newest 30 videos and transcribes them.
3. `magpie` on its own opens the camera roll at http://127.0.0.1:8766.

To download everything rather than the newest 30:

```bash
uv run magpie pull --all
```

That takes a while since it downloads every video. Count on roughly 7 MB of disk per reel.

## Bookmark it

`setup` already did this on Windows and macOS. If you skipped it with `--no-login`, run this once:

```bash
uv run magpie web install
```

Magpie now starts hidden when you log in, and it is running already. Bookmark **http://127.0.0.1:8766** and it will always be there.

`uv run magpie web uninstall` removes the login item and stops the page. All `install` does is add one file: a shortcut in your Startup folder on Windows, or `~/Library/LaunchAgents/com.mal0ware.magpie.web.plist` on macOS. It needs no admin rights.

On macOS, keep the `Magpie` folder outside Desktop, Documents and Downloads. macOS does not let a background program read those folders without asking.

On Linux there is no `install` yet. Run `uv run magpie web` and leave the terminal open, or add that command to your login items yourself.

## Using the camera roll

The page is the main way to use Magpie. You rarely need the command line after setup.

| Button | What it does |
| --- | --- |
| **Sync** | Lists new saves from Instagram and fetches their thumbnails. The browser with the extension has to be open. |
| **Pull** | Downloads and transcribes every post that is not on this computer yet. It tells you how many and roughly how big before it starts. |
| **Last 30** | Selects your 30 most recent saves. |
| **Copy merged transcripts** | Copies the selected items as one block of text, ready to paste. |
| **Free old videos…** | Deletes the video files of everything older than your newest N saves. See [Tidying up](#tidying-up). |

Select one or more tiles and three more buttons appear: **Free video**, **Remove** and **Unsave**. They are explained under [Tidying up](#tidying-up).

Each tile has a small dot for its transcript: done, waiting, or nothing to transcribe.

- Click a tile to play the video and read its caption and transcript beside it. If the video is not on this computer yet, opening it downloads and transcribes just that one, and keeps it. The first transcript also downloads the speech model, about 500 MB, once.
- Flicking through with the arrow keys does not download every post you pass. A download starts once you have stayed on a post for a moment.
- Click the corner of a tile, or Ctrl-click, to select it. Shift-click selects a range.
- With a tile focused, Enter opens it and Space selects it.
- In the viewer, the left and right arrows move between posts. Escape closes it.

A typical session: open the bookmark, press **Sync**, open the posts you care about, select them, press **Copy**, paste into Claude. Only what you open takes up space.

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
| `setup` | Sets everything up and opens the camera roll. `--no-pull` downloads nothing yet, `--no-login` does not start at login. |
| `uninstall` | Removes everything Magpie put on this machine. See [Uninstall](#uninstall). |
| `magpie` or `magpie web` | Opens the camera roll. `--port N` picks another port, `--no-browser` skips opening a tab. |
| `web install`, `web uninstall` | Start at login, or stop doing that (Windows and macOS). |
| `sync` | Lists saves until it reaches one it already has; the first time, that is all of them. `--limit N` looks at the newest N. `--all` walks your whole saved history again. |
| `pull` | Downloads then transcribes the last 30. `--last N` changes the count, `--all` does everything, `--retry` takes items that failed before. `pull SHORTCODE...` does just those posts. |
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

The speech model is the one thing kept elsewhere. It sits in the Hugging Face cache (`~/.cache/huggingface/hub`), which other tools such as ytmerge share.

## What Magpie leaves running

- **The camera roll**, if you let setup start it at login. It is a small local web server that only listens on `127.0.0.1`. `uv run magpie web uninstall` stops it and removes the login item.
- **The bridge**, only while it is being used. It starts when a sync or an unsave needs it and exits by itself after ten minutes with nothing to do.
- **An Instagram tab**, only during a sync or unsave and only if you had none open. The extension closes it afterwards.

Thumbnails come with every sync. A video is only downloaded when you open that post, press **Pull**, or run `pull`. **Free old videos…** gives the space back and keeps the transcripts.

## Uninstall

```bash
uv run magpie uninstall
```

This removes the login item, stops the camera roll and the bridge, and deletes `~/.magpie` after showing you its size and asking. `--keep-data` keeps your library. `--yes` skips the question. The speech model is shared with other tools, so it is only deleted if you add `--model`; otherwise uninstall tells you where it is and how big.

Two things are left for you, and uninstall names them: remove **Magpie Bridge** on your browser's extensions page, and delete the `Magpie` folder.

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
| A tile has no thumbnail | Thumbnail links expire a few hours after a sync. `uv run magpie sync --all` gets fresh ones. |
| A post will not download or play | Open it and press **Download again**. Posts from private accounts need a recent **Sync** first. |
| Downloads fail a day after a sync | Instagram's video links expire within hours. Run `sync --limit N` again to refresh them, then `pull`. |
| Transcription is slow | You are on the CPU. Check your NVIDIA driver is current, or use a smaller model such as `base.en`. |
| `ffmpeg` not found | Install it (see [Before you start](#before-you-start)) and open a new terminal. |
| Unsave says the extension is an older version | On the extensions page, press the reload arrow on the Magpie Bridge card. |
| The bookmark does not load | Run `uv run magpie`. If Magpie starts at login, look at `~/.magpie/web.log`. |
| The first sync after a while takes half a minute to start | The bridge had exited and the extension checks in every 30 seconds. It is waiting for that. |
| An Instagram tab stays open after a sync | You are on an older extension. Press the reload arrow on the Magpie Bridge card. |
| Port 8766 is taken | `uv run magpie web --port 8777`, and bookmark that address instead. |

The extension has its own console: on the extensions page, click **Service worker** on the Magpie Bridge card.

## Limits

- Built on Windows 11 with Opera GX, and run on macOS. Any Chromium browser works. Linux should work but I have not run it there, and it has no start-at-login.
- A Mac has no NVIDIA card, so transcription runs on the CPU there. It works; a one-minute reel takes a good deal longer than two seconds.
- `magpie copy` (the command) is Windows-only. On other systems use the page's Copy button, or `copy --stdout` piped to your clipboard tool (`pbcopy` on macOS).
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
