"""自动标定：对每个要素，遍历 (region/color 组合 × 帧号)，打分
= 本要素该帧占比 / max(其它要素同帧占比, 空按全程峰值)；比值越大越专一。"""
import json
from pathlib import Path

import numpy as np

R = json.loads(Path(r"F:/taspipe_scratch/pack_calib.json").read_text(encoding="utf-8"))
ELS = list(R)
TRIPLES = list(R[ELS[0]]["positive"])

best = {}
for e in ELS:
    cands = []
    for t in TRIPLES:
        idle = max(R[e]["negative"][t])
        others = [np.asarray(R[o]["positive"][t]) for o in ELS if o != e]
        own = np.asarray(R[e]["positive"][t])
        n = len(own)
        for f in range(n):
            ceil = max(idle, max(float(a[f]) for a in others))
            if own[f] <= 0 or ceil <= 0:
                continue
            cands.append((own[f] / ceil, t, f, own[f], ceil))
    cands.sort(reverse=True)
    best[e] = cands[:6]
    print(f"\n== {e} ==")
    for ratio, t, f, val, ceil in best[e][:6]:
        print(f"  {t:14s} f{f:<3d} 本要素={val:.4f} 其它/空按上界={ceil:.4f} 分离比={ratio:.1f}x")

Path(r"F:/taspipe_scratch/pack_calib_best.json").write_text(
    json.dumps({k: [[r, t, f, v, c] for r, t, f, v, c in vals] for k, vals in best.items()},
               ensure_ascii=False, indent=2), encoding="utf-8")

# 帧级交叉表：把选中的 (triple, frame) 组合列出来，看每列是不是只有本要素亮
print("\n\n帧级交叉表（行=要素，列=为该要素选出的判据）")
cols = {e: best[e][0][1:3] for e in ELS}
head = "element".ljust(18) + "".join(f"{e[:14]:>20s}" for e in ELS)
print(head)
for e in ELS:
    t, f = cols[e]
    line = f"{t} f{f}".ljust(18)
    for o in ELS:
        v = R[o]["positive"][t][f]
        i = max(R[o]["negative"][t])
        line += f"{v:>13.4f}/{i:.3f}"
    print(f"{e[:16]:18s}" + "".join(f"{R[o]['positive'][t][f]:>20.4f}" for o in ELS))
