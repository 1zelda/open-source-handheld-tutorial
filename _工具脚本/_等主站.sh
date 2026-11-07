#!/bin/sh
# 【已退役，用 _镜像循环.sh】这个探针只探**直连**主站，而 11-04 21:3x 起 Clash Verge 换到 7891，
# 主站 443 直连断着、走代理 1.6 秒就通 —— 于是它一直报"主站不通"，104 个仓一个没补。
# 判"能不能动盘"这件事本来就该只在 python 里写一份（switch2_emu_fetch.probe_github()，
# 直连/代理都试），别再在 shell 里重复一遍。留着不删是为了对照这段历史。
#
# 等 github.com:443 的窗口再跑源码镜像。这台机到主站的 443 一天里断了好几回，
# 而 api/codeload/release-assets 全程正常——所以成品包下载不受影响，只有镜像要等窗口。
#
# 为什么要循环而不是一次性的：11-04 18:24 实测主站在**几十秒尺度**上抖，
# 上一版 watcher 探到通了就启动镜像、镜像自己的 preflight 20 秒后却失败，watcher 就此退出，
# 白丢一个窗口。现在改成"退出码非 0 就再等再试"，直到 all 自己跑完（幂等，已镜像的按 HEAD 跳）。
cd /f/开源掌机教程 || exit 1
round=0
for i in $(seq 1 120); do
  if GIT_TERMINAL_PROMPT=0 git -c http.proxy= -c https.proxy= ls-remote \
       https://github.com/octocat/Hello-World.git HEAD >/dev/null 2>&1; then
    round=$((round + 1))
    echo "[watch] 第 $i 次探测：主站通，启动镜像（第 $round 轮）"
    MIRROR_AREA=成品移植游戏库 PYTHONIOENCODING=utf-8 py -3 -X utf8 \
      _工具脚本/switch2_emu_fetch.py all > _工具脚本/_lib_mirror5.out 2>&1
    rc=$?
    echo "[watch] 第 $round 轮镜像退出码 $rc（0=跑完，1=还有失败或被闸门中止）"
    if [ "$rc" = "0" ]; then
      echo "[watch] 镜像全部处理完，收工"
      exit 0
    fi
    echo "[watch] 60 秒后再看主站"
    sleep 60
    continue
  fi
  echo "[watch] 第 $i 次探测：主站仍不通，60 秒后再看"
  sleep 60
done
echo "[watch] 探测次数用尽，主站没稳定恢复，不动盘"
exit 1
