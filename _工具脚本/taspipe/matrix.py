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
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import sys
import threading
from pathlib import Path

from .schema import Verdict
from . import registry as R
from . import popularity
from . import acquire as A
from .auto import JobSpec, orchestrate, expected_fingerprint
from .record import expected_frames

# 默认排除：忍龙已出片（不重复实验）。冷门不再靠这份子串清单拦，
# 改由 popular_titles.json 名单正向筛（用户 2026-11-22 口径：只测最有名的作品）。
DEFAULT_EXCLUDE = ("Ninja Gaiden", "Nova")

# 天马边框模板按平台分：FC 与 SFC 的版式/配色不同，套错会把成片做歪。
TEMPLATE_BY_PLATFORM = {"NES": "fc_tianma_cover", "FC": "fc_tianma_cover",
                        "SNES": "snes_tianma_cover", "SFC": "snes_tianma_cover"}

# 样片帧数下限（按平台）。SNES 的片头比 NES 长得多，实测四部里三部在 600 帧窗口
# 内全黑或只有厂标：MMX2 5628 到第 1250 帧才出画面（60 帧采样 luma 0.0、
# 600 帧采样最大 4.3，两次都低于 8.0 门槛）、Mega Man 7 6092 600 帧全黑、
# DKC2 窗口里只有 Rareware/Nintendo 标。F-Zero 7406 是例外，第 150 帧就亮
# （luma 87.2）。抬到 3000 帧多花约 40s（SNES 吞吐 32.1s 启动 + 帧/60），
# 换四部 SNES 都有画面证据，而不是让 picture_content 逐格判不可判。
PICTURE_FLOOR_FRAMES = {"SNES": 3000, "SFC": 3000}


def slice_frames(platform, frames, movie_frames=None):
    """样片帧数按平台下限抬高；被下限抬上去的那一档不许超过片子自身长度。

    frames=None 是「整片」，一律不动。封顶只作用在下限抬高上：显式请求的帧数
    保持原样透传，免得这条规则顺手改掉别处的采样口径。抬到 3000 而片子只有
    1200 帧会自造假失败——endpoint_reached 判的是 n_frames == 期望帧数，
    回放在片尾自然停住，检查格就把「采完了」报成 fail。"""
    if frames is None:
        return None
    n = int(frames)
    floor = PICTURE_FLOOR_FRAMES.get((platform or "").upper())
    if floor and n < floor:
        n = floor
        if movie_frames:
            n = min(n, int(movie_frames))
    return n


def rom_available(pub, lib, romset, versions=None):
    """候选链走 acquire.rom_sha1_candidates（出版物 rom_sha1 / bk2 Header / version 页三处）。

    不能只看前两处：11-22 实测 4776/4831/5231 三条只有 bk2 Header 对得上本地文件，
    旧的「两处即淘汰」会让 acquire 已经解开的假阻塞在矩阵这一层原样复发。"""
    return any(sha in romset for sha, _src in A.rom_sha1_candidates(pub, lib, versions))


def famous_playthrough_cells(lib=None, exclude=DEFAULT_EXCLUDE, frames=None, audio=False):
    """从 live registry 取 replayable 且「在热门名单上」的名作建 playthrough 格。

    两道筛子各管各的：名单筛掉冷门（正向白名单，宁漏不错认），exclude 筛掉已出片/已实验过的。
    不写死游戏名单：候选从当前可回放集现查，热不热门从名单文件现查。"""
    lib = Path(lib or R.DEFAULT_LIB)
    pubs = R.load_publications(lib)
    ri, vi, bh = R.index_roms(lib), R.index_versions(lib), R.discover_bizhawk(R.DEFAULT_EMU)
    romset = set(ri.keys())

    # 名单筛子放在可用性之前：冷门不必开 bk2 zip，读 Header 的成本只落在热门那几十条上。
    excl = [e.strip().lower() for e in exclude if e.strip()]
    seen_games = set()
    cells = []
    for p in pubs:
        game = p.get("game", "")
        gl = game.lower()
        if any(e in gl for e in excl):
            continue
        if gl in seen_games:          # 同名作多出版物只取一条（避免重复格）
            continue
        if not popularity.is_famous(game, p.get("platform", "")):
            continue
        if not rom_available(p, lib, romset, vi):
            continue
        r = R.assess(p, lib, ri, vi, bh)
        if r["status"] != "replayable":
            continue
        seen_games.add(gl)
        mv = p.get("local_movie")
        movie_frames = expected_frames(str(lib / mv)) if mv else None
        cells.append({"game": game, "job_type": "playthrough", "pub_id": p["id"],
                      "source": "movie",
                      "frames": slice_frames(p.get("platform", ""), frames, movie_frames),
                      "audio": audio,
                      "template": TEMPLATE_BY_PLATFORM.get(
                          (p.get("platform") or "").upper(), "fc_tianma_cover")})
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


