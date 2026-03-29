from __future__ import annotations

import time

import httpx

from ideas_generator.connectors.base import engagement_points, dt_from_unix
from ideas_generator.models import RawItem
from ideas_generator.normalize import combine_title_body, strip_html


API = "https://api.stackexchange.com/2.3"


def fetch_stackexchange_items(sites: list[str], pages_per_site: int = 3) -> list[RawItem]:
    """Fetch recent questions from given Stack Exchange sites (no key; low quota)."""
    items: list[RawItem] = []
    with httpx.Client(timeout=30.0) as client:
        for site in sites:
            for page in range(1, pages_per_site + 1):
                params = {
                    "order": "desc",
                    "sort": "creation",
                    "site": site,
                    "pagesize": 100,
                    "page": page,
                    "filter": "withbody",
                }
                r = client.get(f"{API}/questions", params=params)
                r.raise_for_status()
                data = r.json()
                for q in data.get("items") or []:
                    qid = str(q.get("question_id"))
                    title = q.get("title") or ""
                    body = strip_html(q.get("body") or "")
                    link = q.get("link") or ""
                    cr = int(q.get("creation_date") or 0)
                    score = q.get("score")
                    ans = q.get("answer_count")
                    text = combine_title_body(title, body)
                    items.append(
                        RawItem(
                            source=f"stackexchange:{site}",
                            external_id=qid,
                            url=link,
                            text=text,
                            created_at=dt_from_unix(cr),
                            engagement=engagement_points(score, ans),
                        )
                    )
                if not data.get("has_more"):
                    break
                time.sleep(0.3)
    seen: set[tuple[str, str]] = set()
    out: list[RawItem] = []
    for it in items:
        k = (it.source, it.external_id)
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out
