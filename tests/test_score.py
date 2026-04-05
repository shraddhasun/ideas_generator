import json
import sqlite3
import time

import pytest

from ideas_generator.config import Settings
from ideas_generator.score import compute_cluster_scores


def test_compute_scores_empty():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            cluster_id INTEGER,
            dropped_reason TEXT,
            source TEXT, url TEXT, text TEXT, created_at REAL, engagement_json TEXT,
            business_tool_fit REAL,
            llm_tool_score REAL, llm_category TEXT, llm_verdict_json TEXT
        );
        """
    )
    s = Settings(openai_api_key=None, gemini_api_key=None)
    assert compute_cluster_scores(conn, s) == []


def test_compute_scores_one_cluster():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            cluster_id INTEGER,
            dropped_reason TEXT,
            source TEXT, url TEXT, text TEXT, created_at REAL, engagement_json TEXT,
            business_tool_fit REAL,
            llm_tool_score REAL, llm_category TEXT, llm_verdict_json TEXT
        );
        """
    )
    now = time.time()
    conn.execute(
        """
        INSERT INTO items (
            id, cluster_id, dropped_reason, source, url, text, created_at, engagement_json,
            business_tool_fit, llm_tool_score, llm_category, llm_verdict_json
        ) VALUES (1, 1, NULL, 'hn', 'http://x', 'paying for broken budget tooling', ?, ?, 1.0,
            0.9, 'business_problem', ?)
        """,
        (
            now,
            json.dumps({"points": 10, "comments": 5}),
            json.dumps({"icp_segment": "b2b_finance_ops", "one_line": "Budget tooling pain"}),
        ),
    )
    s = Settings(openai_api_key=None, gemini_api_key=None)
    out = compute_cluster_scores(conn, s)
    assert len(out) == 1
    assert out[0].cluster_id == 1
    assert out[0].item_count == 1
    assert "hn" in out[0].source_breakdown
    assert out[0].problem_sentence
    assert out[0].verbatim_lead
    assert "paying for broken budget tooling" in out[0].verbatim_lead
    assert out[0].wtp_score > 0
    assert out[0].llm_icp_mode == "b2b_finance_ops"
    assert "10 pts" in out[0].engagement_lead_metrics
    assert out[0].composite_rank == 1
    assert out[0].recurrence_score >= 0.0
    assert out[0].llm_wtp_mean is None


def test_compute_scores_llm_wtp_and_sort():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            cluster_id INTEGER,
            dropped_reason TEXT,
            source TEXT, url TEXT, text TEXT, created_at REAL, engagement_json TEXT,
            business_tool_fit REAL,
            llm_tool_score REAL, llm_category TEXT, llm_verdict_json TEXT
        );
        """
    )
    now = time.time()
    verdict_a = {
        "icp_segment": "b2b_devtools",
        "one_line": "Low WTP",
        "willingness_to_pay_score": 0.2,
        "wtp_rationale": "no budget signal",
    }
    verdict_b = {
        "icp_segment": "b2b_devtools",
        "one_line": "High WTP",
        "willingness_to_pay_score": 0.8,
        "wtp_rationale": "procurement and renewal",
    }
    conn.execute(
        """
        INSERT INTO items (
            id, cluster_id, dropped_reason, source, url, text, created_at, engagement_json,
            business_tool_fit, llm_tool_score, llm_category, llm_verdict_json
        ) VALUES
        (1, 1, NULL, 'hn', 'http://a', 'text a', ?, ?, 1.0, 0.9, 'business_problem', ?),
        (2, 1, NULL, 'hn', 'http://b', 'text b', ?, ?, 1.0, 0.9, 'business_problem', ?)
        """,
        (
            now,
            json.dumps({"points": 1, "comments": 1}),
            json.dumps(verdict_a),
            now,
            json.dumps({"points": 100, "comments": 50}),
            json.dumps(verdict_b),
        ),
    )
    s = Settings(openai_api_key=None, gemini_api_key=None)
    out = compute_cluster_scores(conn, s)
    assert len(out) == 1
    assert out[0].llm_wtp_mean == pytest.approx(0.5)
    assert out[0].llm_wtp_max == pytest.approx(0.8)
    assert out[0].llm_wtp_rationale == "procurement and renewal"

    conn.execute(
        """
        INSERT INTO items (
            id, cluster_id, dropped_reason, source, url, text, created_at, engagement_json,
            business_tool_fit, llm_tool_score, llm_category, llm_verdict_json
        ) VALUES (3, 2, NULL, 'hn', 'http://c', 'quiet', ?, ?, 1.0, 0.9, 'business_problem', ?)
        """,
        (
            now,
            json.dumps({"points": 0, "comments": 0}),
            json.dumps({"icp_segment": "b2b_devtools", "one_line": "x"}),
        ),
    )
    by_eng = compute_cluster_scores(conn, s, sort_primary="engagement")
    assert [x.cluster_id for x in by_eng] == [1, 2]
    by_rec = compute_cluster_scores(conn, s, sort_primary="recurrence")
    assert len(by_rec) == 2
