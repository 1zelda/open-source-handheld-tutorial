# -*- coding: utf-8 -*-
"""暂存新稠密探针、重跑 hybrid 双臂，并在 finally 恢复生产隔离。"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261125_source_audit_fix"
PROD = ROOT / "_工具脚本/taspipe/游戏包/知识库"
BASE = PROD / "index.json"
HYBRID = PROD / "index_hybrid.json"
PYTHON = Path("F:/kb_pilot_venv/Scripts/python.exe")


def dense_path(index):
    import hashlib
    return PROD / f"embeddings_{hashlib.sha256(index.read_bytes()).hexdigest()[:12]}.npz"


def run():
    sys.stdout.reconfigure(encoding="utf-8")
    probes = [(OUT / "dense_probe" / dense_path(index).name, dense_path(index)) for index in (BASE, HYBRID)]
    assert all(source.is_file() for source, _ in probes)
    assert all(not target.exists() for _, target in probes), "生产目录已有稠密件，拒绝覆盖"
    created = []
    env = {**os.environ, "HF_HUB_CACHE": "F:/kb_pilot_hf_cache", "HF_HUB_OFFLINE": "1",
           "NO_PROXY": "localhost,127.0.0.1", "PYTHONIOENCODING": "utf-8"}
    try:
        for source, target in probes:
            shutil.copy2(source, target)
            created.append(target)
        subprocess.run([str(PYTHON), "-u", str(OUT / "regression_source_inheritance_20261125.py"),
                        "--arms", "hybrid_default", "hybrid_strict", "--out",
                        str(OUT / "regression_hybrid_20261125.json")], cwd=ROOT / "_工具脚本",
                       env=env, check=True)
        subprocess.run([sys.executable, "-u", str(OUT / "regression_source_inheritance_20261125.py"),
                        "--combine", str(OUT / "regression_base_20261125.json"),
                        str(OUT / "regression_hybrid_20261125.json"), "--out",
                        str(OUT / "regression_source_inheritance_20261125.json")], check=True)
        subprocess.run([sys.executable, "-u", str(OUT / "summarize_arm_audit_20261125.py")], check=True)
    finally:
        for target in created:
            target.unlink(missing_ok=True)
        assert all(not target.exists() for _, target in probes)
        print("生产稠密件已全部清理", flush=True)
    subprocess.run([sys.executable, "-u", str(OUT / "verify_dense_isolation_20261125.py")], check=True)
    print("DENSE_ARM_RERUN_OK_AND_ISOLATED", flush=True)


if __name__ == "__main__":
    run()
