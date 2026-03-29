from __future__ import annotations

import numpy as np
from fastembed import TextEmbedding


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n <= 0:
        return v
    return v / n


def embed_anchor(model: TextEmbedding, anchor_text: str) -> np.ndarray:
    raw = list(model.embed([anchor_text]))[0]
    return _l2_normalize(np.asarray(raw, dtype=np.float32))


def business_tool_cosine(item_vec: np.ndarray, anchor_vec: np.ndarray) -> float:
    """Cosine similarity of L2-normalized vectors (inner product)."""
    a = _l2_normalize(item_vec.astype(np.float32))
    b = anchor_vec.astype(np.float32)
    return float(np.dot(a, b))
