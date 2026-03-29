from __future__ import annotations

import csv
import io
from typing import TextIO

from ideas_generator.models import ScoredCluster


def _md_cell(s: str, max_len: int | None = 120) -> str:
    t = (s or "").replace("|", "\\|").replace("\n", " ")
    if max_len is not None and len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def report_markdown(
    scored: list[ScoredCluster],
    top: int,
    out: TextIO | None = None,
    *,
    compact: bool = False,
    detail_limit: int = 15,
) -> str:
    out = out or io.StringIO()
    lines: list[str] = [
        "# Problem themes",
        "",
        "Summary: each row includes the **problem** line (LLM `one_line` when present, otherwise a line from the newest post), scores, a **lead** link, and in **Cluster detail** a **verbatim** excerpt from the newest post as evidence.",
        "",
        "| Rank | Cluster | **Problem** | Posts | 7d | 30d | LLM | Category | Srcs | **Composite** | Lead |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |",
    ]
    slice_ = scored[:top]
    for i, s in enumerate(slice_, start=1):
        llm_cell = f"{s.llm_score_avg:.2f}" if s.llm_score_avg is not None else "—"
        cat_cell = _md_cell(s.llm_category_mode or "—", 24)
        prob = _md_cell(s.problem_sentence, None)
        lead = _md_cell(s.sample_text, 80)
        url = s.sample_url or ""
        lines.append(
            f"| {i} | {s.cluster_id} | {prob} | {s.item_count} | {s.recurrence_7d} | {s.recurrence_30d} | "
            f"{llm_cell} | {cat_cell} | {s.source_count} | **{s.composite:.3f}** | [{lead}]({url}) |"
        )

    if not compact and slice_:
        n_detail = min(detail_limit, len(slice_))
        lines.extend(["", "## Cluster detail", ""])
        for i, s in enumerate(slice_[:n_detail], start=1):
            llm_avg = f"{s.llm_score_avg:.2f}" if s.llm_score_avg is not None else "—"
            cat = s.llm_category_mode or "—"
            lines.append(f"### {i}. Cluster {s.cluster_id} — composite **{s.composite:.3f}**")
            lines.append("")
            if s.problem_sentence:
                lines.append(f"> **Problem:** {_md_cell(s.problem_sentence, None)}")
                lines.append("")
            if s.verbatim_lead:
                lines.append(f"> **Verbatim (newest post):** {_md_cell(s.verbatim_lead, None)}")
                lines.append("")
            lines.append(
                f"- **Posts:** {s.item_count} · **Recurrence (7d / 30d):** {s.recurrence_7d} / "
                f"{s.recurrence_30d} · **Distinct source kinds:** {s.source_count}"
            )
            lines.append(f"- **LLM avg:** {llm_avg} · **Dominant category:** {cat}")
            if s.source_breakdown:
                lines.append(f"- **Sources (counts):** {s.source_breakdown}")
            lead_txt = _md_cell(s.sample_text, 300)
            lu = s.sample_url or "#"
            lines.append(f"- **Lead (most recent):** [{lead_txt}]({lu})")
            for j, (tx, uu) in enumerate(s.extra_samples, start=2):
                lines.append(f"- **Also {j}:** [{_md_cell(tx, 200)}]({uu or '#'})")
            lines.append("")

    text = "\n".join(lines).rstrip() + "\n"
    if hasattr(out, "write"):
        out.write(text)
    return text


def report_csv(scored: list[ScoredCluster], top: int, out: TextIO) -> None:
    w = csv.writer(out)
    w.writerow(
        [
            "rank",
            "cluster_id",
            "item_count",
            "recurrence_7d",
            "recurrence_30d",
            "recency",
            "engagement",
            "sources",
            "severity",
            "wtp",
            "composite",
            "llm_score_avg",
            "llm_category_mode",
            "source_breakdown",
            "llm_one_line",
            "problem_sentence",
            "verbatim_lead",
            "sample",
            "url",
            "extra_sample_1_text",
            "extra_sample_1_url",
            "extra_sample_2_text",
            "extra_sample_2_url",
        ]
    )
    for i, s in enumerate(scored[:top], start=1):
        ex1 = s.extra_samples[0] if len(s.extra_samples) > 0 else ("", "")
        ex2 = s.extra_samples[1] if len(s.extra_samples) > 1 else ("", "")
        w.writerow(
            [
                i,
                s.cluster_id,
                s.item_count,
                s.recurrence_7d,
                s.recurrence_30d,
                f"{s.recency_score:.4f}",
                f"{s.engagement_score:.4f}",
                s.source_count,
                f"{s.severity_score:.4f}",
                f"{s.wtp_score:.4f}",
                f"{s.composite:.4f}",
                f"{s.llm_score_avg:.4f}" if s.llm_score_avg is not None else "",
                s.llm_category_mode or "",
                s.source_breakdown,
                (s.llm_one_line or "").replace("\n", " ")[:2000],
                (s.problem_sentence or "").replace("\n", " ")[:2000],
                (s.verbatim_lead or "").replace("\n", " ")[:2000],
                s.sample_text.replace("\n", " ")[:500],
                s.sample_url,
                ex1[0].replace("\n", " ")[:500],
                ex1[1],
                ex2[0].replace("\n", " ")[:500],
                ex2[1],
            ]
        )
