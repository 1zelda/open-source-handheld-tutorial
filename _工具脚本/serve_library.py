#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""serve_library.py —— 把教程库以只读 HTTP 服务出去(2026-10-21 新增)

用途:XiFan XF45V / 手机 / 局域网内任何设备直接读 01-教程库、03/05 资料和
06 的报告,不用再来回拷文件。http.server 只实现 GET/HEAD,天然只读。

用法:
  py -3 _工具脚本/serve_library.py                # 只绑 127.0.0.1:8080(只有本机能看)
  py -3 _工具脚本/serve_library.py --lan          # 绑 0.0.0.0,局域网设备可读
  py -3 _工具脚本/serve_library.py --lan --port 8088

安全边界(默认最小暴露):
  - 默认只听 127.0.0.1;--lan 是显式选择,会打印本机所有网卡地址。
  - 不设上传/删除(SimpleHTTPRequestHandler 只有 GET/HEAD)。
  - 服务范围是整个库根目录(04-游戏资源库 也在内 —— 那里面只有合法收录与自制软件,
    没有商业 ROM/BIOS,见 README 的边界一节);要缩小范围改 --root。
"""
import argparse
import functools
import http.server
import os
import socket
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lan_ips():
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lan", action="store_true", help="绑 0.0.0.0(局域网可读);默认只绑 127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--root", default=ROOT, help="服务根目录(默认整个库)")
    args = ap.parse_args()

    bind = "0.0.0.0" if args.lan else "127.0.0.1"
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=args.root)
    with http.server.ThreadingHTTPServer((bind, args.port), handler) as srv:
        print("教程库只读服务:http://127.0.0.1:%d/  (root=%s)" % (args.port, args.root))
        if args.lan:
            for ip in lan_ips():
                print("  局域网:http://%s:%d/" % (ip, args.port))
            print("  Ctrl+C 停止;只读(GET/HEAD),不设上传删除")
        else:
            print("  (只听本机;要给别人/掌机用加 --lan)")
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\n停了")


if __name__ == "__main__":
    main()
