"""`magpie setup` and `magpie uninstall` with every outside thing stubbed."""

import pytest

from magpie import cli, setup
from magpie.sources import bridge
from magpie.web import autostart

CONNECTED = {"protocol": 1, "extension_connected": True, "extension_version": "0.3.0"}
WAITING = {"protocol": 1, "extension_connected": False, "extension_version": None}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A machine where everything works. Tests break one thing at a time."""
    calls = []
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(setup.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(setup.time, "sleep", lambda s: None)
    monkeypatch.setattr(bridge, "status", lambda *a, **k: CONNECTED)
    monkeypatch.setattr(bridge, "ensure_daemon", lambda: CONNECTED)
    monkeypatch.setattr(bridge, "stop_daemon", lambda: calls.append("stop_daemon") or True)
    monkeypatch.setattr(setup.sources_cli, "cmd_sync",
                        lambda a: calls.append(("sync", a.limit, a.all)) or 0)
    monkeypatch.setattr(setup.pipeline_cli, "cmd_pull",
                        lambda a: calls.append(("pull", a.last)) or 0)
    monkeypatch.setattr(autostart, "supported", lambda: True)
    monkeypatch.setattr(autostart, "install",
                        lambda port: calls.append("install") or tmp_path / "item")
    monkeypatch.setattr(autostart, "uninstall", lambda: calls.append("uninstall") or True)
    monkeypatch.setattr(autostart, "running", lambda host, port: "start" in calls)
    monkeypatch.setattr(autostart, "start_background", lambda port: calls.append("start"))
    monkeypatch.setattr(autostart, "stop_background",
                        lambda host, port: calls.append("stop_web") or True)
    monkeypatch.setattr(setup.webbrowser, "open", lambda url: calls.append(("open", url)))
    monkeypatch.setattr(setup.web_cli, "_web",
                        lambda a: calls.append(("foreground", a.port)) or 0)
    monkeypatch.setattr(setup, "model_dirs", lambda: [])
    return calls


def test_setup_runs_every_step_and_opens_the_roll(world, capsys):
    assert cli.main(["setup"]) == 0
    assert world == [("sync", None, False), "install", "start",
                     ("open", "http://127.0.0.1:8766")]  # and not one video
    out = capsys.readouterr().out
    assert "http://127.0.0.1:8766" in out and "magpie uninstall" in out


def test_setup_again_does_not_start_a_second_server(world, monkeypatch):
    monkeypatch.setattr(autostart, "running", lambda host, port: True)
    assert cli.main(["setup"]) == 0
    assert "start" not in world and ("open", "http://127.0.0.1:8766") in world


def test_setup_stops_without_ffmpeg(world, monkeypatch, capsys):
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    assert cli.main(["setup"]) == 1
    assert world == [] and "ffmpeg is not installed" in capsys.readouterr().out


def test_setup_waits_for_the_extension_then_carries_on(world, monkeypatch, capsys):
    answers = [None, WAITING, WAITING, CONNECTED, CONNECTED]
    monkeypatch.setattr(bridge, "status", lambda *a, **k: answers.pop(0) if answers else CONNECTED)
    monkeypatch.setattr(bridge, "ensure_daemon", lambda: WAITING)
    assert cli.main(["setup"]) == 0
    out = capsys.readouterr().out
    assert "Load unpacked" not in out  # it was loaded already, just slow to check in
    assert "stop_daemon" not in world and "install" in world


def test_setup_shows_the_load_steps_when_the_extension_does_not_check_in(world, monkeypatch, capsys):
    monkeypatch.setattr(setup, "EXT_CHECK_IN", 0)
    answers = [None, WAITING, WAITING]
    monkeypatch.setattr(bridge, "status", lambda *a, **k: answers.pop(0) if answers else CONNECTED)
    monkeypatch.setattr(bridge, "ensure_daemon", lambda: WAITING)
    assert cli.main(["setup"]) == 0
    out = capsys.readouterr().out
    assert "Load unpacked" in out and "carries on by itself" in out


def test_giving_up_on_the_extension_stops_the_daemon_setup_started(world, monkeypatch):
    answers = [None]  # nothing was running before setup
    monkeypatch.setattr(bridge, "status", lambda *a, **k: answers.pop(0) if answers else WAITING)
    monkeypatch.setattr(bridge, "ensure_daemon", lambda: WAITING)
    assert cli.main(["setup", "--wait", "0"]) == 1
    assert world == ["stop_daemon"]


def test_giving_up_leaves_a_daemon_that_was_already_running(world, monkeypatch):
    monkeypatch.setattr(bridge, "status", lambda *a, **k: WAITING)
    monkeypatch.setattr(bridge, "ensure_daemon", lambda: WAITING)
    assert cli.main(["setup", "--wait", "0"]) == 1
    assert world == []


def test_ctrl_c_while_waiting_also_cleans_up(world, monkeypatch):
    answers = [None]

    def status(*a, **k):
        if answers:
            return answers.pop(0)
        raise KeyboardInterrupt

    monkeypatch.setattr(bridge, "status", status)
    monkeypatch.setattr(bridge, "ensure_daemon", lambda: WAITING)
    assert cli.main(["setup"]) == 1
    assert world == ["stop_daemon"]


def test_setup_stops_when_sync_fails(world, monkeypatch):
    monkeypatch.setattr(setup.sources_cli, "cmd_sync", lambda a: 1)
    assert cli.main(["setup"]) == 1
    assert world == []  # nothing downloaded, nothing installed


def test_no_login_runs_in_the_foreground_and_installs_nothing(world):
    assert cli.main(["setup", "--no-login"]) == 0
    assert world == [("sync", None, False), ("foreground", 8766)]


def test_setup_downloads_videos_only_when_asked(world):
    assert cli.main(["setup", "--pull", "12"]) == 0
    assert world[:2] == [("sync", None, False), ("pull", 12)]


def test_a_system_without_login_items_runs_in_the_foreground(world, monkeypatch):
    monkeypatch.setattr(autostart, "supported", lambda: False)
    assert cli.main(["setup"]) == 0
    assert "install" not in world and world[-1] == ("foreground", 8766)


def test_old_extension_is_asked_to_reload(world, monkeypatch, capsys):
    old = dict(CONNECTED, extension_version="0.2.0")
    monkeypatch.setattr(bridge, "ensure_daemon", lambda: old)
    assert cli.main(["setup"]) == 0
    assert "reload arrow" in capsys.readouterr().out


# -- uninstall ---------------------------------------------------------------

def _library(tmp_path):
    home = tmp_path / "home"
    (home / "library" / "abc").mkdir(parents=True)
    (home / "magpie.db").write_bytes(b"x")
    (home / "library" / "abc" / "video.mp4").write_bytes(b"x" * 1000)
    return home


def test_uninstall_stops_everything_and_deletes_the_library(world, tmp_path, capsys):
    home = _library(tmp_path)
    assert cli.main(["uninstall", "--yes"]) == 0
    assert world == ["uninstall", "stop_web", "stop_daemon"]
    assert not home.exists()
    out = capsys.readouterr().out
    assert "Magpie Bridge" in out and str(setup.REPO) in out


def test_uninstall_without_a_terminal_deletes_no_data(world, tmp_path, monkeypatch, capsys):
    home = _library(tmp_path)
    monkeypatch.setattr(setup.sys.stdin, "isatty", lambda: False, raising=False)
    assert cli.main(["uninstall"]) == 0
    assert home.exists() and "--yes" in capsys.readouterr().out
    assert world == ["uninstall", "stop_web", "stop_daemon"]  # the rest still happens


def test_uninstall_asks_and_takes_no_for_an_answer(world, tmp_path, monkeypatch):
    home = _library(tmp_path)
    monkeypatch.setattr(setup.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda q: "")
    assert cli.main(["uninstall"]) == 0 and home.exists()
    monkeypatch.setattr("builtins.input", lambda q: "y")
    assert cli.main(["uninstall"]) == 0 and not home.exists()


def test_uninstall_keep_data(world, tmp_path):
    home = _library(tmp_path)
    assert cli.main(["uninstall", "--yes", "--keep-data"]) == 0 and home.exists()


def test_uninstall_refuses_a_folder_that_is_not_magpies(world, tmp_path, monkeypatch, capsys):
    other = tmp_path / "documents"
    other.mkdir()
    (other / "thesis.docx").write_bytes(b"x")
    monkeypatch.setenv("MAGPIE_HOME", str(other))
    assert cli.main(["uninstall", "--yes"]) == 0
    assert (other / "thesis.docx").exists() and "left alone" in capsys.readouterr().out


def test_the_shared_speech_model_is_only_deleted_when_asked(world, tmp_path, monkeypatch, capsys):
    model = tmp_path / "hub" / "models--Systran--faster-whisper-small.en"
    model.mkdir(parents=True)
    (model / "model.bin").write_bytes(b"x")
    monkeypatch.setattr(setup, "model_dirs", lambda: [model] if model.exists() else [])
    assert cli.main(["uninstall", "--yes"]) == 0
    assert model.exists() and "--model" in capsys.readouterr().out
    assert cli.main(["uninstall", "--yes", "--model"]) == 0
    assert not model.exists()
