from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import Counter, defaultdict
from typing import Any

from ideas_generator import db as dbm
from ideas_generator.config import Settings
from ideas_generator.llm_util import llm_screen_enabled
from ideas_generator.models import ScoredCluster

# Severity / WTP keyword lists (expand over time).
_SEVERITY = [
    "blocking",
    "blocked",
    "downtime",
    "lost revenue",
    "losing money",
    "compliance",
    "audit",
    "security breach",
    "outage",
    "deadline",
    "can't ship",
    "cant ship",
    "regulator",
    "gdpr",
    "pci",
    "fine",
    "penalty",
]

_WTP = [
    "pay for",
    "paying for",
    "budget",
    "subscription",
    "roi",
    "vendor",
    "tooling",
    "saas",
    "we use",
    "per seat",
    "invoice",
    "rfp",
    "renewal",
    "renewing",
    "soc2",
    "soc 2",
    "sla",
    "contract",
    "procurement",
    "enterprise",
    "purchase order",
    "list price",
    "quote",
]


def _engagement_value(eng: dict[str, Any]) -> float:
    pts = float(eng.get("points") or eng.get("score") or 0)
    com = float(eng.get("comments") or eng.get("num_comments") or eng.get("answer_count") or 0)
    return math.log1p(max(pts, 0)) + math.log1p(max(com, 0))


def _recency_decay(ts: float, now: float, half_life_days: float) -> float:
    age_days = max(0.0, (now - ts) / 86400.0)
    return math.exp(-age_days / max(half_life_days, 1e-6))


def _keyword_score(text: str, keywords: list[str]) -> float:
    low = text.lower()
    hits = sum(1 for k in keywords if k.lower() in low)
    return min(1.0, hits / 3.0)


def _verbatim_lead_excerpt(text: str, max_len: int = 400) -> str:
    """Short excerpt from the lead post for reports (verbatim evidence)."""
    t = (text or "").strip()
    if not t:
        return ""
    if t.lower().startswith("show hn:"):
        t = t[len("show hn:") :].strip()
    one_line = " ".join(t.split())
    if len(one_line) > max_len:
        return one_line[: max_len - 1] + "…"
    return one_line


def _fallback_problem_sentence(text: str) -> str:
    """One sentence from the lead post when the LLM did not provide one_line."""
    t = (text or "").strip()
    if not t:
        return ""
    if t.lower().startswith("show hn:"):
        t = t[len("show hn:") :].strip()
    line = t.split("\n")[0].strip()
    for i, ch in enumerate(line):
        if ch in ".!?" and i > 12:
            return line[: i + 1].strip()
    if len(line) > 240:
        return line[:237].rstrip() + "…"
    return line


