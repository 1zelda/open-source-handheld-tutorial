"""Isolated BizHawk batch runner; control.py owns normalization and the CLI."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
import zipfile

from . import statejump, watchdog
from .schema import (adopt_state_sync_settings, sha256_file, split_rom_spec,
                     state_sync_settings, verify_core_identity)


class RuntimeBlocked(RuntimeError):
    pass


def _json(path: Path, value):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False),
                   encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _wire(value) -> str:
    # Data-only length-prefixed protocol: never load/loadstring/dofile user input.
    if value is None:
        return "z"
    if type(value) is bool:
        return "t" if value else "f"
    if isinstance(value, str):
        text = value.encode("utf-8").hex()
        return f"s{len(text)}:{text}"
    if type(value) in (int, float):
        if not math.isfinite(value) or abs(value) > 2**53:
            raise ValueError("wire number outside exact Lua numeric range")
        text = str(value)
        return f"n{len(text)}:{text}"
    if isinstance(value, list):
        return f"a{len(value)}:" + "".join(_wire(x) for x in value)
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return f"d{len(value)}:" + "".join(_wire(k) + _wire(v) for k, v in value.items())
    raise ValueError(f"unsupported wire value: {type(value).__name__}")


def _absolute(value, what):
    p = Path(value)
    if not p.is_absolute():
        raise RuntimeBlocked(f"{what} must be absolute: {value}")
    return p.resolve()


def _inside(path, root):
    return path == root or root in path.parents


def _copy_runtime(source: Path, dest: Path):
    # Exclude only well-known user-output directories, not a DLL/file allowlist.
    outputs = {"movies", "state", "states", "savestates", "saveram", "screenshots", "logs"}

    def ignore(directory, names):
        ignored = []
        for name in names:
            p = Path(directory) / name
            if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
                raise RuntimeBlocked(f"runtime dependency is a link/junction: {p}")
            relative = p.relative_to(source)
            protected = relative.parts[0].lower() in {"dll", "firmware", "tools", "lua", "shaders", "gamedb", "externaltools"}
            if not protected and p.is_dir() and len(relative.parts) <= 2 and name.lower() in outputs:
                ignored.append(name)
            elif not protected and len(relative.parts) <= 2 and p.suffix.lower() in {
                    ".bk2", ".tasproj", ".fm2", ".state", ".sav", ".srm", ".log", ".avi", ".mp4"}:
                ignored.append(name)
            elif p.parent == source and name.lower().startswith("config.ini.bak"):
                ignored.append(name)
        return ignored

    shutil.copytree(source, dest, ignore=ignore, copy_function=shutil.copyfile)


SPEEDS = ("realtime", "unthrottled")


def apply_speed(cfg, speed, frameskip=0):
    """回放墙钟档位。realtime 保持 BizHawk 默认 60Hz 节流；unthrottled 关掉时钟节流。

    只改墙钟，不改仿真帧序：驱动每步都断言 delta==1，出片侧还要用同帧 RAM 摘要
    证明两档逐帧等价，否则不许拿 unthrottled 的结果当验收。

    frameskip 只跳过渲染、不跳仿真帧。实测（NesHawk，7429 转换件，skip 0 与 skip 8
    各跑 1500 帧）：同帧 RAM sha256 相同，1500 张逐帧截图 sha256 逐字节相同，
    所以截图在跳渲染下不会取到旧画面。换核心须重跑这条对照才许沿用。
    """
    if speed not in SPEEDS:
        raise RuntimeBlocked(f"unknown speed tier: {speed}")
    if type(frameskip) is not int or not 0 <= frameskip <= 60:
        raise RuntimeBlocked(f"invalid frameskip: {frameskip}")
    if frameskip:
        cfg["FrameSkip"] = frameskip
    if speed == "unthrottled":
        cfg.update(Unthrottled=True, ClockThrottle=False, VSyncThrottle=False,
                   SoundEnabled=False, RunLuaDuringTurbo=True)
    return cfg


def _configure(source: Path, clone: Path, program: dict, sound=False, start_paused=True, state_sync=None):
    import tas_replay

    tas_replay.force_core(str(clone), program["system"], program["core"])
    config = clone / "config.ini"
    cfg = json.loads(config.read_text(encoding="utf-8-sig"))
    cfg.update(StartPaused=bool(start_paused), SingleInstanceMode=False, AutoLoadLastSaveSlot=False,
               RunInBackground=True, AcceptBackgroundInput=False, DontTryOtherCores=True,
               ScreenshotCaptureOsd=False, FrameSkip=0, AutoMinimizeSkipping=False,
               SkipLagFrame=False, DisableLuaScriptsOnLoad=False, SoundEnabled=bool(sound),
               UpdateAutoCheckEnabled=False, AutosaveSaveRAM=False, SuppressAskSave=True,
               CommonToolSettings={}, CustomToolSettings={})
    apply_speed(cfg, program.get("speed", "realtime"), program.get("frameskip", 0))
    for key, val in cfg.items():
        if key.startswith("Recent") and isinstance(val, dict):
            val["AutoLoad"] = False
    cfg.setdefault("Savestates", {}).update(Type=0, SaveScreenshot=True)
    cfg.setdefault("Movies", {})["MovieEndAction"] = 3  # Finish, never switch to RECORD.
    cfg.setdefault("Cheats", {}).update(DisableOnLoad=True, LoadFileByGame=False, AutoSaveOnClose=False)
    cfg["Cheats"].setdefault("Recent", {})["AutoLoad"] = False
    for binding in cfg.get("HotkeyBindings", {}).get("Bindings", []):
        binding["Bindings"] = ""

    paths = cfg.setdefault("PathEntries", {}).setdefault("Paths", [])
    base = next((p["Path"] for p in paths if p.get("System") == "Global_NULL"
                 and p.get("Type") == "Base"), ".")
    original_base = (source / base).resolve()
    resource_types = {"Firmware", "Tools", "Lua", "External Tools"}
    for i, entry in enumerate(paths):
        kind = entry.get("Type", "")
        if kind in resource_types:
            original = (original_base / entry["Path"]).resolve()
            if _inside(original, source):
                target = clone / original.relative_to(source)
            else:
                target = clone / "resources" / str(i)
                if not original.is_dir():
                    raise RuntimeBlocked(f"missing external runtime resource: {original}")
                _copy_runtime(original, target)
            entry["Path"] = str(target)
        else:
            target = clone / "io" / str(i)
            target.mkdir(parents=True, exist_ok=True)
            entry["Path"] = str(target)
    # Defaults for missing entries stay relative to this private global Base.
    global_base = next((p for p in paths if p.get("System") == "Global_NULL"
                        and p.get("Type") == "Base"), None)
    if global_base is None:
        paths.append({"System": "Global_NULL", "Type": "Base", "Path": str(clone)})
    else:
        global_base["Path"] = str(clone)
    for i, (key, value) in enumerate(cfg.get("FirmwareUserSpecifications", {}).items()):
        original = (source / value).resolve()
        if not original.is_file():
            raise RuntimeBlocked(f"missing configured firmware: {original}")
        target = clone / "custom_firmware" / (str(i) + original.suffix)
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(original, target)
        cfg["FirmwareUserSpecifications"][key] = str(target)

    sync = program.get("sync_settings") or {}
    if sync:
        # The public contract currently permits NES Controls, not arbitrary CLR types.
        if program["system"] != "NES" or program["core"] != "NesHawk":
            raise RuntimeBlocked("nonempty sync_settings currently requires NES/NesHawk Controls")
        controls = sync.get("Controls", sync)
        if not isinstance(controls, dict) or any(type(v) not in (str, bool) for v in controls.values()):
            raise RuntimeBlocked("sync_settings must contain NES Controls string/bool values")
        key = "BizHawk.Emulation.Cores.Nintendo.NES.NES"
        settings = cfg.setdefault("CoreSyncSettings", {}).setdefault(key, {})
        settings.setdefault("$type", key + "+NESSyncSettings, BizHawk.Emulation.Cores")
        settings.setdefault("Controls", {}).update(controls)
    if state_sync is not None:
        expectation = program.get("core_identity") or {}
        if state_sync["o"].get("$type") != expectation.get("sync_type"):
            raise RuntimeBlocked("state CLR sync type does not match requested core")
        key, adopted = adopt_state_sync_settings(state_sync)
        cfg.setdefault("CoreSyncSettings", {})[key] = adopted
    _json(config, cfg)


def _movie_inputs(path: Path) -> int:
    with zipfile.ZipFile(path) as z:
        if "Header.txt" not in z.namelist() or "Input Log.txt" not in z.namelist():
            raise RuntimeBlocked("materialized movie is not a BK2 with Header/Input Log")
        return sum(line.startswith(b"|") for line in z.read("Input Log.txt").splitlines())


def _read_events(path: Path):
    events, errors = [], []
    if path.exists():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("event is not an object")
                events.append(value)
            except ValueError as exc:
                errors.append(f"events.jsonl line {n}: {exc}")
    return events, errors


def _terminate(proc):
    # Popen's process handle, never an image-name kill or someone else's PID.
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _timing_summary(report):
    """把吞吐落成产物事实：setup=起模拟器之前的准备（ROM 取条目、配置隔离），process=Popen 到退出，
    boot=Popen 到第一次心跳。历史做法是拿 plan.json/result.json 的 mtime 相减，那会把准备、
    模拟器冷启、回放三段糊成一个数——11-22 SNES 三点（50/1200/2400 帧）自相矛盾就是这么来的。
    编码段（ffmpeg）不计入 process_seconds。"""
    if "setup_seconds" in report and "process_seconds" in report:
        report["wall_seconds"] = round(report["setup_seconds"] + report["process_seconds"], 3)
    advanced = report.get("frames_advanced") or 0
    process, boot = report.get("process_seconds"), report.get("boot_seconds")
    if process and advanced:
        report["frames_per_second"] = round(advanced / process, 2)
        if boot is not None and process > boot:
            report["frames_per_second_after_boot"] = round(advanced / (process - boot), 2)
    return report


def _dialog_error_message(dialogs, fallback):
    parts = []
    for item in dialogs:
        title = str(item.get("title") or "")
        texts = [str(text) for text in item.get("texts") or [] if str(text).strip()]
        parts.append(title + (": " + " / ".join(texts) if texts else ""))
    return "EmuHawk error dialog: " + " | ".join(parts or fallback)


def _verify_identity_request(request, work, token, report):
    if request.get("token") != token:
        raise RuntimeError("core identity token mismatch")
    path = Path(request["state"])
    if not path.is_absolute() or not _inside(path.resolve(), work):
        raise RuntimeError("core identity state escaped private work directory")
    if request.get("frame") != 0:
        raise RuntimeError("core identity state was not captured at frame zero")
    sync = state_sync_settings(path)
    log_text = (work / "emuhawk.log").read_text(encoding="utf-8", errors="replace")
    check = verify_core_identity(report["core_identity_expectation"], sync, log_text)
    check.update(frame=0, state=str(path), state_sha256=sha256_file(path),
                 state_sync_type=(sync or {}).get("o", {}).get("$type"))
    report["core_identity"] = check["verdict"]
    report["core_identity_evidence"] = check
    _json(work / "identity_reply.json", {"token": token, "allow": check["verdict"] == "pass",
                                         "verdict": check["verdict"], "reason": check["reason"]})
    if check["verdict"] != "pass":
        raise RuntimeBlocked("zero-frame core identity rejected: " + check["reason"])


def _wait(proc, work: Path, token: str, deadline: float, report: dict, t_launch=None):
    replied = set()
    identity_replied = False
    started_at = time.monotonic()
    last_progress = last_dialog = started_at
    startup_dialogs = []
    stamp = None
    while proc.poll() is None:
        now = time.monotonic()
        if stamp is None and now - started_at <= 30:
            count = watchdog.dismiss_bizhawk_dialog(
                proc.pid, titles=watchdog.STARTUP_DIALOG_TITLES, records=startup_dialogs)
            if count:
                report["startup_dialogs"] = startup_dialogs
        if now >= deadline:
            # 先把"是截止掐的"写进报告再抛：调用方拿实到帧数做长度核对时，
            # 少了这个标记就会把截断说成"电影短了"（11-22 实测 4776 差 134 帧就这么误判过）。
            report["deadline_exceeded"] = True
            raise TimeoutError("runtime deadline exceeded")
        hb = work / "heartbeat.txt"
        if hb.exists():
            current = hb.stat().st_mtime_ns
            if current != stamp:
                stamp, last_progress = current, now
                if "boot_seconds" not in report and t_launch is not None:
                    # 第一次心跳＝电影加载完、客户端开始推进；不记就分不出"冷启慢"还是"回放慢"
                    report["boot_seconds"] = round(now - t_launch, 3)
        identity_request = work / "identity_request.json"
        if identity_request.is_file() and not identity_replied:
            _verify_identity_request(json.loads(identity_request.read_text(encoding="utf-8")),
                                     work, token, report)
            identity_replied = True
        request = work / f"gate_request_{len(replied) + 1}.json"
        if request.exists():
            gate = json.loads(request.read_text(encoding="utf-8"))
            seq = gate["seq"]
            if seq not in replied:
                if gate.get("token") != token:
                    raise RuntimeError("state admission token mismatch")
                a, b = Path(gate["original"]), Path(gate["roundtrip"])
                if not all(p.is_absolute() and _inside(p.resolve(), work) for p in (a, b)):
                    raise RuntimeError("state admission path escaped private work directory")
                check = statejump.compare_state_core(str(a), str(b))
                allowed = check["match"] is True and check["core_identity_match"] is True
                check.update(seq=seq, original=str(a), roundtrip=str(b), admitted=allowed)
                report.setdefault("state_checks", []).append(check)
                _json(work / f"gate_reply_{seq}.json", {"seq": seq, "token": token, "allow": allowed})
                replied.add(seq)
        if now - last_progress > 5 and now - last_dialog > 3:
            windows = watchdog.windows_of_pid(proc.pid)
            dangerous = [title for _, title, _, visible in windows if visible and
                         any(x in title.lower() for x in ("error", "exception", "错误"))]
            if dangerous:
                evidence = [item for item in watchdog.stall_windows(proc.pid)
                            if any(x in item.get("title", "").lower() for x in ("error", "exception", "错误"))]
                report["error_dialogs"] = evidence
                raise RuntimeError(_dialog_error_message(evidence, dangerous))
            count = watchdog.dismiss_bizhawk_dialog(proc.pid)
            if count:
                report.setdefault("dialogs", []).append({"count": count, "titles": [w[1] for w in windows]})
            last_dialog = now
        if now - last_progress > 60:
            raise TimeoutError("EmuHawk stalled: no heartbeat for 60 seconds")
        try:
            proc.wait(timeout=min(0.05, max(0.001, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            continue
    report["returncode"] = proc.returncode
    if proc.returncode != 0:
        raise RuntimeError(f"EmuHawk exited with code {proc.returncode}")


def _encode(program: dict, work: Path, deadline: float, count: int):
    video = work / "artifacts" / "video.mp4"
    # Run the existing encoder in a bounded child; its own subprocess has no timeout.
    script = ("import sys; sys.path.insert(0,sys.argv[1]); "
              "from tas_replay import encode_video; "
              "encode_video(sys.argv[2],float(sys.argv[3]),sys.argv[4],sys.argv[5])")
    cmd = [sys.executable, "-B", "-c", script, str(Path(__file__).resolve().parents[1]),
           str(work / "artifacts" / "frames"), str(program["fps"]), str(video), program["ffmpeg"]]
    # On timeout kill only the encoder we started, including its ffmpeg descendant.
    with (work / "encode.log").open("wb") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        try:
            rc = proc.wait(timeout=max(0.001, deadline - time.monotonic()))
            if rc:
                raise RuntimeError(f"encode_video failed with code {rc}; see encode.log")
        finally:
            if proc.poll() is None:
                watchdog.tree_kill(proc.pid)
                _terminate(proc)
    probe = subprocess.run([program["ffprobe"], "-v", "error", "-count_frames", "-show_entries",
                            "stream=codec_type,nb_read_frames", "-of", "json", str(video)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=max(0.001, deadline - time.monotonic()), check=True)
    data = json.loads(probe.stdout)
    _json(work / "ffprobe.json", data)
    streams = data.get("streams", [])
    vs = [s for s in streams if s.get("codec_type") == "video"]
    if len(vs) != 1 or int(vs[0].get("nb_read_frames", -1)) != count:
        raise RuntimeError("ffprobe video frame count does not equal actual advances")
    if any(s.get("codec_type") == "audio" for s in streams):
        raise RuntimeError("unexpected audio stream in PNG-only capture")
    return {"path": str(video), "frames": count, "audio": False}


def _remap(value, work: Path, out: Path):
    if isinstance(value, list):
        return [_remap(x, work, out) for x in value]
    if isinstance(value, dict):
        return {k: _remap(v, work, out) for k, v in value.items()}
    if isinstance(value, str):
        prefix = (work / "artifacts").as_posix() + "/"
        normalized = value.replace("\\", "/")
        if normalized.startswith(prefix):
            return str(out / normalized[len(prefix):])
    return value


def execute(program: dict, out_dir: str, work_root: str, timeout: float = 300) -> dict:
    report = {"status": "failed", "execution": "fail", "completion": "inconclusive",
              "reason": "runtime did not finish", "events": [], "artifacts": [],
              "frames_advanced": 0, "movie": {"expected_inputs": 0, "consumed_inputs": 0,
                                               "sync": "unverified"},
              "work_dir": str(Path(work_root).absolute()), "audio": False,
              "core_identity": "unverified", "core_identity_expectation": program.get("core_identity") or {},
              "speed": program.get("speed", "realtime"),
              "capture_rule": "one PNG after each actual advance; no initial PNG in video; load/save/shot/gate add zero frames"}
    t_begin = time.monotonic()
    work = out = lock = proc = None
    owns_lock, lock_written, lock_identity = False, False, None
    token = uuid.uuid4().hex
    errors = []
    try:
        candidate = _absolute(out_dir, "out_dir")
        if candidate.exists() and (not candidate.is_dir() or any(candidate.iterdir())):
            raise RuntimeBlocked("out_dir must be new or empty; refusing to overwrite")
        root = _absolute(work_root, "work_root")
        if not str(root).isascii():
            raise RuntimeBlocked("work_root must be an ASCII absolute path")
        source = _absolute(program["bizhawk"], "bizhawk")
        if any(_inside(a, b) for a, b in ((root, source), (source, root), (candidate, source),
                                         (source, candidate), (candidate, root), (root, candidate))):
            raise RuntimeBlocked("source, work_root and out_dir must be disjoint")
        candidate.mkdir(parents=True, exist_ok=True)
        out = candidate
        if not (source / "EmuHawk.exe").is_file():
            raise RuntimeBlocked("EmuHawk.exe not found")
        if not math.isfinite(timeout) or timeout <= 0:
            raise RuntimeBlocked("timeout must be positive and finite")
        deadline = time.monotonic() + timeout
        # 截断警告要把本次生效的 --timeout 报出来，否则调用方只拿到"到点掐断"却不知道该加多大。
        report["timeout_seconds"] = timeout
        root.mkdir(parents=True, exist_ok=True)
        lock = root / ".control_runtime.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeBlocked(f"work_root locked; old/unknown lock must be handled by owner: {lock}") from exc
        owns_lock = True
        lock_identity = os.fstat(fd)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            json.dump({"token": token, "pid": os.getpid()}, f)
        lock_written = True
        work = Path(tempfile.mkdtemp(prefix="run_", dir=root)).resolve()
        report["work_dir"] = str(work)
        artifacts = work / "artifacts"
        artifacts.mkdir()
        (artifacts / "frames").mkdir()
        if program.get("tail_probe"):
            (artifacts / "tail").mkdir()
        clone_name = source.name if source.name.isascii() else "BizHawk"
        clone = work / clone_name
        _copy_runtime(source, clone)
        state_sync = None
        if program["start"]["kind"] == "state":
            initial = artifacts / "initial.state"
            shutil.copyfile(_absolute(program["start"]["path"], "state"), initial)
            if sha256_file(initial) != program["start"]["sha256"]:
                raise RuntimeBlocked("state SHA-256 changed before runtime launch")
            state_sync = state_sync_settings(initial)
            if state_sync is not None:
                key, adopted = adopt_state_sync_settings(state_sync)
                report["state_sync_adoption"] = {
                    "source_sha256": sha256_file(initial), "key": key, "settings": adopted,
                    "adopted": True, "frame": 0}
        _configure(source, clone, program, state_sync=state_sync)
        shutil.copyfile(clone / "config.ini", work / "isolated_config.json")

        # 先切条目再解析路径：_absolute 走 Path.resolve()，会把条目里的 / 改成 \。
        rom_archive, rom_entry = split_rom_spec(program["rom"])
        rom_archive = _absolute(str(rom_archive), "rom")
        ext = Path(rom_entry).suffix if rom_entry else rom_archive.suffix
        if not re.fullmatch(r"\.[A-Za-z0-9]+", ext):
            raise RuntimeBlocked("ROM extension must be ASCII")
        local_rom = work / ("rom" + ext)
        if rom_entry is None:
            shutil.copyfile(rom_archive, local_rom)
        else:
            # 压缩包寻址：只导出那一条条目成独立文件，原包字节不动，模拟器仍吃明文件。
            with zipfile.ZipFile(rom_archive) as zf:
                try:
                    local_rom.write_bytes(zf.read(rom_entry))
                except KeyError:
                    raise RuntimeBlocked(f"ROM entry missing in archive: {rom_entry}")
        digest = statejump.sha1_file(str(local_rom))
        if digest != str(program["rom_sha1"]).upper():
            raise RuntimeBlocked("ROM SHA-1 changed before runtime launch")
        payload = copy.deepcopy(program)
        payload.update(token=token, work_dir=work.as_posix())
        payload["rom"] = local_rom.as_posix()
        start = payload["start"]
        cmd = [str(clone / "EmuHawk.exe"), "--chromeless"]
        if start["kind"] == "state":
            start["path"] = initial.as_posix()
        elif start["kind"] == "movie":
            import tas_replay
            initial = work / "movie.bk2"
            source_movie = work / "source_movie.bin"
            shutil.copyfile(_absolute(start["path"], "movie"), source_movie)
            if sha256_file(source_movie) != start["sha256"]:
                raise RuntimeBlocked("movie SHA-256 changed before runtime launch")
            tas_replay.materialize_movie(str(source_movie), str(initial))
            count = _movie_inputs(initial)
            if start.get("movie_input_lines") is not None and start["movie_input_lines"] != count:
                raise RuntimeBlocked(f"movie_input_lines {start['movie_input_lines']} 与素材里的输入行 {count} 不一致")
            declared = start.get("movie_frames")
            if declared is not None and not 0 < declared <= count:
                raise RuntimeBlocked(f"声明帧数 {declared} 落在素材输入行 1..{count} 之外")
            start.update(path=initial.as_posix(), movie_frames=count)
            report["movie"]["expected_inputs"] = count
            cmd.append("--movie=" + str(initial))
        elif start["kind"] != "boot":
            raise RuntimeBlocked("unknown start kind")
        for number, step in enumerate(payload["steps"], 1):
            if step["op"] != "seed_ram":
                continue
            local_seed = work / f"seed_ram_{number:04d}.bin"
            shutil.copyfile(_absolute(step["path"], "seed_ram"), local_seed)
            if sha256_file(local_seed) != step["sha256"]:
                raise RuntimeBlocked("seed RAM SHA-256 changed before runtime launch")
            step["path"] = local_seed.as_posix()
        # Keep only runtime data in the Lua channel, not source paths or tool configuration.
        payload = {k: payload[k] for k in ("id", "system", "core", "core_identity", "start", "steps", "completion",
                                          "capture", "frameskip", "tail_probe", "token", "work_dir")}
        (work / "program.dat").write_text(_wire(payload), encoding="ascii")
        template = Path(__file__).with_suffix(".lua").read_text(encoding="utf-8")
        lua = work / "batch.lua"
        lua.write_text(template.replace("__CONTROL_WORKDIR__", json.dumps(work.as_posix())),
                       encoding="utf-8", newline="\n")
        cmd += ["--lua=" + str(lua), str(local_rom)]
        report["command"] = cmd
        if time.monotonic() >= deadline:
            # 和 _wait 里同理：先标记"是截止掐的"，调用方才不会把 0 帧说成"电影短了"。
            report["deadline_exceeded"] = True
            raise TimeoutError("runtime setup exceeded timeout")
        t_launch = time.monotonic()
        report["setup_seconds"] = round(t_launch - t_begin, 3)
        with (work / "emuhawk.log").open("wb") as log:
            proc = subprocess.Popen(cmd, cwd=str(clone), stdout=log, stderr=subprocess.STDOUT)
            try:
                _wait(proc, work, token, deadline, report, t_launch)
            finally:
                # 截断/异常那趟也要留下时间，否则"跑得很慢"与"根本没跑"在产物里长得一样
                report["process_seconds"] = round(time.monotonic() - t_launch, 3)
                _timing_summary(report)
        result_path = work / "runtime_result.json"
        if not result_path.is_file():
            raise RuntimeError("EmuHawk exited without runtime_result.json")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("token") != token:
            raise RuntimeError("runtime result token mismatch")
        if report.get("core_identity") != "pass":
            raise RuntimeBlocked("runtime has no passing zero-frame core identity evidence")
        # completion_witness 由 control._check_latch_witness 在唯一生产入口 run() 里核对，
        # 这里只负责搬运，别在这里复制一份判定逻辑。
        for key in ("status", "execution", "completion", "reason", "frames_advanced", "movie",
                    "checkpoints", "final_frame", "completion_witness", "tail_samples"):
            if key in result:
                report[key] = result[key]
        _timing_summary(report)          # 实到帧数要等这里搬完才算得出 fps，重算一次覆盖 finally 那份
        if report["status"] != "done" or report["execution"] != "pass":
            raise RuntimeError("Lua batch failed: " + report["reason"])
        if any(not c["admitted"] for c in report.get("state_checks", [])):
            raise RuntimeError("state admission rejected")
        if report["completion"] not in ("pass", "fail", "inconclusive"):
            raise RuntimeError("invalid completion verdict")
        if not program["completion"] and report["completion"] != "inconclusive":
            raise RuntimeError("empty completion must be inconclusive")
        for name in ("final.state", "final.png"):
            if not (artifacts / name).is_file() or not (artifacts / name).stat().st_size:
                raise RuntimeError(f"missing final artifact: {name}")
        log_text = (work / "emuhawk.log").read_text(encoding="utf-8", errors="replace")
        bad = [line for line in log_text.splitlines()
               if re.search(r"(?i)(unhandled exception|NLua\.Exceptions|LuaException|^\s*error[: ])", line)]
        if bad:
            raise RuntimeError("EmuHawk logged errors: " + " | ".join(bad[-8:]))
        if program["capture"]:
            n = report["frames_advanced"]
            names = {p.name for p in (artifacts / "frames").iterdir()}
            if names != {f"f{i:04d}.png" for i in range(n)}:
                raise RuntimeError("capture sequence does not match frames_advanced")
            if n:
                report["video"] = _encode(program, work, deadline, n)
            else:
                report["video"] = {"frames": 0, "audio": False, "reason": "no advances; no video"}
    except Exception as exc:
        report.update(status="blocked" if isinstance(exc, RuntimeBlocked) else "failed",
                      execution="fail", reason=f"{type(exc).__name__}: {exc}")
        errors.append(traceback.format_exc())
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            errors.append(str(exc.stderr)[-8192:])
    finally:
        try:
            _terminate(proc)
        except Exception as exc:
            errors.append(f"process cleanup: {exc}")
            report.update(status="failed", execution="fail", reason=f"process cleanup: {exc}")
        if work is not None:
            try:
                events, event_errors = _read_events(work / "events.jsonl")
                report["events"] = events
                if events:
                    report["frames_advanced"] = max(report["frames_advanced"], max(e.get("frames_advanced", 0) for e in events))
                    report["movie"]["consumed_inputs"] = max(report["movie"].get("consumed_inputs", 0), max(e.get("consumed_inputs", 0) for e in events))
                if event_errors:
                    raise RuntimeError("; ".join(event_errors))
            except Exception as exc:
                errors.append(str(exc))
                report.update(status="failed", execution="fail", reason=str(exc))
            try:
                if out is not None:
                    for p in sorted((work / "artifacts").rglob("*")):
                        if p.is_file():
                            dest = out / p.relative_to(work / "artifacts")
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(p, dest)
                    for name in ("emuhawk.log", "events.jsonl", "heartbeat.txt", "isolated_config.json",
                                 "encode.log", "ffprobe.json", "runtime_result.json", "identity_request.json",
                                 "identity_reply.json"):
                        p = work / name
                        if p.is_file():
                            dest = out / ("lua_result.json" if name == "runtime_result.json" else name)
                            shutil.copyfile(p, dest)
                    report = _remap(report, work, out)
                    with (out / "events.jsonl").open("w", encoding="utf-8", newline="\n") as f:
                        for event in report["events"]:
                            f.write(json.dumps(event, ensure_ascii=True, allow_nan=False) + "\n")
            except Exception as exc:
                errors.append(f"artifact copy: {exc}")
                report.update(status="failed", execution="fail", reason=f"artifact copy: {exc}")
            # Only our run directory is eligible; if process termination failed, leave it intact.
            if proc is None or proc.poll() is not None:
                try:
                    if report["execution"] == "pass":
                        shutil.rmtree(work)
                    else:
                        for p in list(work.iterdir()):
                            if p.is_dir():
                                shutil.rmtree(p)
                            elif p.name not in {"emuhawk.log", "events.jsonl", "heartbeat.txt",
                                                "batch.lua", "isolated_config.json", "encode.log", "ffprobe.json",
                                                "identity_request.json", "identity_reply.json"}:
                                p.unlink()
                            elif p.stat().st_size > 2 * 1024 * 1024:
                                with p.open("rb") as f:
                                    f.seek(-2 * 1024 * 1024, os.SEEK_END)
                                    ending = f.read()
                                p.write_bytes(ending)
                        report["diagnostic_tail_limit_bytes"] = 2 * 1024 * 1024
                except Exception as exc:
                    errors.append(f"private directory cleanup: {exc}")
                    report.update(status="failed", execution="fail", reason=f"private directory cleanup: {exc}")
        if owns_lock:
            try:
                if proc is not None and proc.poll() is None:
                    raise RuntimeError("owned process still running; retaining lock")
                if not os.path.samestat(lock_identity, lock.stat()):
                    raise RuntimeError("lock ownership changed; not deleting")
                if lock_written and json.loads(lock.read_text(encoding="ascii")).get("token") != token:
                    raise RuntimeError("lock token changed; not deleting")
                lock.unlink()
            except Exception as exc:
                errors.append(f"lock cleanup: {exc}")
                report.update(status="failed", execution="fail", reason=f"lock cleanup: {exc}")
        # 截断路径的实到帧数是上面从 events.jsonl 里捞回来的，晚于 with 块里那次 finally，
        # 所以速率要在这里再算一遍：不然"跑了一半被截止掐了"的趟只剩耗时、没有 fps。
        _timing_summary(report)
        report["work_dir_retained"] = work is not None and work.exists()
        report["movie"]["sync"] = "unverified"
        if errors:
            report["diagnostics"] = errors
        if out is not None and out.is_dir():
            try:
                report["artifacts"] = [str(p.resolve()) for p in sorted(out.rglob("*")) if p.is_file() and p.stat().st_size]
                target = out / "runtime_result.json"
                if str(target) not in report["artifacts"]:
                    report["artifacts"].append(str(target))
                _json(target, report)
            except Exception as exc:
                report.update(status="failed", execution="fail", reason=f"cannot write runtime report: {exc}")
    return report
