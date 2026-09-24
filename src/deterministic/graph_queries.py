"""
Deterministic structural checks over the parsed repo set.

These do NOT use an LLM. Every function here returns a fact that is
either true or false against the data — no judgment involved. This is
the same category as the module-wise project's queries.py, but
implemented as plain Python over parsed source strings so it can run
without a live Neo4j instance during local/CI testing. A Neo4j-backed
version can wrap these same functions later without changing their
contracts (inputs/outputs stay the same).
"""
import re
from pathlib import Path
from dataclasses import dataclass


@dataclass
class ModuleRef:
    consumer_repo: str
    module_name: str
    version: str


SOURCE_RE = re.compile(
    r'source\s*=\s*"[^"]*//modules/([a-zA-Z0-9_-]+)\?ref=([a-zA-Z0-9._-]+)"'
)


def find_module_references(repos_dir: Path) -> list[ModuleRef]:
    """Walk every consumer repo's .tf files and extract module source refs."""
    refs = []
    for repo_dir in repos_dir.iterdir():
        if not repo_dir.is_dir() or repo_dir.name == "infra-modules":
            continue
        for tf_file in repo_dir.glob("*.tf"):
            text = tf_file.read_text()
            for match in SOURCE_RE.finditer(text):
                module_name, version = match.groups()
                refs.append(ModuleRef(repo_dir.name, module_name, version))
    return refs


def find_unused_modules(repos_dir: Path) -> list[str]:
    """
    Modules defined in infra-modules/modules/* with zero consumers
    across all other repos. Deterministic: pure set difference.
    """
    modules_dir = repos_dir / "infra-modules" / "modules"
    all_modules = {p.name for p in modules_dir.iterdir() if p.is_dir()}
    refs = find_module_references(repos_dir)
    consumed = {r.module_name for r in refs}
    return sorted(all_modules - consumed)


def find_version_drift(repos_dir: Path) -> dict[str, list[ModuleRef]]:
    """
    Modules consumed at more than one distinct version across repos.
    Deterministic: group by module name, flag if >1 distinct version.
    """
    refs = find_module_references(repos_dir)
    by_module: dict[str, list[ModuleRef]] = {}
    for r in refs:
        by_module.setdefault(r.module_name, []).append(r)

    drift = {}
    for module_name, module_refs in by_module.items():
        versions = {r.version for r in module_refs}
        if len(versions) > 1:
            drift[module_name] = module_refs
    return drift


def find_consumers_of(repos_dir: Path, module_name: str) -> list[ModuleRef]:
    """Blast radius: which repos consume a given module, at what version."""
    refs = find_module_references(repos_dir)
    return [r for r in refs if r.module_name == module_name]
