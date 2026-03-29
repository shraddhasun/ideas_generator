from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ideas_generator.connectors.base import engagement_points
from ideas_generator.models import RawItem
from ideas_generator.normalize import combine_title_body, normalize_text

DEVTO_API = "https://dev.to/api/articles"


def fetch_devto_articles(token: str | None = None, *, limit: int = 30) -> list[RawItem]:
    """
    Recent public articles from dev.to (official REST API).
    Optional **api-key** for authenticated rate limits: https://developers.forem.com/api
    """
    n = max(1, min(int(limit), 1000))
    params = {"per_page": n}
    headers = {"Accept": "application/json", "User-Agent": "ideas-generator/0.1"}
    key = (token or "").strip()
    if key:
        headers["api-key"] = key
    items: list[RawItem] = []
    with httpx.Client(timeout=45.0) as client:
        r = client.get(DEVTO_API, params=params, headers=headers)
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, list):
        return items
    for art in data:
        aid = art.get("id")
        if aid is None:
            continue
        title = normalize_text(art.get("title") or "")
        desc = normalize_text(art.get("description") or "")
        text = combine_title_body(title, desc)
        if not text:
            continue
        url = (art.get("url") or "").strip() or f"https://dev.to{art.get('path') or ''}"
        ts = str(art.get("published_timestamp") or "")
        created = _parse_iso(ts)
        reactions = int(art.get("public_reactions_count") or art.get("positive_reactions_count") or 0)
        comments = int(art.get("comments_count") or 0)
        items.append(
            RawItem(
                source="devto",
                external_id=str(aid),
                url=url,
                text=text,
                created_at=created,
                engagement=engagement_points(reactions, comments),
            )
        )
    return items


def _parse_iso(s: str) -> datetime:
    s = (s or "").strip()
    if not s:
        return datetime.now(tz=timezone.utc).replace(tzinfo=None)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return datetime.now(tz=timezone.utc).replace(tzinfo=None)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
