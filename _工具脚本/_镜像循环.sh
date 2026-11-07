#!/bin/sh
# 源码镜像循环：不再在 shell 里自己探主站，直接把闸门交给 python。
#
# 为什么要改：上一版 _等主站.sh 探的是**直连**主站（`git -c http.proxy= ls-remote`），
# 11-04 21:3x Clash Verge 从 7890 换到 7891 之后，这个探针一直在报"主站不通"，
# 而同一分钟走代理的 `ls-remote` 1.6 秒就返回了 —— watcher 白等，104 个仓一个没补。
# 现在闸门写在 switch2_emu_fetch.probe_github() 里：直连、代理哪条通用哪条，
# 两条都不通就"不动盘"退出 1，本轮不写任何半成品。重跑幂等（已镜像的按 HEAD 跳）。
cd /f/开源掌机教程 || exit 1
for round in $(seq 1 40); do
  echo "[mirror-loop] 第 $round 轮 $(date +%H:%M:%S)"
  MIRROR_AREA=成品移植游戏库 PYTHONIOENCODING=utf-8 py -3 -X utf8 \
    _工具脚本/switch2_emu_fetch.py all
  rc=$?
  echo "[mirror-loop] 第 $round 轮退出码 $rc（0=203 个目标全处理完，1=闸门拦下或还有失败）$(date +%H:%M:%S)"
  if [ "$rc" = "0" ]; then
    echo "[mirror-loop] 镜像补齐，收工"
    exit 0
  fi
  sleep 60
done
echo "[mirror-loop] 40 轮跑完仍有缺口，剩下哪些仓看 抓取台账.tsv 的 note 列"
exit 1
