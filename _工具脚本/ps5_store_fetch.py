"""RecompStore 目录批量获取：源码 clone + 成品包下载 + sha256 校验 + 解包复检。

台账来源：catalog.json（商店目录）与 ps5_assets.tsv（各仓库 release 资产快照，
由 `_工具脚本/ps5_assets_snapshot.py` 生成 —— 它取"最新一个带资产的 release"，pre-release 也算。
幂等：已存在且哈希相符则跳过；不符则重下。
"""
import os, sys, json, subprocess, hashlib, zipfile, tarfile, io, time, fnmatch, shutil, atexit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ps5_assets_snapshot import env  # 代理 7890 没开时 gh 会全线失败，见该函数注释

ROOT = r"F:\开源掌机教程\06-资讯监控\PS5移植商店"
SCR = r"F:\开源掌机教程\_scratch"
GH = r"C:\Users\Administrator/.workbuddy/binaries/gh/bin/gh.exe"
SRC_DIR = os.path.join(ROOT, "源码")
BIN_DIR = os.path.join(ROOT, "成品包")
LEDGER = os.path.join(ROOT, "获取台账.tsv")
LOG = os.path.join(ROOT, "获取日志.txt")
CLONE_MB_CAP = 800

os.makedirs(SRC_DIR, exist_ok=True)
os.makedirs(BIN_DIR, exist_ok=True)


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


LOCK = LEDGER + ".lock"


def acquire_lock():
    """一次只让一个进程写台账。
    11-04 实测：两个跑批同时在写，后写的那个把前一个刚复算好的 149 条 verify 结论抹成了空。"""
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        who, age = "?", 0.0
        try:
            with io.open(LOCK, encoding="utf-8") as fh:
                who = fh.read().strip()
            age = (time.time() - os.path.getmtime(LOCK)) / 60
        except OSError:
            pass
        sys.exit(f"另一个 ps5_store_fetch 正在写台账（PID {who}，锁已存在 {age:.0f} 分钟）。\n"
                 f"等它跑完再跑；确认它早断了就手动删 {LOCK}")
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)

    def release():
        if os.path.exists(LOCK):
            os.remove(LOCK)

    atexit.register(release)


def dir_mb(path):
    total = 0
    for r, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return total / 1e6


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def own_copy(needs):
    n = (needs or "").lower()
    return any(k in n for k in ["iso", "disc", "wad", "game files", "game data",
                                "own ", "your copy", "gog", "title update"])


# 疑似原厂游戏数据的特征文件名（扫包复检用，不是判据只是点名）
SUSPECT = [".usm", ".pak", ".bf", ".wtf", ".mod", ".fgc", ".xexp", ".arb",
           "audio_bank", "movies/", ".ogg.patch"]


def audit_zip(path):
    """返回 (成员数, 总解压字节, 命中的疑似原厂数据特征)。"""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            total = sum(i.file_size for i in z.infolist())
    except Exception as e:
        return (None, None, f"打不开:{e}")
    low = [n.lower() for n in names]
    hits = sorted({s for s in SUSPECT for n in low if s in n})
    return (len(names), total, hits)


def load():
    d = json.load(open(os.path.join(SCR, "cat.json"), encoding="utf-8"))
    all_ = {}
    for k in ["apps", "newerStoreApps", "v2Apps"]:
        for a in d.get(k, []):
            all_[a["id"]] = a
    assets = {}
    for ln in open(os.path.join(SCR, "ps5_assets.tsv"), encoding="utf-8").read().splitlines()[1:]:
        p = ln.split("\t")
        if len(p) < 3:
            continue
        items = []
        for it in p[2].split(" ;; "):
            if not it.strip():
                continue
            nm_sz, _, dg = it.rpartition(" sha256:")
            name, _, size = nm_sz.rpartition(" ")
            items.append((name, int(size or 0), dg))
        assets[p[0]] = (p[1], items)
    return all_, assets


