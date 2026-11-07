# -*- coding: utf-8 -*-
"""自测_看板.py —— 把看板 /api/* 返回的条数,和台账文件/工厂 SQLite 自己数出来的行数对起来。

期望值不写死:每张表现读现数(csv/json 独立解析,工厂表独立 SELECT COUNT),所以台账涨行也不会假红。
跑法:先起看板(py -3 08-数据看板/看板.py),再 py -3 08-数据看板/自测_看板.py
"""
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASE = "http://127.0.0.1:" + (sys.argv[1] if len(sys.argv) > 1 else "8090")

NEWS = "06-资讯监控/台账.tsv"
SOURCES = "06-资讯监控/源登记表.tsv"
CATALOG = "06-资讯监控/PS5移植商店/catalog.json"

# 看板数据集 -> 期望行数的独立算法(TSV 数数据行,PS5 数 catalog 里那几个桶)
GAME_TSV = {
    "pm_r36s": "04-游戏资源库/公版与开源游戏/portmaster_r36s_全清单.tsv",
    "pm_pool": "04-游戏资源库/公版与开源游戏/ports全量合法池/_manifest.tsv",
    "pm_watch": "06-资讯监控/PortMaster端口快照.tsv",
    "hot": "04-游戏资源库/爆款收录/收录台账.tsv",
    "rescue": "04-游戏资源库/下架抢救/收录台账.tsv",
    "assets": "04-游戏资源库/公版与开源游戏/免费素材/免费素材台账.tsv",
    "major": "06-资讯监控/移植大作/移植大作台账.tsv",
}
REPO_TSV = {
    "legal": "06-资讯监控/合法收录登记表.tsv",
    "s2repo": "06-资讯监控/Switch2模拟器/仓库登记表.tsv",
    "s2fetch": "06-资讯监控/Switch2模拟器/抓取台账.tsv",
    "s2bundle": "06-资讯监控/Switch2模拟器/bundle台账.tsv",
    "ps5repo": "06-资讯监控/PS5移植商店/仓库底账.tsv",
    "ps5asset": "06-资讯监控/PS5移植商店/获取台账.tsv",
    "rescue_reg": "06-资讯监控/下架抢救登记表.tsv",
}
PS5_BUCKETS = ("apps", "newerStoreApps", "v2Apps", "comingSoon", "comingSoonV2")

fails = []


