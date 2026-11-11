# -*- coding: utf-8 -*-
r"""网盘账号库：多网盘多账号的凭据保管 + 有效性探测 + 切活跃号——**逻辑层，自己不起界面**。

11-05 之前这个文件还自带一个 127.0.0.1:5320 的网页（另一张表、另一个端口、另一份渲染）。
现在界面并进了 `08-数据看板\看板.py` 的「网盘」页签：看板调本文件的 `form_schema()` 出字段表、
调 `do_action()` 干活、调 `list_safe()` 出账号明细。留两个端口就是让同一件事有两个入口、
两套渲染、两份会漂的判据，所以拆掉了。命令行子命令（list/add/check/use/orphans/selftest）照旧。

凭据值用 Windows DPAPI 加密后写进 F:\OpenList\账号库.json——密文只在这台机器的
当前 Windows 用户下能解开，复制到别的机器或换用户都读不出来，值本身不进知识库、不进网盘、
不从本文件的任何返回值里出去（`do_action` 只回密文长度和人话结论）。
"""
import argparse
import base64
import ctypes
import ctypes.wintypes as w
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net_proxy                                                               # noqa: E402  外网请求的代理口现探
import netdisk_upload as nd                                    # noqa: E402  复用登录与挂载点接口

try:
    import 网盘扫码登录 as qr                                                   # noqa: E402  扫码窗口 + CDP 抓 cookie
    QR_ERR = ""
except Exception as _e:                                        # 缺 websocket-client 之类：界面要说清哪条走不了
    qr = None
    QR_ERR = "%s: %s" % (type(_e).__name__, str(_e)[:160])

DB_PATH = os.environ.get("NETDISK_DB", os.path.join(nd.OL_DIR, "账号库.json"))

# 三个盘的中文名，界面和挂载点命名都用它
DISKS = {"Quark": "夸克", "BaiduNetdisk": "百度", "Thunder": "迅雷"}
SECRET_RE = re.compile(r"(cookie|token|password|secret|key)", re.I)
ALIAS_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,23}$")

# ---------------------------------------------------------------- DPAPI

_k32 = ctypes.windll.crypt32


class _Blob(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("pb", ctypes.c_void_p)]


def _as_blob(raw):
    buf = ctypes.create_string_buffer(raw, len(raw))
    b = _Blob()
    b.cb = len(raw)
    b.pb = ctypes.cast(buf, ctypes.c_void_p)
    return b, buf


def dpapi_protect(text):
    """明文字符串 -> DPAPI 密文（base64）。绑定当前 Windows 用户。"""
    raw = text.encode("utf-8")
    if not raw:
        raise SystemExit("空字符串不加密，免得把空凭据当有效值存下来")
    inp, _keep = _as_blob(raw)
    out = _Blob()
    if not _k32.CryptProtectData(ctypes.byref(inp), "netdisk-accounts",
                                 None, None, None, 0, ctypes.byref(out)):
        raise OSError("CryptProtectData 调用失败（错误码 %s）" % ctypes.GetLastError())
    return base64.b64encode(ctypes.string_at(out.pb, out.cb)).decode()


def dpapi_unprotect(b64):
    if not b64:
        return ""
    raw = base64.b64decode(b64)
    inp, _keep = _as_blob(raw)
    out = _Blob()
    if not _k32.CryptUnprotectData(ctypes.byref(inp), None, None, None, None, 0,
                                   ctypes.byref(out)):
        raise RuntimeError("DPAPI 解不开：这份账号库不是本机当前用户产出的，或被改坏了")
    return ctypes.string_at(out.pb, out.cb).decode("utf-8")


# ---------------------------------------------------------------- 账号库

def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_db():
    if not os.path.exists(DB_PATH):
        return {"accounts": []}
    with open(DB_PATH, encoding="utf-8") as fh:
        d = json.load(fh)
    d.setdefault("accounts", [])
    return d


def save_db(db):
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(db, fh, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, DB_PATH)


def get_acct(db, alias):
    for a in db["accounts"]:
        if a["alias"] == alias:
            return a
    return None


_AUTH = None


def _auth():
    """整个进程共用一份 OpenList 登录态。

    11-08：原来每次 do_action 都 new 一个 Auth()，而扫码页每 2 秒 poll 一次 ——
    等于每 2 秒拿管理员密码登一次 OpenList（日志刷屏、界面「等好久」）。
    token 本身在 Auth 里缓存 40 小时，把它挂到进程级就够了。"""
    global _AUTH
    if _AUTH is None:
        _AUTH = nd.Auth()
    return _AUTH


def fields_of(driver):
    """从跑着的 OpenList 现取该驱动的字段表，不写死字段名。"""
    a = _auth()
    dl = a.get("/api/admin/driver/list").get("data") or {}
    if driver not in dl:
        raise SystemExit("OpenList 里没有驱动 %s，可选：%s"
                         % (driver, ", ".join(sorted(DISKS))))
    return dl[driver].get("additional") or [], bool((dl[driver].get("config") or {}).get("no_upload"))


def secret_of(acct):
    return json.loads(dpapi_unprotect(acct.get("secret", "")))


def store_secret(acct, values):
    acct["secret"] = dpapi_protect(json.dumps(values, ensure_ascii=False))
    # 只记长度，不记任何摘要/哈希：免得留一份能离线猜 cookie 的材料
    acct["secret_len"] = {k: len(v or "") for k, v in values.items()}


# ---------------------------------------------------------------- 与 OpenList 对接

def build_addition(acct):
    add = dict(acct.get("plain") or {})
    add.update(secret_of(acct))
    drv = acct.get("driver", "")
    return {k: coerce(drv, k, v) for k, v in add.items()}


_types_cache = {}


def field_types(driver):
    """每个字段在 OpenList 里是什么类型（bool/number/string/select...），按盘缓存一次。
    取不到就回空表，那时所有值原样当字符串发——和以前一样，不会更糟。"""
    if driver not in _types_cache:
        try:
            known, _ = fields_of(driver)
        except BaseException:
            return {}
        _types_cache[driver] = {f["name"]: (f.get("type") or "") for f in known if f.get("name")}
    return _types_cache[driver]


def coerce(driver, name, val):
    """OpenList 的 addition 是 JSON：bool 字段必须给**真布尔**。
    11-05 第一次真挂载就是栽在这：表单里存的是字符串 "false"，夸克驱动 init 直接
    `ReadBool: expect t or f` 报错、挂载点变成 guest 态。number 同理。"""
    t = field_types(driver).get(name, "")
    if t == "bool":
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes", "y", "on", "t")
    if t == "number":
        try:
            f = float(val)
            return int(f) if f.is_integer() else f
        except (TypeError, ValueError):
            return val
    return val


def find_storage(auth, mount_path):
    r = auth.get("/api/admin/storage/list?page=1&per_page=200")
    for s in ((r.get("data") or {}).get("content") or []):
        if s.get("mount_path") == mount_path:
            return s
    return None


_STORAGE_MANAGED = {"id", "modified", "status", "mount_path", "order", "remark",
                    "enabled", "disabled", "driver", "cache_expiration", "addition"}


def _carry_storage_opts(ex, body):
    """纯函数：OpenList update 是整行覆盖，旧行里账号库不管的存储级设置（web_proxy/
    down_proxy_url 等）必须带回来，否则一次 activate/重扫就冲成零值，夸克直链本机下载必 412。
    11-10 实测踩过：重扫后 web_proxy 被冲 False，下载 412。自检钉死。"""
    out = {k: v for k, v in (ex or {}).items() if k not in _STORAGE_MANAGED}
    out.update(body)
    return out


def register(auth, acct, remark=None):
    """把这条账号写成 OpenList 挂载点：没有就 create，有就 update。
    OpenList 对『凭据不对』的处理是照样建行、把它标成 work=failed 并回一条错误，
    所以这里不看 code 当结论，一律回查挂载点在不在，再决定怎么报。"""
    add = build_addition(acct)
    ex = find_storage(auth, acct["mount_path"])
    body = _carry_storage_opts(ex, {
        "mount_path": acct["mount_path"], "order": acct.get("order", 0),
        "remark": remark if remark is not None else (acct.get("remark") or acct["alias"]),
        "enabled": bool(acct.get("active", True)), "driver": acct["driver"],
        "cache_expiration": 30, "addition": json.dumps(add, ensure_ascii=False)})
    if ex:
        body["id"] = ex["id"]
        r = auth.api("/api/admin/storage/update", body)
    else:
        r = auth.api("/api/admin/storage/create", body)
    now_exists = find_storage(auth, acct["mount_path"])
    if now_exists:
        body["id"] = now_exists["id"]
        if not ex:  # create 被 OpenList 当成初始化失败，但行已经落库且 enabled 可能没生效，补一次 update
            auth.api("/api/admin/storage/update", body)
    return r, bool(now_exists)


def drop_storage(auth, mount_path):
    """删挂载点。v4.2.9 的 DeleteStorage 取的是 **query 参数 id**（源码
    server/handles/storage.go:124 `idStr := c.Query("id")`），放 body 里会得到
    `strconv.Atoi: parsing "": invalid syntax`——踩过，别再发成 JSON 体。"""
    ex = find_storage(auth, mount_path)
    if not ex:
        return True, "本来就没有这个挂载点"
    r = auth.api("/api/admin/storage/delete?id=%s" % ex["id"], {})
    gone = find_storage(auth, mount_path) is None
    return gone, str(r.get("message") or "")[:120] or ("删掉了" if gone else "没删掉")


def probe(auth, acct):
    """真去列一次挂载点根目录：能列出东西（或空目录但 200）才算凭据有效。"""
    r = auth.api("/api/fs/list", {"path": acct["mount_path"], "page": 1,
                                  "per_page": 5, "refresh": True})
    code = r.get("code")
    msg = str(r.get("message") or "")[:180]
    if code == 200:
        content = ((r.get("data") or {}).get("content") or [])
        return True, "列到 %d 项" % len(content), len(content)
    return False, msg, -1


# ---------------------------------------------------------------- 账号操作（CLI 与界面共用）

def add_account(driver, alias, values, plain=None, remark=""):
    db = load_db()
    if not ALIAS_RE.match(alias or ""):
        raise SystemExit("账号别名只能用小写字母/数字/-/_，2~24 位，例如 quark-03")
    if get_acct(db, alias):
        raise SystemExit("已经有叫 %s 的账号了，要覆盖就先用界面里的『改凭据』" % alias)
    known, _ = fields_of(driver)
    names = [f["name"] for f in known if f.get("name")]
    miss = [n for n in names if n not in (values or {}) and n not in (plain or {})]
    secret = {k: v for k, v in (values or {}).items() if SECRET_RE.search(k)}
    rest = {k: v for k, v in (values or {}).items() if not SECRET_RE.search(k)}
    rest.update(plain or {})
    acct = {"alias": alias, "driver": driver, "mount_path": "/" + alias,
            "created": now(), "active": True, "order": len(db["accounts"]),
            "remark": remark or ("%s-%s" % (DISKS.get(driver, driver), alias)),
            "fields": names, "missing_required": miss,
            "plain": rest, "secret": ""}
    store_secret(acct, secret)
    db["accounts"].append(acct)
    save_db(db)
    return acct


def activate(db, auth, acct):
    """建/改挂载点并探一次，结果写回账号库。返回 (有效吗, 给人看的那句话)。"""
    r, exists = register(auth, acct)
    acct["mount_msg"] = str(r.get("message") or "")[:160]
    if not exists:
        acct["last_check"], acct["last_ok"], acct["last_msg"] = now(), False, acct["mount_msg"]
        save_db(db)
        return False, "挂载点没落库：" + (acct["mount_msg"] or "OpenList 没回错误信息")
    good, msg, n = probe(auth, acct)
    if not good and acct["mount_msg"] and msg != acct["mount_msg"]:
        msg = "%s（OpenList：%s）" % (msg, acct["mount_msg"])
    acct["last_check"], acct["last_ok"], acct["last_msg"], acct["items"] = now(), good, msg, n
    save_db(db)
    return good, msg


def use_only(db, auth, target):
    """同盘只留一个活跃账号：切过去，其余停用（走同一个 register()，不再手搓请求体）。"""
    out = []
    for a in db["accounts"]:
        if a["driver"] != target["driver"]:
            continue
        a["active"] = (a["alias"] == target["alias"])
        register(auth, a)
        out.append(a["alias"])
    save_db(db)
    return out


# ---------------------------------------------------------------- 看板用的对外接口
#
# 这一段是 08-数据看板\看板.py 的「网盘」页签唯一进来的门。三条硬规矩：
#   1) **返回值里永远没有凭据值**——只回整条密文的长度（cipher_len）和人话结论；
#   2) **不往外抛 SystemExit**——下面 add_account/probe/fields_of 那套是为命令行写的，
#      错就 SystemExit；界面调用必须把它接住变成 {ok:false,msg}，否则看板的工作线程直接死、
#      浏览器那头就是一直转圈、什么错都看不到；
#   3) **不猜字段名**——表单要出哪些格子一律从跑着的 OpenList 现取（fields_of）。

