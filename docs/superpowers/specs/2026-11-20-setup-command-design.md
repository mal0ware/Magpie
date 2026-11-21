# One-command setup, and cleaning up after ourselves

## Why

After `uv sync` a new user gets nothing: no page, no next step. First run is
three commands, and Magpie leaves things behind (a bridge daemon that never
exits, an Instagram tab it opened, no way to remove itself). Some users are on
macOS, where there is no start-at-login at all.

## Goals

- `uv run magpie setup` takes a fresh clone to an open camera roll.
- Works on Windows and macOS. Linux gets everything except start-at-login.
- Nothing Magpie opens outlives its use, and one command removes everything.

## Non-goals

- Installing the browser extension automatically. Chromium does not allow it.
- Auto-deleting videos. `free` already exists and stays manual.

## Approaches

1. **A `setup` subcommand that calls the existing pieces** (picked). Reuses
   `ensure_daemon`, `run_sync`, `pull`, `autostart`. Safe to re-run.
2. A shell/PowerShell installer script. Two scripts to keep in step, and it
   cannot wait on the extension cleanly.
3. Do it all from the web page's empty state. Still needs a command to start
   the page, and the page cannot check for ffmpeg.

## Design

`magpie setup [--no-pull] [--no-login] [--port N]`

1. Check `ffmpeg` is on PATH; if not, print the install line for this OS, stop.
2. Start the bridge. If the extension is not connected, print the load steps
   (browser-neutral) and poll until it connects. Ctrl+C or a 10 minute timeout
   stops a daemon that setup itself started.
3. `sync`. A plain sync on an empty library now lists the whole history
   (the 30 cap is gone; `--limit N` still exists).
4. `pull` the newest 30 (skipped by `--no-pull`). The page's Pull gets the rest.
5. Start at login, then open the roll. Windows: Startup shortcut (as now).
   macOS: a LaunchAgent plist. With `--no-login`, or on Linux, run the page in
   the foreground instead so nothing is left running.
6. Print where data lives and that `magpie uninstall` removes it.

Cleaning up:

- **Instagram tab.** The extension remembers a tab it opened itself and closes
  it on a `release` message (sent after sync and unsave) or after 2 idle
  minutes. A tab the user opened is never closed. Extension 0.3.0.
- **Bridge daemon.** Exits after 10 minutes with no requests. It is started on
  demand already, so nothing else changes. Cost: the first sync after an idle
  exit can wait up to 30 s for the extension to reconnect.
- **Web server.** Writes `~/.magpie/web.pid` while running so it can be stopped.
- **`magpie uninstall [--yes] [--keep-data] [--model]`.** Removes the login
  item, stops the web server and bridge, and deletes `~/.magpie` after a
  confirmation that shows its size. The speech model lives in the shared
  Hugging Face cache (ytmerge uses it too), so it is only deleted with
  `--model`; otherwise its path and size are printed. Ends by naming what is
  left by hand: the extension and the repo folder.

## My calls (not discussed)

- 10 minute daemon idle, 2 minute tab idle.
- Model deletion is opt-in because the cache is shared.
- `--no-login` runs in the foreground rather than leaving a background server.
