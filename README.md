# moonbit-crdt

**Conflict-free replicated data types (CRDTs) for MoonBit — with a cross-implementation differential testing harness.**

> Offline-first applications need data structures whose replicas can be edited
> independently and merged later **without a coordinator and without conflicts**.
> MoonBit's standard library has no such data structures. This package provides
> four of them — and, more importantly, a verification setup that can *prove*
> they behave as specified.

[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![moon](https://img.shields.io/badge/moon-0.1.20261119-informational)](https://www.moonbitlang.com/download/)

---

## 1. What is in the box

| Type | Use case | Merge rule |
|---|---|---|
| `GCounter` | a counter that only ever grows (likes, views, events) | point-wise **max** over per-replica keys |
| `PNCounter` | a counter that also supports decrements | two grow-only counters, subtracted on read |
| `ORSet` | a replicated set where an element can be added *and* removed concurrently (**add wins**) | **union of dots** + point-wise max of dot counters |
| `LWWRegister` | a replicated key/value map | keep the entry with the greater `(wall, counter, node)` |

All four provide the three algebraic laws that make a CRDT usable:

* **commutative** — `merge(a, b) == merge(b, a)`
* **associative** — `merge(merge(a, b), c) == merge(a, merge(b, c))`
* **idempotent** — `merge(a, a) == a`

They are verified three independent ways — see [§4](#4-how-do-we-know-it-works).

---

## 2. Quick start

```bash
# 1. install the MoonBit toolchain
curl -fsSL https://cli.moonbitlang.com/install/unix.sh | bash
export PATH="$HOME/.moon/bin:$PATH"

# 2. run the demo
moon run cmd/main

# 3. run the test suite (27 tests: unit + property + regression)
moon test

# 4. run the benchmarks
moon bench

# 5. run the cross-implementation differential harness
python3 tools/fuzz_diff.py --cases 2500 --seed 20261124
```

Using it from another MoonBit project:

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

### 3.2 `PNCounter` — counter with decrements

Built from two grow-only counters, one for increments and one for decrements.
The value is `positive.value() - negative.value()`.

A single *signed* counter would need a merge rule that decides which side
"won" — precisely the conflict a CRDT must avoid. Splitting the state removes
the conflict by construction: subtraction happens only at read time, on a
single replica.

### 3.3 `ORSet` — observed-remove set, add-wins

Every `add` mints a unique **dot** `<replica>#<seq>` and attaches it to the
element. `remove(elem)` deletes *only the dots the remover has observed*. A
concurrent `add` on another replica mints a *new* dot, which the remover has
not seen — so the element survives. That is the add-wins behaviour, and it
falls out of the representation rather than being special-cased.

The per-replica dot counters are merged with a point-wise maximum as well: if
they could go backwards, the same dot could be minted twice after a merge and
the set would lose track of it.

### 3.4 `LWWRegister` — last-writer-wins register

Each key maps to `(wall, counter, node, value)`. The merge keeps the entry
with the greater timestamp, comparing `wall` first, then `counter`, then the
`node` id. Because the node id is unique, `(wall, counter, node)` is a
**total** order — so concurrent writes always resolve to the same winner on
every replica, with no value silently lost in a tie.

`wall` and `counter` are `Int64`, not `Int`: MoonBit's `Int` is 32-bit, and a
millisecond timestamp does not fit in 32 bits.

---

## 4. How do we know it works?

Three independent layers, each able to catch what the others cannot.

### 4.1 Unit tests — `crdt_test.mbt`

Concrete semantics of every operation, pinned down one by one — **27 tests in total** (11 unit,
11 property, 5 regression).

Concrete semantics of every operation, pinned down one by one.

### 4.2 Property tests — `crdt_test.mbt` (QuickCheck)

Every algebraic law is stated as a property over **random** inputs and checked
over many generated cases (fixed seeds, so runs are reproducible):

> `property: gcounter merge is commutative` ·
> `property: gcounter merge is associative` ·
> `property: gcounter merge is idempotent` ·
> `property: gcounter value never decreases when merging` ·
> `property: pncounter merge is commutative and idempotent` ·
> `property: orset merge is commutative` · `… idempotent` · `… convergence` ·
> `property: lwwregister merge is commutative and keeps the maximum`

### 4.3 Cross-implementation differential harness — `tools/`

A property test can only prove that the implementation does what the property
says. If the property and the implementation share a mistake, both are wrong
together. A **differential test** against a second implementation written from
the specification catches exactly that.

```
tools/reference_crdt.py   an independent implementation of the same semantics,
                          in a different language, with different data
                          structures, written from the spec rather than
                          transliterated from the MoonBit source
tools/fuzz_diff.py        generates random operation streams, replays each of
                          them through BOTH implementations, compares the
                          canonical output byte for byte, and shrinks any
                          disagreement down to a minimal reproduction
```

Result on the development machine — **18,000 randomly generated cases across
four seeds and four operation-length profiles, zero disagreements**:

```
seed 20261124  2500 cases/family  max 12 ops   10000 cases   0 mismatches
seed 777        1000 cases/family  max 12 ops    4000 cases   0 mismatches
seed 31337       400 cases/family  max 40 ops    1600 cases   0 mismatches
seed 42          600 cases/family  max 25 ops    2400 cases   0 mismatches
```

(raw logs in [`evidence/`](evidence/))

#### Bugs this harness actually found

The harness is not decoration — it found real defects during development, and
each one is now pinned by a regression test in `crdt_test.mbt`:

| # | Defect | How it was found | Why it mattered | Fix |
|---|---|---|---|---|
| 1 | `LWWWorld::apply` required 5 tokens before applying an operation, but a `merge` operation has **3** — so **every merge was silently dropped** and the LWW world never merged anything | differential harness, minimal case `lww\|shrink\|merge A C` | the LWW path was completely dead; unit tests had not covered it because they exercised the type directly, not the world model | arity guard corrected to 3, `set` checked separately for 6 |
| 2 | The two implementations disagreed on whether a merge **source** that does not exist becomes visible in the canonical output | differential harness, minimal case `lww\|shrink\|merge A B` | an ambiguous canonical form makes differential comparison unreliable — the spec was silent | spec tightened: a replica appears in the output iff some operation wrote to it or merged into it; both implementations follow it |
| 3 | A negative delta was accepted by `GCounter::inc`, which broke the **grow-only** invariant: the total value could *decrease* after a merge | property test (`gcounter value never decreases when merging`), counterexample `[0, 1159266240, 988463898]` | a silent violation of the type's central invariant | negative deltas are rejected and documented; regression test added |
| 4 | The LWW tie-break was ignored by one of the property statements | property test (`lwwregister merge is commutative …`) | the property was wrong, not the library — but it hid the fact that the tie-break is the *node id* | property corrected to mirror the library's total order |
| 5 | The canonical order used MoonBit's **built-in** string comparison, which is **numeric-aware** (`"C#10" < "C#2"` is *false* in MoonBit, *true* in Python) | differential harness, long-stream run (`max_ops=40`, seed 31337) — the two implementations ordered the same dots differently | a canonical form that is not language-independent cannot be compared across implementations; every long case with a double-digit dot number would mismatch | the order is now **defined explicitly** as UTF-16 code unit order on both sides (`lexical_cmp` in MoonBit, UTF-16BE sort key in Python) |

Two of the five are **library** defects, two are **specification**
defects and one is a **cross-language** defect — all three classes matter, and
none of them is visible from a single-implementation test suite.

### 4.4 Regression tests

Every row of the table above has a corresponding `regression:` test in
`crdt_test.mbt`, so the bugs cannot come back silently.

---

## 5. Benchmarks

`moon bench` (MoonBit 0.1.20261119, x86-64 server, `wasm-gc` backend):

| Benchmark | Time (mean ± σ) |
|---|---|
| `gcounter merge` (1000 distinct replicas) | 59.91 µs ± 2.35 µs |
| `orset merge` (1000 elements) | 120.62 µs ± 11.47 µs |
| `orset add` (1000 sequential adds) | 6.87 ms ± 1.61 ms |
| `lwwregister merge` (1000 keys) | 63.71 µs ± 1.84 µs |

The OR-Set is the most expensive type to merge, and that is inherent: merging
a set means unioning the dot sets, which is proportional to the number of
dots.  The counter and register merges are flat in the number of *keys*
they have to merge.

Raw output: [`evidence/bench.log`](evidence/bench.log).

---

## 6. Design decisions worth knowing about

* **`Int64` for counters and timestamps.** MoonBit's `Int` is 32-bit; a
  millisecond timestamp (`~1.7 × 10¹²`) and a long-lived counter both overflow
  it. The first version of this package used `Int` and the property tests
  caught the resulting overflow immediately.
* **Negative increments are rejected, not clamped.** A G-Counter is grow-only
  by definition; accepting a decrement would let the value move *backwards*
  for reasons no replica can explain. Rejecting the input keeps the invariant
  true by construction.
* **A canonical form instead of structural equality.** Several of these types
  are sets underneath. Two replicas that merged the same dots in a different
  order hold the same state but are not structurally equal, so equality is
  defined as equality of the canonical string. This also gives the differential
  harness something stable to compare.
* **Dots are encoded as strings** (`"node-7#12"`) instead of a tuple. It keeps
  the canonical form readable, keeps the type hashable, and makes the wire
  format obvious.
* **The canonical order is explicit, not the language default.** MoonBit's
  built-in string comparison is numeric-aware, Python's is not; a canonical
  form that depends on the host language's collation is not comparable across
  implementations. The order is therefore defined as UTF-16 code unit order
  and implemented the same way on both sides.
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
* M. Kleppmann, *Designing Data-Intensive Applications* (O'Reilly, 2017),
  ch. 5 — the LWW register and the hybrid logical clock pattern.

No code was copied from either source; the implementations are written from
the definitions in this README. The MoonBit standard library is used only for
`Map`/`Array`/`QuickCheck`, and the `quickcheck` package is used as documented
in `moonbitlang/core`.

**AI usage.** The implementations were written with AI assistance (the
`moonbit-crdt` project, 2026-11-24) and then validated by the three
verification layers above; every defect the AI introduced was found by the
property tests and the differential harness, not by reading the code. The
authors can explain and defend every line of the implementation and the
reasoning behind each merge rule.

---

## 8. Layout

```
moonbit-crdt/
├── moon.mod / moon.pkg          module + package configuration
├── gcounter.mbt                 grow-only counter
├── pncounter.mbt                positive/negative counter
├── orset.mbt                    observed-remove set (add-wins)
├── lwwregister.mbt              last-writer-wins register
├── canonical.mbt                canonical (order-independent) rendering
├── world.mbt                    replica-world model + operation grammar
├── crdt_test.mbt                unit + property + regression tests
├── crdt_bench_test.mbt          benchmarks
├── cmd/main/                    runnable demonstration
├── cmd/replay/                  replay engine used by the differential harness
├── tools/
│   ├── reference_crdt.py        independent reference implementation (Python)
│   └── fuzz_diff.py             differential fuzzing harness with shrinking
└── evidence/                    raw logs of the runs quoted above
```

## 9. License

Apache-2.0 — see [LICENSE](LICENSE).
