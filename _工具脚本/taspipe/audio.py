# -*- coding: utf-8 -*-
"""M5/#10：NES 同步音频采集（WASAPI loopback）+ 产物级音画同步复核。

发行版 BizHawk 2.8 无头 A/V dump 不可用，改录系统回放的遊戲原声（loopback）。
不改动模拟器版本/核心 => 不破坏回放确定性。
同步要点：回放须强制实时（client.speedmode(100)），loopback 与帧 0 同时启动；
起点偏移（加载/片头）靠裁前缀对齐帧0。逐帧截图 I/O 让速率波动，单 atempo 中段残差
实测可达 ±1.3s，故用逐帧 mtime 锚点重采样(warp_to_frames)对齐到帧时间轴。
闸门 verify_frame_sync：锚点==现场帧 mtime（防用错曲线）+ 时钟单调/速率 sane +
时长==帧时间轴 + 多个持续静音->有声锚点逐一对帧（查中段漂移，三态证据不足不过）。
按键沿瞬态法 input_sync_check 对乐曲密集游戏会被音乐掩盖，仅作旁证不作闸门。
"""
import io
import os
import re
import subprocess
import threading
import wave
import zipfile

import numpy as np
import pyaudiowpatch as pa

from .schema import CheckResult, Verdict


def loopback_device(p):
    wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
    default_out = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
    for d in p.get_loopback_device_info_generator():
        if d["name"].startswith(default_out["name"]):
            return d
    raise RuntimeError("找不到默认输出的 WASAPI loopback 设备")


class LoopbackRecorder:
    """start() 开始录系统回放声音；stop(wav) 落盘。线程安全地收集回调块。"""

    def __init__(self):
        self._p = pa.PyAudio()
        try:
            dev = loopback_device(self._p)
        except Exception:
            self._p.terminate()
            raise
        self.rate = int(dev["defaultSampleRate"])
        self.channels = min(2, int(dev["maxInputChannels"]))
        self._index = int(dev["index"])
        self._chunks = []
        self._stream = None
        self._lock = threading.Lock()

    def _callback(self, in_data, frame_count, time_info, status):
        with self._lock:
            self._chunks.append(in_data)
        return (None, pa.paContinue)

    def start(self):
        self._stream = self._p.open(
            format=pa.paInt16, channels=self.channels, rate=self.rate,
            input=True, input_device_index=self._index,
            frames_per_buffer=1024, stream_callback=self._callback)
        self._stream.start_stream()
        return self

    def stop(self, out_wav):
        if self._stream is not None:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        with self._lock:
            data = b"".join(self._chunks)
            self._chunks = []
        with wave.open(str(out_wav), "wb") as w:
            w.setnchannels(self.channels)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(data)
        self._p.terminate()
        return out_wav


def max_db(wav_path):
    """WAV 最大音量 dB（区分有原声 / 静音）。"""
    with wave.open(str(wav_path), "rb") as w:
        n = w.getnframes()
        raw = w.readframes(n)
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    if a.size == 0:
        return None
    peak = np.abs(a).max()
    if peak <= 0:
        return -91.0
    return round(20 * np.log10(peak / 32768.0), 1)


