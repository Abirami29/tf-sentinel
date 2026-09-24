import sys
sys.path.insert(0, "/opt/airflow")
import json
import requests
import hashlib

from datetime import datetime, timedelta, timezone
from pathlib import Path
from airflow.sdk import Param, dag, get_current_context, task
from airflow.exceptions import AirflowSkipException
from airflow.providers.standard.operators.hitl import HITLOperator
from airflow.providers.common.ai.hooks.langchain import LangChainHook
from airflow.hooks.base import BaseHook

MODULES_ROOT = "/opt/airflow/data/sample-repos/infra-modules/modules"
JIRA_SITE = "https://data-projects.atlassian.net"
JIRA_PROJECT_KEY = "TFS"
REVIEWED_STORE = Path("/opt/airflow/data/reviewed_findings.json")

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
{{"findings": [{{"resource": "<resource address, e.g. aws_security_group.web>", "category": "open_network_access"|"missing_encryption"|"missing_public_access_block"|"other", "issue": "...", "severity": "low"|"medium"|"high", "reasoning": "one sentence, max 20 words"}}]}}
"resource" must be the exact Terraform resource type and name from the code.
Report at most one finding per resource and category.
If there are no findings, return {{"findings": []}}.
"""


class DynamicOptionsHITLOperator(HITLOperator):
    """HITLOperator whose options can come from an upstream task's output."""
    template_fields = (*HITLOperator.template_fields, "options")

    def validate_options(self) -> None:
        # At parse time options is still an XComArg; only validate once it's a real list.
        if isinstance(self.options, list):
            super().validate_options()

    def execute(self, context):
        super().validate_options()  # options is resolved by now
        return super().execute(context)


DEFAULT_REVIEW_LIMIT = 15
OPTION_ISSUE_MAX_CHARS = 120
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "unknown": 3}

ACTION_TICKET = "TICKET"
ACTION_DISMISS = "DISMISS"


def make_option(action: str, finding: dict) -> str:
    # Label only; the full issue text still goes into the Jira ticket.
    issue = finding["issue"]
    if len(issue) > OPTION_ISSUE_MAX_CHARS:
        issue = issue[: OPTION_ISSUE_MAX_CHARS - 3] + "..."
    return f"{action} {finding['finding_id']}: [{finding['module']}] {issue}"


def parse_decisions(chosen_options: list[str]) -> tuple[set[str], set[str], set[str]]:
    """Split HITL selections into (ticket_ids, dismiss_ids, conflict_ids).

    A finding ticked as both TICKET and DISMISS is a conflict and gets no decision
    (fail-closed): it is neither ticketed nor recorded, so it comes back next run.
    """
    ticket, dismiss = set(), set()
    for opt in chosen_options:
        action, fid = opt.split(":", 1)[0].split()
        if action == ACTION_TICKET:
            ticket.add(fid)
        elif action == ACTION_DISMISS:
            dismiss.add(fid)
    conflicts = ticket & dismiss
    return ticket - conflicts, dismiss - conflicts, conflicts


SECURITY_CATEGORIES = {"open_network_access", "missing_encryption", "missing_public_access_block", "other"}


def security_id_key(f: dict) -> str:
    """Stable identity for an LLM finding: resource + category, never the free-text wording.

    The LLM rewords the same issue on every run, so hashing `issue` makes a
    decided finding look new next time. Falls back to the text only if the
    model omitted the structured fields.
    """
    resource = str(f.get("resource", "")).strip().lower()
    category = str(f.get("category", "")).strip().lower()
    if resource and category in SECURITY_CATEGORIES:
        return f"{resource}|{category}"
    return f["issue"]


