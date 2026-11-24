#!/usr/bin/env bash
# regenerate_evidence.sh — 重新生成 evidence/ 下的全部原始日志。
#
# 为什么要脚本化
# --------------
# evidence/ 里的日志必须**能被第三方按同一条命令复现**。手抄的数字、事后补写的
# 摘要都不算数 —— 这个脚本把「跑什么、在哪跑、拿什么当输入」写死，跑一次就得到
# 一整套自洽的日志。
#
# 它同时修掉了评审指出的两个证据缺陷：
#   * m3：日志头部原来写 `cases=seed20261124`（把标签当数量），现在写真实数量；
#   * m4：四条 summary 原来没有 seed 标注且顺序错乱，现在按 seed 排序并标注。
#
# 用法（在项目根目录）：
#     bash tools/regenerate_evidence.sh [输出目录]
#
# 依赖：MoonBit 工具链（`moon`，需在 PATH 里）与 python3。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/evidence}"

cd "$ROOT"
mkdir -p "$OUT"

# 代码指纹：把每份日志绑定到产生它的代码树状态。
# 没有它，重跑后的日志可能与旧件逐字节相同（日志只记数量、不记用例），
# 于是无法证明「这批数字是新代码跑出来的」。
FP="$(python3 tools/provenance.py --quiet)"

# 期望测试数：与 README §4.1 的声明必须一致（16 unit + 10 property + 10 regression）。
# `moon test` 在**一个测试都没找到**时同样退出 0（例如 moon.pkg 缺失），所以
# 「退出码为 0」不能当作「测试通过」的证据 —— 这里显式断言测试数。
EXPECTED_TESTS="${EXPECTED_TESTS:-36}"

if ! command -v moon >/dev/null 2>&1; then
  echo "error: 'moon' not found in PATH." >&2
  echo "       install it with:" >&2
  echo "         curl -fsSL https://cli.moonbitlang.com/install/unix.sh | bash" >&2
  echo "         export PATH=\"\$HOME/.moon/bin:\$PATH\"" >&2
  exit 2
fi

# 四组种子：与 README §4 表格一一对应（cases 是「每族用例数」，共 4 族）。
SEEDS=("20261124 2500 12" "777 1000 12" "31337 400 40" "42 600 25")

echo "==> provenance selftest"
# 指纹本身必须可复现、且不夹带依赖缓存里的文件，否则证据与代码的绑定是假的。
python3 tools/provenance.py --selftest

echo "==> environment"
{
  echo "# moonbit-crdt — environment of the recorded run"
  echo
  echo "date(UTC)   : $(date -u '+%Y-%m-%d %H:%M:%S')"
  echo "moon        : $(moon version --all | head -1)"
  echo "python      : $(python3 --version 2>&1)"
  echo "uname       : $(uname -srm)"
  echo "cpu         : $(nproc) cores"
  echo "commit      : $(git rev-parse HEAD 2>/dev/null || echo '(not a git checkout)')"
  echo "module      : $(grep '^name' moon.mod | tr -d ' ')"
  echo "code-fp     : $FP"
  echo "tests       : $EXPECTED_TESTS (asserted against the README)"
} > "$OUT/environment.txt"
cat "$OUT/environment.txt"

echo "==> moon check"
{
  echo "# moon check"
  echo "# code fingerprint: $FP"
  echo "\$ moon check"
  moon check 2>&1
} > "$OUT/moon_check.log"

echo "==> moon test"
{
  echo "# moon test"
  echo "# code fingerprint: $FP"
  echo "\$ moon test"
  moon test 2>&1
} > "$OUT/moon_test.log"

# --- 硬断言：测试数必须与 README 一致，且全部通过 -------------------------
TOTAL="$(grep -oE 'Total tests: [0-9]+' "$OUT/moon_test.log" | tail -1 | grep -oE '[0-9]+' || true)"
PASSED="$(grep -oE 'passed: [0-9]+' "$OUT/moon_test.log" | tail -1 | grep -oE '[0-9]+' || true)"
FAILED="$(grep -oE 'failed: [0-9]+' "$OUT/moon_test.log" | tail -1 | grep -oE '[0-9]+' || true)"
TOTAL="${TOTAL:-0}"; PASSED="${PASSED:-0}"; FAILED="${FAILED:-1}"

