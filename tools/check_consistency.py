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
import hashlib
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
# Round eight (m4): the old pattern matched *any* "…: <number>" line, so a
# line such as "18,000 cases, 0 mismatches" could be read as a coverage
# figure.  A coverage row always starts with the family tag ("[lww]",
# "[orset]", "[values]"), so the tag is now required.
COVERAGE_RE = re.compile(
    r"^\[[a-z]+\]\s+[^:\n]*:\s*(\d+(?: / \d+)?)(?:\s+cases)?\s*$", re.M
)

# The fingerprint every evidence file carries in its header.
# ``environment.txt`` spells it "code-fp     : <hash>" (a key/value line,
# not a "# code fingerprint:" comment), so both spellings are accepted.
FP_RE = re.compile(r"(?:code fingerprint|code-fp)\s*:\s*([0-9a-f]{64})")

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
    # Round eight (m5): the comment above already claimed environment.txt was
    # included, but the tuple did not list it — so one of the twelve evidence
    # files was never checked for freshness.
    "environment.txt",
)

# The README's test-suite breakdown.  It must add up to the declared count.
# NOTE: the breakdown itself has **no independent evidence** (the test log
# does not classify the tests), so only the sum is checkable — this check
# catches "15 + 10 + 13" but cannot catch "15 + 10 + 12".  The README says so
# explicitly, in §4.
#
# Round eight (m4): the old pattern accepted *any* three "number word" triples,
# so it also matched the prose phrase "18,000 cases, 0 mismatches" (it latched
# onto "1,000 cases, 0 mismatches") and reported a bogus breakdown of
# [1, 0, 0].  The category names are now an explicit whitelist and the
# numbers must be separated from them by whitespace — a thousands separator
# cannot satisfy that.
BREAKDOWN_CATEGORY = r"(?:unit|property|regression|tests?)"
# 第十二轮 m-6：类别名可以写成两词（`unit tests` / `property tests` /
# `regression tests`），只认单词会让这类分解**整条看不见**（第十二轮复评的
# 变异体 F 就是这一类）。
# NOTE: the whole phrase is wrapped in a non-capturing group: an alternation
# that is *not* grouped binds to the whole pattern, so `A|B` spliced into a
# longer regex silently turns the rest of the pattern into the second branch.
BREAKDOWN_CATEGORY_PHRASE = (
    r"((?:unit|property|regression)(?:\s+tests?)?|tests?)"
)
# 第十二轮 m-5/m-6：分解的**分隔符**与**类别名的写法**都不再决定判据能否命中。
# 分隔符集合：`,` `+` `;` `、` `，` `and`。
BREAKDOWN_SEP = r"(?:,|\+|;|、|，|\band\b)"
# NOTE: every line below ends with an explicit "+".  Relying on Python's
# implicit adjacent-string concatenation across a line that ends in a
# string *expression* silently drops the following lines — that is how the
# first version of this pattern ended up matching only part of a triple
# (and how a negative test of the gate passed for the wrong reason).
BREAKDOWN_RE = re.compile(
    r"(?<![\d,])(\d+)\s+" + BREAKDOWN_CATEGORY_PHRASE + r"\b\s*" + BREAKDOWN_SEP + r"\s*"
    + r"(\d+)\s+" + BREAKDOWN_CATEGORY_PHRASE + r"\b\s*" + BREAKDOWN_SEP + r"\s*"
    + r"(\d+)\s+" + BREAKDOWN_CATEGORY_PHRASE + r"\b"
)
# Round nine (n1): the whitelist above means a **renamed** category makes
# BREAKDOWN_RE match nothing at all — the loop body then never runs and the
# check is **silently disabled** (it is not a failure, it is a no-op).
# Fix: **fail closed**.  A generic triple detector finds "N word, N word,
# N word" whatever the words are; if such a triple exists but the whitelist
# pattern matched none, the breakdown's categories are outside the whitelist
# and the sum is **not verified** — that must be reported, not ignored.
# The generic pattern keeps the same "no thousands separator" guard, so the
# prose "18,000 cases, 0 mismatches" still cannot trigger it.
# 第十一轮 m-8：分解的**句式是可改的**，判据不能依赖句式。
# 原文的分解是 `**37 tests in total** (16 unit, 10 property, 11 regression)`；
# 把括号内的分隔符改成 `+` / `;` / `and`，原判据就再也匹配不到 → 分解和完全不被校验。
# 因此：**锚定**在「N tests in total (...)」这句话上，从锚点里取三类数目再求和。
ANCHOR_BREAKDOWN_RE = re.compile(
    r"(?P<total>\d+)\s+tests?\s+in\s+total[\*\s:：]*\((?P<inner>[^)]*)\)",
    re.IGNORECASE,
)
# 锚点括号内：三个「数 + 类别名」（类别名允许拉丁字母或中文）
ANCHOR_ITEM_RE = re.compile(r"(\d+)\s*([A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\-]*)")

