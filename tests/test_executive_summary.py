"""
Same plumbing-vs-judgment split as tests/test_llm_checks_eval.py —
this tests that a mocked LLM response gets parsed correctly, NOT
whether the LLM is smart. Judgment quality (does it actually pick
the right priorities) needs its own golden-set eval if you want that
verified with the same rigor as security_check/duplicate_check.
"""
from unittest.mock import patch

from src.orchestrator.graph import executive_summary


def test_priorities_are_formatted_into_readable_lines():
    mock_response = {"priorities": [
        {"module": "security-group-web", "issue": "open SSH", "why_it_matters": "internet-facing risk"}
    ]}
    with patch("src.orchestrator.graph.invoke_json", return_value=mock_response):
        result = executive_summary({"report_text": "irrelevant for this test"})
    assert "security-group-web" in result["executive_summary"]
    assert "open SSH" in result["executive_summary"]


def test_empty_priorities_gives_a_clear_no_op_message_not_blank():
    with patch("src.orchestrator.graph.invoke_json", return_value={"priorities": []}):
        result = executive_summary({"report_text": "irrelevant"})
    assert result["executive_summary"] != ""
    assert "no single finding" in result["executive_summary"].lower()


def test_llm_error_is_visible_not_silently_empty():
    with patch("src.orchestrator.graph.invoke_json", return_value={"_error": "timeout"}):
        result = executive_summary({"report_text": "irrelevant"})
    assert "unavailable" in result["executive_summary"]
    assert "timeout" in result["executive_summary"]