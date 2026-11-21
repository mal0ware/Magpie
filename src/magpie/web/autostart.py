"""Keep the camera roll running in the background so its address can be
bookmarked. On Windows that is a shortcut in the Startup folder; on macOS a
LaunchAgent. Either one starts the server, hidden, at login, and `uninstall`
takes it away again. Nothing here needs admin rights."""

import os
import plistlib
import signal
import socket
import subprocess
import sys
from pathlib import Path

from .. import store

SHORTCUT = "Magpie.lnk"
LABEL = "com.mal0ware.magpie.web"  # the macOS LaunchAgent


def running(host: str, port: int) -> bool:
    """Is something already listening where the roll lives?"""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def log_path() -> Path:
    return store.home() / "web.log"


def supported() -> bool:
    """Can Magpie start itself at login on this system?"""
    return sys.platform in ("win32", "darwin")


def _require_supported() -> None:
    if not supported():
        raise OSError("starting at login is only set up for Windows and macOS; here, run "
                      "`magpie web` and leave it open, or add it to your login items")


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def login_item_path() -> Path:
    """Where this system's login item lives, installed or not."""
    return shortcut_path() if sys.platform == "win32" else plist_path()


# -- the running server ------------------------------------------------------

def pid_path() -> Path:
    return store.home() / "web.pid"


def write_pid() -> None:
    pid_path().write_text(str(os.getpid()), encoding="ascii")


def clear_pid() -> None:
    try:
        if pid_path().read_text(encoding="ascii").strip() == str(os.getpid()):
            pid_path().unlink()
    except OSError:
        pass


def stop_background(host: str, port: int) -> bool:
    """Stop a running camera roll server. Returns whether one was stopped.

    Only acts when something is listening on the roll's port AND web.pid names
    a process, so a stale pid file never gets an unrelated program killed."""
    path = pid_path()
    try:
        pid = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return False
    if not running(host, port):
        path.unlink(missing_ok=True)  # left behind by a crash
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    finally:
        path.unlink(missing_ok=True)
    return True


def shortcut_path() -> Path:
    return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu"
            / "Programs" / "Startup" / SHORTCUT)


def background_command(port: int) -> list[str]:
    """The server process. It is a console program on purpose: a virtualenv's
    pythonw.exe can hand off to the console python.exe anyway, which makes
    Windows open an empty terminal window. Callers hide the console instead."""
    return [sys.executable, "-m", "magpie.cli", "web", "--background", "--port", str(port)]


def start_background(port: int) -> None:
    # CREATE_NO_WINDOW gives it a console with no window, which its children
    # inherit. (DETACHED_PROCESS gives it none, so a child opens a visible one.)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(background_command(port), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     start_new_session=os.name != "nt")  # outlive the terminal


def install(port: int) -> Path:
    """Write the login item. Returns its path."""
    _require_supported()
    cmd = background_command(port)
    if sys.platform == "darwin":
        # A plist in ~/Library/LaunchAgents is loaded at every login. It is not
        # loaded now: the caller starts the server itself this first time.
        path = plist_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            plistlib.dump({"Label": LABEL, "ProgramArguments": cmd, "RunAtLoad": True,
                           "ProcessType": "Background",
                           "WorkingDirectory": str(Path.home())}, f)
        return path
    link = shortcut_path()
    conhost = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "conhost.exe"

    def q(s: str) -> str:  # a PowerShell single-quoted string
        return "'" + s.replace("'", "''") + "'"

    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({q(str(link))}); "
        # conhost --headless runs a console program with no window at all.
        f"$s.TargetPath = {q(str(conhost))}; "
        f"$s.Arguments = {q('--headless ' + subprocess.list2cmdline(cmd))}; "
        f"$s.WorkingDirectory = {q(str(Path.home()))}; "
        "$s.Description = 'Magpie camera roll'; $s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   check=True, capture_output=True)
    return link


def uninstall() -> bool:
    """Remove the login item. Returns whether there was one."""
    _require_supported()
    if sys.platform == "darwin":
        path = plist_path()
        if not path.exists():
            return False
        # Forget it now as well, if launchd loaded it at this login.
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"],
                       capture_output=True)
        path.unlink()
        return True
    link = shortcut_path()
    if link.exists():
        link.unlink()
        return True
    return False
