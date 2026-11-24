// Unit tests and property tests for the CRDT implementations.
//
// The property tests use the `quickcheck` package that ships with MoonBit's
// standard library.  Every property is stated over *random* inputs and is
// checked over many generated cases (fixed seed → reproducible runs).
//
// Test scope:
//   * unit tests pin down the concrete semantics of every operation;
//   * property tests pin down the *algebraic* guarantees that make a CRDT
//     usable: commutativity, associativity, idempotence, monotonicity and
//     convergence.

///|
/// Safe element access: QuickCheck generates arrays whose length varies from
/// zero upwards, so indexing `xs[i]` directly would panic on short arrays.
/// Missing elements are treated as `0`, which keeps every property meaningful
/// for every generated size.
fn nth(xs : Array[Int32], i : Int32) -> Int64 {
  if i >= 0 && i < xs.length() {
    xs[i].to_int64()
  } else {
    0L
  }
}

///|
test "gcounter: increment accumulates per replica" {
  let c = @moonbit-crdt.GCounter::new().inc("A", 3L).inc("A", 2L)
  assert_eq(c.get("A"), 5L)
  assert_eq(c.get("B"), 0L)
  assert_eq(c.value(), 5L)
}

///|
test "gcounter: merge takes the point-wise maximum" {
  let a = @moonbit-crdt.GCounter::new().inc("A", 5L)
  let b = @moonbit-crdt.GCounter::new().inc("A", 2L).inc("B", 7L)
  let merged = @moonbit-crdt.GCounter::merge(a, b)
  assert_eq(merged.get("A"), 5L)
  assert_eq(merged.get("B"), 7L)
  assert_eq(merged.value(), 12L)
}

///|
test "gcounter: canonical form is stable and sorted" {
  let a = @moonbit-crdt.GCounter::new().inc("B", 1L).inc("A", 2L)
  assert_eq(a.canonical(), "A=2;B=1")
}

///|
test "gcounter: negative increments are rejected (grow-only invariant)" {
  let c = @moonbit-crdt.GCounter::new().inc("A", 5L).inc("A", -3L)
  assert_eq(c.get("A"), 5L)
}

///|
test "pncounter: value is positive minus negative" {
  let c = @moonbit-crdt.PNCounter::new().pinc("A", 10L).ninc("A", 3L)
  assert_eq(c.value(), 7L)
}

///|
test "pncounter: merge keeps both halves independent" {
  let a = @moonbit-crdt.PNCounter::new().pinc("A", 4L)
  let b = @moonbit-crdt.PNCounter::new().ninc("B", 2L).pinc("B", 1L)
  let merged = @moonbit-crdt.PNCounter::merge(a, b)
  assert_eq(merged.value(), 3L)
}

///|
test "orset: add then remove hides the element" {
  let s = @moonbit-crdt.ORSet::new().add("A", "x")
  assert_true(s.contains("x"))
  let removed = s.remove("x")
  assert_false(removed.contains("x"))
}

///|
test "orset: add-wins — a concurrent add survives a remove" {
  // Replica A adds "x"; replica B removes "x" but has not observed A's dot,
  // so the removal cannot cancel the addition.
  let a = @moonbit-crdt.ORSet::new().add("A", "x")
  let b = @moonbit-crdt.ORSet::new().remove("x")
  let merged = @moonbit-crdt.ORSet::merge(a, b)
  assert_true(merged.contains("x"))
}

///|
test "orset: dots are unique per replica and per operation" {
  let a = @moonbit-crdt.ORSet::new().add("A", "x").add("A", "x")
  assert_eq(a.canonical(), "x=A#0,A#1")
}

///|
test "lwwregister: the greater timestamp wins" {
  let a = @moonbit-crdt.LWWRegister::new().set("A", "k", "old", 100L, 0L)
  let b = @moonbit-crdt.LWWRegister::new().set("B", "k", "new", 200L, 0L)
  assert_eq(@moonbit-crdt.LWWRegister::merge(a, b).get("k"), Some("new"))
  assert_eq(@moonbit-crdt.LWWRegister::merge(b, a).get("k"), Some("new"))
}

///|
test "lwwregister: the node id breaks timestamp ties deterministically" {
  let a = @moonbit-crdt.LWWRegister::new().set("A", "k", "from-a", 100L, 0L)
  let b = @moonbit-crdt.LWWRegister::new().set("B", "k", "from-b", 100L, 0L)
  // "B" > "A", so B wins — and both replicas agree on that.
  assert_eq(@moonbit-crdt.LWWRegister::merge(a, b).get("k"), Some("from-b"))
  assert_eq(@moonbit-crdt.LWWRegister::merge(b, a).get("k"), Some("from-b"))
}

///|
test "lwwregister: a stale write never overwrites a newer one" {
  let newer = @moonbit-crdt.LWWRegister::new().set("A", "k", "newer", 200L, 0L)
  let older = @moonbit-crdt.LWWRegister::new().set("B", "k", "older", 100L, 0L)
  assert_eq(@moonbit-crdt.LWWRegister::merge(newer, older).get("k"), Some("newer"))
}