SAFE_KEYS = ("alias", "driver", "mount_path", "created", "active", "remark",
             "last_check", "last_ok", "last_msg", "items", "mount_msg",
             "uid", "nickname", "member", "ident_msg", "ident_at", "slot",
             "state", "fail_n", "needs_relogin", "last_ok_at", "checked_ts",
             "cookie_refresh")


def safe_rec(a):
    """把一条账号投影成「能上界面」的样子：白名单字段 + 密文长度，值一个都不给。"""
    rec = {k: a.get(k) for k in SAFE_KEYS if k in a}
    if isinstance(a.get("fields"), list):
        rec["fields"] = len(a["fields"])              # 字段名本身都可能沾凭据线索，只报个数
    if isinstance(a.get("missing_required"), list):
        rec["missing_required"] = len(a["missing_required"])
    rec["cipher_len"] = len(a.get("secret") or "")    # DPAPI 密文长度：证明「存了但没给你看」
    try:
        rec["slot"] = int(rec.get("slot") or 1)       # 老记录没这栏＝第 1 槽（profile-<盘> 本来就是第 1 槽）
    except (TypeError, ValueError):
        rec["slot"] = 1
    # 库里那份 secret_len（每个密文格的长度）不上界面：格名本身就是凭据线索，
    # 和上面「fields 只报个数」是同一条规矩——要证明存了，cipher_len 够了。
    rec["driver_label"] = DISKS.get(a.get("driver", ""), a.get("driver", ""))
    rec["last_msg"] = (rec.get("last_msg") or "")[:200]
    rec["mount_msg"] = (rec.get("mount_msg") or "")[:200]
    for k in ("nickname", "member", "ident_msg", "uid"):      # 界面要显示，但别让长串撑爆表格
        rec[k] = (str(rec.get(k, "")) or "")[:60]
    return rec


def list_safe():
    return [safe_rec(a) for a in load_db()["accounts"]]


def form_schema(driver):
    """表单该出哪些格子。名字/必填/类型/默认值全是 OpenList 说了算，我这边不写死。"""
    if driver not in DISKS:
        return {"ok": False, "msg": "不认识的盘 %s（可选：%s）" % (driver, "、".join(DISKS))}
    try:
        known, ro = fields_of(driver)
    except SystemExit as e:
        return {"ok": False, "msg": str(e)[:300]}
    except Exception as e:
        return {"ok": False, "msg": "问 OpenList 要字段表失败：%s: %s" % (type(e).__name__, str(e)[:200])}
    fields = []
    for f in known:
        n = f.get("name")
        if not n:
            continue
        fields.append({"name": n, "required": bool(f.get("required")),
                       "type": f.get("type", ""), "default": str(f.get("default", ""))[:60],
                       "secret": bool(SECRET_RE.search(n))})
    return {"ok": True, "driver": driver, "label": DISKS[driver],
            "no_upload": ro, "fields": fields,
            "login_kind": (qr.DISKS.get(driver) or {}).get("kind", ""),
            "login_howto": (qr.DISKS.get(driver) or {}).get("howto", "") if qr else
                           "扫码模块没装好（%s），只能手填凭据" % QR_ERR,
            "qr_ready": bool(qr), "qr_max_slot": (qr.MAX_SLOTS if qr else 0),
            "qr_slots": qr_slots(driver), "qr_browsers": qr_browsers()}


def qr_slots(driver):
    """这个盘有哪几格登录位（一个 profile 一个号）。看板出下拉、界面显示「谁占着第几槽」都读这里。"""
    if not qr or driver not in DISKS:
        return []
    return qr.slots(driver)


def qr_browsers():
    """能拿来开扫码窗口的浏览器，和装了但走不通的那些（附原因）。"""
    if not qr:
        return {"ok": [], "unusable": []}
    return {"ok": qr.browsers(), "unusable": qr.unusable()}


def screenshot(driver, slot=1):
    """看板 GET /api/netdisk/shot 用：把某个登录位的扫码窗口画面截成 PNG 回给界面。
    画面里可能有二维码——二维码不是凭据（它是登录页公开广播的一次性串），
    但只经回环端口显示一次，不落盘、不进台账、不进日志。"""
    if driver not in DISKS:
        return None, "不认识的盘 %s" % driver
    if not qr:
        return None, "扫码模块没装好（%s）" % QR_ERR
    return qr.shot(driver, qr._slot(slot))


def screenshot_ex(driver, slot=1):
    """同 screenshot，但多回一个 mode：'card'(截到二维码卡片) / 'page'(没找到卡片，
    退成首屏整页) / ''。看板拿它给前端打一个「这是整页画面」的小角标。"""
    if driver not in DISKS:
        return None, "不认识的盘 %s" % driver, ""
    if not qr:
        return None, "扫码模块没装好（%s）" % QR_ERR, ""
    fn = getattr(qr, "shot_ex", None)
    if fn:
        return fn(driver, qr._slot(slot))
    # 老版本扫码模块没有 shot_ex：退回两元组，有图就当卡片
    png, err = qr.shot(driver, qr._slot(slot))
    return png, err, ("card" if png else "")


def screenshot_meta(driver, slot=1):
    """这一格最近那张扫码画面的裁剪框（{mode, clip}）。看板拿 clip 经 X-Shot-Clip 头给前端，
    前端据此把「点在二维码图上哪」换算回网页坐标，点击才能真落到刷新按钮/页签上。"""
    if not qr or driver not in DISKS:
        return {}
    fn = getattr(qr, "last_shot", None)
    return fn(driver, qr._slot(slot)) if fn else {}


# ---------------------------------------------------------------- 「到底登录上没、这是谁」
#
# cookie 里名字齐 **不等于** 登录，这条踩过两回：
#   1) 独立 profile 头一回打开夸克就带着 __pus/__puus/__uid（游客态也发），光看名字分不出真假；
#   2) 11-05 18:15 拿 drive.quark.cn/1/clouddrive/member 裸问，回 401 code=31001
#      "require login [guest]"，当时据此写成"这接口要夸克客户端签名、不能当判据"——
#      11-06 复核：那句是**误判**，401 是少了 pr 参数，不是没登录。带 ?pr=ucpro&fr=pc 只凭 cookie
#      就回 code=0 + total_capacity/use_capacity（同一串 cookie 逐档试过：裸的 401 / 只 fr 401 /
#      pr+fr 200 / pr+fr+vip_acc+utdid 200 / pan 域 pr+fr 200）。
#      但判"登录上没"仍然用 account/info 的 nickname：它是三档参照实测过的稳判据；
#      member 这个接口只拿来读会员档和容量，而且游客态会不会也回 200 没验过，不当登录依据。
# 现在用 pan.quark.cn/account/info，三档参照实测过：没 cookie→code=OK 但 data 是空的；
# 假 cookie→code=UNKNOWN_EXCEPTION；真 cookie→code=OK + data.nickname（还带头像）。
# 只有 nickname 非空才算登录上。ID 用 cookie 里的 __uid（账号 id 的编码串，跟着账号走）；
# b-user-id 是这台浏览器的设备 id（36 位 UUID），换 profile 就变，不能当账号 ID。
# 这一段的凭据值只在内存里过一遍：不进返回值、不进日志、不进台账。

NET_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
QUARK_INFO = "https://pan.quark.cn/account/info"
# 会员/容量接口。pr=ucpro 不能省：11-06 实测带 pr+fr 只凭 cookie 就回 code=0 + total_capacity，
# 少了 pr 才回 31001 require login [guest]——之前记成"这接口要客户端签名"是把缺参数当成没登录。
QUARK_MEMBER = "https://drive.quark.cn/1/clouddrive/member?pr=ucpro&fr=pc"
_ALIAS_PREFIX = {"Quark": "quark", "BaiduNetdisk": "baidu", "Thunder": "xunlei"}


def _json_of(raw):
    try:
        j = json.loads((raw or b"").decode("utf-8", "replace"))
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def _ext_get(url, headers=None, timeout=12):
    """问网盘自己的接口。代理口现探（net_proxy），没活着就直连。
    HTTP 错误码原样回——夸克判游客用的就是 401，吞掉错误码就没法分辨游客和会员。"""
    req = urllib.request.Request(url, headers=dict(NET_HEADERS, **(headers or {})))
    u = net_proxy.proxy_url() if net_proxy.alive() else ""
    handlers = [urllib.request.ProxyHandler({"http": u, "https": u})] if u else []
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.getcode(), _json_of(r.read())
    except urllib.error.HTTPError as e:
        return e.code, _json_of(e.read())
    except Exception as e:
        return 0, {"_err": "%s: %s" % (type(e).__name__, str(e)[:180])}


def cookie_kv(text):
    """'k=v; k=v' -> dict。只用来挑 uid 这类身份名，值不往外传。"""
    out = {}
    for part in re.split(r"[;,\s]+", text or ""):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip():
                out[k.strip()] = v.strip()
    return out


def capacity_text(total, used):
    """把夸克给的两个字节数挤成一句人话。
    数读不出来回空串——别说成「剩 0」，更不许由此得出「满了」；
    数读出来了但剩的不大于 0 才说满（NORMAL 号上 use_capacity 是坏的，这句正好和探针一致）。"""
    try:
        t = int(total)
        u = int(used or 0)
    except (TypeError, ValueError):
        return ""
    if t <= 0:
        return ""
    gb = 1024 ** 3
    free = t - u
    if free <= 0:
        return "共 %.2f GB / 已用 %.2f GB——满了，夸克会退回 capacity limit" % (t / gb, u / gb)
    return "共 %.2f GB / 剩 %.2f GB" % (t / gb, free / gb)


def member_of(fields):
    """问夸克要「会员档 + 容量」,回给人看的一小串(问不着回空串)。凭据值只在内存里过一遍。
    故意不把「还剩多少字节」算成一个数回给调用方:夸克在 NORMAL 号上报的 use_capacity 是坏的
    (11-06 实测 10.10 GB 的额度说成已用 33501.92 GB),给个数就有人会拿它当闸门 —— 拦路用的是
    上传器那边那 1 字节探针,这里只负责把话说明白。
    也只用来读容量,不用来判登录:游客态会不会也回 200 没验过,判登录仍然看 account/info 的 nickname。"""
    ck = ((fields or {}).get("cookie") or "").strip()
    if not ck:
        return ""
    st, j = _ext_get(QUARK_MEMBER, {"Cookie": ck, "Referer": "https://pan.quark.cn/"})
    d = j.get("data") if isinstance(j.get("data"), dict) else {}
    if not d:
        return ""
    return " ".join(x for x in (str(d.get("member_type") or ""),
                                capacity_text(d.get("total_capacity"), d.get("use_capacity"))) if x)[:72]


def capacity_for(target):
    """按挂载点名或别名问一句这个号现在是什么档、夸克报的额度是多少(挂载点名就是别名)。
    号不认识、驱动不是夸克、没问出来,都回空串——让上传那头自己决定放行还是提醒,这里不替它猜「满」。"""
    name = str(target or "").strip("/").split("/")[0]
    if not name:
        return ""
    acct = get_acct(load_db(), name)
    if not acct or acct.get("driver") != "Quark":
        return ""
    fields = dict(acct.get("plain") or {})
    fields.update(secret_of(acct) or {})
    return member_of(fields)


def identity_of(driver, fields):
    """拿凭据去网盘那边认一次人。ok=True 只在网盘亲口承认这是登录账号时才给。
    回 {ok, uid, nickname, member, src, msg}，一个凭据字段都不带。"""
    fields = fields or {}
    if driver == "Quark":
        ck = (fields.get("cookie") or "").strip()
        if not ck:
            return {"ok": False, "msg": "没给 cookie，问不了夸克你是谁"}
        st, j = _ext_get(QUARK_INFO, {"Cookie": ck, "Referer": "https://pan.quark.cn/"})
        if j.get("_err"):
            return {"ok": False, "msg": "问夸克 account/info 没通：%s" % j["_err"]}
        data = j.get("data") if isinstance(j.get("data"), dict) else {}
        nick = str(data.get("nickname") or data.get("nick_name") or "")
        if st != 200 or not nick:               # 游客/坏 cookie 都在这格露馅：nickname 拿不到
            return {"ok": False, "uid": "", "nickname": "", "member": "", "src": "",
                    "msg": "夸克没认这个会话是登录账号（HTTP %s，code=%s %s，nickname 是空的）"
                           "——扫码那步还没成" % (st, j.get("code"), str(j.get("message") or "")[:40])}
        uid = str(data.get("uid") or data.get("user_id") or cookie_kv(ck).get("__uid") or "")
        mem = member_of(fields)                    # 会员档 + 容量，只是附言，认人仍然靠上面的 nickname
        return {"ok": True, "uid": uid[:40], "nickname": nick[:40], "member": mem,
                "src": "夸克 account/info 给昵称 + cookie __uid 给账号 ID" +
                       ("；容量问的 member 接口" if mem else ""),
                "msg": "夸克认了这个账号：%s（ID %s）%s"
                       % (nick, (uid[:10] + "…") if len(uid) > 10 else uid or "没给",
                          ("——" + mem) if mem else "")}
    if driver == "Thunder":
        user = (fields.get("username") or "").strip()
        if not user:
            return {"ok": False, "msg": "迅雷要的是账号+密码，username 没填，没名字可记"}
        return {"ok": True, "uid": "", "nickname": user[:40], "member": "",
                "src": "你填的账号名（迅雷没有可匿名核对的接口，没做在线验身）", "msg": ""}
    if driver == "BaiduNetdisk":
        return {"ok": False, "msg": "百度走 OAuth refresh_token，昵称/ID 这条还没接"
                                   "（不影响保存：填了 token 照样能挂）"}
    return {"ok": False, "msg": "不认识的盘 %s" % driver}


