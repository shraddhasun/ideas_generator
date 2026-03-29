from __future__ import annotations

import sqlite3

import numpy as np
from rich.progress import track

from ideas_generator import db as dbm
from ideas_generator.config import Settings
from ideas_generator.llm_util import llm_screen_enabled


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom <= 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def rebuild_clusters(conn: sqlite3.Connection, settings: Settings) -> int:
    """Sequential assignment: assign each item to nearest centroid or create a new cluster."""
    rows = dbm.list_embedded_items(
        conn,
        min_business_tool_fit=settings.min_business_tool_fit,
        require_llm=llm_screen_enabled(settings),
        llm_min_tool_score=settings.llm_min_tool_score,
    )
    dbm.clear_cluster_assignments(conn)
    conn.commit()

    cluster_centroids: dict[int, np.ndarray] = {}
    cluster_counts: dict[int, int] = {}

    n_assigned = 0
    for row in track(rows, description="Clustering"):
        iid = int(row["id"])
        emb = dbm.blob_to_vec(row["embedding_blob"])

        best_cid: int | None = None
        best_sim = -1.0
        for cid, centroid in cluster_centroids.items():
            sim = _cosine(emb, centroid)
            if sim > best_sim:
                best_sim = sim
                best_cid = cid

        if best_cid is not None and best_sim >= settings.cluster_similarity_threshold:
            cid = best_cid
            n = cluster_counts[cid]
            old = cluster_centroids[cid]
            new_centroid = (old * n + emb) / (n + 1)
            cluster_centroids[cid] = new_centroid
            cluster_counts[cid] = n + 1
            dbm.update_cluster_centroid(conn, cid, new_centroid, cluster_counts[cid])
            dbm.set_item_cluster(conn, iid, cid)
        else:
            cid = dbm.insert_cluster(conn, emb)
            cluster_centroids[cid] = emb.copy()
            cluster_counts[cid] = 1
            dbm.set_item_cluster(conn, iid, cid)

        n_assigned += 1

    conn.commit()
    return n_assigned
