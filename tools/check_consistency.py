#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_consistency.py — the one place that decides how many tests this project has.

Why
---
The fourth, fifth and sixth independent reviews all found the same *kind* of
gap in the verification chain: the suite, the README and the evidence script
each declared a test count, but nothing checked all three at once.  The script
and CI therefore drifted apart, and a green `moon test` was routinely mistaken
for "the suite ran".

This module is the single entry point that closes that gap.  It is called by

    * ``tools/regenerate_evidence.sh``  (the evidence run), and
    * ``.github/workflows/ci.yml``       (CI),

so the two can no longer assert different things.  It checks **three** numbers
against each other:

    1. the number of tests the suite actually ran (``moon test`` output),
    2. the number this module declares (``EXPECTED_TESTS``), and
    3. the number the README declares (every ``<N> tests`` it mentions).

Measured facts about ``moon test`` (MoonBit 0.1.20261119, verified on the
server — see ``README.md`` §4.7):

    * removing ``moon.pkg``            -> ``moon test`` exits **255**,
                                         ``moon check`` exits **255**;
    * removing the *test file* only    -> ``moon test`` exits **0** having
                                         found nothing at all;
    * a failing assertion              -> ``moon test`` exits non-zero **and**
                                         still prints the summary line.

Because the third case prints a summary and the second one does not, the
summary line is the only reliable signal — hence the explicit count assertion
below, and hence the readable diagnostics: a caller that only looks at the
exit code is told *what* went wrong, not just *that* something did.

Usage::

    python3 tools/check_consistency.py                     # run `moon test` itself
    python3 tools/check_consistency.py --test-log PATH     # check a saved log
    python3 tools/check_consistency.py --print-expected    # print the declared count

Exit codes::

    0  everything agrees
    2  the environment is unusable (e.g. `moon` is not installed)
    3  a consistency failure — the diagnostic is printed on stderr
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# The declared number of tests.  This constant is the single source of truth:
# the evidence script and CI both come here, so they cannot disagree with
# each other, and the README is cross-checked against it.
#
# The environment variable EXPECTED_TESTS overrides it, which is how the
# "what if the README and the suite drifted apart?" experiments are run.
# --------------------------------------------------------------------------
EXPECTED_TESTS = 37

# "37 tests", "37 tests." — the way the README declares a count.
README_COUNT_RE = re.compile(r"(\d+)\s+tests")

# "Total tests: 37, passed: 37, failed: 0." — the way `moon test` declares one.
TOTAL_RE = re.compile(r"Total tests:\s*(\d+)")
PASSED_RE = re.compile(r"passed:\s*(\d+)")
FAILED_RE = re.compile(r"failed:\s*(\d+)")

EXIT_OK = 0
EXIT_ENV = 2
EXIT_MISMATCH = 3


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def expected_tests() -> int:
    raw = os.environ.get("EXPECTED_TESTS")
    if raw is None or raw.strip() == "":
        return EXPECTED_TESTS
    try:
        return int(raw.strip())
    except ValueError:
        print(
            f"error: EXPECTED_TESTS={raw!r} is not an integer.",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_ENV)


