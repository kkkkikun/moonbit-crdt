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
///   3. **An observed removal is durable** — merging with a stale replica
///      does *not* bring the removed element back.
///   4. **Concurrent writes to the same key** — a deterministic winner is
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

  // --- 3. OR-Set: a concurrent add wins, an observed removal is durable --
  println("[3] OR-Set — a concurrent add wins, but an observed removal is durable")
  println("  canonical form = <live dots>|<tombstoned dots>|<dot counters>")

  // (a) Genuine add-wins.  B has *observed* A's first dot (A#0) and removes
  //     the element; A concurrently adds the same element again (A#1) — a dot
  //     B has never seen.  The removal kills A#0 (it is now a tombstone); the
  //     unobserved concurrent add survives.
  let a_first = @moonbit-crdt.ORSet::new().add("A", "lamp")
  let b_seen = @moonbit-crdt.ORSet::merge(@moonbit-crdt.ORSet::new(), a_first)
  let a_concurrent = @moonbit-crdt.ORSet::add(a_first, "A", "lamp")
  let b_removed = @moonbit-crdt.ORSet::remove(b_seen, "lamp")
  let merged_addwins = @moonbit-crdt.ORSet::merge(a_concurrent, b_removed)
  println("  (a) add-wins — B removed the dot it had seen; A added a dot B never saw")
  println("      A          = \{a_concurrent.canonical()}")
  println("      B          = \{b_removed.canonical()}")
  println("      merged     = \{merged_addwins.canonical()}")
  println("      contains   = \{merged_addwins.contains("lamp")}  <- the concurrent add won")
  println("")

  // (b) Durable removal.  A removes a dot it has observed, then merges with B,
  //     which still holds that old dot.  The element must NOT come back — the
  //     tombstone travels with the state.
  let c_first = @moonbit-crdt.ORSet::new().add("A", "desk")
  let d_stale = @moonbit-crdt.ORSet::merge(@moonbit-crdt.ORSet::new(), c_first)
  let c_removed = @moonbit-crdt.ORSet::remove(c_first, "desk")
  let merged_durable = @moonbit-crdt.ORSet::merge(c_removed, d_stale)
  let merged_durable_rev = @moonbit-crdt.ORSet::merge(d_stale, c_removed)
  println("  (b) durable removal — A removed a dot it had observed; B still holds it")
  println("      A          = \{c_removed.canonical()}")
  println("      B (stale)  = \{d_stale.canonical()}")
  println("      merged     = \{merged_durable.canonical()}")
  println("      contains   = \{merged_durable.contains("desk")} / \{merged_durable_rev.contains("desk")}  <- not resurrected")
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

  println("Every merge above is commutative, associative and idempotent,")
  println("under the preconditions stated in the README (distinct node ids,")
  println("each replica writing only its own counter key).")
  println("see crdt_test.mbt and the differential harness in tools/.")
}
