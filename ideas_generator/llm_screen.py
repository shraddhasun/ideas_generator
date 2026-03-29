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

Goal: say how strong a **business tool / B2B product opportunity** the content is.

A HIGH score (0.7–1.0) means: a **concrete operational or commercial pain** that organizations face and that could plausibly be addressed by **building and selling software**—SaaS, internal tools, integrations, automation, compliance/security products, data platforms, support/ops tools—not just reading about a stock or a headline.

A LOW score (0.0–0.3) means: **market news**, stock moves, **general interest**, politics/war, consumer gadget chatter, gaming, pure research links, or commentary **without** a clear “someone would pay for a product to fix this” angle.

Middle band: ambiguous or weak product angle.

**content_angle** (what the reader can *do* with it for product ideation—not the same as category):
- **problem_opportunity**: The piece **surfaces a problem that needs solving**—recurring pain, workflow gap, need for a tool, buyer friction, or clear demand for a better approach. Use this even when the **format** is news-like (reporting an industry event, case, or story) if that reporting is in service of **explaining or illustrating the problem** (what’s broken, who suffers, what’s missing).
- **news_or_event**: Mostly **informational**: reports what happened (incident, lawsuit, funding, headline) **without** a usable thread of **ongoing operational pain** or **what buyers/builders should solve next**. Pure “here’s the story” or spectacle, not “here’s the gap to fix.”
- **mixed**: Real mix of event-reporting and explicit problem/solution framing.

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
