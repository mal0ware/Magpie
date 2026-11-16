"""Keep the camera roll running in the background so its address can be
bookmarked: a shortcut in the Windows Startup folder that starts the server,
hidden, at login. Nothing here needs admin rights."""

import os
import socket
import subprocess
import sys
from pathlib import Path

from .. import store

SHORTCUT = "Magpie.lnk"


def running(host: str, port: int) -> bool:
    """Is something already listening where the roll lives?"""
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def log_path() -> Path:
    return store.home() / "web.log"


def _require_windows() -> None:
    if sys.platform != "win32":
        raise OSError("install is Windows-only for now; on other systems run "
                      "`magpie web` and leave it open, or add it to your login items")


def shortcut_path() -> Path:
    return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu"
            / "Programs" / "Startup" / SHORTCUT)


def background_command(port: int) -> list[str]:
    """The hidden server process: pythonw has no console window."""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    return [str(pythonw if pythonw.exists() else exe), "-m", "magpie.cli",
            "web", "--background", "--port", str(port)]


def start_background(port: int) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(background_command(port), creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def install(port: int) -> Path:
    """Write the Startup shortcut. Returns its path."""
    _require_windows()
    cmd = background_command(port)
    link = shortcut_path()

    def q(s: str) -> str:  # a PowerShell single-quoted string
        return "'" + s.replace("'", "''") + "'"

    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({q(str(link))}); "
        f"$s.TargetPath = {q(cmd[0])}; "
        f"$s.Arguments = {q(subprocess.list2cmdline(cmd[1:]))}; "
        f"$s.WorkingDirectory = {q(str(Path.home()))}; "
        "$s.Description = 'Magpie camera roll'; $s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                   check=True, capture_output=True)
    return link


def uninstall() -> bool:
    """Remove the Startup shortcut. Returns whether there was one."""
    _require_windows()
    link = shortcut_path()
    if link.exists():
        link.unlink()
        return True
    return False
