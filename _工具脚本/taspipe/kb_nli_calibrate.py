# -*- coding: utf-8 -*-
"""用人工校准集测 mDeBERTa NLI；阈值只服务影子提示。"""
import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from taspipe import kb_nli as N


def score(predictions):
    confusion = {a: {b: 0 for b in ("entailment", "neutral", "contradiction")}
                 for a in ("entailment", "neutral", "contradiction")}
    for row in predictions:
        confusion[row["expected"]][row["label"]] += 1
    labels = ("entailment", "neutral", "contradiction")
    correct = sum(confusion[x][x] for x in labels)
    f1 = []
    for x in labels:
        tp = confusion[x][x]
        denom = sum(confusion[x].values()) + sum(confusion[a][x] for a in labels)
        f1.append(2 * tp / denom if denom else 0.0)
    return {"confusion_matrix": confusion, "accuracy": correct / len(predictions),
            "macro_f1": sum(f1) / len(f1), "samples": len(predictions)}


def choose_thresholds(predictions):
    result = {}
    details = {}
    for label in ("entailment", "contradiction"):
        positives = [r["probabilities"].get(label, 0.0)
                     for r in predictions if r["expected"] == label]
        negatives = [r["probabilities"].get(label, 0.0)
                     for r in predictions if r["expected"] != label]
        positive_floor = max(0.5, round(min(positives), 4))
        negative_ceiling = max(negatives) if negatives else 0.0
        details[label] = {"positive_floor": positive_floor,
                          "negative_ceiling": negative_ceiling,
                          "separates": positive_floor > negative_ceiling}
        if positive_floor <= negative_ceiling:
            result[label] = None
        else:
            result[label] = min(0.99, round(positive_floor, 4))
    return result, details


def shadow(prediction, thresholds):
    label = prediction["label"]
    p = prediction["probabilities"].get(label, 0.0)
    if label == "contradiction" and p >= thresholds["contradiction"]:
        return "veto_candidate"
    if label == "entailment" and p >= thresholds["entailment"]:
        return "supports_shadow"
    return "uncertain"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path,
                    default=Path(__file__).with_name("nli_calibration_cases.json"))
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).with_name("nli_calibration.json"))
    args = ap.parse_args()
    data = json.loads(args.cases.read_text(encoding="utf-8"))
    if data["model"]["revision"] != N.MODEL_REV or data["model"]["id"] != N.MODEL_ID:
        raise RuntimeError("校准集与生产模型常量不一致")
    started = time.perf_counter()
    predictions = []
    for case in data["cases"]:
        t0 = time.perf_counter()
        pred = N.predict(case["premise"], case["hypothesis"])
        row = {k: case[k] for k in ("id", "source_chunk", "expected")}
        row.update(pred)
        row["seconds"] = round(time.perf_counter() - t0, 4)
        predictions.append(row)
        print(row["id"], row["expected"], row["label"],
              round(row["probabilities"][row["label"]], 4), row["seconds"], flush=True)
    thresholds, separation = choose_thresholds(predictions)
    publishable = all(isinstance(v, (int, float)) for v in thresholds.values())
    metrics = score(predictions)
    for row in predictions:
        row["shadow_decision"] = shadow(row, thresholds) if publishable else "disabled"
    payload = {
        "schema_version": 1,
        "status": "ready" if publishable else "failed",
        "model": data["model"],
        "calibrated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "samples": len(predictions),
        "scope_note": "仅人工影子校准；样本不足，不能据此宣称真实通过率或统计显著性。",
        "threshold_policy": "取各类正例最低概率；正负区间必须分离；影子判断不改变生产裁决。",
        "thresholds": thresholds if publishable else None,
        "separation": separation,
        "failure_reason": None if publishable else "至少一类正负概率区间重叠，禁止发布支持/否决阈值",
        "metrics": metrics,
        "runtime": {"device": predictions[0]["device"],
                    "dtype": predictions[0]["dtype"],
                    "initial_load_seconds": round(predictions[0]["seconds"], 4),
                    "elapsed_seconds": round(time.perf_counter() - started, 4)},
        "predictions": predictions,
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    payload["sha256"] = hashlib.sha256(raw).hexdigest()
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print("THRESHOLDS", json.dumps(thresholds, ensure_ascii=False), flush=True)
    print("METRICS", json.dumps(metrics, ensure_ascii=False), flush=True)
    print("DONE", args.out, "STATUS", payload["status"], flush=True)
    if not publishable:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
