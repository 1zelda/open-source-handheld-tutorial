"""RecompStore 目录层 diff：抓 catalog.json，与上次快照比对，点名新增/消失/改版的移植。

不动 源登记表.tsv 的抓取路径（那条 URL 不是 feed，交给生产 monitor 会天天报失败）。
产物：06-资讯监控/PS5移植商店/移植目录变更.md + _catalog_snapshot.json
"""
import json, os, time, urllib.request, datetime

ROOT = r"F:\开源掌机教程\06-资讯监控\PS5移植商店"
URL = "https://recompstore.com/catalog.json"
SNAP = os.path.join(ROOT, "_catalog_snapshot.json")
OUT = os.path.join(ROOT, "移植目录变更.md")


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 Chrome/120"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    d = json.loads(raw.decode("utf-8"))
    return raw, d


def index(d):
    out = {}
    for key in ["apps", "newerStoreApps", "v2Apps"]:
        for a in d.get(key, []):
            src = a.get("source") or {}
            out[a["id"]] = {
                "name": a.get("name"), "cat": a.get("category"), "kind": a.get("kind"),
                "ver": a.get("version"), "repo": src.get("repo") or "",
                "asset": src.get("asset") or "", "size": a.get("size") or "",
                "needs": a.get("needs") or "", "dev": a.get("dev") or "",
            }
    return out


def main():
    raw, d = fetch()
    now = index(d)
    prev = {}
    if os.path.exists(SNAP):
        prev = json.load(open(SNAP, encoding="utf-8")).get("index", {})
    added = [k for k in now if k not in prev]
    gone = [k for k in prev if k not in now]
    bumped = [k for k in now if k in prev and now[k]["ver"] != prev[k]["ver"]]

    lines = ["# PS5 移植目录变更（RecompStore catalog.json）", ""]
    lines += [f"- 抓取时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
              f"- 目录自报 updated：{d.get('updated')}",
              f"- 条目：本次 {len(now)} / 上次 {len(prev)}（字节 {len(raw):,}）",
              f"- 本次 diff：新增 {len(added)} / 下架 {len(gone)} / 改版 {len(bumped)}", ""]
    for lab, keys in (("新增", added), ("下架", gone), ("改版", bumped)):
        if not keys:
            continue
        lines.append(f"## {lab}（{len(keys)}）")
        for k in sorted(keys):
            n = now[k]
            old = prev.get(k, {})
            tail = f"  ← 原 v{old.get('ver')}" if lab == "改版" and old.get("ver") else ""
            need = f"｜要自备：{n['needs']}" if n["needs"] else ""
            lines.append(f"- **{n['name']}** v{n['ver']}｜{n['cat']}/{n['kind']}"
                         f"｜{n['repo']}｜{n['size']}{need}{tail}")
        lines.append("")
    open(OUT, "w", encoding="utf-8").write("\n".join(lines))
    json.dump({"fetched": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "updated": d.get("updated"), "index": now},
              open(SNAP, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"条目 {len(now)}（上次 {len(prev)}）新增 {len(added)} 下架 {len(gone)} 改版 {len(bumped)} -> {OUT}")


if __name__ == "__main__":
    main()
