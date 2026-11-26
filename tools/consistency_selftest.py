#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""consistency_selftest.py — 一致性门禁的**负向回归**。
（第十一轮 m-8 / 第十二轮 m-2 / 第十四轮 m-1·m-2·m-3 / 第十六轮 m-5·m-6·m-7）

它回答一个问题：**「分解和」的判据真的被修好了吗？**

第十一轮复评实测：把 README 的分解改写成非「逗号句式」（`+` / `;` / `and`），
再在别处放一个合法的白名单三元组做诱饵，分解和**完全不被校验**，门禁 exit 0
（README 里 37 与 38 自相矛盾却全绿）。第十一轮据此在门禁里加了
**锚点解析**（`ANCHOR_BREAKDOWN_RE`：「N tests in total (...)」→ 取三类数目求和）。

第十二轮复评指出本文件**没有鉴别力**（M-2）：旧版诱饵是
`3 unit, 2 property, 1 regression`（**和 = 6**）—— 它**自己**就不是合法的白名单
三元组，于是每个变异体都会**因为诱饵自己**而报出「分解问题」，
→「判据被遮住与否」都判 PASS。把本文件拷到**有漏洞的公开树**上同样 5/5 PASS
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
* **m-3（断言耦合到报错文案）**：断言原来匹配一句固定的**文案**，一次无害的措辞
  重构就会让自测变红 —— 而面对红色的最省事做法是**把断言改松**，那正好把鉴别力
  抽掉（第十二轮 M-2 的复发路径）。
  → 本版断言**只核对行为**：问题条数 + **机器码**（`Problem.code`）。
  文案可以自由改写；机器码才是判据身份。

第十六轮复评又指出三件事，本版一并修掉：

* **m-5（亲和性判据造成新误报面）**：第十四轮的「亲和」判据只问「三个类别名里
  **有没有一个**含 unit/property/regression/test/case」，于是
  「3 case classes, 2 case groups and 1 case family」这类**散文**被判成矛盾的分解
  ⇒ 门禁 exit 3。
  → 本文件新增 G1–G5 五只**散文**用例：它们必须**零问题**。
  → 并新增 G6：非分解的三元组 + 句子里**在三元组之外**声明了测试数 ⇒ 必须报
  （`declared-sum`），保证「误报面收窄」不是把判据整体放松。
* **m-6（分隔符集合不完整 ⇒ 整条逃逸）**：`/`、`&`、破折号不在分隔符集合里，
  于是「16 unit test cases / 11 property test cases / 11 regression test cases」
  这类写法的矛盾分解**整条不可见** ⇒ 门禁 exit 0。
  → 本文件新增 S1–S5 五只**分隔符**用例：它们必须被报出（`category-sum`）。
* **m-7（措辞探针自锚定 ⇒ 静默空转 / 假红）**：第十四轮的措辞探针硬编码了一句
  报错文案，而同一句**也写在门禁源码的注释里**：只改消息 → 探针空转却仍报 PASS；
  连注释一起改 → 探针判 FAIL → 自测 exit 1 → CI 假红。
  → 本版把探针的锚点改成**结构**（见下），并新增「注释探针」与「对照探针」。

第十六轮的探针（锚点是结构，不是文案）
----------------------------------------

| 探针 | 改写方式 | 期望 |
|---|---|---|
| 文案探针 | 用 `ast` 找到每一条 `problem(code, message)` 调用的**第二个实参**（消息），把它的源码区间整段换成占位串（机器码不动） | 矩阵结论（条数 + 机器码）**逐例不变** |
| 注释探针 | 用 `tokenize` 把源码里的**注释**全部抹掉 | 矩阵结论**逐例不变** |
| 对照探针 | 把**声明的测试数**加一（判据级的改动） | 矩阵结论**必须变化**（否则前两只就是恒真的） |

三只探针都不引用门禁源码里的**任何一句可编辑的文本**：改文案不会让探针失效，
改注释也不会 —— 所以「无害的措辞重构」与「注释重写」都**不会**让自测变红。

用法：
    python3 tools/consistency_selftest.py
退出码：0 = 全部符合预期；1 = 有用例不符合预期（**在没修的树上也会是 1**）。
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import io
import os
import sys
import tempfile
import tokenize
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

