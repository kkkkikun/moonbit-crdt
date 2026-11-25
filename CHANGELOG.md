# Changelog

All notable changes to `moonbit-crdt` are recorded here.

The project is **not published to the MoonBit registry yet** (see `README.md`
§2), so there are no release tags. The headings below name the **states of
`main`** that the independent reviews examined, with the commit they were
made at — the commit history, the issues and the pull requests carry the rest
of the update record.

## Unreleased — the sixth-review fixes (2026-11-25)

Fixes for the ten **m**-level findings of the sixth independent review
(`qa/independent_review_round6.md` in the project workspace). The one **S**
finding (public history still contains commits signed with a real name) is an
outbound action and is tracked outside this file.

### Verification chain

* **The evidence script can no longer die before it prints its diagnosis.**
  `moon test`'s output is captured, the exit code is kept, and the assertion
  block is always reached — so a genuinely failing suite now produces
  `error: 'moon test': total=37 passed=36 failed=1` instead of a bare
  non-zero exit. A missing README now produces a "README drift" diagnostic
  instead of `grep: README.md: No such file or directory`.
* **One test-count gate, shared by the script and CI.**
  `tools/check_consistency.py` is the single entry point that checks the
  number of tests the suite ran, the number the project declares, and the
  number the README declares, against each other. `tools/regenerate_evidence.sh`
  and `.github/workflows/ci.yml` both call it, so the evidence run and CI can
  no longer assert different numbers — and CI now cross-checks the README too,
  which it did not do before.
* **The `moon test` premise in the documentation is now the measured fact.**
  Deleting `moon.pkg` makes `moon test` **and** `moon check` exit **255**;
  only deleting the *test file* makes `moon test` exit 0 having found
  nothing. The previous wording claimed the opposite for the `moon.pkg`
  case. `README.md` §4.7 now tabulates all three measured behaviours.

### Evidence

* `evidence/fuzz_diff.long.log` — a stale pre-fix log with no fingerprint —
  was **removed** from the current `evidence/`; byte-identical copies remain
  in both archive directories (SHA-256 verified before the removal).
* `evidence/fuzz_summary.txt` now carries the code fingerprint header like
  every other file the script writes.
* `evidence/environment.txt` now records the commit of the checkout the tree
  was copied from when it runs inside one, and says plainly that it is *not* a
  checkout otherwise — pointing at the code fingerprint as the authoritative
  identity of the tree. No SHA is ever invented.
* The archive is now **complete**: all thirteen files that `evidence/` held at
  `3b66d8c` are in `evidence/archive/pre-round4-20261124/`, byte for byte
  (SHA-256 compared against `git ls-tree 3b66d8c evidence/`).

### Documentation

* The three places that described the value table as "`a` = 1 … `z` = 26" now
  describe the table that is actually implemented (`README.md` §6,
  `world.mbt`, `tools/reference_crdt.py`).
* `README.md` §8 lists the real layout, including `tools/provenance.py`,
  `tools/check_consistency.py`, `evidence/archive/` and this file — and no
  longer claims that the script regenerates *every* raw log in `evidence/`.
* `README.md` §4.5 now **discloses** that the coverage report's
  `resurrectable` metric is an element-level proxy: a dot-level simulation on
  the same traffic counts about 4084 against the element-level 4360 the tool
  reports — a gap of roughly 7 %.
* Both archive READMEs no longer claim that the script "writes every file in
  `evidence/`" and that it is "the same script CI runs".

## The fifth-review fixes (2026-11-24, `4b11da6`)

* **Evidence is bound to the code that produced it.** `tools/provenance.py`
  computes a fingerprint over every source file that can influence a recorded
  run and writes it into the header of every log the script produces.
* **The coverage report and the differential harness share one traffic
  source** (`fuzz_diff.generate_cases()`), so the reported coverage describes
  the cases that were actually compared.
* **The `resurrectable` metric implements its own written definition** — the
  earlier version over-counted by more than four times (343 against a true
  count of 11 on the same traffic).
* **The README's benchmark numbers are the measured ones**, copied verbatim
  from `evidence/bench.log`, with a note that the absolute values move with
  the machine's load.
* **A new regression test pins the merge publish semantics**:
  `regression: a merge does not publish a replica that never existed`. The
  earlier test could not see the defect it was meant to pin, because merging
  a replica that *already exists* changes nothing; injecting the mutation
  again makes the new test fail.
* The fingerprint's coverage was widened to include
  `tools/regenerate_evidence.sh` and `cmd/main/main.mbt` (18 → 20 files).

## The fourth-review fixes (2026-11-24, `6aa5fec` / `7481303`)

* **The value table grew from 27 to 57 tokens** — the letters `a` … `z`, the
  `0` token, the uppercase letters `A` … `Z`, and the symbol tokens `!` = -1,
  `@` = -2, `[` = 2^31 - 1, `]` = 2^31. The old alphabet could not express a
  negative number or a value above 26, which left whole classes of width and
  sign defects invisible to the harness.
* **The OR-Set removal became durable**: removed dots are kept as tombstones
  and merged like any other part of the state.
* **The LWW tie-break is plain lexicographic on both sides**, not the host
  language's numeric-aware comparison, and the canonical encoding was made
  **injective** (keys and values are percent-escaped).

## The first public state (2026-11-24)

* `792ea15` — the four CRDT types (GCounter, PNCounter, OR-Set, LWW-Register)
  and the canonical rendering.
* `568d148` — unit, property and regression tests, plus the benchmarks.
* `740bf0d`, `c92685e` — the runnable demo, the replay engine, and the
  cross-implementation differential harness with an independent Python
  reference.
* `3dab50b`, `9d60219`, `c0508af` — the README and the evidence logs;
  `.github/workflows/ci.yml` added.
