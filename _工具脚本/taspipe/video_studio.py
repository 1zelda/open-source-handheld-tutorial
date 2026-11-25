# -*- coding: utf-8 -*-
"""成片视频精加工工作台（解决 showcase 原生切片「无字幕铭牌、无出招表显示、闪太快、无音轨」四大短板）。

为什么需要本模块：
原 `showcase.py` 调 `tas_replay.encode_video` 只是把 `f%04d.png` 裸压成无声 MP4 再简单拼接，
直接发 B站/抖音存在 4 个明显问题：
1. 观众不知道当前放的是哪一招、叫什么名字、属于第几个要素；
2. 观众看不到搓招指令谱面（如 `↓ ↙ ← ↙ ↓ ↘ → + C` 或 `↑ ↑ ↓ ↓ ← → ← → B A`）；
3. 必杀技/彩蛋触发瞬间往往只有十几帧（0.2 秒），一闪而过看不清细节；
4. Statejump 高速截图链路默认没有音轨（静音视频在内容平台完播率极低）。

本模块 (`taspipe.video_studio`) 对 `showcase_report.json` 产出的成片进行全自动工业级包装：
1. 动态绘制 HUD 招式铭牌 + 按键搓招谱面胶囊（使用 PIL 直接绘在每帧安全区或天马边框信息栏，不遮挡核心特效）；
2. 高光帧 0.5x 慢动作特写回放（自动围绕 `detection.frame` 前后窗口生成帧插倍慢放特写）；
3. 自动音轨混流与保底（支持混入实录原声 WAV、自定义 BGM 或自动生成复古街机提示音 + AAC 标准音轨，确保 100% 含有效音轨）。

保存位置：F:\\开源掌机教程\\_工具脚本\\taspipe\\video_studio.py
运行命令（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.video_studio polish --pack "taspipe/游戏包/megaman1_weapons.showcase.json" --showcase-dir "F:/taspipe_scratch/mm1_final/final"
  py -3 -u -m taspipe.video_studio render-hud-demo --out "F:/taspipe_scratch/hud_demo.mp4"
"""
import argparse
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent


def _load_font(size: int = 22):
    """优先加载 Windows 微软雅黑 / 黑体（支持中文与箭头符号 ↓↘→），回退默认字体。"""
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ]
    for fp in candidates:
        if os.path.isfile(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_hud_overlay_on_image(
    img: Image.Image,
    index: int,
    total: int,
    label: str,
    notation: str = "",
    kind: str = "weapon",
    is_slowmo: bool = False,
) -> Image.Image:
    """在单张游戏或边框画面顶部/底部安全区绘制半透明招式铭牌与搓招指令条。"""
    base = img.convert("RGBA")
    w, h = base.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    scale = max(1.0, min(w / 640.0, h / 360.0))
    font_title = _load_font(max(12, int(20 * scale)))
    font_sub = _load_font(max(10, int(15 * scale)))

    banner_h = max(28, int(44 * scale))
    draw.rectangle([0, 0, w, banner_h], fill=(12, 16, 28, 195))
    draw.line([(0, banner_h), (w, banner_h)], fill=(88, 168, 248, 230), width=max(1, int(2 * scale)))

    kind_badge = {
        "weapon": "武器 WEAPON",
        "move": "必杀 MOVE",
        "skill": "奥义 SKILL",
        "transform": "变身 FORM",
        "easter_egg": "彩蛋 SECRET",
    }.get(kind, "要素 ITEM")

    title_text = f"[{index:02d}/{total:02d}] {kind_badge} · {label}"
    if is_slowmo:
        title_text += "  [0.5x 慢动作特写]"

    draw.text((int(12 * scale), int(8 * scale)), title_text, font=font_title, fill=(255, 245, 210, 255))

    if notation:
        bot_h = max(24, int(36 * scale))
        y0 = h - bot_h
        draw.rectangle([0, y0, w, h], fill=(18, 22, 36, 185))
        cmd_str = f"指令 INPUT :  {notation}"
        draw.text((int(12 * scale), y0 + int(6 * scale)), cmd_str, font=font_sub, fill=(120, 232, 255, 255))

    return Image.alpha_composite(base, overlay).convert("RGB")


def generate_retro_chime_wav(wav_path: Path, duration_sec: float, freq_hz: float = 523.25, sample_rate: int = 44100):
    """当未开启 WASAPI 实录或无外部 BGM 时，生成带开头清脆街机提示音的合法 WAV 音轨。"""
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = max(1, int(duration_sec * sample_rate))
    chime_samples = min(n_samples, int(0.18 * sample_rate))

    buf = bytearray()
    for i in range(n_samples):
        if i < chime_samples:
            f = freq_hz if i < chime_samples // 2 else freq_hz * 1.25
            env = 1.0 - (i / chime_samples)
            val = int(6000 * env * math.sin(2.0 * math.pi * f * (i / sample_rate)))
        else:
            val = 0
        buf += struct.pack("<h", max(-32768, min(32767, val)))

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(buf))
    return wav_path


