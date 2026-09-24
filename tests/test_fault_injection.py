"""
ITERATION 3 — fault injection / failure-handling policy.

Answers the framework doc's "what happens when something breaks" row
directly, with a test instead of just a written claim. The policy:
if one check node errors, mark it skipped and continue the rest of
the audit — don't let one bad module or one flaky LLM call take down
findings for every other module.
"""
import pytest


def run_checks_with_fault_tolerance(modules: list[str], check_fn) -> dict:
    """
    Minimal stand-in for the orchestrator's fan-out node. Wraps each
    check_fn call in try/except per the failure-handling policy, so
    this test can prove the POLICY works without needing the full
    LangGraph orchestrator wired up yet. Port this same try/except
    shape into the real fan-out node in src/orchestrator/graph.py.
    """
    results = {}
    for module in modules:
        try:
            results[module] = {"status": "ok", "result": check_fn(module)}
        except Exception as e:
            results[module] = {"status": "skipped", "error": str(e)}
    return results


def test_one_module_erroring_does_not_stop_other_modules_from_being_checked():
    """
    WHAT: run a fake check across 3 modules, where the check function
    deliberately raises for the middle one only.
    WHY IT MATTERS: this is the actual behavior behind the "recovers
    from failure" requirement in the assignment's agent checklist —
    without this, a single malformed .tf file or one bad LLM response
    would silently zero out the entire audit report instead of just
    that one module's findings.
    PASS: modules 1 and 3 have status "ok", module 2 has status
    "skipped" — and critically, the function returns at all instead
    of raising and killing the whole run.
    FAIL: if this test itself raises, the try/except isn't actually
    wrapping the call, or it's only catching a narrower exception
    type than what the check function raises.
    """
    def flaky_check(module_name: str):
        if module_name == "broken-module":
            raise ValueError("simulated malformed LLM JSON response")
        return f"{module_name} is fine"

    results = run_checks_with_fault_tolerance(
        ["module-a", "broken-module", "module-c"], flaky_check
    )

    assert results["module-a"]["status"] == "ok"
    assert results["broken-module"]["status"] == "skipped"
    assert results["module-c"]["status"] == "ok"


def test_skipped_module_reason_is_captured_not_just_hidden():
    """
    WHAT: confirm the error message itself is retained in the result,
    not just a bare "skipped" flag with no context.
    WHY IT MATTERS: "skipped" with no reason is nearly useless when
    you're reading the final report and trying to figure out whether
    to trust it — you need to know WHY a module was skipped to decide
    if it's safe to ignore or needs a manual look.
    PASS: the error string shows up in the skipped module's result.
    FAIL: check the except block is capturing str(e) and not
    discarding it.
    """
    def always_fails(module_name: str):
        raise RuntimeError("Neo4j connection timed out")

    results = run_checks_with_fault_tolerance(["some-module"], always_fails)
    assert "Neo4j connection timed out" in results["some-module"]["error"]


def test_all_modules_failing_still_returns_a_report_not_an_exception():
    """
    WHAT: worst case — every single module's check fails.
    WHY IT MATTERS: this is the edge of the fault-tolerance policy.
    Even in total failure, the orchestrator should hand back a
    (all-skipped) report for a human to look at, not crash the whole
    process with no output at all — a human reviewing "everything was
    skipped, here's why" can act on that; a stack trace with no
    report gives them nothing.
    PASS: function returns normally, dict has 2 entries, both skipped.
    FAIL: if this raises, something outside the per-module try/except
    is unguarded (e.g. a setup step before the loop starts).
    """
    def always_fails(module_name: str):
        raise ConnectionError("simulated total outage")

    results = run_checks_with_fault_tolerance(["m1", "m2"], always_fails)
    assert len(results) == 2
    assert all(r["status"] == "skipped" for r in results.values())