# 第十六轮 m-5 的反例：第十四轮的「亲和」判据（任一类别名含 test/case/unit/
# regression 就算亲和）把这些**语义合法**的散文当成了分解 ⇒ 门禁 exit 3。
# 它们的共同点是**三个类别名同族** —— 分解的三类本来就是三类不同的东西。
PROSE_CASE_FAMILY = ("The harness reports 3 case classes, 2 case groups "
                      "and 1 case family.\n")
PROSE_UNIT_VARIANTS = ("The build has 3 unit variants, 2 unit flavors "
                        "and 1 unit image.\n")
PROSE_REGRESSION_JOBS = ("The nightly job has 3 regression jobs, 2 regression stages "
                          "and 1 regression slot.\n")
PROSE_CN_UNIT_TESTS = "我们运行了 3 单元测试, 2 单元测试 and 1 单元测试。\n"
# 这一只还顺带覆盖「散文尾词被吞成类别名」：旧判据把第三个类别名抽成
# 「test batch during」，并把这句散文报成「test breakdown」。
PROSE_TEST_BATCH = ("We ran 3 test cases, 2 test suites and 1 test batch "
                    "during development.\n")

# 第十六轮 m-5 的**对照**：不是分解的三元组，但同一句里**在三元组之外**声明了
# 测试数 ⇒ 那一句自相矛盾 ⇒ 必须报（`declared-sum`）。
# 这一只保证「误报面收窄」不是把判据整体放松。
DECLARED_SUM_TRIPLE = ("The suite has 37 tests: 16 benchmarks, 11 suites "
                        "and 11 oracles.\n")

# 第十六轮 m-6 的反例：**分隔符**决定三元组能不能被看见。
# 旧分隔符集合（`,` `+` `;` `、` `，` `and`）不含 `/`、`&`、破折号（– — ~），
# 于是下面这些写法的矛盾分解（和值均为 38）**整条不可见** ⇒ 门禁 exit 0。
SEP_SLASH = ("Historically the suite had 16 unit test cases / 11 property test cases "
             "/ 11 regression test cases.\n")
SEP_AMP = ("Historically the suite had 16 unit test cases & 11 property test cases "
           "& 11 regression test cases.\n")
SEP_EM_DASH = ("Historically the suite had 16 unit test cases — 11 property test cases "
               "— 11 regression test cases.\n")
SEP_EN_DASH = ("Historically the suite had 16 unit suites – 11 property suites "
               "– 11 regression suites.\n")
SEP_TILDE = ("Historically the suite had 16 unit suites ~ 11 property suites "
             "~ 11 regression suites.\n")

