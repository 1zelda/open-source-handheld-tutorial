"""游戏控制任务：盘点、规划、TAS/宏执行、ROM 副本修改与续跑。"""
import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import uuid
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from taspipe import popularity
from taspipe import registry as R
from taspipe.schema import SchemaError, asset, core_identity_expectation, sha256_file, split_rom_spec

HERE = Path(__file__).resolve().parent
DEFAULT_WORK = Path(HERE.anchor) / "taspipe_scratch" / "control_runtime"
NAME = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
CMP = {"eq", "ne", "ge", "le"}


def _object(value, allowed, required=(), label="配置"):
    if not isinstance(value, dict):
        raise SchemaError(f"{label} 必须是对象")
    unknown = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unknown or missing:
        raise SchemaError(f"{label} 未知字段={sorted(unknown)} 缺字段={sorted(missing)}")
    return value


def _integer(value, label, lo=0, hi=0x7FFFFFFF):
    if type(value) is not int or not lo <= value <= hi:
        raise SchemaError(f"{label} 必须是 {lo}..{hi} 的整数")
    return value


def _name(value, label):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise SchemaError(f"{label} 仅允许 1..80 个 ASCII 字母、数字、下划线、短横线")
    return value


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{label} 必须是非空字符串")
    return value


def _path(value, base):
    p = Path(_text(value, "路径"))
    return str((p if p.is_absolute() else base / p).resolve())


def _rom_path(value, base):
    """解析 ROM 寻址：只让包路径过文件系统，压缩包条目名逐字符保留。

    Path.resolve() 会把 `包.zip!a/b.sfc` 里的 / 改成 \\，之后 zf.read 找不到条目
    （11-21 接压缩包寻址时实测到这条假 missing_rom）。
    """
    archive, entry = split_rom_spec(_text(value, "路径"))
    resolved = _path(str(archive), base)
    return f"{resolved}!{entry}" if entry is not None else resolved


def _hash(value, length, label):
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value):
        raise SchemaError(f"{label} 必须是 {length} 位十六进制")
    return value.lower()


def _list(value, label, empty=False):
    if not isinstance(value, list) or (not empty and not value):
        raise SchemaError(f"{label} 必须是{'可空' if empty else '非空'}数组")
    return value


def _address(value):
    if isinstance(value, str) and re.fullmatch(r"0[xX][0-9a-fA-F]+", value):
        value = int(value, 16)
    return _integer(value, "地址", hi=0xFFFFFFFF)


def _evidence(raw, ident):
    """通关判据的证词：哪一步的截图、那张图的字节摘要、人眼在上面读到了什么。

    11-21 实测教训：3232 塞尔达的 $051C==100 在第 74403 帧成立，terminal 语义的
    false_frames/fell_back 四项全过，判定 completion=pass；而把那张截图放大一看，
    画面上写的是 GAME OVER——那是死亡淡出，通关淡出用的也是同一个字节。
    纯 RAM 断言自证不了"这是什么局面"，所以声称通关必须附一张可核对的图。
    """
    _object(raw, {"checkpoint", "seen", "sha256", "frame_tolerance"},
            {"checkpoint", "seen", "sha256"}, label=f"completion.checks[{ident}].evidence")
    row = {"checkpoint": _name(raw["checkpoint"], "evidence.checkpoint"),
           "seen": _text(raw["seen"], "evidence.seen"),
           "sha256": _text(raw["sha256"], "evidence.sha256").strip().lower()}
    if not row["seen"].strip():
        raise SchemaError(f"completion.checks[{ident}].evidence.seen 不能是空串，要写清那一帧画面上有什么")
    if any(c in row["seen"] for c in "\r\n\0"):
        raise SchemaError(f"completion.checks[{ident}].evidence.seen 不得含控制字符")
    if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
        raise SchemaError(f"completion.checks[{ident}].evidence.sha256 不是 64 位十六进制摘要")
    row["frame_tolerance"] = _integer(raw.get("frame_tolerance", 0), "evidence.frame_tolerance", 0, 600)
    return row


def _memory(items, kind, allow_latch=False):
    result, ids = [], set()
    for i, item in enumerate(_list(items, kind)):
        extra = {"cmp", "value"} if kind == "checks" else {"value", "expect"} if kind == "writes" else set()
        if allow_latch:
            extra |= {"latch", "evidence"}
        required = {"domain", "addr"} | ({"value"} if kind == "writes" else {"id"})
        if kind == "checks":
            required |= {"cmp", "value"}
        _object(item, {"id", "domain", "addr", "width", "endian"} | extra, required, kind)
        row = dict(item)
        if allow_latch:
            # latch=true：这条判据在重放过程中逐帧求值，只要出现过一次成立就算过，
            # 并把首次成立的帧号记进产物。塞尔达(3232)带 "Uses a game restart sequence"
            # 标签、洛克人X2(5628) 末帧已经回到标题画面——这两部只在末帧求值都会把
            # 真通关判成 fail，所以"曾经成立"必须是判据的一等模式，不是靠人眼看录像。
            # latch="terminal"：只认最后一段不间断成立（片尾仍成立 + 中途确实回落过）。
            # 11-21 实测吃过教训：3232 的 $051C 在 52343 帧就摸到过 100，74420 帧起才
            # 不回落；once 语义把中段淡出当成了通关。两种语义分开，不许混用。
            # 不成立时整键删掉：老任务的 program 字节不变，指纹不会因为新增字段而漂移。
            if "latch" in row:
                if row["latch"] == "terminal":
                    pass
                elif type(row["latch"]) is not bool:
                    raise SchemaError("completion.checks.latch 只能是布尔值或字符串 \"terminal\"")
                elif not row["latch"]:
                    del row["latch"]
        row["domain"] = _text(row["domain"], "domain")
        if any(c in row["domain"] for c in "\r\n\0"):
            raise SchemaError("domain 不得含控制字符")
        row["addr"] = _address(row["addr"])
        row["width"] = _integer(row.get("width", 1), "width", 1, 4)
        if row["width"] not in (1, 2, 4):
            raise SchemaError("width 仅支持 1/2/4 字节")
        row["endian"] = row.get("endian", "little")
        if row["endian"] not in ("little", "big"):
            raise SchemaError("endian 必须是 little 或 big")
        if row["addr"] + row["width"] > 0x100000000:
            raise SchemaError("地址加宽度越界")
        row["id"] = _name(row.get("id", f"write_{i}"), "观测 ID")
        if row["id"] in ids:
            raise SchemaError(f"重复观测 ID: {row['id']}")
        ids.add(row["id"])
        if allow_latch and "evidence" in row:
            row["evidence"] = _evidence(row["evidence"], row["id"])
        if kind == "checks" and (not isinstance(row["cmp"], str) or row["cmp"] not in CMP):
            raise SchemaError(f"不支持比较符 {row['cmp']}")
        for key in ("value", "expect"):
            if key in row:
                row[key] = _integer(row[key], key, hi=(1 << (8 * row["width"])) - 1)
        result.append(row)
    if kind == "writes":
        occupied = set()
        for row in result:
            for addr in range(row["addr"], row["addr"] + row["width"]):
                key = row["domain"], addr
                if key in occupied:
                    raise SchemaError("同一次 patch 不允许重叠写入")
                occupied.add(key)
    return result


def _players(value, platform):
    from taspipe.retro_platforms import PLATFORM_SPECS
    if not isinstance(value, dict):
        raise SchemaError("players 必须是玩家编号到按键数组的对象")
    allowed = PLATFORM_SPECS[platform]["buttons"]
    result = {}
    for player, buttons in value.items():
        if player not in ("1", "2", "3", "4"):
            raise SchemaError("玩家编号必须是字符串 1..4")
        _list(buttons, "buttons", empty=True)
        if any(not isinstance(b, str) or b not in allowed for b in buttons):
            raise SchemaError(f"{platform} 未知按键 {buttons}，允许 {sorted(allowed)}")
        if len(set(buttons)) != len(buttons):
            raise SchemaError("按键不得重复")
        result[player] = list(buttons)
    return result


def compile_macro(parts, macros, platform, stack=()):
    result = []
    for part in _list(parts, "宏段"):
        if not isinstance(part, dict):
            raise SchemaError("宏段必须是对象")
        if "use" in part:
            _object(part, {"use", "repeat"}, {"use"}, "宏引用")
            name = _name(part["use"], "宏名")
            if name not in macros:
                raise SchemaError(f"宏未定义: {name}")
            if name in stack:
                raise SchemaError(f"宏循环引用: {' -> '.join((*stack, name))}")
            n = _integer(part.get("repeat", 1), "repeat", 1, 100000)
            nested = compile_macro(macros[name], macros, platform, (*stack, name))
            if len(result) + len(nested) * n > 100000:
                raise SchemaError("单宏展开超过 100000 段，请分任务执行")
            for _ in range(n):
                result.extend(deepcopy(nested))
        elif "notation" in part:
            from taspipe.macro_compiler import compile_notation
            _object(part, {"notation", "facing", "dir_frames", "attack_hold", "charge_frames", "player"},
                    {"notation"}, "招式记法")
            if part.get("facing", "right") not in ("left", "right"):
                raise SchemaError("facing 必须为 left/right")
            kwargs = {k: part[k] for k in ("facing", "dir_frames", "attack_hold", "charge_frames") if k in part}
            for key in ("dir_frames", "attack_hold", "charge_frames"):
                if key in kwargs:
                    _integer(kwargs[key], key, 1, 100000)
            notation = _text(part["notation"], "notation")
            # 上游编译器会忽略部分未知字符；先限制到已实现的记法语法。
            from taspipe.macro_compiler import PRESET_MACROS, SHORTHAND_MOTIONS
            preset = notation.lstrip("@").upper()
            motion = notation.split("+", 1)[0].upper()
            numeric = re.fullmatch(r"(?:\[[1-9]\]|[1-9])+?(?:\+[A-Za-z0-9]+)*", notation)
            arrows = re.fullmatch(r"[↓↑←→↘↙↖↗蓄]+(?:\+[A-Za-z0-9]+)*", notation)
            if preset not in PRESET_MACROS and motion not in SHORTHAND_MOTIONS and not numeric and not arrows:
                raise SchemaError("notation 请用数字/箭头+按键、已登记简写或 @预设；精确按键请用 players")
            if preset in PRESET_MACROS and PRESET_MACROS[preset].get("platform") != platform:
                raise SchemaError("预设宏所属平台不匹配")
            raw = ("," * (kwargs.get("dir_frames", 2) - 1) if notation == "5"
                   else compile_notation(notation, platform=platform, **kwargs))
            player = str(_integer(part.get("player", 1), "player", 1, 4))
            for frame in raw.split(","):
                result.append({"frames": 1, "players": _players({player: frame.split("+") if frame else []}, platform)})
        else:
            _object(part, {"frames", "players"}, {"frames"}, "输入段")
            result.append({"frames": _integer(part["frames"], "frames", 1),
                           "players": _players(part.get("players", {}), platform)})
        if len(result) > 100000:
            raise SchemaError("单宏展开超过 100000 段")
    return result


def _header_value(header, name):
    # 同一个键有两种写法：上游电影写 VBlankCount，BizHawk 导入器写 vblankCount。
    for key, value in header.items():
        if key.lower() == name.lower():
            return value.strip()
    return None


def _header_int(header, name):
    try:
        return int(_header_value(header, name))
    except (TypeError, ValueError):
        return None


def _header_float(header, name):
    raw = _header_value(header, name)
    if raw is None:
        return None
    # 老 BizHawk 按本机区域把小数点写成逗号（ClockRate 5369318,18181818）。
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _bk2_frames(header, lines):
    """输入日志的行数只在"一行=一帧"的核心上等于帧数。

    实测 NesHawk：4751/4812/5231/5246/5254/3232 六部按行数跑完整部电影，心跳里的实到帧数与行数
    逐帧相等（39084、40680、43443、45472、4509、80384），所以非子帧核心的行数就是帧数。
    实测子帧核心（本地 12 部 SubNESHawk）：行数不是帧数——6012 有 5,788,209 行而真实只有 1.76 万帧，
    按行数展开会跑出 329 倍的荒谬长度。帧数来源按 CycleCount/ClockRate×平台 fps 折，
    9 部这样折出来与站点时长折的帧数 0.000% 相同（写死 60 会统一偏低 0.14~0.19%）；
    剩下 3 部没有 CycleCount，VBlankCount 本身就等于站点帧数（4065: 6736、4135: 9195、4567: 13），
    减 1 反而每部少 1 帧。
    """
    core = (_header_value(header, "Core") or "").lower()
    if not core.startswith("sub"):
        return lines, "input_log"
    from taspipe.retro_platforms import PLATFORM_SPECS
    platform = _header_value(header, "Platform") or ""
    key = next((k for k in PLATFORM_SPECS if k.lower() == platform.lower()), None)
    if key is None:
        raise SchemaError(f"子帧核心电影的平台 {platform or '(缺)'} 不在 PLATFORM_SPECS 里，折不出帧数")
    fps = PLATFORM_SPECS[key]["fps"]
    cycle, rate = _header_int(header, "CycleCount"), _header_float(header, "ClockRate")
    if cycle is not None and rate:
        return max(round(cycle / rate * fps), 1), "cycle_count"
    vblank = _header_int(header, "VBlankCount")
    if vblank is not None and vblank > 1:
        return vblank, "vblank_count"
    raise SchemaError("子帧核心电影没有可确定的帧数来源（既无 CycleCount+ClockRate，也无 VBlankCount）")


def _version_trim(text):
    """2.3.0 与目录 BizHawk-2.3 是同一个版本；只裁末段为 0 的那一节，2.9.1 不许裁成 2.9。"""
    parts = str(text).split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


DRIVER_STALLED_BIZHAWK = ("2.3", "2.3.1")
DRIVER_OK_BIZHAWK = ("2.8", "2.9", "2.9.1", "2.10", "2.11")

