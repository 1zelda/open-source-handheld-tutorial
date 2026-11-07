#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""网盘扫码登录.py —— 开一个本机浏览器的独立窗口登录网盘,再用 CDP 把 cookie 抓回来。

为什么要自己开浏览器(2026-11-05 查过):
  OpenList 的夸克/百度/迅雷三个驱动**没有扫码入口**。我把 openlist.exe 里二维码相关的
  字符串翻了一遍,"二维码"/"getQrCode"/"qrcodeLogin" 只落在 115 和联通云盘(189)身上,
  所以指望 OpenList 后台"点一下出二维码"是不存在的,只能自己把网盘的登录页开到用户眼前。

为什么读浏览器的 cookie 而不是让用户按 F12:
  用户是网络外行,"F12→Network→Cookie 头"这条路他走不通;而且夸克的 __pus/__puus、
  百度的 BDUSS 都是 httpOnly,页面的 document.cookie 根本看不见它们。
  CDP 的 Network.getAllCookies 拿的是浏览器存储里的全量(含 httpOnly),而且只限我们
  自己开的那个 user-data-dir —— 不碰用户日常浏览器的 cookie 库。

四条硬规矩:
  1) cookie 的值只在这个函数的返回值里存在,不落日志、不落文件、不回界面;
     界面只看名字和个数。要留痕只有 名称/域/路径。
  2) 调试端口只绑 127.0.0.1(Edge/Chrome 的 --remote-debugging-port 就是回环),
     而且用的是独立 profile —— 关掉窗口就什么都留不下。
  3) 端口按「盘 × 槽位」分配:夸克 9331、百度 9332、迅雷 9333 是**第 1 槽**,
     第 n 槽 = 基址 + (n-1)*10(夸克第 2 槽 9341)。槽位 1 的路径和端口一个字没动,
     旧账号照样能用。
  4) 一个 profile 只有一个登录位:同一个槽里登第二个号,会把第一个号从这个 cookie 罐里
     挤掉 —— 所以「多账号」不是多开浏览器,是**多开槽位**,每个槽各一个 profile。

为什么不直接读你日常浏览器里已经登着的号(2026-11-05 实测,四条都堵):
  a) Chrome 156 / Edge 136 / Edge Dev 的 cookie 全是 v20 前缀 = App-Bound 加密。本机
     Local State 里的 os_crypt.app_bound_encrypted_key 头部是 "APPB\x01",拿 DPAPI 解直接
     失败(err=13 ERROR_DATA_NOT_VALID) —— 只有浏览器自己那侧解得开,别的进程读不走。
     对照:我们独立 profile 里的 cookie 是 v10,同一份 DPAPI 测试解开 32 字节主密钥,顺利。
  b) 日常 Edge 正在跑(20 个 msedge 进程),它的 Network/Cookies 连只读打开都拒绝:
     "unable to open database file"。
  c) 就算能读也没号可捞:Chrome/Profile 1 的 421 条里没有任何 quark 域;Edge Dev 那 617 条里
     只有 .quark.cn/b.quark.cn/pan.quark.cn 的埋点 cookie(_UP_A4A_11_/isg/tfstk/b-user-id),
     **没有 __pus/__kps/__uid 这套登录态**,即没登录;Firefox 172 条里连 quark 域都没有。
     本机唯一真登着夸克的 profile,就是我们自己的 F:\OpenList\扫码登录\profile-Quark。
  d) 拿 --remote-debugging-port 去接日常浏览器的现成会话也不行:调试端口只在**非默认**
     user-data-dir 上生效,把用户日常那份目录传进去,浏览器会忽略这个开关。
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time

try:
    import websocket                      # websocket-client,本机 1.8.0
except ImportError:                       # 缺库不炸导入:界面会点名说这条走不了
    websocket = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import net_proxy                           # noqa: E402  本机调用必须绕开代理口
import netdisk_upload as nd                # noqa: E402  OL_DIR 与统一日志

