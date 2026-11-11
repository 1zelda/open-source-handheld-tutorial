# -*- coding: utf-8 -*-
"""Exporter：成品合成 —— 按可复用「视频模板」给游戏画面套边框。

默认模板 fc_tianma_cover（04-游戏资源库/TAS输入录像库/视频模板/fc_tianma_cover.json）：
  * 背景 = 该游戏 boxFront 封面放大铺满 + 高斯模糊 + 压暗（每款游戏自带主题底色）；
  * 左侧 = 游戏画面整数倍放大（flags=neighbor 保像素锐利），外描一圈浅色细框；
  * 右侧 = 干净的 boxFront 立绘 + 下方 logo 横幅（天马封面观感）。
无封面时退路：纯深色底 + 居中整数倍画面（不臆造封面），并如实标注 fallback。
模板 JSON 固化画幅/配色/模糊/布局比例，改模板即可换风格而不动代码；预览图见同目录 .preview.png。

画面整数倍放大后用 ffmpeg overlay 贴到静态 bezel 上，音轨从原片 -c:a copy 原样保留
（不重编码、不破坏 M5 已校正的音画同步）。输出帧数/时长与原片一致才算合成通过。

运行: python -m taspipe.exporter compose --in <gameplay.mp4> --out <bordered.mp4> \
        --sha1 <ROM sha1> [--template fc_tianma_cover] [--covers <covers根目录>]
"""
import argparse
import glob
import json
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

from .schema import CheckResult, Verdict, Stage, asset
from .backends import _verification, _write_json, _run_id

DEFAULT_TEMPLATE = "fc_tianma_cover"


def template_dir():
    from . import registry as R
    return os.path.join(str(R.DEFAULT_LIB), "视频模板")