# 控制运行器「实测跑过整片」的平台白名单，判据是 execution=pass + 输入行全消费 + 末帧真看过图，
# 不是 schema 里有 spec。
#   NES  —— 塞尔达 80384 帧、忍者龙剑传1 39084 帧等若干部。
#   SNES —— 11-21 pub_5628 洛克人X2（BSNES @ BizHawk 2.9.1，ROM 来自
#           F:\BaiduNetdiskDownload\rom\snes\洛克人 X2.zip）：events 末条
#           consumed_inputs=frames_advanced=111725（Input Log 全消费），
#           length_check 111725 vs 站点 111724（Δ1 帧 = 0.0009%，在 0.5% 容差内），
#           runtime/final.png 是真渲染画面（标题画面，非黑屏/报错框）。
#           注意这只证明"驱动得动整片"，不证明通关：该片 completion 仍 inconclusive
#           （末帧回到标题画面，通关判据还没写）。
# GBA/GB/MD/PCE 那批 ROM 齐但本机一部没驱动过，报成「只差 ROM」就是假绿灯。
# 实测成功后把平台码加进来并在旁边写下证据。
PLATFORMS_DRIVER_PROVEN = ("NES", "SNES")
NON_DEGRADABLE_BLOCKERS = frozenset({"audio_not_wired"})


def platform_driver_proven(code):
    """平台码（schema Platform 值或 PLATFORM_SPECS 键）是否已有整片实测证据。"""
    return str(code or "") in PLATFORMS_DRIVER_PROVEN


def driver_stall_version(bizhawk_dir_name):
    """本机实测：BizHawk 2.3/2.3.1 在本驱动下一步不推进。

    证据：pub_3789（BizHawk-2.3，NesHawk，realtime）、pub_4003（BizHawk-2.3.1，realtime 与
    unthrottled 两档）三条实跑到 `step_started` 后 heartbeat 恒为 `0 running 0 0`，60 秒零帧被杀；
    同期 2.8/2.9/2.9.1/2.10/2.11 全部正常推进（含 6012 的 realtime 子帧片 17588 帧）。
    因此拦的是版本，不是速度档；2.4~2.7 本机没装，不在此表里，也不据此拦。
    """
    m = re.search(r"\d+(?:\.\d+)*", str(bizhawk_dir_name))
    if not m:
        return None
    ver = _version_trim(m.group())
    return ver if ver in DRIVER_STALLED_BIZHAWK else None


# NES 各核心 System Bus 实测可读窗口。QuickNes 读 $4000-$7FFF 拿到的是总线浮值：同一片电影
# 31000 与 33059 两帧该窗口 8192/8192 逐字节相同，NesHawk 同窗口 0/8192 相同（证据见说明书 §33）。
# quickerNES / Sub* 未实测，因此不进表=不拦，缺口按 §33 记录。
NES_READABLE_WINDOWS = {
    "QuickNes": ((0x0000, 0x2000), (0x8000, 0x10000)),
    "NesHawk": ((0x0000, 0x10000),),
}


def _memory_items(program):
    """把程序里所有会读写内存的条目摊平成 (出处, 条目)，供启动前闸门检查地址可达性。"""
    for item in program.get("completion") or []:
        yield "completion", item
    for step in program.get("steps") or []:
        for kind in ("checks", "watches", "writes"):
            for item in step.get(kind) or []:
                yield f"step {step.get('id')} {kind}", item


def _is_pal(header):
    """PAL 头有四种写法：缺省、"0"、"False"（BizHawk 1.x，实测 6 部且行数与站点帧数 0.000% 相同）、
    "1"/"true"（真 PAL，实测 4113/4233 两部，折算帧率 50.0069）。只认字面 "0" 会把 NTSC 误判成 PAL。"""
    return (_header_value(header, "PAL") or "").strip().lower() not in ("", "0", "false")


def _site_seconds(time_text):
    parts = str(time_text).split(":")
    try:
        if len(parts) == 3:
            secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        elif len(parts) == 2:
            secs = int(parts[0]) * 60 + float(parts[1])
        else:
            secs = float(parts[0])
    except ValueError:
        return None
    return secs if secs > 0 else None


def _site_frames(time_text, fps):
    """把站点时长换成帧数。必须用平台自己的 fps：NES 是 60.0988，写死 60 会让每条电影差 +0.16%。"""
    secs = _site_seconds(time_text)
    return round(secs * fps) if secs is not None else None


def _site_duration_check(time_text, frames, fps):
    expected = _site_frames(time_text, fps)
    secs = _site_seconds(time_text)
    nominal_delta = None if secs is None else secs - frames / 60.0
    platform_ok = expected is not None and abs(frames - expected) <= 2
    nominal_ok = nominal_delta is not None and abs(nominal_delta) <= 0.005
    return {
        "accepted": platform_ok or nominal_ok,
        "basis": "platform_fps" if platform_ok else "nominal_60_rounded" if nominal_ok else "mismatch",
        "site_frames_platform_fps": expected,
        "delta_frames": None if expected is None else frames - expected,
        "site_seconds": secs,
        "nominal_60_delta_seconds": nominal_delta,
    }


def _tight_tolerance(expected_frames):
    """期望值取自电影自身帧数时，容差就该收到 ±2 帧：0.5% 的相对容差在 10 万帧的片子上
    等于允许少跑 507 帧（11-22 实测 4776 截断 134 帧仍算"帧数一致"），那种通过没有意义。
    短片子按 0.05 上限夹住，长片子按 2 帧折算。"""
    if not isinstance(expected_frames, int) or expected_frames < 1:
        return 0.005
    return min(0.05, 2.0 / expected_frames)


def _check_length(actual, expected, tolerance):
    """电影长度核对：期望帧与实到帧的差必须在容差内。这是通关的必要条件，不是充分条件。"""
    if actual is None or expected is None:
        return {"pass": False, "actual": actual, "expected": expected, "tolerance": tolerance,
                "reason": "缺少可比较的帧数"}
    delta = actual - expected
    within = abs(delta) <= tolerance * expected
    return {"pass": bool(within), "actual": actual, "expected": expected, "tolerance": tolerance,
            "delta_frames": delta, "delta_percent": round(delta / expected * 100, 4),
            "reason": "帧数一致" if within else f"实到 {actual} 与期望 {expected} 差 {delta} 帧"}


def _latch_holds(actual, cmp, expected):
    if cmp == "eq":
        return actual == expected
    if cmp == "ne":
        return actual != expected
    if cmp == "ge":
        return actual >= expected
    if cmp == "le":
        return actual <= expected
    raise SchemaError(f"不支持比较符 {cmp}")


def _check_latch_witness(program, runtime):
    """latch 判据的"曾经成立"必须有帧号，且帧号落在本任务真实推进的帧数内。

    只在末帧求值会把通关后回标题/重开游戏的电影判成 fail（3232 塞尔达带
    "Uses a game restart sequence"、5628 洛克人X2 末帧是标题画面），所以中途成立算数；
    但"中途成立"不能是运行器自报一句话——没有 witness 帧号、帧号越界、
    或回读值其实不满足比较式，都不算过。
    latch="terminal" 多要两格证据：false_frames（不成立的帧数，必须 ≥1，否则判据恒真）
    与 fell_back（成立后又回落的次数），用来核对"从这一帧起保持到收尾"是不是真的连续。
    """
    latch = [c for c in program.get("completion") or [] if c.get("latch")]
    witness = runtime.get("completion_witness") or {}
    if not latch:
        if witness:
            raise SchemaError("任务里没有 latch 判据，运行器却返回了 witness")
        return
    advanced = runtime.get("frames_advanced", 0)
    for item in latch:
        entry = witness.get(item["id"])
        if entry is None:
            if runtime.get("completion") == "pass":
                raise SchemaError(f"latch 判据 {item['id']} 判过却没有 witness 帧号")
            continue
        frame, value = entry.get("frame"), entry.get("value")
        if type(frame) is not int or type(value) is not int:
            raise SchemaError(f"latch 判据 {item['id']} 的 witness 缺帧号或缺读数")
        if not 0 <= frame <= advanced:
            raise SchemaError(f"latch 判据 {item['id']} 的 witness 帧号 {frame} 越出本任务推进的 {advanced} 帧")
        if not _latch_holds(value, item["cmp"], item["value"]):
            raise SchemaError(f"latch 判据 {item['id']} 回读 {value} 并不满足 {item['cmp']} {item['value']}")
        if item["latch"] == "terminal":
            # "收尾保持"必须有回落证据：false_frames==0 意味着判据从第一帧就成立，
            # 那是恒真式，不是通关转折；fell_back 缺失同样是证据不全。
            for key in ("false_frames", "fell_back"):
                if type(entry.get(key)) is not int or entry[key] < 0:
                    raise SchemaError(f"terminal 判据 {item['id']} 的 witness 缺 {key}，无法核对"
                                      f"\u201c成立后又回落\u201d是不是真的连续保持到收尾")
            if entry["false_frames"] < 1:
                raise SchemaError(f"terminal 判据 {item['id']} 自始成立（false_frames=0），"
                                  f"这条判据不构成\u201c由未达成变为达成\u201d，不许算通关")


TAIL_WINDOW_FRAMES = 1500
TAIL_STRIDE = 20
TAIL_MIN_FROZEN_FRAMES = 600
# 600 帧不是拍的：3232 的死亡尾段实测 74600–75400 共 41 个采样逐字节相同（800 帧静止），
# 而打怪过程中的采样每 20 帧就换一个摘要。阈值取实测跨度的 3/4，留出真结局动画的余量。


def _tail_probe(ts, start, checks, length):
    """决定这一趟要不要在末段反复截图；返回 None 就是"不测"，原因由报告里的 measured=False 说清。"""
    if not ts.get("enabled", bool(checks)):
        return None
    final = (length or {}).get("frames") or \
        (start.get("movie_frames") if start.get("kind") == "movie" else None)
    if type(final) is not int or final <= 0:
        return None
    window = ts.get("window_frames", TAIL_WINDOW_FRAMES)
    stride = ts.get("stride", TAIL_STRIDE)
    return {"from": max(0, final - window), "stride": stride, "max": window // stride + 2,
            "window_frames": window, "min_frozen_frames": ts.get("min_frozen_frames",
                                                                 TAIL_MIN_FROZEN_FRAMES)}


def _tail_measurement(runtime, probe):
    """末段采样的字节摘要 → 尾部长最短静止窗。"""
    digests = []
    for s in runtime.get("tail_samples") or []:
        frame, digest = s.get("frame"), _digest(s.get("screenshot"), "sha256")
        if type(frame) is int and digest:
            digests.append((frame, digest))
    floor = (probe or {}).get("min_frozen_frames", TAIL_MIN_FROZEN_FRAMES)
    if len(digests) < 2:
        return {"measured": False, "samples": len(digests), "frozen": False,
                "min_frozen_frames": floor,
                "reason": "末段采样不足 2 张，静止度没法判（tail_probe 未生效或截图不可读）"}
    last = digests[-1][1]
    i = len(digests) - 1
    while i > 0 and digests[i - 1][1] == last:
        i -= 1
    run = digests[i:]
    frozen = run[-1][0] - run[0][0]
    return {"measured": True, "samples": len(digests), "distinct": len({d for _, d in digests}),
            "frozen_start_frame": run[0][0], "frozen_end_frame": run[-1][0],
            "frozen_samples": len(run), "frozen_frames": frozen, "digest": last[:16],
            "min_frozen_frames": floor, "frozen": frozen >= floor}


def _picture_health(runtime):
    """把已经落在盘上的检查点截图压成一个事实：末段有没有长时间逐字节相同。

    6012 实测：后半段 20 个检查点字节完全相同（黑屏），而 execution 照样是 pass、
    tail_stasis 因为"没有通关声称"按设计不采样。看图的人一眼能发现，不看图的闸门会直接交出去。
    逐字节相同既可能是黑屏/卡帧，也可能是真静止（对话、结算），单看画面分不开——
    但同一批检查点的 System Bus 转储已经在盘上了，所以这里顺手量第二层：
    画面不动而内存还在变 = 机器还在跑（黑屏是片子内容/PPU 不出图），画面和内存同时不动 = 才像真卡住。
    只报事实；dead_tail 会把生产任务判成 failed，缺少截图则留 unmeasured 供交付入口拦截。
    帧号取 runtime.checkpoints，不靠文件名推。
    """
    rows = []
    for v in (runtime.get("checkpoints") or {}).values():
        f, s = v.get("frame"), v.get("screenshot")
        if type(f) is not int or not s or not os.path.isfile(s):
            continue
        ram = v.get("ram")
        ram = ram.get("path") if isinstance(ram, dict) else ram
        rows.append((f, s, ram if type(ram) is str and os.path.isfile(ram) else None))
    cps = [(f, s) for f, s, _ in rows]
    if len(cps) < 2:
        return {"measured": False, "checkpoints": len(cps), "min_dead_frames": TAIL_WINDOW_FRAMES,
                "machine_state": "unmeasured",
                "reason": "可用检查点截图不足 2 张，画面静止度不判"}
    cps.sort(key=lambda c: c[0])
    rows.sort(key=lambda r: r[0])
    digests = [sha256_file(s) for _, s in cps]
    runs, start = [], 0
    for k in range(1, len(digests) + 1):
        if k == len(digests) or digests[k] != digests[start]:
            runs.append({"samples": k - start, "from_frame": cps[start][0], "to_frame": cps[k - 1][0],
                         "digest": digests[start][:16]})
            start = k
    tail = runs[-1]
    longest = max(runs, key=lambda r: (r["samples"], r["to_frame"] - r["from_frame"]))
    span = tail["to_frame"] - tail["from_frame"]
    dead = tail["samples"] >= 2 and span >= TAIL_WINDOW_FRAMES
    ram_paths = [r[2] for r in rows if tail["from_frame"] <= r[0] <= tail["to_frame"] and r[2]]
    if tail["samples"] < 2:
        state, detail = "not_needed", "末段没有连续相同的画面，机器层不用判"
    elif len(ram_paths) < 2:
        state, detail = "unmeasured", "末段这几格没有可读的内存转储，机器有没有在跑不判"
    else:
        n_ram = len({sha256_file(p) for p in ram_paths})
        state = "changing" if n_ram > 1 else "static"
        detail = "末段 %d 格检查点的 System Bus 转储有 %d 种" % (tail["samples"], n_ram)
    return {"measured": True, "checkpoints": len(cps), "distinct": len(set(digests)),
            "runs": {"tail": tail, "longest": longest},
            "identical_tail_frames": span,
            "machine_state": state, "machine_state_detail": detail,
            "min_dead_frames": TAIL_WINDOW_FRAMES,
            "dead_tail": dead,
            "reason": (("末段 %d 个检查点（%d..%d 帧）画面逐字节相同；%s——结论前必须看图"
                        % (tail["samples"], tail["from_frame"], tail["to_frame"], detail))
                       if dead else
                       ("末段连续相同只有 %d 格（%d..%d 帧，跨度 %d 帧），没到 %d 帧的静止窗；%s"
                        % (tail["samples"], tail["from_frame"], tail["to_frame"], span,
                           TAIL_WINDOW_FRAMES, detail)))}


