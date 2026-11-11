# -*- coding: utf-8 -*-
"""配置驱动状态构造层（auto 设计 state 阶段）：把「要素前一刻的状态」落到可执行机制。

三来源（schema.StateOrigin），能力一律以 backend.probe() 的 live capabilities 为准，不臆造：
  * normal_prefix   —— 电影从帧0正常回放（NES/FBNeo batch_replay 已验证）。要素若被现成 TAS
                       电影覆盖，就回放整片再按帧窗切片：这是 NES 要素最稳的状态路径（不依赖存档）。
  * tas_checkpoint  —— 已有 TAS 的检查点分支（同样靠电影回放定位，机制 = replay_movie）。
  * display_patch   —— 展示用状态修改（金手指 / 存档加载）。NES BizHawk 的 savestate 与
                       ram_read 已由 statejump.StateSession 接线，backends.probe 证据门控
                       （验证/t3_statejump/report.json 全 pass + BizHawk 可用）转真；无证据
                       时仍 supported=False => 诚实 UNSUPPORTED，不伪装能加载。FBNeo 有 rig .fs
                       存档（savestate=True），街机招式展示走此来源可用。

机制结论必须有消费方支撑：本模块只判「能不能」，真正回放/采集由 auto 调 record/pipeline/
backends.run_move 执行。缺能力 => MISSING_RESOURCE/UNSUPPORTED_CAPABILITY，证据不足不通过。

运行: python -m taspipe.statebuild --source movie --backend nes
      python -m taspipe.statebuild --source savestate --backend nes   # 无证据=>unsupported；有证据缺文件=>blocked
"""
import argparse
import json
import sys

from .schema import State, StateOrigin, FailureCode, to_dict

# source（jobspec）-> 需要的能力键 + 机制名。能力键对应 backends.probe().capabilities。
_SOURCE_MECHANISM = {
    "movie":       ("batch_replay", "replay_movie", StateOrigin.NORMAL_PREFIX),
    "checkpoint":  ("batch_replay", "replay_movie", StateOrigin.TAS_CHECKPOINT),
    "arcade_move": ("savestate", "arcade_move_fs", StateOrigin.DISPLAY_PATCH),
    "savestate":   ("savestate", "load_savestate", StateOrigin.DISPLAY_PATCH),
    "cheat":       ("ram_read", "apply_cheat", StateOrigin.DISPLAY_PATCH),
}


def _cap_supported(capabilities, key):
    c = (capabilities or {}).get(key)
    if isinstance(c, dict):
        return bool(c.get("supported")), c.get("evidence", "")
    return bool(c), ""


def build_state(source, profile_id, capabilities, state_id="st_auto",
                clock_position=0, cheat=None, savestate=None):
    """返回 {status, state, origin, mechanism, supported, blockers, capture_hint}。

    capabilities: backend.probe()['capabilities']（live）。source 未知 => SCHEMA_INVALID。
    能力不足 => 诚实 blocked（UNSUPPORTED_CAPABILITY），state 仍给出 origin 供台账记录，
    但 supported=False，auto 不得据此采集。
    """
    if source not in _SOURCE_MECHANISM:
        return {"status": "blocked", "state": None, "origin": None, "mechanism": None,
                "supported": False,
                "blockers": [{"code": FailureCode.SCHEMA_INVALID.value,
                              "reason": f"未知 state source: {source}（允许 {sorted(_SOURCE_MECHANISM)}）"}]}
    cap_key, mechanism, origin = _SOURCE_MECHANISM[source]
    ok, evidence = _cap_supported(capabilities, cap_key)
    st = State(state_id=state_id, profile_id=profile_id, origin=origin,
               clock_position=clock_position,
               rebuild_recipe_ref=mechanism).validate()
    blockers = []
    if not ok:
        code = (FailureCode.UNSUPPORTED_CAPABILITY
                if origin == StateOrigin.DISPLAY_PATCH else FailureCode.MISSING_RESOURCE)
        blockers.append({"code": code.value,
                         "reason": f"{source} 需能力 {cap_key}，当前 supported=False：{evidence or '未接线/未验证'}"})
    # display_patch 还需实际资源（存档/金手指），即便能力接线了缺资源也 blocked
    if origin == StateOrigin.DISPLAY_PATCH and ok:
        if mechanism == "load_savestate" and not savestate:
            blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                             "reason": "load_savestate 需 savestate 文件，未提供"})
        if mechanism == "apply_cheat" and not cheat:
            blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                             "reason": "apply_cheat 需金手指代码/文件，未提供"})
    status = "ready" if ok and not blockers else "blocked"
    return {"status": status, "state": to_dict(st), "origin": origin.value,
            "mechanism": mechanism, "supported": ok and not blockers,
            "blockers": blockers,
            "capture_hint": {"mechanism": mechanism, "clock_position": clock_position,
                             "savestate": savestate, "cheat": cheat}}


def _probe_capabilities(backend):
    from .backends import BizHawkNESBackend, FBNeoBackend
    from . import registry as R
    if backend == "fbneo":
        return FBNeoBackend().probe()["capabilities"]
    bh = R.discover_bizhawk(R.DEFAULT_EMU).get("2.8")
    return BizHawkNESBackend(bh).probe()["capabilities"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, choices=sorted(_SOURCE_MECHANISM))
    ap.add_argument("--backend", default="nes", choices=["nes", "fbneo"])
    ap.add_argument("--profile", default="probe_profile")
    ap.add_argument("--savestate", default=None)
    ap.add_argument("--cheat", default=None)
    args = ap.parse_args()
    caps = _probe_capabilities(args.backend)
    res = build_state(args.source, args.profile, caps,
                      savestate=args.savestate, cheat=args.cheat)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["status"] == "ready" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())