def compute_cluster_scores(conn: sqlite3.Connection, settings: Settings) -> list[ScoredCluster]:
    now = time.time()
    t7 = now - 86400 * 7
    t30 = now - 86400 * 30

    params_list: list[float] = []
    clauses: list[str] = []
    if settings.min_business_tool_fit > 0:
        clauses.append("business_tool_fit IS NOT NULL AND business_tool_fit >= ?")
        params_list.append(float(settings.min_business_tool_fit))
    if llm_screen_enabled(settings):
        clauses.append("llm_tool_score IS NOT NULL AND llm_tool_score >= ?")
        params_list.append(float(settings.llm_min_tool_score))

    extra = (" AND " + " AND ".join(clauses)) if clauses else ""

    rows = conn.execute(
        f"""
        SELECT cluster_id, id, source, url, text, created_at, engagement_json,
               llm_tool_score, llm_category, llm_verdict_json
        FROM items
        WHERE cluster_id IS NOT NULL AND dropped_reason IS NULL
        {extra}
        """,
        tuple(params_list),
    ).fetchall()

    by_cluster: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_cluster[int(row["cluster_id"])].append(row)

    scored: list[ScoredCluster] = []

    for cid, items in by_cluster.items():
        texts = []
        rec7 = rec30 = 0
        recency_sum = 0.0
        eng_vals: list[float] = []
        sources: set[str] = set()
        best_url = ""
        best_text = ""
        lead_full = ""
        best_ts = 0.0
        rows_with_eng: list[tuple[sqlite3.Row, float]] = []
        llm_scores: list[float] = []
        cat_counter: Counter[str] = Counter()
        llm_one_line = ""

        for row in items:
            ts = float(row["created_at"])
            t = row["text"] or ""
            texts.append(t)
            if ts >= t7:
                rec7 += 1
            if ts >= t30:
                rec30 += 1
            recency_sum += _recency_decay(ts, now, settings.recency_half_life_days)
            try:
                eng = json.loads(row["engagement_json"] or "{}")
            except json.JSONDecodeError:
                eng = {}
            ev = _engagement_value(eng)
            eng_vals.append(ev)
            rows_with_eng.append((row, ev))
            sources.add(row["source"].split(":")[0])
            if row["llm_tool_score"] is not None:
                llm_scores.append(float(row["llm_tool_score"]))
            lc = row["llm_category"]
            if lc and str(lc).strip():
                cat_counter[str(lc).strip()] += 1
            if ts >= best_ts:
                best_ts = ts
                best_url = row["url"] or ""
                lead_full = t
                best_text = (t[:400] + "…") if len(t) > 400 else t

        best_llm_row: sqlite3.Row | None = None
        best_llm_sc = -1.0
        for row in items:
            sc = row["llm_tool_score"]
            if sc is None:
                continue
            f = float(sc)
            if f > best_llm_sc:
                best_llm_sc = f
                best_llm_row = row
        if best_llm_row is not None:
            try:
                v = json.loads(best_llm_row["llm_verdict_json"] or "{}")
                llm_one_line = str(v.get("one_line") or "").strip()
            except json.JSONDecodeError:
                llm_one_line = ""

        problem_sentence = (
            llm_one_line.strip() if llm_one_line else _fallback_problem_sentence(lead_full)
        )
        verbatim_lead = _verbatim_lead_excerpt(lead_full)

        src_counts = Counter(str(row["source"]) for row in items)
        source_breakdown = ", ".join(f"{s} ({c})" for s, c in src_counts.most_common())

        llm_score_avg: float | None = None
        if llm_scores:
            llm_score_avg = sum(llm_scores) / len(llm_scores)
        llm_category_mode = cat_counter.most_common(1)[0][0] if cat_counter else None

        extra_samples: list[tuple[str, str]] = []
        seen_urls = {best_url}
        for row, eng in sorted(rows_with_eng, key=lambda x: x[1], reverse=True):
            u = row["url"] or ""
            if not u or u in seen_urls:
                continue
            seen_urls.add(u)
            tt = row["text"] or ""
            snippet = (tt[:120] + "…") if len(tt) > 120 else tt
            extra_samples.append((snippet, u))
            if len(extra_samples) >= 2:
                break

        n = max(len(items), 1)
        recurrence_score = min(1.0, rec7 / 10.0) * 0.7 + min(1.0, rec30 / 25.0) * 0.3
        recency_score = min(1.0, recency_sum / max(n, 1))
        engagement_score = min(1.0, sum(eng_vals) / max(n, 1) / 5.0)
        cross = min(1.0, (len(sources) - 1) * 0.5 + 0.2) if len(sources) else 0.2

        blob = "\n".join(texts)
        severity_score = _keyword_score(blob, _SEVERITY)
        wtp_score = _keyword_score(blob, _WTP)

        composite = (
            settings.weight_recurrence * recurrence_score
            + settings.weight_recency * recency_score
            + settings.weight_engagement * engagement_score
            + settings.weight_cross_platform * cross
            + settings.weight_severity * severity_score
            + settings.weight_wtp * wtp_score
        )

        scored.append(
            ScoredCluster(
                cluster_id=cid,
                recurrence_7d=rec7,
                recurrence_30d=rec30,
                recency_score=recency_score,
                engagement_score=engagement_score,
                source_count=len(sources),
                severity_score=severity_score,
                wtp_score=wtp_score,
                composite=composite,
                sample_text=best_text,
                sample_url=best_url,
                item_count=len(items),
                llm_score_avg=llm_score_avg,
                llm_category_mode=llm_category_mode,
                source_breakdown=source_breakdown,
                llm_one_line=llm_one_line,
                problem_sentence=problem_sentence,
                verbatim_lead=verbatim_lead,
                extra_samples=extra_samples,
            )
        )

    scored.sort(
        key=lambda s: (s.composite, s.recurrence_7d, s.recurrence_30d),
        reverse=True,
    )
    return scored


def persist_snapshots(
    conn: sqlite3.Connection, scored: list[ScoredCluster], run_at: float | None = None
) -> None:
    run_at = run_at or time.time()
    for s in scored:
        payload = {
            "recurrence_7d": s.recurrence_7d,
            "recurrence_30d": s.recurrence_30d,
            "recency_score": s.recency_score,
            "engagement_score": s.engagement_score,
            "source_count": s.source_count,
            "severity_score": s.severity_score,
            "wtp_score": s.wtp_score,
            "composite": s.composite,
        }
        dbm.save_snapshot(conn, run_at, s.cluster_id, payload)
    conn.commit()
