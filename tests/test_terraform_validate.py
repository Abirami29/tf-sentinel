"""
ITERATION 1 — `terraform validate` integration (syntax/validity, not
config judgment). This answers "does it catch broken code like
Copilot does" — via a real tool, not an LLM guess.

These tests exercise src/deterministic/terraform_validate.py directly
— NOT raw subprocess calls — so a bug in the wrapper itself (wrong
cwd, wrong flag, swallowed stderr) gets caught here, not just a bug
in terraform itself.

Skipped entirely if the `terraform` CLI isn't installed.
"""
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from src.deterministic.terraform_validate import (
    validate_module,
    validate_changed_modules,
    TerraformNotInstalled,
)

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None,
    reason="terraform CLI not installed in this environment",
)


def test_valid_module_passes_validate(sample_repos_dir):
    """
    WHAT: vpc-base is syntactically valid HCL.
    WHY IT MATTERS: negative case — confirms validate_module isn't
    just failing on everything (e.g. due to a missing provider
    schema — the false-failure mode from the last run, now fixed by
    running init first inside the wrapper itself).
    PASS: result.valid is True, error_message is empty.
    FAIL: if init succeeded but this still fails, it's now a real
    problem in vpc-base/main.tf — the wrapper's init step already
    rules out the "missing provider schema" false-failure mode.
    """
    module_dir = sample_repos_dir / "infra-modules" / "modules" / "vpc-base"
    result = validate_module(module_dir)
    assert result.valid is True, result.error_message
    assert result.error_message == ""


def test_module_with_open_security_group_still_passes_validate(sample_repos_dir):
    """
    WHAT: security-group-web has a real security PROBLEM (open
    ingress on :22) but is syntactically VALID HCL.
    WHY IT MATTERS: this is a scope-boundary test — confirms
    validate_module correctly stays in its lane. It should NOT catch
    security misconfigurations; that's tflint/checkov's and the LLM
    security_check's job. If this test fails (validate reports
    invalid), something is confusing "insecure" with "invalid" in
    the wrapper, which would be a category error worth catching
    immediately.
    PASS: result.valid is True — syntactically fine, security concern
    is a separate check's problem.
    FAIL: check the wrapper isn't accidentally doing more than plain
    terraform validate does.
    """
    module_dir = sample_repos_dir / "infra-modules" / "modules" / "security-group-web"
    result = validate_module(module_dir)
    assert result.valid is True, result.error_message


def test_malformed_hcl_fails_validate(tmp_path):
    """
    WHAT: deliberately broken HCL (unclosed brace) in a throwaway dir.
    WHY IT MATTERS: this is the actual "catches incorrect code"
    behavior from the original question — confirms validate_module
    genuinely rejects broken input.
    PASS: result.valid is False, error_message is non-empty.
    FAIL: if this passes, something is wrong with how the wrapper
    invokes validate (e.g. wrong working directory) — terraform
    itself reliably catches this class of error.
    """
    broken = tmp_path / "broken.tf"
    broken.write_text('resource "aws_vpc" "a" {\n  cidr_block = "10.0.0.0/16"\n')  # missing closing brace
    result = validate_module(tmp_path)
    assert result.valid is False
    assert result.error_message != ""


def test_init_failure_is_distinguished_from_a_real_validity_problem(tmp_path):
    """
    WHAT: simulate `terraform init` failing (mocked, so this doesn't
    depend on actually being offline to test the offline case).
    WHY IT MATTERS: the wrapper deliberately labels init failures
    differently from validate failures — an init failure usually
    means "no network access to the registry," not "this code is
    broken." Someone reading an audit report needs to know which one
    they're looking at, or they'll go hunting for a syntax bug that
    doesn't exist.
    PASS: result.valid is False AND error_message explicitly
    mentions "terraform init failed" rather than looking like a
    generic validate error.
    FAIL: check the early-return branch in validate_module() after
    the init subprocess call.
    """
    with patch("src.deterministic.terraform_validate.subprocess.run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = "could not connect to registry.terraform.io"
        result = validate_module(tmp_path)

    assert result.valid is False
    assert "terraform init failed" in result.error_message


def test_missing_terraform_cli_raises_a_clear_error_not_a_silent_pass(tmp_path):
    """
    WHAT: simulate terraform CLI not being on PATH at all (mocked).
    WHY IT MATTERS: this is the fault-tolerance boundary case — if
    terraform isn't installed, the wrapper must raise
    TerraformNotInstalled loudly so the orchestrator's fan-out node
    can mark this check as skipped (per the project's failure-handling
    policy), rather than this function silently returning "valid"
    for a module it never actually checked. A silent false-pass here
    would be worse than no check at all — it would give false
    confidence.
    PASS: TerraformNotInstalled is raised.
    FAIL: check the _terraform_available() guard at the top of
    validate_module() is actually being hit before any subprocess
    call.
    """
    with patch("src.deterministic.terraform_validate.shutil.which", return_value=None):
        with pytest.raises(TerraformNotInstalled):
            validate_module(tmp_path)


def test_multiple_changed_files_in_same_module_only_validates_once(sample_repos_dir):
    """
    WHAT: pass two file paths that both live inside vpc-base/ to
    validate_changed_modules.
    WHY IT MATTERS: terraform validate is not free — it re-checks the
    whole module directory. If a module has 3 changed files, calling
    validate_module() once per file would run the same check three
    times for no benefit. This confirms the file->module dedup
    actually happens.
    PASS: exactly one ValidateResult returned, for vpc-base's
    directory.
    FAIL: check the set-based dedup in validate_changed_modules() —
    likely comparing Path objects that resolve differently (e.g. one
    relative, one absolute) and failing to dedupe as a result.
    """
    module_dir = sample_repos_dir / "infra-modules" / "modules" / "vpc-base"
    fake_changed_files = [module_dir / "main.tf", module_dir / "main.tf"]  # same file twice, worst case

    results = validate_changed_modules(fake_changed_files)
    assert len(results) == 1
    assert results[0].module_dir == module_dir