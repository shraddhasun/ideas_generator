from __future__ import annotations

import csv
import io
from typing import TextIO

from ideas_generator.models import ScoredCluster

# Human-readable labels for llm_icp_mode (slug → display).
_ICP_LABELS: dict[str, str] = {
    "b2b_devtools": "B2B dev / engineering",
    "b2b_sales_marketing": "B2B sales & marketing / RevOps",
    "b2b_finance_ops": "B2B finance & ops / HR-tech",
    "b2b_security_it": "B2B security & IT",
    "b2b_vertical_real_estate": "B2B real estate / built world",
    "b2b_vertical_healthcare": "B2B healthcare",
    "b2b_vertical_other": "B2B other vertical",
    "consumer": "Consumer",
    "prosumer_creator": "Prosumer / creator economy",
    "meta_industry": "Industry / meta discussion",
    "unclear": "Unclear",
}


def _icp_display(slug: str | None) -> str:
    if not slug:
        return "—"
    return _ICP_LABELS.get(slug, slug.replace("_", " "))


def _llm_wtp_display(mean: float | None) -> str:
    if mean is None:
        return "—"
    return f"{mean:.2f}"


def _sort_section_title(sort_primary: str) -> str:
    sp = (sort_primary or "composite").strip().lower()
    if sp == "engagement":
        return "Ranked themes (by engagement score)"
    if sp == "recurrence":
        return "Ranked themes (by problem recurrence)"
    return "Ranked themes (by composite score)"


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
    engagement_highlight_n: int = 10,
    sort_primary: str = "composite",
) -> str:
    out = out or io.StringIO()
    slice_ = scored[:top]
    by_engagement = sorted(scored, key=lambda s: s.engagement_score, reverse=True)[
        :engagement_highlight_n
    ]

    sort_label = (sort_primary or "composite").strip().lower()
    if sort_label not in ("composite", "engagement", "recurrence"):
        sort_label = "composite"

    lines: list[str] = [
        "# Problem intelligence report",
        "",
        "## Executive summary",
        "",
        "**What is a “cluster”?** Posts are grouped by **semantic similarity** (embedding distance): a cluster is a recurring **theme**—similar complaints, workflows, or product angles discussed on different days or sites. The numeric cluster id is only an internal key; use the **Problem** text and quotes below as the real label.",
        "",
        "**How rows are ranked:** The main table uses **primary sort** "
        f"`{sort_label}` (see `ideas report --sort`). "
        "**composite** (default) mixes recurrence (7d / 30d), recency, normalized **engagement** (log-scaled points/votes + comments per platform), cross-platform spread, and light keyword signals for severity and keyword **WTP**. "
        "**engagement** sorts by normalized engagement first (discussion volume). "
        "**recurrence** sorts by the internal recurrence score (recent repeat discussion in the window). "
        "Each row also shows **composite rank**—position if you sorted by composite instead—so you can compare “buzz” vs “default priority”.",
        "",
        "**Engagement (norm):** Average of log(1+points)+log(1+comments) across posts in the theme, then scaled into [0,1] for the cluster (same signal used in composite). Per-platform raw metrics appear in the engagement highlights and detail rows.",
        "",
        "**WTP (LLM):** Mean of `willingness_to_pay_score` (0–1) from LLM verdicts across posts in the theme; **rationale** comes from the **highest** per-post score in the cluster. Missing or pre-upgrade verdicts show “—”. Keyword **wtp** in CSV is the legacy text heuristic; prefer the LLM column for buyer intent.",
        "",
        "**Ideal customer profile (ICP):** Each theme shows the **dominant** `icp_segment` from the LLM screen (majority vote across posts). Re-run `ideas llm-screen` after upgrading so new posts get `icp_segment` and WTP fields; older verdicts default to “unclear” / “—” until re-screened.",
        "",
    ]

    if slice_:
        lines.append(
            "### Top problems by "
            + ("composite rank" if sort_label == "composite" else f"{sort_label} rank")
        )
        lines.append("")
        for i, s in enumerate(slice_[: min(7, len(slice_))], start=1):
            prob = (s.problem_sentence or "").strip() or "(no one-line summary)"
            lines.append(f"{i}. {_md_cell(prob, None)}")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            f"## Strongest audience engagement (top {min(engagement_highlight_n, len(by_engagement))} themes)",
            "",
            "Sorted by **normalized engagement score** (average log points + log comments across posts in the theme—not the same as composite rank). Use this section to find threads that **drew replies and votes**, with **sources** called out.",
            "",
        ]
    )

    for i, s in enumerate(by_engagement, start=1):
        prob = _md_cell(s.problem_sentence or "—", None)
        icp = _md_cell(_icp_display(s.llm_icp_mode), 40)
        lines.append(
            f"### {i}. Cluster `{s.cluster_id}` — composite rank #{s.composite_rank} · "
            f"{_md_cell(icp, None)}"
        )
        lines.append("")
        lines.append(f"> **Problem:** {prob}")
        lines.append("")
        lines.append(
            f"- **Engagement score (norm):** {s.engagement_score:.3f} · **Posts:** {s.item_count} · "
            f"**Recurrence (7d / 30d):** {s.recurrence_7d} / {s.recurrence_30d}"
        )
        if s.engagement_lead_metrics:
            lines.append(f"- **Newest post (for context):** {s.engagement_lead_metrics}")
        if s.source_breakdown:
            lines.append(f"- **Sources (full labels, post counts):** {s.source_breakdown}")
        for src, url, metrics, snip in s.engagement_top_posts:
            src_short = src.split(":")[0]
            host = src if ":" in src else src_short
            u = url or "#"
            lines.append(
                f"- **High-engagement post** ({host}): {metrics} — [{_md_cell(snip, 160)}]({u})"
            )
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            f"## {_sort_section_title(sort_label)}",
            "",
            "| Rank | Cluster | **Problem** | ICP | Category | Posts | 7d | 30d | Eng† | LLM | **WTP‡** | Srcs | **Comp** | #C†† | Lead |",
            "| --- | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )

    for i, s in enumerate(slice_, start=1):
        llm_cell = f"{s.llm_score_avg:.2f}" if s.llm_score_avg is not None else "—"
        wtp_cell = _llm_wtp_display(s.llm_wtp_mean)
        icp_cell = _md_cell(_icp_display(s.llm_icp_mode), 24)
        cat_cell = _md_cell(s.llm_category_mode or "—", 22)
        prob = _md_cell(s.problem_sentence, None)
        lead = _md_cell(s.sample_text, 64)
        url = s.sample_url or ""
        lines.append(
            f"| {i} | {s.cluster_id} | {prob} | {icp_cell} | {cat_cell} | {s.item_count} | "
            f"{s.recurrence_7d} | {s.recurrence_30d} | {s.engagement_score:.3f} | {llm_cell} | "
            f"{wtp_cell} | {s.source_count} | **{s.composite:.3f}** | {s.composite_rank} | [{lead}]({url}) |"
        )

    lines.extend(
        [
            "",
            "† **Eng:** normalized average log engagement (points/votes + comments) within the theme; comparable across clusters.",
            "‡ **WTP:** LLM `willingness_to_pay_score` mean across posts (0–1); “—” if unknown.",
            "†† **#C:** rank by **composite** (stable reference when the table is sorted by engagement or recurrence).",
            "",
        ]
    )

    if not compact and slice_:
        n_detail = min(detail_limit, len(slice_))
        lines.extend(["## Theme detail (evidence)", ""])
        for i, s in enumerate(slice_[:n_detail], start=1):
            llm_avg = f"{s.llm_score_avg:.2f}" if s.llm_score_avg is not None else "—"
            cat = s.llm_category_mode or "—"
            icp = _icp_display(s.llm_icp_mode)
            lines.append(
                f"### {i}. Theme · internal id `{s.cluster_id}` · composite **{s.composite:.3f}** "
                f"(composite rank #{s.composite_rank})"
            )
            lines.append("")
            if s.problem_sentence:
                lines.append(f"> **Problem (summary):** {_md_cell(s.problem_sentence, None)}")
                lines.append("")
            if s.verbatim_lead:
                lines.append(
                    f"> **Verbatim (newest post):** {_md_cell(s.verbatim_lead, None)}"
                )
                lines.append("")
            lines.append(
                f"- **Posts:** {s.item_count} · **Recurrence (7d / 30d):** {s.recurrence_7d} / "
                f"{s.recurrence_30d} · **Distinct source families:** {s.source_count}"
            )
            lines.append(
                f"- **Engagement (norm):** {s.engagement_score:.3f}"
                + (
                    f" · **Newest post metrics:** {s.engagement_lead_metrics}"
                    if s.engagement_lead_metrics
                    else ""
                )
            )
            wtp_m = _llm_wtp_display(s.llm_wtp_mean)
            wtp_line = f"- **LLM WTP (mean):** {wtp_m}"
            if s.llm_wtp_rationale:
                wtp_line += f" · **WTP note (highest post):** {_md_cell(s.llm_wtp_rationale, None)}"
            lines.append(wtp_line)
            lines.append(
                f"- **LLM avg:** {llm_avg} · **Dominant category:** {cat} · **Dominant ICP:** {icp}"
            )
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
            "recurrence_score",
            "recency",
            "engagement",
            "sources",
            "severity",
            "wtp",
            "llm_wtp_mean",
            "llm_wtp_max",
            "llm_wtp_rationale",
            "composite",
            "composite_rank",
            "llm_score_avg",
            "llm_category_mode",
            "llm_icp_mode",
            "icp_label",
            "source_breakdown",
            "engagement_lead_metrics",
            "engagement_top_posts",
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
        top_posts = " | ".join(
            f"{src} [{metrics}] {url}" for src, url, metrics, _ in s.engagement_top_posts
        )
        w.writerow(
            [
                i,
                s.cluster_id,
                s.item_count,
                s.recurrence_7d,
                s.recurrence_30d,
                f"{s.recurrence_score:.4f}",
                f"{s.recency_score:.4f}",
                f"{s.engagement_score:.4f}",
                s.source_count,
                f"{s.severity_score:.4f}",
                f"{s.wtp_score:.4f}",
                f"{s.llm_wtp_mean:.4f}" if s.llm_wtp_mean is not None else "",
                f"{s.llm_wtp_max:.4f}" if s.llm_wtp_max is not None else "",
                (s.llm_wtp_rationale or "").replace("\n", " ")[:2000],
                f"{s.composite:.4f}",
                s.composite_rank,
                f"{s.llm_score_avg:.4f}" if s.llm_score_avg is not None else "",
                s.llm_category_mode or "",
                s.llm_icp_mode or "",
                _icp_display(s.llm_icp_mode),
                s.source_breakdown,
                s.engagement_lead_metrics,
                top_posts,
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
