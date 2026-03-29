from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from ideas_generator.connectors.base import engagement_points
from ideas_generator.models import RawItem
from ideas_generator.normalize import combine_title_body, normalize_text, strip_html


def fetch_discourse_latest(
    base_urls: list[str],
    *,
    topics_per_site: int = 30,
    user_agent: str = "ideas-generator/0.1",
) -> list[RawItem]:
    """
    Recent topics from Discourse forums via public ``/latest.json`` (no API key).
    """
    base_urls = [u.strip().rstrip("/") for u in base_urls if u.strip()]
    if not base_urls:
        return []

    n = max(1, min(int(topics_per_site), 100))
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    items: list[RawItem] = []
    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        for base in base_urls:
            host = urlparse(base).netloc or "discourse"
            url = f"{base}/latest.json"
            try:
                r = client.get(url, headers=headers)
                r.raise_for_status()
                data = r.json()
            except (httpx.HTTPError, ValueError):
                continue
            topics = (data.get("topic_list") or {}).get("topics") or []
            for t in topics[:n]:
                tid = t.get("id")
                if tid is None:
                    continue
                slug = (t.get("slug") or "").strip() or str(tid)
                title = normalize_text(t.get("title") or "")
                excerpt = strip_html(t.get("excerpt") or "")
                text = combine_title_body(title, excerpt)
                if not text:
                    text = title
                topic_url = f"{base}/t/{slug}/{tid}"
                created = _parse_discourse_time(str(t.get("created_at") or t.get("bumped_at") or ""))
                views = int(t.get("views") or 0)
                posts_n = int(t.get("posts_count") or t.get("reply_count") or 0)
                items.append(
                    RawItem(
                        source=f"discourse:{host}",
                        external_id=f"discourse:{host}:{int(tid)}",
                        url=topic_url,
                        text=text,
                        created_at=created,
                        engagement=engagement_points(views, posts_n),
                    )
                )
    return items


def _parse_discourse_time(s: str) -> datetime:
    s = (s or "").strip()
    if not s:
        return datetime.now(tz=timezone.utc).replace(tzinfo=None)
    try:
        if "T" in s:
            iso = s
            if iso.endswith("Z"):
                iso = iso[:-1] + "+00:00"
            dt = datetime.fromisoformat(iso)
        else:
            dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return datetime.now(tz=timezone.utc).replace(tzinfo=None)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
