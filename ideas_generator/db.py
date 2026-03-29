from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from ideas_generator.models import RawItem


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at REAL NOT NULL,
    fetched_at REAL NOT NULL,
    engagement_json TEXT NOT NULL DEFAULT '{}',
    embedding_blob BLOB,
    business_tool_fit REAL,
    llm_tool_score REAL,
    llm_category TEXT,
    llm_verdict_json TEXT,
    llm_content_angle TEXT,
    cluster_id INTEGER,
    dropped_reason TEXT,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    centroid_blob BLOB NOT NULL,
    member_count INTEGER NOT NULL DEFAULT 0,
    last_updated REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cluster_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at REAL NOT NULL,
    cluster_id INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_id);
CREATE INDEX IF NOT EXISTS idx_items_created ON items(created_at);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate_items_columns(conn)
    conn.commit()


def _migrate_items_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
    if "business_tool_fit" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN business_tool_fit REAL")
    if "llm_tool_score" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN llm_tool_score REAL")
    if "llm_category" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN llm_category TEXT")
    if "llm_verdict_json" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN llm_verdict_json TEXT")
    if "llm_content_angle" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN llm_content_angle TEXT")


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    try:
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def upsert_item(
    conn: sqlite3.Connection,
    item: RawItem,
    *,
    dropped_reason: str | None = None,
) -> int:
    now = datetime.utcnow().timestamp()
    eng = json.dumps(item.engagement, ensure_ascii=False)
    cur = conn.execute(
        """
        INSERT INTO items (source, external_id, url, text, created_at, fetched_at, engagement_json, dropped_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
            url=excluded.url,
            text=excluded.text,
            created_at=excluded.created_at,
            fetched_at=excluded.fetched_at,
            engagement_json=excluded.engagement_json,
            dropped_reason=excluded.dropped_reason
        RETURNING id
        """,
        (
            item.source,
            item.external_id,
            item.url,
            item.text,
            item.created_at.timestamp(),
            now,
            eng,
            dropped_reason,
        ),
    )
    row = cur.fetchone()
    return int(row[0])


def set_embedding_and_fit(
    conn: sqlite3.Connection,
    item_id: int,
    vec: np.ndarray,
    business_tool_fit: float,
) -> None:
    conn.execute(
        """
        UPDATE items SET embedding_blob = ?, business_tool_fit = ?, cluster_id = NULL
        WHERE id = ?
        """,
        (vec.astype(np.float32).tobytes(), float(business_tool_fit), item_id),
    )


def list_items_need_fit_backfill(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, embedding_blob FROM items
            WHERE embedding_blob IS NOT NULL
              AND dropped_reason IS NULL
              AND business_tool_fit IS NULL
            """
        )
    )


def list_items_without_embedding(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT id, text FROM items WHERE embedding_blob IS NULL AND dropped_reason IS NULL"
        )
    )


def list_embedded_items(
    conn: sqlite3.Connection,
    *,
    min_business_tool_fit: float,
    require_llm: bool,
    llm_min_tool_score: float,
    exclude_llm_news_angle: bool = False,
) -> list[sqlite3.Row]:
    conditions = ["embedding_blob IS NOT NULL", "dropped_reason IS NULL"]
    params: list[float] = []

    if min_business_tool_fit > 0:
        conditions.extend(["business_tool_fit IS NOT NULL", "business_tool_fit >= ?"])
        params.append(float(min_business_tool_fit))

    if require_llm:
        conditions.extend(["llm_tool_score IS NOT NULL", "llm_tool_score >= ?"])
        params.append(float(llm_min_tool_score))
        if exclude_llm_news_angle:
            # NULL = legacy rows before angle existed; keep them in the pipeline.
            conditions.append(
                "(llm_content_angle IS NULL OR TRIM(llm_content_angle) != 'news_or_event')"
            )

    sql = f"""
        SELECT id, source, url, text, created_at, engagement_json, embedding_blob, cluster_id
        FROM items
        WHERE {" AND ".join(conditions)}
        ORDER BY created_at ASC
    """
    return list(conn.execute(sql, params))


def list_items_pending_llm(
    conn: sqlite3.Connection,
    *,
    min_embed_fit_to_screen: float,
    force: bool,
    limit: int,
) -> list[sqlite3.Row]:
    lim_clause = f" LIMIT {int(limit)} " if limit > 0 else ""
    null_clause = "" if force else " AND llm_tool_score IS NULL "
    q = f"""
        SELECT id, text, url, source, business_tool_fit FROM items
        WHERE embedding_blob IS NOT NULL
          AND dropped_reason IS NULL
          {null_clause}
          AND (
            business_tool_fit IS NULL
            OR business_tool_fit >= ?
          )
        ORDER BY id
        {lim_clause}
    """
    return list(conn.execute(q, (float(min_embed_fit_to_screen),)))


def set_llm_verdict(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    tool_score: float,
    category: str,
    verdict_json: str,
    content_angle: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE items
        SET llm_tool_score = ?, llm_category = ?, llm_verdict_json = ?,
            llm_content_angle = ?, cluster_id = NULL
        WHERE id = ?
        """,
        (float(tool_score), category, verdict_json, content_angle, item_id),
    )


def stamp_skipped_llm_low_embed(
    conn: sqlite3.Connection,
    embed_below: float,
) -> int:
    cur = conn.execute(
        """
        UPDATE items
        SET llm_tool_score = 0,
            llm_category = 'skipped_low_embed',
            llm_verdict_json = '{}',
            llm_content_angle = NULL,
            cluster_id = NULL
        WHERE embedding_blob IS NOT NULL
          AND dropped_reason IS NULL
          AND llm_tool_score IS NULL
          AND business_tool_fit IS NOT NULL
          AND business_tool_fit < ?
        """,
        (float(embed_below),),
    )
    return int(cur.rowcount or 0)


def clear_cluster_assignments(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE items SET cluster_id = NULL")
    conn.execute("DELETE FROM clusters")


def insert_cluster(conn: sqlite3.Connection, centroid: np.ndarray) -> int:
    cur = conn.execute(
        "INSERT INTO clusters (centroid_blob, member_count, last_updated) VALUES (?, ?, ?)",
        (
            centroid.astype(np.float32).tobytes(),
            1,
            datetime.utcnow().timestamp(),
        ),
    )
    return int(cur.lastrowid)


def update_cluster_centroid(
    conn: sqlite3.Connection, cluster_id: int, centroid: np.ndarray, member_count: int
) -> None:
    conn.execute(
        "UPDATE clusters SET centroid_blob = ?, member_count = ?, last_updated = ? WHERE id = ?",
        (
            centroid.astype(np.float32).tobytes(),
            member_count,
            datetime.utcnow().timestamp(),
            cluster_id,
        ),
    )


def set_item_cluster(conn: sqlite3.Connection, item_id: int, cluster_id: int) -> None:
    conn.execute("UPDATE items SET cluster_id = ? WHERE id = ?", (cluster_id, item_id))


def blob_to_vec(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def save_snapshot(
    conn: sqlite3.Connection,
    run_at: float,
    cluster_id: int,
    payload: dict[str, Any],
) -> None:
    conn.execute(
        "INSERT INTO cluster_snapshots (run_at, cluster_id, payload_json) VALUES (?, ?, ?)",
        (run_at, cluster_id, json.dumps(payload, ensure_ascii=False)),
    )


def last_snapshot_run(conn: sqlite3.Connection) -> float | None:
    row = conn.execute("SELECT MAX(run_at) FROM cluster_snapshots").fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])