def _check_tail_stasis(program, runtime, stasis):
    """跑完停在静止画面上时，证词必须出自那张静止屏——不能拿中途更好看的一帧交差。

    3232 的教训就是中途那帧（74403）看着像打赢，末段第 74520 帧才写着 GAME OVER。
    """
    checks = program.get("completion") or []
    if not checks or runtime.get("completion") != "pass":
        return runtime.get("completion", "inconclusive"), runtime.get("reason", "")
    if not stasis.get("frozen"):
        return "pass", runtime.get("reason", "")
    cps = runtime.get("checkpoints") or {}
    for item in checks:
        ev = item.get("evidence")
        if not ev:
            continue
        cp = cps.get(ev["checkpoint"]) or {}
        if type(cp.get("frame")) is int and cp["frame"] < stasis["frozen_start_frame"]:
            return ("inconclusive",
                    f"末段第 {stasis['frozen_start_frame']}–{stasis['frozen_end_frame']} 帧画面逐字节相同"
                    f"（{stasis['frozen_samples']} 个采样，静止 {stasis['frozen_frames']} 帧 ≥ "
                    f"{stasis['min_frozen_frames']}），像停在结算/菜单画面；"
                    f"但通关判据 {item['id']} 的证词取自第 {cp['frame']} 帧，在那之前。"
                    f"要看的是末屏：把 checkpoint 挪到末段之后重新看图，再决定这条判据成不成立")
    return "pass", runtime.get("reason", "")


def _check_predicate_platform(platform, runtime, warnings):
    """非 NES 的内存判据即便 --allow 放行，也只许留现象、不许出 pass。

    地址映射、可读窗口、帧量化都只在 NES 上实测过；在 SNES/GB/PSX 上读 NES 那套地址，
    数字自洽也不代表那个局面。这一条是单向降级（pass→inconclusive），
    --allow 买不回 pass，只买"这一次真跑过"。
    """
    completion = runtime.get("completion", "inconclusive")
    if completion != "pass":
        return completion, ""
    if not any(w.get("code") == "predicate_platform_unproven" for w in (warnings or [])):
        return completion, ""
    return ("inconclusive",
            f"{platform} 的判据地址表本机没实测过，内存数字含义不明，pass 降级为 inconclusive；"
            f"要出 pass 先补本平台判据表，或改用 §35 截图证词那条链（看图不受这条限制）")


def _check_completion_evidence(program, runtime):
    """RAM 判据说"通关"不算，要拿画面核对：证词指向的截图必须真在本次产物里、
    字节摘要与登记值一致、而且拍摄帧号要贴着判据成立的帧号。

    这一条把"看一眼屏幕"钉进流程，而不是靠人自觉：3232 的 pass 是四格数字全绿
    却把死亡淡出判成通关——数字越自洽，越需要一张独立来源的图来对质。
    证据不齐时返回 inconclusive，不抛异常：执行本身是成功的，废掉的只是那句声称。
    """
    checks = program.get("completion") or []
    if not checks or runtime.get("completion") != "pass":
        return runtime.get("completion", "inconclusive"), runtime.get("reason", "")
    cps, witness = runtime.get("checkpoints") or {}, runtime.get("completion_witness") or {}
    for item in checks:
        ev = item.get("evidence")
        if not ev:
            return ("inconclusive", f"通关判据 {item['id']} 没登记截图证词(evidence)；"
                                    f"只看 RAM 数字判不了局面，先跑 window 看图再把证词写进任务")
        cp = cps.get(ev["checkpoint"])
        if not isinstance(cp, dict):
            return ("inconclusive", f"证词 {item['id']}→{ev['checkpoint']} 在本次运行的 checkpoints 里不存在")
        png = cp.get("screenshot")
        actual = _digest(png, "sha256")
        if actual is None:
            return ("inconclusive", f"证词 {item['id']} 指向的截图不可读：{png}")
        if actual != ev["sha256"]:
            return ("inconclusive", f"证词 {item['id']} 的图被换过：登记 {ev['sha256'][:16]}…，"
                                    f"实读 {actual[:16]}…（{png}）")
        wframe = (witness.get(item["id"]) or {}).get("frame", runtime.get("final_frame"))
        if type(wframe) is not int or type(cp.get("frame")) is not int:
            return ("inconclusive", f"证词 {item['id']} 缺帧号，核对不了图与判据是否同一时刻")
        if cp["frame"] > runtime.get("frames_advanced", 0):
            return ("inconclusive", f"证词 {item['id']} 的图标称第 {cp['frame']} 帧，本次只推进了 "
                                    f"{runtime.get('frames_advanced')} 帧，图不可能出自这一趟")
        if item.get("latch") == "terminal":
            # terminal 的 witness 帧是"最后一段不间断成立"的**起点**（运行器记的是 p.start），
            # 不是拍照那一刻。拿它和截图帧做容差比较，只要保持段比检查点早开始哪怕一帧，
            # 一次真保持也会被判成不通过——11-22 读代码时发现这条组合没人踩到（现有任务里
            # terminal+evidence 为 0 条），趁没人用先修。改判"图必须落在保持段内"。
            last = runtime.get("final_frame") or runtime.get("frames_advanced") or cp["frame"]
            if not wframe <= cp["frame"] <= last:
                return ("inconclusive",
                        f"证词 {item['id']} 的图在第 {cp['frame']} 帧，但 terminal 判据从第 {wframe} 帧起"
                        f"才保持到第 {last} 帧，图不在保持段里（保持段起点之前拍的图对不上这句声称）")
            continue
        how = "首次成立" if item.get("latch") else "末帧求值"
        if abs(cp["frame"] - wframe) > ev["frame_tolerance"]:
            return ("inconclusive", f"证词 {item['id']} 的图在第 {cp['frame']} 帧，判据在第 {wframe} 帧{how}，"
                                    f"相差 {abs(cp['frame'] - wframe)} 帧 > frame_tolerance={ev['frame_tolerance']}"
                                    + ("；latch=once 的全片逐帧探针若在结局之前就命中，说明这条判据不是通关旗标"
                                       if item.get("latch") else ""))
    return "pass", runtime.get("reason", "")


_BK2_ALIASES = {"header": ("header.txt", "header"), "input": ("input log.txt", "input log")}


def _digest(path, algo):
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.new(algo)
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _arm_doc(spec, entry, index, samples):
    """由主任务派生一条臂：换掉 profile 与电影，按采样点插 replay+checkpoint 留字节。
    臂不带走主任务的录制/通关判据/闸门——它只负责在同一帧上留下可比的东西。"""
    doc = deepcopy(spec)
    profile = doc["profile"]
    profile["core"] = entry["core"]
    profile["bizhawk"] = entry.get("bizhawk") or profile["bizhawk"]
    if "system" in entry:
        profile["system"] = entry["system"]
    if "sync_settings" in entry:
        profile["sync_settings"] = deepcopy(entry["sync_settings"])
    doc["start"] = {"kind": "movie", "path": entry["movie"]["path"], "sha256": entry["movie"]["sha256"]}
    doc["id"] = f"{spec['id']}__arm_{entry['label']}"
    # 采样臂仍要跟着主任务的速度档，否则 33000 帧的片子按实时一帧一帧走，白等十几分钟。
    doc["record"] = {k: spec["record"][k] for k in ("speed", "frameskip") if k in spec.get("record", {})}
    doc["completion"], doc["verify"] = {}, {}
    steps, consumed = [], 0
    steps.extend(deepcopy(step) for step in spec["steps"] if step.get("op") == "seed_ram")
    capture = next((step for step in spec["steps"] if step.get("op") == "checkpoint"), {})
    ram_fields = {k: deepcopy(capture[k]) for k in ("ram", "ram_domain", "ram_addr", "ram_bytes", "memory_dumps") if k in capture}
    for j, sample in enumerate(samples):
        frames = "end" if sample == "end" else sample - consumed
        if frames != "end":
            consumed = sample
        steps.append({"id": f"arm{index:02d}_to_{j:03d}", "op": "replay", "frames": frames})
        steps.append({"id": f"arm{index:02d}_sample_{j:03d}", "op": "checkpoint",
                      "name": f"sample_{j:03d}", **ram_fields})
    doc["steps"] = steps
    return doc


def _arm_samples(result, compare):
    out = {}
    for name, cp in sorted(((result.get("runtime") or {}).get("checkpoints") or {}).items()):
        row = {"frame": cp.get("frame")}
        ram = cp.get("ram")
        if "ram" in compare:
            row["ram"] = _digest(ram.get("path") if isinstance(ram, dict) else None, "sha256")
        if "png" in compare:
            row["png"] = _digest(cp.get("screenshot"), "md5")
        out[name] = row
    return out


def _compare_arms(reference, candidate, compare):
    """逐采样点先比实到帧号，再比 RAM/画面摘要。帧号对不上=两条时间线根本不同长。"""
    divergent, gaps = [], []
    for name in sorted(reference):
        other = candidate.get(name)
        if other is None:
            gaps.append(f"{name} 候选臂没有该采样点")
            continue
        if reference[name].get("frame") != other.get("frame"):
            divergent.append({"sample": name, "frame": reference[name].get("frame"), "kind": "frame",
                              "reference": reference[name].get("frame"), "candidate": other.get("frame")})
        for kind in compare:
            a, b = reference[name].get(kind), other.get(kind)
            if a is None or b is None:
                gaps.append(f"{name}.{kind} 摘要不可读")
            elif a != b:
                divergent.append({"sample": name, "frame": reference[name].get("frame"), "kind": kind,
                                  "reference": a, "candidate": b})
    frames = [d["frame"] for d in divergent if isinstance(d.get("frame"), int)]
    return {"agree": not divergent and not gaps, "divergent": divergent, "gaps": gaps,
            "first_divergent_frame": min(frames) if frames else None}


def _sync_verdict(pairs):
    """一致臂全同且至少一条 → pass；任一一致臂分叉 → fail；
    反证臂（expect=differ）反而相同 → 判据看不见差异，只能 inconclusive，不许升格成通过。"""
    agree = [p for p in pairs if p["expect"] == "agree"]
    differ = [p for p in pairs if p["expect"] == "differ"]
    broken = [p for p in pairs if p["status"] != "pass"]
    if broken:
        return "not_run", "候选臂没跑成，同步判定不成立：" + "，".join(p["label"] for p in broken)
    if any(not p["comparison"]["agree"] for p in agree):
        worst = next(p for p in agree if not p["comparison"]["agree"])
        first = worst["comparison"]["first_divergent_frame"]
        if first is not None:
            return "fail", f"{worst['label']} 与参照臂在帧 {first} 起分叉（{worst['comparison']['divergent'][0]['kind']}）"
        return "fail", f"{worst['label']} 与参照臂有采样点不可比：" + "；".join(worst["comparison"]["gaps"])
    if any(p["comparison"]["agree"] for p in differ):
        return "inconclusive", ("反证臂 " + "，".join(p["label"] for p in differ if p["comparison"]["agree"]) +
                                " 与参照臂逐字节相同，这对判据看不见差异，不能升格成同步通过")
    if not agree:
        return "inconclusive", "只声明了 differ 臂，没有任何一致项可以证明同步"
    return "pass", (f"{len(agree)} 条候选臂与参照臂逐采样点同帧同字节" +
                    (f"，{len(differ)} 条反证臂如预期分叉" if differ else ""))


def _seed_event(result):
    for event in (result.get("runtime") or {}).get("events") or []:
        if event.get("op") == "seed_ram" and event.get("kind") == "step_done":
            data = event.get("seed_ram") or {}
            return {"domain": data.get("domain"), "bytes": data.get("bytes"),
                    "start": data.get("start"), "sha256_verified_by_runner": data.get("sha256_verified_by_runner"),
                    "frame": event.get("frame"), "consumed_inputs": event.get("consumed_inputs")}
    return None


