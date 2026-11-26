# Changelog

All notable changes to `moonbit-crdt` are recorded here.

The project is **not published to the MoonBit registry yet** (see `README.md`
§2), so there are no release tags. The headings below name the **states of
`main`** that the independent reviews examined, with the commit they were
made at — the commit history, the issues and the pull requests carry the rest
of the update record.

## Unreleased — the eleventh- and twelfth-review fixes (2026-11-26)

Fixes for the findings of the **eleventh** and **twelfth** independent
reviews (`qa/independent_review_round11.md` and
`qa/independent_review_round12.md` in the project workspace). The one **S**
finding — the public history still contains commits signed with a real name —
is an outbound action and is tracked outside this file.

### The breakdown guard no longer depends on how the sentence is written (m-8)

Round eleven found that the guard which cross-checks the README's
`16 unit, 10 property, 11 regression` breakdown against the declared test
count could be **switched off by rewriting the sentence**: with the
parentheses changed to `16 unit + 10 property + 12 regression` (or `;`, or
`and`) neither the whitelist pattern nor the generic detector matched it, so
the sum of the breakdown was never verified at all — and a legal triple
planted elsewhere kept the fail-closed branch quiet.

The guard now **anchors** on the sentence that declares the count
(`N tests in total (...)`), takes the three numbers out of the anchor and
adds them up, whatever the separators are. If the anchor is missing or does
not list exactly three counts, the guard **fails closed**.

### The guard accepts every way of spelling the breakdown, and stops
### mistaking prose for a breakdown (m-5, m-6)

The whitelist probe now accepts `,` `+` `;` `and` `、` `，` as separators and
`unit tests` / `property tests` / `regression tests` as category names, so a
*second*, contradicting breakdown written in another style is checked as well.

The generic probe used to report **any** three numbers followed by three words
as a broken breakdown, which turned ordinary prose — "We ran 5 benchmarks, 3
suites and 2 oracles during development." — into a false positive. A triple
whose category names are outside the whitelist is now reported only when it
sits in a sentence that declares a test count.

### The negative regression can finally tell "fixed" from "not fixed" (m-8 / M-2)

`tools/consistency_selftest.py` runs the guard over mutated copies of the
README and requires every mutation to be caught. Its decoy is now a **legal**
triple (12 unit, 14 property, 11 regression — sum 37), so a mutation can only
be reported by the rule under test, and the mutations that change the
sentence's shape have to be reported by the **anchor** rule specifically.
Copied onto a tree without that rule the selftest **fails** (exit 1) — the
previous version passed on a vulnerable tree as well and therefore proved
nothing. CI runs it on every push.

The evidence was regenerated on the build server after these changes
(`tools/regenerate_evidence.sh`, exit 0), so the recorded fingerprints match
the current tree again. Benchmark figures are load-dependent and differ per
run — that is stated in `README.md` §4.7.

## Unreleased — the ninth- and tenth-review fixes (2026-11-25)

Fixes for the **n1** finding of the ninth independent review and the **n3**
finding of the tenth independent review (`qa/independent_review_round9.md` and
`qa/independent_review_round10.md` in the project workspace). The one **S**
finding — the public history still contains commits signed with a real name —
is an outbound action and is tracked outside this file.

### The test-breakdown guard can no longer be switched off by renaming a category (n1, n3)

The guard that cross-checks the README's `16 unit, 10 property, 11 regression`
breakdown against the declared test count used to **skip silently** when the
category names were not in its whitelist: the whitelist pattern matched
nothing, the loop body never ran, and the breakdown's sum was never verified
at all. Round nine changed it to **fail closed** — a generic
`N word, N word, N word` detector reports the breakdown as unverified when the
whitelist does not match.

Round ten found that this fix could still be **bypassed with a decoy**: the
fail-closed branch only fired when the whitelist matched *nothing*, so renaming
the real breakdown's categories while planting one legal whitelist triple
elsewhere kept the branch from running, and the real breakdown's sum went
completely unchecked.

The gate now judges **every generic triple on its own**: each one must be
covered by a whitelist match at the same position, or its sum counts as
unverified. A decoy can no longer hide the real breakdown. Verified on the
build server: renaming a category, renaming it together with a decoy, and
renaming it with a wrong sum are all rejected (exit 3); inserting a decoy
alone, keeping a correct breakdown and the prose "18,000 cases, 0 mismatches"
are all accepted (exit 0).

The evidence was regenerated on the build server after this change
(`tools/regenerate_evidence.sh`, exit 0), so the recorded fingerprints and the
README's benchmark figures match the current tree again. Benchmark figures are
load-dependent and differ per run — that is stated in `README.md` §4.7.

## Unreleased — the eighth-review fixes (2026-11-25)

