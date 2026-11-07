from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import db, packaging
from .models import Status, count_by_status, status_label
from .sniff import sniff_file

TAIL = 4000


@dataclass
class GateOutcome:
    status: str
    detail: dict
    evidence_path: str | None = None


def _inside(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _missing_outcome(gate: dict, message: str) -> GateOutcome:
    if gate.get("na_when_missing") and gate.get("na_reason"):
        return GateOutcome(Status.NA.value, {"reason": gate["na_reason"], "missing": message})
    if gate.get("missing", "fail") == "blocked":
        return GateOutcome(Status.BLOCKED.value, {"reason": message})
    return GateOutcome(Status.FAIL.value, {"reason": message})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def gate_file_exists(gate: dict, ctx: dict) -> GateOutcome:
    path = Path(gate["path"])
    if not path.exists():
        return _missing_outcome(gate, f"文件或目录不存在：{path}")
    if path.is_dir() and not gate.get("allow_dir"):
        return GateOutcome(Status.FAIL.value, {"reason": f"期望文件但得到目录：{path}"})
    size = path.stat().st_size if path.is_file() else None
    min_size = int(gate.get("min_size", 0))
    if size is not None and size < min_size:
        return GateOutcome(Status.FAIL.value,
                           {"reason": f"文件过小：{size} < {min_size}", "size": size})
    return GateOutcome(Status.PASS.value, {"path": str(path), "size": size},
                       str(path) if path.is_file() else None)


def gate_sha256(gate: dict, ctx: dict) -> GateOutcome:
    path = Path(gate["path"])
    if not path.is_file():
        return _missing_outcome(gate, f"文件不存在：{path}")
    digest = _sha256(path)
    expected = (gate.get("expected") or "").lower()
    size = path.stat().st_size
    if expected and digest != expected:
        return GateOutcome(Status.FAIL.value,
                           {"expected": expected, "actual": digest, "size": size}, str(path))
    return GateOutcome(Status.PASS.value, {"sha256": digest, "size": size}, str(path))


def gate_elf_arch(gate: dict, ctx: dict) -> GateOutcome:
    path = Path(gate["path"])
    if not path.is_file():
        return _missing_outcome(gate, f"文件不存在：{path}")
    info = sniff_file(path)
    if info["format"] != "elf":
        return GateOutcome(Status.FAIL.value, {"reason": "不是 ELF", "format": info["format"]})
    expected = gate.get("arch")
    if expected and info["arch"] != expected:
        return GateOutcome(Status.FAIL.value,
                           {"expected": expected, "actual": info["arch"], **info["detail"]},
                           str(path))
    return GateOutcome(Status.PASS.value, info, str(path))


def gate_nro_header(gate: dict, ctx: dict) -> GateOutcome:
    path = Path(gate["path"])
    if not path.is_file():
        return _missing_outcome(gate, f"文件不存在：{path}")
    size = path.stat().st_size
    with open(path, "rb") as fh:
        head = fh.read(0x20)
    if size < 0x200:
        return GateOutcome(Status.FAIL.value, {"reason": f"NRO 过小：{size} B"})
    if head[0x10:0x14] != b"NRO0":
        return GateOutcome(Status.FAIL.value,
                           {"reason": "0x10 处没有 NRO0", "head": head[:0x20].hex()})
    first = int.from_bytes(head[:4], "little")
    branch = (first & 0xFC000000) == 0x14000000
    if not branch:
        return GateOutcome(Status.FAIL.value,
                           {"reason": "首指令不是 ARM64 分支", "head": head[:4].hex()})
    return GateOutcome(Status.PASS.value,
                       {"size": size, "sha256": _sha256(path), "entry_branch": True},
                       str(path))


def gate_package_integrity(gate: dict, ctx: dict) -> GateOutcome:
    path = Path(gate["path"])
    if not path.is_file():
        return _missing_outcome(gate, f"安装包不存在：{path}")
    try:
        detail = packaging.verify_package(path)
    except packaging.PackageError as exc:
        return GateOutcome(Status.FAIL.value, {"reason": str(exc)}, str(path))
    return GateOutcome(Status.PASS.value, detail, str(path))


def gate_command(gate: dict, ctx: dict) -> GateOutcome:
    command = [str(part) for part in gate["command"]]
    cwd = Path(gate.get("cwd") or ctx["work_dir"])
    cwd.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({str(k): str(v) for k, v in gate.get("env", {}).items()})
    env["PORTFACTORY_JOB"] = ctx["job_id"]
    timeout = int(gate.get("timeout", 300))
    log_path = Path(ctx["job_dir"]) / "logs" / f"gate_{ctx['stage_id']}_{gate['id']}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        proc = subprocess.run(
            command, cwd=str(cwd), env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as exc:
        log_path.write_text(f"$ {' '.join(command)}\n{exc}\n", encoding="utf-8")
        return GateOutcome(Status.BLOCKED.value,
                           {"reason": f"命令不可用：{command[0]}", "error": str(exc)},
                           str(log_path))
    except subprocess.TimeoutExpired as exc:
        output = (exc.output or "") if isinstance(exc.output, str) else ""
        log_path.write_text(f"$ {' '.join(command)}\nTIMEOUT {timeout}s\n{output}", encoding="utf-8")
        return GateOutcome(Status.FAIL.value,
                           {"reason": f"超时 {timeout}s", "output_tail": output[-TAIL:]},
                           str(log_path))

    output = proc.stdout or ""
    log_path.write_text(f"$ {' '.join(command)}\n\n{output}", encoding="utf-8")
    expected_exit = int(gate.get("expected_exit", 0))
    detail = {"command": command, "exit": proc.returncode, "output_tail": output[-TAIL:]}
    if proc.returncode != expected_exit:
        return GateOutcome(Status.FAIL.value, detail, str(log_path))
    return GateOutcome(Status.PASS.value, detail, str(log_path))


def gate_manual_attestation(gate: dict, ctx: dict) -> GateOutcome:
    att_path = Path(gate["path"])
    evidence_dir = Path(gate.get("evidence_dir") or Path(ctx["job_dir"]) / "evidence")
    if not att_path.is_file():
        return GateOutcome(Status.BLOCKED.value,
                           {"reason": "缺少真机验收记录", "expected": str(att_path)})
    if not _inside(att_path, evidence_dir):
        return GateOutcome(Status.FAIL.value,
                           {"reason": "验收记录不在任务证据目录内", "path": str(att_path)})
    try:
        data = json.loads(att_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return GateOutcome(Status.FAIL.value, {"reason": f"验收记录不是合法 JSON：{exc}"},
                           str(att_path))

    if data.get("job_id") != ctx["job_id"]:
        return GateOutcome(Status.FAIL.value,
                           {"reason": "验收记录不属于本任务", "recorded": data.get("job_id")},
                           str(att_path))
    missing_meta = [k for k in ("tester", "device", "date") if not data.get(k)]
    if missing_meta:
        return GateOutcome(Status.FAIL.value,
                           {"reason": "验收记录缺少字段", "fields": missing_meta}, str(att_path))

    checks = {}
    for item in data.get("checks", []):
        if isinstance(item, dict) and item.get("id"):
            checks[item["id"]] = item
    required = list(gate.get("required_checks", []))
    if not required:
        return GateOutcome(Status.FAIL.value, {"reason": "闸门未声明 required_checks"},
                           str(att_path))

    absent = [cid for cid in required if cid not in checks]
    if absent:
        return GateOutcome(Status.BLOCKED.value,
                           {"reason": "验收记录缺少检查项", "checks": absent}, str(att_path))

    failed = [cid for cid in required if checks[cid].get("result") != "pass"]
    if failed:
        return GateOutcome(Status.FAIL.value,
                           {"reason": "真机检查未通过", "checks": failed}, str(att_path))

    proof = []
    for cid in required:
        rel = checks[cid].get("evidence")
        if not rel:
            return GateOutcome(Status.FAIL.value,
                               {"reason": f"检查项 {cid} 声称通过但没有证据"}, str(att_path))
        ev_path = (evidence_dir / rel).resolve()
        if not _inside(ev_path, evidence_dir):
            return GateOutcome(Status.FAIL.value,
                               {"reason": f"证据路径越界：{rel}"}, str(att_path))
        if not ev_path.is_file() or ev_path.stat().st_size == 0:
            return GateOutcome(Status.FAIL.value,
                               {"reason": f"证据文件缺失或为空：{rel}"}, str(att_path))
        proof.append({
            "check": cid,
            "evidence": rel,
            "size": ev_path.stat().st_size,
            "sha256": _sha256(ev_path),
        })

    return GateOutcome(Status.PASS.value, {
        "tester": data["tester"],
        "device": data["device"],
        "date": data["date"],
        "checks": proof,
    }, str(att_path))


def gate_release_ready(gate: dict, ctx: dict) -> GateOutcome:
    prior = ctx.get("prior_results", [])
    required = [row for row in prior if row.get("required")]
    if not required:
        return GateOutcome(Status.FAIL.value, {"reason": "发布前没有任何必需闸门"})
    counts = count_by_status(required)
    detail = {"counts": counts, "labels": {k: status_label(k) for k in counts}}
    if counts[Status.FAIL.value]:
        return GateOutcome(Status.FAIL.value, detail)
    if counts[Status.BLOCKED.value]:
        return GateOutcome(Status.BLOCKED.value, detail)
    if counts[Status.NOT_RUN.value] or counts[Status.PENDING.value] or counts[Status.RUNNING.value]:
        return GateOutcome(Status.NOT_RUN.value, detail)
    if counts[Status.PASS.value] == 0:
        return GateOutcome(Status.FAIL.value, detail)
    return GateOutcome(Status.PASS.value, detail)


GATE_TYPES = {
    "file_exists": gate_file_exists,
    "sha256": gate_sha256,
    "elf_arch": gate_elf_arch,
    "nro_header": gate_nro_header,
    "package_integrity": gate_package_integrity,
    "command": gate_command,
    "manual_attestation": gate_manual_attestation,
    "release_ready": gate_release_ready,
}


def run_gate(gate: dict, ctx: dict) -> GateOutcome:
    handler = GATE_TYPES.get(gate["type"])
    if handler is None:
        raise ValueError(f"unknown gate type: {gate['type']}")
    try:
        return handler(gate, ctx)
    except Exception as exc:  # a crashing gate must never look like a pass
        return GateOutcome(Status.FAIL.value,
                           {"reason": f"闸门执行异常：{type(exc).__name__}: {exc}"})