GENERIC_CATEGORY_PHRASE = (
    r"([A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff-]*"
    r"(?:\s+[A-Za-z\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff-]*)?)"
)
GENERIC_BREAKDOWN_RE = re.compile(
    # 第十一轮 m-8：分隔符放宽到 `,` `+` `;` `and` `、` `，`（原来只认逗号），
    # 类别名允许拉丁字母或中文 —— 否则「改句式」就能让三元组整条漏检。
    # 第十二轮 m-6：类别名放宽到**最多两个词**（`unit tests` 这种写法），
    # 否则多词类别名的分解对两个探测都不可见。
    r"(?<![\d,])(\d+)\s+" + GENERIC_CATEGORY_PHRASE + r"\b\s*"
    + BREAKDOWN_SEP + r"\s*"
    r"(\d+)\s+" + GENERIC_CATEGORY_PHRASE + r"\b\s*"
    + BREAKDOWN_SEP + r"\s*"
    r"(\d+)\s+" + GENERIC_CATEGORY_PHRASE + r"\b"
)
# 第十二轮 m-5：通用探测会把**任何**「三个数 + 三个词」都当成分解，
# 于是一句普通散文（例如 "We ran 5 benchmarks, 3 suites and 2 oracles during
# development."）被报成「分解用错了类别名」—— 这是**误报**，不是缺陷检出。
# 修法：只有当这个三元组**落在声明了测试数的句子里**时，才按
# 「分解的类别名越界」报错（fail closed）；纯散文里的三元组不阻断。
TEST_COUNT_DECL_RE = re.compile(r"\b\d+\s+tests?\b", re.IGNORECASE)


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


def strip_code(text: str) -> str:
    """Return the text with every code block and every HTML comment removed.

    Round seven of the review showed that a fenced *example* can satisfy a
    naive "the README mentions N tests" scan, so a declaration inside a code
    block must not count as one.

    Round eight (m2) showed that stripping only ``` fences leaves three
    bypasses open, each of them measured to exit 0:

      * a ``~~~`` fence (CommonMark allows it as well as ```);
      * an **indented** code block (four spaces or a tab);
      * an **HTML comment** (``<!-- … -->``), which Markdown renders as
        nothing and which therefore must not count as prose either.

    All three are removed here.

    An **odd** number of fences means the document itself is malformed.  That
    is reported rather than papered over: dropping everything from the
    unpaired fence to the end of the file would silently hide the whole
    remainder of the README from every check.
    """
    for marker in ("```", "~~~"):
        if text.count(marker) % 2 != 0:
            raise ValueError(
                f"the document has an odd number of {marker} fences "
                f"({text.count(marker)}) — a code block is not closed, so the "
                "rest of the file cannot be read reliably")

    # HTML comments (possibly spanning several lines).
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    # Fenced blocks, both flavours.  The fence may be indented.
    text = re.sub(r"^[ \t]*(`{3,}|~{3,}).*?^\1[ \t]*$", "", text,
                  flags=re.S | re.M)

    # Indented code blocks.
    #
    # Only a *standalone* run of indented lines counts as one: in Markdown an
    # indented code block must not interrupt a paragraph and it ends at the
    # first blank line.  A list item's continuation lines are indented too,
    # but they follow the list marker rather than a blank line — stripping
    # them would silently delete real prose from the text every check reads.
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        is_indented = line.startswith("    ") or line.startswith("\t")
        if not (is_indented and (not out or not out[-1].strip())):
            out.append(line)
            i += 1
            continue
        # a standalone indented block starts here — drop it entirely
        while i < n and (lines[i].startswith("    ") or lines[i].startswith("\t")
                         or not lines[i].strip()):
            i += 1
    return "\n".join(out)


