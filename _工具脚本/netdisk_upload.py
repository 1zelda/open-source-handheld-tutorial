#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网盘上传器：把本地产物经本机 OpenList 推到夸克/百度/迅雷等网盘挂载点。

用法（都在这一台机器上跑，OpenList 只听 127.0.0.1:5244）：

  py -3 netdisk_upload.py status                      # 服务在不在线、有哪些挂载点
  py -3 netdisk_upload.py mount Quark                 # 交互式登记一个网盘挂载点（凭据只进 OpenList 库）
  py -3 netdisk_upload.py upload --scope 自制产物      # 按清单上传一批
  py -3 netdisk_upload.py upload --mount /夸克 --file 某文件 --as /目录/文件名
  py -3 netdisk_upload.py verify                      # 拿台账逐条回读网盘侧大小复校
  py -3 netdisk_upload.py stop                        # 用完把服务停掉（默认让它挂着，空载 ~58MB）

凭据口径：网盘 cookie/token 和 OpenList 管理员密码都不写进本仓库、不落任何文件；
管理员密码只从环境变量 OPENLIST_ADMIN_PASSWORD 读。
"""
import argparse
import csv
import getpass
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

try:
    # 传失败时 OpenList 的 message 里常带网盘返回的怪字符(实测 \u200b),
    # 默认 gbk 输出会在这条本该解释失败原因的路上 UnicodeEncodeError 崩掉。
    # stderr 一起改:SystemExit 的话走的是 stderr,留着 GBK 就成了同一次跑两种编码、拼一起全是乱码。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))      # F:\开源掌机教程
OL_DIR = os.environ.get("OPENLIST_DIR", r"F:\OpenList")
OL_EXE = os.path.join(OL_DIR, "openlist.exe")
HOST, PORT = "127.0.0.1", 5244
BASE = "http://%s:%d" % (HOST, PORT)
ADMIN_USER = os.environ.get("OPENLIST_ADMIN_USER", "admin")
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "网盘上传清单.tsv")
LEDGER_DIR = os.path.join(ROOT, "06-资讯监控", "网盘上传")
LEDGER = os.path.join(LEDGER_DIR, "网盘上传台账.tsv")
HDR = ["local_path", "remote_path", "bytes", "sha256", "mount", "status", "at", "info"]
BIG = 64 * 1024 * 1024        # 单文件超过这个体积就当任务传（As-Task），避免长时间占连接
CHUNK = 4 * 1024 * 1024


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


# 网盘/驱动回的错误信息里常夹零宽字符（实测 Quark 的 capacity limit[​]）。只 strip 两头不够：
# 它夹在中间照样会跟着进台账和界面，变成看不见的垃圾（顺带也能挡住 GBK 控制台那条老崩溃）。
_ODD = ("​", "‌", "‍", "﻿")


def msg_of(resp, limit=160, fallback="OpenList 没回错误信息"):
    s = str((resp or {}).get("message") or "")
    for ch in _ODD:
        s = s.replace(ch, "")
    return s.strip()[:limit] or fallback


# ---------------------------------------------------------------- 服务与鉴权
def up():
    try:
        socket.create_connection((HOST, PORT), timeout=1.5).close()
        return True
    except OSError:
        return False


def ensure_server():
    if up():
        return True
    if not os.path.isfile(OL_EXE):
        log("找不到 %s，装的位置不对（可用环境变量 OPENLIST_DIR 指过去）" % OL_EXE)
        return False
    log("5244 没在听，拉起 OpenList…")
    env = dict(os.environ)
    env.pop("HTTPS_PROXY", None)          # 本地调用别绕代理，绕了会被掐（10054）
    env.pop("HTTP_PROXY", None)
    subprocess.Popen([OL_EXE, "start"], cwd=OL_DIR, env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        if up():
            time.sleep(0.6)               # 端口开了再等一下，让它把库加载完
            log("已就绪")
            return True
        time.sleep(0.5)
    log("起了 20 秒还没监听，去看 %s" % os.path.join(OL_DIR, "data", "log", "log.log"))
    return False


def stop_server():
    if not up():
        log("本来就没在跑")
        return
    subprocess.run([OL_EXE, "stop"], cwd=OL_DIR, capture_output=True, text=True)
    log("已停止 OpenList")


class Auth:
    def __init__(self):
        self.tok = ""
        self.at = 0.0

    def token(self):
        if self.tok and time.time() - self.at < 40 * 3600:
            return self.tok
        pw = os.environ.get("OPENLIST_ADMIN_PASSWORD")
        if not pw:
            raise SystemExit("没设环境变量 OPENLIST_ADMIN_PASSWORD（管理员密码）。"
                             "改密码：openlist.exe admin set 新密码；"
                             "永久生效：setx OPENLIST_ADMIN_PASSWORD \"新密码\"")
        d = self.raw("POST", "/api/auth/login",
                     body=json.dumps({"username": ADMIN_USER, "password": pw}).encode(),
                     ctype="application/json")
        if d.get("code") != 200:
            raise SystemExit("登录失败：%s（密码不对就在 F:\\OpenList 里跑 openlist.exe admin set 新密码）"
                             % d.get("message"))
        self.tok = d["data"]["token"]
        self.at = time.time()
        log("已登录（token 只在内存里，不落盘）")
        return self.tok

    def raw(self, method, path, body=None, ctype=None, headers=None, timeout=600, auth=True):
        req = urllib.request.Request(BASE + path, data=body, method=method)
        if ctype:
            req.add_header("Content-Type", ctype)
        req.add_header("Connection", "close")
        if auth and self.tok:
            req.add_header("Authorization", self.tok)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        last = None
        for _ in range(2):                      # 10054 会被本机代理/杀软掐一次，重试一次
            if hasattr(body, "seek"):
                body.seek(0)                    # 重传必须从头，否则第二遍是半个文件
            try:
                raw = urllib.request.urlopen(req, timeout=timeout).read()
                return json.loads(raw)
            except urllib.error.HTTPError as e:
                raw = e.read()
                try:
                    return json.loads(raw)
                except ValueError:
                    return {"code": e.code, "message": raw[:200].decode("utf-8", "replace")}
            except Exception as e:              # noqa: BLE001
                last = e
                time.sleep(1.0)
        return {"code": -1, "message": "%s: %s" % (type(last).__name__, last)}

    def call(self, method, path, payload=None, **kw):
        """带 401 续期的一次调用：token 过期就重新登录再试一遍。"""
        if not self.tok:
            self.token()
        d = self.raw(method, path, **kw)
        if d.get("code") == 401:
            self.tok, self.at = "", 0.0
            self.token()
            d = self.raw(method, path, **kw)
        return d

    def api(self, path, payload):
        return self.call("POST", path, body=json.dumps(payload).encode(),
                         ctype="application/json")

    def get(self, path):
        return self.call("GET", path)


# ---------------------------------------------------------------- 网盘侧读写
def mounts(a):
    d = a.get("/api/admin/storage/list?page=1&per_page=200")
    out = []
    for s in ((d.get("data") or {}).get("content") or []):
        out.append({"id": s.get("id"), "mount_path": s.get("mount_path"),
                    "driver": s.get("driver"), "disabled": bool(s.get("disabled")),
                    "status": s.get("status") or "",
                    "remark": s.get("remark") or ""})
    return out


def remote_stat(a, path):
    d = a.api("/api/fs/get", {"path": path})
    if d.get("code") != 200:
        return None
    x = d.get("data") or {}
    return {"size": x.get("size"), "name": x.get("name"),
            "sha256": (x.get("hashinfo") or {}).get("sha256") if isinstance(x.get("hashinfo"), dict) else ""}


def put_stream(a, local, remote, size, sha):
    """裸流上传：PUT /api/fs/put + File-Path 头（v4.2.9 源码 server/handles/fsup.go）。"""
    a.token()
    headers = {
        "File-Path": urllib.parse.quote(remote, safe=""),
        "X-File-Size": str(size),
        "X-File-Sha256": sha,
        "Overwrite": "true",
        "Last-Modified": str(int(os.path.getmtime(local) * 1000)),
    }
    if size >= BIG:
        headers["As-Task"] = "true"            # 大文件转后台任务，别让这条连接挂几十分钟
    with open(local, "rb") as fh:
        return a.raw("PUT", "/api/fs/put", body=fh, ctype="application/octet-stream",
                     headers=headers)


# ---------------------------------------------------------------- 台账
def load_ledger():
    if not os.path.isfile(LEDGER):
        return {}
    with io_open(LEDGER) as fh:
        return {r["local_path"]: r for r in csv.DictReader(fh, delimiter="\t")
                if r.get("local_path")}


def io_open(path, mode="r", encoding="utf-8"):
    return open(path, mode=mode, encoding=encoding, newline="")


def save_ledger(rows):
    os.makedirs(LEDGER_DIR, exist_ok=True)
    with io_open(LEDGER, "w") as fh:
        w = csv.DictWriter(fh, fieldnames=HDR, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def record(rows, rec):
    rows[rec["local_path"]] = rec


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(CHUNK), b""):
            h.update(blk)
    return h.hexdigest()


# ---------------------------------------------------------------- 清单
def read_manifest():
    if not os.path.isfile(MANIFEST):
        return []
    with io_open(MANIFEST) as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    out = []
    for r in rows:
        if (r.get("enable") or "1").strip() != "1":
            continue
        out.append({"name": r["name"].strip(), "dir": r["dir"].strip(),
                    "remote_prefix": r["remote_prefix"].strip(),
                    "include": (r.get("include") or "*").strip(),
                    "exclude": (r.get("exclude") or "").strip(),
                    "exclude_dir": (r.get("exclude_dir") or "").strip(),
                    "mount": r["mount"].strip()})
    return out


def glob_to_re(pat):
    parts = []
    for ch in pat:
        if ch == "*":
            parts.append(".*")
        elif ch == "?":
            parts.append(".")
        else:
            parts.append(re.escape(ch))
    return re.compile("".join(parts) + r"\Z", re.I)


def want(name, include, exclude):
    inc = [glob_to_re(p.strip()) for p in include.split(";") if p.strip()]
    exc = [glob_to_re(p.strip()) for p in exclude.split(";") if p.strip()]
    if any(x.match(name) for x in exc):
        return False
    return any(x.match(name) for x in inc) if inc else True


def is_under(rel, skip):
    return rel == skip or rel.startswith(skip + "/")


def walk(scope, mount):
    base = scope["dir"]
    if not os.path.isabs(base):
        base = os.path.join(ROOT, base)
    # 清单里的 dir 允许写 /，但台账按 local_path 认行，混着斜杠会让同一个文件记成两行。
    base = os.path.normpath(base)
    if not os.path.isdir(base):
        log("  清单里的目录不存在：%s" % base)
        return []
    skip = [s.strip().strip("/") for s in scope.get("exclude_dir", "").split(";") if s.strip()]
    out = []
    for dp, dn, fn in os.walk(base):
        rel_dp = os.path.relpath(dp, base).replace("\\", "/")
        if rel_dp == ".":
            rel_dp = ""
        dn[:] = [d for d in dn if not d.startswith(".")
                 and not any(is_under((rel_dp + "/" + d).strip("/"), s) for s in skip)]
        for f in sorted(fn):
            rel = os.path.relpath(os.path.join(dp, f), base).replace("\\", "/")
            if not want(f, scope["include"], scope["exclude"]):
                continue
            lp = os.path.join(dp, f)
            rp = "/%s/%s/%s" % (mount.strip("/"), scope["remote_prefix"].strip("/"), rel)
            out.append((lp, "/" + rp.strip("/")))
    return out


# ---------------------------------------------------------------- 上传
def remote_wait(a, path, size, tries=40):
    """As-Task 传的是后台任务，落盘要等；回读直到 size 对上或次数用完。"""
    for i in range(tries):
        rs = remote_stat(a, path)
        if rs and rs["size"] == size:
            return rs
        time.sleep(2.0)
    return remote_stat(a, path)


def push(a, pairs, rows, label):
    ok = skip = fail = 0
    tot = 0
    for local, remote in pairs:
        size = os.path.getsize(local)
        tot += size
        prev = rows.get(local)
        if prev and prev.get("status") == "OK" and int(prev.get("bytes") or -1) == size:
            rs = remote_stat(a, remote)
            if rs and rs["size"] == size:
                skip += 1
                continue
        sha = sha256(local)
        r = put_stream(a, local, remote, size, sha)
        code = r.get("code")
        if code == 200:
            rs = remote_wait(a, remote, size) if size >= BIG else remote_stat(a, remote)
            if rs and rs["size"] == size:
                ok += 1
                record(rows, {"local_path": local, "remote_path": remote, "bytes": str(size),
                              "sha256": sha, "mount": remote.split("/")[1],
                              "status": "OK", "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "info": ""})
            else:
                fail += 1
                record(rows, {"local_path": local, "remote_path": remote, "bytes": str(size),
                              "sha256": sha, "mount": remote.split("/")[1], "status": "FAIL",
                              "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "info": "网盘侧回读 size=%s 跟本地 %d 对不上" %
                                      (rs and rs["size"], size)})
                log("  回读不符：%s" % remote)
        else:
            fail += 1
            record(rows, {"local_path": local, "remote_path": remote, "bytes": str(size),
                          "sha256": sha, "mount": remote.split("/")[1], "status": "FAIL",
                          "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "info": msg_of(r, 180)})
            log("  传失败：%s -> %s" % (os.path.basename(local), msg_of(r, 120)))
    log("%s：成功 %d / 跳过 %d / 失败 %d，本轮涉及 %.2f GB"
        % (label, ok, skip, fail, tot / 1e9))
    return ok, skip, fail


def clean_arg_path(v, what):
    """Git Bash 会把以 / 开头的参数拼上它自己的根（如 /夸克 变成 /D:/Git/夸克），
    所以这里认出这种改写并明确报错，而不是把错路径传到网盘去。"""
    p = "/" + v.strip("/")
    if re.match(r"^/[A-Za-z]:[/\\]", p):
        raise SystemExit("%s“%s”被 Git Bash 改写过（它给 / 开头的参数拼上了自己的根目录）。"
                         "去掉开头的斜杠只写名字，或者先 set MSYS_NO_PATHCONV=1 再跑。"
                         % (what, v))
    return p


# ---------------------------------------------------------------- 传之前先问对面让不让写
_ACCT = None
PROBE_LOCAL = None          # 那个 1 字节探针文件，落在这里（跟其它中间产物同一个目录，好一并清）
PROBE_REMOTE = "/.netdisk_upload_probe"
_PROBE_OK = {}              # 同一个挂载点一轮里只探一次


def acct_mod():
    """按需把账号台读进来（文件名是中文，不能直接 import）。只在要报容量时读。"""
    global _ACCT
    if _ACCT is None:
        import importlib.util
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "网盘账号台.py")
        spec = importlib.util.spec_from_file_location("netdisk_accounts", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _ACCT = m
    return _ACCT


def capacity_note(mount):
    """账号台那边问一句这个号现在的会员档/容量，只为把话说清楚。
    夸克在 NORMAL 号上报的 use_capacity 是坏的（11-06 实测：共 10.10 GB 的号说「已用 33501.92 GB」），
    所以这句话只能当参考，绝不能拿它拦路——拦路用下面那个探针。"""
    try:
        return acct_mod().capacity_for(mount) or ""
    except Exception as e:
        return "容量没问出来（%s）" % type(e).__name__


def probe_write(a, mount):
    """往这个挂载点的根丢一个 1 字节文件、回读、再删掉——问清「这里到底收不收东西」。
    回 (写得进吗, 给人看的那句话)。为什么不靠接口报的剩余字节：见 capacity_note 上面那段。
    dry-run 不调它（探针是真写）。"""
    if mount in _PROBE_OK:
        return _PROBE_OK[mount]
    global PROBE_LOCAL
    if PROBE_LOCAL is None:
        PROBE_LOCAL = os.path.join(ROOT, "_scratch", "网盘探针")
        os.makedirs(PROBE_LOCAL, exist_ok=True)
        PROBE_LOCAL = os.path.join(PROBE_LOCAL, "probe.txt")
        with open(PROBE_LOCAL, "wb") as fh:
            fh.write(b"1")
    remote = "/%s%s" % (mount.strip("/"), PROBE_REMOTE)
    size = os.path.getsize(PROBE_LOCAL)
    res = None
    try:
        r = put_stream(a, PROBE_LOCAL, remote, size, sha256(PROBE_LOCAL))
        if r.get("code") == 200:
            rs = remote_stat(a, remote)
            res = (True, "探针写得进（1 字节回读 %s）" % (rs and rs["size"])) if rs and rs["size"] == size \
                else (False, "探针写进去了但回读不到（size=%s）" % (rs and rs["size"]))
        else:
            res = (False, msg_of(r))
    except Exception as e:
        res = (False, "探针这一步就炸了：%s: %s" % (type(e).__name__, str(e)[:120]))
    try:
        if remote_stat(a, remote):
            # OpenList 4.2.9 的 /api/fs/remove 收的是 {dir, names}（源码 server/handles/fsmanage.go:369），
            # 不是 AList v3 那套 {path, names, dir_names}——形状错了它一律回 400 "Empty file names"。
            a.api("/api/fs/remove", {"dir": "/%s" % mount.strip("/"),
                                     "names": [os.path.basename(PROBE_REMOTE)]})
    except Exception:
        pass                        # 删不掉是留个 1 字节垃圾，比误拦一整档轻，但不能安静：下面说一句
    if res[0] and remote_stat(a, remote):
        res = (res[0], res[1] + "（注意：探针没删干净，%s 还留着）" % remote)
    _PROBE_OK[mount] = res
    return res


def write_gate(a, pairs):
    """按这一堆文件的目标挂载点探一次。回 None 表示不用拦；回 (拦, 那句话) 表示这一档别传。"""
    names = {rp.split("/")[1] for _, rp in pairs if rp.count("/") > 1}
    if len(names) != 1:
        return None
    mount = names.pop()
    if mount in ("本地暂存",):        # 本机的暂存盒不用问网盘
        return None
    ok, why = probe_write(a, mount)
    if ok:
        return None
    return mount, why, capacity_note(mount)


def cmd_upload(a, args):
    rows = load_ledger()
    grand = [0, 0, 0]
    if args.mount:
        args.mount = clean_arg_path(args.mount, "挂载路径")
    if args.as_:
        args.as_ = clean_arg_path(args.as_, "远端路径")
    if args.file:
        local = os.path.abspath(args.file)
        if not os.path.isfile(local):
            raise SystemExit("文件不存在：%s" % local)
        if not args.mount and not args.as_:
            raise SystemExit("--file 要配 --mount /夸克 或 --as /夸克/目录/文件名")
        remote = args.as_ or "/%s/%s" % (args.mount.strip("/"), os.path.basename(local))
        jobs = [(("单文件 " + os.path.basename(local)), [(local, remote)])]
    else:
        scopes = read_manifest()
        if not scopes:
            raise SystemExit("清单是空的：%s" % MANIFEST)
        picked = [s for s in scopes if not args.scope or s["name"] == args.scope]
        if args.scope and not picked:
            raise SystemExit("清单里没有这一档：%s（可选：%s）"
                             % (args.scope, ", ".join(s["name"] for s in scopes)))
        if args.mount:
            picked = [s for s in picked if s["mount"].strip("/") == args.mount.strip("/")]
        if not picked:
            raise SystemExit("按 --scope/--mount 过滤后没活可干")
        jobs = [(s["name"], walk(s, s["mount"])) for s in picked]

    for label, pairs in jobs:
        log("%s：%d 个文件待传" % (label, len(pairs)))
        if args.dry_run:
            for lp, rp in pairs[:25]:
                log("   会传 %s -> %s" % (lp, rp))
            if len(pairs) > 25:
                log("   …还有 %d 条" % (len(pairs) - 25))
            names = {rp.split("/")[1] for _, rp in pairs if rp.count("/") > 1}
            if len(names) == 1 and names != {"本地暂存"}:
                log("   对面现状（夸克报的数，仅供参考）：%s" % (capacity_note(names.pop()) or "没量到"))
            continue
        gate = write_gate(a, pairs)
        if gate:
            grand[2] += len(pairs)
            log("%s：拦下没传 —— 往 /%s 丢探针被退回来：%s%s"
                % (label, gate[0], gate[1],
                   ("。对面现在：%s" % gate[2]) if gate[2] else ""))
            log("   这一档 %d 个文件一个字节都没动，台账里不会留 FAIL" % len(pairs))
            continue
        r = push(a, pairs, rows, label)
        grand = [grand[i] + r[i] for i in range(3)]
        save_ledger(list(rows.values()))
    if args.dry_run:
        log("dry-run，什么都没传")
        return 0
    log("台账：%s" % LEDGER)
    return 0 if grand[2] == 0 else 1


def cmd_verify(a, args):
    rows = load_ledger()
    if not rows:
        log("台账空的，没什么可校")
        return 0
    bad = miss = ok = gone = 0
    for lp, r in sorted(rows.items()):
        if not os.path.isfile(lp):
            r["status"] = "LOCAL-GONE"
            r["info"] = "本地文件已经不在了，网盘那份留着不动"
            gone += 1
            continue
        if sha256(lp) != r["sha256"]:
            r["status"] = "LOCAL-CHANGED"
            r["info"] = "本地在这之后被改过，网盘那份是旧的，下次 upload 会重传"
            bad += 1
            continue
        rs = remote_stat(a, r["remote_path"])
        if not rs:
            r["status"] = "MISSING"
            r["info"] = "网盘侧读不到这个路径"
            miss += 1
        elif rs["size"] != int(r["bytes"]):
            r["status"] = "SIZE-DIFF"
            r["info"] = "网盘 %s vs 本地 %s" % (rs["size"], r["bytes"])
            bad += 1
        else:
            r["status"] = "OK"
            r["info"] = "复核 %s" % time.strftime("%Y-%m-%d %H:%M")
            ok += 1
    save_ledger(list(rows.values()))
    log("复核：网盘相符 %d / 不符 %d / 网盘缺档 %d / 本地已删 %d" % (ok, bad, miss, gone))
    return 0 if (bad + miss) == 0 else 1


def cmd_prune(a, args):
    """传完并且「本地哈希 == 台账 == 网盘侧体积」三条全对上，才准删本地那一份。
    默认只出清单不动手，要 --yes 才真删；同一条盘的规矩是「不代删用户的其它文件」，
    所以这里只吃台账里 status=OK 的路径，其余一律留着并点名说为什么留。"""
    if args.mount:
        args.mount = clean_arg_path(args.mount, "挂载路径")
    rows = load_ledger()
    if not rows:
        log("台账是空的：%s——没传成功过的东西一条都不许删" % LEDGER)
        return 1
    if args.file:
        cands = [os.path.abspath(args.file)]
    else:
        scopes = read_manifest()
        picked = [s for s in scopes if not args.scope or s["name"] == args.scope]
        if args.scope and not picked:
            raise SystemExit("清单里没有这一档：%s（可选：%s）"
                             % (args.scope, ", ".join(s["name"] for s in scopes)))
        if args.mount:
            picked = [s for s in picked if s["mount"].strip("/") == args.mount.strip("/")]
        if not picked:
            raise SystemExit("按 --scope/--mount 过滤后没活可干")
        cands = [lp for _s, pairs in [(s, walk(s, s["mount"])) for s in picked]
                 for lp, _rp in pairs]

    ready, kept = [], Counter()
    freed = 0
    for lp in cands:
        r = rows.get(lp)
        if not os.path.isfile(lp):
            kept["本地本来就没有"] += 1
            continue
        if not r or r.get("status") != "OK":
            kept["台账里没有这条或状态不是 OK（还没传验过）"] += 1
            continue
        size = os.path.getsize(lp)
        if size != int(r.get("bytes") or -1):
            kept["本地体积和上传时不一样了（传完又被改过）"] += 1
            continue
        if sha256(lp) != r["sha256"]:
            kept["本地哈希和台账对不上（这份可能被改糊过）"] += 1
            continue
        rs = remote_stat(a, r["remote_path"])
        if not rs:
            kept["网盘侧现在读不到这个路径"] += 1
            continue
        if rs["size"] != size:
            kept["网盘侧体积不符"] += 1
            continue
        ready.append((lp, size, r["remote_path"]))
        freed += size
    log("候选 %d 个文件：可腾 %d 个 / %.2f GB，留下 %d 个" % (len(cands), len(ready), freed / 1073741824.0, sum(kept.values())))
    for why, n in kept.most_common():
        log("  留 %5d 个：%s" % (n, why))
    for lp, size, rp in ready[:25]:
        log("   会删 %s（%.2f GB）← 网盘 %s" % (lp, size / 1073741824.0, rp))
    if len(ready) > 25:
        log("   …还有 %d 条" % (len(ready) - 25))
    if not ready:
        return 1
    if not args.yes:
        log("这是清单，一个字节都没删。确认过再加 --yes")
        return 0

    t0 = time.time()
    deleted = 0
    for lp, size, rp in ready:
        try:
            os.remove(lp)
        except OSError as exc:
            log("  删不掉，收手：%s（%s）" % (lp, exc))
            break
        rows[lp]["status"] = "PRUNED"
        rows[lp]["info"] = "网盘已核验（size %d + sha256 相符），本地腾掉于 %s" % (
            size, time.strftime("%Y-%m-%d %H:%M:%S"))
        deleted += 1
    save_ledger(list(rows.values()))
    log("腾完 %d 个 / %.2f GB｜%.0f s（哈希这趟是逐个现读的，慢在这里）"
        % (deleted, freed / 1073741824.0, time.time() - t0))
    return 0 if deleted == len(ready) else 1


def cmd_status(a, args):
    log("服务：%s:%d %s" % (HOST, PORT, "在听" if up() else "没起"))
    if not up():
        return 0
    if not a.token():
        return 1
    ms = mounts(a)
    if not ms:
        log("还没有任何挂载点。跑：py -3 netdisk_upload.py mount Quark")
    for m in ms:
        d = a.api("/api/fs/get", {"path": m["mount_path"]})
        log("  #%-3s %-16s 驱动 %-14s %s  %s" % (m["id"], m["mount_path"], m["driver"],
                                                 "停用" if m["disabled"] else "启用",
                                                 m["status"]))
    return 0


# 登记挂载点时，各驱动要填的字段（缺省就按 OpenList 返回的 schema 现问）
PROMPT_HELP = {
    "Quark": "cookie = 浏览器登录 pan.quark.cn 后 F12 里整串 Cookie；root_folder_id 留 0（根目录）",
    "BaiduNetdisk": "refresh_token = 百度网盘开放平台授权拿到的；root_folder_path 一般是 /",
    "Thunder": "username 带 +86；password 是迅雷账号密码（不是网盘验证码）",
}


def cmd_mount(a, args):
    driver = args.driver
    dl = a.get("/api/admin/driver/list")
    data = dl.get("data") or {}
    if driver not in data:
        raise SystemExit("这个 OpenList 没有叫 %s 的驱动，可选（能写的）：%s"
                         % (driver, ", ".join(sorted(
                             k for k, v in data.items()
                             if not (v.get("config") or {}).get("no_upload")))))
    cfg = data[driver].get("config") or {}
    if cfg.get("no_upload"):
        log("注意：%s 在这个版本里是只读驱动，传不进去" % driver)
    add = {}
    print("登记挂载点 %s（凭据只进 OpenList 自己的库，不落这个仓库，输入不回显）" % driver)
    for f in data[driver].get("additional") or []:
        name = f.get("name")
        if not name:
            continue
        dv = f.get("default")
        dv = "" if dv is None else str(dv)
        tip = "%s%s（可回车用默认）: " % (name, "*" if f.get("required") else "")
        val = getpass.getpass(tip) if re.search(r"(cookie|token|password|secret|key)", name, re.I) \
            else input(tip)
        add[name] = val.strip() or dv
    mount_path = input("挂到网盘目录用哪个路径名（回车用 /%s）: " % driver).strip() or ("/" + driver)
    if driver in PROMPT_HELP:
        log("提示：" + PROMPT_HELP[driver])
    body = {"mount_path": mount_path, "order": 0, "remark": "netdisk_upload 登记",
            "enabled": True, "driver": driver, "cache_expiration": 30,
            "addition": json.dumps(add, ensure_ascii=False)}
    r = a.api("/api/admin/storage/create", body)
    log("登记结果：code=%s %s" % (r.get("code"), str(r.get("message"))[:150]))
    if r.get("code") == 200:
        log("挂载点 %s 建好了。先单传一个文件试：%s" % (mount_path, "py -3 netdisk_upload.py upload --mount %s --file 某个文件" % mount_path))
    return 0 if r.get("code") == 200 else 1


def main():
    p = argparse.ArgumentParser(description="经本机 OpenList 把产物推到网盘")
    p.add_argument("cmd", choices=["status", "mount", "upload", "verify", "prune", "start", "stop"])
    p.add_argument("driver", nargs="?", default="", help="mount 子命令用的驱动名，如 Quark")
    p.add_argument("--scope", default="", help="只传清单里这一档")
    p.add_argument("--mount", default="", help="只传挂到这个路径的档")
    p.add_argument("--file", default="", help="只传这一个本地文件")
    p.add_argument("--as", dest="as_", default="", help="远端路径，配合 --file")
    p.add_argument("--dry-run", action="store_true", help="只列出会传什么，不真传")
    p.add_argument("--yes", action="store_true", help="prune 专用：核验通过的文件真删，不加就只出清单")
    args = p.parse_args()

    if args.cmd == "stop":
        stop_server()
        return 0
    if args.cmd == "start":
        return 0 if ensure_server() else 1
    if not ensure_server():
        return 1
    a = Auth()
    if args.cmd == "status":
        return cmd_status(a, args)
    if args.cmd == "mount":
        if not args.driver:
            raise SystemExit("mount 后面要跟驱动名，如：mount Quark / mount BaiduNetdisk / mount Thunder")
        return cmd_mount(a, args)
    if args.cmd == "verify":
        if not a.token():
            return 1
        return cmd_verify(a, args)
    if args.cmd == "prune":
        # 这条绝不能掉进下面的 upload 分支：那是「写盘」，这条是「删盘」
        if not a.token():
            return 1
        return cmd_prune(a, args)
    if not a.token():
        return 1
    return cmd_upload(a, args)


if __name__ == "__main__":
    sys.exit(main())
