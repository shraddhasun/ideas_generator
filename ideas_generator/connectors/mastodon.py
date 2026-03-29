from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ideas_generator.connectors.base import engagement_points
from ideas_generator.models import RawItem
from ideas_generator.normalize import combine_title_body, strip_html


def fetch_mastodon_tag_timelines(
    host: str,
    hashtags: list[str],
    *,
    limit: int = 40,
    user_agent: str = "ideas-generator/0.1",
) -> list[RawItem]:
    """
    Public hashtag timelines (no token on most instances): ``/api/v1/timelines/tag/:tag``.
    ``host`` should be like ``mastodon.social`` (no scheme).
    """
    host = (host or "").strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
    hashtags = [h.strip().lstrip("#") for h in hashtags if h.strip()]
    if not host or not hashtags:
        return []

    limit = max(1, min(int(limit), 80))
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    base = f"https://{host}"
    items: list[RawItem] = []
    with httpx.Client(timeout=45.0) as client:
        for tag in hashtags:
            url = f"{base}/api/v1/timelines/tag/{tag}"
            try:
                r = client.get(url, params={"limit": limit}, headers=headers)
                r.raise_for_status()
                statuses = r.json()
            except (httpx.HTTPError, ValueError):
                continue
            if not isinstance(statuses, list):
                continue
            for st in statuses:
                if st.get("reblog"):
                    continue
                sid = st.get("id")
                if sid is None:
                    continue
                content = strip_html(st.get("content") or "")
                spoiler = strip_html(st.get("spoiler_text") or "")
                text = combine_title_body(spoiler, content) if spoiler else (content or "")
                if not text:
                    continue
                url_post = (st.get("url") or "").strip()
                if not url_post:
                    continue
                created = _parse_masto_time(str(st.get("created_at") or ""))
                reblogs = int(st.get("reblogs_count") or 0)
                favs = int(st.get("favourites_count") or 0)
                replies = int(st.get("replies_count") or 0)
                eng = int(reblogs) + int(favs) + int(replies)
                items.append(
                    RawItem(
                        source=f"mastodon:{host}",
                        external_id=f"mastodon:{host}:{sid}",
                        url=url_post,
                        text=text[:8000],
                        created_at=created,
                        engagement=engagement_points(eng, replies),
                    )
                )
    return items


def _parse_masto_time(s: str) -> datetime:
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
