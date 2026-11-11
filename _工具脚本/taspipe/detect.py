# -*- coding: utf-8 -*-
"""M4：受控检测插件（依据 _scratch/强模型方案回复.md §4.4 / B4）。

CheckSpec.plugin_id 只能命中这里注册的插件；不执行来自网页/模型输出的任意代码。
每个插件返回 (Verdict, reason)；证据不足 => INCONCLUSIVE，不是通过。
检测器只判"要素是否出现"，不兼任最终成片验收（那是 M6）。
"""
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