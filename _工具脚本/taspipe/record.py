# -*- coding: utf-8 -*-
"""M5：整条 TAS 录制 + 终点/成片/音频验收（依据 _scratch/强模型方案回复.md §5 M5）。

三道分开验：
  * 回放到达声明终点（n_frames == 电影帧数，无 desync）——600 帧前缀验证不能代替整片；
  * 最终视频确实录对（帧数/时长与帧映射一致）；
  * 音频独立闸门。NES 发行版 BizHawk 2.8 无头 A/V dump 实测不可用
    （--dump-type=avi 无产物；=ffmpeg 挂起 GUI 框）。默认（audio=False）判 inconclusive；
    --audio 走 WASAPI loopback 同步采集：强制实时回放(client.speedmode(100))录系统原声，
    不改核心/版本故不破坏确定性，mux 进成片后量 max_db 判非静音。
    音画同步：逐帧截图 I/O 让回放速率波动，单 atempo 线性校正中段残差实测可达 ±1.3s；
    改用逐帧 mtime 锚点重采样(warp_to_frames)把音频对齐到帧时间轴，再由
    audio.verify_frame_sync 拿现场帧 mtime + 多个静音->有声锚点实测复核（三态，证据不足不过）。
    按键沿瞬态法(input_sync_check)对乐曲密集游戏会被音乐掩盖，仅作旁证不作闸门。

运行: python -m taspipe.record full --pub 5246 --out <dir> [--frames N] [--fps 60] [--audio]
      python -m taspipe.record sync --run <已有run.json>        # 只重验同步，不重录
      python -m taspipe.record sync --run <已有run.json> --fix  # 逐帧重采样修复音频再验
"""
import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

from .schema import CheckResult, Verdict, Stage, asset, Verification
from .backends import _verification, _write_json, _run_id


def mux_av(video, wav, out, ffmpeg="ffmpeg"):
    """把音轨 mux 进视频。apad 把音轨补到不短于视频，-shortest 才以视频为准收尾；
    否则音轨稍短于视频时 -shortest 会截掉结尾视频帧（11-09 实测 3600→3599）。"""
    subprocess.run([ffmpeg, "-y", "-i", video, "-i", wav,
                    "-c:v", "copy", "-af", "apad", "-c:a", "aac",
                    "-shortest", out], check=True, capture_output=True)
    return out


def expected_frames(movie):
    """bk2 输入日志 '|' 行数 = 帧数；非 bk2 返回 None。"""
    try:
        z = zipfile.ZipFile(movie)
        name = "Input Log.txt"
        if name not in z.namelist():
            inner = [n for n in z.namelist() if n.lower().endswith(".bk2")]
            if not inner:
                return None
            import io
            z = zipfile.ZipFile(io.BytesIO(z.read(inner[0])))
        if name not in z.namelist():
            return None
        return sum(1 for l in z.read(name).decode("utf-8", "replace").splitlines()
                   if l.startswith("|"))
    except Exception:
        return None


