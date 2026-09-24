"""
ITERATION 1 — diff scoping. Answers "how do we only scan the new
code changes, not the whole repo every time."
"""
from src.diffing.git_diff_scope import changed_tf_files


def test_only_changed_file_is_returned_not_unchanged_ones(temp_git_repo):
    """
    WHAT: temp_git_repo fixture has two commits — commit 1 adds
    unchanged.tf, commit 2 adds changed.tf. Diffing HEAD~1 vs HEAD
    should return only changed.tf.
    WHY IT MATTERS: this is the entire point of diff-scoping — if
    unchanged.tf shows up here, every check downstream (validate,
    tflint, security_check) will waste time and LLM tokens re-scanning
    files that didn't change, exactly the "full repo re-scan every
    time" problem this was built to avoid.
    PASS: exactly one file returned, and its name is "changed.tf".
    FAIL: if unchanged.tf also comes back, the git diff command args
    are wrong (check base_ref/head_ref order — git diff is base..head,
    reversing them silently returns the opposite set of changes).
    """
    changed = changed_tf_files(temp_git_repo)
    names = {f.name for f in changed}
    assert names == {"changed.tf"}


def test_falls_back_to_full_scan_on_repo_with_no_prior_commit(tmp_path):
    """
    WHAT: a git repo with a single commit and nothing to diff HEAD~1
    against.
    WHY IT MATTERS: this is a real edge case — the very first time
    the audit runs against a repo, there's no "previous state" to
    diff from. A naive implementation would crash or silently return
    an empty file list, meaning the FIRST audit run ever would check
    nothing at all.
    PASS: falls back to returning all .tf files in the repo rather
    than raising an exception or returning [].
    FAIL: if this raises, the try/except in changed_tf_files isn't
    catching the right exception type (git diff against a
    nonexistent ref exits non-zero, which subprocess.run raises as
    CalledProcessError only when check=True is set — confirm that).
    """
    import subprocess
    repo = tmp_path / "fresh-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "only.tf").write_text('resource "aws_vpc" "a" { cidr_block = "10.0.0.0/16" }\n')
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "first"], cwd=repo, check=True, capture_output=True)

    result = changed_tf_files(repo)
    assert len(result) == 1
    assert result[0].name == "only.tf"


def test_non_tf_files_are_excluded_from_scope(temp_git_repo):
    """
    WHAT: add a README.md change alongside a .tf change, confirm only
    the .tf file comes back.
    WHY IT MATTERS: prevents the audit from wasting a parse attempt
    on a markdown file (python-hcl2 would just error on it).
    PASS: README.md is never in the returned list, regardless of
    whether it changed.
    FAIL: the extension filter in changed_tf_files isn't applied
    correctly.
    """
    import subprocess
    (temp_git_repo / "README.md").write_text("some doc change\n")
    subprocess.run(["git", "add", "."], cwd=temp_git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "doc change"], cwd=temp_git_repo, check=True, capture_output=True)

    changed = changed_tf_files(temp_git_repo, base_ref="HEAD~1", head_ref="HEAD")
    names = {f.name for f in changed}
    assert "README.md" not in names
