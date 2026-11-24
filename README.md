# moonbit-crdt

**Conflict-free replicated data types (CRDTs) for MoonBit — with a cross-implementation differential testing harness.**

> Offline-first applications need data structures whose replicas can be edited
> independently and merged later **without a coordinator and without conflicts**.
> MoonBit's standard library has no such data structures. This package provides
> four of them — and, more importantly, a verification setup that checks they
> behave as specified, and that shows its own teeth when it does not.

[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![moon](https://img.shields.io/badge/moon-0.1.20261119-informational)](https://www.moonbitlang.com/download/)
[![author](https://img.shields.io/badge/author-kkkkikun-8250df)](https://github.com/kkkkikun)

---

## 1. What is in the box

| Type | Use case | Merge rule |
|---|---|---|
| `GCounter` | a counter that only ever grows (likes, views, events) | point-wise **max** over per-replica keys |
| `PNCounter` | a counter that also supports decrements | two grow-only counters, subtracted on read |
| `ORSet` | a replicated set where an element can be added *and* removed concurrently | **union of dots** + **union of tombstones**, minus every tombstoned dot + point-wise max of dot counters |
| `LWWRegister` | a replicated key/value map | keep the entry with the greater `(wall, counter, node)` |

All four provide the three algebraic laws that make a CRDT usable:

* **commutative** — `merge(a, b) == merge(b, a)`
* **associative** — `merge(merge(a, b), c) == merge(a, merge(b, c))`
* **idempotent** — `merge(a, a) == a`

**These laws hold under two preconditions that the library does *not* enforce.**
They are the caller's responsibility, and §3.1 / §3.4 say exactly what breaks
when they are violated:

1. **Every replica writes only its own counter key.** `GCounter::inc` accepts
   any key. If two replicas write the same key concurrently, the point-wise
   maximum silently discards the smaller increment.
2. **Every node id is unique.** `LWWRegister::set` takes the node id as an
   argument. If two replicas use the same id with the same `(wall, counter)`,
   the tie-break cannot decide between them and `merge(a, b)` may differ from
   `merge(b, a)` — the library stops converging, silently.

They are checked by the verification layers in [§4](#4-how-do-we-know-it-works):
unit and property tests, a cross-implementation differential harness, fault
injection, and a coverage report.

---

## 2. Quick start

```bash
# 1. install the MoonBit toolchain
curl -fsSL https://cli.moonbitlang.com/install/unix.sh | bash
export PATH="$HOME/.moon/bin:$PATH"

# 2. run the demo
moon run cmd/main

# 3. run the test suite (33 tests: 16 unit + 10 property + 7 regression)
moon test

# 4. run the benchmarks
moon bench

# 5. run the cross-implementation differential harness
python3 tools/fuzz_diff.py --cases 2500 --seed 20261124

# 6. check that the harness would actually catch a defect (fault injection)
python3 tools/fault_injection.py --project . --work /tmp/c05_fault_injection

# 7. check that the generated traffic reaches the branches under test
python3 tools/coverage_report.py --cases 2500 --seed 20261124
```

Using it from another MoonBit project:

> **Precondition:** the import below only resolves once the module has been
> published to the MoonBit registry (`moon publish`). **This package has not
> been published** — the registry is not reachable from the development
> environment, so `import { "kkkkikun/moonbit-crdt" }` does not resolve from
> an outside project yet. Inside this repository the very same import is used
> by `cmd/main` and `cmd/replay`, which import the module by the name in
> `moon.mod`.

```moonbit
import { "kkkkikun/moonbit-crdt" }

let counter = @moonbit-crdt.GCounter::new().inc("node-1", 1L)
let other = @moonbit-crdt.GCounter::new().inc("node-2", 1L)
let merged = @moonbit-crdt.GCounter::merge(counter, other)
println(merged.value())   // 2
```

---

## 3. The data structures

### 3.1 `GCounter` — grow-only counter

State is a map `replica → count`. A replica **only ever writes its own key**,
so two replicas never write the same key concurrently and no conflict can
arise. Merging therefore takes the point-wise maximum: the newest value of
each key wins, the stale one is discarded, and nothing is lost.

> **Caller guarantee.** "Only ever writes its own key" is *not* enforced by the
> library — `inc(replica, delta)` will happily write any key you name. If two
> replicas write the same key, the point-wise maximum keeps the larger of the
> two and the smaller increment is silently lost. The property is a precondition
> of the merge rule, not a guarantee the library provides.

### 3.2 `PNCounter` — counter with decrements

Built from two grow-only counters, one for increments and one for decrements.
The value is `positive.value() - negative.value()`.

A single *signed* counter would need a merge rule that decides which side
"won" — precisely the conflict a CRDT must avoid. Splitting the state removes
the conflict by construction: subtraction happens only at read time, on a
single replica.

### 3.3 `ORSet` — observed-remove set with **durable** removal

Every `add` mints a unique **dot** `<replica>#<seq>` and attaches it to the
element. The set therefore has three parts:

* `elems` — element → the dots that are currently **live**,
* `tombstones` — element → the dots that have been **removed**,
* `counters` — replica → the next sequence number for that replica.

`remove(elem)` moves every dot of `elem` that the removing replica has
**observed** from `elems` into `tombstones`. `merge` unions the dots *and* the
tombstones and then **drops every dot that some replica has tombstoned**. An
element is present iff at least one non-tombstoned dot is attached to it.

That gives the two halves of the observed-remove contract:

* **A removal that was observed is durable.** The tombstone travels with the
  state, so merging with a replica that still holds the old dot does **not**
  bring the element back — not in either merge direction, and not on the
  replica that performed the removal.
* **A concurrent add that was never observed wins.** A replica that adds the
  element while another replica removes it mints a *new* dot that the remover
  has never seen; a removal cannot tombstone a dot it does not know about, so
  the element survives. That is the add-wins behaviour, and it falls out of the
  representation rather than being special-cased.

Both halves are visible in the canonical form, which renders three sections:

```
<live dots>|<tombstoned dots>|<dot counters>
```

so a removal and its durability can be read straight out of the canonical
string (this is the demo in `cmd/main`):

```
A          = lamp=A#0,A#1||A=2        # A holds two live dots
B          = lamp=|lamp=A#0|A=1       # B removed the dot it had seen (tombstone)
merged     = lamp=A#1|lamp=A#0|A=2    # A#0 is dead; A#1, never observed, is alive
```

The per-replica dot counters are merged with a point-wise maximum as well: if
they could go backwards, the same dot could be minted twice after a merge and
the set would lose track of it. The counters are part of the canonical form
too, so that this invariant is *observable* rather than merely asserted.

### 3.4 `LWWRegister` — last-writer-wins register

Each key maps to `(wall, counter, node, value)`. The merge keeps the entry
with the greater timestamp, comparing `wall` first, then `counter`, then the
`node` id.

* **The timestamp is supplied by the caller.** `set(node, key, value, wall,
  counter)` takes both components; the library contains **no clock**. The
  `(wall, counter)` pair is the timestamp *format* a hybrid logical clock
  produces, but producing it — advancing the counter inside one millisecond,
  clamping `wall` to `max(local_wall, last_seen_wall)` — is the caller's job.
* **The node id is the last tie-break, and it must be unique.** The library
  does not check it. With distinct node ids, `(wall, counter, node)` is a
  **total** order, so concurrent writes resolve to the same winner on every
  replica. If two replicas use the *same* node id with the same
  `(wall, counter)`, the order is no longer total: `merge(a, b)` may differ
  from `merge(b, a)` and the replicas silently stop converging.
* **The node id is compared in plain code-unit order**, not with the host
  language's built-in string comparison. MoonBit's built-in `>` is
  *numeric-aware* (`"node-10" > "node-2"` is true in MoonBit, false in
  Python), so using it would make two implementations of the same
  specification elect **different** winners. The order is spelled out
  explicitly — see `lexical_cmp` in `canonical.mbt`.

`wall` and `counter` are `Int64`, not `Int`: MoonBit's `Int` is 32-bit, and a
millisecond timestamp does not fit in 32 bits.

---

## 4. How do we know it works?

Several layers, each able to catch what the others cannot — and each able to
say out loud when it *cannot* catch something.

All of them are wired into CI: `.github/workflows/ci.yml` runs `moon check`,
`moon test`, `moon bench`, the differential harness, the coverage report, the
fault injection and the demo on every push and pull request — with smaller
case counts, because CI is a smoke test rather than the measurement run.

### 4.1 Unit tests — `crdt_test.mbt`

Concrete semantics of every operation, pinned down one by one — **33 tests in
total** (16 unit, 10 property, 7 regression).

### 4.2 Property tests — `crdt_test.mbt` (QuickCheck)

Every algebraic law is stated as a property over **random** inputs:

> `property: gcounter merge is commutative` ·
> `property: gcounter merge is associative` ·
> `property: gcounter merge is idempotent` ·
> `property: gcounter value never decreases when merging` ·
> `property: pncounter merge is commutative and idempotent` ·
> `property: orset merge is commutative` · `… idempotent` · `… convergence` ·
> `property: lwwregister merge is commutative and keeps the maximum` ·
> `property: world replay is deterministic`

**How large are these properties, exactly?** MoonBit's `quickcheck` driver
runs with `count = 100` and `seed = 37`, and both are fixed. Each of the ten
properties is therefore checked against **100 generated cases**, and because
the seed is fixed, **every run checks the same 100 cases**. That makes the
runs reproducible, but it also means the property suite explores *one* batch of
inputs rather than a growing sample: a defect that only shows up on inputs the
fixed seed does not produce will not be found here. Varying the traffic is the
job of the differential harness (§4.3), which takes the seed as a parameter
and was run with four different seeds.

### 4.3 Cross-implementation differential harness — `tools/`

A property test can only prove that the implementation does what the property
says. If the property and the implementation share a mistake, both are wrong
together. A **differential test** against a second implementation of the same
contract is the way to look for that — but only to the extent that the two
implementations are genuinely independent, and it is worth being precise about
where they are and are not.

```
tools/reference_crdt.py   the reference implementation (Python)
tools/fuzz_diff.py        generates random operation streams, replays each of
                          them through BOTH implementations, compares the
                          canonical output byte for byte, and shrinks any
                          disagreement down to a minimal reproduction
```

**Where the two implementations are independent — and where they are not.**
The independence is *not* uniform across the four types, so the harness's
proof power differs by type:

| Type | Python side | Independent? |
|---|---|---|
| `ORSet` | keeps a per-element **causal context** and computes liveness with the **ORSWOT / 2P-Set** rule `live = (live_a ∩ live_b) ∪ (live_a \ seen_b) ∪ (live_b \ seen_a)` | **Yes — a different algorithm.** The MoonBit side stores tombstones and filters the merged dot set by them. Two different formulations of the same contract, so a mistake on either side surfaces as a mismatch. |
| `GCounter` | point-wise max over per-replica keys | **No — the same rule**, re-implemented in another language with another data structure (`dict` vs `Map`). |
| `PNCounter` | two grow-only counters, subtracted on read | **No — the same rule.** |
| `LWWRegister` | keep the greater `(wall, counter, node)`, compared in UTF-16BE order | **No — the same rule.** The *order* is pinned down explicitly on both sides, so this is language-level independence only. |

So, precisely:

* for the **OR-Set**, the differential test is an **algorithmic** cross-check
  and can catch a semantic mistake in either implementation;
* for the **counters and the register**, it is a **language-level** cross-check
  and can catch differences in integer width, collation, argument-count guards
  and map iteration order — but it **cannot** catch a mistake that both sides
  make in the same way.

This is precisely why the harness was not left to carry the semantics on its
own: the first version of `reference_crdt.py` copied the MoonBit merge rule
verbatim, and therefore shared the MoonBit implementation's own bug — the
element came back after a removal on *both* sides, and no number of cases
could tell. The Python side was rewritten against the ORSWOT / 2P-Set
causal-context rule, and the removal bug is now caught by the harness (§4.4).

**Result on the development machine** — 18,000 randomly generated cases across
four seeds and four operation-length profiles, zero disagreements:

| seed | cases/family | max ops | cases compared | mismatches |
|---|---|---|---|---|
| 20261124 | 2500 | 12 | 10000 | 0 |
| 777 | 1000 | 12 | 4000 | 0 |
| 31337 | 400 | 40 | 1600 | 0 |
| 42 | 600 | 25 | 2400 | 0 |

**What that number does and does not mean.** The *volume* is the same before
and after the OR-Set rewrite, but the *proof power* is not:

* **before** the fix, the Python side used the MoonBit side's own merge rule,
  so for the OR-Set these 18,000 cases compared an implementation with a copy
  of itself — they could not have detected the removal bug;
* **after** the fix, the Python side computes liveness with a different
  algorithm, so the same 18,000 cases are a real cross-check of the removal
  contract, and the result is backed by the fault-injection evidence below.

The generator was also changed to produce the situations that matter: the
replica alphabet deliberately includes multi-character ids (`node-2`,
`node-10`), and a large share of the LWW streams contain a write conflict
that *only* the node id can decide.

(raw logs in [`evidence/`](evidence/))

#### Defects the verification setup actually found

Each one is pinned by a test, so it cannot come back silently.

| # | Defect | How it was found | Why it mattered | Fix | Pinned by |
|---|---|---|---|---|---|
| 1 | `LWWWorld::apply` required 5 tokens before applying an operation, but a `merge` operation has **3** — so **every merge was silently dropped** and the LWW world never merged anything | differential harness, minimal case `lww\|shrink\|merge A C` | the LWW path was completely dead; unit tests had not covered it because they exercised the type directly, not the world model | arity guard corrected to 3, `set` checked separately for 6 | `regression: lww world applies merge operations` |
| 2 | The two implementations disagreed on whether a merge **source** that does not exist becomes visible in the canonical output | differential harness, minimal case `lww\|shrink\|merge A B` | an ambiguous canonical form makes differential comparison unreliable — the spec was silent | spec tightened: a replica appears in the output iff some operation wrote to it or merged into it; both implementations follow it | `regression: merging from an unknown replica does not publish it` |
| 3 | A negative delta was accepted by `GCounter::inc`, which broke the **grow-only** invariant: the total value could *decrease* after a merge | property test (`gcounter value never decreases when merging`), counterexample `[0, 1159266240, 988463898]` | a silent violation of the type's central invariant | negative deltas are rejected and documented; regression test added | `regression: gcounter rejects negative deltas` |
| 4 | The LWW tie-break was ignored by one of the property statements | property test (`lwwregister merge is commutative …`) | the property was wrong, not the library — but it hid the fact that the tie-break is the *node id* | property corrected to mirror the library's total order | `regression: lww tie-break is the node id` |
| 5 | The canonical order used MoonBit's **built-in** string comparison, which is **numeric-aware** (`"C#10" < "C#2"` is *false* in MoonBit, *true* in Python) | differential harness, long-stream run (`max_ops=40`, seed 31337) — the two implementations ordered the same dots differently | a canonical form that is not language-independent cannot be compared across implementations; every long case with a double-digit dot number would mismatch | the order is now **defined explicitly** as UTF-16 code unit order on both sides (`lexical_cmp` in MoonBit, UTF-16BE sort key in Python) | `regression: canonical order is plain lexicographic, not numeric-aware` |
| 6 | The canonical encoding was **not injective**: the key sets `{a, b}` and `{a=1;b}` both rendered as `a=1;b=2`, so two different states compared equal | independent review probe | the harness compares canonical strings — states that render the same string are invisible to it | keys and values are percent-escaped (`;` `=` `|` `%`), on both sides | `regression: canonical pairs are escaped, so the encoding is injective` |
| 7 | **OR-Set removal was not durable**: `remove` dropped the dots instead of recording them, so merging with a replica that still held the old dots brought the element **back** — on the replica that had removed it | independent review probe; now reproduced on demand by fault injection | the observed-remove contract was broken: a removal that *was* observed could be undone | `ORSet` keeps `tombstones`; `remove` moves the observed dots into them; `merge` unions them and drops every tombstoned dot; the canonical form renders them | `orset: removal is durable — merging with a stale replica does not resurrect it` |
| 8 | The **LWW tie-break** used the host language's numeric-aware built-in comparison, so the MoonBit implementation and the Python reference elected **opposite winners** for the same concurrent write | independent review probe; now reproduced on demand by fault injection | the total order was not language-independent, so two implementations of the same specification disagreed on the winner | `ts_greater` compares the node id with `lexical_cmp` (UTF-16 code unit order); the Python side uses the UTF-16BE sort key | `lwwregister: the node tie-break is plain lexicographic, not numeric-aware` |

The classes are deliberately mixed: implementation defects (1, 3, 7, 8),
specification defects (2, 4) and canonical-format defects (5, 6) — and none of
them is visible from a single-implementation test suite.

### 4.4 Fault injection — can the harness actually fail?

"18,000 cases, 0 mismatches" is only evidence if the harness *would* have
reported a mismatch had the implementation been wrong. `tools/fault_injection.py`
answers exactly that question: it copies the project into a scratch directory,
injects a **known** semantic defect into the MoonBit implementation, and runs
the harness against the copy. The harness must fail, print the mismatching
case and shrink it to a minimal reproduction.

Two faults are injected — the two most serious defects in the table above
(7 and 8):

| Injected fault | Result | Minimal reproduction found |
|---|---|---|
| `S1` — the tombstone filter is neutered, so a removed element comes back | **DETECTED** (800 cases, 1 mismatch) | `orset\|shrink\|add node-10 z;merge node-2 node-10;rem node-10 z;merge node-2 node-10` |
| `S2` — the node tie-break falls back to MoonBit's numeric-aware built-in comparison | **DETECTED** (800 cases, 25 mismatches) | `lww\|shrink\|set node-2 k2 v2 e c;set node-10 k2 v3 e c;merge node-2 node-10` |

```
[verdict] 2/2 injected faults detected by the differential harness
```

The script never modifies the project it is given, and it exits non-zero if
any injected fault goes unnoticed.

(raw log: [`evidence/fault_injection.log`](evidence/fault_injection.log))

### 4.5 Coverage — did the traffic reach the branch under test?

A differential harness that never generates the situation it claims to test is
worse than no harness: it reports "0 mismatches" and the reader concludes the
property was verified. `tools/coverage_report.py` answers that question for
the two situations that decide this project's correctness:

| Branch | Why it matters | Measured (2500 cases/family, seed 20261124) |
|---|---|---|
| LWW conflict decided **only by the node id** | the exact case a wrong tie-break breaks (defect 8) | **1959 / 2500** cases |
| OR-Set removal that is **resurrectable** — a removal followed by a merge with a replica that still holds the removed dots | the exact case a forgotten removal breaks (defect 7) | **551** durable removals observed, of which **343** are resurrectable |

The script **exits non-zero** when a branch is never reached, so "0
mismatches" can never be green for lack of coverage.

This layer is what keeps the volume honest: without it, "18,000 cases" could
mean "18,000 cases that never exercise the tie-break at all".

(raw log: [`evidence/coverage_report.log`](evidence/coverage_report.log))

### 4.6 Regression tests

Every defect in the table in §4.3 has a test that pins it — defects 1–6 as
`regression:` tests, the two review-found ones (7 and 8) as named unit tests
(`orset: removal is durable …` and `lwwregister: the node tie-break is plain
lexicographic, not numeric-aware`). A seventh `regression:` test pins a design
decision rather than a found defect: `regression: counters and timestamps stay
inside Int64 at the 32-bit boundary`.

---

## 5. Benchmarks

`moon bench` (MoonBit 0.1.20261119, x86-64 server, `wasm-gc` backend) measures
the merge paths — the operations that dominate the cost of a replicated
application, because a merge happens on every sync.

| Benchmark | Time (mean ± σ) |
|---|---|
| `gcounter merge` (1000 entries) | **57.41 µs ± 2.76 µs** |
| `orset merge` (1000 elements) | **141.13 µs ± 8.36 µs** |
| `orset add` (1000 sequential adds) | **6.38 ms ± 714.79 µs** |
| `lwwregister merge` (1000 keys) | **74.86 µs ± 2.77 µs** |

The benchmark names above are the ones `moon bench` prints. "1000 entries" means 1000
distinct replica keys (one increment each) — a counter with a single key would make the
merge O(1) and the benchmark meaningless. The measured values in this table are copied
verbatim from `evidence/bench.log`; regenerate them with `bash tools/regenerate_evidence.sh`.


The OR-Set is the most expensive type to merge, and that is inherent: merging
a set means unioning the dot sets — and now also the tombstone sets — which is
proportional to the number of dots. The counter and register merges are flat
in the number of *keys* they have to merge.

Raw output: [`evidence/bench.log`](evidence/bench.log).

---

## 6. Design decisions worth knowing about

* **`Int64` for counters and timestamps.** MoonBit's `Int` is 32-bit; a
  millisecond timestamp (`~1.7 × 10¹²`) and a long-lived counter both overflow
  it. The type signatures are therefore `Int64` end to end, and the 32-bit
  boundary is pinned by a test (`regression: counters and timestamps stay
  inside Int64 at the 32-bit boundary`).
* **Negative increments are rejected, not clamped.** A G-Counter is grow-only
  by definition; accepting a decrement would let the value move *backwards*
  for reasons no replica can explain. Rejecting the input keeps the invariant
  true by construction.
* **A removal is recorded, not forgotten.** The first version of the OR-Set
  dropped the removed dots from the local table, so the removal did not travel
  with the state and the element came back on the next merge. The removed dots
  are kept as **tombstones**, which are merged like any other part of the
  state. This is the difference between "add-wins" and "the removal is
  durable", and both halves are part of the contract.
* **A canonical form instead of structural equality.** Several of these types
  are sets underneath. Two replicas that merged the same dots in a different
  order hold the same state but are not structurally equal, so equality is
  defined as equality of the canonical string. This also gives the differential
  harness something stable to compare. The encoding is **injective** — keys and
  values are percent-escaped, so two different states can never render the
  same string.
* **Dots are encoded as strings** (`"node-7#12"`) instead of a tuple. It keeps
  the canonical form readable, keeps the type hashable, and makes the wire
  format obvious.
* **The canonical order is explicit, not the language default.** MoonBit's
  built-in string comparison is numeric-aware, Python's is not; a canonical
  form that depends on the host language's collation is not comparable across
  implementations. The order is therefore defined as UTF-16 code unit order
  and implemented the same way on both sides. The same applies to the LWW node
  tie-break.
* **The operation grammar uses letters instead of decimal numbers** (`a` = 1 …
  `z` = 26). This removes *all* text-to-number parsing from the implementation
  that the differential test is supposed to validate — one less place for a
  parser bug to hide. Unit tests use plain integer literals and therefore
  cover the full numeric range.

---

## 7. Reference and provenance

The algorithms implemented here are the standard, well-known CRDT constructions
from the literature:

* N. Preguiça, M. Shapiro et al., *A comprehensive study of Convergent and
  Commutative Replicated Data Types* (INRIA RR-7506, 2011) — the source of
  the G-Counter / PN-Counter / OR-Set (add-wins, observed-remove) definitions
  and of the `delta-state` merge rules used here.
* N. Preguiça, M. Shapiro, M. Baquero, M. Zawirski, *Conflict-free Replicated
  Data Types* (SSS 2011) — the causal-context construction behind the
  ORSWOT / 2P-Set liveness rule that the **Python reference implementation**
  uses for the OR-Set (`tools/reference_crdt.py`, see the rule quoted in
  §4.3). The MoonBit side expresses the same contract with tombstones
  instead.
* M. Kleppmann, *Designing Data-Intensive Applications* (O'Reilly, 2017),
  ch. 5 — the LWW register and the hybrid logical clock pattern. **Only the
  LWW register is implemented here**: the clock is not part of this package,
  the caller supplies the `(wall, counter)` timestamp (see §3.4).

No code was copied from either source; the implementations are written from
the definitions in this README. The MoonBit standard library is used only for
`Map`/`Array`/`QuickCheck`, and the `quickcheck` package is used as documented
in `moonbitlang/core`.

**AI usage.** The implementations were written with AI assistance (the
`moonbit-crdt` project, 2026-11-24) and then validated by the verification
layers above. The property tests and the differential harness found a series
of defects along the way; the two most serious ones — the OR-Set removal that
was not durable, and the LWW tie-break that fell back to the host language's
numeric-aware comparison — were found by an **independent review** of the
project rather than by the test suite, and are now pinned by fault injection
(§4.4) and by tests. The author can explain and defend every line of the
implementation and the reasoning behind each merge rule.

---

## 8. Layout

```
moonbit-crdt/
├── moon.mod / moon.pkg          module + package configuration
├── gcounter.mbt                 grow-only counter
├── pncounter.mbt                positive/negative counter
├── orset.mbt                    observed-remove set with durable removal (tombstones)
├── lwwregister.mbt              last-writer-wins register
├── canonical.mbt                canonical (order-independent) rendering
├── world.mbt                    replica-world model + operation grammar
├── crdt_test.mbt                unit + property + regression tests
├── crdt_bench_test.mbt          benchmarks
├── cmd/main/                    runnable demonstration
├── cmd/replay/                  replay engine used by the differential harness
├── .github/workflows/ci.yml     CI: check / test / bench / differential / coverage / fault injection
├── tools/
│   ├── reference_crdt.py        reference implementation (Python)
│   ├── fuzz_diff.py             differential fuzzing harness with shrinking
│   ├── fault_injection.py       injects known defects, checks the harness fails
│   ├── coverage_report.py       measures whether the traffic reaches the branches
│   └── regenerate_evidence.sh   regenerates every raw log in evidence/
└── evidence/                    raw logs of the runs quoted above
```

## 9. Author / 贡献者

**[kkkkikun](https://github.com/kkkkikun)** — 本仓库全部代码、测试、差分测试 harness 与文档均由该作者独立完成。

## 10. License

Apache-2.0 — see [LICENSE](LICENSE).
