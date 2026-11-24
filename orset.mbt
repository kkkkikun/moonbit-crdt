///|
/// # OR-Set (Observed-Remove Set, add-wins) — **with durable removal**
///
/// A replicated set where an element can be added and removed concurrently on
/// different replicas, and **the add wins**.
///
/// ## Semantics
///
/// * Every `add` creates a **unique dot** `<replica>#<seq>`; the element is
///   associated with that dot.
/// * `remove(elem)` deletes **only the dots the removing replica has
///   observed** (observed-remove semantics).  A concurrent `add` on another
///   replica produces a *new* dot, which the remover has not observed, so the
///   element survives — this is exactly the *add-wins* behaviour.
/// * `merge` unions the dot sets of both replicas, unions the **tombstones**,
///   and then **drops every dot that some replica has tombstoned**.
/// * The element is present iff at least one *non-tombstoned* dot is attached
///   to it.
///
/// ## Why removal must be recorded (the bug this file used to have)
///
/// The first version of this file removed an element by simply dropping its
/// dots from the local table:
/// ```moonbit
/// match elems.get(elem) {
///   Some(_) => elems.set(elem, [])   // ← the removal was forgotten
///   None => ()
/// }
/// ```
/// `merge` was a plain union of dot sets, so **any replica that still held the
/// old dots resurrected the element on the next merge**.  Concretely:
///
/// ```
/// add A x      → A = x=A#0
/// rem A x      → A = x=          (removed)
/// merge A B    → A = x=A#0      ← x is back, on the replica that removed it
/// ```
///
/// That breaks the monotonicity of observed-remove semantics: a removal that
/// *was* observed by the remover must stay removed.  The fix is to keep the
/// removed dots as **tombstones** so the removal travels with the state.
///
/// ## Why dots instead of a plain set
///
/// A plain replicated set cannot decide what happens when one replica removes
/// an element while another concurrently adds it: the removal and the
/// addition carry no information about each other, so a deterministic merge
/// would have to pick one side and lose the other.  Attaching a unique dot to
/// every addition records *which* addition is being removed, which makes the
/// conflict resolvable without coordination.
///
/// ## Why the dot counters are merged too
///
/// The dot counter of a replica must never go backwards, otherwise the same
/// dot could be minted twice after a merge and the set would lose track of it.
/// Merging the counters with a point-wise maximum guarantees that.
///
/// ## Algebraic guarantees
///
/// * **Commutative / Associative / Idempotent** merge
///   (dot union + tombstone union + counter max)
/// * **Convergence**: any two replicas that have seen the same set of
///   operations end up with the same canonical state.
/// * **Removal durability**: once a replica has removed a dot it has observed,
///   that dot can never come back — not through a merge with a stale replica,
///   not through a later merge in the other direction.
pub struct ORSet {
  elems : Map[String, Array[String]]
  counters : Map[String, Int64]
  /// Elements whose dots have been removed, and the removed dots themselves.
  /// A tombstone is what makes a removal *durable*: it is merged like any
  /// other part of the state, so every replica learns that the dot is dead.
  tombstones : Map[String, Array[String]]
}

///|
pub fn ORSet::new() -> ORSet {
  ORSet::{ elems: Map([]), counters: Map([]), tombstones: Map([]) }
}

///|
pub fn ORSet::add(self : ORSet, replica : String, elem : String) -> ORSet {
  let seq = match self.counters.get(replica) {
    Some(v) => v
    None => 0L
  }
  let dot = replica + "#" + "\{seq}"
  let elems = self.elems.copy()
  match elems.get(elem) {
    Some(dots) => {
      let next = dots.copy()
      next.push(dot)
      elems.set(elem, next)
    }
    None => elems.set(elem, [dot])
  }
  let counters = self.counters.copy()
  counters.set(replica, seq + 1L)
  ORSet::{ elems: elems, counters: counters, tombstones: self.tombstones }
}

///|
pub fn ORSet::remove(self : ORSet, elem : String) -> ORSet {
  let elems = self.elems.copy()
  let tombstones = self.tombstones.copy()
  match elems.get(elem) {
    Some(dots) => {
      // Only the dots this replica has *observed* are removed.  They are moved
      // into the tombstone table instead of being forgotten, so the removal
      // survives every later merge.
      if dots.length() > 0 {
        let dead = match tombstones.get(elem) {
          Some(prev) => {
            let next = prev.copy()
            for dot in dots.iter() {
              if !next.contains(dot) {
                next.push(dot)
              }
            }
            next
          }
          None => dots.copy()
        }
        tombstones.set(elem, dead)
      }
      elems.set(elem, [])
    }
    None => ()
  }
  ORSet::{ elems: elems, counters: self.counters, tombstones: tombstones }
}

///|
pub fn ORSet::contains(self : ORSet, elem : String) -> Bool {
  match self.elems.get(elem) {
    Some(dots) => dots.length() > 0
    None => false
  }
}

///|
pub fn ORSet::merge(a : ORSet, b : ORSet) -> ORSet {
  let elems = a.elems.copy()
  for (elem, dots) in b.elems.iter() {
    match elems.get(elem) {
      Some(mine) => {
        let combined = mine.copy()
        for dot in dots.iter() {
          if !combined.contains(dot) {
            combined.push(dot)
          }
        }
        elems.set(elem, combined)
      }
      None => elems.set(elem, dots.copy())
    }
  }
  // Tombstones travel with the state — this is what makes removal durable.
  let tombstones = a.tombstones.copy()
  for (elem, dots) in b.tombstones.iter() {
    match tombstones.get(elem) {
      Some(mine) => {
        let combined = mine.copy()
        for dot in dots.iter() {
          if !combined.contains(dot) {
            combined.push(dot)
          }
        }
        tombstones.set(elem, combined)
      }
      None => tombstones.set(elem, dots.copy())
    }
  }
  // Drop every dot that any replica has tombstoned.
  // (Collect the keys first: the map must not be mutated while iterating it.)
  let keys = []
  for (elem, _) in elems.iter() {
    keys.push(elem)
  }
  for elem in keys.iter() {
    match tombstones.get(elem) {
      Some(dead) => {
        let dots = match elems.get(elem) {
          Some(d) => d
          None => []
        }
        let kept = []
        for dot in dots.iter() {
          if !dead.contains(dot) {
            kept.push(dot)
          }
        }
        elems.set(elem, kept)
      }
      None => ()
    }
  }
  let counters = a.counters.copy()
  for (replica, c) in b.counters.iter() {
    match counters.get(replica) {
      Some(mine) => if c > mine {
        counters.set(replica, c)
      }
      None => counters.set(replica, c)
    }
  }
  ORSet::{ elems: elems, counters: counters, tombstones: tombstones }
}

///|
pub fn ORSet::canonical(self : ORSet) -> String {
  let pairs = []
  for (elem, dots) in self.elems.iter() {
    let sorted_dots = sort_strings(dots)
    pairs.push((elem, join_with(sorted_dots, ",")))
  }
  let live = canonical_pairs(pairs)
  let dead_pairs = []
  for (elem, dots) in self.tombstones.iter() {
    let sorted_dots = sort_strings(dots)
    dead_pairs.push((elem, join_with(sorted_dots, ",")))
  }
  // The per-replica dot counters are part of the state: the invariant "a
  // counter never goes backwards" is only observable if they are rendered.
  let counter_pairs = []
  for (replica, c) in self.counters.iter() {
    counter_pairs.push((replica, "\{c}"))
  }
  live + "|" + canonical_pairs(dead_pairs) + "|" + canonical_pairs(counter_pairs)
}

