"""
LLM-judgment security check.

SCOPE: this only handles context-dependent risk assessment — e.g.
network access rules, missing/weak encryption, missing public-access
blocking. Known, fixed-pattern issues (open 0.0.0.0/0 ingress caught
by tflint, deprecated arguments/instance types, missing version-
constraint blocks, missing deletion protection) are handled by the
deterministic layer in src/deterministic/ — see that layer for
terraform_validate.py, tflint_check.py, and
deletion_protection_check.py. This module is intentionally the
smaller, harder-to-automate 20%, not the primary catch-all.

DELETION-PROTECTION EXCLUSION — two layers, on purpose:
Prompt-only exclusion of skip_final_snapshot/deletion-protection
findings proved unreliable across repeated golden-set runs (failed
2 of 3 runs even with an explicit instruction not to report it) —
see eval/golden_sets/security_check_golden.csv history. Rather than
keep tuning the prompt and hoping the model complies, there's now a
deterministic post-filter (EXCLUDED_TERMS) as a backstop that holds
regardless of model behavior or future model swaps.
"""
from dataclasses import dataclass

from src.llm.nebius_client import get_llm, invoke_json


@dataclass
class SecurityFinding:
    module: str
    issue: str
    severity: str  # "low" | "medium" | "high"
    reasoning: str


SECURITY_PROMPT = """You are reviewing Terraform for security risk,
including both clear misconfigurations and context-dependent
judgment calls.

Known deterministic issues already checked separately by other
systems — do NOT report any of these under any circumstances, even
if they appear risky:
- Missing version-constraint blocks (required_version, required_providers)
- Deprecated resource arguments or deprecated instance types
- skip_final_snapshot, deletion protection, or final snapshot settings
  on any resource — this is handled by a separate deterministic
  system, never mention it

Discrepancies between code comments and actual resource configuration
are a SEPARATE documentation-drift concern, checked elsewhere — do
not report those here, only report risk arising from the actual
resource configuration itself.

Specifically check for, in addition to anything else you notice:
- Overly permissive network access (open CIDR ranges, unrestricted ports)
- Missing or weak encryption settings — note: standard SSE-S3 (AES256)
  encryption is adequate and should NOT be flagged on its own; only
  flag encryption that is missing entirely or genuinely misconfigured,
  not a preference for a more advanced tier like SSE-KMS
- Missing public-access blocking on storage resources

Module: {module_name}

{resource_text}

Respond ONLY with valid JSON, no other text, always as an object with
a "findings" key (never a bare list):
{{"findings": [{{"issue": "...", "severity": "low"|"medium"|"high", "reasoning": "one sentence, max 20 words"}}]}}
If there are no findings, return {{"findings": []}}.
"""

# Deterministic backstop — see module docstring. Filters out any
# finding whose issue text mentions these terms, regardless of what
# the prompt asked for, so this exclusion holds even if a model
# doesn't reliably follow the prompt instruction above.
EXCLUDED_TERMS = ["skip_final_snapshot", "final snapshot", "deletion protection"]


def check_module_security(module_name: str, resource_text: str) -> list[SecurityFinding]:
    llm = get_llm(max_tokens=8192, temperature=0.1, frequency_penalty=0.4)
    prompt = SECURITY_PROMPT.format(module_name=module_name, resource_text=resource_text)
    result = invoke_json(llm, prompt)

    if isinstance(result, dict) and "_error" in result:
        return [SecurityFinding(
            module=module_name,
            issue="LLM_CALL_FAILED",
            severity="unknown",
            reasoning=result["_error"],
        )]

    # Defend against the LLM returning a bare list (e.g. `[]` or
    # `[{...}]`) instead of the requested {"findings": [...]} wrapper
    # shape — observed for real on vpc-base during eval runs.
    if isinstance(result, list):
        findings_data = result
    elif isinstance(result, dict):
        findings_data = result.get("findings", [])
    else:
        return [SecurityFinding(
            module=module_name,
            issue="UNEXPECTED_RESPONSE_SHAPE",
            severity="unknown",
            reasoning=f"invoke_json returned type {type(result).__name__}, expected dict or list",
        )]

    findings = [
        SecurityFinding(
            module=module_name,
            issue=f["issue"],
            severity=f["severity"],
            reasoning=f["reasoning"],
        )
        for f in findings_data
    ]

    # Deterministic exclusion backstop — see EXCLUDED_TERMS docstring above.
    findings = [
        f for f in findings
        if not any(term in f.issue.lower() for term in EXCLUDED_TERMS)
    ]

    return findings