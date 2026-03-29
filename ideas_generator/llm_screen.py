from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import httpx
from rich.progress import track

from ideas_generator import db as dbm
from ideas_generator.config import Settings
from ideas_generator.llm_util import llm_screen_enabled

_SYSTEM = """You classify posts from Hacker News, forums, and Q&A sites.

Goal: say how strong a **niche B2B / operational software opportunity** the content is—whether a **small product team** could plausibly **own** the problem with a tool, integration, or workflow product. Prefer **specific** pain (named workflow, system, role, or vertical) over generic “startups should…” or broad industry commentary.

A HIGH score (0.7–1.0) means: **concrete operational or commercial pain** in a business context—integrations, rev/finance ops, IT, security/compliance, support, data pipelines, procurement, or clear buyer frustration with existing tools—and the text gives enough thread that **someone could validate and build** against it.

A LOW score (0.0–0.3) means: **market or stock news**, fundraising hype without pain, **generic career/startup advice**, crypto/speculation, politics/war, consumer hobbies, gaming, pure research with no business process angle, or **commentary without** a “who would pay for a fix” story.

Middle band: ambiguous, thin detail, or weak product angle.

**content_angle** (what the reader can *do* with it for product ideation—not the same as category):
- **problem_opportunity**: Surfaces **recurring pain**, a workflow gap, buyer friction, or demand for a better tool—even if the **format** is partly news-like—**if** it still explains what is broken, for whom, or what’s missing operationally.
- **news_or_event**: Mostly **informational**: what happened (funding, lawsuit, headline) **without** a usable line on **ongoing operational pain** or what to build next.
- **mixed**: Both event-reporting and explicit problem/solution framing.

**one_line**: One short sentence: **who** (role/org type) has the problem and **what** gap or workaround (not generic praise/criticism of a headline). If the post is low-signal for product work, say why briefly.

Respond ONLY with valid JSON matching this shape:
{"tool_opportunity_score": <number 0.0-1.0>, "category": "<one of: business_problem, market_news, consumer_interest, politics_world, gaming, research_link, opinion_analysis, other>", "content_angle": "<one of: problem_opportunity, news_or_event, mixed>", "one_line": "<short reason>"}
"""


_CONTENT_ANGLES = frozenset({"problem_opportunity", "news_or_event", "mixed"})


def normalize_content_angle(raw: str | None) -> str:
    a = (raw or "").strip().lower().replace("-", "_")
    if a in _CONTENT_ANGLES:
        return a
    return "mixed"


def _call_openai(messages: list[dict[str, str]], settings: Settings) -> str:
    url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": settings.openai_model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": messages,
    }
    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"]


def _call_gemini(user_block: str, settings: Settings) -> str:
    key = (settings.gemini_api_key or "").strip()
    if not key:
        raise ValueError("GEMINI_API_KEY is not set")
    model = settings.gemini_model.strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    combined = _SYSTEM + "\n\n---\n\n" + user_block
    payload = {
        "contents": [{"role": "user", "parts": [{"text": combined}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, params={"key": key}, json=payload)
        r.raise_for_status()
        data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini returned no candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    if not parts:
        raise ValueError("Gemini candidate had no parts")
    return parts[0]["text"]


def parse_verdict(raw_json: str) -> tuple[float, str, dict[str, Any]]:
    obj = json.loads(raw_json)
    score = float(obj.get("tool_opportunity_score", 0))
    score = max(0.0, min(1.0, score))
    cat = str(obj.get("category", "other"))
    obj["content_angle"] = normalize_content_angle(obj.get("content_angle"))
    return score, cat, obj


def classify_one(text: str, url: str, source: str, settings: Settings) -> tuple[float, str, str]:
    user = (
        f"Source: {source}\nURL: {url}\n\nText:\n{text[:8000]}\n"
        if len(text) <= 8000
        else f"Source: {source}\nURL: {url}\n\nText:\n{text[:8000]}…\n"
    )
    if settings.llm_provider == "gemini":
        raw = _call_gemini(user, settings)
    else:
        raw = _call_openai(
            [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
            settings,
        )
    score, cat, obj = parse_verdict(raw)
    return score, cat, json.dumps(obj, ensure_ascii=False)


def verdict_content_angle(verdict_json: str) -> str:
    """Return normalized content_angle from stored verdict JSON (default mixed)."""
    try:
        obj = json.loads(verdict_json or "{}")
    except json.JSONDecodeError:
        return "mixed"
    return normalize_content_angle(obj.get("content_angle"))


def run_llm_screen(conn: sqlite3.Connection, settings: Settings, *, force: bool = False) -> int:
    if not llm_screen_enabled(settings):
        return 0

    n_stamped = dbm.stamp_skipped_llm_low_embed(
        conn, settings.llm_screen_min_embed_fit
    )
    conn.commit()

    pending = dbm.list_items_pending_llm(
        conn,
        min_embed_fit_to_screen=settings.llm_screen_min_embed_fit,
        force=force,
        limit=settings.llm_max_items_per_run,
    )

    done = 0
    for row in track(pending, description="LLM screen"):
        try:
            score, cat, verdict_json = classify_one(
                str(row["text"]),
                str(row["url"]),
                str(row["source"]),
                settings,
            )
            dbm.set_llm_verdict(
                conn,
                int(row["id"]),
                tool_score=score,
                category=cat,
                verdict_json=verdict_json,
                content_angle=verdict_content_angle(verdict_json),
            )
            done += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        time.sleep(max(0.0, settings.llm_sleep_seconds))

    return done + n_stamped
