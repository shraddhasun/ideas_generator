import numpy as np

from ideas_generator.business_fit import business_tool_cosine


def test_cosine_identical_normalized():
    v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    assert business_tool_cosine(v, v) == 1.0
