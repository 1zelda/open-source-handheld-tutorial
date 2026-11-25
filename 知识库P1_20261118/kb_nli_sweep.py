# -*- coding: utf-8 -*-
"""NLI 影子实测：26 题 + 60 探针；不拿问题冒充 claim，不改变生产裁决。"""
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K
from taspipe import kb_nli as N

CLAIMS = {
    "Q02": "热血队内仅 Yoritsune 原生拥有燕返；秘技后全员可获得。",
    "Q04": "やさしい難易度では敵チームも必殺シュートを出せない。",
    "Q05": "1Pは通常キャプテンのMFを操作し、控室の作戦会議でどの選手でもMFに替えられる。",
    "Q10": "3対3のチームバトルはROM側の制限であり、1対1には変更できない。",
    "Q18": "暂停秘技成功的判定签名是得分框「ひっさつOK」。",
    "X03": "トルネード・パンチはキーパーだけの必殺技である。",
    "X15": "熱血足球は最大4人同時に遊べる。",
    "X21": "元永はゴールキーパーである。",
}
STRUCTURED = {"Q01", "Q03", "Q06", "Q07", "Q08"}


def sha(p):
    p = Path(p)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def call(q):
    f = q.get("filters", {})
    return K.query(q["q"], game=f.get("game"), revision=f.get("revision"),
                   platform=f.get("platform"), topk=30, top_window=3)


def run(items, label):
    rows = []
    for q in items:
        base = call(q)
        claim = CLAIMS.get(q["id"])
        shadow = call(q)
        if claim:
            shadow = K.query(q["q"], game=q.get("filters", {}).get("game"),
                             revision=q.get("filters", {}).get("revision"),
                             platform=q.get("filters", {}).get("platform"),
                             topk=30, top_window=3, nli_shadow=True, nli_claim=claim)
        unchanged = (base.get("status") == shadow.get("status")
                     and base.get("selected_evidence") == shadow.get("selected_evidence"))
        selected = (base.get("selected_evidence") or [None])[0]
        raw = None
        skip = None
        if not claim:
            skip = "no_atomic_claim"
        elif q["id"] in STRUCTURED:
            skip = "structured_fact_not_delegated_to_nli"
        elif base.get("status") != "pass" or selected is None:
            skip = "no_production_pass"
        else:
            try:
                texts = K._selector_texts(base, None)
                prov = selected.get("fragment_provenance") or {}
                premise = prov.get("evidence_excerpt") or texts.get(selected.get("chunk_id"))
                if not premise:
                    skip = "evidence_text_unavailable"
                else:
                    raw = N.predict(premise, claim)
                    raw = {k: raw[k] for k in
                           ("label", "probabilities", "margin", "device", "dtype",
                            "premise_chars", "hypothesis_chars")}
            except Exception as exc:
                skip = f"{type(exc).__name__}: {exc}"
        rows.append({
            "id": q["id"], "q": q["q"], "kind": q.get("kind"),
            "base_status": base.get("status"), "base_refusal": base.get("refusal"),
            "selected_chunk": selected.get("chunk_id") if selected else None,
            "selected_locator": selected.get("locator") if selected else None,
            "claim": claim, "claim_policy": "manual_atomic_claim" if claim else None,
            "production_nli": shadow.get("nli_shadow"),
            "production_unchanged": unchanged, "raw_nli": raw, "raw_skip": skip,
            "index_used": base.get("index_used"),
            "index_sha256": base.get("index_sha256"),
        })
        print(label, q["id"], base.get("status"), "unchanged", unchanged,
              "raw", (raw or {}).get("label"), "skip", skip, flush=True)
    return rows


def main():
    questions = json.loads((HERE / "p2_questions_ext.json").read_text(encoding="utf-8"))["questions"]
    ext = json.loads((HERE / "probe_questions_ext.json").read_text(encoding="utf-8"))["questions"]
    base_obj = json.loads((HERE / "probe_questions.json").read_text(encoding="utf-8"))
    base_probes = base_obj["questions"] if isinstance(base_obj, dict) else base_obj
    started = time.perf_counter()
    qrows = run(questions, "Q")
    erows = run(ext, "X")
    brows = run(base_probes, "W")
    cal_path = Path(N.__file__).with_name("nli_calibration.json")
    cal = json.loads(cal_path.read_text(encoding="utf-8"))
    all_rows = qrows + erows + brows
    out = {
        "schema_version": 1, "taken_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scope": "26题+60探针；只有人工原子 claim 且生产 pass 的证据才跑原始 NLI；其余逐格记跳过原因。",
        "calibration": {"status": cal.get("status"), "thresholds": cal.get("thresholds"),
                        "sha256": cal.get("sha256"), "samples": cal.get("samples")},
        "model": {"id": N.MODEL_ID, "revision": N.MODEL_REV},
        "summary": {
            "rows": len(all_rows),
            "production_unchanged": sum(r["production_unchanged"] for r in all_rows),
            "with_atomic_claim": sum(bool(r["claim"]) for r in all_rows),
            "raw_predictions": sum(r["raw_nli"] is not None for r in all_rows),
            "raw_labels": dict(Counter(r["raw_nli"]["label"] for r in all_rows if r["raw_nli"])),
            "skip_reasons": dict(Counter(r["raw_skip"] for r in all_rows if r["raw_skip"])),
            "production_nli_status": dict(Counter((r["production_nli"] or {}).get("status")
                                                  for r in all_rows)),
        },
        "code": {name: sha(Path(module.__file__)) for name, module in
                 (("kb", K), ("kb_nli", N), ("sweep", sys.modules[__name__]))},
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "questions": qrows, "probes_ext": erows, "probes_base": brows,
    }
    dest = HERE / "nli_shadow_sweep.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("SUMMARY", json.dumps(out["summary"], ensure_ascii=False), flush=True)
    print("DONE", dest, flush=True)


if __name__ == "__main__":
    main()
