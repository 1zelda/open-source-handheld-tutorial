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
import urllib.error
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


def fields_of(driver):
    """从跑着的 OpenList 现取该驱动的字段表，不写死字段名。"""
    a = nd.Auth()
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


def register(auth, acct, remark=None):
    """把这条账号写成 OpenList 挂载点：没有就 create，有就 update。
    OpenList 对『凭据不对』的处理是照样建行、把它标成 work=failed 并回一条错误，
    所以这里不看 code 当结论，一律回查挂载点在不在，再决定怎么报。"""
    add = build_addition(acct)
    body = {"mount_path": acct["mount_path"], "order": acct.get("order", 0),
            "remark": remark if remark is not None else (acct.get("remark") or acct["alias"]),
            "enabled": bool(acct.get("active", True)), "driver": acct["driver"],
            "cache_expiration": 30, "addition": json.dumps(add, ensure_ascii=False)}
    ex = find_storage(auth, acct["mount_path"])
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
             "uid", "nickname", "member", "ident_msg", "ident_at", "slot")


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


def _next_slot(driver, db):
    """这个盘下一个没人占的登录位；十格都占了回 0（调用方据此说「满了」）。"""
    if not qr:
        return 0
    used = {int(a.get("slot") or 1) for a in db["accounts"] if a.get("driver") == driver}
    for n in range(1, qr.MAX_SLOTS + 1):
        if n not in used:
            return n
    return 0


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
        r = qr.start(driver, slot, str(p.get("exe") or ""))
        return bool(r.get("ok")), r.get("msg", ""), _qr_state(driver, slot, {"phase": "start"})
    if phase == "close":
        r = qr.close(driver, slot)
        return bool(r.get("ok")), r.get("msg", ""), _qr_state(driver, slot, {"phase": "close"})
    if phase == "purge":
        r = qr.purge(driver, slot)
        return bool(r.get("ok")), r.get("msg", ""), _qr_state(driver, slot, {"phase": "purge"})
    if phase != "poll":
        return False, "不认识的扫码阶段 %s" % phase, None

    st = _qr_state(driver, slot)
    if not st.get("listening"):
        return False, st.get("msg") or "第 %d 槽的登录窗口没开着（先点『打开扫码窗口』）" % slot, st
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
        prev = int(same.get("slot") or 1)
        try:
            stored = (secret_of(same) or {}).get(target) or ""
        except Exception:
            stored = ""                        # 解不开（换机器/库坏了）就往下走覆盖那条路
        if prev == slot and stored == ck:      # 这一槽登着的就是它，库里那份一字不差
            return False, ("第 %d 槽登着的就是「%s」（%s）——和库里存的 cookie 一模一样，不用重扫，窗口给你留着。"
                           "要加另一个号：把上面『登录位』调到%s再点『打开扫码窗口』，"
                           "那是另一个独立 profile，不会顶掉这个号。"
                           % (slot, same.get("nickname") or same["alias"], same["alias"],
                              ("第 %d 槽 " % nxt) if nxt else "（十格已占满，先删一个号）")), \
                dict(st, already=True, alias=same["alias"], next_slot=nxt)
        sec = secret_of(same) if same.get("secret") else {}
        sec.update({k: v for k, v in fields.items() if SECRET_RE.search(k)})
        store_secret(same, sec)
        for k, v in fields.items():
            if not SECRET_RE.search(k) and v:
                same.setdefault("plain", {})[k] = v
        same["slot"] = slot
        fill_identity(db, same, fields)
        ok, msg = activate(db, auth, same)
        qr.close(driver, slot)
        where = "" if prev == slot else "（原来登在第 %d 槽，现在改记第 %d 槽）" % (prev, slot)
        return ok, "同一个账号重扫好了：%s（%s凭据已更新，第 %d 槽的窗口关掉）—— %s" % (
            same["alias"], where, slot, msg), safe_rec(same)
    alias = auto_alias(driver, seed, db)
    remark = ("%s %s" % (DISKS[driver], ident.get("nickname") or "")).strip()[:60]
    add_account(driver, alias, fields, remark=remark)
    db = load_db()
    acct = get_acct(db, alias)
    acct["slot"] = slot
    fill_identity(db, acct, fields)
    ok, msg = activate(db, auth, acct)
    qr.close(driver, slot)
    return ok, ("扫码登录成功：自动起名 %s（ID %s，账号名 %s，登在第 %d 槽）—— %s；"
                "窗口已关，这一槽的 profile 留着，下次点开还是这个号"
                % (alias, acct.get("uid") or "网盘没给", acct.get("nickname") or "网盘没给", slot, msg))[:400], \
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


