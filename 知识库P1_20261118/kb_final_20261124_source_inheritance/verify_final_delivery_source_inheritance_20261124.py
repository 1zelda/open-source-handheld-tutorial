# -*- coding: utf-8 -*-
"""交付闭环复核：清单哈希、Markdown 链接、PDF QA、旧交付与生产隔离。"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124_source_inheritance"
MANIFEST = OUT / "final_manifest_source_inheritance_20261124.json"
INVENTORY = OUT / "artifact_inventory_source_inheritance_20261124.json"
REPORT = ROOT / "知识库改进优化指导_2026-11-24_来源继承修正回填.md"
INVENTORY_MD = OUT / "artifact_inventory_source_inheritance_20261124.md"
QA = OUT / "report_qc_source_inheritance_20261124/render_qa.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_record(record):
    path = Path(record["path"])
    assert path.is_file(), path
    assert path.stat().st_size == record["bytes"], path
    assert sha(path) == record["sha256"], path


def check_links(markdown):
    missing = []
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", markdown.read_text(encoding="utf-8")):
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            continue
        path_text, _, fragment = target.partition("#")
        path = (markdown.parent / path_text).resolve() if path_text else markdown
        if not path.exists():
            missing.append({"source": str(markdown), "target": target, "reason": "missing"})
            continue
        if fragment.startswith("L") and path.is_file():
            line = int(fragment[1:].split("-", 1)[0])
            if line > len(path.read_text(encoding="utf-8").splitlines()):
                missing.append({"source": str(markdown), "target": target, "reason": "line_out_of_range"})
    return missing


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    qa = json.loads(QA.read_text(encoding="utf-8"))
    check_record(manifest["index"])
    check_record(manifest["hybrid_probe_index"])
    check_record(manifest["report_md"])
    for row in inventory["artifacts"]:
        check_record(row)
    for name, record in manifest["prior_delivery_unchanged"]["artifacts"].items():
        check_record(record)
        assert record["sha256"] == record["expected_sha256"]
    assert sha(REPORT) == manifest["report_md"]["sha256"]
    assert all(qa["checks"].values())
    assert qa["pdf_sha256"] == sha(ROOT / "知识库改进优化指导_2026-11-24_来源继承修正回填.pdf")
    assert manifest["dense_isolation"]["all_checks_ok"] is True
    assert manifest["dense_isolation"]["auto_index_is_base"] is True
    assert manifest["dense_isolation"]["production_dense_present"] == {"base": False, "hybrid": False}
    sources_audit = json.loads(Path(manifest["audits"]["sources"]["artifact"]["path"]).read_text(encoding="utf-8"))
    assert sources_audit["counts"]["fail"] == 1
    assert manifest["open_items"]["sources_audit"].startswith("fail=1:")
    missing = check_links(REPORT) + check_links(INVENTORY_MD)
    result = {"schema": "kb_final_delivery_verification_v1",
              "manifest_artifacts_checked": 3,
              "inventory_artifacts_checked": len(inventory["artifacts"]),
              "prior_delivery_artifacts_checked": len(manifest["prior_delivery_unchanged"]["artifacts"]),
              "markdown_sources_checked": [str(REPORT), str(INVENTORY_MD)],
              "missing_links": missing, "pdf_checks": qa["checks"],
              "dense_isolation_ok": True, "all_checks_ok": not missing}
    target = OUT / "final_delivery_verification_source_inheritance_20261124.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
