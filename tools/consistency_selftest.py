#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""consistency_selftest.py — 一致性门禁的**负向回归**。
（第十一轮 m-8 / 第十二轮 m-2 / 第十四轮 m-1·m-2·m-3）

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

第十二轮据此改了两件事：

1. **诱饵合法**：诱饵是 `12 unit, 14 property, 11 regression`（**和 = 37**），
   两棵树都不会报它 —— 于是「有没有报出分解问题」**只能**由被测判据决定。
2. **断言落到具体规则上**：每个变异体不只要求「有分解问题」，还要求**由哪条规则**
   报出。

第十四轮复评又指出两件事，本版一并修掉：

* **m-1（漏检）**：通用探针只认「两词类别名」，且只检查「所在句子声明了测试数」
  的三元组 ⇒ 三词类别名 / 不声明测试数的矛盾分解**整条逃逸**。
  → 本文件新增 X4 / X7 / X8 三只**逃逸**变异体（和值均为 38，与声明矛盾）。
* **m-2（反向误报）**：句子声明了测试数时，**合规**的三元组（和 = 37）被判错
  ⇒ 门禁 exit 3。→ 本文件新增 C2 用例：一句**合规**的非白名单分解必须**零问题**。
* **m-3（断言耦合到报错文案）**：断言原来匹配 `the same sentence declares` 这类
  **文案**，一次无害的措辞重构就会让自测变红 —— 而面对红色的最省事做法是
  **把断言改松**，那正好把鉴别力抽掉（第十二轮 M-2 的复发路径）。
  → 本版断言**只核对行为**：问题条数 + **机器码**（`Problem.code`）。
  文案可以自由改写；机器码才是判据身份。
  本文件末尾还有一只**措辞探针**：把门禁的一处报错措辞改掉（判据与行为完全不动），
  要求自测的结论**逐例不变**。

用法：
    python3 tools/consistency_selftest.py
退出码：0 = 全部符合预期；1 = 有用例不符合预期（**在没修的树上也会是 1**）。
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
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

# 第十四轮 m-2 的反例：一句**完全合规**的非白名单分解。
# 和值 = 37 = 项目声明的测试数，类别名只是把「tests」写成「suites」。
# 旧判据只看「所在句子有没有声明测试数」，于是把这一句判错（门禁 exit 3）——
# 那是**误报**，不是缺陷检出。
COMPLIANT_TRIPLE = ("The 37 tests are organised as 12 unit suites, 14 property suites "
                    "and 11 regression suites.\n")

# 第十四轮 m-5 的反例（沿用）：纯散文里的三元组，和值 ≠ 37，且同一句里没有
# 「N tests」—— 它们**不是**分解，不阻断。
PROSE_TRIPLE = ("We ran 5 benchmarks, 3 suites and 2 oracles during development.\n")
PROSE_TRIPLE2 = ("The deployment uses 3 shards, 5 replicas and 2 zones.\n")

# 第十四轮 m-3 的措辞探针：只改**报错文案**，判据与行为完全不动。
WORDING_PROBE = ("the same sentence declares", "the sentence declares")

# 机器码（判据身份）—— 由 tools/check_consistency.py 的 `problem()` 给出。
# 文案可以自由改写；**机器码**是自测唯一的判据句柄。
RULE_ANCHOR_MISSING = "anchor-missing"
RULE_ANCHOR_SUM = "anchor-sum"
RULE_WHITELIST_SUM = "whitelist-sum"
RULE_CATEGORY_SUM = "category-sum"


