from __future__ import annotations

import html
import re


_ws = re.compile(r"\s+")
_html_tags = re.compile(r"<[^>]+>")


def strip_html(text: str) -> str:
    t = _html_tags.sub(" ", text or "")
    return normalize_text(t)


def normalize_text(text: str) -> str:
    t = html.unescape(text or "")
    t = _ws.sub(" ", t).strip()
    return t


def combine_title_body(title: str, body: str) -> str:
    title = normalize_text(title)
    body = normalize_text(body)
    if not body:
        return title
    if not title:
        return body
    return f"{title}\n\n{body}"
