from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ideas_generator.connectors.base import engagement_points
from ideas_generator.models import RawItem
from ideas_generator.normalize import combine_title_body, strip_html

PH_GRAPHQL = "https://api.producthunt.com/v2/api/graphql"

_POSTS_QUERY = """
query Posts($first: Int!) {
  posts(first: $first, order: RANKING) {
    edges {
      node {
        id
        name
        tagline
        url
        createdAt
        votesCount
        commentsCount
        description
      }
    }
  }
}
"""


def fetch_product_hunt_items(token: str, *, limit: int = 50) -> list[RawItem]:
    """Recent Product Hunt launches via official GraphQL API (requires developer token)."""
    token = (token or "").strip()
    if not token:
        return []

    first = max(1, min(int(limit), 100))
    payload = {"query": _POSTS_QUERY, "variables": {"first": first}}
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    items: list[RawItem] = []
    with httpx.Client(timeout=60.0) as client:
        r = client.post(PH_GRAPHQL, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    errors = data.get("errors")
    if errors:
        raise RuntimeError(f"Product Hunt API: {errors!r}")
    edges = (
        (((data.get("data") or {}).get("posts") or {}).get("edges"))
        or []
    )
    for edge in edges:
        node = (edge or {}).get("node") or {}
        pid = str(node.get("id") or "").strip()
        if not pid:
            continue
        name = (node.get("name") or "").strip()
        tagline = (node.get("tagline") or "").strip()
        url = (node.get("url") or "").strip() or "https://www.producthunt.com"
        desc = strip_html(node.get("description") or "")
        text = combine_title_body(name, f"{tagline}\n\n{desc}".strip() if desc else tagline)
        if not text:
            text = name or url
        created_raw = node.get("createdAt") or ""
        created_at = _parse_ph_datetime(str(created_raw))
        votes = int(node.get("votesCount") or 0)
        comments = int(node.get("commentsCount") or 0)
        items.append(
            RawItem(
                source="producthunt",
                external_id=pid,
                url=url,
                text=text,
                created_at=created_at,
                engagement=engagement_points(votes, comments),
            )
        )
    return items


def _parse_ph_datetime(s: str) -> datetime:
    s = s.strip()
    if not s:
        return datetime.now(tz=timezone.utc)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)
