from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ideas_generator import db as dbm
from ideas_generator.config import get_settings
from ideas_generator.llm_screen import normalize_icp_segment

_ROLE_KEYWORDS = (
    "software engineer",
    "engineering team",
    "developer",
    "dev team",
    "platform team",
    "sre",
    "devops",
    "product manager",
    "pm team",
    "product design",
    "product designer",
    "ux team",
    "ui team",
    "design ops",
)

_TOOL_PAIN_KEYWORDS = (
    "tool",
    "tools",
    "workflow",
    "integration",
    "manual",
    "automation",
    "broken",
    "friction",
    "slow",
    "pain",
    "workaround",
    "replace",
    "migrate",
    "vendor",
    "cost",
    "budget",
    "compliance",
    "approval",
    "handoff",
    "context switching",
    "backlog",
    "debugging",
    "incident",
    "deployment",
    "design handoff",
    "ticket triage",
)


@dataclass
class DevtoolsCluster:
    cluster_id: int
    item_count: int
    recurrence_7d: int
    recurrence_30d: int
    recurrence_score: float
    recency_score: float
    engagement_score: float
    wtp_score: float | None
    composite: float
    problem: str
    lead_text: str
    lead_url: str
    source_count: int
    role_mix: str
    wtp_note: str
    composite_rank: int = 0


def _engagement_value(eng: dict) -> float:
    pts = float(eng.get("points") or eng.get("score") or 0)
    com = float(eng.get("comments") or eng.get("num_comments") or eng.get("answer_count") or 0)
    return math.log1p(max(pts, 0)) + math.log1p(max(com, 0))


def _recency_decay(ts: float, now: float, half_life_days: float = 21.0) -> float:
    age_days = max(0.0, (now - ts) / 86400.0)
    return math.exp(-age_days / max(half_life_days, 1e-6))


def _fallback_problem_sentence(text: str) -> str:
    line = " ".join((text or "").strip().split())
    if not line:
        return "Unknown pain point"
    for i, ch in enumerate(line):
        if ch in ".!?" and i > 20:
            return line[: i + 1]
    return line[:220] + ("…" if len(line) > 220 else "")


def _extract_verdict(vj: str) -> dict:
    try:
        return json.loads(vj or "{}")
    except json.JSONDecodeError:
        return {}


def _is_devtools_item(text: str, verdict_json: str) -> bool:
    low = (text or "").lower()
    role_hit = any(k in low for k in _ROLE_KEYWORDS)
    pain_hit = any(k in low for k in _TOOL_PAIN_KEYWORDS)
    verdict = _extract_verdict(verdict_json)
    icp = normalize_icp_segment(verdict.get("icp_segment"))
    llm_devtools = icp == "b2b_devtools"
    return llm_devtools or (role_hit and pain_hit)


def _cluster_rows(conn: sqlite3.Connection, *, days: int = 90) -> list[DevtoolsCluster]:
    now = time.time()
    t_min = now - days * 86400
    t7 = now - 7 * 86400
    t30 = now - 30 * 86400
    rows = conn.execute(
        """
        SELECT cluster_id, source, url, text, created_at, engagement_json, llm_verdict_json
        FROM items
        WHERE cluster_id IS NOT NULL
          AND dropped_reason IS NULL
          AND created_at >= ?
        """,
        (t_min,),
    ).fetchall()

    by_cluster: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        if _is_devtools_item(str(r["text"] or ""), str(r["llm_verdict_json"] or "")):
            by_cluster[int(r["cluster_id"])].append(r)

    out: list[DevtoolsCluster] = []
    for cid, items in by_cluster.items():
        rec7 = rec30 = 0
        recency = 0.0
        eng_vals: list[float] = []
        best_ts = 0.0
        lead_text = ""
        lead_url = ""
        llm_one_line = ""
        roles: dict[str, int] = defaultdict(int)
        wtp_vals: list[float] = []
        top_wtp = -1.0
        top_wtp_note = ""
        source_families: set[str] = set()
        for row in items:
            ts = float(row["created_at"] or 0)
            if ts >= t7:
                rec7 += 1
            if ts >= t30:
                rec30 += 1
            recency += _recency_decay(ts, now)
            source_families.add(str(row["source"]).split(":")[0])
            verdict = _extract_verdict(str(row["llm_verdict_json"] or ""))
            icp = normalize_icp_segment(verdict.get("icp_segment"))
            roles[icp] += 1
            wtp = verdict.get("willingness_to_pay_score")
            try:
                if wtp is not None:
                    wf = max(0.0, min(1.0, float(wtp)))
                    wtp_vals.append(wf)
                    if wf > top_wtp:
                        top_wtp = wf
                        top_wtp_note = str(verdict.get("wtp_rationale") or "").strip()[:200]
            except (TypeError, ValueError):
                pass
            if not llm_one_line:
                llm_one_line = str(verdict.get("one_line") or "").strip()
            try:
                eng = json.loads(row["engagement_json"] or "{}")
            except json.JSONDecodeError:
                eng = {}
            eng_vals.append(_engagement_value(eng))
            if ts >= best_ts:
                best_ts = ts
                lead_text = str(row["text"] or "")
                lead_url = str(row["url"] or "")
        n = max(1, len(items))
        recurrence_score = min(1.0, rec7 / 8.0) * 0.5 + min(1.0, rec30 / 20.0) * 0.5
        recency_score = min(1.0, recency / n)
        engagement_score = min(1.0, (sum(eng_vals) / n) / 5.0)
        wtp_score = (sum(wtp_vals) / len(wtp_vals)) if wtp_vals else None
        composite = (
            0.35 * recurrence_score
            + 0.20 * recency_score
            + 0.25 * engagement_score
            + 0.20 * (wtp_score if wtp_score is not None else 0.0)
        )
        role_mix = ", ".join(f"{k}:{v}" for k, v in sorted(roles.items(), key=lambda x: x[1], reverse=True)[:3])
        out.append(
            DevtoolsCluster(
                cluster_id=cid,
                item_count=len(items),
                recurrence_7d=rec7,
                recurrence_30d=rec30,
                recurrence_score=recurrence_score,
                recency_score=recency_score,
                engagement_score=engagement_score,
                wtp_score=wtp_score,
                composite=composite,
                problem=llm_one_line or _fallback_problem_sentence(lead_text),
                lead_text=_fallback_problem_sentence(lead_text),
                lead_url=lead_url,
                source_count=len(source_families),
                role_mix=role_mix or "unknown",
                wtp_note=top_wtp_note or "unknown",
            )
        )
    out.sort(key=lambda x: (x.composite, x.recurrence_score), reverse=True)
    for i, c in enumerate(out, start=1):
        c.composite_rank = i
    return out


