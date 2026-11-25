# -*- coding: utf-8 -*-
"""验证未批准稠密层不激活，并复核旧最终交付指纹未变。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261125_source_audit_fix"
KB_DIR = ROOT / "_工具脚本/taspipe/游戏包/知识库"
sys.path.insert(0, str(ROOT / "_工具脚本"))

from taspipe import kb as K
from taspipe import kb_dense as KD


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def state(paths):
    return {
        str(p): {
            "exists": p.is_file(),
            "size": p.stat().st_size if p.is_file() else None,
            "mtime_ns": p.stat().st_mtime_ns if p.is_file() else None,
            "sha256": sha(p) if p.is_file() else None,
        }
        for p in paths
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    protected = [
        ROOT / "知识库改进优化指导_2026-11-24_strict片段修正回填.md",
        ROOT / "知识库P1_20261118/kb_final_20261124/final_manifest_after_strict_citation_fix_20261124.json",
        ROOT / "知识库P1_20261118/kb_final_20261124/artifact_inventory_after_strict_citation_fix_20261124.json",
    ]
    before = state(protected)
    expected = {
        str(protected[0]): "66c1bdeb0f3cde492751cbfbea237c6ff3083eb4218927481b5a833139635657",
        str(protected[1]): "7855b800e0862ce551e3aeb211f362c931f27ba067869f4de3b532f30ba2d934",
        str(protected[2]): "e728670c4aea20544a0bc719432435b1d7efc34bbce52e80d88ea99e8ac8b9fd",
    }
    actual = {p: info["sha256"] for p, info in before.items()}
    base_index = KB_DIR / "index.json"
    hybrid_index = KB_DIR / "index_hybrid.json"
    ready_base = KD.ready(base_index)
    ready_hybrid = KD.ready(hybrid_index)
    selected_index, domain_local = K._select_index(None)
    base_production_dense = [
        KD.npz_path(base_index).is_file(),
        KD.npz_path(hybrid_index).is_file(),
    ]
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (base_index, hybrid_index)]
    probe_files = [OUT / f"dense_probe/embeddings_{value[:12]}.npz" for value in hashes]

    prior = json.loads((OUT / "regression_base_20261125.json").read_text(encoding="utf-8"))
    questions = json.loads((ROOT / "知识库P1_20261118/p2_questions_ext.json")
                           .read_text(encoding="utf-8"))["questions"]
    questions += json.loads((ROOT / "知识库P1_20261118/probe_questions_ext.json")
                            .read_text(encoding="utf-8"))["questions"]
    qmap = {q["id"]: q for q in questions}
    rows = []
    for old in prior["rows"]:
        q = qmap[old["id"]]
        f = q.get("filters", {})
        answer = K.query(q["q"], game=f.get("game"), revision=f.get("revision"),
                         platform=f.get("platform"), topk=30, top_window=3)
        locators = [h.get("locator") for h in answer.get("selected_evidence") or []]
        expected_arm = old["arms"]["base_default"]
        expected_locators = [h.get("locator") for h in expected_arm["selected"]]
        rows.append({
            "id": q["id"],
            "status": answer["status"],
            "expected_status": expected_arm["status"],
            "selected_locators": locators,
            "expected_locators": expected_locators,
            "retrieval": answer.get("retrieval"),
            "index_used": answer.get("index_used"),
            "unchanged": answer["status"] == expected_arm["status"] and locators == expected_locators,
        })
    after = state(protected)
    changed = [p for p in before if before[p] != after[p]]
    old_hash_ok = all(actual.get(p) == v for p, v in expected.items())
    result = {
        "schema": "kb_dense_isolation_verification_v1",
        "production_dense_present": {
            "base": base_production_dense[0],
            "hybrid": base_production_dense[1],
        },
        "dense_ready": {"base": ready_base, "hybrid": ready_hybrid},
        "auto_index": str(selected_index),
        "auto_domain_local": domain_local,
        "auto_index_is_base": Path(selected_index) == base_index,
        "probe_files": [{"path": str(p), "exists": p.is_file(),
                         "size": p.stat().st_size if p.is_file() else None,
                         "sha256": sha(p) if p.is_file() else None} for p in probe_files],
        "base_rows": rows,
        "base_query_count": len(rows),
        "base_queries_unchanged": all(r["unchanged"] for r in rows),
        "old_delivery_expected_hashes": expected,
        "old_delivery_actual_hashes": actual,
        "old_delivery_hashes_ok": old_hash_ok,
        "old_delivery_state_changed": changed,
        "all_checks_ok": (
            not any(base_production_dense)
            and ready_base[0] is False and ready_hybrid[0] is False
            and Path(selected_index) == base_index
            and all(p.is_file() for p in probe_files)
            and all(r["unchanged"] for r in rows)
            and old_hash_ok and not changed
        ),
    }
    target = OUT / "dense_isolation_verification_20261125.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in (
        "production_dense_present", "dense_ready", "auto_index", "auto_domain_local",
        "base_query_count", "base_queries_unchanged", "old_delivery_hashes_ok",
        "old_delivery_state_changed", "all_checks_ok")}, ensure_ascii=False, indent=2))
    return 0 if result["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
