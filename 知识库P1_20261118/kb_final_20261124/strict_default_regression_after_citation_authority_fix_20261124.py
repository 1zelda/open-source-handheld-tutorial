# -*- coding: utf-8 -*-
"""26题默认/strict原始状态回归：只读隔离索引，生产kb.query，零LLM。"""
import hashlib
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
P2 = ROOT / "知识库P1_20261118"
sys.path.insert(0, str(ROOT / "_工具脚本"))
sys.path.insert(0, str(P2 / "知识库小样_20261118"))
sys.path.insert(0, str(ROOT / "知识库小样_20261118"))
from taspipe import kb
import eval_common as E

JSON_PATH = OUT / "strict_default_regression_after_citation_authority_fix_20261124.json"
DEFAULT = {"topk": 30, "top_window": 3, "fact_selector": None, "fragment_policy": None}
STRICT = {**DEFAULT, "fragment_policy": "strict"}


def sha(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def snapshot(paths):
    out = {}
    for p in paths:
        p = Path(p)
        out[str(p)] = {"exists": p.is_file(), "bytes": p.stat().st_size if p.is_file() else 0,
                       "mtime_ns": p.stat().st_mtime_ns if p.is_file() else None,
                       "sha256": sha(p)}
    return out


def call(q, index_path, mode):
    f = q.get("filters", {})
    return kb.query(q["q"], game=f.get("game"), revision=f.get("revision"),
                    platform=f.get("platform"), topk=DEFAULT["topk"],
                    top_window=DEFAULT["top_window"], index_path=index_path,
                    fact_selector=mode["fact_selector"], fragment_policy=mode["fragment_policy"])


def row(q, res, grade):
    return {"status": res.get("status"), "refusal": res.get("refusal"),
            "reason": res.get("reason"), "condition": res.get("condition"),
            "grade": grade, "selected_evidence": res.get("selected_evidence") or [],
            "fragment_policy": res.get("fragment_policy"), "fact_selector": res.get("fact_selector"),
            "index_used": res.get("index_used"), "index_sha256": res.get("index_sha256")}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    questions = json.loads((P2 / "p2_questions_ext.json").read_text(encoding="utf-8"))["questions"]
    protected = [Path(kb.INDEX_JSON), Path(kb.INDEX_JSON).with_name("corpus_map.json"),
                 Path(kb.ESPORTS_DB)] if hasattr(kb, "ESPORTS_DB") else [Path(kb.INDEX_JSON)]
    before = snapshot(protected)
    temp_paths = []
    with tempfile.TemporaryDirectory(prefix="strict_regression_", dir=OUT) as td:
        temp_paths.append(td)
        isolated = Path(td) / "index.json"
        shutil.copyfile(kb.INDEX_JSON, isolated)
        rows = []
        for q in questions:
            base = call(q, isolated, DEFAULT)
            strict = call(q, isolated, STRICT)
            gp, gs = E.grade_v2(q, base), E.grade_v2(q, strict)
            rows.append({"id": q["id"], "q": q["q"], "tier": q["expect"],
                         "default": row(q, base, gp), "strict": row(q, strict, gs),
                         "raw_default_pass": base.get("status") == "pass",
                         "raw_strict_pass": strict.get("status") == "pass",
                         "strict_regressed_v2": gp["ok"] and not gs["ok"]})
            print(f"{q['id']:4s} default={base.get('status'):12s}/{gp['ok']!s:5s} "
                  f"strict={strict.get('status'):12s}/{gs['ok']!s:5s}", flush=True)
    after = snapshot(protected)
    changed = [p for p in before if before[p] != after[p]]
    defaults_raw = sum(r["raw_default_pass"] for r in rows)
    strict_raw = sum(r["raw_strict_pass"] for r in rows)
    payload = {
        "schema": "strict_default_regression_after_citation_authority_fix_v1",
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "questions": len(rows), "modes": {"default": DEFAULT, "strict_fragments": STRICT},
        "source_index": {"path": str(Path(kb.INDEX_JSON)), "sha256": sha(kb.INDEX_JSON),
                         "bytes": Path(kb.INDEX_JSON).stat().st_size},
        "code": {**{name: sha(Path(module.__file__)) for name, module in
                    (("kb", kb), ("kb_provenance", sys.modules["taspipe.kb_provenance"]),
                     ("eval_common", E))}, "runner": sha(Path(__file__))},
        "summary": {
            "default_raw_pass": defaults_raw, "strict_raw_pass": strict_raw,
            "default_v2_ok": sum(r["default"]["grade"]["ok"] for r in rows),
            "strict_v2_ok": sum(r["strict"]["grade"]["ok"] for r in rows),
            "strict_intercepted": [r["id"] for r in rows
                                   if r["raw_default_pass"] and not r["raw_strict_pass"]],
            "strict_v2_regressed": [r["id"] for r in rows if r["strict_regressed_v2"]],
            "wrong_evidence_default": [r["id"] for r in rows if r["default"]["grade"]["wrong_evidence"]],
            "wrong_evidence_strict": [r["id"] for r in rows if r["strict"]["grade"]["wrong_evidence"]],
        },
        "isolation": {"before": before, "after": after, "changed_paths": changed,
                      "temp_paths": temp_paths,
                      "temp_paths_removed": all(not Path(p).exists() for p in temp_paths),
                      "ok": not changed and all(not Path(p).exists() for p in temp_paths)},
        "rows": rows,
    }
    payload["ok"] = (payload["summary"]["strict_v2_ok"] == 21
                     and payload["summary"]["default_v2_ok"] == 26
                     and payload["summary"]["strict_intercepted"]
                     == ["Q01", "Q02", "Q03", "Q04", "Q05", "Q18"]
                     and not payload["summary"]["wrong_evidence_default"]
                     and not payload["summary"]["wrong_evidence_strict"]
                     and payload["isolation"]["ok"])
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(JSON_PATH), "summary": payload["summary"],
                      "isolation_ok": payload["isolation"]["ok"], "ok": payload["ok"]},
                     ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