def _run_arms(spec, base, parent, work_root, timeout, executor=None, allow=()):
    """串行跑各臂（BizHawk 一次只开一个），再逐采样点对照。"""
    from . import fceux as F
    cfg = spec["verify"]["arms"]
    entries, compare, samples = cfg["entries"], cfg["compare"], cfg["samples"]
    arms, logs = [], []
    for i, entry in enumerate(entries):
        root = Path(parent) / "arms" / f"{i:02d}_{entry['label']}"
        try:
            res = run(_arm_doc(spec, entry, i, samples), base, root, work_root=work_root,
                      timeout=timeout, executor=executor, allow=allow)
        except Exception as e:
            res = {"status": "blocked", "reason": f"{type(e).__name__}: {e}", "blockers": []}
        try:
            logs.append(F.input_log_digest(entry["movie"]["path"]))
        except Exception:
            logs.append(None)
        arms.append({"label": entry["label"], "role": "reference" if i == 0 else "candidate",
                     "core": entry["core"], "system": entry.get("system"), "expect": entry["expect"],
                     "bizhawk": entry.get("bizhawk") or spec["profile"]["bizhawk"],
                     "movie": entry["movie"]["path"], "movie_sha256": entry["movie"]["sha256"],
                     "input_log_sha256": logs[-1], "seed_ram": _seed_event(res),
                     "execution": (res.get("verification") or {}).get("execution", "not_run"),
                     "core_identity": (res.get("verification") or {}).get("core_identity", "unverified"),
                     "status": res.get("status"), "reason": res.get("reason", ""),
                     "blockers": res.get("blockers", []), "report": str(root / "control.json"),
                     "samples": _arm_samples(res, compare)})
    pairs = []
    for i in range(1, len(arms)):
        broken = (arms[i]["execution"] != "pass" or arms[0]["execution"] != "pass"
                  or arms[i]["core_identity"] != "pass" or arms[0]["core_identity"] != "pass")
        pairs.append({"reference": arms[0]["label"], "label": arms[i]["label"], "expect": arms[i]["expect"],
                      "status": "not_run" if broken else "pass",
                      "comparison": ({"agree": False, "divergent": [], "gaps": ["臂未跑成，无采样字节可比"],
                                      "first_divergent_frame": None} if broken
                                     else _compare_arms(arms[0]["samples"], arms[i]["samples"], compare))})
    seeds = [arm.get("seed_ram") for arm in arms]
    seed_identical = all(seed == seeds[0] for seed in seeds) and seeds[0] is not None
    expected_seed = next((step for step in spec["steps"] if step.get("op") == "seed_ram"), None)
    seed_valid = expected_seed is None or all(
        seed and seed.get("domain") == expected_seed.get("domain")
        and seed.get("start") == expected_seed.get("addr")
        and seed.get("bytes") == expected_seed.get("bytes")
        and seed.get("sha256_verified_by_runner") is True
        and seed.get("frame") == 0 and seed.get("consumed_inputs") == 0 for seed in seeds)
    if any(arm["core_identity"] != "pass" for arm in arms):
        verdict, why = "fail", "参照臂或候选臂缺少零帧实际核心身份通过证据"
    elif not seed_valid:
        verdict, why = "fail", "初始内存在参照臂或候选臂缺少零帧全量回读证据"
    elif any(seed is not None for seed in seeds) and not seed_identical:
        verdict, why = "fail", "各臂初始内存注入域、地址、长度或执行时点不一致"
    elif not (len([x for x in logs if x]) == len(logs) and len(set(logs)) == 1):
        verdict, why = "fail", "各臂 Input Log.txt 摘要不一致，不能作为同输入同步证据"
    else:
        verdict, why = _sync_verdict(pairs)
    return {"samples": samples, "compare": compare, "source": cfg.get("source", ""),
            "input_log_identical": len([x for x in logs if x]) == len(logs) and len(set(logs)) == 1,
            "seed_ram_identical": seed_identical, "seed_ram_valid": seed_valid,
            "input_logs": logs, "arms": arms, "pairs": pairs, "sync": verdict, "sync_reason": why}



def _zip_read(archive, kind):
    # 上游 bk2 有三种写法：BizHawk 1.x 用 "Header"/"Input Log"，2.x 用 ".txt" 后缀，导入件全小写。
    names = {n.lower(): n for n in archive.namelist()}
    for alias in _BK2_ALIASES[kind]:
        if alias in names:
            return archive.read(names[alias])
    raise SchemaError(f"bk2 内缺少 {'/'.join(_BK2_ALIASES[kind])}，实际成员={archive.namelist()[:6]}")


def _bk2_text(data):
    # 有的作者名带非 UTF-8 字节（4113 的 0xf6），一个怪字节不该让整部电影解析不出来。
    return data.decode("utf-8-sig", "replace")


def _bk2_info(path):
    with zipfile.ZipFile(path) as outer:
        if "header.txt" in {n.lower() for n in outer.namelist()} or "header" in {n.lower() for n in outer.namelist()}:
            header_data = _zip_read(outer, "header")
            input_data = _zip_read(outer, "input")
        else:
            members = [n for n in outer.namelist() if n.lower().endswith(".bk2")]
            if len(members) != 1:
                raise SchemaError("外壳 ZIP 必须明确包含唯一一部 BK2")
            with zipfile.ZipFile(io.BytesIO(outer.read(members[0]))) as inner:
                header_data = _zip_read(inner, "header")
                input_data = _zip_read(inner, "input")
    header = {k: v.strip() for k, v in
              (line.split(" ", 1) for line in _bk2_text(header_data).splitlines() if " " in line)}
    lines = sum(line.startswith("|") for line in _bk2_text(input_data).splitlines())
    if lines < 1:
        raise SchemaError("电影没有输入帧")
    frames, source = _bk2_frames(header, lines)
    return header, frames, {"lines": lines, "source": source}


def load_spec(path):
    path = Path(path).resolve()
    return json.loads(path.read_text(encoding="utf-8-sig")), path.parent


