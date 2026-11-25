# -*- coding: utf-8 -*-
"""全域评测：静态结构化事实 + 动态空域 + 时效陷阱 + 跨域 + 复古回归，零 LLM。"""
import argparse
import collections
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))

from taspipe import kb  # noqa: E402
from taspipe import kb_answer  # noqa: E402
from taspipe import kb_esports as KE  # noqa: E402
from taspipe import kb_provenance  # noqa: E402
from taspipe import kb_route  # noqa: E402
from taspipe import kb_selector  # noqa: E402


def _sha(p):
    p = Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def _call(q):
    if q["route"] == "static":
        return KE.query_static(q["name"], q["kind"], q.get("patch"))
    return kb.query_auto(q["q"], game=q.get("game"), revision=q.get("revision"),
                         topk=30, top_window=3)


def _grade(q, r):
    e = q["expect"]
    checks = {"status": r.get("status") == e["status"]}
    if "refusal" in e:
        checks["refusal"] = r.get("refusal") == e["refusal"]
    if "reason_code" in e:
        checks["reason_code"] = r.get("reason_code") == e["reason_code"]
    ev = r.get("selected_evidence") or []
    checks["evidence_count"] = len(ev) == e["evidence_count"]
    if e["status"] != "pass":
        checks["no_false_evidence"] = not ev
    answer = r.get("answer_text") or ""
    checks["answer_contains"] = all(x in answer for x in e.get("answer_contains", []))
    if "dataset_revision" in e:
        checks["dataset_revision"] = r.get("dataset_revision") == e["dataset_revision"]
    if "domains" in e:
        ds = [d["domain"] for d in r.get("auto_routing", {}).get("domains", [])]
        checks["domains"] = ds == e["domains"]
    if "mode" in e:
        checks["mode"] = r.get("auto_routing", {}).get("mode") == e["mode"]
    return {"ok": all(checks.values()), "checks": checks}


def run(qs):
    rows = []
    for q in qs:
        r = _call(q)
        g = _grade(q, r)
        ev = (r.get("selected_evidence") or [{}])[0]
        rows.append({"id": q["id"], "category": q["category"], "q": q["q"],
                     "grade": g, "status": r.get("status"),
                     "refusal": r.get("refusal"), "reason_code": r.get("reason_code"),
                     "answer_text": r.get("answer_text"),
                     "evidence": {"id": ev.get("evidence_id") or ev.get("chunk_id"),
                                  "locator": ev.get("locator")},
                     "index_used": r.get("index_used"),
                     "auto_routing": r.get("auto_routing")})
        print(f"{q['id']} {g['ok']} {r.get('status')}/{r.get('refusal') or r.get('reason_code') or '-'}",
              flush=True)
    return rows


def render(d):
    L = [f"# 全域生产评测 · {d['taken_at']}", "",
         f"- 严格通过：{d['summary']['ok']}/{d['summary']['total']}",
         f"- 代码指纹：{d['code']}", f"- 索引 sha256：{d['index_sha256']}",
         f"- 电竞库 sha256：{d['db_sha256']}", "", "## 分类计数", ""]
    for k, v in d["summary"]["by_category"].items():
        L.append(f"- {k}: {v['ok']}/{v['total']}")
    L += ["", "## 逐题", "", "| 题 | 类目 | 结果 | 状态/拒答 | 证据定位 | 失败检查 |",
          "|---|---|---|---|---|---|"]
    for r in d["questions"]:
        bad = [k for k, v in r["grade"]["checks"].items() if not v]
        L.append(f"| {r['id']} | {r['category']} | {r['grade']['ok']} | "
                 f"{r['status']}/{r['refusal'] or r['reason_code'] or '-'} | "
                 f"{r['evidence']['locator'] or '-'} | {bad or '-'} |")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--questions", default=str(HERE / "full_domain_questions_20261124.json"))
    ap.add_argument("--out", default=str(HERE / "full_domain_eval_20261124"))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    qs = json.loads(Path(args.questions).read_text(encoding="utf-8"))["questions"]
    rows = run(qs)
    by_cat = collections.defaultdict(lambda: {"ok": 0, "total": 0})
    for r in rows:
        by_cat[r["category"]]["total"] += 1
        by_cat[r["category"]]["ok"] += int(r["grade"]["ok"])
    d = {"schema": "full_domain_eval_v1", "taken_at": time.strftime("%Y-%m-%d %H:%M:%S"),
         "questions": rows,
         "summary": {"total": len(rows), "ok": sum(r["grade"]["ok"] for r in rows),
                     "by_category": dict(by_cat)},
         "index_sha256": _sha(kb.INDEX_JSON), "db_sha256": _sha(KE.DB_PATH),
         "code": {"kb": _sha(kb.__file__), "kb_answer": _sha(kb_answer.__file__),
                  "kb_esports": _sha(KE.__file__),
                  "kb_provenance": _sha(kb_provenance.__file__),
                  "kb_route": _sha(kb_route.__file__),
                  "kb_selector": _sha(kb_selector.__file__),
                  "producer": _sha(__file__)}}
    out = Path(args.out)
    out.with_suffix(".json").write_text(json.dumps(d, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    out.with_suffix(".md").write_text(render(d), encoding="utf-8")
    print(f"DONE {d['summary']['ok']}/{d['summary']['total']} {out.with_suffix('.md')}")
    return 0 if d["summary"]["ok"] == d["summary"]["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