BASE_DIR = os.path.join(nd.OL_DIR, "扫码登录")
DETACHED = 0x00000008 | 0x00000200
MAX_SLOTS = 10          # 一个盘最多开几个登录位(你说每个盘可能挂十个号,按十格算)

# 每个盘:登录页 + 第 1 槽的调试端口(第 n 槽见 port_of)+ cookie 归到哪个域 + 这个盘的登录方式 + 界面该怎么教用户。
# 登录页给的是首页,不是猜的深链:夸克/百度会把没登录的人自己带到登录框,省得我们写死一个会变的地址。
# markers 只用来"看一眼抓到些啥",**不能**拿来判"登录上了"——独立 profile 第一次打开夸克就自动有了
# __pus/__puus/__uid(游客态也发)。判登录由账号台问 pan.quark.cn/account/info:游客拿不到 nickname。
# (drive.quark.cn 那个 member 接口只用来读会员档和容量,不拿来判登录:11-05 记的「它要客户端签名、裸问必回
#  31001 guest」是误判,少了 pr 参数而已——带 ?pr=ucpro&fr=pc 只凭 cookie 就回 code=0。判登录仍只看 nickname。)
DISKS = {
    "Quark": {
        "label": "夸克网盘", "port": 9331, "url": "https://pan.quark.cn/",
        "domains": ("quark.cn",), "markers": ("__pus", "__puus"), "field": "cookie",
        "kind": "qrcode",
        "howto": "① 点『打开扫码窗口』,夸克登录页开在一个独立窗口(不碰你日常浏览器) ② 手机夸克 App 扫窗口里的二维码 ③ 扫完什么都不用回来填:这一页每 2 秒问一次,"
                 "这一页关着也有看板服务端每 15 秒自己巡一遍,网盘那边认出是真账号了才存,并自动起名字。\n"
                 "      要登第二个号:把上面的『登录位』调到 2 再点打开 —— 那是另一个独立 profile,里面是干净的游客态,"
                 "扫进去不会顶掉第 1 个号的登录态(每个号各占一格,互不打扰)。",
    },
    "BaiduNetdisk": {
        "label": "百度网盘", "port": 9332, "url": "https://pan.baidu.com/",
        "domains": ("baidu.com",), "markers": ("BDUSS",), "field": "",
        "kind": "oauth",
        "howto": "百度这个盘在 OpenList 里要的是 refresh_token(OAuth),不是 cookie —— 所以扫码抓 cookie "
                 "对它没用。窗口可以先开给你登录看内容;真挂载还差一步授权换 token(下一步做)。",
    },
    "Thunder": {
        "label": "迅雷云盘", "port": 9333, "url": "https://pan.xunlei.com/",
        "domains": ("xunlei.com",), "markers": ("actoken", "token"), "field": "",
        "kind": "password",
        "howto": "迅雷这个盘在 OpenList 里要的是账号+密码(下面表单的 username + password 两格),不是 cookie。"
                 "填完直接按『保存并挂载 + 立刻探测』;要扫码看内容再点『打开登录窗口』。",
    },
}

BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)
# 本机装着但**用不了**的浏览器,界面里点名说清为什么,免得用户以为漏了他哪个号。
UNUSABLE = (
    (r"C:\Program Files\Mozilla Firefox\firefox.exe",
     "Firefox 不吃 --remote-debugging-port(它只有 Juggernaut/geckodriver 那套),CDP 抓不到 cookie"),
)


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg))


def browsers():
    """本机可用的、能开独立 profile + 调试端口的浏览器。第一个是默认。"""
    out = []
    for p in BROWSERS:
        if not os.path.isfile(p):
            continue
        vers = [n for n in os.listdir(os.path.dirname(p)) if re.match(r"^\d+(\.\d+)+$", n)
                and os.path.isdir(os.path.join(os.path.dirname(p), n))]
        out.append({"exe": p, "name": os.path.splitext(os.path.basename(p))[0],
                    "file": os.path.basename(p), "version": (vers or ["?"])[0]})
    return out


