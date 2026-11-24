#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fuzz_diff.py — cross-implementation differential testing harness.

What it does
------------
1. Generates random operation streams (seeded → reproducible) for each CRDT
   family.
2. Replays them through **two independent implementations**:
   * the MoonBit implementation (`moon run cmd/replay`), and
   * the Python reference implementation (`tools/reference_crdt.py`).
3. Compares the canonical output of both, byte for byte.
4. When they disagree, **shrinks** the failing case down to a minimal
   reproduction (delta debugging) and prints it, so the bug can be fixed and
   the case can be stored as a regression test.

Why it matters
--------------
Property tests inside one implementation cannot catch a mistake that is
*shared* by the property and the implementation.  A differential test against
an implementation written from the specification can.  The harness is also the
project's regression corpus generator: every case it produces can be frozen
into `tests/regression/`.

Usage
-----
    python3 tools/fuzz_diff.py --cases 2000 --seed 20261124
    python3 tools/fuzz_diff.py --cases 200 --seed 7 --moon-cmd "moon run cmd/replay --"

Options
-------
    --cases N        number of random cases per family (default 2000)
    --seed S         random seed (default 20261124)
    --batch N        cases per MoonBit invocation (default 400)
    --families LIST  comma separated subset of gcounter,pncounter,orset,lww
    --moon-cmd CMD   command prefix used to run the MoonBit replay engine
    --keep-going     report every failing case instead of stopping at the first