// ---------------------------------------------------------------------------
// Property tests
// ---------------------------------------------------------------------------

///|
test "property: gcounter merge is commutative" {
  @quickcheck.check((xs : Array[Int32]) => {
    let a = @moonbit-crdt.GCounter::new().inc("A", nth(xs, 0)).inc("B", nth(xs, 1))
    let b = @moonbit-crdt.GCounter::new().inc("A", nth(xs, 2)).inc("C", nth(xs, 3))
    @moonbit-crdt.GCounter::merge(a, b).canonical() ==
    @moonbit-crdt.GCounter::merge(b, a).canonical()
  })
}

///|
test "property: gcounter merge is associative" {
  @quickcheck.check((xs : Array[Int32]) => {
    let a = @moonbit-crdt.GCounter::new().inc("A", nth(xs, 0))
    let b = @moonbit-crdt.GCounter::new().inc("B", nth(xs, 1))
    let c = @moonbit-crdt.GCounter::new().inc("C", nth(xs, 2))
    let left = @moonbit-crdt.GCounter::merge(@moonbit-crdt.GCounter::merge(a, b), c)
    let right = @moonbit-crdt.GCounter::merge(a, @moonbit-crdt.GCounter::merge(b, c))
    left.canonical() == right.canonical()
  })
}

///|
test "property: gcounter merge is idempotent" {
  @quickcheck.check((xs : Array[Int32]) => {
    let a = @moonbit-crdt.GCounter::new().inc("A", nth(xs, 0)).inc("B", nth(xs, 1))
    @moonbit-crdt.GCounter::merge(a, a).canonical() == a.canonical()
  })
}

///|
test "property: gcounter value never decreases when merging" {
  @quickcheck.check((xs : Array[Int32]) => {
    let a = @moonbit-crdt.GCounter::new().inc("A", nth(xs, 0))
    let b = @moonbit-crdt.GCounter::new().inc("A", nth(xs, 1)).inc("B", nth(xs, 2))
    @moonbit-crdt.GCounter::merge(a, b).value() >= a.value()
  })
}

///|
test "property: pncounter merge is commutative and idempotent" {
  @quickcheck.check((xs : Array[Int32]) => {
    let a = @moonbit-crdt.PNCounter::new().pinc("A", nth(xs, 0)).ninc("A", nth(xs, 1))
    let b = @moonbit-crdt.PNCounter::new().pinc("B", nth(xs, 2)).ninc("B", nth(xs, 3))
    @moonbit-crdt.GCounter::merge(a.pos, b.pos).canonical() ==
    @moonbit-crdt.GCounter::merge(b.pos, a.pos).canonical() &&
    @moonbit-crdt.GCounter::merge(a.neg, b.neg).canonical() ==
    @moonbit-crdt.GCounter::merge(b.neg, a.neg).canonical() &&
    @moonbit-crdt.PNCounter::merge(a, a).canonical() == a.canonical()
  })
}

///|
test "property: orset merge is commutative" {
  @quickcheck.check((xs : Array[Int32]) => {
    let e1 = if nth(xs, 0) % 2 == 0 { "x" } else { "p" }
    let e2 = if nth(xs, 1) % 2 == 0 { "y" } else { "q" }
    let a = @moonbit-crdt.ORSet::new().add("A", e1).add("A", e2)
    let b = @moonbit-crdt.ORSet::new().add("B", e2).add("B", e1)
    @moonbit-crdt.ORSet::merge(a, b).canonical() ==
    @moonbit-crdt.ORSet::merge(b, a).canonical()
  })
}

///|
test "property: orset merge is idempotent" {
  @quickcheck.check((xs : Array[Int32]) => {
    let e1 = if nth(xs, 0) % 2 == 0 { "x" } else { "p" }
    let a = @moonbit-crdt.ORSet::new().add("A", e1).remove(e1).add("A", "z")
    @moonbit-crdt.ORSet::merge(a, a).canonical() == a.canonical()
  })
}

///|
test "property: orset convergence — replicas that saw the same ops agree" {
  @quickcheck.check((xs : Array[Int32]) => {
    // A and B each add "x"; merging in either direction must converge.
    let e1 = if nth(xs, 0) % 2 == 0 { "x" } else { "p" }
    let a = @moonbit-crdt.ORSet::new().add("A", e1)
    let b = @moonbit-crdt.ORSet::new().add("B", e1)
    let ab = @moonbit-crdt.ORSet::merge(a, b)
    let ba = @moonbit-crdt.ORSet::merge(b, a)
    ab.canonical() == ba.canonical() && ab.contains(e1) && ba.contains(e1)
  })
}

///|
/// Mirrors the library's total order on `(wall, counter, node)`: the node id
/// is the last tie-break, so with equal timestamps "B" beats "A".
fn lww_wins_a(wall_a : Int64, wall_b : Int64) -> Bool {
  if wall_a != wall_b {
    wall_a > wall_b
  } else {
    false
  }
}

