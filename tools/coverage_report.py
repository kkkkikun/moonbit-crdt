#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""coverage_report.py — how much of the interesting behaviour does the
differential harness actually reach?

Why this file exists
--------------------
A differential harness that never generates the situation it claims to test is
worse than no harness: it reports "0 mismatches" and the reader concludes the
property was verified.  The fourth independent review made exactly that point
about the *previous* version of this file — it generated **its own** case
stream instead of measuring the stream the harness actually compares, and its
"resurrectable removals" counter did not implement the definition in its own
docstring (it reported 343 where the true count under the same stream is 77).

So this version:

* measures **the same cases the harness compares** — both call
  ``fuzz_diff.generate_cases()`` with the same seed, case count and family
  order (the families share one random stream, so the order matters);
* implements the definition its own docstring gives, and says which definition
  it implements;
* reports the *reachability* of the value ranges the operation grammar can
  express, because two whole classes of defects (accepted negative
  increments, counters truncated to 32 bits) were invisible to the harness
  while the alphabet could only produce small positive numbers.

Usage
-----
    python3 tools/coverage_report.py --cases 2500 --seed 20261124
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fuzz_diff import REPLICAS, generate_cases  # noqa: E402
from reference_crdt import VALUE_TOKENS  # noqa: E402
from provenance import fingerprint as code_fingerprint  # noqa: E402

NEGATIVE_TOKENS = {t for t, v in VALUE_TOKENS.items() if v < 0}
LARGE_TOKENS = {t for t, v in VALUE_TOKENS.items() if v > 26}


def lww_coverage(cases: list) -> tuple[int, int]:
    """(node-decided conflicts, counter-arbitrated conflicts), counted in cases.

    *node-decided* — two replicas wrote the same key with the same
    ``(wall, counter)``: only the node id can decide the winner.
    *counter-arbitrated* — two replicas wrote the same key with the same
    ``wall`` but different ``counter``: the counter decides, before the node
    id is even looked at.  This is the middle layer of the total order
    ``(wall, counter, node)``.
    """
    node_cases = 0
    counter_cases = 0
    for ops in cases:
        written: dict[str, dict[str, tuple[str, str]]] = {}
        for op in ops:
            if op[0] == "set":
                _, replica, key, _value, wall, counter = op
                written.setdefault(replica, {})[key] = (wall, counter)
        by_full: dict[tuple[str, str, str], set[str]] = {}
        by_wall: dict[tuple[str, str], set[str]] = {}
        for replica, keys in written.items():
            for key, (wall, counter) in keys.items():
                by_full.setdefault((key, wall, counter), set()).add(replica)
                by_wall.setdefault((key, wall), set()).add(replica)
        if any(len(nodes) > 1 for nodes in by_full.values()):
            node_cases += 1
        if any(len(nodes) > 1 for nodes in by_wall.values()):
            counter_cases += 1
    return node_cases, counter_cases


def orset_coverage(cases: list) -> tuple[int, int, int]:
    """(durable removals, resurrectable removals, removals of unknown elements).

    Definitions used here — and the ones the docstring used to *claim*:

    *durable removal*
        a ``rem`` of an element the removing replica had actually observed
        (i.e. it held the element at that moment).

    *resurrectable removal*
        a durable removal that is **followed** — later in the same operation
        stream — by a merge which brings the element back from a replica that
        still holds it.  That is the situation in which "remove then merge"
        actually resurrects the element, and therefore the situation the
        removal-durability property is about.

        The previous version counted any removal whose element was held by
        *some* other replica at *some* point in the stream, without requiring
        the merge to happen after the removal.  That over-counts by a factor
        of about four.
    """
    durable = 0
    resurrectable = 0
    unknown = 0
    for ops in cases:
        holds: dict[str, set[str]] = {}
        removals: list[tuple[int, str, str]] = []
        merges: list[tuple[int, str, str, frozenset, frozenset]] = []
        for idx, op in enumerate(ops):
            if op[0] == "add":
                _, replica, elem = op
                holds.setdefault(replica, set()).add(elem)
            elif op[0] == "rem":
                _, replica, elem = op
                if elem in holds.get(replica, ()):
                    holds[replica].discard(elem)
                    removals.append((idx, replica, elem))
                    durable += 1
                else:
                    unknown += 1
            elif op[0] == "merge":
                target, source = op[1], op[2]
                target_set = frozenset(holds.get(target, ()))
                source_set = frozenset(holds.get(source, ()))
                holds.setdefault(target, set()).update(holds.get(source, ()))
                merges.append((idx, target, source, target_set, source_set))
        for idx, replica, elem in removals:
            for jdx, target, source, target_set, source_set in merges:
                if jdx <= idx:
                    continue
                # The remover must be the *target* of the later merge: that is
                # the case where the stale holder's copy is merged back into
                # the replica that removed the element.  If the remover is the
                # *source*, the element it removed is gone from it as well and
                # nothing is resurrected.
                if target == replica and elem in source_set:
                    resurrectable += 1
                    break
    return durable, resurrectable, unknown


