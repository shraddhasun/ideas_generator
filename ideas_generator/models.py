from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class RawItem:
    source: str
    external_id: str
    url: str
    text: str
    created_at: datetime
    engagement: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoredCluster:
    cluster_id: int
    recurrence_7d: int
    recurrence_30d: int
    recurrence_score: float
    recency_score: float
    engagement_score: float
    source_count: int
    severity_score: float
    wtp_score: float
    composite: float
    composite_rank: int
    sample_text: str
    sample_url: str
    item_count: int = 0
    llm_score_avg: float | None = None
    llm_category_mode: str | None = None
    llm_icp_mode: str | None = None
    llm_wtp_mean: float | None = None
    llm_wtp_max: float | None = None
    llm_wtp_rationale: str | None = None
    source_breakdown: str = ""
    llm_one_line: str = ""
    engagement_lead_metrics: str = ""
    engagement_top_posts: list[tuple[str, str, str, str]] = field(
        default_factory=list
    )  # (source, url, metrics, snippet)
    problem_sentence: str = ""  # LLM one_line, or heuristic from lead post
    verbatim_lead: str = ""  # excerpt from the most recent post (evidence, not paraphrased)
    extra_samples: list[tuple[str, str]] = field(default_factory=list)  # (text, url) up to 2 more
