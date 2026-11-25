# -*- coding: utf-8 -*-
"""M4：受控检测插件（依据 _scratch/强模型方案回复.md §4.4 / B4）。

CheckSpec.plugin_id 只能命中这里注册的插件；不执行来自网页/模型输出的任意代码。
每个插件返回 (Verdict, reason)；证据不足 => INCONCLUSIVE，不是通过。
检测器只判"要素是否出现"，不兼任最终成片验收（那是 M6）。
"""
from pathlib import Path

import numpy as np
from PIL import Image

from .schema import CheckSpec, CheckResult, Verdict, SchemaError

PLUGINS = {}


def register(pid):
    def deco(fn):
        PLUGINS[pid] = fn
        return fn
    return deco


def _arr(frame_path):
    return np.asarray(Image.open(frame_path).convert("RGB"), dtype=np.int32)


@register("frame_color_fraction")
def _color_fraction(params, frame_path):
    """目标颜色像素占比 >= min_fraction => pass。用于区分场景（如天空蓝=游戏中）。"""
    rgb = params.get("rgb")
    tol = int(params.get("tol", 12))
    minf = float(params.get("min_fraction", 0.3))
    if not rgb or len(rgb) != 3:
        return Verdict.INCONCLUSIVE, "params.rgb 缺失/非法"
    a = _arr(frame_path)
    diff = np.abs(a - np.asarray(rgb, dtype=np.int32)).max(axis=2)
    frac = float((diff <= tol).mean())
    ok = frac >= minf
    return (Verdict.PASS if ok else Verdict.FAIL), \
        f"color{tuple(rgb)}±{tol} fraction={frac:.3f} (min={minf})"


@register("frame_luma_range")
def _luma_range(params, frame_path):
    """平均亮度在 [min,max] => pass。用于拒黑帧/白帧（错误起点）。"""
    lo = float(params.get("min", 0))
    hi = float(params.get("max", 255))
    a = _arr(frame_path)
    luma = float((0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]).mean())
    ok = lo <= luma <= hi
    return (Verdict.PASS if ok else Verdict.FAIL), \
        f"mean_luma={luma:.1f} range=[{lo},{hi}]"


@register("frame_region_color_fraction")
def _region_color_fraction(params, frame_path):
    """归一化子矩形内目标颜色占比 >= min_fraction => pass（M9 新类别小插件）。

    region=[x0,y0,x1,y1]（0..1 归一化，尺度无关）；省略则整帧。用于把检测限定到
    HUD 血条等局部区域（如 KOF98 顶部绿血条）， game-specific 的参数落在游戏包里，
    插件本身通用。region 非法/像素为空 => inconclusive，不静默通过。
    """
    rgb = params.get("rgb")
    tol = int(params.get("tol", 12))
    minf = float(params.get("min_fraction", 0.3))
    region = params.get("region")
    if not rgb or len(rgb) != 3:
        return Verdict.INCONCLUSIVE, "params.rgb 缺失/非法"
    a = _arr(frame_path)
    h, w = a.shape[:2]
    if region is not None:
        if len(region) != 4:
            return Verdict.INCONCLUSIVE, "region 须为 [x0,y0,x1,y1]"
        x0, y0, x1, y1 = region
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            return Verdict.INCONCLUSIVE, f"region 越界 {region}"
        sub = a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    else:
        sub = a
    if sub.size == 0:
        return Verdict.INCONCLUSIVE, "region 像素为空"
    diff = np.abs(sub - np.asarray(rgb, dtype=np.int32)).max(axis=2)
    frac = float((diff <= tol).mean())
    ok = frac >= minf
    return (Verdict.PASS if ok else Verdict.FAIL), \
        f"region={region} color{tuple(rgb)}±{tol} fraction={frac:.3f} (min={minf})"


