from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .intake import sha256_file
from .portkit import cache

KINDS = {"analysis_only", "module_source", "buildable_project", "aot_project"}
QUALIFICATION = {"whole_game_behavior": "not_run", "device_test": "not_run", "release_allowed": False}


class HandoffError(ValueError):
    pass


def file_records(root: Path) -> list[dict]:
    if root.is_symlink() or root.is_junction():
        raise HandoffError(f"工程根目录不能是链接：{root}")
    root = root.resolve()
    try:
        records = [{"path": p.relative_to(root).as_posix(), "size": p.stat().st_size,
                    "sha256": sha256_file(p)} for p in cache.files(root)]
    except (OSError, cache.CacheError) as exc:
        raise HandoffError(str(exc)) from exc
    if not records:
        raise HandoffError("不能交接空工程")
    return records


def check_project(manifest: dict, root: Path) -> None:
    if file_records(root) != manifest["project"]["files"]:
        raise HandoffError("工程文件集合或内容与交接清单不符")


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise HandoffError(message)


def _validate(data: dict) -> None:
    _need(isinstance(data, dict), "交接清单必须是对象")
    _need(type(data.get("schema")) is int and data["schema"] == 1, "只支持交接 schema 1")
    _need(isinstance(data.get("kind"), str) and data["kind"] in KINDS, "未知工程类型")
    for key in ("producer", "source_platform"):
        _need(isinstance(data.get(key), str) and bool(data[key].strip()), f"缺少 {key}")
    _need(isinstance(data.get("unresolved"), list) and all(
        isinstance(item, str) and item.strip() for item in data["unresolved"]), "unresolved 必须为字符串列表")
    _need(data.get("qualification") == QUALIFICATION and
          data["qualification"].get("release_allowed") is False, "交接清单不得自授游戏或发布资格")
    for key, path_key in (("spec", "path"), ("project", "root")):
        item = data.get(key)
        _need(isinstance(item, dict), f"缺少 {key}")
        _need(isinstance(item.get(path_key), str) and Path(item[path_key]).is_absolute(),
              f"{key}.{path_key} 必须为绝对路径")
    _need(bool(re.fullmatch(r"[0-9a-f]{64}", str(data["spec"].get("sha256", "")))), "spec 缺少完整 SHA256")
    records = data["project"].get("files")
    _need(isinstance(records, list) and bool(records), "工程文件清单不能为空")
    seen = set()
    for item in records:
        _need(isinstance(item, dict), "文件记录必须是对象")
        rel = item.get("path")
        _need(isinstance(rel, str) and bool(rel), "文件缺少相对路径")
        parts = PurePosixPath(rel).parts
        _need(not PurePosixPath(rel).is_absolute() and not any(
            p in ("..", ".git") for p in parts) and "\\" not in rel and ":" not in rel
            and PurePosixPath(rel).as_posix() == rel and rel != ".", f"文件路径越界或不规范：{rel}")
        normalized = os.path.normcase(rel)
        _need(normalized not in seen, f"文件路径重复：{rel}")
        seen.add(normalized)
        _need(type(item.get("size")) is int and item["size"] >= 0, f"文件大小无效：{rel}")
        _need(bool(re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))), f"文件哈希无效：{rel}")
    expected = cache.digest({k: v for k, v in data.items() if k != "id"})
    _need(data.get("id") == expected, "交接清单身份摘要不符")


def create(project: Path, spec_path: Path, *, kind: str, producer: str,
           source_platform: str, unresolved: list[str] | None = None) -> dict:
    project, spec_path = Path(project).absolute(), Path(spec_path).resolve()
    try:
        data = {"schema": 1, "kind": kind, "producer": producer, "source_platform": source_platform,
                "project": {"root": str(project), "files": file_records(project)},
                "spec": {"path": str(spec_path), "sha256": sha256_file(spec_path)},
                "unresolved": unresolved if unresolved is not None else [],
                "qualification": dict(QUALIFICATION)}
    except OSError as exc:
        raise HandoffError(str(exc)) from exc
    data["id"] = cache.digest(data)
    _validate(data)
    return data


def write(path: Path, manifest: dict) -> None:
    _validate(manifest)
    path = Path(path).resolve()
    _need(not path.is_relative_to(Path(manifest["project"]["root"]).resolve()),
          "交接清单不能写入工程内部")
    _need(path != Path(manifest["spec"]["path"]).resolve(), "交接清单不能覆盖 spec")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid4().hex}.part")
    try:
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load(path: Path, *, require_buildable: bool = False) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        _validate(data)
        if require_buildable:
            _need(data["kind"] in ("buildable_project", "aot_project"),
                  "伪代码或孤立模块不能作为完整工程进入移植线")
            _need(not data["unresolved"], "工程还有未解决依赖，不能进入移植线")
        _need(sha256_file(Path(data["spec"]["path"])) == data["spec"]["sha256"], "spec 已变化")
        check_project(data, Path(data["project"]["root"]))
        return data
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"交接清单不可用：{exc}") from exc
