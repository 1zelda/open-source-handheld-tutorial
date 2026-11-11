# -*- coding: utf-8 -*-
"""配置驱动编排器（auto 设计主体）：输入游戏名 + 任务类型 → 自动跑完出片，运行时零大模型。

把已有 M0–M10 生产模块串成一条可配置流水线，不重写它们：
  resolve（名→出版物，live assess）→ acquire（ROM/金手指，本地优先+门控）→ state（来源→机制，
  能力以 live probe 为准）→ capture（record/pipeline）→ detect（gamepack/clipper 受控插件）→
  clip+export（clipper/exporter）→ verify+ledger（指纹复用，失败分类）。

两条主 flow：
  * playthrough（B 通关）：委托 pipeline.run_chain（CAPTURE/EXPORT 指纹复用）→ 边框成片。
    这是泛化主力：任何 registry 判 replayable 的名作都能跑，无需逐游戏知识。
  * moves/items/transform/easter_egg（A 要素）：
      - source=movie/checkpoint：回放电影到要素帧窗 → clipper 切片+检测器验收 → 逐要素导出。
        要素帧窗+检测器来自离线 authored 的逐游戏包（运行时不生成、不调模型）。
      - source=arcade_move：FBNeo rig .fs 起手 → backends.run_move 一招一可用成片。
      - source=savestate/cheat：NES 已经 statejump.StateSession 接线（存档跳跃/RAM 读写/逐帧宏），
        能力转真须 验证/t3_statejump/report.json 全 pass 证据；无证据/缺资源 => statebuild 诚实 blocked，不伪装。

逐游戏知识（帧窗/检测器/招式记法）提前写在 packs/ 里（离线 authoring 可用 LLM）；本模块只消费。
红线沿用：不自动抓商业 ROM 全集；金手指/存档只索引本地；缺资源/缺能力 => 诚实 blocked。

运行:
  python -m taspipe.auto plan --game "Zelda" --type playthrough      # 干跑：只 resolve/acquire/state
  python -m taspipe.auto run  --game "Metroid" --type playthrough --frames 600 --out <dir>
  python -m taspipe.auto run  --spec job.json --out <dir>
  python -m taspipe.auto run  --game "KOF98" --type moves --source arcade_move --pack <pack.json> --out <dir>
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .schema import FailureCode, Verdict, Stage, CheckSpec, SchemaError, asset
from .ledger import Ledger, fingerprint
from . import registry as R
from . import acquire as AQ
from . import statebuild as SB

JOB_TYPES = ("playthrough", "moves", "items", "transform", "easter_egg")
SOURCES = ("movie", "checkpoint", "arcade_move", "savestate", "cheat")
_ELEMENT_TYPES = ("moves", "items", "transform", "easter_egg")


@dataclass
class JobSpec:
    game: str
    job_type: str
    pub_id: str = ""
    source: str = "movie"
    pack: str = ""
    elements: list = field(default_factory=list)
    frames: int = None
    fps: float = 60.0988
    audio: bool = False
    template: str = "fc_tianma_cover"
    out: str = ""
    cheat_query: str = ""
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"

    def validate(self):
        if not self.game or not self.game.strip():
            raise SchemaError("JobSpec 缺 game")
        if self.job_type not in JOB_TYPES:
            raise SchemaError(f"JobSpec.job_type 非法 {self.job_type!r}，允许 {JOB_TYPES}")
        if self.source not in SOURCES:
            raise SchemaError(f"JobSpec.source 非法 {self.source!r}，允许 {SOURCES}")
        if self.job_type in _ELEMENT_TYPES and not self.pack and not self.elements:
            raise SchemaError(f"要素任务 {self.job_type} 需 pack 或 elements（逐游戏知识，离线 authored）")
        if self.frames is not None and self.frames <= 0:
            raise SchemaError("JobSpec.frames 须为正整数或 None（整片）")
        return self

    @classmethod
    def from_dict(cls, d):
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})

    def slug(self):
        g = re.sub(r"[^a-z0-9]+", "_", self.game.lower()).strip("_")[:40]
        tail = self.pub_id or self.source
        return f"{g}_{self.job_type}_{tail}"


def load_elements(spec):
    """要素定义：优先 spec.elements 内联，否则读 spec.pack 的 elements。返回 list。"""
    if spec.elements:
        return list(spec.elements)
    if spec.pack:
        p = Path(spec.pack)
        if not p.is_file():
            raise SchemaError(f"要素包不存在: {spec.pack}")
        d = json.loads(p.read_text(encoding="utf-8"))
        return d.get("elements", [])
    return []


def resolve_job(spec, lib=None):
    """名→出版物 + live assess（不读 stale registry.json）。返回 (pub|None, assess|None)。
    arcade_move 不走 registry（KOF98 是 rig，不在 TASVideos 出版物里）=> (None, None)。"""
    if spec.source == "arcade_move":
        return None, None
    lib = Path(lib or R.DEFAULT_LIB)
    pubs = R.load_publications(lib)
    ri, vi, bh = R.index_roms(lib), R.index_versions(lib), R.discover_bizhawk(R.DEFAULT_EMU)
    if spec.pub_id:
        pub = next((p for p in pubs if p["id"] == spec.pub_id), None)
        if not pub:
            return None, {"status": "blocked", "blockers": [
                {"code": FailureCode.MISSING_RESOURCE.value, "reason": f"未知 pub_id {spec.pub_id}"}]}
        return pub, R.assess(pub, lib, ri, vi, bh)
    g = spec.game.strip().lower()
    cands = [p for p in pubs if g and g in p.get("game", "").lower()]
    if not cands:
        return None, {"status": "blocked", "blockers": [
            {"code": FailureCode.MISSING_RESOURCE.value, "reason": f"按名未找到出版物: {spec.game}"}]}
    assessed = [(p, R.assess(p, lib, ri, vi, bh)) for p in cands]
    ready = [(p, r) for p, r in assessed if r["status"] == "replayable"]
    return (ready or assessed)[0]


def _spec_fp_params(spec):
    """指纹参数排除 out（位置无关：同一输入+参数在不同输出目录应视为同一格，便于矩阵跳过）。"""
    return {k: v for k, v in asdict(spec).items() if k != "out"}


def expected_fingerprint(spec, lib=None):
    """不采集即算出本格指纹（resolve+acquire，cheap）。blocked => None。与 orchestrate 写入
    job.json 的 fp 同口径，供 matrix 判「已完成格」跳过。"""
    spec.validate()
    if spec.source == "arcade_move":
        return fingerprint([], {"spec": _spec_fp_params(spec)})
    pub, assess = resolve_job(spec, lib)
    if not pub or assess.get("status") != "replayable":
        return None
    acq = AQ.acquire(pub, lib, cheat_query=spec.cheat_query or None,
                     need_cheat=spec.source in ("cheat", "savestate"))
    if acq["status"] != "ready":
        return None
    inp = _nes_inputs(assess, acq["rom"])
    return fingerprint([inp["movie"], inp["rom"]], {"spec": _spec_fp_params(spec)})


def _nes_inputs(assess, rom):
    prof = assess["profile"]
    return {"movie": assess["movie"], "rom": rom,
            "bizhawk_dir": prof["capability_report"]["bizhawk_dir"],
            "profile_id": prof["profile_id"], "core": assess.get("core") or "NesHawk",
            "system": "NES"}


def _backend_caps(assess, source):
    from .backends import BizHawkNESBackend, FBNeoBackend
    if source == "arcade_move":
        return FBNeoBackend().probe()["capabilities"], "arcade_fbneo"
    bh = assess["profile"]["capability_report"]["bizhawk_dir"]
    return BizHawkNESBackend(bh).probe()["capabilities"], "nes_bizhawk"


def plan(spec, lib=None, netdisk_resolver=None):
    """干跑：resolve + acquire + state，不采集。返回可执行性预判（auto 的 plan 子命令）。"""
    spec.validate()
    pub, assess = resolve_job(spec, lib)
    out = {"game": spec.game, "job_type": spec.job_type, "source": spec.source,
           "slug": spec.slug(), "stages": {}}
    if spec.source == "arcade_move":
        caps, backend_id = _backend_caps(None, "arcade_move")
        st = SB.build_state("arcade_move", "kof98eck", caps)
        out["stages"]["resolve"] = {"status": "ready", "backend": "arcade_fbneo（rig，不走 registry）"}
        out["stages"]["acquire"] = {"status": "ready", "note": "街机 ROM/BIOS 由 rig 管理"}
        out["stages"]["state"] = st
        out["status"] = "ready" if st["status"] == "ready" else "blocked"
        out["elements"] = len(load_elements(spec)) if (spec.pack or spec.elements) else 0
        return out
    if not pub or assess.get("status") != "replayable":
        out["stages"]["resolve"] = {"status": "blocked",
                                    "blockers": (assess or {}).get("blockers", [])}
        out["status"] = "blocked"
        return out
    out["stages"]["resolve"] = {"status": "ready", "pub_id": pub["id"],
                                "game": pub.get("game"), "core": assess.get("core"),
                                "platform": assess.get("platform_code")}
    need_cheat = spec.source in ("cheat", "savestate")
    acq = AQ.acquire(pub, lib, netdisk_resolver=netdisk_resolver,
                     cheat_query=spec.cheat_query or None, need_cheat=need_cheat)
    out["stages"]["acquire"] = acq
    if acq["status"] != "ready":
        out["status"] = "blocked"
        return out
    caps, backend_id = _backend_caps(assess, spec.source)
    st = SB.build_state(spec.source, assess["profile"]["profile_id"], caps,
                        cheat=(acq["cheat"]["entries"][0]["abs_path"]
                               if acq["cheat"]["status"] == "found" else None))
    out["stages"]["state"] = st
    out["status"] = "ready" if st["status"] == "ready" else "blocked"
    if spec.job_type in _ELEMENT_TYPES:
        try:
            out["elements"] = len(load_elements(spec))
        except SchemaError as e:
            out["elements"] = 0
            out["stages"]["elements"] = {"status": "blocked", "reason": str(e)}
            out["status"] = "blocked"
    return out


def _write_job(out_dir, doc):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    p = Path(out_dir) / "job.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(p)


def run_playthrough(spec, pub, assess, acq, out_dir):
    from . import pipeline
    inp = _nes_inputs(assess, acq["rom"])
    res = pipeline.run_chain(inp["movie"], inp["rom"], out_dir, inp["bizhawk_dir"],
                             inp["profile_id"], frames=spec.frames, fps=spec.fps,
                             audio=spec.audio, core=inp["core"], system=inp["system"],
                             template=spec.template, ffmpeg=spec.ffmpeg, ffprobe=spec.ffprobe)
    ok = res["failed_stage"] is None and res["deliverable_ref"]
    return {"status": "done" if ok else "failed",
            "verdict": Verdict.PASS.value if ok else Verdict.FAIL.value,
            "deliverable_ref": res["deliverable_ref"], "failed_stage": res["failed_stage"],
            "reused_capture": res["reused_capture"], "reused_export": res["reused_export"],
            "ledger": res["ledger"]}


def run_movie_elements(spec, pub, assess, acq, out_dir):
    """回放电影到要素帧窗 → 逐要素切片+检测器验收+导出。capture 一次，clip 多段。"""
    from . import record, clipper, exporter
    from .backends import BizHawkNESBackend
    elements = load_elements(spec)
    if not elements:
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                "blockers": [{"code": FailureCode.SCHEMA_INVALID.value, "reason": "无要素定义"}]}
    ranged = [e for e in elements if e.get("frame_range")]
    if not ranged:
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                "blockers": [{"code": FailureCode.SCHEMA_INVALID.value,
                              "reason": "movie 要素需 frame_range（帧窗），包里没有"}]}
    inp = _nes_inputs(assess, acq["rom"])
    out_dir = str(out_dir)
    led = Ledger(str(Path(out_dir) / "ledger.json"))
    be = BizHawkNESBackend(inp["bizhawk_dir"])
    prof = {"profile_id": inp["profile_id"]}
    max_end = max(int(e["frame_range"][1]) for e in ranged)
    cap_frames = spec.frames or (max_end + 60)

    cap_fp = fingerprint([inp["movie"], inp["rom"]],
                         {"frames": cap_frames, "fps": spec.fps, "audio": spec.audio,
                          "core": inp["core"], "bizhawk": inp["bizhawk_dir"]})
    reuse = led.reusable(Stage.CAPTURE, "capture", cap_fp)
    if reuse:
        raw = reuse["artifact_refs"][0]["uri"]
    else:
        cap_job = led.register(Stage.CAPTURE, "capture", cap_fp)
        try:
            cap = record.run_full(be, prof, inp["movie"], inp["rom"], out_dir,
                                  frames=cap_frames, fps=spec.fps, ffmpeg=spec.ffmpeg,
                                  ffprobe=spec.ffprobe, core=inp["core"], system=inp["system"],
                                  audio=spec.audio, bezel="off")
        except Exception as e:
            led.fail(cap_job, FailureCode.NONDETERMINISM, f"{type(e).__name__}: {e}")
            raise
        if cap["verification"]["verdict"] == "fail":
            led.fail(cap_job, FailureCode.DETERMINISTIC_DIVERGENCE, "capture verdict=fail")
            return {"status": "failed", "verdict": Verdict.FAIL.value, "failed_stage": "capture",
                    "ledger": led.summary()}
        raw = cap["deliverable_ref"]
        led.complete(cap_job, [raw, str(Path(out_dir) / (cap["run_id"] + ".run.json"))],
                     cap["verification"]["verdict"])

    import hashlib
    rom_sha1 = hashlib.sha1(Path(inp["rom"]).read_bytes()).hexdigest().upper()
    clips_dir = str(Path(out_dir) / "clips")
    results = []
    for el in ranged:
        eid = el["element_id"]
        start, end = int(el["frame_range"][0]), int(el["frame_range"][1])
        specs = [CheckSpec(**c) for c in el.get("success_checks", [])]
        cut_fp = fingerprint([raw], {"start": start, "end": end, "fps": spec.fps,
                                     "checks": [asdict(s) for s in specs]})
        reuse_c = led.reusable(Stage.CUT, eid, cut_fp)
        if reuse_c:
            clip_uri = reuse_c["artifact_refs"][0]["uri"]
            clip_v = reuse_c["verification_verdict"]
        else:
            cut_job = led.register(Stage.CUT, eid, cut_fp, deps=["capture"])
            rec = clipper.run_cut(raw, (start, end), spec.fps, specs, clips_dir,
                                  element_id=eid, ffmpeg=spec.ffmpeg, ffprobe=spec.ffprobe)
            clip_uri = rec["media"]["uri"]
            clip_v = rec["verification"]["verdict"]
            if clip_v == "fail":
                led.fail(cut_job, FailureCode.CAPTURE_WRONG_SEGMENT, f"clip {eid} verdict=fail")
            else:
                led.complete(cut_job, [clip_uri, str(Path(clips_dir) / (rec["clip_id"] + ".clip.json"))], clip_v)
        # 导出边框成片（检测器未过的片段不冒充可用素材）
        bordered = str(Path(out_dir) / f"{eid}_bordered.mp4")
        exp_fp = fingerprint([clip_uri], {"template": spec.template, "sha1": rom_sha1})
        reuse_e = led.reusable(Stage.EXPORT, eid, exp_fp)
        if reuse_e:
            exp_uri = reuse_e["artifact_refs"][0]["uri"]
            exp_v = reuse_e["verification_verdict"]
        else:
            exp_job = led.register(Stage.EXPORT, eid, exp_fp, deps=[f"cut:{eid}"])
            br = exporter.compose(clip_uri, bordered, rom_sha1=rom_sha1, template=spec.template,
                                  ffmpeg=spec.ffmpeg, ffprobe=spec.ffprobe)
            exp_uri = bordered
            exp_v = br["verification"]["verdict"]
            if exp_v == "fail":
                led.fail(exp_job, FailureCode.CAPTURE_WRONG_SEGMENT, f"export {eid} fail")
            else:
                led.complete(exp_job, [exp_uri, str(Path(out_dir) / (br["run_id"] + ".export.json"))], exp_v)
        results.append({"element_id": eid, "kind": el.get("kind"), "frame_range": [start, end],
                        "clip_verdict": clip_v, "export_verdict": exp_v,
                        "deliverable_ref": exp_uri if exp_v != "fail" else None})
    passed = sum(1 for r in results if r["clip_verdict"] == "pass" and r["export_verdict"] == "pass")
    verdict = (Verdict.PASS.value if passed == len(results)
               else Verdict.FAIL.value if any(r["clip_verdict"] == "fail" for r in results)
               else Verdict.INCONCLUSIVE.value)
    return {"status": "done" if passed == len(results) else "partial",
            "verdict": verdict, "elements": results, "passed": passed,
            "total": len(results), "ledger": led.summary()}


def run_arcade_moves(spec, out_dir):
    from .backends import FBNeoBackend
    elements = load_elements(spec)
    if not elements:
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                "blockers": [{"code": FailureCode.SCHEMA_INVALID.value, "reason": "无招式定义"}]}
    be = FBNeoBackend()
    out_dir = str(out_dir)
    led = Ledger(str(Path(out_dir) / "ledger.json"))
    results = []
    for el in elements:
        eid = el["element_id"]
        notation = el.get("notation")
        if not notation:
            results.append({"element_id": eid, "verdict": Verdict.INCONCLUSIVE.value,
                            "reason": "缺 notation"})
            continue
        slug = el.get("slug", eid)
        char = el.get("char", "kyo")
        ready, why = be.compile_check(notation)
        if not ready:
            results.append({"element_id": eid, "notation": notation,
                            "verdict": Verdict.INCONCLUSIVE.value,
                            "reason": f"记法编译不过（谱面符号需转编译器记法）：{why}"})
            continue
        mv_fp = fingerprint([], {"notation": notation, "char": char, "slug": slug,
                                 "state": el.get("state"), "approach": el.get("approach", 0)})
        reuse = led.reusable(Stage.CAPTURE, eid, mv_fp)
        if reuse:
            uri = reuse["artifact_refs"][0]["uri"]
            v = reuse["verification_verdict"]
        else:
            job = led.register(Stage.CAPTURE, eid, mv_fp)
            run = be.run_move(notation, slug, str(Path(out_dir) / eid), char=char,
                              state=el.get("state"), unmute=not el.get("mute", False),
                              approach=el.get("approach", 0), ffmpeg=spec.ffmpeg)
            v = run["verification"]["verdict"]
            uri = (run["recording_refs"][0]["uri"] if run["recording_refs"] else None)
            if v == "fail" or not uri:
                led.fail(job, FailureCode.UNSUPPORTED_CAPABILITY, f"move {eid} verdict={v}")
            else:
                led.complete(job, [uri, str(Path(out_dir) / eid / (run["run_id"] + ".run.json"))], v)
        results.append({"element_id": eid, "notation": notation, "verdict": v,
                        "deliverable_ref": uri})
    passed = sum(1 for r in results if r["verdict"] == "pass")
    verdict = (Verdict.PASS.value if passed == len(results)
               else Verdict.INCONCLUSIVE.value if passed == 0 else Verdict.PASS.value)
    return {"status": "done" if passed == len(results) else "partial",
            "verdict": verdict, "elements": results, "passed": passed,
            "total": len(results), "ledger": led.summary()}


def orchestrate(spec, lib=None, netdisk_resolver=None, out_dir=None, dry_run=False):
    """七阶段编排。dry_run=True 只到 state（plan）。返回 job 结果 dict（含 status/verdict）。"""
    spec.validate()
    if dry_run:
        return plan(spec, lib, netdisk_resolver)
    out_dir = str(out_dir or spec.out)
    if not out_dir:
        raise SchemaError("run 需 --out 或 spec.out")
    job_dir = str(Path(out_dir) / spec.slug())
    base = {"game": spec.game, "job_type": spec.job_type, "source": spec.source,
            "slug": spec.slug(), "pub_id": spec.pub_id}

    if spec.source == "arcade_move":
        caps, _ = _backend_caps(None, "arcade_move")
        st = SB.build_state("arcade_move", "kof98eck", caps)
        if st["status"] != "ready":
            doc = {**base, "status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                   "failed_stage": "state", "blockers": st["blockers"]}
            _write_job(job_dir, doc)
            return doc
        res = run_arcade_moves(spec, job_dir)
        doc = {**base, **res, "fp": fingerprint([], {"spec": _spec_fp_params(spec)})}
        _write_job(job_dir, doc)
        return doc

    pub, assess = resolve_job(spec, lib)
    if not pub or assess.get("status") != "replayable":
        doc = {**base, "status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
               "failed_stage": "resolve", "blockers": (assess or {}).get("blockers", [])}
        _write_job(job_dir, doc)
        return doc
    base["pub_id"] = pub["id"]
    need_cheat = spec.source in ("cheat", "savestate")
    acq = AQ.acquire(pub, lib, netdisk_resolver=netdisk_resolver,
                     cheat_query=spec.cheat_query or None, need_cheat=need_cheat)
    if acq["status"] != "ready":
        doc = {**base, "status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
               "failed_stage": "acquire", "blockers": acq["blockers"]}
        _write_job(job_dir, doc)
        return doc
    caps, _ = _backend_caps(assess, spec.source)
    st = SB.build_state(spec.source, assess["profile"]["profile_id"], caps,
                        cheat=(acq["cheat"]["entries"][0]["abs_path"]
                               if acq["cheat"]["status"] == "found" else None))
    if st["status"] != "ready":
        doc = {**base, "status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
               "failed_stage": "state", "blockers": st["blockers"]}
        _write_job(job_dir, doc)
        return doc

    inputs = _nes_inputs(assess, acq["rom"])
    fp = fingerprint([inputs["movie"], inputs["rom"]], {"spec": _spec_fp_params(spec)})
    if spec.job_type == "playthrough":
        res = run_playthrough(spec, pub, assess, acq, job_dir)
    else:
        res = run_movie_elements(spec, pub, assess, acq, job_dir)
    doc = {**base, **res, "fp": fp, "rom": acq["rom"], "movie": inputs["movie"]}
    _write_job(job_dir, doc)
    return doc


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "plan"):
        p = sub.add_parser(name)
        p.add_argument("--spec", default=None, help="JobSpec JSON 路径")
        p.add_argument("--game", default=None)
        p.add_argument("--type", dest="job_type", default=None, choices=JOB_TYPES)
        p.add_argument("--pub", dest="pub_id", default=None)
        p.add_argument("--source", default=None, choices=SOURCES)
        p.add_argument("--pack", default=None)
        p.add_argument("--frames", type=int, default=None)
        p.add_argument("--fps", type=float, default=None)
        p.add_argument("--audio", action="store_true", default=None)
        p.add_argument("--template", default=None)
        p.add_argument("--cheat-query", default=None)
        p.add_argument("--out", default=None)
        p.add_argument("--lib", default=None)
        p.add_argument("--ffmpeg", default=None)
        p.add_argument("--ffprobe", default=None)
    args = ap.parse_args()

    if args.spec:
        d = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        spec = JobSpec.from_dict(d)
    else:
        if not args.game or not args.job_type:
            ap.error("需 --spec 或 (--game 且 --type)")
        spec = JobSpec(game=args.game, job_type=args.job_type)
    # CLI 覆盖 spec 字段（仅显式给出的）
    for k in ("pub_id", "source", "pack", "frames", "fps", "audio", "template",
              "cheat_query", "out", "ffmpeg", "ffprobe"):
        v = getattr(args, k, None)
        if v is not None:
            setattr(spec, k, v)
    if args.out:
        spec.out = args.out
    try:
        spec.validate()
    except SchemaError as e:
        print(f"JobSpec 非法: {e}", file=sys.stderr)
        return 1
    res = orchestrate(spec, lib=args.lib, out_dir=args.out or spec.out,
                      dry_run=(args.cmd == "plan"))
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if args.cmd == "plan":
        return 0 if res.get("status") == "ready" else 2
    return 0 if res.get("status") in ("done",) else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())