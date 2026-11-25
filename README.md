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

# 3. run the test suite (37 tests: 16 unit + 10 property + 11 regression)
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

The first run of this workflow on the branch that introduced it
([run 45397878777](https://github.com/kkkkikun/moonbit-crdt/actions/runs/45397878777))
went green in 28 s and reported, in that order:

```
Total tests: 33, passed: 33, failed: 0.
[summary] 1200 cases compared, 0 mismatch(es)
[lww]   node-decided conflicts : 236 / 300 cases
[ok] the generated traffic reaches both branches the harness claims to test
[verdict] 2/2 injected faults detected by the differential harness
```

(That run predates the three regression tests added by the fourth review —
**33 was the count at that time**; the current suite has **37**, and the number
in `evidence/moon_test.log` is the one that describes the current tree.)

The last two lines matter more than the first one: the coverage report and the
fault injection are the two steps that can turn a green run red — the first
when the generated traffic stops reaching the branch it claims to test, the
second when the harness stops catching defects it is supposed to catch.

**A green `moon test` is not enough on its own.** Measured on MoonBit
0.1.20261119: deleting `moon.pkg` makes `moon test` **and** `moon check` exit
**255**; deleting only the *test file* (leaving `moon.pkg` intact) makes
`moon test` exit **0** having found nothing at all. A green exit code is
therefore not, by itself, evidence that the suite ran — so the **test count**
is asserted against this README by **one** checker,
`tools/check_consistency.py`, which both `tools/regenerate_evidence.sh` and CI
call. Neither the script nor CI can drift from the other, and neither can
drift from this document.

### 4.1 Unit tests — `crdt_test.mbt`

Concrete semantics of every operation, pinned down one by one — **37 tests in
total** (16 unit, 10 property, 11 regression).

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
| `S1` — the tombstone filter is neutered, so a removed element comes back | **DETECTED** (800 cases, **299** mismatches) | `orset\|shrink\|add node-2 x;merge node-10 node-2;rem node-2 x;merge node-2 node-10` |
| `S2` — the node tie-break falls back to MoonBit's numeric-aware built-in comparison | **DETECTED** (800 cases, 28 mismatches) | `lww\|shrink\|set node-2 k1 v3 h !;set node-10 k1 v2 h !;merge node-2 node-10` |

Note how much louder `S1` is now: **299 of 800 cases** diverge, where before the
generator was improved it was 1. That is the point of generating the removal
scenario deliberately instead of hoping for it — a harness that finds a defect
once in 800 runs is one typo away from missing it.

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
| LWW conflict decided **only by the node id** | the exact case a wrong tie-break breaks (defect 8) | **1956 / 2500** cases |
| LWW conflict decided by the **counter** (same wall, different counter) | the middle layer of the `(wall, counter, node)` order — untested until the fourth review | **1983 / 2500** cases |
| OR-Set removal that is **resurrectable** — a removal followed by a merge with a replica that still holds the removed dots (the tool measures this at **element** level — see the note below) | the exact case a forgotten removal breaks (defect 7) | **5275** durable removals observed, of which **4360** are resurrectable |
| OR-Set removal of an element **that no other replica holds** | the case a removal that never propagates breaks — the removal has to reach every replica | **4448** removals |
| a **negative** value in the traffic | an implementation that accepted a negative increment would be invisible | **366 / 2500** cases |
| a value **above 26** in the traffic | an implementation that truncated a counter to 32 bits would be invisible | **2124 / 2500** cases |

The script **exits non-zero** when a branch is never reached, so "0
mismatches" can never be green for lack of coverage.

This layer is what keeps the volume honest: without it, "18,000 cases" could
mean "18,000 cases that never exercise the tie-break at all".

Two things about this table are worth stating plainly, because the fourth
review found both:

* **It measures the traffic the harness actually compares.** The report and
  the harness call the same `fuzz_diff.generate_cases()` with the same seed,
  case count and family order. An earlier version of this file generated its
  *own* stream, so its numbers described a different set of cases than the
  ones the "0 mismatches" claim rested on.
* **It implements the definition it claims.** "Resurrectable" means: a durable
  removal that is *followed* by a merge which brings the element back from a
  replica that still holds it. The earlier version counted any removal whose
  element was held by another replica at *some* point in the stream, without
  requiring the merge to happen after the removal — that over-counted by more
  than four times (343 against a true count of **77** for the same traffic).
* **It is an element-level proxy, and this is the honest caveat.** The wording
  in the table ("a replica that still holds the removed **dots**") describes
  the *dot-level* truth; what `tools/coverage_report.py` tracks is the
  **element**. The two do not coincide exactly: a merge can bring one dot of
  an element back while the element's other dots stay tombstoned — the
  element-level rule calls that "resurrectable", the dot-level rule does not.
  On the same traffic (2500 cases/family, seed 20261124) the gap between the
  two readings is small — of the order of a few percent — so the "4.4×
  over-count" defect the fourth review found is gone.
  **This file deliberately does not quote a dot-level number.** A dot-level
  count is not reproducible from this repository: it depends on how the
  simulation represents the causal context, and two independent
  implementations of the same prose definition produced noticeably different
  numbers (the reviews recorded ≈4084 and ≈4302 on the same traffic).
  A figure no one in this repository can re-run is not a verifiable figure, so
  the only number quoted here is the element-level one the tool produces and
  `evidence/coverage_report.log` contains.

The last two rows of the table exist because the operation grammar used to be
letters only (`a` = 1 … `z` = 26). That alphabet cannot express a negative
number or a number above 26, so an implementation that accepted a negative
increment, or one that truncated a counter to 32 bits, would have passed the
differential harness unnoticed. The value table now also carries `!` = -1,
`@` = -2, `A` … `Z` = 27 … 52, `[` = 2^31 - 1 and `]` = 2^31 — the last one
deliberately one past the signed 32-bit boundary.

(raw log: [`evidence/coverage_report.log`](evidence/coverage_report.log))

### 4.6 Regression tests

Every defect in the table in §4.3 has a test that pins it — defects 1–6 as
`regression:` tests, the two review-found ones (7 and 8) as named unit tests
(`orset: removal is durable …` and `lwwregister: the node tie-break is plain
lexicographic, not numeric-aware`). A seventh `regression:` test pins a design
decision rather than a found defect: `regression: counters and timestamps stay
inside Int64 at the 32-bit boundary`.

The fourth review added three more, each pinning a gap it found:

| Test | What it pins |
|---|---|
| `regression: lww counter arbitrates before the node id` | the **counter** layer of the `(wall, counter, node)` order — the node layer had a test, this one did not |
| `regression: a merge leaves the source replica untouched` | a merge writes into the target only; it must not publish the source or grow it |
| `regression: the operation grammar decodes negative and large values` | the extended value table (`!`, `@`, `A`…`Z`, `[`, `]`) — without it the harness cannot reach the negative and 32-bit-boundary paths |

The fifth review added one more, and it is worth spelling out **why** the
previous one was not enough:

| Test | What it pins |
|---|---|
| `regression: a merge does not publish a replica that never existed` | merging a replica that was **never created** must not bring it into existence |

The test above it (`… leaves the source replica untouched`) merges two
replicas that **already exist**, so it cannot see the defect the fourth
review's mutation actually was. That mutation added `replicas.set(source, s)`
to the merge branch — "publish the source as well". With an existing source
that line stores the source's own value back, i.e. it changes nothing, and
the suite stayed **green with the defect present**. The observable
consequence is only visible when the source **does not exist**: the world
then publishes a replica that was never there, and the canonical form grows
a line. The new test merges a replica named `ghost` that was never created
and asserts the canonical form is unchanged. Injecting the mutation again
makes that test fail — that is the point of adding it.

### 4.7 How a log is bound to the code that produced it

A log that only records *numbers* cannot prove *which* code produced them.
This is not hypothetical: after the value table grew and the generator changed,
the regenerated fuzz logs came out **byte-identical** to the previous ones (the
logs record counts, not cases), so the log carried no evidence that the new
code had been exercised at all.

Two mechanisms close that gap.

**A code fingerprint.** `tools/provenance.py` hashes every source file that
can influence a recorded run — the MoonBit sources, `moon.pkg`, the Python
reference, the harness and the test suite — and folds the hashes into one
digest. Every file **written by `tools/regenerate_evidence.sh`** — the 12
listed in §8 — carries it in its header, and `evidence/environment.txt` carries
it as `code-fp`. (The archived logs under `evidence/archive/` predate the
mechanism and carry no fingerprint — they are history, not evidence about the
current tree; each archive directory says so in its own README.)

```
# code fingerprint: <64 hex digits>
```

The exact digest is **not written here on purpose**: it changes with every
change to any participating file, so a value frozen into the README would be
stale (and unreproducible) the moment the tree changes. Print the one that
belongs to *your* tree with:

```
$ python3 tools/provenance.py --quiet
```

and compare it with the `# code fingerprint:` line of any log
(`grep -m1 'code fingerprint' evidence/bench.log`).

**The fingerprint is now *checked*, not just written.** Until the seventh review
it was recorded in every log and never compared with anything: editing one line
of `world.mbt` left all twelve logs stale while every gate stayed green. The
consistency gate now recomputes the digest of the current tree and refuses to
pass when a recorded log was produced by a different one:

```
$ printf '\n// probe\n' >> world.mbt     # MoonBit comments start with "//"
$ python3 tools/check_consistency.py --test-log evidence/moon_test.log --moon-exit 0
error: the recorded evidence and the README disagree:
  - evidence/bench.log was produced by a different source tree
    (recorded <recorded digest>…, current <current digest>…) — the evidence is
    stale, re-run tools/regenerate_evidence.sh
```

> The two digests above are shown as placeholders on purpose: they are
> recomputed on every run, so a frozen pair would be stale and unreproducible.
> The command above is the reproduction — the gate's exit code is the assertion.

A third mechanism protects the logs themselves. `evidence/MANIFEST.sha256`
lists the SHA-256 of every recorded log, and the consistency gate recomputes
those digests, so **editing a log without updating the manifest fails the
gate**. The limit is stated rather than hidden: a change that updates the log,
the manifest *and* the README consistently still passes — no check that
compares numbers can rule that out, because the benchmark figures are
load-dependent (see below) and therefore cannot be re-derived offline. What
the manifest does guarantee is that a log is bound to the tree state it was
committed with.

Two runs on the same tree produce the same digest, and any change to any
participating file changes it. The file list is enumerated explicitly on
purpose: a broad glob such as `**/moon.pkg` would also pick up the dependency
packages that `moon` downloads into `.mooncakes/`, which would make the
fingerprint change depending on whether the dependencies had been fetched yet.
`python3 tools/provenance.py --selftest` checks all of that (stability, no
forbidden directories, nothing outside the allowed set) and exits non-zero if
it regresses.

**An asserted test count.** What `moon test` actually does, measured on
MoonBit 0.1.20261119:

| Tree state | `moon test` | `moon check` |
|---|---|---|
| `moon.pkg` deleted | **exit 255** (`Cannot find import …`) | **exit 255** |
| only the *test file* deleted | **exit 0**, having found nothing at all | exit 0 |
| one assertion really fails | non-zero exit, **and the summary line is still printed** | exit 0 |

The summary line is therefore the only reliable signal, and a suite that
*fails* must not be able to hide behind a verdict of "nothing ran".
`tools/check_consistency.py` parses the summary and fails unless the count is
exactly what this README declares:

```
    [assert] moon test: 37 tests, 37 passed, 0 failed (README agrees)
```

It also fails if this README itself mentions a different count, so the document
and the suite cannot drift apart silently. **CI runs the same checker**
(`tools/check_consistency.py`), so the evidence script and CI cannot assert
different numbers — and the failure mode is a readable diagnostic, not a bare
non-zero exit:

```
error: 'moon test': total=37 passed=36 failed=1
       The suite did not pass — see the log for the failing test.
```

**What the checker now checks (all four, since the seventh review).** The
review found that each of these could be broken without turning any gate red,
so each now has its own failure:

| # | Check | What it stops |
|---|---|---|
| 1 | the suite's count vs. the declared count | a test file silently disappearing |
| 2 | the README's **prose** declaration vs. the declared count | rewriting the declaration into a form the scan does not see, and letting a fenced *example* stand in for a declaration |
| 3 | every recorded log's fingerprint vs. **this** tree | shipping stale evidence that was produced by older code |
| 4 | this README's benchmark and coverage numbers vs. the recorded logs | a table that no longer matches the logs it claims to summarise |

Check 2 is the subtle one: the gate used to scan the whole file, so a sample
output inside a fenced code block could satisfy it while the real sentence had been
rewritten. It now ignores fenced blocks and requires a declaration **in the
prose**; deleting or rewording that sentence is an error:

```
error: README drift: …/README.md declares no test count in its prose
       (no '<N> tests' phrase outside a fenced code block).
       A fenced example is not a declaration: the gate used to accept
       one, which let the real declaration be rewritten freely.
```

Checks 3 and 4 are what make the evidence a claim about *this* commit rather
than about some commit in the same repository.

> `moon.pkg` is **source**, not build output: it declares which imports belong
> to the `test` section, and it decides whether `moon test` finds the suite.
> Do not exclude it when copying the tree. (If it *is* missing, both `moon
> check` and `moon test` fail with exit 255 — they do not pass silently.)

---

## 5. Benchmarks

`moon bench` (MoonBit 0.1.20261119, x86-64 server, `wasm-gc` backend) measures
the merge paths — the operations that dominate the cost of a replicated
application, because a merge happens on every sync.

| Benchmark | Time (mean ± σ) |
|---|---|
| `gcounter merge` (1000 entries) | **110.89 µs ± 19.01 µs** |
| `orset merge` (1000 elements) | **326.60 µs ± 20.93 µs** |
| `orset add` (1000 sequential adds) | **14.98 ms ± 1.43 ms** |
| `lwwregister merge` (1000 keys) | **149.22 µs ± 18.88 µs** |

The benchmark names above are the ones `moon bench` prints. "1000 entries" means 1000
distinct replica keys (one increment each) — a counter with a single key would make the
merge O(1) and the benchmark meaningless. The measured values in this table are copied
verbatim from `evidence/bench.log`; regenerate them with `bash tools/regenerate_evidence.sh`.

> **Read them as one measurement, not as constants.** The machine is shared, and
> the absolute numbers move with its load — a re-run on a busy machine can come
> out more than twice as slow. The number that matters for a comparison is the
> one next to it in the *same* log: `evidence/bench.log` carries the run's code
> fingerprint, so a log can always be traced to the tree that produced it.
>
> The load the machine was under during this particular run is recorded in
> `evidence/environment.txt` as `load-average`. The server is shared with
> other people's work; this run was taken while its load average was around
> **120**, and the same code measured on the same tree at a load average around
> 51 came out roughly twice as fast. **If you re-run
> `bash tools/regenerate_evidence.sh`, update these four numbers in the same
> commit**, or the README will no longer match `evidence/bench.log` — the
> consistency gate in `tools/check_consistency.py` now checks exactly that.


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
* **The operation grammar uses tokens instead of decimal numbers.** The value
  table has **57** entries: `0` = 0, the letters `a` … `z` = 1 … 26, the
  uppercase letters `A` … `Z` = 27 … 52, and four symbol tokens (`!` = -1,
  `@` = -2, `[` = 2^31 - 1, `]` = 2^31). This removes *all* text-to-number
  parsing from the implementation that the differential test is supposed to
  validate — one less place for a parser bug to hide. Unit tests use plain
  integer literals and therefore cover the full numeric range.

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
├── CHANGELOG.md                 the update record: what changed in which version
├── tools/
│   ├── reference_crdt.py        reference implementation (Python)
│   ├── fuzz_diff.py             differential fuzzing harness with shrinking
│   ├── fault_injection.py       injects known defects, checks the harness fails
│   ├── coverage_report.py       measures whether the traffic reaches the branches
│   ├── provenance.py            computes the code fingerprint every log carries
│   ├── check_consistency.py     the one test-count / README consistency gate
│   └── regenerate_evidence.sh   regenerates this round's raw logs in evidence/
└── evidence/                    raw logs of the runs quoted above
    ├── bench.log
    ├── coverage_report.log
    ├── demo.log
    ├── environment.txt
    ├── fault_injection.log
    ├── fuzz_diff.seed42.log
    ├── fuzz_diff.seed777.log
    ├── fuzz_diff.seed20261124.log
    ├── fuzz_diff.seed31337.log
    ├── fuzz_summary.txt
    ├── moon_check.log
    ├── moon_test.log
    ├── MANIFEST.sha256          SHA-256 of every log above; the gate checks it
    └── archive/                 superseded runs, kept as audit history only
        ├── pre-round4-20261124/
        └── pre-fix-20261124/
```

`tools/regenerate_evidence.sh` regenerates **this round's** raw logs — the
twelve files listed under `evidence/` above (plus `MANIFEST.sha256`), and
nothing else. It does not
write anything under `evidence/archive/`: those directories hold superseded
runs that are kept as audit history, each with its own README saying why every
file in it is obsolete. `evidence/environment.txt` also records the commit of
the checkout the tree was copied from, when it is run inside one; when the
tree is not a checkout (a plain copy on the build server), it says so and
points at the code fingerprint, which is the authoritative identity of the
tree either way.

**Three of the twelve files are not byte-reproducible by nature**, and the
difference is understood rather than mysterious:

| File | Why a re-run can differ |
|---|---|
| `bench.log` | the timings move with the machine's load (see §5) |
| `environment.txt` | it records the run's timestamp |
| `moon_check.log` | its last line depends on the build cache: `ran 2 tasks, now up to date` on a fresh copy, `no work to do` on a re-run in the same tree |

The other nine are byte-identical across runs on the same tree.

**Where the update record lives.** `CHANGELOG.md` is the version-by-version
record of what changed; the commit history, the issues and the pull requests
carry the rest of it.

## 9. Author / 贡献者

**[kkkkikun](https://github.com/kkkkikun)** — 本仓库全部代码、测试、差分测试 harness 与文档均由该作者独立完成。

## 10. License

Apache-2.0 — see [LICENSE](LICENSE).