def value_reachability(cases: list) -> tuple[int, int]:
    """(cases containing a negative value, cases containing a value > 26)."""
    negative = 0
    large = 0
    for ops in cases:
        toks = {op[-1] for op in ops if op[0] in ("inc", "pinc", "ninc")}
        toks |= {op[4] for op in ops if op[0] == "set"}
        toks |= {op[5] for op in ops if op[0] == "set"}
        if toks & NEGATIVE_TOKENS:
            negative += 1
        if toks & LARGE_TOKENS:
            large += 1
    return negative, large


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=2500)
    ap.add_argument("--seed", type=int, default=20261124)
    ap.add_argument("--max-ops", type=int, default=12)
    args = ap.parse_args()

    # Bind this report to the tree state that produced it (tools/provenance.py).
    _digest, _ = code_fingerprint(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(f"# code fingerprint: {_digest}")

    # **Same stream as the harness**: same seed, same case count, same family
    # order.  See fuzz_diff.generate_cases().
    streams = generate_cases(args.seed, args.cases, args.max_ops)

    lww_cases = streams["lww"]
    orset_cases = streams["orset"]
    gcounter_cases = streams["gcounter"]

    node_cases, counter_cases = lww_coverage(lww_cases)
    durable, resurrectable, unknown = orset_coverage(orset_cases)
    neg_cases, large_cases = value_reachability(gcounter_cases)

    print("== differential coverage report ==")
    print(f"seed={args.seed} cases/family={args.cases} max-ops={args.max_ops}")
    print("(the stream below is the one the harness compares — both call "
          "fuzz_diff.generate_cases())")
    print()
    print(f"[lww]    node-decided conflicts   : {node_cases} / {len(lww_cases)} cases")
    print(f"[lww]    counter-arbitrated cases  : {counter_cases} / {len(lww_cases)} cases")
    print(f"[orset]  durable removals         : {durable}")
    print(f"[orset]  resurrectable removals   : {resurrectable}")
    print(f"[orset]  removals of unknown elem : {unknown}")
    print(f"[values] cases with a negative    : {neg_cases} / {len(gcounter_cases)} cases")
    print(f"[values] cases with a value > 26  : {large_cases} / {len(gcounter_cases)} cases")
    print()

    # A coverage report that only prints a warning is a report nobody reads.
    # If the generated traffic never reaches the branch it claims to test,
    # the command has to fail — otherwise "0 mismatches" can be green for
    # lack of coverage instead of because the implementation is correct.
    gaps = []
    if node_cases == 0:
        gaps.append(
            "the LWW traffic never reaches a node-decided conflict — "
            "the tie-break is NOT covered by the differential harness")
    if counter_cases == 0:
        gaps.append(
            "the LWW traffic never reaches a counter-arbitrated conflict — "
            "the (wall, counter, node) total order is only half covered")
    if durable == 0 or resurrectable == 0:
        gaps.append(
            "the OR-Set traffic never reaches a resurrectable removal — "
            "removal durability is NOT covered by the differential harness")
    if neg_cases == 0:
        gaps.append(
            "the generated traffic never contains a negative value — "
            "a defect that accepts negative increments would NOT be caught")
    if large_cases == 0:
        gaps.append(
            "the generated traffic never contains a value above 26 — "
            "a defect that truncates a counter to 32 bits would NOT be caught")

    if gaps:
        print("FAIL: coverage gap")
        for gap in gaps:
            print(f"  - {gap}")
        print()
        print("A '0 mismatches' result under this coverage proves nothing.")
        return 1

    print("[ok] the generated traffic reaches every branch the harness claims to test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
