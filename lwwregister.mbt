///|
/// # LWW-Register (Last-Writer-Wins Register)
///
/// A replicated register holding one value per key, where concurrent writes
/// are resolved by a **total order on timestamps** rather than by arrival
/// order.
///
/// ## Semantics
///
/// * Each key maps to `(wall, counter, node, value)`:
///   `wall` is a logical wall-clock millisecond, `counter` breaks ties inside
///   the same millisecond on the same node, `node` is the replica id and
///   breaks the remaining ties.
/// * `merge` keeps, per key, the entry with the **greater timestamp**.
/// * Because `(wall, counter, node)` is a *total* order (the node id is
///   unique), the merge is deterministic — two replicas always pick the same
///   winner, and no value can be "lost" by a tie.
///
/// ## About the timestamp format
///
/// Each key maps to `(wall, counter, node, value)`.  The pair `(wall,
/// counter)` is the **shape** of a hybrid logical clock timestamp — a
/// millisecond wall clock plus a per-millisecond counter — but **this
/// library contains no clock**: `set()` takes `wall` and `counter` as
/// arguments, and producing them is the caller's job.
///
/// The caller is responsible for keeping the timestamps it publishes
/// monotonically increasing per replica.  A skewed clock that publishes a
/// `wall` value smaller than one it has already used can make a later write
/// lose against an earlier one — the register will converge, but it will
/// converge to the *older* value.
///
/// `wall` and `counter` are `Int64` rather than `Int`, because a millisecond
/// timestamp does not fit in MoonBit's 32-bit `Int`.
///
/// ## Algebraic guarantees
///
/// * **Commutative / Associative / Idempotent** merge
/// * **Convergent**: replicas that have seen the same writes agree.
pub struct LWWRegister {
  entries : Map[String, (Int64, Int64, String, String)]
}

///|
pub fn LWWRegister::new() -> LWWRegister {
  LWWRegister::{ entries: Map([]) }
}

///|
/// Total order on `(wall, counter, node, value)` tuples.
/// The `value` is never compared: it is payload, not part of the order.
///
/// ⚠️ The node id is compared with **`lexical_cmp`**, not with the built-in
/// `>`: MoonBit's default string comparison is *numeric-aware*
/// (`"node-10" > "node-2"` is **true** in MoonBit but **false** in Python),
/// so using it here would make two implementations of the same specification
/// elect **different winners** for the same concurrent writes.  The canonical
/// order is therefore spelled out explicitly — the same way `canonical.mbt`
/// does for the dot ordering.
pub fn LWWRegister::ts_greater(
  a : (Int64, Int64, String, String),
  b : (Int64, Int64, String, String),
) -> Bool {
  if a.0 != b.0 {
    return a.0 > b.0
  }
  if a.1 != b.1 {
    return a.1 > b.1
  }
  lexical_cmp(a.2, b.2) > 0
}

///|
pub fn LWWRegister::set(
  self : LWWRegister,
  node : String,
  key : String,
  value : String,
  wall : Int64,
  counter : Int64,
) -> LWWRegister {
  let entries = self.entries.copy()
  let ts = (wall, counter, node, value)
  match entries.get(key) {
    Some(old) => if LWWRegister::ts_greater(ts, old) {
      entries.set(key, ts)
    }
    None => entries.set(key, ts)
  }
  LWWRegister::{ entries: entries }
}

///|
pub fn LWWRegister::get(self : LWWRegister, key : String) -> String? {
  match self.entries.get(key) {
    Some((_, _, _, value)) => Some(value)
    None => None
  }
}

///|
pub fn LWWRegister::merge(a : LWWRegister, b : LWWRegister) -> LWWRegister {
  let entries = a.entries.copy()
  for (k, ts) in b.entries.iter() {
    match entries.get(k) {
      Some(old) => if LWWRegister::ts_greater(ts, old) {
        entries.set(k, ts)
      }
      None => entries.set(k, ts)
    }
  }
  LWWRegister::{ entries: entries }
}

///|
pub fn LWWRegister::canonical(self : LWWRegister) -> String {
  let pairs = []
  for (k, ts) in self.entries.iter() {
    pairs.push((k, "\{ts.0}.\{ts.1}.\{ts.2}=\{ts.3}"))
  }
  canonical_pairs(pairs)
}
