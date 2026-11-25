"""CX4 真机 A/B 的准备件：走生产 resolve/assess，把 5628 的回放身份落盘。

只读网盘外的本地资源，不下载、不改模拟器安装目录。"""
import json
import os
import sys

sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import registry as R  # noqa: E402

PUB = 5628
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assess_5628.json")


def main():
    lib = R.DEFAULT_LIB
    pubs = {int(p["id"]): p for p in R.load_publications(lib)}
    pub = pubs[PUB]
    ri = R.index_roms(lib)
    vi = R.index_versions(lib)
    bh = R.discover_bizhawk(R.DEFAULT_EMU)
    a = R.assess(pub, lib, ri, vi, bh)
    need = a.get("rom_sha1") or pub.get("rom_sha1")
    hits = ri.get(need.upper(), ri.get(need.lower(), [])) if need else []
    blob = json.dumps({"assess": a, "rom_hits_by_sha1": hits,
                       "bizhawk_found": {k: str(v) for k, v in (bh or {}).items()}},
                      ensure_ascii=False, indent=1, default=str)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(blob)
    print("wrote", OUT, len(blob), "bytes")
    print("rom_sha1 need:", need)
    print("rom hits:", hits[:6])
    for k in ("ready", "blockers", "movie", "rom", "core", "system", "bizhawk_dir"):
        if k in a:
            print("  %-11s %s" % (k, str(a[k])[:200]))


main()
