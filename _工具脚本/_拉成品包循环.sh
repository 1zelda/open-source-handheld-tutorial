#!/bin/sh
# 循环重跑成品包下载，直到一轮里 0 失败（recomp_lib_assets.py 的退出码就是这条判据）。
#
# 为什么要循环：这台机到 release-assets 的带宽在几十分钟尺度上抖（11-04 实测 6 MB/s →
# 19 KB/s），而"全库游戏都要"这一档有 1 GB 级的包。按 300 KB/s 的速度下限给时间，链路慢时
# 这些包必然超时；连 6 个失败就熔断，所以一轮下不完不是丢数据，是这一轮的链路不够。
# 幂等判据是"本地字节数 == API 报的 size"，下一轮只补没落地的，已下的直接跳。
cd /f/开源掌机教程 || exit 1
# 同一档只许一个循环：11-05 07:0x 端口包那边起过两份循环，两份各自的 git 抢同一个
# .git/index.lock，第二份报 PermissionError 秒退，日志上看着像"链路在拒"。
PIDF=_scratch/pull_loop.pid
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; then
  echo "[pull-loop] 已有循环在跑（PID $(cat "$PIDF")），这个副本退出，不抢它的活"
  exit 0
fi
echo $$ > "$PIDF"
for round in $(seq 1 40); do
  echo "[pull-loop] 第 $round 轮开始 $(date +%H:%M:%S)"
  PYTHONIOENCODING=utf-8 py -3 -X utf8 \
    _工具脚本/recomp_lib_assets.py pull 2>&1
  rc=$?
  echo "[pull-loop] 第 $round 轮退出码 $rc（0=本轮 0 失败且整条队列都塞得进预算；1=还有没下完或失败的格子）$(date +%H:%M:%S)"
  if [ "$rc" = "0" ]; then
    echo "[pull-loop] 计划里要的全部资产都已落地，收工"
    exit 0
  fi
  sleep 120
done
echo "[pull-loop] 40 轮跑完仍有失败，剩下的格子见台账"
exit 1
