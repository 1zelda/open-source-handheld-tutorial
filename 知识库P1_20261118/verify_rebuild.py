# -*- coding: utf-8 -*-
"""生产重建验证：新索引 vs v2 备份（zh 块逐块同 text_sha）+ v3 冻结件（ja 块逐块同文）。

只读核对，不写任何生产文件。用法：py -3 -u verify_rebuild.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NEW = ROOT / "_工具脚本" / "taspipe" / "游戏包" / "知识库" / "index.json"
OLD = HERE / "index_backup_v2_20261119.json"
V3 = HERE / "v3_index.json"


def main():
    new = json.loads(NEW.read_text(encoding="utf-8"))
    old = json.loads(OLD.read_text(encoding="utf-8"))
    v3 = json.loads(V3.read_text(encoding="utf-8"))
    fails = []

    def byfile(idx):
        d = {}
        for c in idx["chunks"]:
            d.setdefault(c["path"], []).append(c)
        return d

    nb, ob, vb = byfile(new), byfile(old), byfile(v3)
    if set(nb) != set(ob):
        fails.append(f"文件集不一致：新{len(nb)} 旧{len(ob)}")

    zh_same = zh_diff = 0
    for path, ochunks in ob.items():
        nchunks = nb.get(path, [])
        okeys = sorted((c["line_start"], c["line_end"], c["text_sha"]) for c in ochunks)
        nkeys = sorted((c["line_start"], c["line_end"], c["text_sha"]) for c in nchunks)
        if path in v3["rechunked"]:
            continue
        zh_same += len(ochunks)
        if okeys != nkeys:
            zh_diff += 1
            fails.append(f"zh 块漂移：{path}（旧{len(ochunks)}块 新{len(nchunks)}块）")

    ja_same = ja_diff = 0
    for path in v3["rechunked"]:
        vchunks = vb.get(path, [])
        nchunks = nb.get(path, [])
        ja_same += len(vchunks)
        vkeys = sorted((c["line_start"], c["line_end"], c["text"]) for c in vchunks)
        nkeys = sorted((c["line_start"], c["line_end"], c["text"]) for c in nchunks)
        if vkeys != nkeys:
            ja_diff += 1
            only_v = [k for k in vkeys if k not in nkeys][:2]
            only_n = [k for k in nkeys if k not in vkeys][:2]
            fails.append(f"ja 块不复现 v3：{path}（v3 {len(vchunks)}块 新{len(nchunks)}块）"
                         f" 仅v3={[(a, b) for a, b, _ in only_v]} 仅新={[(a, b) for a, b, _ in only_n]}")
        if not all(c.get("lang") == "ja" for c in nchunks):
            fails.append(f"ja 文件有块未标 lang=ja：{path}")

    langs = {"ja": 0, "zh": 0}
    for c in new["chunks"]:
        langs[c.get("lang", "zh")] += 1
    print(f"新索引总块数 {len(new['chunks'])}（ja={langs['ja']} zh={langs['zh']}）")
    print(f"v3 冻结件总块数 {len(v3['chunks'])}（{v3['stats']}）")
    print(f"zh 逐块同 sha：{zh_same} 块，漂移文件 {zh_diff}")
    print(f"ja 复现 v3：{ja_same} 块，不复现文件 {ja_diff}")
    if len(new["chunks"]) != len(v3["chunks"]):
        fails.append(f"总块数 {len(new['chunks'])} ≠ v3 {len(v3['chunks'])}")
    if fails:
        print("FAIL：")
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("VERIFY OK：zh 块与 v2 逐块同 sha，ja 块与 v3 冻结件逐块同文，总数一致")


if __name__ == "__main__":
    main()