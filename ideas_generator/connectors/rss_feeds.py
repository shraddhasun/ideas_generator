from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import feedparser
import httpx

from ideas_generator.connectors.base import engagement_points
from ideas_generator.models import RawItem
from ideas_generator.normalize import combine_title_body, strip_html


def _feed_label(feed_url: str) -> str:
    try:
        host = (urlparse(feed_url).hostname or "rss").lower()
        return host.replace("www.", "")
    except Exception:
        return "rss"


def _entry_datetime(entry: feedparser.FeedParserDict) -> datetime:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError):
                continue
    raw = entry.get("published") or entry.get("updated") or ""
    if isinstance(raw, str) and raw.strip():
        try:
            dt = parsedate_to_datetime(raw.strip())
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc)
            return dt.replace(tzinfo=None)
        except (TypeError, ValueError):
            pass
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _external_id(link: str, title: str) -> str:
    base = f"{link}|{title}"[:500]
    return hashlib.sha256(base.encode("utf-8", errors="replace")).hexdigest()[:32]


def fetch_rss_feeds(
    feed_urls: list[str],
    *,
    max_per_feed: int = 25,
    user_agent: str = "ideas-generator/0.1",
) -> list[RawItem]:
    """
    Fetch public RSS/Atom feeds — **no API key**. Works for Lobsters (``/h.rss``), blogs, etc.
    """
    feed_urls = [u.strip() for u in feed_urls if u.strip()]
    if not feed_urls:
        return []

    max_per_feed = max(1, min(int(max_per_feed), 200))
    headers = {"User-Agent": user_agent, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}
    items: list[RawItem] = []
    with httpx.Client(timeout=45.0, follow_redirects=True) as client:
        for feed_url in feed_urls:
            label = _feed_label(feed_url)
            try:
                r = client.get(feed_url, headers=headers)
                r.raise_for_status()
            except httpx.HTTPError:
                continue
            parsed = feedparser.parse(r.content)
            for entry in (parsed.entries or [])[:max_per_feed]:
                link = (entry.get("link") or "").strip()
                title = strip_html(entry.get("title") or "")
                summary = strip_html(entry.get("summary") or entry.get("description") or "")
                text = combine_title_body(title, summary)
                if not text and link:
                    text = link
                if not text:
                    continue
                if not link:
                    link = feed_url
                eid = _external_id(link, title)
                items.append(
                    RawItem(
                        source=f"rss:{label}",
                        external_id=f"rss:{label}:{eid}",
                        url=link,
                        text=text,
                        created_at=_entry_datetime(entry),
                        engagement=engagement_points(None, None),
                    )
                )
    return items
