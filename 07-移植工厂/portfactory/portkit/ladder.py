"""成品资格阶梯：把已有阶段记录换算成 R0–R6，只复述证据，不执行构建或运行。

每一级都必须能被当前文件和哈希复核；任何一级缺失，后面的等级不会因为“看起来做过”而算通过。
真机与发布两级永远需要额外入口，本地状态不会自动授予。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import cache

LEVELS = [
    ("R0", "准入", "spec 与本次构建记录一致，admit 通过"),
    ("R1", "源码冻结", "fetch 快照仍在，内容未变"),
    ("R2", "可构建", "本次构建产物存在且哈希未变"),
    ("R3", "静态闸门", "打包成功，声明的闸门全部通过"),
    ("R4", "主机运行", "当前产物在主机上跑到全部检查点"),
    ("R5", "真机", "真机执行器与人工验收记录"),
    ("R6", "发布", "发布清单与单独授权"),
]
ORDER = [item[0] for item in LEVELS]
NAMES = {item[0]: item[1] for item in LEVELS}

R5_REASON = "portkit 还没有真机执行器与验收记录入口（P3-B 未实现）"
R6_REASON = "发布资格不由本地状态自动授予；需要单独的发布清单和授权"


class LadderError(ValueError):
    pass


def _level(level_id: str, status: str, evidence: str = "", reason: str = "") -> dict:
    return {"id": level_id, "name": NAMES[level_id], "status": status,
            "evidence": evidence, "reason": reason}


def _load_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _stage(target: dict, name: str) -> dict:
    return (target.get("stages") or {}).get(name) or {}


def assess(spec, target_name: str, work_root: Path) -> dict:
    work = (Path(work_root) / spec.id).resolve()
    state_path = work / "state.json"
    base = {
        "schema": 1,
        "spec": {"id": spec.id, "title": spec.title,
                 "path": str(Path(spec.path).resolve()) if spec.path else None,
                 "sha256": cache.digest(spec.raw)},
        "target": target_name,
        "work": str(work),
        "release_allowed": False,
        "levels": [],
    }
    state = _load_json(state_path) if state_path.is_file() else None
    if state is None:
        reason = "还没有构建记录；先执行 port build" if not state_path.is_file() \
            else "状态文件损坏或格式不对"
        return _finish(base, _unbuilt(reason), [reason, f"R5 真机：{R5_REASON}",
                                                f"R6 发布：{R6_REASON}"])

    target = (state.get("targets") or {}).get(target_name) or {}
    if not target:
        reason = f"还没有构建过目标 {target_name}；先执行 port build"
        return _finish(base, _unbuilt(reason), [reason, f"R5 真机：{R5_REASON}",
                                                f"R6 发布：{R6_REASON}"])

    levels: list[dict] = []
    blockers: list[str] = []
    blocked = False

    def add(level_id: str, ok: bool, evidence: str, reason: str) -> None:
        nonlocal blocked
        if blocked:
            levels.append(_level(level_id, "not_run", reason="前一级未达成"))
            return
        if ok:
            levels.append(_level(level_id, "pass", evidence=evidence))
        else:
            levels.append(_level(level_id, "blocked", evidence=evidence, reason=reason))
            blockers.append(f"{level_id} {NAMES[level_id]}：{reason}")
            blocked = True

    # ---- R0 准入
    record_path = Path(target.get("record", "")) if target.get("record") else None
    record = _load_json(record_path) if record_path and record_path.is_file() else None
    if record is None:
        add("R0", False, "", "工作目录缺少构建记录，无法确认 spec 版本")
    elif record.get("spec_sha256") != base["spec"]["sha256"]:
        add("R0", False, str(record_path), "spec 在构建之后被改动，需要重新构建")
    elif _stage(target, "admit").get("status") != "pass":
        add("R0", False, str(record_path), "admit 未通过")
    else:
        add("R0", True, str(record_path), "")

    # ---- R1 源码冻结
    fetch = _stage(target, "fetch")
    if fetch.get("status") != "pass":
        add("R1", False, "", "fetch 未通过")
    elif not fetch.get("outputs") or not cache.unchanged(fetch["outputs"]):
        add("R1", False, str((fetch.get("paths") or {}).get("src", "")),
            "源码快照已丢失或内容变化")
    else:
        add("R1", True, str((fetch.get("paths") or {}).get("src", "")), "")

    # ---- R2 可构建
    build = _stage(target, "build")
    identity = (build.get("detail") or {}).get("artifact_identity")
    if build.get("status") != "pass" or not identity:
        add("R2", False, "", "build 未通过或缺少产物身份")
    elif not cache.unchanged([identity]):
        add("R2", False, str(identity.get("path", "")), "产物在构建之后被改动或删除")
    else:
        add("R2", True, str(identity.get("path", "")), "")

    # ---- R3 静态闸门
    package = _stage(target, "package")
    verify = _stage(target, "verify")
    gates_detail = (verify.get("detail") or {}).get("gates") or {}
    if package.get("status") != "pass" or verify.get("status") != "pass":
        add("R3", False, "", "package 或 verify 未通过")
    elif not gates_detail:
        add("R3", False, "", "verify 没有记录任何闸门结果")
    elif any((outcome or {}).get("status") != "pass" for outcome in gates_detail.values()):
        failed = [name for name, outcome in gates_detail.items()
                  if (outcome or {}).get("status") != "pass"]
        add("R3", False, "", "闸门未通过：" + ", ".join(failed))
    elif not package.get("outputs") or not cache.unchanged(package["outputs"]):
        add("R3", False, "", "打包产物在验证之后被改动或删除")
    else:
        evidence = (package.get("detail") or {}).get("path", "")
        add("R3", True, str(evidence), "")

    # ---- R4 主机运行
    runtime = target.get("runtime") or {}
    session = _load_json(Path(runtime["record"])) if runtime.get("record") else None
    if not runtime or not session:
        add("R4", False, "", "还没有主机运行证据；执行 port run")
    elif runtime.get("status") != "pass" or session.get("status") != "pass":
        add("R4", False, str(runtime.get("record", "")), "运行证据未通过")
    elif not session.get("artifact_unchanged"):
        add("R4", False, str(runtime.get("record", "")), "运行期间产物被改写")
    elif session.get("timed_out") or session.get("missing") or session.get("out_of_order"):
        add("R4", False, str(runtime.get("record", "")), "运行超时或检查点不完整")
    elif not identity or (session.get("artifact") or {}).get("sha256") != identity.get("sha256"):
        add("R4", False, str(runtime.get("record", "")), "运行证据对应的不是当前产物")
    elif not cache.unchanged([identity]):
        add("R4", False, str(runtime.get("record", "")), "产物在运行之后被改动或删除")
    elif runtime.get("plan_sha256") != (session.get("plan") or {}).get("sha256"):
        add("R4", False, str(runtime.get("record", "")), "运行记录与登记的计划哈希不一致")
    else:
        plan_path = runtime.get("plan")
        if plan_path and Path(plan_path).is_file() and \
                cache.stamp(Path(plan_path))["sha256"] != runtime.get("plan_sha256"):
            add("R4", False, str(runtime.get("record", "")),
                "运行计划在证据生成之后被改动，需要重跑")
        else:
            add("R4", True, str(runtime.get("record", "")), "")

    levels.append(_level("R5", "blocked", reason=R5_REASON))
    blockers.append(f"R5 真机：{R5_REASON}")
    levels.append(_level("R6", "blocked", reason=R6_REASON))
    blockers.append(f"R6 发布：{R6_REASON}")
    return _finish(base, levels, blockers)


def _unbuilt(reason: str) -> list[dict]:
    levels = [_level(level_id, "blocked", reason=reason) for level_id in ORDER[:5]]
    levels.append(_level("R5", "blocked", reason=R5_REASON))
    levels.append(_level("R6", "blocked", reason=R6_REASON))
    return levels


def _finish(base: dict, levels: list[dict], blockers: list[str]) -> dict:
    passed = [item["id"] for item in levels if item["status"] == "pass"]
    level = passed[-1] if passed else None
    if level is None:
        next_level = "R0"
    else:
        index = ORDER.index(level) + 1
        next_level = ORDER[index] if index < len(ORDER) else None
    return {**base, "levels": levels, "level": level, "next": next_level,
            "blockers": blockers}


def render(result: dict) -> str:
    spec = result["spec"]
    current = f"{result['level']} {NAMES[result['level']]}" if result["level"] else "未达到 R0"
    upcoming = f"{result['next']} {NAMES[result['next']]}" if result["next"] else "无"
    lines = [f"# {spec['title']} → {result['target']} 资格评估", "",
             f"- spec：`{spec['path']}`（{spec['sha256'][:16]}…）",
             f"- 工作目录：`{result['work']}`",
             f"- 当前等级：**{current}**；下一级：{upcoming}",
             "- 发布资格：禁止（本地状态不会自动授予）", "",
             "| 等级 | 名称 | 状态 | 依据 |", "|---|---|---|---|"]
    for item in result["levels"]:
        note = item.get("evidence") or item.get("reason") or ""
        if isinstance(note, str) and len(note) > 80:
            note = "…" + note[-79:]
        lines.append(f"| {item['id']} | {item['name']} | {item['status']} | {note} |")
    if result["blockers"]:
        lines += ["", "阻断："]
        lines += [f"- {item}" for item in result["blockers"]]
    lines += ["", "等级定义：" + "；".join(f"{lid} {name}＝{desc}"
                                          for lid, name, desc in LEVELS)]
    lines += ["", "本评估只复述已有记录并复核文件哈希，不执行构建或运行；"
                  "R5/R6 必须通过真机与发布入口单独取得。", ""]
    return "\n".join(lines)
