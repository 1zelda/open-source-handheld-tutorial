"""运行证据：在受控条件下真的执行已构建产物，采集可复核的检查点。

这里只认机器观测到的进程结果：
  * 产物必须来自本次 spec/目标上一次成功的 build，且运行前后哈希一致；
  * 退出码、超时、stdout/stderr 全文与检查点时间线一起写入会话记录；
  * 没有任何检查点的计划会被拒绝——跑起来不等于玩到了。

不把它当“整游戏可玩”或“真机验收”：记录里固定 not_run / release_allowed=false。
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from uuid import uuid4

from ..research import ResearchError, run_lock, write_json
from . import cache
from .spec import SpecError

MAX_TIMEOUT = 300
DEFAULT_OUTPUT_LIMIT = 4 * 1024 * 1024
MIN_OUTPUT_LIMIT = 1024
MAX_CHECKPOINTS = 64
MAX_CHECKPOINT_NAME = 64
NAME_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,%d}$" % MAX_CHECKPOINT_NAME)
PLAN_KEYS = {"schema", "id", "timeout", "checkpoints", "checkpoint_prefix", "args", "env",
             "program", "kind", "copy", "output_limit", "require_exit", "ordered"}


class SessionError(ValueError):
    pass


def load_plan(path: Path) -> dict:
    import json

    path = Path(path).resolve()
    if not path.is_file():
        raise SessionError(f"运行计划不存在：{path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionError(f"运行计划不是合法 JSON：{exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != 1:
        raise SessionError("运行计划必须是 schema 1 的对象")
    unknown = sorted(set(raw) - PLAN_KEYS)
    if unknown:
        raise SessionError(f"运行计划有未知字段：{unknown}")
    plan_id = str(raw.get("id", ""))
    if not NAME_RE.match(plan_id):
        raise SessionError("运行计划需要合法的 id")
    timeout = raw.get("timeout", 60)
    if not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT:
        raise SessionError(f"timeout 必须是 1..{MAX_TIMEOUT} 的整数")
    checkpoints = raw.get("checkpoints")
    if not isinstance(checkpoints, list) or not checkpoints:
        raise SessionError("运行计划至少需要一个检查点；没有观测目标就不允许运行")
    if len(checkpoints) > MAX_CHECKPOINTS:
        raise SessionError(f"检查点最多 {MAX_CHECKPOINTS} 个")
    names = []
    for item in checkpoints:
        name = str(item)
        if not NAME_RE.match(name):
            raise SessionError(f"检查点名不合法：{name!r}")
        if name in names:
            raise SessionError(f"检查点重复：{name}")
        names.append(name)
    prefix = raw.get("checkpoint_prefix", "PF_CHECKPOINT ")
    if not isinstance(prefix, str) or not prefix:
        raise SessionError("checkpoint_prefix 必须是非空字符串")
    args = raw.get("args", [])
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise SessionError("args 必须是字符串列表")
    env = raw.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                            for k, v in env.items()):
        raise SessionError("env 必须是字符串到字符串的映射")
    program = raw.get("program")
    if program is not None and not isinstance(program, str):
        raise SessionError("program 必须是字符串")
    kind = raw.get("kind", "host")
    if kind not in ("host", "device"):
        raise SessionError("kind 只能是 host 或 device")
    copies = raw.get("copy", [])
    if not isinstance(copies, list):
        raise SessionError("copy 必须是列表")
    seen_dst = set()
    clean_copies = []
    for entry in copies:
        if not isinstance(entry, dict) or not entry.get("src") or not entry.get("dst"):
            raise SessionError("copy 条目需要 src 和 dst")
        if "${run}" in str(entry["src"]):
            raise SessionError("copy.src 不能引用 ${run}：复制发生在运行目录创建之前")
        dst = str(entry["dst"]).replace("\\", "/")
        parts = [p for p in dst.split("/") if p not in ("", ".")]
        if not parts or dst.startswith("/") or ".." in parts or re.match(r"^[A-Za-z]:", dst):
            raise SessionError(f"copy.dst 必须是运行目录内的相对路径：{dst}")
        if dst in seen_dst:
            raise SessionError(f"copy.dst 重复：{dst}")
        seen_dst.add(dst)
        clean_copies.append({"src": str(entry["src"]), "dst": "/".join(parts)})
    output_limit = raw.get("output_limit", DEFAULT_OUTPUT_LIMIT)
    if not isinstance(output_limit, int) or output_limit < MIN_OUTPUT_LIMIT:
        raise SessionError(f"output_limit 至少 {MIN_OUTPUT_LIMIT} 字节")
    require_exit = raw.get("require_exit", 0)
    if not isinstance(require_exit, int):
        raise SessionError("require_exit 必须是整数")
    ordered = raw.get("ordered", True)
    if not isinstance(ordered, bool):
        raise SessionError("ordered 必须是布尔值")

    plan = {"id": plan_id, "timeout": timeout, "checkpoints": names,
            "checkpoint_prefix": prefix, "args": args, "env": env,
            "program": program, "kind": kind, "copy": clean_copies,
            "output_limit": output_limit, "require_exit": require_exit,
            "ordered": ordered}
    return {"plan": plan, "path": str(path), "sha256": cache.stamp(path)["sha256"]}


def _expand(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("${" + key + "}", value)
    return text


class SessionRunner:
    def __init__(self, spec, target_name: str, work_root: Path, plan_path: Path,
                 dry_run: bool = False):
        self.spec = spec
        self.target_name = target_name
        self.work_root = (Path(work_root) / spec.id).resolve()
        self.dry_run = dry_run
        self.loaded = load_plan(plan_path)
        self.plan = self.loaded["plan"]
        self.state_path = self.work_root / "state.json"

    # ---------------------------------------------------------------- 前置
    def _state(self) -> dict:
        import json

        if not self.state_path.is_file():
            raise SessionError("还没有构建记录；先执行 port build")
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SessionError(f"状态文件损坏：{exc}") from exc
        if not isinstance(state, dict):
            raise SessionError("状态文件格式不对")
        return state

    def _target(self) -> dict:
        try:
            return self.spec.target(self.target_name)
        except SpecError as exc:
            raise SessionError(str(exc)) from exc

    def _inputs(self, state: dict) -> dict:
        target = state.get("targets", {}).get(self.target_name)
        if not target:
            raise SessionError(f"还没有构建过目标 {self.target_name}；先执行 port build")
        stages = target.get("stages", {})
        for stage in ("build", "verify"):
            entry = stages.get(stage, {})
            if entry.get("status") != "pass":
                raise SessionError(f"上一次 {stage} 没有通过；先重新构建")
        build = stages["build"]
        identity = build.get("detail", {}).get("artifact_identity")
        artifact = build.get("detail", {}).get("artifact")
        if not identity or not artifact:
            raise SessionError("构建记录缺少产物身份")
        if not cache.unchanged([identity]):
            raise SessionError("产物在构建之后发生了变化；先重新构建再运行")
        artifact_path = Path(artifact).resolve()
        if not artifact_path.is_file():
            raise SessionError(f"产物不存在：{artifact_path}")
        if not artifact_path.is_relative_to(self.work_root):
            raise SessionError("产物不在本任务的工作目录内，拒绝执行")
        data = (stages.get("fetch", {}).get("paths") or {}).get("data")
        data_path = Path(data).resolve() if data and Path(data).is_dir() else None
        return {"artifact": artifact_path, "identity": identity, "data": data_path}

    def _copy_sources(self, artifacts: dict) -> list[dict]:
        values = {"artifact": str(artifacts["artifact"]),
                  "data": str(artifacts["data"] or ""),
                  "spec": str((self.spec.path.parent if self.spec.path else Path.cwd()).resolve()),
                  "run": ""}
        allowed = [self.work_root, self.spec.path.parent if self.spec.path else Path.cwd()]
        resolved = []
        for entry in self.plan["copy"]:
            if "${data}" in entry["src"] and not values["data"]:
                raise SessionError("计划引用了 ${data}，但本任务没有数据目录")
            text = _expand(entry["src"], values)
            if "${" in text:
                raise SessionError(f"copy.src 有未展开的变量：{entry['src']}")
            source = Path(text)
            if not source.is_absolute():
                source = (self.spec.path.parent if self.spec.path else Path.cwd()) / source
            source = source.resolve()
            if not source.exists():
                raise SessionError(f"copy.src 不存在：{source}")
            if not any(source.is_relative_to(root.resolve()) for root in allowed) \
                    and source != artifacts["artifact"]:
                raise SessionError(f"copy.src 不在 spec/工作目录内：{source}")
            resolved.append({"src": source, "dst": entry["dst"]})
        return resolved

    # ---------------------------------------------------------------- 执行
    def run(self) -> dict:
        if self.dry_run:
            return self._run()
        if not self.state_path.is_file():
            raise SessionError("还没有构建记录；先执行 port build")
        self.work_root.mkdir(parents=True, exist_ok=True)
        try:
            with run_lock(self.work_root):
                return self._run()
        except ResearchError as exc:
            raise SessionError(str(exc)) from exc
        except OSError as exc:
            raise SessionError(str(exc)) from exc

    def _run(self) -> dict:
        if self.plan["kind"] == "device":
            raise SessionError("本机没有登记的设备执行器；device 运行需要真机链路（P3-B 未实现）")
        state = self._state()
        self._target()
        artifacts = self._inputs(state)
        copies = self._copy_sources(artifacts)
        run_id = "run_" + uuid4().hex
        record = {
            "schema": 1,
            "id": run_id,
            "spec": {"path": str(Path(self.spec.path).resolve()) if self.spec.path else None,
                     "sha256": cache.digest(self.spec.raw)},
            "target": self.target_name,
            "plan": {"path": self.loaded["path"], "sha256": self.loaded["sha256"],
                     **self.plan},
            "artifact": artifacts["identity"],
            "started_at": _now(),
            "grader": "process-checkpoints",
            "whole_game_behavior": "not_run",
            "device_test": "not_run",
            "release_allowed": False,
        }
        if self.dry_run:
            record["status"] = "planned"
            record["command"] = [self.plan["program"] or str(artifacts["artifact"])] + \
                [_expand(a, self._values(artifacts, Path("."))) for a in self.plan["args"]]
            record["copies"] = [{"src": str(c["src"]), "dst": c["dst"]} for c in copies]
            return {**record, "report": _report(record)}
        session_dir = self.work_root / self.target_name / "runtime" / run_id
        run_dir = session_dir / "run"
        logs = session_dir / "logs"
        run_dir.mkdir(parents=True, exist_ok=True)
        logs.mkdir(parents=True, exist_ok=True)
        for entry in copies:
            target = (run_dir / entry["dst"]).resolve()
            if not target.is_relative_to(run_dir.resolve()):
                raise SessionError(f"copy.dst 越界：{entry['dst']}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry["src"].is_dir():
                shutil.copytree(entry["src"], target, dirs_exist_ok=True)
            else:
                shutil.copy2(entry["src"], target)

        values = self._values(artifacts, run_dir)
        program = self.plan["program"] or str(artifacts["artifact"])
        program = _expand(program, values)
        command = [program] + [_expand(a, values) for a in self.plan["args"]]
        env = dict(os.environ)
        env.update({k: _expand(v, values) for k, v in self.plan["env"].items()})
        out_path = logs / "stdout.log"
        err_path = logs / "stderr.log"
        for path in (out_path, err_path):
            path.write_bytes(b"")

        started = time.time()
        sink = _CheckpointSink(self.plan["checkpoints"], self.plan["checkpoint_prefix"],
                               self.plan["ordered"], started)
        with open(out_path, "ab") as out, open(err_path, "ab") as err:
            proc = subprocess.Popen(
                command, cwd=str(run_dir), env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=(os.name != "nt"),
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0))
            readers = [
                _Reader(proc.stdout, out, self.plan["output_limit"], sink, "stdout"),
                _Reader(proc.stderr, err, self.plan["output_limit"], sink, "stderr"),
            ]
            for reader in readers:
                reader.start()
            timed_out = False
            try:
                code = proc.wait(timeout=self.plan["timeout"])
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_tree(proc)
                try:
                    code = proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    code = -9
            for reader in readers:
                reader.join(timeout=15)
        seconds = round(time.time() - started, 3)
        try:
            after = cache.stamp(artifacts["artifact"])
        except (OSError, ValueError):
            after = None
        record.update({
            "exit": code,
            "timed_out": timed_out,
            "seconds": seconds,
            "command": command,
            "cwd": str(run_dir),
            "stdout": _file_record(out_path),
            "stderr": _file_record(err_path),
            "truncated": [r.label for r in readers if r.truncated],
            "checkpoints": sink.entries,
            "unexpected_markers": sink.unexpected,
            "missing": sink.missing(),
            "out_of_order": sink.out_of_order(),
            "artifact_unchanged": after == artifacts["identity"],
            "ended_at": _now(),
        })
        problems = []
        if timed_out:
            problems.append(f"超时 {self.plan['timeout']}s")
        if code != self.plan["require_exit"]:
            problems.append(f"退出码 {code}（要求 {self.plan['require_exit']}）")
        if sink.missing():
            problems.append("缺少检查点：" + ", ".join(sink.missing()))
        if sink.out_of_order():
            problems.append("检查点顺序不符：" + ", ".join(sink.out_of_order()))
        if after != artifacts["identity"]:
            problems.append("运行期间产物被改写")
        record["status"] = "fail" if problems else "pass"
        record["reason"] = "；".join(problems)
        record["record"] = str(session_dir / "session.json")
        write_json(Path(record["record"]), record)
        state["targets"][self.target_name]["runtime"] = {
            "status": record["status"], "record": record["record"],
            "plan": self.loaded["path"], "plan_sha256": self.loaded["sha256"],
            "artifact_sha256": artifacts["identity"]["sha256"], "at": record["ended_at"],
        }
        write_json(self.state_path, state)
        return {**record, "report": _report(record)}

    def _values(self, artifacts: dict, run_dir: Path) -> dict[str, str]:
        return {"artifact": str(artifacts["artifact"]),
                "data": str(artifacts["data"] or ""),
                "spec": str((self.spec.path.parent if self.spec.path else Path.cwd()).resolve()),
                "run": str(run_dir)}


class _CheckpointSink:
    def __init__(self, required: list[str], prefix: str, ordered: bool, started: float):
        self.required = required
        self.prefix = prefix
        self.ordered = ordered
        self.started = started
        self.lock = threading.Lock()
        self.entries: list[dict] = []
        self.seen: list[str] = []
        self.unexpected = 0

    def feed(self, line: str, stream: str) -> None:
        if not line.startswith(self.prefix):
            return
        name = line[len(self.prefix):].strip()
        with self.lock:
            if name not in self.required:
                self.unexpected += 1
                return
            if name in self.seen:
                return
            self.seen.append(name)
            self.entries.append({"name": name, "stream": stream,
                                 "seconds": round(time.time() - self.started, 3),
                                 "line": line[:200]})

    def missing(self) -> list[str]:
        with self.lock:
            return [name for name in self.required if name not in self.seen]

    def out_of_order(self) -> list[str]:
        with self.lock:
            if not self.ordered:
                return []
            expected = [n for n in self.required if n in self.seen]
            return [] if self.seen == expected else \
                [f"应先 {','.join(expected)}，实际 {','.join(self.seen)}"]


class _Reader(threading.Thread):
    def __init__(self, pipe, fh, limit: int, sink: _CheckpointSink, label: str):
        super().__init__(daemon=True)
        self.pipe = pipe
        self._read = getattr(pipe, "read1", pipe.read)
        self.fh = fh
        self.limit = limit
        self.sink = sink
        self.label = label
        self.truncated = False
        self._buffer = b""

    def run(self) -> None:
        written = 0
        try:
            while True:
                chunk = self._read(8192)
                if not chunk:
                    break
                if written < self.limit:
                    part = chunk[:self.limit - written]
                    self.fh.write(part)
                    self.fh.flush()
                    written += len(part)
                    if len(part) < len(chunk):
                        self.truncated = True
                    self._buffer += chunk
                else:
                    self.truncated = True
                    self._buffer += chunk
                if len(self._buffer) > (1 << 20):
                    self._buffer = self._buffer[-65536:]
                self._drain()
            self._drain(final=True)
        finally:
            try:
                self.pipe.close()
            except OSError:
                pass

    def _drain(self, final: bool = False) -> None:
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            self.sink.feed(line.decode("utf-8", "replace").rstrip("\r"), self.label)
        if final and self._buffer:
            self.sink.feed(self._buffer.decode("utf-8", "replace").rstrip("\r"), self.label)
            self._buffer = b""


def _kill_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True, timeout=30)
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:
        proc.kill()


def _file_record(path: Path) -> dict:
    return {"path": str(path), "size": path.stat().st_size,
            "sha256": cache.stamp(path)["sha256"]}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _report(record: dict) -> str:
    lines = [f"# 运行会话 {record['id']}", "",
             f"- 目标：{record['target']} / 计划：{record['plan']['id']}",
             f"- 产物：`{record['artifact']['path']}` ({record['artifact']['sha256'][:16]}…)",
             f"- 判定器：process-checkpoints；整游戏行为：未测试；真机：未测试；发布资格：禁止", ""]
    if record["status"] == "planned":
        lines += [f"- 命令：`{record['command']}`"]
        for entry in record.get("copies", []):
            lines.append(f"- 复制：{entry['src']} → {entry['dst']}")
        lines.append("")
        return "\n".join(lines)
    lines += ["| 项 | 值 |", "|---|---|",
              f"| 状态 | **{record['status']}** |",
              f"| 退出码 | {record['exit']}（要求 {record['plan']['require_exit']}） |",
              f"| 用时 | {record['seconds']}s / 上限 {record['plan']['timeout']}s |",
              f"| 超时 | {'是' if record['timed_out'] else '否'} |",
              f"| 检查点 | {len(record['checkpoints'])}/{len(record['plan']['checkpoints'])} |",
              f"| 产物未变 | {'是' if record['artifact_unchanged'] else '否'} |"]
    if record.get("reason"):
        lines.append(f"| 原因 | {record['reason']} |")
    if record["checkpoints"]:
        lines += ["", "| 检查点 | 流 | 到达(秒) |", "|---|---|---:|"]
        for item in record["checkpoints"]:
            lines.append(f"| {item['name']} | {item['stream']} | {item['seconds']} |")
    lines += ["", f"- stdout：`{record['stdout']['path']}` ({record['stdout']['size']} B)",
              f"- stderr：`{record['stderr']['path']}` ({record['stderr']['size']} B)", ""]
    return "\n".join(lines)