def normalize(doc, base):
    from taspipe.retro_platforms import PLATFORM_SPECS
    doc = deepcopy(doc)
    base = Path(base)
    _object(doc, {"version", "id", "mode", "game", "purpose", "rom", "platform", "profile", "start",
                  "macros", "steps", "completion", "record", "patches", "verify", "provenance"},
            {"version", "id", "mode", "rom"})
    # provenance 只记「这台臂是怎么来的」，不参与执行；站点版本本机没装、照抄同 ROM
    # 原生片那台臂的情况必须有据可查，否则台账会把"继承"写成"登记版本可用"。
    if "provenance" in doc:
        _object(doc["provenance"], {"arm_inherited_from"}, {"arm_inherited_from"}, "provenance")
        inh = doc["provenance"]["arm_inherited_from"]
        _object(inh, {"pub_id", "declared", "used", "core"}, {"pub_id", "declared", "used"}, "arm_inherited_from")
    if type(doc["version"]) is not int or doc["version"] != 1:
        raise SchemaError("仅支持任务 version=1")
    _name(doc["id"], "任务 id")
    if doc["mode"] not in ("session", "rom_patch"):
        raise SchemaError("mode 必须是 session 或 rom_patch")
    _object(doc["rom"], {"path", "sha1"}, {"path", "sha1"}, "rom")
    doc["rom"] = {"path": _rom_path(doc["rom"]["path"], base), "sha1": _hash(doc["rom"]["sha1"], 40, "ROM SHA1")}
    if doc["mode"] == "rom_patch":
        if split_rom_spec(doc["rom"]["path"])[1] is not None:
            raise SchemaError("rom_patch 只做明文件的定长字节补丁；压缩包内 ROM 不许被写回原包，"
                              "要改就先把该条目落成独立文件再建任务")
        if set(doc) - {"version", "id", "mode", "game", "rom", "patches"}:
            raise SchemaError("rom_patch 任务不接受会话参数")
        occupied = set()
        for patch in _list(doc.get("patches"), "patches"):
            _object(patch, {"offset", "expect", "value"}, {"offset", "expect", "value"}, "ROM 字节补丁")
            patch["offset"] = _address(patch["offset"])
            for key in ("expect", "value"):
                value = patch[key]
                if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-fA-F]{2})+", value):
                    raise SchemaError(f"{key} 必须是偶数位非空十六进制字节串")
                patch[key] = value.lower()
            if len(patch["expect"]) != len(patch["value"]):
                raise SchemaError("ROM 补丁不可改变文件长度")
            for pos in range(patch["offset"], patch["offset"] + len(patch["value"]) // 2):
                if pos in occupied:
                    raise SchemaError("ROM 补丁区间重叠")
                occupied.add(pos)
        return doc, None
    if "patches" in doc:
        raise SchemaError("会话修改请使用 op=patch；文件补丁请用 mode=rom_patch")
    platform = doc.get("platform")
    if not isinstance(platform, str) or platform not in PLATFORM_SPECS:
        raise SchemaError(f"未建模 platform={platform}")
    doc["purpose"] = doc.get("purpose", "control")
    if doc["purpose"] not in ("control", "playthrough"):
        raise SchemaError("purpose 必须为 control/playthrough")
    profile = _object(doc.get("profile"), {"bizhawk", "core", "system", "sync_settings"},
                      {"bizhawk", "core", "system"}, "profile")
    profile["bizhawk"] = _path(profile["bizhawk"], base)
    _text(profile["core"], "core")
    if profile["system"] != PLATFORM_SPECS[platform]["system"]:
        raise SchemaError("profile.system 与 platform 不一致")
    sync = profile.get("sync_settings", {})
    if not isinstance(sync, dict):
        raise SchemaError("profile.sync_settings 必须是对象")
    if platform == "SNES" and sync:
        identity = core_identity_expectation(platform, profile["core"])
        deterministic = identity.get("deterministic_setting")
        if not deterministic:
            raise SchemaError("SNES sync_settings 当前仅支持 BSNES/BSNESv115+ 确定性开机设置")
        key, value = deterministic["key"], deterministic["value"]
        allowed = {key, "LeftPort", "RightPort"}
        if profile["core"] == "BSNESv115+":
            allowed.add("FastPPU")
        _object(sync, allowed, {key}, "sync_settings")
        if "FastPPU" in sync and type(sync["FastPPU"]) is not bool:
            raise SchemaError("FastPPU 必须是布尔值")
        actual = sync[key]
        if type(actual) is not type(value) or actual != value:
            raise SchemaError(f"SNES 冷启动必须显式使用确定性设置 {key}={value!r}")
        for port in ("LeftPort", "RightPort"):
            if port in sync and (type(sync[port]) is not int or sync[port] not in (0, 1)):
                raise SchemaError(f"{port} 必须是整数 0（未连接）或 1（控制器）")
    elif platform != "NES" and sync:
        raise SchemaError("本版 sync_settings 仅支持 NES 控制器拓扑和 SNES BSNES 确定性开机设置")
    if platform == "NES" and sync:
        _object(sync, {"NesLeftPort", "NesRightPort"}, label="sync_settings")
        if any(v not in ("ControllerNES", "UnpluggedNES") for v in sync.values()):
            raise SchemaError("本版拓扑只支持 ControllerNES/UnpluggedNES")
    start = doc.setdefault("start", {"kind": "boot"})
    _object(start, {"kind", "path", "sha256"}, {"kind"}, "start")
    if start["kind"] not in ("boot", "state", "movie"):
        raise SchemaError("start.kind 必须为 boot/state/movie")
    if start["kind"] == "boot":
        if set(start) != {"kind"}:
            raise SchemaError("boot 不接受 path/sha256")
    else:
        start["path"] = _path(start.get("path"), base)
        start["sha256"] = _hash(start.get("sha256"), 64, "初态资产 SHA256")
    macros = doc.setdefault("macros", {})
    if not isinstance(macros, dict):
        raise SchemaError("macros 必须是对象")
    compiled = {}
    for name, parts in macros.items():
        _name(name, "宏名")
        compiled[name] = compile_macro(parts, macros, platform, (name,))
    steps, ids, saved, shots = [], set(), set(), set()
    movie_active = start["kind"] == "movie"
    for raw in _list(doc.get("steps"), "steps"):
        if not isinstance(raw, dict):
            raise SchemaError("步骤必须是对象")
        op = raw.get("op")
        fields = {"advance": {"frames"}, "macro": {"name", "repeat"}, "input": {"segments"},
                  "replay": {"frames"}, "takeover": set(),
                  "checkpoint": {"name", "ram", "ram_domain", "ram_addr", "ram_bytes", "memory_dumps", "registers"}, "load": {"name"},
                  "seed_ram": {"path", "sha256", "domain", "addr", "bytes"},
                  "patch": {"writes"}, "observe": {"watches"}, "assert": {"checks"},
                  "until": {"checks", "max_frames", "players"}, "screenshot": {"name"}}
        if not isinstance(op, str) or op not in fields:
            raise SchemaError(f"未知操作 {op}")
        _object(raw, {"id", "op"} | fields[op], {"id", "op"}, "step")
        step = deepcopy(raw)
        sid = _name(step["id"], "步骤 id")
        if sid in ids:
            raise SchemaError(f"重复步骤 id {sid}")
        ids.add(sid)
        if op in ("input", "macro", "advance", "patch", "until") and movie_active:
            raise SchemaError("电影回放中修改或输入前必须显式 takeover")
        if op == "replay":
            if not movie_active:
                raise SchemaError("replay 需要尚未 takeover 的 movie 初态")
            if step.get("frames") != "end":
                step["frames"] = _integer(step.get("frames"), "replay.frames", 1)
        elif op == "takeover":
            if not movie_active:
                raise SchemaError("takeover 需要正在回放的 movie")
            movie_active = False
        elif op == "advance":
            step["frames"] = _integer(step.get("frames"), "frames", 1)
        elif op in ("checkpoint", "load", "screenshot"):
            name = _name(step.get("name"), "资产名")
            if op == "checkpoint":
                if name in saved:
                    raise SchemaError(f"检查点不可覆盖: {name}")
                saved.add(name)
                if "ram" in step and type(step["ram"]) is not bool:
                    raise SchemaError("checkpoint.ram 必须是布尔值")
                if "registers" in step and type(step["registers"]) is not bool:
                    raise SchemaError("checkpoint.registers 必须是布尔值")
                if step.get("ram") is False and any(k in step for k in ("ram_domain", "ram_addr", "ram_bytes")):
                    raise SchemaError("ram=false 时不得指定 RAM 导出范围")
                if "ram_domain" in step:
                    _text(step["ram_domain"], "checkpoint.ram_domain")
                if "ram_addr" in step:
                    step["ram_addr"] = _address(step["ram_addr"])
                if "ram_bytes" in step:
                    step["ram_bytes"] = _address(step["ram_bytes"])
                    if step["ram_bytes"] == 0:
                        raise SchemaError("checkpoint.ram_bytes 必须大于 0")
                if "memory_dumps" in step:
                    dumps, dump_names = [], set()
                    for item in _list(step["memory_dumps"], "checkpoint.memory_dumps"):
                        _object(item, {"name", "domain", "addr", "bytes"}, {"name", "domain", "addr", "bytes"},
                                "checkpoint.memory_dumps")
                        dump_name = _name(item["name"], "checkpoint.memory_dumps.name")
                        if dump_name in dump_names:
                            raise SchemaError(f"重复内存导出名: {dump_name}")
                        dump_names.add(dump_name)
                        size = _address(item["bytes"])
                        if size == 0:
                            raise SchemaError("checkpoint.memory_dumps.bytes 必须大于 0")
                        dumps.append({"name": dump_name, "domain": _text(item["domain"], "checkpoint.memory_dumps.domain"),
                                      "addr": _address(item["addr"]), "bytes": size})
                    step["memory_dumps"] = dumps
            elif op == "screenshot":
                if name in shots:
                    raise SchemaError(f"截图不可覆盖: {name}")
                shots.add(name)
            if op == "load":
                if name not in saved:
                    raise SchemaError(f"检查点尚未创建: {name}")
                movie_active = False
        elif op == "seed_ram":
            step["path"] = _path(step.get("path"), base)
            step["sha256"] = _hash(step.get("sha256"), 64, "SRAM 资产 SHA256")
            step["domain"] = _text(step.get("domain"), "seed_ram.domain")
            step["addr"] = _address(step.get("addr"))
            step["bytes"] = _address(step.get("bytes"))
            if step["bytes"] == 0:
                raise SchemaError("seed_ram.bytes 必须大于 0")
            if any(previous["op"] == "replay" for previous in steps):
                raise SchemaError("seed_ram 必须放在第一条 replay 之前")
        elif op == "macro":
            name = _name(step.get("name"), "宏名")
            if name not in compiled:
                raise SchemaError(f"未定义宏 {name}")
            n = _integer(step.get("repeat", 1), "repeat", 1, 100000)
            if len(compiled[name]) * n > 100000:
                raise SchemaError("宏展开超过 100000 段")
            step = {"id": sid, "op": "input", "segments": deepcopy(compiled[name] * n)}
        elif op == "input":
            step["segments"] = compile_macro(step.get("segments"), macros, platform)
        elif op == "patch":
            step["writes"] = _memory(step.get("writes"), "writes")
        elif op == "observe":
            step["watches"] = _memory(step.get("watches"), "watches")
        elif op in ("assert", "until"):
            step["checks"] = _memory(step.get("checks"), "checks")
            if op == "until":
                step["max_frames"] = _integer(step.get("max_frames"), "max_frames", 1)
                step["players"] = _players(step.get("players", {}), platform)
        steps.append(step)
    completion = doc.get("completion", {})
    _object(completion, {"source", "checks"}, label="completion")
    if completion:
        _text(completion.get("source"), "通关/目标判据依据 source")
        checks = _memory(completion.get("checks"), "checks", allow_latch=True)
    else:
        checks = []
    for step in steps:
        for write in step.get("writes", []):
            if any(write["domain"] == check["domain"] and
                   max(write["addr"], check["addr"]) < min(write["addr"] + write["width"], check["addr"] + check["width"])
                   for check in checks):
                raise SchemaError("completion 不得直接读取本任务写入的目标字节自证；请使用独立结果判据")
    record = doc.get("record", {})
    _object(record, {"video", "audio", "fps", "ffmpeg", "ffprobe", "speed", "frameskip"},
            label="record")
    for flag in ("video", "audio"):
        if flag in record and type(record[flag]) is not bool:
            raise SchemaError(f"record.{flag} 必须为布尔值")
    speed = record.get("speed", "realtime")
    if speed not in ("realtime", "unthrottled"):
        raise SchemaError("record.speed 只能是 realtime 或 unthrottled")
    frameskip = record.get("frameskip", 0)
    if type(frameskip) is not int or not 0 <= frameskip <= 60:
        raise SchemaError("record.frameskip 必须是 0..60 的整数")
    fps = record.get("fps", PLATFORM_SPECS[platform]["fps"])
    if type(fps) not in (int, float) or not math.isfinite(fps) or fps <= 0:
        raise SchemaError("fps 必须是有限正数")
    verify = doc.get("verify", {})
    _object(verify, {"length", "arms", "tail_stasis"}, label="verify")
    if "tail_stasis" in verify:
        # 末段画面静止度：整片跑完停在菜单/结算画面时，画面会连续几百帧逐字节相同。
        # 3232 就是这么被发现的（74600–75400 帧 41 个采样同一张图），当时靠人眼。
        ts = _object(verify["tail_stasis"],
                     {"enabled", "window_frames", "stride", "min_frozen_frames", "source"},
                     set(), "verify.tail_stasis")
        if "enabled" in ts and not isinstance(ts["enabled"], bool):
            raise SchemaError("verify.tail_stasis.enabled 必须是布尔")
        for key, hi in (("window_frames", 20000), ("stride", 600), ("min_frozen_frames", 20000)):
            if key in ts:
                ts[key] = _integer(ts[key], f"verify.tail_stasis.{key}", 1, hi)
        if "source" in ts:
            _text(ts["source"], "verify.tail_stasis.source")
    if "length" in verify:
        length = _object(verify["length"], {"frames", "tolerance", "source"}, {"frames"}, "verify.length")
        length["frames"] = _integer(length["frames"], "verify.length.frames", 1)
        tolerance = length.get("tolerance", 0.005)
        if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or not 0 < tolerance <= 0.05:
            raise SchemaError("verify.length.tolerance 必须是 (0, 0.05] 的实数")
        length["tolerance"] = tolerance
        if "source" in length:
            _text(length["source"], "verify.length.source")
    if "arms" in verify:
        # 多臂对照：同一份输入在几套核心/版本上重放到同一帧，比 RAM 与画面。
        # 长度闸门只证明「跑满了」，同步闸门才证明「跑的是同一条时间线」。
        if start["kind"] != "movie":
            raise SchemaError("verify.arms 需要 start.kind=movie，各臂必须放同一份输入")
        arms = _object(verify["arms"], {"samples", "compare", "entries", "source"}, {"entries"}, "verify.arms")
        samples, previous = [], 0
        declared = _list(arms.get("samples", ["end"]), "verify.arms.samples")
        for i, item in enumerate(declared):
            if item == "end":
                if i != len(declared) - 1:
                    raise SchemaError("verify.arms.samples 的 end 只能放在最后")
                samples.append("end")
                break
            frame = _integer(item, "verify.arms.samples 帧号", 1)
            if frame <= previous:
                raise SchemaError("verify.arms.samples 帧号必须严格递增")
            samples.append(frame)
            previous = frame
        if not samples:
            raise SchemaError("verify.arms.samples 至少一个采样点")
        arms["samples"] = samples
        compare = _list(arms.get("compare", ["ram", "png"]), "verify.arms.compare")
        if len(set(compare)) != len(compare) or any(c not in ("ram", "png") for c in compare):
            raise SchemaError("verify.arms.compare 只能是 ram/png 的不重复组合")
        arms["compare"] = compare
        entries = _list(arms["entries"], "verify.arms.entries")
        if len(entries) < 2:
            raise SchemaError("verify.arms.entries 至少两条：参照臂 + 候选臂")
        labels = set()
        for i, entry in enumerate(entries):
            _object(entry, {"label", "system", "core", "bizhawk", "sync_settings", "movie", "expect", "note"},
                    {"label", "core", "movie"}, f"verify.arms.entries[{i}]")
            _name(entry["label"], "臂 label")
            if entry["label"] in labels:
                raise SchemaError("臂 label 不可重复")
            labels.add(entry["label"])
            entry["core"] = _text(entry["core"], "臂 core")
            if "system" in entry:
                _text(entry["system"], "臂 system")
            if "bizhawk" in entry:
                entry["bizhawk"] = _path(entry["bizhawk"], base)
            if "sync_settings" in entry and not isinstance(entry["sync_settings"], dict):
                raise SchemaError("臂 sync_settings 必须是对象")
            movie = _object(entry["movie"], {"path", "sha256"}, {"path", "sha256"}, f"臂 movie[{i}]")
            movie["path"] = _path(movie["path"], base)
            movie["sha256"] = _hash(movie["sha256"], 64, "臂 movie SHA256")
            entry["movie"] = movie
            entry["expect"] = entry.get("expect", "agree")
            if entry["expect"] not in ("agree", "differ"):
                raise SchemaError("verify.arms.entries.expect 只能是 agree 或 differ")
            if i == 0:
                if entry["expect"] != "agree":
                    raise SchemaError("参照臂（entries[0]）不许声明 differ")
                if movie["path"] != start["path"] or movie["sha256"] != start["sha256"]:
                    raise SchemaError("参照臂必须就是本任务的初态电影，否则对照的两条时间线不是同一条")
                if entry["core"] != profile["core"] or entry.get("bizhawk", profile["bizhawk"]) != profile["bizhawk"]:
                    raise SchemaError("参照臂的核心/版本必须与本任务 profile 一致")
        for entry in entries[1:]:
            if entry["core"] == profile["core"] and entry.get("bizhawk", profile["bizhawk"]) == profile["bizhawk"]:
                raise SchemaError("候选臂不能与参照臂使用相同核心和相同 BizHawk 版本")
        if "source" in arms:
            _text(arms["source"], "verify.arms.source")
    ts = verify.get("tail_stasis") or {}
    tail_probe = _tail_probe(ts, start, checks, verify.get("length"))
    program = {"id": doc["id"], "platform": platform, "system": profile["system"],
               "core": profile["core"], "core_identity": core_identity_expectation(profile["system"], profile["core"]),
               "bizhawk": profile["bizhawk"], "rom": doc["rom"]["path"],
               "rom_sha1": doc["rom"]["sha1"], "sync_settings": profile.get("sync_settings", {}),
               "start": deepcopy(start), "steps": steps, "completion": checks,
               "capture": record.get("video", False), "fps": fps, "speed": speed,
               "frameskip": frameskip, "tail_probe": tail_probe,
               "ffmpeg": _text(record.get("ffmpeg", "ffmpeg"), "ffmpeg"),
               "ffprobe": _text(record.get("ffprobe", "ffprobe"), "ffprobe")}
    return doc, program


def plan(doc, base, allow=()):
    normalized, program = normalize(doc, base)
    allow = set(allow or ())
    blockers, files = [], []
    # 选题闸门排在所有资源检查之前：冷门作品连 ROM 哈希都不用算，直接不占测试格。
    _pop = popularity.gate_blocker(normalized)
    if _pop:
        blockers.append(_pop)
    rom_archive, rom_entry = split_rom_spec(normalized["rom"]["path"])
    if rom_entry is None:
        if not rom_archive.is_file():
            blockers.append({"code": "missing_rom", "reason": str(rom_archive)})
        else:
            files.append(rom_archive)
            actual = hashlib.sha1(rom_archive.read_bytes()).hexdigest()
            if actual != normalized["rom"]["sha1"]:
                blockers.append({"code": "rom_mismatch", "reason": f"actual={actual}"})
    else:
        # 压缩包内寻址：只读那一条条目算哈希，绝不写回原包。
        if not rom_archive.is_file():
            blockers.append({"code": "missing_rom", "reason": str(rom_archive)})
        else:
            files.append(rom_archive)
            try:
                with zipfile.ZipFile(rom_archive) as zf:
                    data = zf.read(rom_entry)
            except KeyError:
                blockers.append({"code": "missing_rom", "reason": f"{rom_archive} 内没有条目 {rom_entry}"})
                data = None
            except (OSError, zipfile.BadZipFile) as e:
                blockers.append({"code": "missing_rom", "reason": f"{rom_archive}: {e}"})
                data = None
            if data is not None:
                actual = hashlib.sha1(data).hexdigest()
                if actual != normalized["rom"]["sha1"]:
                    blockers.append({"code": "rom_mismatch", "reason": f"actual={actual}"})
    if program:
        if normalized["platform"] in ("PSP", "ARCADE_FBNEO"):
            blockers.append({"code": "backend_not_wired", "reason": "此运行器是 BizHawk；独立 PPSSPP/FBNeo 控制适配待接"})
        elif normalized["platform"] not in PLATFORMS_DRIVER_PROVEN:
            blockers.append({"code": "driver_platform_unproven",
                             "reason": f"资源/版本齐也不等于能跑：控制运行器实测过整片的平台只有 "
                                       f"{', '.join(PLATFORMS_DRIVER_PROVEN)}，{normalized['platform']} 还没跑过一部。"
                                       f"要实测就加 --allow driver_platform_unproven，产物里会留下这条降级记录"})
        bh = Path(program["bizhawk"])
        if not (bh / "EmuHawk.exe").is_file():
            blockers.append({"code": "missing_emulator", "reason": str(bh)})
        else:
            files.extend(p for p in bh.rglob("*") if p.is_file() and
                         (p.suffix.lower() in (".exe", ".dll") or p.name == "config.ini"))
            stalled = driver_stall_version(bh.name)
            if stalled:
                blockers.append({"code": "driver_stall_measured",
                                 "reason": f"BizHawk {stalled} 在本驱动下不进放映（实测 2.3/2.3.1 两个速度档全部 0 帧），"
                                           f"换 {list(DRIVER_OK_BIZHAWK)} 里的版本或按原电影版本另找核心"})
        inh = normalized.get("provenance", {}).get("arm_inherited_from")
        if inh:
            # 站点登记的那个 BizHawk 本机没有，这台臂是照抄同 ROM 另一部原生片借来的。
            # 借来的臂没在这个 ROM 上实测过，所以拦在启动前，放行要显式 --allow 且产物留痕。
            blockers.append({"code": "emulator_version_inherited",
                             "reason": f"臂是继承的：站点登记 {inh['declared']!r} 本机没装，改用同 ROM 原生片 "
                                       f"pub {inh['pub_id']} 的 BizHawk {inh['used']}（Core={inh.get('core')}）；"
                                       f"这台臂在该 ROM 上还没实测过整片，要试就加 --allow emulator_version_inherited"})
        if normalized.get("record", {}).get("audio"):
            blockers.append({"code": "audio_not_wired", "reason": "原子控制运行器尚未接游戏原生音轨，不能用静音片冒充"})
        start = program["start"]
        if start["kind"] != "boot":
            path = Path(start["path"])
            if not path.is_file():
                blockers.append({"code": "missing_start", "reason": str(path)})
            else:
                files.append(path)
                if sha256_file(path) != start["sha256"]:
                    blockers.append({"code": "start_mismatch", "reason": str(path)})
                if start["kind"] == "movie":
                    try:
                        header, frames, length = _bk2_info(path)
                        start["movie_frames"] = frames
                        start["movie_input_lines"] = length["lines"]
                        start["movie_frame_source"] = length["source"]
                        required = _hash(header.get("SHA1"), 40, "电影 SHA1")
                        if required != normalized["rom"]["sha1"]:
                            blockers.append({"code": "movie_rom_mismatch", "reason": required})
                        if header.get("Platform") != program["system"] or header.get("Core") != program["core"]:
                            blockers.append({"code": "movie_profile_mismatch", "reason": "电影核心/系统与 profile 不一致"})
                        version = re.search(r"\d+(?:\.\d+)+", header.get("emuVersion", ""))
                        dir_ver = re.search(r"\d+(?:\.\d+)*", bh.name)
                        if version is None or dir_ver is None or _version_trim(version.group()) != _version_trim(dir_ver.group()):
                            blockers.append({"code": "emulator_version_unverified",
                                             "reason": f"电影 emuVersion {version.group() if version else '无'} 与目录 {bh.name} 不是同一版本"})
                        consumed = 0
                        for step in program["steps"]:
                            if step["op"] == "replay":
                                if step["frames"] == "end":
                                    step["frames"] = frames - consumed
                                consumed += step["frames"]
                                if step["frames"] <= 0 or consumed > frames:
                                    blockers.append({"code": "movie_range", "reason": "replay 超出电影输入长度或重复 end"})
                    except (OSError, ValueError, KeyError, zipfile.BadZipFile, SchemaError) as e:
                        # SchemaError 也要落成 blocker：子帧核心又缺 CycleCount/VBlankCount 的电影就是这种，
                        # 让它抛出去会整批崩掉，剩下的片子一条都评不出来。
                        blockers.append({"code": "movie_format", "reason": str(e)})
        for step in program["steps"]:
            if step["op"] != "seed_ram":
                continue
            source = Path(step["path"])
            if not source.is_file():
                blockers.append({"code": "missing_seed_ram", "reason": str(source)})
                continue
            files.append(source)
            if source.stat().st_size != step["bytes"]:
                blockers.append({"code": "seed_ram_size", "reason": f"{source}: {source.stat().st_size} != {step['bytes']}"})
            if sha256_file(source) != step["sha256"]:
                blockers.append({"code": "seed_ram_mismatch", "reason": str(source)})
        # 末段采样窗要贴着真实末帧定，而电影帧数只有读了 .bk2 才知道，所以在 plan 里重算一次。
        program["tail_probe"] = _tail_probe((normalized.get("verify") or {}).get("tail_stasis") or {}, start,
                                            program["completion"],
                                            (normalized.get("verify") or {}).get("length"))
        window = NES_READABLE_WINDOWS.get(program["core"]) if normalized["platform"] == "NES" else None
        if window:
            for where, item in _memory_items(program):
                if item["domain"] != "System Bus":
                    continue
                lo, hi = item["addr"], item["addr"] + item["width"]
                if not any(a <= lo and hi <= b for a, b in window):
                    blockers.append({"code": "memory_window_unreadable",
                                     "reason": f"{where} 的 {item.get('id') or '%04X' % lo} 在 {lo:#06x}+{item['width']}，"
                                               f"{program['core']} 读该窗口只会得到恒定总线浮值，"
                                               f"可读窗口={['%04X-%04X' % w for w in window]}；换地址或换核心"})
        # 判据表的平台覆盖：上面那道可读窗口闸门只认识 NES 的核心，对非 NES 是空转。
        # 空转不等于放行——NES 的地址映射搬到 SNES/GB/PSX 上读的是另一个含义的数字，
        # 数字再自洽也不是那个局面（§34/§35 同一条教训），所以这里单独拦一道。
        if normalized["platform"] not in R.PREDICATE_TABLE_MEASURED:
            judging = [(where, item) for where, item in _memory_items(program)
                       if where == "completion" or where.split()[-1] == "checks"]
            if judging:
                blockers.append({"code": "predicate_platform_unproven",
                                 "reason": f"{normalized['platform']} 没有本机实测过的判据表："
                                           f"{len(judging)} 条带判定的内存断言（{sorted(set(w for w, _ in judging))}）"
                                           f"沿用 NES 的地址映射，可读窗口与帧量化也只在 NES 上核过，"
                                           f"换平台读回来的不是同一个含义；"
                                           f"观察（watches/writes）和截图不受这条限制——补本平台判据表靠的正是读地址；"
                                           f"要放行判定就 --allow predicate_platform_unproven，"
                                           f"但 pass 买不回来，结果降成 inconclusive"})
        cp_names = {s.get("name") for s in program["steps"] if s["op"] == "checkpoint"}
        for item in program["completion"]:
            ev = item.get("evidence")
            if not ev:
                blockers.append({"code": "completion_evidence_missing",
                                 "reason": f"通关判据 {item['id']} 没有截图证词。流程是先看图再定判据："
                                           f"python _工具脚本/taspipe/control.py window --spec … --from … --to … 拿到 "
                                           f"runtime/checkpoint_NNNN.png，读数写进 evidence.seen、图名写进 evidence.checkpoint、"
                                           f"字节摘要写进 evidence.sha256（缺任何一格都不许声称通关）"})
            elif ev["checkpoint"] not in cp_names:
                blockers.append({"code": "completion_evidence_step_missing",
                                 "reason": f"evidence.checkpoint={ev['checkpoint']} 不是本任务的 checkpoint 步骤，"
                                           f"跑完不会产出这张图；本任务可用的采样点有 "
                                           f"{sorted(x for x in cp_names if x)[:6]}{'…' if len(cp_names) > 6 else ''}"})
        arms_cfg = normalized.get("verify", {}).get("arms")
        if arms_cfg:
            # 臂的资格在启动前查：核心/版本/电影头三项必须自洽，且各臂放的是同一份输入。
            # 输入层不同就不是「同步」问题而是「两盘带子」，逐帧对照没有意义，直接拦下。
            from . import fceux as F
            ref_frames = ref_log = None
            for i, entry in enumerate(arms_cfg["entries"]):
                tag = f"臂 {entry['label']}"
                bh = Path(entry.get("bizhawk") or program["bizhawk"])
                if not (bh / "EmuHawk.exe").is_file():
                    blockers.append({"code": "missing_emulator", "reason": f"{tag}: {bh}"})
                else:
                    files.append(bh / "EmuHawk.exe")
                    stalled = driver_stall_version(bh.name)
                    if stalled:
                        blockers.append({"code": "driver_stall_measured",
                                         "reason": f"{tag}: BizHawk {stalled} 在本驱动下不进放映（实测 0 帧）"})
                movie = Path(entry["movie"]["path"])
                if not movie.is_file():
                    blockers.append({"code": "missing_arm_movie", "reason": f"{tag}: {movie}"})
                    continue
                files.append(movie)
                if sha256_file(movie) != entry["movie"]["sha256"]:
                    blockers.append({"code": "arm_movie_mismatch", "reason": f"{tag} 内容已变化: {movie}"})
                    continue
                try:
                    header, frames, _info = _bk2_info(movie)
                    log = F.input_log_digest(movie)
                except (OSError, ValueError, KeyError, zipfile.BadZipFile, SchemaError) as e:
                    blockers.append({"code": "arm_movie_format", "reason": f"{tag}: {e}"})
                    continue
                want_system = entry.get("system") or program["system"]
                if header.get("Platform") != want_system or header.get("Core") != entry["core"]:
                    blockers.append({"code": "arm_profile_mismatch",
                                     "reason": f"{tag}: 头部 Platform={header.get('Platform')} "
                                               f"Core={header.get('Core')}，声明要 {want_system}/{entry['core']}"})
                ver = re.search(r"\d+(?:\.\d+)+", header.get("emuVersion", ""))
                dir_ver = re.search(r"\d+(?:\.\d+)*", bh.name)
                if ver is None or dir_ver is None or _version_trim(ver.group()) != _version_trim(dir_ver.group()):
                    blockers.append({"code": "arm_emulator_version_unverified",
                                     "reason": f"{tag}: 头部 emuVersion {ver.group() if ver else '无'} "
                                               f"与目录 {bh.name} 不是同一版本"})
                if i == 0:
                    ref_frames, ref_log = frames, log
                elif frames != ref_frames:
                    blockers.append({"code": "arm_length_mismatch",
                                     "reason": f"{tag}: {frames} 帧与参照臂 {ref_frames} 帧不同长，逐帧对照不成立"})
                elif log != ref_log:
                    blockers.append({"code": "arm_input_log_mismatch",
                                     "reason": f"{tag}: 输入层字节与参照臂不同，两臂放的不是同一份操作"})
            if ref_frames and arms_cfg["samples"] != ["end"]:
                for point in [x for x in arms_cfg["samples"] if x != "end"]:
                    if point > ref_frames:
                        blockers.append({"code": "arm_sample_out_of_range",
                                         "reason": f"采样点 {point} 超出参照臂 {ref_frames} 帧"})
    else:
        rom = split_rom_spec(normalized["rom"]["path"])[0]
        if rom.is_file():
            data = rom.read_bytes()
            for patch in normalized["patches"]:
                offset, expected = patch["offset"], bytes.fromhex(patch["expect"])
                if data[offset:offset + len(expected)] != expected:
                    blockers.append({"code": "patch_precondition", "reason": f"offset={offset} 原始字节不符或越界"})
    sources = [HERE / n for n in ("control.py", "control_runtime.py", "control_runtime.lua", "schema.py",
                                  "macro_compiler.py", "retro_platforms.py", "statejump.py", "watchdog.py")]
    sources.append(HERE.parent / "tas_replay.py")
    files.extend(p for p in sources if p.is_file())
    digest = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode())
    for path in sorted(set(files), key=str):
        digest.update(str(path).encode("utf-8"))
        digest.update(sha256_file(path).encode("ascii"))
    warned = [b for b in blockers if b["code"] in allow and b["code"] not in NON_DEGRADABLE_BLOCKERS]
    blockers = [b for b in blockers if b["code"] not in allow or b["code"] in NON_DEGRADABLE_BLOCKERS]
    return {"status": "blocked" if blockers else "ready", "id": normalized["id"],
            "mode": normalized["mode"], "spec": normalized, "program": program,
            "fingerprint": digest.hexdigest(), "blockers": blockers, "warnings": warned,
            "verification": {"execution": "not_run", "completion": "not_run", "sync": "unverified",
                                 "core_identity": "not_run"}}


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


