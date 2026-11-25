# -*- coding: utf-8 -*-
"""从 ph3_selector_sweep 的生产路径 JSON 派生可读摘要，不重跑查询。"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def derive(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(d.get("summary", {}).get("modes"), dict):
        raise ValueError(f"{path} 不是当前生产路径 sweep 格式")
    modes = d["summary"]["modes"]
    details = {}
    for mode in modes:
        details[mode] = {
            "fixed": [r["id"] for r in d["questions"] if r["classes"][mode] == "fixed"],
            "regressed": [r["id"] for r in d["questions"] if r["classes"][mode] == "regressed"],
            "unchanged_fail": [r["id"] for r in d["questions"]
                               if r["classes"][mode] == "unchanged_fail"],
            "intercepted": [
                {"id": r["id"], "kind": r.get("kind")}
                for r in d.get("probes_ext", []) + d.get("probes_base", [])
                if r["classes"][mode] == "intercepted"],
            "newly_passed": [
                {"id": r["id"], "kind": r.get("kind")}
                for r in d.get("probes_ext", []) + d.get("probes_base", [])
                if r["classes"][mode] == "newly_passed"],
        }
    return {"source": Path(path).name, "taken_at": d.get("taken_at"),
            "index": d.get("index", {}), "code": d.get("code", {}),
            "base_v2_ok": d["summary"].get("base_v2_ok"), "modes": modes,
            "details": details}


def render(items):
    L = ["# 选择器生产接线摘要", ""]
    for s in items:
        L += [f"## {s['source']}", "",
              f"- 时间：{s['taken_at']}；索引：`{s['index'].get('name')}` "
              f"sha16 `{s['index'].get('sha16')}`（{s['index'].get('chunks')} 块）",
              f"- 生产基线严格出证：{s['base_v2_ok']}/26", "",
              "| 模式 | 严格出证 | 修好 | 打坏 | 错误出证 | 仍pass但换证 | 探针新放行 | 探针拦截 |",
              "|---|---|---|---|---|---|---|---|"]
        for mode, v in s["modes"].items():
            L.append(f"| {mode} | {v['v2_ok']}/26 | {v['classes'].get('fixed', 0)} | "
                     f"{v['classes'].get('regressed', 0)} | {v['wrong_evidence']} | "
                     f"{v['evidence_swapped']} | {v['newly_passed']} | {v['intercepted']} |")
        if "strict_fragments" in s["details"]:
            v = s["details"]["strict_fragments"]
            L += ["", "### strict_fragments 逐格", "",
                  f"- 修好：{v['fixed'] or '无'}；打坏：{v['regressed'] or '无'}",
                  f"- 仍未过：{v['unchanged_fail'] or '无'}",
                  f"- 拦截探针：{v['intercepted'] or '无'}",
                  f"- 新放行探针：{v['newly_passed'] or '无'}"]
        L.append("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("json", nargs="*", help="生产路径 sweep JSON；默认取最新可用件")
    ap.add_argument("--out", default=str(HERE / "ph3_selector_summary.md"))
    args = ap.parse_args(argv)
    paths = [Path(p) for p in args.json]
    if not paths:
        candidates = []
        for p in HERE.glob("ph3_selector_*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(d.get("summary", {}).get("modes"), dict):
                candidates.append((d.get("taken_at", ""), p))
        paths = [p for _, p in sorted(candidates, reverse=True)[:1]]
    if not paths:
        raise SystemExit("没有可用的生产路径 sweep JSON")
    out = Path(args.out)
    out.write_text(render([derive(p) for p in paths]), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
