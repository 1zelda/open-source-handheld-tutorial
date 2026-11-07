#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""daily_run.py —— 每天要跑的三步,给 Windows 计划任务用(不联网判版权,闸门在 scene_dl 里)。

为什么要单独一个入口:计划任务里塞 PowerShell + 中文路径会被控制台代码页坑一次
(UTF-8 无 BOM 的 .ps1 在 5.1 下按 ANSI 读,中文路径直接变乱码)。Python 原生按 Unicode 处理路径,
所以任务只负责 `py -3 这个文件`,余下的都在 Python 里。

跑什么:
  0) rsshub_ctl.py up   —— 自建 RSSHub 没起就起(中文层唯一通路,2026-10-21 补建)。
                         放在最前面:scene_monitor 要抓 127.0.0.1:1200 的四个 cn_rsshub_* 源。
                         起进程时清代理变量(header-generator 与代理头互斥),幂等,已在跑就跳过。
  1) scene_monitor.py  —— 抓全部启用源、追加台账、重算爆款与"大作登陆平台"专线、生成当天日报。
  2) rescue_watch.py   —— 下架抢救层:盯"会被立即下架"的目标(见 06-资讯监控/下架抢救登记表.tsv),
                         活着就立刻抓、新镜像雷达、已挂源存在性巡检、下架新闻里的 GitHub 链接。
                         单轮即可,真正的窗口期监控靠 --watch 循环(文档里有 schtasks 命令)。
  3) scene_dl.py       —— 只下 **合法收录登记表.tsv 里 enabled=1** 的那些(幂等,已在台账的不重复下),
                         每次跑完自动重做扫包复检(疑似商业游戏数据必须点名)+ 磁盘/台账对账补记。
  4) ports_watch.py    —— PortMaster 新端口发现层:每天比一次上游端口清单,新端口/换版写进
                         `PortMaster新端口.md` 并追加当天日报(只发现不下载)。
  5) scene_topic.py    —— 不联网,只按台账重生成《专题-源码泄露与盗版打击.md》(窄口径,裸 leak 不算)。
  6) weekly_digest.py  —— 不联网,生成/刷新《周报/YYYY-Www.md》(本周至今:入库量/聚焦分布/HOT/
                         新 payload/常败源)。幂等,每天刷新同一个文件,周日自然成稿。
各步的退出码与输出都追加到 06-资讯监控/_schedule.log,失败不许静默。
日志是**流式落盘**的:2026-10-16 08:38 那轮 scene_dl 中途死掉,因为原来等子进程结束才一次性写日志,
整个 section 连 exit= 行都没留下,事后查不出它跑到哪儿死的 —— 现在逐行写临时文件、异常也补一行。
"""
import datetime as dt
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "06-资讯监控", "_schedule.log")
TOOLS = os.path.join(ROOT, "_工具脚本")


def run(script, extra=None):
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tmp = os.path.join(TOOLS, "_step_%s.tmp" % script.replace(".py", ""))
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write("\n==== %s %s ====\n" % (stamp, script))
    rc = -1
    try:
        with open(tmp, "w", encoding="utf-8", errors="replace") as tf:
            p = subprocess.Popen([sys.executable, os.path.join(TOOLS, script)] + (extra or []),
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", cwd=ROOT)
            for line in p.stdout:            # 流式读:子进程边打边存,它死了日志也已经在
                tf.write(line)
                tf.flush()
            rc = p.wait()
    except Exception as e:                   # 连启动都失败也要留痕
        with open(tmp, "a", encoding="utf-8") as tf:
            tf.write("\n[launcher] %s: %s\n" % (type(e).__name__, e))
    with open(LOG, "a", encoding="utf-8") as fh, open(tmp, encoding="utf-8", errors="replace") as tf:
        fh.write(tf.read())
        if rc < 0:
            fh.write("\n[launcher] 本步被中断(未见 exit 行即是异常终止,输出止于上方最后一行)\n")
        fh.write("\nexit=%d\n" % rc)
    if os.path.exists(tmp):
        os.remove(tmp)
    print("%s exit=%d" % (script, rc))
    return rc


if __name__ == "__main__":
    rc0 = run("rsshub_ctl.py", ["up"])   # 中文层基础设施:没起就先起(幂等)
    rc1 = run("scene_monitor.py", ["--retry-failed"])   # 带错峰重试:Reddit 429 隔几分钟能捞回大半
    rc2 = run("rescue_watch.py")     # 抢救层必须在 scene_monitor 之后:日报是它重写的,抢救段要追加在当天日报尾部
    rc3 = run("scene_dl.py")
    rc4 = run("ports_watch.py")      # 只发现不下载,放 scene_dl 之后(它不改日报也不改台账)
    rc5 = run("scene_topic.py")      # 离线,只按台账重生成专题表
    rc6 = run("weekly_digest.py")    # 离线,刷新本周周报(趋势视角:入库量/聚焦/HOT/常败源)
    print("日志: %s" % LOG)
    sys.exit(0 if rc0 == 0 and rc1 == 0 and rc2 == 0 and rc3 == 0 and rc4 == 0 and rc5 == 0 and rc6 == 0 else 1)