def get(path_, **params):
    url = BASE + path_
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path_, obj):
    """看板的唯一写入口。这里只发「不认识的动作」这类必定不落盘的请求,不碰真凭据。"""
    req = urllib.request.Request(BASE + path_, data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads((e.read().decode("utf-8") or "{}"))


def get_raw(path_, **params):
    """给 /api/netdisk/shot 那条用:它回的是二进制,不能当 JSON 解。
    返回 (状态码, Content-Type, 前 8 字节)。"""
    url = BASE + path_
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(8)
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read(8)


def check(label, got, want):
    ok = got == want
    print("%-40s %-6s got=%s want=%s" % (label, "PASS" if ok else "FAIL", got, want))
    if not ok:
        fails.append(label)
    return ok


def note(label, val=""):
    print("%-40s %s" % (label, val))


def tsv_data_rows(rel):
    """台账真实数据行数:表头之外、至少一个单元格非空。"""
    with open(os.path.join(ROOT, rel), encoding="utf-8-sig", newline="") as f:
        rd = list(csv.reader(f, delimiter="\t"))
    return [r for r in rd[1:] if any(c.strip() for c in r)]


def tsv_dicts(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


# ---------------------------------------------------------------- 资讯
news_file = tsv_dicts(NEWS)
ov = get("/api/overview")
check("overview 资讯总数", ov["news"]["total"], len(news_file))
check("overview HOT", ov["news"]["hot"], sum(1 for r in news_file if (r.get("flag_hot") or "").strip()))
check("overview 大作登陆", ov["news"]["arrival"], sum(1 for r in news_file if (r.get("flag_arrival") or "").strip()))
check("overview 源登记", ov["sources"]["total"], len(tsv_data_rows(SOURCES)))

n = get("/api/news", limit=5)
check("news 全量", n["total"], len(news_file))
check("news flag=hot", get("/api/news", flag="hot", limit=1)["total"],
      sum(1 for r in news_file if (r.get("flag_hot") or "").strip()))
check("news flag=arrival", get("/api/news", flag="arrival", limit=1)["total"],
      sum(1 for r in news_file if (r.get("flag_arrival") or "").strip()))
check("news flag=focus", get("/api/news", flag="focus", limit=1)["total"],
      sum(1 for r in news_file if (r.get("flag_focus") or "").strip()))
for kind in sorted({(r.get("kind") or "-") for r in news_file}):
    if kind == "-":
        continue
    want = sum(1 for r in news_file if (r.get("kind") or "-") == kind)
    check("news kind=%s" % kind, get("/api/news", kind=kind, limit=1)["total"], want)
src_id = news_file[0]["source_id"]
check("news source=%s" % src_id, get("/api/news", source=src_id, limit=1)["total"],
      sum(1 for r in news_file if r.get("source_id") == src_id))
note("news q=PortMaster", get("/api/news", q="PortMaster", limit=1)["total"])
hits = get("/api/news", q="PortMaster", limit=50)["rows"]
note("news 关键词命中数", len(hits))
check("news 命中的行文本里真含关键词",
      sum(1 for r in hits if "portmaster" not in
          (r["title"] + " " + r["url"] + " " + r["note"] + " " + r["focus"]).lower()), 0)
tail = get("/api/news", offset=n["total"] - 3, limit=200)
check("news 翻页到尾", tail["offset"] + len(tail["rows"]), n["total"])
check("news limit 有上限保护", get("/api/news", limit=99999)["limit"], 1000)

# ---------------------------------------------------------------- 游戏
gf = get("/api/games_facets")
gds = {x["ds"]: x for x in gf["ds"]}
want_games = 0
for k, rel in GAME_TSV.items():
    want = len(tsv_data_rows(rel))
    want_games += want
    check("游戏 ds=%s" % k, gds.get(k, {}).get("count"), want)
cat = json.load(open(os.path.join(ROOT, CATALOG), encoding="utf-8"))
want_ps5 = sum(len(cat.get(b) or []) for b in PS5_BUCKETS)
want_games += want_ps5
check("游戏 ds=ps5", gds.get("ps5", {}).get("count"), want_ps5)
check("游戏 合计", gf["total"], want_games)
note("游戏 各 ds 体积合计(MB)", round(sum(x["bytes"] for x in gf["ds"]) / 1048576.0, 1))
for k in ("pm_pool", "hot", "rescue", "assets", "ps5"):
    note("游戏 %s 本地在=%s 缺=%s" % (k, gds[k]["local"], gds[k]["missing"]), "")

# ---------------------------------------------------------------- 库
rf = get("/api/repos_facets")
rds = {x["ds"]: x for x in rf["ds"]}
want_repos = 0
for k, rel in REPO_TSV.items():
    want = len(tsv_data_rows(rel))
    want_repos += want
    check("库 ds=%s" % k, rds.get(k, {}).get("count"), want)
inv = open(os.path.join(ROOT, "02-模拟器库/已clone仓库/README_inventory.md"), encoding="utf-8").read()
body = inv.split("## 汇总")[0]
# 独立算法:每个分类小节的表 = 表头行 + 分隔行 + N 条数据行;拿竖线总数减去 2×小节数
sections = sum(1 for ln in body.splitlines() if ln.startswith("## "))
pipe_lines = sum(1 for ln in body.splitlines() if ln.startswith("|"))
want_clone = pipe_lines - 2 * sections
want_repos += want_clone
check("库 ds=clone", rds.get("clone", {}).get("count"), want_clone)
check("库 合计", rf["total"], want_repos)


# ---------------------------------------------------------------- 工厂(SQLite 状态库)
FACTORY_DB = "07-移植工厂/state/factory.db"
# 看板 ds -> 库里的真表名(自己数 SQL,不信看板的数)
FACTORY_TABLE = {
    "pf_jobs": "jobs", "pf_games": "games", "pf_runs": "research_runs",
    "pf_modules": "research_modules", "pf_attempts": "research_attempts",
    "pf_gates": "gate_results", "pf_stages": "stages", "pf_artifacts": "artifacts",
    "pf_devices": "devices", "pf_events": "events",
}
# 哪张表拿哪一列当"本地产物路径"(与看板 base_row 的 local 同源)
FACTORY_PATH = {
    "pf_jobs": ("jobs", "workdir"), "pf_games": ("games", "root_path"),
    "pf_runs": ("research_runs", "workdir"), "pf_modules": ("research_modules", "module_path"),
    "pf_attempts": ("research_attempts", "request_path"), "pf_artifacts": ("artifacts", "path"),
}
FDB = os.path.join(ROOT, *FACTORY_DB.split("/"))
import hashlib
def _db_sha():
    return hashlib.sha256(open(FDB, "rb").read()).hexdigest() if os.path.isfile(FDB) else None
sha_before = _db_sha()
ff = get("/api/factory_facets")
fds = {x["ds"]: x for x in ff["ds"]}
if os.path.isfile(FDB):
    import sqlite3
    fcon = sqlite3.connect("file:" + FDB.replace("\\", "/") + "?mode=ro", uri=True)
    want_factory = 0
    for k, tbl in sorted(FACTORY_TABLE.items()):
        want = fcon.execute("SELECT COUNT(*) FROM %s" % tbl).fetchone()[0]
        want_factory += want
        check("工厂 ds=%s" % k, fds.get(k, {}).get("count"), want)
    check("工厂 合计", ff["total"], want_factory)
    # verified 在所有带 status 列的表里数,不只盯 research_modules
    want_verified = 0
    for tbl in sorted(set(FACTORY_TABLE.values())):
        cols = {c[1] for c in fcon.execute("PRAGMA table_info(%s)" % tbl)}
        if "status" in cols:
            want_verified += fcon.execute(
                "SELECT COUNT(*) FROM %s WHERE status='verified'" % tbl).fetchone()[0]
    check("工厂 status=verified 命中", get("/api/factory", status="verified", limit=1)["total"],
          want_verified)
    for k, (tbl, col) in sorted(FACTORY_PATH.items()):
        have = 0
        for (v,) in fcon.execute("SELECT %s FROM %s" % (col, tbl)):
            p = v or ""
            if p and os.path.exists(p if os.path.isabs(p) else os.path.join(ROOT, p)):
                have += 1
        check("工厂 %s 本地在" % k, fds.get(k, {}).get("local"), have)
        check("工厂 %s 缺文件=行数-在" % k, fds.get(k, {}).get("missing"), fds[k]["count"] - have)
    fcon.close()
    for fk in ("pf_gates", "pf_stages", "pf_devices", "pf_events"):
        check("工厂 %s 不判本地(库里没路径列)" % fk,
              (fds[fk]["local"], fds[fk]["missing"]), (0, 0))
    note("工厂 本地在 / 缺文件", "%s / %s" % (sum(x["local"] for x in ff["ds"]),
                                        sum(x["missing"] for x in ff["ds"])))
else:
    note("工厂 跳过断言(库里没这个文件)", FACTORY_DB)
if os.path.isfile(FDB):
    for _off in (0, 2000, 4000, 6000):        # 把 7,957 行全量翻一遍
        get("/api/factory", offset=_off, limit=2000)
    check("工厂 看板读过之后库字节没变", _db_sha(), sha_before)
    note("工厂 WAL 旁文件(只读连接也会生成,非看板写入)",
         [(f, os.path.getsize(FDB + f)) for f in ("-shm", "-wal") if os.path.exists(FDB + f)])
check("overview 工厂 总行", ov.get("factory", {}).get("total"), ff["total"])
check("overview 工厂 接单数", ov.get("factory", {}).get("jobs"), fds.get("pf_jobs", {}).get("count"))


def dump_all(kind, flag):
    """按 flag 翻到底,取全量行(服务端单次 limit 上限 2000)。"""
    rows, off = [], 0
    while True:
        d = get("/api/" + kind, flag=flag, offset=off, limit=2000)
        rows += d["rows"]
        if len(rows) >= d["total"]:
            return d["total"], rows
        off = len(rows)


for kind, fac in (("games", gf), ("repos", rf), ("factory", ff)):
    t_loc, locs = dump_all(kind, "local")
    t_mis, mis = dump_all(kind, "missing")
    check("%s flag=local = 各 ds 之和" % kind, t_loc, sum(x["local"] for x in fac["ds"]))
    check("%s flag=missing = 各 ds 之和" % kind, t_mis, sum(x["missing"] for x in fac["ds"]))
    check("%s 判在本地的行磁盘真有文件" % kind,
          sum(1 for r in locs if not os.path.exists(os.path.join(ROOT, r["local"]))), 0)
    check("%s 判缺文件的行磁盘真没有" % kind,
          sum(1 for r in mis if r["local"] and os.path.exists(os.path.join(ROOT, r["local"]))), 0)
    check("%s 缺文件的行也有名字" % kind, len([r for r in mis if not r["name"]]), 0)
    note("%s 本地在 / 台账有记录但缺文件" % kind, "%s / %s" % (t_loc, t_mis))
    t_brk, brks = dump_all(kind, "broken")
    note("%s 校验对不上" % kind, "%s 条: %s" % (t_brk, [r["name"][:24] for r in brks[:6]]))

# ---------------------------------------------------------------- 源
s = get("/api/sources")
check("源 全量", s["total"], len(tsv_data_rows(SOURCES)))
note("本轮 run", "%s 新入 %s 累计 %s 失败 %s" % (s["run_utc"], s["run_new"], s["ledger_total"], len(s["failures"])))

# ---------------------------------------------------------------- 报告
rep = get("/api/reports")
groups = {}
for x in rep:
    groups[x["group"]] = groups.get(x["group"], 0) + 1
note("报告 分组", groups)
check("报告 每条路径磁盘真有", sum(1 for x in rep if not os.path.isfile(os.path.join(ROOT, x["path"]))), 0)
check("报告 只列 md/txt", sum(1 for x in rep if not x["name"].lower().endswith((".md", ".txt"))), 0)
# 夹带的上游打包树(动手实践/*/package/、specs/licenses/)是别人的 LICENSE 与 readme,不该当本库文档列出来
check("报告 不含上游打包树",
      sum(1 for x in rep if {"package", "licenses"} & set(x["path"].split("/"))), 0)
# 独立数一遍磁盘:01-教程库 里该被列出的 md/txt 有多少(剪掉二进制/上游目录)
SKIP = {".git", "__pycache__", "上游wiki", "_sites", "_git", "已clone仓库", "成品包", "源码",
        "整仓bundle", ".venv", "venv", "_归档", "系统镜像", "node_modules", "package", "licenses"}
on_disk_tut = 0
for dp, dns, fns in os.walk(os.path.join(ROOT, "01-教程库")):
    dns[:] = [d for d in dns if d not in SKIP]
    on_disk_tut += sum(1 for fn in fns if fn.lower().endswith((".md", ".txt")))
check("报告 教程组 = 磁盘实数", groups.get("教程", 0), on_disk_tut)
for rel_group, folder in (("日报", "06-资讯监控/日报"), ("周报", "06-资讯监控/周报")):
    on_disk = [f for f in os.listdir(os.path.join(ROOT, folder)) if f.endswith(".md")]
    in_api = [x for x in rep if x["path"].startswith(folder + "/")]
    check("报告 %s 份数" % rel_group, len(in_api), len(on_disk))
check("报告 不含上游镜像/clone 仓库", len([x for x in rep if "上游wiki" in x["path"] or "已clone仓库" in x["path"]]), 0)
day = [x for x in rep if x["path"].startswith("06-资讯监控/日报")]
doc = get("/api/doc", **{"path": day[-1]["path"]})
check("报告 打开正文非空", bool(doc["content"].strip()), True)
check("报告 打开路径回显", doc["path"], day[-1]["path"])
code = None
try:
    get("/api/doc", path="../../../../Windows/win.ini")
except urllib.error.HTTPError as e:
    code = e.code
check("报告 越界路径被拒(404)", code, 404)

# ---------------------------------------------------------------- 网盘(唯一带写路径的页签)
ND_SCOPES_REL = "_工具脚本/网盘上传清单.tsv"
ND_LEDGER_REL = "06-资讯监控/网盘上传/网盘上传台账.tsv"
OL_DIR = os.environ.get("OPENLIST_DIR", r"F:\OpenList")
nd = get("/api/netdisk")


def _listening(port):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.4)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        s.close()


raw_db = {}
if os.path.isfile(os.path.join(OL_DIR, "账号库.json")):
    with open(os.path.join(OL_DIR, "账号库.json"), encoding="utf-8") as f:
        raw_db = json.load(f)
accts = raw_db.get("accounts") or []
check("网盘 OpenList 在听 = 独立探的 5244", nd["openlist"]["listening"], _listening(5244))
# 11-05:填 cookie 的表单从独立端口(5320)并进了看板这一页;旧页面必须真死掉,不然又是两张皮
check("网盘 旧登录页 5320 已拆掉(不再监听)", _listening(5320), False)
check("网盘 账号台模块读进来了", nd["account"]["loadable"], True)
check("网盘 账号台三件套接口齐(do_action/form_schema/list_safe)", nd["account"]["has_api"], True)
check("网盘 写侧门:绑回环 + 接口齐 才可写",
      nd["account"]["writable"], nd["bind"] in ("127.0.0.1", "::1") and nd["account"]["has_api"])
check("网盘 锁与理由同进退(没锁就不该有锁的话)",
      bool(nd["account"]["write_blocked"]), not nd["account"]["writable"])
check("网盘 明细来自账号台而不是看板自己投影",
      [a["alias"] for a in nd["accounts"]],
      [a.get("alias") for a in accts])
check("网盘 库里条数 = 文件实数(模块挂了也能点名)", nd["store"]["raw_total"], len(accts))
check("网盘 默认盘的字段表拿到且有格子",
      (nd["schema"]["ok"], len(nd["schema"]["fields"]) > 0), (True, True))
check("网盘 字段表只有 OpenList 那几个属性,不夹带值",
      sorted({k for f in nd["schema"]["fields"] for k in f}),
      ["default", "name", "required", "secret", "type"])
check("网盘 字段表里 secret 是布尔不是凭据",
      {type(f["secret"]).__name__ for f in nd["schema"]["fields"]}, {"bool"})
f_j = get("/api/netdisk_fields", driver="NoSuchDisk")
check("网盘 不认识的盘:拒绝而不是出空表",
      (f_j["ok"], f_j["fields"], "不认识的盘" in (f_j.get("msg") or "")), (False, [], True))
# 写入口的三道门:只有这一个路径收 POST / 未知动作被账号台接住 / 不异常挂死
p_code, p_j = post("/api/netdisk/action", {"action": "no-such-action"})
check("网盘 写入口:未知动作回 200 + ok=False(不抛异常)", (p_code, p_j.get("ok")), (200, False))
check("网盘 写入口:未知动作点名可选值", "不认识的动作" in (p_j.get("msg") or ""), True)
p_code, _ = post("/api/overview", {"action": "save"})
check("网盘 写入口:除这一个路径外一律不收 POST", p_code, 405)
check("网盘 账号数 = 账号库文件实数", nd["store"]["total"], len(accts))
check("网盘 各盘账号合计 = 账号数", sum(d["total"] for d in nd["by_driver"]), len(accts))
check("网盘 活跃数 = 文件里 active 为真", nd["store"]["active"], sum(1 for a in accts if a.get("active")))
check("网盘 探测有效 = 文件里 last_ok 为真", nd["store"]["ok"], sum(1 for a in accts if a.get("last_ok")))

# ---------------------------------------------------------------- 扫码这一条(11-05 新入口)
# 只走「必定被拒」的错路:phase=poll/start 会真去开浏览器、真会往库里写,自测绝不碰。
_static_html = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()
_static_js = open(os.path.join(HERE, "app.js"), encoding="utf-8").read()
check("网盘 界面有『打开扫码窗口』这个按钮", 'id="qrStart"' in _static_html, True)
check("网盘 接口交代扫码模块装没装成", ("qr_ready" in nd["account"], "qr_err" in nd["account"]), (True, True))
q_code, q_j = post("/api/netdisk/action", {"action": "qr", "driver": "Quark", "phase": "no-such-phase"})
check("网盘 扫码错阶段:回 200 + ok=False 且点名不认识",
      (q_code, q_j.get("ok"), "不认识的扫码阶段" in (q_j.get("msg") or "")), (200, False, True))
_, q_j2 = post("/api/netdisk/action", {"action": "qr", "driver": "NoSuchDisk"})
check("网盘 扫码不认识的盘:拒绝", (q_j2.get("ok"), "不认识的盘" in (q_j2.get("msg") or "")), (False, True))
check("网盘 扫码错路把画面接口分开放(不冒充账号)",
      ("qr" in q_j, q_j.get("account")), (True, None))
with open(os.path.join(OL_DIR, "账号库.json"), encoding="utf-8") as _f:
    check("网盘 上面这几枪扫码请求一个字没写进库",
          len((json.load(_f).get("accounts") or [])), len(accts))
s_code, s_type, s_head = get_raw("/api/netdisk/shot", driver="NoSuchDisk")
check("网盘 扫码画面:没窗口/不认识的盘 → 503 且是 JSON",
      (s_code, "json" in s_type), (503, True))
s_code2, s_type2, s_head2 = get_raw("/api/netdisk/shot", driver="Quark")
check("网盘 扫码画面:窗口开着就吐真 PNG,否则 503(不许 500/HTML)",
      (s_code2, s_type2 if s_code2 == 200 else "json" in s_type2,
       s_head2[:4] == b"\x89PNG" if s_code2 == 200 else True),
      (True, True, True) if s_code2 == 200 else (503, True, True))
note("网盘 现在:扫码窗口", "画面拿得到(有窗口在开)" if s_code2 == 200 else "没开着(按钮点了才开)")

# ---- 登录位(槽位):一个 profile 只有一个登录位,多账号靠多开槽位,后扫的不顶掉先扫的 ----
_sl = nd["schema"].get("qr_slots") or []
check("网盘 登录位表满格(格数=上限,上限不只一格)",
      (len(_sl) > 1, len(_sl) == nd["schema"]["qr_max_slot"]), (True, True))
check("网盘 每个登录位都交代端口/profile/在不在听/被哪个浏览器占着",
      sorted({k for s in _sl for k in s}),
      ["exe", "listening", "port", "profile", "profile_exists", "slot", "started_at"])
check("网盘 登录位编号从 1 排到底、端口两两不撞",
      ([s["slot"] for s in _sl], len({s["port"] for s in _sl})),
      (list(range(1, len(_sl) + 1)), len(_sl)))
# 端口和 profile 名不许看板/界面自己拼,必须是扫码模块那一份现给的
check("网盘 端口按槽位每格 +10、profile 名跟着槽位走",
      [s["slot"] for s in _sl
       if s["port"] != _sl[0]["port"] + (s["slot"] - 1) * 10
       or s["profile"] != ("profile-Quark" if s["slot"] == 1
                           else "profile-Quark-%02d" % s["slot"])],
      [])
_bt = nd["schema"].get("qr_browsers") or {}
check("网盘 浏览器分成「能拿来扫码」和「装了但抓不到 cookie」两堆",
      (bool(_bt.get("ok")),
       all(b["exe"] and b["version"] for b in _bt.get("ok") or []),
       all(x["why"] for x in _bt.get("unusable") or [])),
      (True, True, True))
check("网盘 账号明细点名这个号占的是第几槽",
      [a["alias"] for a in nd["accounts"] if not isinstance(a.get("slot"), int)], [])
# 乱填的登录位要被夹住,不许把接口弄成 500,也不许因为一个垃圾号就真去开浏览器
_codes = [get_raw("/api/netdisk/shot", driver="Quark", slot=v)[0]
          for v in ("999", "-3", "垃圾", "0")]
check("网盘 扫码画面:登录位乱填只会被夹回合法格(不出 500/502)",
      [c for c in _codes if c == 500], [])
_, q_j3 = post("/api/netdisk/action", {"action": "qr", "driver": "Quark",
                                       "phase": "no-such-phase", "slot": 7})
check("网盘 扫码带登录位也照旧被错阶段挡在门外(没顺手开窗口)",
      (q_j3.get("ok"), "不认识的扫码阶段" in (q_j3.get("msg") or "")), (False, True))
check("网盘 界面有「登录位」「用哪个浏览器」两个下拉",
      ('id="qrSlot"' in _static_html and 'id="qrExe"' in _static_html), True)
check("网盘 界面把槽位带进轮询和画面请求(不是只画个样子)",
      ("&slot=" in _static_js and "slot: nd.slot" in _static_js and
       "qrPaintSlots" in _static_js), True)
check("网盘 界面把「本来就登着」这格说出来(不再闷声关窗口)",
      ("j.qr.already" in _static_js and "这一槽本来就登着" in _static_js), True)
_nd_notes = json.dumps(nd["notes"], ensure_ascii=False)
check("网盘 交代了多账号靠多开登录位、彼此顶不掉",
      ("登录位" in _nd_notes and "顶掉" in _nd_notes), True)
check("网盘 交代了日常浏览器里登着的号为什么捞不过来(11-05 实测)",
      ("App-Bound" in _nd_notes or "app_bound" in _nd_notes), True)

# ---- 服务端看守:网页没开着也要能把扫上的号收下(11-05 那次"没反应"的根因) ----
_wt = nd["account"].get("watch") or {}
check("网盘 看板自己那根看守线程在跑(不靠网页每 2 秒问)",
      (_wt.get("on"), isinstance(_wt.get("cycle"), int), _wt.get("every_sec", 0) >= 5),
      (True, True, True))
check("网盘 看守把节奏/轮数/最近处理过哪几格报出来",
      sorted(_wt.keys()), ["cycle", "every_sec", "held", "hits", "last_at", "last_err", "on", "why"])
check("网盘 界面把看守状态画出来(不然用户只能靠猜)",
      ("ndWatch(r.account.watch)" in _static_js and "服务端看守" in _static_js), True)
check("网盘 界面切回这一页时会跟到真开着的那格(不死盯第 1 槽)",
      ("s.qr_slots" in _static_js and "other.slot" in _static_js), True)

scope_f = tsv_dicts(ND_SCOPES_REL)
ledger_f = tsv_dicts(ND_LEDGER_REL)
check("网盘 档位数 = 清单行数", len(nd["scopes"]), len(scope_f))
check("网盘 台账条数 = 台账文件数据行", nd["ledger"]["total"], len(ledger_f))
check("网盘 台账体积 = 逐行 bytes 相加", nd["ledger"]["bytes"],
      sum(int(r["bytes"]) for r in ledger_f if (r.get("bytes") or "").isdigit()))
check("网盘 台账按状态数一致",
      nd["ledger"]["by_status"],
      {k: sum(1 for r in ledger_f if (r.get("status") or "(空)") == k)
       for k in sorted({(r.get("status") or "(空)") for r in ledger_f})})
mism = []
for sf in scope_f:
    rec = next((x for x in nd["scopes"] if x["name"] == sf["name"]), None)
    if rec is None:
        mism.append(sf["name"] + ":看板没这档")
        continue
    if rec["enable"] != sf["enable"]:
        mism.append(sf["name"] + ":enable")
    want_up = sum(1 for r in ledger_f if sf["remote_prefix"] and
                  ("/" + sf["remote_prefix"].strip("/\\")) in (r.get("remote_path") or "").replace("\\", "/"))
    if rec["uploaded"] != want_up:
        mism.append("%s:已传 %s≠%s" % (sf["name"], rec["uploaded"], want_up))
    if rec["dir_exists"] != os.path.isdir(os.path.join(ROOT, *sf["dir"].replace("\\", "/").split("/"))):
        mism.append(sf["name"] + ":目录存在性")
check("网盘 档位逐项与文件对得上", mism, [])
# enable≠1 的档位必须在"要留意"里点名,不然静默跳过没人看得见
off_names = sorted(sf["name"] for sf in scope_f if sf["enable"] != "1")
warn_text = " ".join(nd["warnings"])
check("网盘 每个关掉的档位都被点名", [n for n in off_names if n not in warn_text], [])

# 凭据泄露检查:接口返回体里不许出现任何 cookie/token/secret 类的字段名。
def keys_of(obj):
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            out |= keys_of(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= keys_of(v)
    return out


# 唯一的例外是 schema —— 那是账号台向 OpenList 现取的**字段说明书**,里面的 "secret"
# 是"这一格是不是密文"的布尔属性,不是凭据值本身;它单独由上面那条属性名白名单把关。
bad_keys = sorted(k for k in keys_of({k: v for k, v in nd.items() if k != "schema"})
                  if re.search(r"(cookie|token|password|secret|plain|credential)", k, re.I))
check("网盘 返回体不含凭据字段名(字段表另议)", bad_keys, [])

# 只剩一个端口:界面与文档里不许再有 5320 那张单独页面残留
# (这两份在扫码那段就先读进来了,这里直接用)
check("界面 5320 残留清零", ("5320" in _static_html) or ("5320" in _static_js), False)
check("界面 account_ui 旧契约清零", "account_ui" in _static_js, False)
check("表单真的内联在这一页",
      ('id="ndFields"' in _static_html and "/api/netdisk/action" in _static_js), True)

# 进程内探针:造一个假账号库(带明显标记),验看板真的把密文/明文挡在门外。
# 只 patch 看板与账号台两边的路径常量,绝不碰 F:\OpenList 里的真账号库。
import importlib.util

spec = importlib.util.spec_from_file_location("kanban_probe", os.path.join(HERE, "看板.py"))
kb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kb)
probe_dir = os.path.join(ROOT, "_scratch", "网盘探针")
os.makedirs(probe_dir, exist_ok=True)
MARK = "DPAPI-FAKE-DO-NOT-LEAK-9137"
PLAIN_MARK = "PLAIN-COOKIE-DO-NOT-LEAK-4471"
PROBE_DB = os.path.join(probe_dir, "账号库.json")
with open(PROBE_DB, "w", encoding="utf-8") as f:
    json.dump({"accounts": [{"alias": "probe-01", "driver": "Quark", "mount_path": "/probe-01",
                             "created": "2026-11-04 00:00:00", "active": True, "remark": "探针号",
                             "last_check": "2026-11-04 00:00:00", "last_ok": True, "last_msg": "OK",
                             "items": 3, "fields": ["cookie", "root_folder_id"], "missing_required": [],
                             "plain": {"root_folder_id": PLAIN_MARK}, "secret": MARK,
                             "secret_len": {"cookie": len(PLAIN_MARK)}}]}, f, ensure_ascii=False)
kb.ACCOUNT_DB = PROBE_DB
kb._cache.pop(("abs", kb.ACCOUNT_DB), None)
pmod, pwhy = kb.acct_mod()
check("探针 账号台模块读进来了(进程内)", (pmod is not None, pwhy), (True, ""))
pmod.DB_PATH = PROBE_DB          # 明细现在出自账号台的 list_safe(),它读的是这个常量

# 槽位的算术只许有一份来源:界面和账号台都现读扫码模块,不许各自拼端口/拼目录名。
# 拼错一格就是"两个号挤同一个 profile",后果是后扫的把先扫的顶掉。
_qrm = getattr(pmod, "qr", None)
check("探针 账号台把扫码模块带在身边(进程内)",
      (_qrm is not None, getattr(pmod, "QR_ERR", "")), (True, ""))
if _qrm:
    _mx = _qrm.MAX_SLOTS
    _bad = []
    for _n in range(1, _mx + 1):
        if _qrm.port_of("Quark", _n) != _qrm.port_of("Quark", 1) + (_n - 1) * 10:
            _bad.append("夸克第%d槽端口" % _n)
        _wp = "profile-Quark" if _n == 1 else "profile-Quark-%02d" % _n
        if os.path.basename(_qrm.profile_of("Quark", _n)) != _wp:
            _bad.append("夸克第%d槽 profile 名(%s)" % (_n, os.path.basename(_qrm.profile_of("Quark", _n))))
        _ws = "session-Quark.json" if _n == 1 else "session-Quark-%02d.json" % _n
        if os.path.basename(_qrm.state_path("Quark", _n)) != _ws:
            _bad.append("夸克第%d槽状态文件名" % _n)
    check("探针 每格登录位端口/目录/状态文件各走各的(第 1 槽沿用老地址不变)", _bad, [])
    check("探针 三个盘的同一格也不撞车",
          len({_qrm.port_of("Quark", 1), _qrm.port_of("BaiduNetdisk", 1), _qrm.port_of("Thunder", 1),
               _qrm.port_of("Quark", _mx), _qrm.port_of("BaiduNetdisk", _mx), _qrm.port_of("Thunder", _mx)}),
          6)
    check("探针 登录位号越界/乱填一律夹回合法格",
          [_qrm._slot(x) for x in (0, -5, "abc", "", None, 999, "3", "10")],
          [1, 1, 1, 1, 1, _mx, 3, _mx])
    check("探针 下一个空登录位跳过占着的格、按盘各算各的",
          pmod._next_slot("Quark", {"accounts": [{"driver": "Quark", "slot": 1},
                                                 {"driver": "Quark"},          # 老记录没这栏 = 占第 1 格
                                                 {"driver": "Quark", "slot": 3},
                                                 {"driver": "Thunder", "slot": 2}]}), 2)
    check("探针 十格占满了报 0(调用方才好说「这盘没空位了」)",
          pmod._next_slot("Quark", {"accounts": [{"driver": "Quark", "slot": _n}
                                                 for _n in range(1, _mx + 1)]}), 0)
    check("探针 截图接口按槽位取(第 1 槽以外也认,不是写死第一格)",
          pmod.screenshot("Quark", 3)[0] is None, True)
    note("网盘 现在:登录位上限", "每个盘 %d 格(第 1 槽 %d / 第 %d 槽 %d)" %
         (_mx, _qrm.port_of("Quark", 1), _mx, _qrm.port_of("Quark", _mx)))
pj = kb.api_netdisk()
pt = json.dumps(pj, ensure_ascii=False)
check("探针 假账号被数出来了", (pj["store"]["total"], pj["accounts"][0]["alias"]), (1, "probe-01"))
check("探针 库里条数与明细同源于假库", pj["store"]["raw_total"], 1)
check("探针 密文标记没漏进接口", MARK in pt, False)
check("探针 明文标记没漏进接口", PLAIN_MARK in pt, False)
check("探针 连 secret_len 也不输出", "secret_len" in pt, False)
check("探针 fields 只报个数不报字段名", pj["accounts"][0]["fields"], 2)
check("探针 密文长度有报(证明存了但没给看)", pj["accounts"][0]["cipher_len"], len(MARK))
check("探针 写侧门在进程内也认绑的地址",
      pj["account"]["writable"], pj["bind"] in ("127.0.0.1", "::1"))
# --lan 那一档不是界面装样子:同一份代码,绑址一变,写侧自己就得关(这里只改进程内的常量,不真开网络口)
kb.BIND = "0.0.0.0"
lj = kb.api_netdisk()
check("探针 --lan 时 writable 自己变 False", lj["account"]["writable"], False)
check("探针 --lan 时把地址写进锁的话里(用户知道为什么锁)",
      ("0.0.0.0" in (lj["account"]["write_blocked"] or "")), True)
kb.BIND = "127.0.0.1"
# 看守那两根判断得是能单测的纯函数,不能埋在 while True 里没人碰得到
kb.BIND = "0.0.0.0"
_lan_ok, _lan_why = kb._watch_allowed()
kb.BIND = "127.0.0.1"
_kb_ok, _kb_why = kb._watch_allowed()
check("探针 看守和界面走同一道写侧门(绑 0.0.0.0 时它自己也不动写路径)",
      (_lan_ok, "0.0.0.0" in _lan_why, _kb_ok, _kb_why), (False, True, True, ""))
check("探针 看守说的「扫上了」只认登录标志齐不齐(窗口没开/缺一条/没盘都不算)",
      [kb._watch_ready(x) for x in (
          {"listening": False, "markers": ["__pus"], "markers_have": ["__pus"]},
          {"listening": True, "markers": ["__pus", "__puus"], "markers_have": ["__pus"]},
          {"listening": True, "markers": ["__pus", "__puus"], "markers_have": ["__pus", "__puus"]},
          {"listening": True, "markers": [], "markers_have": []})],
      [False, False, True, False])

# ---- 传之前那道写闸门(11-06:两个夸克号都退回 capacity limit;它报的 use_capacity 在 NORMAL 号上
#      是坏的——共 10.10 GB 的额度说成「已用 33501.92 GB」。数字不能拦路,只能真丢 1 字节问对面收不收。) ----
# 下面全部走假传输:一个字节也不出这台机器,只验代码形状。
import argparse
_nu_spec = importlib.util.spec_from_file_location(
    "nd_upload_probe", os.path.join(ROOT, "_工具脚本", "netdisk_upload.py"))
nu = importlib.util.module_from_spec(_nu_spec)
_nu_spec.loader.exec_module(nu)
_GB = 1024 ** 3
ZWSP = chr(0x200b)          # 网盘返回的 message 里真带这个零宽字符,GBK 控制台上会当场炸


class _FakeAuth:
    """假传输:只记账挨了哪几枪。put_code/stat_size/remove_code 决定探针这一趟演哪种结局。"""

    def __init__(self, put_code=400, put_msg="", stat_size=None, remove_code=200):
        self.put_code, self.put_msg = put_code, put_msg
        self.stat_size, self.remove_code = stat_size, remove_code
        self.calls = []

    def token(self):
        return "假 token，出不了这个进程"

    def raw(self, method, path, body=None, ctype=None, headers=None, **_kw):
        self.calls.append((method, path, dict(headers or {})))
        return {"code": self.put_code, "message": self.put_msg}

    def api(self, path, payload):
        self.calls.append(("POST", path, dict(payload)))
        if path == "/api/fs/get":
            return ({"code": 200, "data": {"size": self.stat_size, "name": "probe"}}
                    if self.stat_size is not None
                    else {"code": 404, "message": "file not found"})
        if path == "/api/fs/remove" and self.remove_code == 200:
            self.stat_size = None               # 删掉了就别让假对象继续"看得见"
        return {"code": self.remove_code, "message": "success" if self.remove_code == 200 else "boom"}


check("闸门 容量话术:剩得多 / 满了 / 数读不出来各说什么",
      [pmod.capacity_text(100 * _GB, 20 * _GB),
       pmod.capacity_text(10 * _GB, 33501 * _GB),
       pmod.capacity_text(10 * _GB, 10 * _GB),
       pmod.capacity_text(None, 5), pmod.capacity_text("垃圾", "垃圾"), pmod.capacity_text(0, 9 * _GB)],
      ["共 100.00 GB / 剩 80.00 GB",
       "共 10.00 GB / 已用 33501.00 GB——满了，夸克会退回 capacity limit",
       "共 10.00 GB / 已用 10.00 GB——满了，夸克会退回 capacity limit",
       "", "", ""])
check("闸门 这条只回一句人话,不回一个能拿去比大小的字节数(留个数就有人拿它当闸门)",
      (hasattr(pmod, "free_bytes"), type(pmod.capacity_text(100 * _GB, 20 * _GB)).__name__,
       pmod.member_of({}), pmod.capacity_for("")),
      (False, "str", "", ""))

_fa1 = _FakeAuth(put_code=400, put_msg="StorageDriver capacity limit[%s] not enough space" % ZWSP)
_r1 = nu.probe_write(_fa1, "quark-gate-blocked")
_puts1 = [c for c in _fa1.calls if c[1] == "/api/fs/put"]
check("闸门 探针只丢一个字节、名字点开头、就落在这档的根上",
      (len(_puts1), _puts1[0][2].get("X-File-Size"),
       urllib.parse.unquote(_puts1[0][2].get("File-Path", ""))),
      (1, "1", "/quark-gate-blocked/.netdisk_upload_probe"))
check("闸门 对面退回容量墙:拦下(写得进=False)、原因照说、零宽字符不跟着往外冒",
      (_r1[0], ZWSP in _r1[1], "capacity limit" in _r1[1]), (False, False, True))
check("闸门 网盘错误信息里的零宽字符整串清掉(只 strip 两头会漏夹在中间的)",
      [nu.msg_of({"message": "a%sb%sc" % (ZWSP, ZWSP)}), nu.msg_of({"message": ZWSP}),
       nu.msg_of({})],
      ["abc", "OpenList 没回错误信息", "OpenList 没回错误信息"])
check("闸门 探针压根没写进去就没什么可删(不许拿 remove 猜),这一路只 PUT+GET 两枪",
      [c[1] for c in _fa1.calls], ["/api/fs/put", "/api/fs/get"])

_fa2 = _FakeAuth(put_code=200, stat_size=1)
_r2 = nu.probe_write(_fa2, "quark-gate-writable")
_rm2 = [c for c in _fa2.calls if c[1] == "/api/fs/remove"]
check("闸门 探针写得进就放行,并把回读到的字节数说出去",
      (_r2[0], "回读 1" in _r2[1], "没删干净" in _r2[1]), (True, True, False))
# OpenList 4.2.9 的 /api/fs/remove 收 {dir, names}(源码 server/handles/fsmanage.go:369);
# 拿 AList v3 那套 {path, names, dir_names} 去发,它一律回 400 "Empty file names" —— 探针就成了删不掉的垃圾。
check("闸门 删探针用 4.2.9 认的 {dir,names},不是 v3 的 {path,dir_names}",
      (len(_rm2), sorted(_rm2[0][2]), _rm2[0][2].get("dir"), _rm2[0][2].get("names")),
      (1, ["dir", "names"], "/quark-gate-writable", [".netdisk_upload_probe"]))
_n2 = len(_fa2.calls)
nu.probe_write(_fa2, "quark-gate-writable")
check("闸门 同一档一轮里只探一次(二十个档位不该变成二十趟网络)", len(_fa2.calls), _n2)

_fa3 = _FakeAuth(put_code=200, stat_size=1, remove_code=500)
_r3 = nu.probe_write(_fa3, "quark-gate-sticky")
check("闸门 探针删不掉不许安静吞掉:照样放行但点名在哪留了垃圾",
      (_r3[0], "没删干净" in _r3[1], "/quark-gate-sticky/.netdisk_upload_probe" in _r3[1]),
      (True, True, True))
check("闸门 探针文件落在 _scratch 里(中间产物集中一处,好一并清)",
      os.path.normpath(nu.PROBE_LOCAL).startswith(os.path.normpath(os.path.join(ROOT, "_scratch"))), True)

_note_saved = nu.capacity_note
nu.capacity_note = lambda m: "NORMAL 共 10.10 GB / 已用 33501.92 GB——满了"
check("闸门 本机暂存盒不去问网盘(它后面没有网盘)",
      nu.write_gate(_FakeAuth(), [(ROOT, "/本地暂存/知识库/a.tsv")]), None)
check("闸门 一批里目标跨了档就不整批拦(各档让各自的探针问)",
      nu.write_gate(_FakeAuth(), [(ROOT, "/quark-a/a.txt"), (ROOT, "/本地暂存/b.tsv")]), None)
_gv = nu.write_gate(_FakeAuth(put_code=400, put_msg="capacity limit"),
                    [(ROOT, "/quark-gate-blocked/目录/a.txt")])
check("闸门 拦住时把「哪一档 / 为什么 / 对面现状」三样一起交出去",
      (_gv[0], "capacity limit" in _gv[1], _gv[2]), ("quark-gate-blocked", True, nu.capacity_note("x")))
nu.capacity_note = _note_saved

_gate_file = os.path.join(probe_dir, "闸门自测.txt")
with open(_gate_file, "wb") as _f:
    _f.write(b"gate probe\n")
_saved = {}
for _n in ("load_ledger", "save_ledger", "push", "write_gate", "log"):
    _saved[_n] = getattr(nu, _n)
_writes = []
_logs = []


def _no_push(*_a, **_k):
    raise AssertionError("闸门拦下了还去 push,等于探针白丢")


nu.load_ledger = lambda *_a, **_k: {}
nu.save_ledger = lambda *_a, **_k: _writes.append(1)
nu.push = _no_push
nu.write_gate = lambda a, pairs: ("quark-gate-upload", "capacity limit", "NORMAL 满了")
nu.log = lambda m: _logs.append(str(m))
_fa4 = _FakeAuth()
_rc = nu.cmd_upload(_fa4, argparse.Namespace(scope=None, mount=None, file=_gate_file,
                                             as_="/quark-gate-upload/闸门自测.txt", dry_run=False))
for _n, _v in _saved.items():
    setattr(nu, _n, _v)
_os = " ".join(_logs)
check("闸门 拦下时一个字节没推、台账没落一笔、也没往网盘发过探针",
      (_rc, len(_writes), _fa4.calls), (1, 0, []))
check("闸门 拦下那句话说得明白:哪一档 / 为什么 / 且交代「不会留 FAIL」",
      [x in _os for x in ("拦下没传", "不会留 FAIL", "/quark-gate-upload", "capacity limit", "NORMAL 满了")],
      [True] * 5)
check("闸门 拦下的条数算进「这一轮有没传的」(退出码非 0,调用方才知道没传成),并点明几个文件没动",
      (_rc, len([l for l in _logs if "一个字节都没动" in l]), "1 个文件" in _os), (1, 1, True))
os.remove(_gate_file)

check("探针 没写过真账号库", os.path.isfile(os.path.join(OL_DIR, "账号库.json")) and
      json.load(open(os.path.join(OL_DIR, "账号库.json"), encoding="utf-8")).get("accounts") == accts, True)
note("网盘 现在:OpenList", "在听" if nd["openlist"]["listening"] else "没在听")
note("网盘 现在:账号台", "模块读进来 · 可写" if nd["account"]["writable"] else
     "模块读进来 · 锁着(%s)" % (nd["account"]["write_blocked"] or nd["bind"]))
note("网盘 现在:夸克要填的格子", "%d 格(必填 %d 格):%s" % (
    len(nd["schema"]["fields"]),
    sum(1 for f in nd["schema"]["fields"] if f["required"]),
    "、".join(f["name"] + ("＊" if f["required"] else "") for f in nd["schema"]["fields"])))
note("网盘 现在:账号/档位/台账", "%s 个号 · %s 档 · %s 条台账" %
     (nd["store"]["total"], len(nd["scopes"]), nd["ledger"]["total"]))
note("网盘 要留意", nd["warnings"])

print("\n结果:", "全部一致" if not fails else "不一致项:" + ", ".join(fails))
sys.exit(1 if fails else 0)
