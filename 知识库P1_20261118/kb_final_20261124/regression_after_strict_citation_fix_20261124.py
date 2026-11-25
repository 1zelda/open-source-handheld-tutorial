# -*- coding: utf-8 -*-
"""生产路径回归：裸引用不连坐，显式转述仍拦截，真实状态隔离。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
sys.path.insert(0, str(ROOT / "_工具脚本"))

from taspipe import kb as K
from taspipe import kb_blind_eval as BE
from taspipe import kb_selector as KS
from taspipe import kb_provenance as KP
from taspipe import sources as S
from taspipe import kb_esports as KE


def sha(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def state():
    return {str(p): {"exists": p.is_file(), "size": p.stat().st_size if p.is_file() else None,
                     "mtime_ns": p.stat().st_mtime_ns if p.is_file() else None, "sha256": sha(p)}
            for p in BE._protected_paths()}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    before = state()
    questions = json.loads((ROOT / "知识库P1_20261118/p2_questions_ext.json")
                           .read_text(encoding="utf-8"))["questions"]
    rows = []
    for q in questions:
        f = q.get("filters", {})
        params = dict(game=f.get("game"), revision=f.get("revision"),
                      platform=f.get("platform"), topk=30, top_window=3)
        base = K.query(q["q"], **params)
        strict = K.query(q["q"], fragment_policy="strict", **params)
        rows.append({"id": q["id"], "base_status": base["status"],
                     "strict_status": strict["status"],
                     "base_selected": [h.get("locator") for h in base.get("selected_evidence") or []],
                     "strict_selected": [h.get("locator") for h in strict.get("selected_evidence") or []]})
    after = state()
    changed = [p for p in before if before[p] != after[p]]
    result = {
        "schema": "kb_post_strict_citation_fix_regression_v1",
        "base_total": len(rows),
        "base_pass": sum(r["base_status"] == "pass" for r in rows),
        "strict_pass": sum(r["strict_status"] == "pass" for r in rows),
        "strict_intercepted_ids": [r["id"] for r in rows
                                   if r["base_status"] == "pass" and r["strict_status"] != "pass"],
        "strict_newly_passed_ids": [r["id"] for r in rows
                                    if r["base_status"] != "pass" and r["strict_status"] == "pass"],
        "rows": rows,
        "isolation": {"ok": not changed, "changed_paths": changed},
        "production_defaults": {"top_window": 3, "fragment_policy": None,
                                "fact_selector": None},
        "code": {name: sha(module.__file__) for name, module in
                 (("kb", K), ("kb_selector", KS), ("kb_provenance", KP),
                  ("kb_blind_eval", BE), ("sources", S), ("kb_esports", KE),
                  ("producer", sys.modules[__name__]))},
    }
    target = OUT / "regression_after_strict_citation_fix_20261124.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("base_total", "base_pass", "strict_pass",
                                               "strict_intercepted_ids", "strict_newly_passed_ids",
                                               "isolation")}, ensure_ascii=False, indent=2))
    return 0 if result["isolation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