if [ "$TOTAL" -eq 0 ]; then
  echo "error: 'moon test' found 0 tests." >&2
  echo "       A green exit code here does NOT mean the suite ran:" >&2
  echo "       MoonBit exits 0 when it discovers no test entry (e.g. the" >&2
  echo "       'moon.pkg' file, which declares the test dependencies, is" >&2
  echo "       missing from the tree)." >&2
  exit 3
fi
if [ "$TOTAL" != "$EXPECTED_TESTS" ]; then
  echo "error: 'moon test' ran $TOTAL tests, but README declares $EXPECTED_TESTS." >&2
  echo "       Either a test file was lost, or README and the suite disagree." >&2
  exit 3
fi
if [ "$PASSED" != "$TOTAL" ] || [ "$FAILED" != "0" ]; then
  echo "error: 'moon test': total=$TOTAL passed=$PASSED failed=$FAILED" >&2
  exit 3
fi
# README 自身也要与 EXPECTED_TESTS 一致（防止只改了一边）。
README_TESTS="$(grep -oE '[0-9]+ tests' README.md | grep -oE '[0-9]+' | sort -u | tr '\n' ' ')"
if [ "$README_TESTS" != "$EXPECTED_TESTS " ]; then
  echo "error: README mentions test counts [$README_TESTS], expected only $EXPECTED_TESTS." >&2
  exit 3
fi
echo "    [assert] moon test: $TOTAL tests, $PASSED passed, $FAILED failed (README agrees)"

echo "==> moon bench"
{
  echo "# moon bench"
  echo "# code fingerprint: $FP"
  echo "\$ moon bench"
  moon bench 2>&1
} > "$OUT/bench.log"

echo "==> demo (moon run cmd/main)"
{
  echo "# demo"
  echo "# code fingerprint: $FP"
  echo "\$ moon run cmd/main"
  moon run cmd/main 2>&1
} > "$OUT/demo.log"

echo "==> differential harness"
: > "$OUT/fuzz_summary.txt"
for spec in "${SEEDS[@]}"; do
  set -- $spec
  seed="$1"; cases="$2"; max_ops="$3"
  log="$OUT/fuzz_diff.seed${seed}.log"
  {
    echo "# seed=${seed} cases=${cases} max_ops=${max_ops}"
    echo "# code fingerprint: $FP"
    echo "# families: gcounter,pncounter,orset,lww  (cases is per family)"
    echo "\$ python3 tools/fuzz_diff.py --cases ${cases} --seed ${seed} --max-ops ${max_ops} --moon-cmd \"moon run cmd/replay --\""
    python3 tools/fuzz_diff.py --cases "$cases" --seed "$seed" --max-ops "$max_ops" \
      --moon-cmd "moon run cmd/replay --" 2>&1
  } | tee "$log"
  # 按 seed 顺序追加到汇总（不再错乱）
  grep '^\[summary\]' "$log" | sed "s/^\[summary\]/[seed ${seed}] [summary]/" >> "$OUT/fuzz_summary.txt"
done

echo "==> coverage report"
{
  echo "# differential coverage report"
  echo "# code fingerprint: $FP"
  echo "# how much of the interesting behaviour the generated traffic actually reaches"
  echo "\$ python3 tools/coverage_report.py --cases 2500 --seed 20261124 --max-ops 12"
  python3 tools/coverage_report.py --cases 2500 --seed 20261124 --max-ops 12 2>&1
} > "$OUT/coverage_report.log"

echo "==> fault injection (the harness must catch known defects)"
{
  echo "# fault injection"
  echo "# code fingerprint: $FP"
  echo "# injects two known defects into the MoonBit side and requires the"
  echo "# differential harness to catch both (and shrink them to a minimal case)."
  echo "\$ python3 tools/fault_injection.py --project . --work /tmp/c05_fault --cases 800 --seed 20261124"
  python3 tools/fault_injection.py --project . --work /tmp/c05_fault --cases 800 --seed 20261124 2>&1
} > "$OUT/fault_injection.log"

echo
echo "==> done. files in $OUT:"
ls -la "$OUT"
