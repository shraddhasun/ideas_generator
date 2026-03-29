from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ideas_generator.connectors.base import engagement_points
from ideas_generator.models import RawItem
from ideas_generator.normalize import combine_title_body, normalize_text


GITHUB_API = "https://api.github.com"


def _parse_github_datetime(s: str) -> datetime:
    s = (s or "").strip()
    if not s:
        return datetime.now(tz=timezone.utc)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def fetch_github_issues(
    token: str | None,
    repos: list[str],
    *,
    per_repo: int = 25,
    user_agent: str = "ideas-generator/0.1",
) -> list[RawItem]:
    """
    Recent open issues from given ``owner/repo`` pairs (not pull requests).
    Token optional but strongly recommended (higher rate limits).
    """
    repos = [r.strip() for r in repos if r.strip()]
    if not repos:
        return []

    tok = (token or "").strip()
    base_headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": user_agent,
    }
    auth_headers = {**base_headers}
    if tok:
        # GitHub accepts Bearer for PATs; classic tokens also work as `token ghp_...`.
        auth_headers["Authorization"] = f"Bearer {tok}"

    per_repo = max(1, min(int(per_repo), 100))
    items: list[RawItem] = []
    with httpx.Client(timeout=60.0) as client:
        for full in repos:
            parts = full.split("/", 1)
            if len(parts) != 2 or not parts[0] or not parts[1]:
                continue
            owner, repo = parts[0], parts[1]
            url = (
                f"{GITHUB_API}/repos/{owner}/{repo}/issues"
                f"?state=open&per_page={per_repo}&sort=updated&direction=desc"
            )
            r = client.get(url, headers=auth_headers)
            # Invalid / mis-scoped fine-grained tokens often return 403 on public repos; retry unauthenticated.
            if r.status_code in (401, 403) and tok:
                r = client.get(url, headers=base_headers)
            if r.status_code == 404:
                continue
            if not r.is_success:
                detail = (r.text or "")[:400]
                raise RuntimeError(
                    f"GitHub API {r.status_code} for {owner}/{repo}: {detail or r.reason_phrase}"
                )
            batch = r.json()
            if not isinstance(batch, list):
                continue
            for issue in batch:
                if issue.get("pull_request"):
                    continue
                num = issue.get("number")
                iid = issue.get("id")
                if num is None or iid is None:
                    continue
                title = normalize_text(issue.get("title") or "")
                body = normalize_text(issue.get("body") or "")
                text = combine_title_body(title, body)
                if not text:
                    continue
                html_url = issue.get("html_url") or f"https://github.com/{owner}/{repo}/issues/{num}"
                created = _parse_github_datetime(str(issue.get("created_at") or ""))
                n_comments = int(issue.get("comments") or 0)
                items.append(
                    RawItem(
                        source=f"github:{owner}/{repo}",
                        external_id=f"github:{owner}:{repo}:{int(num)}",
                        url=html_url,
                        text=text,
                        created_at=created,
                        engagement=engagement_points(None, n_comments),
                    )
                )
    return items
