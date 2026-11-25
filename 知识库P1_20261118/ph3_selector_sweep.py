# -*- coding: utf-8 -*-
"""阶段3 选择器生产接线实测：26 题 + 60 探针，零 LLM。

每个变体都调用生产 kb.query(fact_selector=...)，不再用 overlay 模拟判定。
  scoped         五类事实接管，复杂问句保留生产原判，不扩窗
  scoped_beyond  同 scoped，但显式允许采用 top_window 外候选
  replace        复杂问句也交给选择器，不通过则拒绝原 pass
  strict_fragments  二手转述/撤回片段不继承整件权威，选择器保持关闭
用法：py -3 -u ph3_selector_sweep.py <输出前缀>
"""
import collections
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
sys.path.insert(0, str(HERE.parent / "知识库小样_20261118"))

from taspipe import kb  # noqa: E402
from taspipe import kb_answer as KA  # noqa: E402
from taspipe import kb_dense as KD  # noqa: E402
from taspipe import kb_route as KR  # noqa: E402
from taspipe import kb_selector as KS  # noqa: E402
from taspipe import kb_provenance as KP  # noqa: E402
import eval_common as E  # noqa: E402

TOPK = 30
WINDOW = 3
MODES = {
    "scoped": {"fact_selector": "scoped"},
    "scoped_beyond": {"fact_selector": "scoped", "selector_beyond_window": True},
    "replace": {"fact_selector": "replace"},
    "strict_fragments": {"fragment_policy": "strict"},
}


def _sha(p):
    p = Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else None


def _call(q, mode=None):
    f = q.get("filters", {})
    kw = dict(game=f.get("game"), revision=f.get("revision"),
              platform=f.get("platform"), topk=TOPK, top_window=WINDOW)
    if mode:
        kw.update(MODES[mode])
    return kb.query(q["q"], **kw)


def _locator(res):
    return (res.get("selected_evidence") or [{}])[0].get("locator")


def _class(base_ok, mode_ok):
    if base_ok and mode_ok:
        return "unchanged_ok"
    if mode_ok:
        return "fixed"
    if base_ok:
        return "regressed"
    return "unchanged_fail"


def _selector(res):
    s = res.get("fact_selector") or {}
    return {k: s.get(k) for k in ("mode", "fact_class", "verdict", "selected",
                                  "selected_rank", "beyond_window", "reason")}


def run_questions(questions):
    rows = []
    for q in questions:
        base = _call(q)
        gp = E.grade_v2(q, base)
        variants = {}
        classes = {}
        for mode in MODES:
            res = _call(q, mode)
            g = E.grade_v2(q, res)
            variants[mode] = {
                "grade": g, "status": res.get("status"),
                "selected_locator": _locator(res), "selector": _selector(res),
                "refusal": res.get("refusal"), "condition": res.get("condition"),
                "fragment_policy": res.get("fragment_policy"),
                "retrieval": res.get("retrieval"), "index_used": res.get("index_used"),
            }
            classes[mode] = _class(gp["ok"], g["ok"])
        row = {"id": q["id"], "q": q["q"], "tier": q["expect"],
               "base": {"grade": gp, "status": base.get("status"),
                        "selected_locator": _locator(base),
                        "retrieval": base.get("retrieval"),
                        "index_used": base.get("index_used")},
               "classes": classes, "variants": variants}
        rows.append(row)
        print(f"{q['id']:4s} base={gp['ok']!s:5s} " +
              " ".join(f"{m}={variants[m]['grade']['ok']!s:5s}/{classes[m]}"
                       for m in MODES), flush=True)
    return rows


def run_probes(questions, label):
    rows = []
    for q in questions:
        base = _call(q)
        bp = base.get("status") == "pass"
        variants = {}
        classes = {}
        for mode in MODES:
            res = _call(q, mode)
            mp = res.get("status") == "pass"
            cls = ("intercepted" if bp and not mp else
                   "newly_passed" if mp and not bp else
                   "still_passed" if mp else "still_refused")
            variants[mode] = {"status": res.get("status"), "class": cls,
                              "selector": _selector(res),
                              "fragment_policy": res.get("fragment_policy"),
                              "refusal": res.get("refusal"),
                              "index_used": res.get("index_used")}
            classes[mode] = cls
        rows.append({"id": q["id"], "q": q["q"], "kind": q.get("kind"),
                     "filters": q.get("filters", {}), "base_status": base.get("status"),
                     "base_index": base.get("index_used"), "classes": classes,
                     "variants": variants})
        print(f"{label}{q['id']:5s} {str(q.get('kind')):19s} " +
              " ".join(f"{m}={classes[m]}" for m in MODES), flush=True)
    return rows