def _sort_clusters(items: list[DevtoolsCluster], sort_primary: str) -> list[DevtoolsCluster]:
    primary = (sort_primary or "composite").strip().lower()
    if primary == "engagement":
        return sorted(items, key=lambda x: (x.engagement_score, x.composite), reverse=True)
    if primary == "recurrence":
        return sorted(items, key=lambda x: (x.recurrence_score, x.composite), reverse=True)
    return sorted(items, key=lambda x: (x.composite, x.recurrence_score), reverse=True)


def render_devtools_markdown(clusters: list[DevtoolsCluster], *, top: int, sort_primary: str) -> str:
    slice_ = clusters[:top]
    sp = (sort_primary or "composite").strip().lower()
    lines = [
        "# Devtools / Product Ops problem report",
        "",
        "Scope: last 90 days only. Audience: software engineering, product design, and product management teams.",
        "",
        "## Criteria used for this report",
        "",
        "- Keep only themes with concrete tool/workflow pain for engineering/design/PM.",
        "- Exclude broad news, politics, and consumer hobby chatter unless tied to team operations.",
        "- Prioritize recurring themes over one-off viral posts.",
        "- Engagement score = normalized log(points/votes + comments).",
        "- WTP = LLM willingness-to-pay score mean when available; missing values stay unknown.",
        "",
        f"## Ranked themes (primary sort: `{sp}`)",
        "",
        "| Rank | #C | Cluster | Problem | Posts | 7d | 30d | Rec | Eng | WTP | Srcs | Role mix | Lead |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for i, c in enumerate(slice_, start=1):
        wtp = f"{c.wtp_score:.2f}" if c.wtp_score is not None else "—"
        lead = c.lead_text.replace("|", "\\|")
        lines.append(
            f"| {i} | {c.composite_rank} | {c.cluster_id} | {c.problem} | {c.item_count} | "
            f"{c.recurrence_7d} | {c.recurrence_30d} | {c.recurrence_score:.2f} | "
            f"{c.engagement_score:.2f} | {wtp} | {c.source_count} | {c.role_mix} | [{lead}]({c.lead_url or '#'}) |"
        )
    lines.extend(["", "## Theme detail", ""])
    for i, c in enumerate(slice_[:15], start=1):
        lines.append(f"### {i}. Cluster `{c.cluster_id}`")
        lines.append("")
        lines.append(f"- Problem: {c.problem}")
        lines.append(
            f"- Signals: posts={c.item_count}, recurrence={c.recurrence_7d}/{c.recurrence_30d}, "
            f"engagement={c.engagement_score:.2f}, wtp={f'{c.wtp_score:.2f}' if c.wtp_score is not None else 'unknown'}"
        )
        lines.append(f"- Role mix: {c.role_mix}")
        lines.append(f"- WTP note: {c.wtp_note}")
        lines.append(f"- Lead evidence: [{c.lead_text}]({c.lead_url or '#'})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate_devtools_report(
    output_path: str | Path = "devtools_report.md",
    *,
    days: int = 90,
    top: int = 25,
    sort_primary: str = "composite",
) -> Path:
    settings = get_settings()
    conn = dbm.connect(settings.database_path)
    dbm.init_db(conn)
    clusters = _cluster_rows(conn, days=days)
    conn.close()
    clusters = _sort_clusters(clusters, sort_primary)
    text = render_devtools_markdown(clusters, top=top, sort_primary=sort_primary)
    out_path = Path(output_path).expanduser().resolve()
    out_path.write_text(text, encoding="utf-8")
    return out_path


def main() -> None:
    out = generate_devtools_report(output_path="devtools_report.md", days=90, top=25, sort_primary="composite")
    print(f"Wrote devtools report (last 90d) → {out}")


if __name__ == "__main__":
    main()