///|
test "property: lwwregister merge is commutative and keeps the maximum" {
  @quickcheck.check((xs : Array[Int32]) => {
    let a = @moonbit-crdt.LWWRegister::new().set("A", "k", "a", nth(xs, 0), 0L)
    let b = @moonbit-crdt.LWWRegister::new().set("B", "k", "b", nth(xs, 1), 0L)
    let ab = @moonbit-crdt.LWWRegister::merge(a, b)
    let ba = @moonbit-crdt.LWWRegister::merge(b, a)
    ab.canonical() == ba.canonical() &&
    ab.get("k") == Some(if lww_wins_a(nth(xs, 0), nth(xs, 1)) { "a" } else { "b" })
  })
}

///|
test "property: world replay is deterministic" {
  @quickcheck.check((xs : Array[Int32]) => {
    let delta = if nth(xs, 0) % 2 == 0 { "a" } else { "z" }
    let ops = [["inc", "A", delta], ["inc", "B", "b"], ["merge", "A", "B"]]
    let mut w1 = @moonbit-crdt.GCounterWorld::new()
    let mut w2 = @moonbit-crdt.GCounterWorld::new()
    for op in ops.iter() {
      w1 = w1.apply(op)
    }
    for op in ops.iter() {
      w2 = w2.apply(op)
    }
    w1.canonical() == w2.canonical()
  })
}

// ---------------------------------------------------------------------------
// Regression tests
//
// Every test below pins down a defect that was found by the cross-implementation
// differential harness (tools/fuzz_diff.py) or by the property tests, and that
// has been fixed.  They are kept so that the bug cannot come back silently.
// ---------------------------------------------------------------------------

///|
/// REGRESSION (differential harness): `merge` operations carry three tokens,
/// while `set` carries six.  An arity guard of "< 5" silently dropped every
/// merge, so the LWW world never actually merged anything.
test "regression: lww world applies merge operations" {
  let mut w = @moonbit-crdt.LWWWorld::new()
  w = w.apply(["set", "A", "k", "v", "a", "b"])
  w = w.apply(["set", "B", "k", "w", "c", "d"])
  w = w.apply(["merge", "A", "B"])
  // B's write has the greater timestamp, so A must now see it.
  assert_eq(w.canonical(), "A=k=3.4.B=w;B=k=3.4.B=w")
}

///|
/// REGRESSION (differential harness): a merge *source* that does not exist is
/// read but not published — a replica shows up in the canonical output only
/// if some operation wrote to it or merged into it.
test "regression: merging from an unknown replica does not publish it" {
  let mut w = @moonbit-crdt.LWWWorld::new()
  w = w.apply(["merge", "A", "C"])
  assert_eq(w.canonical(), "A=")
}

///|
/// REGRESSION (property test): a G-Counter is grow-only.  A negative delta
/// used to be applied, which let the total value *decrease* after a merge.
test "regression: gcounter rejects negative deltas" {
  let a = @moonbit-crdt.GCounter::new().inc("A", 10L)
  let b = @moonbit-crdt.GCounter::new().inc("A", -100L).inc("B", 5L)
  let merged = @moonbit-crdt.GCounter::merge(a, b)
  assert_eq(merged.get("A"), 10L)
  assert_eq(merged.value(), 15L)
}

///|
/// REGRESSION (property test): the LWW tie-break is the node id, so with equal
/// timestamps "B" wins — on every replica, in both merge directions.
test "regression: lww tie-break is the node id" {
  let a = @moonbit-crdt.LWWRegister::new().set("A", "k", "a", 5L, 0L)
  let b = @moonbit-crdt.LWWRegister::new().set("B", "k", "b", 5L, 0L)
  assert_eq(@moonbit-crdt.LWWRegister::merge(a, b).get("k"), Some("b"))
  assert_eq(@moonbit-crdt.LWWRegister::merge(b, a).get("k"), Some("b"))
}

///|
/// REGRESSION (differential harness): MoonBit's built-in string comparison is
/// numeric-aware ("C#10" < "C#2" is false), while Python's is lexicographic.
/// The canonical order is therefore defined explicitly — UTF-16 code unit
/// order — on both sides.  Without this, two implementations would order the
/// same dots differently and every comparison would fail.
test "regression: canonical order is plain lexicographic, not numeric-aware" {
  assert_true(@moonbit-crdt.lexical_cmp("C#10", "C#2") < 0)
  assert_true(@moonbit-crdt.lexical_cmp("C#2", "C#10") > 0)
  assert_eq(@moonbit-crdt.lexical_cmp("abc", "abc"), 0)
  // and the sorted order follows that definition
  let sorted = @moonbit-crdt.sort_strings(["C#10", "C#2", "C#1"])
  assert_eq(sorted[0], "C#1")
  assert_eq(sorted[1], "C#10")
  assert_eq(sorted[2], "C#2")
}
