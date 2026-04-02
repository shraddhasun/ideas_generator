import json

from ideas_generator.llm_screen import (
    _is_producthunt_source,
    _sanitize_llm_text,
    parse_verdict,
)


def test_parse_verdict():
    score, cat, obj = parse_verdict(
        '{"tool_opportunity_score": 0.8, "category": "business_problem", "one_line": "Ops pain"}'
    )
    assert score == 0.8
    assert cat == "business_problem"
    assert obj["one_line"] == "Ops pain"
    assert obj["icp_segment"] == "unclear"


def test_parse_verdict_icp():
    _, _, obj = parse_verdict(
        '{"tool_opportunity_score": 0.5, "category": "business_problem", "one_line": "x", "icp_segment": "b2b_devtools"}'
    )
    assert obj["icp_segment"] == "b2b_devtools"


def test_parse_verdict_clamps():
    score, _, _ = parse_verdict('{"tool_opportunity_score": 99, "category": "other"}')
    assert score == 1.0


def test_parse_verdict_wtp():
    _, _, obj = parse_verdict(
        '{"tool_opportunity_score": 0.5, "category": "business_problem", '
        '"willingness_to_pay_score": 0.75, "wtp_rationale": "Mentioned RFP and budget"}'
    )
    assert obj["willingness_to_pay_score"] == 0.75
    assert "RFP" in obj["wtp_rationale"]


def test_parse_verdict_wtp_clamps():
    _, _, obj = parse_verdict(
        '{"tool_opportunity_score": 0.5, "category": "other", "willingness_to_pay_score": 2.0}'
    )
    assert obj["willingness_to_pay_score"] == 1.0


def test_parse_verdict_wtp_omitted():
    _, _, obj = parse_verdict('{"tool_opportunity_score": 0.5, "category": "other"}')
    assert "willingness_to_pay_score" not in obj


def test_sanitize_llm_text_strips_nul_bytes():
    assert _sanitize_llm_text("a\x00b") == "ab"
    assert _sanitize_llm_text("") == ""


def test_sanitize_llm_text_strips_lone_surrogates():
    # Lone surrogates can make JSON request bodies invalid for OpenAI.
    bad = "a\ud800b"
    out = _sanitize_llm_text(bad)
    assert out == "ab"
    json.dumps({"messages": [{"role": "user", "content": out}]})


def test_producthunt_source_detector():
    assert _is_producthunt_source("producthunt")
    assert _is_producthunt_source("producthunt:launch")
    assert not _is_producthunt_source("hn")
