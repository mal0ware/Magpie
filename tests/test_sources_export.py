import json
from pathlib import Path

from magpie import cli
from magpie.sources import export
from magpie.store import Store

FIX = Path(__file__).parent / "fixtures" / "sources_saved_posts.json"


def order(store):
    return [i.shortcode for i in store.recent(limit=100)]


def test_parse_export_sorts_newest_saved_first_and_dedupes():
    items = export.parse_export(json.loads(FIX.read_text(encoding="utf-8")))
    assert [i.shortcode for i in items] == ["DReelAAA111", "DTvEEE55555", "DVideoDDD44"]
    assert [i.author for i in items] == ["cook.with.sam", "gym_notes", "old.uploads"]
    assert items[0].kind == "reel" and items[0].url == "https://www.instagram.com/reel/DReelAAA111/"


def test_parse_export_copes_with_an_unknown_layout():
    data = [{"label_values": [{"label": "URL", "value": "https://www.instagram.com/reel/AAA/"}]},
            {"media": [], "href": "https://www.instagram.com/p/BBB/"}]
    assert [i.shortcode for i in export.parse_export(data)] == ["AAA", "BBB"]  # file order kept
    assert export.parse_export({"unrelated": 1}) == []


def test_import_into_empty_then_into_existing_library(tmp_path):
    s = Store(tmp_path / "t.db")
    assert export.import_export(s, FIX) == (3, 3)
    assert order(s) == ["DReelAAA111", "DTvEEE55555", "DVideoDDD44"]
    assert export.import_export(s, FIX) == (0, 3)

    s2 = Store(tmp_path / "t2.db")
    export.add_urls(s2, ["https://www.instagram.com/reel/NEWEST/"])
    assert export.import_export(s2, FIX) == (3, 3)
    assert order(s2) == ["NEWEST", "DReelAAA111", "DTvEEE55555", "DVideoDDD44"]  # history goes below


def test_add_urls_puts_them_on_top_first_url_uppermost(tmp_path):
    s = Store(tmp_path / "t.db")
    export.add_urls(s, ["https://www.instagram.com/reel/OLD/"])
    new, items, bad = export.add_urls(s, [
        "https://www.instagram.com/reel/A1/", " https://www.instagram.com/p/B2/?img_index=1 ",
        "not a url", "https://www.instagram.com/reel/A1/", ""])
    assert (new, len(items), bad) == (2, 2, ["not a url"])
    assert order(s) == ["A1", "B2", "OLD"]


def test_cli_import_and_add(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MAGPIE_HOME", str(tmp_path))
    assert cli.main(["import", str(FIX)]) == 0
    assert "3 new of 3" in capsys.readouterr().out
    assert cli.main(["add", "https://www.instagram.com/reel/ZZZ/", "junk"]) == 0
    out = capsys.readouterr()
    assert "1 new of 1" in out.out and "junk" in out.err
    assert order(Store()) [0] == "ZZZ" and Store().count() == 4
    assert cli.main(["add", "junk"]) == 1
    assert cli.main(["import", str(tmp_path / "missing.json")]) == 1
