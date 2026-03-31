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

from rich.console import Console

_console = Console(stderr=True)

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

**icp_segment**: Who would *buy* or *use* a product suggested by this post—pick the **best single label**:
- **b2b_devtools** — engineering, infra, CI/CD, APIs, data eng, internal platforms
- **b2b_sales_marketing** — sales, marketing, RevOps, CRM, ads, GTM tooling
- **b2b_finance_ops** — finance, accounting, FP&A, procurement, HR ops, legal ops
- **b2b_security_it** — security, compliance, ITSM, identity, risk
- **b2b_vertical_real_estate** — real estate, construction, prop tech buyers
- **b2b_vertical_healthcare** — clinics, payers, health IT, regulated care settings
- **b2b_vertical_other** — other clear B2B vertical (retail ops, logistics, education orgs, etc.)
- **consumer** — end consumers / prosumer apps (not primarily a business buyer)
- **prosumer_creator** — creators, indie hackers, solo tools, newsletters, media
- **meta_industry** — discussion *about* tech/startups/industry with no concrete buyer workflow
- **unclear** — cannot tell from the text

**willingness_to_pay_score** (0.0–1.0): How strongly the text signals someone would **pay for software** to address the pain—budget, vendor churn, procurement, ROI, compliance cost, “we need a tool”, explicit replacement of a product, etc. **0** if no buyer/purchase angle.

**wtp_rationale**: One short phrase (≤200 chars) citing the strongest signal (or “none” if score is low).

Respond ONLY with valid JSON matching this shape:
{"tool_opportunity_score": <number 0.0-1.0>, "category": "<one of: business_problem, market_news, consumer_interest, politics_world, gaming, research_link, opinion_analysis, other>", "content_angle": "<one of: problem_opportunity, news_or_event, mixed>", "one_line": "<short reason>", "icp_segment": "<one of the icp_segment labels above>", "willingness_to_pay_score": <number 0.0-1.0>, "wtp_rationale": "<short string>"}
"""


_CONTENT_ANGLES = frozenset({"problem_opportunity", "news_or_event", "mixed"})

_ICP_SEGMENTS = frozenset(
    {
        "b2b_devtools",
        "b2b_sales_marketing",
        "b2b_finance_ops",
        "b2b_security_it",
        "b2b_vertical_real_estate",
        "b2b_vertical_healthcare",
        "b2b_vertical_other",
        "consumer",
        "prosumer_creator",
        "meta_industry",
        "unclear",
    }
)


def normalize_content_angle(raw: str | None) -> str:
    a = (raw or "").strip().lower().replace("-", "_")
    if a in _CONTENT_ANGLES:
        return a
    return "mixed"


def normalize_icp_segment(raw: str | None) -> str:
    a = (raw or "").strip().lower().replace("-", "_")
    if a in _ICP_SEGMENTS:
        return a
    return "unclear"


def _sanitize_llm_text(text: str) -> str:
    """Strip NULs etc. that can produce invalid requests or odd API errors."""
    return (text or "").replace("\x00", "")


def _openai_error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error")
        if isinstance(err, dict):
            code = err.get("code") or err.get("type")
            msg = err.get("message")
            parts = [str(x) for x in (code, msg) if x]
            return ": ".join(parts) if parts else str(data)[:800]
        return str(data)[:800]
    except Exception:
        return (resp.text or "")[:800]


def _call_openai(
    messages: list[dict[str, str]],
    settings: Settings,
    *,
    json_object: bool = True,
) -> str:
    url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": settings.openai_model,
        "temperature": 0.1,
        "messages": messages,
    }
    if json_object:
        payload["response_format"] = {"type": "json_object"}
    base = settings.openai_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=120.0) as client:
            r = client.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if r.status_code == 400 and json_object:
                api_msg = _openai_error_message(r)
                low = api_msg.lower()
                if "response_format" in low or "json_object" in low:
                    payload.pop("response_format", None)
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
    except httpx.HTTPStatusError as e:
        detail = _openai_error_message(e.response)
        raise RuntimeError(
            f"OpenAI HTTP {e.response.status_code} for model={settings.openai_model!r}: {detail}"
        ) from e
    except httpx.ConnectError as e:
        hint = (
            f"Cannot connect to {base} ({e!s}). "
            "If you use a local OpenAI-compatible proxy (LiteLLM, Ollama, etc.), start it. "
            "Otherwise remove or fix IDEAS_OPENAI_BASE_URL (default is https://api.openai.com/v1)."
        )
        raise RuntimeError(hint) from e
    except httpx.ConnectTimeout as e:
        raise RuntimeError(
            f"Timeout connecting to {base} ({e!s}). Check network, VPN, or IDEAS_OPENAI_BASE_URL."
        ) from e
    return data["choices"][0]["message"]["content"]


def _user_block(text: str, url: str, source: str, max_chars: int) -> str:
    body = text if len(text) <= max_chars else text[:max_chars] + "…"
    return f"Source: {source}\nURL: {url}\n\nText:\n{body}\n"


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


def _normalize_wtp_rationale(raw: Any) -> str:
    s = str(raw or "").strip()
    return s[:200] if len(s) > 200 else s


def parse_verdict(raw_json: str) -> tuple[float, str, dict[str, Any]]:
    obj = json.loads(raw_json)
    score = float(obj.get("tool_opportunity_score", 0))
    score = max(0.0, min(1.0, score))
    cat = str(obj.get("category", "other"))
    obj["content_angle"] = normalize_content_angle(obj.get("content_angle"))
    obj["icp_segment"] = normalize_icp_segment(obj.get("icp_segment"))
    if "willingness_to_pay_score" in obj and obj["willingness_to_pay_score"] is not None:
        wtp = float(obj["willingness_to_pay_score"])
        obj["willingness_to_pay_score"] = max(0.0, min(1.0, wtp))
    if "wtp_rationale" in obj and obj["wtp_rationale"] is not None:
        obj["wtp_rationale"] = _normalize_wtp_rationale(obj["wtp_rationale"])
    return score, cat, obj


def classify_one(text: str, url: str, source: str, settings: Settings) -> tuple[float, str, str]:
    text = _sanitize_llm_text(text)
    last_exc: Exception | None = None
    for max_chars in (8000, 4000, 2000):
        user = _user_block(text, url, source, max_chars)
        try:
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
        except json.JSONDecodeError as e:
            last_exc = e
            continue
        except RuntimeError as e:
            err_s = str(e).lower()
            if (
                "context_length" in err_s
                or "too many tokens" in err_s
                or "maximum context length" in err_s
                or "token limit" in err_s
                or "reduce the length" in err_s
            ):
                last_exc = e
                continue
            raise
    raise RuntimeError(
        f"LLM classification failed after truncating input (last error: {last_exc})"
    ) from last_exc


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
    skipped = 0
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
        except RuntimeError as exc:
            conn.rollback()
            msg = str(exc)
            if msg.startswith("OpenAI HTTP 400"):
                skipped += 1
                _console.print(
                    f"[yellow]LLM screen skip[/yellow] id={row['id']} url={row['url']}: {msg}"
                )
                continue
            raise
        except Exception:
            conn.rollback()
            raise
        time.sleep(max(0.0, settings.llm_sleep_seconds))

    if skipped:
        _console.print(f"[yellow]Skipped {skipped} item(s) due to OpenAI HTTP 400[/yellow]")

    return done + n_stamped
