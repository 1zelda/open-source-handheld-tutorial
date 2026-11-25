# -*- coding: utf-8 -*-
"""P5 干净块级验证（零模型、零臂混淆）：
拿 preP5 hybrid 基线 JSON 里真实 surfaced 的块（chunk_id），用当前生产
kb_answer.annotate 重判可答性，对比基线存储的 preP5 answerable。
同块同臂 => 差异只来自 P5 查询时逻辑（C1 首量词 / C2 射门焦点 / C3a 域泛词停用）。
另核 26 冻结金标块当前仍可答（零误杀）。
用法（系统 py -3）：py -3 -u p5_block_verify.py > p5_block_verify_out.txt
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K  # noqa: E402
from taspipe import kb_answer as KA  # noqa: E402

idx = K.load_index(K.INDEX_JSON)
chunks = idx["chunks"]
by_id = {}
for c in chunks:
    cid = c.get("chunk_id") or c.get("id")
    by_id[cid] = c

base = json.loads((HERE / "p5_probe_ext_results_preP5.json").read_text(encoding="utf-8"))
frozen = json.loads((HERE / "p1_questions_ext.json").read_text(encoding="utf-8"))

print("=== preP5 hybrid 基线 surfaced 块：P5 前后可答性翻转（同块重判）===")
flips = []
for r in base:
    q = r["q"]
    for win in ("w3", "w5"):
        for h in r[win]["hits"]:
            c = by_id.get(h["chunk_id"])
            if c is None:
                continue
            pre = h["answerable"]
            post = KA.annotate(q, c["text"], K.tokens, c.get("lang", "zh"))["answerable"]
            if pre != post:
                flips.append((r["id"], win, h["rank"], h["locator"], pre, post))
for fid, win, rank, loc, pre, post in flips:
    print(f"  {fid:5s} {win} rank{rank} {loc}  {pre} -> {post}")
print(f"  翻转块数：{len(flips)}（True->False=P5 堵假阳性；False->True 须为 0）")
bad = [f for f in flips if f[4] is False and f[5] is True]
print(f"  反向翻转（False->True，不应有）：{len(bad)}")

print("\n=== 靶标假块须 True->False（X25/X26/X28 w3；X01/X06/X07/X24 w5）===")
targets = {"X25", "X26", "X28", "X01", "X06", "X07", "X24"}
for fid, win, rank, loc, pre, post in flips:
    if fid in targets:
        print(f"  {fid} {win} rank{rank} {pre}->{post}")

print("\n=== 26 冻结金标块当前生产仍可答（重叠语义同 eval_common._gold_hit；零误杀）===")
killed = 0
for q in frozen["questions"]:
    g = q.get("gold")
    if not g:
        continue
    cs = [c for c in chunks
          if g["path_contains"] in (c.get("path") or c.get("source") or c.get("locator") or "")
          and c.get("line_start", 0) <= g["line_end"]
          and c.get("line_end", 0) >= g["line_start"]]
    ans = [KA.annotate(q["q"], c["text"], K.tokens, c.get("lang", "zh"))["answerable"] for c in cs]
    if cs and not any(ans):
        killed += 1
        print(f"  {q['id']} KILLED {q['q'][:30]}（{len(cs)} 块全不可答）")
print(f"  金标误杀数：{killed}（权威回归判据仍以生产 eval_common.grade 为准）")