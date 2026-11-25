# -*- coding: utf-8 -*-
"""T3 前置件：NES BizHawk 状态会话（存档跳跃 / RAM 读写 / 逐帧宏 / 帧精确截图）。

工作模式（用户 2026-11-10 拍板）：走位一次到「要素前一刻」→ save 存快照 →
之后每次尝试 = attempt（load+宏+空档+截图，单指令原子完成）→ 检测器验收，
单次尝试秒级，不必每次从头回放。金手指走 read/write 改 RAM。

机制：tas_replay.STATE_LUA_TMPL 起持久 EmuHawk + 文件指令通道（cmd.txt/resp.txt，
id 单调去重）；看门狗线程复用 watchdog 的点框/树杀。能力转真以
验证/t3_statejump/report.json 全 pass 为证据（backends.probe 证据门控，无证据不真）。

红线提醒：纯改 RAM 构造的状态须经检测器正负例验收，游戏逻辑不认的假状态
不能冒充真实复现；确定性（同快照+同输入=同画面）由 verify 实跑钉死。

运行: python -m taspipe.statejump verify --rom <rom.nes> --out <验证/t3_statejump>
"""
import argparse
import contextlib
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import state_registry, watchdog
from .schema import SchemaError

# 平台手柄键名由 Python 静态表注入 Lua；joypad.get 只返回当前按住的键，不能当合法键表。
BUTTON_ALIASES = {"U": "Up", "D": "Down", "L": "Left", "R": "Right"}
KNOWN_BUTTONS = {"A", "B", "Select", "Start", "Up", "Down", "Left", "Right"}

# 多平台按键集：只放宽「宏谱解析」这一层，不代表对应后端已核验可出片。
# 生产准入由 showcase.PLATFORM_PROFILES[platform]["verified"] 独立把关。
_DIRECTIONS = {"Up", "Down", "Left", "Right"}
PLATFORM_BUTTONS = {
    "NES": set(KNOWN_BUTTONS),
    "SNES": set(KNOWN_BUTTONS) | {"X", "Y", "L", "R"},
    "GBA": set(KNOWN_BUTTONS) | {"L", "R"},
    "GB": set(KNOWN_BUTTONS),
    "GBC": set(KNOWN_BUTTONS),
    "MD": set(KNOWN_BUTTONS) | {"X", "Y", "Z", "Mode", "C"},
    "PCE": _DIRECTIONS | {"Run", "Select", "II", "I"},
    "PS1": _DIRECTIONS | {"Select", "Start", "Square", "Triangle", "Circle", "Cross",
                          "L1", "L2", "R1", "R2", "L3", "R3"},
    "PSP": _DIRECTIONS | {"Select", "Start", "Square", "Triangle", "Circle", "Cross",
                          "L", "R", "Analog"},
    "ARCADE_FBNEO": {"Up", "Down", "Left", "Right", "A", "B", "C", "D", "Start", "Coin"},
    "ARCADE_MAME": {"Up", "Down", "Left", "Right", "A", "B", "C", "D", "Start", "Coin"},
}
PLATFORM_ALIASES = {
    "NES": dict(BUTTON_ALIASES, T="Start", S="Select"),
    "SNES": {"U": "Up", "D": "Down", "LT": "Left", "RT": "Right", "T": "Start", "S": "Select"},
    "GBA": {"U": "Up", "D": "Down", "LT": "Left", "RT": "Right", "T": "Start", "S": "Select"},
    "GB": dict(BUTTON_ALIASES, T="Start", S="Select"),
    "GBC": dict(BUTTON_ALIASES, T="Start", S="Select"),
    "MD": dict(BUTTON_ALIASES, T="Start", M="Mode"),
    "PCE": dict(BUTTON_ALIASES, Start="Run", B="II", A="I"),
    "PS1": {"U": "Up", "D": "Down", "L": "Left", "R": "Right", "X": "Cross",
            "O": "Circle", "Sq": "Square", "Tr": "Triangle", "A": "Circle",
            "B": "Cross", "Y": "Square"},
    "PSP": {"U": "Up", "D": "Down", "LT": "Left", "RT": "Right"},
    "ARCADE_FBNEO": dict(BUTTON_ALIASES),
    "ARCADE_MAME": dict(BUTTON_ALIASES),
}


def buttons_for(platform="NES"):
    """平台 → 允许的手柄键名。未知平台退回 NES 集合（不静默放宽）。"""
    return PLATFORM_BUTTONS.get(str(platform).upper(), set(KNOWN_BUTTONS))


def button_aliases_for(platform="NES"):
    return PLATFORM_ALIASES.get(str(platform).upper(), BUTTON_ALIASES)


def _clean_token(s, what):
    if not isinstance(s, str) or not s or any(c.isspace() for c in s):
        raise SchemaError(f"{what} 须为非空且不含空白的字符串: {s!r}")
    return s


def _domain_arg(s):
    """内存域名 → 线格式安全写法。

    BizHawk 的域名本身可能带空格（如 FBNeo 的 "m68K RAM"、PSX 的 "MainRAM"
    虽不带但同类），而指令行按空格切参。这里把空白编码成 %20，Lua 侧 read8/
    write8/dump 解码还原。不含空白的域名输出完全不变，向后兼容。
    """
    if not isinstance(s, str) or not s.strip():
        raise SchemaError(f"内存域须为非空字符串: {s!r}")
    if "%" in s:
        raise SchemaError(f"内存域不得含 %（与转义符冲突）: {s!r}")
    return re.sub(r"\s", "%20", s.strip())


def _path_arg(p):
    _clean_token(p, "路径")
    try:
        p.encode("ascii")
    except UnicodeEncodeError:
        raise SchemaError("路径须纯 ASCII（中文路径请先落到临时工作目录，Lua io 中文会转码损坏）")
    return p.replace("\\", "/")


def _addr(a, platform="NES"):
    """地址 → 十进制线格式。

    默认 NES 仍严格 0..0xFFFF（自检依赖）；非 NES 平台允许 24/32 位地址，
    并接受知识包里常见的 "0xNNNN" 十六进制字符串。上限按平台放宽，
    但「是否真能读写该内存域」由后端实测决定，不由这里背书。
    """
    if isinstance(a, str):
        s = a.strip()
        if not re.fullmatch(r"0[xX][0-9A-Fa-f]+", s):
            raise SchemaError(f"地址字符串须为 0x 十六进制: {a!r}")
        a = int(s, 16)
    if type(a) is not int:
        raise SchemaError(f"地址须为整数或 0x 十六进制字符串: {a!r}")
    hi = 0xFFFF if str(platform).upper() == "NES" else 0xFFFFFFFF
    if not 0 <= a <= hi:
        raise SchemaError(f"地址越界(0..{hi:#x}): {a!r}")
    return str(a)


def _byte(v):
    if not isinstance(v, int) or not 0 <= v <= 255:
        raise SchemaError(f"字节值须为 0..255 整数: {v!r}")
    return str(v)


