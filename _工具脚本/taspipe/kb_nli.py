# -*- coding: utf-8 -*-
"""NLI 影子层：只给支持/否决提示，绝不改变 kb.query 的三态裁决。"""
import json
import re
import threading
from pathlib import Path

MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
MODEL_REV = "8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c"
CALIBRATION_PATH = Path(__file__).with_name("nli_calibration.json")
_LOCK = threading.Lock()
_STATE = None
STRUCTURED_RE = re.compile(
    r"SHA1|sha1|哈希|指纹|校验和|字节|文件大小|0x[0-9a-fA-F]+|"
    r"(?:A|B|X|Y|スタート|セレクト)\s*[×x*]\s*\d+|(?:→|->)|"
    r"\d+(?:\.\d+)?\s*(?:年|月|日|种|名|人|场|个|支|条|首|文字|B|KB|MB|GB)\b",
    re.IGNORECASE,
)


class NLIError(RuntimeError):
    pass


def _load_calibration():
    if not CALIBRATION_PATH.is_file():
        raise NLIError("NLI 校准件不存在，先跑 kb_nli_calibrate")
    data = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
    if data.get("model", {}).get("revision") != MODEL_REV:
        raise NLIError("NLI 校准件与模型 revision 不一致")
    if data.get("status") != "ready":
        raise NLIError("NLI 校准未通过，生产影子层保持关闭")
    thresholds = data.get("thresholds") or {}
    for key in ("entailment", "contradiction"):
        value = thresholds.get(key)
        if not isinstance(value, (int, float)) or not 0.5 <= value <= 0.99:
            raise NLIError(f"NLI {key} 阈值非法")
    return data


def _load_model(device=None):
    global _STATE
    with _LOCK:
        if _STATE is not None and (device is None or _STATE[1] == device):
            return _STATE
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise NLIError("缺 torch/transformers，NLI 影子层未运行") from exc
        if not torch.cuda.is_available():
            raise NLIError("CUDA 不可用；按显存纪律不静默改 CPU")
        dev = torch.device(device or "cuda:0")
        if dev.type != "cuda":
            raise NLIError("NLI 生产路径只接受 CUDA；CPU 须另批并记录代价")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REV,
                                                  trust_remote_code=False)
        model = AutoModelForSequenceClassification.from_pretrained(
            MODEL_ID, revision=MODEL_REV, trust_remote_code=False,
            dtype=torch.float32,
        ).to(dev).eval()
        _STATE = (tokenizer, dev, model, torch)
        return _STATE


def predict(premise, hypothesis, device=None, max_length=512):
    if not premise or not premise.strip() or not hypothesis or not hypothesis.strip():
        raise NLIError("NLI 需要非空 evidence 与完整 claim")
    tokenizer, dev, model, torch = _load_model(device)
    enc = tokenizer(premise, hypothesis, truncation=True, max_length=max_length,
                    padding=True, return_tensors="pt")
    enc = {k: v.to(dev) for k, v in enc.items()}
    with torch.inference_mode():
        logits = model(**enc).logits[0].float()
        probs = torch.softmax(logits, dim=-1).cpu().tolist()
    labels = {str(k).lower(): str(v).lower() for k, v in model.config.id2label.items()}
    named = {labels.get(str(i), str(i)): float(p) for i, p in enumerate(probs)}
    best = max(named, key=named.get)
    ordered = sorted(named.values(), reverse=True)
    return {"label": best, "probabilities": named,
            "margin": ordered[0] - ordered[1], "device": str(dev),
            "dtype": "float32", "max_length": max_length,
            "premise_chars": len(premise), "hypothesis_chars": len(hypothesis)}


def assess(claim, evidence, *, eligible=True, structured=False, device=None,
           calibration=None):
    base = {"policy": "shadow_only_no_status_change", "model": MODEL_ID,
            "revision": MODEL_REV, "claim_chars": len(claim or ""),
            "evidence_chars": len(evidence or "")}
    if not eligible:
        return {**base, "status": "not_run", "reason": "hard_gate_rejected"}
    if not claim or not claim.strip():
        return {**base, "status": "not_run", "reason": "claim_required"}
    if structured or STRUCTURED_RE.search(claim):
        return {**base, "status": "not_applicable",
                "reason": "structured_fact_not_delegated_to_nli"}
    cal = calibration or _load_calibration()
    pred = predict(evidence, claim, device=device)
    thresholds = cal["thresholds"]
    label = pred["label"]
    prob = pred["probabilities"].get(label, 0.0)
    if label == "contradiction" and prob >= thresholds["contradiction"]:
        decision = "veto_candidate"
    elif label == "entailment" and prob >= thresholds["entailment"]:
        decision = "supports_shadow"
    else:
        decision = "uncertain"
    return {**base, **pred, "status": "shadow", "decision": decision,
            "thresholds": thresholds, "calibration_sha256": cal.get("sha256")}


def ready():
    try:
        cal = _load_calibration()
        _load_model()
        return True, f"ready rev={MODEL_REV[:12]} samples={cal.get('samples')}"
    except NLIError as exc:
        return False, str(exc)
