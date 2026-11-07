#!/usr/bin/env bash
set -u
cd "/f/开源掌机教程/02-模拟器库/已clone仓库/系统镜像" || exit 1
declare -A SIZE=(
 ["grc803_xf45v-ee-r-TF-20260207-zh-mod.img.7z.001"]=1992294400
 ["grc803_xf45v-ee-r-TF-20260207-zh-mod.img.7z.002"]=205521082
)
BASE="https://github.com/lcdyk0517/XiFan.mod/releases/download/tf-build-20260320-035330"
for name in "${!SIZE[@]}"; do
  want=${SIZE[$name]}
  for try in 1 2 3 4 5 6 7 8; do
    have=$(stat -c%s "$name" 2>/dev/null || echo 0)
    [ "$have" = "$want" ] && { echo "OK   $name"; break; }
    echo "[try $try] $name have=$have want=$want"
    curl --http1.1 -L -C - --fail -o "$name" --retry 10 --retry-delay 5 --retry-all-errors \
      --speed-limit 2000 --speed-time 120 "$BASE/$name" || echo "  curl exit $?"
  done
done
ls -la grc803_xf45v*