ACTIONS = {"save": _act_save, "check": _act_check, "use": _act_use, "del": _act_del, "qr": _act_qr}
# 扫码这四个阶段里，只有「真的扫上了要入库」才需要 OpenList 管理员口令；
# 开窗口/看进度/关窗口/清 profile 跟 OpenList 无关，所以口令没设也能用。
NO_AUTH_NEEDED = ("qr",)


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
    auth = nd.Auth()
    if not auth.token():
        if kind not in NO_AUTH_NEEDED:
            return out(False, "登不上 OpenList：环境变量 OPENLIST_ADMIN_PASSWORD 没设或不对（值不进日志、不进库）")
        auth = None                        # 扫码的开窗口/看进度/关窗口跟 OpenList 无关，口令没设也能用
    try:
        ok, msg, rec = fn(p, auth)
    except SystemExit as e:                       # 命令行那套「错就 SystemExit」在这里接住
        ok, msg, rec = False, str(e)[:300], None
    except Exception as e:
        ok, msg, rec = False, "%s: %s" % (type(e).__name__, str(e)[:260]), None
    res = out(ok, msg, rec)
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
                         "slot": args.slot, "exe": args.exe})
    keep = ("listening", "port", "url", "login_url", "cookie_count", "cookie_names",
            "names", "markers", "markers_have", "login_ok", "phase", "howto", "msg",
            "slot", "max_slot", "profile", "already", "next_slot")
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
    ok, msg = activate(db, nd.Auth(), acct)
    print("%s 加好：%s（%s）ID %s 账号名 %s"
          % (args.alias, "有效" if ok else "已存但探测没过", msg,
             acct.get("uid") or "没认出", acct.get("nickname") or "没认出"))
    return 0 if ok else 1


def cmd_check(args):
    db = load_db()
    auth = nd.Auth()
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


def cmd_use(args):
    db = load_db()
    a = get_acct(db, args.alias)
    if not a:
        print("没有这个账号")
        return 1
    use_only(db, nd.Auth(), a)
    ok, msg, n = probe(nd.Auth(), a)
    a["last_check"], a["last_ok"], a["last_msg"] = now(), ok, msg
    save_db(db)
    print("%s 现在是 %s 的活跃号：%s" % (a["alias"], DISKS.get(a["driver"], a["driver"]), msg))
    return 0 if ok else 1


def cmd_orphans(args):
    """列/删「OpenList 里有挂载点、账号库里没有对应账号」的孤儿（删号失败或手工建过会留下）。
    默认只列不删，删必须点名 --drop。"""
    db = load_db()
    auth = nd.Auth()
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
        got = [qr._slot(x) for x in ("0", "-3", "", "x", None, "99", 7)]
        if got != [1, 1, 1, 1, 1, 10, 7]:
            fails.append("slot 没夹在 1~10 里：%s" % got)
        if _next_slot("Quark", {"accounts": [{"driver": "Quark", "slot": 1},
                                             {"driver": "Quark"},
                                             {"driver": "Thunder", "slot": 2}]}) != 2:
            fails.append("下一个空登录位算错（第 1 槽被占、没标 slot 的老记录按第 1 槽算）")
        if _next_slot("Quark", {"accounts": [{"driver": "Quark", "slot": n} for n in range(1, 11)]}) != 0:
            fails.append("十格占满了还让开新槽")
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
    a.set_defaults(fn=cmd_qr)
    a = sp.add_parser("selftest", help="不写库的自检")
    a.set_defaults(fn=cmd_selftest)
    args = p.parse_args()
    if not getattr(args, "cmd", None):
        p.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
