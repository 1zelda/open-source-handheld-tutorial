"""构建故障 → AI 补丁 → 真实重建 → 结论。

这个模块只做两件不依赖模型的事：
  1. 把一次真实失败的构建整理成自足的请求（证据 + 硬约束 + 可复制提示词）；
  2. 校验外部提交的补丁，并把它交给生产 runner 在全新副本里重建。

“修好了”从不来自模型自述，只来自 runner 的 build/package/verify 全通过；
补丁不许碰 spec、闸门、portkit 代码或 .git。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from ..research import write_json
from . import cache

MAX_PATCH_BYTES = 262_144
MAX_FILES = 12
MAX_CHANGED_LINES = 600
MAX_EVIDENCE_BYTES = 131_072
MAX_FILE_BYTES = 24_576
MAX_LOG_TAIL = 8_000
DEFAULT_BUDGET = 3

PORTKIT_DIR = Path(__file__).resolve().parent
FACTORY_DIR = PORTKIT_DIR.parent.parent

_PATH_TOKEN = re.compile(r"[A-Za-z0-9_@+./:\\-]+\.(?:c|h|cc|cpp|cxx|hpp|hh|s|S|m|mm|mk|cmake|txt|json|xml|ac|am|py|lua|sh|cfg|conf|ini)\b")


class RepairError(ValueError):
    pass


@dataclass
class PatchInfo:
    files: list[dict] = field(default_factory=list)
    added: int = 0
    removed: int = 0
    sha256: str = ""

    def as_dict(self) -> dict:
        return {"files": self.files, "added": self.added, "removed": self.removed,
                "sha256": self.sha256}


def _diff_path(raw: str) -> str:
    text = raw.replace("\r", "").rstrip("\n")
    if "\t" in text:
        text = text.split("\t", 1)[0]
    text = text.rstrip()
    if text.startswith('"'):
        raise RepairError("补丁路径带引号（含空格或特殊字符），请用 git diff 生成后再提交")
    if text == "/dev/null":
        return ""
    return text


def _clean_path(raw: str, where: str) -> str:
    path = raw.strip()
    for prefix in ("a/", "b/"):
        if path.startswith(prefix):
            path = path[2:]
            break
    if not path:
        raise RepairError(f"{where} 缺少文件路径")
    if "\\" in path:
        raise RepairError(f"补丁路径含反斜杠，拒绝：{raw}")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise RepairError(f"补丁路径是绝对路径，拒绝：{raw}")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise RepairError(f"补丁路径越界，拒绝：{raw}")
    if not parts:
        raise RepairError(f"补丁路径为空：{raw}")
    return "/".join(parts)


def parse_patch(text: str, *, project_root: Path | None = None,
                spec_path: Path | None = None) -> PatchInfo:
    blob = text.encode("utf-8")
    if len(blob) > MAX_PATCH_BYTES:
        raise RepairError(f"补丁超过 {MAX_PATCH_BYTES} 字节上限")
    if "GIT binary patch" in text or text.startswith("Binary files "):
        raise RepairError("不接受二进制补丁")

    info = PatchInfo(sha256=cache.digest({"patch": text}))
    seen: dict[str, dict] = {}
    current: dict | None = None
    in_hunk = False
    for raw in text.splitlines():
        line = raw.replace("\r", "")
        if line.startswith(("diff --git ", "diff -", "Index: ", "Only in ")):
            current, in_hunk = None, False
            continue
        if line.startswith("GIT binary patch") or line.startswith("Binary files "):
            raise RepairError("不接受二进制补丁")
        if line.startswith(("old mode ", "new mode ", "deleted file mode ",
                            "new file mode 100755", "new file mode 100644", "index ")):
            if line.startswith(("old mode ", "new mode ", "deleted file mode ",
                                "new file mode 100755")):
                raise RepairError("修复补丁不许删除文件、改模式或新增可执行文件")
            continue
        if not in_hunk and line.startswith("--- "):
            current = {"from": _diff_path(line[4:]), "to": "", "added": 0, "removed": 0}
            continue
        if current is not None and not in_hunk and line.startswith("+++ "):
            current["to"] = _diff_path(line[4:])
            continue
        if line.startswith("@@"):
            if current is None:
                raise RepairError("补丁里出现没有文件头的 hunk")
            in_hunk = True
            if "to" not in current:
                raise RepairError("补丁文件头不完整（缺 +++ 行）")
            raw_path = current["to"] or current["from"]
            if not current["to"]:
                raise RepairError("修复补丁不许删除文件")
            path = _clean_path(raw_path, "文件头")
            _check_target(path, project_root, spec_path)
            entry = seen.setdefault(path, {"path": path, "added": 0, "removed": 0,
                                           "new": current["from"] == ""})
            current["path"] = path
            current["entry"] = entry
            continue
        if in_hunk and current is not None:
            if line.startswith("+") and not line.startswith("+++"):
                info.added += 1
                current["entry"]["added"] += 1
            elif line.startswith("-") and not line.startswith("---"):
                info.removed += 1
                current["entry"]["removed"] += 1
            continue
        if in_hunk and not line.startswith((" ", "+", "-", "\\")):
            in_hunk = False

    info.files = [seen[p] for p in sorted(seen)]
    if not info.files:
        raise RepairError("补丁里没有任何文件改动（需要 git apply 能识别的 unified diff）")
    if len(info.files) > MAX_FILES:
        raise RepairError(f"补丁改了 {len(info.files)} 个文件，超过 {MAX_FILES} 个上限")
    if info.added + info.removed > MAX_CHANGED_LINES:
        raise RepairError(f"补丁改动 {info.added + info.removed} 行，超过 {MAX_CHANGED_LINES} 行上限")
    if info.added + info.removed == 0:
        raise RepairError("补丁没有增删任何行")
    return info


def _check_target(path: str, project_root: Path | None, spec_path: Path | None) -> None:
    parts = path.split("/")
    if ".git" in parts:
        raise RepairError(f"补丁不能改版本库元数据：{path}")
    if project_root is None:
        top = parts[0]
        if top in ("portfactory", "specs", "state", "tests") and (FACTORY_DIR / top).exists():
            raise RepairError(f"补丁不能改移植工厂自身的 {top}/：{path}")
        return
    root = project_root.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise RepairError(f"补丁目标越出工程目录：{path}")
    if spec_path is not None and target == Path(spec_path).resolve():
        raise RepairError("补丁不能改本次 spec")
    if target.is_relative_to(PORTKIT_DIR):
        raise RepairError(f"补丁不能改 portkit 的闸门或流水线代码：{path}")
    if root.is_relative_to(FACTORY_DIR):
        top = path.split("/")[0]
        if top in ("portfactory", "specs", "state", "tests"):
            raise RepairError(f"补丁不能改移植工厂自身的 {top}/：{path}")


def _note() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _failing_stage(result: dict) -> dict | None:
    for stage in result.get("stages", []):
        if stage["status"] != "pass":
            return stage
    return None


def _safe_text(path: Path, limit: int) -> str:
    try:
        blob = path.read_bytes()
    except OSError:
        return ""
    if b"\0" in blob[:4096]:
        return ""
    return blob[:limit].decode("utf-8", "replace")


def _source_root(runner, target: str, stage_id: str) -> Path | None:
    entry = runner.state.get("targets", {}).get(target, {}).get("stages", {}).get(stage_id, {})
    raw = (entry.get("paths") or {}).get("src")
    return Path(raw) if raw and Path(raw).is_dir() else None


def _hint_files(log_text: str, src: Path) -> list[str]:
    found: list[str] = []
    root = src.resolve()
    for token in _PATH_TOKEN.findall(log_text):
        raw = token.replace("\\", "/")
        candidates = []
        try:
            candidates.append(Path(raw).resolve().relative_to(root).as_posix())
        except (OSError, ValueError):
            pass
        candidates.append(raw.lstrip("./"))
        for candidate in candidates:
            if not candidate or candidate.startswith("/") or ":/" in candidate:
                continue
            if (src / candidate).is_file() and candidate not in found:
                found.append(candidate)
                break
    return found


def build_request(runner, result: dict, *, includes: list[str] | None = None,
                  budget: int = DEFAULT_BUDGET) -> dict:
    stage = _failing_stage(result)
    if stage is None:
        raise RepairError("本次运行没有失败阶段，不需要修复请求")
    target = result["target"]
    src = _source_root(runner, target, stage["id"]) or _source_root(runner, target, "fetch")
    logs = []
    detail = stage.get("detail") or {}
    if detail.get("reason"):
        logs.append({"label": "失败原因", "path": "", "tail": str(detail["reason"])})
    if detail.get("tail"):
        logs.append({"label": "日志尾部", "path": "", "tail": str(detail["tail"])[:MAX_LOG_TAIL]})
    for step in detail.get("steps") or []:
        if step.get("log"):
            logs.append({"label": step.get("step", "step"), "path": str(step["log"]),
                         "tail": _safe_text(Path(step["log"]), MAX_LOG_TAIL)})
    if stage["id"] == "verify":
        gates = (detail.get("gates") or {})
        logs.append({"label": "闸门结果", "path": "",
                     "tail": "\n".join(f"{k}: {v.get('status')} {v.get('detail')}"
                                       for k, v in gates.items())})

    files = []
    evidence = []
    if src is not None:
        try:
            listing = cache.files(src)
        except (OSError, ValueError):
            listing = []
        for path in listing:
            rel = path.relative_to(src).as_posix()
            files.append({"path": rel, "size": path.stat().st_size})
            if len(files) >= 600:
                break
        wanted = []
        for item in includes or []:
            cleaned = item.replace("\\", "/").lstrip("./")
            if cleaned and cleaned not in wanted:
                wanted.append(cleaned)
        for log in logs:
            for rel in _hint_files(log.get("tail", ""), src):
                if rel not in wanted:
                    wanted.append(rel)
        budget_left = MAX_EVIDENCE_BYTES
        for rel in wanted:
            path = (src / rel).resolve()
            if not path.is_file() or not path.is_relative_to(src.resolve()):
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = _safe_text(path, MAX_FILE_BYTES)
            if not text:
                continue
            if len(text.encode("utf-8")) > budget_left:
                break
            budget_left -= len(text.encode("utf-8"))
            evidence.append({"path": rel, "size": path.stat().st_size, "text": text})

    request = {
        "schema": 1,
        "id": "rep_" + uuid4().hex,
        "created_at": _note(),
        "spec": {"path": str(Path(runner.spec.path).resolve()), "sha256": result["spec_sha256"]},
        "target": target,
        "work": str(runner.work_root.parent),
        "handoff": str(Path(runner.handoff_path).resolve()) if runner.handoff_path else None,
        "attempt": 1,
        "budget": int(budget),
        "failing_stage": stage["id"],
        "reason": str(detail.get("reason") or ""),
        "run_record": result.get("record"),
        "source_root": str(src) if src else None,
        "logs": logs,
        "files": files,
        "included": evidence,
        "constraints": {"max_files": MAX_FILES, "max_changed_lines": MAX_CHANGED_LINES,
                        "max_bytes": MAX_PATCH_BYTES},
    }
    request["prompt"] = prompt_text(request)
    return request


def prompt_text(request: dict) -> str:
    return f"""你是移植构建修复助手。下面的证据来自一次真实构建，不要假设证据里没有出现的代码。