@contextmanager
def _lock(directory):
    lock = Path(directory) / ".control.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SchemaError(f"输出目录已被占用；核实进程后再处理锁: {lock}")
    token = f"{os.getpid()}:{uuid.uuid4().hex}"
    try:
        with os.fdopen(fd, "w", encoding="ascii") as out:
            out.write(token)
        yield
    finally:
        if lock.is_file() and lock.read_text(encoding="ascii") == token:
            lock.unlink()


def _reusable(report, fp):
    if (report.get("status") not in ("done", "inconclusive") or report.get("fingerprint") != fp
            or report.get("verification", {}).get("execution") != "pass"
            or report.get("verification", {}).get("core_identity") != "pass"):
        return False
    refs = report.get("artifacts", [])
    if not refs:
        return False
    try:
        return all(Path(r["uri"]).is_file() and Path(r["uri"]).stat().st_size == r["byte_size"]
                   and sha256_file(r["uri"]) == r["sha256"] for r in refs)
    except (OSError, KeyError, TypeError):
        return False


def _guard_outputs(targets, sources):
    for target in map(Path, targets):
        for source in map(Path, sources):
            if (target.resolve() == source.resolve() or
                    (target.exists() and source.exists() and target.samefile(source))):
                raise SchemaError(f"输出路径与输入资产重合: {target}")


def _inputs(doc):
    archive, _entry = split_rom_spec(doc["rom"]["path"])
    paths = [str(archive)]
    if doc.get("start", {}).get("path"):
        paths.append(doc["start"]["path"])
    return paths


