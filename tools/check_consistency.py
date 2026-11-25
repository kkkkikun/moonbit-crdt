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

Round seven of the independent review found that (3) could be satisfied by a
**fenced example block** instead of a real declaration: rewriting the one real
sentence to "38 cases" removed the only prose declaration, and the sample
output inside a ```` ``` ```` block still supplied "37 tests", so the gate
answered "README agrees".  The gate now therefore

    * ignores fenced code blocks when looking for the declaration,
    * requires at least one declaration **in the prose**, and
    * additionally cross-checks the README's benchmark and coverage numbers
      against the recorded evidence, and the evidence's code fingerprint
      against the current sources (a stale evidence set is a failure, not a
      detail).

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

# --- round seven: the fingerprint and the evidence cross-checks -----------
# A benchmark line in `evidence/bench.log` and in the README:
#   "  57.37 µs ±   2.47 µs"   /   "57.37 µs ± 2.47 µs"
BENCH_RE = re.compile(r"([\d.]+)\s*(µs|ms)\s*±\s*([\d.]+)\s*(µs|ms)")

# A coverage figure in `evidence/coverage_report.log`:
#   "[lww]    node-decided conflicts   : 1956 / 2500 cases"
#   "[orset]  durable removals         : 5275"
# (the trailing " cases" is optional — three of the seven lines end in a
# bare number)
COVERAGE_RE = re.compile(r"^.*:\s*(\d+(?: / \d+)?)(?:\s+cases)?\s*$", re.M)

# The fingerprint every evidence file carries in its header.
FP_RE = re.compile(r"code fingerprint:\s*([0-9a-f]{64})")

# The evidence files that must carry a fingerprint and must agree with the
# current sources.  ``environment.txt`` is included: it records the identity
# of the tree the run was made from.
EVIDENCE_FILES = (
    "bench.log",
    "coverage_report.log",
    "demo.log",
    "fault_injection.log",
    "fuzz_diff.seed20261124.log",
    "fuzz_diff.seed42.log",
    "fuzz_diff.seed777.log",
    "fuzz_diff.seed31337.log",
    "fuzz_summary.txt",
    "moon_check.log",
    "moon_test.log",
)

# The README's test-suite breakdown.  It must add up to the declared count.
# NOTE: the breakdown itself has **no independent evidence** (the test log
# does not classify the tests), so only the sum is checkable — this check
# catches "15 + 10 + 13" but cannot catch "15 + 10 + 12".  The README says so
# explicitly, in §4.
BREAKDOWN_RE = re.compile(r"(\d+)\s*(\w+)\s*,\s*(\d+)\s*(\w+)\s*,\s*(\d+)\s*(\w+)")


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


def strip_fenced(text: str) -> str:
    """Return the text with every fenced code block removed.

    Round seven of the review showed that a fenced *example* can satisfy a
    naive "the README mentions N tests" scan, so a declaration inside a code
    block must not count as one.

    An **odd** number of fences means the document itself is malformed.  That
    is reported rather than papered over: dropping everything from the
    unpaired fence to the end of the file would silently hide the whole
    remainder of the README from every check.
    """
    if text.count("```") % 2 != 0:
        raise ValueError(
            f"the document has an odd number of ``` fences ({text.count('```')}) "
            "— a code block is not closed, so the rest of the file cannot be "
            "read reliably")
    return re.sub(r"```.*?```", "", text, flags=re.S)


def read_text_safe(path: Path) -> tuple[str | None, str | None]:
    """Read a text file.  Returns (text, error_message).

    Round seven: a README that is not valid UTF-8 used to raise an uncaught
    ``UnicodeDecodeError`` and dump a traceback — an environment problem
    dressed up as a consistency failure.  It now produces a readable
    diagnostic.
    """
    try:
        return path.read_text(encoding="utf-8"), None
    except FileNotFoundError:
        return None, f"{path} does not exist"
    except UnicodeDecodeError as exc:
        return None, (
            f"{path} is not valid UTF-8 ({exc.reason} at byte {exc.start}). "
            "The README must be UTF-8 text for the counts to be checkable."
        )
    except OSError as exc:
        return None, f"{path} could not be read: {exc}"


def current_fingerprint(root: Path) -> str | None:
    """The code fingerprint of the current tree, or None if it cannot be computed."""
    script = root / "tools" / "provenance.py"
    if not script.is_file():
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--quiet", "--root", str(root)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    token = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
    return token if re.fullmatch(r"[0-9a-f]{64}", token) else None


def check_evidence_fingerprint(root: Path) -> list[str]:
    """The recorded evidence must have been produced by *this* source tree.

    Round seven of the review: the fingerprint was written into every log but
    never **checked**, so editing one line of ``world.mbt`` left every
    evidence file stale while all gates stayed green.
    """
    problems: list[str] = []
    evidence = root / "evidence"
    if not evidence.is_dir():
        return ["evidence/ directory is missing — the recorded evidence cannot be checked."]

    current = current_fingerprint(root)
    if current is None:
        return ["could not compute the current code fingerprint (tools/provenance.py failed)"]

    for name in EVIDENCE_FILES:
        path = evidence / name
        if not path.is_file():
            problems.append(f"evidence/{name} is missing")
            continue
        text, err = read_text_safe(path)
        if text is None:
            problems.append(f"evidence/{name}: {err}")
            continue
        found = FP_RE.findall(text)
        if not found:
            problems.append(f"evidence/{name} carries no code fingerprint")
            continue
        stale = sorted({f for f in found if f != current})
        if stale:
            problems.append(
                f"evidence/{name} was produced by a different source tree "
                f"(recorded {stale[0][:12]}…, current {current[:12]}…) — "
                "the evidence is stale, re-run tools/regenerate_evidence.sh"
            )
    return problems


