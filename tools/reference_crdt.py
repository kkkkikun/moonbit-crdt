#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reference_crdt.py — an independent reference implementation of the CRDT
semantics implemented by `moonbit-crdt`.

Why does this file exist?
-------------------------
A unit test can only prove that the implementation does what the test says.
A *differential* test proves something stronger: that the implementation
agrees with a **second, independent implementation** of the same
specification.  If the two disagree, at least one of them is wrong — and the
disagreement is a concrete, reproducible artefact rather than a vague worry.

This file is that second implementation.  It is written in a different
language, with different data structures (Python dicts / lists instead of
MoonBit's `Map` / `Array`), and it was written from the *specification* in the
library documentation rather than by transliterating the MoonBit source.  The
canonical output format is shared, so the two can be compared byte for byte.

It is intentionally dependency-free (standard library only) so that it can run
anywhere the MoonBit toolchain runs.

Operation grammar (identical to the MoonBit side):

    inc   <replica> <delta>                                  gcounter
    pinc  <replica> <delta>                                  pncounter
    ninc  <replica> <delta>                                  pncounter
    add   <replica> <element>                                orset
    rem   <replica> <element>                                orset
    set   <replica> <key> <value> <wall> <counter>           lww
    merge <target> <source>                                  all

Numbers are encoded as letters (a=1 … z=26) so that neither side has to parse
decimal numbers out of text.
"""

from __future__ import annotations

import string

# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

LETTERS = string.ascii_lowercase

# The value table used by the operation grammar.  It must stay in step with
# ``VALUE_TOKENS`` in ``world.mbt`` — the differential harness compares the two
# implementations against each other, so a table mismatch would show up as
# nonsense mismatches rather than as the bug we are looking for.
#
# The letters a..z (1..26) are the historical encoding.  The extra entries
# exist because that alphabet alone cannot express a negative number or a
# number larger than 26, which leaves whole classes of defects invisible to
# the harness (accepted negative increments, counters truncated to 32 bits).
# "]" is 2**31 on purpose: one past the signed 32-bit boundary.
VALUE_TOKENS = {
    "0": 0,
    "a": 1,
    "b": 2,
    "c": 3,
    "d": 4,
    "e": 5,
    "f": 6,
    "g": 7,
    "h": 8,
    "i": 9,
    "j": 10,
    "k": 11,
    "l": 12,
    "m": 13,
    "n": 14,
    "o": 15,
    "p": 16,
    "q": 17,
    "r": 18,
    "s": 19,
    "t": 20,
    "u": 21,
    "v": 22,
    "w": 23,
    "x": 24,
    "y": 25,
    "z": 26,
    "A": 27,
    "B": 28,
    "C": 29,
    "D": 30,
    "E": 31,
    "F": 32,
    "G": 33,
    "H": 34,
    "I": 35,
    "J": 36,
    "K": 37,
    "L": 38,
    "M": 39,
    "N": 40,
    "O": 41,
    "P": 42,
    "Q": 43,
    "R": 44,
    "S": 45,
    "T": 46,
    "U": 47,
    "V": 48,
    "W": 49,
    "X": 50,
    "Y": 51,
    "Z": 52,
    "!": -1,
    "@": -2,
    "[": 2147483647,
    "]": 2147483648,
}


def letter_to_int(token: str) -> int:
    """Decode the value encoding used by the operation grammar."""
    return VALUE_TOKENS.get(token, 0)


def sort_key(text: str) -> bytes:
    """Sort key giving plain lexicographic (UTF-16 code unit) order.

    MoonBit's built-in string comparison is numeric-aware, so the canonical
    order is defined explicitly here as UTF-16 code unit order and implemented
    the same way on the MoonBit side (see `lexical_cmp` in canonical.mbt).
    """
    return text.encode("utf-16-be")


def escape_component(text: str) -> str:
    """Escape the characters that are structural in the canonical format.

    The canonical form is `k=v;k=v` (and the OR-Set adds a `|` separated
    section), so those characters inside a key or a value would make the
    encoding non-injective — two *different* states could render the same
    string and compare equal.  Mirrors `escape_component` in canonical.mbt.
    """
    return (
        text.replace("%", "%25")
        .replace(";", "%3B")
        .replace("=", "%3D")
        .replace("|", "%7C")
    )


def canonical_pairs(pairs: dict) -> str:
    """Render a mapping as `k=v;k=v` with the keys sorted (escaped)."""
    return ";".join(
        f"{escape_component(k)}={escape_component(pairs[k])}"
        for k in sorted(pairs, key=sort_key)
    )


# --------------------------------------------------------------------------
# The CRDTs
# --------------------------------------------------------------------------


class GCounter:
    """Grow-only counter: each replica owns one key, merge takes per-key max."""

    def __init__(self, counts: dict | None = None):
        self.counts = dict(counts or {})

    def get(self, replica: str) -> int:
        return self.counts.get(replica, 0)

    def inc(self, replica: str, delta: int) -> "GCounter":
        # Negative deltas are rejected: the counter is grow-only.
        if delta < 0:
            return GCounter(self.counts)
        counts = dict(self.counts)
        counts[replica] = self.get(replica) + delta
        return GCounter(counts)

    def merge(self, other: "GCounter") -> "GCounter":
        counts = dict(self.counts)
        for key, value in other.counts.items():
            if key not in counts or value > counts[key]:
                counts[key] = value
        return GCounter(counts)

    def value(self) -> int:
        return sum(self.counts.values())

    def canonical(self) -> str:
        return canonical_pairs({k: str(v) for k, v in self.counts.items()})


class PNCounter:
    """Positive/negative counter built from two grow-only counters."""

    def __init__(self, pos: GCounter | None = None, neg: GCounter | None = None):
        self.pos = pos or GCounter()
        self.neg = neg or GCounter()

    def pinc(self, replica: str, delta: int) -> "PNCounter":
        return PNCounter(self.pos.inc(replica, delta), self.neg)

    def ninc(self, replica: str, delta: int) -> "PNCounter":
        return PNCounter(self.pos, self.neg.inc(replica, delta))

    def merge(self, other: "PNCounter") -> "PNCounter":
        return PNCounter(self.pos.merge(other.pos), self.neg.merge(other.neg))

    def value(self) -> int:
        return self.pos.value() - self.neg.value()

    def canonical(self) -> str:
        return f"p={self.pos.canonical()}|n={self.neg.canonical()}"


class ORSet:
    """Observed-remove set, add-wins, using unique dots per addition.

    This implementation is deliberately **not** a transliteration of the
    MoonBit one.  The MoonBit side stores *tombstones* (the removed dots) and
    filters the merged dot set by them.  This side keeps a **per-element
    causal context** — `seen`, every dot ever associated with the element —
    and computes liveness with the ORSWOT / 2P-Set merge rule:

        live = (live_a ∩ live_b) ∪ (live_a \\ seen_b) ∪ (live_b \\ seen_a)

    i.e. a dot survives only if **both** replicas still have it, or if the
    other replica has **never seen it** (and therefore could not have removed
    it).  A dot that the other replica has seen *and* removed stays dead —
    that is the observed-remove contract.

    The two formulations are equivalent, but they are computed differently, so
    a mistake in one of them surfaces as a **differential mismatch** instead
    of being invisible in both.  (The first version of this file copied the
    MoonBit merge rule verbatim, which meant the two sides could not possibly
    disagree — and the differential harness proved nothing about the
    semantics.  It also shared the same bug: a removal was forgotten, so the
    element came back on the next merge.)
    """

    def __init__(self, elems: dict | None = None, counters: dict | None = None,
                 seen: dict | None = None):
        # elems: element -> set of live dots
        # seen:  element -> set of every dot ever seen for it (live ∪ removed)
        self.elems = {k: set(v) for k, v in (elems or {}).items()}
        self.counters = dict(counters or {})
        self.seen = {k: set(v) for k, v in (seen or {}).items()}

    def add(self, replica: str, elem: str) -> "ORSet":
        seq = self.counters.get(replica, 0)
        dot = f"{replica}#{seq}"
        elems = {k: set(v) for k, v in self.elems.items()}
        elems.setdefault(elem, set()).add(dot)
        seen = {k: set(v) for k, v in self.seen.items()}
        seen.setdefault(elem, set()).add(dot)
        counters = dict(self.counters)
        counters[replica] = seq + 1
        return ORSet(elems, counters, seen)

    def remove(self, elem: str) -> "ORSet":
        # Only the dots this replica has *observed* are removed.  They stay in
        # `seen` (the causal context), which is what makes the removal durable:
        # a replica that later merges with a stale copy of this one will not
        # resurrect the element.
        elems = {k: set(v) for k, v in self.elems.items()}
        if elem in elems:
            elems[elem] = set()
        seen = {k: set(v) for k, v in self.seen.items()}
        return ORSet(elems, self.counters, seen)

    def contains(self, elem: str) -> bool:
        return len(self.elems.get(elem, ())) > 0

    def merge(self, other: "ORSet") -> "ORSet":
        elems: dict = {}
        seen: dict = {}
        for elem in set(self.seen) | set(other.seen):
            live_a = self.elems.get(elem, set())
            live_b = other.elems.get(elem, set())
            seen_a = self.seen.get(elem, set())
            seen_b = other.seen.get(elem, set())
            seen[elem] = seen_a | seen_b
            elems[elem] = (
                (live_a & live_b) | (live_a - seen_b) | (live_b - seen_a)
            )
        counters = dict(self.counters)
        for replica, count in other.counters.items():
            if replica not in counters or count > counters[replica]:
                counters[replica] = count
        return ORSet(elems, counters, seen)

    def canonical(self) -> str:
        live = canonical_pairs(
            {k: ",".join(sorted(v, key=sort_key)) for k, v in self.elems.items()}
        )
        dead = canonical_pairs(
            {
                k: ",".join(
                    sorted(self.seen.get(k, set()) - self.elems.get(k, set()), key=sort_key)
                )
                for k in self.seen
                if self.seen.get(k, set()) - self.elems.get(k, set())
            }
        )
        counters = canonical_pairs({k: str(v) for k, v in self.counters.items()})
        return f"{live}|{dead}|{counters}"


class LWWRegister:
    """Last-writer-wins register with a total order on (wall, counter, node)."""

    def __init__(self, entries: dict | None = None):
        # entries: key -> (wall, counter, node, value)
        self.entries = dict(entries or {})

    @staticmethod
    def _greater(a, b) -> bool:
        if a[0] != b[0]:
            return a[0] > b[0]
        if a[1] != b[1]:
            return a[1] > b[1]
        # UTF-16 code unit order — the same order the MoonBit side uses via
        # `lexical_cmp`.  Python's plain `>` would compare by Unicode code
        # point, and MoonBit's built-in `>` is *numeric-aware*, so both would
        # disagree with this definition for ids like "node-2" / "node-10".
        return a[2].encode("utf-16-be") > b[2].encode("utf-16-be")

    def set(self, node: str, key: str, value: str, wall: int, counter: int) -> "LWWRegister":
        entries = dict(self.entries)
        candidate = (wall, counter, node, value)
        if key not in entries or self._greater(candidate, entries[key]):
            entries[key] = candidate
        return LWWRegister(entries)

    def get(self, key: str):
        entry = self.entries.get(key)
        return entry[3] if entry else None

    def merge(self, other: "LWWRegister") -> "LWWRegister":
        entries = dict(self.entries)
        for key, candidate in other.entries.items():
            if key not in entries or self._greater(candidate, entries[key]):
                entries[key] = candidate
        return LWWRegister(entries)

    def canonical(self) -> str:
        return canonical_pairs(
            {k: f"{v[0]}.{v[1]}.{v[2]}={v[3]}" for k, v in self.entries.items()}
        )


# --------------------------------------------------------------------------
# The world model (one value per replica)
# --------------------------------------------------------------------------

_EMPTY = {
    "gcounter": GCounter,
    "pncounter": PNCounter,
    "orset": ORSet,
    "lww": LWWRegister,
}


class World:
    """Holds one CRDT value per replica and applies operations to it."""

    def __init__(self, family: str):
        if family not in _EMPTY:
            raise ValueError(f"unknown family: {family}")
        self.family = family
        self.replicas: dict = {}

    def _get(self, replica: str):
        """Read a replica, creating (and thereby publishing) it if unknown."""
        if replica not in self.replicas:
            self.replicas[replica] = _EMPTY[self.family]()
        return self.replicas[replica]

    def _peek(self, replica: str):
        """Read a replica without publishing it.

        `merge <target> <source>` reads the source but must not make it
        visible in the canonical output: a replica appears in the output iff
        some operation *wrote to* it or *merged into* it.  (This rule was
        added after the differential harness found the two implementations
        disagreeing on exactly this point.)
        """
        if replica in self.replicas:
            return self.replicas[replica]
        return _EMPTY[self.family]()

    def apply(self, op: list) -> "World":
        if not op:
            return self
        cmd = op[0]
        if self.family == "gcounter":
            if cmd == "inc" and len(op) >= 3:
                self.replicas[op[1]] = self._get(op[1]).inc(op[1], letter_to_int(op[2]))
            elif cmd == "merge" and len(op) >= 3:
                self.replicas[op[1]] = self._get(op[1]).merge(self._peek(op[2]))
        elif self.family == "pncounter":
            if cmd == "pinc" and len(op) >= 3:
                self.replicas[op[1]] = self._get(op[1]).pinc(op[1], letter_to_int(op[2]))
            elif cmd == "ninc" and len(op) >= 3:
                self.replicas[op[1]] = self._get(op[1]).ninc(op[1], letter_to_int(op[2]))
            elif cmd == "merge" and len(op) >= 3:
                self.replicas[op[1]] = self._get(op[1]).merge(self._peek(op[2]))
        elif self.family == "orset":
            if cmd == "add" and len(op) >= 3:
                self.replicas[op[1]] = self._get(op[1]).add(op[1], op[2])
            elif cmd == "rem" and len(op) >= 3:
                self.replicas[op[1]] = self._get(op[1]).remove(op[2])
            elif cmd == "merge" and len(op) >= 3:
                self.replicas[op[1]] = self._get(op[1]).merge(self._peek(op[2]))
        elif self.family == "lww":
            if cmd == "set" and len(op) >= 6:
                self.replicas[op[1]] = self._get(op[1]).set(
                    op[1], op[2], op[3], letter_to_int(op[4]), letter_to_int(op[5])
                )
            elif cmd == "merge" and len(op) >= 3:
                self.replicas[op[1]] = self._get(op[1]).merge(self._peek(op[2]))
        return self

    def canonical(self) -> str:
        return canonical_pairs(
            {name: state.canonical() for name, state in self.replicas.items()}
        )


def run_case(family: str, name: str, ops: list) -> str:
    """Replay one case and return the canonical line the MoonBit side prints."""
    world = World(family)
    for op in ops:
        world.apply(op)
    return f"{name}|{world.canonical()}"


if __name__ == "__main__":  # small self-check
    demo = run_case("gcounter", "demo", [["inc", "A", "a"], ["inc", "B", "b"], ["merge", "A", "B"]])
    print(demo)
