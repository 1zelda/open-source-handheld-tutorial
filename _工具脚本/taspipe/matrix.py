# -*- coding: utf-8 -*-
"""泛化矩阵跑批（auto 设计 matrix 层）：≥6 名作 × 多任务类型，证明配置驱动流程能泛化。

每格 = 一个 JobSpec。逐格调 auto.orchestrate（真实生产路径），按指纹跳过已完成格：
  * cell_done = job.json 存在 + status=done + verdict=pass + 产物真在 + fp==expected_fingerprint。
  * 跳过格不重采集（不重复忍龙）；重跑矩阵只补缺失/失效格。
  * 断言从台账/产物现查，不写死「还缺谁」名单（正常推进后名单会变）。

覆盖表逐格直接计数（done/skipped/blocked/failed/partial），不用总数减失败倒推。
泛化主力是 playthrough：任何 registry 判 replayable 的名作都能跑，无需逐游戏知识包。

运行:
  python -m taspipe.matrix famous --out <dir> [--frames 600] [--exclude "Ninja Gaiden,Nova"]
  python -m taspipe.matrix run --matrix matrix.json --out <dir>
  python -m taspipe.matrix status --out <dir>
"""
import argparse
import json
import sys
from pathlib import Path

from .schema import Verdict
from . import registry as R
from .auto import JobSpec, orchestrate, expected_fingerprint

# 默认排除：忍龙已出片（不重复实验）；Nova 是 homebrew（用户明令换名作）。
DEFAULT_EXCLUDE = ("Ninja Gaiden", "Nova")


def famous_playthrough_cells(lib=None, exclude=DEFAULT_EXCLUDE, frames=None, audio=False):
    """从 live registry 取 replayable 名作建 playthrough 格（排除已做/homebrew）。
    不写死游戏名单：名单从当前可回放集现查，排除项按名子串。"""
    lib = Path(lib or R.DEFAULT_LIB)
    pubs = R.load_publications(lib)
    ri, vi, bh = R.index_roms(lib), R.index_versions(lib), R.discover_bizhawk(R.DEFAULT_EMU)
    # 廉价预筛：所需 ROM SHA-1 在本地索引里才可能 replayable（出版物 rom_sha1 / version 页），
    # 避免对 4694 条逐个开 bk2 zip 读 Header（实测全量 assess >2min，预筛后 36 条 ~4s）。
    romset = set(ri.keys())

    def _candidate(p):
        s = R.norm_sha1(p.get("rom_sha1"))
        if s and s in romset:
            return True
        v = vi.get(p.get("version_id", ""))
        return bool(v and v.get("sha1") in romset)

    excl = [e.strip().lower() for e in exclude if e.strip()]
    seen_games = set()
    cells = []
    for p in pubs:
        if not _candidate(p):
            continue
        r = R.assess(p, lib, ri, vi, bh)
        if r["status"] != "replayable":
            continue
        game = p.get("game", "")
        gl = game.lower()
        if any(e in gl for e in excl):
            continue
        if gl in seen_games:          # 同名作多出版物只取一条（避免重复格）
            continue
        seen_games.add(gl)
        cells.append({"game": game, "job_type": "playthrough", "pub_id": p["id"],
                      "source": "movie", "frames": frames, "audio": audio})
    return cells


