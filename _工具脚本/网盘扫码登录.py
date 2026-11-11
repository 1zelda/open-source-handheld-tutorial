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

from concurrent.futures import ThreadPoolExecutor

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


def _max_slots():
    """一个盘最多开几个登录位。11-08 用户要求「每个平台 15~20 个」，默认 20 格。
    留一个环境变量口子：OPENLIST_QR_MAX_SLOTS=15 这种，重开看板即生效（要重启进程）。"""
    try:
        n = int(os.environ.get("OPENLIST_QR_MAX_SLOTS") or 0)
    except (TypeError, ValueError):
        n = 0
    return n if 2 <= n <= 60 else 20


MAX_SLOTS = _max_slots()

# headless 默认开:用户明确要求「不要弹窗口」,画面由 shot() 裁成登录卡片回给看板。
# 实测(11-08 09:0x)夸克在 headless 下二维码照常渲染;要临时改回真窗口:OPENLIST_QR_HEADED=1。
QR_HEADED = os.environ.get("OPENLIST_QR_HEADED", "") not in ("", "0", "false", "no")
# 必须盖掉默认的 HeadlessChrome UA,否则夸克首页不渲染右侧登录卡片(实测)。
QR_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0")

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
        "kind": "qrcode", "mount_by": "cookie",
        "howto": "手机夸克 App 扫上面的码 → 自动占一个空槽入库，不用选槽、不用回来填。",
    },
    "BaiduNetdisk": {
        "label": "百度网盘", "port": 9332, "url": "https://pan.baidu.com/",
        "domains": ("baidu.com",), "markers": ("BDUSS",), "field": "",
        "kind": "oauth", "mount_by": "refresh_token",
        "howto": "OpenList 挂百度要 refresh_token（不是 cookie）—— 扫码只能登进来看内容，挂载请在下面表单填 refresh_token。",
    },
    "Thunder": {
        "label": "迅雷云盘", "port": 9333, "url": "https://pan.xunlei.com/",
        "domains": ("xunlei.com",), "markers": ("actoken", "token"), "field": "",
        "kind": "password", "mount_by": "password",
        "howto": "迅雷要账号+密码：下面表单填 username / password，按保存即可挂载（扫码只能看内容）。",
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


def _tab_url(port):
    """端口上浏览器当前主页面 URL —— 只读 /json/list,不开 websocket,便宜(给 slots 并发探用)。
    取不到(端口没回话/还没有页面)回 ''。"""
    try:
        tabs = _http_json(port, "/json/list", timeout=2.0)
    except Exception:
        return ""
    pages = [t for t in tabs if t.get("type") == "page"]
    if not pages:
        return ""
    http = [t for t in pages if (t.get("url") or "").startswith("http")]
    return ((http or pages)[0].get("url") or "")


def _page_hijacked(driver, url):
    """端口还通、profile 还是我们的,但页面被别的程序用 CDP 导航走了 —— 这种槽不能再当登录窗口。
    (11-08 实测:录播 webui 连上夸克第 4 槽的调试端口 9361,把我们那个 headless 浏览器导到了它自己的
     file:///F:/录播.../reaction.html;端口探通、profile 也对,可页面已经不是登录页了。)
    只认**明确的外来 URL**(file:// 或别的 http 域)才算被占;空白页/新标签页(刚开窗还在加载)
    和取不到 URL 都不算,免得误杀刚开好的窗口。"""
    if not url:
        return False
    if url.startswith(("about:", "chrome:", "edge:")):
        return False
    d = DISKS.get(driver) or {}
    if url.startswith("http") and any(dom in url for dom in d.get("domains", ())):
        return False
    return True


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

def start(driver, slot=1, exe_hint="", fresh=False):
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
        occupied = _tab_url(port)
        if _page_hijacked(driver, occupied):
            # 这一格的调试端口被别的程序连上、页面导航走了(11-08:录播 webui 把第 4 槽导到它自己的
            # reaction.html)——那不是登录窗口,以前在这儿直接报错,用户看到的就是「点了没反应」。
            # 现在先把它关掉,下面照常开一格干净的。
            close(driver, n)
            time.sleep(0.3)          # close() 已经等到端口关了,这点余量只是让进程把手上的锁放掉
        elif fresh:
            # 用户点的是「扫码登录」= 要一张新码。上一轮的窗口就算还开着,页面也早就不在登录态了
            # (11-08 13:47:窗口挂了一上午,截图一直 503),重开一格干净的比复用靠谱。
            close(driver, n)
            time.sleep(0.3)
        else:
            return {"ok": True, "msg": "第 %d 槽已经在跑了（后台·不弹窗），直接扫上面的码就行" % n,
                    "port": port, "slot": n, "url": d["url"], "reused": True, "exe": exe,
                    "profile": profile,
                    "started_at": (_read_state(driver, n) or {}).get("started_at", "")}

    fresh = not os.path.isdir(profile)         # 新建的槽位=游客态,界面该催用户扫;老槽位里可能已经登着号
    os.makedirs(profile, exist_ok=True)
    # 冷启动这几条是「点扫码登录要等半天」的主要来源:新 profile 一开,浏览器会先把组件更新、
    # 翻译、推荐、默认应用这些东西挨个拉一遍,才轮到页面。全关掉能省两三秒,而且不影响登录。
    args = [exe, "--remote-debugging-port=%d" % port, "--user-data-dir=%s" % profile,
            "--no-first-run", "--no-default-browser-check", "--disable-sync", "--lang=zh-CN",
            "--disable-background-networking", "--disable-component-update",
            "--disable-default-apps", "--no-service-autorun", "--disable-extensions",
            "--disable-client-side-phishing-detection", "--metrics-recording-only",
            "--disable-features=Translate,MediaRouter,OptimizationHints,CalculateNativeWinOcclusion",
            "--user-agent=%s" % QR_UA, "--window-size=1280,900"]
    if not QR_HEADED:
        args.insert(1, "--headless=new")
        args.insert(2, "--disable-gpu")
    else:
        args.append("--new-window")
    args.append(d["url"])
    env = net_proxy.env()           # 代理口现探,别写死;127.0.0.1 一律直连(它自己会加 NO_PROXY)
    log("开浏览器 第%d槽:%s profile=%s(独立窗口,不碰你日常浏览器的 cookie)"
        % (n, os.path.basename(exe), profile))
    p = subprocess.Popen(args, cwd=BASE_DIR, env=env, creationflags=DETACHED,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 端口探测的粒度 0.3s → 0.1s:浏览器常常 1.5 秒就起来了,却要等到下一个 0.3 秒的整拍
    for _ in range(100):
        if port_alive(port, 0.1):
            break
        time.sleep(0.1)
    else:
        try:
            p.kill()
        except Exception:
            pass
        return {"ok": False, "msg": "浏览器起来了但调试端口 127.0.0.1:%d 连不上(可能被组策略禁了调试端口)" % port}
    _write_state(driver, n, {"driver": driver, "slot": n, "pid": p.pid, "port": port,
                             "profile": profile, "exe": exe,
                             "started_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    # 11-08:开端口就返回会让第一枪截到首页(码还没渲染),用户「聚焦两次」。这里先把页面驱到
    # 二维码卡片再返回,第一张截图就是码;驱不到也不报错,上层照旧退首屏、下一拍再聚焦。
    focus_login(port)
    return {"ok": True, "msg": "第 %d 槽已就绪（后台运行，不弹窗口）—— 二维码就在上面那个框里，手机扫一下"
                            % n,
            "port": port, "slot": n, "url": d["url"], "pid": p.pid, "profile": profile,
            "exe": exe, "fresh_profile": fresh, "headless": not QR_HEADED,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}


CLEAR_JS = r"""
(() => {
  let n = 0;
  // 1) 点掉各种“×”关闭键（夸克首页会弹“客户端已登录，点击可直接登录”这类推广层，正好压在登录卡片上）
  document.querySelectorAll('div,span,button,a,i,svg').forEach((el) => {
    const t = (el.textContent || '').trim();
    if (!/^(×|✕|✖|✗|关闭|知道了)$/.test(t)) return;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.width < 64 && r.height > 0 && r.height < 64) {
      try { el.click(); n++; } catch (e) {}
    }
  });
  // 2) 兜底：把盖住页面的固定定位大弹层藏掉（不含二维码画布的那种）
  document.querySelectorAll('div').forEach((el) => {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' || cs.display === 'none') return;
    const r = el.getBoundingClientRect();
    if (r.width < 240 || r.height < 200) return;
    if (el.querySelector('canvas')) return;
    const cls = (el.className || '') + '';
    if (!/modal|dialog|mask|popup|guide|banner|toast/i.test(cls)) return;
    el.style.display = 'none'; n++;
  });
  // 3) 「客户端已登录，点击可直接登录」这张卡没有二维码 —— 交给 Python 那边用真鼠标点「扫码登录」
  //    （JS 的 el.click() 在这张卡上不触发，实测无效；真鼠标事件才切得动）。
  return n;
})()
"""

CARD_JS = r"""
(() => {
  // 以「二维码画布」为锚点，再往外长到卡片边框为止 —— 比按文字猜容器稳得多
  const cands = [...document.querySelectorAll('canvas')].map((c) => ({ c, r: c.getBoundingClientRect() }))
    .filter((o) => o.r.width >= 130 && o.r.width <= 380 && Math.abs(o.r.width - o.r.height) < 80)
    .sort((a, b) => b.r.width - a.r.width);
  if (!cands.length) return null;
  const anchor = cands[0], a = anchor.r;
  let el = anchor.c, best = { x: a.x, y: a.y, w: a.width, h: a.height };
  for (let i = 0; i < 7 && el.parentElement; i++) {
    el = el.parentElement;
    const r = el.getBoundingClientRect();
    if (r.width > 620 || r.height > a.height + 460) break;   // 再往外就是整页了
    if (r.width >= a.width + 40 && r.height >= a.height + 90) best = { x: r.x, y: r.y, w: r.width, h: r.height };
  }
  return best;
})()
"""


def _clear_overlays(port):
    """关掉压住登录卡片的推广层。返回真关掉了几处 —— 一处都没关就别再白等那 0.5 秒,
    这一步是每 2 秒一次的轮询都要走的,攒起来就是「画面怎么半天不出来」。"""
    try:
        r = _cdp(port, "Runtime.evaluate", {"expression": CLEAR_JS, "returnByValue": True})
        return int(((r or {}).get("result") or {}).get("value") or 0)
    except Exception:
        return 0


LOGIN_ENTRY_JS = r"""
(() => {
  // 页面停在网盘首页时压根没有登录卡片(夸克首页就是一张营销页 + 右上角一个「登录」)。
  // 这里把页面自己的登录入口找出来,交给 Python 用真鼠标点 —— 点完才有二维码可截。
  // 11-08 用户「没显示出二维码」:夸克首页顶栏写的是「直接登录」,以前只认
  // 登录/立即登录/马上登录这几个精确词,于是这个入口一直没被点,二维码自然出不来。
  // 改成「短、且含登录二字」就认,再排掉确实不是入口的那些词。
  const out = [];
  document.querySelectorAll('a,button,div,span,li,p').forEach((el) => {
    if (el.children.length > 2) return;
    const t = (el.textContent || '').replace(/\s+/g, '');
    if (!t || t.length > 8) return;
    if (!/登录|登陆/.test(t)) return;
    if (/下载|协议|已登录|未登录|登录后|登录中/.test(t)) return;
    const r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 14 || r.width > 240 || r.height > 72) return;
    if (r.top < 0 || r.left < 0 || r.top > window.innerHeight || r.left > window.innerWidth) return;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) return;
    if (cs.pointerEvents === 'none') return;
    out.push({x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
              w: Math.round(r.width), h: Math.round(r.height), text: t});
  });
  return out;
})()
"""

# port -> 上次「替用户点登录入口」的时刻。页面没卡片时每次轮询都去点一下,会把用户
# 刚展开的下拉/弹层点掉,所以同一个窗口 10 秒内只替人点一次。
_CARD_TRY = {}
_CARD_TRY_EVERY = 10.0


def _click_login_entry(port):
    """点页面自己的「登录」入口。挑最靠上、最靠右的那个(登录/注册基本都在顶栏右角)。"""
    try:
        r = _cdp(port, "Runtime.evaluate", {"expression": LOGIN_ENTRY_JS, "returnByValue": True})
        hits = ((r or {}).get("result") or {}).get("value") or []
    except Exception:
        return False
    if not hits:
        return False
    h = sorted(hits, key=lambda x: (x["y"], -x["x"]))[0]
    try:
        for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
            _cdp(port, "Input.dispatchMouseEvent",
                 {"type": typ, "x": h["x"], "y": h["y"], "button": "left", "clickCount": 1})
        return True
    except Exception:
        return False


QR_TAB_JS = r"""
(() => {
  const out = [];
  document.querySelectorAll('*').forEach((el) => {
    if (el.children.length > 3) return;
    const t = (el.textContent || '').replace(/\s+/g, '');
    if (t !== '扫码登录') return;
    const r = el.getBoundingClientRect();
    if (r.width < 8 || r.height < 8 || r.width > 220) return;
    out.push({x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
              w: Math.round(r.width), h: Math.round(r.height)});
  });
  return out;
})()
"""


def _click_qr_tab(port):
    """卡片停在「客户端已登录」时，用**真鼠标事件**点「扫码登录」——JS 的 click() 在这张卡上不生效。

    为什么会停在那张卡：本机装了夸克 PC 客户端且已登录（quark.exe），网页版会嗅到它，
    然后拿「点一下就登客户端那个号」替代二维码。对「加新号」来说这是死路，必须切回扫码。
    """
    try:
        r = _cdp(port, "Runtime.evaluate", {"expression": QR_TAB_JS, "returnByValue": True})
        hits = ((r or {}).get("result") or {}).get("value") or []
    except Exception:
        return False
    if not hits:
        return False
    h = max(hits, key=lambda x: x["w"] * x["h"])      # 取可点面积最大的那个
    try:
        for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
            _cdp(port, "Input.dispatchMouseEvent",
                 {"type": typ, "x": h["x"], "y": h["y"], "button": "left", "clickCount": 1})
        return True
    except Exception:
        return False


def card_clip(port, pad=10, ensure=True):
    """只截「登录这个框」——以二维码画布为锚点量出卡片 bbox，交给 CDP 裁。

    11-08 用户要求：不要弹窗口、画面聚焦在登录框上。窗口已经改成 headless（根本不出现），
    截图再按卡片裁一刀，看板里看到的就是一张放大的二维码，不用去碰浏览器。

    11-08 第二次（用户：「登录码完全不聚焦」）：裁不到卡片时**不再**退化成整页截图 ——
    整页截图放到那一格里，二维码只有指甲盖大，等于没给。量不到的常见原因是页面还停在首页
    （首页根本没有登录卡片），所以这里先替用户点一下页面自己的「登录」入口，再量一次；
    还是没有就点卡片上的「扫码登录」页签，再量。两次都不成就回 None，让上层明说「没找到二维码」。
    """
    if _clear_overlays(port):
        time.sleep(0.25)                     # 真关掉了弹层才值得等这一下
    clip = _clip_by_canvas(port, pad)
    if clip:
        return clip
    if not ensure:
        return None
    now = time.time()
    if now - _CARD_TRY.get(port, 0.0) < _CARD_TRY_EVERY:
        return None                          # 刚替人点过,别每 2 秒又点一次
    _CARD_TRY[port] = now
    if _click_login_entry(port):
        time.sleep(0.9)                      # 登录卡片多半是个带动画的弹层
        _clear_overlays(port)
        clip = _clip_by_canvas(port, pad)
        if clip:
            return clip
    if _click_qr_tab(port):
        time.sleep(1.2)
        _clear_overlays(port)
        return _clip_by_canvas(port, pad)
    return None


def focus_login(port, timeout=9.0):
    """开窗口后主动把页面驱到「二维码卡片」再返回 —— 让第一张截图就是码,而不是首页。

    11-08 用户:「一开始显示的不是二维码,需要聚焦两次才能聚焦到二维码,这个过程能快一点吗」。
    根因:start() 一探到调试端口就返回,这时夸克首页 DOM 往往还没加载完;前端紧接着的第一枪
    card_clip 点不到登录入口,退成整页首屏(page 模式),要等下一拍(2 秒)页面才就绪、才量得到码。
    这里在 start() 里一次性把页面驱到二维码再返回,画布一冒头就回,第一枪自然就是 card。

    顺序很关键:本机装着已登录的夸克 PC 客户端时,pan.quark.cn 直接给「客户端已登录,点击可
    直接登录」那张卡(没有二维码)。这时若先点顶栏「直接登录」会去登客户端那个号(对加新号是死路),
    所以**先点「扫码登录」页签**切出二维码;只有连扫码页签都没有(纯首页)才点登录入口把卡片叫出来。
    入口/页签点过就把 clicked_entry 置上,免得在二维码页上又把「微信登录」之类当入口点跑页。
    超时仍没码就回 False,上层照旧退首屏、下一拍再聚焦。"""
    _ensure_viewport(port)
    t0 = time.time()
    clicked_entry = False
    while time.time() - t0 < timeout:
        if not port_alive(port, 0.3):
            return False
        if _clear_overlays(port):
            time.sleep(0.2)
        if _clip_by_canvas(port):
            return True
        if _click_qr_tab(port):
            clicked_entry = True               # 已在登录卡上切扫码,别再点顶栏入口把页面带跑
            time.sleep(0.8)
            continue
        if not clicked_entry and _click_login_entry(port):
            clicked_entry = True
            _CARD_TRY[port] = time.time()      # 已替人点过,别让随后的 card_clip 十秒内又点一次
            time.sleep(0.8)                    # 登录卡片多半是个带动画的弹层
            continue
        time.sleep(0.35)                       # 页面还在加载,等下一轮再点
    return bool(_clip_by_canvas(port))


def _clip_by_canvas(port, pad=10):
    try:
        r = _cdp(port, "Runtime.evaluate", {"expression": CARD_JS, "returnByValue": True})
        v = ((r or {}).get("result") or {}).get("value") or None
    except Exception:
        return None
    if not v or not v.get("w") or not v.get("h"):
        return None
    return {"x": max(0.0, v["x"] - pad), "y": max(0.0, v["y"] - pad * 2),
            "width": v["w"] + pad * 2, "height": v["h"] + pad * 3, "scale": 2}


_MIN_VIEW_W = 1180
_MIN_VIEW_H = 780


def _viewport_of(port):
    """按端口读当前视口(CSS 像素)。只给截图这一层做判断用,不回给前端。"""
    try:
        r = _cdp(port, "Runtime.evaluate", {
            "expression": "JSON.stringify({w: window.innerWidth, h: window.innerHeight})",
            "returnByValue": True})
        v = json.loads(((r or {}).get("result") or {}).get("value") or "{}")
        return int(v.get("w") or 0), int(v.get("h") or 0)
    except Exception:
        return 0, 0


def _ensure_viewport(port, want_w=_MIN_VIEW_W, want_h=_MIN_VIEW_H):
    """窗口被开成很小的时候(实测有一格只剩 400x420),页面会被挤成一条:
    登录入口跑到视野外、二维码压根不在可视区 —— 这正是「没显示出二维码」的一种。
    这里用 Emulation 把渲染尺寸拉回正常值。只有明显过小才动,平时不重排(免得每 2 秒跳一次)。"""
    w, h = _viewport_of(port)
    if w >= want_w and h >= want_h:
        return False
    if QR_HEADED:
        # 真窗口模式下这个窗口是用户能看见、能自己拉大的,替它改渲染尺寸反而会看着别扭
        return False
    try:
        _cdp(port, "Emulation.setDeviceMetricsOverride", {
            "width": want_w, "height": want_h, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(0.35)                 # 等页面按新宽度重排完再截
        return True
    except Exception:
        return False


def _page_clip(port):
    """找不到二维码时的退路:截「首屏」而不是整篇长页。

    整页动辄 3000+ 像素高,整张缩到一个框里什么都看不清;只取首屏、并把四边各收一点,
    内容在框里就能显得大一些 —— 也就是用户要的「显示页面 + 稍微聚焦一点」。"""
    w, h = _viewport_of(port)
    if not w or not h:
        return None
    dx = int(w * 0.05)
    dy = int(h * 0.02)
    return {"x": dx, "y": dy, "width": max(320, w - dx * 2),
            "height": max(240, h - dy * 2), "scale": 1}


def shot(driver, slot=1, focus=True):
    """兼容老调用:只要 (png, err)。"""
    png, err, _mode = shot_ex(driver, slot, focus=focus)
    return png, err


# 最近一次 shot_ex 给每格用的裁剪框（{mode, clip}）。只存坐标不存图，给点击回传换算用。
_LAST_SHOT = {}


def last_shot(driver, slot=1):
    """这一格最近那张截图的裁剪框（x/y/scale）。前端拿它把图上点击映射回网页坐标。
    回一份独立副本:clip 也拷一层,调用方改它不会污染存着的那份(下一张还要靠它换算)。"""
    rec = _LAST_SHOT.get((driver, _slot(slot))) or {}
    clip = rec.get("clip")
    return {"mode": rec.get("mode", ""),
            "clip": (dict(clip) if isinstance(clip, dict) else clip)}


def shot_ex(driver, slot=1, focus=True):
    """把当前页面截一张 PNG 回来,给界面当"实时二维码"显示。截图里可能有二维码,
    但二维码不是凭据:它只在浏览器和本机之间显示,我不落盘、不进台账。

    回三个值:(png, err, mode)。mode 是给前端打角标用的:
      'card' —— 截到登录卡片(二维码那一块,放大后就是一张能扫的码);
      'page' —— 页面上没找到二维码卡片,退成整页首屏(让人至少看得见页面在干什么);
      ''     —— 没截到。

    11-08 用户:「没显示出二维码 那就显示页面 然后想办法稍微聚焦一点也行」——
    以前找不到卡片就直接回一句提示、什么都不给看,现在改成退回首屏截图。"""
    if driver not in DISKS:
        return None, "不认识的盘 %s" % driver, ""
    port = port_of(driver, slot)
    if not port_alive(port):
        return None, "窗口没开着", ""
    if _page_hijacked(driver, _tab_url(port)):
        return None, "这一格的窗口被别的程序占用了(页面不在登录页)——点『扫码登录』另开一格干净的", ""
    params = {"format": "png"}
    mode = ""
    used_clip = None
    if focus:
        # 先保证窗口不是那种 400x420 的畸形尺寸,否则登录入口会被挤出视野、量不到卡片
        _ensure_viewport(port)
        clip = card_clip(port)
        if clip:
            params["clip"] = clip
            used_clip = clip
            mode = "card"
        else:
            pclip = _page_clip(port)
            if pclip:
                params["clip"] = pclip
                used_clip = pclip
            mode = "page"
    try:
        res = _cdp(port, "Page.captureScreenshot", params)
        import base64
        # 记下这张图用的裁剪框：前端把「点在图上哪」换算回网页坐标时要靠它（点击回传）
        _LAST_SHOT[(driver, _slot(slot))] = {"mode": mode, "clip": used_clip}
        return base64.b64decode(res.get("data") or ""), "", mode
    except Exception as e:
        if "Timeout" in type(e).__name__ or isinstance(e, TimeoutError):
            return None, ("画面暂时取不到（页面还在加载？）—— 过两秒会自动重试。"), ""
        return None, "%s: %s" % (type(e).__name__, str(e)[:160]), ""


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
    给界面出「登录位」下拉用;十格全出,空的也列出来,用户才知道还能往下登几个。

    11-08:探测改成并发。以前十格是挨个 connect,每格等满 0.4 秒超时 → 这一个函数就要
    3.6 秒,而每打开一次网盘页要问两遍(整页一次 + 字段接口一次),页面白等 7 秒,
    看着就像"卡死了/服务是不是没开"。十格一起问,总耗时≈一格。"""
    if driver not in DISKS:
        return []
    nums = list(range(1, MAX_SLOTS + 1))
    ports = [port_of(driver, n) for n in nums]

    def _probe(p):
        live = port_alive(p, 0.4)
        return live, (_tab_url(p) if live else "")

    try:
        with ThreadPoolExecutor(max_workers=len(nums)) as ex:
            probed = list(ex.map(_probe, ports))
    except Exception:                    # 线程开不出来就退回串行,功能不受影响
        probed = [_probe(p) for p in ports]
    out = []
    for n, port, (live, url) in zip(nums, ports, probed):
        prof = profile_of(driver, n)
        st = _read_state(driver, n) or {}
        hijacked = _page_hijacked(driver, url)   # 端口通但页面被别的程序导航走 = 被占用,不算登录窗口
        out.append({"slot": n, "port": port,
                    "profile": os.path.basename(prof),
                    "profile_exists": os.path.isdir(prof),
                    "listening": live,
                    "page_ok": not hijacked,
                    "foreign_url": (url if hijacked else "")[:120],
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
    url = page_url(driver, n) if up else ""
    hijacked = up and _page_hijacked(driver, url)
    mine, why = (None, "窗口没开着")
    if up and not hijacked:
        mine, why = cookie_names(driver, n)
    elif hijacked:
        why = ("第 %d 槽的窗口被别的程序占用了(页面被导航到 %s)——点『扫码登录』会另开一格干净的"
               % (n, (url or "别处")[:80]))
    names = sorted({c["name"] for c in mine}) if mine else []
    have = [m for m in d["markers"] if m in names]
    return {"ok": True, "driver": driver, "label": d["label"], "kind": d["kind"],
            "slot": n, "max_slot": MAX_SLOTS, "listening": up, "port": port,
            "page_ok": not hijacked, "foreign_url": (url if hijacked else "")[:120],
            "url": url,
            "profile": os.path.basename(profile_of(driver, n)),
            "profile_exists": os.path.isdir(profile_of(driver, n)),
            "exe": os.path.basename(st.get("exe") or ""),
            "headless": not QR_HEADED,
            "login_url": d["url"], "howto": d["howto"], "field": d["field"],
            "cookie_count": len(mine or []), "names": names[:40],
            "markers": list(d["markers"]), "markers_have": have,
            "msg": why or "", "started_at": st.get("started_at", "")}


# ---------------------------------------------------------------- 通用浏览器交互(内嵌视图)
#
# 下面是「内嵌浏览器视图」这一层的能力,和上面的「扫码登录」是两回事:
#   扫码那条只关心"把二维码截给用户、扫上就抓 cookie 关窗口";
#   这一层把某个登录位(profile)里开着的浏览器当成一个**活的网页**,给前端当"内嵌浏览器"用——
#   能导航、能点、能滚、能截整页,前端把鼠标坐标回传过来,这里用 CDP 的真鼠标事件落到网页上。
# 安全边界和上面一致:只连 127.0.0.1 的调试端口,只碰我们自己那个独立 profile,值不落盘、不写日志。


def view_metrics(driver, slot=1):
    """当前页面的视口尺寸(设备像素)+ 整页可滚动高度。前端据此把截图按比例映射回真实坐标。"""
    if driver not in DISKS:
        return None, "不认识的盘 %s" % driver
    port = port_of(driver, _slot(slot))
    if not port_alive(port):
        return None, "窗口没开着"
    try:
        r = _cdp(port, "Runtime.evaluate", {
            "expression": "JSON.stringify({w: window.innerWidth, h: window.innerHeight,"
                          " dpr: window.devicePixelRatio||1,"
                          " sw: document.documentElement.scrollWidth,"
                          " sh: document.documentElement.scrollHeight})",
            "returnByValue": True})
        v = json.loads(((r or {}).get("result") or {}).get("value") or "{}")
        return {"viewport_w": int(v.get("w") or 0), "viewport_h": int(v.get("h") or 0),
                "dpr": float(v.get("dpr") or 1), "scroll_w": int(v.get("sw") or 0),
                "scroll_h": int(v.get("sh") or 0)}, ""
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, str(e)[:160])


def view_navigate(driver, slot=1, url=""):
    """让这一格的浏览器跳到某个网址(默认跳回该盘首页)。"""
    if driver not in DISKS:
        return {"ok": False, "msg": "不认识的盘 %s" % driver}
    port = port_of(driver, _slot(slot))
    if not port_alive(port):
        return {"ok": False, "msg": "窗口没开着(先点『打开扫码窗口』)"}
    d = DISKS[driver]
    target = (url or d["url"]).strip()
    if not target.startswith(("http://", "https://")):
        return {"ok": False, "msg": "只接 http/https 地址"}
    try:
        _cdp(port, "Page.navigate", {"url": target})
        return {"ok": True, "msg": "已导航到 %s" % target[:80], "url": target}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, str(e)[:160])}


def view_click(driver, slot=1, x=0, y=0, ensure_view=False):
    """把前端在截图上的点击(页面坐标)回传到真浏览器:一次完整的鼠标按下+抬起。

    ensure_view:扫码卡片那条路要置 True。卡片截图(shot_ex)是先 _ensure_viewport 拉到
    1180x780 再量的裁剪框,可那个 Emulation 尺寸过一会儿会退回窗口自然尺寸(实测 769x916);
    点击若不在同一视口里投,换算回来的坐标就落到卡片外。这里点之前再拉一次,保证和截图同几何。
    内嵌浏览器视图(view_shot 整页)用的是自然视口、前后一致,别置 True,否则反而把它的布局改歪。"""
    if driver not in DISKS:
        return {"ok": False, "msg": "不认识的盘 %s" % driver}
    port = port_of(driver, _slot(slot))
    if not port_alive(port):
        return {"ok": False, "msg": "窗口没开着"}
    try:
        if ensure_view:
            _ensure_viewport(port)
        for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
            _cdp(port, "Input.dispatchMouseEvent",
                 {"type": typ, "x": float(x), "y": float(y),
                  "button": "left", "clickCount": 1})
        return {"ok": True, "msg": "已点击 (%s, %s)" % (round(float(x), 1), round(float(y), 1))}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, str(e)[:160])}


def view_scroll(driver, slot=1, dx=0, dy=0, x=-1, y=-1):
    """滚轮。dy>0 往下滚。x/y 是光标在网页里的 CSS 坐标(前端从截图上换算回来的)。

    11-08 修:以前固定投到 (0,0) —— 那是页面左上角,很多站那块是个不吃滚轮的横幅,
    滚轮投下去整页纹丝不动,用户只能说「非常难滑」。现在按光标位置投,滚在哪个列表上就滚哪个。
    返回里带 moved:滚完页面一像素都没动(到顶/到底/这块不滚),前端据此让看板自己接着滚。
    """
    if driver not in DISKS:
        return {"ok": False, "msg": "不认识的盘 %s" % driver}
    port = port_of(driver, _slot(slot))
    if not port_alive(port):
        return {"ok": False, "msg": "窗口没开着"}
    try:
        tgt, why = page_target(port)
        ws = (tgt or {}).get("webSocketDebuggerUrl")
        if not ws:
            return {"ok": False, "msg": why or "没找到页面 target"}
        c = Cdp(ws)
        try:
            vp = c.call("Runtime.evaluate", {
                "expression": "JSON.stringify({w: window.innerWidth, h: window.innerHeight,"
                              " sx: window.scrollX, sy: window.scrollY})",
                "returnByValue": True})
            v = json.loads(((vp or {}).get("result") or {}).get("value") or "{}")
            px = float(x) if x is not None and float(x) >= 0 else (v.get("w") or 800) / 2.0
            py = float(y) if y is not None and float(y) >= 0 else (v.get("h") or 600) / 2.0
            px = max(1.0, min(px, (v.get("w") or 800) - 2))
            py = max(1.0, min(py, (v.get("h") or 600) - 2))
            c.call("Input.dispatchMouseEvent",
                   {"type": "mouseWheel", "x": px, "y": py,
                    "deltaX": float(dx or 0), "deltaY": float(dy or 0)})
            time.sleep(0.03)
            ap = c.call("Runtime.evaluate", {
                "expression": "[window.scrollX, window.scrollY]", "returnByValue": True})
            after = ((ap or {}).get("result") or {}).get("value") or [0, 0]
            moved = (after[0] != v.get("sx")) or (after[1] != v.get("sy"))
        finally:
            c.close()
        return {"ok": True, "msg": "已滚动 (%s, %s)" % (dx, dy), "moved": bool(moved)}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, str(e)[:160])}


# CDP 上要发「真按键」而不是塞文字的那几个键:虚拟键码 + 键名(Enter 还要带 \r 才算按下)
ND_KEYS = {
    "Enter": (13, "Enter", "\r"), "Backspace": (8, "Backspace", None),
    "Tab": (9, "Tab", "\t"), "Escape": (27, "Escape", None), "Delete": (46, "Delete", None),
    "ArrowUp": (38, "ArrowUp", None), "ArrowDown": (40, "ArrowDown", None),
    "ArrowLeft": (37, "ArrowLeft", None), "ArrowRight": (39, "ArrowRight", None),
    "Home": (36, "Home", None), "End": (35, "End", None),
    "PageUp": (33, "PageUp", None), "PageDown": (34, "PageDown", None),
}

# 每个假名/汉字都靠 insertText,不经剪贴板、不碰用户剪贴板,也不落任何日志(值就是网页要的输入)
def view_text(driver, slot=1, text=""):
    """把一段文字送进当前聚焦的元素 —— 相当于人在那个输入框里打字。
    中文/emoji 走 Input.insertText(输入法组完字之后的效果),不走按键序列。"""
    if driver not in DISKS:
        return {"ok": False, "msg": "不认识的盘 %s" % driver}
    port = port_of(driver, _slot(slot))
    if not port_alive(port):
        return {"ok": False, "msg": "窗口没开着"}
    text = str(text or "")
    if not text:
        return {"ok": False, "msg": "没有要输入的字"}
    try:
        _cdp(port, "Input.insertText", {"text": text})
        return {"ok": True, "msg": "已输入 %d 个字" % len(text)}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, str(e)[:160])}


def view_key(driver, slot=1, key=""):
    """发一个真按键(回车/退格/方向键/删除…)。"""
    if driver not in DISKS:
        return {"ok": False, "msg": "不认识的盘 %s" % driver}
    port = port_of(driver, _slot(slot))
    if not port_alive(port):
        return {"ok": False, "msg": "窗口没开着"}
    spec = ND_KEYS.get(str(key or ""))
    if not spec:
        return {"ok": False, "msg": "不认识的键 %s" % key}
    vk, name, text = spec
    try:
        base = {"windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk, "key": name, "code": name}
        if text:
            base["text"] = text
        _cdp(port, "Input.dispatchKeyEvent", dict(base, type="keyDown"))
        _cdp(port, "Input.dispatchKeyEvent", dict(base, type="keyUp", text=""))
        return {"ok": True, "msg": "已按键 %s" % name}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, str(e)[:160])}


def view_shot(driver, slot=1, focus=False):
    """截当前页面。focus=False 截整个视口(内嵌浏览器视图用),focus=True 沿用扫码那张卡片放大。
    始终按 devicePixelRatio 放大,保证前端缩小后仍清晰。"""
    if driver not in DISKS:
        return None, "不认识的盘 %s" % driver
    port = port_of(driver, _slot(slot))
    if not port_alive(port):
        return None, "窗口没开着"
    params = {"format": "png"}
    if focus:
        clip = card_clip(port)
        if clip:
            params["clip"] = clip
    try:
        res = _cdp(port, "Page.captureScreenshot", params)
        import base64
        return base64.b64decode(res.get("data") or ""), ""
    except Exception as e:
        if "Timeout" in type(e).__name__ or isinstance(e, TimeoutError):
            return None, "画面暂时取不到(页面还在加载?)—— 过两秒自动重试。"
        return None, "%s: %s" % (type(e).__name__, str(e)[:160])


def view_url(driver, slot=1):
    return page_url(driver, _slot(slot))


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
