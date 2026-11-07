#!/bin/sh
# 循环补落 PortMaster 端口包树，直到工作树和 HEAD 对得上（portmaster_tree.py 的退出码就是这条判据）。
#
# 为什么要循环：这棵是 blobless 克隆，150,416 个 blob 得分批逐个点名要（一批上限 CHUNK_BLOBS=300 个），
# 而 11-05 实测每批都可能被隧道掀断（`unable to read sha1 file` → 整批 rc=128）。
# 断一批只损失一批：已经拿到的对象留在本地对象库里，下一轮接着要还缺的，进度是累加的。
#
# 读数为什么不能拿 `git status` 当尺子（11-05 07:0x 栽了两小时的根因）：
# 索引几乎是空的，status 于是把同一批路径报两遍（`D ` = HEAD 有索引没、`??` = 盘上有没进索引），
# 还把未跟踪的目录**塌成一条带尾斜杠的条目**（`ports/`、`.github/workflows/`）。尾斜杠 pathspec
# 的语义是"整个目录"，`ports/` 一条就把 150,414 个 blob 塞进同一次按需取 ⇒ 服务端算不完 ⇒ 每批作废。
# 现在读数走 `ls-tree HEAD` 减 `ls-files`（见 missing_rels），批内只有具体文件。
# 但"这一批有没有进展"仍要再看对象库字节：git 中断时不写索引，那批的读数因此不动，
# 而对象库可能真进了几百 MB（11-05 06:44 就是被这个假读数骗停的）。
cd /f/开源掌机教程 || exit 1
REPO="${1:-PortsMaster/PortMaster-New}"
# 一个仓只许一条循环在跑：11-05 起过两次，两棵循环抢同一个 index.lock，
# 后起的那轮秒退（`index.lock 删不掉：PermissionError`）却把台账读起来像"链路在拒"。
PIDF=_scratch/tree_loop.pid
if [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; then
  echo "[tree-loop] 已有循环在跑（PID $(cat "$PIDF")），这个副本退出，不抢它的锁"
  exit 0
fi
echo $$ > "$PIDF"
for round in $(seq 1 30); do
  echo "[tree-loop] 第 $round 轮开始 $(date +%H:%M:%S)｜$REPO"
  PYTHONIOENCODING=utf-8 py -3 -X utf8 -u \
    _工具脚本/portmaster_tree.py fetch "$REPO" 2>&1
  rc=$?
  echo "[tree-loop] 第 $round 轮退出码 $rc（0=工作树落满或已相符）$(date +%H:%M:%S)"
  if [ "$rc" = "0" ]; then
    echo "[tree-loop] 树齐了，收工"
    exit 0
  fi
  sleep 60
done
echo "[tree-loop] 30 轮跑完仍没落满，剩下的格子见端口包台账"
exit 1
