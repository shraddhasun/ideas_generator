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
    recency_score: float
    engagement_score: float
    source_count: int
    severity_score: float
    wtp_score: float
    composite: float
    sample_text: str
    sample_url: str
    item_count: int = 0
    llm_score_avg: float | None = None
    llm_category_mode: str | None = None
    source_breakdown: str = ""
    llm_one_line: str = ""
    problem_sentence: str = ""  # LLM one_line, or heuristic from lead post
    verbatim_lead: str = ""  # excerpt from the most recent post (evidence, not paraphrased)
    extra_samples: list[tuple[str, str]] = field(default_factory=list)  # (text, url) up to 2 more