def check_readme_numbers(readme_text: str, root: Path) -> list[str]:
    """The README's benchmark and coverage figures must match the evidence.

    Round seven of the review: changing a benchmark value in the README
    (e.g. "99.99 µs") or a coverage figure (e.g. "15 / 10 / 12") left every
    gate green, because nothing compared the prose with the logs.
    """
    problems: list[str] = []
    prose = strip_fenced(readme_text)

    # --- benchmarks: the two sets must be equal, not merely overlapping ---
    bench_path = root / "evidence" / "bench.log"
    if bench_path.is_file():
        bench_text, err = read_text_safe(bench_path)
        if bench_text is None:
            problems.append(f"evidence/bench.log: {err}")
        else:
            def norms(text: str) -> set[str]:
                return {
                    f"{a} {u} ± {b} {v}"
                    for a, u, b, v in BENCH_RE.findall(text)
                }

            from_bench = norms(bench_text)
            from_readme = norms(prose)
            if from_bench and from_readme != from_bench:
                problems.append(
                    "the README's benchmark numbers differ from evidence/bench.log: "
                    f"README {sorted(from_readme)} vs evidence {sorted(from_bench)}"
                )
    else:
        problems.append("evidence/bench.log is missing — benchmarks cannot be checked")

    # --- coverage figures: every figure in the log must appear in the prose ---
    cov_path = root / "evidence" / "coverage_report.log"
    if cov_path.is_file():
        cov_text, err = read_text_safe(cov_path)
        if cov_text is None:
            problems.append(f"evidence/coverage_report.log: {err}")
        else:
            figures = [f for f in COVERAGE_RE.findall(cov_text) if f]
            missing = [f for f in figures if f not in prose]
            if missing:
                problems.append(
                    "the README does not mention these coverage figures from "
                    f"evidence/coverage_report.log: {missing}"
                )
            # ... and the prose must not invent a "/ 2500" figure of its own.
            prose_frac = set(re.findall(r"\b(\d+) / 2500\b", prose))
            log_frac = {f.split(" / ")[0] for f in figures if " / " in f}
            extra = sorted(prose_frac - log_frac)
            if extra:
                problems.append(
                    f"the README mentions coverage fractions {extra} that are not in "
                    "evidence/coverage_report.log"
                )
    else:
        problems.append(
            "evidence/coverage_report.log is missing — coverage figures cannot be checked"
        )

    # --- the suite breakdown must add up to the declared count ---
    m = BREAKDOWN_RE.search(prose)
    if m:
        nums = [int(m.group(i)) for i in (1, 3, 5)]
        if sum(nums) != expected_tests():
            problems.append(
                f"the README's test breakdown {nums} sums to {sum(nums)}, "
                f"but the project declares {expected_tests()} tests"
            )

    return problems


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
    skip_evidence_checks: bool = False,
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

    readme_text, readme_err = read_text_safe(readme)
    if readme_text is None:
        print(f"error: cannot read {readme}: {readme_err}", file=sys.stderr)
        print(
            "       The README is part of the contract this gate checks, so it has\n"
            "       to be readable UTF-8 text.",
            file=sys.stderr,
        )
        return EXIT_ENV

    # Round seven: a declaration inside a fenced example block does not count.
    try:
        prose = strip_fenced(readme_text)
    except ValueError as exc:
        print(f"error: README drift: {readme}: {exc}", file=sys.stderr)
        return EXIT_MISMATCH
    counts = sorted({int(n) for n in README_COUNT_RE.findall(prose)})
    if not counts:
        print(
            f"error: README drift: {readme} declares no test count in its prose "
            "(no '<N> tests' phrase outside a fenced code block).",
            file=sys.stderr,
        )
        print(
            "       A fenced example is not a declaration: the gate used to accept\n"
            "       one, which let the real declaration be rewritten freely.",
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

    # --- round seven: the evidence must match this tree, and the README's
    # --- numbers must match the evidence. ---------------------------------
    # ``--skip-evidence-checks`` is used by the evidence script's *first*
    # pass: at that moment the logs on disk are still the previous run's, so
    # comparing them with the current sources would fail by construction.
    # The script runs the full check again at the very end.
    if not skip_evidence_checks:
        root = readme.parent
        extra_problems = check_evidence_fingerprint(root) + check_readme_numbers(
            readme_text, root
        )
        if extra_problems:
            print("error: the recorded evidence and the README disagree:", file=sys.stderr)
            for p in extra_problems:
                print(f"  - {p}", file=sys.stderr)
            print(
                "       Re-run tools/regenerate_evidence.sh after changing the "
                "sources, and keep the README's numbers in step with it.",
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
    parser.add_argument(
        "--skip-evidence-checks",
        action="store_true",
        help=(
            "only check the suite, the declared count and the README's prose "
            "declaration; skip the evidence-freshness and README-vs-evidence "
            "cross-checks (used by the evidence script's first pass, when the "
            "logs on disk are still the previous run's)"
        ),
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

    return check(
        text,
        moon_exit,
        readme,
        expected,
        log_path,
        skip_evidence_checks=args.skip_evidence_checks,
    )


if __name__ == "__main__":
    sys.exit(main())
