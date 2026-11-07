"""重建 PS5 商店的 release 资产快照 `_scratch/ps5_assets.tsv`。

为什么要这个脚本:上一版快照是拿 `repos/{repo}/releases/latest` 抓的,而 GitHub 这个接口
在"只有 pre-release 的仓库"上必定返回 404 —— PS5 商店里有 13 个项目的最新包就是 alpha/beta/rc,
于是快照里那 13 行的 tag 列被写成了一段 404 JSON 正文,台账就跟着判成"无可用资产"。
这里改成列全部 releases,取**最新一个带资产的 release**(允许 pre-release,跳过 draft)。

用法:
    py -3 _工具脚本/ps5_assets_snapshot.py            # 只修坏行/缺行,好行原样保留
    py -3 _工具脚本/ps5_assets_snapshot.py --all      # 全部仓库重查一遍(gh api 有额度,慢)
    py -3 _工具脚本/ps5_assets_snapshot.py --check    # 只报告,不写文件

写完之后跑 `py -3 _工具脚本/ps5_store_fetch.py bin` 才会真下载。
"""
import io
import json
import os
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREA = os.path.join(ROOT, "06-资讯监控", "PS5移植商店")
SCR = os.path.join(ROOT, "_scratch")
SNAP = os.path.join(SCR, "ps5_assets.tsv")
CATJSON = os.path.join(AREA, "catalog.json")
LOG = os.path.join(AREA, "获取日志.txt")
GH = os.path.expanduser(r"~\.workbuddy\binaries\gh\bin\gh.exe")
if not os.path.isfile(GH):
    GH = "gh"

HDR = ["repo", "tag", "assets(name|bytes|digest)", "has_release"]
BUCKETS = ["apps", "newerStoreApps", "v2Apps", "comingSoon", "comingSoonV2"]


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with io.open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def env():
    """代理口不写死（7890→7891 换过一次），探到哪个用哪个；一个都不活就清空变量直连——
    写死或原样继承旧口的 HTTPS_PROXY 会让每个 gh 调用失败，而本机直连其实是通的。"""
    import net_proxy
    return net_proxy.env()


def gh_releases(repo):
    """返回该仓库全部 release(按 GitHub 给的顺序,新在前);取不到返回 None。"""
    r = subprocess.run([GH, "api", "repos/%s/releases?per_page=100" % repo],
                       capture_output=True, env=env(), timeout=120)
    if r.returncode != 0:
        return None
    try:
        d = json.loads(r.stdout.decode("utf-8", "replace"))
    except ValueError:
        return None
    return d if isinstance(d, list) else None


def pick_release(rels):
    """最新一个『有资产且不是草稿』的 release。pre-release 要,因为它常常就是唯一的一版。"""
    for rel in rels or []:
        if rel.get("draft"):
            continue
        if rel.get("assets"):
            return rel
    return None


def read_snap():
    out = {}
    if not os.path.isfile(SNAP):
        return out
    lines = io.open(SNAP, encoding="utf-8").read().splitlines()
    for ln in lines[1:]:
        p = ln.split("\t")
        if len(p) < 2 or not p[0]:
            continue
        out[p[0]] = {"tag": p[1], "assets": p[2] if len(p) > 2 else "",
                    "has": p[3] if len(p) > 3 else ""}
    return out


def known_digests(cell):
    """把旧快照那格 'name bytes sha256:xxx ;; ...' 拆成 {文件名: 哈希}。"""
    out = {}
    for it in (cell or "").split(" ;; "):
        it = it.strip()
        if not it:
            continue
        nm_sz, _, dg = it.rpartition(" sha256:")
        name, _, _size = nm_sz.rpartition(" ")
        out[name] = dg
    return out


def broken(rec):
    """坏行 = 压根没有,或者 tag 列被写成了 GitHub 的错误正文,或者资产格是空的。"""
    if rec is None:
        return True
    tag = rec.get("tag") or ""
    if "Not Found" in tag or '"message"' in tag or tag.startswith("{"):
        return True
    return not (rec.get("assets") or "").strip()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    check = mode == "--check"
    cat = json.load(io.open(CATJSON, encoding="utf-8"))
    repos = []
    for b in BUCKETS:
        for e in cat.get(b) or []:
            if not isinstance(e, dict):
                continue
            src = e.get("source") or {}
            r = (src.get("repo") or "").strip("/")
            if r and r not in repos:
                repos.append(r)
    snap = read_snap()
    for r in snap:
        if r not in repos:
            repos.append(r)
    log("快照重建：目录+快照共 %d 个仓库｜模式 %s" % (len(repos), mode or "只修坏行"))

    fixed = kept = failed = 0
    detail = []
    for repo in repos:
        old = snap.get(repo)
        if mode != "--all" and not broken(old):
            kept += 1
            continue
        rels = gh_releases(repo)
        if rels is None:
            failed += 1
            detail.append((repo, "gh api 失败", ""))
            log("  取不到 %s（gh api 失败或仓库不存在）" % repo)
            continue
        rel = pick_release(rels)
        if not rel:
            snap[repo] = {"tag": "", "assets": "", "has": "NO_RELEASE"}
            failed += 1
            detail.append((repo, "无带资产的 release", "%d 个 release" % len(rels)))
            log("  无可用 release %s（列了 %d 个 release，都没资产或全是草稿）" % (repo, len(rels)))
            continue
        dg = known_digests((old or {}).get("assets"))
        cell = " ;; ".join("%s %s sha256:%s" % (a["name"], a.get("size", 0), dg.get(a["name"], ""))
                           for a in rel["assets"])
        snap[repo] = {"tag": rel.get("tag_name") or "", "assets": cell,
                      "has": "OK%s" % ("-PRE" if rel.get("prerelease") else "")}
        fixed += 1
        detail.append((repo, snap[repo]["tag"], "%d 个资产" % len(rel["assets"])))
        log("  补 %s -> %s%s（%d 个资产）" % (repo, snap[repo]["tag"],
            " [pre-release]" if rel.get("prerelease") else "", len(rel["assets"])))

    if check:
        log("--check：本会改 %d 行、保留 %d 行、取不到 %d 行（没写文件）" % (fixed, kept, failed))
        return
    tmp = SNAP + ".new"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\t".join(HDR) + "\n")
        for repo in sorted(snap):
            v = snap[repo]
            fh.write("\t".join([repo, v["tag"], v["assets"], v["has"]]) + "\n")
    os.replace(tmp, SNAP)
    log("写出 %s（%d 行）｜本次改 %d / 保留 %d / 取不到 %d" % (SNAP, len(snap), fixed, kept, failed))
    rep = os.path.join(SCR, "ps5_快照重建.md")
    with io.open(rep, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# PS5 release 资产快照重建（%s）\n\n" % time.strftime("%Y-%m-%d %H:%M"))
        fh.write("改 %d 行 / 保留 %d 行 / 取不到 %d 行。判据：取最新一个带资产且非草稿的 release，"
                 "pre-release 也算（`releases/latest` 接口会漏掉只有 pre-release 的仓库）。\n\n"
                 % (fixed, kept, failed))
        fh.write("| 仓库 | 结果 | 备注 |\n| --- | --- | --- |\n")
        for repo, tag, note in detail:
            fh.write("| %s | %s | %s |\n" % (repo, tag, note))
    log("报告 %s" % rep)


if __name__ == "__main__":
    main()
