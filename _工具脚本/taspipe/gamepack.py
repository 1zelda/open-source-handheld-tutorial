# -*- coding: utf-8 -*-
"""M4：逐游戏知识包 + 正负例验收（依据 _scratch/强模型方案回复.md §5 M4 / B4）。

游戏包 = Element 记录 + 帧 fixture。验收两道：
  * 正例帧必须通过 success_checks；
  * 每个负例帧（普通动作/错误起点）必须被同一组 success_checks 拒绝。
两道都过才算该要素检测器合格；证据不足 => inconclusive。
无可靠 RAM 时用视觉检测，歧义留人工复核（本模块不静默放行）。

运行: python -m taspipe.gamepack run <pack.json>
"""
import argparse
import json
import sys
from pathlib import Path

from .schema import (Element, CheckSpec, CheckResult, Verification, Verdict,
                     Stage, to_dict)
from . import detect


def load_pack(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _checks(specs, frame_path):
    return [detect.run_check(s, frame_path) for s in specs]


def _verdict(checks):
    v = Verification("tmp", "tmp", Stage.VERIFY, checks).validate()
    return v.verdict


def run_element(pack, el, base=None):
    base = Path(base) if base else Path(".")
    frames = {k: (str(v) if Path(v).is_absolute() else str(base / v))
              for k, v in pack.get("frames", {}).items()}
    element = Element(
        element_id=el["element_id"],
        game_revision_id=pack["game_revision_id"],
        kind=el.get("kind", "element"),
        success_checks=[CheckSpec(**s) for s in el.get("success_checks", [])],
        negative_cases=el.get("negative_cases", []),
    ).validate()

    pos_frame = frames.get(el.get("positive_frame"))
    pos_checks = _checks(element.success_checks, pos_frame) if pos_frame else []
    pos_verdict = _verdict(pos_checks) if pos_checks else Verdict.INCONCLUSIVE

    checks = [CheckResult("positive_passed",
                          Verdict.PASS if pos_verdict == Verdict.PASS else Verdict.FAIL,
                          evidence_refs=[str(pos_frame)],
                          reason=f"positive verdict={pos_verdict.value}")]
    neg_detail = []
    for nc in element.negative_cases:
        nf = frames.get(nc.get("frame"))
        nchecks = _checks(element.success_checks, nf) if nf else []
        nv = _verdict(nchecks) if nchecks else Verdict.INCONCLUSIVE
        # 负例必须"不被判通过"。若负例也 pass => 检测器分不清，FAIL。
        rejected = nv != Verdict.PASS
        checks.append(CheckResult(
            f"negative_{nc['case_id']}_rejected",
            Verdict.PASS if rejected else Verdict.FAIL,
            evidence_refs=[str(nf)],
            reason=f"negative verdict={nv.value}（须 != pass）"))
        neg_detail.append({"case_id": nc["case_id"], "frame": nf,
                           "verdict": nv.value, "rejected": rejected,
                           "checks": [to_dict(c) for c in nchecks]})

    ver = Verification(f"ver_{element.element_id}", element.element_id,
                       Stage.VERIFY, checks).validate()
    return {
        "element_id": element.element_id,
        "kind": element.kind,
        "positive": {"frame": pos_frame, "verdict": pos_verdict.value,
                     "checks": [to_dict(c) for c in pos_checks]},
        "negatives": neg_detail,
        "verification": {**to_dict(ver), "verdict": ver.verdict.value},
    }


def run_pack(path):
    pack = load_pack(path)
    base = Path(path).resolve().parent
    results = [run_element(pack, el, base) for el in pack.get("elements", [])]
    passed = sum(1 for r in results if r["verification"]["verdict"] == "pass")
    return {"game_id": pack.get("game_id"), "total": len(results),
            "passed": passed, "results": results}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["run"])
    ap.add_argument("pack")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    doc = run_pack(args.pack)
    if args.out:
        Path(args.out).write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    print(f"game={doc['game_id']} 要素 {doc['total']} 合格 {doc['passed']}")
    for r in doc["results"]:
        print(f"  [{r['verification']['verdict']}] {r['element_id']} "
              f"positive={r['positive']['verdict']} "
              f"negatives=" + ",".join(f"{n['case_id']}:{'拒' if n['rejected'] else '误放'}"
                                       for n in r["negatives"]))
    return 0 if doc["passed"] == doc["total"] else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())