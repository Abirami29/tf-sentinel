"""
Deterministic syntax/validity check via `terraform validate`.

No LLM involved, ever. This wraps the same init+validate sequence
proved out in tests/test_terraform_validate.py, but as a reusable
function the orchestrator can actually call — rather than that logic
only living inside a test.

SCOPE NOTE: `terraform validate` operates on a whole module
DIRECTORY, not individual files — HCL needs full module context
(variables.tf, provider blocks, etc. defined in sibling files) to
validate correctly. This is why git_diff_scope.changed_tf_files()
returns changed FILES, but validate_module() takes a module
DIRECTORY. validate_changed_modules() below does that file-to-module
mapping for you — don't call validate_module() once per changed file,
call validate_changed_modules() with the file list instead.
"""
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class TerraformNotInstalled(RuntimeError):
    """
    Raised when the terraform CLI isn't on PATH. Caller (the
    orchestrator's fan-out node) should catch this and mark the
    syntax-check step as skipped for this run — per the project's
    fault-tolerance policy — rather than this function silently
    returning a misleading pass/fail.
    """


@dataclass
class ValidateResult:
    module_dir: Path
    valid: bool
    error_message: str  # empty string if valid


def _terraform_available() -> bool:
    return shutil.which("terraform") is not None


def validate_module(module_dir: Path) -> ValidateResult:
    """
    Run `terraform init -backend=false` then `terraform validate`
    against module_dir.

    Raises TerraformNotInstalled if the CLI isn't present, so the
    caller decides how to handle that (skip this check for the whole
    audit run, warn, etc.) instead of this function guessing.
    """
    if not _terraform_available():
        raise TerraformNotInstalled(
            "terraform CLI not found on PATH — install it to enable "
            "syntax/validity checking; until then this check will be "
            "skipped for the whole audit run"
        )

    init_result = subprocess.run(
        ["terraform", "init", "-backend=false", "-input=false", "-no-color"],
        cwd=module_dir, capture_output=True, text=True,
    )
    if init_result.returncode != 0:
        # init failing usually means no network access to the provider
        # registry — that's a different problem than the module being
        # invalid. Surface that distinction rather than reporting a
        # false "invalid" that would send someone hunting for a syntax
        # bug that doesn't exist.
        return ValidateResult(
            module_dir=module_dir,
            valid=False,
            error_message=(
                "terraform init failed (not a code validity issue — "
                f"likely no registry access): {init_result.stderr.strip()}"
            ),
        )

    validate_result = subprocess.run(
        ["terraform", "validate", "-no-color"],
        cwd=module_dir, capture_output=True, text=True,
    )
    return ValidateResult(
        module_dir=module_dir,
        valid=validate_result.returncode == 0,
        error_message="" if validate_result.returncode == 0 else validate_result.stderr.strip(),
    )


def validate_changed_modules(changed_files: list[Path]) -> list[ValidateResult]:
    """
    Maps changed files (typically from
    src.diffing.git_diff_scope.changed_tf_files) up to their
    containing module directories, dedupes, and validates each
    directory ONCE — a module with 3 changed files still only gets
    validated one time, not three.
    """
    module_dirs = {f.parent for f in changed_files}
    return [validate_module(d) for d in sorted(module_dirs)]