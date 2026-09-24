"""
Deterministic check for missing deletion protection on stateful
resources (databases, in scope here — could extend to other stateful
resource types later).

Moved here from security_check.py's LLM prompt after that approach
proved unreliable across 3 consecutive eval runs (0/3 pass rate on
this specific finding). This is a fixed presence/value check, not a
judgment call — exactly the profile that belongs in the deterministic
layer, not the LLM layer, per this project's two-layer design.
"""
import re
from dataclasses import dataclass

# Matches skip_final_snapshot = true (or = "true"), tolerant of
# whitespace/quote variations. Deliberately narrow — only matches
# this one specific argument, not a general-purpose HCL parser.
SKIP_FINAL_SNAPSHOT_RE = re.compile(
    r'skip_final_snapshot\s*=\s*"?true"?', re.IGNORECASE
)


@dataclass
class DeletionProtectionIssue:
    module: str
    issue: str
    severity: str


def check_deletion_protection(module_name: str, resource_text: str) -> list[DeletionProtectionIssue]:
    """
    Flags skip_final_snapshot=true — deletion of the resource will
    not create a final snapshot, meaning accidental deletion is
    unrecoverable. AWS's own default for this argument is False
    (safe), so only an explicit true is worth flagging; absence of
    the argument entirely is not an issue.
    """
    if SKIP_FINAL_SNAPSHOT_RE.search(resource_text):
        return [DeletionProtectionIssue(
            module=module_name,
            issue="skip_final_snapshot=true — accidental deletion will not create a recovery snapshot",
            severity="medium",
        )]
    return []