"""互斥检测器搜索（第 2 版）。

规则 = 1 个下限检查 + 0~2 个上限检查，逐帧合取判定。要求：
  A. 在本要素正样本的选定帧通过；
  B. 在本要素空按对照的每一帧失败（检测的是弹头，不是枪械图标/静态背景）；
  C. 在其它四支枪正样本的每一帧失败（这一格是这支枪，不是别的枪）。
"""
import itertools
import json
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(r"F:/taspipe_scratch/pack_calib_frames")
ELS = ["default_rifle", "machine_gun_m", "fire_thrower_f", "spread_gun_s", "laser_gun_l"]
COLORS = {"white": ([254, 254, 254], 30), "warm": ([254, 130, 112], 40),
          "darkred": ([181, 50, 32], 40)}
XS = [0.23, 0.28, 0.34, 0.42, 0.50, 0.58]
YS = [0.20, 0.26, 0.32, 0.375, 0.42, 0.48, 0.56]
EPS = 1e-5

print("加载实测帧…")
raw = {e: {s: [np.asarray(Image.open(p).convert("RGB"), dtype=np.int16)
               for p in sorted((OUT / e / s).glob("f*.png"))]
           for s in ("positive", "negative")} for e in ELS}
H, W = raw[ELS[0]]["positive"][0].shape[:2]

frac = {}
for cn, (rgb, tol) in COLORS.items():
    integ = {}
    for e in ELS:
        for s in ("positive", "negative"):
            st = np.abs(np.stack(raw[e][s]) - np.asarray(rgb, dtype=np.int32)).max(axis=3)
            m = (st <= tol).astype(np.float32)
            integ[(e, s)] = np.cumsum(np.cumsum(m, axis=1), axis=2)
    for x0, x1 in itertools.combinations(XS, 2):
        for y0, y1 in itertools.combinations(YS, 2):
            if (x1 - x0) < 0.05 or (y1 - y0) < 0.03:
                continue
            py0, py1, px0, px1 = int(y0 * H), int(y1 * H), int(x0 * W), int(x1 * W)
            area = (py1 - py0) * (px1 - px0)
            if area < 200:
                continue
            frac[(cn, x0, y0, x1, y1)] = {
                k: (v[:, py1, px1] - v[:, py0, px1] - v[:, py1, px0] + v[:, py0, px0]) / area
                for k, v in integ.items()}
print(f"候选区域 {len(frac)} 个")


def geo(a, b):
    return float(np.sqrt(max(a, EPS) * max(b, EPS)))


def try_rule(e, kmin, f_sel, kmaxes):
    own, neg = frac[kmin][(e, "positive")], frac[kmin][(e, "negative")]
    t = geo(max(neg.max() * 1.8, EPS), own[f_sel])
    if own[f_sel] < t or float(neg.max()) >= t or not bool((neg < t).all()):
        return None
    us = []
    for km in kmaxes:
        base = max(float(frac[km][(e, "positive")][f_sel]) * 2.0, EPS)
        top = max(float(frac[km][(o, "positive")].max()) for o in ELS if o != e)
        if top <= base * 1.5:
            return None
        us.append(geo(base, top))
    for o in ELS:
        if o == e:
            continue
        p = frac[kmin][(o, "positive")]
        ok = p < t
        for km, u in zip(kmaxes, us):
            ok = ok | (frac[km][(o, "positive")] > u)
        if not bool(ok.all()):
            return None
    own_all = [(own[f] >= t) and all(float(frac[km][(e, "positive")][f]) <= u
                                     for km, u in zip(kmaxes, us))
                for f in range(len(own))]
    n_pass = sum(own_all)
    margin_others = min(t / max(frac[kmin][(o, "positive")].max(), EPS) for o in ELS if o != e)
    return {"frame": f_sel, "thr": round(t, 6), "maxes": [list(k) for k in kmaxes],
            "u": [round(u, 6) for u in us], "own_value": round(float(own[f_sel]), 6),
            "neg_max": round(float(neg.max()), 6), "frames_passing": n_pass,
            "margin_neg": round(float(t / max(neg.max(), EPS)), 2),
            "margin_others": round(float(margin_others), 2)}


results = {}
for e in ELS:
    pos = {k: v[(e, "positive")] for k, v in frac.items()}
    negm = {k: v[(e, "negative")].max() for k, v in frac.items()}
    cands_min = [(float(pos[k].max() / max(negm[k], EPS)), k) for k in frac
                 if pos[k].max() > 0.002 and negm[k] < pos[k].max() / 3]
    cands_min.sort(reverse=True)
    cands_min = cands_min[:30]
    cands_max = [(float(max(frac[k][(o, "positive")].max()
                            for o in ELS if o != e) / max(pos[k].max(), EPS)), k)
                 for k in frac if pos[k].max() < 0.0025]
    cands_max.sort(reverse=True)
    cands_max = [k for _, k in cands_max[:20]]

    found = []
    for _, kmin in cands_min:
        own = pos[kmin]
        for f_sel in (int(np.argmax(own)), int(np.argmax(own)) - 1, int(np.argmax(own)) + 1):
            if not 0 <= f_sel < len(own):
                continue
            for r in (0, 1, 2):
                for kmaxes in itertools.combinations(cands_max, r):
                    res = try_rule(e, kmin, f_sel, kmaxes)
                    if res:
                        found.append(res)
    found.sort(key=lambda d: (d["margin_neg"] >= 5, min(d["margin_neg"], d["margin_others"])),
               reverse=True)
    results[e] = found[:10]
    print(f"\n== {e}  可行规则 {len(found)} 条 ==")
    for d in found[:4]:
        print(f"  f{d['frame']:<3d} 通过帧数{d['frames_passing']:2d} 下限{tuple(d and [])}"
              f" thr={d['thr']:.5f} 实测{d['own_value']:.5f} 空按max={d['neg_max']:.5f} "
              f"上限{d['maxes']} u={d['u']} 余量 对照{d['margin_neg']} 他枪{d['margin_others']}")

Path(r"F:/taspipe_scratch/detector_rules.json").write_text(json.dumps(results, indent=2),
                                                            encoding="utf-8")
print("\n写出 detector_rules.json")
