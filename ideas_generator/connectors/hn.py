from __future__ import annotations

import time

import httpx

from ideas_generator.connectors.base import engagement_points, dt_from_unix
from ideas_generator.models import RawItem
from ideas_generator.normalize import normalize_text


HN_ALGOLIA = "https://hn.algolia.com/api/v1"


def fetch_hn_items(lookback_seconds: int) -> list[RawItem]:
    """Fetch recent HN stories via Algolia search API (no auth)."""
    now = int(time.time())
    min_ts = now - lookback_seconds
    items: list[RawItem] = []
    page = 0

    with httpx.Client(timeout=30.0) as client:
        while page < 8:
            params = {
                "tags": "story",
                "numericFilters": f"created_at_i>{min_ts}",
                "page": page,
                "hitsPerPage": 50,
            }
            r = client.get(f"{HN_ALGOLIA}/search", params=params)
            r.raise_for_status()
            data = r.json()
            hits = data.get("hits") or []
            if not hits:
                break
            for h in hits:
                oid = str(h.get("objectID") or h.get("story_id") or "")
                if not oid:
                    continue
                title = normalize_text(h.get("title") or "")
                url = h.get("url") or f"https://news.ycombinator.com/item?id={oid}"
                created = int(h.get("created_at_i") or 0)
                pts = h.get("points")
                ncom = h.get("num_comments")
                text = title
                items.append(
                    RawItem(
                        source="hn",
                        external_id=oid,
                        url=url,
                        text=text,
                        created_at=dt_from_unix(created),
                        engagement=engagement_points(pts, ncom),
                    )
                )
            page += 1
            if len(hits) < 50:
                break

    # Dedupe by external_id keeping latest fetch order
    seen: set[str] = set()
    out: list[RawItem] = []
    for it in items:
        if it.external_id in seen:
            continue
        seen.add(it.external_id)
        out.append(it)
    return out