# Backwards-compatible alias: the old name is used by other tooling.
strip_fenced = strip_code


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


def check_evidence_fingerprint(root: Path, evidence_dir: Path | None = None) -> list[str]:
    """The recorded evidence must have been produced by *this* source tree.

    Round seven of the review: the fingerprint was written into every log but
    never **checked**, so editing one line of ``world.mbt`` left every
    evidence file stale while all gates stayed green.
    """
    problems: list[str] = []
    evidence = evidence_dir if evidence_dir is not None else (root / "evidence")
    if not evidence.is_dir():
        return [f"{evidence} directory is missing — the recorded evidence cannot be checked."]

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


def check_evidence_manifest(evidence_dir: Path) -> list[str]:
    """``evidence/MANIFEST.sha256`` must match the files it lists.

    Round eight (m6): the README-vs-evidence cross-check can be defeated by
    changing the log **and** the README together — the gate then sees a
    perfectly self-consistent pair of wrong numbers.  What it can still catch
    is a change to a log that is not backed by the manifest.

    So every evidence file is listed in ``evidence/MANIFEST.sha256`` with its
    SHA-256, and the gate recomputes those digests.  Editing a log without
    updating the manifest is a failure.

    The limit is stated plainly rather than hidden: somebody who edits the
    log, the manifest *and* the README consistently can still get through.
    Nothing that compares numbers can rule that out — only re-running the
    harness can, and the benchmark figures are load-dependent (see §4.7).
    """
    problems: list[str] = []
    manifest = evidence_dir / "MANIFEST.sha256"
    if not manifest.is_file():
        return [
            f"{manifest.name} is missing — the evidence files are not protected "
            "against a log being edited without the manifest being updated"
        ]

    listed: dict[str, str] = {}
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            problems.append(f"{manifest.name}: cannot parse the line {raw!r}")
            continue
        digest, name = parts[0].strip(), parts[1].strip().lstrip("*")
        listed[name] = digest

    for name in EVIDENCE_FILES:
        if name not in listed:
            problems.append(f"{manifest.name} does not list evidence/{name}")
            continue
        path = evidence_dir / name
        if not path.is_file():
            continue  # already reported by the freshness check
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != listed[name]:
            problems.append(
                f"evidence/{name} does not match {manifest.name} "
                f"(manifest {listed[name][:12]}…, actual {actual[:12]}…) — "
                "the log was changed without updating the manifest"
            )

    for name in listed:
        if name not in EVIDENCE_FILES:
            problems.append(f"{manifest.name} lists an unknown file: {name}")

    return problems


def triple_signature(match: re.Match) -> tuple[str, ...]:
    """The **content** of a "N word, N word, N word" triple.

    Both the whitelist pattern and the generic pattern number their groups
    the same way (1/3/5 = the counts, 2/4/6 = the category names), so the
    signature of the same text is identical in both — that is what makes
    "is this generic triple covered by a whitelist triple?" decidable.
    """
    return tuple(match.group(i) for i in range(1, 7))