def run_moon_test() -> tuple[str, int]:
    """Run `moon test` and return (combined output, exit code)."""
    try:
        proc = subprocess.run(
            ["moon", "test"],
            cwd=str(project_root()),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except FileNotFoundError:
        print(
            "error: 'moon' not found in PATH.\n"
            "       install it with:\n"
            "         curl -fsSL https://cli.moonbitlang.com/install/unix.sh | bash\n"
            "         export PATH=\"$HOME/.moon/bin:$PATH\"",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_ENV)
    return proc.stdout, proc.returncode


def tail(text: str, lines: int = 8) -> str:
    parts = [ln for ln in text.splitlines() if ln.strip()]
    if not parts:
        return "    (no output)"
    picked = parts[-lines:]
    return "\n".join("    " + ln for ln in picked)


def last_int(pattern: re.Pattern, text: str) -> int | None:
    """The **last** number the pattern matches, or None.

    The last one is the summary line: `moon test` prints its summary at the
    end, and a failing test's own line can contain the words "passed"/"failed"
    before that.
    """
    found = pattern.findall(text)
    return int(found[-1]) if found else None


def check(
    test_log: str,
    moon_exit: int,
    readme: Path,
    expected: int,
    log_path: Path | None = None,
) -> int:
    """Run every consistency check.  Returns the process exit code."""
    # --- 1. did `moon test` even produce a summary? ------------------------
    n_total = last_int(TOTAL_RE, test_log)
    if n_total is None:
        print("error: 'moon test' produced no test summary line.", file=sys.stderr)
        print(
            "       The summary looks like 'Total tests: N, passed: N, failed: N'.",
            file=sys.stderr,
        )
        print(f"       'moon test' exited with {moon_exit}.", file=sys.stderr)
        if log_path is not None:
            print(f"       Full output: {log_path}", file=sys.stderr)
        print("       Last lines of the output:", file=sys.stderr)
        print(tail(test_log), file=sys.stderr)
        print(
            "       NOTE: a missing 'moon.pkg' makes 'moon test' exit 255 — it does\n"
            "       NOT exit 0. A green exit code only happens when the *test\n"
            "       files* are gone while 'moon.pkg' is intact.",
            file=sys.stderr,
        )
        return EXIT_MISMATCH

    n_passed = last_int(PASSED_RE, test_log)
    n_failed = last_int(FAILED_RE, test_log)
    n_passed = 0 if n_passed is None else n_passed
    n_failed = 0 if n_failed is None else n_failed

    # --- 2. the suite ran at all? -----------------------------------------
    if n_total == 0:
        print("error: 'moon test' found 0 tests.", file=sys.stderr)
        print(
            "       A green exit code here does NOT mean the suite ran:", file=sys.stderr
        )
        print(
            "       MoonBit exits 0 when it discovers no test entry (e.g. the test\n"
            "       file was deleted while 'moon.pkg' is still intact).",
            file=sys.stderr,
        )
        if log_path is not None:
            print(f"       Full output: {log_path}", file=sys.stderr)
        return EXIT_MISMATCH

    # --- 3. did every test pass? -------------------------------------------
    # This comes *before* the count check on purpose: when a test really
    # fails, "total=… passed=… failed=…" is the diagnostic that names the
    # problem, and the count may be off as a *consequence* of the failure.
    if n_passed != n_total or n_failed != 0:
        print(
            f"error: 'moon test': total={n_total} passed={n_passed} failed={n_failed}",
            file=sys.stderr,
        )
        print(
            "       The suite did not pass — see the log for the failing test.",
            file=sys.stderr,
        )
        if log_path is not None:
            print(f"       Full output: {log_path}", file=sys.stderr)
        print("       Last lines of the output:", file=sys.stderr)
        print(tail(test_log), file=sys.stderr)
        return EXIT_MISMATCH

    # --- 4. the suite agrees with the declared count? -----------------------
    if n_total != expected:
        print(
            f"error: 'moon test' ran {n_total} tests, but the project declares "
            f"{expected}.",
            file=sys.stderr,
        )
        print(
            "       Either a test file was lost, or the declared count and the\n"
            "       suite disagree.",
            file=sys.stderr,
        )
        if log_path is not None:
            print(f"       Full output: {log_path}", file=sys.stderr)
        return EXIT_MISMATCH

    # --- 5. does the README agree? -----------------------------------------
    if not readme.is_file():
        print(
            f"error: README drift: {readme} does not exist, so the documented test\n"
            "       count can no longer be checked against the suite.",
            file=sys.stderr,
        )
        print(
            "       Restore the README (or pass --readme) — the documentation and\n"
            "       the suite must not drift apart silently.",
            file=sys.stderr,
        )
        return EXIT_MISMATCH

    readme_text = readme.read_text(encoding="utf-8")
    counts = sorted({int(n) for n in README_COUNT_RE.findall(readme_text)})
    if not counts:
        print(
            f"error: README drift: {readme} mentions no test count at all "
            "(no '<N> tests' phrase).",
            file=sys.stderr,
        )
        return EXIT_MISMATCH
    if counts != [expected]:
        listed = " ".join(str(c) for c in counts)
        print(
            f"error: README drift: README mentions test counts [{listed}], "
            f"expected only {expected}.",
            file=sys.stderr,
        )
        print(
            "       The document and the suite must declare the same number.",
            file=sys.stderr,
        )
        return EXIT_MISMATCH

    print(
        f"    [assert] moon test: {n_total} tests, {n_passed} passed, "
        f"{n_failed} failed (README agrees)"
    )
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assert that the suite, the declared count and the README agree."
    )
    parser.add_argument(
        "--test-log",
        default=None,
        help="file holding the `moon test` output (default: run `moon test`)",
    )
    parser.add_argument(
        "--moon-exit",
        type=int,
        default=None,
        help="exit code of the `moon test` run (default: 0, or the real one)",
    )
    parser.add_argument(
        "--expected",
        type=int,
        default=None,
        help="the declared number of tests (default: EXPECTED_TESTS or 37)",
    )
    parser.add_argument(
        "--readme",
        default=None,
        help="README to cross-check (default: <project root>/README.md)",
    )
    parser.add_argument(
        "--print-expected",
        action="store_true",
        help="print the declared number of tests and exit",
    )
    args = parser.parse_args(argv)

    if args.print_expected:
        print(expected_tests())
        return EXIT_OK

    expected = args.expected if args.expected is not None else expected_tests()
    readme = Path(args.readme) if args.readme else project_root() / "README.md"

    if args.test_log:
        path = Path(args.test_log)
        if not path.is_file():
            print(f"error: test log {path} does not exist.", file=sys.stderr)
            return EXIT_ENV
        text = path.read_text(encoding="utf-8", errors="replace")
        moon_exit = args.moon_exit if args.moon_exit is not None else 0
        log_path: Path | None = path
    else:
        text, moon_exit = run_moon_test()
        if args.moon_exit is not None:
            moon_exit = args.moon_exit
        log_path = None

    return check(text, moon_exit, readme, expected, log_path)


if __name__ == "__main__":
    sys.exit(main())