def polish_single_clip(
    raw_clip: Path,
    out_clip: Path,
    index: int,
    total: int,
    label: str,
    notation: str = "",
    kind: str = "weapon",
    peak_frame: int = 12,
    fps: float = 60.0,
    add_slowmo: bool = True,
    bgm_wav: Path = None,
    ffmpeg: str = "ffmpeg",
) -> dict:
    """对单个要素 MP4 片段执行：抽帧 -> 绘制 HUD 铭牌与搓招指令 -> 可选拼接高光 0.5x 慢动作 -> 混流音轨。"""
    with tempfile.TemporaryDirectory(prefix="tas_studio_") as tmp:
        tmp_dir = Path(tmp)
        raw_frames_dir = tmp_dir / "raw"
        out_frames_dir = tmp_dir / "out"
        raw_frames_dir.mkdir()
        out_frames_dir.mkdir()

        subprocess.run([
            ffmpeg, "-v", "error", "-y", "-i", str(raw_clip),
            "-start_number", "0", str(raw_frames_dir / "f%04d.png")
        ], check=True)

        src_files = sorted(raw_frames_dir.glob("f*.png"))
        if not src_files:
            raise RuntimeError(f"未能从 {raw_clip} 解出帧")

        out_idx = 0
        for sf in src_files:
            im = Image.open(sf)
            decorated = draw_hud_overlay_on_image(im, index, total, label, notation=notation, kind=kind, is_slowmo=False)
            decorated.save(out_frames_dir / f"f{out_idx:04d}.png")
            out_idx += 1

        if add_slowmo and len(src_files) >= 8:
            p_center = min(max(0, int(peak_frame)), len(src_files) - 1)
            w_start = max(0, p_center - 10)
            w_end = min(len(src_files), p_center + 14)
            for sf in src_files[w_start:w_end]:
                im = Image.open(sf)
                decorated = draw_hud_overlay_on_image(im, index, total, label, notation=notation, kind=kind, is_slowmo=True)
                for _ in range(2):
                    decorated.save(out_frames_dir / f"f{out_idx:04d}.png")
                    out_idx += 1

        silent_mp4 = tmp_dir / "video_only.mp4"
        subprocess.run([
            ffmpeg, "-v", "error", "-y", "-framerate", str(fps),
            "-i", str(out_frames_dir / "f%04d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            str(silent_mp4)
        ], check=True)

        duration_sec = out_idx / float(fps)
        wav_to_use = bgm_wav if (bgm_wav and Path(bgm_wav).is_file()) else generate_retro_chime_wav(tmp_dir / "chime.wav", duration_sec)

        out_clip.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            ffmpeg, "-v", "error", "-y",
            "-i", str(silent_mp4), "-i", str(wav_to_use),
            "-c:v", "copy", "-af", "apad", "-c:a", "aac", "-shortest",
            str(out_clip)
        ], check=True)

    return {"clip": str(out_clip), "frames": out_idx, "duration_sec": round(duration_sec, 3)}