def _probe_video(path, ffprobe="ffprobe"):
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                        "stream=codec_type,nb_frames:format=duration",
                        "-of", "json", str(path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        return None
    return json.loads(r.stdout or "{}")


def nes_audio_gate():
    """NES 发行版 2.8 音频闸门：实测无头 A/V dump 不可用 => inconclusive（不是通过）。"""
    return CheckResult(
        "audio_present", Verdict.INCONCLUSIVE,
        reason="BizHawk 2.8 发行版无头 A/V dump 实测不可用(avi 无产物/ffmpeg 挂起)；"
               "需 dev build 或 WASAPI loopback 同步采集后再验。截图链路目前无声。")


def run_full(backend, profile, movie, rom, out_dir, frames=None, fps=60,
             ffmpeg="ffmpeg", ffprobe="ffprobe", core="NesHawk", system="NES",
             audio=False, bezel="auto"):
    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    exp = frames or expected_frames(movie)
    if not exp:
        raise SystemExit("无法确定电影帧数（非 bk2 且未给 --frames）")
    rid = _run_id()
    import tas_replay
    # audio=True：强制实时回放 + WASAPI loopback 同步录系统原声（不改核心/版本，不破坏确定性）。
    rec = None
    t_rec = None
    wav = os.path.join(out_dir, f"{rid}.wav") if audio else None
    if audio:
        import time
        from .audio import LoopbackRecorder
        rec = LoopbackRecorder().start()
        t_rec = time.time()   # 采集起点；帧0截图 mtime 减去它 = 模拟器加载耗时（对齐用）
    res = tas_replay.run_replay(movie, rom, core, system,
                                backend.bizhawk_dir, exp, realtime=audio)
    if rec is not None:
        rec.stop(wav)   # 回放结束即停采集；起点偏移留 onset 复核
    audio_onset = None
    load_offset = None
    if audio and os.path.isfile(wav):
        from .audio import onset_sec
        audio_onset = onset_sec(wav)   # 首个可闻采样（音乐起点，未必是帧0：片头可能静音）
        f0 = os.path.join(res["frames_dir"], "f0000.png")
        if t_rec is not None and os.path.isfile(f0):
            load_offset = max(0.0, os.path.getmtime(f0) - t_rec)   # 真正的帧0对齐偏移=加载耗时
    # 逐帧截图有 I/O 开销，实时回放速率会波动。单 atempo 只校首尾直线，中段残差实测
    # 可到 ±1.3s；逐帧 mtime 是真实时钟，残差超 50ms 就改逐帧锚点重采样（warp），否则 atempo。
    wall_replay = None
    atempo = None
    mt_curve = None
    warp = False
    if audio and res["n_frames"] > 1:
        from .audio import frame_mt, clock_residual
        mt_curve = [t for _, t in frame_mt(res["frames_dir"])]
        if mt_curve:
            wall_replay = mt_curve[-1] - mt_curve[0]
            target = res["n_frames"] / fps
            resid = clock_residual(mt_curve, fps)
            warp = bool(len(resid) and float(abs(resid).max()) > 0.05)
            if not warp and abs(wall_replay - target) > 0.3:
                atempo = wall_replay / target
    # 三态判定：只有「cap.txt 明确写了 status=complete/movie_end 且无 desync」
    # 才配叫 pass。11-07 那次空 cap.txt（TIMEOUT 1635s 被杀）判了 pass，
    # 是「没发现失败＝通过」的假绿灯，这里堵死。
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
                    reason=f"termination={term}; dismissed={wd.get('dismissed', 0)}; "
                           f"stalls={wd.get('stalls', 0)}; elapsed={wd.get('elapsed')}s"),
        CheckResult("endpoint_reached",
                    Verdict.PASS if res["n_frames"] == exp else Verdict.FAIL,
                    reason=f"{res['n_frames']}/{exp} 帧（须整片到终点）"),
    ]
    recording_refs = []
    synced_wav = ref_wav = None
    ref_zero_wall = None
    video = os.path.join(out_dir, f"{rid}.mp4")
    # 卡死/超时也用已采到的帧继续编码、mux、出片 —— 自动退出之后的「继续下一步」。
    # 证据等级由上面两个 check 如实标注，不因为出了片就把回放洗成通过。
    if res["n_frames"] > 0 and desync is not True:
        tas_replay.encode_video(res["frames_dir"], fps, video, ffmpeg)
        okv = os.path.isfile(video) and os.path.getsize(video) > 0
        checks.append(CheckResult("video_encoded",
                                  Verdict.PASS if okv else Verdict.FAIL,
                                  evidence_refs=[video]))
        if okv:
            if audio and os.path.isfile(wav):
                # 先按加载耗时裁掉前缀（独立文件，避免 -ss+-shortest+-c:v copy 截断视频），再 mux。
                src_wav = wav
                ref_zero_wall = t_rec
                # 录音停止比末帧晚约一个 watchdog 退出间隔（尾巴），只裁前缀会留下超出
                # 帧时间轴的尾音使 audio_sync_review 时长闸误报；用 -t 把音频界定到
                # [帧0, 末帧+1帧] 的真实跨度。重编码 PCM 才能采样级精确裁切。
                ss = load_offset if (load_offset is not None and load_offset > 0.1) else 0.0
                if mt_curve:
                    from .audio import trim_span
                    span = (mt_curve[-1] - mt_curve[0]) + 1.0 / fps
                    src_wav = os.path.join(out_dir, f"{rid}_trim.wav")
                    trim_span(wav, ss, span, src_wav, ffmpeg)
                    ref_zero_wall = mt_curve[0]
                elif load_offset is not None and load_offset > 0.1:
                    from .audio import trim_span
                    src_wav = os.path.join(out_dir, f"{rid}_trim.wav")
                    trim_span(wav, load_offset, None, src_wav, ffmpeg)
                    ref_zero_wall = t_rec + load_offset
                ref_wav = src_wav   # 校正前（已裁前缀+界尾），同步闸门的参考
                if warp:
                    from .audio import warp_to_frames
                    corr = os.path.join(out_dir, f"{rid}_sync.wav")
                    warp_to_frames(src_wav, mt_curve, fps, ref_zero_wall, corr)
                    src_wav = corr
                elif atempo:
                    corr = os.path.join(out_dir, f"{rid}_drift.wav")
                    subprocess.run([ffmpeg, "-y", "-i", src_wav, "-af", f"atempo={atempo:.6f}",
                                    "-c:a", "pcm_s16le", corr], check=True, capture_output=True)
                    src_wav = corr
                synced_wav = src_wav
                muxed = os.path.join(out_dir, f"{rid}_av.mp4")
                mux_av(video, src_wav, muxed, ffmpeg)
                os.replace(muxed, video)
                recording_refs.append(asset(wav))
                if synced_wav != wav:
                    recording_refs.append(asset(synced_wav))
            recording_refs.append(asset(video))
            d = _probe_video(video, ffprobe) or {}
            v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
            nb = int(v.get("nb_frames") or 0)
            dur = float(d.get("format", {}).get("duration") or 0)
            checks.append(CheckResult("final_video_frames",
                                      Verdict.PASS if nb == res["n_frames"] else Verdict.FAIL,
                                      evidence_refs=[video],
                                      reason=f"mp4 {nb} 帧 vs 采集 {res['n_frames']}"))
            checks.append(CheckResult("final_video_duration",
                                      Verdict.PASS if abs(dur - res["n_frames"] / fps) < 0.5 else Verdict.FAIL,
                                      reason=f"mp4 {dur:.2f}s vs {res['n_frames']/fps:.2f}s"))
    else:
        checks.append(CheckResult("video_encoded", Verdict.FAIL, reason="无帧或 desync"))
    if audio:
        from .audio import max_db, onset_sec
        have_wav = os.path.isfile(wav)
        db = max_db(wav) if have_wav else None
        audible = db is not None and db > -60.0
        checks.append(CheckResult(
            "audio_non_silent", Verdict.PASS if audible else Verdict.INCONCLUSIVE,
            evidence_refs=[wav] if have_wav else [],
            reason=f"loopback max_db={db}dB" + ("" if audible else
                   "（未录到原声/静音：复核默认输出设备与模拟器声音是否开启）")))
        onset = audio_onset if audio_onset is not None else (onset_sec(wav) if have_wav else None)
        lo = f"{load_offset:.2f}" if load_offset is not None else "None"
        corr = ("逐帧 mtime 锚点重采样(warp)" if warp else
                (f"线性 atempo={atempo:.6f}" if atempo else "无漂移校正"))
        drift = (f"；墙钟 {wall_replay:.2f}s vs 成片 {res['n_frames']/fps:.2f}s，{corr}"
                 if wall_replay else "")
        align = (f"load_offset={lo}s 裁前缀对齐帧0（音乐 onset={onset}s，片头可能静音）"
                 f"{drift}；")
        if have_wav and mt_curve and synced_wav:
            from .audio import verify_frame_sync
            sync = verify_frame_sync(res["frames_dir"], mt_curve, synced_wav,
                                     ref_wav, ref_zero_wall, fps)
            checks.append(CheckResult("audio_sync_review", sync.verdict,
                                      evidence_refs=sync.evidence_refs,
                                      reason=align + sync.reason))
        else:
            checks.append(CheckResult("audio_sync_review", Verdict.INCONCLUSIVE,
                                      reason=align + "无逐帧时钟曲线或 wav，未验"))
    else:
        checks.append(nes_audio_gate())

    # FC 自动封面边框：auto = NES 且本地缓存了对应 ROM sha1 的天马封面才套；
    # 无封面不臆造、跳过并如实标注（先跑 tianma_fetch 缓存）。on = 强制（无封面退路深色底）。
    deliver = video
    if bezel != "off" and os.path.isfile(video):
        is_fc = (system or "").upper() in ("NES", "FC", "FAMICOM")
        if bezel == "on" or is_fc:
            import hashlib
            from . import exporter
            sha = hashlib.sha1(Path(rom).read_bytes()).hexdigest().upper()
            cover = exporter.find_cover(rom_sha1=sha)
            if cover or bezel == "on":
                bordered = os.path.join(out_dir, f"{rid}_bordered.mp4")
                br = exporter.compose(video, bordered, rom_sha1=sha,
                                      ffmpeg=ffmpeg, ffprobe=ffprobe)
                bv = br["verification"]["verdict"]
                checks.append(CheckResult(
                    "bezel_export", _V[bv], evidence_refs=[bordered],
                    reason=f"FC 封面边框 x{br['layout']['scale']} -> {bordered}；"
                           f"合成验收={bv}"))
                recording_refs.append(asset(bordered))
                deliver = bordered
            else:
                checks.append(CheckResult(
                    "bezel_cover", Verdict.INCONCLUSIVE,
                    reason=f"FC 自动边框：本地无 sha1={sha} 的天马封面，跳过边框；"
                           f"先跑 tianma_fetch --game <网盘目录名> --slug <本地slug> --sha1 {sha} 缓存"))

    frame_map = {"clock_unit": "emu_frame", "fps": fps, "count": res["n_frames"],
                 "expected": exp, "pts_formula": "frame/fps", "lag_adjusted": False,
                 "tail_policy": "replay_to_movie_end：只复播到输入日志末帧（通关判定/最终出口帧）；"
                                "输入结束后的结局/credits 不补录；首帧为加载空白、末帧为通关现场，"
                                "首尾各抽帧留证目视确认",
                 "audio_wall_span": round(wall_replay, 3) if wall_replay else None,
                 "audio_drift_atempo": round(atempo, 6) if atempo else None}
    fm = os.path.join(out_dir, f"{rid}.framemap.json")
    _write_json(fm, frame_map)
    ver = _verification("ver_" + rid, rid, Stage.CAPTURE, checks)
    pid = profile.get("profile_id") if isinstance(profile, dict) else profile.profile_id
    run = {"schema_version": 1, "run_id": rid, "profile_id": pid,
           "input_ref": str(movie), "state_ref": None, "purpose": "full_replay",
           "events_ref": None, "checkpoints_ref": res["work"] + "/cap.txt",
           "frame_map_ref": fm, "recording_refs": recording_refs,
           "deliverable_ref": deliver,
           "desync": desync, "n_frames": res["n_frames"], "expected": exp,
           "termination": term, "watchdog": wd,
           "verification": ver}
    _write_json(os.path.join(out_dir, f"{rid}.run.json"), run)
    return run


