///|
/// A runnable demonstration of the four CRDTs in this package.
///
/// It shows the three situations that actually matter for an offline-first
/// application:
///
///   1. **Disjoint edits merge without conflict** — two replicas edit
///      different things at the same time.
///   2. **Concurrent add vs. remove** — the add wins, and *both* replicas
///      agree on that after the merge.
///   3. **Concurrent writes to the same key** — a deterministic winner is
///      chosen, and it is the same winner on both replicas.
///
/// Run with:
/// ```
/// moon run cmd/main
/// ```

///|
fn main {
  println("=== moonbit-crdt ===")
  println("")

  // --- 1. G-Counter: two replicas count independently, then merge ---------
  println("[1] G-Counter — disjoint increments merge cleanly")
  let counter_a = @moonbit-crdt.GCounter::new().inc("A", 3)
  let counter_b = @moonbit-crdt.GCounter::new().inc("B", 5)
  let merged = @moonbit-crdt.GCounter::merge(counter_a, counter_b)
  println("  A = \{counter_a.canonical()} (value \{counter_a.value()})")
  println("  B = \{counter_b.canonical()} (value \{counter_b.value()})")
  println("  merged = \{merged.canonical()} (value \{merged.value()})")
  println("  -> no increment is lost, and the merge is order-independent")
  println("")

  // --- 2. PN-Counter: a counter that also supports decrements ------------
  println("[2] PN-Counter — increments and decrements coexist")
  let pn = @moonbit-crdt.PNCounter::new().pinc("A", 10).ninc("A", 4)
  println("  state = \{pn.canonical()}")
  println("  value = \{pn.value()} (10 increments - 4 decrements)")
  println("")

  // --- 3. OR-Set: concurrent add and remove, add wins --------------------
  println("[3] OR-Set — concurrent add vs. remove (add wins)")
  let set_a = @moonbit-crdt.ORSet::new().add("A", "lamp")
  let set_b = @moonbit-crdt.ORSet::new().remove("lamp")
  println("  A adds \"lamp\"   -> contains: \{set_a.contains("lamp")}")
  println("  B removes \"lamp\" -> contains: \{set_b.contains("lamp")}")
  let set_merged = @moonbit-crdt.ORSet::merge(set_a, set_b)
  println("  merged          -> contains: \{set_merged.contains("lamp")}")
  println("  -> the removal could not cancel an addition it never observed")
  println("")

  // --- 4. LWW-Register: concurrent writes to the same key ----------------
  println("[4] LWW-Register — concurrent writes, deterministic winner")
  let reg_a = @moonbit-crdt.LWWRegister::new().set("A", "theme", "light", 1000L, 0L)
  let reg_b = @moonbit-crdt.LWWRegister::new().set("B", "theme", "dark", 2000L, 0L)
  let reg_merged = @moonbit-crdt.LWWRegister::merge(reg_a, reg_b)
  println("  A writes \"light\" at t=1000")
  println("  B writes \"dark\"  at t=2000")
  let winner = match reg_merged.get("theme") {
    Some(v) => v
    None => "<none>"
  }
  println("  merged value = \{winner}")
  println("  (the same winner is chosen no matter which side merges first)")
  println("")

  println("Every merge above is commutative, associative and idempotent —")
  println("see crdt_test.mbt and the differential harness in tools/.")
}