def load_matrix(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return d.get("cells", d if isinstance(d, list) else [])


def _deliverable_present(doc):
    """产物真在才算完成格（量产物，不只看 status 字段）。"""
    if doc.get("deliverable_ref"):
        return Path(doc["deliverable_ref"]).is_file()
    els = doc.get("elements") or []
    if els:
        return all(e.get("deliverable_ref") and Path(e["deliverable_ref"]).is_file()
                   for e in els)
    return False


def cell_done(spec, out_root, lib=None):
    """已完成格判定：job.json + done + pass + 产物在 + 指纹一致。任一不符 => 未完成。"""
    job_dir = Path(out_root) / spec.slug()
    jf = job_dir / "job.json"
    if not jf.is_file():
        return False, "no job.json"
    try:
        doc = json.loads(jf.read_text(encoding="utf-8"))
    except Exception:
        return False, "job.json 损坏"
    if doc.get("status") != "done" or doc.get("verdict") != Verdict.PASS.value:
        return False, f"status={doc.get('status')} verdict={doc.get('verdict')}"
    if not _deliverable_present(doc):
        return False, "产物缺失"
    exp = expected_fingerprint(spec, lib)
    if exp is None or doc.get("fp") != exp:
        return False, "指纹不符/输入变更"
    return True, "指纹一致+产物在"


def run_matrix(cells, out_root, lib=None, skip_done=True, dry_run=False, on_cell=None):
    """逐格跑 auto。返回 {cells:[{game,job_type,slug,action,status,verdict,...}], coverage:{...}}。"""
    out_root = str(out_root)
    results = []
    for cd in cells:
        spec = JobSpec.from_dict(cd)
        try:
            spec.validate()
        except Exception as e:
            rec = {"game": spec.game, "job_type": spec.job_type, "slug": spec.slug(),
                   "action": "invalid", "status": "blocked", "verdict": None, "reason": str(e)}
            results.append(rec)
            if on_cell:
                on_cell(rec)
            continue
        if skip_done and not dry_run:
            done, why = cell_done(spec, out_root, lib)
            if done:
                jf = Path(out_root) / spec.slug() / "job.json"
                doc = json.loads(jf.read_text(encoding="utf-8"))
                rec = {"game": spec.game, "job_type": spec.job_type, "source": spec.source,
                       "slug": spec.slug(), "action": "skipped", "status": "done",
                       "verdict": doc.get("verdict"), "reason": why,
                       "deliverable_ref": doc.get("deliverable_ref")}
                results.append(rec)
                if on_cell:
                    on_cell(rec)
                continue
        doc = orchestrate(spec, lib=lib, out_dir=out_root, dry_run=dry_run)
        rec = {"game": spec.game, "job_type": spec.job_type, "source": spec.source,
               "slug": spec.slug(), "action": "planned" if dry_run else "ran",
               "status": doc.get("status"), "verdict": doc.get("verdict"),
               "failed_stage": doc.get("failed_stage"),
               "deliverable_ref": doc.get("deliverable_ref"),
               "reason": "; ".join(b.get("reason", "") for b in doc.get("blockers", []))[:120]}
        results.append(rec)
        if on_cell:
            on_cell(rec)
    coverage = _coverage(results)
    report = {"cells": results, "coverage": coverage, "total": len(results)}
    Path(out_root).mkdir(parents=True, exist_ok=True)
    (Path(out_root) / "matrix_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def _coverage(results):
    """逐格直接计数（不总数减失败倒推）。"""
    counts = {}
    for r in results:
        key = r["action"] if r["action"] in ("skipped", "invalid", "planned") else r["status"]
        counts[key] = counts.get(key, 0) + 1
    passed = sum(1 for r in results if r.get("verdict") == Verdict.PASS.value)
    return {"by_result": counts, "pass": passed, "total": len(results)}


def status(out_root):
    """从已落盘 job.json 现查覆盖（不重跑）。"""
    out_root = Path(out_root)
    rows = []
    for jf in sorted(out_root.glob("*/job.json")):
        try:
            d = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append({"slug": jf.parent.name, "game": d.get("game"),
                     "job_type": d.get("job_type"), "status": d.get("status"),
                     "verdict": d.get("verdict"),
                     "deliverable_present": _deliverable_present(d)})
    return {"jobs": rows, "total": len(rows),
            "pass": sum(1 for r in rows if r["verdict"] == Verdict.PASS.value)}


def _print_report(report):
    print(f"矩阵 {report['total']} 格 | 覆盖 {json.dumps(report['coverage'], ensure_ascii=False)}")
    for r in report["cells"]:
        print(f"  [{r['action']}/{r['status']}] {r['game']} · {r['job_type']} · {r.get('source','')}"
              f" verdict={r.get('verdict')}" + (f" | {r['reason']}" if r.get("reason") else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("famous", help="从 live registry 建名作 playthrough 矩阵并跑")
    f.add_argument("--out", required=True)
    f.add_argument("--frames", type=int, default=None)
    f.add_argument("--audio", action="store_true")
    f.add_argument("--exclude", default=",".join(DEFAULT_EXCLUDE))
    f.add_argument("--lib", default=None)
    f.add_argument("--plan", action="store_true", help="干跑不采集")
    f.add_argument("--no-skip", action="store_true")
    r = sub.add_parser("run", help="跑自定义矩阵 JSON")
    r.add_argument("--matrix", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--lib", default=None)
    r.add_argument("--plan", action="store_true")
    r.add_argument("--no-skip", action="store_true")
    s = sub.add_parser("status", help="从落盘 job.json 现查覆盖")
    s.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.cmd == "status":
        print(json.dumps(status(args.out), ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "famous":
        cells = famous_playthrough_cells(args.lib, exclude=args.exclude.split(","),
                                         frames=args.frames, audio=args.audio)
    else:
        cells = load_matrix(args.matrix)
    if not cells:
        print("矩阵为空（无可回放名作或 cells 空）", file=sys.stderr)
        return 1
    report = run_matrix(cells, args.out, lib=args.lib, skip_done=not args.no_skip,
                        dry_run=args.plan, on_cell=lambda rec: None)
    _print_report(report)
    cov = report["coverage"]
    return 0 if cov.get("failed", 0) == 0 and cov.get("blocked", 0) == 0 else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())