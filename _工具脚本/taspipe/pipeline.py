# -*- coding: utf-8 -*-
"""M8：可续跑调度器 —— 把 FC 产品链拆成 CAPTURE / EXPORT 两阶段，按台账指纹复用。

中断后只补缺失阶段：CAPTURE 已 done 且指纹/产物校验通过 => 跳过回放（长片不用从头录）；
EXPORT 缺失/失效 => 只重跑合成。旧文件不冒充新产物：复用须指纹+sha256 双重校验，重跑写
新 attempt 文件名；失败现场保留：台账 entries 追加式，fail 不覆盖历史。

运行:
  python -m taspipe.pipeline run --pub 5246 --out <dir> [--frames N] [--audio] [--template fc_tianma_cover]
  python -m taspipe.pipeline status --out <dir>
"""
import argparse
import hashlib
import json
import os
import sys

from .schema import Stage, FailureCode, asset
from .ledger import Ledger, fingerprint
from . import record, exporter


def run_chain(movie, rom, out_dir, bizhawk_dir, profile_id, frames=None, fps=60.0988,
              audio=False, core="NesHawk", system="NES",
              template=exporter.DEFAULT_TEMPLATE, ffmpeg="ffmpeg", ffprobe="ffprobe",
              resume=True):
    from .backends import BizHawkNESBackend
    out_dir = str(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    led = Ledger(os.path.join(out_dir, "ledger.json"))
    be = BizHawkNESBackend(bizhawk_dir)
    prof = {"profile_id": profile_id}

    # ---- CAPTURE ----
    cap_fp = fingerprint([movie, rom], {"frames": frames, "fps": fps, "audio": audio,
                                        "core": core, "system": system,
                                        "bizhawk": str(bizhawk_dir), "profile": profile_id})
    cap_job = None
    reuse = led.reusable(Stage.CAPTURE, "capture", cap_fp) if resume else None
    if reuse:
        raw = reuse["artifact_refs"][0]["uri"]
        reused_capture = True
    else:
        reused_capture = False
        cap_job = led.register(Stage.CAPTURE, "capture", cap_fp)
        try:
            cap = record.run_full(be, prof, movie, rom, out_dir, frames=frames, fps=fps,
                                  ffmpeg=ffmpeg, ffprobe=ffprobe, core=core, system=system,
                                  audio=audio, bezel="off")
        except Exception as e:
            led.fail(cap_job, FailureCode.NONDETERMINISM, f"{type(e).__name__}: {e}")
            raise
        raw = cap["deliverable_ref"]
        v = cap["verification"]["verdict"]
        if v == "fail":
            code = (FailureCode.DETERMINISTIC_DIVERGENCE if cap.get("desync") is True
                    else FailureCode.NONDETERMINISM)
            led.fail(cap_job, code, f"capture verdict=fail desync={cap.get('desync')}")
            return {"deliverable_ref": None, "failed_stage": "capture",
                    "reused_capture": False, "reused_export": False, "ledger": led.summary()}
        run_json = os.path.join(out_dir, cap["run_id"] + ".run.json")
        led.complete(cap_job, [raw, run_json], v)

    # ---- EXPORT ----
    sha1 = hashlib.sha1(open(rom, "rb").read()).hexdigest().upper()
    tpl_path = os.path.join(exporter.template_dir(), template + ".json")
    exp_fp = fingerprint([raw, tpl_path], {"sha1": sha1, "template": template})
    reuse_e = led.reusable(Stage.EXPORT, "export", exp_fp) if resume else None
    if reuse_e:
        bordered = reuse_e["artifact_refs"][0]["uri"]
        reused_export = True
    else:
        reused_export = False
        exp_job = led.register(Stage.EXPORT, "export", exp_fp, deps=[cap_job or "capture:reuse"])
        bordered = os.path.join(out_dir, exp_job.replace(":", "_") + "_bordered.mp4")
        br = exporter.compose(raw, bordered, rom_sha1=sha1, template=template,
                              ffmpeg=ffmpeg, ffprobe=ffprobe)
        v = br["verification"]["verdict"]
        if v == "fail":
            led.fail(exp_job, FailureCode.CAPTURE_WRONG_SEGMENT, "export verdict=fail")
            return {"deliverable_ref": None, "failed_stage": "export",
                    "reused_capture": reused_capture, "reused_export": False,
                    "ledger": led.summary()}
        exp_json = os.path.join(out_dir, br["run_id"] + ".export.json")
        led.complete(exp_job, [bordered, exp_json], v)

    return {"deliverable_ref": bordered, "failed_stage": None,
            "reused_capture": reused_capture, "reused_export": reused_export,
            "ledger": led.summary()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--pub", default="5246")
    r.add_argument("--out", required=True)
    r.add_argument("--frames", type=int, default=None)
    r.add_argument("--fps", type=float, default=60.0988)
    r.add_argument("--audio", action="store_true")
    r.add_argument("--template", default=exporter.DEFAULT_TEMPLATE)
    r.add_argument("--no-resume", action="store_true")
    r.add_argument("--ffmpeg", default="ffmpeg")
    r.add_argument("--ffprobe", default="ffprobe")
    s = sub.add_parser("status")
    s.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.cmd == "status":
        led = Ledger(os.path.join(args.out, "ledger.json"))
        print(json.dumps(led.summary(), ensure_ascii=False, indent=1))
        for e in led.entries:
            print(f"  {e['job_id']} {e['status']} verdict={e['verification_verdict']} "
                  f"fail={e['failure_code']}")
        return 0

    from .backends import _nes_backend_from_registry
    be, prof, movie, rom = _nes_backend_from_registry(args.pub)
    res = run_chain(movie, rom, args.out, be.bizhawk_dir, prof["profile_id"],
                    frames=args.frames, fps=args.fps, audio=args.audio,
                    template=args.template, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe,
                    resume=not args.no_resume)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["failed_stage"] is None else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())