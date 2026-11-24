///|
/// Replay engine CLI.
///
/// Reads **case streams** from the command line and prints the canonical
/// state of each case.  One case = one argument:
///
/// ```
/// <family>|<name>|<op>;<op>;…
/// ```
///
/// The point of this program is that it can be driven by a *different*
/// implementation of the same semantics: `tools/fuzz_diff.py` generates random
/// case streams, computes the expected canonical state with an independent
/// Python reference implementation, and compares the two.  A mismatch means
/// the MoonBit implementation and the reference disagree — i.e. a bug.
///
/// Usage:
/// ```
/// moon run cmd/replay -- "gcounter|case-1|inc A a;inc B b;merge A B"
/// ```

///|
fn split_to_strings(s : String, sep : String) -> Array[String] {
  let out = []
  for part in s.split(sep).iter() {
    out.push(part.to_owned())
  }
  out
}

///|
fn run_case(family : String, name : String, ops : Array[Array[String]]) -> String {
  if family == "gcounter" {
    let mut world = @moonbit-crdt.GCounterWorld::new()
    for op in ops.iter() {
      world = world.apply(op)
    }
    return name + "|" + world.canonical()
  }
  if family == "pncounter" {
    let mut world = @moonbit-crdt.PNCounterWorld::new()
    for op in ops.iter() {
      world = world.apply(op)
    }
    return name + "|" + world.canonical()
  }
  if family == "orset" {
    let mut world = @moonbit-crdt.ORSetWorld::new()
    for op in ops.iter() {
      world = world.apply(op)
    }
    return name + "|" + world.canonical()
  }
  if family == "lww" {
    let mut world = @moonbit-crdt.LWWWorld::new()
    for op in ops.iter() {
      world = world.apply(op)
    }
    return name + "|" + world.canonical()
  }
  name + "|ERROR:unknown-family:" + family
}

///|
fn main {
  let args = @env.args()
  let mut i = 1
  while i < args.length() {
    let case = args[i]
    let parts = split_to_strings(case, "|")
    if parts.length() >= 3 {
      let family = parts[0]
      let name = parts[1]
      let raw_ops = split_to_strings(parts[2], ";")
      let ops = []
      for raw in raw_ops.iter() {
        ops.push(split_to_strings(raw, " "))
      }
      println(run_case(family, name, ops))
    }
    i = i + 1
  }
}
