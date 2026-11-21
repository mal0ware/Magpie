# Setup command Implementation Plan

**Goal:** `uv run magpie setup` takes a fresh clone to an open camera roll, and Magpie cleans up what it opens.

**Architecture:** A new `magpie/setup.py` track registers `setup` and `uninstall` and only calls existing pieces. Cleanup lives where the thing is opened: the extension closes its tab, the daemon exits itself, autostart owns the login item and the pid file.

**Tech Stack:** Python 3.12, websockets, starlette, plistlib, launchd, Chromium MV3.

**Spec:** `docs/superpowers/specs/2026-11-20-setup-command-design.md`

## Global Constraints

- Windows and macOS both supported; Linux has no start-at-login.
- Tests never touch Instagram, launchd, or the real `~/.magpie`.
- No new dependencies.

## Review Focus

- Setup re-run on a finished install: must not re-list or re-download.
- Ctrl+C while waiting for the extension: a daemon setup started is stopped.
- Old extension (0.2.0) gets `release`: the "unknown action" reply is ignored.
- `uninstall` with no terminal and no `--yes`: deletes no data.
- Stale `web.pid` whose process is gone: `stop_background` does not kill a stranger.

## Tasks

1. **First sync takes everything; neutral wording.** `sources/sync.py` drops `FIRST_SYNC_LIMIT`; `sources/cli.py` `load_steps()` names no single browser. Test: `test_plain_sync_on_empty_library_takes_everything` (100 saved → 100 new).
2. **Release.** `bridge.release() -> bool` (never starts a daemon, never raises); `run_sync` and `manage.unsave` call it when done. `extension/background.js` tracks its own tab in `chrome.storage.session`, closes on `release` or 2 idle minutes; manifest 0.3.0 with `storage`. Tests: release relayed; release with no daemon returns False.
3. **Daemon idle exit.** `Daemon(idle_exit: float | None = IDLE_EXIT)` with `IDLE_EXIT = 600`; `status` does not count as use. Test: daemon with `idle_exit=0.2` ends `serve()` by itself; one that keeps getting requests does not.
4. **Autostart on macOS + pid file.** `autostart.supported() -> bool`, `plist_path()`, `install(port)`, `uninstall()` branch on platform; `write_pid()`, `clear_pid()`, `stop_background(host, port) -> bool`. Tests: plist round-trip under `tmp_path` with `launchctl` stubbed; stale pid not killed.
5. **`magpie/setup.py`.** `cmd_setup(args) -> int`, `cmd_uninstall(args) -> int`, `register(sub)`; wired in `cli.py`. Tests drive both with every seam monkeypatched.
6. **Docs.** README install/first-run/uninstall, `extension/README.md`, empty-state hint in `web/static/index.html`.
7. **Verify.** `uv run pytest`, then `uv run magpie setup` on this Mac.
