#!/bin/bash
# 同步“投稿最新版本”文件夹：论文 PDF + 完整 tex 源 + 补充包 + arXiv 包。
# 每次修改后由 make_supplementary.sh 自动调用，也可手动执行。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/投稿最新版本"
mkdir -p "$DEST/tex"
cp "$ROOT/paper/main.pdf"                "$DEST/AgentFootprint_paper.pdf"
rsync -a --delete "$ROOT/paper/main.tex" "$ROOT/paper/references.bib" "$DEST/tex/"
rsync -a --delete "$ROOT/paper/figures/" "$DEST/tex/figures/"
cp "$ROOT/supplementary_v1.tar.zst"      "$DEST/supplementary.tar.zst"
[ -f "$ROOT/arxiv/agentfootprint_arxiv.tar.gz" ] && cp "$ROOT/arxiv/agentfootprint_arxiv.tar.gz" "$DEST/arxiv_source.tar.gz"
date -u +"synced %Y-%m-%dT%H:%M:%SZ" > "$DEST/最后同步时间.txt"
git -C "$ROOT" rev-parse --short HEAD >> "$DEST/最后同步时间.txt" 2>/dev/null || true
echo "投稿最新版本/ 已同步"