def summarize(qs, pe, pb):
    base_ok = sum(r["base"]["grade"]["ok"] for r in qs)
    out = {"base_v2_ok": base_ok, "modes": {}}
    for mode in MODES:
        grades = [r["variants"][mode]["grade"] for r in qs]
        classes = collections.Counter(r["classes"][mode] for r in qs)
        swapped = [r["id"] for r in qs
                   if r["base"]["grade"]["ok"] and r["variants"][mode]["grade"]["ok"]
                   and r["base"]["selected_locator"] != r["variants"][mode]["selected_locator"]]
        by_kind = collections.defaultdict(collections.Counter)
        for r in pe:
            by_kind[r["kind"]][r["classes"][mode]] += 1
        out["modes"][mode] = {
            "v2_ok": sum(g["ok"] for g in grades),
            "classes": dict(classes),
            "wrong_evidence": [r["id"] for r in qs
                               if r["variants"][mode]["grade"]["wrong_evidence"]],
            "missed_answer": [r["id"] for r in qs
                              if r["variants"][mode]["grade"]["missed_answer"]],
            "evidence_swapped": swapped,
            "newly_passed": [r["id"] for r in pe if r["classes"][mode] == "newly_passed"],
            "intercepted": [r["id"] for r in pe if r["classes"][mode] == "intercepted"],
            "probes_ext_by_kind": {k: dict(v) for k, v in by_kind.items()},
            "probes_base": dict(collections.Counter(r["classes"][mode] for r in pb)),
        }
    return out


def render(out):
    L = [f"# 选择器生产接线实测 · {out['taken_at']}", "",
         f"- 索引：`{out['index']['name']}` sha16 {out['index']['sha16']}"
         f"（{out['index']['chunks']} 块）；候选 top{out['topk']}，生产窗口 {out['window']}",
         f"- 代码指纹：" + "，".join(f"{k}={v}" for k, v in out["code"].items()), "",
         f"## 总结（生产基线 {out['summary']['base_v2_ok']}/26）", "",
         "| 模式 | v2 | 修好 | 打坏 | 错误出证 | 仍pass但换证 | 探针新放行 | 探针拦截 |",
         "|---|---|---|---|---|---|---|---|"]
    for mode, s in out["summary"]["modes"].items():
        L.append(f"| {mode} | {s['v2_ok']}/26 | {s['classes'].get('fixed', 0)} | "
                 f"{s['classes'].get('regressed', 0)} | {s['wrong_evidence']} | "
                 f"{s['evidence_swapped']} | {s['newly_passed']} | {s['intercepted']} |")
    for mode in MODES:
        L += ["", f"## {mode}", "",
              "| 题 | 档 | 分类 | 基线 | 接线后 | 选中位 | 基线出证 | 接线后出证 |",
              "|---|---|---|---|---|---|---|---|"]
        for r in out["questions"]:
            v = r["variants"][mode]
            L.append(f"| {r['id']} | {r['tier']} | {r['classes'][mode]} | "
                     f"{r['base']['grade']['ok']} | {v['grade']['ok']} | "
                     f"{v['selector'].get('selected_rank')} | {r['base']['selected_locator']} | "
                     f"{v['selected_locator']} |")
        L += ["", "| 探针 | 标签 | 分类 | 事实类 | 选中位 | 状态 | 选择器原因 |",
              "|---|---|---|---|---|---|---|"]
        for r in out["probes_ext"]:
            v = r["variants"][mode]
            L.append(f"| {r['id']} | {r['kind']} | {v['class']} | "
                     f"{v['selector'].get('fact_class')} | {v['selector'].get('selected_rank')} | "
                     f"{v['status']} | {v['selector'].get('reason')} |")
    return "\n".join(L) + "\n"


def main():
    prefix = Path(sys.argv[1])
    qfile = json.loads((HERE / "p2_questions_ext.json").read_text(encoding="utf-8"))["questions"]
    pext = json.loads((HERE / "probe_questions_ext.json").read_text(encoding="utf-8"))["questions"]
    pbase = json.loads((HERE / "probe_questions.json").read_text(encoding="utf-8"))
    pbase = pbase["questions"] if isinstance(pbase, dict) else pbase

    probe0 = kb.query("燕返", game="nekketsu_soccer2", topk=1)
    used = Path(probe0.get("index_used") or kb.INDEX_JSON)
    if not used.is_absolute():
        used = kb.INDEX_JSON.parent / used.name
    idx = kb.load_index(used)
    out = {"taken_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "index": {"name": used.name, "sha16": _sha(used),
                     "chunks": len(idx["chunks"]) if idx else 0},
           "code": {n: _sha(Path(m.__file__)) for n, m in
                    (("kb", kb), ("kb_answer", KA), ("kb_selector", KS),
                     ("kb_route", KR), ("kb_dense", KD), ("kb_provenance", KP),
                     ("eval_common", E), ("producer", sys.modules[__name__]))},
           "topk": TOPK, "window": WINDOW, "modes": MODES}
    out["questions"] = run_questions(qfile)
    out["probes_ext"] = run_probes(pext, "X")
    out["probes_base"] = run_probes(pbase, "B")
    out["summary"] = summarize(out["questions"], out["probes_ext"], out["probes_base"])
    prefix.with_suffix(".json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    prefix.with_suffix(".md").write_text(render(out), encoding="utf-8")
    print("DONE", prefix.with_suffix(".md"), flush=True)


if __name__ == "__main__":
    main()
