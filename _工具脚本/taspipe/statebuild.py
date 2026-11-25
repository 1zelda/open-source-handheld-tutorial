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
from pathlib import Path

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
    from .backends import BizHawkNESBackend
    from . import registry as R
    if backend == "fbneo":
        from .backends import FBNeoBackend
        return FBNeoBackend().probe()["capabilities"]
    bh = R.discover_bizhawk(R.DEFAULT_EMU).get("2.8")
    return BizHawkNESBackend(bh).probe()["capabilities"]


# ===================================================== 可执行状态构造（导航 + 冻结）
#
# build_state() 只回答「能不能」；本节回答「状态在哪、怎么到、到了没有」。
# nav 配方 = 冷启动 ROM -> 逐步输入宏 -> 每步用 RAM 断言证明落点 -> 存快照 -> 跨进程复现。
# 断言不过一律判 failed/blocked，绝不把「点了 Start 应该进去了」当证据。

_OPS = {"==": lambda a, b: a == b, "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b, "<": lambda a, b: a < b,
        ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}


def _blocked(code, reason):
    return {"status": "blocked", "code": code, "reason": reason, "steps": [],
            "evidence": [], "state": None}


def _ram_reader(dump_path):
    """把一次帧对齐的 RAM 转储包成 read(addr)->int，断言只可能读冻结点那一帧的字节。"""
    raw = Path(str(dump_path)).read_bytes()

    def read(addr):
        a = int(addr)
        if not 0 <= a < len(raw):
            raise IndexError(f"RAM 转储只到 {len(raw)} 字节，addr={a} 越界")
        return raw[a]
    return read


def check_expect(read, expect):
    """把 expect 列表跑成逐条判定。read(addr)->int 由调用方提供（便于离线自检桩测）。"""
    out = []
    for e in expect or []:
        addr, op, want = int(e["addr"]), str(e.get("op", "==")), int(e["value"])
        got = int(read(addr))
        fn = _OPS.get(op)
        out.append({"addr": addr, "op": op, "want": want, "got": got,
                    "pass": bool(fn(got, want)) if fn else False,
                    "note": "" if fn else f"未知 op: {op}"})
    return out


def _validate_recipe(recipe):
    if not isinstance(recipe, dict):
        return "nav 配方必须是 JSON 对象"
    if not str(recipe.get("game_id") or "").strip():
        return "game_id 必填"
    prof = recipe.get("profile")
    if not isinstance(prof, dict):
        return "缺 profile（rom/rom_sha1/core/system/bizhawk）"
    for k in ("rom", "core", "system", "bizhawk", "rom_sha1", "profile_id"):
        if not str(prof.get(k) or "").strip():
            return f"profile.{k} 必填"
    steps = recipe.get("steps")
    if not isinstance(steps, list) or not steps:
        return "steps 至少一步（空 steps 等于没导航）"
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict) or not (s.get("macro") or s.get("run") or s.get("extra")):
            return f"steps[{i}] 需要 macro/run/extra 之一"
        if s.get("expect"):
            return (f"steps[{i}].expect 已废弃：导航是一条原子 attempt，中间点读不到 RAM；"
                    "把断言放到配方顶层 expect")
        if s.get("shot"):
            return (f"steps[{i}].shot 已废弃：中途截图会让 Lua 多推不定帧数；"
                    "证据统一用 nav_ref/ctrl/reload_ref")
    if not (recipe.get("expect") or []):
        return "顶层 expect 必填：没有 RAM 断言就无法证明真的到了实机态"
    for e in recipe["expect"]:
        if "addr" not in e or "value" not in e:
            return "expect 每项需要 addr+value"
        if str(e.get("op", "==")) not in _OPS:
            return f"expect op 非法: {e.get('op')}"
    if not str(recipe.get("save_name") or "").strip():
        return "save_name 必填（快照名，ASCII）"
    return None


def combined_spec(steps, system="NES"):
    """把多步导航拼成一条宏（空帧=中立输入），交给单条 attempt 原子跑完。"""
    from . import statejump as SJ
    parts, total = [], 0
    for st in steps:
        if st.get("macro"):
            spec = SJ.parse_macro(str(st["macro"]), system)
            parts.append(spec)
            total += len(spec.split(","))
        n = int(st.get("extra") or st.get("run") or 0)
        if n > 0:
            parts.append(",".join([""] * n))
            total += n
    return ",".join(parts), total