def parse_macro(spec, platform="NES"):
    """宏谱 → 规范线格式。逗号分帧、+ 分同帧按键、空帧=中立。
    "Start,,A+B" => "Start,,A+B"；别名按平台展开，GBA/SNES 的 R 是肩键。
    同一个记号既是真实键又是别名时（街机 D、PCE A/B），和弦含其它真实键就按真实键解释。
    """
    _clean_token(spec, "宏谱")
    allowed = buttons_for(platform)
    aliases = button_aliases_for(platform)
    out = []
    for tok in spec.split(","):
        if tok == "":
            out.append("")
            continue
        parts = tok.split("+")
        button_context = any(b in allowed and b not in aliases for b in parts)
        names = []
        for b in parts:
            if not (button_context and b in allowed and b in aliases):
                b = aliases.get(b, b)
            if b not in allowed:
                raise SchemaError(
                    f"未知按键: {b!r}（platform={platform} 允许 {sorted(allowed)} 及别名 {aliases}）")
            names.append(b)
        out.append("+".join(names))
    return ",".join(out)


def _v_profile(kw):
    return [_path_arg(kw["state"]), _path_arg(kw["roundtrip"])]


def _v_save(kw):
    return [_path_arg(kw["path"])]


def _v_seed_ram(kw):
    args = [_path_arg(kw["path"]), _domain_arg(kw["domain"]), _path_arg(kw["state"])]
    if kw.get("addr", 0):
        args.append(str(kw["addr"]))
    return args


def _v_load(kw):
    a = [_path_arg(kw["path"])]
    if kw.get("shot"):
        a.append(_path_arg(kw["shot"]))
    return a


def _v_read(kw):
    a = [_addr(kw["addr"], kw.get("platform", "NES"))]
    if kw.get("domain"):
        a.append(_domain_arg(kw["domain"]))
    return a


def _v_write(kw):
    a = [_addr(kw["addr"], kw.get("platform", "NES")), _byte(kw["value"])]
    if kw.get("domain"):
        a.append(_domain_arg(kw["domain"]))
    return a


def _v_ramtest(kw):
    a = [_addr(kw["addr"], kw.get("platform", "NES"))]
    if kw.get("domain"):
        a.append(_domain_arg(kw["domain"]))
    return a


def _v_run(kw):
    n = kw["frames"]
    if not isinstance(n, int) or n < 1:
        raise SchemaError(f"run 帧数须为正整数: {n!r}")
    a = [str(n)]
    if kw.get("shot"):
        a.append(_path_arg(kw["shot"]))
    return a


def _v_macro(kw):
    a = [parse_macro(kw["spec"], kw.get("platform", "NES"))]
    if kw.get("shot"):
        a.append(_path_arg(kw["shot"]))
    return a


def _v_attempt(kw):
    a = [_path_arg(kw["state"])]
    spec = kw.get("spec") or "-"
    a.append("-" if spec == "-" else parse_macro(spec, kw.get("platform", "NES")))
    extra = kw.get("extra", 0)
    if not isinstance(extra, int) or extra < 0:
        raise SchemaError(f"attempt extra 须为 >=0 整数: {extra!r}")
    a.append(str(extra))
    save = kw.get("save")
    ram = kw.get("ram")
    probe = kw.get("probe")
    bus_probe = kw.get("bus_probe")
    if kw.get("shot") or save or ram or probe is not None or bus_probe is not None:
        # 线格式按位置切参：只给 save/ram/probe 时前面的位补 "-"
        a.append(_path_arg(kw["shot"]) if kw.get("shot") else "-")
    if save or ram or probe is not None or bus_probe is not None:
        a.append(_path_arg(save) if save else "-")
    if ram or probe is not None or bus_probe is not None:
        a.append(_path_arg(ram) if ram else "-")
    if probe is not None:
        a.append(_addr(probe, kw.get("platform", "NES")))
        if kw.get("probe_domain"):
            a.append(_domain_arg(kw["probe_domain"]))
    if bus_probe is not None:
        a.append("-")
        a.append(_addr(bus_probe, kw.get("platform", "NES")))
        if kw.get("bus_scope"):
            a.append(_domain_arg(kw["bus_scope"]))
    if ram:
        while len(a) < 7:
            a.append("-")
        if len(a) == 7:
            a.append(_domain_arg(kw["probe_domain"]) if kw.get("probe_domain") else "-")
        while len(a) < 10:
            a.append("-")
        start = kw.get("ram_start", 0)
        length = kw.get("ram_length", 2048)
        _addr(start, kw.get("platform", "NES"))
        if not isinstance(length, int) or not 1 <= length <= 0x10000:
            raise SchemaError(f"attempt ram_length 须为 1..0x10000 整数: {length!r}")
        a.extend((str(start), str(length)))
    patches = kw.get("patches") or []
    if patches:
        if _patch_mode(patches) != "one_shot":
            raise SchemaError("attempt 只允许一次性补丁")
        while len(a) < 12:
            a.append("-")
        a.append(_format_patches(patches, kw.get("platform", "NES")))
    return a


def _v_ramdump(kw):
    a = [_path_arg(kw["path"])]
    n = kw.get("length", 2048)
    if not isinstance(n, int) or not 1 <= n <= 0x10000:
        raise SchemaError(f"ramdump 长度须为 1..0x10000 整数: {n!r}")
    start = kw.get("start", 0)
    _addr(start, kw.get("platform", "NES"))
    a.append(str(n))
    a.append(str(start))
    if kw.get("domain"):
        a.append(_domain_arg(kw["domain"]))
    return a


def _tasklist_emuhawk_processes():
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, errors="replace",
                             timeout=10).stdout or ""
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        cols = line.split('","')
        if len(cols) < 2 or not cols[0].strip('"').lower().startswith("emuhawk"):
            continue
        try:
            rows.append({"pid": int(cols[1]), "name": cols[0].strip('"'), "exe": None})
        except ValueError:
            continue
    return rows


def _single_instance_mode(exe):
    if not exe:
        return None
    try:
        cfg = json.loads((Path(exe).parent / "config.ini").read_text(encoding="utf-8-sig"))
        value = cfg.get("SingleInstanceMode", True)
        return value if isinstance(value, bool) else None
    except (OSError, ValueError, AttributeError):
        return None


def emuhawk_processes():
    """活着的 EmuHawk 进程及可执行路径；路径量不到时显式留 None。"""
    try:
        import psutil
    except ImportError:
        return _tasklist_emuhawk_processes()
    try:
        rows = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            info = proc.info
            if not str(info.get("name") or "").lower().startswith("emuhawk"):
                continue
            rows.append({"pid": int(info["pid"]), "name": info.get("name"),
                         "exe": info.get("exe"),
                         "single_instance": _single_instance_mode(info.get("exe"))})
        return rows
    except Exception:
        return _tasklist_emuhawk_processes()


def _same_installation(exe, bizhawk):
    if not exe:
        return False
    try:
        return (os.path.normcase(os.path.realpath(os.path.dirname(exe))) ==
                os.path.normcase(os.path.realpath(bizhawk)))
    except OSError:
        return False


