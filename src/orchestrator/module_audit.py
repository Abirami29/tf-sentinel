"""
Plain-Python module audit logic — deliberately NOT an Airflow task yet.
This function has no Airflow dependency at all; it can be called directly
from a script, a test, or later wrapped in a one-line @task decorator
without any change to the logic itself.

Routing decision (see TODO.md, item #1):
  security_check (LLM) is SKIPPED when a module fails terraform validate.
  A semantic security judgment on syntactically broken code is premature
  and wastes an LLM call on something that can't even be applied yet.
  Skipped modules are marked "skipped_invalid", never silently "clean".
"""
from pathlib import Path
import logging

from src.deterministic.terraform_validate import validate_module, TerraformNotInstalled
from src.deterministic.tflint_check import run_tflint, TflintNotInstalled
from src.deterministic.deletion_protection_check import check_deletion_protection
from src.llm_checks.security_check import check_module_security


def module_audit_logic(module_dir: Path) -> dict:
    """
    Runs all checks for a single module directory. Returns a nested
    result dict — reshaping into the flat finding format happens later,
    in merge_findings, so this function has one job: run checks
    correctly and report what happened, including what was skipped
    and why.
    """
    name = module_dir.name
    result: dict = {"module": name, "errors": []}

    # --- validate: always runs, it's the gate for security below ---
    try:
        v = validate_module(module_dir)
        result["validate"] = {"valid": v.valid, "error": v.error_message}
    except TerraformNotInstalled as e:
        # Environment problem, not a per-module problem — no point
        # continuing to "check" every other module the same way.
        logging.error(f"Terraform not installed — aborting run: {e}")
        raise

    except Exception as e:
        result["validate"] = {"skipped": True, "reason": str(e)}
        result["errors"].append(f"{name} validate: {e}")
        v = None

    # --- tflint: always runs, independent of validate result ---
    try:
        lint = run_tflint(module_dir)
        result["tflint"] = {
            "clean": lint.clean,
            "issues": [f"[{i.rule}] {i.message}" for i in lint.issues],
        }
    except TerraformNotInstalled as e:
        # Environment problem, not a per-module problem — no point
        # continuing to "check" every other module the same way.
        logging.error(f"Terraform not installed — aborting run: {e}")
        raise
    except Exception as e:
        result["tflint"] = {"skipped": True, "reason": str(e)}
        result["errors"].append(f"{name} tflint: {e}")

    # --- need resource text for deletion_protection + security ---
    try:
        resource_text = (module_dir / "main.tf").read_text()
    except Exception as e:
        result["errors"].append(f"{name} read main.tf: {e}")
        return result  # can't run remaining checks without the file

    # --- deletion_protection: always runs, cheap, deterministic ---
    try:
        dp_issues = check_deletion_protection(name, resource_text)
        result["deletion_protection"] = [i.issue for i in dp_issues]
    except Exception as e:
        result["deletion_protection"] = {"skipped": True, "reason": str(e)}
        result["errors"].append(f"{name} deletion_protection: {e}")

    # --- security (LLM): GATED behind validate passing (routing #1) ---
    validate_passed = v is not None and getattr(v, "valid", False)
    if validate_passed:
        try:
            sec_findings = check_module_security(name, resource_text)
            result["security"] = {
                "status": "checked",
                "findings": [
                    f"[{f.severity}] {f.issue}: {f.reasoning}" for f in sec_findings
                ],
            }
        except Exception as e:
            result["security"] = {"status": "error", "reason": str(e)}
            result["errors"].append(f"{name} security_check: {e}")
    else:
        # Explicitly distinguish "skipped because invalid" from "clean"
        result["security"] = {
            "status": "skipped_invalid",
            "reason": "terraform validate failed; skipping LLM security review",
        }

    return result
