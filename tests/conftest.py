"""
Shared fixtures. Nothing in here calls a real LLM or a real cloud
account — that's intentional so `pytest` can run offline, fast, and
in CI without secrets. Anything that genuinely needs network access
(the LLM-judgment checks) gets a `_call_llm` mock, not a live call.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SAMPLE_REPOS = REPO_ROOT / "data" / "sample-repos"


@pytest.fixture
def sample_repos_dir() -> Path:
    return SAMPLE_REPOS


@pytest.fixture
def temp_git_repo(tmp_path):
    """
    A throwaway git repo with two commits, so diff-scoping tests have
    something real to diff against without touching the actual sample
    repos (which stay clean/reusable across test runs).
    """
    repo = tmp_path / "throwaway-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)

    (repo / "unchanged.tf").write_text('resource "aws_vpc" "a" { cidr_block = "10.0.0.0/16" }\n')
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True)

    (repo / "changed.tf").write_text('resource "aws_vpc" "b" { cidr_block = "10.1.0.0/16" }\n')
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add second vpc"], cwd=repo, check=True, capture_output=True)

    return repo
