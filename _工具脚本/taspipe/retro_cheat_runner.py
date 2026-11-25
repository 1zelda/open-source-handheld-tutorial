# -*- coding: utf-8 -*-
"""现成开源库直跑胶水模块：直接调用 stable-retro 内置存档 + 本地 libretro-database/cht 金手指库自动出片。

解决痛点（无需手写开机导航、无需手动查 RAM 地址）：
1. 直接解析本地已有的 `02-模拟器库/已clone仓库/工具与ROM管理/libretro-database/cht/` 下数万款全平台 `.cht` 金手指文件，
   自动提取「全武器 (All Weapons) / 无限能量 (Infinite Energy/Ammo) / 全装甲 (All Armor) / 全魂 (All Souls) / 满气 (Max Power)」
   的真实内存地址与数值，作为**无损候选**报告（compile_status 仅 candidate/blocked，
   证据不足 patches 为空；不注入、不声称已在游戏验证）。
2. 直接对接 `stable-retro`（Farama-Foundation/stable-retro）：
   - 自动复用其内置的 1000+ 款跨平台游戏 `Level1.state`（开机即在第一关受控起点）与 `data.json` 内存变量表；
   - 支持一键导入本地 `roms_verify` 目录并直接调用 `stable_retro` 渲染 MP4，或导出状态给 BizHawk / FBNeo 合成天马边框。

保存位置：F:\\开源掌机教程\\_工具脚本\\taspipe\\retro_cheat_runner.py
运行命令（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.retro_cheat_runner search-cht --platform NES --query "Mega Man"
  py -3 -u -m taspipe.retro_cheat_runner list-retro-games --filter "MegaMan"
  py -3 -u -m taspipe.retro_cheat_runner run-retro-showcase --game "MegaMan-Nes" --out "F:/taspipe_scratch/retro_mm1"
  py -3 -u -m taspipe.retro_cheat_runner auto-inject-cht --pack "taspipe/游戏包/megaman1_weapons.showcase.json" --cht-query "Mega Man"
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT_ROOT = HERE.parent
PROJECT_ROOT = SCRIPT_ROOT.parent

CHT_ROOT = PROJECT_ROOT / "02-模拟器库" / "已clone仓库" / "工具与ROM管理" / "libretro-database" / "cht"
ROMS_VERIFY_ROOT = PROJECT_ROOT / "04-游戏资源库" / "TAS输入录像库" / "roms_verify"
STABLE_RETRO_CLONE = (PROJECT_ROOT / "02-模拟器库" / "已clone仓库"
                      / "TAS与要素采集开源库" / "stable-retro")
RETRO_SPLITS = ("stable", "contrib", "experimental")

# 标准平台码 -> libretro-database/cht 下的目录名映射
CHT_PLATFORM_DIRS = {
    "NES": "Nintendo - Nintendo Entertainment System",
    "SNES": "Nintendo - Super Nintendo Entertainment System",
    "GBA": "Nintendo - Game Boy Advance",
    "GB": "Nintendo - Game Boy",
    "GBC": "Nintendo - Game Boy Color",
    "MD": "Sega - Mega Drive - Genesis",
    "PCE": "NEC - PC Engine - TurboGrafx 16",
    "PS1": "Sony - PlayStation",
    "PSP": "Sony - PlayStation Portable",
    "ARCADE_FBNEO": "FBNeo - Arcade Games",
}


# ===========================================================================
# 1. 解析本地 libretro-database/cht/*.cht 现成金手指文件（无损候选，不执行）
# ===========================================================================
# 已知且语义明确的 cheatN_* 字段；其余字段一律保留原文并整条阻塞。
_KNOWN_CHT_FIELDS = {"desc", "code", "address", "value", "enable", "handler",
                     "big_endian", "rumble"}
# NES Game Genie 字母表，依据 BizHawk NesGameGenieDecoder.cs（源码取证存
# _scratch/tas_taskA_20261120/NesGameGenieDecoder.cs）：A P Z L G I T Y E O X U K S V N
_GG_ALPHABET = set("APZLGITYEOXUKSVN")
_COLON_RE = re.compile(r"(?:0x)?([0-9A-Fa-f]{4,6}):(?:0x)?([0-9A-Fa-f]{1,4})")
_HEX8_RE = re.compile(r"[0-9A-Fa-f]{8}")
_GG_DASH_RE = re.compile(r"[0-9A-Z]{4}-[0-9A-Z]{4}")


def _blk(code, detail=""):
    return {"code": code, "detail": detail}


def _parse_int(s):
    s = s.strip()
    return int(s, 16) if s.lower().startswith("0x") else int(s)


def _map_raw_address(addr, platform):
    """把原始地址码映射到已证明的内存域偏移；证明不足返回 (None, blocker)。

    只实现本轮有明确域语义的两档：NES CPU RAM 直映段、SNES 7E 段 WRAM。
    其余平台/段一律阻塞，不猜基址。
    """
    if platform is None:
        return None, _blk("platform_unproven", "未给平台，不做任何地址域映射")
    if platform == "NES":
        if 0x0000 <= addr <= 0x07FF:
            return {"addr": addr, "domain": "nes_cpu_ram", "width_bits": 8}, None
        if 0x0800 <= addr <= 0x1FFF:
            return None, _blk("nes_mirror_unproven", f"0x{addr:04X} 落在 RAM 镜像段，未证明归一化规则")
        return None, _blk("nes_bus_domain_unproven", f"0x{addr:04X} 非 CPU RAM 直映段")
    if platform == "SNES":
        if 0x7E0000 <= addr <= 0x7FFFFF:
            return {"addr": addr - 0x7E0000, "domain": "snes_wram_offset", "width_bits": 8}, None
        return None, _blk("snes_bus_domain_unproven",
                          f"0x{addr:06X} 是总线地址且不在已证明的 7E WRAM 段，不能当域偏移")
    return None, _blk("raw_address_domain_unproven", f"平台 {platform} 的原始地址域编译规则未实现")


def _classify_code_part(part, platform):
    """单个码段分类。返回 (code_type, patch_or_None, blockers)。"""
    m = _COLON_RE.fullmatch(part)
    if m:
        addr, val = int(m.group(1), 16), int(m.group(2), 16)
        if val > 0xFF:
            return "raw_hex_colon", None, [_blk("value_exceeds_byte", f"值 0x{val:X} 超过单字节，不截断")]
        mapped, b = _map_raw_address(addr, platform)
        if b:
            return "raw_hex_colon", None, [b]
        mapped["value"] = val
        mapped["apply"] = "one_shot_candidate"
        return "raw_hex_colon", mapped, []

    letters = part.upper().replace("-", "")
    if ((len(part) in (6, 8) or _GG_DASH_RE.fullmatch(part.upper()))
            and set(letters) <= _GG_ALPHABET
            and any(c not in "0123456789ABCDEF" for c in letters)):
        return "game_genie", None, [_blk("game_genie_decode_not_implemented", "加密码，未实现解码，不当裸内存写")]

    if _HEX8_RE.fullmatch(part):
        head6, tail2 = int(part[:6], 16), int(part[6:], 16)
        if platform == "SNES":
            if 0x7E0000 <= head6 <= 0x7FFFFF:
                return "snes_par_compact", {"addr": head6 - 0x7E0000, "value": tail2,
                                            "domain": "snes_wram_offset", "width_bits": 8,
                                            "apply": "one_shot_candidate"}, []
            return "snes_par_compact", None, [_blk("snes_par_bank_unproven", f"银行 0x{head6:06X} 不在已证明的 7E WRAM 段")]
        if platform in ("GB", "GBC") and part[:2].upper() == "01":
            return "gb_gameshark", None, [_blk("gb_gameshark_compile_not_implemented", "GB Gameshark 类型码，语义未编译")]
        if platform is None:
            return "encoded_hex8_unproven", None, [_blk("platform_unproven", "8 位十六进制串可能是 SNES PAR / GB Gameshark / 其他，未给平台不猜")]
        return "encoded_hex8_unknown", None, [_blk("unknown_encoding", f"平台 {platform} 下无法证明该 8 位串语义")]

    return "unknown", None, [_blk("unknown_code_part", f"无法识别的码段 {part!r}")]


def _gba_ewram_patch(bus_addr, value, write_width):
    if not 0x02000000 <= bus_addr <= 0x0203FFFF:
        return None, _blk("gba_bus_domain_unproven",
                          f"0x{bus_addr:08X} 不在已证明的 GBA EWRAM 段")
    return {"addr": bus_addr - 0x02000000, "value": value, "domain": "EWRAM",
            "width_bits": 8, "write_width_bits": write_width,
            "bus_address": bus_addr, "apply": "per_frame"}, None


def _compile_gba_codebreaker(code):
    """编译未加密 Code Breaker 的 8/16 位写与 4 型半字滑动写。

    规范：3aaaaaaa 00xx / 8aaaaaaa yyyy / 4aaaaaaa yyyy zzzzxxxx iiii。
    4 型每轮写一个半字，xxxx 是重复次数，iiii 是以字节为单位的地址步长。
    """
    tokens = [tok for tok in re.split(r"[\s+;,]+", code.strip()) if tok]
    patches = []
    code_parts = []
    blockers = []
    types = []
    index = 0
    while index < len(tokens):
        blocker_count = len(blockers)
        head = tokens[index]
        group = [head]
        code_type = "gba_codebreaker"
        width = None
        if (len(head) == 8 and re.fullmatch(r"[0-9A-Fa-f]{8}", head)
                and head[0] in "38" and index + 1 < len(tokens)
                and re.fullmatch(r"(?:[0-9A-Fa-f]{4}|[0-9A-Fa-f]{8})", tokens[index + 1])):
            index += 1
            group.append(tokens[index])
            width = 1 if head[0] == "3" else 2
            code_type = "gba_codebreaker_write"
            value = int(group[1], 16)
            bus_addr = int(head[1:], 16)
            if value >= (1 << (width * 8)):
                blockers.append(_blk("gba_codebreaker_value_too_wide",
                                      f"{head} {group[1]} 超出 {width * 8} 位宽度"))
            else:
                for byte in range(width):
                    patch, blocker = _gba_ewram_patch(
                        bus_addr + byte, (value >> (byte * 8)) & 0xFF, width * 8)
                    if blocker:
                        blockers.append(blocker)
                    else:
                        patches.append(patch)
        elif (len(head) == 8 and re.fullmatch(r"[0-9A-Fa-f]{8}", head)
              and head[0] == "4" and index + 3 < len(tokens)
              and re.fullmatch(r"[0-9A-Fa-f]{4}", tokens[index + 1])
              and re.fullmatch(r"[0-9A-Fa-f]{8}", tokens[index + 2])
              and re.fullmatch(r"[0-9A-Fa-f]{4}", tokens[index + 3])):
            index += 3
            group.extend(tokens[index - 2:index + 1])
            code_type = "gba_codebreaker_slide"
            bus_addr = int(head[1:], 16)
            value = int(group[1], 16)
            value_step = int(group[2][:4], 16)
            repetitions = int(group[2][4:], 16)
            address_step = int(group[3], 16)
            if repetitions == 0 or repetitions > 4096:
                blockers.append(_blk("gba_codebreaker_slide_count_unsafe",
                                      f"重复次数 {repetitions} 不在 1..4096"))
            if address_step == 0 or address_step % 2:
                blockers.append(_blk("gba_codebreaker_slide_step_unproven",
                                      f"半字写的地址步长 {address_step} 不是正偶数"))
            if not blockers:
                for repeat in range(repetitions):
                    current = (value + value_step * repeat) & 0xFFFF
                    current_addr = bus_addr + repeat * address_step
                    for byte in range(2):
                        patch, blocker = _gba_ewram_patch(
                            current_addr + byte, (current >> (byte * 8)) & 0xFF, 16)
                        if blocker:
                            blockers.append(blocker)
                        else:
                            patches.append(patch)
        else:
            if len(head) == 8 and re.fullmatch(r"[0-9A-Fa-f]{8}", head):
                blockers.append(_blk("gba_codebreaker_opcode_unsupported",
                                      f"Code Breaker 类型 {head[0]} 或行结构未实现：{' '.join(group)}"))
            else:
                blockers.append(_blk("gba_codebreaker_line_invalid",
                                      f"非法 Code Breaker 码段：{head!r}"))
        types.append(code_type)
        code_parts.append({"part": " ".join(group), "code_type": code_type,
                           "compilable": len(blockers) == blocker_count})
        index += 1
    if blockers:
        patches = []
    uniq = list(dict.fromkeys(types))
    code_type = uniq[0] if len(uniq) == 1 else "gba_codebreaker_compound"
    if len(code_parts) > 1:
        code_type = "gba_codebreaker_compound"
    return code_type, patches, code_parts, blockers


def parse_libretro_cht(cht_path: Path, platform: str | None = None) -> list[dict]:
    """无损解析 .cht：保留全部原字段与原码，安全分类，证据不足不给可执行补丁。

    compile_status 只有 candidate / blocked，不存在 verified；
    patches 仅含已证明平台+地址域+单字节宽度的无条件映射，否则为空。
    """
    cht_path = Path(cht_path)
    text = cht_path.read_text(encoding="utf-8", errors="replace")
    kv = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip().strip('"').strip("'")

    try:
        total = int(kv.get("cheats", 0) or 0)
    except ValueError:
        total = 0
    entries = []
    for i in range(total):
        prefix = f"cheat{i}_"
        raw_fields = {k[len(prefix):]: v for k, v in kv.items() if k.startswith(prefix)}
        desc = raw_fields.get("desc", f"cheat_{i}")
        code = raw_fields.get("code", "")
        addr_str = raw_fields.get("address", "")
        val_str = raw_fields.get("value", "")

        blockers = []
        for fname in raw_fields:
            if fname not in _KNOWN_CHT_FIELDS:
                blockers.append(_blk("unknown_field", f"cheat{i}_{fname} 语义未知，整条阻塞"))
        if raw_fields.get("handler", "0") not in ("", "0"):
            blockers.append(_blk("unknown_handler", f"handler={raw_fields['handler']!r}"))
        if raw_fields.get("big_endian", "").lower() in ("true", "1"):
            blockers.append(_blk("big_endian_unsupported", "大端写入语义未实现"))
        if raw_fields.get("rumble", "0").lower() not in ("", "0", "false"):
            blockers.append(_blk("rumble_unsupported", f"rumble={raw_fields['rumble']!r}"))

        patches = []
        code_parts = []
        if addr_str and val_str:
            code_type = "retroarch_memory"
            try:
                addr = _parse_int(addr_str)
                val = _parse_int(val_str)
            except ValueError:
                blockers.append(_blk("invalid_integer", f"address={addr_str!r} value={val_str!r}"))
            else:
                if addr < 0:
                    blockers.append(_blk("negative_address", str(addr)))
                if val < 0:
                    blockers.append(_blk("negative_value", f"{val} 不做补码猜测"))
                elif val > 0xFF:
                    blockers.append(_blk("value_exceeds_byte", f"{val} 超过单字节，不截断"))
                elif platform is None:
                    blockers.append(_blk("platform_unproven", "RetroArch 内存偏移须绑定平台后才可执行"))
                elif not blockers:
                    patches.append({"addr": addr, "value": val,
                                    "domain": "libretro_system_ram_offset",
                                    "width_bits": 8, "apply": "per_frame"})
        elif code:
            if platform == "GBA":
                code_type, patches, code_parts, code_blockers = _compile_gba_codebreaker(code)
                blockers.extend(code_blockers)
                if blockers:
                    patches = []
            else:
                parts = [p for p in re.split(r"[+;,\s]+", code) if p]
                part_patches = []
                types = []
                for part in parts:
                    ptype, patch, pbl = _classify_code_part(part, platform)
                    types.append(ptype)
                    code_parts.append({"part": part, "code_type": ptype,
                                       "compilable": patch is not None and not pbl})
                    if pbl:
                        blockers.extend(pbl)
                    elif patch is not None:
                        part_patches.append(patch)
                uniq = list(dict.fromkeys(types))
                code_type = uniq[0] if len(uniq) == 1 else "compound_mixed"
                # 复合码整体分析：任一段不可编译则整条不给补丁，绝不输出半截
                if not blockers and len(part_patches) == len(parts):
                    patches = part_patches
        else:
            code_type = "empty"
            blockers.append(_blk("no_code_or_address", "既无 code 也无 address/value"))

        entries.append({
            "index": i,
            "desc": desc,
            "code": code,
            "source_file": str(cht_path),
            "raw_fields": raw_fields,
            "code_type": code_type,
            "code_parts": code_parts,
            "compound": len(code_parts) > 1,
            "compile_status": "candidate" if patches and not blockers else "blocked",
            "blockers": blockers,
            "patches": patches,
        })
    return entries


def search_local_chts(platform: str, query: str, cht_root: Path = CHT_ROOT,
                      file_offset: int = 0, file_limit: int | None = 10,
                      cheat_offset: int = 0, cheat_limit: int | None = 40,
                      include_all: bool = False) -> dict:
    """搜索本地 .cht 并分类候选。总数/返回数/截断标志逐格可核对。

    file_limit / cheat_limit 传 None 表示不截断；include_all=True 时附带每文件全部条目。
    同名不同版本文件全部保留，不做去重、不默认采用第一份。
    """
    plat_key = (platform or "NES").upper()
    sub_name = CHT_PLATFORM_DIRS.get(plat_key, "")
    target_dir = Path(cht_root) / sub_name if sub_name else Path(cht_root)
    if not target_dir.is_dir():
        return {
            "status": "missing_cht_dir",
            "expected_dir": str(target_dir),
            "hint": "请确认 02-模拟器库/已clone仓库/工具与ROM管理/libretro-database 已完整检出",
            "matches": [],
        }

    q_words = [w.lower() for w in re.split(r"\s+", query.strip()) if w]
    matched_files = []
    for p in sorted(target_dir.glob("*.cht")):
        low = p.stem.lower()
        if all(w in low for w in q_words):
            matched_files.append(p)

    keyword_re = re.compile(
        r"weapon|energy|ammo|infinite|all\s+|have\s+|unlock|armor|soul|magic|power|beam|bomb|cutter|fire|ice|thunder|magnet|hadoken|invinc",
        re.I,
    )
    window = matched_files[file_offset:]
    if file_limit is not None:
        window = window[:file_limit]
    results = []
    blocker_summary = {}
    for pf in window:
        parsed = parse_libretro_cht(pf, platform=plat_key)
        useful = [e for e in parsed if keyword_re.search(e["desc"])]
        cwin = useful[cheat_offset:]
        if cheat_limit is not None:
            cwin = cwin[:cheat_limit]
        for e in parsed:
            for b in e["blockers"]:
                blocker_summary[b["code"]] = blocker_summary.get(b["code"], 0) + 1
        row = {
            "cht_file": str(pf),
            "source_sha256": hashlib.sha256(pf.read_bytes()).hexdigest(),
            "total_cheats": len(parsed),
            "useful_total": len(useful),
            "cheat_offset": cheat_offset,
            "useful_returned": len(cwin),
            "useful_truncated": cheat_offset + len(cwin) < len(useful),
            "useful_element_cheats": cwin,
        }
        if include_all:
            row["all_cheats"] = parsed
            row["all_cheats_returned"] = len(parsed)
        results.append(row)

    return {
        "status": "ok",
        "platform": plat_key,
        "query": query,
        "cht_root": str(target_dir),
        "files_found": len(matched_files),
        "file_offset": file_offset,
        "files_returned": len(results),
        "files_truncated": file_offset + len(results) < len(matched_files),
        "results": results,
        "totals_returned_files": {
            "parsed": sum(r["total_cheats"] for r in results),
            "useful": sum(r["useful_total"] for r in results),
            "useful_returned": sum(r["useful_returned"] for r in results),
        },
        "blocker_summary": blocker_summary,
        "note": "候选报告：未注入任何游戏包、未在游戏中验证；compile_status 无 verified。",
    }


# ===========================================================================
# 2. 对接 Farama-Foundation/stable-retro（免手写开机导航，直接用内置 Level1.state）
# ===========================================================================
def check_stable_retro() -> dict:
    """检查当前 Python 环境是否已安装 stable-retro，并返回内置支持的游戏数量。"""
    try:
        import stable_retro
        games = stable_retro.data.list_games()
        return {
            "installed": True,
            "version": getattr(stable_retro, "__version__", "unknown"),
            "builtin_games_count": len(games),
        }
    except ImportError:
        return {
            "installed": False,
            "install_cmd": "pip install stable-retro gymnasium[other] moviepy",
            "note": "安装后可直接复用 1000+ 款跨平台游戏的内置开局 .state 快照与 data.json 内存表",
        }


def _normalize_data_root(root):
    """接受 data 目录本身或仓库根目录，返回 (data_root, error)。"""
    p = Path(root)
    for cand in (p, p / "stable_retro" / "data"):
        if cand.is_dir() and any((cand / s).is_dir() for s in RETRO_SPLITS):
            return cand, None
    return None, (f"{p}（及其 stable_retro/data 子目录）下未找到 "
                  f"{'/'.join(RETRO_SPLITS)} 任何 split 目录")


def _scan_data_root(data_root):
    """逐 split 枚举全部游戏目录的只读盘点。不完整目录显式报缺，不静默丢弃。

    不用 stable_retro.data.list_games()：它默认只看 stable、按 rom.sha 筛选、
    跨 split 合并重名，会漏掉需要报告的不完整目录（任务书 §6 修订口径）。
    """
    records, bad_json = [], []
    per_split = {}
    for split in RETRO_SPLITS:
        sdir = data_root / split
        games = sorted(d for d in sdir.iterdir() if d.is_dir()) if sdir.is_dir() else []
        split_states = split_scen = split_data = 0
        for g in games:
            states = sorted(p.stem for p in g.glob("*.state"))
            has_data = (g / "data.json").is_file()
            has_sha = (g / "rom.sha").is_file()
            has_scen = (g / "scenario.json").is_file()
            data_valid = None
            if has_data:
                try:
                    json.loads((g / "data.json").read_text(encoding="utf-8"))
                    data_valid = True
                except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
                    data_valid = False
                    bad_json.append({"path": str(g / "data.json"), "error": str(e)})
            missing = []
            if not has_data:
                missing.append("data.json")
            if not has_sha:
                missing.append("rom.sha")
            if not states:
                missing.append("*.state")
            records.append({
                "game": g.name, "split": split,
                "rel_path": f"{split}/{g.name}",
                "data_json": has_data, "data_json_valid": data_valid,
                "rom_sha": has_sha, "scenario_json": has_scen,
                "states": states, "state_count": len(states),
                "missing": missing,
            })
            split_states += len(states)
            split_scen += int(has_scen)
            split_data += int(has_data)
        per_split[split] = {
            "exists": sdir.is_dir(), "game_dirs": len(games),
            "dirs_with_data_json": split_data,
            "state_files": split_states, "scenario_files": split_scen,
        }
    names = {}
    for r in records:
        names.setdefault(r["game"], []).append(r["split"])
    duplicates = [{"game": n, "splits": s} for n, s in sorted(names.items()) if len(s) > 1]
    counts = {
        "game_dirs_total": len(records),
        "dirs_with_data_json": sum(r["data_json"] for r in records),
        "dirs_with_valid_data_json": sum(r["data_json_valid"] is True for r in records),
        "state_files_total": sum(r["state_count"] for r in records),
        "scenario_files_total": sum(r["scenario_json"] for r in records),
        "unique_game_names": len(names),
        "incomplete_dirs": sum(bool(r["missing"]) for r in records),
    }
    return {"records": records, "bad_json": bad_json, "per_split": per_split,
            "counts": counts, "duplicates": duplicates}


def discover_stable_retro(root=None, filter_str="", offset=0, limit=50):
    """统一只读资源发现：显式 root 优先；否则包安装位置与源码克隆都进同一套盘点。

    计数一律现算；limit=None 取全部。任何失败都返回结构化原因，不返回空字典。
    """
    candidates = []
    if root is not None:
        candidates.append((root, "explicit"))
    else:
        try:
            import stable_retro
            candidates.append((stable_retro.data.path(), "installed_package"))
        except Exception:
            pass
        candidates.append((STABLE_RETRO_CLONE / "stable_retro" / "data", "source_clone"))
    roots, all_records, all_bad = [], [], []
    per_root_split, dup_sets = {}, {}
    for path, tag in candidates:
        data_root, err = _normalize_data_root(path)
        if err:
            roots.append({"tag": tag, "path": str(path), "status": "error", "reason": err})
            continue
        scan = _scan_data_root(data_root)
        roots.append({"tag": tag, "path": str(path), "data_root": str(data_root),
                      "status": "ok", "counts": scan["counts"],
                      "duplicates": scan["duplicates"]})
        per_root_split[tag] = scan["per_split"]
        for r in scan["records"]:
            all_records.append({**r, "root_tag": tag, "root": str(data_root)})
            dup_sets.setdefault(r["game"], set()).add((tag, r["split"]))
        all_bad.extend({**b, "root_tag": tag} for b in scan["bad_json"])
    if not any(r["status"] == "ok" for r in roots):
        return {"status": "no_data_root", "roots": roots,
                "reason": "没有可盘点的 stable-retro 数据根（显式 root 无效或包/克隆均缺失）"}
    q = filter_str.lower()
    matched = [r for r in all_records if q in r["game"].lower()] if q else all_records
    matched.sort(key=lambda r: (r["root_tag"], r["split"], r["game"]))
    total = len(matched)
    page = matched[offset:] if limit is None else matched[offset:offset + limit]
    agg = {}
    for r in roots:
        if r["status"] != "ok":
            continue
        for k, v in r["counts"].items():
            agg[k] = agg.get(k, 0) + v
    cross_dup = [{"game": n, "locations": sorted(f"{t}/{s}" for t, s in locs)}
                 for n, locs in sorted(dup_sets.items()) if len(locs) > 1]
    return {
        "status": "ok", "source": "filesystem_inventory",
        "installed": check_stable_retro()["installed"],
        "roots": roots, "per_split": per_root_split,
        "counts": agg, "bad_json": all_bad, "duplicates_within_root":
            [d for r in roots if r["status"] == "ok" for d in r["duplicates"]],
        "duplicates_across_roots": cross_dup,
        "filter": filter_str, "total_records": total,
        "offset": offset, "limit": limit, "returned_count": len(page),
        "records": page,
    }


def list_stable_retro_games(filter_str: str = "", root=None, offset=0, limit=50) -> dict:
    res = discover_stable_retro(root=root, filter_str=filter_str,
                                offset=offset, limit=limit)
    if res["status"] == "ok":
        res["matched_count"] = res["total_records"]
        res["games"] = res["records"]
    return res


def run_stable_retro_showcase(game_name: str, out_dir: Path, steps: int = 180, import_dir: Path = ROMS_VERIFY_ROOT) -> dict:
    """直接用 stable-retro 内置开局存档跑动作展示并输出 MP4（完全免写开机导航）。"""
    info = check_stable_retro()
    if not info["installed"]:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return info

    import stable_retro
    from PIL import Image

    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 若指定了本地 ROM 目录，先自动导入匹配 SHA-1 的 ROM
    if import_dir and import_dir.is_dir():
        subprocess.run([sys.executable, "-m", "stable_retro.import", str(import_dir)], capture_output=True)

    states = stable_retro.data.list_states(game_name)
    state_to_use = states[0] if states else stable_retro.State.DEFAULT
    bk2_dir = out_dir / "bk2_records"
    frames_dir = out_dir / "frames"
    bk2_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    env = stable_retro.make(
        game=game_name,
        state=state_to_use,
        record=str(bk2_dir),
        render_mode="rgb_array",
    )
    obs, _ = env.reset()
    ram_vars = {}
    for idx in range(steps):
        # 示范触发：交替进行攻击与方向移动，同时自动抓取 RGB 帧与内置 data.json 内存变量
        action = env.action_space.sample()
        obs, rew, terminated, truncated, step_info = env.step(action)
        if idx == 0 and step_info:
            ram_vars = {k: int(v) for k, v in step_info.items() if isinstance(v, (int, float))}
        img = Image.fromarray(obs)
        img.save(frames_dir / f"f{idx:04d}.png")
        if terminated or truncated:
            env.reset()
    env.close()

    # 编码为标准 MP4
    mp4_out = out_dir / f"{game_name}_{state_to_use}.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-framerate", "60",
        "-i", str(frames_dir / "f%04d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
        str(mp4_out),
    ], check=True)

    res = {
        "status": "done",
        "game": game_name,
        "builtin_state_used": str(state_to_use),
        "builtin_ram_variables_sample": ram_vars,
        "mp4": str(mp4_out),
        "bk2_dir": str(bk2_dir),
    }
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def auto_inject_cht_into_pack(pack_path: Path, cht_query: str,
                              out_path: Path | None = None,
                              file_limit: int | None = None,
                              cheat_limit: int | None = None,
                              cht_root: Path = CHT_ROOT) -> dict:
    """只读检索本地 .cht，生成候选报告写到新路径；不改游戏包一个字节，不注入、不声称已验证。"""
    pack_path = Path(pack_path)
    pack_sha_before = hashlib.sha256(pack_path.read_bytes()).hexdigest()
    doc = json.loads(pack_path.read_text(encoding="utf-8"))
    plat = doc.get("platform", "NES")
    found = search_local_chts(plat, cht_query, cht_root=cht_root, file_limit=file_limit,
                              cheat_limit=cheat_limit, include_all=True)
    pack_sha_after = hashlib.sha256(pack_path.read_bytes()).hexdigest()
    report = dict(found)
    report.update({
        "report_kind": "cheat_candidates_only",
        "injected": False,
        "verified_in_game": False,
        "pack": str(pack_path),
        "pack_sha256": pack_sha_before,
        "pack_sha256_after": pack_sha_after,
        "pack_unchanged": pack_sha_before == pack_sha_after,
    })
    out_report = Path(out_path) if out_path else pack_path.with_suffix(".cht_candidates.json")
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "pack": str(pack_path),
        "platform": plat,
        "cht_files_found": found.get("files_found", 0),
        "candidates_saved_to": str(out_report),
        "pack_unchanged": report["pack_unchanged"],
        "injected": False,
    }, ensure_ascii=False, indent=2))
    return report


def _limit_arg(s):
    if s is None or str(s).lower() == "all":
        return None
    return int(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_cht = sub.add_parser("search-cht", help="在本地 libretro-database/cht 中搜索游戏金手指候选（无损分类，不执行）")
    p_cht.add_argument("--platform", default="NES", choices=sorted(CHT_PLATFORM_DIRS))
    p_cht.add_argument("--query", required=True, help="游戏英文名关键词，如 'Mega Man' / 'Contra' / 'Aria of Sorrow'")
    p_cht.add_argument("--file-offset", type=int, default=0)
    p_cht.add_argument("--file-limit", default="10", help="返回文件数上限，'all' 取全部")
    p_cht.add_argument("--cheat-offset", type=int, default=0)
    p_cht.add_argument("--cheat-limit", default="40", help="每文件返回候选条数上限，'all' 取全部")
    p_cht.add_argument("--include-all", action="store_true", help="附带每文件全部条目（含未过关键词筛选的）")
    p_cht.add_argument("--out", default="", help="把完整 JSON 报告写到该新路径")

    p_list = sub.add_parser("list-retro-games", help="只读盘点 stable-retro 数据根（逐 split、含不完整目录）")
    p_list.add_argument("--filter", default="", help="按游戏名过滤")
    p_list.add_argument("--root", default=None, help="显式数据根或仓库根；缺省扫包安装位置+源码克隆")
    p_list.add_argument("--offset", type=int, default=0)
    p_list.add_argument("--limit", default="50", help="返回条数上限，'all' 取全部")
    p_list.add_argument("--export", default="", help="完整清单（不分页）写到该新路径，已存在则拒绝")

    p_run = sub.add_parser("run-retro-showcase", help="直接用 stable-retro 内置 Level1.state 跑录制并生成 MP4")
    p_run.add_argument("--game", required=True, help="如 MegaMan2-Nes / SuperMetroid-Snes / StreetsOfRage2-Genesis")
    p_run.add_argument("--steps", type=int, default=180)
    p_run.add_argument("--out", required=True)

    p_inj = sub.add_parser("auto-inject-cht", help="只读检索 .cht 生成候选报告（不注入、不改游戏包）")
    p_inj.add_argument("--pack", required=True)
    p_inj.add_argument("--cht-query", required=True)
    p_inj.add_argument("--out", default="", help="报告输出新路径；缺省为包旁 .cht_candidates.json")
    p_inj.add_argument("--file-limit", default="all")
    p_inj.add_argument("--cheat-limit", default="all")

    args = ap.parse_args()
    if args.cmd == "search-cht":
        res = search_local_chts(args.platform, args.query,
                                file_offset=args.file_offset,
                                file_limit=_limit_arg(args.file_limit),
                                cheat_offset=args.cheat_offset,
                                cheat_limit=_limit_arg(args.cheat_limit),
                                include_all=args.include_all)
        if args.out:
            outp = Path(args.out)
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"saved_to": str(outp), "files_found": res.get("files_found"),
                              "files_returned": res.get("files_returned")}, ensure_ascii=False))
        else:
            print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "list-retro-games":
        if args.export:
            outp = Path(args.export)
            if outp.exists():
                print(f"拒绝覆盖已存在的导出文件: {outp}", file=sys.stderr)
                sys.exit(2)
            full = discover_stable_retro(root=args.root, filter_str=args.filter,
                                         offset=0, limit=None)
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(json.dumps(full, ensure_ascii=False, indent=1), encoding="utf-8")
            print(json.dumps({"saved_to": str(outp), "status": full["status"],
                              "total_records": full.get("total_records"),
                              "counts": full.get("counts")}, ensure_ascii=False))
        else:
            res = list_stable_retro_games(args.filter, root=args.root,
                                          offset=args.offset, limit=_limit_arg(args.limit))
            print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "run-retro-showcase":
        run_stable_retro_showcase(args.game, Path(args.out), steps=args.steps)
    elif args.cmd == "auto-inject-cht":
        auto_inject_cht_into_pack(Path(args.pack), args.cht_query,
                                  out_path=Path(args.out) if args.out else None,
                                  file_limit=_limit_arg(args.file_limit),
                                  cheat_limit=_limit_arg(args.cheat_limit))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
