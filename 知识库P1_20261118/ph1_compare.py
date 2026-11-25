# -*- coding: utf-8 -*-
"""阶段1（运行与出证契约）两臂零回归对账（零 LLM，只读已落盘产物）。

验收判据（评审实施路线§阶段1）：本阶段不改排序/窗口/可答性判定 ⇒
两臂评测 grades 与探针 flip/w3/w5 须逐格等于 P10 基线；新契约字段
（selected_evidence/index_used/version_hints）必须存在且身份一致；
生产索引/语料真实文件 sha+块数+字节数不动。
用法：py -3 -u ph1_compare.py
"""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")


def load(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def grades_by_id(ev):
    return {g["id"]: g for g in ev["grades"]}


def probe_by_id(rows):
    return {r["id"]: r for r in rows}


def cell_diff(new, old, keys=None):
    out = []
    for i in old:
        a, b = new.get(i), old[i]
        if keys:
            a = {k: (a or {}).get(k) for k in keys}
            b = {k: b[k] for k in keys}
        if json.dumps(a, sort_keys=True, ensure_ascii=False) != json.dumps(b, sort_keys=True, ensure_ascii=False):
            out.append(i)
    return out


def main():
    verdict = []

    def check(name, cond, detail=""):
        verdict.append((name, bool(cond)))
        print(f"{'OK ' if cond else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))

    # ── 两臂逐格零差异（vs P10 基线） ──────────────────────────
    for arm in ("bm25", "hybrid"):
        new_ev = load(f"ph1_prod_{arm}.json")
        old_ev = load(f"p10_prod_{arm}.json")
        d = cell_diff(grades_by_id(new_ev), grades_by_id(old_ev))
        check(f"{arm} 评测 grades 逐格零差异(vs P10)",
              not d and new_ev["summary"]["ok"] == old_ev["summary"]["ok"],
              f"ok={new_ev['summary']['ok']}/{new_ev['summary']['total']} diff_ids={d}")
        new_pb = load(f"ph1_probe_{arm}.json")
        old_pb = load(f"p10_probe_{arm}.json")
        pd = cell_diff(probe_by_id(new_pb), probe_by_id(old_pb), keys=("flip", "w3", "w5"))
        check(f"{arm} 探针 flip/w3/w5 逐格零差异(vs P10)", not pd, f"diff_ids={pd}")

    # ── 臂身份真实性（hybrid 臂必须真走了富集，不是静默兜底） ──
    hb = load("ph1_prod_hybrid.json")
    rets = {g["retrieval"] for g in hb["grades"]}
    none_ids = [r["id"] for r in hb["results"] if r["res"].get("retrieval") is None]
    none_ok = all(r["res"]["status"] == "miss" and r["res"].get("refusal") == "out_of_scope"
                  for r in hb["results"] if r["res"].get("retrieval") is None)
    check("hybrid 臂真实走 hybrid_union12（无检索字段的必须全是域外拒答）",
          rets <= {"hybrid_union12", None} and "hybrid_union12" in rets and none_ok,
          f"retrieval集={rets} 无字段题={none_ids}")
    bb = load("ph1_prod_bm25.json")
    retsb = {g.get("retrieval") for g in bb["grades"]}
    check("bm25 臂全部 bm25_only/域外拒答", retsb <= {"bm25_only", None},
          f"retrieval集={retsb}")

    # ── 新契约字段：pass 必带放行依据块 + 索引身份 + 版本钉 ────
    for arm, want_idx in (("bm25", "index.json"), ("hybrid", "index_hybrid.json")):
        ev = load(f"ph1_prod_{arm}.json")
        bad_sel, bad_idx = [], []
        for r in ev["results"]:
            res = r["res"]
            if res.get("index_used") not in (want_idx, None):
                bad_idx.append(r["id"])
            if res["status"] == "pass":
                sel = res.get("selected_evidence") or []
                ids = {h["chunk_id"] for h in res["hits"]}
                if len(sel) != 1 or sel[0]["chunk_id"] not in ids:
                    bad_sel.append(r["id"])
            elif "selected_evidence" in res:
                bad_sel.append(r["id"] + "(非pass带出证)")
        check(f"{arm} pass 出证绑定完整（恰1块且在hits内；非pass不带）", not bad_sel,
              f"问题={bad_sel}")
        check(f"{arm} index_used 身份一致（{want_idx}）", not bad_idx, f"问题={bad_idx}")
    eck_ok = all(r["res"].get("version_hints") == ["kof98eck"]
                 for r in hb["results"] if r["id"] in ("Q09", "Q10"))
    check("ECK 问句版本钉暴露（Q09/Q10 version_hints=[kof98eck]，信息层不改判分）", eck_ok)

    # ── 真实文件反查：生产索引/语料字节不动 ────────────────────
    from taspipe import kb as K
    expect = [
        (Path(K.INDEX_JSON), "09096a016496405a", 625, 2916773),
        (Path(K.hybrid_index_path()), "8d12dd89abbb", 639, 2953449),
    ]
    for p, sha_prefix, nchunks, nbytes in expect:
        b = p.read_bytes()
        sha = hashlib.sha256(b).hexdigest()
        n = len(json.loads(b)["chunks"])
        check(f"真实文件未动 {p.name}（sha前缀/块数/字节）",
              sha.startswith(sha_prefix) and n == nchunks and len(b) == nbytes,
              f"sha={sha[:16]} N={n} bytes={len(b)}")
    m = json.loads(Path(K.CORPUS_MAP).read_text(encoding="utf-8"))
    from taspipe import sources as S
    zh_expect = {"setsumei": ("da3200681eb4f34d", 7472), "urawaza": ("4389b67595729f60", 1735)}
    for e in m["entries"]:
        if e.get("hybrid_only"):
            key = "setsumei" if "setsumei" in e["path"] else "urawaza"
            pref, nb = zh_expect[key]
            b = S.resolve_path(e["path"]).read_bytes()
            check(f"对照件字节未动 {Path(e['path']).name}",
                  hashlib.sha256(b).hexdigest().startswith(pref) and len(b) == nb
                  and e.get("index") is False,
                  f"sha={hashlib.sha256(b).hexdigest()[:16]} bytes={len(b)} index={e.get('index')}")

    n_ok = sum(1 for _, c in verdict if c)
    print(f"\nPH1_COMPARE {n_ok}/{len(verdict)}")
    sys.exit(0 if n_ok == len(verdict) else 1)


if __name__ == "__main__":
    main()