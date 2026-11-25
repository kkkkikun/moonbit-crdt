# Archived evidence — pre-fix run (2026-11-24, before the OR-Set / LWW fixes)

These logs are kept **only as audit history**. They describe the code *as it
was before* the fixes that landed in PR #2 (merged 2026-11-24, `90dbc1b`).

**Do not read them as describing the current implementation.** In particular:

| Log | What it was | Why it is superseded |
|---|---|---|
| `moon_test.log` | `Total tests: 27, passed: 27` | the suite now has **37** tests |
| `bench.log` | the pre-fix timings | the OR-Set merge path now also unions the tombstone table and filters the merged dot set by it, so the merge cost changed |
| `demo.log` | the old demo | the OR-Set section demonstrated a *removal on an empty set* — it could not show removal durability, because removal was not durable yet |
| `fuzz_diff.*.log` | the pre-fix differential run | the reference implementation was rewritten (ORSWOT causal-context rule instead of "drop the dot"), and the generator now produces node-decided write conflicts on purpose — **these two runs are not comparable**, and the old one had no proof power at the semantic level |
| `fuzz_summary.txt` | four summary lines, no seed labels, out of order | the current one is ordered by seed and labelled |
| `environment.txt` | the toolchain of the old run | superseded |

Two defects in the archived logs are themselves worth recording, because they
were found by the independent review and are the reason the regeneration
script exists:

* the old `fuzz_diff.*.log` headers wrote `cases=seed20261124` — a **label in
  the place of a number**;
* the old `fuzz_summary.txt` listed the four summaries **out of order and
  without seeds**.

## How the current logs are produced

```bash
bash tools/regenerate_evidence.sh
```

That script regenerates **this round's** raw logs in `evidence/` — the twelve
files listed in `README.md` §8 — with correct headers, and nothing else. It
writes nothing under `evidence/archive/`. The current `evidence/` was
produced by it on the merged code, on the same server and toolchain recorded
in `evidence/environment.txt`.

CI does **not** run the whole script; what CI runs for the test count is the
same gate the script uses, `tools/check_consistency.py`, so the two cannot
disagree about how many tests the project has.
