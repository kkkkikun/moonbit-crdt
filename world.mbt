///|
/// # Replica world models
///
/// Each `*World` type models **a set of replicas** holding one CRDT value
/// each, and knows how to apply an *operation* to it.  The operations are
/// encoded as plain text so that the same operation stream can be replayed by
/// the MoonBit implementation **and** by an independent reference
/// implementation written in another language — that is the whole point of
/// the differential harness in `tools/`.
///
/// ## Operation grammar (one line = one operation)
///
/// ```
/// inc   <replica> <delta>     G-Counter increment   (delta is a letter: a=1 … z=26)
/// pinc  <replica> <delta>     PN-Counter increment
/// ninc  <replica> <delta>     PN-Counter decrement
/// add   <replica> <element>   OR-Set add
/// rem   <replica> <element>   OR-Set remove (observed dots only)
/// set   <replica> <key> <value> <wall> <counter>   LWW-Register write
/// merge <target> <source>     merge source into target
/// ```
///
/// Numbers are encoded as **letters** rather than decimal digits on purpose:
/// it keeps the operation stream free of any text-to-number parsing in the
/// MoonBit implementation, which removes a whole class of parsing bugs from
/// the thing the differential test is supposed to validate.  The values are
/// still fully covered by the unit tests, which use plain integer literals.

///|
/// Decodes the letter encoding used by the operation grammar.
pub fn letter_to_int(s : String) -> Int64 {
  if s == "0" {
    return 0L
  }
  if s == "a" {
    return 1L
  }
  if s == "b" {
    return 2L
  }
  if s == "c" {
    return 3L
  }
  if s == "d" {
    return 4L
  }
  if s == "e" {
    return 5L
  }
  if s == "f" {
    return 6L
  }
  if s == "g" {
    return 7L
  }
  if s == "h" {
    return 8L
  }
  if s == "i" {
    return 9L
  }
  if s == "j" {
    return 10L
  }
  if s == "k" {
    return 11L
  }
  if s == "l" {
    return 12L
  }
  if s == "m" {
    return 13L
  }
  if s == "n" {
    return 14L
  }
  if s == "o" {
    return 15L
  }
  if s == "p" {
    return 16L
  }
  if s == "q" {
    return 17L
  }
  if s == "r" {
    return 18L
  }
  if s == "s" {
    return 19L
  }
  if s == "t" {
    return 20L
  }
  if s == "u" {
    return 21L
  }
  if s == "v" {
    return 22L
  }
  if s == "w" {
    return 23L
  }
  if s == "x" {
    return 24L
  }
  if s == "y" {
    return 25L
  }
  if s == "z" {
    return 26L
  }
  0L
}

///|
/// Renders a world (one value per replica) canonically:
/// `replica=<state>;replica=<state>` with replicas sorted by name.
pub fn canonical_world(states : Array[(String, String)]) -> String {
  let pairs = []
  for (name, state) in states.iter() {
    pairs.push((name, state))
  }
  canonical_pairs(pairs)
}

///|
pub struct GCounterWorld {
  replicas : Map[String, GCounter]
}

///|
pub fn GCounterWorld::new() -> GCounterWorld {
  GCounterWorld::{ replicas: Map([]) }
}

///|
pub fn GCounterWorld::apply(self : GCounterWorld, op : Array[String]) -> GCounterWorld {
  if op.length() < 3 {
    return self
  }
  let replicas = self.replicas.copy()
  let cmd = op[0]
  if cmd == "inc" {
    let replica = op[1]
    let delta = letter_to_int(op[2])
    let current = match replicas.get(replica) {
      Some(c) => c
      None => GCounter::new()
    }
    replicas.set(replica, current.inc(replica, delta))
  } else if cmd == "merge" {
    let target = op[1]
    let source = op[2]
    let t = match replicas.get(target) {
      Some(c) => c
      None => GCounter::new()
    }
    let s = match replicas.get(source) {
      Some(c) => c
      None => GCounter::new()
    }
    replicas.set(target, GCounter::merge(t, s))
  } else {
    return self
  }
  GCounterWorld::{ replicas: replicas }
}

///|
pub fn GCounterWorld::canonical(self : GCounterWorld) -> String {
  let states = []
  for (name, counter) in self.replicas.iter() {
    states.push((name, counter.canonical()))
  }
  canonical_world(states)
}

///|
pub struct PNCounterWorld {
  replicas : Map[String, PNCounter]
}

///|
pub fn PNCounterWorld::new() -> PNCounterWorld {
  PNCounterWorld::{ replicas: Map([]) }
}