def load_gate(path: str | None = None):
    """加载门禁模块（默认是本目录下的 tools/check_consistency.py）。"""
    target = path or os.path.join(HERE, "check_consistency.py")
    spec = importlib.util.spec_from_file_location("cc_selftest", target)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cases(text: str):
    """(名称, 变异后的 README, 期望, 期望的机器码)

    期望：
        "none"        —— 必须**一条问题都没有**（合法改动 / 合规陈述）
        "at_least_one"—— 必须**至少一条**分解问题
    机器码：期望由**哪条规则**报出（None = 不限定规则，只要求有/没有问题）。
    """
    out = []

    def add(name, mutated, expect, rule=None):
        out.append({"name": name, "text": mutated, "expect": expect, "rule": rule})

    # --- 合规侧：这些改动**不许**产生任何问题 ---
    add("C0 未改动的 README", text, "none")
    add("C1 未改动 + 合法诱饵（和 = 37）", text + "\n" + DECOY, "none")
    # 第十四轮 m-2：合规的非白名单分解（和 = 37，同一句声明了测试数）
    add("C2 合规的非白名单分解（和 = 37）", text + "\n" + COMPLIANT_TRIPLE, "none")
    # 第十四轮 m-5（沿用）：纯散文里的三元组不是分解
    add("C3 纯散文三元组（和 ≠ 37，同一句未声明测试数）", text + "\n" + PROSE_TRIPLE, "none")
    add("C4 纯散文三元组（分片/副本/可用区）", text + "\n" + PROSE_TRIPLE2, "none")

    # --- 缺陷侧：这些改动**必须**被抓住 ---
    for label, sep in (("+", " + "), (";", " ; "), ("and", " and ")):
        m = text.replace(
            BREAKDOWN_LINE,
            "Concrete semantics of every operation, pinned down one by one — "
            "**37 tests in\ntotal** (16 unit" + sep + "10 property" + sep + "12 regression).")
        assert m != text, label + " 变异未生效"
        add(f"M{label} 改句式({label}) + 数字错 + 合法诱饵", m + "\n" + DECOY,
            "at_least_one", RULE_ANCHOR_SUM)

    m4 = text.replace(BREAKDOWN_LINE,
                      "Concrete semantics of every operation, pinned down one by one.")
    assert m4 != text, "M4 变异未生效"
    add("M4 分解锚点整句删除", m4 + "\n" + DECOY, "at_least_one", RULE_ANCHOR_MISSING)

    m5 = text.replace(
        BREAKDOWN_LINE,
        "Concrete semantics of every operation, pinned down one by one — "
        "**37 tests in\ntotal** (16 unit, 10 property, 12 regression).")
    assert m5 != text, "M5 变异未生效"
    add("M5 逗号句式 + 数字错", m5, "at_least_one", RULE_ANCHOR_SUM)

    # 第十二轮 m-6：多词类别名（`unit tests`）的第二处分解 —— 旧判据看不见它。
    m6 = text + ("\nHistorically the suite had 16 unit tests, 11 property tests "
                 "and 11 regression tests.\n")
    add("M6 第二处多词类别名分解 + 合法诱饵", m6 + DECOY, "at_least_one", RULE_WHITELIST_SUM)

    # 第十四轮 m-1：三只**逃逸**变异体（和值均为 38，与声明矛盾）。
    # 它们的类别名不在白名单、所在句子**没有**声明测试数 ——
    # 旧判据对它们完全失明（实测 0 条 → 门禁 exit 0）。
    for name, tail in (
        ("X4 三词类别名（unit test cases）",
         "Historically the suite had 16 unit test cases, 11 property test cases "
         "and 11 regression test cases.\n"),
        ("X7 两词非白名单类别名（unit suites）",
         "Historically the suite had 16 unit suites, 11 property suites "
         "and 11 regression suites.\n"),
        ("X8 复数单词类别名（units/properties/regressions）",
         "Historically the suite had 16 units, 11 properties and 11 regressions.\n"),
    ):
        add(f"{name}（和 = 38，同一句未声明测试数）", text + "\n" + tail,
            "at_least_one", RULE_CATEGORY_SUM)

    # 对照组：与 X8 相同的三元组，但**同一句里声明了测试数** ——
    # 旧判据能抓住它（证明 X4/X7/X8 逃逸的唯一变量就是「句子里有没有 N tests」）。
    add("X9 对照组：X8 三元组 + 同一句声明了测试数",
        text + "\nThe 37 tests were once organised as 16 units, 11 properties "
               "and 11 regressions.\n",
        "at_least_one", RULE_CATEGORY_SUM)

    return out


def baseline_problems(gate, text: str, ev_dir: Path) -> set:
    """**未改动**的 README 本身产生的问题集合（基线）。

    自测要回答的是「这个变异体**额外**引入了什么问题」，所以必须先把基线
    减掉：否则一棵**本身就不干净**的树（例如证据与 README 的覆盖数已经对不上）
    会让每一个用例都带上与被测判据无关的问题，鉴别力就被污染了。
    减基线用的是**问题条目的集合差**，不是对文案的断言 ——
    第十四轮 m-3 的要求是「断言不耦合到文案」，不是「看不见文案」。
    """
    return {str(p) for p in gate.check_readme_numbers(
        text, Path(ROOT), ev_dir, skip_bench_cross_check=True)}


