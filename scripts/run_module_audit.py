"""
Manual verification script — run this to see real output from
module_audit_logic against your synthetic sample repos, before
wrapping it in Airflow. Not a test (no assertions), just a way to
look at real results with your own eyes.

Usage:
    python scripts/run_module_audit.py
"""
import json
from pathlib import Path

from src.orchestrator.module_audit import module_audit_logic

MODULES_ROOT = Path("data/sample-repos/infra-modules/modules")


def main():
    if not MODULES_ROOT.exists():
        print(f"Can't find {MODULES_ROOT} — run this from the repo root.")
        return

    for module_dir in sorted(p for p in MODULES_ROOT.iterdir() if p.is_dir()):
        print(f"\n{'=' * 60}")
        print(f"MODULE: {module_dir.name}")
        print("=" * 60)
        result = module_audit_logic(module_dir)
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
