# -*- coding: utf-8 -*-
"""P8 收尾反查（R5）：生产 index/corpus_map/sources/台账/npz mtime+sha256 与诊断前基线一致；
临时件全在 p8_scratch，生产索引仍 625 块、对照仍 index:false。
用法：py -3 -u p8_verify.py
"""
import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K  # noqa: E402
from taspipe import sources as S  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRATCH = HERE / "p8_scratch"
BASELINE = SCRATCH / "prod_baseline.json"


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    before = json.loads(BASELINE.read_text(encoding="utf-8"))
    files = [K.INDEX_JSON, K.CORPUS_MAP, S.REG_JSON, S.LEDGER_JSON,
             K.INDEX_JSON.with_name("embeddings_09096a016496.npz")]
    diff = []
    for p in files:
        p = Path(p)
        now = ({"mtime_ns": p.stat().st_mtime_ns, "sha256": _sha(p),
                "bytes": p.stat().st_size} if p.is_file() else None)
        was = before.get(str(p))
        same = (was == now)
        print(f"  {p.name}: {'一致 OK' if same else '!!! 变动'} "
              f"{(now or {}).get('sha256', 'MISSING')[:12] if now else 'MISSING'}")
        if not same:
            diff.append(p.name)
    # 生产索引块数 + 对照仍 index:false
    idx = json.loads(Path(K.INDEX_JSON).read_text(encoding="utf-8"))
    m = json.loads(Path(K.CORPUS_MAP).read_text(encoding="utf-8"))
    dz = [e for e in m["entries"] if "对照" in e["path"]]
    print(f"\n  生产索引块数={idx['stats']['N']}（应 625）")
    print(f"  对照登记 index:false 保持: {all(e.get('index') is False for e in dz)}（{len(dz)} 条）")
    # scratch 临时件清单
    print("\n  scratch 临时件（诊断产物，可清）:")
    for p in sorted(SCRATCH.iterdir()):
        print(f"    {p.name}  {p.stat().st_size}B")
    ok = (not diff) and idx["stats"]["N"] == 625 and all(e.get("index") is False for e in dz)
    print(f"\n[R5 反查] {'生产零污染 OK' if ok else '!!! 生产被污染或块数/登记异常'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()