# 机器码（判据身份）—— 由 tools/check_consistency.py 的 `problem()` 给出。
# 文案可以自由改写；**机器码**是自测唯一的判据句柄。
RULE_ANCHOR_MISSING = "anchor-missing"
RULE_ANCHOR_SUM = "anchor-sum"
RULE_WHITELIST_SUM = "whitelist-sum"
RULE_CATEGORY_SUM = "category-sum"
RULE_DECLARED_SUM = "declared-sum"


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
        "none"        —— 必须**一条问题都没有**（合法改动 / 合规陈述 / 散文）
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

    # --- 第十六轮 m-5：**散文**里的三元组不是分解（必须零问题） ---
    for name, tail in (
        ("G1 散文三元组（case classes / case groups / case family）",
         PROSE_CASE_FAMILY),
        ("G2 散文三元组（unit variants / unit flavors / unit image）",
         PROSE_UNIT_VARIANTS),
        ("G3 散文三元组（regression jobs / regression stages / regression slot）",
         PROSE_REGRESSION_JOBS),
        ("G4 中文散文三元组（单元测试 ×3）",
         PROSE_CN_UNIT_TESTS),
        ("G5 散文三元组（test cases / test suites / test batch）",
         PROSE_TEST_BATCH),
    ):
        add(f"{name}（和值 ≠ 37，同一句未声明测试数）", text + "\n" + tail, "none")

    # 第十六轮 m-5 的对照：非分解的三元组 + 句子里在三元组之外声明了测试数。
    add("G6 非分解三元组 + 同句在三元组之外声明测试数",
        text + "\n" + DECLARED_SUM_TRIPLE, "at_least_one", RULE_DECLARED_SUM)

    # --- 第十六轮 m-6：**分隔符**不能决定三元组能不能被看见 ---
    for name, tail in (
        ("S1 斜杠分隔的矛盾分解（unit test cases）", SEP_SLASH),
        ("S2 与号分隔的矛盾分解（unit test cases）", SEP_AMP),
        ("S3 破折号分隔的矛盾分解（unit test cases）", SEP_EM_DASH),
        ("S4 连接号分隔的矛盾分解（unit suites）", SEP_EN_DASH),
        ("S5 波浪号分隔的矛盾分解（unit suites）", SEP_TILDE),
    ):
        add(f"{name}（和 = 38）", text + "\n" + tail + "\n" + DECOY,
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


# --------------------------------------------------------------------------
# 第十六轮 m-7：探针的锚点是**结构**，不是任何一句可编辑的文本。
#
# 第十四轮的措辞探针硬编码了一句报错文案，而同一句**也写在门禁源码的注释里**：
#   * 只改两条**消息**（不动注释）→ `str.replace` 只改到注释 → 被测门禁与
#     「改写后」的门禁行为**完全相同** → 探针**空转**却仍报 PASS（静默失效）；
#   * 连**注释**一起改 → 探针找不到那句短语 → 判 FAIL → 自测 exit 1 →
#     CI 与统一门禁**假红**，而判据与行为一字未动。
#
# 下面的三只改写器都只认**结构**：函数调用的位置、注释 token、模块级常量。
# 于是「改文案」与「改注释」都**不会**让自测失败。
# --------------------------------------------------------------------------


def _byte_lines(src: str) -> tuple[bytes, list[int]]:
    """(字节串, 每行起始字节偏移)。

    ``ast`` 的 ``col_offset`` 是 **UTF-8 字节**偏移，不是字符偏移 ——
    源码里有中文，按字符切会切错位置。
    """
    data = src.encode("utf-8")
    offsets: list[int] = []
    pos = 0
    for line in data.split(b"\n"):
        offsets.append(pos)
        pos += len(line) + 1
    return data, offsets


def _replace_spans(src: str, spans: list[tuple[int, int, bytes]]) -> str:
    """按字节区间替换源码（从后往前替换，偏移才不会失效）。"""
    data, _ = _byte_lines(src)
    for start, end, new in sorted(spans, key=lambda s: s[0], reverse=True):
        data = data[:start] + new + data[end:]
    return data.decode("utf-8")


def mangle_messages(src: str) -> tuple[str, int]:
    """把门禁里每一条诊断的**消息**整段换成占位串（返回改写条数）。

    锚点是 ``problem(...)`` 调用的**第二个实参**（消息）的位置 —— 结构，
    不是文案。维护者怎么改写措辞，这只探针都照样生效；机器码（第一个实参）
    不动 ⇒ 判据身份不动 ⇒ 矩阵结论必须逐例不变。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src, 0
    _, offsets = _byte_lines(src)
    spans: list[tuple[int, int, bytes]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if fname != "problem":
            continue
        msg = None
        if len(node.args) >= 2:
            msg = node.args[1]
        else:
            for kw in node.keywords:
                if kw.arg == "message":
                    msg = kw.value
        if msg is None or not hasattr(msg, "lineno") or msg.end_lineno is None:
            continue
        start = offsets[msg.lineno - 1] + msg.col_offset
        end = offsets[msg.end_lineno - 1] + msg.end_col_offset
        spans.append((start, end, b'"<wording replaced by the selftest probe>"'))
    if not spans:
        return src, 0
    return _replace_spans(src, spans), len(spans)


def strip_comments(src: str) -> tuple[str, int]:
    """把源码里的**注释**全部抹掉（返回抹掉的条数）。

    注释只是解释：抹掉它，行为必须完全一样。这只探针证明的是
    「改注释 ⇒ 自测不变红」。
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return src, 0
    lines = src.splitlines(keepends=True)
    removed = 0
    for tok in tokens:
        if tok.type != tokenize.COMMENT:
            continue
        (srow, scol), (erow, ecol) = tok.start, tok.end
        if srow != erow or srow > len(lines):
            continue
        line = lines[srow - 1]
        lines[srow - 1] = line[:scol] + " " * (ecol - scol) + line[ecol:]
        removed += 1
    return "".join(lines), removed


def bump_declared_count(src: str) -> tuple[str, int]:
    """把**声明的测试数**加一（判据级的改动，返回改写条数）。

    这是**对照探针**：判据一改，矩阵结论**必须**变化 —— 否则前两只探针
    就是恒真的（第十二轮 M-2 的原样）。
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src, 0
    _, offsets = _byte_lines(src)
    spans: list[tuple[int, int, bytes]] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "EXPECTED_TESTS" not in names:
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, int):
            continue
        if value.end_lineno is None:
            continue
        start = offsets[value.lineno - 1] + value.col_offset
        end = offsets[value.end_lineno - 1] + value.end_col_offset
        spans.append((start, end, str(value.value + 1).encode("ascii")))
    if not spans:
        return src, 0
    return _replace_spans(src, spans), len(spans)


def compare_matrix(gate_a, gate_b, all_cases, ev_dir: Path):
    """比对两套门禁在**同一批用例**上的结论（问题条数 + 机器码）。

    返回 (结论是否一致, 失败原因)。两套门禁各自减掉**自己**的基线 ——
    基线是按问题文本做集合差的，所以两边的基线必须分别算。
    """
    base_a = baseline_problems(gate_a, all_cases[0]["text"], ev_dir)
    base_b = baseline_problems(gate_b, all_cases[0]["text"], ev_dir)
    for case in all_cases:
        p1, c1 = run_case(gate_a, case, ev_dir, base_a)
        p2, c2 = run_case(gate_b, case, ev_dir, base_b)
        if len(p1) != len(p2) or c1 != c2:
            return False, (f"用例「{case['name']}」结论变了："
                           f"原 {len(p1)} 条 {c1} vs 改后 {len(p2)} 条 {c2}")
    return True, ""


def structural_probe(gate, all_cases, ev_dir: Path, mutator, label: str,
                     expect_change: bool):
    """用 mutator 造一份「改写后的门禁」，比对矩阵结论。

    返回 (状态, 说明)，状态 ∈ {"PASS", "FAIL", "N/A"}：
      * ``expect_change=False``（文案 / 注释探针）：结论必须**逐例不变**；
      * ``expect_change=True``（对照探针）：结论**必须变** —— 否则探针恒真。
    探针**不适用**（源码里没有可改写的结构）时判 N/A，不判失败 ——
    「不适用」不是红：机器码断言本身已经守着判据身份。
    """
    src = (Path(HERE) / "check_consistency.py").read_text(encoding="utf-8")
    mutated, n = mutator(src)
    if n == 0:
        return "N/A", f"{label}：门禁源码里没有可改写的结构，探针不适用（不判失败）"
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "check_consistency.py"
        target.write_text(mutated, encoding="utf-8")
        try:
            other = load_gate(str(target))
        except Exception as exc:  # noqa: BLE001 - 改写后的源码可能语法不合法
            return "FAIL", f"{label}：改写后的门禁无法加载（{exc}）"
        same, reason = compare_matrix(gate, other, all_cases, ev_dir)
    if expect_change:
        if same:
            return "FAIL", f"{label}：判据级改动之后矩阵结论**没有**变化 ⇒ 探针恒真"
        return "PASS", f"{label}：判据级改动被探针看见（矩阵结论确实变了）"
    if not same:
        return "FAIL", reason
    return "PASS", ""


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
          "（第十一轮 m-8 / 第十二轮 m-2 / 第十四轮 m-1·m-2·m-3 / "
          "第十六轮 m-5·m-6·m-7）===")
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

    # --- 第十六轮 m-7：结构化探针（锚点是结构，不是文案） ---
    for label, mutator, expect_change in (
        ("文案探针（结构化改写：每条诊断的消息整段替换，判据不动）",
         mangle_messages, False),
        ("注释探针（结构化改写：注释全部抹掉，判据不动）",
         strip_comments, False),
        ("对照探针（判据级改动：声明的测试数 +1，矩阵必须变化）",
         bump_declared_count, True),
    ):
        status, reason = structural_probe(
            gate, all_cases, ev_dir, mutator, label, expect_change)
        print(f"  {label} → {status}")
        if status == "FAIL":
            print(f"        └ 失败原因：{reason}")
            ok = False
        elif reason:
            print(f"        └ {reason}")

    print("合计：%s" % ("全部符合预期" if ok else "有用例不符合预期"))
    if ok:
        print("鉴别力：本自测要求每只缺陷型变异体由**指定的机器码**报出，"
              "且每只合规型变异体**零问题**；在缺少相应判据的旧门禁上，"
              "这些用例必然 FAIL（退出码 1）。三只探针的锚点是**结构**"
              "（调用位置 / 注释 token / 模块级常量），不是任何一句可编辑的"
              "文案 —— 改文案与改注释都不会让自测变红。")
    else:
        print("鉴别力：本自测在当前树上已不通过 —— 它**不能**证明门禁被修好了。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
