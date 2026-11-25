#!/usr/bin/env bash
# regenerate_evidence.sh — 重新生成 evidence/ 下**本轮**的全部原始日志。
#
# 它生成这 12 个文件（全部带 code fingerprint 头，environment.txt 用 code-fp）：
#   bench.log  coverage_report.log  demo.log  environment.txt  fault_injection.log
#   fuzz_diff.seed42.log  fuzz_diff.seed777.log  fuzz_diff.seed20261124.log
#   fuzz_diff.seed31337.log  fuzz_summary.txt  moon_check.log  moon_test.log
#
# 它**不**碰 evidence/archive/ 下的历史留档（那些是被取代的旧件，见各自的 README）。
#
# 为什么要脚本化
# --------------
# evidence/ 里的日志必须**能被第三方按同一条命令复现**。手抄的数字、事后补写的
# 摘要都不算数 —— 这个脚本把「跑什么、在哪跑、拿什么当输入」写死，跑一次就得到
# 一整套自洽的日志。
#
# 它同时修掉了**第四轮**评审指出的两个证据缺陷（这里的 m3/m4 是第四轮的编号）：
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

# 期望测试数：**唯一真源**在 tools/check_consistency.py 里（README §4.1 声明
# 16 unit + 10 property + 11 regression = 37）。本脚本与 CI 都调用那一个入口，
# 所以两边不可能各说各话；README 里的数也会被同一个入口交叉核对。
#
# 关于 `moon test` 的退出码 —— 这是**实测事实**，不是推测（MoonBit 0.1.20261119）：
#   * 删掉 moon.pkg        -> moon test 与 moon check 都退出 **255**；
#   * 只删掉测试文件        -> moon test 退出 **0**（但一个测试都没找到）；
#   * 有一条断言真的失败    -> moon test 非 0 退出，**并且仍然打印汇总行**。
# 所以「退出码为 0」不能当作「测试通过」的证据 —— 必须显式断言测试数。
EXPECTED_TESTS="$(python3 tools/check_consistency.py --print-expected)"

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
# commit：只有在**项目根目录本身就是某个 git 工作树的最上层**时才记录
# `git rev-parse HEAD`。否则（例如把这棵树复制到服务器上再跑、或把它放在
# 另一个仓库里）拿到的 SHA 属于别的仓库，记下来就是**假的 provenance** ——
# 这种情况下如实写「不是 git checkout」，并指出真正的身份是下面的 code fingerprint。
GIT_TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null || true)"
ROOT_REAL="$(cd "$ROOT" && pwd -P)"
if [ -n "$GIT_TOPLEVEL" ] && [ "$(cd "$GIT_TOPLEVEL" && pwd -P)" = "$ROOT_REAL" ]; then
  COMMIT="$(git rev-parse HEAD 2>/dev/null || echo '(unknown)')"
  COMMIT_STATE="base commit of the checkout this tree was copied from; the working tree may carry uncommitted changes — the code fingerprint below is the authoritative identity of the tree"
else
  COMMIT="(not a git checkout)"
  COMMIT_STATE="this tree is a copy, not a checkout of the upstream repository — the code fingerprint below is the authoritative identity of the tree"
fi
{
  echo "# moonbit-crdt — environment of the recorded run"
  echo
  echo "date(UTC)   : $(date -u '+%Y-%m-%d %H:%M:%S')"
  echo "moon        : $(moon version --all | head -1)"
  echo "python      : $(python3 --version 2>&1)"
  echo "uname       : $(uname -srm)"
  echo "cpu         : $(nproc) cores"
  echo "load-average: $(awk '{print $1, $2, $3}' /proc/loadavg 2>/dev/null || echo 'unknown')"
  echo "commit      : $COMMIT"
  echo "commit-state: $COMMIT_STATE"
  echo "module      : $(grep '^name' moon.mod | tr -d ' ')"
  echo "code-fp     : $FP"
  echo "tests       : $EXPECTED_TESTS (asserted against the README)"
} > "$OUT/environment.txt"
cat "$OUT/environment.txt"

echo "==> moon check"
# `moon check` 失败时不静默死掉：把退出码和输出尾巴打出来，便于运维定位。
MOON_CHECK_RC=0
{
  echo "# moon check"
  echo "# code fingerprint: $FP"
  echo "\$ moon check"
  moon check 2>&1
} > "$OUT/moon_check.log" || MOON_CHECK_RC=$?
if [ "$MOON_CHECK_RC" -ne 0 ]; then
  echo "error: 'moon check' failed (exit $MOON_CHECK_RC)." >&2
  echo "       Full output: $OUT/moon_check.log" >&2
  echo "       Last lines:" >&2
  tail -8 "$OUT/moon_check.log" | sed 's/^/       /' >&2
  exit 2
fi

echo "==> moon test"
# `moon test` 失败时**不要**在这里直接退出：那样脚本就永远到不了下面的断言，
# 运维拿不到「总数/通过数/失败数」这条诊断。所以先把退出码收下来，让日志写完，
# 再由 tools/check_consistency.py 统一判定并打印可读诊断。
MOON_TEST_RC=0
{
  echo "# moon test"
  echo "# code fingerprint: $FP"
  echo "\$ moon test"
  moon test 2>&1
} > "$OUT/moon_test.log" || MOON_TEST_RC=$?

# --- 硬断言：测试数必须与 README 一致，且全部通过 -------------------------
# 判定逻辑集中在 tools/check_consistency.py —— CI 调的是同一个入口。
python3 tools/check_consistency.py \
  --test-log "$OUT/moon_test.log" \
  --moon-exit "$MOON_TEST_RC" \
  --expected "$EXPECTED_TESTS"

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
# 汇总文件也带指纹头：它与四份 seed 日志同源，没有指纹就无法证明它是哪棵
# 源码树跑出来的（第五轮 M3 指出过这个漏口）。
{
  echo "# code fingerprint: $FP"
  echo "# seed summary of the differential harness (one [summary] line per seed)"
} > "$OUT/fuzz_summary.txt"
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