def run_case(gate, case, ev_dir: Path, baseline: set):
    """跑一个变异体，返回 (问题列表, 机器码列表)。"""
    raw = gate.check_readme_numbers(
        case["text"], Path(ROOT), ev_dir, skip_bench_cross_check=True)
    problems = [p for p in raw if str(p) not in baseline]
    codes = sorted({getattr(p, "code", None) for p in problems} - {None})
    return problems, codes


def judge(case, problems, codes):
    """判定一个用例；返回 (是否通过, 失败原因)。"""
    if case["expect"] == "none":
        if not problems:
            return True, ""
        return False, ("unexpected problem(s): "
                       + " | ".join(str(p)[:110] for p in problems[:2]))
    if not problems:
        return False, "no problem reported"
    if case["rule"] and case["rule"] not in codes:
        seen = codes or ["<none: the gate reports no machine rule code>"]
        return False, (f"problem reported, but not by rule {case['rule']} "
                       f"(codes seen: {seen})")
    return True, ""


def wording_probe(gate, all_cases, ev_dir: Path, baseline: set):
    """第十四轮 m-3：只改**报错措辞**（判据与行为完全不动），结论必须逐例不变。

    这一只探针是本版的核心：它证明自测**不再**耦合到文案 ——
    一次无害的措辞重构不会再让 CI 与统一门禁变红。
    """
    src_path = Path(HERE) / "check_consistency.py"
    src = src_path.read_text(encoding="utf-8")
    mutated = src.replace(*WORDING_PROBE)
    if mutated == src:
        return False, "措辞探针未生效：门禁里没有出现待改的措辞"
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "check_consistency.py"
        target.write_text(mutated, encoding="utf-8")
        reworded = load_gate(str(target))
        reworded_base = baseline_problems(reworded, all_cases[0]["text"], ev_dir)
        for case in all_cases:
            p1, c1 = run_case(gate, case, ev_dir, baseline)
            p2, c2 = run_case(reworded, case, ev_dir, reworded_base)
            if len(p1) != len(p2) or c1 != c2:
                return False, (f"用例「{case['name']}」在措辞改动后结论变了："
                               f"原 {len(p1)} 条 {c1} vs 改后 {len(p2)} 条 {c2}")
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.parse_args()
    gate = load_gate()
    text = open(README, encoding="utf-8").read()
    ev_dir = Path(ROOT) / "evidence"
    all_cases = cases(text)
    baseline = baseline_problems(gate, text, ev_dir)
    ok = True
    print("=== C05 一致性门禁 · 分解判据负向回归"
          "（第十一轮 m-8 / 第十二轮 m-2 / 第十四轮 m-1·m-2·m-3）===")
    print(f"诱饵（合法白名单三元组，和 = 37）：{DECOY.strip()}")
    print("断言口径：**问题条数 + 机器码**（不核对报错措辞）")
    if baseline:
        print(f"基线（未改动的 README 本身的问题，已从每个用例里减掉）：{len(baseline)} 条")
    for case in all_cases:
        problems, codes = run_case(gate, case, ev_dir, baseline)
        good, reason = judge(case, problems, codes)
        want = ("0 条" if case["expect"] == "none" else "≥1 条")
        if case["rule"]:
            want += f"，且由规则「{case['rule']}」报出"
        print(f"  {case['name']} → 分解问题 {len(problems)} 条（期望{want}）"
              f" → {'PASS' if good else 'FAIL'}")
        if not good:
            print(f"        └ 失败原因：{reason}")
        for p in problems[:2]:
            print("        └ " + str(p)[:150])
        if not good:
            ok = False

    # --- 第十四轮 m-3：措辞探针 ---
    probe_ok, probe_reason = wording_probe(gate, all_cases, ev_dir, baseline)
    print(f"  措辞探针（只改报错措辞，判据不动） → {'PASS' if probe_ok else 'FAIL'}")
    if not probe_ok:
        print(f"        └ 失败原因：{probe_reason}")
        ok = False

    print("合计：%s" % ("全部符合预期" if ok else "有用例不符合预期"))
    if ok:
        print("鉴别力：本自测要求每只缺陷型变异体由**指定的机器码**报出，"
              "且每只合规型变异体**零问题**；在缺少相应判据的旧门禁上，"
              "这些用例必然 FAIL（退出码 1）。措辞探针保证断言不耦合到报错文案。")
    else:
        print("鉴别力：本自测在当前树上已不通过 —— 它**不能**证明门禁被修好了。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