@register("frame_region_color_fraction_max")
def _region_color_fraction_max(params, frame_path):
    """归一化子矩形内目标颜色占比 <= max_fraction => pass（上限型判据）。

    下限判据只能证明「这个特征出现了」；当弹幕互相包含（激光光束里也有白色弹头像素）
    时，单靠下限说明不了「这一格是它而不是别的枪」。上限判据把「不该出现的特征确实没
    出现」也变成可复核证据，和下限配对才构成互斥判据。region 必填，缺参数 => inconclusive。
    """
    rgb = params.get("rgb")
    tol = int(params.get("tol", 12))
    maxf = params.get("max_fraction")
    region = params.get("region")
    if not rgb or len(rgb) != 3:
        return Verdict.INCONCLUSIVE, "params.rgb 缺失/非法"
    if maxf is None:
        return Verdict.INCONCLUSIVE, "params.max_fraction 缺失"
    if not region or len(region) != 4:
        return Verdict.INCONCLUSIVE, "上限判据必须给 region=[x0,y0,x1,y1]"
    maxf = float(maxf)
    x0, y0, x1, y1 = region
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return Verdict.INCONCLUSIVE, f"region 越界 {region}"
    a = _arr(frame_path)
    h, w = a.shape[:2]
    sub = a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    if sub.size == 0:
        return Verdict.INCONCLUSIVE, "region 像素为空"
    diff = np.abs(sub - np.asarray(rgb, dtype=np.int32)).max(axis=2)
    frac = float((diff <= tol).mean())
    ok = frac <= maxf
    return (Verdict.PASS if ok else Verdict.FAIL), \
        f"region={region} color{tuple(rgb)}±{tol} fraction={frac:.4f} (max={maxf})"


