"""
ITERATION 1 — deletion-protection check. Deterministic, no LLM,
no ambiguity: skip_final_snapshot either appears set to true in the
text or it doesn't.
"""
from src.deterministic.deletion_protection_check import check_deletion_protection


def test_flags_skip_final_snapshot_true(sample_repos_dir):
    """
    WHAT: rds-postgres has skip_final_snapshot = true (planted,
    same module the LLM check kept missing across 3 eval runs).
    WHY IT MATTERS: this is the actual fix for the reliability
    problem — a fixed presence/value check doesn't have the flakiness
    an LLM judgment call does.
    PASS: exactly one issue returned for rds-postgres.
    FAIL: check the regex against the actual formatting in
    rds-postgres/main.tf — quote style or spacing may not match.
    """
    module_path = sample_repos_dir / "infra-modules" / "modules" / "rds-postgres" / "main.tf"
    resource_text = module_path.read_text()

    issues = check_deletion_protection("rds-postgres", resource_text)
    assert len(issues) == 1
    assert "skip_final_snapshot" in issues[0].issue


def test_does_not_flag_module_without_the_argument_at_all(sample_repos_dir):
    """
    WHAT: vpc-base has no skip_final_snapshot argument anywhere
    (it's not even a database resource).
    WHY IT MATTERS: negative case — confirms the regex isn't matching
    something unrelated by accident.
    PASS: empty list.
    FAIL: over-matching — check the regex isn't accidentally matching
    partial/unrelated text.
    """
    module_path = sample_repos_dir / "infra-modules" / "modules" / "vpc-base" / "main.tf"
    resource_text = module_path.read_text()

    issues = check_deletion_protection("vpc-base", resource_text)
    assert issues == []


def test_does_not_flag_explicit_false():
    """
    WHAT: a resource with skip_final_snapshot = false explicitly set.
    WHY IT MATTERS: false is the safe value (AWS default too) — only
    an explicit true is the actual risk. This confirms the regex
    checks the VALUE, not just the argument's presence.
    PASS: empty list.
    FAIL: check the regex is matching "true" specifically, not just
    the argument name.
    """
    text = 'resource "aws_db_instance" "x" {\n  skip_final_snapshot = false\n}\n'
    issues = check_deletion_protection("test-module", text)
    assert issues == []


def test_handles_quoted_true_value():
    """
    WHAT: skip_final_snapshot = "true" (quoted string, less common
    but valid HCL — some people write booleans as strings).
    WHY IT MATTERS: a regex that only matches the bare `true` token
    would silently miss this equally-real variant.
    PASS: one issue returned.
    FAIL: check the regex's optional-quote handling.
    """
    text = 'resource "aws_db_instance" "x" {\n  skip_final_snapshot = "true"\n}\n'
    issues = check_deletion_protection("test-module", text)
    assert len(issues) == 1