def run_nav(recipe, work, ffmpeg="ffmpeg", boot_timeout=90.0):
    """原子导航：从 root 快照一次 attempt 跑到冻结点，产帧精确、可字节复现的 base 状态。

    为什么非得原子：Lua 主循环在没有待办指令时每轮也推一帧，命令间空闲时长取决于
    Python 处理上一条响应的时间。实测同一条多命令配方跑两次，开机 70 帧的 RAM 就差
    9 字节、最终快照 18736 vs 25231 字节——「跑导航再存快照」根本不可复现。
    复现单位只有一个：已冻结的快照。
      * recipe.root_state 给了（资产仓的 boot/base）=> 从它出发，字节可复现；
      * 没给 => 先存一个本次开机态当 root。上电 RAM 是 NesHawk 随机的，所以 bootstrap
        本身不可复现，但它产出的 root 快照是后续一切可复现导航的起点，必须一起入库。

    返回 {status, root, state, expect, drift, control, reload, evidence, profile}。
    """
    from . import statejump as SJ

    bad = _validate_recipe(recipe)
    if bad:
        return _blocked("SCHEMA_INVALID", bad)
    prof = recipe["profile"]
    rom, bizhawk = Path(str(prof["rom"])), Path(str(prof["bizhawk"]))
    if not rom.is_file():
        return _blocked("MISSING_RESOURCE", f"ROM 不存在: {rom}")
    want = str(prof["rom_sha1"]).strip().upper()
    got = SJ.sha1_file(rom).upper()
    if got != want:
        return _blocked("MISSING_RESOURCE", f"ROM 哈希不符：期望 {want} 实际 {got}（不许用别的版本导航）")
    if not (bizhawk / "EmuHawk.exe").is_file():
        return _blocked("MISSING_RESOURCE", f"BizHawk 不可用: {bizhawk}")

    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    evidence = []
    spec, frames = combined_spec(recipe["steps"], str(prof["system"]))
    save_path = Path(work / (str(recipe["save_name"]) + ".state"))
    ref_shot = Path(work / "nav_ref.png")
    root_path, root_kind = None, None
    state = control = None
    drift = None
    sess = SJ.StateSession(rom=str(rom), bizhawk=str(bizhawk), core=str(prof["core"]),
                           system=str(prof["system"]), work=str(work))
    try:
        sess.start(boot_timeout=boot_timeout)
        if recipe.get("root_state"):
            root_path = Path(str(recipe["root_state"]))
            if not root_path.is_file():
                return _blocked("MISSING_RESOURCE", f"root_state 不存在: {root_path}")
            root_kind = "provided"
            boot_frame, _ = sess.ping()
        else:
            root_path = Path(sess.save("boot_root"))
            root_kind = "bootstrapped"          # 本次上电态：随机 RAM 已固化进这个文件
            boot_frame, _ = sess.ping()
        root_ascii = sess.use_state(str(root_path), name="nav_root")
        sess.attempt(root_ascii, spec=spec, extra=0,
                     shot=str(ref_shot), save=str(save_path))
        evidence += [ref_shot, save_path]
        from . import state_registry as SR
        state = {"path": str(save_path), "sha1": SJ.sha1_file(save_path),
                 "sha256": _sha256(save_path), "size": save_path.stat().st_size,
                 "content": SR.state_content_fingerprint(save_path),
                 "ref_shot_sha1": SJ.sha1_file(ref_shot).upper()}
        root = {"path": str(root_path), "kind": root_kind, "sha256": _sha256(root_path),
                "size": root_path.stat().st_size, "boot_frame": boot_frame,
                "nav_frames": frames}
        if recipe.get("ramdump"):
            dump = Path(work) / "ram_base.bin"
            # RAM 必须挂在同一个 attempt 的收尾：单独发 ramdump 会漂到不定帧上，读到的不是冻结点。
            sess.attempt(str(save_path), spec="-", extra=0, ram=str(dump))
            evidence.append(dump)
            state["ram_sha256"] = _sha256(dump)
        else:
            dump = None
        read = _ram_reader(dump) if dump else (lambda a: sess.read(a))  # noqa: E731
        checks_now = check_expect(read, recipe["expect"])
        gap = int(recipe.get("drift_probe_frames", 240))
        after_dump = Path(work) / "ram_after_drift.bin"
        after_shot = Path(work) / "after_drift.png"
        if dump:
            sess.attempt(str(save_path), spec="-", extra=gap, ram=str(after_dump), shot=str(after_shot))
            read_after = _ram_reader(after_dump)
        else:
            sess.run(gap)
            read_after = read
            after_dump = after_shot = None
        checks_after = check_expect(read_after, recipe["expect"])
        drift = {"frames": gap,
                 "pass": all(c["pass"] for c in checks_now) and all(c["pass"] for c in checks_after)
                         and [c["got"] for c in checks_now] == [c["got"] for c in checks_after],
                 "at_freeze": checks_now, f"after_{gap}": checks_after}
        if after_dump:
            drift["ram_diff_bytes"] = sum(
                1 for x, y in zip(dump.read_bytes(), after_dump.read_bytes()) if x != y)
            evidence += [after_dump, after_shot]
        if recipe.get("control_check", True):
            from .universal_authoring import check_controllability
            control = check_controllability(sess, save_path, work / "ctrl")
            evidence += [Path(v) for v in control["screenshots"].values()]
    except Exception as e:  # 会话异常一律如实失败，不伪造状态
        return {"status": "failed", "code": "SESSION_ERROR", "reason": f"{type(e).__name__}: {e}",
                "evidence": [str(p) for p in evidence], "state": None}
    finally:
        sess.close()

    if not drift["pass"]:
        return {"status": "failed", "code": "NAV_ASSERTION_FAILED",
                "reason": "冻结点 RAM 断言不过或断言值在中立空跑后漂移："
                          + json.dumps({"at_freeze": drift["at_freeze"],
                                        "after": drift[f"after_{drift['frames']}"]}, ensure_ascii=False),
                "root": root, "state": state, "drift": drift,
                "evidence": [str(p) for p in evidence]}
    if control is not None and not control.get("controllable"):
        return {"status": "failed", "code": "STATE_NOT_LIVE",
                "reason": f"冻结态不受控：action={control.get('action_effective')} "
                          f"menu={control.get('menu_effective')} "
                          f"ram_diff={control.get('ram_diff_bytes')}（过场/信屏不能当 base）",
                "root": root, "state": state, "drift": drift, "control": control,
                "evidence": [str(p) for p in evidence]}

    reload_ok, reload_detail = None, "reload_check=False，未做跨进程复现"
    if recipe.get("reload_check", True):
        import os
        import shutil
        reload = SJ.StateSession(rom=str(rom), bizhawk=str(bizhawk), core=str(prof["core"]),
                                 system=str(prof["system"]), work=str(work / "reload"))
        try:
            reload.start(boot_timeout=boot_timeout)
            st2 = os.path.join(reload.work, "base.state")
            shutil.copyfile(str(save_path), st2)
            re_shot = Path(reload._wpath("reload_ref", ".png"))
            reload.attempt(st2, extra=0, shot=str(re_shot))
            reload_ok, reload_detail = SJ._png_pixels_equal(ref_shot, re_shot, ffmpeg)
            evidence += [re_shot]
        except Exception as e:
            reload_ok, reload_detail = False, f"跨进程复核异常: {type(e).__name__}: {e}"
        finally:
            reload.close()
    status = "ready" if reload_ok is not False else "failed"
    return {"status": status, "code": None if status == "ready" else "NONDETERMINISTIC_STATE",
            "reason": "" if status == "ready" else f"跨进程 reload 画面不一致：{reload_detail}",
            "spec_frames": frames, "root": root, "state": state, "drift": drift,
            "ram_bin": str(dump) if dump else None,
            "control": control, "evidence": [str(p) for p in evidence],
            "reload": {"pass": reload_ok, "detail": reload_detail},
            "profile": {"profile_id": prof["profile_id"], "rom": str(rom), "rom_sha1": got,
                        "core": prof["core"], "system": prof["system"],
                        "bizhawk": str(bizhawk), "fps": recipe.get("fps", 60.0988)}}