def _update_sync_check(run, chk):
    """把 audio_sync_review 检查行替换/追加进 run，并按三态重新聚合总 verdict。"""
    row = {"check_id": chk.check_id, "verdict": chk.verdict.value,
           "evidence_refs": chk.evidence_refs, "event_position": None,
           "reason": chk.reason}
    checks = run["verification"]["checks"]
    for i, c in enumerate(checks):
        if c["check_id"] == "audio_sync_review":
            checks[i] = row
            break
    else:
        checks.append(row)
    crs = [CheckResult(c["check_id"], c["verdict"], c.get("evidence_refs", []),
                       c.get("event_position"), c.get("reason", ""))
           for c in checks]
    v = Verification(run["verification"]["verification_id"],
                     run["verification"]["subject_ref"],
                     run["verification"]["stage"], crs).validate()
    run["verification"]["verdict"] = v.verdict.value


def _frames_dir_of(run):
    return str(Path(run["checkpoints_ref"]).parent / "frames")


def reverify_sync(run_json, ffmpeg="ffmpeg"):
    """对已出片产物重跑逐帧同步闸门并更新 run.json（不重录、不改音频，走同一生产检查函数）。"""
    run = json.loads(Path(run_json).read_text(encoding="utf-8"))
    fm = json.loads(Path(run["frame_map_ref"]).read_text(encoding="utf-8"))
    fps = float(fm["fps"])
    frames_dir = _frames_dir_of(run)
    from .audio import frame_mt, verify_frame_sync
    mt_curve = [t for _, t in frame_mt(frames_dir)] if os.path.isdir(frames_dir) else []
    refs = [a["uri"] for a in run.get("recording_refs", [])]
    rid = run["run_id"]
    synced = next((u for u in refs if u.endswith("_sync.wav")), None)
    ref_wav = (next((u for u in refs if u.endswith("_trim.wav")), None)
               or next((u for u in refs if u.endswith(rid + ".wav")), None))
    if not mt_curve or not synced or not ref_wav:
        chk = CheckResult("audio_sync_review", Verdict.INCONCLUSIVE,
                          reason="缺逐帧时钟曲线或校正音频(_sync.wav)/参考音频，先跑 sync --fix")
    else:
        chk = verify_frame_sync(frames_dir, mt_curve, synced, ref_wav, mt_curve[0], fps)
    _update_sync_check(run, chk)
    _write_json(run_json, run)
    return run["verification"]


