"""
Scopes which files a check run should actually touch.

Two deliberately different scopes (see project write-up Q3):
  - changed_tf_files(): diff-scoped, only files that changed between
    two git refs. Used for validate/lint/security checks — no reason
    to re-scan a whole repo for a one-file change.
  - Cross-repo blast radius (graph_queries.find_consumers_of) is
    NOT diff-scoped on purpose: a change to one module can affect
    consumers who didn't change anything themselves, so that check
    always needs full-graph visibility, not just the diff.
"""
import subprocess
from pathlib import Path


def changed_tf_files(repo_dir: Path, base_ref: str = "HEAD~1", head_ref: str = "HEAD") -> list[Path]:
    """
    Return .tf files that changed between base_ref and head_ref in repo_dir.
    Falls back to "all .tf files" if the repo has no prior commit to diff
    against (e.g. first commit) so callers never silently get an empty scope.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref, head_ref],
            cwd=repo_dir, capture_output=True, text=True, check=True,
        )
        changed = [
            repo_dir / line for line in result.stdout.splitlines()
            if line.endswith(".tf")
        ]
        return [f for f in changed if f.exists()]
    except subprocess.CalledProcessError:
        # No base_ref to diff against (e.g. repo has only one commit).
        # Fall back to scanning everything rather than silently returning [].
        return list(repo_dir.glob("*.tf"))
