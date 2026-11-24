# Archived evidence — pre-round-4-review run (2026-11-24)

These logs are the ones that were in `evidence/` **before** the fourth
independent review's findings were applied. They are kept **only as audit
history**: they describe the code as of merged PR #3 (`3b66d8c`), *not* as of
the current tree.

**Do not read them as describing the current implementation.**

| Log | What it was | Why it is superseded |
|---|---|---|
| `moon_test.log` | `Total tests: 33, passed: 33` | the suite now has **36** tests — three new regression tests were added (LWW counter arbitration, merge must not rewrite its source copy, extended value-token decoding) |
| `bench.log` | the pre-round-4 timings | the reference implementation's value table grew from 27 to 57 entries, so the corpus changed and the timings are not comparable |
| `moon_check.log` | the type-check output of the older tree | superseded |
| `environment.txt` | the toolchain of the older run | superseded |
| `coverage_report.log` | the older coverage report | the report was rewritten to share one traffic source with the fuzz harness, to implement the `resurrectable` definition literally, and to add the counter-arbitration and negative/large-value reachability metrics |
| `fault_injection.log` | the older fault-injection run | superseded by the run that catches the deliberately injected S1 defect at 299/800 cases (was 1/800) |

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

That script writes every file in `evidence/` from scratch, and it is the same
script CI runs. The current `evidence/` was produced by it on the current tree,
on the same server and toolchain recorded in `evidence/environment.txt`.

For the earlier archive (the logs that predate PR #2) see
`../pre-fix-20261124/README.md`.