def stable_finding_id(module: str, check_type: str, issue: str) -> str:
    raw = f"{module}|{check_type}|{issue}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def parse_llm_json(raw: str) -> dict:
    """Parse the LLM response, tolerating ```json fences. Raises ValueError on anything but a JSON object."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    parsed = json.loads(text)  # JSONDecodeError is a ValueError subclass
    if not isinstance(parsed, dict):
        raise ValueError(f"expected JSON object, got {type(parsed).__name__}")
    return parsed


@dag(
    schedule=None,
    catchup=False,
    tags=["tf-sentinel"],
    params={
        "review_limit": Param(
            DEFAULT_REVIEW_LIMIT,
            type="integer",
            minimum=0,
            description="Max findings per review, highest severity first. 0 = show all.",
        ),
    },
)
def tf_sentinel_audit():

    @task
    def list_modules() -> list[str]:
        root = Path(MODULES_ROOT)
        return [str(p) for p in sorted(root.iterdir()) if p.is_dir()]

    @task(map_index_template="{{ module_name }}")
    def run_deterministic_checks(module_dir: str) -> dict:
        from src.deterministic.terraform_validate import validate_module
        from src.deterministic.tflint_check import run_tflint
        from src.deterministic.deletion_protection_check import check_deletion_protection

        module_path = Path(module_dir)
        name = module_path.name
        get_current_context()["module_name"] = name  # set first, so the label shows even if a check fails
        result = {"module": name}

        v = validate_module(module_path)
        result["validate"] = {"valid": v.valid, "error": v.error_message}

        lint = run_tflint(module_path)
        result["tflint"] = {
            "clean": lint.clean,
            "issues": [f"[{i.rule}] {i.message}" for i in lint.issues],
        }

        resource_text = (module_path / "main.tf").read_text()
        result["resource_text"] = resource_text

        dp_issues = check_deletion_protection(name, resource_text)
        result["deletion_protection"] = [i.issue for i in dp_issues]

        return result

    @task(map_index_template="{{ module_name }}")
    def check_security(deterministic_result: dict) -> dict:
        get_current_context()["module_name"] = deterministic_result["module"]
        if not deterministic_result["validate"]["valid"]:
            deterministic_result["security"] = {"status": "skipped_invalid"}
            return deterministic_result

        hook = LangChainHook(
            llm_conn_id="nebius_default",
            llm_model="openai:deepseek-ai/DeepSeek-V4-Flash-0731",
        )
        llm = hook.get_chat_model()
        response = llm.invoke(
            SECURITY_PROMPT.format(
                module_name=deterministic_result["module"],
                resource_text=deterministic_result["resource_text"],
            )
        )
        deterministic_result["security"] = {"status": "checked", "raw_response": str(response.content)}
        return deterministic_result

    @task
    def reshape_findings(module_results: list[dict]) -> list[dict]:
        findings = []

        for result in module_results:
            module = result["module"]

            if not result["validate"]["valid"]:
                error = result["validate"]["error"]
                findings.append({
                    "finding_id": stable_finding_id(module, "validate", error),  # FIX 1: was undefined `issue`
                    "module": module,
                    "check_type": "validate",
                    "detection_method": "deterministic",
                    "issue": error,
                    "severity": "high",
                })

            if not result["tflint"]["clean"]:
                for issue in result["tflint"]["issues"]:
                    findings.append({
                        "finding_id": stable_finding_id(module, "tflint", issue),
                        "module": module,
                        "check_type": "tflint",
                        "detection_method": "deterministic",
                        "issue": issue,
                        "severity": "medium",
                    })

            for issue in result["deletion_protection"]:
                findings.append({
                    "finding_id": stable_finding_id(module, "deletion_protection", issue),
                    "module": module,
                    "check_type": "deletion_protection",
                    "detection_method": "deterministic",
                    "issue": issue,
                    "severity": "high",
                })

            security = result["security"]
            if security.get("status") == "checked":
                try:
                    parsed = parse_llm_json(security["raw_response"])
                    # Build the whole list first so a malformed item doesn't leave partial findings behind.
                    security_findings = [
                        {
                            "finding_id": stable_finding_id(module, "security", security_id_key(f)),
                            "module": module,
                            "check_type": "security",
                            "detection_method": "llm",
                            "issue": f["issue"],
                            "severity": f.get("severity", "unknown"),
                        }
                        for f in parsed.get("findings", [])
                    ]
                    findings.extend(security_findings)
                except (KeyError, TypeError, ValueError) as e:
                    findings.append({
                        # FIX 2b: was leaked `issue`. Keyed per module so the error text (which varies) doesn't matter.
                        "finding_id": stable_finding_id(module, "security_parse_error", "unparseable_response"),
                        "module": module,
                        "check_type": "security_parse_error",
                        "detection_method": "llm",
                        "issue": f"Could not parse LLM response: {e}",
                        "severity": "unknown",
                    })

        return findings

    @task
    def filter_new_findings(findings: list[dict]) -> list[dict]:
        reviewed = json.loads(REVIEWED_STORE.read_text()) if REVIEWED_STORE.exists() else {}
        new, seen = [], set()
        for f in findings:
            fid = f["finding_id"]
            if fid in reviewed or fid in seen:  # also drop same-run duplicates (e.g. repeated tflint messages)
                continue
            seen.add(fid)
            new.append(f)
        return new

    @task
    def prioritize_for_review(findings: list[dict], params=None) -> list[dict]:
        """Highest severity first, capped at review_limit (0 = all). The rest stay pending for the next run."""
        ordered = sorted(findings, key=lambda f: SEVERITY_ORDER.get(f["severity"], 99))
        limit = int((params or {}).get("review_limit", DEFAULT_REVIEW_LIMIT))
        return ordered if limit == 0 else ordered[:limit]

    @task
    def build_options(findings: list[dict]) -> list[str]:
        # HITL can't be shown with zero options; skip the review and everything downstream instead.
        if not findings:
            raise AirflowSkipException("No new findings to review")
        options = []
        for f in findings:  # keep each finding's two options next to each other
            options.append(make_option(ACTION_TICKET, f))
            options.append(make_option(ACTION_DISMISS, f))
        return options

    @task
    def normalize_review(review_response: dict) -> dict:
        """Turn the HITL response into a channel-independent decision set.

        Everything downstream only sees this shape, so a future Slack review
        only has to produce the same dict.
        """
        ticket_ids, dismiss_ids, conflict_ids = parse_decisions(review_response["chosen_options"])
        return {
            "ticket": sorted(ticket_ids),
            "dismiss": sorted(dismiss_ids),
            "conflict": sorted(conflict_ids),
        }

    deterministic_results = run_deterministic_checks.expand(module_dir=list_modules())
    final_results = check_security.expand(deterministic_result=deterministic_results)
    findings = reshape_findings(final_results)
    new_findings = filter_new_findings(findings)
    to_review = prioritize_for_review(new_findings)
    options = build_options(to_review)

    review = DynamicOptionsHITLOperator(
        task_id="review_findings",
        subject="tf-sentinel: Review findings before creating Jira tickets",
        body=(
            "Showing {{ ti.xcom_pull(task_ids='prioritize_for_review') | length }} of "
            "{{ ti.xcom_pull(task_ids='filter_new_findings') | length }} new findings, highest severity first. "
            "To see all of them, trigger the DAG with review_limit = 0.\n\n"
            "Each finding appears twice.\n\n"
            "- Tick **TICKET** to create a Jira issue.\n"
            "- Tick **DISMISS** to close it without a ticket.\n"
            "- Leave both unticked to decide later; it will come back on the next run.\n\n"
            "Ticking both for the same finding counts as no decision."
        ),
        options=options,
        multiple=True,
        response_timeout=timedelta(hours=24),
    )

    @task(retries=0)  # a retry would re-create tickets that already succeeded
    def create_jira_tickets(findings: list[dict], decisions: dict) -> dict[str, str]:
        ticket_ids = set(decisions["ticket"])
        approved_findings = [f for f in findings if f["finding_id"] in ticket_ids]

        conn = BaseHook.get_connection("jira_default")
        auth = (conn.login, conn.password)
        created: dict[str, str] = {}

        for finding in approved_findings:
            payload = {
                "fields": {
                    "project": {"key": JIRA_PROJECT_KEY},
                    "summary": f"[tf-sentinel] {finding['check_type']}: {finding['module']}",
                    "issuetype": {"name": "Task"},
                    "labels": ["tf-sentinel"],
                    "description": {
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{
                                    "type": "text",
                                    "text": f"{finding['issue']} (severity: {finding['severity']}, detected via: {finding['detection_method']})"
                                }]
                            }
                        ]
                    }
                }
            }
            resp = requests.post(f"{JIRA_SITE}/rest/api/3/issue", json=payload, auth=auth, timeout=30)
            resp.raise_for_status()
            created[finding["finding_id"]] = resp.json()["key"]

        return created

    @task
    def record_decisions(findings: list[dict], decisions: dict, jira_keys: dict[str, str]) -> None:
        reviewed = json.loads(REVIEWED_STORE.read_text()) if REVIEWED_STORE.exists() else {}
        ticket_ids, dismiss_ids, conflict_ids = set(decisions["ticket"]), set(decisions["dismiss"]), decisions["conflict"]

        decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        pending = 0
        for f in findings:
            fid = f["finding_id"]
            # Keep the finding's details so the store is readable on its own.
            details = {k: f[k] for k in ("module", "check_type", "severity", "issue")}
            if fid in ticket_ids:
                reviewed[fid] = {"status": "approved", "jira_key": jira_keys.get(fid), "decided_at": decided_at, **details}
            elif fid in dismiss_ids:
                reviewed[fid] = {"status": "dismissed", "decided_at": decided_at, **details}
            else:
                pending += 1  # no decision: not recorded, so it resurfaces next run

        REVIEWED_STORE.write_text(json.dumps(reviewed, indent=2))
        print(
            f"approved={len(ticket_ids)} dismissed={len(dismiss_ids)} "
            f"pending={pending} (of which conflicting={len(conflict_ids)}: {sorted(conflict_ids)})"
        )

    decisions = normalize_review(review.output)
    jira_keys = create_jira_tickets(to_review, decisions)
    record_decisions(to_review, decisions, jira_keys)


tf_sentinel_audit()
