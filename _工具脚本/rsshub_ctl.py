#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rsshub_ctl.py —— 自建 RSSHub 的起停与体检(2026-10-21 新增)

背景:中文层(贴吧/B站/知乎/NGA)的唯一通路是自建 RSSHub,公共实例全灭。
本机 Node 24.19 满足 RSSHub 引擎要求(^22.22.2 || ^24.15.0),无 Docker,
装在 f:/rsshub-npm(npm 路线,pnpm 的 safe-delete 会被 IDE 审批链拦死,见交接稿口径 25)。

用法:
  py -3 _工具脚本/rsshub_ctl.py up       # 没起就起(daily_run 每次跑前调用)
  py -3 _工具脚本/rsshub_ctl.py status   # 端口 + 一条真路由的体检
  py -3 _工具脚本/rsshub_ctl.py test     # 跑全部已登记路由,打印 http/条目数
  py -3 _工具脚本/rsshub_ctl.py stop     # 停掉

铁规矩:
  - 起进程时**必须清掉 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY**:RSSHub 的 header-generator
    生成的浏览器头与代理头互斥,带着代理起会把 zhihu/nga/bilibili 全打成 503
    (实测报错 No headers based on this input can be generated)。
  - caniuse-lite 必须钉在 1.0.30001810(RSSHub pnpm override 的意图):新版 caniuse 的
    "last 5 chrome versions" 超出 header-generator 数据范围,MODERN_*_CHROME 预设会抛错。
  - 路由只能"实测再登记":test 子命令就是给登记表抄证据用的。
"""
import os
import socket
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOME = r"f:\rsshub-npm"
PORT = 1200
PIDFILE = os.path.join(HOME, "rsshub.pid")
LOGFILE = os.path.join(HOME, "rsshub.log")
ENTRY = os.path.join(HOME, "dist", "index.mjs")

# 已登记路由(与 06-资讯监控/源登记表.tsv 的 cn_rsshub_* 行一一对应)
ROUTES = [
    ("cn_rsshub_bili_popular", "/bilibili/popular/all"),
    ("cn_rsshub_zhihu_daily", "/zhihu/daily"),
    ("cn_rsshub_nga_pc", "/nga/forum/334"),
    ("cn_rsshub_nga_it", "/nga/forum/436"),
]
# 已知不通/已移除的路由,列出来防止下一轮重复踩
KNOWN_BAD = [
    ("/bilibili/user/video/478439944", "412 反爬(WBI 签名),浏览器兜底 45s 超时 —— B站用户空间视频流拿不到"),
    ("/tieba/forum/<吧名>", "RSSHub 1.0.0 已移除贴吧路由(实测 404 route does not exist or has been deleted)"),
    ("/nga/forum/525622", "该 fid 在自建实例上返回 this route is empty(空板/需登录)"),
]


def port_open(port=PORT):
    try:
        c = socket.create_connection(("127.0.0.1", port), timeout=3)
        c.close()
        return True
    except OSError:
        return False


def child_env():
    """复制当前环境,剔除全部代理变量 —— 国内站直连,代理会让 header-generator 抛错。"""
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy", "NO_PROXY", "no_proxy"):
        env.pop(k, None)
    env["NODE_ENV"] = "production"
    env["NODE_OPTIONS"] = "--max-http-header-size=32768"
    env["PORT"] = str(PORT)
    return env


def up():
    if port_open():
        print("RSSHub 已在跑(127.0.0.1:%d)" % PORT)
        return 0
    if not os.path.exists(ENTRY):
        print("X 缺入口 %s —— f:/rsshub-npm 没构建?" % ENTRY)
        return 1
    log = open(LOGFILE, "a", encoding="utf-8")
    p = subprocess.Popen(["node", ENTRY], cwd=HOME, env=child_env(), stdout=log, stderr=log,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                         close_fds=True)
    with open(PIDFILE, "w", encoding="utf-8") as fh:
        fh.write(str(p.pid))
    import time
    for _ in range(20):
        time.sleep(1)
        if port_open():
            print("RSSHub 已起(pid %d,127.0.0.1:%d)" % (p.pid, PORT))
            return 0
    print("X 起了 20 秒端口还没开,看 %s" % LOGFILE)
    return 1


def _curl(path, timeout=75):
    r = subprocess.run(["curl.exe", "-s", "-L", "--max-time", str(timeout), "-A", "Mozilla/5.0",
                        "-w", "\n@@%{http_code}", "http://127.0.0.1:%d%s" % (PORT, path)],
                       capture_output=True)
    out = r.stdout.decode("utf-8", "replace")
    body, _, code = out.rpartition("\n@@")
    return (code.strip() or "000"), body


def status():
    if not port_open():
        print("RSSHub 没在跑")
        return 1
    print("RSSHub 在跑(127.0.0.1:%d)" % PORT)
    ok = 0
    import re
    for name, path in ROUTES:
        code, body = _curl(path)
        items = len(re.findall(r"<item[\s>]", body))
        flag = "OK" if (code == "200" and items > 0) else "FAIL"
        if flag == "OK":
            ok += 1
        print("  %-22s %-4s %s  items=%d" % (name, flag, path, items))
    print("体检:%d/%d 条路由可用" % (ok, len(ROUTES)))
    return 0 if ok else 1


def test():
    import re
    if not port_open():
        print("RSSHub 没在跑,先 up")
        return 1
    for name, path in ROUTES:
        code, body = _curl(path)
        items = len(re.findall(r"<item[\s>]", body))
        titles = re.findall(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", body, re.S)[1:3]
        print("=" * 70)
        print("%s  http=%s items=%d  %s" % (name, code, items, path))
        for t in titles:
            print("   ", re.sub(r"\s+", " ", t)[:80])
    print("=" * 70)
    print("已知不通(别重复踩):")
    for path, why in KNOWN_BAD:
        print("  -", path, "->", why)
    return 0


def stop():
    pid = None
    if os.path.exists(PIDFILE):
        pid = open(PIDFILE, encoding="utf-8").read().strip()
    if pid:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        print("已按 pidfile 杀 %s" % pid)
    else:
        r = subprocess.run(["netstat", "-ano"], capture_output=True)
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            if ":%d " % PORT in line and "LISTENING" in line:
                p = line.split()[-1]
                subprocess.run(["taskkill", "/PID", p, "/T", "/F"], capture_output=True)
                print("已按 netstat 杀 %s" % p)
                break
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    print("停了" if not port_open() else "X 还在跑")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    sys.exit({"up": up, "status": status, "test": test, "stop": stop}.get(cmd, status)())
