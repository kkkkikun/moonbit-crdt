#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fault_injection.py — prove that the differential harness can actually fail.

Why this file exists
--------------------
"18,000 cases, 0 mismatches" is only evidence if the harness would have
reported a mismatch had the implementation been wrong.  A harness that is
silently green — because it never compares anything, or because both sides
share the same bug — proves nothing at all.

This script performs **fault injection**: it takes a pristine copy of the
project, injects a *known* semantic defect into the MoonBit implementation,
and then runs the differential harness against it.  The harness **must** fail,
report the mismatching case, and shrink it to a minimal reproduction.

The defects injected here are exactly the two bugs the first independent
review found in this project:

* ``S1`` — OR-Set removal is not durable (the element comes back on merge).
* ``S2`` — LWW tie-break uses the host language's numeric-aware string
  comparison, so two implementations elect *different* winners.

Usage
-----
    python3 tools/fault_injection.py --project <path-to-a-pristine-copy>
                                     [--work <scratch-dir>]

The script never touches the project it is given: it copies the tree into the
scratch directory first and patches the copy.  Exit code 0 means *every*
injected fault was detected; non-zero means the harness missed one.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

# --------------------------------------------------------------------------
# The injected faults: (name, file, original snippet, faulty snippet, family)
# --------------------------------------------------------------------------

FAULTS = [
    (
        "S1-orset-resurrection",
        "orset.mbt",
        "          if !dead.contains(dot) {",
        "          if true {",
        "orset",
    ),
    (
        "S2-lww-numeric-aware-tiebreak",
        "lwwregister.mbt",
        "  lexical_cmp(a.2, b.2) > 0",
        "  a.2 > b.2",
        "lww",
    ),
]


def run(cmd: list, cwd: str) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def inject(project: str, fault) -> bool:
    """Write the faulty variant of one source file. Returns True on success."""
    _, fname, original, faulty, _ = fault
    path = os.path.join(project, fname)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if original not in text:
        return False
    text = text.replace(original, faulty, 1)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True,
                    help="pristine copy of the project (will NOT be modified)")
    ap.add_argument("--work", default="/tmp/c05_fault_injection",
                    help="scratch directory for the mutated copies")
    ap.add_argument("--cases", type=int, default=800)
    ap.add_argument("--seed", type=int, default=20261124)
    args = ap.parse_args()

    source = os.path.abspath(args.project)
    work = os.path.abspath(args.work)
    os.makedirs(work, exist_ok=True)

    results = []
    all_detected = True

    for fault in FAULTS:
        name, _, _, _, family = fault
        target = os.path.join(work, name)
        if os.path.exists(target):
            shutil.rmtree(target)
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        # Build artifacts of the source copy must not leak into the mutant.
        for junk in ("_build", "target", ".moon"):
            junk_path = os.path.join(target, junk)
            if os.path.isdir(junk_path):
                shutil.rmtree(junk_path)

        if not inject(target, fault):
            print(f"[SKIP] {name}: could not find the snippet to replace "
                  f"in {fault[1]} — the source moved, this script needs updating")
            all_detected = False
            results.append((name, "SKIP", "snippet not found"))
            continue

        code, out = run(
            [
                sys.executable, "tools/fuzz_diff.py",
                "--cases", str(args.cases),
                "--seed", str(args.seed),
                "--families", family,
                "--moon-cmd", "moon run cmd/replay --",
            ],
            cwd=target,
        )
        detected = code != 0 and "[FAIL]" in out
        summary = ""
        for line in out.splitlines():
            if line.startswith("[summary]"):
                summary = line.strip()
        minimal = ""
        for line in out.splitlines():
            if line.strip().startswith("minimal:"):
                minimal = line.strip()
                break
        print(f"[{'DETECTED' if detected else 'MISSED'}] {name}")
        print(f"    exit code : {code}")
        if summary:
            print(f"    summary   : {summary}")
        if minimal:
            print(f"    minimal   : {minimal}")
        if not detected:
            all_detected = False
        results.append((name, "DETECTED" if detected else "MISSED", summary))

    print()
    print(f"[verdict] {sum(1 for r in results if r[1] == 'DETECTED')}"
          f"/{len(results)} injected faults detected by the differential harness")
    return 0 if all_detected else 1


if __name__ == "__main__":
    raise SystemExit(main())
