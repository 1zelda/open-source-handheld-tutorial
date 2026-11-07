from __future__ import annotations

import hashlib
from pathlib import Path

from . import db
from .sniff import DATA_EXTS, EXEC_EXTS, sniff_file, survey_directory

QUICK_HASH_LIMIT = 256 * 1024 * 1024
HEAD_TAIL = 1024 * 1024


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def quick_sha256(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    with open(path, "rb") as fh:
        digest.update(fh.read(HEAD_TAIL))
        if size > HEAD_TAIL * 2:
            fh.seek(-HEAD_TAIL, 2)
            digest.update(fh.read(HEAD_TAIL))
    return "quick:" + digest.hexdigest()


def file_fingerprint(path: Path, hash_policy: str = "full") -> dict:
    stat = path.stat()
    info = sniff_file(path)
    if hash_policy == "none":
        hash_value = None
        policy = "none"
    elif hash_policy == "quick" or stat.st_size > QUICK_HASH_LIMIT:
        hash_value = quick_sha256(path)
        policy = "quick"
    else:
        hash_value = sha256_file(path)
        policy = "full"
    info.update(size=stat.st_size, sha256=hash_value, hash_policy=policy)
    return info


def _key_files(root: Path, survey: dict) -> list[Path]:
    picked: list[Path] = []

    def add(rel: str) -> None:
        path = root / rel
        if path.is_file() and path not in picked:
            picked.append(path)

    for rel in survey["executables"]:
        add(rel)
    for rel in survey["data_files"]:
        add(rel)
    for item in survey["largest"]:
        add(item["path"])
    return picked[:80]


def directory_fingerprint(root: Path, hash_policy: str = "full") -> dict:
    survey = survey_directory(root)
    hashes = []
    if hash_policy != "none":
        for path in _key_files(root, survey):
            try:
                stat = path.stat()
            except OSError:
                continue
            if hash_policy == "quick" or stat.st_size > QUICK_HASH_LIMIT:
                value = quick_sha256(path)
                policy = "quick"
            else:
                value = sha256_file(path)
                policy = "full"
            hashes.append({
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "size": stat.st_size,
                "sha256": value,
                "hash_policy": policy,
            })
    survey["key_file_hashes"] = hashes
    survey["hash_policy"] = hash_policy
    survey["key_files_hashed"] = len(hashes)
    return survey


def fingerprint(path: Path, hash_policy: str = "full") -> dict:
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_dir():
        return directory_fingerprint(path, hash_policy)
    return file_fingerprint(path, hash_policy)


def record_game(factory, path: str | Path, name: str | None = None,
                hash_policy: str = "full") -> dict:
    target = Path(path).resolve()
    fp = fingerprint(target, hash_policy)
    game_id = db.new_id("game_")
    kind = "directory" if target.is_dir() else "file"
    display = name or target.name
    with factory.connect() as conn:
        conn.execute(
            "INSERT INTO games(id, name, root_path, kind, fingerprint, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (game_id, display, str(target), kind, db.dump_json(fp), db.now()),
        )
        db.event(conn, None, "game.intake", f"登记游戏 {display} -> {target}")
    return {
        "id": game_id,
        "name": display,
        "path": str(target),
        "kind": kind,
        "fingerprint": fp,
    }


def format_summary(record: dict) -> str:
    fp = record["fingerprint"]
    lines = [f"游戏编号：{record['id']}", f"名称：{record['name']}", f"路径：{record['path']}",
             f"类型：{record['kind']}"]
    if record["kind"] == "file":
        lines += [
            f"识别格式：{fp.get('format')}",
            f"架构：{fp.get('arch') or '未识别'}",
            f"大小：{fp.get('size')} B",
            f"SHA256（{fp.get('hash_policy')}）：{fp.get('sha256')}",
        ]
    else:
        lines += [
            f"文件数：{fp.get('file_count')}{'（已截断）' if fp.get('truncated') else ''}",
            f"总大小：{fp.get('total_size')} B",
            f"已计算哈希的关键文件：{fp.get('key_files_hashed')}",
        ]
        for signal in fp.get("signals", []):
            lines.append(f"线索（{signal['confidence']}）：{signal['label']} ← {', '.join(signal['evidence'])}")
        if not fp.get("signals"):
            lines.append("线索：未命中内置文件名模式，需按内容继续识别")
    lines.append(fp.get("note", "指纹与格式判断不构成版本确认。"))
    return "\n".join(lines)


__all__ = [
    "DATA_EXTS", "EXEC_EXTS", "sha256_file", "quick_sha256", "fingerprint",
    "record_game", "format_summary", "file_fingerprint", "directory_fingerprint",
]
