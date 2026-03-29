from __future__ import annotations

import sqlite3

import numpy as np
from fastembed import TextEmbedding
from rich.progress import track

from ideas_generator import db as dbm
from ideas_generator.business_fit import business_tool_cosine, embed_anchor
from ideas_generator.config import Settings


def _backfill_fit(
    conn: sqlite3.Connection,
    model: TextEmbedding,
    anchor: np.ndarray,
    label: str,
) -> int:
    rows = dbm.list_items_need_fit_backfill(conn)
    if not rows:
        return 0
    n = 0
    for row in track(rows, description=label):
        iid = int(row["id"])
        arr = dbm.blob_to_vec(row["embedding_blob"])
        fit = business_tool_cosine(arr, anchor)
        conn.execute(
            "UPDATE items SET business_tool_fit = ?, cluster_id = NULL WHERE id = ?",
            (float(fit), iid),
        )
        n += 1
    return n


def run_embed(conn: sqlite3.Connection, settings: Settings) -> int:
    model = TextEmbedding(model_name=settings.embedding_model)
    anchor = embed_anchor(model, settings.business_tool_anchor)

    rows = dbm.list_items_without_embedding(conn)
    count = 0
    batch_size = 32

    if rows:
        texts = [r["text"] for r in rows]
        ids = [r["id"] for r in rows]
        for i in track(range(0, len(rows), batch_size), description="Embedding"):
            batch_ids = ids[i : i + batch_size]
            batch_texts = texts[i : i + batch_size]
            vectors = list(model.embed(batch_texts))
            for row_id, vec in zip(batch_ids, vectors, strict=True):
                arr = np.array(vec, dtype=np.float32)
                fit = business_tool_cosine(arr, anchor)
                dbm.set_embedding_and_fit(conn, int(row_id), arr, fit)
                count += 1
        conn.commit()

    # Existing DBs: embeddings without fit scores.
    bf = _backfill_fit(conn, model, anchor, "Backfill business-tool fit")
    conn.commit()
    return count + bf
