# -*- coding: utf-8 -*-
"""Fail-closed TAS production: convert, replay, verify evidence, regress, publish."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import traceback
import uuid
import zipfile

from . import control
from . import movie_converters
from .retro_platforms import PLATFORM_SPECS
from .schema import SchemaError, asset, sha1_resource, sha256_file


def sample_frames(total: int, interval: int = 600) -> list[int]:
    if type(total) is not int or total < 1 or type(interval) is not int or interval < 1:
        raise SchemaError("采样总帧数与间隔须为正整数")
    frames = [1]
    frames.extend(range(1 + interval, total, interval))
    if frames[-1] != total:
        frames.append(total)
    return frames


def build_spec(movie: Path, rom: str, bizhawk: Path, core: str, system: str,
               platform: str, frames: int, game: str, interval: int = 600,
               capture: bool = True, fps: float | None = None,
               arms: list[dict] | None = None, speed: str = "unthrottled",
               seed_ram: dict | None = None, sync_samples=None,
               ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> dict:
    if not game.strip():
        raise SchemaError("生产任务必须写明游戏名，不能绕过选题闸门")
    if speed not in ("realtime", "unthrottled"):
        raise SchemaError("生产速度只能是 realtime 或 unthrottled")
    steps, previous = [], 0
    if seed_ram is not None:
        seed = dict(seed_ram)
        seed["id"] = "seed_initial_sram"
        seed["op"] = "seed_ram"
        if core != "BSNES" or system != "SNES":
            raise SchemaError("当前只允许向 SNES BSNES 冷启动电影注入初始 SRAM")
        source = Path(seed["path"])
        if not source.is_file() or source.stat().st_size != seed["bytes"]:
            raise SchemaError("初始 SRAM 文件缺失或长度不符")
        if sha256_file(source) != seed["sha256"]:
            raise SchemaError("初始 SRAM SHA-256 不符")
        seed["path"] = str(source.resolve())
        steps.append(seed)
    for index, frame in enumerate(sample_frames(frames, interval), 1):
        steps.append({"id": f"replay_{index:03d}", "op": "replay", "frames": frame - previous})
        checkpoint = {"id": f"checkpoint_{index:03d}", "op": "checkpoint", "name": f"cp_{frame:05d}"}
        if system == "SNES" and core in ("BSNES", "BSNESv115+"):
            # BSNES 默认 System Bus 为 16MB；逐字节导出 115 次会主导全片耗时。
            checkpoint.update(ram_domain="System Bus", ram_addr=0x7E0000, ram_bytes=0x20000)
        steps.append(checkpoint)
        previous = frame
    verify = {"length": {"frames": frames, "tolerance": 1e-12,
                         "source": "生产任务要求完整消费电影输入，帧数必须精确相等"},
              "tail_stasis": {"enabled": True, "window_frames": 12000,
                              "stride": 60, "min_frozen_frames": 1200,
                              "source": "生产入口独立检测末段画面冻结"}}
    if arms:
        if len(arms) < 2:
            raise SchemaError("同步对照至少需要两条臂")
        entries = []
        for index, raw in enumerate(arms):
            entry = dict(raw)
            entry.setdefault("system", system)
            if index == 0:
                entry["movie"] = {"path": str(movie.resolve()), "sha256": sha256_file(movie)}
                if entry.get("core", core) != core:
                    raise SchemaError("同步参照臂核心必须与主任务一致")
            else:
                if not entry.get("movie"):
                    raise SchemaError("同步候选臂必须指定 movie")
                if (entry.get("core", core) == core
                        and Path(entry.get("bizhawk") or bizhawk).resolve() == Path(bizhawk).resolve()):
                    raise SchemaError("同步候选臂必须更换核心或 BizHawk 版本，不能自己和自己对照")
            entries.append(entry)
        if sync_samples == "all":
            samples = [*sample_frames(frames, interval)[:-1], "end"]
        elif sync_samples is None:
            samples = [1, max(1, frames // 2), "end"]
        elif isinstance(sync_samples, list):
            samples = sync_samples
        else:
            raise SchemaError("同步采样只能是 all、帧号列表或默认值")
        verify["arms"] = {"entries": entries, "samples": samples,
                          "compare": ["ram", "png"], "source": "生产入口强制多臂同输入对照"}
    return {
        "version": 1, "id": "produce_" + re.sub(r"[^A-Za-z0-9_-]+", "_", movie.stem),
        "mode": "session", "purpose": "control", "game": game, "platform": platform,
        "rom": {"path": str(Path(rom).resolve()), "sha1": sha1_resource(rom).lower()},
        "profile": {"bizhawk": str(bizhawk.resolve()), "core": core, "system": system},
        "start": {"kind": "movie", "path": str(movie.resolve()), "sha256": sha256_file(movie)},
        "steps": steps,
        "record": {"video": bool(capture), "audio": False, "speed": speed,
                   "fps": float(fps or PLATFORM_SPECS[platform]["fps"]),
                   "ffmpeg": ffmpeg, "ffprobe": ffprobe},
        "verify": verify,
    }


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value):
    control.write_json(path, value)


def _movie_identity(movie: Path):
    header, frames, length = control._bk2_info(movie)
    system, core = header.get("Platform"), header.get("Core")
    if not system or not core:
        raise SchemaError("BK2 缺少 Platform/Core 身份")
    platform = next((name for name, spec in PLATFORM_SPECS.items() if spec["system"] == system), None)
    if platform is None:
        raise SchemaError(f"控制运行器未建模电影系统 {system}")
    return header, frames, length, platform, system, core


def _core_state_identity(core_state: Path | None) -> dict | None:
    if core_state is None:
        return None
    path = Path(core_state).resolve()
    return {"path": str(path), "sha256": sha256_file(path)}


def _read_rom_bytes(rom: str) -> bytes:
    path = Path(rom)
    raw = path.read_bytes()
    if raw[:4] != b"PK\x03\x04":
        return raw
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [name for name in archive.namelist()
                 if Path(name).suffix.lower() in (".sfc", ".smc", ".swc", ".fig")]
        if len(names) != 1:
            raise SchemaError(f"ROM ZIP 必须恰有一个 SNES ROM 条目: {rom}")
        return archive.read(names[0])


def _prepare_bsnes_seed(parsed: dict, original_rom: str, out: Path) -> tuple[str, dict]:
    out.mkdir(parents=True, exist_ok=True)
    rom = _read_rom_bytes(original_rom)
    if len(rom) < 0x8000:
        raise SchemaError("SNES ROM 太短，不能校验卡带头")
    map_mode = rom[0x7FD5] & 0x30
    if map_mode == 0x20:
        map_offset = 0x7FC0
    elif map_mode == 0x30:
        map_offset = 0xFFC0
    else:
        raise SchemaError(f"不支持的 SNES 卡带映射模式: 0x{map_mode:02x}")
    if map_offset + 0x20 > len(rom):
        raise SchemaError("SNES ROM 卡带头超出文件范围")
    sram = parsed.get("savestate_data")
    if not isinstance(sram, bytes) or not sram:
        raise SchemaError("BSNES FROM_RESET SMV 缺少内置初始 SRAM")
    if len(sram) & (len(sram) - 1) or not 1024 <= len(sram) <= 0x20000:
        raise SchemaError("SMV 初始 SRAM 必须是 1KB 至 128KB 的二次幂长度")
    declared_code = rom[map_offset + 0x18]
    declared = (1024 << declared_code) if declared_code else 0
    changed = []
    effective_rom = str(Path(original_rom).resolve())
    if declared != len(sram):
        patched = bytearray(rom)
        patched[map_offset + 0x18] = (len(sram).bit_length() - 1) - 10
        changed.append(map_offset + 0x18)
        patched[map_offset + 0x1C:map_offset + 0x20] = b"\0" * 4
        checksum = sum(patched) & 0xFFFF
        complement = checksum ^ 0xFFFF
        struct.pack_into("<HH", patched, map_offset + 0x1C, checksum, complement)
        changed.extend(range(map_offset + 0x1C, map_offset + 0x20))
        rom_path = (out / "rom_sram_patched.sfc").resolve()
        rom_path.write_bytes(patched)
        effective_rom = str(rom_path)
        rom = bytes(patched)
    seed_path = (out / "initial_sram.bin").resolve()
    seed_path.write_bytes(sram)
    digest = hashlib.sha256(sram).hexdigest()
    evidence = {
        "seed_ram": {"id": "seed_initial_sram", "op": "seed_ram", "path": str(seed_path),
                     "sha256": digest, "domain": "CARTRAM", "addr": 0, "bytes": len(sram)},
        "effective_rom": str(Path(effective_rom).resolve()),
        "effective_rom_sha1": sha1_resource(effective_rom).lower(),
        "effective_rom_sha256": sha256_file(effective_rom),
        "source_rom": str(Path(original_rom).resolve()),
        "source_rom_sha1": sha1_resource(original_rom).lower(),
        "declared_sram_bytes": declared,
        "initial_sram_bytes": len(sram),
        "initial_sram_sha256": digest,
        "patched_header_offsets": [f"0x{offset:x}" for offset in changed],
    }
    return effective_rom, evidence


def _prepare_movie(source: Path, out: Path, rom: str, bizhawk: Path, core: str,
                   core_state: Path | None) -> tuple[Path, dict]:
    target = out / "movie.bk2"
    report_path = out / "conversion.json"
    source_hash = sha256_file(source)
    core_state_id = _core_state_identity(core_state)
    effective_rom = rom
    seed_evidence = None
    if source.suffix.lower() != ".bk2" and core == "BSNES":
        parsed = movie_converters.parse_smv(source)
        if parsed.get("platform") != "SNES" or not parsed.get("from_reset"):
            raise SchemaError("自动 SRAM 注入只支持 SNES BSNES FROM_RESET SMV")
        effective_rom, seed_evidence = _prepare_bsnes_seed(parsed, rom, out)
        seed = seed_evidence["seed_ram"]
        if not Path(seed["path"]).is_file() or sha256_file(seed["path"]) != seed["sha256"]:
            raise SchemaError("生成的初始 SRAM 未通过复核")
    if source.suffix.lower() == ".bk2":
        if target.exists():
            if sha256_file(target) != source_hash:
                raise SchemaError("既有 movie.bk2 与源电影不一致，拒绝覆盖")
        else:
            shutil.copyfile(source, target)
        return target, {"status": "reused", "source": str(source.resolve()),
                        "source_sha256": source_hash, "out": str(target.resolve()),
                        "sha256": sha256_file(target), "effective_rom": str(Path(effective_rom).resolve()),
                        "seed_ram": None, "report": None}
    if target.exists():
        previous = _read_json(report_path) if report_path.is_file() else {}
        if (previous.get("source_sha256") == source_hash and previous.get("sha256") == sha256_file(target)
                and previous.get("core") == core and previous.get("core_state") == core_state_id
                and previous.get("effective_rom_sha1") == sha1_resource(effective_rom).lower()
                and previous.get("seed_evidence") == seed_evidence
                and previous.get("status") in ("converted", "reused")):
            return target, {**previous, "status": "reused"}
        raise SchemaError("既有转换件缺少匹配的来源/核心/ROM/SRAM/哈希证据，拒绝覆盖")
    result = movie_converters.convert_movie_file(
        source, target, rom_sha1=sha1_resource(effective_rom), rom_path=effective_rom, bizhawk=bizhawk,
        work=out / "convert_work", game_name=out.name, core_state_path=core_state, core=core)
    result.update(source=str(source.resolve()), source_sha256=source_hash,
                  sha256=sha256_file(target), rom=str(Path(effective_rom).resolve()),
                  effective_rom=str(Path(effective_rom).resolve()),
                  effective_rom_sha1=sha1_resource(effective_rom).lower(),
                  effective_rom_sha256=sha256_file(effective_rom),
                  seed_evidence=seed_evidence, core_state=core_state_id,
                  report=str(report_path.resolve()))
    _write_json(report_path, result)
    return target, result


def frame_streaks(hashes: list[str]) -> list[dict]:
    if not hashes:
        return []
    streaks = []
    start, previous = 1, hashes[0]
    for number, digest in enumerate(hashes[1:], 2):
        if digest != previous:
            streaks.append({"start": start, "end": number - 1,
                            "frames": number - start, "md5": previous})
            start, previous = number, digest
    streaks.append({"start": start, "end": len(hashes),
                    "frames": len(hashes) - start + 1, "md5": previous})
    return streaks


def inspect_video(report: dict, frames: int, ffmpeg: str = "ffmpeg",
                  ffprobe: str = "ffprobe", max_static_frames: int = 1200) -> dict:
    declared = (report.get("runtime") or {}).get("video") or {}
    declared_path = declared.get("path") if isinstance(declared, dict) else None
    if declared_path:
        videos = [Path(row["uri"]) for row in report.get("artifacts") or []
                  if Path(row.get("uri", "")).resolve() == Path(declared_path).resolve()]
    else:
        videos = [Path(row["uri"]) for row in report.get("artifacts") or []
                  if Path(row.get("uri", "")).name == "video.mp4"]
    errors = []
    evidence = {"video_count": len(videos), "max_static_frames": max_static_frames}
    if len(videos) != 1 or not videos[0].is_file():
        errors.append("生产视频缺失或不是唯一 video.mp4")
        return {"pass": False, "errors": errors, "evidence": evidence}
    video = videos[0]
    evidence["path"] = str(video.resolve())
    try:
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=nb_frames", "-of", "json", str(video)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=True, timeout=120)
        stream = json.loads(probe.stdout)["streams"][0]
        evidence["probe"] = stream
        if stream.get("nb_frames") != str(frames):
            errors.append(f"视频容器帧数 {stream.get('nb_frames')} != {frames}")
        decoded = subprocess.run(
            [ffmpeg, "-nostdin", "-v", "error", "-i", str(video), "-map", "0:v:0",
             "-f", "framemd5", "-"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True, timeout=600)
        hashes = [line.rsplit(",", 1)[-1].strip() for line in decoded.stdout.splitlines()
                  if line and not line.startswith("#")]
        if len(hashes) != frames:
            errors.append(f"视频实际解码帧数 {len(hashes)} != {frames}")
        streaks = frame_streaks(hashes)
        longest = max(streaks, key=lambda item: item["frames"]) if streaks else None
        final = streaks[-1] if streaks else None
        evidence.update(decoded_frames=len(hashes), unique_frame_md5=len(set(hashes)),
                        final_streak=final, longest_streak=longest,
                        top_streaks=sorted(streaks, key=lambda item: item["frames"],
                                           reverse=True)[:10], sha256=sha256_file(video))
        if final and final["frames"] > max_static_frames:
            errors.append(f"视频末段连续静止 {final['frames']} 帧，超过 {max_static_frames}")
        if longest and longest["frames"] > max_static_frames:
            errors.append(f"视频最长连续静止 {longest['frames']} 帧，超过 {max_static_frames}")
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError) as exc:
        errors.append(f"视频逐帧复核失败: {type(exc).__name__}: {exc}")
    return {"pass": not errors, "errors": errors, "evidence": evidence}


def verify_evidence(report: dict) -> list[str]:
    errors = []
    for row in report.get("artifacts") or []:
        if not isinstance(row, dict):
            errors.append("产物清单含非对象记录")
            continue
        try:
            path = Path(row["uri"])
            actual = sha256_file(path)
            if actual != row.get("sha256"):
                errors.append(f"产物 SHA-256 不一致: {path}")
            if path.stat().st_size != row.get("byte_size") or path.stat().st_size == 0:
                errors.append(f"产物大小不符或为空: {path}")
        except (KeyError, OSError, TypeError) as exc:
            errors.append(f"产物不可复核: {row!r}: {exc}")
    return errors


def inspect_result(report: dict, frames: int, sample_count: int,
                   acceptance: dict | None = None, interval: int = 600) -> dict:
    errors = []
    verification = report.get("verification") or {}
    runtime = report.get("runtime") or {}
    completion = verification.get("completion")
    if report.get("status") != "done" or runtime.get("status") != "done":
        errors.append("control/runtime 状态不是 done")
    if verification.get("execution") != "pass" or runtime.get("execution") != "pass":
        errors.append("执行验收不是 pass")
    if verification.get("core_identity") != "pass" or runtime.get("core_identity") != "pass":
        errors.append("实际核心身份验收不是 pass")
    if verification.get("sync") != "pass":
        errors.append("独立同步验收不是 pass")
    if verification.get("visual") != "pass":
        errors.append("视觉验收不是 pass")
    if runtime.get("frames_advanced") != frames:
        errors.append(f"实到帧数 {runtime.get('frames_advanced')} != {frames}")
    movie = runtime.get("movie") or {}
    if movie.get("expected_inputs") != frames or movie.get("consumed_inputs") != frames:
        errors.append("电影输入没有完整消费")
    events = runtime.get("events") or []
    seed_starts = [event for event in events if event.get("op") == "seed_ram" and event.get("kind") == "step_started"]
    seed_done = [event for event in events if event.get("op") == "seed_ram" and event.get("kind") == "step_done"]
    if len(seed_starts) != len(seed_done):
        errors.append("初始 SRAM 注入缺少完整执行事件")
    for event in seed_done:
        data = event.get("seed_ram") or {}
        if (not data.get("sha256_verified_by_runner") or type(data.get("bytes")) is not int
                or data.get("bytes") < 1 or event.get("frame") != 0 or event.get("consumed_inputs") != 0):
            errors.append("初始 SRAM 注入没有零帧全量回读证据")
    picture = report.get("picture") or {}
    if not picture.get("measured") or picture.get("dead_tail") is not False:
        errors.append("画面测量未完成或发现死尾")
    checkpoints = runtime.get("checkpoints") or {}
    if len(checkpoints) != sample_count:
        errors.append(f"检查点数 {len(checkpoints)} != {sample_count}")
    actual_frames = sorted(row.get("frame") for row in checkpoints.values() if type(row.get("frame")) is int)
    expected_frames = sample_frames(frames, interval)
    if actual_frames != expected_frames:
        errors.append("检查点帧号与生产采样表不一致")
    for name, row in checkpoints.items():
        screenshot = row.get("screenshot")
        if not screenshot or not Path(screenshot).is_file() or Path(screenshot).stat().st_size == 0:
            errors.append(f"检查点 {name} 缺少非空截图")
    if not any(f <= 600 for f in actual_frames) or not any(
            frames * 0.4 <= f <= frames * 0.6 for f in actual_frames) or not any(
            f >= frames - 600 for f in actual_frames):
        errors.append("开头、中段或结尾检查点缺失")
    if acceptance:
        reviews = acceptance.get("reviews")
        if not isinstance(reviews, list):
            errors.append("交付证词缺少 reviews 开头/中段/结尾三帧复核清单")
        else:
            zones = set()
            final_reviewed = False
            for review in reviews:
                name = review.get("checkpoint") if isinstance(review, dict) else None
                row = checkpoints.get(name) or {}
                screenshot = row.get("screenshot")
                digest = sha256_file(screenshot) if screenshot and Path(screenshot).is_file() else None
                frame = row.get("frame")
                if digest != review.get("sha256"):
                    errors.append(f"交付证词截图 SHA-256 不符: {name}")
                if not str(review.get("seen") or "").strip():
                    errors.append(f"交付证词缺少可见内容: {name}")
                if type(frame) is int and frame <= 600:
                    zones.add("opening")
                if type(frame) is int and frames * 0.4 <= frame <= frames * 0.6:
                    zones.add("middle")
                if type(frame) is int and frame >= frames - 600:
                    zones.add("ending")
                    final_reviewed = frame == frames
            if zones != {"opening", "middle", "ending"}:
                errors.append("交付证词必须覆盖开头、中段、结尾三个画面区域")
            if not final_reviewed:
                errors.append("交付证词必须锁定真实末帧")
        completion = "pass" if not any("交付证词" in error for error in errors) else "fail"
    if completion != "pass":
        errors.append("通关验收不是 pass")
    errors.extend(verify_evidence(report))
    return {"pass": not errors, "errors": errors, "frames": frames,
            "checkpoints": len(checkpoints), "visual": verification.get("visual"),
            "sync": verification.get("sync"), "completion": completion}


def review_template(out: Path) -> dict:
    report = _read_json(out / "control" / "control.json")
    frames = report.get("runtime", {}).get("frames_advanced")
    checkpoints = report.get("runtime", {}).get("checkpoints") or {}
    if type(frames) is not int or frames < 1:
        raise SchemaError("现有回放没有可生成复核模板的帧数")
    rows = sorted(((row.get("frame"), name, row) for name, row in checkpoints.items()
                   if type(row.get("frame")) is int), key=lambda item: item[0])
    if not rows:
        raise SchemaError("现有回放没有检查点截图")
    middle = min(rows, key=lambda item: abs(item[0] - frames / 2))
    chosen = [rows[0], middle, rows[-1]]
    reviews = []
    for frame, name, row in chosen:
        screenshot = row.get("screenshot")
        if not screenshot or not Path(screenshot).is_file():
            raise SchemaError(f"检查点 {name} 缺少截图")
        reviews.append({"checkpoint": name, "frame": frame,
                        "sha256": sha256_file(screenshot), "seen": ""})
    return {"reviews": reviews}


def build_contact_sheets(report: dict, out: Path) -> list[dict]:
    checkpoints = (report.get("runtime") or {}).get("checkpoints") or {}
    rows = sorted(((row.get("frame"), name, row) for name, row in checkpoints.items()
                   if type(row.get("frame")) is int), key=lambda item: item[0])
    if not rows:
        return []
    from PIL import Image, ImageDraw

    def load(row):
        path = Path(row["screenshot"])
        with Image.open(path) as source:
            return source.convert("RGB")

    def save(canvas, name):
        target = out / name
        temporary = out / ("." + name + ".tmp")
        canvas.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, target)
        return asset(str(target))

    middle = min(rows, key=lambda item: abs(item[0] - rows[-1][0] / 2))
    chosen = [rows[0], middle, rows[-1]]
    review = Image.new("RGB", (3 * 512, 474), (18, 18, 18))
    draw = ImageDraw.Draw(review)
    for index, (frame, name, row) in enumerate(chosen):
        image = load(row)
        image.thumbnail((512, 448), Image.Resampling.LANCZOS)
        x = index * 512 + (512 - image.width) // 2
        review.paste(image, (x, 0))
        draw.text((index * 512 + 8, 454), f"frame={frame} {name}", fill=(240, 240, 240))
    artifacts = [save(review, "review_contact_sheet.png")]

    columns, cell_width, cell_height, thumb_width, thumb_height = 5, 272, 252, 256, 224
    grid_rows = (len(rows) + columns - 1) // columns
    overview = Image.new("RGB", (columns * cell_width, grid_rows * cell_height), (18, 18, 18))
    draw = ImageDraw.Draw(overview)
    for index, (frame, name, row) in enumerate(rows):
        image = load(row)
        image.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        x = (index % columns) * cell_width + (cell_width - image.width) // 2
        y = (index // columns) * cell_height
        overview.paste(image, (x, y))
        draw.text((x, y + 228), f"frame={frame}", fill=(240, 240, 240))
    artifacts.append(save(overview, "checkpoints_contact_sheet.png"))
    return artifacts


def run_regressions(out: Path) -> dict:
    directory = out / "regression"
    directory.mkdir(parents=True, exist_ok=True)
    tools = Path(__file__).resolve().parents[1]
    commands = [
        ("converter", [sys.executable, "-m", "taspipe.selftest"], "SELFTEST OK"),
        ("control", [sys.executable, "-m", "taspipe.control_selftest"], "OK"),
        ("cross_platform", [sys.executable, "-m", "taspipe.cross_platform_selftest_gates"],
         "CROSS_PLATFORM_SELFTEST OK"),
    ]
    results = []
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for name, command, marker in commands:
        log = directory / f"{name}.log"
        with log.open("wb") as stream:
            completed = subprocess.run(command, cwd=tools, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=900)
        text = log.read_text(encoding="utf-8", errors="replace")
        results.append({"name": name, "returncode": completed.returncode,
                        "marker_found": marker in text, "log": str(log.resolve()),
                        "sha256": sha256_file(log)})
    return {"pass": all(row["returncode"] == 0 and row["marker_found"] for row in results),
            "tests": results}


def request_identity(source: Path, rom: str, out: Path, bizhawk: Path, core: str,
                     game: str, interval: int, capture: bool, fps: float | None,
                     core_state: Path | None, arms: list[dict] | None,
                     speed: str = "unthrottled", sync_samples=None,
                     ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
                     acceptance: dict | None = None, allow: tuple[str, ...] = ()) -> str:
    payload = {"source": str(Path(source).resolve()), "source_sha256": sha256_file(source),
               "rom": str(Path(rom).resolve()), "rom_sha1": sha1_resource(rom).lower(),
               "out": str(Path(out).resolve()), "bizhawk": str(Path(bizhawk).resolve()),
               "core": core, "game": game, "interval": interval, "capture": bool(capture),
               "fps": float(fps) if fps is not None else None, "speed": speed,
               "core_state": _core_state_identity(core_state), "arms": arms,
               "sync_samples": sync_samples, "ffmpeg": ffmpeg, "ffprobe": ffprobe,
               "acceptance": acceptance, "allow": list(allow)}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _quarantine_deliverable(out: Path) -> str | None:
    target = out / "deliverable.mp4"
    if not target.is_file():
        return None
    quarantined = out / f"deliverable.rejected.{uuid.uuid4().hex}.mp4"
    os.replace(target, quarantined)
    return str(quarantined.resolve())


def produce(source: Path, rom: str, out: Path, bizhawk: Path, core: str,
            game: str, interval: int = 600, timeout: float = 1800,
            work_root: Path | None = None, core_state: Path | None = None,
            acceptance: dict | None = None, capture: bool = True,
            fps: float | None = None, executor=None, arms: list[dict] | None = None,
            speed: str = "unthrottled", allow: tuple[str, ...] = (),
            sync_samples=None, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> dict:
    if speed not in ("realtime", "unthrottled"):
        raise SchemaError("生产速度只能是 realtime 或 unthrottled")
    allow = tuple(allow)
    source, out, bizhawk = source.resolve(), out.resolve(), bizhawk.resolve()
    request_sha256 = request_identity(source, rom, out, bizhawk, core, game, interval,
                                      capture, fps, core_state, arms, speed, sync_samples,
                                      ffmpeg, ffprobe, acceptance, allow)
    if out.exists() and any(out.iterdir()):
        manifest_path = out / "production_manifest.json"
        if manifest_path.is_file():
            previous = _read_json(manifest_path)
            if previous.get("status") == "accepted" and previous.get("request_sha256") != request_sha256:
                raise SchemaError("输出目录已有不同生产任务的验收清单，拒绝覆盖；请使用新的输出目录")
        if not (out / "control" / "control.json").is_file():
            raise SchemaError("输出目录非空且没有可续跑的 control/control.json，拒绝覆盖")
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "production_manifest.json"
    base = {"source": str(source), "rom": str(Path(rom).resolve()), "out": str(out),
            "bizhawk": str(bizhawk), "core": core, "speed": speed, "allow": list(allow),
            "ffmpeg": ffmpeg, "ffprobe": ffprobe, "request_sha256": request_sha256}
    try:
        movie, conversion = _prepare_movie(source, out, rom, bizhawk, core, core_state)
        header, frames, length, platform, system, actual_core = _movie_identity(movie)
        if actual_core != core:
            raise SchemaError(f"电影核心 {actual_core} != 请求核心 {core}")
        effective_rom = conversion.get("effective_rom", rom)
        spec = build_spec(movie, effective_rom, bizhawk, core, system, platform, frames,
                          game, interval, capture, fps, arms, speed,
                          (conversion.get("seed_evidence") or {}).get("seed_ram"), sync_samples,
                          ffmpeg, ffprobe)
        spec_path = out / "production_spec.json"
        _write_json(spec_path, spec)
        result = control.run(spec, out, out / "control", work_root=work_root or out / "work",
                             timeout=timeout, executor=executor, allow=allow)
        result.setdefault("artifacts", []).append(asset(str(movie)))
        if conversion.get("report"):
            result.setdefault("artifacts", []).append(asset(conversion["report"]))
        seed_evidence = conversion.get("seed_evidence")
        if seed_evidence:
            result.setdefault("artifacts", []).extend([
                asset(seed_evidence["seed_ram"]["path"]), asset(seed_evidence["effective_rom"])])
        result.setdefault("artifacts", []).extend(build_contact_sheets(result, out))
        inspection = inspect_result(result, frames, len(sample_frames(frames, interval)),
                                    acceptance, interval)
        video_inspection = inspect_video(result, frames, ffmpeg, ffprobe) if capture else {
            "pass": True, "errors": [], "evidence": {"skipped": "capture disabled"}}
        inspection["errors"].extend(video_inspection["errors"])
        inspection["pass"] = not inspection["errors"]
        inspection["video"] = video_inspection
        regression = run_regressions(out)
        accepted = inspection["pass"] and regression["pass"]
        quarantined = None if accepted else _quarantine_deliverable(out)
        manifest = {**base, "status": "accepted" if accepted else "rejected",
                    "frames": frames, "interval": interval,
                    "sample_count": len(sample_frames(frames, interval)),
                    "movie_sha256": sha256_file(movie), "conversion": conversion,
                    "conversion_report": asset(conversion["report"]) if conversion.get("report") else None,
                    "spec": asset(str(spec_path)), "control": result, "inspection": inspection,
                    "video_inspection": video_inspection,
                    "acceptance": acceptance, "interval": interval, "arms": arms,
                    "sync_samples": sync_samples, "regression": regression,
                    "deliverable": None, "quarantined_deliverable": quarantined}
        if accepted:
            videos = [Path(row["uri"]) for row in result.get("artifacts", [])
                      if Path(row.get("uri", "")).name == "video.mp4"]
            if capture and len(videos) != 1:
                raise SchemaError("通过闸门但未找到唯一 video.mp4，拒绝发布")
            if videos:
                target = out / "deliverable.mp4"
                temporary = out / ".deliverable.mp4.tmp"
                shutil.copyfile(videos[0], temporary)
                os.replace(temporary, target)
                manifest["deliverable"] = asset(str(target))
        _write_json(manifest_path, manifest)
        return manifest
    except Exception as exc:
        quarantined = _quarantine_deliverable(out)
        manifest = {**base, "status": "rejected", "reason": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc(), "deliverable": None,
                    "quarantined_deliverable": quarantined}
        _write_json(manifest_path, manifest)
        return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--movie", default="")
    parser.add_argument("--rom", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--bizhawk", default="")
    parser.add_argument("--core", default="")
    parser.add_argument("--game", default="")
    parser.add_argument("--make-review-template", action="store_true")
    parser.add_argument("--interval", type=int, default=600)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--work-root", default="")
    parser.add_argument("--core-state", default="")
    parser.add_argument("--acceptance", default="")
    parser.add_argument("--arms", default="")
    parser.add_argument("--sync-samples", default="", help="all 或逗号分隔帧号；默认开头/中段/结尾")
    parser.add_argument("--fps", type=float, default=None)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--speed", choices=("realtime", "unthrottled"), default="unthrottled")
    parser.add_argument("--allow", action="append", default=[],
                        help="仅放行 control 已有的软 blocker；执行/同步/视觉/证据硬闸门不可放行")
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    if args.make_review_template:
        template = review_template(out)
        _write_json(out / "review_template.json", template)
        print(json.dumps(template, ensure_ascii=False, indent=2))
        return 0
    if not args.movie or not args.rom or not args.bizhawk or not args.game:
        parser.error("生产模式必须提供 --movie --rom --bizhawk --game")
    source = Path(args.movie).resolve()
    core = args.core
    if not core and source.suffix.lower() == ".bk2":
        core = control._bk2_info(source)[0].get("Core", "")
    if not core:
        raise SchemaError("非 BK2 生产必须显式指定 --core")
    acceptance = _read_json(Path(args.acceptance).resolve()) if args.acceptance else None
    arms = _read_json(Path(args.arms).resolve()) if args.arms else None
    sync_samples = None
    if args.sync_samples:
        sync_samples = "all" if args.sync_samples == "all" else [
            int(value) for value in args.sync_samples.split(",") if value.strip()]
    result = produce(source, args.rom, out, Path(args.bizhawk), core, args.game,
                     interval=args.interval, timeout=args.timeout,
                     work_root=Path(args.work_root).resolve() if args.work_root else None,
                     core_state=Path(args.core_state).resolve() if args.core_state else None,
                     acceptance=acceptance, capture=not args.no_video, fps=args.fps, arms=arms,
                     speed=args.speed, allow=tuple(args.allow), sync_samples=sync_samples,
                     ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "accepted" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
