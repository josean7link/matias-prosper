"""Fase 0 (Aug 2026) — Enforce the pytest failure baseline.

Runs the full backend test suite, compares the set of failing tests
against the frozen baseline in `backend/tests/BASELINE_FAILURES.md`,
and exits non-zero if a test that was NOT in the baseline is failing.

Rationale: the suite currently has ~48 pre-existing failures that we
are choosing not to fix as part of the KYB work. Without a canary,
any new regression drowns in that noise. This script is the canary.

The baseline only shrinks. New failures = regression. Pre-existing
failures that get fixed on their own initiative are welcome — they
are reported but do not fail the run (they should be removed from the
baseline in a follow-up commit).

Usage:
    python scripts/check_test_baseline.py
    # exits 0 if no regressions; 2 if regressions present; 1 on error
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_MD = REPO_ROOT / "backend" / "tests" / "BASELINE_FAILURES.md"


def _parse_baseline() -> tuple[set[str], set[str]]:
    """Return (stable_failures, flaky_failures) parsed from BASELINE.

    The file has two tables (STABLE, FLAKY). Rows have the shape
    `| N | \\`tests/x::y\\` | ... |`. Section header before each row
    determines the bucket.
    """
    if not BASELINE_MD.exists():
        print(f"ERROR: baseline file not found at {BASELINE_MD}",
              file=sys.stderr)
        sys.exit(1)
    stable: set[str] = set()
    flaky: set[str] = set()
    bucket = stable
    for line in BASELINE_MD.read_text().splitlines():
        low = line.lower()
        if low.startswith("## stable failures"):
            bucket = stable
            continue
        if low.startswith("## flaky"):
            bucket = flaky
            continue
        m = re.match(r"\|\s*\d+\s*\|\s*`([^`]+)`\s*\|", line)
        if m:
            bucket.add(m.group(1).strip())
    return stable, flaky


def _run_pytest() -> tuple[set[str], int]:
    proc = subprocess.run(
        ["python", "-m", "pytest", "tests/", "--tb=no", "-q",
         "-p", "no:cacheprovider"],
        cwd=REPO_ROOT / "backend",
        capture_output=True, text=True, timeout=600)
    failing: set[str] = set()
    for line in proc.stdout.splitlines():
        if not line.startswith("FAILED "):
            continue
        m = re.match(r"FAILED (\S+)", line)
        if m:
            failing.add(m.group(1).strip())
    return failing, proc.returncode


def main() -> int:
    stable, flaky = _parse_baseline()
    failing, rc = _run_pytest()
    # A test in `flaky` is neither a regression when it fails nor a
    # "resolved bonus" when it passes.
    new_failures = sorted(failing - stable - flaky)
    resolved = sorted(stable - failing)
    flaky_hit = sorted(failing & flaky)

    print(f"stable baseline:    {len(stable)}")
    print(f"flaky baseline:     {len(flaky)}  (not counted as failures)")
    print(f"currently failing:  {len(failing)}")
    print(f"resolved (bonus):   {len(resolved)}")
    print(f"flaky observed:     {len(flaky_hit)}")
    print(f"NEW failures:       {len(new_failures)}")
    print()
    if flaky_hit:
        print("Flaky tests observed failing this run "
              "(informational — not a regression):")
        for n in flaky_hit:
            print(f"  ~ {n}")
        print()
    if resolved:
        print("Pre-existing failures that no longer fail "
              "(consider removing from baseline):")
        for n in resolved:
            print(f"  - {n}")
        print()
    if new_failures:
        print("REGRESSIONS — these tests were passing in the baseline "
              "and now fail:")
        for n in new_failures:
            print(f"  ! {n}")
        return 2
    print("OK — no regressions vs baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
