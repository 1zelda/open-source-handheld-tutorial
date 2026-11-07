# -*- coding: utf-8 -*-
"""本机代理口只有一个事实来源。

为什么要有这个文件：代理口不是常量。Clash Verge 用 7890 用了一阵，11-04 换到 7891，
而两处残留都还写着旧口 —— shell 里继承的 HTTPS_PROXY=http://127.0.0.1:7890，
以及 ~/.gitconfig 里的 http.proxy（环境变量盖不掉它）。所以"现在该走哪个口"必须
**探出来**，不能读环境变量，也不能去改全局 git 配置（那是账号级/机器级改动，不动）。

旧口留在候选里兜底：代理软件哪天再换回去，这条线不用改代码。
"""
import os
import socket

PORTS = (7891, 7890)          # 新口在前，旧口兜底
_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
         "http_proxy", "https_proxy", "all_proxy")
_url = None                   # 探一次就记住：每条命令都重探会把整批 clone 拖慢


def proxy_url():
    """活着的那个口的 URL；一个都不活返回空串（＝直连）。"""
    global _url
    if _url is None:
        _url = ""
        for p in PORTS:
            s = socket.socket()
            s.settimeout(1.5)
            try:
                s.connect(("127.0.0.1", p))
                _url = "http://127.0.0.1:%d" % p
                break
            except OSError:
                pass
            finally:
                s.close()
    return _url


def alive():
    return bool(proxy_url())


def env(base=None):
    """把代理变量显式写成探到的那个口；没活着的一律清空。
    继承来的 HTTPS_PROXY 可能是旧口，所以"活着"这一支也要覆盖，不能原样返回。"""
    e = dict(os.environ if base is None else base)
    u = proxy_url()
    for k in _KEYS:
        e[k] = u
    if u and not (e.get("NO_PROXY") or e.get("no_proxy")):
        # 本机服务不能绕代理：127.0.0.1 上的调用被代理截过（ollama/OpenList 都栽过）
        e["NO_PROXY"] = "localhost,127.0.0.1,::1"
    return e


def git_flags():
    """给 git 用的显式覆盖：`-c http.proxy=<口> -c https.proxy=<口>`。
    两种状态都得给 —— 走代理时要盖掉 ~/.gitconfig 里的旧口，直连时要盖掉它写的 7890。"""
    u = proxy_url()
    return ["-c", "http.proxy=" + u, "-c", "https.proxy=" + u]


def describe():
    u = proxy_url()
    return "代理 %s 可用" % u if u else "代理 %s 都不通，走直连" % ("/".join(map(str, PORTS)),)