def _sha256(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(recipe, work, ffmpeg="ffmpeg", revision=None, reuse=True):
    """run_nav 通过后把快照登记成状态资产包，返回 {status, state_ref, package, nav}。

    只有导航断言 + 跨进程 reload 全过才转 state_verified；否则返回 blocked/failed
    且不落包——半成品状态一旦进仓，下游就会拿它当「验证过」复用。
    同一条 nav_recipe 已有 state_verified 及以上的包时直接复用，不再重跑模拟器。
    """
    from . import state_registry as SR
    if reuse and not revision:
        hit = SR.find_verified_nav(str(recipe["game_id"]), str(recipe["profile"]["profile_id"]),
                                  recipe.get("steps") or [],
                                  str(recipe.get("state_name") or "base"))
        if hit:
            return {"status": "ready", "reason": "", "reused": True,
                    "game_id": hit["game_id"], "profile_id": hit["profile_id"],
                    "revision": hit["revision"], "state_name": hit["state_name"],
                    "state_ref": f"{hit['game_id']}/{hit['profile_id']}/{hit['revision']}"
                                 f"#{hit['state_name']}",
                    "package": hit["package"], "nav": None}
    nav = run_nav(recipe, work, ffmpeg=ffmpeg)
    if nav.get("status") != "ready":
        return {"status": nav.get("status", "failed"),
                "reason": nav.get("reason") or nav.get("code") or "导航未通过",
                "state_ref": None, "package": None, "nav": nav}
    prof = dict(recipe["profile"])
    prof["emulator"] = str(prof["bizhawk"])
    prof.setdefault("fps", nav["profile"]["fps"])
    game_id = str(recipe["game_id"])
    profile_id = str(prof["profile_id"])
    state_name = str(recipe.get("state_name") or "base")
    pkg = SR.create(game_id, prof, revision=revision, status="resources_ready",
                    note=str(recipe.get("note") or "nav freeze"))
    revision = pkg["revision"]
    SR.attach_nav(game_id, profile_id, revision, recipe, nav, state_name)
    pkg = SR.set_status(game_id, profile_id, revision, "state_verified")
    return {"status": "ready", "reason": "", "game_id": game_id, "profile_id": profile_id,
            "revision": revision, "state_name": state_name,
            "state_ref": f"{game_id}/{profile_id}/{revision}#{state_name}",
            "package": str(SR.package_dir(game_id, profile_id, revision)), "nav": nav}


def patch_sweep(recipe, work, addr, values, macro, extra=30, sample_frames=(10, 20, 30),
                ffmpeg="ffmpeg", state=None):
    """标定用：同一 base 状态写入 addr=value，跑同一段宏，逐帧截图并给帧签名。

    用途是把「这个地址到底控制什么」变成可复算的证据（相同 value 出同图、不同 value 出异图），
    而不是靠文档说「0xAA 是武器」。返回 {addr, values:[{value, sig, pngs}], clusters}。
    """
    import hashlib
    from . import statejump as SJ
    bad = _validate_recipe(recipe)
    if bad:
        return _blocked("SCHEMA_INVALID", bad)
    prof = recipe["profile"]
    rom, bizhawk = Path(str(prof["rom"])), Path(str(prof["bizhawk"]))
    if SJ.sha1_file(rom).upper() != str(prof["rom_sha1"]).strip().upper():
        return _blocked("MISSING_RESOURCE", f"ROM 哈希不符: {rom}")
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    if state:
        # 已登记的状态包直接用：标定要测的是「写这个字节会不会改画面」，重跑导航只是烧时间
        if not Path(str(state)).is_file():
            return _blocked("MISSING_RESOURCE", f"标定用的 base 状态不存在: {state}")
        nav = None
    else:
        nav = run_nav(recipe, work, ffmpeg=ffmpeg)
        if nav.get("status") != "ready":
            return {"status": "failed", "code": "BASE_NOT_READY", "reason": nav.get("reason"),
                    "nav": nav}
        state = nav["state"]["path"]
    sess = SJ.StateSession(rom=str(rom), bizhawk=str(bizhawk), core=str(prof["core"]),
                           system=str(prof["system"]), work=str(work / "sweep"))
    out = []
    try:
        sess.start()
        state = sess.use_state(state)      # 资产仓是中文路径，Lua 只认 ASCII
        spec = SJ.parse_macro(str(macro), str(prof["system"]))
        n_mac = len(spec.split(","))
        for v in values:
            d = work / "sweep" / f"v{int(v):02x}"
            sess.dump(str(d).replace("\\", "/"), spec=spec, extra=max(0, int(extra) - n_mac),
                      state=state, patches=[{"addr": int(addr), "value": int(v)}])
            pngs = sorted(d.glob("*.png"))
            sigs = {}
            for k in sample_frames:
                pick = pngs[min(k, len(pngs)) - 1] if pngs else None
                if pick:
                    sigs[k] = hashlib.sha1(pick.read_bytes()).hexdigest()[:12]
            out.append({"value": int(v), "hex": f"0x{int(v):02X}", "frames": len(pngs),
                        "sig": sigs, "dir": str(d)})
    finally:
        sess.close()
    clusters = {}
    for o in out:
        clusters.setdefault(tuple(o["sig"].values()), []).append(o["hex"])
    return {"status": "ready", "addr": int(addr), "macro": str(macro), "extra": extra,
            "base_state": state, "values": out,
            "clusters": [{"sig": list(k), "values": v} for k, v in clusters.items()]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=False, choices=sorted(_SOURCE_MECHANISM),
                    help="能力判定分支（不给则必须给 --recipe）")
    ap.add_argument("--backend", default="nes", choices=["nes", "fbneo"])
    ap.add_argument("--profile", default="probe_profile")
    ap.add_argument("--savestate", default=None)
    ap.add_argument("--cheat", default=None)
    ap.add_argument("--recipe", default=None, help="nav 配方 JSON：跑导航并可冻结成状态资产包")
    ap.add_argument("--work", default=None, help="导航临时目录（必须 ASCII），默认 F:/taspipe_scratch/nav/<profile_id>")
    ap.add_argument("--register", action="store_true", help="导航通过后登记 state_verified 资产包")
    ap.add_argument("--revision", default=None, help="固定 revision 名（复跑同一版时用）")
    ap.add_argument("--no-reuse", action="store_true",
                    help="即使同一条 nav_recipe 已验证过也重跑（默认复用，禁止重测）")
    ap.add_argument("--root-state", default=None,
                    help="用已冻结的上电/基态快照当导航起点（复现路线）；不给则本次开机 bootstrap")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    ap.add_argument("--sweep-addr", default=None, help="标定：写入的 RAM 地址（十进制或 0x）")
    ap.add_argument("--sweep-values", default="0", help="逗号分隔的候选字节值，如 0,1,2,17,18")
    ap.add_argument("--sweep-macro", default="B,,,,B,,,,B,,,,", help="标定期间执行的宏")
    ap.add_argument("--sweep-extra", type=int, default=30)
    ap.add_argument("--state", default=None,
                    help="标定/导航复用时直接指定 base 存档；不给则按 nav_recipe 指纹查已验证包，查不到才重跑导航")
    args = ap.parse_args()

    def _recipe():
        r = json.loads(Path(args.recipe).read_text(encoding="utf-8"))
        if args.root_state:
            r["root_state"] = args.root_state
        return r

    if args.recipe and args.sweep_addr is not None:
        recipe = _recipe()
        pid = str((recipe.get("profile") or {}).get("profile_id") or "nav")
        work = Path(args.work) if args.work else Path("F:/taspipe_scratch/nav") / pid
        addr = int(args.sweep_addr, 0)
        vals = [int(x, 0) for x in str(args.sweep_values).split(",") if x.strip() != ""]
        from . import state_registry as SR
        state = args.state
        if not state:
            hit = SR.find_verified_nav(str(recipe["game_id"]), pid,
                                       recipe.get("steps") or [],
                                       str(recipe.get("state_name") or "base"))
            state = hit["state_path"] if hit else None
        res = patch_sweep(recipe, work, addr, vals, args.sweep_macro,
                          extra=args.sweep_extra, ffmpeg=args.ffmpeg, state=state)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res.get("status") == "ready" else 2

    if args.recipe:
        recipe = _recipe()
        pid = str((recipe.get("profile") or {}).get("profile_id") or "nav")
        work = Path(args.work) if args.work else Path("F:/taspipe_scratch/nav") / pid
        if args.register:
            res = freeze(recipe, work, ffmpeg=args.ffmpeg, revision=args.revision,
                         reuse=not args.no_reuse)
        else:
            res = run_nav(recipe, work, ffmpeg=args.ffmpeg)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res.get("status") == "ready" else 2

    if not args.source:
        ap.error("需要 --source（能力判定）或 --recipe（导航/冻结）")
    caps = _probe_capabilities(args.backend)
    res = build_state(args.source, args.profile, caps,
                      savestate=args.savestate, cheat=args.cheat)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res["status"] == "ready" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())