def refix_audio(run_json, frames_dir=None, ffmpeg="ffmpeg", ffprobe="ffprobe"):
    """修复已出片产物的音画同步（不重录视频）：用现场帧 mtime 曲线把裁前缀音频逐帧锚点
    重采样(warp)，与纯视频重新 mux，过 verify_frame_sync 闸门，更新 run.json/framemap。
    旧成片冻结成 _oldsync.mp4 失败现场（假绿灯实物留证）。帧目录被清则拒绝（无法逐帧校正）。
    """
    run = json.loads(Path(run_json).read_text(encoding="utf-8"))
    fm_path = run["frame_map_ref"]
    fm = json.loads(Path(fm_path).read_text(encoding="utf-8"))
    fps = float(fm["fps"])
    out_dir = os.path.dirname(os.path.abspath(run_json))
    rid = run["run_id"]
    if frames_dir is None:
        frames_dir = _frames_dir_of(run)
    from .audio import frame_mt, warp_to_frames, verify_frame_sync
    if not os.path.isdir(frames_dir):
        raise SystemExit(f"现场帧目录缺失，无法逐帧校正: {frames_dir}")
    mt_curve = [t for _, t in frame_mt(frames_dir)]
    if len(mt_curve) != run["n_frames"]:
        raise SystemExit(f"现场帧 {len(mt_curve)} != run 记录 {run['n_frames']}，曲线不完整")
    ref_wav = os.path.join(out_dir, f"{rid}_trim.wav")
    if not os.path.isfile(ref_wav):
        ref_wav = os.path.join(out_dir, f"{rid}.wav")
    if not os.path.isfile(ref_wav):
        raise SystemExit("缺参考音频（_trim.wav / .wav）")
    vsrc = os.path.join(out_dir, f"{rid}_vonly.mp4")
    video = os.path.join(out_dir, f"{rid}.mp4")
    if not os.path.isfile(vsrc):
        if not os.path.isfile(video):
            raise SystemExit("缺纯视频中间件且无当前成片可抽视频流")
        subprocess.run([ffmpeg, "-y", "-i", video, "-map", "0:v:0", "-c", "copy", vsrc],
                       check=True, capture_output=True)
    ref_zero_wall = mt_curve[0]
    synced = os.path.join(out_dir, f"{rid}_sync.wav")
    warp_to_frames(ref_wav, mt_curve, fps, ref_zero_wall, synced)
    oldsync = os.path.join(out_dir, f"{rid}_oldsync.mp4")
    if os.path.isfile(video) and not os.path.isfile(oldsync):
        os.replace(video, oldsync)
    muxed = os.path.join(out_dir, f"{rid}_av.mp4")
    mux_av(vsrc, synced, muxed, ffmpeg)
    os.replace(muxed, video)
    chk = verify_frame_sync(frames_dir, mt_curve, synced, ref_wav, ref_zero_wall, fps)
    refs = []
    for p in [os.path.join(out_dir, f"{rid}.wav"), ref_wav, synced, vsrc, oldsync, video]:
        if os.path.isfile(p):
            a = asset(p)
            if a not in refs:
                refs.append(a)
    run["recording_refs"] = refs
    run["deliverable_ref"] = video
    fm["audio_drift_atempo"] = None
    fm["audio_correction"] = "warp_mtime"
    fm["audio_warp_span"] = round(mt_curve[-1] - mt_curve[0], 3)
    fm["audio_sync_verdict"] = chk.verdict.value
    _write_json(fm_path, fm)
    chk.reason = (f"逐帧 mtime 锚点重采样(warp)：墙钟 {mt_curve[-1] - mt_curve[0]:.2f}s "
                  f"-> 帧时间轴 {run['n_frames'] / fps:.2f}s；") + chk.reason
    _update_sync_check(run, chk)
    _write_json(run_json, run)
    return run["verification"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["full", "sync"])
    ap.add_argument("--run", help="sync 子命令：已有 run.json 路径（重验音画同步，不重录）")
    ap.add_argument("--fix", action="store_true",
                    help="sync 子命令：先用现场帧 mtime 逐帧重采样修复音频再验（不重录视频）")
    ap.add_argument("--pub", default="5246")
    ap.add_argument("--frames", type=int, default=None)
    ap.add_argument("--fps", type=float, default=60.0,
                    help="编码帧率；NES 实时音频对齐须用核心原生率(NTSC≈60.0988)，"
                         "否则成片比实时音轨长、-shortest 会截掉结尾")
    ap.add_argument("--out", help="full 子命令的输出目录")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    ap.add_argument("--audio", action="store_true",
                    help="强制实时回放并 WASAPI loopback 同步录原声（NES 音频准入）")
    ap.add_argument("--border", choices=["auto", "on", "off"], default="auto",
                    help="FC 封面边框：auto=NES 且已缓存对应天马封面才套（默认）；"
                         "on=强制（无封面退路深色底）；off=不套")
    args = ap.parse_args()
    if args.cmd == "sync":
        if not args.run:
            raise SystemExit("sync 子命令需要 --run <run.json>")
        if args.fix:
            ver = refix_audio(args.run, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
        else:
            ver = reverify_sync(args.run, ffmpeg=args.ffmpeg)
        print(json.dumps(ver, ensure_ascii=False, indent=1))
        return 0 if ver["verdict"] != "fail" else 2
    if not args.out:
        raise SystemExit("full 子命令需要 --out <dir>")
    from .backends import _nes_backend_from_registry
    be, prof, movie, rom = _nes_backend_from_registry(args.pub)
    run = run_full(be, prof, movie, rom, args.out, frames=args.frames,
                   fps=args.fps, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe,
                   audio=args.audio, bezel=args.border)
    print(json.dumps(run, ensure_ascii=False, indent=1))
    return 0 if run["verification"]["verdict"] != "fail" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())