def onset_sec(wav_path, thresh_db=-60.0):
    """首个超过阈值的采样时间（秒），用于对齐音频起点；全静音返回 None。"""
    with wave.open(str(wav_path), "rb") as w:
        rate = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768.0
    if a.size == 0:
        return None
    # raw 是多声道交错采样，时间基须按 rate*channels，否则立体声 onset 会翻倍。
    win = max(1, rate * ch // 100)  # 10ms
    for i in range(0, a.size - win, win):
        seg = a[i:i + win]
        db = 20 * np.log10(max(np.abs(seg).max(), 1e-9))
        if db > thresh_db:
            return round(i / (rate * ch), 3)
    return None


def press_frames(movie, buttons=("P1 A", "P1 B")):
    """bk2 里指定键的按下沿帧号（0 起）。列位从 LogKey 解析，不硬编码键序；
    '#' 标记每组首键（如 #Power|Reset|#P1 Up|...），按住不算沿。"""
    z = zipfile.ZipFile(movie)
    if "Input Log.txt" not in z.namelist():
        inner = [n for n in z.namelist() if n.lower().endswith(".bk2")]
        if not inner:
            return []
        z = zipfile.ZipFile(io.BytesIO(z.read(inner[0])))
    if "Input Log.txt" not in z.namelist():
        return []
    lines = z.read("Input Log.txt").decode("utf-8", "replace").splitlines()
    key = next((l for l in lines if l.startswith("LogKey:")), None)
    if not key:
        return []
    cols = {}
    g, i = -1, 0
    for tok in key[len("LogKey:"):].split("|"):
        if not tok:
            continue
        if tok.startswith("#"):
            g += 1
            i = 0
            tok = tok[1:]
        else:
            i += 1
        cols[tok] = (g, i)
    want = [cols[b] for b in buttons if b in cols]
    if not want:
        return []
    out = []
    prev = [False] * len(want)
    f = -1
    for l in lines:
        if not l.startswith("|"):
            continue
        f += 1
        groups = l.split("|")[1:-1]
        cur = [gi < len(groups) and ci < len(groups[gi]) and groups[gi][ci] != "."
               for gi, ci in want]
        if any(c and not p for c, p in zip(cur, prev)):
            out.append(f)
        prev = cur
    return out


def decode_audio(path, ffmpeg="ffmpeg", rate=48000):
    """容器音轨 -> mono float32 PCM（同步测量用，不落盘）。"""
    r = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0",
                        "-f", "f32le", "-ac", "1", "-ar", str(rate), "-"],
                       capture_output=True)
    if r.returncode:
        raise RuntimeError(f"解码音轨失败: {path}")
    return np.frombuffer(r.stdout, dtype="<f4"), rate