"""

from __future__ import annotations

import argparse
import os
import random
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reference_crdt import LETTERS, run_case  # noqa: E402

# The replica ids deliberately include **multi-character** ones: the LWW
# tie-break compares node ids as plain code-unit strings, and a single-letter
# alphabet ("A", "B", "C") can never expose a numeric-aware comparison —
# that bug only shows up with ids like "node-2" vs "node-10".
REPLICAS = ["A", "B", "C", "node-2", "node-10"]
# Ids whose order depends on the *host language's* collation.  MoonBit's
# built-in string comparison is numeric-aware ("node-10" > "node-2"), while
# the canonical order used by this library is plain code-unit order
# ("node-10" < "node-2").  A write conflict decided by one of these ids is
# therefore the **only** way the differential harness can detect a tie-break
# that accidentally falls back to the built-in comparison — so the generator
# produces such conflicts on purpose instead of hoping for them.
NUMERIC_REPLICAS = ["node-2", "node-10"]
ELEMENTS = ["x", "y", "z"]
KEYS = ["k1", "k2"]
VALUES = ["v1", "v2", "v3"]

# Probability that a generated LWW stream contains a *deliberate* write
# conflict: two replicas write the same key with the same (wall, counter),
# so the winner can only be decided by comparing the node ids.
TIE_PROBABILITY = 0.4


def tie_pair(rng: random.Random) -> list:
    """Two concurrent writes that only the node id can decide.

    Both replicas write the *same* key with the *same* ``(wall, counter)``.
    The merge therefore has to fall back to comparing the node ids — the one
    place where two implementations of the same specification are known to
    disagree if the tie-break uses the host language's collation.
    """
    left, right = rng.sample(NUMERIC_REPLICAS, 2)
    key = rng.choice(KEYS)
    wall = rng.choice(LETTERS)
    counter = rng.choice(LETTERS)
    return [
        ["set", left, key, rng.choice(VALUES), wall, counter],
        ["set", right, key, rng.choice(VALUES), wall, counter],
    ]


def node_decided_conflicts(ops: list) -> int:
    """Count write conflicts in an LWW stream that only the node id decides."""
    written: dict[str, dict[str, tuple[str, str]]] = {}
    for op in ops:
        if op[0] == "set":
            _, replica, key, _value, wall, counter = op
            written.setdefault(replica, {})[key] = (wall, counter)
    stamps: dict[tuple[str, str, str], set[str]] = {}
    for replica, keys in written.items():
        for key, (wall, counter) in keys.items():
            stamps.setdefault((key, wall, counter), set()).add(replica)
    return sum(1 for nodes in stamps.values() if len(nodes) > 1)


def random_ops(rng: random.Random, family: str, length: int) -> list:
    """Build a random operation stream for the given family."""
    ops = []
    for _ in range(length):
        if family == "gcounter":
            if rng.random() < 0.3:
                ops.append(["merge", rng.choice(REPLICAS), rng.choice(REPLICAS)])
            else:
                ops.append(["inc", rng.choice(REPLICAS), rng.choice(LETTERS)])
        elif family == "pncounter":
            roll = rng.random()
            if roll < 0.25:
                ops.append(["merge", rng.choice(REPLICAS), rng.choice(REPLICAS)])
            elif roll < 0.6:
                ops.append(["pinc", rng.choice(REPLICAS), rng.choice(LETTERS)])
            else:
                ops.append(["ninc", rng.choice(REPLICAS), rng.choice(LETTERS)])
        elif family == "orset":
            roll = rng.random()
            if roll < 0.25:
                ops.append(["merge", rng.choice(REPLICAS), rng.choice(REPLICAS)])
            elif roll < 0.65:
                ops.append(["add", rng.choice(REPLICAS), rng.choice(ELEMENTS)])
            else:
                ops.append(["rem", rng.choice(REPLICAS), rng.choice(ELEMENTS)])
        elif family == "lww":
            if rng.random() < 0.25:
                ops.append(["merge", rng.choice(REPLICAS), rng.choice(REPLICAS)])
            else:
                ops.append([
                    "set",
                    rng.choice(REPLICAS),
                    rng.choice(KEYS),
                    rng.choice(VALUES),
                    rng.choice(LETTERS),
                    rng.choice(LETTERS),
                ])
            # Deliberate node-decided conflicts: without these the tie-break
            # path is almost never reached (measured: 13 of 2500 cases) and the
            # harness would report "0 mismatches" without having tested it.
            if rng.random() < TIE_PROBABILITY:
                ops.extend(tie_pair(rng))
    return ops


def encode_case(family: str, name: str, ops: list) -> str:
    """Encode a case exactly the way the MoonBit replay engine expects."""
    body = ";".join(" ".join(str(tok) for tok in op) for op in ops)
    return f"{family}|{name}|{body}"


def run_moonbit(moon_cmd: str, cases: list) -> list:
    """Run the MoonBit replay engine over a batch of cases."""
    cmd = shlex.split(moon_cmd) + cases
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"MoonBit replay engine failed (exit {proc.returncode}):\n"
            f"{proc.stderr.strip()[:2000]}"
        )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if len(lines) != len(cases):
        raise RuntimeError(
            f"expected {len(cases)} output lines, got {len(lines)}\n"
            f"stdout head: {proc.stdout[:500]}"
        )
    return lines


def shrink_case(family: str, ops: list, moon_cmd: str) -> list:
    """Delta-debugging shrink: remove operations while the mismatch survives."""
    current = list(ops)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(current):
            candidate = current[:i] + current[i + 1:]
            name = "shrink"
            encoded = encode_case(family, name, candidate)
            try:
                moon_out = run_moonbit(moon_cmd, [encoded])[0]
            except RuntimeError:
                i += 1
                continue
            ref_out = run_case(family, name, candidate)
            if moon_out != ref_out:
                current = candidate
                changed = True
            else:
                i += 1
    return current


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=2000, help="cases per family")
    ap.add_argument("--seed", type=int, default=20261124)
    ap.add_argument("--batch", type=int, default=400, help="cases per MoonBit run")
    ap.add_argument("--families", default="gcounter,pncounter,orset,lww")
    ap.add_argument("--moon-cmd", default="moon run cmd/replay --")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--max-ops", type=int, default=12)
    args = ap.parse_args()

    families = [f.strip() for f in args.families.split(",") if f.strip()]
    rng = random.Random(args.seed)
    failures = 0
    total = 0

    for family in families:
        cases = []
        expected = []
        for i in range(args.cases):
            ops = random_ops(rng, family, rng.randint(1, args.max_ops))
            name = f"{family}-{i}"
            cases.append(encode_case(family, name, ops))
            expected.append(run_case(family, name, ops))
            total += 1

        mismatches = []
        for start in range(0, len(cases), args.batch):
            chunk = cases[start:start + args.batch]
            chunk_expected = expected[start:start + args.batch]
            moon_out = run_moonbit(args.moon_cmd, chunk)
            for idx, (m, e) in enumerate(zip(moon_out, chunk_expected)):
                if m != e:
                    mismatches.append((start + idx, m, e))
            if mismatches and not args.keep_going:
                break

        if not mismatches:
            print(f"[ok] {family}: {len(cases)} cases — MoonBit and the reference agree")
            continue

        failures += len(mismatches)
        print(f"[FAIL] {family}: {len(mismatches)} mismatching case(s)")
        for idx, moon_line, ref_line in mismatches[:5]:
            ops = [op.split(" ") for op in cases[idx].split("|", 2)[2].split(";")]
            minimal = shrink_case(family, ops, args.moon_cmd)
            print("  case   :", cases[idx])
            print("  moonbit:", moon_line)
            print("  python :", ref_line)
            print("  minimal:", encode_case(family, "shrink", minimal))
            print()

    print(f"[summary] {total} cases compared, {failures} mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
