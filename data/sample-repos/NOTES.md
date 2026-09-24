    # Planted issues — internal reference only

This file documents what's deliberately planted in the sample repos,
for humans reading test results. NEVER referenced by any check's
code — checks only ever read `main.tf` files directly, so nothing
here can leak into an LLM prompt or bias a finding.

(This file replaces inline `# PLANTED ISSUE` comments that used to
live directly in the .tf files — those were accidentally being read
by security_check/duplicate_check as part of the resource text,
meaning the LLM was echoing back the comment's own description of
the expected answer rather than genuinely analyzing the resource
block. Caught via scripts/run_audit.py output on 2026-08-31.)

| Module | Planted issue | Which check should catch it |
|---|---|---|
| `security-group-web` | Open ingress 0.0.0.0/0 on port 22 | `security_check` (LLM) |
| `vpc-base` | Nothing — dedicated negative case | (should never be flagged by anything) |
| `s3-bucket-legacy` / `s3-bucket-standard` | Independently-written near-duplicate modules | `duplicate_check` (LLM) |
| `rds-postgres` | (a) `skip_final_snapshot=true` (b) stale comment claiming encryption is disabled when `storage_encrypted=true` | (a) `deletion_protection_check` (deterministic) (b) future doc-drift check — not yet built |
| `sqs-queue` | Zero consumers across all repos | `find_unused_modules` (deterministic) |
| `s3-bucket-hardened` | Nothing — dedicated negative case, encryption + public-access-block + versioning all present | (should never be flagged by anything) |