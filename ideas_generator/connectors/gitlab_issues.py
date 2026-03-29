from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from ideas_generator.connectors.base import engagement_points
from ideas_generator.models import RawItem
from ideas_generator.normalize import combine_title_body, normalize_text


def fetch_gitlab_issues(
    token: str | None,
    projects: list[str],
    *,
    host: str = "https://gitlab.com",
    per_project: int = 25,
    user_agent: str = "ideas-generator/0.1",
) -> list[RawItem]:
    """
    Open issues from public GitLab projects (``namespace/project`` on ``host``).
    Token optional; improves rate limits and private project access.
    """
    projects = [p.strip() for p in projects if p.strip()]
    if not projects:
        return []

    base = host.rstrip("/")
    per_project = max(1, min(int(per_project), 100))
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json",
    }
    tok = (token or "").strip()
    if tok:
        headers["PRIVATE-TOKEN"] = tok

    items: list[RawItem] = []
    with httpx.Client(timeout=60.0) as client:
        for project in projects:
            enc = quote(project, safe="")
            url = f"{base}/api/v4/projects/{enc}/issues?state=opened&per_page={per_project}&order_by=updated_at"
            r = client.get(url, headers=headers)
            if r.status_code == 404:
                continue
            if r.status_code in (401, 403) and tok:
                h2 = {k: v for k, v in headers.items() if k != "PRIVATE-TOKEN"}
                r = client.get(url, headers=h2)
            if r.status_code == 404:
                continue
            if not r.is_success:
                continue
            batch = r.json()
            if not isinstance(batch, list):
                continue
            for issue in batch:
                iid = issue.get("iid")
                iid_db = issue.get("id")
                if iid is None or iid_db is None:
                    continue
                title = normalize_text(issue.get("title") or "")
                body = normalize_text(issue.get("description") or "")
                text = combine_title_body(title, body)
                if not text:
                    continue
                html_url = (issue.get("web_url") or "").strip()
                if not html_url:
                    continue
                created = _parse_gitlab_time(str(issue.get("created_at") or ""))
                n_comments = int(issue.get("user_notes_count") or 0)
                items.append(
                    RawItem(
                        source=f"gitlab:{project}",
                        external_id=f"gitlab:{project}:{int(iid)}",
                        url=html_url,
                        text=text,
                        created_at=created,
                        engagement=engagement_points(None, n_comments),
                    )
                )
    return items


def _parse_gitlab_time(s: str) -> datetime:
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
