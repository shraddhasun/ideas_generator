from __future__ import annotations

from datetime import datetime


def engagement_points(points: int | None, comments: int | None) -> dict:
    out: dict[str, int] = {}
    if points is not None:
        out["points"] = int(points)
    if comments is not None:
        out["comments"] = int(comments)
    return out


def dt_from_unix(ts: float | int) -> datetime:
    return datetime.utcfromtimestamp(float(ts))