def fill_identity(db, acct, fields):
    """把「这是谁」写到账号上：uid / 昵称 / 会员档。判不出登录也把原因留在 ident_msg 里，
    界面就能显示"存了但没验身"而不是假装没事。"""
    ident = identity_of(acct.get("driver", ""), fields)
    acct["uid"] = ident.get("uid", "")
    acct["nickname"] = ident.get("nickname", "")
    acct["member"] = ident.get("member", "")
    acct["ident_msg"] = ((("已核对：" + ident["src"]) if ident.get("ok") else "未核对：")
                         + (ident.get("msg") or ""))[:200]
    acct["ident_at"] = now()
    save_db(db)
    return ident


def auto_alias(driver, seed, db):
    """自动起名 quark-<uid 尾巴>。网盘没给 uid 就退化成 cookie 指纹的前 8 位，
    重扫同一个账号命中同一个名字（改凭据走 update，不会越扫越多）。"""
    tail = re.sub(r"[^a-z0-9]", "", str(seed or "").lower())[-8:]
    if len(tail) < 4:
        tail = hashlib.sha1(str(seed or "").encode("utf-8")).hexdigest()[:8]
    exist = {a.get("alias") for a in db["accounts"]}
    cand = "%s-%s" % (_ALIAS_PREFIX.get(driver, "acct"), tail)
    n = 2
    while cand in exist:
        cand = "%s-%s-%d" % (_ALIAS_PREFIX.get(driver, "acct"), tail, n)
        n += 1
    return cand[:24]


def _qr_state(driver, slot, extra=None):
    """把扫码模块的状态收成界面能看的样子：只回名字和个数，cookie 值不在里面。"""
    if not qr:
        return {"ok": False, "listening": False, "msg": "扫码模块没装好（%s）" % QR_ERR}
    st = qr.status(driver, slot)
    st.update(extra or {})
    return st


def _live_slots(driver, db):
    """还算「在用」的登录位。state=dead（体检发现登不上）的号不再占槽 —— 用户要的就是
    「哪个失效了就把槽释放出来，下次登录自动挑空闲的」。"""
    out = set()
    for a in db["accounts"]:
        if a.get("driver") != driver or a.get("state") == "dead":
            continue
        try:
            n = int(a.get("slot") or 0)
        except Exception:
            n = 0
        if n > 0:
            out.add(n)
    return out


def _next_slot(driver, db):
    """这个盘下一个没人占的登录位；一个空位都没有才回 0（调用方据此说「满了」）。"""
    if not qr:
        return 0
    used = _live_slots(driver, db)
    for n in range(1, qr.MAX_SLOTS + 1):
        if n not in used:
            return n
    return 0


def _slot_state(driver):
    """一次现探：{槽号: 行}。探不到(扫码模块没装/端口全不通)回 {}。"""
    if not qr:
        return {}
    try:
        return {int(r["slot"]): r for r in (qr.slots(driver) or [])}
    except Exception:
        return {}


def _clean_slot(driver, db):
    """「开新号」该落在哪一格。

    11-08 用户第四次困惑：「只登了 4 个号，却说十格满了」。老写法把两种东西都当成「占着」：
    ① 账号库里的号；② profile 目录还在（哪怕库里根本没这个号）。于是扫一次留一个空壳，
    几次下来十格全成空壳，界面就喊「满了」——其实一个号都没多。
    现在的判据只看**真占着**的两样：
      · 账号库里有号且没判死（state != dead）；
      · 这一格的窗口真开着、且页面还在网盘登录页（被别的程序导航走的不算，可以关掉重开）。
    profile 残留一律不算占位：挑中它就在开窗前清掉（start 段会做）。所以「4 个号 + 20 格」
    永远挑得到第 5、6…格。只有「号 + 活窗口」把 20 格填满了才回 0。
    """
    if not qr:
        return 0
    used = _live_slots(driver, db)
    rows = _slot_state(driver)
    span = range(1, qr.MAX_SLOTS + 1)

    def listening(n):
        return bool((rows.get(n) or {}).get("listening"))

    def live_page(n):                       # 窗口开着且还停在网盘登录页 = 正在用
        r = rows.get(n) or {}
        return r.get("listening") and r.get("page_ok", True)

    free = [n for n in span if n not in used and not listening(n)]
    clean = [n for n in free if not (rows.get(n) or {}).get("profile_exists")]
    if clean:
        return clean[0]                     # 首选：没号、没窗口、连 profile 都没有
    if free:
        return free[0]                      # 次选：有 profile 残留，开窗前一并清掉
    hijack = [n for n in span if n not in used and not live_page(n) and listening(n)]
    if hijack:
        return hijack[0]                    # 只剩被别的程序占着的窗口：关掉重开
    return 0


def _why_full(driver, db):
    """满了的时候把话说清楚：几个号、几个开着的窗口，免得再出「4 个号说十格满」这种鬼话。"""
    used = _live_slots(driver, db)
    rows = _slot_state(driver)
    live = [n for n in range(1, qr.MAX_SLOTS + 1)
            if (rows.get(n) or {}).get("listening") and (rows.get(n) or {}).get("page_ok", True)]
    return ("%d 个登录位全占着了：%d 个号（第 %s 槽）+ %d 个开着的窗口（第 %s 槽）。"
            "关掉多余的窗口，或删一个号／点『体检失效号』释放，再点扫码登录。"
            % (qr.MAX_SLOTS, len(used), "、".join(str(x) for x in sorted(used)) or "—",
               len(live), "、".join(str(x) for x in live) or "—"))


def _prepare_slot(driver, slot):
    """把这一格弄回游客态：关窗口 → 删 profile → 清状态文件。返回做了什么，给界面交代。
    只在「这一格没有号」时才被调用（_clean_slot 保证），不会动到已有账号的登录态。"""
    if not qr:
        return []
    did = []
    try:
        if qr.port_alive(qr.port_of(driver, slot)):
            qr.close(driver, slot)
            did.append("关掉上一轮的窗口")
            time.sleep(0.2)          # close() 自己已经等到端口没了,这里只留一点点余量
    except Exception:
        pass
    try:
        if os.path.isdir(qr.profile_of(driver, slot)):
            if _hard_purge(driver, slot):
                did.append("清掉残留的登录态")
            else:
                did.append("残留登录态清不掉（窗口还占着文件），照样新开")
    except Exception:
        pass
    return did


