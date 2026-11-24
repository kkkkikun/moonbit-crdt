///|
/// # OR-Set (Observed-Remove Set, add-wins)
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
/// * `merge` unions the dot sets of both replicas and takes the point-wise
///   maximum of the per-replica dot counters.
/// * The element is present iff at least one dot is attached to it.
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
/// * **Commutative / Associative / Idempotent** merge (dot union + counter max)
/// * **Convergence**: any two replicas that have seen the same set of
///   operations end up with the same canonical state.
pub struct ORSet {
  elems : Map[String, Array[String]]
  counters : Map[String, Int64]
}

///|
pub fn ORSet::new() -> ORSet {
  ORSet::{ elems: Map([]), counters: Map([]) }
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
  ORSet::{ elems: elems, counters: counters }
}

///|
pub fn ORSet::remove(self : ORSet, elem : String) -> ORSet {
  let elems = self.elems.copy()
  match elems.get(elem) {
    Some(_) => elems.set(elem, [])
    None => ()
  }
  ORSet::{ elems: elems, counters: self.counters }
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
  let counters = a.counters.copy()
  for (replica, c) in b.counters.iter() {
    match counters.get(replica) {
      Some(mine) => if c > mine {
        counters.set(replica, c)
      }
      None => counters.set(replica, c)
    }
  }
  ORSet::{ elems: elems, counters: counters }
}

///|
pub fn ORSet::canonical(self : ORSet) -> String {
  let pairs = []
  for (elem, dots) in self.elems.iter() {
    let sorted_dots = sort_strings(dots)
    pairs.push((elem, join_with(sorted_dots, ",")))
  }
  canonical_pairs(pairs)
}
