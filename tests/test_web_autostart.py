import sys

import pytest

from magpie import cli
from magpie.web import autostart


def test_background_command_points_at_the_roll():
    cmd = autostart.background_command(8766)
    assert cmd[1:] == ["-m", "magpie.cli", "web", "--background", "--port", "8766"]


def test_plain_magpie_opens_the_roll(monkeypatch, capsys):
    monkeypatch.setattr(autostart, "running", lambda host, port: True)
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    assert cli.main([]) == 0
    assert opened == ["http://127.0.0.1:8766"]
    assert "already running" in capsys.readouterr().out


@pytest.mark.skipif(sys.platform != "win32", reason="Startup folder is Windows-only")
def test_install_and_uninstall_write_the_startup_shortcut(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "shortcut_path", lambda: tmp_path / "Magpie.lnk")
    link = autostart.install(8766)
    assert link.exists() and link.stat().st_size > 0
    assert autostart.uninstall() is True and not link.exists()
    assert autostart.uninstall() is False


@pytest.mark.skipif(sys.platform != "darwin", reason="LaunchAgents are macOS-only")
def test_install_and_uninstall_write_the_launch_agent(tmp_path, monkeypatch):
    import plistlib

    plist = tmp_path / "LaunchAgents" / "magpie.plist"
    monkeypatch.setattr(autostart, "plist_path", lambda: plist)
    ran = []
    monkeypatch.setattr(autostart.subprocess, "run", lambda cmd, **kw: ran.append(cmd))

    assert autostart.install(8766) == plist
    job = plistlib.loads(plist.read_bytes())
    assert job["Label"] == autostart.LABEL and job["RunAtLoad"] is True
    assert job["ProgramArguments"] == autostart.background_command(8766)
    assert "KeepAlive" not in job  # stopping it must not bring it straight back
    assert ran == []  # installing loads nothing: the caller starts the server

    assert autostart.uninstall() is True and not plist.exists()
    assert ran and ran[0][:2] == ["launchctl", "bootout"]
    assert autostart.uninstall() is False


def test_stop_background_never_kills_on_a_stale_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    killed = []
    monkeypatch.setattr(autostart.os, "kill", lambda pid, sig: killed.append(pid))

    assert autostart.stop_background("127.0.0.1", 8766) is False  # no pid file

    (tmp_path / "web.pid").write_text("424242")
    monkeypatch.setattr(autostart, "running", lambda host, port: False)
    assert autostart.stop_background("127.0.0.1", 8766) is False
    assert killed == [] and not (tmp_path / "web.pid").exists()

    (tmp_path / "web.pid").write_text("424242")
    monkeypatch.setattr(autostart, "running", lambda host, port: True)
    assert autostart.stop_background("127.0.0.1", 8766) is True
    assert killed == [424242] and not (tmp_path / "web.pid").exists()


def test_clear_pid_leaves_another_servers_file_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    autostart.write_pid()
    assert (tmp_path / "web.pid").read_text() == str(autostart.os.getpid())
    (tmp_path / "web.pid").write_text("1")
    autostart.clear_pid()
    assert (tmp_path / "web.pid").exists()
