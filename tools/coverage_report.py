#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""coverage_report.py — how much of the interesting behaviour does the fuzzer
actually reach?

A differential harness that never generates the situation it claims to test is
worse than no harness: it reports "0 mismatches" and the reader concludes the
property was verified.

Two coverage questions matter for this project:

``tie-break``
    Does the generated LWW traffic ever contain a write conflict that is
    decided *only* by the node id?  That is the exact case the first review
    found broken (S2): two replicas write the same key with the same
    ``(wall, counter)``, so the winner can only be chosen by comparing the
    node ids.

``removal``
    Does the generated OR-Set traffic ever contain a removal that is followed
    by a merge with a replica that still holds the removed dots?  That is the
    exact case the first review found broken (S1): the element comes back.

The script answers both questions by *replaying* the generated operation
streams with an instrumented reference implementation and counting how many
cases hit the interesting branch.

Usage
-----
    python3 tools/coverage_report.py --cases 2500 --seed 20261124
"""

from __future__ import annotations

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fuzz_diff import REPLICAS, random_ops  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=2500)
    ap.add_argument("--seed", type=int, default=20261124)
    ap.add_argument("--max-ops", type=int, default=12)
    args = ap.parse_args()

    rng = random.Random(args.seed)

    # ---- LWW: node-decided conflicts -------------------------------------
    lww_cases = 0
    lww_ties = 0
    for _ in range(args.cases):
        ops = random_ops(rng, "lww", rng.randint(1, args.max_ops))
        lww_cases += 1
        written: dict[str, dict[str, tuple[str, str]]] = {}
        for op in ops:
            if op[0] == "set":
                _, replica, key, _value, wall, counter = op
                written.setdefault(replica, {})[key] = (wall, counter)
        stamps: dict[tuple[str, str, str], set[str]] = {}
        for replica, keys in written.items():
            for key, (wall, counter) in keys.items():
                stamps.setdefault((key, wall, counter), set()).add(replica)
        if any(len(nodes) > 1 for nodes in stamps.values()):
            lww_ties += 1

    # ---- OR-Set: removal followed by a merge with a stale holder ---------
    orset_cases = 0
    orset_removals = 0
    orset_resurrectable = 0
    for _ in range(args.cases):
        ops = random_ops(rng, "orset", rng.randint(1, args.max_ops))
        orset_cases += 1
        # Track, per replica, the elements it has *observed* (i.e. that it
        # could remove) and whether it removed them.
        observed: dict[str, set[str]] = {}
        removed: dict[str, set[str]] = {}
        for op in ops:
            if op[0] == "add":
                _, replica, elem = op
                observed.setdefault(replica, set()).add(elem)
            elif op[0] == "merge":
                target, source = op[1], op[2]
                if source in observed:
                    observed.setdefault(target, set()).update(observed[source])
            elif op[0] == "rem":
                _, replica, elem = op
                if elem in observed.get(replica, set()):
                    removed.setdefault(replica, set()).add(elem)
                    orset_removals += 1
        # A removal is "resurrectable" if some *other* replica still holds the
        # element and could merge it back in.
        for replica, elems in removed.items():
            for elem in elems:
                for other, seen in observed.items():
                    if other != replica and elem in seen:
                        orset_resurrectable += 1
                        break

    print("== differential coverage report ==")
    print(f"seed={args.seed} cases/family={args.cases} max_ops={args.max_ops}")
    print()
    print(f"[lww]   node-decided conflicts : {lww_ties} / {lww_cases} cases")
    print(f"[orset] durable removals       : {orset_removals} removals observed")
    print(f"[orset] resurrectable removals : {orset_resurrectable}")
    print()
    if lww_ties == 0:
        print("WARNING: the LWW traffic never reaches a node-decided conflict —")
        print("         the tie-break is NOT covered by the differential harness.")
    if orset_removals == 0 or orset_resurrectable == 0:
        print("WARNING: the OR-Set traffic never reaches a resurrectable removal —")
        print("         removal durability is NOT covered by the differential harness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
