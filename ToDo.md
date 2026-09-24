# tf-sentinel — TODO

## In progress
- [ ] Design and implement `merge_findings` — combine structural_audit, module_audit, duplicate_audit outputs into one flat finding list: `{finding_id, check_type, detection_method, module, issue, severity}`

## LLM call routing (active work)
- [ ] #1 — Gate `security_check` (LLM) behind `validate` passing: skip LLM security review on modules that fail basic `terraform validate`, since a semantic security judgment on syntactically broken code is premature. Mark as `skipped_invalid`, not `clean`, in merge_findings output.
- [ ] #2a — Change-triggered fast path: `security_check` only runs on modules that changed in the current run (may already be true via `git_diff_scope` — confirm no path re-checks unchanged modules).
- [ ] #2b — NEW: Separate scheduled DAG (`tf_sentinel_security_sweep`, weekly) that runs `security_check` on ALL modules regardless of change, to catch newly-discovered risk in unchanged code (new CVEs, provider vulnerabilities, shifted best practices). Feeds into the same merge_findings → HITL → Jira pipeline as the change-triggered DAG.
- [ ] #3 — SHELVED: only run `duplicate_audit`'s hardcoded pair check if one of the two known candidate modules changed. Low priority, small scope, revisit only if time allows.

## Core pipeline (not started)
- [ ] Build Airflow DAG: port structural_audit, module_audit, duplicate_audit as @task functions
- [ ] Build HITLOperator step — per-finding approve/dismiss (multi-select)
- [ ] Build Jira ticket creation on approve; suppress on dismiss
- [ ] Wire up Jira sandbox (free Atlassian Cloud plan)

## Known limitations to document in README (deliberately not fixing now)
- [ ] `FERNET_KEY` not set in local Docker Compose setup — defaults to blank, meaning connection passwords/sensitive data in the metadata DB aren't encrypted at rest. Fine for local hackathon development; a real deployment would generate and set a proper Fernet key via the `FERNET_KEY` env var.
- [ ] Terraform is version-pinned (1.9.8), but tflint uses /latest/ - slightly inconsistent reproducibility between the two. Fine for a hackathon demo; a production Dockerfile would pin both explicitly.
- [ ] `module_audit_logic` is called sequentially in `run_module_audit.py` (a manual verification script, not the real execution path). The real DAG should use Airflow dynamic task mapping to parallelize per-module audits, with a bounded pool (not unlimited concurrency) to avoid LLM rate limits / cost spikes — same lesson as the 900+ Snowflake task scaling problem. Not fixed now because there's no real repo/user scale yet to justify it — deliberately deferred, not ignored.
- [ ] `graph_queries.py` module-reference regex only matches one source URL shape (Git-style `?ref=`) — misses registry sources, local relative paths. `python-hcl2` is available but unused; a real parser would close this gap.
- [ ] `deletion_protection_check.py` only checks `skip_final_snapshot=true`, not the `deletion_protection` boolean argument directly.
- [ ] `git_diff_scope.py` hardcoded to `HEAD~1`/`HEAD` — doesn't correctly scope a multi-commit PR's full diff against a target branch's merge-base.
- [ ] `nebius_client.py` — no request timeout, fixed (non-exponential) retry delay, hardcoded to one LLM vendor.
- [ ] `security_check.py`'s deterministic exclusion backstop (`EXCLUDED_TERMS`) only covers one category (deletion protection) — no equivalent backstop for other instructions the LLM might drift on.
- [ ] Eval runner (`eval/run_eval.py`) not yet copied into tf-sentinel — only golden-set CSVs are present.
- [ ] No live Neo4j graph — `graph_queries.py` runs on parsed files, designed for but not yet wired to a real graph DB.
- [ ] Phase 2 / "Layer 2" agentic judgment layer (context-dependent risk review beyond deterministic findings) — deliberately out of scope for hackathon submission.

## Done
- [x] Copy safe files from terraform-governance-agent (deterministic checks, LLM checks, tests, eval golden sets, synthetic .tf files, .tflint.hcl, root + tests conftest.py)
- [x] Strip secrets (.env, tfstate, tfvars, .idea/) — confirmed clean
- [x] Full test suite passing in new repo
- [x] Repo created: tf-sentinel, MIT license