def browser_exe(exe=""):
    """给了就用给的那个(必须在本机检出列表里),没给就挑第一个。"""
    ok = [b["exe"] for b in browsers()]
    if exe and exe in ok:
        return exe
    return ok[0] if ok else ""


def unusable():
    """装了但走不通的浏览器,连同走不通的原因(界面/命令行要说清哪条堵)。"""
    return [{"file": os.path.basename(p), "why": why}
            for p, why in UNUSABLE if os.path.isfile(p)]


# ---------------------------------------------------------------- 槽位:一个盘 N 个登录位

def _slot(slot):
    try:
        n = int(str(slot).strip() or 1)
    except (TypeError, ValueError):
        n = 1
    return max(1, min(MAX_SLOTS, n))


def port_of(driver, slot=1):
    """第 1 槽用盘的老端口(9331/9332/9333,一个字没动),往后每槽 +10。"""
    d = DISKS.get(driver) or {}
    return int(d.get("port") or 0) + (_slot(slot) - 1) * 10


def profile_of(driver, slot=1):
    n = _slot(slot)
    name = "profile-%s" % driver if n == 1 else "profile-%s-%02d" % (driver, n)
    return os.path.join(BASE_DIR, name)


def state_path(driver, slot=1):
    n = _slot(slot)
    name = "session-%s.json" % driver if n == 1 else "session-%s-%02d.json" % (driver, n)
    return os.path.join(BASE_DIR, name)


