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
