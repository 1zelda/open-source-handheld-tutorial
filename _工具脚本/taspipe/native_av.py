# -*- coding: utf-8 -*-
"""BizHawk 原生逐帧同步音视频导出。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from . import statejump, watchdog
from .schema import SchemaError

FFMPEG_SHA256 = "8436760af8f81c95eff92d854a7684e6d3cedb872888420359fc45c8eb2664ac"
FFMPEG_VERSION = "ffmpeg version 4.4.1"
AV_AUDIO_TOLERANCE_SECONDS = 0.001


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _run(command, timeout=60, text=True):
    return subprocess.run(command, capture_output=True, timeout=timeout,
                          text=text, encoding="utf-8" if text else None,
                          errors="replace" if text else None)


def validate_ffmpeg(path):
    path = Path(path)
    if not path.is_file():
        raise SchemaError(f"FFmpeg 不存在: {path}")
    digest = sha256(path)
    if digest != FFMPEG_SHA256:
        raise SchemaError(f"FFmpeg SHA256 不匹配: {digest}")
    result = _run([str(path), "-version"], timeout=20)
    first_line = (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else ""
    if result.returncode != 0 or FFMPEG_VERSION not in first_line:
        raise SchemaError(f"FFmpeg 版本不符合 BizHawk 要求: {first_line!r}")
    return {"path": str(path), "sha256": digest, "version": first_line}


def _lua_string(value):
    return json.dumps(str(value), ensure_ascii=True)


def _controls(tokens):
    if not tokens:
        return "{}"
    names = tokens.split("+")
    return "{" + ", ".join(f"[{_lua_string(name)}]=true" for name in names) + "}"


def render_capture_lua(macro, platform, extra, patches, work, speed=100, joypad_port=1):
    if type(extra) is not int or extra < 0:
        raise SchemaError("extra 须为非负整数")
    canonical = statejump.parse_macro(macro, platform) if macro and macro != "-" else "-"
    macro_frames = 0 if canonical == "-" else len(canonical.split(","))
    total = macro_frames + extra
    if total < 1:
        raise SchemaError("原生导出至少一帧")
    if type(speed) is not int or speed < 1:
        raise SchemaError("speed 须为正整数")
    if type(joypad_port) is not int or not 0 <= joypad_port <= 4:
        raise SchemaError("joypad_port 须为 0..4")
    work_arg = statejump._path_arg(str(work))
    controls = []
    if macro_frames:
        controls.extend(_controls(token) for token in canonical.split(","))
    controls.extend(["{}"] * extra)
    patch_lines = []
    for patch in patches or []:
        addr = statejump._addr(patch["addr"], platform)
        value = statejump._byte(patch["value"])
        domain = statejump._domain_arg(patch["domain"])
        patch_lines.append(f"memory.write_u8({addr}, {value}, {_lua_string(domain.replace('%20', ' '))})")
    if not patch_lines:
        patch_lines = ["-- no one-shot patches"]
    return f'''local dir = {_lua_string(work_arg)}
local hb = io.open(dir .. "/heartbeat.txt", "w")
local logf = io.open(dir .. "/capture.log", "w")
if not hb or not logf then error("native A/V work files unavailable") end
client.speedmode({speed})
client.pause()
local function log(s)
    logf:write(s .. "\\n")
    logf:flush()
end
local use_joypad_port = false
for name in pairs(joypad.get() or {{}}) do
    if string.find(name, "^P%d+ ") then use_joypad_port = true; break end
end
local function set_controls(inputs)
    if use_joypad_port then joypad.set(inputs, {joypad_port}) else joypad.set(inputs) end
end
{os.linesep.join(patch_lines)}
local inputs = {{{', '.join(controls)}}}
for i = 1, #inputs do
    set_controls(inputs[i])
    client.unpause()
    emu.frameadvance()
    client.pause()
    hb:seek("set", 0)
    hb:write(string.format("%08d native_av\\n", i))
    hb:flush()
    log(string.format("frame %d", i))
end
set_controls({{}})
hb:close()
logf:close()
client.exit()
'''


def build_command(bizhawk, work, output, state, rom, total):
    if type(total) is not int or total < 1:
        raise SchemaError("dump-length 须为正整数")
    return [
        str(Path(bizhawk) / "EmuHawk.exe"), "--chromeless",
        "--dump-type=ffmpeg", f"--dump-name={statejump._path_arg(str(output))}",
        f"--dump-length={total}", "--dump-close", "--audiosync=true",
        f"--load-state={statejump._path_arg(str(state))}",
        f"--lua={statejump._path_arg(str(Path(work) / 'capture.lua'))}",
        statejump._path_arg(str(rom)),
    ]


def _volume(stderr):
    peaks = re.findall(r"max_volume:\s*([-0-9.]+)\s*dB", stderr)
    means = re.findall(r"mean_volume:\s*([-0-9.]+)\s*dB", stderr)
    return {
        "max_db": float(peaks[-1]) if peaks else None,
        "mean_db": float(means[-1]) if means else None,
    }


def _av_timing(video, audio, expected_frames, fps):
    expected_samples = round(expected_frames / fps * 44100)
    tolerance_samples = round(AV_AUDIO_TOLERANCE_SECONDS * 44100)
    try:
        video_start = int(video.get("start_pts")) if video else None
        audio_start = int(audio.get("start_pts")) if audio else None
        audio_samples = int(audio.get("nb_frames")) if audio else None
    except (TypeError, ValueError):
        video_start = audio_start = audio_samples = None
    return {
        "expected_audio_samples": expected_samples,
        "audio_samples": audio_samples,
        "sample_delta": None if audio_samples is None else audio_samples - expected_samples,
        "tolerance_samples": tolerance_samples,
        "video_start_pts": video_start,
        "audio_start_pts": audio_start,
        "checks": {
            "video_start_zero": video_start == 0,
            "audio_start_zero": audio_start == 0,
            "audio_sample_span": audio_samples is not None and abs(audio_samples - expected_samples) <= tolerance_samples,
        },
    }


def inspect_output(path, expected_frames, fps, ffmpeg, ffprobe, expected_resolution=None):
    if type(expected_frames) is not int or expected_frames < 1:
        raise SchemaError("expected_frames 须为正整数")
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise SchemaError("fps 须为正数")
    path = Path(path)
    result = {"path": str(path), "exists": path.is_file(), "checks": {}}
    if not path.is_file():
        result["checks"]["file_nonempty"] = False
        result["status"] = "fail"
        return result
    result["bytes"] = path.stat().st_size
    result["sha256"] = sha256(path)
    result["checks"]["file_nonempty"] = result["bytes"] > 0
    probe = _run([str(ffprobe), "-v", "error", "-show_entries",
                  "stream=codec_type,codec_name,width,height,start_pts,nb_frames,sample_rate,channels:format=duration",
                  "-of", "json", str(path)], timeout=60)
    try:
        document = json.loads(probe.stdout or "{}")
    except json.JSONDecodeError:
        document = {}
    streams = document.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = (document.get("format") or {}).get("duration")
    result["streams"] = streams
    result["duration"] = float(duration) if duration is not None else None
    result["checks"]["ffprobe_ok"] = probe.returncode == 0
    result["checks"]["video_stream"] = video is not None
    result["checks"]["video_frames"] = bool(video and str(video.get("nb_frames")) == str(expected_frames))
    result["checks"]["audio_stream"] = audio is not None
    result["checks"]["audio_format"] = bool(
        audio and str(audio.get("sample_rate")) == "44100" and int(audio.get("channels") or 0) == 2)
    timing = _av_timing(video, audio, expected_frames, fps)
    result["timing"] = timing
    result["checks"].update(timing["checks"])
    if expected_resolution is not None:
        result["checks"]["resolution"] = bool(
            video and int(video.get("width") or 0) == expected_resolution[0]
            and int(video.get("height") or 0) == expected_resolution[1])
    result["checks"]["duration"] = bool(
        result["duration"] is not None and abs(result["duration"] - expected_frames / fps) <= 0.05)
    volume = _run([str(ffmpeg), "-v", "info", "-i", str(path), "-map", "0:a:0",
                   "-af", "volumedetect", "-f", "null", "-"], timeout=60)
    result["audio"] = _volume(volume.stderr)
    result["checks"]["audio_non_silent"] = bool(
        volume.returncode == 0 and result["audio"]["max_db"] is not None
        and result["audio"]["max_db"] > -91.0)
    result["status"] = "pass" if all(result["checks"].values()) else "fail"
    return result


def compare_to_png(video_path, frames_dir, expected_frames, ffmpeg, ffprobe):
    import numpy as np
    from PIL import Image

    video_path, frames_dir = Path(video_path), Path(frames_dir)
    if type(expected_frames) is not int or expected_frames < 1:
        raise SchemaError("expected_frames 须为正整数")
    probe = _run([str(ffprobe), "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height,nb_frames", "-of", "json", str(video_path)])
    if probe.returncode != 0:
        raise RuntimeError(f"ffprobe 读取视频失败: {probe.stderr!r}")
    try:
        stream = json.loads(probe.stdout or "{}")["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        probed_frames = int(stream["nb_frames"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as e:
        raise RuntimeError(f"ffprobe 视频元数据不完整: {e}") from e
    if probed_frames != expected_frames:
        raise SchemaError(f"视频帧数不符: ffprobe={probed_frames}, expected={expected_frames}")
    decoded = _run([str(ffmpeg), "-v", "error", "-i", str(video_path), "-map", "0:v:0",
                    "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], timeout=120, text=False)
    if decoded.returncode != 0:
        raise RuntimeError(f"ffmpeg 解码视频失败 rc={decoded.returncode}: {decoded.stderr!r}")
    frame_bytes = width * height * 3
    if len(decoded.stdout) != expected_frames * frame_bytes:
        raise RuntimeError(
            f"解码像素长度不符: bytes={len(decoded.stdout)}, expected={expected_frames * frame_bytes}")
    video = np.frombuffer(decoded.stdout, dtype=np.uint8).reshape(expected_frames, height, width, 3)
    frames = []
    for index in range(expected_frames):
        path = frames_dir / f"f{index:04d}.png"
        with Image.open(path) as image:
            pixels = np.asarray(image.convert("RGB"))
        if pixels.shape != (height, width, 3):
            raise SchemaError(f"PNG 尺寸不符: {path} {pixels.shape}")
        frames.append(pixels)
    exact = [bool(np.array_equal(video[i], frames[i])) for i in range(expected_frames)]
    return {
        "expected_frames": expected_frames,
        "video_frames": len(video),
        "exact_frames": sum(exact),
        "exact": len(video) == expected_frames and all(exact),
        "frame_results": exact,
    }


def capture(slot, rom, state, output, macro=None, extra=0, patches=None,
            platform="GBA", fps=59.7275, ffmpeg="ffmpeg", ffprobe="ffprobe",
            expected_resolution=None, hard_timeout=90):
    ffmpeg_info = validate_ffmpeg(ffmpeg)
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"拒绝覆盖既有输出: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="native_av_", dir=slot.work))
    rom_copy = work / ("input" + Path(rom).suffix)
    state_copy = work / "input.state"
    temp_output = work / "capture.avi"
    shutil.copyfile(rom, rom_copy)
    shutil.copyfile(state, state_copy)
    lua = render_capture_lua(macro, platform, extra, patches, work)
    (work / "capture.lua").write_text(lua, encoding="utf-8")
    total = (0 if not macro or macro == "-" else len(statejump.parse_macro(macro, platform).split(","))) + extra
    command = build_command(slot.path, work, temp_output, state_copy, rom_copy, total)
    target = slot.path / "dll" / "ffmpeg.exe"
    shutil.copyfile(ffmpeg, target)
    cfg_path = slot.path / "config.ini"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    cfg.update(FFmpegFormat="AVI Lossless FFV1", VideoWriterAudioSync=True,
               SoundEnabled=True, SoundEnabledNormal=True, StartPaused=True,
               ScreenshotCaptureOsd=False, AviCaptureOsd=False)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    started = time.monotonic()
    with statejump.installation_lock(slot.path), (work / "emulator.log").open("wb") as fh:
        proc = subprocess.Popen(command, cwd=slot.path, stdout=fh, stderr=subprocess.STDOUT)
        watch = watchdog.watch_process(proc, str(work), poll=0.25, stall_timeout=20,
                                       dismiss_grace=8, hard_timeout=hard_timeout,
                                       auto_dismiss=True)
    verification = inspect_output(temp_output, total, fps, ffmpeg, ffprobe, expected_resolution)
    clean_exit = watch["termination"] == "exited" and watch["returncode"] == 0
    status = "pass" if clean_exit and verification["status"] == "pass" else "fail"
    report = {
        "status": status,
        "command": command,
        "work": str(work),
        "ffmpeg": ffmpeg_info,
        "watch": watch,
        "wall_seconds": round(time.monotonic() - started, 3),
        "verification": verification,
    }
    if status == "pass":
        shutil.copyfile(temp_output, output)
        report["output"] = str(output)
        report["output_sha256"] = sha256(output)
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if status != "pass":
        raise RuntimeError(f"原生 A/V 导出未通过: {work / 'report.json'}")
    return report