def run(doc, base, out_dir, work_root=DEFAULT_WORK, timeout=300, executor=None, allow=()):
    if type(timeout) not in (float, int) or not math.isfinite(timeout) or timeout <= 0:
        raise SchemaError("timeout 必须为有限正数")
    pre = plan(doc, base, allow)
    root = Path(out_dir).resolve()
    _guard_outputs([root / "control.json", root / ".control.lock"], _inputs(pre["spec"]))
    root.mkdir(parents=True, exist_ok=True)
    with _lock(root):
        manifest = root / "control.json"
        if pre["status"] == "blocked":
            result = {k: pre[k] for k in ("status", "id", "mode", "fingerprint", "blockers",
                                          "warnings", "verification")}
            result["artifacts"] = []
            write_json(manifest, result)
            return result
        if manifest.is_file():
            previous = json.loads(manifest.read_text(encoding="utf-8"))
            if _reusable(previous, pre["fingerprint"]):
                return {**previous, "reused": True}
        attempt = root / ("attempt_" + uuid.uuid4().hex[:12])
        attempt.mkdir()
        result = {"id": pre["id"], "mode": pre["mode"], "fingerprint": pre["fingerprint"],
                  "reused": False, "attempt_dir": str(attempt), "status": "running", "artifacts": [],
                  "warnings": pre.get("warnings", []),
                  "verification": {"execution": "not_run", "completion": "inconclusive", "sync": "unverified",
                                   "core_identity": "not_run"}}
        write_json(manifest, result)
        write_json(attempt / "plan.json", pre)
        try:
            normalized = pre["spec"]
            if pre["mode"] == "rom_patch":
                source = Path(normalized["rom"]["path"])
                data = bytearray(source.read_bytes())
                if hashlib.sha1(data).hexdigest() != normalized["rom"]["sha1"]:
                    raise SchemaError("ROM 在预检后发生变化")
                for patch in normalized["patches"]:
                    offset = patch["offset"]
                    expect = bytes.fromhex(patch["expect"])
                    if data[offset:offset + len(expect)] != expect:
                        raise SchemaError("ROM 补丁前置字节已变化")
                    data[offset:offset + len(expect)] = bytes.fromhex(patch["value"])
                target = attempt / ("patched" + source.suffix)
                target.write_bytes(data)
                result.update(status="done", modified_rom_sha1=hashlib.sha1(data).hexdigest(),
                              source_rom_sha1=normalized["rom"]["sha1"])
                result["verification"] = {"execution": "pass", "completion": "inconclusive",
                                          "sync": "not_applicable", "core_identity": "not_applicable"}
                refs = [target]
            else:
                if executor is None:
                    from taspipe.control_runtime import execute
                    executor = execute
                runtime_out = attempt / "runtime"
                runtime_out.mkdir()
                runtime = executor(pre["program"], str(runtime_out), str(work_root), timeout=timeout)
                result["runtime"] = runtime
                execution = runtime.get("execution", "fail")
                completion = runtime.get("completion", "inconclusive")
                if execution not in ("pass", "fail") or completion not in ("pass", "fail", "inconclusive"):
                    raise SchemaError("运行器返回非法判定")
                _check_latch_witness(pre["program"], runtime)
                verdict, why = _check_predicate_platform(normalized["platform"], runtime, pre.get("warnings"))
                if verdict != completion:
                    result["predicate_platform"] = {"runner": completion, "final": verdict, "reason": why}
                    completion = verdict
                verdict, why = _check_completion_evidence(pre["program"], runtime)
                if verdict != completion:
                    result["completion_evidence"] = {"runner": completion, "final": verdict, "reason": why}
                    completion = verdict
                stasis = _tail_measurement(runtime, pre["program"].get("tail_probe"))
                result["tail_stasis"] = stasis
                picture = _picture_health(runtime)
                result["picture"] = picture
                if picture.get("dead_tail"):
                    result["warnings"] = list(result.get("warnings") or []) + [
                        {"code": "picture_dead_tail", "detail": picture["reason"] + "；生产交付已拒绝"}]
                if completion == "pass":
                    tail_verdict, tail_why = _check_tail_stasis(pre["program"], runtime, stasis)
                    if tail_verdict != completion:
                        result["tail_stasis"]["downgraded"] = tail_why
                        completion = tail_verdict
                visual = "fail" if picture.get("dead_tail") else ("pass" if picture.get("measured") else "unverified")
                identity = runtime.get("core_identity", "unverified")
                if identity != "pass":
                    execution = "fail"
                    result["status"] = "failed"
                    result["reason"] = "实际核心身份验收不是 pass：" + runtime.get("core_identity_evidence", {}).get("reason", "缺少零帧证据")
                result["verification"] = {"execution": execution, "completion": completion,
                                          "sync": "unverified", "visual": visual, "core_identity": identity}
                result["status"] = "done" if execution == "pass" else "failed"
                if completion == "fail" or picture.get("dead_tail"):
                    result["status"] = "failed"
                elif normalized["purpose"] == "playthrough" and completion != "pass":
                    result["status"] = "inconclusive" if execution == "pass" else "failed"
                result["reason"] = runtime.get("reason", "")
                if stasis.get("downgraded"):
                    # 末屏静止而证词取自中途：废掉那句声称，并把该看哪一帧写进 reason。
                    result["reason"] = stasis["downgraded"]
                elif "completion_evidence" in result:
                    # 通关声称被证词闸门废掉时，reason 要说清废在哪一格，不许留着运行器那句无关的话。
                    result["reason"] = result["completion_evidence"]["reason"]
                spec_verify = normalized.get("verify", {})
                if "length" in spec_verify:
                    check = _check_length(runtime.get("frames_advanced"), spec_verify["length"]["frames"],
                                          spec_verify["length"]["tolerance"])
                    check["source"] = spec_verify["length"].get("source", "")
                    result["length_check"] = check
                    if not check["pass"]:
                        # 帧数对不上 = 跑的不是这部电影的完整长度，成功与否都不许登记成通关。
                        result["status"] = "failed"
                        if runtime.get("status") == "blocked":
                            # 11-22 实测 4776：锁没让回放启动，实到 0 帧，头条却写成"长度核对不通过"，
                            # 把人引去查电影长度；病因在锁，必须点名。
                            result["warnings"] = list(result.get("warnings") or []) + [
                                {"code": "replay_never_started",
                                 "detail": f"回放根本没跑起来，帧数当然对不上；真正病因：{runtime.get('reason', '')}"}]
                            result["reason"] = "长度核对不通过（回放没跑起来，不是电影短了）：" + check["reason"]
                        elif runtime.get("deadline_exceeded"):
                            if not check["actual"]:
                                # 截止在启动阶段就到了（EmuHawk 还没拉起），说"截断了回放"会误导。
                                result["warnings"] = list(result.get("warnings") or []) + [
                                    {"code": "runtime_deadline_truncated",
                                     "detail": f"--timeout {runtime.get('timeout_seconds')}s 在回放启动前就到期，"
                                               f"一帧都没跑；真正病因：{runtime.get('reason', '')}"}]
                                result["reason"] = "长度核对不通过（截止在启动前就到、回放没跑起来，不是电影本身短）：" + check["reason"]
                            else:
                                result["warnings"] = list(result.get("warnings") or []) + [
                                    {"code": "runtime_deadline_truncated",
                                     "detail": f"--timeout {runtime.get('timeout_seconds')}s 到点掐断回放，"
                                               f"实到 {check['actual']} 帧是截止帧号、不是电影长度；要跑完就加大 --timeout"}]
                                result["reason"] = "长度核对不通过（截止截断了回放，不是电影本身短）：" + check["reason"]
                        else:
                            result["reason"] = "长度核对不通过：" + check["reason"]
                if picture.get("dead_tail"):
                    result["reason"] = (result["reason"] + "；" if result["reason"] else "") + "视觉验收不通过：" + picture["reason"]
                refs = runtime.get("artifacts", [])
                if execution == "pass" and (not refs or any(not Path(p).is_file() or Path(p).stat().st_size == 0 for p in refs)):
                    raise SchemaError("运行器未交付完整非空产物，不能登记成功")
                if "arms" in spec_verify and execution == "pass":
                    # 臂对照要重放整段电影，成本按臂数成倍增加；串行跑，一次只开一个 EmuHawk。
                    arms_report = _run_arms(normalized, base, attempt, work_root, timeout, executor, allow)
                    result["arms"] = arms_report
                    result["verification"]["sync"] = arms_report["sync"]
                    if arms_report["sync"] == "fail" and result["status"] == "done":
                        result["status"] = "inconclusive"
                        result["reason"] = "同步对照不通过：" + arms_report["sync_reason"]
                elif "arms" in spec_verify:
                    result["verification"]["sync"] = "fail"
            result["artifacts"] = [asset(str(p)) for p in refs]
            result["artifacts"].append(asset(str(attempt / "plan.json")))
        except Exception as e:
            result["status"] = "failed"
            result["verification"]["execution"] = "fail"
            result["reason"] = f"{type(e).__name__}: {e}"
        write_json(attempt / "result.json", result)
        result["artifacts"].append(asset(str(attempt / "result.json")))
        write_json(manifest, result)
        return result


def catalog(lib, emu_root):
    doc = R.build(lib, emu_root, out=None)
    inventory = Counter()
    platforms = Counter()
    movies = Path(lib) / "movies"
    if movies.is_dir():
        for p in movies.rglob("*"):
            if p.is_file():
                inventory[p.suffix.lower() or "(no extension)"] += 1
                platforms[p.relative_to(movies).parts[0]] += 1
    doc["inventory"] = {"files": sum(inventory.values()), "formats": dict(inventory), "platforms": dict(platforms)}
    doc["execution_status"] = "not_run"
    doc["note"] = "replayable 是资源预检，不是实测同步或通关；输入文件数不等于独立游戏数"
    return doc


def init_movie(pub_id, lib, emu_root):
    pubs = R.load_publications(lib)
    pub = next((p for p in pubs if str(p["id"]) == str(pub_id)), None)
    if pub is None:
        raise SchemaError(f"未登记出版物 {pub_id}")
    assessment = R.assess(pub, lib, R.index_roms(lib), R.index_versions(lib), R.discover_bizhawk(emu_root))
    # 只有「该平台驱动还没实测」和「臂是继承来的」这两条可以带着生成任务，否则新平台的
    # 实测永远开不了工；真跑的时候由 plan 的同名闸门拦着，要过就得显式 --allow。
    soft = ("driver_platform_unproven", "emulator_version_inherited")
    hard = [b for b in assessment["blockers"] if b["code"] not in soft]
    if hard:
        raise SchemaError(json.dumps(hard, ensure_ascii=False))
    from taspipe.retro_platforms import PLATFORM_SPECS
    header, frames, length = _bk2_info(assessment["movie"])
    system = _header_value(header, "Platform") or ""
    platform = next((k for k, v in PLATFORM_SPECS.items() if v["system"] == system), None)
    if platform is None:
        raise SchemaError(f"控制运行器未建模电影平台 {system}")
    if _is_pal(header):
        raise SchemaError(f"出版物 {pub_id} 声明 PAL，帧数口径只在 NTSC 上标定过，需人工核对后再生成任务")
    spec = {"version": 1, "id": "pub_" + str(pub_id), "mode": "session", "purpose": "playthrough",
            "game": pub.get("game", ""), "platform": platform,
            "rom": {"path": assessment["rom_match"][0], "sha1": assessment["required_rom_sha1"].lower()},
            "profile": {"bizhawk": assessment["emulator_dir"], "core": _header_value(header, "Core"),
                        "system": system},
            "start": {"kind": "movie", "path": assessment["movie"], "sha256": sha256_file(assessment["movie"])},
            "steps": [{"id": "full_movie", "op": "replay", "frames": "end"}],
            "record": {"video": False, "audio": False, "fps": PLATFORM_SPECS[platform]["fps"]}}
    if assessment.get("arm_inherited_from"):
        spec["provenance"] = {"arm_inherited_from": assessment["arm_inherited_from"]}
    expected = _site_frames(pub.get("time", ""), PLATFORM_SPECS[platform]["fps"])
    duration_check = _site_duration_check(pub.get("time", ""), frames, PLATFORM_SPECS[platform]["fps"])
    if not duration_check["accepted"]:
        if expected is None:
            raise SchemaError(f"出版物 {pub_id} 的时长 {pub.get('time')!r} 读不出秒数，不能生成带长度核对的通关任务")
        raise SchemaError(f"出版物 {pub_id} 的站点时长 {pub.get('time')} 折 {expected} 帧，"
                          f"电影自身 {frames} 帧（行数 {length['lines']}，口径 {length['source']}）："
                          f"差 {frames - expected} 帧超过 2 帧，且不等于按名义 60fps 舍入的站点时长，"
                          "先弄清电影长度口径再生成任务")
    spec["verify"] = {"length": {"frames": frames, "tolerance": _tight_tolerance(frames),
                                 "source": f"电影自身 {length['source']} 口径 {frames} 帧；"
                                           f"站点时长 {pub.get('time')} 折 {expected} 帧"
                                           f"（横检差 {frames - expected} 帧，口径 {duration_check['basis']}）"}}
    return spec


def window_spec(pub_id, lo, hi, step, lib, emu_root, base_spec=None):
    """把整片回放切成"只在指定帧窗内每 step 帧留一张画面+一份字节"的观察任务。

    通关判据不能靠整片跑完再全量对 RAM：那只能证明"跑到了"，看不出这一屏在打什么。
    先用窗口把画面看懂（门在哪、敌人从哪来、目标是什么），再拿看得见的切换去锁字节。
    --spec 从现成任务派生（不重新盘点，秒出）；--pub 走 init_movie，要为一条片子扫全库 ROM。
    """
    if base_spec is not None:
        spec = deepcopy(base_spec)
        spec.pop("completion", None)
        spec["verify"] = spec.get("verify") or {}
        if not spec["verify"].get("length"):
            raise SchemaError("基任务没有 verify.length，定不出窗口上界")
    else:
        spec = init_movie(pub_id, lib, emu_root)
    total = spec["verify"]["length"]["frames"]
    if not (type(lo) is int and type(hi) is int and type(step) is int):
        raise SchemaError("window 的 --from/--to/--step 必须是整数")
    if not 1 <= lo < hi <= total:
        raise SchemaError(f"窗口 {lo}..{hi} 越界，电影 {pub_id or spec.get('id')} 只有 {total} 帧")
    if not 1 <= step <= 600:
        raise SchemaError("window --step 必须在 1..600，太粗的采样看不出画面在什么时候切换")
    steps, cursor = [], 0

    def goto(target):
        nonlocal cursor
        steps.append({"id": f"to_{target}", "op": "replay", "frames": target - cursor})
        steps.append({"id": f"cp_{target}", "op": "checkpoint", "name": f"cp_{target}"})
        cursor = target

    goto(lo)
    for f in range(lo + step, hi + 1, step):
        goto(f)
    if cursor != hi:
        # 步长不整除窗口时补最后一格：不补的话末屏停在 hi 之前，
        # 长度闸门就会拿"格子没走到终点"当成片子的问题（11-21 实测 12 条里 9 条这样假失败）。
        goto(hi)
    spec["steps"] = steps
    spec["id"] = f"{pub_id and 'pub_' + str(pub_id) or spec.get('id', 'task')}_window_{lo}_{hi}"
    spec["purpose"] = "control"
    if spec.get("game"):
        # 没名字就不拼注释：拼了会把「— 只看 …」当成标题送进选题闸门，
        # 闸门会报成「这部冷门」而不是「spec 没写 game」。
        spec["game"] = f"{spec['game']}{popularity.WINDOW_NOTE}{lo}..{hi} 帧（每 {step} 帧一屏）"
    # 窗口是拿来"看"的，实时逐帧走会把一次盘点拖成几十分钟
    record = {"video": False, "audio": False, "speed": "unthrottled"}
    if spec.get("record", {}).get("fps"):
        record["fps"] = spec["record"]["fps"]
    spec["record"] = record
    spec["verify"] = {"length": {"frames": hi, "tolerance": _tight_tolerance(hi),
                                 "source": f"窗口终点 {hi} 帧（整片 {total} 帧的前缀）"}}
    return spec