def emuhawk_pids(install_dir=None):
    """点名 EmuHawk；给 install_dir 时只拦同一安装目录。

    路径量不到的进程按同安装保守拦截，避免 psutil 缺权限时把真正的单实例冲突放过去。
    """
    rows = emuhawk_processes()
    if install_dir is None:
        return [r["pid"] for r in rows]
    return [r["pid"] for r in rows
            if not r.get("exe") or r.get("single_instance") is not False
            or _same_installation(r["exe"], install_dir)]


@contextlib.contextmanager
def installation_lock(bizhawk):
    """跨进程锁住一个 BizHawk 安装目录；不同副本可同时运行。"""
    key = hashlib.sha256(os.path.normcase(os.path.realpath(bizhawk)).encode("utf-8")).hexdigest()
    lock_dir = Path(Path(bizhawk).resolve().anchor) / "taspipe_scratch" / "emulator_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / (key + ".lock")
    with open(path, "a+b") as fh:
        if fh.seek(0, os.SEEK_END) == 0:
            fh.write(b"\0")
            fh.flush()
        fh.seek(0)
        if os.name == "nt":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError as exc:
                    if exc.winerror not in (errno.EACCES, errno.EDEADLK, 33):
                        raise
                    time.sleep(0.1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _patch_mode(patches):
    modes = set()
    for patch in patches:
        if not isinstance(patch, dict):
            raise SchemaError("dump patches 每项须为 {addr,value,domain?}")
        apply = patch.get("apply", "one_shot")
        if apply in ("one_shot", "one_shot_candidate"):
            modes.add("one_shot")
        elif apply == "per_frame":
            modes.add("per_frame")
        else:
            raise SchemaError(f"未知 patch apply 语义: {apply!r}")
    if len(modes) > 1:
        raise SchemaError("一次性补丁与逐帧补丁不能混在同一次 dump")
    return next(iter(modes), "one_shot")


def _format_patches(patches, platform="NES"):
    _patch_mode(patches)
    toks = []
    for patch in patches:
        tok = f"{_addr(patch.get('addr'), platform)}:{_byte(patch.get('value'))}"
        if patch.get("domain"):
            tok += "@" + _domain_arg(patch["domain"])
        toks.append(tok)
    return ";".join(toks) or "-"


def _v_dump(kw):
    a = [_path_arg(kw["frames_dir"])]
    platform = kw.get("platform", "NES")
    spec = kw.get("spec") or "-"
    a.append("-" if spec == "-" else parse_macro(spec, platform))
    extra = kw.get("extra", 0)
    if not isinstance(extra, int) or extra < 0:
        raise SchemaError(f"dump extra 须为 >=0 整数: {extra!r}")
    a.append(str(extra))
    state = kw.get("state")
    patches = kw.get("patches") or []
    if state or patches:
        a.append(_path_arg(state) if state else "-")
        a.append(_format_patches(patches, platform))
        if _patch_mode(patches) == "per_frame":
            a.append("per_frame")
    return a


_OPS = {
    "ping": lambda kw: [], "quit": lambda kw: [], "stop_movie": lambda kw: [],
    "domains": lambda kw: [], "businfo": lambda kw: [], "gameinfo": lambda kw: [], "profile": _v_profile,
    "save": _v_save, "seed_ram": _v_seed_ram, "load": _v_load, "shot": _v_save,
    "read": _v_read, "write": _v_write,
    "ramtest": _v_ramtest,
    "run": _v_run, "macro": _v_macro, "attempt": _v_attempt,
    "ramdump": _v_ramdump, "dump": _v_dump,
}


def format_command(cid, op, **kw):
    """指令 → 单行线格式（"id op args..."）。非法 op/参数在此拦下，不进模拟器。"""
    if not isinstance(cid, int) or cid < 1:
        raise SchemaError(f"指令 id 须为正整数: {cid!r}")
    if op not in _OPS:
        raise SchemaError(f"未知 op: {op!r}（允许 {sorted(_OPS)}）")
    return " ".join([str(cid), op] + _OPS[op](kw))


def parse_response(line):
    """resp.txt 单行 → {id, ok, data}。格式非法抛 SchemaError（不静默当成功）。"""
    parts = line.split(" ", 2)
    if len(parts) < 2 or parts[1] not in ("ok", "err"):
        raise SchemaError(f"响应格式非法: {line!r}")
    try:
        cid = int(parts[0])
    except ValueError:
        raise SchemaError(f"响应 id 非整数: {line!r}")
    return {"id": cid, "ok": parts[1] == "ok",
            "data": parts[2] if len(parts) > 2 else ""}


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


GBA_MGBA_SHOULDER_DIRECT_SHA1 = "DC128F51BE49A4FAB085C1FE940DF725B1B90163"
GBA_MGBA_CORE_TYPE = "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk"


def gba_mgba_calibration(bizhawk):
    dll = Path(bizhawk) / "dll" / "mgba.dll"
    if not dll.is_file():
        raise SchemaError(f"GBA mGBA 原生库缺失: {dll}")
    digest = sha1_file(dll)
    allowed = digest == GBA_MGBA_SHOULDER_DIRECT_SHA1
    return {
        "binary_sha1": digest,
        "shoulder_mapping": "direct" if allowed else "uncalibrated",
        "status": "calibrated_direct" if allowed else "uncalibrated",
        "shoulder_input": "allowed" if allowed else "blocked",
    }


def check_shoulder_calibration(platform, spec, calibration):
    if (str(platform).upper() != "GBA" or spec in (None, "-")
            or calibration.get("shoulder_input") == "allowed"):
        return
    for tok in parse_macro(spec, platform).split(","):
        if any(name in ("L", "R") for name in tok.split("+")):
            raise SchemaError("GBA 肩键尚未按当前 mgba.dll 哈希校准，拒绝发送可能反置的 L/R 输入")


def saved_core_type(path):
    import zipfile

    try:
        with zipfile.ZipFile(path) as z:
            obj = json.loads(z.read("SyncSettings.json"))["o"]["$type"]
        return obj.split("+SyncSettings", 1)[0]
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


STATE_CONTENT_PROBES = {
    "px": 0x0480,
    "scr": 0x001B,
    "cur": 0x005F,
    "owned": 0x005D,
    "hp": 0x006B,
}

STATE_CONTENT_PROFILES = {
    "2F88381557339A14C20428455F6991C1EB902C99": {
        "1fcb3e7ccb8844c0d05a7569da9a0af293356b2aded5f9b8ae52eb13f63fef46": {
            "expected": {"px": 128, "scr": 0, "cur": 0, "owned": 0, "hp": 28},
            "source": "t34j base 双会话 + 11-24 零帧截图",
        },
        "9b886af5e4afc4cba6774aa2b474d51c572d3fbeee9f952b5e2e126ce321fe32": {
            "expected": {"px": 140, "scr": 23, "cur": 0, "owned": 128, "hp": 28},
            "source": "t56 guts.state 11-24 生产采样+走廊截图",
        },
        "e90b8b5f81032e0ec90cdd8ee56bd0415092b188f58d1a1d55138240ac3e1058": {
            "expected": {"px": 59, "scr": 19, "cur": 2, "owned": 148, "hp": 28},
            "source": "t62 fireman.state 11-24 生产采样+Boss房截图",
        },
        "e9a0041d5714c2bfbb6de228d16a8eb7f41a23a3b04b1aba02089a3ea7d2c201": {
            "expected": {"px": 140, "scr": 47, "cur": 6, "owned": 254, "hp": 28},
            "source": "t48 water_fx.state 11-24 生产采样+水下房截图",
        },
        "f417525308f2a71fbbf2984f814101863556389520970b1af4315c1f4a5fb72d": {
            "expected": {"px": 156, "scr": 47, "cur": 6, "owned": 254, "hp": 28},
            "source": "t41 carry2.state 11-24 生产采样+水下持块截图",
        },
        "da5d4af1049d2013e4d2dfc4e87ebbeea95e6ecdd14eeef1b6c4d03b4134c182": {
            "expected": {"px": 144, "scr": 47, "cur": 6, "owned": 254, "hp": 28},
            "source": "base_wily_grab.state 11-24 生产采样+水下平台截图",
        },
    },
}


def state_content_profile(rom_sha1, state_sha256):
    return STATE_CONTENT_PROFILES.get(str(rom_sha1).upper(), {}).get(state_sha256)


class StateProfileMismatch(RuntimeError):
    """P1 拓扑/内容闸门：零帧加载→回存不一致、内容指纹不符或加载失败。"""

    def __init__(self, report):
        self.report = report
        super().__init__(report.get("reason") or "state profile mismatch")


def compare_state_core(orig_path, roundtrip_path):
    """比对两份 .state 的 Core.bin（含 Core.bin.zst）序列化内容与 BizVersion 身份。

    控制器拓扑/核心身份差异必落在 Core.bin；只读比对，不改任何存档字节。
    """
    import zipfile

    def member(path, name):
        try:
            with zipfile.ZipFile(path) as z:
                try:
                    return z.read(name)
                except KeyError:
                    return None
        except (zipfile.BadZipFile, OSError):
            return None

    a, b = member(orig_path, "Core.bin"), member(roundtrip_path, "Core.bin")
    core_member = "Core.bin"
    if a is None and b is None:
        a, b = member(orig_path, "Core.bin.zst"), member(roundtrip_path, "Core.bin.zst")
        core_member = "Core.bin.zst"
    va, vb = member(orig_path, "BizVersion.txt"), member(roundtrip_path, "BizVersion.txt")
    fa, fb = member(orig_path, "Framebuffer.bmp"), member(roundtrip_path, "Framebuffer.bmp")
    sa, sb = member(orig_path, "SyncSettings.json"), member(roundtrip_path, "SyncSettings.json")
    first = None
    if a is not None and b is not None:
        n = min(len(a), len(b))
        first = next((i for i in range(n) if a[i] != b[i]), None)
        if first is None and len(a) != len(b):
            first = n
    rep = {
        "match": a is not None and b is not None and a == b,
        "core_member": core_member,
        "core_encoding": "zstd" if core_member.endswith(".zst") else "raw",
        "comparison": "serialized_core_bytes",
        "core_bytes_orig": None if a is None else len(a),
        "core_bytes_roundtrip": None if b is None else len(b),
        "first_diff_offset": first,
        "bizversion_orig": None if va is None else va.decode("utf-8", "replace").strip(),
        "bizversion_roundtrip": None if vb is None else vb.decode("utf-8", "replace").strip(),
        "core_identity_match": va is not None and va == vb,
        "framebuffer_match": fa is not None and fb is not None and fa == fb,
        "sync_settings_match": sa is not None and sb is not None and sa == sb,
    }
    if not rep["match"]:
        rep["reason"] = (
            f"{core_member} 缺失或不可读（原/回存）" if a is None or b is None
            else f"{core_member} 序列化字节不一致（首差异偏移 {first}，"
                 f"{rep['core_bytes_orig']}→{rep['core_bytes_roundtrip']} 字节）")
    return rep


def read_sync_controls(bizhawk_dir, core_key="BizHawk.Emulation.Cores.Nintendo.NES.NES"):
    """读 config.ini CoreSyncSettings 的 Controls 子节（拓扑闸门诊断证据）。"""
    try:
        conf = json.loads((Path(bizhawk_dir) / "config.ini").read_text(encoding="utf-8"))
        return conf.get("CoreSyncSettings", {}).get(core_key, {}).get("Controls")
    except (OSError, ValueError, AttributeError):
        return None


class _Guard(threading.Thread):
    """非阻塞看门狗：心跳停滞先点框（PID 精确），再停滞就树杀并标 dead。"""

    def __init__(self, proc, work, stall_timeout=45.0):
        super().__init__(daemon=True)
        self.proc = proc
        self.work = work
        self.stall_timeout = stall_timeout
        self.started_at = time.monotonic()
        self.stop_event = threading.Event()
        self.dead = False
        self.dismissed = 0

    def run(self):
        hb = watchdog.heartbeat_path(self.work)
        last_progress = time.time()
        last_mt = 0.0
        while not self.stop_event.is_set():
            if self.proc.poll() is not None:
                self.dead = True
                return
            try:
                mt = os.path.getmtime(hb)
            except OSError:
                mt = 0.0
            now = time.time()
            if mt > last_mt + 1e-6:
                last_mt = mt
                last_progress = now
            if mt == 0.0 and now - self.started_at <= 30:
                watchdog.dismiss_bizhawk_dialog(
                    self.proc.pid, titles=watchdog.STARTUP_DIALOG_TITLES)
            if now - last_progress > 5.0:
                self.dismissed += watchdog.dismiss_bizhawk_dialog(self.proc.pid)
            if now - last_progress > self.stall_timeout:
                watchdog.tree_kill(self.proc.pid)
                self.dead = True
                return
            self.stop_event.wait(0.5)


class StateSession:
    """持久 EmuHawk 状态会话。with 语法保证退出（quit → 等退出 → 树杀兜底）。

    所有截图/存档路径落在 ASCII 临时工作目录（Lua io 中文转码坑，沿用 tas_replay
    口径）；要长期保存由调用方 shutil 拷出。command 单飞（锁），id 单调递增。
    """

    def __init__(self, rom, bizhawk, core="NesHawk", system="NES", movie=None,
                 work=None, speed=400, joypad_port=1):
        self.rom = os.path.abspath(str(rom))
        self.bizhawk = os.path.abspath(str(bizhawk))
        self.core = core
        self.system = system
        self.platform = system
        if self.platform.upper() == "GBA":
            if str(core).lower() != "mgba":
                raise SchemaError("GBA 生产会话只准入已实测的 mGBA；拒绝不可用核心静默回退")
            self.input_calibration = gba_mgba_calibration(self.bizhawk)
        else:
            self.input_calibration = {"status": "not_applicable", "shoulder_mapping": "not_applicable"}
        if not isinstance(joypad_port, int) or not 0 <= joypad_port <= 4:
            raise SchemaError(f"joypad_port 须为 0..4 整数: {joypad_port!r}")
        self.joypad_port = joypad_port
        self.movie = os.path.abspath(str(movie)) if movie else None
        if self.movie:
            # 槽位闸门与回放侧同源：SNES 电影带着 NES 槽位起会话，症状是 0 帧卡死，不像配置错
            from .record import slot_conflict
            conf = slot_conflict(self.movie, system)
            if conf:
                raise SchemaError(conf)
        # Lua 的 io.open 按 EmuHawk 进程 cwd 解析相对路径 ⇒ 相对 work 会让 logf=nil 启动即崩（11-14 实测）。
        self.work = os.path.abspath(str(work or tempfile.mkdtemp(prefix="tas_state_")))
        self.speed = int(speed)
        self._proc = None
        self._guard = None
        self._lock = threading.Lock()
        self._install_lock = None
        self._cid = 0
        self._domain_sizes = None
        self._current_domain_name = None

    def start(self, boot_timeout=60.0):
        lock = installation_lock(self.bizhawk)
        lock.__enter__()
        self._install_lock = lock
        try:
            return self._start_unlocked(boot_timeout=boot_timeout)
        except BaseException:
            self.close()
            raise

    def _release_install_lock(self):
        lock, self._install_lock = self._install_lock, None
        if lock is not None:
            lock.__exit__(None, None, None)

    def _start_unlocked(self, boot_timeout=60.0):
        import tas_replay
        from .schema import SchemaError
        os.makedirs(self.work, exist_ok=True)
        hb0 = watchdog.heartbeat_path(self.work)
        # 上一轮崩在 Python 侧会留下活的 EmuHawk 和旧心跳；旧心跳一存在，下面的
        # 「看见心跳就算起来了」会立刻假绿灯，第一条指令再超时（11-14 连踩三次）。
        if os.path.isfile(hb0):
            m0 = os.path.getmtime(hb0)
            time.sleep(0.6)
            if os.path.getmtime(hb0) > m0:
                raise RuntimeError(
                    f"工作目录 {self.work} 上有活着的会话在写心跳，"
                    "先结束它（残留 EmuHawk）再重开，否则两个进程抢同一条 cmd/resp 通道")
        for stale in (hb0, os.path.join(self.work, "cmd.txt"),
                      os.path.join(self.work, "cmd.txt.tmp"), os.path.join(self.work, "resp.txt")):
            try:
                os.remove(stale)
            except OSError:
                pass
        # 锁按安装目录排他；不同 BizHawk 副本可并行，同一副本必须等前一会话退出。
        live = emuhawk_pids(self.bizhawk)
        if live:
            raise RuntimeError(
                "BizHawk 单实例冲突：已有 EmuHawk PID=%s（同安装，或对方仍开启 SingleInstanceMode）；"
                "先结束它，或确认所有并发副本都关闭单实例模式" %
                (",".join(str(p) for p in live)))
        r = os.path.join(self.work, "rom" + os.path.splitext(self.rom)[1])
        shutil.copyfile(self.rom, r)
        tas_replay.force_core(self.bizhawk, self.system, self.core)
        lua = os.path.join(self.work, "session.lua")
        buttons = ",".join(f'["{name}"]=true' for name in sorted(buttons_for(self.platform)))
        body = (tas_replay.STATE_LUA_TMPL
                .replace("__DIR__", self.work.replace("\\", "/"))
                .replace("__SPEED__", str(self.speed))
                .replace("__BUTTONS__", buttons)
                .replace("__PORT__", str(self.joypad_port))
                .replace("__BUSPROBE_START__", "local bus_addr = p[11] and p[11] ~= \"-\" and tonumber(p[11]) or nil\n\t\t\tbus_probe = bus_addr and start_bus_probe(bus_addr, bus_scope) or nil"))
        if "__BUSPROBE_START__" in body or "__SWAP_SHOULDERS__" in body:
            raise SchemaError("Lua 模板占位符未替换")
        with open(lua, "w", encoding="utf-8") as f:
            f.write(body)
        cmd = [os.path.join(self.bizhawk, "EmuHawk.exe"), "--chromeless"]
        if self.movie:
            m = os.path.join(self.work, "movie.bk2")
            tas_replay.materialize_movie(self.movie, m)
            cmd.append(f"--movie={m}")
        cmd += [f"--lua={lua}", r]
        emulator_log = os.path.join(self.work, "emulator.log")
        with open(emulator_log, "wb") as log_fh:
            self._proc = subprocess.Popen(cmd, cwd=self.bizhawk, stdout=log_fh,
                                          stderr=subprocess.STDOUT)
        self._guard = _Guard(self._proc, self.work)
        self._guard.start()
        deadline = time.time() + boot_timeout
        hb = watchdog.heartbeat_path(self.work)
        while time.time() < deadline:
            if self._guard.dead:
                raise RuntimeError("EmuHawk 启动失败（看门狗标 dead，见 session.log/heartbeat）")
            if os.path.isfile(hb):
                return self
            time.sleep(0.2)
        self.close()
        raise TimeoutError(f"EmuHawk {boot_timeout}s 未写出心跳（启动卡死）")

    def _send(self, line):
        tmp = os.path.join(self.work, "cmd.txt.tmp")
        # newline="" 钉死 LF：Windows 文本模式会把 \n 翻成 \r\n，Lua 按空格切词
        # 会把 "ping\r" 当成未知 op（11-10 实测）。自检有字节级闸门。
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(line + "\n")
        dst = os.path.join(self.work, "cmd.txt")
        for i in range(50):
            try:
                os.replace(tmp, dst)
                return
            except PermissionError:
                time.sleep(0.02)          # Lua 正持 cmd.txt 的极窄窗口，重试
        raise TimeoutError("cmd.txt 替换持续失败（Lua 侧文件锁异常）")

    def _wait_resp(self, cid, timeout):
        resp = os.path.join(self.work, "resp.txt")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._guard.dead or self._proc.poll() is not None:
                raise RuntimeError(f"会话已死（指令 {cid} 无响应；看 session.log）")
            try:
                with open(resp, encoding="utf-8") as f:
                    line = f.read()
            except OSError:
                line = ""
            if line.endswith("\n"):
                r = parse_response(line.strip())
                if r["id"] == cid:
                    try:
                        os.remove(resp)
                    except OSError:
                        pass
                    if not r["ok"]:
                        raise RuntimeError(f"Lua 拒绝指令 {cid}: {r['data']}")
                    return r
            time.sleep(0.02)
        raise TimeoutError(f"指令 {cid} 超时 {timeout}s 无响应")

    def command(self, op, timeout=None, **kw):
        if self._proc is None:
            raise RuntimeError("会话未 start")
        with self._lock:
            if self._guard.dead or self._proc.poll() is not None:
                raise RuntimeError("会话已死（看门狗树杀或进程退出）")
            kw.setdefault("platform", getattr(self, "platform", self.system))
            if op in ("macro", "attempt", "dump"):
                check_shoulder_calibration(kw["platform"], kw.get("spec"), self.input_calibration)
            self._cid += 1
            line = format_command(self._cid, op, **kw)
            if timeout is None:
                n = kw.get("frames", 0)
                if op == "macro":
                    n = len(parse_macro(kw["spec"], kw["platform"]).split(","))
                elif op == "attempt":
                    spec = kw.get("spec") or "-"
                    n = (0 if spec == "-" else len(parse_macro(spec, kw["platform"]).split(","))) + kw.get("extra", 0)
                elif op == "dump":
                    spec = kw.get("spec") or "-"
                    n = (0 if spec == "-" else len(parse_macro(spec, kw["platform"]).split(","))) + kw.get("extra", 0)
                timeout = max(30.0, n / 30.0 + 10.0)
            self._send(line)
            return self._wait_resp(self._cid, timeout)

    # ---- 便捷封装（路径一律相对 work，纯 ASCII）----
    def _wpath(self, name, ext):
        _clean_token(name, "名字")
        return os.path.join(self.work, name + ext).replace("\\", "/")

    def ping(self):
        d = self.command("ping")["data"].split()
        return int(d[0]), d[1]

    def _verify_saved_core(self, path):
        if self.platform.upper() == "GBA" and saved_core_type(path) != GBA_MGBA_CORE_TYPE:
            raise RuntimeError(f"GBA 存档核心身份不符，拒绝静默回退: {saved_core_type(path)!r}")
        return path

    def save(self, name):
        p = self._wpath(name, ".state")
        self.command("save", path=p)
        return self._verify_saved_core(p)

    def load(self, path, shot=None):
        kw = {"path": path}
        if shot:
            kw["shot"] = shot
        return self.command("load", **kw)

    def shot(self, name):
        p = self._wpath(name, ".png")
        self.command("shot", path=p)
        return p

    def game_name(self):
        name = self.command("gameinfo")["data"]
        if not name or any(ord(ch) < 32 for ch in name):
            raise RuntimeError("模拟器未返回合法游戏名")
        return name

    def read(self, addr, domain=None):
        _addr(addr, self.platform)
        self._check_domain_range(addr, 1, domain)
        return int(self.command("read", addr=addr, domain=domain)["data"])

    def write(self, addr, value, domain=None):
        _addr(addr, self.platform)
        _byte(value)
        self._check_domain_range(addr, 1, domain)
        self.command("write", addr=addr, value=value, domain=domain)
        if self.read(addr, domain=domain) != value:
            raise RuntimeError(f"内存写入未生效: {addr:#x}={value} domain={domain or 'current'}")

    def seed_ram(self, data, domain, name="seed", addr=0):
        if not isinstance(data, bytes) or not data:
            raise SchemaError("seed_ram data 须为非空 bytes")
        if not isinstance(domain, str) or not domain:
            raise SchemaError("seed_ram domain 须为非空内存域名")
        _addr(addr, self.platform)
        self._check_domain_range(addr, len(data), domain)
        src = self._wpath(name + "_seed", ".bin")
        dst = self._wpath(name, ".state")
        with open(src, "wb") as f:
            f.write(data)
        response = self.command("seed_ram", path=src, domain=domain, state=dst, addr=addr)
        self._verify_saved_core(dst)
        return dst, response["data"]

    def ramtest(self, addr, domain=None):
        _addr(addr, self.platform)
        self._check_domain_range(addr, 1, domain)
        o, v = self.command("ramtest", addr=addr, domain=domain)["data"].split()
        o, v = int(o), int(v)
        if v == o:
            raise RuntimeError(f"内存域写入未生效: {addr:#x} domain={domain or 'current'}")
        return o, v

    def domains(self):
        if self._domain_sizes is None:
            rows = []
            for token in self.command("domains")["data"].split("|"):
                current = token.endswith("*")
                name, size = (token[:-1] if current else token).rsplit(":", 1)
                rows.append({"name": name, "size": int(size), "current": current})
                if current:
                    self._current_domain_name = name
            self._domain_sizes = {row["name"]: row["size"] for row in rows}
        return [{"name": name, "size": size, "current": name == self._current_domain_name}
                for name, size in self._domain_sizes.items()]

    def current_domain(self):
        if self._domain_sizes is None:
            self.domains()
        if self._current_domain_name is None:
            raise RuntimeError("模拟器未报告当前内存域")
        return {"name": self._current_domain_name,
                "size": self._domain_sizes[self._current_domain_name], "current": True}

    def _check_domain_range(self, addr, length, domain=None):
        if self._domain_sizes is None:
            self.domains()
        name = domain or self.current_domain()["name"]
        size = self._domain_sizes.get(name)
        if size is None:
            raise SchemaError(f"内存域不存在: {name}")
        if not 0 <= addr or addr + length > size:
            raise SchemaError(f"地址越界: domain={name} addr={addr:#x} length={length} size={size:#x}")

    def run(self, frames, shot=None):
        kw = {"frames": frames}
        if shot:
            kw["shot"] = shot
        return self.command("run", **kw)

    def macro(self, spec, shot=None):
        kw = {"spec": spec}
        if shot:
            kw["shot"] = shot
        return self.command("macro", **kw)

    def use_state(self, path, name=None):
        """把资产仓里的存档搬进 ASCII 工作目录并返回可用路径。

        状态资产按计划书落在 04-游戏资源库/…（中文路径），而 Lua 的 io 遇到中文路径会
        转码损坏，所以任何生产消费方都必须先经这一步。
        """
        src = Path(str(path))
        if not src.is_file():
            raise SchemaError(f"存档不存在: {src}")
        name = name or re.sub(r"[^A-Za-z0-9_.-]", "_", src.stem)[:40] or "state"
        dst = Path(self.work) / f"{name}.state"
        if not (dst.is_file() and
                hashlib.sha256(dst.read_bytes()).hexdigest() ==
                hashlib.sha256(src.read_bytes()).hexdigest()):
            shutil.copyfile(str(src), str(dst))
        return str(dst).replace("\\", "/")

    def check_state_profile(self, state_path, name="profile_check"):
        """零帧加载→回存核对；已建档游戏再断言五键内容指纹。"""
        src = self.use_state(state_path, name=name + "_src")
        rt = self._wpath(name + "_roundtrip", ".state")
        if self.platform == "GBA":
            data = self.command("profile", state=src, roundtrip=rt)["data"]
            before, after = data.split("~", 1)
            rep = compare_state_core(src, rt)
            self._verify_saved_core(rt)
            rep["memory_fingerprint_before"] = before
            rep["memory_fingerprint_after"] = after
            rep["memory_fingerprint_match"] = before == after
            rep["match_basis"] = "memory_domains+framebuffer+sync_settings+bizversion"
            rep["match"] = (before == after and rep["framebuffer_match"]
                            and rep["sync_settings_match"] and rep["core_identity_match"])
            if rep["match"]:
                rep.pop("reason", None)
            else:
                rep["reason"] = (
                    "GBA 状态语义不一致: "
                    f"memory={rep['memory_fingerprint_match']} "
                    f"framebuffer={rep['framebuffer_match']} "
                    f"sync={rep['sync_settings_match']} "
                    f"version={rep['core_identity_match']}")
        else:
            self.command("attempt", state=src, spec="-", extra=0, save=rt)
            rep = compare_state_core(src, rt)

        rom_sha1 = getattr(self, "_rom_sha1", None)
        if rom_sha1 is None:
            rom_sha1 = sha1_file(self.rom)
            self._rom_sha1 = rom_sha1
        content = {"axis": "unprofiled_game", "checked": False, "match": None,
                   "probes": dict(STATE_CONTENT_PROBES), "rom_sha1": rom_sha1}
        if rom_sha1 in STATE_CONTENT_PROFILES:
            state_sha256 = hashlib.sha256(Path(state_path).read_bytes()).hexdigest()
            content_sha256 = state_registry.state_content_fingerprint(state_path)["content_sha256"]
            profile = state_content_profile(rom_sha1, content_sha256)
            actual = {key: self.read(addr) for key, addr in STATE_CONTENT_PROBES.items()}
            content.update(axis="state_fingerprint", checked=True,
                           state_sha256=state_sha256, content_sha256=content_sha256,
                           actual=actual,
                           expected=profile["expected"] if profile else None,
                           profile_source=profile["source"] if profile else None,
                           match=actual == profile["expected"] if profile else False)
            if profile is None:
                content["axis"] = "unprofiled_state"
                rep["match"] = False
                reasons = [rep["reason"]] if rep.get("reason") else []
                reasons.append("已建档游戏出现未登记内容指纹的状态；拒绝静默放行")
                rep["reason"] = "；".join(reasons)
            elif not content["match"]:
                rep["match"] = False
                diff = {key: {"expected": profile["expected"][key], "actual": actual[key]}
                        for key in STATE_CONTENT_PROBES if actual[key] != profile["expected"][key]}
                content["diff"] = diff
                reasons = [rep["reason"]] if rep.get("reason") else []
                reasons.append(f"状态内容指纹不符: {diff}")
                rep["reason"] = "；".join(reasons)
            if content["match"] and rep["match"]:
                rep["match_basis"] = "serialized_core_bytes+state_content_fingerprint"
        rep["content_fingerprint"] = content
        rep["state_path"] = str(state_path)
        rep["roundtrip_path"] = rt
        return rep

    def attempt(self, state, spec=None, extra=0, shot=None, save=None, ram=None,
                probe=None, probe_domain=None, bus_probe=None, bus_scope=None,
                ram_start=None, ram_length=None, patches=None):
        """原子执行 load+宏+空档，并可选存状态、RAM、截图或采样输入寄存器。

        probe 在收尾读一字节；bus_probe 监听推进期间的总线读写，返回
        ``帧号~读取值~读取次数~写入值~写入次数``，用于区分核心是否真的收到按键。
        """
        kw = {"state": state, "spec": spec or "-", "extra": extra}
        if ram:
            start = 0 if ram_start is None else ram_start
            length = 2048 if ram_length is None else ram_length
            _addr(start, self.platform)
            self._check_domain_range(int(start), length, probe_domain)
            kw.update(ram_start=start, ram_length=length)
        if shot:
            kw["shot"] = shot
        if save:
            kw["save"] = save
        if ram:
            kw["ram"] = ram
            if probe_domain:
                kw["probe_domain"] = probe_domain
        if probe is not None:
            _addr(probe, self.platform)
            self._check_domain_range(probe, 1, probe_domain)
            kw["probe"] = probe
            if probe_domain:
                kw["probe_domain"] = probe_domain
        if bus_probe is not None:
            _addr(bus_probe, self.platform)
            kw["bus_probe"] = bus_probe
            if bus_scope:
                kw["bus_scope"] = bus_scope
        if patches:
            if _patch_mode(patches) != "one_shot":
                raise SchemaError("attempt 只允许一次性补丁")
            for patch in patches:
                addr = _addr(patch["addr"], self.platform)
                _byte(patch["value"])
                self._check_domain_range(int(addr), 1, patch.get("domain"))
            kw["patches"] = patches
        result = self.command("attempt", **kw)
        if save:
            self._verify_saved_core(save)
        return result

    def dump(self, frames_dir, spec=None, extra=0, state=None, patches=None):
        """从可选快照/RAM 前置态连续逐帧截图，返回实际采集帧数（非模拟器绝对帧号）。"""
        os.makedirs(frames_dir, exist_ok=True)
        for patch in patches or []:
            addr = _addr(patch["addr"], self.platform)
            _byte(patch["value"])
            self._check_domain_range(int(addr), 1, patch.get("domain"))
        return int(self.command("dump", frames_dir=frames_dir,
                                spec=spec or "-", extra=extra,
                                state=state, patches=patches or [])["data"])

    def ramdump(self, path, length=2048, domain=None, start=0):
        """把指定内存域 start..start+length-1 原始字节落盘。返回字节数。"""
        if not isinstance(length, int) or not 1 <= length <= 0x10000:
            raise SchemaError(f"ramdump 长度须为 1..0x10000 整数: {length!r}")
        _addr(start, self.platform)
        self._check_domain_range(start, length, domain)
        return int(self.command("ramdump", path=path, length=length,
                                domain=domain, start=start)["data"])

    def stop_movie(self):
        return self.command("stop_movie")["data"]

    def close(self):
        if self._proc is None:
            self._release_install_lock()
            return
        try:
            if self._proc.poll() is None and not self._guard.dead:
                try:
                    self.command("quit", timeout=5)
                except (RuntimeError, TimeoutError, ValueError):
                    pass
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                watchdog.tree_kill(self._proc.pid)
        finally:
            if self._guard is not None:
                self._guard.stop_event.set()
                self._guard.join(timeout=3)
            self._release_install_lock()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()


# ------------------------------------------------------------- 实跑验收

def _png_pixels_equal(a, b, ffmpeg="ffmpeg"):
    """PNG 字节不同不等于画面不同（编码器差异）。字节相同直接 True；
    不同则用 ffmpeg 解成原始像素再比，避免把编码差异误报成 desync。
    返回 (是否相等, 说明)。"""
    if sha1_file(a) == sha1_file(b):
        return True, "字节一致"
    try:
        ra = subprocess.run([ffmpeg, "-v", "error", "-i", str(a),
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            capture_output=True, timeout=30)
        rb = subprocess.run([ffmpeg, "-v", "error", "-i", str(b),
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"字节不一致且像素复核不可用: {e}"
    if ra.returncode == 0 and rb.returncode == 0 and ra.stdout and rb.stdout:
        return ra.stdout == rb.stdout, "字节不一致，按原始像素比对"
    return False, "字节不一致且 ffmpeg 解码失败"


def macro_is_effective(neutral_png, macro_png, ffmpeg="ffmpeg"):
    """宏有效 = 同快照同总帧数下，宏画面与中立画面「不同」。
    _png_pixels_equal 返回的是「相等」，故此处取反——11-10 曾误把相等当有效
    （假阳性绿灯），抽成纯函数锁住语义，自检用相同图必判无效钉死它。
    返回 (是否有效, 说明)。"""
    eq, how = _png_pixels_equal(neutral_png, macro_png, ffmpeg)
    return (not eq), how


def verify(rom, bizhawk, out_dir, core="NesHawk", system="NES", movie=None,
           ffmpeg="ffmpeg"):
    """实跑验收：存档/RAM/宏/确定性（同进程+跨进程）。全部产物拷到 out_dir，
    report.json 全 pass 才许 backends.probe 把能力转真（证据门控）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    checks = []

    def add(name, passed, detail, evidence=()):
        checks.append({"name": name, "pass": bool(passed), "detail": detail,
                       "evidence": [str(p) for p in evidence]})

    # 热血足球2 实测：开场信屏有输入锁定期（约前 780 帧任何键无效），
    # 锁定期内「宏无效」是游戏行为不是注入失败。故逐轮 +600 帧找响应态，
    # 每轮先 Start 后全键 mash；4 轮（约 2600 帧）仍无反应才判 FAIL。
    macro_spec = "Start,,,,,,Start,,,,,,"   # 两次 Start 点按（帧数=逗号数+1）
    mash_spec = "A+B+Start+Select,,,,,,A+B+Start+Select,,,,,,"
    kept = {}

    def keep(name, src):
        dst = out_dir / (name + Path(src).suffix)
        shutil.copyfile(src, dst)
        kept[name] = dst
        return dst

    def cap(name, fn, **kw):
        """跑指令并帧精确截图，产物拷到 out_dir。"""
        p = kw.pop("shot")
        fn(shot=p, **kw)
        return keep(name, p)

    with StateSession(rom, bizhawk, core, system, movie=movie) as s:
        frame, mode = s.ping()
        add("boot_ping", True, f"frame={frame} mode={mode}")
        if movie:
            s.run(300)
            s.stop_movie()
        title = cap("title", s.run, frames=180, shot=s._wpath("title", ".png"))
        add("boot_frames", True, "启动后中立跑 180 帧并帧精确截图", [title])

        o, v = s.ramtest(0x0000)
        add("ram_roundtrip", v == (o + 1) % 256,
            f"addr=0x0000 原值={o} 写入={(o + 1) % 256} 读回={v}（同帧原子，已恢复原值）")
        rv = s.read(0x0000)
        add("ram_read", rv == o, f"独立 read 指令读回={rv}（与 ramtest 原值一致）")

        st = s.save("base")
        add("savestate_file", os.path.isfile(st) and os.path.getsize(st) > 0,
            f"快照 {os.path.getsize(st)} 字节")

        neut = mac = None
        responsive = False
        hit_spec = macro_spec
        hit_round = -1
        for round_i in range(4):
            neut = cap("neutral60", s.attempt, state=st, extra=60,
                       shot=s._wpath("neutral60", ".png"))
            for spec in (macro_spec, mash_spec):
                # extra 动态补齐：中立与宏总帧数严格相等（宏帧数=逗号数+1）
                n_mac = len(parse_macro(spec).split(","))
                mac = cap("macro60", s.attempt, state=st, spec=spec, extra=60 - n_mac,
                          shot=s._wpath("macro60", ".png"))
                effective, _ = macro_is_effective(neut, mac, ffmpeg)
                if effective:            # 画面不同 = 注入有效
                    responsive = True
                    hit_spec = spec
                    hit_round = round_i
                    break
            if responsive:
                break
            s.run(600)                   # 输入锁定期：推进后再存再试
            st = s.save("base")
        add("macro_effective", responsive,
            (f"round={hit_round} spec={hit_spec.split(',')[0]} 同快照同总帧数画面不同 "
             f"neut_sha1={sha1_file(neut)[:12]} mac_sha1={sha1_file(mac)[:12]}"
             if responsive else
             "推进约 2600 帧、Start/全键 mash 均无画面变化，无法证明注入有效"),
            [neut, mac])
        keep("base", st)
        # 确定性用「最终 base」（响应态搜索可能推进过快照），与跨进程比对同源
        a = cap("det_a", s.attempt, state=st, shot=s._wpath("det_a", ".png"))
        s.run(120)                       # 故意漂移，再 load 必须拉回同一画面
        b = cap("det_b", s.attempt, state=st, shot=s._wpath("det_b", ".png"))
        eq, how = _png_pixels_equal(a, b, ffmpeg)
        add("determinism_reload", eq, f"load→截图 vs 漂移120帧→load→截图（{how}）", [a, b])
        n_hit = len(parse_macro(hit_spec).split(","))
        mac2 = cap("macro60b", s.attempt, state=st, spec=hit_spec, extra=60 - n_hit,
                   shot=s._wpath("macro60b", ".png"))
        eq2, how2 = _png_pixels_equal(mac, mac2, ffmpeg)
        add("determinism_macro", eq2, f"同快照+同宏两次尝试画面一致（{how2}）", [mac, mac2])
        base_state = kept["base"]

    with StateSession(rom, bizhawk, core, system) as s2:
        st2 = os.path.join(s2.work, "base.state")
        shutil.copyfile(base_state, st2)
        c = cap("det_cross", s2.attempt, state=st2, shot=s2._wpath("det_cross", ".png"))
        eq3, how3 = _png_pixels_equal(kept["det_a"], c, ffmpeg)
        add("determinism_cross_process", eq3,
            f"进程1存档→进程2读档截图一致（{how3}）", [kept["det_a"], c])

    report = {"rom": str(rom), "bizhawk": str(bizhawk), "core": core,
              "system": system, "movie": str(movie) if movie else None,
              "created": time.strftime("%Y-%m-%d %H:%M:%S"),
              "checks": checks,
              "all_pass": all(c["pass"] for c in checks)}
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="实跑验收（存档/RAM/宏/确定性），产物+report.json")
    v.add_argument("--rom", required=True)
    v.add_argument("--bizhawk", default=None, help="默认取 registry 发现的 2.8")
    v.add_argument("--core", default="NesHawk")
    v.add_argument("--system", default="NES")
    v.add_argument("--movie", default=None, help="可选：先回放 300 帧再 stop_movie 取状态")
    v.add_argument("--out", required=True)
    v.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args()
    if args.cmd == "verify":
        bh = args.bizhawk
        if not bh:
            from . import registry as R
            bh = R.discover_bizhawk(R.DEFAULT_EMU).get("2.8")
        if not bh:
            raise SystemExit("未发现 BizHawk 2.8，请用 --bizhawk 指定")
        rep = verify(args.rom, bh, args.out, args.core, args.system,
                     args.movie, args.ffmpeg)
        for c in rep["checks"]:
            print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}: {c['detail']}")
        print(f"all_pass={rep['all_pass']} -> {Path(args.out) / 'report.json'}")
        return 0 if rep["all_pass"] else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())