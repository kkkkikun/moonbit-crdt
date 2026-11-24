///|
/// # PN-Counter (Positive-Negative Counter)
///
/// A counter that supports both increments and decrements, built from two
/// G-Counters: a *positive* one and a *negative* one.
///
/// ## Semantics
///
/// * `pinc(replica, delta)` increments the positive G-Counter.
/// * `ninc(replica, delta)` increments the negative G-Counter.
/// * `merge` merges both halves independently.
/// * `value = positive.value() - negative.value()`.
///
/// ## Why two counters instead of one signed counter
///
/// A single signed counter would need a merge rule that knows which side
/// "won", which is exactly the conflict a CRDT must avoid.  Splitting the
/// state into two grow-only halves removes the conflict entirely: each half
/// is conflict-free by construction, and subtraction happens only at read
/// time on a single replica.
///
/// ## Algebraic guarantees
///
/// Same as `GCounter` for commutativity / associativity / idempotence of
/// `merge`; additionally the **value is invariant under merging**: merging a
/// replica with a stale copy can never change the merged value.
pub struct PNCounter {
  pos : GCounter
  neg : GCounter
}

///|
pub fn PNCounter::new() -> PNCounter {
  PNCounter::{ pos: GCounter::new(), neg: GCounter::new() }
}

///|
///|
/// Increments the positive half.  Negative deltas are rejected, see
/// `GCounter::inc`.
pub fn PNCounter::pinc(self : PNCounter, replica : String, delta : Int64) -> PNCounter {
  PNCounter::{ pos: self.pos.inc(replica, delta), neg: self.neg }
}

///|
///|
/// Increments the negative half.  Negative deltas are rejected, see
/// `GCounter::inc`.
pub fn PNCounter::ninc(self : PNCounter, replica : String, delta : Int64) -> PNCounter {
  PNCounter::{ pos: self.pos, neg: self.neg.inc(replica, delta) }
}

///|
pub fn PNCounter::merge(a : PNCounter, b : PNCounter) -> PNCounter {
  PNCounter::{
    pos: GCounter::merge(a.pos, b.pos),
    neg: GCounter::merge(a.neg, b.neg),
  }
}

///|
pub fn PNCounter::value(self : PNCounter) -> Int64 {
  self.pos.value() - self.neg.value()
}

///|
pub fn PNCounter::canonical(self : PNCounter) -> String {
  "p=" + self.pos.canonical() + "|n=" + self.neg.canonical()
}
