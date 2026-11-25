# -*- coding: utf-8 -*-
"""P8 给临时再索引建稠密指纹件（venv + CUDA）。只写 scratch 临时 npz，生产 npz 不碰。
用法：export HF_HUB_CACHE=F:/kb_pilot_hf_cache; venv/Scripts/python.exe -u p8_dense.py
"""
import hashlib
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb_dense as D  # noqa: E402
from taspipe import kb as K  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRATCH = HERE / "p8_scratch"
TI = SCRATCH / "index_reindex.json"


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    prod_npz = K.INDEX_JSON.with_name("embeddings_09096a016496.npz")
    before = (_sha(prod_npz), prod_npz.stat().st_mtime_ns) if prod_npz.is_file() else None
    print("临时索引:", TI, "chunks=", len(__import__("json").loads(TI.read_text(encoding="utf-8"))["chunks"]), flush=True)
    rep = D.build_dense(str(TI))
    print("dense built:", rep, flush=True)
    after = (_sha(prod_npz), prod_npz.stat().st_mtime_ns) if prod_npz.is_file() else None
    print("[反查 R5] 生产 npz 变动:", "无 OK" if before == after else f"!!! {before} -> {after}", flush=True)
    if before != after:
        sys.exit(1)


if __name__ == "__main__":
    main()