Fixes for the **1 M + 8 m** findings of the eighth independent review
(`qa/independent_review_round8.md` in the project workspace). The one **S**
finding — the public history still contains commits signed with a real name —
is an outbound action and is tracked outside this file.

### The evidence script no longer fails on a healthy tree (M1)

The seventh review added a *second* consistency pass at the end of
`tools/regenerate_evidence.sh`, and that pass had two defects that made the
script **exit 3 on a perfectly healthy tree**:

* it checked `<repo>/evidence/` — the *previous* run's logs — instead of the
  `$OUT` directory it had just written;
* it required the README's benchmark figures to equal the freshly recorded
  ones. A benchmark value depends on the machine's load, so re-running the
  evidence **necessarily** produces a different number. Comparing them was
  comparing a fresh measurement with a frozen one.

The comparison now belongs where it can succeed — the clean-tree check (CI,
running against the committed `evidence/`) — while the regeneration run checks
the thing it is actually responsible for: *were these logs produced by the
current sources?* `check_consistency.py` gained `--evidence-dir` (which
directory to check) and `--skip-bench-cross-check` (skip the load-dependent
comparison); the script passes both and then prints the new benchmark line so
the README can be synced.

### The gate can no longer be walked around (m2, m3, m4, m5, m6)

* **m2** — a declaration inside a `~~~` fence, an indented code block or an
  HTML comment still satisfied the "the README declares N tests" check. All
  three are now stripped, and an unpaired fence of either flavour is reported
  instead of silently swallowing the rest of the file.
* **m3** — the suite breakdown was checked with a single regex match, so a
  correct triple early in the document masked a wrong one later on. Every
  triple is checked now.
* **m4** — the same pattern also matched the prose phrase *"18,000 cases, 0
  mismatches"* and reported a bogus breakdown of `[1, 0, 0]`. The category
  names are now an explicit whitelist and a thousands separator cannot satisfy
  the pattern. The coverage pattern likewise requires its family tag.
* **m5** — `evidence/environment.txt` was not in the freshness list even
  though the comment above the list said it was; it is checked now, and its
  `code-fp:` spelling is recognised.
* **m6** — the README-vs-evidence comparison could be defeated by changing
  the log *and* the README together. `evidence/MANIFEST.sha256` now lists the
  SHA-256 of every recorded log and the gate recomputes them, so a log
  changed without the manifest fails. The remaining limit — a change that
  updates log, manifest and README consistently — is stated in README §4.7
  rather than left implicit, because no comparison of numbers can rule it out
  while the benchmark values are load-dependent.

### Documentation (m7, m8)

* **m7** — this file had no entry for the seventh review's fixes.
* **m8** — README §4.7 showed a frozen fingerprint and a mutation command
  using `#` as a comment, which is not a MoonBit comment (`//` is), so the
  example could not be reproduced. Both are now placeholders plus the command
  that prints the live values.

### Outbound

The GitHub Support request (the only path to the remaining **S** finding) is
kept in the project workspace and is refreshed against the final commit of
this round — its quoted commit IDs must not outlive the commit they name.

---

## Unreleased — the seventh-review fixes (2026-11-25)

Fixes for the **1 M + 6 m** findings of the seventh independent review
(`qa/independent_review_round7.md` in the project workspace).

* **M1** — the Support request contained four statements that were not true
  of the repository: it named a commit that was no longer `main`, called all
  thirteen non-`noreply` commits pull-request commits (only one was), said
  the remote branches had been deleted (they were rewritten, not deleted), and
  quoted an `ls-remote` output that no longer matched. The local object store
  was genuinely pruned (`reflog expire --expire=now --all` plus
  `git gc --prune=now`), which took the local non-`noreply` commits from
  thirteen to one; the request now says exactly that.
* **m1** — the gate accepted a test-count declaration inside a fenced code
  block. A declaration only counts in the prose; an unpaired fence is now an
  error rather than a way to hide the rest of the file.
* **m2** — the code fingerprint was written into every log and never checked.
  The gate now recomputes the digest of the current tree and refuses to pass
  when a recorded log came from a different one.
* **m3** — README §4.5 quoted a dot-level figure that no independent
  implementation could reproduce. The figure is gone; the section states the
  order of magnitude and why the exact value is not reproducible.
* **m4** — README said "11" where the tooling said "77". The truth is 77
  (confirmed against the fourth review's own table), and the README now says
  77.
* **m5** — the benchmark, coverage and breakdown figures were not part of any
  gate. They are now cross-checked against the recorded logs.
* **m6** — a README that is not valid UTF-8 produced a traceback. It now
  produces a readable diagnostic and a distinct exit code.

The update record also gained this file, and `tools/check_consistency.py`
became the single entry point that the evidence script and CI both call.

---

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