def _pid_alive(pid):
    """问 Windows 这个 pid 还在不在：True / False，量不到 = None。

    不用 tasklist：自检闸门禁止起子进程（11-21 实测会被 isolation violation 抓住），
    而且它在中文 Windows 上是 GBK 输出。
    """
    if not isinstance(pid, int) or pid <= 0 or os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == 5                  # ERROR_ACCESS_DENIED = 在，只是没权限查
    except (AttributeError, OSError, ValueError):
        return None


def _runtime_lock_state(work_root):
    """串行窗口的锁现在是什么状态：谁占的、那个 pid 还在不在。None = 没人占。

    11-21 实测：我 kill 掉 SNES 那趟之后锁没清，紧接着 13 条 NES 批次全部 0 帧失败，
    每条都白写一份 attempt 才报出同一个原因。0 帧失败是环境问题，不是片子的问题，
    所以批次开工前必须先问一次，跑中途撞上同样的原因就就地停。
    """
    lock = Path(work_root) / ".control_runtime.lock"
    if not lock.is_file():
        return None
    try:
        info = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    pid = info.get("pid") if isinstance(info, dict) else None
    try:
        alive = _pid_alive(pid)
    except Exception:
        alive = None
    return {"path": str(lock), "token": (info or {}).get("token"), "pid": pid, "pid_alive": alive}


def _lock_holder_words(held):
    """把锁的状态说成人话；三档措辞不能合并——"查不到"说成"死锁"就等于允许清锁。"""
    if held["pid_alive"] is True:
        return "占位进程 pid %s 还活着=有别的任务在用串行窗口" % held["pid"]
    if held["pid_alive"] is False:
        return "占位进程 pid %s 已不存在=死锁" % held["pid"]
    return "占位者 pid %s 查不到（量不到不等于没人占）" % held["pid"]


def _lock_tokens(text):
    """两种锁各自的 (pid, token)：work_root 那份是 JSON，`_lock()` 写的是 "pid:token" 纯文本。"""
    try:
        info = json.loads(text)
    except ValueError:
        head, _, tail = text.strip().partition(":")
        return (int(head) if head.isdigit() else None), (tail or None)
    if not isinstance(info, dict):
        return None, None
    return info.get("pid"), info.get("token")


def reclaim_stale_lock(path, expect_token=None):
    """收残留锁：只有把持有者量到"已不存在=死锁"才允许，活着或查不到一律拒。

    11-22 实测：密扫被外部终止后 work_root 那份锁留下了，下一趟 terminal 以实到 0 报
    `replay_never_started`。当时生产件只会拒绝、不会收，清锁只能手搓 ⇒ 违反"结果走生产代码路径"，
    于是把认领判据写死在这：默认只报不删；删前重读一次锁内容，被别的任务改过就拒（pid 会被复用）。
    """
    lock = Path(path)
    if not lock.is_file():
        return {"status": "free", "lock": str(lock), "removed": None}
    pid, token = _lock_tokens(lock.read_text(encoding="utf-8"))
    words = _lock_holder_words({"pid": pid, "pid_alive": _pid_alive(pid)})
    if expect_token is not None and token != expect_token:
        raise SchemaError(f"拒绝清锁：{lock} 里的 token 与认领凭据不符，别收不是自己那趟的锁")
    if _pid_alive(pid) is not False:
        raise SchemaError(f"拒绝清锁：{words}；只有量到已不存在才允许收残留，查不到时先手动核实进程")
    removed = {"pid": pid, "token": token, "pid_alive": False}
    if _lock_tokens(lock.read_text(encoding="utf-8")) != (pid, token):
        raise SchemaError(f"拒绝清锁：核实与删除之间锁内容变了，可能已被新任务占用: {lock}")
    lock.unlink()
    return {"status": "stale_cleared", "lock": str(lock), "removed": removed,
            "still_there": lock.is_file()}


def locks_state(work_root=DEFAULT_WORK, out_dir=None):
    """只读盘点串行窗口和输出目录的锁，谁占的、还在不在。"""
    out = {"runtime_lock": _runtime_lock_state(work_root)}
    if out_dir is not None:
        lock = Path(out_dir) / ".control.lock"
        state = None
        if lock.is_file():
            pid, token = _lock_tokens(lock.read_text(encoding="utf-8"))
            state = {"path": str(lock), "pid": pid, "token": token, "pid_alive": _pid_alive(pid)}
        out["output_lock"] = state
    return out


def batch(spec_paths, base, out_dir, work_root=DEFAULT_WORK, timeout=300, allow=()):
    root = Path(out_dir).resolve()
    jobs, ids = [], set()
    for spec_path in _list(spec_paths, "jobs"):
        path = Path(_path(spec_path, Path(base)))
        doc, source_base = load_spec(path)
        normalized, _ = normalize(doc, source_base)
        if normalized["id"] in ids:
            raise SchemaError(f"批次任务 id 重复: {normalized['id']}")
        ids.add(normalized["id"])
        _guard_outputs([root / "batch.json", root / ".control.lock"], [path, *_inputs(normalized)])
        jobs.append((doc, source_base, normalized["id"]))
    held = _runtime_lock_state(work_root)
    if held:
        raise SchemaError(f"串行窗口已被占用: {held['path']} {_lock_holder_words(held)}；"
                          f"确认占用者并处理锁之后再生批次，这里一条都不启动")
    root.mkdir(parents=True, exist_ok=True)
    results = []
    with _lock(root):
        for doc, source_base, jid in jobs:
            try:
                report = run(doc, source_base, root / jid, work_root, timeout, allow=allow)
            except Exception as e:
                report = {"id": jid, "status": "failed", "reason": f"{type(e).__name__}: {e}"}
            results.append(report)
            rt = report.get("runtime") or {}
            stop = rt.get("frames_advanced") == 0 and "RuntimeBlocked" in str(rt.get("reason", ""))
            if stop:
                for _doc, _base, rest_id in jobs[len(results):]:
                    results.append({"id": rest_id, "status": "blocked",
                                    "reason": "串行窗口锁被占用，批次就地停止（0 帧失败不是片子的问题，不烧后面的 attempt）"})
            # 落盘必须和返回的那份一致：先写再补 blocked 会让 batch.json 少几格
            write_json(root / "batch.json", {"jobs": results, "counts": dict(Counter(r["status"] for r in results))})
            if stop:
                break
    return {"jobs": results, "counts": dict(Counter(r["status"] for r in results))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    cat = sub.add_parser("catalog", help="只读盘点电影、版本与 ROM")
    cat.add_argument("--lib", default=str(R.DEFAULT_LIB))
    cat.add_argument("--emu", default=str(R.DEFAULT_EMU))
    cat.add_argument("--out", required=True)
    init = sub.add_parser("init", help="从已配对出版物生成完整回放任务，不启动模拟器")
    init.add_argument("--pub", required=True)
    init.add_argument("--lib", default=str(R.DEFAULT_LIB))
    init.add_argument("--emu", default=str(R.DEFAULT_EMU))
    init.add_argument("--out", required=True)
    win = sub.add_parser("window", help="生成只看某段帧窗的观察任务（每 step 帧留画面+字节），不启动模拟器")
    win.add_argument("--pub", help="出版物 id：会重新盘点 ROM/版本，慢")
    win.add_argument("--spec", help="现成任务 json：直接从它派生窗口，秒出（默认走这条）")
    win.add_argument("--from", dest="lo", type=int, required=True)
    win.add_argument("--to", dest="hi", type=int, required=True)
    win.add_argument("--step", type=int, default=25)
    win.add_argument("--lib", default=str(R.DEFAULT_LIB))
    win.add_argument("--emu", default=str(R.DEFAULT_EMU))
    win.add_argument("--out", required=True)
    for name in ("plan", "run", "batch"):
        p = sub.add_parser(name)
        p.add_argument("--spec", required=True)
        p.add_argument("--out", required=name != "plan")
        p.add_argument("--allow", default="",
                       help="逗号分隔的可降级阻塞码，转 warnings 后继续跑（只用于实测，例如 "
                            "driver_platform_unproven）；audio_not_wired 不可降级；产物里会留下记录")
        if name != "plan":
            p.add_argument("--work-root", default=str(DEFAULT_WORK))
            p.add_argument("--timeout", type=float, default=300)
    status = sub.add_parser("status")
    status.add_argument("--out", required=True)
    lk = sub.add_parser("locks", help="报串行窗口/输出目录的锁被谁占着；默认只读，加 --clear-stale 才收残留")
    lk.add_argument("--work-root", default=str(DEFAULT_WORK))
    lk.add_argument("--out", help="输出目录：顺带报它的 .control.lock")
    lk.add_argument("--clear-stale", action="store_true",
                    help="收残留锁：先用生产件 _pid_alive 核实，只在量到"
                         "「已不存在=死锁」时才删；活着或查不到一律拒，退出码 1")
    lk.add_argument("--expect-token", help="认领凭据：锁里的 token 必须等于它，防止收到别人那趟的锁")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            report = init_movie(args.pub, args.lib, args.emu)
            target = Path(args.out)
            if target.exists():
                raise SchemaError("init 不覆盖已有任务，请使用新文件名")
            write_json(target, report)
            print(json.dumps({"status": "created", "out": str(target.resolve()), "id": report["id"]}, ensure_ascii=False))
            return 0
        if args.command == "window":
            if bool(args.spec) == bool(args.pub):
                raise SchemaError("window 要 --spec 或 --pub 二选一（--spec 秒出，--pub 要扫全库 ROM）")
            base_doc = None
            if args.spec:
                base_doc, _ = load_spec(args.spec)
                base_doc, _ = normalize(base_doc, Path(args.spec).resolve().parent)
            report = window_spec(args.pub, args.lo, args.hi, args.step, args.lib, args.emu,
                                 base_spec=base_doc)
            target = Path(args.out)
            if target.exists():
                raise SchemaError("window 不覆盖已有任务，请使用新文件名")
            write_json(target, report)
            print(json.dumps({"status": "created", "out": str(target.resolve()), "id": report["id"],
                              "checkpoints": sum(1 for s in report["steps"] if s["op"] == "checkpoint")},
                             ensure_ascii=False))
            return 0
        if args.command == "catalog":
            report = catalog(args.lib, args.emu)
            write_json(args.out, report)
            print(json.dumps({"out": str(Path(args.out).resolve()), "summary": report["summary"], "inventory": report["inventory"]}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "locks":
            state = locks_state(args.work_root, args.out)
            paths = [s["path"] for s in (state["runtime_lock"], state.get("output_lock"))
                     if s and s.get("path")]
            if args.clear_stale:
                cleared, refused = [], []
                for p in paths:
                    try:
                        cleared.append(reclaim_stale_lock(p, args.expect_token))
                    except SchemaError as e:
                        refused.append({"lock": p, "reason": str(e)})
                state["cleared"], state["refused"] = cleared, refused
                print(json.dumps(state, ensure_ascii=False, indent=2))
                return 1 if refused else 0
            print(json.dumps(state, ensure_ascii=False, indent=2))
            return 0
        if args.command == "status":
            directory = Path(args.out)
            path = directory / ("batch.json" if (directory / "batch.json").is_file() else "control.json")
            report = json.loads(path.read_text(encoding="utf-8"))
        else:
            doc, base = load_spec(args.spec)
            allow = tuple(x.strip() for x in str(args.allow).split(",") if x.strip())
            if args.command == "plan":
                report = plan(doc, base, allow)
                if args.out:
                    _guard_outputs([args.out], [args.spec, *_inputs(report["spec"])])
                    write_json(args.out, report)
            else:
                if not math.isfinite(args.timeout) or args.timeout <= 0:
                    raise SchemaError("timeout 必须为有限正数")
                _guard_outputs([Path(args.out) / "control.json", Path(args.out) / "batch.json",
                                Path(args.out) / ".control.lock"], [args.spec])
                if args.command == "batch":
                    _object(doc, {"jobs"}, {"jobs"}, "批次")
                    report = batch(doc["jobs"], base, args.out, args.work_root, args.timeout, allow)
                else:
                    report = run(doc, base, args.out, args.work_root, args.timeout, allow=allow)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if "jobs" in report:
            return 0 if all(j["status"] == "done" for j in report["jobs"]) else 2
        return 0 if report.get("status") in ("done", "ready") else 3 if report.get("status") == "inconclusive" else 2
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as e:
        print(json.dumps({"status": "error", "reason": f"{type(e).__name__}: {e}"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