def reap_dead(auth, db=None, hours=6, force=False):
    """体检：把已经登不上的号标成失效、腾出它的槽并清掉那一格 profile。

    保守两条：① 6 小时内查过就不再查（探一次要真去列目录）；② 要连续两次探失败才判死，
    免得一次网络抖动就把好号释放掉。返回 {"checked":n, "freed":[(alias, slot, why)]}。
    """
    db = db or load_db()
    now = time.time()
    checked, freed = 0, []
    for a in list(db["accounts"]):
        if not force:
            try:
                last = float(a.get("checked_ts") or 0)
            except Exception:
                last = 0
            if now - last < hours * 3600:
                continue
        try:
            ok, why, _n = probe(auth, a)
        except SystemExit as e:                 # 管理员口令没设：整轮别做了
            return {"checked": checked, "freed": freed, "err": str(e)[:160]}
        except Exception as e:
            ok, why = False, "%s: %s" % (type(e).__name__, str(e)[:120])
        checked += 1
        a["checked_ts"] = int(now)
        a["checked_msg"] = (why or "")[:120]
        if ok:
            a["state"] = "ok"
            a["fail_n"] = 0
            continue
        a["fail_n"] = int(a.get("fail_n") or 0) + 1
        if a["fail_n"] < 2:
            continue                            # 一次失败先记着，下一轮再说
        slot = int(a.get("slot") or 0)
        a["state"] = "dead"
        a["dead_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        a["slot"] = 0
        if slot:
            a["released_slot"] = slot
            freed.append((a.get("alias"), slot, why))
            _hard_purge(a.get("driver") or "Quark", slot)
    save_db(db)
    return {"checked": checked, "freed": freed}


def _act_reap(p, auth):
    """界面上的「体检失效号」：现在就去问一遍每个号的挂载还通不通。"""
    if not auth:
        return False, "没有管理员口令（OPENLIST_ADMIN_PASSWORD），体检不了", None
    r = reap_dead(auth, force=bool(p.get("force")))
    if r.get("err"):
        return False, r["err"], None
    if not r["checked"]:
        return True, "刚体检过（6 小时内不重复探），没动任何号", None
    if not r["freed"]:
        return True, "体检 %d 个号：都还能用" % r["checked"], None
    return True, "体检 %d 个号，释放 %d 格：%s" % (
        r["checked"], len(r["freed"]),
        "、".join("%s（第 %d 槽）" % (al, sl) for al, sl, _ in r["freed"])), None


def _act_fs(p, auth):
    """文件面板：列目录 / 拿详情 / 删除 / 上传指定文件 —— 全走 OpenList 的 /api/fs/*。
    op 取值：list(列目录) / stat(拿一个路径详情) / rm(删) / upload(把本地文件传到指定目录)。
    路径一律挂载点起头(如 /quark-03/某个目录)，先夹到合法，再交给 OpenList。
    上传的本地路径只在服务端这一侧被读，不回界面、不写日志；上传本体走 netdisk_upload 的裸流。"""
    if not auth or not auth.token():
        return False, "登不上 OpenList：管理员口令没设或不对", None
    op = (p.get("op") or "list").strip()
    alias = (p.get("alias") or "").strip()
    path = _clean_fs_path(p.get("path"))

    if op == "list":
        page = max(1, min(1000, int(p.get("page") or 1)))
        pp = max(1, min(200, int(p.get("per_page") or 100)))
        r = auth.api("/api/fs/list", {"path": path, "page": page, "per_page": pp,
                                      "refresh": bool(p.get("refresh"))})
        if r.get("code") != 200:
            return False, "列目录失败：%s" % (str(r.get("message") or "")[:180]), None
        data = r.get("data") or {}
        content = data.get("content") or []
        rows = [{"name": x.get("name"), "is_dir": bool(x.get("is_dir")),
                 "size": x.get("size"), "modified": x.get("modified")}
                for x in content]
        return True, "列到 %d 项" % len(rows), {"path": path, "total": data.get("total"),
                                               "rows": rows}

    if op == "stat":
        r = auth.api("/api/fs/get", {"path": path})
        if r.get("code") != 200:
            return False, "拿不到这个路径：%s" % (str(r.get("message") or "")[:180]), None
        return True, "ok", {"path": path, "meta": (r.get("data") or {})}

    if op == "rm":
        if not path or path.rstrip("/") in ("", "/"):
            return False, "不能删根目录", None
        d, name = path.rsplit("/", 1) if "/" in path.strip("/") else ("/", path.strip("/"))
        if not name:
            return False, "路径不对", None
        r = auth.api("/api/fs/remove", {"dir": "/" + d.strip("/"),
                                        "names": [name]})
        if r.get("code") != 200:
            return False, "删不掉：%s" % (str(r.get("message") or "")[:180]), None
        return True, "已删 %s" % path, None

    if op == "upload":
        local = (p.get("local") or "").strip()
        if not local or not os.path.isfile(local):
            return False, "本地文件不存在：%s" % (local or "(空)"), None
        remote_dir = ("/" + path.strip("/")) if path.strip("/") else "/"
        name = os.path.basename(local)
        remote = (remote_dir.rstrip("/") + "/" + name)
        size = os.path.getsize(local)
        sha = nd.sha256(local)
        try:
            r = nd.put_stream(auth, local, remote, size, sha)
        except Exception as e:
            return False, "上传失败：%s: %s" % (type(e).__name__, str(e)[:180]), None
        if r.get("code") != 200 and r.get("code") != 0:
            return False, "上传没成：%s" % (str(r.get("message") or "")[:180]), None
        return True, "已传 %s → %s（%d 字节）" % (name, remote, size), {"path": remote, "size": size}

    return False, "不认识的文件操作 %s（可选 list/stat/rm/upload）" % op, None


def _clean_fs_path(path):
    """夹一个挂载点路径：去掉危险字符，保证在 / 之下、不带 ..、不指向库外。"""
    s = (path or "").replace("\\", "/").strip()
    if not s or s == "/":
        return "/"
    s = "/" + s.strip("/")
    while "/../" in s:
        s = s.replace("/../", "/")
    if s.endswith("/.."):
        s = s.rsplit("/", 1)[0]
    while "//" in s:
        s = s.replace("//", "/")
    return s or "/"


# ---------------------------------------------------------------- 视图占用登记
#
# 11-08 用户的原话：「内嵌浏览器应该能够操作啊，现在根本没有操作页面」。
# 查下来的根子是**看板自己的看守**：它每 15 秒把每个「看着已经登进去」的格子 poll 一遍，
# poll 成功那条路一律 qr.close(slot) —— 用户刚点开的内嵌浏览器，十几秒后就被自家看守关了，
# 界面上只剩一张不再更新的旧图，点哪儿都没反应。实测：同一个 profile 直接开（不经过看守）
# 能活 40 秒以上，经过看板 10~15 秒必掉，和看守周期严丝合缝。
# 所以这里登记「这一格正在被内嵌浏览器用」，收尾关窗口的时候先看一眼。
_VIEW_USE = {}
VIEW_KEEP_SEC = 900          # 15 分钟没人动这一格，才允许看守把它收掉


def _mark_view(driver, slot, op=""):
    try:
        _VIEW_USE[(driver, int(slot))] = (time.time(), op or "")
    except (TypeError, ValueError):
        pass


def _view_in_use(driver, slot, sec=None):
    try:
        t = _VIEW_USE.get((driver, int(slot)))
    except (TypeError, ValueError):
        return False
    if not t:
        return False
    return (time.time() - t[0]) < (sec or VIEW_KEEP_SEC)


def _close_view(driver, slot):
    """扫码这条链收尾要关窗口时走这里：用户正在内嵌浏览器里用这一格就不关。
    回 True = 真关了，False = 给他留着。"""
    if _view_in_use(driver, slot):
        return False
    try:
        qr.close(driver, slot)
    except Exception:
        return False
    return True


def _act_nav(p, auth):
    """内嵌浏览器视图：把前端对「那一格浏览器」的操作落到 CDP 真事件上。
    op：open(开窗口并导航)/shot(整页截图)/metrics(视口尺寸)/click(点击)/scroll(滚动)/
        goto(导航)/url(当前地址)。driver+slot 指定哪一格(哪一号的登录态)。"""
    if not qr:
        return False, "扫码/浏览器模块没装好（%s）" % QR_ERR, None
    driver = (p.get("driver") or "Quark").strip()
    if driver not in DISKS:
        return False, "不认识的盘 %s" % driver, None
    slot = qr._slot(p.get("slot"))
    op = (p.get("op") or "shot").strip()
    _mark_view(driver, slot, op)          # → 看守别把这一格收掉（见 _VIEW_USE 那段注释）

    if op == "open":
        r = qr.start(driver, slot, str(p.get("exe") or ""))
        if not r.get("ok"):
            return False, r.get("msg", ""), None
        # 开窗后把页面带到该盘首页(或指定地址)，并给前端最新视口
        url = (p.get("url") or "").strip()
        if url:
            qr.view_navigate(driver, slot, url)
        m, _ = qr.view_metrics(driver, slot)
        return True, "第 %d 槽已开窗" % slot, {"slot": slot, "port": r.get("port"),
                                               "metrics": m}
    if op == "close":
        r = qr.close(driver, slot)
        return bool(r.get("ok")), r.get("msg", ""), {"slot": slot}
    if op == "shot":
        png, err = qr.view_shot(driver, slot, focus=bool(p.get("focus")))
        if png is None:
            return False, err or "没截到", None
        import base64
        m, _m = qr.view_metrics(driver, slot)
        return True, "ok", {"slot": slot, "png": base64.b64encode(png).decode(),
                            "url": qr.view_url(driver, slot), "metrics": m}
    if op == "metrics":
        m, err = qr.view_metrics(driver, slot)
        if m is None:
            return False, err or "窗口没开着", None
        return True, "ok", {"slot": slot, "metrics": m, "url": qr.view_url(driver, slot)}
    if op == "click":
        r = qr.view_click(driver, slot, float(p.get("x") or 0), float(p.get("y") or 0),
                          ensure_view=bool(p.get("ensure")))
        return r.get("ok", False), r.get("msg", ""), None
    if op == "scroll":
        r = qr.view_scroll(driver, slot, float(p.get("dx") or 0), float(p.get("dy") or 0),
                           float(p.get("x", -1) if p.get("x") is not None else -1),
                           float(p.get("y", -1) if p.get("y") is not None else -1))
        return r.get("ok", False), r.get("msg", ""), {"moved": r.get("moved")}
    if op == "text":
        r = qr.view_text(driver, slot, str(p.get("text") or ""))
        return r.get("ok", False), r.get("msg", ""), None
    if op == "key":
        r = qr.view_key(driver, slot, str(p.get("key") or ""))
        return r.get("ok", False), r.get("msg", ""), None
    if op == "goto":
        r = qr.view_navigate(driver, slot, str(p.get("url") or ""))
        return r.get("ok", False), r.get("msg", ""), None
    if op == "url":
        return True, "ok", {"url": qr.view_url(driver, slot)}
    return False, "不认识的浏览器操作 %s（可选 open/close/shot/metrics/click/scroll/text/key/goto/url）" % op, None


def _hard_purge(driver, slot):
    """直接删掉某一格的 profile 目录（不经过 CDP 关窗口那套）。

    为什么不用 qr.purge：它在看板进程里偶尔抛 SystemExit(1)（底层 close/CDP 那条链），
    被吞掉之后 profile 还在，下一轮又占着格子 —— 实测「自动挑空槽」一直挑不到第 4 格。
    自己 rmtree 只看目录，失败就返回 False，语义清楚。
    """
    if not qr:
        return False
    try:
        p = qr.profile_of(driver, slot)
    except Exception:
        return False
    if not p.startswith(qr.BASE_DIR):
        return False
    import shutil
    try:
        shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass
    try:
        st = qr._read_state(driver, slot) or {}
        if st and not qr.port_alive(qr.port_of(driver, slot)):
            qr._rm_state(driver, slot)
    except Exception:
        pass
    return not os.path.isdir(p)


def _reap_orphan_profiles(driver, db):
    """清掉「有 profile 但库里没有号、窗口也没开着」的孤儿格。

    不扫地的话每扫一次就永久占掉一格（实测 11-08 一上午就攒了 4/6/7 三个空壳），
    格数越用越少，最后明明没几个号却喊「占满」。只清我们自己的 profile 目录。
    """
    if not qr:
        return 0
    used = _live_slots(driver, db)
    try:
        live = {int(r["slot"]) for r in (qr.slots(driver) or []) if r.get("listening")}
    except Exception:
        live = set()
    killed = 0
    for n in range(1, qr.MAX_SLOTS + 1):
        if n in used or n in live:
            continue
        if not os.path.isdir(qr.profile_of(driver, n)):
            continue
        if _hard_purge(driver, n):
            killed += 1
    return killed


def _act_qr(p, auth):
    """扫码这条链的四个阶段：start 开窗口 / poll 问扫上没（扫上了就抓+验+存）/ close / purge。
    都按「盘 × 登录位（slot）」走：一个登录位 = 一个独立 profile = 一个号的登录态，
    换号扫是换一格，不是把上一格那个号顶掉。
    界面每 2 秒 poll 一次，用户只管扫码，不用回来填任何东西。"""
    phase = (p.get("phase") or "poll").strip()
    driver = (p.get("driver") or "Quark").strip()
    if not qr:
        return False, "扫码模块没装好（%s）——手填凭据那条还能用" % QR_ERR, None
    if driver not in DISKS:
        return False, "不认识的盘 %s" % driver, None
    slot = qr._slot(p.get("slot"))
    if phase == "start":
        # 11-08 用户要求：「槽位别让我选，每次自动加一个」。
        # 所以 start 一律自己挑一格：库里没号 + 没有活窗口（详见 _clean_slot）。
        # 之前那套「前端发 slot + auto_new 兜底」全撤了 —— 它已经连着坑了三次
        # （下拉回第 1 槽、老脚本不带 auto_new、并号改槽位）。
        db0 = load_db()
        req = qr._slot(p.get("slot"))
        # 但「这一格还开着、又不是哪个号的」就别再开新格了：点一次扫码登录开一格浏览器，
        # 一上午能攒出六个 headless 进程 + 六个空壳 profile（11-08 实测：第 6/8/9/10 格都是这么来的），
        # 探测越来越慢、格数越用越少,用户看到的就是「启动越来越慢」。同一格重开,秒回。
        reuse = 0
        try:
            used = _live_slots(driver, db0)
            r0 = (_slot_state(driver).get(req) or {})
            if req not in used and r0.get("listening") and r0.get("page_ok", True):
                reuse = req
        except BaseException:
            reuse = 0
        try:
            clean = reuse or _clean_slot(driver, db0)
        except BaseException as e:
            # 以前这里 `except BaseException: clean = 0` 把异常吞成「满了」，
            # 于是任何一个意外都长成同一句「十格都占满了」——用户当然觉得莫名其妙。
            return False, ("挑登录位时出错了：%s: %s —— 这跟「占满」无关，"
                           "把这句话发给开发者看。" % (type(e).__name__, str(e)[:120])), None
        if not clean:
            # 真的一个空位都没有：先扫掉「有 profile 但库里没号、窗口也没开」的空壳格，再试一次
            try:
                _reap_orphan_profiles(driver, db0)
            except BaseException:
                pass
            db0 = load_db()
            try:
                clean = _clean_slot(driver, db0)
            except BaseException as e:
                return False, ("挑登录位时出错了：%s: %s" % (type(e).__name__, str(e)[:120])), None
        if not clean:
            return False, _why_full(driver, db0), None
        slot = clean
        if reuse:
            # 同一格重开:profile 留着(游客态),省掉删 20~100MB 目录那几秒
            did = []
            r = qr.start(driver, slot, str(p.get("exe") or ""), fresh=True)
        else:
            # 这一格没号（_clean_slot 保证），开窗前一并收拾干净：关掉上一轮残留的窗口、
            # 删掉旧 profile —— 否则窗口一开就是「已登录某个号」的状态，压根不出二维码，
            # 用户看到的就是「点了扫码登录什么都没有」。
            did = _prepare_slot(driver, slot)
            r = qr.start(driver, slot, str(p.get("exe") or ""), fresh=True)
        st = _qr_state(driver, slot, {"phase": "start"})
        msg = r.get("msg", "")
        if did:
            msg += "（%s）" % "、".join(did)
        return bool(r.get("ok")), msg, st
    if phase == "close":
        r = qr.close(driver, slot)
        return bool(r.get("ok")), r.get("msg", ""), _qr_state(driver, slot, {"phase": "close"})
    if phase == "purge":
        r = qr.purge(driver, slot)
        return bool(r.get("ok")), r.get("msg", ""), _qr_state(driver, slot, {"phase": "purge"})
    if phase != "poll":
        return False, "不认识的扫码阶段 %s" % phase, None

    st = _qr_state(driver, slot)
    if not st.get("listening") or not st.get("page_ok", True):
        # 11-08「明明开着窗口，界面却说没开成」+「串项目」：页面可能盯着一格早就关掉的老槽，
        # 或这一格的窗口被别的程序(录播)连上调试端口导航走了。先看谁真开着**且还停在登录页**，跟过去再问。
        try:
            live = [r for r in (qr.slots(driver) or []) if r.get("listening") and r.get("page_ok", True)]
        except Exception:
            live = []
        follow = next((r for r in live if int(r.get("slot") or 0) != slot), None)
        if follow:
            was, slot = slot, int(follow["slot"])
            st = _qr_state(driver, slot)
            st["followed_from"] = was
            st["msg"] = "第 %d 槽没在登录页，跟到真正开着的第 %d 槽" % (was, slot)
        else:
            return False, st.get("msg") or "第 %d 槽的登录窗口没开着（先点『扫码登录』）" % slot, st
    target = (qr.DISKS.get(driver) or {}).get("field") or ""
    if not target:
        return False, "%s 在 OpenList 里不吃 cookie，扫码只当看内容——挂载请按下面的表单填" % DISKS[driver], st
    ck, why, names = qr.build_cookie(driver, slot)
    if ck is None:
        return False, why or "还没抓到 cookie", dict(st, cookie_names=names)
    fields = dict(_default_values(driver))
    fields[target] = ck
    ident = identity_of(driver, fields)
    st = dict(st, cookie_names=names[:40], cookie_count=len(names), login_ok=bool(ident.get("ok")))
    if not ident.get("ok"):
        return False, "抓到了但还没登录上：%s" % (ident.get("msg") or "网盘没认"), st
    if not (auth and auth.token()):
        return False, ("已经认出账号 %s，但存不进 OpenList：管理员口令没设"
                       "（环境变量 OPENLIST_ADMIN_PASSWORD）" % (ident.get("nickname") or ident.get("uid")), st)

    db = load_db()
    seed = ident.get("uid") or hashlib.sha1(ck.encode("utf-8")).hexdigest()[:12]
    same = None
    if ident.get("uid"):
        for a in db["accounts"]:
            if a.get("driver") == driver and str(a.get("uid")) == str(ident["uid"]):
                same = a
                break
    nxt = _next_slot(driver, db)
    if same:                                   # 同一个账号重扫 = 换凭据，不新开一条
        prev = int(same.get("slot") or 0)
        if not prev:
            # 这个号之前体检判死、槽已经释放了（slot=0）。重新扫上就重新占一个空槽，
            # 不能走下面「并号」那条（会把它当成"库里已有"直接拒掉）。
            clean = _clean_slot(driver, db) or slot
            sec0 = secret_of(same) if same.get("secret") else {}
            sec0.update({k: v for k, v in fields.items() if SECRET_RE.search(k)})
            store_secret(same, sec0)
            for k, v in fields.items():
                if not SECRET_RE.search(k) and v:
                    same.setdefault("plain", {})[k] = v
            same["slot"] = clean
            same.pop("state", None)
            same.pop("released_slot", None)
            same["fail_n"] = 0
            fill_identity(db, same, fields)
            ok, msg = activate(db, auth, same)
            _close_view(driver, clean)
            return ok, "这个号之前失效、槽已释放；这次重新登进第 %d 槽 —— %s" % (clean, msg), safe_rec(same)
        try:
            stored = (secret_of(same) or {}).get(target) or ""
        except Exception:
            stored = ""                        # 解不开（换机器/库坏了）就往下走覆盖那条路
        if prev == slot and stored == ck:      # 这一槽登着的就是它，库里那份一字不差
            return False, ("第 %d 槽登着的就是「%s」（%s）——和库里存的 cookie 一模一样，不用重扫，窗口给你留着。"
                           "要加另一个号：把上面『登录位』调到%s再点『打开扫码窗口』，"
                           "那是另一个独立 profile，不会顶掉这个号。"
                           % (slot, same.get("nickname") or same["alias"], same["alias"],
                              ("第 %d 槽 " % nxt) if nxt else "（%d 个登录位都占着了，先删一个号）" % qr.MAX_SLOTS)), \
                dict(st, already=True, alias=same["alias"], next_slot=nxt)
        sec = secret_of(same) if same.get("secret") else {}
        sec.update({k: v for k, v in fields.items() if SECRET_RE.search(k)})
        store_secret(same, sec)
        for k, v in fields.items():
            if not SECRET_RE.search(k) and v:
                same.setdefault("plain", {})[k] = v
        if prev != slot:
            # 11-08 用户第三次困惑的正是这里：扫的这个号**库里已经有了**，只是扫进了另一格。
            # 原来的写法把记录从第 3 槽直接改记到第 5 槽、再关掉窗口 —— 用户看到的是
            # 「扫完窗口自己关了、也没多出账号」，而且第 3 槽那格 profile 还登着同一个号，留下两格并号。
            # 正确做法：槽位一概不动，把这一格多扫出来的窗口清掉，并明确告诉用户这不是新号。
            same["slot"] = prev
            fill_identity(db, same, fields)      # 只刷新昵称/ID 这类身份信息，槽位保持原样
            save_db(db)
            qr.purge(driver, slot)               # 这一格是并号扫出来的，删掉别留重复登录态
            return False, ("扫的这个号库里已经有了：「%s」（%s，一直登在第 %d 槽）—— 不是新号，所以没有新增账号；"
                           "第 %d 槽那个多扫出来的窗口已经关掉清空。"
                           "要加下一个号：先在手机夸克 App 里退出/切换到另一个账号，再点『打开扫码窗口』扫。"
                           % (same.get("nickname") or same["alias"], same["alias"], prev, slot)), \
                   dict(st, already=True, duplicate=True, alias=same["alias"],
                        slot=prev, scanned_slot=slot, next_slot=nxt)
        fill_identity(db, same, fields)
        ok, msg = activate(db, auth, same)
        kept = not _close_view(driver, slot)
        return ok, "同一个账号重扫好了：%s（凭据已更新%s）—— %s" % (
            same["alias"], "、窗口给你留着（内嵌浏览器正在用这一格）" if kept
            else "、第 %d 槽的窗口关掉" % slot, msg), safe_rec(same)
    alias = auto_alias(driver, seed, db)
    remark = ("%s %s" % (DISKS[driver], ident.get("nickname") or "")).strip()[:60]
    add_account(driver, alias, fields, remark=remark)
    db = load_db()
    acct = get_acct(db, alias)
    acct["slot"] = slot
    fill_identity(db, acct, fields)
    ok, msg = activate(db, auth, acct)
    kept = not _close_view(driver, slot)
    return ok, ("扫码登录成功：自动起名 %s（ID %s，账号名 %s，登在第 %d 槽）—— %s；%s"
                % (alias, acct.get("uid") or "网盘没给", acct.get("nickname") or "网盘没给", slot, msg,
                   "窗口给你留着（内嵌浏览器正在用这一格），这一槽的 profile 还是这个号"
                   if kept else "窗口已关，这一槽的 profile 留着，下次点开还是这个号"))[:400], \
        safe_rec(acct)


def _default_values(driver):
    """网盘表单里非凭据那几格先按 OpenList 自己的默认值填上（root_folder_id 之类），
    免得自动入库的账号因为少填必填项被标成坏号。默认值也是现取的，不写死。"""
    try:
        known, _ = fields_of(driver)
    except BaseException:
        return {}
    out = {}
    for f in known:
        n = f.get("name")
        if n and not SECRET_RE.search(n):
            out[n] = str(f.get("default", "") or "")
    return out


def _act_save(p, auth):
    """新建或覆盖一条账号 = 存凭据 + 建/改挂载点 + 立刻探一次，并顺手验一次身（谁都能看出存的哪个号）。"""
    alias = (p.get("alias") or "").strip()
    driver = (p.get("driver") or "").strip()
    remark = (p.get("remark") or "").strip()
    vals = {k: (v if isinstance(v, str) else str(v or "")) for k, v in (p.get("fields") or {}).items()}
    db = load_db()
    existing = get_acct(db, alias)
    if p.get("edit"):
        if not existing:
            return False, "要改的账号 %s 不在库里" % alias, None
        sec = {k: v for k, v in vals.items() if SECRET_RE.search(k) and v}
        old = secret_of(existing)
        old.update(sec)
        store_secret(existing, old)                 # 没重填的密文字段保持原值，不会被抹成空
        for k, v in vals.items():
            if not SECRET_RE.search(k) and v:
                existing.setdefault("plain", {})[k] = v
        merged = dict(existing.get("plain") or {})
        merged.update(old)                       # 内存里拼回完整凭据，只用来验身，不往外传
        fill_identity(db, existing, merged)
        ok, msg = activate(db, auth, existing)
        if not ok:                       # 别「加好了」和红色报错同屏：存是存了，是这个号用不了
            return False, "凭据改了（挂载点 %s），但探测没过，cookie 可能还是不对：%s" % (
                existing["mount_path"], msg), safe_rec(existing)
        return True, "更新并探测：%s" % msg, safe_rec(existing)
    if existing:
        return False, "已经有叫 %s 的账号了，要覆盖走『改凭据』" % alias, None
    if not ALIAS_RE.match(alias):
        return False, "别名只能用的小写字母/数字/-/_，2~24 位，例如 quark-03", None
    if driver not in DISKS:
        return False, "不认识的盘 %s" % driver, None
    if not any(v.strip() for v in vals.values()):
        return False, "一格都没填，没东西可存", None
    add_account(driver, alias, vals, remark=remark)
    db = load_db()
    acct = get_acct(db, alias)
    fill_identity(db, acct, vals)
    ok, msg = activate(db, auth, acct)
    label = acct.get("nickname") or acct.get("uid") or "没认出账号名"
    if not ok:                           # 库里这条已经在界面上了，话要说清「存下了但用不了」
        return False, "号存下了（%s，挂载点 %s），但挂载点列不出东西，cookie 多半不对：%s" % (
            label, acct["mount_path"], msg), safe_rec(acct)
    return True, "加好了（%s，挂载点 %s）：%s" % (label, acct["mount_path"], msg), safe_rec(acct)


def _act_check(p, auth):
    db = load_db()
    a = get_acct(db, (p.get("alias") or "").strip())
    if not a:
        return False, "没有这个账号", None
    ok, msg, n = probe(auth, a)
    a["last_check"], a["last_ok"], a["last_msg"], a["items"] = now(), ok, msg, n
    save_db(db)
    try:                                   # 顺手刷新「这是谁」：cookie 过期会在昵称这栏露出来
        merged = dict(a.get("plain") or {})
        merged.update(secret_of(a) if a.get("secret") else {})
        fill_identity(db, a, merged)
    except Exception as e:
        a["ident_msg"] = "验身没跑成：%s" % type(e).__name__
        save_db(db)
    return ok, msg, safe_rec(a)


def _act_use(p, auth):
    db = load_db()
    a = get_acct(db, (p.get("alias") or "").strip())
    if not a:
        return False, "没有这个账号", None
    switched = use_only(db, auth, a)
    ok, msg, n = probe(auth, a)
    a["last_check"], a["last_ok"], a["last_msg"], a["items"] = now(), ok, msg, n
    save_db(db)
    return ok, "已切到 %s（同盘 %d 个重新登记，其余停用）：%s" % (a["alias"], len(switched), msg), safe_rec(a)


def _act_del(p, auth):
    """先删 OpenList 的挂载点，**删掉了才抹库里的密文**——反过来就留下没人认领的挂载点。"""
    db = load_db()
    a = get_acct(db, (p.get("alias") or "").strip())
    if not a:
        return False, "没有这个账号", None
    gone, msg = drop_storage(auth, a["mount_path"])
    if not gone:
        return False, "挂载点 %s 没删掉（%s），密文原样留着不动" % (
            a["mount_path"], msg or "OpenList 没回话"), safe_rec(a)
    was_active, driver = bool(a.get("active")), a.get("driver")
    db["accounts"] = [x for x in db["accounts"] if x["alias"] != a["alias"]]
    tail = ""
    if was_active:                    # 删的是当前在用的号：同盘还有别人就接上，
        rest = [x for x in db["accounts"] if x.get("driver") == driver]   # 不然库里全停用、
        if rest:                      # 网盘那侧的挂载点却还挂着，两边对不上
            use_only(db, auth, rest[0])
            tail = "，同盘接着用 %s" % rest[0]["alias"]
    save_db(db)
    return True, "挂载点删掉了，库里这条（含密文）也一起抹了%s" % tail, None


# ---------------------------------------------------------------- 定时保活
# 痛点：cookie 寿命由网盘服务器定，闲置会更快到期；以前只有手动点「检查」才探，
# 下载中途才发现失效。这里把「探」变成定时轻量请求：① 每次探都是一次带凭据的真实
# 请求，能续闲置寿命；② 提前发现到期、写预警报告；③ 失效盘预备扫码（重登只需扫一次）。
# 不保证永不过期（服务器说了算），只把重登 friction 降到最低。凭据值仍走 DPAPI，绝不进报告。

KA_REPORT = os.path.join(nd.ROOT, "06-资讯监控", "网盘保活", "保活报告.json")


def _ka_mark(a, ok, msg, n, ts):
    """纯函数：把一次探测结果记进账号（两次连败才判死，免得一回网络抖动误杀好号）。
    不联网、不写库，方便离线自检钉死状态机。ts 是 epoch 秒。"""
    stamp = dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    a["last_check"], a["last_ok"], a["last_msg"], a["items"] = stamp, bool(ok), (msg or "")[:200], n
    a["checked_ts"], a["checked_msg"] = int(ts), (msg or "")[:120]
    if ok:
        a["state"], a["fail_n"], a["needs_relogin"] = "ok", 0, False
        a["last_ok_at"] = stamp
    else:
        a["fail_n"] = int(a.get("fail_n") or 0) + 1
        dead = a["fail_n"] >= 2
        a["state"] = "dead" if dead else "warn"
        a["needs_relogin"] = dead
    return a


def _prepared_window(driver, db):
    """这个盘是不是已经有一格开着的、还没扫上号的登录窗（listening+page_ok 且不属于任何活号）。
    有就回那格槽号、别再开新格——否则每天保活给同一个失效盘各开一扇窗，几天就堆满 headless 进程
    （_clean_slot 会避开活窗另挑空格，正是堆积的根）。回 0 表示没有现成预备窗。"""
    if not qr:
        return 0
    used = _live_slots(driver, db)
    rows = _slot_state(driver)
    for n in range(1, qr.MAX_SLOTS + 1):
        r = rows.get(n) or {}
        if n not in used and r.get("listening") and r.get("page_ok", True):
            return n
    return 0


def _puus_fresh(cookies, now_ts):
    """纯函数：__puus 是夸克下载态的命根（TTL≈18h），expiry 距现在 >17h 才算这次访问
    真滚到了新 cookie。光看 cookie 在不在不够——profile 磁盘里那份旧的也在。"""
    for c in cookies or []:
        if c.get("name") == "__puus":
            try:
                return float(c.get("expires") or 0) - now_ts > 17 * 3600
            except (TypeError, ValueError):
                return False
    return False


def _download_probe(auth, a):
    """字节级下载探针：挂载点根目录挑最小文件（≤1MB）拉前 256 字节。
    列目录只要 __pus（≈9 天）就绿，下载要 __puus（≈18h）——不实测字节就是假绿（11-10 踩过）。
    返回 (ok, msg)；ok=None 表示没探成（根目录没小文件），不算失败也不算通过。"""
    r = auth.api("/api/fs/list", {"path": a["mount_path"], "page": 1, "per_page": 100, "refresh": True})
    items = ((r.get("data") or {}).get("content") or [])
    files = [it for it in items if not it.get("is_dir") and 0 < (it.get("size") or 0) <= 1024 * 1024]
    if not files:
        return None, "根目录没有 ≤1MB 的文件，字节探针没探"
    it = min(files, key=lambda x: x["size"])
    p = a["mount_path"].rstrip("/") + "/" + it["name"]
    d = auth.api("/api/fs/get", {"path": p})
    x = d.get("data") or {}
    if not x.get("sign"):
        return False, "fs/get 没给 sign：%s" % str(d.get("message") or "")[:100]
    url = nd.BASE + "/d" + urllib.parse.quote(p) + "?sign=" + urllib.parse.quote(x["sign"])
    req = urllib.request.Request(url, headers={"Range": "bytes=0-255"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data, code = resp.read(), resp.status
    except urllib.error.HTTPError as e:
        return False, "HTTP %d" % e.code
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, str(e)[:100])
    want = min(256, it["size"])
    if code not in (200, 206) or len(data) != want:
        return False, "HTTP %d 回了 %d 字节（要 %d）" % (code, len(data), want)
    return True, "下载实测 OK（%s 前 %d 字节）" % (it["name"][:30], want)


def refresh_from_profile(db, auth, a):
    """夸克持久化续期：开独立 profile 访问 pan.quark.cn 让服务器滚动 cookie，抓回来走
    store_secret+activate 生产路径回写 OpenList，再实测字节下载。
    返回 (ok, msg)，msg 只含人话结论、不含凭据值。
    为什么需要它：OpenList 存的是 cookie 快照不会自己滚，__puus ≈18h 一过下载就 403/412，
    而列目录要的 __pus ≈9 天还活着——保活只列目录就一直是假绿。浏览器 profile 每次访问
    都会被服务器滚新 cookie，所以每天开两次窗抓回来回写，登录态就能一直续下去。"""
    if a.get("driver") != "Quark" or not qr:
        return False, "非夸克或没扫码模块，续不了期"
    slot = int(a.get("slot") or 1)
    if not os.path.isdir(qr.profile_of("Quark", slot)):
        return False, "没有 profile，续不了期（要重扫一次）"
    r = qr.start("Quark", slot)
    if not r.get("ok"):
        return False, "开窗口失败：%s" % (r.get("msg") or "")[:120]
    opened = not r.get("reused")
    grabbed = False
    try:
        if r.get("reused"):
            # 窗口已开着时页面停在旧响应上，不重新导航服务器就不滚 cookie
            try:
                qr._cdp(qr.port_of("Quark", slot), "Page.navigate",
                        {"url": qr.DISKS["Quark"]["url"]})
            except Exception:
                pass
        cookies = None
        for _ in range(15):                     # 等服务器把 __puus 滚新（页面加载+set-cookie 才算）
            time.sleep(2)
            cookies, _why = qr.cookie_names("Quark", slot)
            if cookies and _puus_fresh(cookies, time.time()):
                break
        else:
            return False, "profile 没登录态或 cookie 没滚动（要重扫一次）"
        ck, why, _names = qr.build_cookie("Quark", slot)
        if ck is None:
            return False, "抓 cookie 失败：%s" % (why or "")[:120]
        grabbed = True                          # 登录态确认，用完可以关窗；没登录的窗留着给用户扫码
        target = (qr.DISKS.get("Quark") or {}).get("field") or "cookie"
        fields = dict(_default_values("Quark"))
        fields[target] = ck
        ident = identity_of("Quark", fields)
        if not ident.get("ok"):
            return False, "新 cookie 网盘没认：%s" % (ident.get("msg") or "")[:120]
        if ident.get("uid") and a.get("uid") and str(ident["uid"]) != str(a["uid"]):
            return False, "profile 登的是别的账号（uid 不符），拒写"
        sec = secret_of(a) if a.get("secret") else {}
        sec.update({k: v for k, v in fields.items() if SECRET_RE.search(k)})
        store_secret(a, sec)
        for k, v in fields.items():
            if not SECRET_RE.search(k) and v:
                a.setdefault("plain", {})[k] = v
        fill_identity(db, a, fields)
        ok, msg = activate(db, auth, a)
        if not ok:
            return False, "回写后列目录失败：%s" % msg[:120]
        pok, pmsg = _download_probe(auth, a)
        if pok is False:
            return False, "续期后下载实测失败：%s" % pmsg[:120]
        return True, "cookie 已续期；%s" % pmsg[:100]
    finally:
        if opened and grabbed:
            qr.close("Quark", slot)             # 用完就关，不堆 headless 进程


def keepalive(auth=None, hours=6, force=False, prepare_qr=False, alias=None,
              report_path=None):
    """对账号逐个轻量保活探测，写预警报告；失效盘可选预备扫码。返回汇总（不含凭据值）。"""
    db = load_db()
    auth = auth or _auth()
    try:
        auth.token()
    except SystemExit as e:
        return {"ok": False, "skipped": "no_password", "msg": str(e)[:200],
                "checked": 0, "accounts": []}
    except Exception as e:
        return {"ok": False, "skipped": "auth_error",
                "msg": "%s: %s" % (type(e).__name__, str(e)[:160]),
                "checked": 0, "accounts": []}
    now_ts = time.time()
    todo = [a for a in db["accounts"] if (not alias or a["alias"] == alias)]
    checked, skipped, recs = 0, 0, []
    for a in todo:
        if not force:
            try:
                last = float(a.get("checked_ts") or 0)
            except Exception:
                last = 0
            if now_ts - last < hours * 3600:
                skipped += 1
                recs.append(safe_rec(a))
                continue
        refresh_msg = ""
        if a.get("driver") == "Quark" and a.get("active", True):
            try:
                rok, rmsg = refresh_from_profile(db, auth, a)
            except SystemExit as e:
                return {"ok": False, "skipped": "no_password", "msg": str(e)[:200],
                        "checked": checked, "accounts": recs}
            except Exception as e:
                rok, rmsg = False, "%s: %s" % (type(e).__name__, str(e)[:100])
            a["cookie_refresh"] = {"ok": bool(rok), "msg": rmsg[:160], "at": now()}
            refresh_msg = rmsg
        try:
            ok, msg, n = probe(auth, a)
        except SystemExit as e:
            return {"ok": False, "skipped": "no_password", "msg": str(e)[:200],
                    "checked": checked, "accounts": recs}
        except Exception as e:
            ok, msg, n = False, "%s: %s" % (type(e).__name__, str(e)[:120]), -1
        if refresh_msg:
            msg = "%s；%s" % (msg, refresh_msg)
        _ka_mark(a, ok, msg, n, now_ts)
        checked += 1
        recs.append(safe_rec(a))
    save_db(db)
    need = [a["alias"] for a in db["accounts"] if a.get("needs_relogin")]
    prepared = []
    if prepare_qr and need and qr:
        drivers = []
        for a in db["accounts"]:
            if a.get("needs_relogin") and a.get("driver") not in drivers:
                drivers.append(a["driver"])
        for drv in drivers:                      # 每盘只留一格预备扫码窗：已有活窗就复用，不每天重开堆进程
            have = _prepared_window(drv, db)
            if have:
                prepared.append({"driver": drv, "ok": True, "slot": have,
                                 "msg": "第 %d 槽已有预备扫码窗，复用不重开（扫一次即可）" % have})
                continue
            r = do_action("qr", {"phase": "start", "driver": drv})
            prepared.append({"driver": drv, "ok": bool(r.get("ok")),
                             "slot": (r.get("qr") or {}).get("slot"),
                             "msg": (r.get("msg") or "")[:160]})
    summary = {
        "ok": True, "checked": checked, "skipped_throttle": skipped,
        "ok_n": sum(1 for a in db["accounts"] if a.get("state") == "ok"),
        "warn_n": sum(1 for a in db["accounts"] if a.get("state") == "warn"),
        "dead_n": sum(1 for a in db["accounts"] if a.get("state") == "dead"),
        "needs_relogin": need, "prepared_qr": prepared,
        "refresh_failed": [a["alias"] for a in db["accounts"]
                           if a.get("active", True) and a.get("driver") == "Quark"
                           and not (a.get("cookie_refresh") or {}).get("ok")],
        "at": now(), "accounts": recs,
    }
    rp = report_path or KA_REPORT
    try:
        os.makedirs(os.path.dirname(rp), exist_ok=True)
        with open(rp, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=1)
        summary["report_path"] = rp
    except Exception as e:
        summary["report_err"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return summary


def _act_keepalive(p, auth):
    if not auth:
        return False, "没有管理员口令（OPENLIST_ADMIN_PASSWORD），保活不了", None
    r = keepalive(auth, hours=float(p.get("hours") or 6),
                  force=bool(p.get("force")), prepare_qr=bool(p.get("prepare_qr")),
                  alias=(p.get("alias") or "").strip() or None)
    if r.get("skipped"):
        return False, r.get("msg") or "保活跳过", None
    msg = "保活 %d 个（节流跳过 %d）：有效 %d / 预警 %d / 失效 %d%s" % (
        r["checked"], r["skipped_throttle"], r["ok_n"], r["warn_n"], r["dead_n"],
        ("；待重登：" + "、".join(r["needs_relogin"])) if r["needs_relogin"] else "")
    return True, msg, r


ACTIONS = {"save": _act_save, "check": _act_check, "use": _act_use, "del": _act_del, "qr": _act_qr,
           "reap": _act_reap, "fs": _act_fs, "nav": _act_nav, "keepalive": _act_keepalive}
# 扫码这四个阶段里，只有「真的扫上了要入库」才需要 OpenList 管理员口令；
# 开窗口/看进度/关窗口/清 profile 跟 OpenList 无关，所以口令没设也能用。
# nav(浏览器视图)同样不碰 OpenList、不碰凭据值，纯 CDP 回环，口令没设也能用。
NO_AUTH_NEEDED = ("qr", "nav")


def do_action(kind, payload=None):
    """看板 POST 进来的唯一门。永远回一个 dict，绝不让异常跑到界面线程上。"""
    p = payload or {}
    if kind == "start":
        ok = nd.ensure_server()
        return {"ok": bool(ok), "msg": "OpenList 127.0.0.1:%d %s" % (
            nd.PORT, "在听" if ok else "起不来——日志在 %s" % os.path.join(nd.OL_DIR, "data", "log", "log.log")),
            "account": None, "accounts": list_safe()}

    def out(ok, msg, rec=None):
        return {"ok": bool(ok), "msg": (msg or "")[:400], "account": rec, "accounts": list_safe()}

    fn = ACTIONS.get(kind)
    if not fn:
        return out(False, "不认识的动作 %s（可选：%s）" % (kind, "、".join(sorted(ACTIONS) + ["start"])))
    auth = _auth()
    login_err = ""
    try:
        tok = auth.token()
    except SystemExit as e:                # 口令没设/不对、或 OpenList 没在听：token() 走 SystemExit
        tok, login_err = "", str(e)[:200]
    except Exception as e:                 # 兜底：契约是「永远回 dict」，别让登录异常炸到界面线程
        tok, login_err = "", "%s: %s" % (type(e).__name__, str(e)[:160])
    if not tok:
        if kind not in NO_AUTH_NEEDED:
            return out(False, "登不上 OpenList：%s（值不进日志、不进库）"
                       % (login_err or "环境变量 OPENLIST_ADMIN_PASSWORD 没设或不对"))
        auth = None                        # 扫码的开窗口/看进度/关窗口跟 OpenList 无关，口令没设也能用
    try:
        ok, msg, rec = fn(p, auth)
    except SystemExit as e:                       # 命令行那套「错就 SystemExit」在这里接住
        _t = str(e)[:300]
        # 有时底层工具直接 sys.exit(1)，str(e) 就只有个 "1"，对用户等于没说
        ok, msg, rec = False, (_t if _t.strip() and not _t.strip().isdigit() else "这一步被内部工具中断了，再点一次通常就好"), None
    except Exception as e:
        ok, msg, rec = False, "%s: %s" % (type(e).__name__, str(e)[:260]), None
    res = out(ok, msg, rec)
    if kind == "nav" and isinstance(rec, dict):
        # 内嵌浏览器那些回执(滚轮到底没到底 = moved)摊到顶层,前端直接读 json.moved;
        # account 还是照旧留给 shot 的 png/url/metrics,两边不打架。
        for k in ("moved", "slot", "url", "metrics"):
            if k in rec:
                res[k] = rec[k]
    if kind == "qr":
        # _act_qr 的第三个返回值两种都有：入库成功时是账号记录，看进度时是扫码状态。
        # 这里分成两个字段给界面，省得前端猜 account 里装的是哪一类。
        is_status = isinstance(rec, dict) and "listening" in rec
        res["qr"] = rec if is_status else None
        res["account"] = None if is_status else rec
        res["qr_ready"] = bool(qr)
        res["qr_err"] = QR_ERR
    return res


# ---------------------------------------------------------------- 命令行

def cmd_list(args):
    db = load_db()
    if not db["accounts"]:
        print("账号库是空的（%s）。开看板「网盘」页签（08-数据看板\\启动看板.bat）按『打开扫码窗口』扫一下，"
              "或手填 cookie。" % DB_PATH)
        return 0
    for a in db["accounts"]:
        print("%-6s %-12s %-14s %s %s %-6s ID %-12s 账号名 %-14s 探测 %s %s"
              % (DISKS.get(a["driver"], a["driver"])[:4], a["alias"], a["mount_path"],
                 "活跃" if a.get("active") else "停用",
                 "有效" if a.get("last_ok") else ("失效" if a.get("last_check") else "未测"),
                 "第%s槽" % (a.get("slot") or 1),
                 (a.get("uid") or "-")[:12], (a.get("nickname") or "-")[:14],
                 a.get("last_check", "-"), (a.get("last_msg") or "")[:60]))
    return 0


def cmd_qr(args):
    """命令行版扫码：poll 一次就能看到「窗口在不在、抓到几个名字、网盘认不认这个会话」。"""
    r = do_action("qr", {"phase": args.phase, "driver": args.driver,
                         "slot": args.slot, "exe": args.exe,
                         "auto_new": "1" if getattr(args, "auto_new", False) else "0"})
    keep = ("listening", "port", "url", "login_url", "cookie_count", "cookie_names",
            "names", "markers", "markers_have", "login_ok", "phase", "howto", "msg",
            "slot", "max_slot", "profile", "already", "next_slot",
            "switched_from", "switched_to")
    print(json.dumps({k: r.get("qr", {}).get(k) for k in keep if (r.get("qr") or {}).get(k) is not None},
                     ensure_ascii=False, indent=1))
    print("结论：%s" % r.get("msg"))
    if r.get("account"):
        print("入库：", json.dumps(r["account"], ensure_ascii=False))
    print("扫码模块：%s" % ("在" if r.get("qr_ready") else "没装好：" + r.get("qr_err", "")))
    return 0 if r.get("ok") else 1


def cmd_add(args):
    env = args.value_env
    if not env:
        vals = {}
        known, _ = fields_of(args.driver)
        for f in known:
            n = f["name"]
            if not n:
                continue
            vals[n] = (getpass.getpass("%s: " % n) if SECRET_RE.search(n) else input("%s: " % n)).strip()
    else:
        raw = os.environ.get(env, "")
        if not raw:
            raise SystemExit("环境变量 %s 是空的，命令行里不要直接敲凭据" % env)
        vals = json.loads(raw)
    acct = add_account(args.driver, args.alias, vals, remark=args.remark)
    db = load_db()
    acct = get_acct(db, args.alias)
    fill_identity(db, acct, vals)
    ok, msg = activate(db, _auth(), acct)
    print("%s 加好：%s（%s）ID %s 账号名 %s"
          % (args.alias, "有效" if ok else "已存但探测没过", msg,
             acct.get("uid") or "没认出", acct.get("nickname") or "没认出"))
    return 0 if ok else 1


def cmd_check(args):
    db = load_db()
    auth = _auth()
    todo = [a for a in db["accounts"]
            if args.alias in ("", "all", None) or a["alias"] == args.alias]
    if not todo:
        print("没有这个账号")
        return 1
    bad = 0
    for a in todo:
        ok, msg, n = probe(auth, a)
        a["last_check"], a["last_ok"], a["last_msg"], a["items"] = now(), ok, msg, n
        merged = dict(a.get("plain") or {})
        merged.update(secret_of(a) if a.get("secret") else {})
        ident = fill_identity(db, a, merged)
        print("%-12s %s  ID %-12s 账号名 %-14s %s"
              % (a["alias"], "有效" if ok else "失效", a.get("uid") or "-",
                 a.get("nickname") or "-", (ident.get("msg") or "")[:50]))
        bad += 0 if ok else 1
    save_db(db)
    return 1 if bad else 0


def cmd_keepalive(args):
    r = keepalive(hours=args.hours, force=args.force, prepare_qr=args.prepare_qr,
                  alias=(args.alias or "").strip() or None)
    if r.get("skipped"):
        print("保活跳过：%s" % (r.get("msg") or r["skipped"]))
        print("（计划任务里这属正常：设了 OPENLIST_ADMIN_PASSWORD 才会真探；本轮不写报告）")
        return 0
    print("保活 %d 个（节流跳过 %d）：有效 %d / 预警 %d / 失效 %d"
          % (r["checked"], r["skipped_throttle"], r["ok_n"], r["warn_n"], r["dead_n"]))
    for a in r["accounts"]:
        if a.get("state") in ("warn", "dead"):
            print("  %-12s %-5s %s" % (a.get("alias"), a.get("state"), (a.get("last_msg") or "")[:60]))
    if r["needs_relogin"]:
        print("待重登：%s（跑 `keepalive --prepare-qr` 或在看板点『扫码登录』预开窗口，扫一次即可）"
              % "、".join(r["needs_relogin"]))
    if r.get("refresh_failed"):
        print("cookie 未续期：%s（夸克下载态 ≈18h，不重扫一次建 profile 就续不了）"
              % "、".join(r["refresh_failed"]))
    for pq in r.get("prepared_qr", []):
        print("  预备扫码 %s：%s %s" % (pq["driver"], "OK" if pq["ok"] else "没开成", pq["msg"]))
    print("报告：%s" % (r.get("report_path") or r.get("report_err", "")))
    return 0


def cmd_use(args):
    db = load_db()
    a = get_acct(db, args.alias)
    if not a:
        print("没有这个账号")
        return 1
    use_only(db, _auth(), a)
    ok, msg, n = probe(_auth(), a)
    a["last_check"], a["last_ok"], a["last_msg"] = now(), ok, msg
    save_db(db)
    print("%s 现在是 %s 的活跃号：%s" % (a["alias"], DISKS.get(a["driver"], a["driver"]), msg))
    return 0 if ok else 1


def cmd_orphans(args):
    """列/删「OpenList 里有挂载点、账号库里没有对应账号」的孤儿（删号失败或手工建过会留下）。
    默认只列不删，删必须点名 --drop。"""
    db = load_db()
    auth = _auth()
    owned = {a["mount_path"] for a in db["accounts"]}
    r = auth.get("/api/admin/storage/list?page=1&per_page=200")
    items = (r.get("data") or {}).get("content") or []
    orphans = [s for s in items if s.get("mount_path") not in owned]
    if not orphans:
        print("没有孤儿挂载点（共 %d 个挂载点，全部对得上账号库）" % len(items))
        return 0
    for s in orphans:
        print("孤儿：%s  驱动 %s  id=%s  状态 %s"
              % (s.get("mount_path"), s.get("driver"), s.get("id"), s.get("status")))
    if args.drop:
        gone, msg = drop_storage(auth, args.drop)
        print("%s：%s" % (args.drop, msg if msg else ("删掉了" if gone else "没删掉")))
        return 0 if gone else 1
    print("要删就点名：py -3 _工具脚本/网盘账号台.py orphans --drop /某挂载点")
    return 0


def cmd_selftest(args):
    """不碰真凭据、不写账号库。原来它验的是「渲染出来的页面里没有明文」，
    现在界面在看板那边，改成验**接口这一层**：字段表来自跑着的 OpenList、四条错路都回话不炸、
    任何返回值里都不许出现凭据值、自检一条都不写进库。"""
    fails = []
    demo = "test-not-a-real-cookie-value"
    b = dpapi_protect(demo)
    if dpapi_unprotect(b) != demo:
        fails.append("DPAPI 往返不一致")
    if b == demo or demo in b:
        fails.append("DPAPI 密文里仍能看到明文")
    if not ALIAS_RE.match("quark-03") or ALIAS_RE.match("夸克 三号") or ALIAS_RE.match("a"):
        fails.append("别名规则判错")

    # 自动起名 / 身份解析：这几个是纯函数（不联网、不写库），能在这里钉死
    if cookie_kv("a=1; b-user-id=42 ; c=") != {"a": "1", "b-user-id": "42", "c": ""}:
        fails.append("cookie_kv 解析不对：%s" % cookie_kv("a=1; b-user-id=42 ; c="))
    db0 = {"accounts": [{"alias": "quark-deadbeef"}]}
    a1 = auto_alias("Quark", "10000000deadbeef", db0)
    if not ALIAS_RE.match(a1):
        fails.append("自动起出来的名字过不了别名规则：%s" % a1)
    if a1 == "quark-deadbeef":
        fails.append("库里同名时自动起名没往后加序号：%s" % a1)
    if not auto_alias("Quark", "10000000deadbeef", {"accounts": []}).endswith("deadbeef"):
        fails.append("自动起名没拿 uid 尾巴当名字：%s" % auto_alias("Quark", "10000000deadbeef", {"accounts": []}))
    if auto_alias("Quark", "中文昵称", db0) == "quark-deadbeef":
        fails.append("没 uid 时该退化成 cookie 指纹，不该撞名")
    if identity_of("Quark", {}).get("ok"):
        fails.append("没给 cookie 却判成已登录")
    if identity_of("Thunder", {"username": "abc"}).get("ok") is not True:
        fails.append("迅雷填了 username 该给账号名（这条不联网）")
    # 保活状态机（纯函数 _ka_mark，不联网不写库）：一次败预警、两次连败判死待重登、复活清零
    ka = {"alias": "quark-x", "driver": "Quark"}
    _ka_mark(ka, True, "列到 3 项", 3, 1000.0)
    if ka.get("state") != "ok" or ka.get("fail_n") != 0 or ka.get("needs_relogin"):
        fails.append("保活：探测成功该 state=ok/fail_n=0/不需重登")
    if not ka.get("last_ok_at"):
        fails.append("保活：成功该记 last_ok_at")
    _ka_mark(ka, False, "401", -1, 2000.0)
    if ka.get("state") != "warn" or ka.get("needs_relogin"):
        fails.append("保活：一次失败该预警(warn)但不判死（防网络抖动误杀）")
    _ka_mark(ka, False, "401", -1, 3000.0)
    if ka.get("state") != "dead" or not ka.get("needs_relogin"):
        fails.append("保活：两次连败该判死(dead)且待重登")
    _ka_mark(ka, True, "列到 3 项", 3, 4000.0)
    if ka.get("state") != "ok" or ka.get("fail_n") != 0 or ka.get("needs_relogin"):
        fails.append("保活：重登成功后该复活 ok、fail_n 清零、取消待重登")
    # 存储级设置保留（纯函数 _carry_storage_opts）：11-10 重扫把 web_proxy 冲 False、下载 412，钉死
    ex = {"id": 10, "modified": "x", "status": "work", "mount_path": "/old", "order": 9,
          "remark": "旧", "disabled": False, "driver": "Quark", "cache_expiration": 1,
          "addition": "{\"cookie\":\"旧值\"}", "web_proxy": True, "down_proxy_url": "",
          "proxy_range": True, "extract_folder": "front", "webdav_policy": "native_proxy"}
    body = _carry_storage_opts(ex, {"mount_path": "/new", "order": 0, "remark": "新",
                                    "enabled": True, "driver": "Quark", "cache_expiration": 30,
                                    "addition": "{\"cookie\":\"新值\"}"})
    if body.get("web_proxy") is not True or body.get("proxy_range") is not True:
        fails.append("回写挂载点把 web_proxy/proxy_range 冲掉了（夸克下载会 412）")
    if body.get("extract_folder") != "front" or body.get("webdav_policy") != "native_proxy":
        fails.append("回写挂载点把 extract_folder/webdav_policy 冲掉了")
    if body.get("mount_path") != "/new" or body.get("cache_expiration") != 30 or "旧值" in body.get("addition", ""):
        fails.append("回写挂载点该覆盖的字段没覆盖（mount_path/cache_expiration/addition）")
    if "id" in body or "status" in body or "modified" in body or "disabled" in body:
        fails.append("回写挂载点把只读/反向字段（id/status/modified/disabled）发回去了")
    if _carry_storage_opts(None, {"driver": "Quark"}) != {"driver": "Quark"}:
        fails.append("新建挂载点（无旧行）该只用 body 本身")
    # __puus 新鲜度（纯函数 _puus_fresh）：TTL≈18h，>17h 才算这次访问真滚到了新 cookie
    now = 1000000.0
    if not _puus_fresh([{"name": "__puus", "expires": now + 18 * 3600}], now):
        fails.append("__puus 刚滚新（18h）该判新鲜")
    if _puus_fresh([{"name": "__puus", "expires": now + 3600}], now):
        fails.append("__puus 只剩 1h（旧快照）该判不新鲜")
    if _puus_fresh([{"name": "__pus", "expires": now + 9 * 86400}], now):
        fails.append("只有 __pus 没有 __puus 该判不新鲜（列目录绿≠下载态活）")
    if _puus_fresh([], now) or _puus_fresh(None, now):
        fails.append("空 cookie 该判不新鲜")
    if _puus_fresh([{"name": "__puus", "expires": "不是数字"}], now):
        fails.append("expires 不是数字该判不新鲜而不是炸")
    if safe_rec(ka).get("state") != "ok" or "needs_relogin" not in safe_rec(ka):
        fails.append("保活：state/needs_relogin 该能上界面（在 SAFE_KEYS 里）")
    # 预备扫码复用：已有活登录窗就复用、别每天给同一失效盘堆窗（monkeypatch 掉真探端口，纯离线）
    if qr:
        _ss, _ls = _slot_state, _live_slots
        try:
            globals()["_slot_state"] = lambda d: {1: {"listening": True, "page_ok": True},
                                                  2: {"listening": False}}
            globals()["_live_slots"] = lambda d, db: set()
            if _prepared_window("Quark", {"accounts": []}) != 1:
                fails.append("预备扫码：第1槽有活登录窗该复用回1（不重开堆窗）")
            globals()["_live_slots"] = lambda d, db: {1}
            if _prepared_window("Quark", {"accounts": []}) != 0:
                fails.append("预备扫码：活窗属于活号时不算预备窗（该回0）")
            globals()["_slot_state"] = lambda d: {1: {"listening": True, "page_ok": False}}
            globals()["_live_slots"] = lambda d, db: set()
            if _prepared_window("Quark", {"accounts": []}) != 0:
                fails.append("预备扫码：窗口被导航走(page_ok=False)不算预备窗")
        finally:
            globals()["_slot_state"], globals()["_live_slots"] = _ss, _ls
    if do_action("qr", {"phase": "nope", "driver": "Quark"}).get("ok"):
        fails.append("不认识的扫码阶段本该失败")
    if do_action("qr", {"phase": "poll", "driver": "NoSuchDisk"}).get("ok"):
        fails.append("不认识的盘扫码本该失败")
    # addition 的类型闸门：bool 给字符串会把挂载点 init 炸掉（11-05 真撞过）
    if coerce("Quark", "use_transcoding_address", "false") is not False:
        fails.append("bool 字段没被转成真布尔：%r" % coerce("Quark", "use_transcoding_address", "false"))
    if coerce("Quark", "only_list_video_file", "true") is not True:
        fails.append("bool 字段 true 没转成真布尔")
    if coerce("Quark", "root_folder_id", "0") != "0":
        fails.append("string 字段被乱改了：%r" % coerce("Quark", "root_folder_id", "0"))

    sch = form_schema("Quark")
    names = []
    if not sch.get("ok"):
        fails.append("问 OpenList 要夸克字段表就失败了（OpenList 得先在听）：%s" % sch.get("msg"))
    else:
        names = [f["name"] for f in sch["fields"]]
        if not any(f["secret"] for f in sch["fields"]):
            fails.append("夸克字段表里没有一个按密文处理的字段（cookie 该走 secret）：%s" % names)
        if all(f["required"] for f in sch["fields"]):
            fails.append("字段表全是必填，不像真的：%s" % names)
        if sch.get("login_kind") != "qrcode":
            fails.append("夸克该标成扫码盘，实际 login_kind=%s" % sch.get("login_kind"))
        if not sch.get("login_howto"):
            fails.append("夸克没回登录说明，界面没法教用户往哪扫")
    if form_schema("NoSuchDisk")["ok"]:
        fails.append("不认识的盘本该报错")

    # 登录位（槽位）这套算术：一个 profile 一个号，换号扫是换格，不是顶掉上一个
    if qr:
        if [qr.port_of("Quark", n) for n in (1, 2, 10)] != [9331, 9341, 9421]:
            fails.append("夸克槽位端口算错：%s" % [qr.port_of("Quark", n) for n in (1, 2, 10)])
        if qr.port_of("BaiduNetdisk", 3) != 9352 or qr.port_of("Thunder", 3) != 9353:
            fails.append("百度/迅雷的槽位端口没按「基址 +（槽-1)×10」走")
        if os.path.basename(qr.profile_of("Quark", 1)) != "profile-Quark":
            fails.append("第 1 槽的 profile 名字动了，老账号那套登录态会找不到：%s"
                         % os.path.basename(qr.profile_of("Quark", 1)))
        if os.path.basename(qr.profile_of("Quark", 2)) != "profile-Quark-02":
            fails.append("第 2 槽该开新 profile，实际是 %s" % os.path.basename(qr.profile_of("Quark", 2)))
        got = [qr._slot(x) for x in ("0", "-3", "", "x", None, "999", 7)]
        if got != [1, 1, 1, 1, 1, qr.MAX_SLOTS, 7]:
            fails.append("slot 没夹在 1~%d 里：%s" % (qr.MAX_SLOTS, got))
        if qr.MAX_SLOTS < 15:
            fails.append("登录位只要了 %d 格，用户要的是每盘 15~20 格" % qr.MAX_SLOTS)
        if _next_slot("Quark", {"accounts": [{"driver": "Quark", "slot": 1},
                                             {"driver": "Quark"},
                                             {"driver": "Thunder", "slot": 2}]}) != 2:
            fails.append("下一个空登录位算错（第 1 槽被占、没标 slot 的老记录按第 1 槽算）")
        if _next_slot("Quark", {"accounts": [{"driver": "Quark", "slot": n}
                                            for n in range(1, qr.MAX_SLOTS + 1)]}) != 0:
            fails.append("空位用光了还让开新槽")
        if _next_slot("Quark", {"accounts": [{"driver": "Quark", "slot": 1},
                                             {"driver": "Quark", "slot": 2},
                                             {"driver": "Quark", "slot": 3},
                                             {"driver": "Quark", "slot": 5}]}) != 4:
            fails.append("4 个号占了 1/2/3/5，下一格该是第 4 槽")
        if sch.get("ok") and not sch.get("qr_slots"):
            fails.append("字段表没带出登录位表，界面出不了『登录位』下拉")
        if sch.get("ok") and len(sch.get("qr_slots") or []) != qr.MAX_SLOTS:
            fails.append("登录位表不是 %d 格：%s" % (qr.MAX_SLOTS, len(sch.get("qr_slots") or [])))
        if sch.get("ok") and not sch.get("qr_browsers", {}).get("ok"):
            fails.append("字段表没带出可用浏览器，界面出不了『用哪个浏览器』下拉")
        if safe_rec({"alias": "x", "driver": "Quark"}).get("slot") != 1:
            fails.append("老记录没 slot 栏时该当第 1 槽")

    checks = [
        ("nope", {}, "不认识的动作"),
        ("check", {"alias": "根本没有的这个号"}, "没有这个账号"),
        ("use", {"alias": "根本没有的这个号"}, ""),
        ("del", {"alias": "根本没有的这个号"}, ""),
        ("save", {"alias": "中文 别名", "driver": "Quark", "fields": {"cookie": demo}}, ""),
        ("save", {"alias": "ui-selftest-01", "driver": "Quark", "fields": {}}, ""),
    ]
    blob = []
    for kind, payload, want in checks:
        r = do_action(kind, payload)
        if r["ok"]:
            fails.append("%s(%s) 本该失败却报成功：%s" % (kind, payload.get("alias") or "-", r["msg"]))
        if want and want not in r["msg"]:
            fails.append("%s 的答复里没有「%s」，实际是：%s" % (kind, want, r["msg"]))
        blob.append(json.dumps(r, ensure_ascii=False))
    # 空 fields 那条走的是「一格都没填」，压根不该碰 OpenList，也不该落库
    if demo in "\n".join(blob):
        fails.append("接口返回值里漏出了凭据明文")

    db = load_db()
    if get_acct(db, "ui-selftest-01"):
        fails.append("自检把账号写进库了")
    print("字段表 Quark：%s" % (names or "（OpenList 没在听，取不到）"))
    print("错路 %d 条全部回话、没炸线程；账号库现有 %d 条（本测试一条没写）"
          % (len(checks), len(db["accounts"])))
    if fails:
        for f in fails:
            print("毛病：%s" % f)
        return 1
    print("自检通过：DPAPI 往返 / 别名规则 / 字段表来自 OpenList / 接口不回凭据值且不写库")
    return 0


def main():
    p = argparse.ArgumentParser(description="三个网盘、多个账号的凭据保管与切换（配本机 OpenList）")
    sp = p.add_subparsers(dest="cmd")
    a = sp.add_parser("list", help="列账号（不显示凭据值）")
    a.set_defaults(fn=cmd_list)
    a = sp.add_parser("add", help="命令行加账号；值走环境变量，别直接敲在命令里")
    a.add_argument("--driver", required=True)
    a.add_argument("--alias", required=True)
    a.add_argument("--remark", default="")
    a.add_argument("--value-env", default="", help="存 JSON 的环境变量名")
    a.set_defaults(fn=cmd_add)
    a = sp.add_parser("check", help="探一条或全部，看凭据还有效吗")
    a.add_argument("alias", nargs="?", default="all")
    a.set_defaults(fn=cmd_check)
    a = sp.add_parser("use", help="把同盘的活跃号切过去")
    a.add_argument("alias")
    a.set_defaults(fn=cmd_use)
    a = sp.add_parser("orphans", help="列/删账号库里没有对应账号的挂载点")
    a.add_argument("--drop", default="", help="点名要删掉的那个挂载路径")
    a.set_defaults(fn=cmd_orphans)
    a = sp.add_parser("qr", help="扫码登录：开窗口 / 问扫上没 / 关窗口 / 清 profile（--slot 选登录位）")
    a.add_argument("phase", nargs="?", default="poll", choices=["start", "poll", "close", "purge"])
    a.add_argument("--driver", default="Quark")
    a.add_argument("--slot", default="1", help="登录位第几格：一格一个独立 profile，换号扫就换格，不顶掉上一个号")
    a.add_argument("--exe", default="", help="用哪个浏览器开这个窗口（默认本机第一个能用的）")
    a.add_argument("--auto-new", action="store_true",
                   help="这一格已登着号就自动换到干净的空登录位（登新号用；要重扫老号就别加）")
    a.set_defaults(fn=cmd_qr)
    a = sp.add_parser("selftest", help="不写库的自检")
    a.set_defaults(fn=cmd_selftest)
    a = sp.add_parser("keepalive", help="定时保活：轻量探测续命+到期预警+可选预备扫码（计划任务用）")
    a.add_argument("--hours", type=float, default=6, help="节流：距上次探测不足这么多小时就跳过（--force 无视）")
    a.add_argument("--force", action="store_true", help="无视听节流，现在就探")
    a.add_argument("--prepare-qr", action="store_true", help="为失效盘预开扫码窗口（重登只需扫一次）")
    a.add_argument("--alias", default="", help="只保活这一个号（默认全部）")
    a.set_defaults(fn=cmd_keepalive)
    args = p.parse_args()
    if not getattr(args, "cmd", None):
        p.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