任务：让这个目标（{request['target']}，阶段 {request['failing_stage']}）真实构建通过。
只输出一个 unified diff，`git apply` 必须能直接应用；不要输出解释、shell 命令、整文件替换或“建议”。

硬约束（违反会被直接拒绝）：
- 只能改工程源码里的文本文件；不许碰 .git、spec、portfactory/portkit 代码或任何闸门。
- 最多 {MAX_FILES} 个文件、{MAX_CHANGED_LINES} 行增删、{MAX_PATCH_BYTES} 字节；不许删除文件、改权限位或提交二进制补丁。
- 做针对失败点的最小修改；不许通过跳过检查、伪造产物、改测试或改构建断言来“通过”。
- 如果证据不足，只输出一行 `INSUFFICIENT_EVIDENCE: <缺少什么>`，不要猜。

提交方式：
  py -3 工厂.py port repair-submit "<request.json>" --patch <你的补丁.diff> --producer <你的名字或工具>

失败原因：
{request['reason'] or '(见日志)'}
"""


def render_markdown(request: dict) -> str:
    lines = [f"# 修复请求 {request['id']}", "", request["prompt"], "", "## 工程文件"]
    lines += [f"- {item['path']} ({item['size']} B)" for item in request["files"]] or ["- （未获取到源码快照）"]
    lines += ["", "## 日志"]
    for log in request["logs"]:
        lines += ["", f"### {log['label']}" + (f" `{log['path']}`" if log.get("path") else ""), "```",
                  log.get("tail", "")[-MAX_LOG_TAIL:], "```"]
    if request["included"]:
        lines += ["", "## 相关源码"]
        for item in request["included"]:
            lines += ["", f"### {item['path']}", "```",
                      item["text"][:MAX_FILE_BYTES], "```"]
    lines.append("")
    return "\n".join(lines)


def save_request(root: Path, request: dict) -> tuple[Path, Path]:
    folder = Path(root) / "repair" / "requests"
    folder.mkdir(parents=True, exist_ok=True)
    json_path = folder / f"attempt-{request['attempt']:02d}.json"
    md_path = folder / f"attempt-{request['attempt']:02d}.md"
    write_json(json_path, request)
    md_path.write_text(render_markdown(request), encoding="utf-8")
    return json_path, md_path


def load_request(path: Path) -> dict:
    import json
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepairError(f"修复请求读不出来：{exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise RepairError("不是有效的修复请求（schema 1）")
    for key in ("spec", "target", "work", "budget", "failing_stage"):
        if key not in data:
            raise RepairError(f"修复请求缺少字段 {key}")
    return data


def history_path(work_root: Path) -> Path:
    return Path(work_root) / "repair" / "history.json"


def load_history(work_root: Path) -> dict:
    import json
    path = history_path(work_root)
    if not path.is_file():
        return {"schema": 1, "attempts": [], "accepted": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RepairError(f"修复历史损坏，拒绝继续：{exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise RepairError("修复历史格式不对，拒绝继续")
    return data


def save_history(work_root: Path, history: dict) -> Path:
    path = history_path(work_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, history)
    return path


def attempts_used(history: dict, spec_sha: str, target: str) -> int:
    return sum(1 for item in history.get("attempts", [])
               if item.get("spec_sha256") == spec_sha and item.get("target") == target)


def seen_patch(history: dict, spec_sha: str, target: str) -> set[str]:
    return {item.get("patch", {}).get("sha256") for item in history.get("attempts", [])
            if item.get("spec_sha256") == spec_sha and item.get("target") == target}


def check_budget(history: dict, request: dict, patch: PatchInfo) -> None:
    spec_sha = request["spec"]["sha256"]
    target = request["target"]
    used = attempts_used(history, spec_sha, target)
    if used >= int(request["budget"]):
        raise RepairError(f"修复预算已用完（{used}/{request['budget']}），停止尝试")
    if patch.sha256 in seen_patch(history, spec_sha, target):
        raise RepairError("这个补丁与之前某次尝试完全相同，拒绝重复提交")


def record_attempt(history: dict, request: dict, *, producer: str, note: str,
                   patch: PatchInfo, patch_path: Path, result: dict | None,
                   outcome: str, reason: str = "") -> dict:
    stages = {stage["id"]: stage for stage in (result or {}).get("stages", [])}
    build = stages.get("build", {}).get("detail", {})
    package = stages.get("package", {}).get("detail", {})
    verify = stages.get("verify", {}).get("detail", {})
    entry = {
        "attempt": int(request["attempt"]),
        "at": _note(),
        "spec_sha256": request["spec"]["sha256"],
        "target": request["target"],
        "producer": producer,
        "note": note,
        "request": request["id"],
        "patch": {**patch.as_dict(), "path": str(patch_path),
                  "files": [f["path"] for f in patch.files]},
        "outcome": outcome,
        "reason": reason,
        "failing_stage": request["failing_stage"],
        "run_record": (result or {}).get("record"),
        "stage_status": {k: v.get("status") for k, v in stages.items()},
        "artifact": build.get("artifact_identity"),
        "package": {k: package.get(k) for k in ("path", "size", "sha256")} if package else None,
        "gates": {k: v.get("status") for k, v in (verify.get("gates") or {}).items()},
        "device_test": "not_run",
        "release_allowed": False,
    }
    history.setdefault("attempts", []).append(entry)
    return entry


def acceptance_problem(result: dict | None, target: dict) -> str:
    if result is None:
        return "没有运行结果"
    for stage in result.get("stages", []):
        if stage["status"] != "pass":
            detail = stage.get("detail") or {}
            reason = detail.get("reason") or ""
            failed = detail.get("failed") or []
            if not reason and failed:
                reason = "闸门未过：" + ", ".join(failed)
            return f"停在 {stage['id']}：{reason}"
    if not target.get("gates"):
        return "目标没有声明任何闸门，无法判定"
    verify = next((s for s in result.get("stages", []) if s["id"] == "verify"), None)
    gates = (verify or {}).get("detail", {}).get("gates") or {}
    if not gates or any(v.get("status") != "pass" for v in gates.values()):
        return "验证闸门没有全通过"
    build = next((s for s in result.get("stages", []) if s["id"] == "build"), None) or {}
    if not (build.get("detail") or {}).get("artifact_identity"):
        return "没有记录产物身份"
    return ""
