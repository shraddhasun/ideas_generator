from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from ideas_generator.connectors.base import engagement_points
from ideas_generator.models import RawItem
from ideas_generator.normalize import combine_title_body, normalize_text


def fetch_lemmy_posts(
    host: str,
    *,
    community_name: str = "",
    limit: int = 25,
    user_agent: str = "ideas-generator/0.1",
) -> list[RawItem]:
    """
    Public post list from a Lemmy instance (``/api/v3/post/list``). No token for read.
    Optionally filter by ``community_name`` (e.g. ``asklemmy`` on that instance).
    """
    host = (host or "").strip().lower().replace("https://", "").replace("http://", "").split("/")[0]
    if not host:
        return []

    limit = max(1, min(int(limit), 50))
    base = f"https://{host}"
    params: dict[str, str | int] = {
        "type_": "All",
        "sort": "New",
        "limit": limit,
        "page": 1,
    }
    comm = (community_name or "").strip()
    if comm:
        # strip community@host if user pasted full id
        if "@" in comm:
            comm = comm.split("@")[0]
        params["community_name"] = comm

    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    items: list[RawItem] = []
    with httpx.Client(timeout=45.0) as client:
        url = f"{base}/api/v3/post/list"
        try:
            r = client.get(url, params=params, headers=headers)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError):
            return items

        posts = data.get("posts") if isinstance(data, dict) else None
        if not isinstance(posts, list):
            return items

        label = urlparse(base).netloc or host
        for wrap in posts:
            p = wrap.get("post") if isinstance(wrap, dict) else None
            if not isinstance(p, dict):
                continue
            pid = p.get("id")
            if pid is None:
                continue
            title = normalize_text(p.get("name") or "")
            body = normalize_text(p.get("body") or "")
            text = combine_title_body(title, body)
            if not text:
                text = title
            if not text:
                continue
            url_post = (p.get("url") or "").strip()
            if not url_post:
                ap = (p.get("ap_id") or "").strip()
                if ap:
                    url_post = ap
                else:
                    continue
            created = _parse_lemmy_time(str(p.get("published") or ""))
            comments = int(p.get("unread_comments") or p.get("comments") or 0)
            score = int(p.get("score") or 0)
            items.append(
                RawItem(
                    source=f"lemmy:{label}",
                    external_id=f"lemmy:{label}:{int(pid)}",
                    url=url_post,
                    text=text[:8000],
                    created_at=created,
                    engagement=engagement_points(score, comments),
                )
            )
    return items


def _parse_lemmy_time(s: str) -> datetime:
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
