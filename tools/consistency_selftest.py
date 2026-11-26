#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""consistency_selftest.py — 一致性门禁的**负向回归**（第十一轮 m-8 / 第十二轮 m-2）。

它回答一个问题：**「分解和」的判据真的被修好了吗？**

第十一轮复评实测：把 README 的分解改写成非「逗号句式」（`+` / `;` / `and`），
再在别处放一个合法的白名单三元组做诱饵，分解和**完全不被校验**，门禁 exit 0
（README 里 37 与 38 自相矛盾却全绿）。第十一轮据此在门禁里加了
**锚点解析**（`ANCHOR_BREAKDOWN_RE`：「N tests in total (...)」→ 取三类数目求和）。

第十二轮复评指出本文件**没有鉴别力**（M-2）：旧版诱饵是
`3 unit, 2 property, 1 regression`（**和 = 6**）—— 它**自己**就不是合法的白名单
三元组，于是每个变异体都会**因为诱饵自己**而报出「分解问题」，
「判据被遮住与否」都判 PASS。把本文件拷到**有漏洞的公开树**上同样 5/5 PASS
⇒ 它分不出「修好」与「没修」。

本版（第十二轮）据此改了两件事：

1. **诱饵合法**：诱饵是 `12 unit, 14 property, 11 regression`（**和 = 37**），
   两棵树都不会报它 —— 于是「有没有报出分解问题」**只能**由被测判据决定。
2. **断言落到具体规则上**：每个变异体不只要求「有分解问题」，还要求**由哪条规则**
   报出 —— 改句式的三个变异体必须由**锚点求和规则**（消息含
   `the same sentence declares`）报出。旧门禁没有这条规则 ⇒ 在旧树上本自检
   **必然失败**（退出码 1）⇒ 本自检**有鉴别力**。

用法：
    python3 tools/consistency_selftest.py
退出码：0 = 全部符合预期；1 = 有用例不符合预期（**在没修的树上也会是 1**）。
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
README = os.path.join(ROOT, "README.md")

BREAKDOWN_LINE = ("Concrete semantics of every operation, pinned down one by one — "
                  "**37 tests in\ntotal** (16 unit, 10 property, 11 regression).")

# 诱饵：**合法**的白名单三元组，和 = 37（= 项目声明的测试数）。
# 它必须合法：诱饵一旦自己就不合法，它报的「分解问题」就与被测判据无关，
# 自检也就失去了鉴别力（第十二轮 M-2 的原样）。
DECOY = ("For reference, the harness itself counts 12 unit, 14 property, 11 regression "
         "fixtures for its own self-checks.\n")

# 消息标记：**哪条规则**报出的问题。
BREAKDOWN_WORDS = ("breakdown", "anchor", "sums to", "three-way")
ANCHOR_SUM_MARK = "the same sentence declares"   # 锚点求和规则（第十一轮 m-8 引入）
ANCHOR_MISSING_MARK = "breakdown anchor"          # 锚点缺失 → fail closed
WHITELIST_SUM_MARK = "but the project declares"   # 白名单三元组求和


def load_gate():
    spec = importlib.util.spec_from_file_location(
        "cc_selftest", os.path.join(HERE, "check_consistency.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mutants(text: str):
    """(名称, 变异后的 README, 期望的分解问题条数下限, 期望由哪条规则报出)

    条数下限为 0 = **一条都不许有**（合法改动）；为 1 = **至少一条**。
    一条都不许有的用例与「由哪条规则报出」一起，构成本自检的鉴别力：
    诱饵合法 ⇒ 变异体的任何一条分解问题都只能来自被测判据。
    """
    out = []
    out.append(("C0 未改动的 README", text, 0, None))
    # 诱饵必须**自己**不触发任何规则 —— 否则后面的断言没有意义。
    out.append(("C1 未改动 + 合法诱饵（和 = 37）", text + "\n" + DECOY, 0, None))

    for label, sep in (("+", " + "), (";", " ; "), ("and", " and ")):
        m = text.replace(
            BREAKDOWN_LINE,
            "Concrete semantics of every operation, pinned down one by one — "
            "**37 tests in\ntotal** (16 unit" + sep + "10 property" + sep + "12 regression).")
        assert m != text, label + " 变异未生效"
        out.append((f"M{label} 改句式({label}) + 数字错 + 合法诱饵", m + "\n" + DECOY,
                    1, ANCHOR_SUM_MARK))

    m4 = text.replace(BREAKDOWN_LINE,
                      "Concrete semantics of every operation, pinned down one by one.")
    assert m4 != text, "M4 变异未生效"
    out.append(("M4 分解锚点整句删除", m4 + "\n" + DECOY, 1, ANCHOR_MISSING_MARK))

    m5 = text.replace(
        BREAKDOWN_LINE,
        "Concrete semantics of every operation, pinned down one by one — "
        "**37 tests in\ntotal** (16 unit, 10 property, 12 regression).")
    assert m5 != text, "M5 变异未生效"
    out.append(("M5 逗号句式 + 数字错", m5, 1, ANCHOR_SUM_MARK))

    # 第十二轮 m-6：多词类别名（`unit tests`）的第二处分解 —— 旧判据看不见它。
    m6 = text + ("\nHistorically the suite had 16 unit tests, 11 property tests "
                 "and 11 regression tests.\n")
    out.append(("M6 第二处多词类别名分解 + 合法诱饵", m6 + DECOY, 1, WHITELIST_SUM_MARK))

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.parse_args()
    gate = load_gate()
    text = open(README, encoding="utf-8").read()
    ev_dir = Path(ROOT) / "evidence"
    ok = True
    print("=== C05 一致性门禁 · 分解判据负向回归（第十一轮 m-8 / 第十二轮 m-2）===")
    print(f"诱饵（合法白名单三元组，和 = 37）：{DECOY.strip()}")
    for name, mutated, want_count, want_mark in mutants(text):
        problems = gate.check_readme_numbers(
            mutated, Path(ROOT), ev_dir, skip_bench_cross_check=True)
        hits = [p for p in problems if any(w in p for w in BREAKDOWN_WORDS)]
        got = len(hits)
        good = (got == 0) if want_count == 0 else (got >= want_count)
        if good and want_mark is not None:
            good = any(want_mark in p for p in hits)
        print(f"  {name} → 分解问题 {got} 条（期望{'0' if want_count == 0 else '≥' + str(want_count)}"
              + (f"，且由「{want_mark}」规则报出" if want_mark else "")
              + f"） → {'PASS' if good else 'FAIL'}")
        for h in hits[:2]:
            print("        └ " + h[:150])
        if not good:
            ok = False
    print("合计：%s" % ("全部符合预期" if ok else "有用例不符合预期"))
    if ok:
        print("鉴别力：本自检要求「改句式」的三个变异体由**锚点求和规则**报出；"
              "在**没有**该规则的旧门禁上这三条必然 FAIL（退出码 1）。")
    else:
        print("鉴别力：本自检在当前树上已不通过 —— 它**不能**证明门禁被修好了。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
