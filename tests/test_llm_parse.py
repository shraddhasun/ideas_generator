from ideas_generator.llm_screen import parse_verdict


def test_parse_verdict():
    score, cat, obj = parse_verdict(
        '{"tool_opportunity_score": 0.8, "category": "business_problem", "one_line": "Ops pain"}'
    )
    assert score == 0.8
    assert cat == "business_problem"
    assert obj["one_line"] == "Ops pain"


def test_parse_verdict_clamps():
    score, _, _ = parse_verdict('{"tool_opportunity_score": 99, "category": "other"}')
    assert score == 1.0