def pick(a, assets):
    src = a.get("source") or {}
    repo, pat = src.get("repo"), src.get("asset")
    if repo not in assets:
        return repo, None, None, "仓库无 release 记录"
    tag, items = assets[repo]
    if not items:
        # 旧版快照是拿 /releases/latest 抓的，只有 pre-release 的仓库必定 404，
        # 那 404 的 JSON 正文会被原样写进 tag 列。这种行不能算"上游没包"，要点名去重建快照。
        if "Not Found" in (tag or "") or (tag or "").startswith("{"):
            return repo, None, None, "快照坏行(/releases/latest 返回 404)：跑 ps5_assets_snapshot.py 重建"
        return repo, None, None, "该 release 没有资产"
    hit = [i for i in items if pat and fnmatch.fnmatch(i[0], pat)]
    note = ""
    if not hit:
        hit = [i for i in items if i[0].lower().endswith((".zip", ".pkg", ".7z", ".tar.gz"))]
        note = f"pattern {pat} 未命中, 回退到压缩资产"
    if not hit:
        return repo, None, None, f"无可用资产 (pattern={pat})"
    name, size, dg = max(hit, key=lambda x: x[1])
    return repo, (tag, name, size, dg), note, ""


def strip_verify(note):
    """去掉旧 note 里上一轮跑出来的校验尾巴，这一轮的结论必须由这一轮的实测给出。"""
    return " ".join(t for t in (note or "").split()
                    if not t.startswith("verify=") and t != "缺档")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    acquire_lock()
    all_, assets = load()
    rows = []
    for a in all_.values():
        repo, chosen, note, err = pick(a, assets)
        rows.append({"name": a["name"], "cat": a.get("category"), "repo": repo,
                     "needs": a.get("needs", ""), "own": own_copy(a.get("needs")),
                     "tag": chosen[0] if chosen else "", "asset": chosen[1] if chosen else "",
                     "bytes": chosen[2] if chosen else 0, "digest": chosen[3] if chosen else "",
                     "note": note or err})
    # 旧台账里已经跑出来的 audit/digest 按名字接回来。任何模式重写台账前都要接：
    # 上一版只在 ledger 模式接，结果 bin 跑一遍把 148 条解包复检整列写空（11-04 踩过）。
    old = {}
    if os.path.exists(LEDGER):
        with io.open(LEDGER, encoding="utf-8-sig") as fh:
            txt = fh.read().splitlines()
        if txt:
            head = txt[0].split("\t")
            for line in txt[1:]:
                d = dict(zip(head, line.split("\t")))
                old[(d.get("name"), d.get("repo"))] = d
    only = {x.strip() for x in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if x.strip()}
    # 只有本轮真会量文件的行才清掉旧 verify 结论：ledger/src 模式不下载不哈希，
    # 定点模式也只处理挑出来的那几个仓库，其余行必须原样续用。
    # （11-04 一次并发的 ledger 跑把 149 条已复算好的结论抹成了空，就是这个闸门没立住。）
    measures = mode in ("all", "bin", "verify")
    touched = 0
    for r in rows:
        d = old.get((r["name"], r.get("repo") or ""))
        if d:
            r["audit"] = d.get("audit") or r.get("audit") or ""
            if d.get("digest"):
                r["digest"] = d["digest"]
            if not (r["note"] or ""):
                hit = measures and (not only or (r.get("repo") or "") in only)
                n = strip_verify(d.get("note")) if hit else (d.get("note") or "")
                touched += 1 if hit else 0
                # 上一轮这行判的是"无可用资产"，这一轮已经解析到资产了 —— 旧结论过期，别接回来。
                if r["asset"] and n.startswith("无可用资产"):
                    n = ""
                r["note"] = n
    log(f"接回旧台账 {len(old)} 条（audit/digest 按名字续用；本轮重算 verify 结论 {touched} 条，"
        f"其余原样续用）")

    todo_bin = [r for r in rows if r["asset"]]
    todo_src = [r for r in rows if r["repo"] and not r["own"]]
    if only:
        todo_bin = [r for r in todo_bin if r["repo"] in only]
        todo_src = [r for r in todo_src if r["repo"] in only]
        log(f"定点模式：只处理 {len(only)} 个仓库（台账仍整本重写，其余行原样接回）")

    if mode in ("all", "src"):
        log(f"源码档：{len(todo_src)} 个仓库（不含需自备原厂数据的 39 个）")
        seen = set()
        for r in todo_src:
            if r["repo"] in seen:
                continue
            seen.add(r["repo"])
            dst = os.path.join(SRC_DIR, r["repo"].replace("/", "__"))
            if os.path.isdir(dst):
                log(f"  跳过已存在 {r['repo']} ({dir_mb(dst):.0f} MB)")
                continue
            p = subprocess.run([GH, "repo", "clone", r["repo"], dst, "--", "--depth", "1"],
                               capture_output=True, text=True, env=env())
            if p.returncode != 0:
                log(f"  CLONE FAIL {r['repo']}: {p.stderr.strip()[:120]}")
                continue
            mb = dir_mb(dst)
            if mb > CLONE_MB_CAP:
                shutil.rmtree(dst, ignore_errors=True)
                log(f"  超 {CLONE_MB_CAP}MB 弃 clone，只留元数据 {r['repo']} ({mb:.0f} MB)")
                r["note"] = (r["note"] + f" clone弃:{mb:.0f}MB").strip()
            else:
                log(f"  cloned {r['repo']} {mb:.0f} MB")

    if mode in ("all", "bin"):
        log(f"成品档：{len(todo_bin)} 个资产，共 {sum(r['bytes'] for r in todo_bin)/1e9:.2f} GB")
        done = fail = skip = 0
        for i, r in enumerate(todo_bin, 1):
            d = os.path.join(BIN_DIR, r["repo"].split("/")[0], r["repo"].split("/")[1])
            os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, r["asset"])
            want = r["digest"].replace("sha256:", "")
            if os.path.isfile(dst) and want and sha256(dst) == want:
                skip += 1
                # 这一行也当场量过哈希了，结论就得由这一行自己写：
                # 早先跳过分支不写 note，台账重跑一遍会把 149 条 verify 抹成空。
                r["note"] = (r["note"] + " verify=OK").strip()
                if i % 20 == 0:
                    log(f"  {i}/{len(todo_bin)} 进度（跳过相符 {skip}）")
                continue
            # 上轮文件已经落盘、台账里却没有参照哈希（补 asset 的那批就是这种）：
            # 按体积认下它并当场自算哈希入库，别删掉重下一遍。
            adopt = (not want and r["bytes"] and os.path.isfile(dst)
                     and os.path.getsize(dst) == int(r["bytes"]))
            if not adopt:
                if os.path.isfile(dst):
                    os.remove(dst)
                p = subprocess.run([GH, "release", "download", r["tag"], "-R", r["repo"],
                                    "-p", r["asset"], "-D", d],
                                   capture_output=True, text=True, env=env())
                if p.returncode != 0 or not os.path.isfile(dst):
                    fail += 1
                    # gh 断线会留下半截 zip。留着它，看板那句 os.path.exists 就会把残包判成"在本地"，
                    # 台账也会一直显示绿——所以失败必须当场删干净，让下一轮真的重下。
                    if os.path.isfile(dst):
                        log(f"  删残包 {r['repo']}/{r['asset']}（{os.path.getsize(dst)} B，"
                            f"应为 {r['bytes']} B）")
                        os.remove(dst)
                    log(f"  DL FAIL {r['repo']} {r['asset']}: {(p.stderr or '').strip()[:110]}")
                    continue
                if r["bytes"] and os.path.getsize(dst) != int(r["bytes"]):
                    fail += 1
                    sz = os.path.getsize(dst)
                    os.remove(dst)
                    log(f"  体积不符 {r['repo']}/{r['asset']}: 实到 {sz} 应为 {r['bytes']}，已删待重下")
                    continue
            got = sha256(dst)
            if want:
                r["note"] = (r["note"] + f" verify={'OK' if got == want else 'MISMATCH'}").strip()
                if got != want:
                    fail += 1
                    log(f"  哈希不符 {r['repo']}/{r['asset']}")
                    continue
            else:
                # 快照里没有参照哈希（刚补上的那批就是这种）：把当场量到的记进台账，
                # 下次跑才有得比；note 里说清这是自算的，不是上游给的。
                r["digest"] = "sha256:" + got
                r["note"] = (r["note"] + " verify=首次(自算哈希,非上游提供)").strip()
            if dst.lower().endswith(".zip"):
                n, uz, hits = audit_zip(dst)
                r["audit"] = f"{n}成员/{uz/1e6:.0f}MB/疑似原厂数据:{hits if hits else '无'}"
            done += 1
            if i % 15 == 0:
                log(f"  {i}/{len(todo_bin)} 已成 {done} 失败 {fail}")
        log(f"成品档完成：成功 {done} / 跳过已相符 {skip} / 失败 {fail}")

    if mode in ("all", "bin", "ledger", "verify"):
        # 台账里 verify 这一路必须是"当场量本地文件"得到的，不能沿用上次跑出来的话。
        # ledger 模式刚把 note 重置成目录元数据，所以两种模式都补这一遍（7.5 GB 全量哈希约几分钟）。
        if mode in ("ledger", "verify"):
            ok = bad = absent = noref = audited = 0
            for r in todo_bin:
                dst = os.path.join(BIN_DIR, r["repo"].split("/")[0], r["repo"].split("/")[1],
                                   r["asset"])
                want = r["digest"].replace("sha256:", "")
                if not os.path.isfile(dst):
                    r["note"] = (r["note"] + " 缺档").strip()
                    absent += 1
                elif want and sha256(dst) != want:
                    r["note"] = (r["note"] + " verify=MISMATCH").strip()
                    bad += 1
                elif not want:
                    r["note"] = (r["note"] + " verify=无参照(只判文件在)").strip()
                    noref += 1
                else:
                    r["note"] = (r["note"] + " verify=OK").strip()
                    ok += 1
                    # 两行台账共用同一个包时（PerfectEye 那对），下载那轮只有一行拿到成员清点，
                    # 另一行永远空着 —— 复算这遍顺手补齐，别留个像"没检查过"的空格。
                    if not (r.get("audit") or "").strip() and dst.lower().endswith(".zip"):
                        n, uz, hits = audit_zip(dst)
                        r["audit"] = f"{n}成员/{uz/1e6:.0f}MB/疑似原厂数据:{hits if hits else '无'}"
                        audited += 1
            log(f"verify：OK {ok} / 不符 {bad} / 缺档 {absent} / 无参照 {noref} / 补成员清点 {audited}")

    hdr = ["name", "category", "repo", "needs_own_copy", "needs", "asset", "bytes",
           "digest", "note", "audit"]
    # 表头列名和行字典的键不是一套（cat / own / audit），必须显式映射。
    # 上一版直接按列名 r.get("category")，结果 category 与 needs_own_copy 两列整本写空。
    with io.open(LEDGER, "w", encoding="utf-8", newline="\n") as f:
        f.write("\t".join(hdr) + "\n")
        for r in sorted(rows, key=lambda x: (not x["own"], x["cat"] or "", x["name"])):
            rec = {"name": r["name"], "category": r.get("cat") or "",
                   "repo": r.get("repo") or "", "needs_own_copy": "1" if r["own"] else "0",
                   "needs": r.get("needs") or "", "asset": r.get("asset") or "",
                   "bytes": r.get("bytes") or 0, "digest": r.get("digest") or "",
                   "note": r.get("note") or "", "audit": r.get("audit") or ""}
            vals = [str(rec[k]).replace("\t", " ").replace('"', "'") for k in hdr]
            f.write("\t".join(vals) + "\n")
    log(f"台账写出 {LEDGER}（{len(rows)} 行）")


if __name__ == "__main__":
    main()
