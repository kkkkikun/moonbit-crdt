#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""provenance.py — compute a code fingerprint that evidence logs can bind to.

Why
---
An evidence log that only records *numbers* cannot prove *which* code produced
those numbers.  The fourth independent review made this concrete: after the
value table grew and the generator changed, the regenerated fuzz logs came out
**byte-identical** to the previous ones (the logs record counts, not cases),
so the log itself carried no evidence that the new code had been exercised.

This module fixes that by hashing every source file that can influence a
recorded run and folding the hashes into one fingerprint:

    python3 tools/provenance.py            # print the fingerprint + the file list
    python3 tools/provenance.py --quiet    # print only the fingerprint

The fingerprint covers both implementations and the test suite:

* the MoonBit side   — `*.mbt` sources, `cmd/replay/*`, `moon.mod`
* the reference side — `tools/*.py` (including this file and the harness)
* the test suite     — `crdt_test.mbt`, `crdt_bench_test.mbt`

Because the list includes `tools/provenance.py` itself, changing this file
changes the fingerprint — the fingerprint cannot silently go stale.

The fingerprint is written into the header of every evidence log, so a log can
be bound to a tree state with:

    python3 tools/provenance.py --quiet
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# Files and directories that take part in a recorded run.
#
# The list is **enumerated explicitly** on purpose.  A broad glob such as
# `**/moon.pkg` is not safe here: `moon` populates `.mooncakes/` with the
# downloaded dependency packages on its first run, and those packages carry
# their own `moon.pkg` — so the fingerprint would silently change depending on
# whether the dependencies had been fetched yet.  A fingerprint that changes
# without a source change is worthless as evidence.
GLOBS = (
    "*.mbt",
    "moon.mod",
    # `moon.pkg` is **source**, not build output: it declares the package's
    # imports (including the test-only dependencies) and therefore decides
    # whether `moon test` finds the suite at all.  It must be hashed, and it
    # must never be excluded from a tree copy.
    "moon.pkg",
    "cmd/main/moon.pkg",
    "cmd/replay/moon.pkg",
    "cmd/replay/*.mbt",
    "tools/*.py",
)

# Directories that must never contribute (build output, caches, vendored data).
EXCLUDE_DIRS = {
    "__pycache__",
    ".git",
    "_build",
    "target",
    "node_modules",
    ".pytest_cache",
    # MoonBit's dependency cache — populated by `moon` itself, not by us.
    ".mooncakes",
    ".moonagent",
    ".moon",
}


def _collect(root: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in GLOBS:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            if path not in seen:
                seen.add(path)
                found.append(path)
    return sorted(found, key=lambda p: str(p.relative_to(root)))


def file_hashes(root: Path) -> dict[str, str]:
    """Map relative path -> sha256 hex digest for every participating file."""
    root = Path(root)
    out: dict[str, str] = {}
    for path in _collect(root):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out[str(path.relative_to(root))] = digest
    return out


def fingerprint(root: Path) -> tuple[str, dict[str, str]]:
    """Return (fingerprint, per-file hashes).

    The fingerprint is the sha256 of the sorted ``"<sha256>  <relpath>\\n"``
    listing, so it changes if *any* participating file changes — and only
    then.
    """
    hashes = file_hashes(root)
    listing = "".join(f"{h}  {name}\n" for name, h in sorted(hashes.items()))
    return hashlib.sha256(listing.encode("utf-8")).hexdigest(), hashes


def default_root() -> Path:
    return Path(__file__).resolve().parent.parent


# Every collected file must live under one of these prefixes.  A file outside
# them means the glob set has drifted (e.g. someone widened `**/moon.pkg`
# again) and the fingerprint would stop being reproducible.
ALLOWED_PREFIXES = ("cmd/", "tools/")
ALLOWED_ROOT_FILES = ("moon.mod", "moon.pkg")


def selftest(root: Path) -> int:
    """Check that the fingerprint is reproducible and that nothing sneaks in.

    1. Computing it twice gives the same digest (idempotent).
    2. No collected file lives in a dependency cache or build directory.
    3. Every collected file is under an allowed prefix / allowed root file.
    """
    digest_a, hashes_a = fingerprint(root)
    digest_b, hashes_b = fingerprint(root)

    failures: list[str] = []

    if digest_a != digest_b:
        failures.append("fingerprint is not stable across two computations")
    if hashes_a != hashes_b:
        failures.append("per-file hashes differ between two computations")

    for name in sorted(hashes_a):
        parts = Path(name).parts
        if any(p in EXCLUDE_DIRS for p in parts):
            failures.append(f"{name}: file comes from an excluded directory")
        if name in ALLOWED_ROOT_FILES:
            continue
        if name.endswith(".mbt") and len(parts) == 1:
            continue
        if any(name.startswith(p) for p in ALLOWED_PREFIXES):
            continue
        failures.append(f"{name}: file is outside the allowed set")

    if not hashes_a:
        failures.append("no files were hashed — the glob set matches nothing")

    if failures:
        print("[FAIL] provenance selftest")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"[ok] provenance selftest: {len(hashes_a)} files, fingerprint {digest_a}")
    print("     - stable across two computations")
    print("     - nothing from a dependency cache or build directory")
    print("     - every file is inside the allowed set")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=None, help="project root (default: the parent of tools/)")
    parser.add_argument("--quiet", action="store_true", help="print only the fingerprint")
    parser.add_argument("--selftest", action="store_true",
                        help="check that the fingerprint is reproducible and collects nothing forbidden")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root else default_root()

    if args.selftest:
        return selftest(root)

    digest, hashes = fingerprint(root)

    if args.quiet:
        print(digest)
        return 0

    print(f"# code fingerprint: {digest}")
    print(f"# files hashed    : {len(hashes)}")
    for name, h in sorted(hashes.items()):
        print(f"{h}  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
