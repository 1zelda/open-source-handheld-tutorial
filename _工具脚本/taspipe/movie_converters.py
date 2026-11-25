# -*- coding: utf-8 -*-
"""全怀旧平台 TAS 录像格式转换库：解锁 SNES(.smv/.lsmv)、GBA/GB(.vbm)、MD(.gmv) 与 NES(.fm2/.fcm) 转换。

解决项目缺口（目标与实施路线.md §2 & §3 T2/T13）：
在 4694 条 TASVideos 出版物中，除 FCEUX (.fm2/.fcm) 外，大量经典名作使用各平台原生模拟器录像格式：
  - SFC/SNES 名作（超级银河战士、时空之轮、超级马里奥世界、大金刚国度）：Snes9x (.smv) / lsnes (.lsmv)
  - GBA/GB/GBC 名作（恶魔城晓月圆舞曲、宝可梦、塞尔达缩小帽、洛克人Zero）：VBA-rr (.vbm)
  - MD/Genesis 名作（索尼克、怒之铁拳、幽游白书魔强统一战、魂斗罗铁血兵团）：Gens (.gmv)

本模块将上述主流 TAS 录像格式统一无损转换为 BizHawk 标准 .bk2 容器（Header.txt + SyncSettings.json + Input Log.txt），
使整条 taspipe 通关录制（record/pipeline）与高光切片（clipper）管线直接复用于全怀旧平台。

运行方式（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.movie_converters inspect --movie "F:/path/to/movie.smv"
  py -3 -u -m taspipe.movie_converters convert --movie "F:/path/to/movie.vbm" --out "F:/out/movie.bk2" --sha1 "ROM_SHA1"
  py -3 -u -m taspipe.movie_converters convert-pub --pub 1234
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

from . import fceux as FCEUX
from . import registry as R


class MovieConvertError(Exception):
    pass


def _extract_from_zip_if_needed(path: Path, exts: tuple) -> tuple[bytes, str]:
    """若输入文件是包裹在 .zip 内的录像文件，自动提取内部匹配的录像字节流。"""
    raw = path.read_bytes()
    if raw[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.lower().endswith(exts):
                    return zf.read(name), Path(name).suffix.lower()
    return raw, path.suffix.lower()


# ---------------------------------------------------------------------------
# 1. Snes9x (.smv) -> BizHawk SNES (.bk2)
# ---------------------------------------------------------------------------
# SMV 16-bit 控制器掩码位定义（Snes9x movie.cpp）：
# low byte:  0x10=R, 0x20=L, 0x40=X, 0x80=A, 0x01=Right, 0x02=Left, 0x04=Down, 0x08=Up
# high byte: 0x10=Start, 0x20=Select, 0x40=Y, 0x80=B
SMV_MASK_TO_BTN = [
    (0x0008, "Up"),
    (0x0004, "Down"),
    (0x0002, "Left"),
    (0x0001, "Right"),
    (0x1000, "Start"),
    (0x2000, "Select"),
    (0x4000, "Y"),
    (0x8000, "B"),
    (0x0040, "X"),
    (0x0080, "A"),
    (0x0020, "L"),
    (0x0010, "R"),
]
SNES_BK2_ORDER = [
    ("Up", "U"), ("Down", "D"), ("Left", "L"), ("Right", "R"),
    ("Select", "s"), ("Start", "S"), ("Y", "Y"), ("B", "B"),
    ("X", "X"), ("A", "A"), ("L", "l"), ("R", "r"),
]


def parse_smv(path: Path) -> dict:
    raw, inner_suffix = _extract_from_zip_if_needed(path, (".smv",))
    if inner_suffix != ".smv":
        raise MovieConvertError(f"ZIP 内未找到 .smv: {path}")
    if len(raw) < 32 or raw[:4] != b"SMV\x1a":
        raise MovieConvertError(f"非合法 Snes9x .smv 文件: {path}")
    version, uid, rerecord_count, num_frames = struct.unpack_from("<IIII", raw, 4)
    ctrl_mask, movie_opts, sync_opts, sync_opts2 = struct.unpack_from("<BBBB", raw, 20)
    savestate_offset, controller_data_offset = struct.unpack_from("<II", raw, 24)
    if version != 1:
        raise MovieConvertError(f"只支持 SMV v1，实际 v{version}: {path}")
    if ctrl_mask == 0 or ctrl_mask & ~0x1F:
        raise MovieConvertError(f"SMV 控制器掩码非法: {ctrl_mask:#x}")
    num_controllers = ctrl_mask.bit_count()
    if num_controllers > 2:
        raise MovieConvertError(f"SNES BK2 当前只接入 P1/P2，拒绝静默丢弃 {num_controllers} 个控制器")
    if controller_data_offset < 32 or controller_data_offset > len(raw):
        raise MovieConvertError(f"SMV 输入区偏移非法: {controller_data_offset} / {len(raw)}")

    from_reset = bool(movie_opts & 0x01)
    savestate_gzip = None
    savestate_data = None
    savestate_sha256 = None
    if from_reset:
        if savestate_offset < 32 or controller_data_offset <= savestate_offset:
            raise MovieConvertError(
                f"SMV 声明从复位启动但偏移非法: state={savestate_offset} input={controller_data_offset}")
        savestate_gzip = raw[savestate_offset:controller_data_offset]
        if not savestate_gzip.startswith(b"\x1f\x8b"):
            raise MovieConvertError("SMV 内置 SRAM 不是 gzip 块")
        try:
            savestate_data = gzip.decompress(savestate_gzip)
        except (OSError, EOFError) as exc:
            raise MovieConvertError(f"SMV 内置 SRAM gzip 解压失败: {exc}") from exc
        if len(savestate_data) != 128 * 1024:
            raise MovieConvertError(f"SMV 内置 SRAM 长度不是 128KB: {len(savestate_data)}")
        savestate_sha256 = hashlib.sha256(savestate_data).hexdigest()
    elif savestate_offset != controller_data_offset:
        raise MovieConvertError(
            f"SMV 未声明 FROM_RESET 但 state/input 偏移不一致: {savestate_offset}/{controller_data_offset}")

    step = 2 * num_controllers
    available = len(raw) - controller_data_offset
    sample_count, tail = divmod(available, step)
    expected_samples = num_frames + 1
    if sample_count < expected_samples:
        raise MovieConvertError(
            f"SMV 输入体截断：声明 {num_frames} 帧需基线+{num_frames}={expected_samples} 个样本，"
            f"实际只有 {sample_count} 个")
    warnings = []
    extra_samples = sample_count - expected_samples
    if extra_samples:
        warnings.append(f"声明帧区间之外另有 {extra_samples} 个样本；只转换声明的 {num_frames} 帧")
    if tail:
        warnings.append(f"文件末尾有 {tail} 个不足一个完整样本的字节；未纳入转换")

    baseline = list(struct.unpack_from("<" + "H" * num_controllers, raw, controller_data_offset))
    frames = []
    pos = controller_data_offset + step
    for _ in range(num_frames):
        words = struct.unpack_from("<" + "H" * num_controllers, raw, pos)
        pos += step
        reset = all(word == 0xFFFF for word in words)
        p1_set = set() if reset else {btn for mask, btn in SMV_MASK_TO_BTN if (words[0] & mask)}
        p2_set = set() if reset or len(words) < 2 else {
            btn for mask, btn in SMV_MASK_TO_BTN if (words[1] & mask)}
        frames.append({"cmd": "reset" if reset else "", "p1": p1_set, "p2": p2_set})

    return {
        "format": "smv",
        "platform": "SNES",
        "core": "Snes9x",
        "version": version,
        "uid": uid,
        "rerecord_count": rerecord_count,
        "from_reset": from_reset,
        "num_controllers": num_controllers,
        "declared_frames": num_frames,
        "n_frames": len(frames),
        "frames": frames,
        "baseline": baseline,
        "sample_count": sample_count,
        "extra_samples": extra_samples,
        "tail_bytes": tail,
        "savestate_gzip": savestate_gzip,
        "savestate_data": savestate_data,
        "savestate_sha256": savestate_sha256,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_inner": inner_suffix,
        "warnings": warnings,
    }


def snes_declared_sram_bytes(rom: bytes) -> int:
    if len(rom) < 0x8000:
        raise MovieConvertError("SNES ROM 太短，不能校验卡带头")
    map_mode = rom[0x7FD5] & 0x30
    if map_mode == 0x20:
        map_offset = 0x7FC0
    elif map_mode == 0x30:
        map_offset = 0xFFC0
    else:
        raise MovieConvertError(f"不支持的 SNES 卡带映射模式: 0x{map_mode:02x}")
    if map_offset + 0x20 > len(rom):
        raise MovieConvertError("SNES ROM 卡带头超出文件范围")
    declared_code = rom[map_offset + 0x18]
    return (1024 << declared_code) if declared_code else 0


def bake_snes9x_core_state(parsed: dict, rom, bizhawk, work=None, domain=None):
    if parsed.get("format") != "smv" or not parsed.get("from_reset"):
        raise MovieConvertError("只有从复位开始且带内置 SRAM 的 SMV 需要烘焙 CoreState")
    data = parsed.get("savestate_data")
    if not isinstance(data, bytes) or len(data) != 128 * 1024:
        raise MovieConvertError("SMV 内置 SRAM 缺失或不是 128KB")

    import tas_replay
    from . import statejump as SJ

    live = SJ.emuhawk_processes()
    if live:
        raise MovieConvertError(f"烘焙 CoreState 前已有 EmuHawk 在运行，拒绝并行启动: {live}")
    scratch = Path(work) if work else Path(tempfile.gettempdir()) / "taspipe_smv_seed"
    scratch.mkdir(parents=True, exist_ok=True)
    td = tempfile.TemporaryDirectory(prefix="smv_seed_", dir=str(scratch))
    work_dir = Path(td.name)
    try:
        rom_path = work_dir / "rom.sfc"
        tas_replay.materialize_rom(str(rom), str(rom_path))
        declared_sram = snes_declared_sram_bytes(rom_path.read_bytes())
        with SJ.StateSession(str(rom_path), str(bizhawk), core="Snes9x", system="SNES",
                             work=str(work_dir / "session")) as session:
            names = {row["name"]: row["size"] for row in session.domains()}
            if declared_sram == 0:
                if domain not in (None, "Save RAM"):
                    raise MovieConvertError("无卡带 SRAM 的电影只能注入原生 Snes9x 的 0x55 初始内存")
                domain = "Save RAM"
                seed_data = b"\x55" * 0x20000
                seed_kind = "snes_wram_power_on"
            else:
                if domain is None:
                    candidates = [name for name in names if name == "Save RAM"]
                    if not candidates:
                        candidates = [name for name in names
                                      if ("save" in name.lower() or "sram" in name.lower())
                                      and names[name] == len(data)]
                    if len(candidates) != 1:
                        raise MovieConvertError(f"无法唯一确定 SNES Save RAM 域: {candidates}；可选域={names}")
                    domain = candidates[0]
                seed_data = data
                seed_kind = "cartridge_sram"
            if names.get(domain) != len(seed_data):
                raise MovieConvertError(
                    f"初始内存域大小不符: {domain}={names.get(domain)}，需要 {len(seed_data)}")
            state_path, response = session.seed_ram(seed_data, domain, name="anchor")
            frame_text, byte_text = response.split()
            core_state = Path(state_path).read_bytes()
    except Exception as exc:
        failed = Path(tempfile.mkdtemp(prefix="smv_seed_failed_", dir=str(scratch)))
        shutil.copytree(work_dir, failed, dirs_exist_ok=True)
        raise MovieConvertError(f"{exc}；诊断已保留: {failed}") from exc
    finally:
        td.cleanup()
    return core_state, {
        "domain": domain,
        "seed_kind": seed_kind,
        "declared_sram_bytes": declared_sram,
        "seed_bytes": int(byte_text),
        "seed_sha256": hashlib.sha256(seed_data).hexdigest(),
        "source_sram_sha256": parsed["savestate_sha256"],
        "anchor_frame": int(frame_text),
        "core_state_bytes": len(core_state),
        "core_state_sha256": hashlib.sha256(core_state).hexdigest(),
        "bizhawk": str(bizhawk),
    }


# ---------------------------------------------------------------------------
# 2. VBA / VBA-rr (.vbm) -> BizHawk GBA / GB / GBC (.bk2)
# ---------------------------------------------------------------------------
# VBM 16-bit 控制器位定义：
# 0x0001=A, 0x0002=B, 0x0004=Select, 0x0008=Start,
# 0x0010=Right, 0x0020=Left, 0x0040=Up, 0x0080=Down,
# 0x0100=R, 0x0200=L, 0x0400/0x0800=Reset
VBM_BATTERY_HEADER_SIZE = 8761
VBM_MASK_TO_BTN = [
    (0x0040, "Up"),
    (0x0080, "Down"),
    (0x0020, "Left"),
    (0x0010, "Right"),
    (0x0008, "Start"),
    (0x0004, "Select"),
    (0x0002, "B"),
    (0x0001, "A"),
    (0x0200, "L"),
    (0x0100, "R"),
]
GBA_BK2_ORDER = [
    ("Up", "U"), ("Down", "D"), ("Left", "L"), ("Right", "R"),
    ("Start", "S"), ("Select", "s"), ("B", "B"), ("A", "A"),
    ("L", "l"), ("R", "r"),
]


def parse_vbm(path: Path) -> dict:
    raw, inner_suffix = _extract_from_zip_if_needed(path, (".vbm",))
    if len(raw) < 256 or raw[:4] != b"VBM\x1a":
        raise MovieConvertError(f"非合法 VBA .vbm 文件: {path}")
    version, uid, num_frames, rerecord_count = struct.unpack_from("<IIII", raw, 4)
    start_flags, controller_flags, system_flags, emu_flags = struct.unpack_from("<BBBB", raw, 20)
    save_type, flash_size = struct.unpack_from("<II", raw, 24)
    savestate_offset, controller_data_offset = struct.unpack_from("<II", raw, 56)

    if version != 1:
        raise MovieConvertError(f"只支持 VBM v1，实际 v{version}: {path}")
    if start_flags & ~0x03 or (start_flags & 0x03) == 0x03:
        raise MovieConvertError(f"VBM 起始标志非法: {start_flags:#x}: {path}")
    if controller_flags & ~0x0F or not controller_flags & 0x01:
        raise MovieConvertError(f"VBM 控制器标志非法: {controller_flags:#x}: {path}")
    controller_count = controller_flags.bit_count()
    if controller_count != 1:
        raise MovieConvertError(f"VBM 当前只转换单控制器录像，实际 {controller_count} 个: {path}")
    if system_flags & ~0x07 or (system_flags & 0x07).bit_count() > 1:
        raise MovieConvertError(f"VBM 系统标志非法: {system_flags:#x}: {path}")
    if emu_flags & 0x08:
        raise MovieConvertError(f"VBM 含旧式不支持标志: {emu_flags:#x}: {path}")
    if controller_data_offset < 256 or controller_data_offset > len(raw):
        raise MovieConvertError(f"VBM 输入区偏移非法: {controller_data_offset}/{len(raw)}: {path}")

    from_savestate = bool(start_flags & 0x01)
    from_sram = bool(start_flags & 0x02)
    if from_savestate or from_sram:
        if savestate_offset < 256 or savestate_offset >= controller_data_offset:
            raise MovieConvertError(
                f"VBM 声明起始数据但偏移非法: state={savestate_offset} input={controller_data_offset}: {path}")
    elif savestate_offset != 0:
        raise MovieConvertError(f"VBM 未声明起始数据但 state 偏移非零: {savestate_offset}: {path}")

    is_gba = bool(system_flags & 0x01)
    is_gbc = bool(system_flags & 0x02)
    is_sgb = bool(system_flags & 0x04)
    platform = "GBA" if is_gba else ("GBC" if is_gbc else ("SGB" if is_sgb else "GB"))
    core = "mGBA" if is_gba else "Gambatte"

    required = controller_data_offset + 2 * num_frames * controller_count
    if required > len(raw):
        raise MovieConvertError(
            f"VBM 输入体截断：声明 {num_frames} 帧需到偏移 {required}，文件仅 {len(raw)} 字节: {path}")
    warnings = []
    trailing_bytes = len(raw) - required
    if trailing_bytes:
        warnings.append(f"声明帧区间之外另有 {trailing_bytes} 字节；未纳入转换")

    start_data_gzip = None
    save_data = None
    save_sha256 = None
    if from_sram:
        start_data_gzip = raw[savestate_offset:controller_data_offset]
        try:
            decoded = gzip.decompress(start_data_gzip)
        except (OSError, EOFError, zlib.error) as exc:
            raise MovieConvertError(f"VBM 内嵌 SRAM gzip 解压失败: {exc}: {path}") from exc
        if save_type == 0:
            expected_save_size = 128 * 1024
        elif save_type == 1:
            expected_save_size = 32 * 1024
        elif save_type == 2:
            expected_save_size = flash_size
        else:
            raise MovieConvertError(f"VBM SRAM 类型 {save_type} 的长度规则未实现: {path}")
        if expected_save_size < 1 or len(decoded) != VBM_BATTERY_HEADER_SIZE + expected_save_size:
            raise MovieConvertError(
                f"VBM SRAM 长度不符：解压 {len(decoded)}，需头部 {VBM_BATTERY_HEADER_SIZE}+{expected_save_size}: {path}")
        save_data = decoded[VBM_BATTERY_HEADER_SIZE:]
        save_sha256 = hashlib.sha256(save_data).hexdigest()
    elif from_savestate:
        start_data_gzip = raw[savestate_offset:controller_data_offset]

    frames = []
    sensor_frame_count = 0
    sensor_bitmask = 0
    pos = controller_data_offset
    for _ in range(num_frames):
        (word,) = struct.unpack_from("<H", raw, pos)
        pos += 2
        if word & 0xF000:
            sensor_frame_count += 1
            sensor_bitmask |= word & 0xF000
        cmd = "reset" if word & 0x0C00 else ""
        p1_set = {btn for mask, btn in VBM_MASK_TO_BTN if word & mask}
        frames.append({"cmd": cmd, "p1": p1_set, "p2": set()})
    if sensor_frame_count:
        warnings.append(
            f"{sensor_frame_count} 帧含动作传感器位 {sensor_bitmask:#06x}；按钮可解析，转换前必须显式处理")

    game_code_raw = struct.unpack_from("<I", raw, 52)[0]
    game_code = struct.pack("<I", game_code_raw).decode("ascii", "replace")
    return {
        "format": "vbm",
        "platform": platform,
        "core": core,
        "version": version,
        "uid": f"{uid:08X}",
        "rerecord_count": rerecord_count,
        "from_savestate": from_savestate,
        "from_sram": from_sram,
        "declared_frames": num_frames,
        "start_flags": start_flags,
        "controller_flags": controller_flags,
        "controller_count": controller_count,
        "system_flags": system_flags,
        "emu_flags": emu_flags,
        "save_type": save_type,
        "flash_size": flash_size,
        "savestate_offset": savestate_offset,
        "controller_data_offset": controller_data_offset,
        "trailing_bytes": trailing_bytes,
        "sensor_frame_count": sensor_frame_count,
        "sensor_bitmask": sensor_bitmask,
        "minor_version": raw[48],
        "rom_title": raw[36:48].split(b"\0", 1)[0].decode("ascii", "replace"),
        "rom_crc": raw[49],
        "rom_checksum": struct.unpack_from("<H", raw, 50)[0],
        "game_code": game_code,
        "game_code_raw": game_code_raw,
        "author": raw[64:128].split(b"\0", 1)[0].decode("cp1252", "replace"),
        "description": raw[128:256].split(b"\0", 1)[0].decode("cp1252", "replace"),
        "start_data_gzip": start_data_gzip,
        "save_data": save_data,
        "save_sha256": save_sha256,
        "n_frames": len(frames),
        "frames": frames,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_inner": inner_suffix,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 3. Gens (.gmv) -> BizHawk Genesis / MD (.bk2)
# ---------------------------------------------------------------------------
# GMV 64 字节头后每帧 3 字节（P1, P2, 6键扩展字节），低电平有效（0 表示按下，1 表示未按）！
GMV_BYTE0_BTNS = [
    (0x01, "Up"),
    (0x02, "Down"),
    (0x04, "Left"),
    (0x08, "Right"),
    (0x10, "A"),
    (0x20, "B"),
    (0x40, "C"),
    (0x80, "Start"),
]
GMV_BYTE2_P1_BTNS = [
    (0x01, "X"),
    (0x02, "Y"),
    (0x04, "Z"),
    (0x08, "Mode"),
]
MD_BK2_ORDER = [
    ("Up", "U"), ("Down", "D"), ("Left", "L"), ("Right", "R"),
    ("A", "A"), ("B", "B"), ("C", "C"), ("Start", "S"),
    ("X", "X"), ("Y", "Y"), ("Z", "Z"), ("Mode", "M"),
]


def parse_gmv(path: Path) -> dict:
    raw, _ = _extract_from_zip_if_needed(path, (".gmv",))
    if len(raw) < 64 or not raw[:15].startswith(b"Gens Movie TEST"):
        raise MovieConvertError(f"非合法 Gens .gmv 文件: {path}")
    rerecord_count = struct.unpack_from("<I", raw, 16)[0]
    flags = raw[22]
    from_savestate = bool(flags & 0x40)

    frames = []
    pos = 64
    while pos + 3 <= len(raw):
        b0, b1, b2 = raw[pos], raw[pos + 1], raw[pos + 2]
        pos += 3
        # GMV 为 active-low：位为 0 代表按下
        p1_set = {btn for mask, btn in GMV_BYTE0_BTNS if not (b0 & mask)}
        p1_set |= {btn for mask, btn in GMV_BYTE2_P1_BTNS if not (b2 & mask)}
        p2_set = {btn for mask, btn in GMV_BYTE0_BTNS if not (b1 & mask)}
        frames.append({"cmd": "", "p1": p1_set, "p2": p2_set})

    return {
        "format": "gmv",
        "platform": "MD",
        "core": "GPGX",
        "rerecord_count": rerecord_count,
        "from_savestate": from_savestate,
        "n_frames": len(frames),
        "frames": frames,
    }


WATERBOX_STATE_MAGIC = b"ActivatedWaterboxHost_v1"
ZSTD_FRAME_MAGIC = b"\x28\xb5\x2f\xfd"


def _zstd_decompress(data: bytes, dll_path) -> bytes:
    import ctypes
    from ctypes import c_char_p, c_size_t, c_uint, c_ulonglong, c_void_p, create_string_buffer

    path = Path(dll_path) if dll_path else None
    if path and path.is_dir():
        path = path / "dll" / "libzstd.dll"
    if path is None or not path.is_file():
        raise MovieConvertError("SNES Waterbox Core.bin 是 Zstandard 压缩流；需 --bizhawk 提供含 dll/libzstd.dll 的 BizHawk 目录")
    try:
        lib = ctypes.CDLL(str(path))
        lib.ZSTD_isError.argtypes = [c_size_t]
        lib.ZSTD_isError.restype = c_uint
        lib.ZSTD_getErrorName.argtypes = [c_size_t]
        lib.ZSTD_getErrorName.restype = c_char_p
        lib.ZSTD_decompressBound.argtypes = [c_void_p, c_size_t]
        lib.ZSTD_decompressBound.restype = c_ulonglong
        lib.ZSTD_decompress.argtypes = [c_void_p, c_size_t, c_void_p, c_size_t]
        lib.ZSTD_decompress.restype = c_size_t
        source = create_string_buffer(data)
        bound = lib.ZSTD_decompressBound(source, len(data))
        if lib.ZSTD_isError(bound):
            raise MovieConvertError(f"Zstandard 解压上界计算失败: {lib.ZSTD_getErrorName(bound).decode('utf-8', 'replace')}")
        if not 0 < bound <= 512 * 1024 * 1024:
            raise MovieConvertError(f"Zstandard 解压上界非法或过大: {bound}")
        target = create_string_buffer(bound)
        size = lib.ZSTD_decompress(target, bound, source, len(data))
        if lib.ZSTD_isError(size):
            raise MovieConvertError(f"Zstandard 解压失败: {lib.ZSTD_getErrorName(size).decode('utf-8', 'replace')}")
        return target.raw[:size]
    except OSError as exc:
        raise MovieConvertError(f"无法加载 Zstandard 库 {path}: {exc}") from exc


def _read_core_state(core_state, waterbox=False, zstd_dll=None):
    data = core_state.read_bytes() if isinstance(core_state, Path) else bytes(core_state)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            if "Core.bin" not in names and "Core.bin.zst" not in names:
                raise MovieConvertError("CoreState 缺 Core.bin")
            if "BizVersion.txt" not in names:
                raise MovieConvertError("CoreState 缺 BizVersion.txt")
            core_member = "Core.bin.zst" if "Core.bin.zst" in names else "Core.bin"
            core_binary = z.read(core_member)
            if not core_binary:
                raise MovieConvertError(f"CoreState 的 {core_member} 为空")
            version = z.read("BizVersion.txt").decode("utf-8", "replace").strip()
            sync = json.loads(z.read("SyncSettings.json")) if "SyncSettings.json" in names else None
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise MovieConvertError(f"CoreState 不是合法 BizHawk 状态: {exc}") from exc
    if core_member.endswith(".zst") or core_binary.startswith(ZSTD_FRAME_MAGIC):
        core_binary = _zstd_decompress(core_binary, zstd_dll)
    if waterbox:
        if not core_binary.startswith(WATERBOX_STATE_MAGIC):
            raise MovieConvertError("SNES Snes9x Core.bin 不是 ActivatedWaterboxHost_v1 宿主状态；拒绝写入电影")
    return core_binary, version, sync


def write_multiplatform_bk2(parsed: dict, out_bk2: Path, rom_sha1: str = "",
                            emu_version: str = "Version 2.8", core_state=None,
                            game_name: str = "", zstd_dll=None, core=None) -> Path:
    """将解析后的多平台录像结构打包为 BizHawk 标准 .bk2 容器。"""
    plat = parsed["platform"]
    core = core or parsed["core"]
    if plat == "SNES":
        bsnes_cores = ("BSNES", "BSNESv115+")
        if core not in ("Snes9x", *bsnes_cores):
            raise MovieConvertError(f"SNES 转换器只接入 Snes9x/BSNES/BSNESv115+，实际 {core}")
        if core in bsnes_cores and emu_version != "Version 2.11.1":
            raise MovieConvertError("BSNES Waterbox 电影仅准入已实测的 BizHawk 2.11.1 身份")
        order = SNES_BK2_ORDER
        controllers = int(parsed.get("num_controllers", 1))
        if controllers not in (1, 2):
            raise MovieConvertError(f"SNES LogKey 只支持 P1/P2，实际 {controllers} 个控制器")
        cols = "|".join(f"P1 {name}" for name, _ in order)
        if controllers == 2:
            cols += "|" + "|".join(f"P2 {name}" for name, _ in order)
        log_key = f"LogKey:#Reset|Power|#{cols}|"
    elif plat in ("GBA", "GB", "GBC"):
        order = GBA_BK2_ORDER if plat == "GBA" else GBA_BK2_ORDER[:8]
        cols = "|".join(f"P1 {name}" for name, _ in order)
        log_key = f"LogKey:#Reset|Power|#{cols}|"
    elif plat == "MD":
        order = MD_BK2_ORDER
        cols = "|".join(f"P1 {name}" for name, _ in order)
        log_key = f"LogKey:#Reset|Power|#{cols}|"
    else:
        raise MovieConvertError(f"未知目标平台: {plat}")

    if parsed["format"] == "vbm" and parsed.get("from_savestate"):
        raise MovieConvertError("VBM 内嵌 VBA 快照与 BizHawk CoreState 不兼容，拒绝降级转换")
    if parsed["format"] == "vbm" and parsed.get("sensor_frame_count"):
        raise MovieConvertError(
            f"VBM 有 {parsed['sensor_frame_count']} 帧动作传感器输入未实现，拒绝静默丢弃")
    sram_only = plat == "SNES" and core in ("BSNES", "BSNESv115+")
    smv_from_reset = parsed.get("format") == "smv" and bool(parsed.get("from_reset"))
    anchored = bool(smv_from_reset or parsed.get("from_savestate") or parsed.get("from_sram"))
    if sram_only:
        if not smv_from_reset or not parsed.get("savestate_data"):
            raise MovieConvertError("BSNES 电影必须使用 SMV v1.43 FROM_RESET 内置 SRAM 锚点")
        if core_state is not None:
            raise MovieConvertError("BSNES 状态不含 SRAM；请冷启动并由生产控制层注入初始 SRAM")
    elif anchored and core_state is None:
        raise MovieConvertError(f"{parsed['format']} 从内置存档/SRAM 启动，缺 BizHawk CoreState；拒绝降级开机直放")
    if not sram_only and not anchored and core_state is not None:
        raise MovieConvertError("开机启动的电影不得夹带 CoreState")

    sync_settings = None
    core_state_bytes = None
    if not sram_only and anchored:
        core_state_bytes, state_version, sync_settings = _read_core_state(
            core_state, waterbox=(plat == "SNES"), zstd_dll=zstd_dll)
        expected_version = emu_version.removeprefix("Version ")
        if state_version.removeprefix("Version ") != expected_version:
            raise MovieConvertError(
                f"CoreState BizVersion={state_version!r} 与电影 emuVersion={emu_version!r} 不一致")
        sync_type = str((sync_settings or {}).get("o", {}).get("$type") or "")
        if sync_settings is not None and plat == "SNES" and "Snes9x+SyncSettings" not in sync_type:
            raise MovieConvertError(f"CoreState 不是 Snes9x SyncSettings: {sync_type!r}")
        if sync_settings is not None and plat == "GBA" and "MGBAHawk" not in sync_type:
            raise MovieConvertError(f"CoreState 不是 MGBAHawk SyncSettings: {sync_type!r}")

    header_lines = [
        "MovieVersion BizHawk v2.0.0",
        "Author taspipe.movie_converters",
        f"emuVersion {emu_version}",
        f"Platform {plat if plat != 'MD' else 'GEN'}",
        f"GameName {game_name or 'converted_' + parsed['format']}",
        f"SHA1 {rom_sha1.upper()}" if rom_sha1 else "SHA1 0000000000000000000000000000000000000000",
        f"Core {core}",
        f"rerecordCount {parsed.get('rerecord_count', 0)}",
    ]
    if sram_only:
        header_lines.append("StartsFromSavestate false")
    elif anchored:
        header_lines.append("StartsFromSavestate true")

    log_lines = ["[Input]", log_key]
    for f in parsed["frames"]:
        cmd_str = "r." if f["cmd"] == "reset" else ("p." if f["cmd"] == "power" else "..")
        p1_str = "".join(mn if name in f["p1"] else "." for name, mn in order)
        if plat == "SNES" and int(parsed.get("num_controllers", 1)) == 2:
            p2_str = "".join(mn if name in f.get("p2", set()) else "." for name, mn in order)
            log_lines.append(f"|{cmd_str}|{p1_str}|{p2_str}|")
        else:
            log_lines.append(f"|{cmd_str}|{p1_str}|")
    log_lines.append("[/Input]")

    out_bk2 = Path(out_bk2)
    out_bk2.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_bk2, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Header.txt", "\n".join(header_lines) + "\n")
        zf.writestr("Input Log.txt", "\n".join(log_lines) + "\n")
        if sync_settings is None and plat == "SNES":
            if core == "BSNESv115+":
                sync_type = "BizHawk.Emulation.Cores.Nintendo.BSNES.BsnesCore+SnesSyncSettings, BizHawk.Emulation.Cores"
            elif sram_only:
                sync_type = "BizHawk.Emulation.Cores.Nintendo.SNES.LibsnesCore+SnesSyncSettings, BizHawk.Emulation.Cores"
            else:
                sync_type = "BizHawk.Emulation.Cores.Nintendo.SNES9X.Snes9x+SyncSettings, BizHawk.Emulation.Cores"
            sync_settings = {"o": {"$type": sync_type, "LeftPort": 1, "RightPort": 1}}
        if sync_settings is not None:
            zf.writestr("SyncSettings.json", json.dumps(sync_settings, separators=(",", ":")))
        if core_state_bytes is not None:
            zf.writestr("Core.bin", core_state_bytes)
    return out_bk2


def inspect_movie(path: Path) -> dict:
    _, suf = _extract_from_zip_if_needed(path, (".smv", ".vbm", ".gmv", ".fm2", ".fcm", ".fm3"))
    if suf in (".fm2", ".fcm", ".fm3"):
        m = FCEUX.parse_fm2(path) if suf != ".fcm" else FCEUX.parse_fcm(path)
        return {
            "format": m.source_format, "platform": "NES", "core": "NesHawk",
            "n_frames": m.n_frames, "rerecord_count": m.rerecord,
            "warnings": m.warnings, "errors": m.errors
        }
    elif suf == ".smv":
        d = parse_smv(path)
    elif suf == ".vbm":
        d = parse_vbm(path)
    elif suf == ".gmv":
        d = parse_gmv(path)
    else:
        raise MovieConvertError(f"不支持的录像后缀: {suf}")
    hidden = {"frames", "savestate_gzip", "savestate_data", "start_data_gzip", "save_data"}
    return {k: v for k, v in d.items() if k not in hidden}


def convert_movie_file(movie_path: Path, out_bk2: Path, rom_sha1: str = "",
                       rom_path=None, bizhawk=None, work=None, game_name: str = "",
                       core_state_path=None, core=None) -> dict:
    _, suf = _extract_from_zip_if_needed(movie_path, (".smv", ".vbm", ".gmv", ".fm2", ".fcm", ".fm3"))
    if core_state_path is not None and suf != ".smv":
        raise MovieConvertError("--core-state 只用于复用 SMV 的 BizHawk 起始状态")
    if suf in (".fm2", ".fcm", ".fm3"):
        m = FCEUX.parse_fm2(movie_path) if suf != ".fcm" else FCEUX.parse_fcm(movie_path)
        FCEUX.to_bk2(m, out_bk2, sha1=rom_sha1 or None)
        return {"status": "converted", "format": m.source_format, "platform": "NES", "n_frames": m.n_frames, "out": str(out_bk2)}
    elif suf == ".smv":
        parsed = parse_smv(movie_path)
        if core_state_path is not None and not parsed.get("from_reset"):
            raise MovieConvertError("--core-state 只能用于 FROM_RESET 起始 SMV")
    elif suf == ".vbm":
        parsed = parse_vbm(movie_path)
    elif suf == ".gmv":
        parsed = parse_gmv(movie_path)
    else:
        raise MovieConvertError(f"不支持转换的格式: {suf}")

    target_core = core or parsed["core"]
    if parsed["platform"] == "SNES" and target_core not in ("Snes9x", "BSNES", "BSNESv115+"):
        raise MovieConvertError(f"SNES 转换器只接入 Snes9x/BSNES/BSNESv115+，实际 {target_core}")
    if target_core in ("BSNES", "BSNESv115+") and core_state_path is not None:
        raise MovieConvertError("BSNES 使用电影内置 SRAM，不接受 Snes9x CoreState")
    core_state = None
    seed_report = None
    zstd_dll = Path(bizhawk) / "dll" / "libzstd.dll" if bizhawk else None
    emu_version = ("Version 2.11.1" if target_core in ("BSNES", "BSNESv115+") else
                   ("Version 2.9.1" if parsed["platform"] == "SNES" else "Version 2.8"))
    if parsed.get("from_reset") and target_core not in ("BSNES", "BSNESv115+"):
        if parsed["platform"] != "SNES" or parsed["core"] != "Snes9x":
            raise MovieConvertError("当前只支持烘焙 SNES Snes9x 的 FROM_RESET 电影")
        if core_state_path is None and not bizhawk:
            raise MovieConvertError("FROM_RESET SMV 需 --bizhawk 指定 BizHawk 目录")
        if core_state_path is not None:
            core_state = Path(core_state_path).read_bytes()
            seed_report = {
                "reused_core_state": str(Path(core_state_path).resolve()),
                "core_state_bytes": len(core_state),
                "core_state_sha256": hashlib.sha256(core_state).hexdigest(),
                "source_sram_sha256": parsed["savestate_sha256"],
            }
        else:
            if not rom_path:
                raise MovieConvertError("FROM_RESET SMV 需 --rom 提供本地 ROM（支持 zip!条目）")
            core_state, seed_report = bake_snes9x_core_state(parsed, rom_path, bizhawk, work=work)
        core_binary, state_version, _ = _read_core_state(core_state, waterbox=True, zstd_dll=zstd_dll)
        if state_version:
            emu_version = state_version
        seed_report["bk2_core_state_bytes"] = len(core_binary)
        seed_report["bk2_core_state_sha256"] = hashlib.sha256(core_binary).hexdigest()
    write_multiplatform_bk2(parsed, out_bk2, rom_sha1=rom_sha1,
                            emu_version=emu_version, core_state=core_state,
                            game_name=game_name, zstd_dll=zstd_dll, core=target_core)
    result = {
        "status": "converted",
        "format": parsed["format"],
        "platform": parsed["platform"],
        "core": target_core,
        "n_frames": parsed["n_frames"],
        "out": str(out_bk2),
        "warnings": parsed.get("warnings", []),
    }
    if seed_report:
        result["core_state"] = seed_report
    return result


def convert_pub(pub_id, lib=None, out_dir=None, bizhawk=None, emu_root=None, work=None):
    """按出版物索引转换到 _converted/<plat>/<id>.bk2；SMV 存档锚点走真实 Snes9x CoreState。"""
    from . import fceux as FCEUX_MODULE
    from .schema import sha1_resource

    lib = Path(lib or R.DEFAULT_LIB)
    pubs = {str(p["id"]): p for p in R.load_publications(lib)}
    if str(pub_id) not in pubs:
        raise MovieConvertError(f"未知出版物 id: {pub_id}")
    pub = pubs[str(pub_id)]
    rel = pub.get("local_movie")
    if not rel:
        raise MovieConvertError(f"pub {pub_id} 无 local_movie（尚未下载）")
    src = lib / rel
    if not src.is_file():
        raise MovieConvertError(f"电影文件不存在: {src}")
    _, suf = _extract_from_zip_if_needed(src, (".smv", ".vbm", ".gmv", ".fm2", ".fcm", ".fm3"))
    if suf in (".fm2", ".fcm", ".fm3"):
        return FCEUX_MODULE.convert_pub(str(pub_id), lib=lib, out_dir=out_dir)

    sha1 = R.norm_sha1(pub.get("rom_sha1"))
    rom_idx = R.index_roms(lib)
    rom_match = rom_idx.get(sha1, []) if sha1 else []
    rom_path = rom_match[0] if rom_match else None
    rom_check = "skip（无本地 ROM）"
    if rom_path:
        actual = sha1_resource(rom_path).upper()
        if actual != sha1:
            raise MovieConvertError(f"ROM SHA-1 不符：电影需 {sha1}，本地 {rom_path}={actual}")
        rom_check = f"pass（{rom_path} SHA1={actual}）"

    parsed = parse_smv(src) if suf == ".smv" else None
    if parsed and parsed["from_reset"]:
        if not rom_path:
            raise MovieConvertError(f"pub {pub_id} 的 SMV 带 FROM_RESET SRAM 锚点，但本地无匹配 ROM")
        if not bizhawk:
            versions = R.discover_bizhawk(emu_root or R.DEFAULT_EMU)
            if "2.9.1" not in versions:
                raise MovieConvertError("FROM_RESET SMV 需要本地 BizHawk 2.9.1 烘焙 CoreState")
            bizhawk = versions["2.9.1"]
        expected = Path(bizhawk).name.removeprefix("BizHawk-")
        if expected != "2.9.1":
            raise MovieConvertError(f"419 类 SRAM 锚点固定用 BizHawk 2.9.1，实际目录 {Path(bizhawk).name}")

    plat = pub.get("platform") or (parsed or {}).get("platform")
    if not plat:
        raise MovieConvertError(f"pub {pub_id} 未声明平台")
    out = Path(out_dir) if out_dir else lib / "_converted" / plat
    out_path = out / f"{pub_id}.bk2"
    scratch = Path(work) if work else Path(Path(lib).anchor) / "taspipe_scratch" / "smv_seed"
    result = convert_movie_file(src, out_path, rom_sha1=sha1, rom_path=rom_path,
                                bizhawk=bizhawk, work=scratch, game_name=pub.get("game", ""))
    result.update({
        "pub_id": str(pub_id), "game": pub.get("game"), "source": str(src),
        "rom_sha1": sha1, "rom_match": rom_match, "rom_sha1_check": rom_check,
        "emu_version": "Version 2.9.1" if suf == ".smv" else "Version 2.8",
        "warnings": result.get("warnings", []),
    })
    return result


def main():
    ap = argparse.ArgumentParser(description="全怀旧平台 TAS 录像转换器 (.smv/.vbm/.gmv/.fm2/.fcm -> .bk2)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_ins = sub.add_parser("inspect", help="解析并查看录像元数据与总帧数")
    p_ins.add_argument("--movie", required=True)

    p_conv = sub.add_parser("convert", help="将录像转换为 BizHawk .bk2")
    p_conv.add_argument("--movie", required=True)
    p_conv.add_argument("--out", required=True)
    p_conv.add_argument("--sha1", default="")
    p_conv.add_argument("--game", default="")
    p_conv.add_argument("--rom", default="")
    p_conv.add_argument("--bizhawk", default="")
    p_conv.add_argument("--work", default="")
    p_conv.add_argument("--core-state", default="", help="复用已校验的 BizHawk .state，跳过重新烘焙")
    p_conv.add_argument("--core", default="", help="指定目标核心；SNES 支持 Snes9x/BSNES/BSNESv115+")

    p_pub = sub.add_parser("convert-pub", help="按出版物 id 转换并写入 _converted 缓存")
    p_pub.add_argument("--pub", required=True)
    p_pub.add_argument("--lib", default="")
    p_pub.add_argument("--out", default="")
    p_pub.add_argument("--bizhawk", default="")
    p_pub.add_argument("--emu-root", default="")
    p_pub.add_argument("--work", default="")

    args = ap.parse_args()
    if args.cmd == "inspect":
        print(json.dumps(inspect_movie(Path(args.movie)), ensure_ascii=False, indent=2))
    elif args.cmd == "convert":
        res = convert_movie_file(Path(args.movie), Path(args.out), rom_sha1=args.sha1,
                                 rom_path=args.rom or None, bizhawk=args.bizhawk or None,
                                 work=args.work or None, game_name=args.game,
                                 core_state_path=args.core_state or None, core=args.core or None)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif args.cmd == "convert-pub":
        res = convert_pub(args.pub, lib=args.lib or None, out_dir=args.out or None,
                          bizhawk=args.bizhawk or None, emu_root=args.emu_root or None,
                          work=args.work or None)
        print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
