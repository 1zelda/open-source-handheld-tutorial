# -*- coding: utf-8 -*-
"""M2/M3：后端薄封装 + 能力探针（依据 _scratch/强模型方案回复.md §4.3 / §5 M2-M3）。

原则：
  * 薄封装现有管线，不重写：NES 走 tas_replay（已验证），FBNeo 走 rig.run_capture。
  * 能力探针如实报告；未验证/未接线的能力 supported=False，不暴露给搜索。
  * 三种验收分开：回放确定性 / 帧采集 / 成片。证据不足 => inconclusive，不是通过。
  * 音频是独立准入项：NES 截图链路无音频（M5 补）；FBNeo 内录 AVI 自带音轨。

运行:
  python -m taspipe.backends probe nes
  python -m taspipe.backends probe fbneo
  python -m taspipe.backends run-nes --pub 5246 --frames 180 --out <dir>
  python -m taspipe.backends run-fbneo --out <dir> --lead 72
"""
import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

from .schema import (Verification, CheckResult, Verdict, Stage, FailureCode,
                     asset, to_dict)

HERE = Path(__file__).resolve()
SCRIPT_DIR = HERE.parents[1]                 # _工具脚本（tas_replay 所在）
RIG_DIR = Path(r"F:\tas_rig")
PROJECT_ROOT = HERE.parents[2]               # F:\开源掌机教程
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _cap(supported, evidence):
    return {"supported": bool(supported), "evidence": evidence}


STATEJUMP_REPORT = (PROJECT_ROOT / "04-游戏资源库" / "TAS输入录像库"
                    / "验证" / "t3_statejump" / "report.json")


def statejump_evidence(report_path=None):
    """T3 状态跳跃实跑验收的证据门控：report.json 全 pass 才许把
    savestate/ram_read/interactive_step 转真。无报告/未全过 => (False, 原因)。
    不凭「Lua API 存在」就标 supported——接线且实跑确定性通过才算数（项目红线）。
    report_path 可注入临时报告供自检；默认读真实验收产物。"""
    p = Path(report_path) if report_path else STATEJUMP_REPORT
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "无 验证/t3_statejump/report.json 实跑证据（未验证）"
    if not d.get("all_pass"):
        failed = [c.get("name") for c in d.get("checks", []) if not c.get("pass")]
        return False, f"实跑验收未全过: {failed}"
    return True, f"验证/t3_statejump/report.json 全 pass（{d.get('created', '')}）"


def _run_id():
    return "run_" + uuid.uuid4().hex[:12]


def _write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def _verification(vid, subject, stage, checks):
    v = Verification(vid, subject, stage, checks).validate()
    d = to_dict(v)
    d["verdict"] = v.verdict.value
    return d


