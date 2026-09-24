"""
Root-level conftest. Separate from tests/conftest.py (which holds
fixtures) — this file's only job is guaranteeing the repo root is on
sys.path so `from src...` imports resolve, regardless of how pytest
is invoked or which pytest version is running. Belt-and-suspenders
alongside pytest.ini's `pythonpath = .` setting.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))