def run_matrix(cells, out_root, lib=None, skip_done=True, dry_run=False, on_cell=None, allow=(),
               workers=1, work_root=None):
    """逐格跑 auto。返回 {cells:[...], coverage:{...}}；workers>1 时按隔离槽并行。"""
    if type(workers) is not int or workers < 1:
        raise ValueError("workers 须为正整数")
    out_root = str(out_root)
    results = [None] * len(cells)
    pending = []
    seen_slugs = set()
    callback_lock = threading.Lock()

    def notify(rec):
        if on_cell:
            with callback_lock:
                on_cell(rec)

    def skipped_record(spec, why, doc):
        return {"game": spec.game, "job_type": spec.job_type, "source": spec.source,
                "slug": spec.slug(), "action": "skipped", "status": "done",
                "verdict": doc.get("verdict"), "reason": why,
                "deliverable_ref": doc.get("deliverable_ref")}

    def ran_record(spec, doc):
        return {"game": spec.game, "job_type": spec.job_type, "source": spec.source,
                "slug": spec.slug(), "action": "planned" if dry_run else "ran",
                "status": doc.get("status"), "verdict": doc.get("verdict"),
                "frames": spec.frames, "failed_stage": doc.get("failed_stage"),
                "deliverable_ref": doc.get("deliverable_ref"),
                "reason": "; ".join(b.get("reason", "") for b in doc.get("blockers", []))[:120]}

    for index, cd in enumerate(cells):
        spec = JobSpec.from_dict(cd)
        try:
            spec.validate()
        except Exception as e:
            results[index] = {"game": spec.game, "job_type": spec.job_type, "slug": spec.slug(),
                              "action": "invalid", "status": "blocked", "verdict": None,
                              "reason": str(e)}
            notify(results[index])
            continue
        if spec.slug() in seen_slugs:
            results[index] = {"game": spec.game, "job_type": spec.job_type, "slug": spec.slug(),
                              "action": "invalid", "status": "blocked", "verdict": None,
                              "reason": "矩阵内 slug 重复；并行写入会争抢同一 job.json"}
            notify(results[index])
            continue
        seen_slugs.add(spec.slug())
        if skip_done and not dry_run:
            done, why = cell_done(spec, out_root, lib)
            if done:
                jf = Path(out_root) / spec.slug() / "job.json"
                doc = json.loads(jf.read_text(encoding="utf-8"))
                results[index] = skipped_record(spec, why, doc)
                notify(results[index])
                continue
        pending.append((index, spec))

    execution = None
    if workers == 1 or dry_run:
        for index, spec in pending:
            doc = orchestrate(spec, lib=lib, out_dir=out_root, dry_run=dry_run, allow=allow)
            results[index] = ran_record(spec, doc)
            notify(results[index])
    elif pending:
        from .parallel import EmulatorSlots
        slots = EmulatorSlots(workers=workers, root=work_root)
        execution = slots.report()

        def run_cell(item):
            index, spec = item
            try:
                doc = orchestrate(spec, lib=lib, out_dir=out_root, dry_run=False,
                                  allow=allow, emulator_slots=slots)
                return index, ran_record(spec, doc)
            except Exception as e:
                return index, {"game": spec.game, "job_type": spec.job_type,
                               "source": spec.source, "slug": spec.slug(), "action": "ran",
                               "status": "failed", "verdict": Verdict.FAIL.value,
                               "failed_stage": "scheduler", "deliverable_ref": None,
                               "reason": f"{type(e).__name__}: {e}"}

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tas_matrix") as pool:
            futures = [pool.submit(run_cell, item) for item in pending]
            for future in as_completed(futures):
                index, rec = future.result()
                results[index] = rec
                notify(rec)
        execution = slots.report()

    coverage = _coverage(results)
    report = {"cells": results, "coverage": coverage, "total": len(results)}
    if execution is not None:
        report["execution"] = execution
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
              f" verdict={r.get('verdict')}"
              + (f" frames={r['frames']}" if r.get("frames") else "")
              + (f" | {r['reason']}" if r.get("reason") else ""))


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
    f.add_argument("--allow", default=None, help="逗号分隔闸门码，降级留痕")
    f.add_argument("--workers", type=int, default=1, help="并发 job 数；每个 worker 一个隔离 BizHawk 副本")
    f.add_argument("--work-root", default=None, help="隔离副本与回放证据的 ASCII 工作根目录")
    r = sub.add_parser("run", help="跑自定义矩阵 JSON")
    r.add_argument("--matrix", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--lib", default=None)
    r.add_argument("--plan", action="store_true")
    r.add_argument("--no-skip", action="store_true")
    r.add_argument("--allow", default=None, help="逗号分隔闸门码，降级留痕")
    r.add_argument("--workers", type=int, default=1, help="并发 job 数；每个 worker 一个隔离 BizHawk 副本")
    r.add_argument("--work-root", default=None, help="隔离副本与回放证据的 ASCII 工作根目录")
    s = sub.add_parser("status", help="从落盘 job.json 现查覆盖")
    s.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.cmd == "status":
        print(json.dumps(status(args.out), ensure_ascii=False, indent=1))
        return 0
    if args.workers < 1:
        ap.error("--workers 须为正整数")
    if args.cmd == "famous":
        cells = famous_playthrough_cells(args.lib, exclude=args.exclude.split(","),
                                         frames=args.frames, audio=args.audio)
    else:
        cells = load_matrix(args.matrix)
    if not cells:
        print("矩阵为空（无可回放名作或 cells 空）", file=sys.stderr)
        return 1
    report = run_matrix(cells, args.out, lib=args.lib, skip_done=not args.no_skip,
                        dry_run=args.plan, on_cell=lambda rec: None,
                        allow=tuple(a.strip() for a in (args.allow or "").split(",") if a.strip()),
                        workers=args.workers, work_root=args.work_root)
    _print_report(report)
    cov = report["coverage"]
    return 0 if cov.get("failed", 0) == 0 and cov.get("blocked", 0) == 0 else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())