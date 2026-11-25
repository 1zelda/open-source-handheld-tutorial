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
      - source=savestate/cheat/showcase：消费 statejump_showcase 知识包，不依赖 TAS 出版物。
        cheat 必须有已明确的 trigger.patches；未编译的作弊候选不自动注入。
        共享 base 逐要素正/反例采集，
        清单齐全且全要素通过才生成正式合辑；单要素试跑走 showcase CLI --only，不冒充全量完成。

逐游戏知识（帧窗/检测器/招式记法）提前写在 packs/ 里（离线 authoring 可用 LLM）；本模块只消费。
红线沿用：不自动抓商业 ROM 全集；金手指/存档只索引本地；缺资源/缺能力 => 诚实 blocked。

运行:
  python -m taspipe.auto plan --game "Zelda" --type playthrough      # 干跑：只 resolve/acquire/state
  python -m taspipe.auto run  --game "Metroid" --type playthrough --frames 600 --out <dir>
  python -m taspipe.auto run  --spec job.json --out <dir>
  python -m taspipe.auto run  --game "KOF98" --type moves --source arcade_move --pack <pack.json> --out <dir>
"""
import argparse
import contextlib
import difflib
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

from .schema import FailureCode, Verdict, Stage, CheckSpec, SchemaError, asset
from .ledger import Ledger, fingerprint
from . import registry as R
from . import acquire as AQ
from . import statebuild as SB
from . import popularity

JOB_TYPES = ("playthrough", "moves", "items", "transform", "easter_egg")
SOURCES = ("movie", "checkpoint", "arcade_move", "savestate", "cheat", "showcase")
_ELEMENT_TYPES = ("moves", "items", "transform", "easter_egg")
_STATE_CAPTURE_SOURCES = ("showcase", "savestate", "cheat")


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
        """作业配置严格入库：未知键直接拒，不静默丢弃。

        静默过滤时一个拼错的 "fps"→"fps_" 或 "elements"→"element" 会让作业按默认值
        跑完并出片，看起来成功，实际跑的是另一回事；要素任务尤其危险（element 拼错 =
        整格没跑）。报错里给最接近的合法键名。
        """
        known = sorted(cls.__dataclass_fields__)
        unknown = [k for k in d if k not in known]
        if unknown:
            raise SchemaError("JobSpec 未知字段 " + "、".join(
                f"{k}（最接近 {'、'.join(difflib.get_close_matches(str(k), known, 3)) or '无'}）"
                for k in unknown)
                + f"；允许 {known}")
        return cls(**d)

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
    """名→出版物 + live 身份解析（不读 stale registry.json）。返回 (pub|None, assess|None)。

    只判身份（电影/平台/核心/BizHawk/所需哈希），ROM 在不在本地由 acquire 判：本地索引
    → 自有网盘钩子 → 外部门控。候选排序仍偏好在本地就能回放的那条，免得同一游戏有多条
    出版物时随机挑一条只能走网盘的，白跑一次获取。
    arcade_move 不走 registry（KOF98 是 rig，不在 TASVideos 出版物里）=> (None, None)。"""
    if spec.source == "arcade_move":
        return None, None
    lib = Path(lib or R.DEFAULT_LIB)
    pubs = R.load_publications(lib)
    ri, vi, bh = R.index_roms(lib), R.index_versions(lib), R.discover_bizhawk(R.DEFAULT_EMU)
    if spec.pub_id:
        pub = next((p for p in pubs if p["id"] == spec.pub_id), None)
        if not pub:
            return None, {"status": "blocked", "identity_status": "unresolved", "blockers": [
                {"code": FailureCode.MISSING_RESOURCE.value, "reason": f"未知 pub_id {spec.pub_id}"}]}
        return pub, R.assess(pub, lib, ri, vi, bh)
    g = spec.game.strip().lower()
    cands = [p for p in pubs if g and g in p.get("game", "").lower()]
    if not cands:
        return None, {"status": "blocked", "identity_status": "unresolved", "blockers": [
            {"code": FailureCode.MISSING_RESOURCE.value, "reason": f"按名未找到出版物: {spec.game}"}]}
    assessed = [(p, R.assess(p, lib, ri, vi, bh)) for p in cands]
    for key, want in (("status", "replayable"), ("identity_status", "resolved")):
        hit = [(p, r) for p, r in assessed if r.get(key) == want]
        if hit:
            return hit[0]
    return assessed[0]


def _spec_fp_params(spec):
    """指纹参数排除 out（位置无关：同一输入+参数在不同输出目录应视为同一格，便于矩阵跳过）。"""
    return {k: v for k, v in asdict(spec).items() if k != "out"}


def _state_capture_plan(spec, netdisk_resolver=None, lib=None):
    from . import showcase

    reasons = []
    if lib is not None:
        reasons.append("状态采集不接受 lib/--lib；请在知识包中指定 ROM 路径或使用按哈希解析的资源钩子")
    if spec.job_type not in _ELEMENT_TYPES:
        reasons.append("状态采集只支持要素任务；完整通关请使用 movie/checkpoint 路线")
    if not spec.pack:
        reasons.append("状态采集需 statejump_showcase 知识包，包含版本、初态、动作和判据")
    if spec.elements:
        reasons.append("状态采集只消费 pack.elements，不接受内联 elements 覆盖")
    if spec.pub_id:
        reasons.append("状态采集由知识包绑定版本，不接受 pub_id")
    if spec.frames is not None:
        reasons.append("状态采集帧数由逐要素 trigger 决定，不接受全局 frames")
    if spec.cheat_query:
        reasons.append("cheat_query 只用于候选检索；请把已确认补丁写入 trigger.patches")
    if reasons:
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                "blockers": [{"code": FailureCode.SCHEMA_INVALID.value, "reason": reason}
                             for reason in reasons]}
    result = showcase.plan(spec.pack, netdisk_resolver=netdisk_resolver, audio=spec.audio)
    if spec.source == "cheat" and result.get("status") == "ready" and not result["patch_elements"]:
        result["blockers"].append({"code": FailureCode.SCHEMA_INVALID.value,
                                   "reason": "source=cheat 需至少一个要素有 trigger.patches；有存档但无补丁请用 savestate"})
        result["status"] = "blocked"
        result["verdict"] = Verdict.INCONCLUSIVE.value
    return result


def expected_fingerprint(spec, lib=None, netdisk_resolver=None):
    """不采集即算出本格指纹（resolve+acquire，cheap）。blocked => None。与 orchestrate 写入
    job.json 的 fp 同口径，供 matrix 判「已完成格」跳过。

    ROM 只在网盘时，注入 resolver 才算得出指纹；否则同一格每次跑都被当成未完成重跑。
    """
    spec.validate()
    if spec.source in _STATE_CAPTURE_SOURCES:
        from . import showcase
        if _state_capture_plan(spec, netdisk_resolver, lib=lib)["status"] != "ready":
            return None
        try:
            files = showcase.resource_files(spec.pack, netdisk_resolver=netdisk_resolver)
        except SchemaError:
            return None
        return fingerprint(files, {"spec": _spec_fp_params(spec)})
    if spec.source == "arcade_move":
        return fingerprint([], {"spec": _spec_fp_params(spec)})
    pub, assess = resolve_job(spec, lib)
    if not pub or assess.get("identity_status") != "resolved":
        return None
    acq = AQ.acquire(pub, lib, netdisk_resolver=netdisk_resolver,
                     cheat_query=spec.cheat_query or None,
                     need_cheat=spec.source in ("cheat", "savestate"))
    if acq["status"] != "ready":
        return None
    inp = _nes_inputs(assess, acq["rom"])
    return fingerprint([inp["movie"], inp["rom"]], {"spec": _spec_fp_params(spec)})


_BIZHAWK_SYSTEM = R.BIZHAWK_SYSTEMS


def _nes_inputs(assess, rom):
    """回放输入：核心名取电影 Header 的 Core，系统名必须按平台给。

    system 写死 "NES" 时，SNES 的电影会被塞进 NES 槽位（PreferredCores["NES"]="BSNESv115+"），
    BizHawk 找不到该平台的核心，片直接跑不出来。系统名只决定「用哪个平台的槽位」，
    核心名仍是电影自己声明的那个。
    """
    prof = assess["profile"]
    plat = str((assess or {}).get("platform_code") or "").upper()
    return {"movie": assess["movie"], "rom": rom,
            "bizhawk_dir": prof["capability_report"]["bizhawk_dir"],
            "profile_id": prof["profile_id"], "core": assess.get("core") or "NesHawk",
            "system": _BIZHAWK_SYSTEM.get(plat, "NES")}


def _backend_caps(assess, source):
    from .backends import BizHawkNESBackend, FBNeoBackend
    if source == "arcade_move":
        return FBNeoBackend().probe()["capabilities"], "arcade_fbneo"
    bh = assess["profile"]["capability_report"]["bizhawk_dir"]
    return BizHawkNESBackend(bh).probe()["capabilities"], "nes_bizhawk"


def _selection_gate(pub, assess, spec, allow=()):
    """选题闸门在编排层的落点（root《选题规则_只测热门作品_2026-11-22.md》）。

    control.plan 那一道只管 control CLI 这条入口；走 registry 的电影/要素任务
    根本不经过 control.plan，冷门作品会被直接开跑。这里把同一把尺子接到编排层，
    判定用解析出的出版物身份（pub.game + 平台），不靠用户口述的名字。

    返回 (blocker|None, warnings)：allow 里点名的 code 降级成 warning 并留痕，
    其余一律挡住。"""
    info = {"game": (pub or {}).get("game") or spec.game,
            "platform": (assess or {}).get("platform_code")
                        or (pub or {}).get("platform") or ""}
    blocker = popularity.gate_blocker(info)
    if not blocker:
        return None, []
    if blocker["code"] in set(allow or ()):
        return None, [blocker]
    return blocker, []


def plan(spec, lib=None, netdisk_resolver=None, allow=()):
    """干跑：resolve + acquire + state，不采集。返回可执行性预判（auto 的 plan 子命令）。"""
    spec.validate()
    out = {"game": spec.game, "job_type": spec.job_type, "source": spec.source,
           "slug": spec.slug(), "stages": {}}
    if spec.source in _STATE_CAPTURE_SOURCES:
        res = _state_capture_plan(spec, netdisk_resolver, lib=lib)
        out["stages"]["showcase"] = res
        out["status"] = res["status"]
        out["elements"] = res.get("elements", 0)
        out["blockers"] = res.get("blockers", [])
        return out
    if spec.source == "arcade_move":
        caps, backend_id = _backend_caps(None, "arcade_move")
        st = SB.build_state("arcade_move", "kof98eck", caps)
        out["stages"]["resolve"] = {"status": "ready", "backend": "arcade_fbneo（rig，不走 registry）"}
        out["stages"]["acquire"] = {"status": "ready", "note": "街机 ROM/BIOS 由 rig 管理"}
        out["stages"]["state"] = st
        out["status"] = "ready" if st["status"] == "ready" else "blocked"
        out["elements"] = len(load_elements(spec)) if (spec.pack or spec.elements) else 0
        return out
    pub, assess = resolve_job(spec, lib)
    if not pub or assess.get("identity_status") != "resolved":
        out["stages"]["resolve"] = {"status": "blocked",
                                    "blockers": (assess or {}).get("blockers", [])}
        out["status"] = "blocked"
        return out
    out["stages"]["resolve"] = {"status": "ready", "pub_id": pub["id"],
                                "game": pub.get("game"), "core": assess.get("core"),
                                "platform": assess.get("platform_code")}
    gate, warnings = _selection_gate(pub, assess, spec, allow)
    if gate:
        out["stages"]["popularity"] = {"status": "blocked", "blockers": [gate]}
        out["status"] = "blocked"
        return out
    if warnings:
        out["stages"]["popularity"] = {"status": "ready", "warnings": warnings}
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


def _job_verdict(ok, stage_verdicts):
    """把台账里各阶段的 verdict 收成 job 级 verdict：fail > inconclusive > pass。

    旧口径是「没崩且有成片文件 = pass」，于是 capture/export 两格都写着 inconclusive
    （11-22 F-Zero 7406：音频那一格没验，job 却报 pass）的活被说成通过。
    空台账同样不给 pass——没有证据就不算验过。
    """
    vs = list(stage_verdicts or [])
    if not ok or Verdict.FAIL.value in vs:
        return Verdict.FAIL.value
    if not vs or Verdict.INCONCLUSIVE.value in vs:
        return Verdict.INCONCLUSIVE.value
    return Verdict.PASS.value


def run_playthrough(spec, pub, assess, acq, out_dir, bizhawk_dir=None, work_root=None):
    from . import pipeline
    inp = _nes_inputs(assess, acq["rom"])
    if bizhawk_dir is not None:
        inp["bizhawk_dir"] = str(bizhawk_dir)
    res = pipeline.run_chain(inp["movie"], inp["rom"], out_dir, inp["bizhawk_dir"],
                             inp["profile_id"], frames=spec.frames, fps=spec.fps,
                             audio=spec.audio, core=inp["core"], system=inp["system"],
                             template=spec.template, ffmpeg=spec.ffmpeg, ffprobe=spec.ffprobe,
                             work_root=work_root)
    ok = res["failed_stage"] is None and res["deliverable_ref"]
    stage_vs = [e.get("verification_verdict") or Verdict.INCONCLUSIVE.value
                for e in Ledger(str(Path(out_dir) / "ledger.json")).entries]
    return {"status": "done" if ok else "failed",
            "verdict": _job_verdict(ok, stage_vs), "stage_verdicts": stage_vs,
            "deliverable_ref": res["deliverable_ref"], "failed_stage": res["failed_stage"],
            "reused_capture": res["reused_capture"], "reused_export": res["reused_export"],
            "ledger": res["ledger"]}


def run_movie_elements(spec, pub, assess, acq, out_dir, bizhawk_dir=None, work_root=None):
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
    fp_bizhawk = inp["bizhawk_dir"]
    if bizhawk_dir is not None:
        inp["bizhawk_dir"] = str(bizhawk_dir)
    out_dir = str(out_dir)
    led = Ledger(str(Path(out_dir) / "ledger.json"))
    be = BizHawkNESBackend(inp["bizhawk_dir"])
    prof = {"profile_id": inp["profile_id"]}
    max_end = max(int(e["frame_range"][1]) for e in ranged)
    cap_frames = spec.frames or (max_end + 60)

    cap_fp = fingerprint([inp["movie"], inp["rom"]],
                         {"frames": cap_frames, "fps": spec.fps, "audio": spec.audio,
                          "core": inp["core"], "bizhawk": fp_bizhawk})
    reuse = led.reusable(Stage.CAPTURE, "capture", cap_fp)
    if reuse:
        raw = reuse["artifact_refs"][0]["uri"]
    else:
        cap_job = led.register(Stage.CAPTURE, "capture", cap_fp)
        try:
            replay_work = (tempfile.mkdtemp(prefix="elements_", dir=work_root)
                           if work_root else None)
            cap = record.run_full(be, prof, inp["movie"], inp["rom"], out_dir,
                                  frames=cap_frames, fps=spec.fps, ffmpeg=spec.ffmpeg,
                                  ffprobe=spec.ffprobe, core=inp["core"], system=inp["system"],
                                  audio=spec.audio, bezel="off", work=replay_work)
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

    from .schema import sha1_resource
    rom_sha1 = sha1_resource(inp["rom"]).upper()
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


def orchestrate(spec, lib=None, netdisk_resolver=None, out_dir=None, dry_run=False, allow=(),
                emulator_slots=None):
    """七阶段编排。dry_run=True 只到 state（plan）。返回 job 结果 dict（含 status/verdict）。"""
    spec.validate()
    if dry_run:
        return plan(spec, lib, netdisk_resolver, allow=allow)
    out_dir = str(out_dir or spec.out)
    if not out_dir:
        raise SchemaError("run 需 --out 或 spec.out")
    job_dir = str(Path(out_dir) / spec.slug())
    base = {"game": spec.game, "job_type": spec.job_type, "source": spec.source,
            "slug": spec.slug(), "pub_id": spec.pub_id}

    if spec.source in _STATE_CAPTURE_SOURCES:
        from . import showcase
        pre = _state_capture_plan(spec, netdisk_resolver, lib=lib)
        if pre["status"] != "ready":
            doc = {**base, "status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                   "failed_stage": "state_contract", "blockers": pre["blockers"], "fp": None}
            _write_job(job_dir, doc)
            return doc
        if emulator_slots is None:
            res = showcase.run(spec.pack, job_dir, template=spec.template, fps=spec.fps,
                               ffmpeg=spec.ffmpeg, ffprobe=spec.ffprobe, audio=spec.audio,
                               netdisk_resolver=netdisk_resolver)
        else:
            with emulator_slots.lease(pre["resources"]["bizhawk"],
                                      system=pre["system"], core=pre["core"]) as slot:
                res = showcase.run(spec.pack, job_dir, template=spec.template, fps=spec.fps,
                                   ffmpeg=spec.ffmpeg, ffprobe=spec.ffprobe, audio=spec.audio,
                                   netdisk_resolver=netdisk_resolver,
                                   bizhawk_dir=slot.path, work_dir=slot.work)
        try:
            fp = fingerprint(showcase.resource_files(spec.pack,
                                                    netdisk_resolver=netdisk_resolver),
                             {"spec": _spec_fp_params(spec)})
        except SchemaError:
            fp = None
        doc = {**base, **res, "fp": fp,
               "execution": {"backend": "statejump_showcase", "mechanism": pre["mechanism"],
                             "patch_elements": pre["patch_elements"],
                             "rom_sha1": pre["required_rom_sha1"]}}
        _write_job(job_dir, doc)
        return doc

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
    if not pub or assess.get("identity_status") != "resolved":
        doc = {**base, "status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
               "failed_stage": "resolve", "blockers": (assess or {}).get("blockers", [])}
        _write_job(job_dir, doc)
        return doc
    base["pub_id"] = pub["id"]
    gate, warnings = _selection_gate(pub, assess, spec, allow)
    if gate:
        doc = {**base, "status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
               "failed_stage": "selection", "blockers": [gate]}
        _write_job(job_dir, doc)
        return doc
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
    with contextlib.ExitStack() as stack:
        slot = None
        if emulator_slots is not None:
            slot = stack.enter_context(emulator_slots.lease(
                inputs["bizhawk_dir"], system=inputs["system"], core=inputs["core"]))
            stack.enter_context(slot.exclusive())
        run_kwargs = {"bizhawk_dir": slot.path if slot else None,
                      "work_root": slot.work if slot else None}
        if spec.job_type == "playthrough":
            res = run_playthrough(spec, pub, assess, acq, job_dir, **run_kwargs)
        else:
            res = run_movie_elements(spec, pub, assess, acq, job_dir, **run_kwargs)
    doc = {**base, **res, "fp": fp, "rom": acq["rom"], "movie": inputs["movie"]}
    if warnings:
        doc["warnings"] = warnings
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
        p.add_argument("--allow", default=None,
                       help="逗号分隔的闸门码，降级成 warning 并在产物里留痕"
                            "（例：title_off_popularity_list）")
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
    allow = tuple(a.strip() for a in (args.allow or "").split(",") if a.strip())
    res = orchestrate(spec, lib=args.lib, out_dir=args.out or spec.out,
                      dry_run=(args.cmd == "plan"), allow=allow)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if args.cmd == "plan":
        return 0 if res.get("status") == "ready" else 2
    return 0 if res.get("status") in ("done",) else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())