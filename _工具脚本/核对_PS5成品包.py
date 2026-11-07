"""脱离下载流程，直接拿盘上的文件复算一遍 PS5 成品包台账。

看板里"在本地/缺档"是 os.path.exists 说了算，这里不信任何台账字段：
逐个台账行按 <成品包>/<作者>/<仓库>/<资产名> 找到真文件，量体积、算 sha256，
再跟台账里记的 bytes / digest 比；同时把盘上没人引用的包也点出来。

用法：
    py -3 _工具脚本\\核对_PS5成品包.py          # 全量（含哈希，约 10 GB 读取）
    py -3 _工具脚本\\核对_PS5成品包.py --fast   # 只比路径和体积，不算哈希
退出码：0 = 台账与磁盘完全对上；1 = 有任何一条对不上。
"""
import os, sys, io, json, hashlib, time

ROOT = r"F:\开源掌机教程\06-资讯监控\PS5移植商店"
BIN_DIR = os.path.join(ROOT, "成品包")
LEDGER = os.path.join(ROOT, "获取台账.tsv")
OUT = r"F:\开源掌机教程\_scratch\PS5成品包核对.md"
OUT_FAST = r"F:\开源掌机教程\_scratch\PS5成品包核对-fast.md"  # 别把全量哈希那份证据覆盖掉


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def read_ledger():
    txt = io.open(LEDGER, encoding="utf-8-sig").read().splitlines()
    head = txt[0].split("\t")
    return [dict(zip(head, l.split("\t"))) for l in txt[1:] if l.strip()]


def walk_disk():
    """返回 {相对路径(小写): (绝对路径, 字节数)}，按 作者/仓库/文件名 建索引。"""
    idx = {}
    for owner in sorted(os.listdir(BIN_DIR)):
        d1 = os.path.join(BIN_DIR, owner)
        if not os.path.isdir(d1):
            continue
        for repo in sorted(os.listdir(d1)):
            d2 = os.path.join(d1, repo)
            if not os.path.isdir(d2):
                continue
            for name in sorted(os.listdir(d2)):
                p = os.path.join(d2, name)
                if os.path.isfile(p):
                    idx[(owner + "/" + repo + "/" + name).lower()] = (p, os.path.getsize(p))
    return idx


def catalog_digests():
    """商店目录里只有 7 条写了 sha256 —— 这几条是真正的"上游给的参照"，
    其余 155 条台账里的哈希是我们自己首次下载时量出来的，只能证明"文件后来没变"。"""
    d = json.load(io.open(os.path.join(ROOT, "catalog.json"), encoding="utf-8"))
    out = {}
    for key in ("apps", "newerStoreApps", "v2Apps"):
        for x in d.get(key, []):
            if isinstance(x, dict) and (x.get("sha256") or "").strip():
                out[x.get("name", "")] = x["sha256"].strip().lower()
    return out


def main():
    fast = "--fast" in sys.argv
    out = OUT_FAST if fast else OUT
    rows = read_ledger()
    disk = walk_disk()
    cat = catalog_digests()
    hit = miss = size_bad = hash_bad = hash_ok = no_digest = no_asset = 0
    up_ok = up_bad = 0
    problems = []
    used = set()
    for r in rows:
        repo, asset = (r.get("repo") or "").strip(), (r.get("asset") or "").strip()
        if not asset:
            no_asset += 1
            problems.append(f"[无资产名] {repo} ｜ note={r.get('note', '')[:60]}")
            continue
        key = (repo + "/" + asset).lower()
        used.add(key)
        got = disk.get(key)
        if not got:
            miss += 1
            problems.append(f"[文件缺失] {repo}/{asset}")
            continue
        path, size = got
        want_size = int(r.get("bytes") or 0)
        if want_size and size != want_size:
            size_bad += 1
            problems.append(f"[体积不符] {repo}/{asset} 实到 {size} 应为 {want_size}")
            continue
        want = (r.get("digest") or "").replace("sha256:", "").strip()
        if fast:
            hit += 1
            continue
        if not want:
            no_digest += 1
            problems.append(f"[台账没记哈希] {repo}/{asset}")
            continue
        got_hash = sha256(path)
        ref = cat.get(r.get("name", ""))
        if ref:
            if got_hash == ref:
                up_ok += 1
            else:
                up_bad += 1
                problems.append(f"[与商店目录声明的哈希不符] {repo}/{asset} "
                                f"实算 {got_hash[:16]}… 声明 {ref[:16]}…")
        if got_hash == want:
            hash_ok += 1
            hit += 1
        else:
            hash_bad += 1
            problems.append(f"[哈希不符] {repo}/{asset}")

    orphans = [(k, v[1]) for k, v in disk.items() if k not in used]

    n = len(rows)
    lines = [
        f"# PS5 成品包核对（{time.strftime('%Y-%m-%d %H:%M')}，{'只比路径+体积' if fast else '逐文件复算 sha256'}）",
        "",
        f"台账 {n} 行 | 有资产名 {n - no_asset} | 命中且校验通过 {hit} | "
        f"文件缺失 {miss} | 体积不符 {size_bad} | 哈希不符 {hash_bad} | "
        f"台账缺哈希 {no_digest} | 台账无资产名 {no_asset} | 盘上没人引用的包 {len(orphans)}",
        "",
        f"盘上实际文件 {len(disk)} 个，合计 {sum(v[1] for v in disk.values())/1e9:.2f} GB"
        f"（台账行比文件多，是因为有的包被两行台账共用）",
        "",
        f"商店目录 `catalog.json` 里带 sha256 的共 {len(cat)} 条，"
        f"这一轮实际比对 **{up_ok + up_bad} 条：对上 {up_ok} / 对不上 {up_bad}**。"
        f"其余台账里的哈希是首次下载时自算的，只能证明「文件之后没变」，不是上游给的参照。"
        if not fast else "（--fast：本轮没算哈希，也没跟商店目录的声明比）",
        "",
    ]
    if problems:
        lines += ["## 对不上的条目", ""] + ["- " + p for p in problems] + [""]
    if orphans:
        lines += ["## 盘上多出来的包（台账没登记）", ""]
        lines += [f"- {k}（{sz} B）" for k, sz in sorted(orphans)] + [""]
    if not problems and not orphans:
        lines.append("全部对上：台账每一行都能在盘上找到体积与哈希都一致的包，"
                     "盘上也没有台账没登记的包。")
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")

    for l in lines[:12]:
        print(l)
    if problems or orphans:
        print(f"\n对不上 {len(problems)} 条 / 多余 {len(orphans)} 个，明细见 {out}")
    print(f"报告写出 {out}")
    return 1 if (problems or orphans) else 0


if __name__ == "__main__":
    sys.exit(main())
