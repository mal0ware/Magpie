import pytest

from magpie.pipeline import fetch


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test reaches the internet. Tests that download replace this themselves."""
    def refuse(url, dest, timeout=60):
        raise OSError("no network in tests")

    monkeypatch.setattr(fetch, "download_url", refuse)
