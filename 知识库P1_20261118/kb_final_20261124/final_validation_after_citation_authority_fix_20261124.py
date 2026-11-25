# -*- coding: utf-8 -*-
"""最终只读核验：共享哈希、清单逐件哈希、PDF QA 与冻结标签。"""
import hashlib
import json
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
MANIFEST_PATH = OUT / "final_manifest_after_citation_authority_fix_20261124.json"
INVENTORY_PATH = OUT / "artifact_inventory_after_citation_authority_fix_20261124.json"
QA_PATH = OUT / "report_qc_after_citation_authority_fix_20261124/render_qa.json"
JSON_PATH = OUT / "final_validation_after_citation_authority_fix_20261124.json"
EXPECTED = {
    "index": "2a93e76d5876c1181e7784a20eca0f4d84888d0292d281fc6eea3564090b9260",
    "kb": "1844d8baceb5ce65f2432908a84425ee1fcb8cb1f6e35e8d10c2f3a25331d08f",
    "provenance": "4bcf3411ab460320ecff0120458141f44315b6cb0af1713143cc75470a6e7463",
    "gates": "158409770f627268070075f5859196c26d5b117f1e7e113d0878cd5bb910d068",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    qa = json.loads(QA_PATH.read_text(encoding="utf-8"))
    shared = {
        "index": sha(ROOT / "_工具脚本/taspipe/游戏包/知识库/index.json"),
        "snapshot": sha(ROOT / "选题决策层/kb快照/index.json"),
        "kb": sha(ROOT / "_工具脚本/taspipe/kb.py"),
        "provenance": sha(ROOT / "_工具脚本/taspipe/kb_provenance.py"),
        "gates": sha(ROOT / "_工具脚本/taspipe/kb_selftest_gates.py"),
    }
    mismatches = []
    for row in inventory["artifacts"]:
        actual = sha(row["path"])
        if actual != row["sha256"] or Path(row["path"]).stat().st_size != row["bytes"]:
            mismatches.append({"id": row["id"], "path": row["path"], "expected": row["sha256"], "actual": actual})
    checks = {
        "shared_index_sha": shared["index"] == EXPECTED["index"],
        "snapshot_sha": shared["snapshot"] == EXPECTED["index"],
        "kb_sha": shared["kb"] == EXPECTED["kb"],
        "provenance_sha": shared["provenance"] == EXPECTED["provenance"],
        "gates_sha": shared["gates"] == EXPECTED["gates"],
        "manifest_index": manifest["index"]["sha256"] == EXPECTED["index"],
        "manifest_snapshot": manifest["news_snapshot"]["sha256"] == EXPECTED["index"],
        "report_sha": manifest["report_md"]["sha256"] == sha(manifest["report_md"]["path"]),
        "inventory_count": len(inventory["artifacts"]) == inventory["artifact_count"],
        "inventory_hashes": not mismatches,
        "pdf_qa": all(qa["checks"].values()),
        "pdf_qa_count": qa["check_count"] == 30,
        "pdf_pages": qa["pages"] == 8,
        "blind": manifest["evaluations"]["blind"]["passed"] == 26,
        "heldout": manifest["evaluations"]["heldout_blind"]["passed"] == 16,
        "full_domain": manifest["evaluations"]["full_domain"]["passed"] == 16,
        "strict_v2": manifest["evaluations"]["selector"]["modes"]["strict_fragments"]["passed"] == 21,
        "strict_raw": manifest["evaluations"]["strict_status_comparison"]["strict_status_pass"] == 7,
        "gates": [manifest["gates"][k]["passed"] for k in
                  ("project_selftest", "kb_selftest", "cross_platform_selftest", "topic_selftest")]
                  == [1462, 302, 33, 166],
        "state_isolation": manifest["state_isolation"]["ok"] is True,
        "dynamic_esports_zero": all(v == 0 for v in manifest["esports_db"]["dynamic_counts"].values()),
        "identity_promoted_zero": manifest["identity_audit"]["promoted"] == 0,
        "megaman_draft": manifest["megaman1"]["draft_status"] == "draft_not_frozen",
        "old_delivery_unchanged": manifest["prior_delivery_unchanged"]["ok"] is True,
        "git_untouched": manifest["git"] == {"commit_created": False, "push_performed": False},
    }
    payload = {"schema": "kb_final_validation_after_citation_authority_fix_v1",
               "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "shared_sha256": shared, "checks": checks,
               "inventory_hash_mismatches": mismatches, "ok": all(checks.values())}
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
