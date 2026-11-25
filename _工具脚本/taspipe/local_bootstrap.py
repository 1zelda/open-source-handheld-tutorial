# -*- coding: utf-8 -*-
"""本地一键落地、解除跨平台死锁、天马6T网盘寻址真ROM、自动生成 base.state 并出片的实跑器。

保存位置：F:\\开源掌机教程\\_工具脚本\\taspipe\\local_bootstrap.py
运行命令（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.local_bootstrap doctor
  py -3 -u -m taspipe.local_bootstrap fetch-tianma --query "Mega Man"
  py -3 -u -m taspipe.local_bootstrap run-ready --out "F:/taspipe_scratch/ready_outputs" --frames 900
  py -3 -u -m taspipe.local_bootstrap auto-showcase --rom "F:/你的干净ROM路径" --preset megaman1 --pack "taspipe/游戏包/megaman1_weapons.showcase.json"
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT_ROOT = HERE.parent          # F:\开源掌机教程\_工具脚本
PROJECT_ROOT = SCRIPT_ROOT.parent  # F:\开源掌机教程
PACK_DIR = HERE / "游戏包"
TPL_DIR = PROJECT_ROOT / "04-游戏资源库" / "TAS输入录像库" / "视频模板"
SCRATCH_DIR = Path("F:/taspipe_scratch/bootstrap_runs")

KNOWN_BAD_MM1_SHA1 = {
    "d8b8c5e2ee76f2ec1820123bb9f8c70f5e603923",  # 本地异常 mega_man_usa.nes (直跳 CLEAR POINTS)
    "2f88381557339a14c20428455f6991c1eb902c99",  # 本地异常 megamanhd.nes
}


def sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest().lower()


def sha1_of(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest().lower()


def nes_headerless_sha1(path: Path) -> str:
    """计算去 iNES 16字节头 (NES\\x1a) 的 PRG+CHR SHA-1（对齐 TASVideos required_rom_sha1 口径）。"""
    raw = path.read_bytes()
    if len(raw) > 16 and raw[:4] == b"NES\x1a":
        return sha1_bytes(raw[16:]).upper()
    return sha1_bytes(raw).upper()


# ===========================================================================
# 1. 自动热修补 statejump.py、showcase.py 与 selftest.py 的跨平台能力
# ===========================================================================
def patch_core_files_for_all_platforms():
    """解除 statejump.py 与 showcase.py 中阻碍非 NES 平台运行的硬编码限制，并同步视频模板。"""
    sj_path = HERE / "statejump.py"
    sc_path = HERE / "showcase.py"
    patched = []

    # 本机安全护栏（2026-11-12）：本机 statejump/showcase 已升级为「平台感知 +
    # verified 准入」版本（PLATFORM_BUTTONS / PLATFORM_PROFILES）。云盘这段扁平化
    # 热修会把 KNOWN_BUTTONS 一次性放宽到 28 键，等于让 NES 也接受 X/Y/L/R，
    # 并绕过未核验后端不得出片的闸门。检测到本机较严实现时直接跳过，绝不覆盖。
    _sj_head = sj_path.read_text(encoding="utf-8") if sj_path.is_file() else ""
    _sc_head = sc_path.read_text(encoding="utf-8") if sc_path.is_file() else ""
    if "PLATFORM_BUTTONS" in _sj_head or "PLATFORM_PROFILES" in _sc_head:
        return ["跳过热修：本机已是平台感知 + verified 准入版本，"
                "云盘扁平化补丁会放宽 NES 键集并绕过准入闸门（保留本机较严实现）"]

    if sj_path.is_file():
        sj_text = sj_path.read_text(encoding="utf-8")
        old_btns = 'KNOWN_BUTTONS = {"A", "B", "Select", "Start", "Up", "Down", "Left", "Right"}'
        new_btns = (
            'KNOWN_BUTTONS = {\n'
            '    "A", "B", "C", "D", "X", "Y", "Z", "L", "R", "L1", "R1", "L2", "R2",\n'
            '    "Select", "Start", "Mode", "Run", "Coin", "I", "II",\n'
            '    "Up", "Down", "Left", "Right", "Triangle", "Circle", "Cross", "Square"\n'
            '}'
        )
        if old_btns in sj_text:
            sj_text = sj_text.replace(old_btns, new_btns)
            patched.append("statejump.KNOWN_BUTTONS 已扩展至全平台 28 键")

        old_alias = 'BUTTON_ALIASES = {"U": "Up", "D": "Down", "L": "Left", "R": "Right"}'
        new_alias = (
            'BUTTON_ALIASES = {\n'
            '    "U": "Up", "D": "Down", "L": "Left", "R": "Right",\n'
            '    "LT": "Left", "RT": "Right", "T": "Start", "S": "Select", "M": "Mode",\n'
            '    "Tr": "Triangle", "O": "Circle", "Sq": "Square"\n'
            '}'
        )
        if old_alias in sj_text:
            sj_text = sj_text.replace(old_alias, new_alias)
            patched.append("statejump.BUTTON_ALIASES 已扩展全平台别名")

        old_addr = "if not isinstance(a, int) or not 0 <= a <= 0xFFFF:"
        new_addr = (
            "if isinstance(a, str) and a.lower().startswith('0x'):\n"
            "        a = int(a, 16)\n"
            "    if not isinstance(a, int) or not 0 <= a <= 0x1FFFFFF:"
        )
        if old_addr in sj_text:
            sj_text = sj_text.replace(old_addr, new_addr)
            patched.append("statejump._addr 已支持 0x 十六进制字符串与 32MB 地址空间")

        sj_path.write_text(sj_text, encoding="utf-8")

    if sc_path.is_file():
        sc_text = sc_path.read_text(encoding="utf-8")
        old_plat_check = (
            '    if doc.get("platform", "NES") != "NES":\n'
            '        raise SchemaError("当前 showcase 生产器仅支持 NES")'
        )
        new_plat_check = (
            '    allowed_plats = {"NES", "FC", "FDS", "SNES", "SFC", "GBA", "GB", "GBC", "MD", "GEN", "PCE", "PS1", "PSX", "ARCADE_FBNEO", "PSP"}\n'
            '    if doc.get("platform", "NES").upper() not in allowed_plats:\n'
            '        raise SchemaError(f"不支持的 showcase 平台: {doc.get(\'platform\')}")'
        )
        if old_plat_check in sc_text:
            sc_text = sc_text.replace(old_plat_check, new_plat_check)
            patched.append("showcase.validate_spec 已解除仅限 NES 的限制")
            sc_path.write_text(sc_text, encoding="utf-8")

    return patched


# ===========================================================================
# 2. 自动落盘跨平台天马边框模板
# ===========================================================================
TEMPLATES = {
    "snes_tianma_cover": {
        "name": "snes_tianma_cover",
        "mode": "cover",
        "canvas": [1920, 1080],
        "bg_blur": 28,
        "bg_brightness": 0.32,
        "accent": [168, 132, 248],
        "fallback_bg": [22, 18, 36],
        "gameplay": {"max_w_frac": 0.68, "max_h_frac": 0.92, "margin_x": 64},
        "panel": {"gap": 48, "margin_right": 64, "pad": 24, "box_max_h_frac": 0.58, "box_top": 96},
    },
    "ps1_tianma_cover": {
        "name": "ps1_tianma_cover",
        "mode": "cover",
        "canvas": [1920, 1080],
        "bg_blur": 30,
        "bg_brightness": 0.28,
        "accent": [88, 168, 248],
        "fallback_bg": [16, 22, 32],
        "gameplay": {"max_w_frac": 0.70, "max_h_frac": 0.92, "margin_x": 56},
        "panel": {"gap": 44, "margin_right": 56, "pad": 24, "box_max_h_frac": 0.56, "box_top": 100},
    },
    "arcade_tianma_cover": {
        "name": "arcade_tianma_cover",
        "mode": "cover",
        "canvas": [1920, 1080],
        "bg_blur": 26,
        "bg_brightness": 0.30,
        "accent": [248, 184, 56],
        "fallback_bg": [28, 16, 16],
        "gameplay": {"max_w_frac": 0.72, "max_h_frac": 0.92, "margin_x": 48},
        "panel": {"gap": 40, "margin_right": 48, "pad": 20, "box_max_h_frac": 0.58, "box_top": 96},
    },
}


def ensure_templates():
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for name, cfg in TEMPLATES.items():
        p = TPL_DIR / f"{name}.json"
        if not p.is_file():
            p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(str(p))
    return written


# ===========================================================================
# 3. 全面体检：查清本地到底有哪些真 ROM、哪些可立即出片、哪些缺文件
# ===========================================================================
def scan_local_roms():
    search_roots = [
        PROJECT_ROOT / "04-游戏资源库" / "TAS输入录像库" / "roms_verify",
        PROJECT_ROOT / "04-游戏资源库" / "自己ROM放这里",
        PROJECT_ROOT / "04-游戏资源库" / "公版与开源",
        Path("F:/tas_rig/roms"),
        Path("F:/taspipe_scratch"),
    ]
    rom_exts = {
        ".nes", ".fds", ".sfc", ".smc", ".gba", ".gb", ".gbc",
        ".md", ".gen", ".bin", ".pce", ".cue", ".chd", ".iso", ".pbp", ".zip"
    }
    found = []
    for root in search_roots:
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in rom_exts:
                found.append(p)
    return found


def run_doctor():
    from . import backends
    from . import registry as R
    from . import retro_platforms as RP

    patches = patch_core_files_for_all_platforms()
    tpls = ensure_templates()
    plat_status = RP.probe_all_platforms()
    local_roms = scan_local_roms()

    mm1_cands = [
        p for p in local_roms
        if re.search(r"mega\s*man|rock\s*man|洛克人", p.name, re.I) and p.suffix.lower() == ".nes"
    ]
    clean_mm1 = []
    bad_mm1 = []
    for p in mm1_cands:
        s = sha1_of(p)
        if s in KNOWN_BAD_MM1_SHA1:
            bad_mm1.append({"path": str(p), "sha1": s, "reason": "已知坏 dump（未战斗直跳 CLEAR POINTS）"})
        else:
            clean_mm1.append({"path": str(p), "sha1": s, "headerless_sha1": nes_headerless_sha1(p)})

    lib = R.DEFAULT_LIB
    ready_pubs = []
    convertible_fceux_pubs = []
    if (lib / "publications.json").is_file():
        pubs = R.load_publications(lib)
        ri, vi, bh = R.index_roms(lib), R.index_versions(lib), R.discover_bizhawk(R.DEFAULT_EMU)
        romset = set(ri.keys())
        for p in pubs:
            req_s = R.norm_sha1(p.get("rom_sha1")) or (vi.get(p.get("version_id", ""), {}).get("sha1") or "")
            if req_s and req_s in romset:
                ass = R.assess(p, lib, ri, vi, bh)
                if ass["status"] == "replayable":
                    ready_pubs.append({"id": p["id"], "game": p.get("game"), "platform": p.get("platform")})
                elif any("FCEUX" in b.get("reason", "") for b in ass.get("blockers", [])):
                    convertible_fceux_pubs.append({"id": p["id"], "game": p.get("game"), "movie": p.get("local_movie")})

    fb_probe = backends.FBNeoBackend().probe()
    rig_states = list(Path("F:/tas_rig/states").glob("*.fs")) if Path("F:/tas_rig/states").is_dir() else []

    report = {
        "core_patches_applied": patches,
        "templates_ensured": tpls,
        "platforms_probe": plat_status,
        "total_local_rom_files_found": len(local_roms),
        "megaman1_rom_diagnosis": {
            "clean_candidates": clean_mm1,
            "known_bad_dumps": bad_mm1,
            "verdict": "READY" if clean_mm1 else "BLOCKED_NEED_CLEAN_MM1_ROM",
        },
        "immediately_runnable_now": {
            "1_replayable_tas_pubs": ready_pubs,
            "2_fceux_auto_convertible_pubs": convertible_fceux_pubs,
            "3_arcade_fbneo_ready": fb_probe["available"],
            "4_arcade_savestates": [str(x) for x in rig_states],
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


# ===========================================================================
# 4. 立即执行当前电脑上 100% 具备资源的实跑出片任务
# ===========================================================================
def run_all_ready_now(out_root: Path, frames_limit: int = 900):
    from . import auto as AUTO
    from . import backends
    from . import fceux as FCEUX
    from . import popularity as POP
    from . import registry as R

    patch_core_files_for_all_platforms()
    ensure_templates()
    out_root.mkdir(parents=True, exist_ok=True)
    summary = {"arcade_moves": [], "fceux_converted": [], "tas_playthroughs": [],
               "off_popularity_list": []}

    fb = backends.FBNeoBackend()
    if fb.probe()["available"]:
        kyo_moves = [
            ("oniyaki", "→↓↘+A"),
            ("yamibarai", "↓↘→+A"),
            ("orochinagi", "↓↙←↙↓↘→+C"),
            ("mushiki", "↓↘→↓↘→+A"),
        ]
        arc_out = out_root / "arcade_kof98_kyo"
        for slug, notation in kyo_moves:
            print(f"[街机实跑] 正在录制 KOF98 草薙京 {slug} ({notation}) ...")
            res = fb.run_move(notation, slug=slug, char="kyo", out_dir=str(arc_out / slug), unmute=True)
            summary["arcade_moves"].append({
                "slug": slug,
                "notation": notation,
                "verdict": res["verification"]["verdict"],
                "recordings": res.get("recording_refs", []),
            })

    lib = R.DEFAULT_LIB
    if (lib / "publications.json").is_file():
        pubs = R.load_publications(lib)
        ri, vi, bh = R.index_roms(lib), R.index_versions(lib), R.discover_bizhawk(R.DEFAULT_EMU)
        romset = set(ri.keys())
        # 用户 2026-11-22 口径：只测最有名、大家玩得多的作品。冷门在这两条循环的最前面就跳过，
        # 既不产 _converted 片，也不占实跑格；被跳过的逐条留名，免得「跑了 0 部」被当成故障。
        off_list = summary["off_popularity_list"]

        def _famous(p):
            info = POP.classify_spec({"game": p.get("game", ""), "platform": p.get("platform", "")})
            if info["on_list"]:
                return True
            off_list.append({"id": p["id"], "game": info["game"], "platform": info["platform"],
                             "reason": info["reason"]})
            return False

        for p in pubs:
            req_s = R.norm_sha1(p.get("rom_sha1")) or (vi.get(p.get("version_id", ""), {}).get("sha1") or "")
            rel = p.get("local_movie") or ""
            if req_s in romset and rel.lower().endswith((".fm2", ".fcm", ".fm3")):
                if not _famous(p):
                    continue
                conv_path = Path(lib) / "_converted" / (p.get("platform") or "NES") / f"{p['id']}.bk2"
                if not conv_path.is_file() and (Path(lib) / rel).is_file():
                    try:
                        FCEUX.convert_publication(p, lib)
                        summary["fceux_converted"].append({"id": p["id"], "game": p.get("game"), "bk2": str(conv_path)})
                    except Exception as e:
                        summary["fceux_converted"].append({"id": p["id"], "error": str(e)})

        played = set()
        for p in pubs:
            req_s = R.norm_sha1(p.get("rom_sha1")) or (vi.get(p.get("version_id", ""), {}).get("sha1") or "")
            if req_s not in romset:
                continue
            if not _famous(p):
                continue
            game_name = p.get("game", "")
            if game_name.lower() in played:
                # 同名作常有 2 条出版物（忍龙 4751/4812、忍龙2 5441/7429），
                # 一趟里跑两遍同一部游戏就是用户投诉过的「重复跑同一个游戏」。
                continue
            ass = R.assess(p, lib, ri, vi, bh)
            if ass["status"] == "replayable":
                played.add(game_name.lower())
                print(f"[名作实跑] 正在录制 {game_name} (pub {p['id']}) ...")
                plat = (p.get("platform") or "NES").upper()
                tpl = "snes_tianma_cover" if plat in ("SNES", "SFC") else "fc_tianma_cover"
                spec = AUTO.JobSpec(
                    game=game_name,
                    job_type="playthrough",
                    pub_id=p["id"],
                    source="movie",
                    frames=frames_limit,
                    audio=True,
                    template=tpl,
                    out=str(out_root / f"pub_{p['id']}"),
                )
                doc = AUTO.orchestrate(spec, lib=lib, out_dir=str(out_root / f"pub_{p['id']}"))
                summary["tas_playthroughs"].append({
                    "pub_id": p["id"],
                    "game": game_name,
                    "status": doc.get("status"),
                    "verdict": doc.get("verdict"),
                    "deliverable_ref": doc.get("deliverable_ref"),
                })
                if len(summary["tas_playthroughs"]) >= 3:
                    break

    rep_file = out_root / "ready_runs_summary.json"
    rep_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


# ===========================================================================
# 5. 单游戏从零自动建 base.state + 自动标定 + 出全量合辑
# ===========================================================================
def auto_bootstrap_showcase(rom_path: Path, preset: str, pack_path: Path, out_dir: Path):
    from . import registry as R
    from . import retro_platforms as RP
    from . import universal_authoring as UA

    patch_core_files_for_all_platforms()
    ensure_templates()

    rom_path = rom_path.resolve()
    if not rom_path.is_file():
        raise SystemExit(f"ROM 文件不存在: {rom_path}")
    if sha1_of(rom_path) in KNOWN_BAD_MM1_SHA1:
        raise SystemExit(
            f"拦截已知坏 ROM ({rom_path.name}, sha1={sha1_of(rom_path)})："
            "该 ROM 开机武器能量预满且选关后直跳 CLEAR POINTS 过场，请先运行 fetch-tianma 获取干净 ROM！"
        )

    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    bh_map = R.discover_bizhawk(R.DEFAULT_EMU)
    bh_dir = bh_map.get("2.8") or next(iter(bh_map.values()), None)
    if not bh_dir:
        raise SystemExit("未找到 BizHawk 目录")

    doc = json.loads(pack_path.read_text(encoding="utf-8"))
    base_state_path = out_dir / "base.state"

    if not base_state_path.is_file():
        print(f"[1/3 自动探路] 正在启动模拟器导航 {rom_path.name} (预设={preset}) 生成真实 base.state ...")
        nav_res = UA.navigate_and_verify_rom(rom_path, Path(bh_dir), preset, out_dir / "nav")
        if nav_res["status"] != "ready" or not nav_res.get("base_state"):
            raise SystemExit(f"自动导航未能进入受控 Gameplay: {json.dumps(nav_res, ensure_ascii=False)}")
        shutil.copy2(nav_res["base_state"], base_state_path)

    doc["rom"] = str(rom_path).replace("\\", "/")
    doc["bizhawk"] = str(bh_dir).replace("\\", "/")
    doc["base_state"] = str(base_state_path).replace("\\", "/")
    pack_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[2/3 自动标定] 正在对 {pack_path.name} 执行正反例逐帧采样与检测框自动标定 ...")
    UA.calibrate_showcase_pack(pack_path, out_dir / "calib_work")

    print(f"[3/3 正式出片] 正在生成全量要素合辑 reel.mp4 ...")
    rep = RP.run_multiplatform_showcase(
        str(pack_path), str(out_dir / "final"), work_dir=str(out_dir / "work")
    )
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="热修补跨平台死锁，并全面体检本地真 ROM / 存档 / 录像就绪状态")

    p_ready = sub.add_parser("run-ready", help="立即把本地已 100% 具备资源的街机招式与 FC 名作跑出真 MP4")
    p_ready.add_argument("--out", default=str(SCRATCH_DIR / "ready_outputs"))
    p_ready.add_argument("--frames", type=int, default=900, help="通关预览录制帧数（设 0 为录整部电影）")

    p_auto = sub.add_parser("auto-showcase", help="给定干净 ROM，自动导航建 base.state + 自动标定 + 出全量合辑")
    p_auto.add_argument("--rom", required=True)
    p_auto.add_argument("--preset", default="generic_nes")
    p_auto.add_argument("--pack", required=True)
    p_auto.add_argument("--out", default=str(SCRATCH_DIR / "auto_showcase"))

    p_tm = sub.add_parser("fetch-tianma", help="调用 tianma_multi_fetch 从天马6T网盘拉取干净多平台 ROM 与封面")
    p_tm.add_argument("--query", default="Mega Man", help="搜索关键词，如 'Mega Man' / 'Metal Slug' / 'Castlevania'")
    p_tm.add_argument("--platform", default="ALL", help="平台目录过滤，如 NES/SNES/GBA/MD/PS1/ARCADE/ALL")

    args = ap.parse_args()
    if args.cmd == "doctor":
        run_doctor()
    elif args.cmd == "run-ready":
        frames = None if args.frames <= 0 else args.frames
        run_all_ready_now(Path(args.out), frames_limit=frames)
    elif args.cmd == "auto-showcase":
        auto_bootstrap_showcase(Path(args.rom), args.preset, Path(args.pack), Path(args.out))
    elif args.cmd == "fetch-tianma":
        from . import tianma_multi_fetch as TMF
        TMF.search_and_pull(args.query, platform_filter=args.platform)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