@register("frame_region_color_fraction_range")
def _region_color_fraction_range(params, frame_path):
    """归一化子矩形内目标颜色占比落在 [min_fraction, max_fraction] => pass。

    「弹幕密度落在某个窗口」本身就是要区分的东西：机枪的暖色弹头占比既不能是 0（那
    是步枪，纯白弹头），也不能高到激光/散弹的量级。拆成两条同区域判据会把同一块像素
    量两遍，所以合成一个区间判据。两个边界都必填，缺任一 => inconclusive。
    """
    rgb = params.get("rgb")
    tol = int(params.get("tol", 12))
    minf, maxf = params.get("min_fraction"), params.get("max_fraction")
    region = params.get("region")
    if not rgb or len(rgb) != 3:
        return Verdict.INCONCLUSIVE, "params.rgb 缺失/非法"
    if minf is None or maxf is None:
        return Verdict.INCONCLUSIVE, "区间判据必须同时给 min_fraction 与 max_fraction"
    if not region or len(region) != 4:
        return Verdict.INCONCLUSIVE, "区间判据必须给 region=[x0,y0,x1,y1]"
    minf, maxf = float(minf), float(maxf)
    if minf > maxf:
        return Verdict.INCONCLUSIVE, f"min_fraction {minf} > max_fraction {maxf}"
    x0, y0, x1, y1 = region
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return Verdict.INCONCLUSIVE, f"region 越界 {region}"
    a = _arr(frame_path)
    h, w = a.shape[:2]
    sub = a[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    if sub.size == 0:
        return Verdict.INCONCLUSIVE, "region 像素为空"
    diff = np.abs(sub - np.asarray(rgb, dtype=np.int32)).max(axis=2)
    frac = float((diff <= tol).mean())
    ok = minf <= frac <= maxf
    return (Verdict.PASS if ok else Verdict.FAIL), \
        f"region={region} color{tuple(rgb)}±{tol} fraction={frac:.4f} range=[{minf},{maxf}]"


def _pixel_box(region, w, h):
    if not isinstance(region, (list, tuple)) or len(region) != 4:
        raise ValueError("region 须为 [x0,y0,x1,y1]")
    x0, y0, x1, y1 = region
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError(f"region 越界 {region}")
    box = int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("region 像素为空")
    return box


def _shifted_overlap(current, reference, dx, dy):
    h, w = current.shape[:2]
    x0, x1 = max(0, dx), min(w, w + dx)
    y0, y1 = max(0, dy), min(h, h + dy)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("平移后没有重叠区域")
    return (current[y0:y1, x0:x1],
            reference[y0 - dy:y1 - dy, x0 - dx:x1 - dx],
            (x0, y0, x1, y1))


def aligned_difference_metrics(current, reference, region, alignment_region,
                               max_shift=0, max_dy=0, diff_threshold=42):
    """估计背景平移后在局部区域比较两帧；返回对齐平移、局部/全局变化分数。"""
    if current.shape != reference.shape:
        raise ValueError("两帧尺寸不同")
    h, w = current.shape[:2]
    rx0, ry0, rx1, ry1 = _pixel_box(region, w, h)
    ax0, ay0, ax1, ay1 = _pixel_box(alignment_region, w, h)
    best = None
    for dy in range(-max_dy, max_dy + 1):
        for dx in range(-max_shift, max_shift + 1):
            try:
                shifted, ref, box = _shifted_overlap(current, reference, dx, dy)
            except ValueError:
                continue
            x0, y0, x1, y1 = box
            ly0, ly1 = max(y0, ay0), min(y1, ay1)
            lx0, lx1 = max(x0, ax0), min(x1, ax1)
            if ly1 <= ly0 or lx1 <= lx0:
                continue
            sub_a = shifted[ly0 - y0:ly1 - y0, lx0 - x0:lx1 - x0]
            sub_b = ref[ly0 - y0:ly1 - y0, lx0 - x0:lx1 - x0]
            delta = np.abs(sub_a - sub_b)
            key = (float(delta.mean()), float((delta.sum(2) > diff_threshold).mean()),
                   abs(dx) + abs(dy))
            if best is None or key < best[0]:
                best = (key, dx, dy)
    if best is None:
        raise ValueError("对齐区域在搜索平移内没有有效重叠")
    _, dx, dy = best
    shifted, ref, box = _shifted_overlap(current, reference, dx, dy)
    x0, y0, x1, y1 = box
    lx0, ly0, lx1, ly1 = max(x0, rx0), max(y0, ry0), min(x1, rx1), min(y1, ry1)
    if lx1 <= lx0 or ly1 <= ly0:
        raise ValueError("局部区域在对齐后没有有效重叠")
    local_delta = np.abs(shifted[ly0 - y0:ly1 - y0, lx0 - x0:lx1 - x0]
                         - ref[ly0 - y0:ly1 - y0, lx0 - x0:lx1 - x0]).sum(2)
    global_delta = np.abs(shifted - ref).sum(2)
    return {
        "dx": dx,
        "dy": dy,
        "alignment_mae": best[0][0],
        "local_changed_fraction": float((local_delta > diff_threshold).mean()),
        "global_changed_fraction": float((global_delta > diff_threshold).mean()),
        "local_pixels": int(local_delta.size),
        "overlap_pixels": int(global_delta.size),
    }


@register("frame_pair_aligned_region_difference")
def _pair_aligned_region_difference(params, frame_path):
    """与参考帧对齐后，局部差分须过下限且全局差分不得越过闪白上限。"""
    reference = params.get("reference_frame")
    if not isinstance(reference, str) or not Path(reference).is_file():
        return Verdict.INCONCLUSIVE, "params.reference_frame 缺失/不存在"
    try:
        current = _arr(frame_path)
        ref = _arr(reference)
        metrics = aligned_difference_metrics(
            current, ref,
            region=params["region"],
            alignment_region=params.get("alignment_region", [0.0, 0.125, 1.0, 0.4875]),
            max_shift=int(params.get("max_shift", 0)),
            max_dy=int(params.get("max_dy", 0)),
            diff_threshold=int(params.get("diff_threshold", 42)),
        )
        minf = float(params["min_changed_fraction"])
        maxg = float(params.get("max_global_changed_fraction", 0.25))
        if not (0 <= minf <= 1 and 0 <= maxg <= 1):
            raise ValueError("min/max fraction 须落在 0..1")
        if not (0 <= int(params.get("max_shift", 0)) <= 64
                and 0 <= int(params.get("max_dy", 0)) <= 16):
            raise ValueError("max_shift/max_dy 越界")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return Verdict.INCONCLUSIVE, f"对齐差分参数/帧非法: {exc}"
    ok = (metrics["local_changed_fraction"] >= minf
          and metrics["global_changed_fraction"] <= maxg)
    return (Verdict.PASS if ok else Verdict.FAIL), (
        f"alignment=({metrics['dx']},{metrics['dy']}) "
        f"local_fraction={metrics['local_changed_fraction']:.4f} (min={minf}) "
        f"global_fraction={metrics['global_changed_fraction']:.4f} (max={maxg})"
    )


def run_check(spec, frame_path):
    """跑一个 CheckSpec 对单帧。未知插件 => INCONCLUSIVE（受控 registry，不静默通过）。"""
    if not isinstance(spec, CheckSpec):
        spec = CheckSpec(**spec)
    spec.validate()
    fn = PLUGINS.get(spec.plugin_id)
    if fn is None:
        return CheckResult(spec.check_id, Verdict.INCONCLUSIVE,
                           evidence_refs=[str(frame_path)],
                           reason=f"未注册插件 {spec.plugin_id}")
    try:
        verdict, reason = fn(spec.params, frame_path)
    except Exception as e:
        return CheckResult(spec.check_id, Verdict.INCONCLUSIVE,
                           evidence_refs=[str(frame_path)],
                           reason=f"插件异常 {type(e).__name__}: {e}")
    return CheckResult(spec.check_id, verdict,
                       evidence_refs=[str(frame_path)], reason=reason)


# ---------------------------------------------------- 数值观察插件（M7 搜索判分）
#
# 搜索格斗单招时，观察量不是帧色而是 HUD 量到的数（对手掉血、气点）。同样走受控
# registry：plugin_id 只能命中这里注册的；缺字段/未注册 => inconclusive，不静默通过。
METRIC_PLUGINS = {}


def register_metric(pid):
    def deco(fn):
        METRIC_PLUGINS[pid] = fn
        return fn
    return deco


@register_metric("metric_min")
def _metric_min(params, metrics):
    """metrics[key] >= min => pass。用于'对手掉血>0=打中'这类搜索判分。"""
    key = params.get("key")
    lo = params.get("min")
    if key is None or lo is None:
        return Verdict.INCONCLUSIVE, "params.key/min 缺失"
    if key not in metrics or metrics[key] is None:
        return Verdict.INCONCLUSIVE, f"观察量缺 {key}（证据不足）"
    val = float(metrics[key])
    ok = val >= float(lo)
    return (Verdict.PASS if ok else Verdict.FAIL), f"{key}={val} (min={lo})"


@register_metric("metric_max")
def _metric_max(params, metrics):
    """metrics[key] <= max => pass。"""
    key = params.get("key")
    hi = params.get("max")
    if key is None or hi is None:
        return Verdict.INCONCLUSIVE, "params.key/max 缺失"
    if key not in metrics or metrics[key] is None:
        return Verdict.INCONCLUSIVE, f"观察量缺 {key}（证据不足）"
    val = float(metrics[key])
    ok = val <= float(hi)
    return (Verdict.PASS if ok else Verdict.FAIL), f"{key}={val} (max={hi})"


def run_metric_check(spec, metrics):
    """跑一个 CheckSpec 对数值观察。未注册插件 => inconclusive（受控，不静默通过）。"""
    if not isinstance(spec, CheckSpec):
        spec = CheckSpec(**spec)
    spec.validate()
    fn = METRIC_PLUGINS.get(spec.plugin_id)
    if fn is None:
        return CheckResult(spec.check_id, Verdict.INCONCLUSIVE,
                           reason=f"未注册数值插件 {spec.plugin_id}")
    try:
        verdict, reason = fn(spec.params, metrics or {})
    except Exception as e:
        return CheckResult(spec.check_id, Verdict.INCONCLUSIVE,
                           reason=f"数值插件异常 {type(e).__name__}: {e}")
    return CheckResult(spec.check_id, verdict, reason=reason)