def _read_state(driver, slot=1):
    try:
        with open(state_path(driver, slot), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _write_state(driver, slot, st):
    os.makedirs(BASE_DIR, exist_ok=True)
    with open(state_path(driver, slot), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def _rm_state(driver, slot=1):
    try:
        os.remove(state_path(driver, slot))
    except OSError:
        pass


def port_alive(port, timeout=0.4):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        s.close()


def _http_json(port, path, timeout=3.0):
    """只问 127.0.0.1 上的调试端口,一个字节都不出本机。"""
    import urllib.request
    with urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def page_target(port):
    """挑一个真正在显示网盘页面的 target。新开的窗口可能先落在"新标签页",那没意义。"""
    try:
        tabs = _http_json(port, "/json/list")
    except Exception as e:
        return None, "调试端口没回话:%s" % type(e).__name__
    pages = [t for t in tabs if t.get("type") == "page"]
    if not pages:
        return None, "浏览器里没有可控制的页面(target 是空的)"
    http = [t for t in pages if (t.get("url") or "").startswith("http")]
    return (http or pages)[0], ""


class Cdp:
    """够用就好的 CDP 客户端:一条命令一个回话,不引额外依赖。"""

    def __init__(self, ws_url, timeout=8.0):
        if websocket is None:
            raise RuntimeError("缺 websocket-client 库(python -m pip install websocket-client),扫码抓 cookie 走不了")
        self.ws = websocket.create_connection(ws_url, timeout=timeout, suppress_origin=True)
        self.n = 0

    def call(self, method, params=None):
        self.n += 1
        mid = self.n
        self.ws.send_text(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + self.ws.gettimeout() + 2
        while time.time() < deadline:
            got = json.loads(self.ws.recv())
            if got.get("id") == mid:
                if got.get("error"):
                    raise RuntimeError("%s -> %s" % (method, got["error"].get("message", got["error"])))
                return got.get("result") or {}
        raise RuntimeError("%s 没回话(超时)" % method)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def _cdp(port, method, params=None, want_page=True):
    if want_page:
        tgt, why = page_target(port)
        if not tgt:
            raise RuntimeError(why)
        ws_url = tgt.get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("这个 target 没有 webSocketDebuggerUrl(浏览器版本或开关问题)")
    else:
        ws_url = _http_json(port, "/json/version").get("webSocketDebuggerUrl")
        if not ws_url:
            raise RuntimeError("浏览器级 target 没给 webSocketDebuggerUrl")
    c = Cdp(ws_url)
    try:
        return c.call(method, params)
    finally:
        c.close()


# ---------------------------------------------------------------- 开 / 看 / 抓 / 关(都按「盘 × 槽位」)

def start(driver, slot=1, exe_hint=""):
    d = DISKS.get(driver)
    if not d:
        return {"ok": False, "msg": "不认识的盘 %s" % driver}
    if websocket is None:
        return {"ok": False, "msg": "缺 websocket-client 库,抓不了 cookie(装一下:pip install websocket-client)"}
    n = _slot(slot)
    exe = browser_exe(exe_hint)
    if not exe:
        return {"ok": False, "msg": "本机没找到 Edge/Chrome,开不了登录窗口"}
    port = port_of(driver, n)
    profile = profile_of(driver, n)
    if port_alive(port):
        return {"ok": True, "msg": "第 %d 槽的窗口已经在开着了(127.0.0.1:%d),直接扫就行" % (n, port),
                "port": port, "slot": n, "url": d["url"], "reused": True, "exe": exe,
                "profile": profile,
                "started_at": (_read_state(driver, n) or {}).get("started_at", "")}
    fresh = not os.path.isdir(profile)         # 新建的槽位=游客态,界面该催用户扫;老槽位里可能已经登着号
    os.makedirs(profile, exist_ok=True)
    args = [exe, "--remote-debugging-port=%d" % port, "--user-data-dir=%s" % profile,
            "--no-first-run", "--no-default-browser-check", "--disable-sync",
            "--new-window", d["url"]]
    env = net_proxy.env()           # 代理口现探,别写死;127.0.0.1 一律直连(它自己会加 NO_PROXY)
    log("开浏览器 第%d槽:%s profile=%s(独立窗口,不碰你日常浏览器的 cookie)"
        % (n, os.path.basename(exe), profile))
    p = subprocess.Popen(args, cwd=BASE_DIR, env=env, creationflags=DETACHED,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if port_alive(port):
            break
        time.sleep(0.3)
    else:
        try:
            p.kill()
        except Exception:
            pass
        return {"ok": False, "msg": "浏览器起来了但调试端口 127.0.0.1:%d 连不上(可能被组策略禁了调试端口)" % port}
    _write_state(driver, n, {"driver": driver, "slot": n, "pid": p.pid, "port": port,
                             "profile": profile, "exe": exe,
                             "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    return {"ok": True, "msg": "第 %d 槽的登录窗口开好了(%s,端口 %d)—— 手机扫码,扫完这里自动认出来"
                            % (n, d["label"], port),
            "port": port, "slot": n, "url": d["url"], "pid": p.pid, "profile": profile,
            "exe": exe, "fresh_profile": fresh,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}


def shot(driver, slot=1):
    """把当前页面截一张 PNG 回来,给界面当"实时二维码"显示。截图里可能有二维码,
    但二维码不是凭据:它只在浏览器和本机之间显示,我不落盘、不进台账。"""
    if driver not in DISKS:
        return None, "不认识的盘 %s" % driver
    port = port_of(driver, slot)
    if not port_alive(port):
        return None, "窗口没开着"
    try:
        res = _cdp(port, "Page.captureScreenshot", {"format": "png"})
        import base64
        return base64.b64decode(res.get("data") or ""), ""
    except Exception as e:
        if "Timeout" in type(e).__name__ or isinstance(e, TimeoutError):
            # 端口在听、页面也在,就是截不到帧 —— 实测唯一的原因是窗口被最小化了(最小化=不画帧)。
            # 别把 WebSocketTimeoutException 甩给用户看,那句话没人知道该干什么。
            return None, ("窗口开着但画面取不到——八成是它被最小化了(最小化以后浏览器就不画帧)。"
                          "把这一格的扫码窗口从任务栏点回屏幕上,画面立刻就有。")
        return None, "%s: %s" % (type(e).__name__, str(e)[:160])


def page_url(driver, slot=1):
    if driver not in DISKS:
        return ""
    port = port_of(driver, slot)
    if not port_alive(port):
        return ""
    tgt, _ = page_target(port)
    return (tgt or {}).get("url", "")


def cookie_names(driver, slot=1):
    """只回名字和域,值不给界面。判定登录状态用名字就够。

    走浏览器级 target 的 Storage.getCookies:页面级 Network.getAllCookies 在页面刚加载时
    会超时(实测 17:56 那次就是),而且页面 target 可能还没建好;浏览器级不受这两个影响。
    """
    d = DISKS.get(driver)
    if not d:
        return None, "不认识的盘 %s" % driver
    port = port_of(driver, slot)
    if not port_alive(port):
        return None, "窗口没开着"
    last = ""
    for _ in range(3):
        try:
            jar = _cdp(port, "Storage.getCookies", want_page=False).get("cookies") or []
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e)[:160])
            time.sleep(0.6)
            continue
        mine = [c for c in jar if any(dom in (c.get("domain") or "") for dom in d["domains"])]
        return mine, ""
    return None, last or "读不到 cookie"


def slots(driver):
    """这个盘有哪几格登录位:profile 在不在、端口在不在听、哪格被哪个窗口占着。
    给界面出「登录位」下拉用;十格全出,空的也列出来,用户才知道还能往下登几个。"""
    if driver not in DISKS:
        return []
    out = []
    for n in range(1, MAX_SLOTS + 1):
        prof = profile_of(driver, n)
        st = _read_state(driver, n) or {}
        out.append({"slot": n, "port": port_of(driver, n),
                    "profile": os.path.basename(prof),
                    "profile_exists": os.path.isdir(prof),
                    "listening": port_alive(port_of(driver, n)),
                    "started_at": st.get("started_at", ""),
                    "exe": os.path.basename(st.get("exe") or "")})
    return out


def purge(driver, slot=1):
    """把这一槽的独立 profile 整包删掉 —— 那里面是浏览器自己的登录态(v10,DPAPI 能解),
    不想留在 F 盘就点这个;代价是这一格下次要重新扫,别的槽不受影响。
    只认我们自己的目录,别的地址一律不删。"""
    if driver not in DISKS:
        return {"ok": False, "msg": "不认识的盘 %s" % driver}
    n = _slot(slot)
    st = _read_state(driver, n) or {}
    prof = st.get("profile") or profile_of(driver, n)
    if not prof.startswith(BASE_DIR + os.sep):
        return {"ok": False, "msg": "profile 路径不在 %s 底下,不敢删:%s" % (BASE_DIR, prof)}
    close(driver, n)
    import shutil
    if os.path.isdir(prof):
        try:
            shutil.rmtree(prof)
        except Exception as e:
            return {"ok": False, "msg": "删不掉(窗口还占着文件?):%s: %s" % (type(e).__name__, str(e)[:120])}
    return {"ok": True, "msg": "第 %d 槽的独立 profile 已删:%s" % (n, prof)}


def _pair(c):
    return "%s=%s" % (c["name"], c.get("value", ""))


def build_cookie(driver, slot=1):
    """按 OpenList 的口径拼 Cookie 头:同域多条全带上,登录标志缺一条就当没登录。
    返回值含凭据,调用方只能当场用掉,不许打印、不许落盘。"""
    d = DISKS[driver]
    mine, why = cookie_names(driver, slot)
    if mine is None:
        return None, why, []
    names = {c["name"] for c in mine}
    miss = [m for m in d["markers"] if m not in names]
    if miss:
        return None, "还没扫上:缺 %s(现在 %d 条)" % ("、".join(miss), len(mine)), sorted(names)
    mine.sort(key=lambda c: (c.get("domain") or "", c["name"]))
    return "; ".join(_pair(c) for c in mine), "", sorted(names)


def close(driver, slot=1):
    if driver not in DISKS:
        return {"ok": False, "msg": "不认识的盘 %s" % driver}
    n = _slot(slot)
    port = port_of(driver, n)
    st = _read_state(driver, n) or {}
    if port_alive(port):
        try:
            _cdp(port, "Browser.close", want_page=False)
        except Exception:
            pass
        for _ in range(20):
            if not port_alive(port):
                break
            time.sleep(0.2)
    if port_alive(port) and st.get("pid"):
        try:
            subprocess.run(["taskkill", "/PID", str(st["pid"])], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)   # 不带 /T:那是另一个进程的树
        except Exception:
            pass
    _rm_state(driver, n)
    return {"ok": not port_alive(port), "slot": n, "port": port,
            "msg": ("第 %d 槽的窗口关好了" % n if not port_alive(port)
                    else "第 %d 槽的窗口没关掉(端口还在 %d)" % (n, port))}


def status(driver, slot=1):
    """界面每 2 秒问一次(经账号台的 qr poll 转一手):窗口在不在、页面到哪了、抓到几条、都是什么名字。
    这里**不判**"登录上了没"——那由账号台拿网盘自己的接口验,名字齐不等于登录。"""
    d = DISKS.get(driver)
    if not d:
        return {"ok": False, "msg": "不认识的盘 %s" % driver}
    n = _slot(slot)
    port = port_of(driver, n)
    st = _read_state(driver, n) or {}
    up = port_alive(port)
    mine, why = (None, "窗口没开着")
    if up:
        mine, why = cookie_names(driver, n)
    names = sorted({c["name"] for c in mine}) if mine else []
    have = [m for m in d["markers"] if m in names]
    return {"ok": True, "driver": driver, "label": d["label"], "kind": d["kind"],
            "slot": n, "max_slot": MAX_SLOTS, "listening": up, "port": port,
            "url": page_url(driver, n) if up else "",
            "profile": os.path.basename(profile_of(driver, n)),
            "profile_exists": os.path.isdir(profile_of(driver, n)),
            "exe": os.path.basename(st.get("exe") or ""),
            "login_url": d["url"], "howto": d["howto"], "field": d["field"],
            "cookie_count": len(mine or []), "names": names[:40],
            "markers": list(d["markers"]), "markers_have": have,
            "msg": why or "", "started_at": st.get("started_at", "")}


# ---------------------------------------------------------------- 命令行

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["start", "status", "shot", "close", "purge", "slots", "disks"])
    ap.add_argument("driver", nargs="?", default="Quark")
    ap.add_argument("--slot", default="1", help="登录位第几格(1~%d);1 是老端口,别动" % MAX_SLOTS)
    ap.add_argument("--exe", default="", help="用哪个浏览器开这个窗口(默认本机第一个)")
    ap.add_argument("--out", default="", help="shot 的 PNG 写到哪(调试用;默认 _scratch)")
    a = ap.parse_args()
    if a.cmd == "disks":
        for k, v in DISKS.items():
            print("%-14s %-6s 第1槽端口 %-5s 标志 cookie %s" % (k, v["label"], v["port"], "、".join(v["markers"])))
        for b in browsers():
            print("浏览器: %-16s %-5s %s" % (b["file"], b["version"], b["exe"]))
        for u in unusable():
            print("用不了: %-16s %s" % (u["file"], u["why"]))
        return 0
    if a.cmd == "slots":
        print(json.dumps(slots(a.driver), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "start":
        r = start(a.driver, a.slot, a.exe)
        print(json.dumps({k: v for k, v in r.items() if k != "url"} , ensure_ascii=False, indent=1))
        return 0 if r["ok"] else 1
    if a.cmd == "status":
        s = status(a.driver, a.slot)
        print(json.dumps(s, ensure_ascii=False, indent=1))
        return 0 if s["ok"] else 1
    if a.cmd == "shot":
        png, why = shot(a.driver, a.slot)
        if png is None:
            print("截图失败:", why)
            return 1
        out = a.out or os.path.join(ROOT, "_scratch", "扫码登录-%s-%s.png" % (a.driver, _slot(a.slot)))
        with open(out, "wb") as f:
            f.write(png)
        print("写了 %s(%d 字节)" % (out, len(png)))
        return 0
    if a.cmd == "close":
        r = close(a.driver, a.slot)
        print(r["msg"])
        return 0 if r["ok"] else 1
    if a.cmd == "purge":
        r = purge(a.driver, a.slot)
        print(r["msg"])
        return 0 if r["ok"] else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
