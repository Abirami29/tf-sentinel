"""
Deterministic lint check via `tflint` + the tflint-ruleset-aws
plugin.

Covers two tiers:
  - tflint core rules: unused variables/declarations, invalid syntax
    (zero setup, no plugin needed)
  - tflint-ruleset-aws plugin: AWS-specific deprecations — deprecated
    instance types, deprecated resource arguments (this is the piece
    that actually answers "does it check for deprecation warnings
    based on the versions and resources used")

The plugin needs a one-time network download (like terraform init
downloading a provider), cached globally in the user's home dir by
tflint itself afterwards — same shape as terraform_validate.py's
init step, so the failure/skip handling mirrors that file
deliberately.
"""
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Repo-root .tflint.hcl — referenced via --config so every module
# directory uses the same plugin config regardless of its own cwd.
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / ".tflint.hcl"


class TflintNotInstalled(RuntimeError):
    """
    Raised when the tflint CLI isn't on PATH. Same contract as
    TerraformNotInstalled in terraform_validate.py — caller (the
    orchestrator's fan-out node) should catch this and mark the lint
    check as skipped for this run, not silently treat it as "clean."
    """


@dataclass
class LintIssue:
    rule: str
    message: str
    severity: str  # tflint reports "error" | "warning" | "notice"


@dataclass
class LintResult:
    module_dir: Path
    clean: bool
    issues: list[LintIssue] = field(default_factory=list)


def _tflint_available() -> bool:
    return shutil.which("tflint") is not None


def _tflint_init() -> tuple[bool, str]:
    """
    Downloads/verifies the aws ruleset plugin per _CONFIG_PATH.
    Idempotent — safe to call before every run_tflint; if the plugin
    is already cached, this just verifies and returns fast rather
    than re-downloading.
    Returns (ok, error_message).
    """
    result = subprocess.run(
        ["tflint", "--init", "--config", str(_CONFIG_PATH)],
        capture_output=True, text=True,
    )
    return result.returncode == 0, result.stderr.strip()


def run_tflint(module_dir: Path) -> LintResult:
    """
    Run `tflint --format=json --config <repo-root>/.tflint.hcl`
    against module_dir, covering both core rules and AWS-specific
    deprecation rules.

    Raises TflintNotInstalled if the CLI isn't present.
    """
    if not _tflint_available():
        raise TflintNotInstalled(
            "tflint CLI not found on PATH — install it to enable lint "
            "checks; until then this check will be skipped for the "
            "whole audit run"
        )

    init_ok, init_error = _tflint_init()
    if not init_ok:
        # Plugin download failed — almost always no network access to
        # the registry, not a problem with the code being checked.
        # Distinguish this from a real lint finding so a human reading
        # the report doesn't go hunting for a bug that doesn't exist.
        return LintResult(
            module_dir=module_dir,
            clean=False,
            issues=[LintIssue(
                rule="tflint_init_error",
                message=f"tflint --init failed (likely no plugin registry access): {init_error}",
                severity="error",
            )],
        )

    result = subprocess.run(
        ["tflint", "--format=json", "--config", str(_CONFIG_PATH)],
        cwd=module_dir, capture_output=True, text=True,
    )

    # tflint exits non-zero both when it finds issues AND on a real
    # crash — the JSON output is what actually distinguishes those
    # two cases, not the exit code alone.
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return LintResult(
            module_dir=module_dir,
            clean=False,
            issues=[LintIssue(
                rule="tflint_execution_error",
                message=f"tflint did not return valid JSON — stderr: {result.stderr.strip()}",
                severity="error",
            )],
        )

    issues = [
        LintIssue(
            rule=i["rule"]["name"],
            message=i["message"],
            severity=i["rule"].get("severity", "warning"),
        )
        for i in payload.get("issues", [])
    ]
    return LintResult(module_dir=module_dir, clean=len(issues) == 0, issues=issues)


def lint_changed_modules(changed_files: list[Path]) -> list[LintResult]:
    """
    Same file->module dedup pattern as
    terraform_validate.validate_changed_modules — a module with 3
    changed files still only gets linted once.
    """
    module_dirs = {f.parent for f in changed_files}
    return [run_tflint(d) for d in sorted(module_dirs)]