def _audio_max_db(path, ffmpeg="ffmpeg"):
    """量音轨最大音量（dB）。全静音约 -91dB。用于区分'有音轨'与'录到游戏原声'。"""
    import re
    import subprocess
    r = subprocess.run([ffmpeg, "-v", "info", "-i", str(path), "-map", "0:a:0",
                        "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.findall(r"max_volume:\s*(-?[\d.]+)\s*dB", r.stderr or "")
    return float(m[-1]) if m else None


# ------------------------------------------------------------- NES / BizHawk

class BizHawkNESBackend:
    backend_id = "nes_bizhawk"

    def __init__(self, bizhawk_dir):
        self.bizhawk_dir = str(bizhawk_dir)

    def probe(self):
        exe = Path(self.bizhawk_dir) / "EmuHawk.exe"
        avail = exe.is_file()
        sj_ok, sj_ev = statejump_evidence()
        live = avail and sj_ok           # 能力转真双闸：BizHawk 可用 + 实跑验收全 pass
        sj_note = sj_ev if live else f"需 BizHawk 可用且实跑验收全 pass；{sj_ev}"
        return {
            "backend_id": self.backend_id,
            "available": avail,
            "clock_unit": "emu_frame",
            "capabilities": {
                "batch_replay": _cap(avail, "tas_replay 逐帧截图回放管线已验证（见 验证/replay_verification.json）"),
                "frame_step": _cap(avail, "Lua emu.frameadvance 逐帧推进"),
                "savestate": _cap(live, sj_note),
                "ram_read": _cap(live, sj_note),
                "audio_capture": _cap(False, "已知缺口：逐帧截图无声音，M5 独立补音频"),
                "interactive_step": _cap(live, sj_note),
            },
            "notes": ["核心须与 bk2 Header 一致（config.ini PreferredCores 强制）",
                      "BizHawk 版本须与 emuVersion 一致",
                      "savestate/ram_read/interactive_step 由 statejump.StateSession 接线，"
                      "证据门控见 验证/t3_statejump/report.json"],
        }

    def run_batch(self, profile, movie, rom, frames, out_dir, fps=60,
                  ffmpeg="ffmpeg", core="NesHawk", system="NES"):
        import tas_replay
        out_dir = str(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        rid = _run_id()
        res = tas_replay.run_replay(movie, rom, core, system,
                                    self.bizhawk_dir, frames)
        desync = res["desync"]
        term = res.get("termination", "unknown")
        wd = res.get("watchdog", {})
        from .watchdog import replay_verdict, exit_verdict
        _V = {"pass": Verdict.PASS, "fail": Verdict.FAIL,
              "inconclusive": Verdict.INCONCLUSIVE}
        v_desync = _V[replay_verdict(desync, term)]
        v_exit = _V[exit_verdict(term)]
        checks = [
            CheckResult("replay_no_desync", v_desync,
                        evidence_refs=[res["work"] + "/cap.txt"],
                        reason=res["report"] + f" | termination={term}"),
            CheckResult("watchdog_clean_exit", v_exit,
                        reason=f"termination={term}; dismissed={wd.get('dismissed', 0)}"),
            CheckResult("frames_captured",
                        Verdict.PASS if res["n_frames"] > 0 else Verdict.FAIL,
                        reason=f"{res['n_frames']}/{frames} 帧"),
        ]
        recording_refs = []
        video = os.path.join(out_dir, f"{rid}.mp4")
        if res["n_frames"] > 0 and desync is not True:
            tas_replay.encode_video(res["frames_dir"], fps, video, ffmpeg)
            okv = os.path.isfile(video) and os.path.getsize(video) > 0
            checks.append(CheckResult("video_encoded",
                                      Verdict.PASS if okv else Verdict.FAIL,
                                      evidence_refs=[video]))
            if okv:
                recording_refs.append(asset(video))
        else:
            checks.append(CheckResult("video_encoded", Verdict.FAIL,
                                      reason="无帧或 desync，未编码"))
        # 音频独立验收：截图链路无声 => 证据不足（不是通过），留待 M5
        checks.append(CheckResult("audio_present", Verdict.INCONCLUSIVE,
                                  reason="截图链路无音频源，M5 补同步音频后再验"))

        frame_map = {"clock_unit": "emu_frame", "fps": fps,
                     "count": res["n_frames"], "pts_formula": "frame/fps",
                     "lag_adjusted": False}
        fm_path = os.path.join(out_dir, f"{rid}.framemap.json")
        _write_json(fm_path, frame_map)
        ver = _verification("ver_" + rid, rid, Stage.CAPTURE, checks)
        run = {
            "schema_version": 1, "run_id": rid,
            "profile_id": profile.get("profile_id") if isinstance(profile, dict) else profile.profile_id,
            "input_ref": str(movie), "state_ref": None, "purpose": "batch_replay",
            "events_ref": None, "checkpoints_ref": res["work"] + "/cap.txt",
            "frame_map_ref": fm_path, "recording_refs": recording_refs,
            "desync": desync, "n_frames": res["n_frames"],
            "termination": term, "watchdog": wd,
            "verification": ver,
        }
        _write_json(os.path.join(out_dir, f"{rid}.run.json"), run)
        return run


# ------------------------------------------------------------- FBNeo / rig

class FBNeoBackend:
    backend_id = "arcade_fbneo"

    def __init__(self, rig_dir=RIG_DIR):
        self.rig_dir = str(rig_dir)

    def _rig(self):
        if self.rig_dir not in sys.path:
            sys.path.insert(0, self.rig_dir)
        import rig
        return rig

    def compile_check(self, notation):
        """采集前先把记法送进真编译器；谱面排版符号(·/或)在这里拦下，不浪费一次采集。"""
        rig = self._rig()
        r = rig.try_compile({"cmd": notation})
        return bool(r.get("ready")), r.get("why", "")

    def probe(self):
        try:
            rig = self._rig()
            import fbneo
            exe = fbneo.discover_exe()
            ref = rig.REFERENCE_MOVIE
            avail = os.path.isfile(exe) and os.path.isfile(ref)
            missing = [] if avail else [p for p in (exe, ref) if not os.path.isfile(p)]
            ev = f"exe={exe} ref={ref}" if avail else f"缺: {missing}"
        except Exception as e:
            avail, ev = False, f"探针异常: {type(e).__name__}: {e}"
        return {
            "backend_id": self.backend_id,
            "available": avail,
            "clock_unit": "emu_frame",
            "capabilities": {
                "batch_replay": _cap(avail, "rig.run_capture 电影→内录 AVI（已验证管线）"),
                "frame_step": _cap(False, "rig 靠墙上时间估帧(59.18fps)，非精确受控步进"),
                "savestate": _cap(avail, "rig .fs 存档（base.fs 等已产出）"),
                "ram_read": _cap(False, "本封装未接线 RAM 读取"),
                "audio_capture": _cap(avail, "内录 AVI 带音轨；实测招式片 benimaru_charge_c max -10.7dB。中立探针可为静音内容，须逐片复测非静音"),
                "interactive_step": _cap(False, "GUI 墙上时间驱动，不暴露给搜索"),
            },
            "notes": ["NEO_FPS=59.18，电影帧号→墙上时间", ev],
        }

    def run_batch(self, profile, out_dir, lead=72, avi3x=2, unmute=False,
                  ffmpeg="ffmpeg"):
        """薄封装 rig.cmd_probe 的核心：全中立电影→内录→帧数对齐验收。

        unmute=False 沿用 rig 默认静音（nAudVolume=0）：有音轨但录的是静音。
        要录游戏原声须 unmute=True，并由 game_audio_audible 复测（M5）。
        """
        out_dir = str(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        rid = _run_id()
        checks = []
        recording_refs = []
        failure = None
        try:
            rig = self._rig()
            import frfile
            frames = [set() for _ in range(lead + 30)]
            mv = frfile.Movie.from_reference(rig.REFERENCE_MOVIE, frames)
            out_fr = os.path.join(out_dir, f"{rid}.fr")
            mv.write(out_fr)
            n_movie = len(frames)
            avi, log, title, st = rig.run_capture(out_fr, n_movie, avi3x=avi3x,
                                                  unmute=unmute)
            n_avi, lost = rig.avi_accounting(n_movie, st, lead, [])
            okv = os.path.isfile(avi) and os.path.getsize(avi) > 0
            checks.append(CheckResult("avi_exists",
                                      Verdict.PASS if okv else Verdict.FAIL,
                                      evidence_refs=[avi]))
            checks.append(CheckResult("frame_alignment", Verdict.PASS,
                                      reason=f"电影{n_movie}/avi{n_avi} 起步丢{lost}帧"))
            streams = rig.probe_streams(avi).get("streams", [])
            a = next((s for s in streams if s.get("codec_type") == "audio"), None)
            checks.append(CheckResult(
                "audio_stream", Verdict.PASS if a else Verdict.FAIL,
                evidence_refs=[avi],
                reason=(f"audio={a.get('codec_name')}/{a.get('sample_rate')}Hz/"
                        f"{a.get('channels')}ch") if a else "AVI 无音轨"))
            # 有音轨 ≠ 录到游戏原声：默认静音约 -91dB。单独验非静音（M5 准入）。
            if a and okv:
                db = _audio_max_db(avi, ffmpeg)
                audible = db is not None and db > -90.0
                note = "" if audible else "（静音：默认 nAudVolume=0，需 unmute=True 重录复测）"
                checks.append(CheckResult(
                    "game_audio_audible",
                    Verdict.PASS if audible else Verdict.INCONCLUSIVE,
                    evidence_refs=[avi],
                    reason=f"max_volume={db}dB{note}"))
            if okv:
                recording_refs.append(asset(avi))
            _write_json(os.path.join(out_dir, f"{rid}.log.json"),
                        {"title": title, "log": log, "streams": st})
        except Exception as e:
            failure = {"code": FailureCode.UNSUPPORTED_CAPABILITY.value,
                       "reason": f"{type(e).__name__}: {e}"}
            checks.append(CheckResult("fbneo_capture", Verdict.FAIL,
                                      reason=failure["reason"]))

        frame_map = {"clock_unit": "emu_frame", "fps": 59.18,
                     "pts_formula": "frame/59.18", "lag_adjusted": False}
        fm_path = os.path.join(out_dir, f"{rid}.framemap.json")
        _write_json(fm_path, frame_map)
        ver = _verification("ver_" + rid, rid, Stage.CAPTURE, checks)
        pid = profile.get("profile_id") if isinstance(profile, dict) else getattr(profile, "profile_id", "kof98eck")
        run = {
            "schema_version": 1, "run_id": rid, "profile_id": pid,
            "input_ref": "rig.REFERENCE_MOVIE", "state_ref": None,
            "purpose": "batch_replay_probe", "events_ref": None,
            "checkpoints_ref": None, "frame_map_ref": fm_path,
            "recording_refs": recording_refs, "verification": ver,
            "failure": failure,
        }
        _write_json(os.path.join(out_dir, f"{rid}.run.json"), run)
        return run

    def run_move(self, notation, slug, out_dir, char="kyo", state=None,
                 unmute=True, avi3x=1, lead=None, tail=None, approach=0,
                 ffmpeg="ffmpeg"):
        """薄封装 rig.capture_move：一招 → 可用成片 + taspipe 独立验收（不重写 rig）。

        与 run_batch（全中立探针）不同，这里喂真实招式输入，出「测完就能用」的展示素材：
        unmute=True 录游戏原声；片头/帧数/色度由 rig.require_clip 把关；命中与否由 rig
        从 HUD 量（对手掉血），空放如实报 inconclusive（不是通过），留距离/记法/气复核。
        默认贴脸起手状态 states/base_<char>_close.fs（第0帧就在对手面前，片头不带路）。
        tail 默认对齐 rig.TAIL_FRAMES(120)：收尾要等被击飞的对手完全落地，capture_move
        自身的 60 帧默认会在对手半空时切掉（用户口径：结束太早）。
        """
        out_dir = str(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        rid = _run_id()
        checks = []
        recording_refs = []
        failure = None
        rec = None
        try:
            rig = self._rig()
            state = state or os.path.join(self.rig_dir, "states", f"base_{char}_close.fs")
            kw = dict(out_dir=out_dir, char=char, state_path=state, unmute=unmute,
                      avi3x=avi3x, approach=approach,
                      tail=tail if tail is not None else rig.TAIL_FRAMES)
            if lead is not None:
                kw["lead"] = lead
            rec, log = rig.capture_move(notation, slug, **kw)
            mp4 = rec["out"]
            okv = os.path.isfile(mp4) and os.path.getsize(mp4) > 0
            checks.append(CheckResult(
                "clip_encoded", Verdict.PASS if okv else Verdict.FAIL,
                evidence_refs=[mp4], reason=f"{rec.get('frames')}帧 {rec.get('size')}"))
            hf = bool(rec.get("head_is_fight"))
            checks.append(CheckResult(
                "head_is_fight", Verdict.PASS if hf else Verdict.INCONCLUSIVE,
                evidence_refs=[mp4],
                reason="成片第0帧是战斗画面（片头已跳过）" if hf else "片头未确认，需复核"))
            streams = rig.probe_streams(mp4).get("streams", [])
            a = next((s for s in streams if s.get("codec_type") == "audio"), None)
            checks.append(CheckResult(
                "audio_stream", Verdict.PASS if a else Verdict.FAIL,
                evidence_refs=[mp4],
                reason=(f"audio={a.get('codec_name')}/{a.get('sample_rate')}Hz/"
                        f"{a.get('channels')}ch") if a else "成片无音轨"))
            if a and okv:
                db = _audio_max_db(mp4, ffmpeg)
                audible = db is not None and db > -90.0
                checks.append(CheckResult(
                    "game_audio_audible",
                    Verdict.PASS if audible else Verdict.INCONCLUSIVE,
                    evidence_refs=[mp4],
                    reason=f"max_volume={db}dB" + ("" if audible else "（静音，需 unmute 复测）")))
            hit = bool(rec.get("hit"))
            checks.append(CheckResult(
                "move_hit", Verdict.PASS if hit else Verdict.INCONCLUSIVE,
                evidence_refs=[mp4],
                reason=f"对手掉血 {rec.get('damage', 0) * 100:.1f}%（"
                       + ("打中了" if hit else "空放：距离/记法/气需复核，不算可用展示素材") + "）"))
            if okv:
                recording_refs.append(asset(mp4))
            _write_json(os.path.join(out_dir, f"{rid}.log.json"),
                        {"rec": rec, "log": log})
        except Exception as e:
            failure = {"code": FailureCode.UNSUPPORTED_CAPABILITY.value,
                       "reason": f"{type(e).__name__}: {e}"}
            checks.append(CheckResult("fbneo_move", Verdict.FAIL,
                                      reason=failure["reason"]))

        frame_map = {"clock_unit": "emu_frame", "fps": 59.18,
                     "pts_formula": "frame/59.18", "lag_adjusted": False}
        fm_path = os.path.join(out_dir, f"{rid}.framemap.json")
        _write_json(fm_path, frame_map)
        ver = _verification("ver_" + rid, rid, Stage.CAPTURE, checks)
        run = {
            "schema_version": 1, "run_id": rid, "profile_id": "kof98eck",
            "input_ref": notation, "state_ref": (rec or {}).get("base_state"),
            "purpose": "move_showcase", "events_ref": None,
            "checkpoints_ref": None, "frame_map_ref": fm_path,
            "recording_refs": recording_refs, "verification": ver,
            "failure": failure, "move_rec": rec,
        }
        _write_json(os.path.join(out_dir, f"{rid}.run.json"), run)
        return run


# ------------------------------------------------------------- M10 资源驱动探针
# PS1(BizHawk Octoshock/Nymashock) 与 PSP(PPSSPP) 走「先探针、缺资源如实报
# blocked、不伪装成功」路线。两者采集管线都尚未接线：即便资源齐备，能力仍标
# supported=False，直到真正实现并验证电影回放 + 内录。PSP 未通过不阻塞现有
# NES/FBNeo 生产（强模型方案 §5 M10 退路）。

PS1_CORE_DLLS = ("octoshock.dll", "nymashock.dll")
PS1_BIOS_NAMES = ("scph5500.bin", "scph5501.bin", "scph5502.bin",
                  "scph1001.bin", "scph7001.bin", "psx.exe")
PS1_GAME_EXTS = (".cue", ".iso", ".chd", ".pbp", ".img", ".mdf", ".ecm", ".bin")
PSP_GAME_EXTS = (".iso", ".cso", ".pbp", ".chd", ".elf", ".prx")
PPSSPP_EXE_NAMES = ("ppssppwindows64.exe", "ppssppwindows.exe",
                    "ppssppheadless.exe", "ppssppsdl.exe", "ppsspp.exe", "ppsspp")


def _find_first(dirs, names=None, exts=None):
    """在若干目录里递归找第一个匹配文件（名字小写比对或扩展名）。返回 path|None。"""
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if not p.is_file():
                continue
            if names and p.name.lower() in names:
                return str(p)
            if exts and p.suffix.lower() in exts:
                return str(p)
    return None


def _m10_run(backend, profile, out_dir, purpose):
    """M10 诚实运行：缺资源 => MISSING_RESOURCE；资源齐但管线未接线 =>
    UNSUPPORTED_CAPABILITY。两种都不采集、都不 PASS，写 run.json 供台账复用。"""
    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    rid = _run_id()
    pr = backend.probe()
    pid = (profile.get("profile_id") if isinstance(profile, dict)
           else getattr(profile, "profile_id", backend.backend_id))
    if not pr["available"]:
        code = FailureCode.MISSING_RESOURCE
        reason = "缺资源: " + "; ".join(pr["missing"])
        check = CheckResult("resources_present", Verdict.FAIL, reason=reason)
    else:
        code = FailureCode.UNSUPPORTED_CAPABILITY
        reason = "资源就绪但采集管线尚未接线/验证（起点/输入/状态/观察/采集均未实现）"
        check = CheckResult("pipeline_wired", Verdict.FAIL, reason=reason)
    ver = _verification("ver_" + rid, rid, Stage.CAPTURE, [check])
    run = {
        "schema_version": 1, "run_id": rid, "profile_id": pid,
        "input_ref": None, "state_ref": None, "purpose": purpose,
        "events_ref": None, "checkpoints_ref": None, "frame_map_ref": None,
        "recording_refs": [], "verification": ver,
        "failure": {"code": code.value, "reason": reason}, "probe": pr,
    }
    _write_json(os.path.join(out_dir, f"{rid}.run.json"), run)
    return run


class BizHawkPS1Backend:
    """PS1 经 BizHawk Octoshock/Nymashock。该核心需真实 BIOS，无 HLE 替代。"""
    backend_id = "ps1_bizhawk"

    def __init__(self, bizhawk_dir=None, bios_dirs=None, game_dirs=None,
                 game=None, emu_root=None):
        self.emu_root = str(emu_root) if emu_root else str(PROJECT_ROOT / "02-模拟器库")
        self.bizhawk_dir = str(bizhawk_dir) if bizhawk_dir else None
        self.bios_dirs = ([str(x) for x in bios_dirs] if bios_dirs
                          else [str(PROJECT_ROOT / "03-BIOS库" / "PS1")])
        self.game_dirs = ([str(x) for x in game_dirs] if game_dirs else [
            str(PROJECT_ROOT / "04-游戏资源库" / "自己ROM放这里"),
            str(PROJECT_ROOT / "04-游戏资源库" / "homebrew自制")])
        self.game = str(game) if game else None

    def _discover_bizhawk(self):
        if self.bizhawk_dir:
            return self.bizhawk_dir
        from . import registry as R
        dirs = R.discover_bizhawk(self.emu_root)

        def ver_key(v):
            return tuple(int(x) for x in re.findall(r"\d+", v))
        ordered = sorted(dirs, key=ver_key, reverse=True)
        for v in ordered:                      # 优先带 PS1 核心 dll 的最高版本
            d = Path(dirs[v])
            if (d / "EmuHawk.exe").is_file() and any(
                    (d / "dll" / n).is_file() for n in PS1_CORE_DLLS):
                return str(d)
        return dirs[ordered[0]] if ordered else None

    def probe(self):
        bh = self._discover_bizhawk()
        exe = str(Path(bh) / "EmuHawk.exe") if bh else None
        exe_ok = bool(exe and Path(exe).is_file())
        core = _find_first([Path(bh) / "dll"], names=PS1_CORE_DLLS) if bh else None
        bios_search = list(self.bios_dirs)
        if bh:
            bios_search.append(str(Path(bh) / "Firmware"))
        bios = _find_first(bios_search, names=PS1_BIOS_NAMES)
        game = (self.game if self.game and Path(self.game).is_file()
                else _find_first(self.game_dirs, exts=PS1_GAME_EXTS))
        missing = []
        if not exe_ok:
            missing.append("EmuHawk.exe（BizHawk 前端）")
        if not core:
            missing.append("PS1 核心 dll（octoshock/nymashock）")
        if not bios:
            missing.append("PS1 BIOS（scph5500/5501/5502.bin；Octoshock 无 HLE，必须）")
        if not game:
            missing.append("PS1 游戏镜像（.cue/.bin/.iso/.chd）")
        avail = bool(exe_ok and core and bios and game)
        return {
            "backend_id": self.backend_id, "available": avail,
            "clock_unit": "emu_frame",
            "resources": {"bizhawk_dir": bh, "exe": exe, "exe_present": exe_ok,
                          "core_dll": core, "core_present": bool(core),
                          "bios": bios, "bios_present": bool(bios),
                          "game": game, "game_present": bool(game)},
            "missing": missing,
            "capabilities": {
                "start_boot": _cap(False, "未接线：需 Lua 加载 BIOS+游戏并确认引导到标题画面"),
                "input_movie": _cap(False, "未接线：PS1 电影回放尚未实现/验证"),
                "savestate": _cap(False, "未接线：Octoshock 存档 API 未验证"),
                "ram_read": _cap(False, "未接线：PS1 RAM 观察地址未标定"),
                "frame_capture": _cap(False, "未接线：PS1 逐帧/AVI 内录未实现"),
                "audio_capture": _cap(False, "未接线：PS1 同步音频采集未实现"),
            },
            "notes": [
                "Octoshock/Nymashock 需真实 PS1 BIOS，无 HLE（见 03-BIOS库/00-BIOS需求总表.md）",
                "即便资源齐备，采集管线仍未接线 => 能力 supported=False，不暴露给搜索",
                "缺资源 => MISSING_RESOURCE，补资源后再实现采集；不伪装成功",
            ],
        }

    def run_batch(self, profile, out_dir, **kw):
        return _m10_run(self, profile, out_dir, "ps1_batch_replay")


class PPSSPPBackend:
    """PSP 经独立 PPSSPP。固件可选（HLE/ProFX 替代）；TAS 采集需 headless/dev
    build + 电影 API，尚未接线。当前仓库仅克隆源码，无构建产物。"""
    backend_id = "psp_ppsspp"

    def __init__(self, exe=None, game=None, game_dirs=None, firmware_dir=None,
                 search_root=None):
        self.exe = str(exe) if exe else None
        self.game = str(game) if game else None
        self.game_dirs = ([str(x) for x in game_dirs] if game_dirs else [
            str(PROJECT_ROOT / "04-游戏资源库" / "自己ROM放这里"),
            str(PROJECT_ROOT / "04-游戏资源库" / "homebrew自制")])
        self.firmware_dir = (str(firmware_dir) if firmware_dir
                             else str(PROJECT_ROOT / "03-BIOS库" / "PSP"))
        self.search_root = (str(search_root) if search_root
                            else str(PROJECT_ROOT / "02-模拟器库"))

    def _discover_exe(self):
        if self.exe:
            return self.exe if Path(self.exe).is_file() else None
        root = Path(self.search_root)
        src = root / "已clone仓库" / "模拟器与核心" / "ppsspp"
        cands = []
        for sub in ("build", "build/Release", "build/Debug", "Windows/Release", "bin"):
            cands += [src / sub / n for n in PPSSPP_EXE_NAMES]
        for d in root.glob("PPSSPP*"):         # 独立安装目录（与源码同级）
            cands += [d / n for n in PPSSPP_EXE_NAMES]
        for c in cands:
            if c.is_file():
                return str(c)
        return None

    def probe(self):
        exe = self._discover_exe()
        game = (self.game if self.game and Path(self.game).is_file()
                else _find_first(self.game_dirs, exts=PSP_GAME_EXTS))
        fw = Path(self.firmware_dir) / "flash0"
        fw_ok = fw.is_dir() and any(p.is_file() for p in fw.rglob("*"))
        missing = []
        if not exe:
            missing.append("已构建的 PPSSPP 可执行文件（当前仅克隆源码，无 build 产物）")
        if not game:
            missing.append("PSP 游戏镜像（.iso/.cso/.pbp）")
        avail = bool(exe and game)
        return {
            "backend_id": self.backend_id, "available": avail,
            "clock_unit": "emu_frame",
            "resources": {"exe": exe, "exe_present": bool(exe),
                          "game": game, "game_present": bool(game),
                          "firmware_flash0": str(fw), "firmware_present": fw_ok},
            "missing": missing,
            "capabilities": {
                "start_boot": _cap(False, "未接线：需 headless 加载游戏并确认引导"),
                "input_movie": _cap(False, "未接线：PPSSPP 电影回放 API 未实现/验证"),
                "savestate": _cap(False, "未接线：PPSSPP 存档 API 未验证"),
                "ram_read": _cap(False, "未接线：PSP RAM 观察地址未标定"),
                "frame_capture": _cap(False, "未接线：PSP 逐帧/内录未实现"),
                "audio_capture": _cap(False, "未接线：PSP 同步音频采集未实现"),
            },
            "notes": [
                "PSP 固件可选：无 flash0 时 PPSSPP 用 HLE/ProFX 替代，多数游戏能跑（非阻塞）",
                "TAS 采集需 headless/dev build + 电影 API，尚未接线 => supported=False",
                "PSP 未通过不阻塞现有 NES/FBNeo 生产（强模型方案 §5 M10 退路）",
            ],
        }

    def run_batch(self, profile, out_dir, **kw):
        return _m10_run(self, profile, out_dir, "psp_batch_replay")


def _nes_backend_from_registry(pub_id):
    from . import registry as R
    pubs = {p["id"]: p for p in R.load_publications(R.DEFAULT_LIB)}
    r = R.assess(pubs[pub_id], R.DEFAULT_LIB, R.index_roms(R.DEFAULT_LIB),
                 R.index_versions(R.DEFAULT_LIB), R.discover_bizhawk(R.DEFAULT_EMU))
    if r["status"] != "replayable":
        raise SystemExit(f"pub {pub_id} 不可回放: " +
                         "; ".join(b["reason"] for b in r["blockers"]))
    prof = r["profile"]
    bizhawk = prof["capability_report"]["bizhawk_dir"]
    return BizHawkNESBackend(bizhawk), prof, r["movie"], r["rom_match"][0]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("backend", choices=["nes", "fbneo", "ps1", "psp"])
    p.add_argument("--bizhawk", default=None)
    p.add_argument("--game", default=None, help="显式指定游戏镜像（ps1/psp）")
    p.add_argument("--exe", default=None, help="显式指定 PPSSPP 可执行文件（psp）")
    rn = sub.add_parser("run-nes")
    rn.add_argument("--pub", default="5246")
    rn.add_argument("--frames", type=int, default=180)
    rn.add_argument("--fps", type=int, default=60)
    rn.add_argument("--out", required=True)
    rn.add_argument("--ffmpeg", default="ffmpeg")
    rf = sub.add_parser("run-fbneo")
    rf.add_argument("--out", required=True)
    rf.add_argument("--lead", type=int, default=72)
    rf.add_argument("--unmute", action="store_true", help="录游戏原声（默认静音）")
    rf.add_argument("--ffmpeg", default="ffmpeg")
    rm = sub.add_parser("run-move", help="一招→可用展示成片（薄包 rig.capture_move，默认录原声）")
    rm.add_argument("notation", help='记法，如 "→↓↘+A"')
    rm.add_argument("--slug", required=True)
    rm.add_argument("--char", default="kyo")
    rm.add_argument("--state", default=None, help="起手状态；默认 states/base_<char>_close.fs")
    rm.add_argument("--out", required=True)
    rm.add_argument("--mute", action="store_true", help="静音（默认录游戏原声）")
    rm.add_argument("--avi3x", type=int, default=1, choices=(1, 2, 3))
    rm.add_argument("--lead", type=int, default=None)
    rm.add_argument("--tail", type=int, default=None,
                    help="收尾帧数；默认 rig.TAIL_FRAMES(120)，等对手完全落地")
    rm.add_argument("--approach", type=int, default=0)
    rm.add_argument("--ffmpeg", default="ffmpeg")
    rp1 = sub.add_parser("run-ps1", help="M10 PS1：缺资源如实报 blocked，不伪装成功")
    rp1.add_argument("--out", required=True)
    rp1.add_argument("--bizhawk", default=None)
    rp1.add_argument("--game", default=None)
    rpp = sub.add_parser("run-psp", help="M10 PSP 独立试验：未通过不阻塞现有生产")
    rpp.add_argument("--out", required=True)
    rpp.add_argument("--exe", default=None)
    rpp.add_argument("--game", default=None)
    args = ap.parse_args()

    if args.cmd == "probe":
        if args.backend == "nes":
            from . import registry as R
            bh = args.bizhawk or R.discover_bizhawk(R.DEFAULT_EMU).get("2.8")
            print(json.dumps(BizHawkNESBackend(bh).probe(), ensure_ascii=False, indent=1))
        elif args.backend == "ps1":
            print(json.dumps(BizHawkPS1Backend(bizhawk_dir=args.bizhawk,
                                               game=args.game).probe(),
                             ensure_ascii=False, indent=1))
        elif args.backend == "psp":
            print(json.dumps(PPSSPPBackend(exe=args.exe, game=args.game).probe(),
                             ensure_ascii=False, indent=1))
        else:
            print(json.dumps(FBNeoBackend().probe(), ensure_ascii=False, indent=1))
        return 0

    if args.cmd == "run-nes":
        be, prof, movie, rom = _nes_backend_from_registry(args.pub)
        run = be.run_batch(prof, movie, rom, args.frames, args.out,
                           fps=args.fps, ffmpeg=args.ffmpeg)
        print(json.dumps(run, ensure_ascii=False, indent=1))
        return 0 if run["verification"]["verdict"] != "fail" else 2

    if args.cmd == "run-fbneo":
        run = FBNeoBackend().run_batch("kof98eck", args.out, lead=args.lead,
                                       unmute=args.unmute, ffmpeg=args.ffmpeg)
        print(json.dumps(run, ensure_ascii=False, indent=1))
        return 0 if run["verification"]["verdict"] != "fail" else 2

    if args.cmd == "run-move":
        run = FBNeoBackend().run_move(args.notation, args.slug, args.out,
                                      char=args.char, state=args.state,
                                      unmute=not args.mute, avi3x=args.avi3x,
                                      lead=args.lead, tail=args.tail,
                                      approach=args.approach, ffmpeg=args.ffmpeg)
        print(json.dumps(run, ensure_ascii=False, indent=1))
        return 0 if run["verification"]["verdict"] != "fail" else 2

    if args.cmd == "run-ps1":
        run = BizHawkPS1Backend(bizhawk_dir=args.bizhawk,
                                game=args.game).run_batch("ps1", args.out)
        print(json.dumps(run, ensure_ascii=False, indent=1))
        return 0 if run["verification"]["verdict"] != "fail" else 2

    if args.cmd == "run-psp":
        run = PPSSPPBackend(exe=args.exe, game=args.game).run_batch("psp", args.out)
        print(json.dumps(run, ensure_ascii=False, indent=1))
        return 0 if run["verification"]["verdict"] != "fail" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())