"""
ITERATION 2 — these tests do NOT judge whether the LLM is "smart."
They judge whether the EVAL PLUMBING is correct: does a finding
actually get parsed into a SecurityFinding object, does severity get
passed through, does an empty LLM response correctly mean "no
findings" rather than crashing.

Mocks invoke_json (the real LLM seam, via src.llm.nebius_client) —
NOT _call_llm, which was the old stub-era interface and no longer
exists in security_check.py now that it calls a real LLM client.

This matters because a bug in the plumbing (e.g. silently swallowing
findings, or crashing on an empty list) would make your golden-set
eval report false negatives that look like the LLM is bad, when
actually your code around the LLM is bad. Test the plumbing
separately from the judgment quality, always — that's what
eval/run_eval.py + the golden sets are for.
"""
from unittest.mock import patch

from src.llm_checks.security_check import check_module_security, SecurityFinding


def test_finding_from_llm_response_is_parsed_correctly():
    """
    WHAT: mock invoke_json to return one well-formed finding, confirm
    check_module_security turns it into a SecurityFinding with all
    fields intact.
    WHY IT MATTERS: this is the seam between "LLM says something" and
    "code acts on it" — a field-name mismatch here (e.g. LLM returns
    "risk" but code reads "severity") would silently produce empty or
    wrong results with no error raised.
    PASS: exactly one SecurityFinding returned, severity == "high".
    FAIL: check the key names in the mocked invoke_json return value
    match what check_module_security reads.
    """
    mock_response = {
        "findings": [
            {"issue": "open ingress on port 22", "severity": "high", "reasoning": "0.0.0.0/0 on SSH"}
        ]
    }
    with patch("src.llm_checks.security_check.invoke_json", return_value=mock_response):
        findings = check_module_security("security-group-web", "resource text here")

    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert findings[0].module == "security-group-web"


def test_empty_findings_list_means_pass_not_crash():
    """
    WHAT: mock invoke_json to return zero findings (the "this module
    is clean" case).
    WHY IT MATTERS: negative case for the eval plumbing — confirms an
    empty result is handled as "no findings," not as a missing key
    that throws a KeyError and takes down the whole audit for one
    clean module.
    PASS: returns an empty list, no exception.
    FAIL: check_module_security's list comprehension assumes
    "findings" key always has content; confirm .get("findings", [])
    style defaulting is actually in place.
    """
    mock_response = {"findings": []}
    with patch("src.llm_checks.security_check.invoke_json", return_value=mock_response):
        findings = check_module_security("vpc-base", "resource text here")

    assert findings == []


def test_malformed_llm_response_does_not_silently_produce_wrong_data():
    """
    WHAT: mock invoke_json to return a response missing the
    "findings" key entirely (simulates a real failure mode — LLM
    returns malformed JSON that still parses, just the wrong shape).
    WHY IT MATTERS: this is the failure-handling policy from the
    project framework doc in practice — a malformed LLM response for
    ONE module should not crash the whole audit, but it also should
    NOT be silently treated as "module is clean."
    PASS: returns an empty list (safe default) rather than raising.
    FAIL: if this raises an unhandled exception instead of using the
    .get() default.
    """
    mock_response = {"unexpected_key": "not what we expected"}
    with patch("src.llm_checks.security_check.invoke_json", return_value=mock_response):
        findings = check_module_security("vpc-base", "resource text here")

    assert findings == []


def test_invoke_json_error_response_is_surfaced_not_silently_dropped():
    """
    WHAT: mock invoke_json to return the real client's actual error
    shape — {"_error": "..."} — which is what nebius_client.py's
    invoke_json returns after exhausting its retries (see
    src/llm/nebius_client.py). This is DIFFERENT from the malformed-
    response test above: that one simulates the LLM returning valid
    JSON in the wrong shape; this one simulates invoke_json itself
    reporting total failure (e.g. truncation or a parse error on
    every retry attempt — both real failure modes we hit while
    building this).
    WHY IT MATTERS: an LLM call that failed 3 times should be clearly
    distinguishable from "module is clean" when a human reads the
    eval report — silently returning [] here would make a failed
    check indistinguishable from a genuinely clean module, which is
    a worse outcome than a visible error.
    PASS: the returned finding's issue/reasoning makes the failure
    visible (e.g. contains "LLM_CALL_FAILED" or the raw error text) —
    NOT an empty list.
    FAIL: if this returns [], check_module_security is treating
    invoke_json's _error case the same as "no findings," which hides
    real failures as false negatives in the eval report.
    """
    mock_response = {"_error": "failed after 3 attempts: finish_reason=length"}
    with patch("src.llm_checks.security_check.invoke_json", return_value=mock_response):
        findings = check_module_security("vpc-base", "resource text here")

    assert findings != []
    assert any("LLM_CALL_FAILED" in f.issue or "failed after" in f.reasoning for f in findings)

def test_bare_list_response_is_handled_not_crashed_on():
    """
    WHAT: mock invoke_json to return a bare list, e.g. [] — not
    wrapped in {"findings": [...]}. Observed for real during golden-
    set eval runs (vpc-base) — the LLM doesn't always honor the
    requested wrapper shape, especially on the "nothing to report"
    case.
    WHY IT MATTERS: without this defensive handling,
    check_module_security crashes with 'list' object has no
    attribute 'get' — a real bug this test would have caught before
    it showed up in a live eval run.
    PASS: returns an empty list, no exception.
    FAIL: check the isinstance(result, list) branch in
    check_module_security.
    """
    with patch("src.llm_checks.security_check.invoke_json", return_value=[]):
        findings = check_module_security("vpc-base", "resource text here")

    assert findings == []