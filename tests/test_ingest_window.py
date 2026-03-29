import time
from datetime import datetime, timedelta, timezone

from ideas_generator.ingest_window import filter_items_by_lookback
from ideas_generator.models import RawItem


def _item(created: datetime) -> RawItem:
    return RawItem(
        source="test",
        external_id="1",
        url="http://x",
        text="t",
        created_at=created,
    )


def test_filter_disabled_when_zero():
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    items = [_item(old)]
    assert filter_items_by_lookback(items, 0) == items


def test_filter_keeps_recent():
    now = datetime.now(timezone.utc)
    recent = _item(now - timedelta(days=1))
    old = _item(now - timedelta(days=30))
    out = filter_items_by_lookback([recent, old], 86400 * 7)
    assert len(out) == 1
    assert out[0] is recent


def test_filter_naive_datetime_treated_as_utc():
    now = time.time()
    recent = _item(datetime.utcfromtimestamp(now - 3600))
    old = _item(datetime.utcfromtimestamp(now - 86400 * 10))
    out = filter_items_by_lookback([recent, old], 86400 * 7)
    assert len(out) == 1
