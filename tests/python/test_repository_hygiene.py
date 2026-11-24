"""Guards against committing restricted data through normal use of this repository."""
from __future__ import annotations

import re
import subprocess

from conftest import ROOT

IGNORED_DIRS = {".git", "node_modules", "dist", ".venv", ".demo", "test-results", "playwright-report", "__pycache__",
                ".pytest_cache"}
DATA_SUFFIXES = {".csv", ".json", ".jsonl", ".parquet", ".pq", ".txt", ".zip"}


def _files():
    """Files git would commit (tracked or untracked, honouring .gitignore)."""
    listing = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True)
    if listing.returncode == 0:
        yield from (ROOT / line for line in listing.stdout.splitlines() if (ROOT / line).is_file())
        return
    for path in ROOT.rglob("*"):            # not a git checkout: fall back to a directory walk
        parts = set(path.relative_to(ROOT).parts)
        if path.is_file() and not IGNORED_DIRS & parts and not any(p.endswith(".egg-info") for p in parts):
            yield path


def test_gitignore_blocks_local_data_and_demo_state():
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for rule in ("/data/", ".demo/", "*.parquet", "*.pq", ".env"):
        assert rule in rules, rule


def test_demo_writes_go_to_an_ignored_directory(tmp_path):
    probe = ROOT / ".demo" / "data_root" / "rebuttal_audit_annotations" / "x" / "y.json"
    result = subprocess.run(["git", "check-ignore", "-q", str(probe)], cwd=ROOT, capture_output=True)
    if result.returncode == 128:      # not a git checkout (e.g. a source archive)
        return
    assert result.returncode == 0


def test_data_files_live_only_in_synthetic_examples_and_results():
    allowed = ("examples/synthetic/", "results/", "config/rubric.json", "package.json", "package-lock.json",
               "tsconfig", "uv.lock", ".github/", "requirements-web.txt")
    for path in _files():
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix in DATA_SUFFIXES and not relative.startswith(allowed):
            raise AssertionError(f"unexpected data file outside examples/ and results/: {relative}")


def test_examples_and_results_contain_no_mimic_style_identifiers():
    # MIMIC-IV subject_id / hadm_id are 8-digit numbers beginning with 1 or 2.
    pattern = re.compile(r"(?<![\d.])[12]\d{7}(?![\d.])")
    allowed = {"20260917"}            # the bootstrap seed of the original analysis
    for directory in ("examples", "results", "docs"):
        for path in (ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix in {".csv", ".json", ".md", ".txt", ".mmd"}:
                found = set(pattern.findall(path.read_text(encoding="utf-8", errors="replace"))) - allowed
                assert not found, f"{path.relative_to(ROOT)} contains identifier-like numbers"
