from __future__ import annotations

from datetime import datetime

import praw

from ideas_generator.models import RawItem
from ideas_generator.normalize import combine_title_body


def fetch_reddit_items(
    client_id: str,
    client_secret: str,
    user_agent: str,
    subreddits: list[str],
    limit_per_sub: int = 50,
) -> list[RawItem]:
    reddit = praw.Reddit(
        client_id=client_id,
        client_secret=client_secret,
        user_agent=user_agent,
    )
    items: list[RawItem] = []
    for sub in subreddits:
        subreddit = reddit.subreddit(sub.strip())
        for post in subreddit.new(limit=limit_per_sub):
            pid = str(post.id)
            title = post.title or ""
            body = post.selftext or ""
            url = f"https://reddit.com{post.permalink}"
            created = datetime.utcfromtimestamp(post.created_utc)
            text = combine_title_body(title, body)
            items.append(
                RawItem(
                    source=f"reddit:{sub.strip()}",
                    external_id=pid,
                    url=url,
                    text=text,
                    created_at=created,
                    engagement={
                        "score": int(post.score),
                        "num_comments": int(post.num_comments),
                    },
                )
            )
    return items