def load_template(name=DEFAULT_TEMPLATE):
    p = os.path.join(template_dir(), name + ".json")
    if not os.path.isfile(p):
        raise SystemExit(f"视频模板不存在: {p}（可用: "
                         f"{[os.path.basename(x)[:-5] for x in glob.glob(os.path.join(template_dir(), '*.json'))]}）")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def find_cover(rom_sha1=None, slug=None, covers_root=None):
    """按 ROM sha1（优先）或目录 slug 在 covers/*/cover.json 里找对应封面。找不到返回 None。"""
    from . import registry as R
    covers_root = covers_root or os.path.join(str(R.DEFAULT_LIB), "covers")
    want = (rom_sha1 or "").upper()
    for cj in sorted(glob.glob(os.path.join(covers_root, "*", "cover.json"))):
        try:
            with open(cj, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            continue
        hit = (want and (d.get("rom_sha1", "").upper() == want)) or \
              (slug and os.path.basename(os.path.dirname(cj)) == slug)
        if hit:
            d["_dir"] = os.path.dirname(cj)
            return d
    return None


def _fit(img, max_w, max_h):
    """等比缩放到不超过 max_w x max_h。返回新图。"""
    w, h = img.size
    r = min(max_w / w, max_h / h)
    return img.resize((max(1, int(w * r)), max(1, int(h * r))), Image.LANCZOS)


def _mask_path(tpl):
    from . import registry as R
    return os.path.join(str(R.DEFAULT_LIB), "masks", tpl["mask"])


def _build_mask_bezel(gw, gh, out_png, tpl):
    """环绕遮罩模式：量遮罩透明屏洞，画面整数倍居中贴洞；返回 layout。"""
    mp = _mask_path(tpl)
    if not os.path.isfile(mp):
        raise SystemExit(f"遮罩不存在: {mp}（放在 registry.DEFAULT_LIB/masks 下）")
    mask = Image.open(mp).convert("RGBA")
    cw, ch = mask.size
    hole = mask.getchannel("A").point(lambda v: 255 if v == 0 else 0).getbbox()
    if not hole:
        raise SystemExit(f"遮罩没有透明屏洞（alpha 全不透明）: {mp}")
    hx0, hy0, hx1, hy1 = hole
    hw, hh = hx1 - hx0, hy1 - hy0
    scale = max(1, min(hw // gw, hh // gh))
    sw, sh = gw * scale, gh * scale
    gx = hx0 + (hw - sw) // 2
    gy = hy0 + (hh - sh) // 2
    base = Image.new("RGBA", (cw, ch), tuple(tpl["fallback_bg"]) + (255,))
    base.alpha_composite(mask)
    base.convert("RGB").save(out_png)
    return {"template": tpl.get("name"), "mode": "mask", "mask": tpl["mask"],
            "scale": scale, "gameplay_scaled": [sw, sh], "overlay_xy": [gx, gy],
            "canvas": [cw, ch], "hole": [hx0, hy0, hx1, hy1], "cover_found": False}


def build_bezel(cover, gw, gh, out_png, tpl):
    """按模板生成静态边框底图，返回 layout（画面放大倍数与贴图坐标）。"""
    if tpl.get("mode") == "mask":
        return _build_mask_bezel(gw, gh, out_png, tpl)
    cw, ch = tpl["canvas"]
    gp, pn = tpl["gameplay"], tpl["panel"]
    accent = tuple(tpl["accent"])
    scale = max(1, min(int(cw * gp["max_w_frac"]) // gw, int(ch * gp["max_h_frac"]) // gh))
    sw, sh = gw * scale, gh * scale
    gx = gp["margin_x"]
    gy = (ch - sh) // 2
    layout = {"template": tpl.get("name"), "scale": scale, "gameplay_scaled": [sw, sh],
              "overlay_xy": [gx, gy], "canvas": [cw, ch], "cover_found": bool(cover)}

    if cover and os.path.isfile(cover.get("boxFront", "")):
        box = Image.open(cover["boxFront"]).convert("RGBA")
        bg = box.convert("RGB").resize((cw, ch), Image.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(tpl["bg_blur"]))
        bg = ImageEnhance.Brightness(bg).enhance(tpl["bg_brightness"])
        bez = bg.convert("RGBA")
        panel_x0 = gx + sw + pn["gap"]
        panel_x1 = cw - pn["margin_right"]
        panel_w = max(120, panel_x1 - panel_x0)
        box_fit = _fit(box, panel_w - pn["pad"], int(ch * pn["box_max_h_frac"]))
        bx = panel_x0 + (panel_w - box_fit.width) // 2
        by = pn["box_top"]
        bez.alpha_composite(box_fit, (bx, by))
        layout["box_xy"] = [bx, by]
        layout["box_size"] = list(box_fit.size)
        logo_p = cover.get("logo", "")
        if logo_p and os.path.isfile(logo_p):
            logo = Image.open(logo_p).convert("RGBA")
            logo_fit = _fit(logo, panel_w - pn["pad"],
                            ch - (by + box_fit.height) - pn["logo_bottom_reserve"])
            lx = panel_x0 + (panel_w - logo_fit.width) // 2
            ly = by + box_fit.height + pn["logo_gap"]
            bez.alpha_composite(logo_fit, (lx, ly))
            layout["logo_xy"] = [lx, ly]
            layout["logo_size"] = list(logo_fit.size)
        bez = bez.convert("RGB")
        dr = ImageDraw.Draw(bez)
        b = gp["border"]
        dr.rectangle([gx - b, gy - b, gx + sw + b, gy + sh + b], outline=accent, width=b)
        pb = pn["border"]
        dr.rectangle([bx - pb, by - pb, bx + box_fit.width + pb, by + box_fit.height + pb],
                     outline=accent, width=pb)
    else:
        bez = Image.new("RGB", (cw, ch), tuple(tpl["fallback_bg"]))
        gx = (cw - sw) // 2
        layout["overlay_xy"] = [gx, gy]
        layout["cover_found"] = False
        dr = ImageDraw.Draw(bez)
        b = gp["border"]
        dr.rectangle([gx - b, gy - b, gx + sw + b, gy + sh + b], outline=accent, width=b)
    bez.save(out_png)
    return layout


def _probe(path, ffprobe):
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                        "stream=codec_type,width,height,nb_frames,avg_frame_rate:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return json.loads(r.stdout or "{}") if r.returncode == 0 else {}


def compose(gameplay, out_mp4, rom_sha1=None, slug=None, covers_root=None,
            template=DEFAULT_TEMPLATE, ffmpeg="ffmpeg", ffprobe="ffprobe",
            bezel_png=None):
    """按模板给 gameplay.mp4 套对应游戏封面边框 -> out_mp4。返回 run dict（含合成验收）。"""
    gameplay = str(gameplay)
    out_mp4 = str(out_mp4)
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
    rid = _run_id()
    tpl = load_template(template)
    d = _probe(gameplay, ffprobe)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    has_audio = any(s.get("codec_type") == "audio" for s in d.get("streams", []))
    gw, gh = int(v.get("width") or 256), int(v.get("height") or 224)
    in_nb = int(v.get("nb_frames") or 0)
    in_dur = float(d.get("format", {}).get("duration") or 0)
    afr = v.get("avg_frame_rate") or "60/1"
    try:
        num, den = afr.split("/")
        fps = float(num) / float(den) if float(den) else 60.0
    except Exception:
        fps = 60.0

    mode = tpl.get("mode", "cover")
    cover = None if mode == "mask" else find_cover(rom_sha1, slug, covers_root)
    bezel_png = bezel_png or os.path.join(os.path.dirname(os.path.abspath(out_mp4)),
                                          f"{rid}_bezel.png")
    layout = build_bezel(cover, gw, gh, bezel_png, tpl)
    sw, sh = layout["gameplay_scaled"]
    gx, gy = layout["overlay_xy"]

    # 背景图按原片帧率循环喂入，overlay shortest=1 在原片结束处停；
    # -fps_mode passthrough 不做重采样（-r 会在循环边界丢几帧）。音轨原样 copy。
    if mode == "mask":
        # 遮罩压在画面之上：纯色底→画面→遮罩(alpha)，圆角/扫描线才能盖住画面。
        cw, ch = layout["canvas"]
        r, g, b = tpl["fallback_bg"]
        vf = (f"[1:v]scale={sw}:{sh}:flags=neighbor[fg];"
              f"[0:v][fg]overlay={gx}:{gy}:shortest=1[mid];"
              f"[mid][2:v]overlay=0:0:shortest=1[v]")
        cmd = [ffmpeg, "-y", "-f", "lavfi", "-i",
               f"color=c=0x{r:02x}{g:02x}{b:02x}:s={cw}x{ch}:r={fps:.6f}",
               "-i", gameplay, "-loop", "1", "-framerate", f"{fps:.6f}",
               "-i", _mask_path(tpl), "-filter_complex", vf, "-map", "[v]"]
    else:
        vf = (f"[1:v]scale={sw}:{sh}:flags=neighbor[fg];"
              f"[0:v][fg]overlay={gx}:{gy}:shortest=1[v]")
        cmd = [ffmpeg, "-y", "-loop", "1", "-framerate", f"{fps:.6f}", "-i", bezel_png,
               "-i", gameplay, "-filter_complex", vf, "-map", "[v]"]
    if has_audio:
        cmd += ["-map", "1:a", "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
            "-fps_mode", "passthrough", out_mp4]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = proc.returncode == 0 and os.path.isfile(out_mp4) and os.path.getsize(out_mp4) > 0

    if mode == "mask":
        first = CheckResult("mask_hole", Verdict.PASS, evidence_refs=[bezel_png],
                            reason=f"遮罩={tpl['mask']} 屏洞={layout['hole']} "
                                   f"画面整数倍 x{layout['scale']} 居中贴洞，遮罩压画面之上")
    else:
        first = CheckResult("cover_matched",
                            Verdict.PASS if cover else Verdict.INCONCLUSIVE,
                            evidence_refs=[bezel_png],
                            reason=(f"sha1={rom_sha1} 命中封面《{cover.get('game')}》" if cover else
                                    f"未找到 sha1={rom_sha1}/slug={slug} 的封面，退路=纯深色底居中（不臆造封面）"))
    checks = [
        first,
        CheckResult("bezel_composed", Verdict.PASS if ok else Verdict.FAIL,
                    evidence_refs=[out_mp4] if ok else [],
                    reason=f"模板={tpl.get('name')} canvas={layout['canvas']} "
                           f"画面整数倍 x{layout['scale']}={sw}x{sh} @({gx},{gy})"
                           + ("" if ok else f" | ffmpeg rc={proc.returncode}: {(proc.stderr or '')[-300:]}")),
    ]
    out_nb, out_dur = 0, 0.0
    if ok:
        od = _probe(out_mp4, ffprobe)
        ov = next((s for s in od.get("streams", []) if s.get("codec_type") == "video"), {})
        out_nb = int(ov.get("nb_frames") or 0)
        out_dur = float(od.get("format", {}).get("duration") or 0)
        checks.append(CheckResult("frames_preserved",
                                  Verdict.PASS if (in_nb and out_nb == in_nb) else Verdict.INCONCLUSIVE,
                                  evidence_refs=[out_mp4],
                                  reason=f"成片 {out_nb} 帧 vs 原片 {in_nb} 帧"))
        checks.append(CheckResult("duration_preserved",
                                  Verdict.PASS if abs(out_dur - in_dur) < 0.5 else Verdict.INCONCLUSIVE,
                                  reason=f"成片 {out_dur:.2f}s vs 原片 {in_dur:.2f}s"))
        checks.append(CheckResult("audio_preserved",
                                  Verdict.PASS if (has_audio and any(
                                      s.get("codec_type") == "audio" for s in od.get("streams", [])))
                                  else Verdict.INCONCLUSIVE,
                                  reason="音轨 -c:a copy 原样保留" if has_audio else "原片无音轨"))
    ver = _verification("ver_" + rid, rid, Stage.EXPORT, checks)
    run = {"schema_version": 1, "run_id": rid, "purpose": "bezel_export",
           "input_ref": gameplay, "template": tpl.get("name"), "cover": cover, "layout": layout,
           "recording_refs": [asset(out_mp4), asset(bezel_png)] if ok else [],
           "verification": ver}
    _write_json(os.path.join(os.path.dirname(os.path.abspath(out_mp4)), f"{rid}.export.json"), run)
    return run


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["compose"])
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sha1", default=None)
    ap.add_argument("--slug", default=None)
    ap.add_argument("--covers", default=None)
    ap.add_argument("--template", default=DEFAULT_TEMPLATE)
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--ffprobe", default="ffprobe")
    args = ap.parse_args()
    run = compose(args.inp, args.out, rom_sha1=args.sha1, slug=args.slug,
                  covers_root=args.covers, template=args.template,
                  ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    print(json.dumps(run, ensure_ascii=False, indent=1))
    return 0 if run["verification"]["verdict"] != "fail" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())