def sentence_around(text: str, start: int, end: int) -> str:
    """The sentence of ``text`` that contains the span ``[start, end)``.

    Sentences end at ``.`` / ``!`` / ``?``.  The span is deliberately taken
    on the raw text (not on a stripped copy) so that the offsets of a regex
    match stay valid.
    """
    left = -1
    for ch in ".!?":
        pos = text.rfind(ch, 0, start)
        if pos > left:
            left = pos
    right = len(text)
    for ch in ".!?":
        pos = text.find(ch, end)
        if pos != -1 and pos < right:
            right = pos
    return text[left + 1:right]


def check_readme_numbers(readme_text: str, root: Path,
                         evidence_dir: Path | None = None,
                         skip_bench_cross_check: bool = False) -> list[str]:
    """The README's benchmark and coverage figures must match the evidence.

    Round seven of the review: changing a benchmark value in the README
    (e.g. "99.99 µs") or a coverage figure (e.g. "15 / 10 / 12") left every
    gate green, because nothing compared the prose with the logs.
    """
    problems: list[str] = []
    prose = strip_code(readme_text)
    evidence = evidence_dir if evidence_dir is not None else (root / "evidence")

    # --- benchmarks: the two sets must be equal, not merely overlapping ---
    #
    # Round eight (M1): a benchmark value depends on the machine's load, so
    # **re-running the evidence necessarily produces a different number**.
    # Comparing the freshly written benchmark against the README would make
    # the evidence script fail on a perfectly healthy tree — which is what
    # happened.  The comparison therefore belongs to the *clean-tree* check
    # (CI, on the committed evidence/), not to the regeneration run; the
    # regeneration run skips it via --skip-bench-cross-check and asks the
    # operator to sync the README instead.
    bench_path = evidence / "bench.log"
    if skip_bench_cross_check:
        pass
    elif bench_path.is_file():
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
    elif not skip_bench_cross_check:
        problems.append("evidence/bench.log is missing — benchmarks cannot be checked")

    # --- coverage figures: every figure in the log must appear in the prose ---
    cov_path = evidence / "coverage_report.log"
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

    # --- 第十一轮 m-8：锚定解析（判据不再依赖「逗号句式」）---
    #
    # 逃逸原理：把分解改写成 `16 unit + 10 property + 11 regression` 之类，
    # 原 BREAKDOWN_RE / GENERIC_BREAKDOWN_RE 都匹配不到 → 分解和**根本没被校验**；
    # 再在别处放一个合法的白名单三元组做诱饵，`matched` 非空，fail-closed 分支也不触发。
    # 现在：从「N tests in total (...)」锚点取三类数目求和，句式怎么改都拦得住。
    anchors = list(ANCHOR_BREAKDOWN_RE.finditer(prose))
    if not anchors:
        problems.append(
            "the README no longer contains the 'N tests in total (...)' breakdown "
            "anchor - the declared count can no longer be cross-checked against "
            "the three-way sum (fail closed)"
        )
    for a in anchors:
        total = int(a.group("total"))
        items = ANCHOR_ITEM_RE.findall(a.group("inner"))
        if len(items) != 3:
            problems.append(
                "the README's breakdown anchor "
                f"{a.group(0)[:70]!r} does not list exactly three counts"
            )
            continue
        nums = [int(n) for n, _ in items]
        if sum(nums) != total:
            problems.append(
                f"the README's test breakdown {nums} sums to {sum(nums)}, "
                f"but the same sentence declares {total} tests"
            )
        if total != expected_tests():
            problems.append(
                f"the README's breakdown anchor declares {total} tests, "
                f"but the project declares {expected_tests()} tests"
            )

    # --- the suite breakdown must add up to the declared count ---
    # Round eight (m3): the old code took only the **first** match, so a
    # correct triple placed early in the document masked a wrong one later on.
    # Every triple is checked now.
    matched = list(BREAKDOWN_RE.finditer(prose))
    for m in matched:
        # 第十二轮：类别名现在**也是捕获组**，所以三个数是第 1/3/5 组。
        nums = [int(m.group(i)) for i in (1, 3, 5)]   # the three counts
        if sum(nums) != expected_tests():
            problems.append(
                f"the README's test breakdown {nums} sums to {sum(nums)}, "
                f"but the project declares {expected_tests()} tests"
            )
    # Round nine (n1): **fail closed**.  If the whitelist pattern matched
    # nothing but a generic "N word, N word, N word" triple exists, the
    # breakdown's category names are outside the whitelist and the sum was
    # never checked — renaming a category must not silently disable the gate.
    #
    # Round ten (n3): the n1 fix above could still be **bypassed with a decoy**.
    # Its fail-closed branch only fires when the whitelist matched *nothing* —
    # so renaming the real breakdown's categories while planting one legal
    # whitelist triple elsewhere kept `matched` non-empty, the branch never
    # ran, and the real breakdown's sum went **completely unchecked**
    # (review mutants N1-e and N1-e2 both exited 0).
    # Fix: judge **every generic triple on its own**.  Each generic match must
    # be covered by a whitelist match with the **same content** (the same three
    # counts and the same three category names — see `triple_signature`).
    # A generic triple that the whitelist does not cover is a triple whose
    # categories are outside the whitelist → its sum is not verified → that is
    # reported.  A decoy therefore cannot hide the real breakdown any more:
    # the real one is itself a generic triple, and it is judged on its own
    # merits.
    generic = list(GENERIC_BREAKDOWN_RE.finditer(prose))
    # 第十二轮 m-6：覆盖关系按**三元组的内容**（三个数 + 三个类别名）判定，
    # 不再按字符区间判定 —— 两个模式的类别名写法一旦不同（单词 vs 两词），
    # 区间就会错位，于是合法的分解会被误报成「类别名越界」。
    covered = {triple_signature(m) for m in matched}
    uncovered = [m for m in generic if triple_signature(m) not in covered]
    # 第十二轮 m-5：只有**落在声明了测试数的句子里**的三元组才算
    # 「分解」；纯散文里的三元组（"5 benchmarks, 3 suites and 2 oracles"）
    # 不阻断 —— 那不是缺陷，是误报。
    suspicious = [
        m for m in uncovered
        if TEST_COUNT_DECL_RE.search(sentence_around(prose, m.start(), m.end()))
    ]
    if not matched:
        # No whitelist triple at all: the breakdown is gone entirely.
        problems.append(
            "the README no longer contains a test-suite breakdown — the "
            "declared count can no longer be cross-checked against a sum"
        )
    elif suspicious:
        shown = " | ".join(repr(m.group(0)) for m in suspicious[:3])
        problems.append(
            "the README's test breakdown uses category names outside the "
            f"whitelist ({BREAKDOWN_CATEGORY}): found {shown} — "
            "the breakdown's sum is therefore NOT verified; either restore the "
            "documented category names or extend the whitelist deliberately"
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
    evidence_dir: Path | None = None,
    skip_bench_cross_check: bool = False,
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
        prose = strip_code(readme_text)
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
        ev_dir = evidence_dir if evidence_dir is not None else (root / "evidence")
        extra_problems = (
            check_evidence_fingerprint(root, ev_dir)
            + check_evidence_manifest(ev_dir)
            + check_readme_numbers(readme_text, root, ev_dir, skip_bench_cross_check)
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
        "--evidence-dir",
        default=None,
        help=(
            "directory holding the evidence to check (default: <project root>/evidence). "
            "The evidence script passes its own output directory so that the freshness "
            "check looks at the files it has just written, not at the previous run's."
        ),
    )
    parser.add_argument(
        "--skip-bench-cross-check",
        action="store_true",
        help=(
            "do not require the README's benchmark figures to equal the recorded ones. "
            "A benchmark value depends on the machine's load, so a re-run necessarily "
            "produces a different number; the regeneration run skips this comparison "
            "and asks the operator to sync the README instead."
        ),
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
        evidence_dir=Path(args.evidence_dir) if args.evidence_dir else None,
        skip_bench_cross_check=args.skip_bench_cross_check,
    )


if __name__ == "__main__":
    sys.exit(main())
