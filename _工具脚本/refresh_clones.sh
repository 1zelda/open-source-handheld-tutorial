#!/bin/bash
# 重新拉取 02-模拟器库/已clone仓库 下的全部仓库到最新版本(浅历史,省空间)。
# 用法: bash _工具脚本/refresh_clones.sh [--dry-run]
set -u
BASE="$(cd "$(dirname "$0")/.." && pwd)/02-模拟器库/已clone仓库"
DRY="${1:-}"
echo "目标目录: $BASE"
cd "$BASE" || exit 1
ok=0; fail=0; skip=0
for r in */*/; do
  [ -d "$r/.git" ] || continue
  url=$(git -C "$r" config --get remote.origin.url) || { echo "[无上游] $r"; skip=$((skip+1)); continue; }
  if [ "$DRY" = "--dry-run" ]; then
    echo "[待更新] $r  <- $url"; continue
  fi
  # 浅仓库更新:重新 fetch 最新提交并硬切到 FETCH_HEAD(浅 clone 无分支跟踪)
  if git -C "$r" fetch --depth 1 origin HEAD >/dev/null 2>&1 && git -C "$r" reset --hard FETCH_HEAD >/dev/null 2>&1; then
    echo "[已更新] $r  $(git -C "$r" log -1 --format=%cs)"; ok=$((ok+1))
  else
    echo "[失败]   $r  $url"; fail=$((fail+1))
  fi
done
echo "---- 完成:更新 $ok,失败 $fail,跳过 $skip ----"
echo "提示:浅仓库里如果有本地改动(自定义配置),先手动备份再跑本脚本。"
