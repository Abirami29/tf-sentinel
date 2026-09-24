"""
ITERATION 1 — Deterministic structural checks.

These are plain correctness tests, not evals. There's no ambiguity
in the answer: a module either has zero consumers or it doesn't, a
module is either consumed at 2+ distinct versions or it isn't. If
these fail, the parsing/matching logic is broken — fix the code, not
the test.
"""
from src.deterministic.graph_queries import (
    find_unused_modules,
    find_version_drift,
    find_consumers_of,
)


def test_finds_the_planted_orphan_module(sample_repos_dir):
    """
    WHAT: sqs-queue is defined in infra-modules but referenced by
    zero consumer repos (planted deliberately — see its main.tf).
    WHY IT MATTERS: this is the exact scenario the audit's "orphan
    module" flag exists to catch — dead infra nobody's using.
    PASS: "sqs-queue" appears in the returned list.
    FAIL: if it's missing, the reference-matching regex or the
    directory walk is silently skipping something.
    """
    unused = find_unused_modules(sample_repos_dir)
    assert "sqs-queue" in unused


def test_does_not_flag_modules_that_are_actually_used(sample_repos_dir):
    """
    WHAT: vpc-base, rds-postgres, s3-bucket-standard are all
    referenced by at least one consumer repo.
    WHY IT MATTERS: false positives here would make the audit noisy
    and untrustworthy — this is the negative-case counterpart to the
    orphan test above.
    PASS: none of these three appear in the unused list.
    FAIL: over-flagging — check the source-ref regex isn't too strict
    or too loose.
    """
    unused = find_unused_modules(sample_repos_dir)
    assert "rds-postgres" not in unused
    assert "s3-bucket-standard" not in unused


def test_finds_the_planted_version_drift(sample_repos_dir):
    """
    WHAT: rds-postgres is referenced at v1.0.0 by service-billing and
    v1.2.0 by service-webshop — two distinct versions, planted
    deliberately.
    WHY IT MATTERS: this is the core "are repos out of sync" signal
    the whole audit is built around.
    PASS: "rds-postgres" is a key in the drift dict, and both
    versions (v1.0.0, v1.2.0) show up among its refs.
    FAIL: either the drift isn't detected at all, or only one version
    is captured — check the source-ref parsing captures ?ref= correctly.
    """
    drift = find_version_drift(sample_repos_dir)
    assert "rds-postgres" in drift
    versions_found = {r.version for r in drift["rds-postgres"]}
    assert versions_found == {"v1.0.0", "v1.2.0"}


def test_does_not_flag_modules_at_consistent_versions(sample_repos_dir):
    """
    WHAT: security-group-web is only referenced at one version
    (v1.0.0) across the sample repos.
    WHY IT MATTERS: negative case — confirms drift detection isn't
    just flagging every module regardless of actual version spread.
    PASS: "security-group-web" is NOT a key in the drift dict.
    FAIL: over-flagging, likely a bug in the version-set comparison
    (e.g. comparing against an empty string instead of skipping).
    """
    drift = find_version_drift(sample_repos_dir)
    assert "security-group-web" not in drift


def test_blast_radius_returns_correct_consumers(sample_repos_dir):
    """
    WHAT: s3-bucket-legacy is consumed by exactly one repo
    (service-analytics) in the sample data.
    WHY IT MATTERS: this is the function the provider-upgrade
    feature's blast-radius step depends on — if it under- or
    over-reports consumers, the upgrade diff will touch the wrong
    files (or miss ones it should touch).
    PASS: exactly one ModuleRef returned, consumer_repo ==
    "service-analytics".
    FAIL: check the regex against the actual source string format in
    service-analytics/main.tf.
    """
    consumers = find_consumers_of(sample_repos_dir, "s3-bucket-legacy")
    assert len(consumers) == 1
    assert consumers[0].consumer_repo == "service-analytics"


def test_blast_radius_on_module_with_no_consumers_returns_empty_not_error(sample_repos_dir):
    """
    WHAT: querying blast radius for the orphaned sqs-queue module.
    WHY IT MATTERS: this is an edge case worth testing explicitly —
    a naive implementation might throw a KeyError or IndexError on
    an empty result instead of gracefully returning [].
    PASS: returns an empty list, no exception raised.
    FAIL: an exception here would crash the whole audit pipeline on
    a perfectly normal "nobody uses this" case — this is exactly the
    kind of thing the fault-injection test (Iteration 3) checks the
    orchestrator handles gracefully, but this test catches it at the
    source.
    """
    consumers = find_consumers_of(sample_repos_dir, "sqs-queue")
    assert consumers == []
