///|
/// # G-Counter (Grow-only Counter)
///
/// A monotonic counter that can be incremented on several replicas and merged
/// without coordination.
///
/// ## Semantics
///
/// * State is a map `replica -> count`.  A replica **only ever writes its own
///   key**, so no two replicas write the same key concurrently.
/// * `inc(replica, delta)` adds `delta` to that replica's own key.
/// * `merge` is the **point-wise maximum** over keys: `merge(a, b)[k] =
///   max(a[k], b[k])`.
/// * `value` is the sum of all keys.
///
/// ## Why point-wise max is the right merge
///
/// Because a replica never writes another replica's key, the value stored for
/// key `k` only ever grows, and it only grows at the owner of `k`.  Taking
/// the maximum therefore keeps the *newest* value for each key and discards
/// the stale one — no information is lost and no conflict can arise.
///
/// ## Algebraic guarantees (verified by the test-suite)
///
/// * **Commutative**: `merge(a, b) == merge(b, a)`
/// * **Associative**: `merge(merge(a, b), c) == merge(a, merge(b, c))`
/// * **Idempotent**: `merge(a, a) == a`
/// * **Monotonic**: `value(merge(a, b)) >= value(a)`
pub struct GCounter {
  counts : Map[String, Int64]
}

///|
pub fn GCounter::new() -> GCounter {
  GCounter::{ counts: Map([]) }
}

///|
pub fn GCounter::get(self : GCounter, replica : String) -> Int64 {
  match self.counts.get(replica) {
    Some(v) => v
    None => 0L
  }
}

///|
/// Increments the counter owned by `replica`.
///
/// A G-Counter is **grow-only**: negative deltas are rejected (ignored) on
/// purpose.  Allowing them would break the "the value of a replica only ever
/// grows" invariant that the point-wise-maximum merge relies on, and the
/// break is silent — a decrement on one replica could be undone by a later
/// merge, i.e. the counter would move *backwards* for reasons no replica can
/// explain.  Rejecting the input keeps the invariant true by construction.
pub fn GCounter::inc(self : GCounter, replica : String, delta : Int64) -> GCounter {
  if delta < 0L {
    return self
  }
  let counts = self.counts.copy()
  counts.set(replica, self.get(replica) + delta)
  GCounter::{ counts: counts }
}

///|
pub fn GCounter::merge(a : GCounter, b : GCounter) -> GCounter {
  let counts = a.counts.copy()
  for (k, v) in b.counts.iter() {
    match counts.get(k) {
      Some(old) => if v > old {
        counts.set(k, v)
      }
      None => counts.set(k, v)
    }
  }
  GCounter::{ counts: counts }
}

///|
pub fn GCounter::value(self : GCounter) -> Int64 {
  let mut total = 0L
  for (_, v) in self.counts.iter() {
    total = total + v
  }
  total
}

///|
pub fn GCounter::canonical(self : GCounter) -> String {
  let pairs = []
  for (k, v) in self.counts.iter() {
    pairs.push((k, "\{v}"))
  }
  canonical_pairs(pairs)
}
