# Archived evidence — pre-round-4-review run (2026-11-24)

These logs are the ones that were in `evidence/` **before** the fourth
independent review's findings were applied. They are kept **only as audit
history**: they describe the code as of merged PR #3 (`3b66d8c`), *not* as of
the current tree.

**Do not read them as describing the current implementation.**

All **thirteen** files that `evidence/` held at `3b66d8c` are here, byte for
byte — nothing was rewritten, re-run or tidied up. The listing was verified
against `git ls-tree 3b66d8c evidence/` file by file (SHA-256 compared); see
`CHANGELOG.md` for the round that completed the archive.

| Log | What it was | Why it is superseded |
|---|---|---|
| `moon_test.log` | `Total tests: 33, passed: 33` | the suite now has **37** tests — four more regression tests have been added since (LWW counter arbitration, merge must not rewrite its source copy, extended value-token decoding, merge must not publish a replica that never existed) |
| `bench.log` | the pre-round-4 timings | the value table grew from 27 to 57 tokens, so the corpus changed and the timings are not comparable |
| `coverage_report.log` | the older coverage report | the report was rewritten to share one traffic source with the fuzz harness, to implement the `resurrectable` definition literally, and to add the counter-arbitration and negative/large-value reachability metrics |
| `demo.log` | the pre-round-4 demo run | it carries **no code fingerprint** — it predates the fingerprint mechanism — so it cannot be bound to a tree state. Its output is otherwise identical to the current `evidence/demo.log`, which is the same run with the fingerprint header |
| `environment.txt` | the toolchain of the older run | superseded — it records neither the code fingerprint nor the commit |
| `fault_injection.log` | the older fault-injection run | superseded by the run that catches the deliberately injected S1 defect at 299/800 cases (was 1/800) |
| `fuzz_diff.long.log` | a long-run differential log from **before** the fixes | it has **no code fingerprint** — it predates the fingerprint mechanism — and the script never regenerates it. It is kept here as history, and it is **not** evidence about the current tree |
| `fuzz_diff.seed20261124.log` | the seed-20261124 run of the older tree | no code fingerprint → it cannot be bound to a tree state; the run of the same seed that the current tree produced is the one in `evidence/` |
| `fuzz_diff.seed31337.log` | the seed-31337 run of the older tree | same as above — and this file was in **no** archive at all until the sixth review pointed the gap out |
| `fuzz_diff.seed42.log` | the seed-42 run of the older tree | same as above |
| `fuzz_diff.seed777.log` | the seed-777 run of the older tree | same as above |
| `fuzz_summary.txt` | the four summary lines of the older tree | no fingerprint header, so the summary cannot be bound to a tree state either; the current one carries the fingerprint |
| `moon_check.log` | the type-check output of the older tree | superseded |

## Why the logs were replaced at all

The fourth review showed that the old evidence **could not detect** whole
classes of defects:

* the old value table had 27 single-letter tokens only, so negative integers
  and values above 26 were unreachable — a whole class of width/sign bugs was
  invisible to the harness;
* the coverage report and the fuzz harness generated traffic **independently**,
  so the reported coverage did not describe the traffic that was actually
  compared;
* the old `resurrectable` counter did not implement the definition written in
  the documentation.

Re-running the same scripts on the old code would therefore have produced
misleading "0 divergences" numbers. The logs above are kept so that the
before/after difference in proof power is auditable.

## How the current logs are produced

```bash
bash tools/regenerate_evidence.sh
```

That script regenerates **this round's** raw logs in `evidence/` — the twelve
files listed in `README.md` §8 — and **nothing else**. It does not write
anything under `evidence/archive/`: this directory holds superseded runs that
are kept as audit history only. The current `evidence/` was produced by that
script on the current tree, on the same server and toolchain recorded in
`evidence/environment.txt`.

CI does **not** run the whole script — a CI run is a smoke test, not a
measurement run. What CI *does* run is the same consistency gate the script
runs for the test count: `tools/check_consistency.py`. The declared number of
tests therefore comes from one place, and the evidence script and CI cannot
disagree about it.

For the earlier archive (the logs that predate PR #2) see
`../pre-fix-20261124/README.md`.
