"""
ITERATION 1 — tflint core rules + tflint-ruleset-aws plugin.

Skipped entirely if the tflint CLI isn't installed. The AWS-plugin
tests will additionally skip (not fail) if there's no network access
to download the plugin on first run — same pattern as
test_terraform_validate.py's init step.
"""
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from src.deterministic.tflint_check import (
    run_tflint,
    lint_changed_modules,
    TflintNotInstalled,
)

pytestmark = pytest.mark.skipif(
    shutil.which("tflint") is None,
    reason="tflint CLI not installed in this environment",
)


def test_module_with_unused_variable_is_flagged(tmp_path):
    """
    WHAT: a module that declares a variable it never uses (core
    tflint rule, no plugin needed).
    WHY IT MATTERS: sanity check that the wrapper correctly invokes
    tflint and parses its JSON output, independent of the AWS plugin
    working at all.
    PASS: clean is False, at least one issue has rule name containing
    "unused".
    FAIL: if this comes back clean, check the JSON parsing — tflint's
    key names can drift between versions.
    """
    (tmp_path / "main.tf").write_text(
        'variable "unused_var" {\n  type = string\n}\n\n'
        'resource "aws_vpc" "a" {\n  cidr_block = "10.0.0.0/16"\n}\n'
    )
    result = run_tflint(tmp_path)
    assert result.clean is False
    assert any("unused" in issue.rule for issue in result.issues), result.issues


def test_deprecated_aws_instance_type_is_flagged(tmp_path):
    """
    WHAT: an aws_instance using a previous-generation instance type
    (t1.micro) — this is the actual answer to "does it check for
    deprecation warnings based on the versions and resources used."
    Requires the tflint-ruleset-aws plugin (aws_instance_previous_type
    rule), not core tflint.
    WHY IT MATTERS: this is the test that actually proves the AWS
    deprecation-checking claim, as opposed to just core syntax
    linting. If this test is the one skipping while others pass,
    that specifically means the plugin isn't loading — check
    .tflint.hcl is being found via --config and the plugin actually
    downloaded (rerun with network access).
    PASS: clean is False, at least one issue's rule name contains
    "previous_type".
    FAIL: if this test SKIPS (not fails), it's a network/plugin-init
    problem, not a code problem — see the skip reason. If it FAILS
    (runs but doesn't flag it), the plugin loaded but either the rule
    is disabled by default or t1.micro isn't covered by this rule
    version — check the installed plugin version's rule docs.
    """
    (tmp_path / "main.tf").write_text(
        'resource "aws_instance" "old" {\n'
        '  ami           = "ami-12345678"\n'
        '  instance_type = "t1.micro"\n'
        '}\n'
    )
    result = run_tflint(tmp_path)

    if result.issues and result.issues[0].rule == "tflint_init_error":
        pytest.skip(f"AWS plugin unavailable: {result.issues[0].message}")

    assert result.clean is False
    assert any("previous_type" in issue.rule for issue in result.issues), result.issues


def test_clean_module_produces_no_issues(sample_repos_dir):
    """
    WHAT: vpc-base — no unused variables, nothing deprecated.
    WHY IT MATTERS: negative case — confirms the wrapper isn't
    over-flagging by default.
    PASS: clean is True, issues list is empty.
    FAIL: if unexpectedly not clean, read the actual issues list
    first — it might be catching something legitimate (e.g. a
    missing required_providers block) worth knowing about regardless.
    """
    module_dir = sample_repos_dir / "infra-modules" / "modules" / "vpc-base"
    result = run_tflint(module_dir)
    assert result.clean is True, result.issues


def test_missing_tflint_cli_raises_not_silent_pass(tmp_path):
    """
    WHAT: simulate tflint not being on PATH (mocked).
    WHY IT MATTERS: a silent false-"clean" here would give false
    confidence a module was checked when it never was.
    PASS: TflintNotInstalled is raised.
    FAIL: check the _tflint_available() guard is hit before the
    subprocess call.
    """
    with patch("src.deterministic.tflint_check.shutil.which", return_value=None):
        with pytest.raises(TflintNotInstalled):
            run_tflint(tmp_path)


def test_non_json_output_is_treated_as_execution_error_not_clean(tmp_path):
    """
    WHAT: simulate tflint returning garbage on stdout (mocked).
    WHY IT MATTERS: JSON-parse failure must never default to "clean"
    — that would silently hide a real execution problem as a passing
    check.
    PASS: clean is False, issue rule identifies this as an execution
    error, not a real lint finding.
    FAIL: check the except json.JSONDecodeError branch in
    run_tflint(). Note this test patches subprocess.run globally
    within the module, so it also skips past the init call — that's
    intentional, it's testing the second subprocess call's failure
    mode specifically.
    """
    with patch("src.deterministic.tflint_check._tflint_init", return_value=(True, "")):
        with patch("src.deterministic.tflint_check.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "not valid json at all"
            mock_run.return_value.stderr = "some crash message"
            result = run_tflint(tmp_path)

    assert result.clean is False
    assert result.issues[0].rule == "tflint_execution_error"


def test_multiple_changed_files_in_same_module_only_lints_once(sample_repos_dir):
    """
    WHAT: pass two file paths inside vpc-base/ to lint_changed_modules.
    WHY IT MATTERS: same dedup contract as validate_changed_modules —
    don't re-run the same lint pass 3 times for a module with 3
    changed files.
    PASS: exactly one LintResult returned, for vpc-base's directory.
    FAIL: check the set-based dedup — likely a Path comparison issue
    if paths resolve differently (relative vs. absolute).
    """
    module_dir = sample_repos_dir / "infra-modules" / "modules" / "vpc-base"
    fake_changed_files = [module_dir / "main.tf", module_dir / "main.tf"]

    results = lint_changed_modules(fake_changed_files)
    assert len(results) == 1
    assert results[0].module_dir == module_dir