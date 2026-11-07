#!/usr/bin/env bash
# 重新生成 02-模拟器库/已clone仓库/README_inventory.md
set -u
ROOT="F:/开源掌机教程/02-模拟器库/已clone仓库"
OUT="$ROOT/README_inventory.md"

{
echo "# 已 clone 到本地的仓库清单"
echo
echo "> 由 \`_工具脚本/gen_inventory.sh\` 生成。分类目录 = \`02-模拟器库/已clone仓库/<分类>/<仓库名>\`。"
echo "> 全部为浅克隆(\`--depth 1\`),更新用 \`bash _工具脚本/refresh_clones.sh\`。"
echo

total_bytes=0
count=0

for cat_dir in "$ROOT"/*/; do
  cat_name=$(basename "$cat_dir")
  [ "$cat_name" = "系统镜像" ] && continue
  [ -d "$cat_dir" ] || continue
  rows=""
  for repo in "$cat_dir"*/; do
    [ -d "$repo" ] || continue
    name=$(basename "$repo")
    if [ -d "$repo/.git" ]; then
      url=$(git -C "$repo" config --get remote.origin.url 2>/dev/null)
      [ -z "$url" ] && url="-"
      url=$(echo "$url" | sed -e 's#\.git$##' -e 's#^https://##')
      commit=$(git -C "$repo" log -1 --format='%cd' --date=short 2>/dev/null)
      [ -z "$commit" ] && commit="-"
      origin="https://$url"
    else
      # 手工存档(不是 clone),仍要计入体积
      url="-"; commit="-"; origin="本地存档,非 git 仓库"
      name="$name"
    fi
    size_kb=$(du -sk "$repo" 2>/dev/null | cut -f1)
    [ -z "$size_kb" ] && size_kb=0
    total_bytes=$((total_bytes + size_kb))
    count=$((count + 1))
    if [ "$size_kb" -ge 1048576 ]; then
      size_h="$(awk -v k=$size_kb 'BEGIN{printf "%.1fGB", k/1048576}')"
    elif [ "$size_kb" -ge 1024 ]; then
      size_h="$(awk -v k=$size_kb 'BEGIN{printf "%.0fMB", k/1024}')"
    else
      size_h="${size_kb}KB"
    fi
    rows="$rows| $cat_name | \`$name\` | $size_h | $commit | $origin |"$'\n'
  done
  [ -z "$rows" ] && continue
  echo "## $cat_name"
  echo
  echo "| 分类 | 仓库 | 体积 | 最近提交 | 上游 |"
  echo "|---|---|---|---|---|"
  printf '%s' "$rows"
  echo
done

size_gb=$(awk -v k=$total_bytes 'BEGIN{printf "%.1f", k/1048576}')
echo "## 汇总"
echo
echo "- git 仓库数:**$count**"
echo "- clone 总体积:**${size_gb} GB**"
echo "- 另有 \`系统镜像/\`(固件 img 压缩包)单独统计,见 \`系统镜像/README.md\`"
} > "$OUT"

echo "生成完成: $OUT ($count 个仓库, ${size_gb}GB)"
