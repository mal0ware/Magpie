"""sync() against a synthetic saved feed. No network, no browser."""

import pytest

from magpie.models import Item
from magpie.sources import feed
from magpie.sources.feed import Page, SourceStop
from magpie.sources.sync import sync
from magpie.store import Store


class FakeFeed:
    """A saved feed, newest first, served in pages. `fail_at` = (call number,
    stop kind) makes that call raise instead."""

    def __init__(self, codes, page_size=12, fail_at=None):
        self.codes = list(codes)
        self.page_size = page_size
        self.fail_at = fail_at
        self.calls = []

    def save(self, *codes):  # the user saves more posts; the last given is newest
        for c in codes:
            self.codes.insert(0, c)

    def __call__(self, max_id):
        self.calls.append(max_id)
        if self.fail_at and len(self.calls) == self.fail_at[0]:
            raise SourceStop(self.fail_at[1], "stop")
        start = int(max_id or 0)
        chunk = self.codes[start:start + self.page_size]
        end = start + len(chunk)
        more = end < len(self.codes)
        items = [Item(shortcode=c, url=feed.post_url(c), video_url=f"https://cdn/{c}?call={len(self.calls)}")
                 for c in chunk]
        return Page(items, str(end) if more else None, more)


def codes(n, prefix="p"):
    return [f"{prefix}{i:03d}" for i in range(n)]  # p000 is the newest


def order(store):
    return [i.shortcode for i in store.recent(limit=1000)]


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.db")


def run(store, fake, **kw):
    sleeps = []
    result = sync(store, fake, sleep=sleeps.append, **kw)
    return result, sleeps


def test_limit_30_then_second_run_adds_nothing(store):
    fake = FakeFeed(codes(100))
    result, sleeps = run(store, fake, limit=30)
    assert (result.new, result.seen, result.pages, result.ok) == (30, 30, 3, True)
    assert order(store) == codes(100)[:30]
    assert len(sleeps) == 2 and all(2.5 <= s <= 5.0 for s in sleeps)  # a pause between pages

    again, _ = run(store, fake, limit=30)
    assert again.new == 0 and store.count() == 30
    assert order(store) == codes(100)[:30]


def test_limit_refreshes_expiring_urls_of_known_items(store):
    fake = FakeFeed(codes(20))
    run(store, fake, limit=5)
    before = store.get("p000").video_url
    run(store, fake, limit=5)
    assert store.get("p000").video_url != before


def test_plain_sync_on_empty_library_takes_everything(store):
    fake = FakeFeed(codes(100))
    result, _ = run(store, fake)
    assert result.new == 100 and order(store) == codes(100)


def test_plain_sync_stops_at_first_known_shortcode(store):
    fake = FakeFeed(codes(100))
    run(store, fake, limit=30)
    fake.save("n1", "n2", "n3")
    fake.calls.clear()
    result, sleeps = run(store, fake)
    assert result.new == 3 and result.pages == 1 and sleeps == []
    assert order(store) == ["n3", "n2", "n1"] + codes(100)[:30]

    fake.calls.clear()
    nothing, _ = run(store, fake)
    assert nothing.new == 0 and nothing.pages == 1


def test_plain_sync_collects_several_pages_of_new_posts_in_one_go(store):
    fake = FakeFeed(codes(40))
    run(store, fake, limit=10)
    fake.save(*reversed(codes(30, "n")))  # n000 newest
    result, _ = run(store, fake)
    assert result.new == 30 and result.pages == 3
    assert order(store) == codes(30, "n") + codes(40)[:10]


def test_all_backfills_older_history_below(store):
    fake = FakeFeed(codes(50))
    run(store, fake, limit=30)
    fake.save("n1")
    result, _ = run(store, fake, everything=True)
    assert result.new == 21 and result.ok
    assert order(store) == fake.codes
    assert fake.calls[-1] is not None and len(fake.calls) > 3


def test_all_on_empty_library_writes_page_by_page(store):
    fake = FakeFeed(codes(50), fail_at=(3, feed.RATE_LIMITED))
    result, _ = run(store, fake, everything=True)
    assert result.stopped == feed.RATE_LIMITED and result.pages == 2
    assert order(store) == codes(50)[:24]  # the two pages before the 429 are kept

    fake.fail_at = None
    resumed, _ = run(store, fake, everything=True)
    assert resumed.new == 26 and order(store) == codes(50)


def test_limit_past_the_known_boundary_keeps_feed_order(store):
    fake = FakeFeed(codes(40), page_size=4)
    run(store, fake, limit=5)
    fake.save("n1", "n2")
    result, _ = run(store, fake, limit=10)
    assert result.new == 5
    assert order(store) == fake.codes[:10]


@pytest.mark.parametrize("kind", [feed.RATE_LIMITED, feed.LOGIN_REQUIRED, feed.CHECKPOINT])
def test_a_stop_is_never_retried(store, kind):
    fake = FakeFeed(codes(100), fail_at=(1, kind))
    result, sleeps = run(store, fake, limit=30)
    assert result.stopped == kind and not result.ok
    assert len(fake.calls) == 1 and sleeps == [] and store.count() == 0


def test_stop_before_reaching_known_posts_saves_nothing(store):
    fake = FakeFeed(codes(40))
    run(store, fake, limit=10)
    fake.save(*codes(30, "n"))
    fake.fail_at = (len(fake.calls) + 2, feed.RATE_LIMITED)
    result, _ = run(store, fake)
    assert result.stopped == feed.RATE_LIMITED and result.new == 0
    assert "not saved" in result.message
    assert order(store) == codes(40)[:10]  # no gap was created


def test_limit_smaller_than_the_new_posts_warns_about_the_gap(store):
    fake = FakeFeed(codes(40))
    run(store, fake, limit=10)
    fake.save(*reversed(codes(30, "n")))
    result, _ = run(store, fake, limit=5)
    assert result.new == 5 and result.ok and "skipped" in result.message
    assert order(store)[:5] == codes(30, "n")[:5]


def test_duplicate_entries_across_pages_are_counted_once(store):
    fake = FakeFeed(["a", "b", "c", "c", "d", "a"], page_size=3)
    result, _ = run(store, fake, everything=True)
    assert result.new == 4 and order(store) == ["a", "b", "c", "d"]


def test_empty_feed(store):
    result, _ = run(store, FakeFeed([]))
    assert result.ok and result.new == 0 and result.pages == 1
