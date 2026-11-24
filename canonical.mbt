///|
/// Shared helpers: deterministic ordering and canonical (order-independent)
/// serialisation.
///
/// Every CRDT in this package exposes a `canonical()` function that renders
/// the state as a **canonical string**: two states are equal **iff** their
/// canonical forms are equal.  This matters because several CRDTs are
/// *sets* underneath (an OR-Set stores a set of dots per element), and two
/// replicas that merged the same dots in a different order hold the same
/// state while comparing unequal element-by-element.
///
/// The canonical form is what the cross-implementation differential harness
/// compares, so it must be stable across languages: keys are sorted, dots
/// are sorted, and no map iteration order may leak into the output.

///|
/// Compares two strings by **UTF-16 code unit order** (i.e. plain
/// lexicographic order).
///
/// Why not the built-in `<`?
/// ----------------------
/// MoonBit's default string comparison is **numeric-aware**: it compares
/// embedded digit runs numerically, so `"C#10" < "C#2"` is *false* in MoonBit
/// but *true* in Python.  The canonical form of this package has to be
/// byte-for-byte comparable across two independent implementations, so the
/// ordering is spelled out here instead of relying on a built-in whose
/// semantics differ between languages.
///
/// The reference implementation in `tools/reference_crdt.py` sorts by the
/// UTF-16BE encoding of the string, which is exactly this order.
pub fn lexical_cmp(a : String, b : String) -> Int32 {
  let ua = a.code_units()
  let ub = b.code_units()
  let na = ua.length()
  let nb = ub.length()
  let n = if na < nb {
    na
  } else {
    nb
  }
  let mut i = 0
  while i < n {
    if ua[i] < ub[i] {
      return -1
    }
    if ua[i] > ub[i] {
      return 1
    }
    i = i + 1
  }
  if na < nb {
    -1
  } else if na > nb {
    1
  } else {
    0
  }
}

///|
pub fn sort_strings(items : Array[String]) -> Array[String] {
  let out = items.copy()
  out.sort_by(fn(x : String, y : String) -> Int32 { lexical_cmp(x, y) })
  out
}

///|
pub fn join_with(items : Array[String], sep : String) -> String {
  let mut out = ""
  let mut first = true
  for item in items.iter() {
    if first {
      first = false
    } else {
      out = out + sep
    }
    out = out + item
  }
  out
}

///|
/// Renders `key=value` pairs as a canonical `k=v;k=v` string with keys sorted.
pub fn canonical_pairs(pairs : Array[(String, String)]) -> String {
  let keys = []
  for (k, _) in pairs.iter() {
    keys.push(k)
  }
  let sorted_keys = sort_strings(keys)
  let mut out = ""
  let mut first = true
  for k in sorted_keys.iter() {
    for (pk, pv) in pairs.iter() {
      if pk == k {
        if first {
          first = false
        } else {
          out = out + ";"
        }
        out = out + k + "=" + pv
      }
    }
  }
  out
}
