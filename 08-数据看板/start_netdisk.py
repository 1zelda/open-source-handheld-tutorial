#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""start_netdisk.py —— 一键拉起 OpenList(5244) + 数据看板(8090),并把「网盘」页签打开。

双击 08-数据看板\\启动网盘账号台.bat 就是跑这个。
11-05 起登录这条整个搬进了看板「网盘」页签(点「▶ 打开扫码窗口」那条),所以这里只负责"让两个服务活着":
OpenList 提供驱动字段表和挂载点,看板提供扫码入口与表单;凭据一律不经过这个脚本。
起 OpenList 用的是 _工具脚本\\netdisk_upload.py 里的 ensure_server()——和上传走同一条路,不另写一套。
"""
import os
import socket
import subprocess
import sys
import time
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "_工具脚本")
sys.path.insert(0, TOOL)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import netdisk_upload as nd                                    # noqa: E402

BOARD_HOST, BOARD_PORT = "127.0.0.1", 8090
BOARD_SCRIPT = os.path.join(HERE, "看板.py")
BOARD_LOG = os.path.join(ROOT, "_scratch", "看板.log")
DETACHED = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def port_up(port, timeout=0.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((BOARD_HOST, port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def start_board():
    """看板已经在听就复用,不重复起一个(同端口第二个进程会 bind 失败,别造僵尸)。"""
    if port_up(BOARD_PORT):
        print("看板已经在跑,不用再起。")
        return True
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        env.pop(k, None)          # 本机调用绕代理会被掐(10054)
    os.makedirs(os.path.dirname(BOARD_LOG), exist_ok=True)
    fh = open(BOARD_LOG, "a", encoding="utf-8", errors="replace")
    fh.write("\n[%s] 拉起看板 %d\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), BOARD_PORT))
    fh.flush()
    subprocess.Popen([sys.executable, BOARD_SCRIPT, "--port", str(BOARD_PORT)],
                     cwd=HERE, env=env, creationflags=DETACHED,
                     stdout=fh, stderr=subprocess.STDOUT)
    for _ in range(50):
        if port_up(BOARD_PORT):
            return True
        time.sleep(0.4)
    return False


def main():
    print("=" * 62)
    print("网盘一条龙:OpenList(5244) + 数据看板(8090)")
    print("=" * 62)

    ok_ol = nd.ensure_server()
    print("  OpenList   127.0.0.1:5244  %s" % ("在听" if ok_ol else "起不来"))
    if not ok_ol:
        print("    查一下:%s" % os.path.join(nd.OL_DIR, "data", "log", "log.log"))

    ok_bd = start_board()
    print("  数据看板   127.0.0.1:%d  %s" % (BOARD_PORT, "在听" if ok_bd else "起不来"))
    if not ok_bd:
        print("    查一下:%s" % BOARD_LOG)

    if ok_bd:
        url = "http://%s:%d/#netdisk" % (BOARD_HOST, BOARD_PORT)
        print("\n打开网盘页签(扫码登录的按钮就在这页顶上):%s" % url)
        try:
            webbrowser.open(url)
        except Exception:
            print("  浏览器没能自动打开,手工访问上面那个地址。")
    if not os.environ.get("OPENLIST_ADMIN_PASSWORD"):
        print("\n警告:这个窗口里没有 OPENLIST_ADMIN_PASSWORD,扫码认出的账号存不进 OpenList"
              "(建挂载点那一步要管理员口令)。"
              "\n  设一次:setx OPENLIST_ADMIN_PASSWORD \"你的密码\"(设完要重开这个窗口)"
              "\n  只报「有没有设」,永远不读它的值。")
    print("\n下一步(在浏览器里):选盘 → 按『▶ 打开扫码窗口』→ 手机扫那个二维码 → 什么都不用填,"
          "这一页每 2 秒问一次、这一页关着看板服务端也每 15 秒自己巡一遍,网盘认出是真账号了就自动抓 cookie、自动起名字(ID 尾巴)入库。")
    print("手上有 refresh_token/账号密码(百度/迅雷)才展开下面的『手填凭据』。")
    print("存进去的 cookie 由 Windows DPAPI 加密,只有你本机这个账户能解开;页面不回显任何值。")
    print("两个服务都在后台跑,这个窗口可以关。看板 Ctrl+C 或任务管理器结束 python 即停。")
    return 0 if (ok_ol and ok_bd) else 1


if __name__ == "__main__":
    sys.exit(main())
