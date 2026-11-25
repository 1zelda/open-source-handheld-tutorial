"""把五支枪的互斥判据落成可复核的表：为每个要素挑一帧使自身余量最大（同余量取中段帧，
避开刚开火的第一帧），验证「其它四支枪的选定帧必须判失败」，并生成知识包片段。"""
import json
from pathlib import Path

import numpy as np

D = json.loads(Path(r"F:/taspipe_scratch/detector_dist.json").read_text(encoding="utf-8"))
COLORS = {"white": [254, 254, 254], "warm": [254, 130, 112]}
TOLS = {"white": 30, "warm": 40}
REGION = {
    "muzzle": [0.23, 0.375, 0.42, 0.42],
    "mid": [0.42, 0.375, 0.58, 0.42],
    "far": [0.58, 0.375, 0.72, 0.42],
    "upper": [0.28, 0.26, 0.46, 0.375],
    "lower": [0.28, 0.42, 0.46, 0.52],
}
# 判据：(颜色, 区域, 下限, 上限)
RULES = {
    "default_rifle":  [("white", "muzzle", 0.010, None), ("warm", "muzzle", None, 0.0005)],
    "machine_gun_m":  [("warm", "muzzle", 0.004, 0.012), ("warm", "upper", None, 0.0005),
                       ("warm", "lower", None, 0.0005)],
    "fire_thrower_f": [("warm", "upper", 0.006, None), ("warm", "lower", 0.006, None),
                       ("warm", "muzzle", None, 0.030)],
    "spread_gun_s":   [("warm", "muzzle", 0.012, None), ("warm", "mid", None, 0.010)],
    "laser_gun_l":    [("warm", "far", 0.050, None), ("warm", "upper", None, 0.0005)],
}


def series(e, side, color, region):
    return np.asarray(D[f"{e}/{side}"][f"{region}/{color}"])


def value(e, side, f, rule):
    return float(series(e, side, rule[0], rule[1])[f])


def rule_pass(e, side, f, rules):
    margins = []
    for r in rules:
        v = value(e, side, f, r)
        lo, hi = r[2], r[3]
        if lo is not None and v < lo:
            return False, 0.0
        if hi is not None and v > hi:
            return False, 0.0
        if lo is not None and hi is not None:
            mid = (lo + hi) / 2.0
            margins.append(min((v - lo) / (mid - lo), (hi - v) / (hi - mid)))
        elif lo is not None:
            margins.append(v / lo)
        else:
            margins.append(hi / max(v, 1e-9))
    return True, min(margins) if margins else 0.0


chosen = {}
for e, rules in RULES.items():
    n = len(series(e, "positive", rules[0][0], rules[0][1]))
    scores = [(rule_pass(e, "positive", f, rules), f) for f in range(n)]
    ok = [(m, f) for (p, m), f in scores if p]
    assert ok, f"{e}: 判据在自身 clip 一帧都不通过"
    best = max(m for m, _ in ok)
    # 同余量（>=0.9*best）里取最靠 clip 中段的帧，保证这一段画面里弹头已经在飞
    cand = [f for m, f in ok if m >= best * 0.9]
    f_sel = min(cand, key=lambda f: abs(f - n / 2))
    m_sel = rule_pass(e, "positive", f_sel, rules)[1]
    neg = len(series(e, "negative", rules[0][0], rules[0][1]))
    chosen[e] = {"frame": int(f_sel), "margin": round(float(m_sel), 2),
                 "neg_all_fail": all(not rule_pass(e, "negative", f, rules)[0]
                                     for f in range(neg))}

print("== 选定帧 / 自身余量 / 空按对照逐帧失败 ==")
for e, c in chosen.items():
    print(f"  {e:17s} frame={c['frame']:3d}  margin={c['margin']:5.2f}  "
          f"空按全帧失败={c['neg_all_fail']}")

print("\n== 交叉验证：他要素选定帧必须判失败 ==")
bad = []
for e, rules in RULES.items():
    for o, c in chosen.items():
        if o == e:
            continue
        p, _ = rule_pass(o, "positive", c["frame"], rules)
        if p:
            bad.append((e, o, c["frame"], [value(o, "positive", c["frame"], r) for r in rules]))
for e, o, f, vals in bad:
    print(f"  ✗ {e} 的判据在 {o} 的 f{f} 上误报: {[round(v, 4) for v in vals]}")
print("  全部互斥 ✓" if not bad else f"  {len(bad)} 处误报")

print("\n== 逐帧命中数（行=判据，列=各 clip）==")
for e, rules in RULES.items():
    row = []
    for o in RULES:
        n = len(series(o, "positive", rules[0][0], rules[0][1]))
        row.append(f"{o.split('_')[0]}:{sum(1 for f in range(n) if rule_pass(o, 'positive', f, rules)[0])}/{n}")
    print(f"  {e:17s} " + " ".join(row))


def checks_of(rules):
    out = []
    for color, region, lo, hi in rules:
        pid = ("frame_region_color_fraction_range" if lo is not None and hi is not None
               else "frame_region_color_fraction" if lo is not None
               else "frame_region_color_fraction_max")
        kind = ("range" if lo is not None and hi is not None else "min" if lo else "max")
        params = {"region": REGION[region], "rgb": COLORS[color], "tol": TOLS[color]}
        if lo is not None:
            params["min_fraction"] = lo
        if hi is not None:
            params["max_fraction"] = hi
        out.append({"check_id": f"{region}_{color}_{kind}", "plugin_id": pid,
                    "params": params, "required": True})
    return out


pack = {"elements": {e: {"detection_frame": chosen[e]["frame"],
                         "success_checks": checks_of(RULES[e])} for e in RULES}}
Path(r"F:/taspipe_scratch/detector_final.json").write_text(
    json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n写出 F:/taspipe_scratch/detector_final.json")
