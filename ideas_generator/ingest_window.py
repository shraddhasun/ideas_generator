from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ideas_generator.models import RawItem


def filter_items_by_lookback(items: list[RawItem], lookback_seconds: int) -> list[RawItem]:
    """
    Keep only items whose ``created_at`` falls within the lookback window (UTC).

    ``lookback_seconds <= 0`` disables filtering (all items kept).
    Naive datetimes are treated as UTC.
    """
    if lookback_seconds <= 0:
        return items
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=lookback_seconds)
    out: list[RawItem] = []
    for it in items:
        ca = it.created_at
        if ca.tzinfo is None:
            ca_utc = ca.replace(tzinfo=timezone.utc)
        else:
            ca_utc = ca.astimezone(timezone.utc)
        if ca_utc >= cutoff:
            out.append(it)
    return out