def sync_deltas(pcm, rate, frames, fps, max_samples=300):
    """按键帧 t=frame/fps 附近 [-60ms,+150ms] 找最强能量上升沿，delta=沿-t（秒）。

    音乐里也有瞬态，单个样本不可信；靠几百个样本的中位数聚类判同步。
    找不到显著上升沿的样本记 None（不计入，不冒充证据）。
    """
    hop = max(1, rate // 200)          # 5ms 能量窗
    n = len(pcm) // hop
    if n < 4 or not frames:
        return []
    e = np.sqrt(np.mean(pcm[:n * hop].reshape(n, hop) ** 2, axis=1))
    rise = np.diff(e, prepend=e[:1])
    step = max(1, len(frames) // max_samples)
    out = []
    for f in frames[::step]:
        t = f / fps
        lo = int((t - 0.06) * rate / hop)
        hi = int((t + 0.15) * rate / hop)
        if lo < 1 or hi >= n:
            continue
        i = lo + int(np.argmax(rise[lo:hi]))
        base = float(np.median(e[lo:hi]))
        if rise[i] <= 0 or e[i] < max(3.0 * base, 1e-4):
            out.append((f, None))
        else:
            out.append((f, round(i * hop / rate - t, 4)))
    return out


def judge_sync(samples):
    """三态：有效样本 <30 证据不足；整体偏移/三段漂移越界 fail；界内 pass。

    容差是工程判据：整体中位 [-20ms,+80ms]（游戏侧发声允许晚几帧）；
    前/中/后三段中位互差 ≤34ms（约 2 帧）——atempo 线性校不准会在这里露馅。
    """
    ds = sorted((f, d) for f, d in samples if d is not None)
    if len(ds) < 30:
        return Verdict.INCONCLUSIVE, f"有效瞬态样本 {len(ds)}<30，证据不足"
    med = float(np.median([d for _, d in ds]))
    third = max(1, len(ds) // 3)
    meds = [float(np.median([d for _, d in ds[i:i + third]]))
            for i in (0, third, 2 * third)]
    drift = max(meds) - min(meds)
    reason = (f"n={len(ds)} 中位偏移={med * 1000:.1f}ms "
              f"三段中位={[round(m * 1000, 1) for m in meds]}ms "
              f"漂移={drift * 1000:.1f}ms")
    if not (-0.02 <= med <= 0.08):
        return Verdict.FAIL, reason + "；整体偏移越界"
    if drift > 0.034:
        return Verdict.FAIL, reason + "；前中后漂移越界（线性校正不准）"
    return Verdict.PASS, reason


def input_sync_check(video, movie, fps, ffmpeg="ffmpeg"):
    """产物级音画同步复核：bk2 按键沿 vs 成片音轨瞬态，返回 CheckResult。"""
    try:
        frames = press_frames(movie)
        if not frames:
            return CheckResult("audio_sync_review", Verdict.INCONCLUSIVE,
                               reason="bk2 无可用按键沿")
        pcm, rate = decode_audio(video, ffmpeg)
        samples = sync_deltas(pcm, rate, frames, fps)
    except Exception as e:
        return CheckResult("audio_sync_review", Verdict.INCONCLUSIVE,
                           reason=f"同步测量不可跑: {type(e).__name__}: {e}")
    v, reason = judge_sync(samples)
    return CheckResult("audio_sync_review", v, evidence_refs=[str(video)],
                       reason=reason)


def frame_mt(frames_dir):
    """[(帧号, mtime)] 按帧号升序。f%04d 超过 9999 变 5 位，字典序会乱，必须按数字排。"""
    out = []
    for name in os.listdir(frames_dir):
        m = re.fullmatch(r"f(\d+)\.png", name)
        if m:
            out.append((int(m.group(1)), os.path.getmtime(os.path.join(frames_dir, name))))
    out.sort()
    return out


def clock_residual(mt, fps):
    """单 atempo 线性模型下每帧的音画错位（秒）：墙钟偏移/atempo - 帧PTS。

    逐帧 mtime 是录制的真实时钟；它偏离直线多少，单 atempo 在中段就错多少
    （实测整片可到 ±1.3s）。残差超容差就该换逐帧锚点校正 warp_to_frames。
    """
    mt = np.asarray(mt, dtype=np.float64)
    n = len(mt)
    if n < 2:
        return np.zeros(n)
    atempo = (mt[-1] - mt[0]) / (n / fps)
    return (mt - mt[0]) / atempo - np.arange(n) / fps


def warp_to_frames(wav, mt, fps, src_zero_wall, out_wav):
    """按逐帧 mtime 曲线把音频重采样到帧时间轴（逐帧锚点，替代单 atempo）。

    输出 PTS t 的采样 = 源墙钟 w(t) 处的采样（线性插值），w(t) 由 (帧PTS->mtime) 插值；
    src_zero_wall = 源 wav 采样 0 的墙钟（trim 后 = mt[0]），起点裁剪内含。
    代价：瞬时速率偏离 1 带来轻微音高调制（实测 95% 时间 <1%），换逐帧对齐、无累积漂移。
    """
    with wave.open(str(wav), "rb") as w:
        rate, ch = w.getframerate(), w.getnchannels()
        src = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32)
    src = src.reshape(-1, ch)
    mt = np.asarray(mt, dtype=np.float64)
    n_out = int(round(len(mt) / fps * rate))
    pts = np.arange(n_out, dtype=np.float64) / rate
    wall = np.interp(pts, np.arange(len(mt)) / fps, mt)
    j = np.clip((wall - src_zero_wall) * rate, 0, len(src) - 1)
    i0 = j.astype(np.int64)
    i1 = np.minimum(i0 + 1, len(src) - 1)
    frac = (j - i0).astype(np.float32)[:, None]
    out = src[i0] * (1 - frac) + src[i1] * frac
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.clip(out, -32768, 32767).astype("<i2").tobytes())
    return out_wav


def wav_duration(wav):
    with wave.open(str(wav), "rb") as w:
        return w.getnframes() / w.getframerate()


def trim_span(wav, ss, span, out, ffmpeg="ffmpeg"):
    """采样级裁切 WAV 到 [ss, ss+span]；span=None 只裁前缀不界尾。

    重编码 PCM 才能按 -ss/-t 精确裁切（-c copy 在 WAV 上按块 seek 会裁错量）。
    界尾(span)用于去掉录音停止晚于末帧的尾巴，使音频跨度==帧时间轴。
    """
    cmd = [ffmpeg, "-y", "-ss", f"{ss:.3f}", "-i", str(wav)]
    if span is not None:
        cmd += ["-t", f"{span:.3f}"]
    cmd += ["-c:a", "pcm_s16le", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def onsets(wav_path, thresh_db=-60.0, min_gap=0.5, min_silence=0.1):
    """静音->可闻 跳变时刻列表（秒），合并 min_gap 内的连续跳变。

    只认持续 >=min_silence 的静音之后的起声作锚点：乐曲里的微静音(<0.1s)在重采样
    前后检测边界会漂上百毫秒（实测假锚点 106/95ms），持续静音的段落起点才稳定可复核。
    """
    with wave.open(str(wav_path), "rb") as w:
        rate, ch = w.getframerate(), w.getnchannels()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    win = max(1, rate * ch // 100)
    dt = win / (rate * ch)
    times = []
    prev = False
    last = -1e9
    silrun = 0.0
    for i in range(0, a.size - win, win):
        db = 20 * np.log10(max(float(np.abs(a[i:i + win]).max()), 1e-9))
        audible = db > thresh_db
        t = i / (rate * ch)
        if audible and not prev and t - last > min_gap and silrun >= min_silence:
            times.append(round(t, 3))
            last = t
        silrun = 0.0 if audible else silrun + dt
        prev = audible
    return times


def verify_frame_sync(frames_dir, mt_used, synced_wav, ref_wav, ref_zero_wall, fps):
    """产物级音画同步闸门：验证"按 mtime 曲线校正"真把音频对齐到帧时间轴。

    查：锚点==现场帧 mtime（防用错/过期曲线）/ 时钟单调 / 速率不离谱 /
    校正后时长==帧时间轴长 / 多个静音->有声锚点逐一对帧（首声只验起点，多锚点查中段漂移）。
    现场帧目录被清或锚点不足 => inconclusive（无法复核，不冒充通过）。
    """
    try:
        pairs = frame_mt(frames_dir)
    except OSError:
        pairs = []
    if not pairs:
        return CheckResult("audio_sync_review", Verdict.INCONCLUSIVE,
                           reason="现场帧目录缺失，无法复核同步映射")
    mt = np.array([t for _, t in pairs], dtype=np.float64)
    used = np.asarray(mt_used, dtype=np.float64)
    if len(used) != len(mt) or float(np.max(np.abs(used - mt))) > 0.001:
        return CheckResult("audio_sync_review", Verdict.FAIL,
                           evidence_refs=[str(synced_wav)],
                           reason="校正锚点与现场帧 mtime 不一致（用错/过期曲线）")
    if not bool(np.all(np.diff(mt) > 0)):
        return CheckResult("audio_sync_review", Verdict.FAIL, reason="帧 mtime 非单调")
    w = max(1, int(fps))
    rate = (mt[w:] - mt[:-w]) / (w / fps)
    rmin, rmax = float(rate.min()), float(rate.max())
    if rmin < 0.3 or rmax > 3.0:
        return CheckResult("audio_sync_review", Verdict.FAIL,
                           reason=f"瞬时速率越界 [{rmin:.3f},{rmax:.3f}]，时钟损坏")
    target = len(mt) / fps
    dur = wav_duration(synced_wav)
    if abs(dur - target) > 0.1:
        return CheckResult("audio_sync_review", Verdict.FAIL,
                           reason=f"校正后音频 {dur:.3f}s != 帧时间轴 {target:.3f}s")
    span = mt[-1] - ref_zero_wall
    ref_ons = [t for t in onsets(ref_wav) if 0 <= t <= span]
    syn_ons = onsets(synced_wav)
    deltas = []
    for on in ref_ons:
        f_on = int(np.argmin(np.abs(mt - (ref_zero_wall + on))))
        exp = f_on / fps
        near = [s for s in syn_ons if abs(s - exp) <= 0.2]
        if near:
            deltas.append(min(near, key=lambda s: abs(s - exp)) - exp)
    if len(deltas) < 3:
        return CheckResult("audio_sync_review", Verdict.INCONCLUSIVE,
                           evidence_refs=[str(synced_wav)],
                           reason=f"静音->有声锚点仅 {len(deltas)}<3，查不了中段漂移")
    maxd = max(abs(d) for d in deltas)
    reason = (f"逐帧锚点 n={len(mt)} 速率[{rmin:.3f},{rmax:.3f}] "
              f"时长{dur:.2f}s=={target:.2f}s 声锚{len(deltas)}个 最大偏移={maxd * 1000:.0f}ms")
    if maxd > 0.05:
        return CheckResult("audio_sync_review", Verdict.FAIL,
                           evidence_refs=[str(synced_wav)], reason=reason + "；越 ±50ms")
    return CheckResult("audio_sync_review", Verdict.PASS,
                       evidence_refs=[str(synced_wav)], reason=reason)