///|
/// Benchmarks for the merge paths — the operations that dominate the cost of
/// a replicated application (a merge happens on every sync).
///
/// Run with:
/// ```
/// moon bench
/// ```

///|
fn bench_gcounter(n : Int64) -> @moonbit-crdt.GCounter {
  // Distinct keys per replica: a counter with a single key would make the
  // merge O(1) and the benchmark meaningless.
  let mut c = @moonbit-crdt.GCounter::new()
  let mut i = 0L
  while i < n {
    c = c.inc("replica\{i}", 1L)
    i = i + 1L
  }
  c
}

///|
fn bench_orset(n : Int64) -> @moonbit-crdt.ORSet {
  let mut s = @moonbit-crdt.ORSet::new()
  let mut i = 0L
  while i < n {
    s = s.add("A", "elem\{i}")
    i = i + 1L
  }
  s
}

///|
test "bench gcounter merge (1000 entries)" (it : @bench.T) {
  let a = bench_gcounter(1000L)
  let b = bench_gcounter(1000L)
  it.bench(fn() {
    let merged = @moonbit-crdt.GCounter::merge(a, b)
    it.keep(merged)
  })
}

///|
test "bench orset merge (1000 elements)" (it : @bench.T) {
  let a = bench_orset(1000L)
  let b = bench_orset(1000L)
  it.bench(fn() {
    let merged = @moonbit-crdt.ORSet::merge(a, b)
    it.keep(merged)
  })
}

///|
test "bench orset add (1000 sequential adds)" (it : @bench.T) {
  it.bench(fn() {
    let s = bench_orset(1000L)
    it.keep(s)
  })
}

///|
test "bench lwwregister merge (1000 keys)" (it : @bench.T) {
  let mut a = @moonbit-crdt.LWWRegister::new()
  let mut b = @moonbit-crdt.LWWRegister::new()
  let mut i = 0L
  while i < 1000L {
    a = a.set("A", "k\{i}", "value", i, 0L)
    b = b.set("B", "k\{i}", "value", i, 0L)
    i = i + 1L
  }
  it.bench(fn() {
    let merged = @moonbit-crdt.LWWRegister::merge(a, b)
    it.keep(merged)
  })
}
