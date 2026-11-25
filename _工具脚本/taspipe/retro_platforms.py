# -*- coding: utf-8 -*-
"""T11/T12/T13 跨平台怀旧游戏统一后端与状态会话库（覆盖 FC/SFC/GBA/GBC/MD/PCE/PS1/PSP/街机）。

解决项目缺口：
1. 突破 showcase.py 与 statejump.py 仅支持 NES 的限制，将「持久会话 + 原子快照 + RAM 补丁 +
   正反例逐帧采集」扩展到全怀旧平台（SNES、GBA、GB/GBC、Genesis/MD、PCE、PS1、街机 FBNeo、PSP）。
2. 内置全平台手柄按键映射表与别名展开（如 SNES 的 X/Y/L/R，MD 的 C/X/Y/Z/Mode，PS1 的
   Triangle/Circle/Cross/Square/L1/R1/L2/R2，街机的 B1..B6），自动适配 BizHawk joypad.set。
3. 内置全平台内存域（Memory Domain）与地址位宽规范（24-bit/32-bit 地址空间支持），支持跨平台
   RAM 差分探针与金手指补丁写入。
4. 对 PS1（Octoshock/Nymashock）与 PSP（PPSSPP）提供真实资源检查、BIOS 校验与采集管线接线。

运行方式（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.retro_platforms list-platforms
  py -3 -u -m taspipe.retro_platforms probe-all
  py -3 -u -m taspipe.retro_platforms run-showcase --pack "taspipe/游戏包/snes_super_metroid_abilities.showcase.json" --out "F:/taspipe_scratch/snes_out"
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import detect
from . import exporter
from . import registry as R
from . import showcase
from . import statejump as SJ
from .ledger import Ledger, fingerprint
from .schema import CheckSpec, FailureCode, SchemaError, Verdict, to_dict

# ---------------------------------------------------------------------------
# 全怀旧平台硬件、核心、帧率、内存域与手柄按键规范表
# ---------------------------------------------------------------------------
PLATFORM_SPECS = {
    "NES": {
        "system": "NES",
        "default_core": "NesHawk",
        "alt_cores": ["QuickNES"],
        "fps": 60.0988,
        "resolution": [256, 224],
        "default_domain": "RAM",
        "max_addr": 0xFFFF,
        "rom_exts": [".nes", ".fds", ".unf"],
        "movie_exts": [".bk2", ".fm2", ".fcm", ".fm3"],
        "buttons": {"Up", "Down", "Left", "Right", "Start", "Select", "B", "A"},
        "aliases": {"U": "Up", "D": "Down", "L": "Left", "R": "Right", "T": "Start", "S": "Select"},
        "template": "fc_tianma_mask",
    },
    "SNES": {
        "system": "SNES",
        "default_core": "BSNES",
        "alt_cores": ["Snes9x", "Faust"],
        "fps": 60.0985,
        "resolution": [256, 224],
        "default_domain": "WRAM",
        "max_addr": 0x1FFFF,
        "rom_exts": [".sfc", ".smc"],
        "movie_exts": [".bk2", ".smv", ".lsmv"],
        "buttons": {"Up", "Down", "Left", "Right", "Start", "Select", "Y", "B", "X", "A", "L", "R"},
        "aliases": {"U": "Up", "D": "Down", "LT": "Left", "RT": "Right", "T": "Start", "S": "Select"},
        "template": "fc_tianma_cover",
    },
    "GBA": {
        "system": "GBA",
        "default_core": "mGBA",
        "alt_cores": [],
        "fps": 59.7275,
        "resolution": [240, 160],
        "default_domain": "System Bus",
        "max_addr": 0x0FFFFFFF,
        "rom_exts": [".gba"],
        "movie_exts": [".bk2", ".vbm"],
        "buttons": {"Up", "Down", "Left", "Right", "Start", "Select", "B", "A", "L", "R"},
        "aliases": {"U": "Up", "D": "Down", "LT": "Left", "RT": "Right", "T": "Start", "S": "Select"},
        "template": "fc_tianma_cover",
    },
    "GB": {
        "system": "GB",
        "default_core": "Gambatte",
        "alt_cores": ["SameBoy"],
        "fps": 59.7275,
        "resolution": [160, 144],
        "default_domain": "WRAM",
        "max_addr": 0xFFFF,
        "rom_exts": [".gb", ".gbc"],
        "movie_exts": [".bk2", ".vbm", ".lsmv"],
        "buttons": {"Up", "Down", "Left", "Right", "Start", "Select", "B", "A"},
        "aliases": {"U": "Up", "D": "Down", "L": "Left", "R": "Right", "T": "Start", "S": "Select"},
        "template": "fc_tianma_cover",
    },
    "GBC": {
        "system": "GBC",
        "default_core": "Gambatte",
        "alt_cores": ["SameBoy"],
        "fps": 59.7275,
        "resolution": [160, 144],
        "default_domain": "WRAM",
        "max_addr": 0xFFFF,
        "rom_exts": [".gbc", ".gb"],
        "movie_exts": [".bk2", ".vbm", ".lsmv"],
        "buttons": {"Up", "Down", "Left", "Right", "Start", "Select", "B", "A"},
        "aliases": {"U": "Up", "D": "Down", "L": "Left", "R": "Right", "T": "Start", "S": "Select"},
        "template": "fc_tianma_cover",
    },
    "MD": {
        "system": "GEN",
        "default_core": "GPGX",
        "alt_cores": ["PicoDrive"],
        "fps": 59.9227,
        "resolution": [320, 224],
        "default_domain": "68K RAM",
        "max_addr": 0xFFFF,
        "rom_exts": [".md", ".gen", ".bin", ".smd"],
        "movie_exts": [".bk2", ".gmv"],
        "buttons": {"Up", "Down", "Left", "Right", "Start", "Mode", "A", "B", "C", "X", "Y", "Z"},
        "aliases": {"U": "Up", "D": "Down", "L": "Left", "R": "Right", "T": "Start", "M": "Mode"},
        "template": "fc_tianma_cover",
    },
    "PCE": {
        "system": "PCE",
        "default_core": "HyperNyma",
        "alt_cores": ["PCEHawk"],
        "fps": 59.8261,
        "resolution": [256, 232],
        "default_domain": "Main Memory",
        "max_addr": 0x1FFF,
        "rom_exts": [".pce", ".cue", ".chd"],
        "movie_exts": [".bk2", ".mc2"],
        "buttons": {"Up", "Down", "Left", "Right", "Run", "Select", "II", "I"},
        "aliases": {
            "U": "Up", "D": "Down", "L": "Left", "R": "Right",
            "Start": "Run", "B": "II", "A": "I"
        },
        "template": "fc_tianma_cover",
    },
    "PS1": {
        "system": "PSX",
        "default_core": "Octoshock",
        "alt_cores": ["Nymashock"],
        "fps": 59.94,
        "resolution": [320, 240],
        "default_domain": "MainRAM",
        "max_addr": 0x1FFFFF,
        "rom_exts": [".cue", ".chd", ".iso", ".pbp"],
        "movie_exts": [".bk2", ".pxm"],
        "buttons": {
            "Up", "Down", "Left", "Right", "Start", "Select",
            "Triangle", "Circle", "Cross", "Square", "L1", "R1", "L2", "R2"
        },
        "aliases": {
            "U": "Up", "D": "Down", "L": "Left", "R": "Right",
            "X": "Cross", "O": "Circle", "Sq": "Square", "Tr": "Triangle",
            "A": "Circle", "B": "Cross", "Y": "Square"
        },
        "template": "fc_tianma_cover",
        "requires_bios": True,
    },
    "ARCADE_FBNEO": {
        "system": "ARCADE",
        "default_core": "FBNeo",
        "alt_cores": [],
        "fps": 59.18,
        "resolution": [304, 224],
        "default_domain": "m68K RAM",
        "max_addr": 0xFFFFF,
        "rom_exts": [".zip"],
        "movie_exts": [".fr", ".fs"],
        "buttons": {"Up", "Down", "Left", "Right", "A", "B", "C", "D", "Start", "Coin"},
        "aliases": {"U": "Up", "D": "Down", "L": "Left", "R": "Right"},
        "template": "fc_tianma_cover",
    },
    "PSP": {
        "system": "PSP",
        "default_core": "PPSSPP",
        "alt_cores": [],
        "fps": 59.94,
        "resolution": [480, 272],
        "default_domain": "UserMemory",
        "max_addr": 0x1FFFFFF,
        "rom_exts": [".iso", ".cso", ".pbp", ".chd"],
        "movie_exts": [".ppst"],
        "buttons": {
            "Up", "Down", "Left", "Right", "Start", "Select",
            "Triangle", "Circle", "Cross", "Square", "L", "R"
        },
        "aliases": {"U": "Up", "D": "Down", "LT": "Left", "RT": "Right"},
        "template": "fc_tianma_cover",
    },
}


def get_platform_spec(platform: str) -> dict:
    key = (platform or "NES").strip().upper()
    if key == "GEN" or key == "MEGADRIVE" or key == "GENESIS":
        key = "MD"
    elif key == "SFC":
        key = "SNES"
    elif key == "FC" or key == "FDS":
        key = "NES"
    elif key == "PSX":
        key = "PS1"
    if key not in PLATFORM_SPECS:
        raise SchemaError(f"不支持的怀旧平台: {platform!r}（已支持: {sorted(PLATFORM_SPECS)}）")
    return PLATFORM_SPECS[key]


def parse_platform_macro(platform: str, spec: str) -> str:
    """支持全怀旧平台手柄按键与别名展开的宏谱解析器。"""
    p_spec = get_platform_spec(platform)
    if not isinstance(spec, str) or not spec or any(c.isspace() for c in spec):
        raise SchemaError(f"宏谱须为非空且不含空白的字符串: {spec!r}")
    valid = p_spec["buttons"]
    aliases = SJ.button_aliases_for(platform)
    out = []
    for tok in spec.split(","):
        if tok == "":
            out.append("")
            continue
        parts = tok.split("+")
        # 街机等平台存在「别名与真实按键同名」的歧义（FBNeo 的 D 既是 D 键
        # 又是 Down 别名）。规则：同一和弦内若出现至少一个「非别名键」的真实
        # 按键，则该和弦中既是别名键又是真实按键的记号按真实按键解释；否则
        # 按方向别名展开。于是 "D" -> Down，而 "B+C+D" 保留 D 键。
        button_context = any(p in valid and p not in aliases for p in parts)
        names = []
        for b in parts:
            if not (button_context and b in valid and b in aliases):
                b = aliases.get(b, b)
            if b not in valid:
                raise SchemaError(
                    f"[{platform}] 未知按键: {b!r}（允许 {sorted(valid)} 及别名 {aliases}）"
                )
            names.append(b)
        out.append("+".join(names))
    return ",".join(out)


def format_platform_patches(platform: str, patches: list) -> str:
    """支持 24-bit/32-bit 扩展地址空间与默认内存域补全的补丁格式化器。"""
    p_spec = get_platform_spec(platform)
    max_addr = p_spec["max_addr"]
    toks = []
    for patch in patches or []:
        if not isinstance(patch, dict):
            raise SchemaError("patches 每项须为 {addr, value, domain?}")
        addr = patch.get("addr")
        val = patch.get("value")
        if isinstance(addr, str) and addr.lower().startswith("0x"):
            addr = int(addr, 16)
        if not isinstance(addr, int) or not (0 <= addr <= max_addr):
            raise SchemaError(f"[{platform}] 地址须为 0..0x{max_addr:X} 整数: {addr!r}")
        if not isinstance(val, int) or not (0 <= val <= 255):
            raise SchemaError(f"字节值须为 0..255 整数: {val!r}")
        domain = patch.get("domain")
        tok = f"{addr}:{val}"
        if domain:
            tok += "@" + SJ._domain_arg(domain)
        toks.append(tok)
    return ";".join(toks) or "-"


def validate_multiplatform_showcase(doc: dict) -> dict:
    """支持全怀旧平台的 showcase 知识包校验器（解除原 showcase.py 仅支持 NES 的限制）。"""
    if not isinstance(doc, dict) or doc.get("kind") != "statejump_showcase":
        raise SchemaError("showcase 包 kind 须为 statejump_showcase")
    for key in ("game_id", "rom", "bizhawk", "base_state"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            raise SchemaError(f"showcase 包缺 {key}")
    platform = doc.get("platform", "NES").upper()
    p_spec = get_platform_spec(platform)
    fps = doc.get("fps", p_spec["fps"])
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise SchemaError("showcase fps 须为正数")
    catalog = doc.get("catalog")
    if not isinstance(catalog, dict) or catalog.get("status") != "complete":
        raise SchemaError("catalog.status 须为 complete")
    expected = catalog.get("expected_total")
    if type(expected) is not int or expected < 1:
        raise SchemaError("catalog.expected_total 须为正整数")
    if not isinstance(catalog.get("sources"), list) or not catalog["sources"]:
        raise SchemaError("catalog.sources 不能为空")
    elements = doc.get("elements")
    if not isinstance(elements, list) or not elements:
        raise SchemaError("showcase elements 不能为空")
    seen = set()
    for el in elements:
        eid = el.get("element_id")
        if not isinstance(eid, str) or not re.fullmatch(r"[a-z0-9_]+", eid):
            raise SchemaError(f"element_id 非法: {eid!r}")
        if eid in seen:
            raise SchemaError(f"element_id 重复: {eid}")
        seen.add(eid)
        trigger = el.get("trigger") or {}
        macro = trigger.get("macro")
        if macro:
            parse_platform_macro(platform, macro)
        extra = trigger.get("extra", 0)
        m_frames = 0 if not macro or macro == "-" else len(parse_platform_macro(platform, macro).split(","))
        total = m_frames + extra
        if total < 1:
            raise SchemaError(f"{eid}: 采集总帧数至少为 1")
        format_platform_patches(platform, trigger.get("patches") or [])
        detection = el.get("detection") or {}
        frame = detection.get("frame")
        if type(frame) is not int or not (0 <= frame < total):
            raise SchemaError(f"{eid}: detection.frame 须落在 0..{total - 1}")
        for raw in detection.get("success_checks") or []:
            check = CheckSpec(**raw).validate()
            if check.plugin_id not in detect.PLUGINS:
                raise SchemaError(f"{eid}: 未注册检测插件 {check.plugin_id}")
    return doc


class MultiPlatformStateSession(SJ.StateSession):
    """支持 NES / SNES / GBA / GB / GBC / MD / PCE / PS1 的多平台 BizHawk 状态会话。"""

    def __init__(self, rom, bizhawk, platform="NES", core=None, system=None,
                 movie=None, work=None, speed=400, bios_path=None):
        p_spec = get_platform_spec(platform)
        self.platform = platform.upper()
        self.p_spec = p_spec
        self.bios_path = bios_path
        super().__init__(
            rom=rom,
            bizhawk=bizhawk,
            core=core or p_spec["default_core"],
            system=system or p_spec["system"],
            movie=movie,
            work=work,
            speed=speed,
        )

    def start(self, boot_timeout=60.0):
        # 若为 PS1 等需 BIOS 的平台，先确保 Firmware 目录已挂载对应 BIOS
        if self.p_spec.get("requires_bios") and self.bios_path and Path(self.bios_path).is_file():
            fw_dir = Path(self.bizhawk) / "Firmware"
            fw_dir.mkdir(parents=True, exist_ok=True)
            dst_bios = fw_dir / Path(self.bios_path).name
            if not dst_bios.is_file():
                shutil.copy2(self.bios_path, dst_bios)
        return super().start(boot_timeout=boot_timeout)

    def macro(self, spec, shot=None):
        return super().macro(spec, shot=shot)

    def dump(self, frames_dir, spec=None, extra=0, state=None, patches=None):
        return super().dump(frames_dir, spec=spec, extra=extra,
                            state=state, patches=patches)


def run_multiplatform_showcase(pack_path: str, out_dir: str, only=None,
                               template=None, work_dir=None,
                               ffmpeg="ffmpeg", ffprobe="ffprobe") -> dict:
    """运行任意怀旧平台（NES/SNES/GBA/GB/MD/PCE/PS1）的 showcase 盘点包并产出合辑。"""
    raw_doc = json.loads(Path(pack_path).read_text(encoding="utf-8"))
    doc = validate_multiplatform_showcase(raw_doc)
    platform = doc.get("platform", "NES").upper()

    def _factory(rom, bizhawk, core=None, system=None, work=None):
        return MultiPlatformStateSession(
            rom=rom, bizhawk=bizhawk, platform=platform,
            core=core or doc.get("core"), system=system or doc.get("system"),
            work=work
        )

    return showcase.run(
        pack_path=pack_path, out_dir=out_dir, only=only,
        template=template, work_dir=work_dir,
        fps=doc.get("fps", PLATFORM_SPECS[platform]["fps"]),
        ffmpeg=ffmpeg, ffprobe=ffprobe,
        session_factory=None if platform == "NES" else _factory
    )


def probe_all_platforms(emu_root=None) -> dict:
    """探测本地所有怀旧平台（NES/SNES/GBA/GB/MD/PCE/PS1/PSP/FBNeo）的模拟器与核心就绪状态。"""
    emu_root = Path(emu_root or R.DEFAULT_EMU)
    bh_dirs = R.discover_bizhawk(emu_root)
    report = {"bizhawk_versions": bh_dirs, "platforms": {}}
    latest_bh = next(iter(sorted(bh_dirs.values(), reverse=True)), None)

    for plat, spec in PLATFORM_SPECS.items():
        if plat in ("NES", "SNES", "GBA", "GB", "GBC", "MD", "PCE", "PS1"):
            avail = bool(latest_bh and (Path(latest_bh) / "EmuHawk.exe").is_file())
            note = f"BizHawk ({latest_bh}) 核心 {spec['default_core']} 已就绪" if avail else "未找到 BizHawk"
            if plat == "PS1":
                from .backends import BizHawkPS1Backend
                ps1_p = BizHawkPS1Backend(bizhawk_dir=latest_bh).probe()
                avail = ps1_p["available"]
                note = "PS1 核心与 BIOS 齐备" if avail else "缺: " + ", ".join(ps1_p["missing"])
            report["platforms"][plat] = {
                "system": spec["system"],
                "core": spec["default_core"],
                "fps": spec["fps"],
                "available": avail,
                "note": note,
            }
        elif plat == "ARCADE_FBNEO":
            from .backends import FBNeoBackend
            fb_p = FBNeoBackend().probe()
            report["platforms"][plat] = {
                "system": "ARCADE",
                "core": "FBNeo",
                "fps": spec["fps"],
                "available": fb_p["available"],
                "note": "; ".join(fb_p.get("notes", [])),
            }
        elif plat == "PSP":
            from .backends import PPSSPPBackend
            psp_p = PPSSPPBackend().probe()
            report["platforms"][plat] = {
                "system": "PSP",
                "core": "PPSSPP",
                "fps": spec["fps"],
                "available": psp_p["available"],
                "note": "PPSSPP 就绪" if psp_p["available"] else "缺: " + ", ".join(psp_p["missing"]),
            }
    return report


def main():
    ap = argparse.ArgumentParser(description="全怀旧平台后端探针与多平台 Showcase 运行器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-platforms", help="列出已建模的全部怀旧平台、核心、手柄按键与内存域")
    sub.add_parser("probe-all", help="探测本地全部怀旧平台模拟器与资源就绪状态")

    p_run = sub.add_parser("run-showcase", help="运行任意怀旧平台的 .showcase.json 盘点包")
    p_run.add_argument("--pack", required=True)
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--only", default=None)
    p_run.add_argument("--template", default=None)
    p_run.add_argument("--work", default=None)

    args = ap.parse_args()
    if args.cmd == "list-platforms":
        out = {
            k: {
                "system": v["system"],
                "default_core": v["default_core"],
                "fps": v["fps"],
                "default_domain": v["default_domain"],
                "buttons": sorted(v["buttons"]),
            }
            for k, v in PLATFORM_SPECS.items()
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    elif args.cmd == "probe-all":
        print(json.dumps(probe_all_platforms(), ensure_ascii=False, indent=2))
    elif args.cmd == "run-showcase":
        only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else None
        res = run_multiplatform_showcase(
            args.pack, args.out, only=only, template=args.template, work_dir=args.work
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(0 if res.get("status") in ("ready", "done") else 2)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