def polish_showcase_production(
    pack_path: Path,
    showcase_dir: Path,
    add_slowmo: bool = True,
    bgm_wav: Path = None,
    ffmpeg: str = "ffmpeg",
) -> dict:
    """读取知识包与 showcase 产出目录，将所有要素片段升级为『带招式铭牌 + 搓招指令 + 慢动作特写 + 音轨』的精装合辑 reel_studio.mp4。"""
    doc = json.loads(pack_path.read_text(encoding="utf-8"))
    fps = float(doc.get("fps", 60.0))
    elements = doc.get("elements", [])
    total = len(elements)

    clips_dir = showcase_dir / "clips"
    studio_dir = showcase_dir / "studio_clips"
    studio_dir.mkdir(parents=True, exist_ok=True)

    polished_clips = []
    details = []
    for idx, el in enumerate(elements, 1):
        eid = el["element_id"]
        bordered = clips_dir / f"{eid}_bordered.mp4"
        raw = bordered if bordered.is_file() else (clips_dir / f"{eid}.mp4")
        if not raw.is_file():
            continue

        trig = el.get("trigger") or {}
        notation = trig.get("notation") or trig.get("macro", "")[:36]
        peak = (el.get("detection") or {}).get("frame", 12)
        out_c = studio_dir / f"{idx:02d}_{eid}_studio.mp4"

        info = polish_single_clip(
            raw_clip=raw,
            out_clip=out_c,
            index=idx,
            total=total,
            label=el.get("label", eid),
            notation=notation,
            kind=el.get("kind", "weapon"),
            peak_frame=peak,
            fps=fps,
            add_slowmo=add_slowmo,
            bgm_wav=bgm_wav,
            ffmpeg=ffmpeg,
        )
        polished_clips.append(str(out_c))
        details.append({"element_id": eid, **info})

    reel_studio = showcase_dir / "reel_studio.mp4"
    if polished_clips:
        concat_txt = studio_dir / "studio.concat.txt"
        concat_txt.write_text(
            "".join("file '" + str(Path(p).resolve()).replace("\\", "/") + "'\n" for p in polished_clips),
            encoding="utf-8",
        )
        subprocess.run([
            ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_txt), "-c", "copy", str(reel_studio)
        ], check=True)

    rep = {
        "status": "done" if polished_clips else "empty",
        "game_id": doc.get("game_id"),
        "polished_count": len(polished_clips),
        "reel_studio_mp4": str(reel_studio) if polished_clips else None,
        "clips": details,
    }
    (showcase_dir / "studio_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return rep


def render_hud_demo(out_mp4: Path, fps: float = 60.0):
    """不依赖模拟器，直接生成一段 2 秒的『带招式铭牌 + 搓招指令条 + 0.5x慢动作 + 复古提示音』验证样片。"""
    out_mp4 = out_mp4.resolve()
    with tempfile.TemporaryDirectory(prefix="tas_hud_demo_") as tmp:
        raw_mp4 = Path(tmp) / "raw.mp4"
        fdir = Path(tmp) / "f"
        fdir.mkdir()
        for i in range(40):
            im = Image.new("RGB", (640, 480), (24, 28, 44))
            dr = ImageDraw.Draw(im)
            x_pos = 120 + i * 10
            dr.ellipse([x_pos, 200, x_pos + 64, 264], fill=(248, 136, 48), outline=(255, 240, 180), width=3)
            im.save(fdir / f"f{i:04d}.png")
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-framerate", str(fps),
            "-i", str(fdir / "f%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(raw_mp4)
        ], check=True)

        res = polish_single_clip(
            raw_clip=raw_mp4,
            out_clip=out_mp4,
            index=1,
            total=8,
            label="里百八式·大蛇薙 (Ura 108 Shiki: Orochinagi)",
            notation="↓ ↙ ← ↙ ↓ ↘ → + C",
            kind="skill",
            peak_frame=20,
            fps=fps,
            add_slowmo=True,
        )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pol = sub.add_parser("polish", help="将 showcase 产出目录升级为带铭牌/搓招表/慢放/音轨的精装合辑")
    p_pol.add_argument("--pack", required=True)
    p_pol.add_argument("--showcase-dir", required=True)
    p_pol.add_argument("--no-slowmo", action="store_true")
    p_pol.add_argument("--bgm", default=None, help="可选背景音乐 WAV/MP3 路径")

    p_demo = sub.add_parser("render-hud-demo", help="生成一段独立验证 HUD 铭牌+指令条+慢放+音轨的样片")
    p_demo.add_argument("--out", required=True)

    args = ap.parse_args()
    if args.cmd == "polish":
        polish_showcase_production(
            Path(args.pack),
            Path(args.showcase_dir),
            add_slowmo=not args.no_slowmo,
            bgm_wav=Path(args.bgm) if args.bgm else None,
        )
    elif args.cmd == "render-hud-demo":
        render_hud_demo(Path(args.out))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
