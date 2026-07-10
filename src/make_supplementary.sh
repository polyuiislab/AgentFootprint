#!/bin/bash
# 组装 OpenReview 补充材料包：脚本 + 任务语料 + 逐 run 度量记录 + 各类缓存/报告。
# 不含 workspace/home 原始库（体积）与 docs/（内部记录）。打包前做泄漏扫描。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)/agentfootprint_supplementary"
mkdir -p "$STAGE"

rsync -a "$ROOT/src/" "$STAGE/src/" --exclude "__pycache__"
rsync -a "$ROOT/tasks/" "$STAGE/tasks/"
# experiments：只带度量与报告类小文件，排除沙箱数据树
rsync -a "$ROOT/experiments/" "$STAGE/experiments/" \
  --include "*/" \
  --include "measurement.json" --include "baseline.json" \
  --include "answers*.json" --include "summary.json" \
  --include "cas_report.json" --include "calibration_report.json" \
  --include "report.json" --include "*.csv" \
  --exclude "*"
# tierb 缓存若为 json/csv 已被上面规则带上；replay_recon 证据单独补
[ -d "$ROOT/experiments/replay_recon" ] && rsync -a "$ROOT/experiments/replay_recon/" "$STAGE/experiments/replay_recon/"

# 清掉空目录
find "$STAGE" -type d -empty -delete

# 路径脱敏：项目前缀 -> "."，其余用户绝对路径 -> "~"
find "$STAGE" \( -name "*.json" -o -name "*.log" -o -name "*.txt" \) -type f \
  -exec sed -i '' -e 's|/Users/[A-Za-z0-9_.-]*/[^"]*aaai2027-storage|.|g' \
                  -e 's|/Users/[A-Za-z0-9_.-]*|~|g' {} +

# 泄漏扫描：不允许任何 key 片段/绝对用户路径（模式拆分避免自匹配）
PAT="sk-or-""v1"
if grep -rl "$PAT" "$STAGE" | head -1; then
  echo "LEAK: key fragment found, abort" >&2; exit 1
fi
if grep -rl "/Users/" "$STAGE" --include "*.json" | head -1; then
  echo "LEAK: absolute /Users path remains, abort" >&2; exit 1
fi

OUT="$ROOT/supplementary_v1.tar.zst"
tar -cf - -C "$(dirname "$STAGE")" "$(basename "$STAGE")" | zstd -19 -T0 -o "$OUT" -f
echo "built: $OUT ($(du -h "$OUT" | cut -f1))"