///|
pub fn PNCounterWorld::apply(self : PNCounterWorld, op : Array[String]) -> PNCounterWorld {
  if op.length() < 3 {
    return self
  }
  let replicas = self.replicas.copy()
  let cmd = op[0]
  if cmd == "pinc" {
    let replica = op[1]
    let delta = letter_to_int(op[2])
    let current = match replicas.get(replica) {
      Some(c) => c
      None => PNCounter::new()
    }
    replicas.set(replica, current.pinc(replica, delta))
  } else if cmd == "ninc" {
    let replica = op[1]
    let delta = letter_to_int(op[2])
    let current = match replicas.get(replica) {
      Some(c) => c
      None => PNCounter::new()
    }
    replicas.set(replica, current.ninc(replica, delta))
  } else if cmd == "merge" {
    let target = op[1]
    let source = op[2]
    let t = match replicas.get(target) {
      Some(c) => c
      None => PNCounter::new()
    }
    let s = match replicas.get(source) {
      Some(c) => c
      None => PNCounter::new()
    }
    replicas.set(target, PNCounter::merge(t, s))
  } else {
    return self
  }
  PNCounterWorld::{ replicas: replicas }
}

///|
pub fn PNCounterWorld::canonical(self : PNCounterWorld) -> String {
  let states = []
  for (name, counter) in self.replicas.iter() {
    states.push((name, counter.canonical()))
  }
  canonical_world(states)
}

///|
pub struct ORSetWorld {
  replicas : Map[String, ORSet]
}

///|
pub fn ORSetWorld::new() -> ORSetWorld {
  ORSetWorld::{ replicas: Map([]) }
}

///|
pub fn ORSetWorld::apply(self : ORSetWorld, op : Array[String]) -> ORSetWorld {
  if op.length() < 3 {
    return self
  }
  let replicas = self.replicas.copy()
  let cmd = op[0]
  if cmd == "add" {
    let replica = op[1]
    let elem = op[2]
    let current = match replicas.get(replica) {
      Some(s) => s
      None => ORSet::new()
    }
    replicas.set(replica, current.add(replica, elem))
  } else if cmd == "rem" {
    let replica = op[1]
    let elem = op[2]
    let current = match replicas.get(replica) {
      Some(s) => s
      None => ORSet::new()
    }
    replicas.set(replica, current.remove(elem))
  } else if cmd == "merge" {
    let target = op[1]
    let source = op[2]
    let t = match replicas.get(target) {
      Some(s) => s
      None => ORSet::new()
    }
    let s = match replicas.get(source) {
      Some(s) => s
      None => ORSet::new()
    }
    replicas.set(target, ORSet::merge(t, s))
  } else {
    return self
  }
  ORSetWorld::{ replicas: replicas }
}

///|
pub fn ORSetWorld::canonical(self : ORSetWorld) -> String {
  let states = []
  for (name, set) in self.replicas.iter() {
    states.push((name, set.canonical()))
  }
  canonical_world(states)
}

///|
pub struct LWWWorld {
  replicas : Map[String, LWWRegister]
}

///|
pub fn LWWWorld::new() -> LWWWorld {
  LWWWorld::{ replicas: Map([]) }
}

///|
pub fn LWWWorld::apply(self : LWWWorld, op : Array[String]) -> LWWWorld {
  // NOTE: the minimum arity is 3 (`merge <target> <source>`); a `set`
  // operation needs 6 tokens and is checked separately below.  An earlier
  // version of this guard required 5 tokens, which silently dropped **every**
  // merge operation — the cross-implementation differential harness is what
  // caught it (see tools/fuzz_diff.py and the README's "bugs found" section).
  if op.length() < 3 {
    return self
  }
  let replicas = self.replicas.copy()
  let cmd = op[0]
  if cmd == "set" && op.length() >= 6 {
    let replica = op[1]
    let key = op[2]
    let value = op[3]
    let wall = letter_to_int(op[4])
    let counter = letter_to_int(op[5])
    let current = match replicas.get(replica) {
      Some(r) => r
      None => LWWRegister::new()
    }
    replicas.set(replica, current.set(replica, key, value, wall, counter))
  } else if cmd == "merge" {
    let target = op[1]
    let source = op[2]
    let t = match replicas.get(target) {
      Some(r) => r
      None => LWWRegister::new()
    }
    let s = match replicas.get(source) {
      Some(r) => r
      None => LWWRegister::new()
    }
    replicas.set(target, LWWRegister::merge(t, s))
  } else {
    return self
  }
  LWWWorld::{ replicas: replicas }
}

///|
pub fn LWWWorld::canonical(self : LWWWorld) -> String {
  let states = []
  for (name, reg) in self.replicas.iter() {
    states.push((name, reg.canonical()))
  }
  canonical_world(states)
}
