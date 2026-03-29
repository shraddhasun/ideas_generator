import json
import sqlite3
import time

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
            id, cluster_id, dropped_reason, source, url, text, created_at, engagement_json, business_tool_fit
        ) VALUES (1, 1, NULL, 'hn', 'http://x', 'paying for broken budget tooling', ?, ?, 1.0)
        """,
        (now, json.dumps({"points": 10, "comments": 5})),
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
