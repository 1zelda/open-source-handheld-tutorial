# -*- coding: utf-8 -*-
"""T2：FCEUX .fm2/.fcm/.fm3 → BizHawk .bk2 转换（镜像 BizHawk 2.8 Fm2Import/FcmImport）。

为什么逐行直转帧对齐：FCEUX 与 BizHawk 都是「每个模拟帧一条输入（含 lag 帧）」。
FCEUX src/movie.cpp 的 currFrameCounter++ 在 FCEUMOV_AddInputState 末尾无条件执行
（src/input.cpp FCEU_UpdateInput 每帧调用），录制时每帧 push 一条记录；BizHawk bk2
 likewise 每帧一行。故 fm2 行数 == 模拟帧数 == bk2 行数，无需插 lag 帧。
（已核 FCEUX 源码与 BizHawk 2.8 Fm2Import.cs/FcmImport.cs 参考实现。）

映射：
  * 按钮序 fm2 RLDUTSBA → bk2 UDLRTSBA（Start=T / Select=S 两边一致）。
  * 命令字段 fm2 0/1/2 → bk2 ../.r/P.（NesHawk LogKey=#Power|Reset，助记符 P=Power、r=Reset）。
  * romChecksum(base64 MD5) → Header MD5；SHA1 由出版物 rom_sha1 注入。
  * port0/port1 → SyncSettings.Controls 与 LogKey 的 P1/P2 列。
  * 回放核心：默认 auto = 照抄同 ROM SHA1 原生 bk2 的 Core/BoardName/emuVersion；
    查不到才用 NesHawk。QuickNes/quickerNES 要写 QuickNES+QuickNESSyncSettings，
    不是 NES+NESSyncSettings。

残留 desync 风险（BizHawk 官方导入器同样丢弃，必须实测回放验证、不打包票）：
  NewPPU / RAMInitOption / RAMInitSeed 标志、FCEUX vs 目标核心的时序差异。
  StartsFromSavestate=1 的电影不支持（与 BizHawk 导入器一致）。

11-21 实测（pub_7429 忍者龙剑传2，同一份输入内容）：NesHawk 臂停在 3-2 SCORE 000000，
QuickNes 臂（= 同 ROM 原生片 5441 的核心）走到 7-5 终 Boss，与 5441 自己的末帧同场景。
写死 NesHawk 会把能通关的片子误判成转换器坏了，所以核心改成按 ROM 取参照片。

运行（生产路径，配合 registry）:
  python -m taspipe.fceux inspect --pub 3232        # 解析+报告，不写盘
  python -m taspipe.fceux convert --pub 3232        # 写 _converted/<plat>/<id>.bk2
  python -m taspipe.fceux convert --pub 7429 --out D:/tmp/x   # 试跑，不动库内件
  python -m taspipe.fceux convert-all --ready-only  # 批量转换有本地 ROM 的条目
"""
import argparse
import base64
import hashlib
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]

# fm2 每端口 8 字符的按钮序（位置 0..7）；字符 != '.' 即按下。
FM2_BUTTONS = ["Right", "Left", "Down", "Up", "Start", "Select", "B", "A"]
# bk2 P1/P2 列渲染序与助记符（NesHawk LogKey 顺序）。
BK2_ORDER = ["Up", "Down", "Left", "Right", "Start", "Select", "B", "A"]
BK2_MNEMONIC = {"Up": "U", "Down": "D", "Left": "L", "Right": "R",
                "Start": "T", "Select": "S", "B": "B", "A": "A"}
# FCM 控制器更新字节的低 3 位按钮序。
FCM_BUTTONS = ["A", "B", "Select", "Start", "Up", "Down", "Left", "Right"]
QUIET_START_LIMIT = 1800  # 30 秒：正常成片在这里早已按下 Start

NESSYNC_TYPE = ("BizHawk.Emulation.Cores.Nintendo.NES.NES+NESSyncSettings, "
                "BizHawk.Emulation.Cores")
QUICKNES_SYNC_TYPES = ("BizHawk.Emulation.Cores.Consoles.Nintendo.QuickNES."
                       "QuickNES+QuickNESSyncSettings, BizHawk.Emulation.Cores")
# 这两个核心不认 NES+NESSyncSettings，写错 $type 会被 BizHawk 直接退回默认设置
SUBFRAME_CORES = ("SubNESHawk", "SubQuickNes")


class ConversionError(Exception):
    pass


class FceuxMovie:
    def __init__(self, source_format):
        self.source_format = source_format      # 'fm2' / 'fcm'
        self.header = {}                        # 原始头键值（小写键）
        self.md5 = None
        self.author = None
        self.game_name = None
        self.rerecord = 0
        self.pal = False
        self.port0 = 1
        self.port1 = 0
        self.fourscore = False
        self.fds = False
        self.frames = []                        # [{"cmd","p1","p2"}]
        self.warnings = []
        self.errors = []

    @property
    def n_frames(self):
        return len(self.frames)


def _decode_md5_blob(blob):
    """fm2 romChecksum: base64:<16字节> 或 0x<32hex>。返回小写 hex 或 None。"""
    if not blob:
        return None
    b = blob.strip()
    try:
        if b.lower().startswith("base64:"):
            raw = base64.b64decode(b[7:])
        elif b.lower().startswith("0x"):
            raw = bytes.fromhex(b[2:])
        else:
            return None
        return raw.hex() if len(raw) == 16 else None
    except Exception:
        return None


def _read_fm2_text(path):
    """fm2 可为纯文本或 zip 外壳（fm3 必为 zip）。返回文本；非 fm2 容器返回 None。"""
    path = str(path)
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    names = z.namelist()
    inner = [n for n in names if n.lower().endswith((".fm2", ".fm3"))]
    if inner:
        return z.read(inner[0]).decode("utf-8", "replace")
    return None


def _frame(cmd, p1, p2):
    return {"cmd": cmd, "p1": set(p1), "p2": set(p2)}


def _one_line(value):
    """bk2 头是逐行 key value；FCM 第二个字符串字段是"影片名"，里面常带换行（515M 就带），
    直接写会把一行头变成两行、第二行没有键名。"""
    return " ".join(str(value).split())


def parse_fm2(path):
    text = _read_fm2_text(path)
    if text is None:
        raise ConversionError(f"非 fm2/fm3 容器: {path}")
    m = FceuxMovie("fm2")
    cmd_map = {"0": "", "1": "reset", "2": "power", "4": "fds0", "8": "fds1"}
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("|"):
            sections = [s for s in line.split("|") if s != ""]
            if not sections:
                continue
            c = sections[0][0] if sections[0] else "0"
            cmd = cmd_map.get(c)
            if cmd is None:
                m.warnings.append(f"未知命令 {c}（按无命令处理）")
                cmd = ""
            if cmd in ("fds0", "fds1"):
                m.fds = True
                m.warnings.append(f"FDS 命令 {c}：NesHawk FDS 未完全支持，按无命令处理")
                cmd = ""
            players = []
            for sec in sections[1:]:
                if len(sec) == 8:
                    players.append({FM2_BUTTONS[i] for i, ch in enumerate(sec) if ch != "."})
                else:
                    players.append(set())
            p1 = players[0] if len(players) > 0 else set()
            p2 = players[1] if len(players) > 1 else set()
            m.frames.append(_frame(cmd, p1, p2))
            continue
        low = line.lower()
        if low.startswith("sub"):
            continue                                   # 字幕：暂不搬运
        if low.startswith("comment author"):
            parts = line.split(" ", 2)
            m.author = parts[2].strip() if len(parts) > 2 else None
            continue
        if " " in line:
            k, v = line.split(" ", 1)
            k, v = k.strip(), v.strip()
        else:
            k, v = line.strip(), ""
        kl = k.lower()
        m.header[kl] = v
        if kl == "romchecksum":
            m.md5 = _decode_md5_blob(v)
            if m.md5 is None:
                m.warnings.append("romChecksum 解析失败（无法做 MD5 一致性校验）")
        elif kl == "romfilename":
            m.game_name = v
        elif kl == "port0":
            m.port0 = 1 if v == "1" else 0
        elif kl == "port1":
            m.port1 = 1 if v == "1" else 0
        elif kl == "port2" and v == "1":
            m.warnings.append("Famicom 扩展口 port2=1 未支持，忽略")
        elif kl == "fourscore" and v == "1":
            m.fourscore = True
            m.warnings.append("fourscore=1（四手柄）未支持，仅映射 P1/P2")
        elif kl == "palflag":
            m.pal = v == "1"
        elif kl == "rerecordcount":
            m.rerecord = int(v) if v.isdigit() else 0
        elif kl == "fds" and v == "1":
            m.fds = True
        elif kl == "startsfromsavestate" and v == "1":
            m.errors.append("StartsFromSavestate=1：从存档起始的电影不支持（同 BizHawk 导入器）")
        elif kl == "version" and v != "3":
            m.warnings.append(f"fm2 version={v}（非 3），可能不兼容")
    if not m.frames:
        m.errors.append("未解析到任何输入帧")
    return m


def parse_fcm(path):
    """二进制 FCM v2（镜像 BizHawk FcmImport.cs）。"""
    data = Path(path).read_bytes()
    if data[:4] != b"FCM\x1a":
        raise ConversionError(f"非 FCM 签名: {path}")
    m = FceuxMovie("fcm")
    pos = 4
    version = struct.unpack_from("<I", data, pos)[0]; pos += 4
    if version != 2:
        raise ConversionError(f"FCM version={version}（须为 2）")
    flags = data[pos]; pos += 1
    if ((flags >> 1) & 1) == 0:
        m.errors.append("FCM 从内嵌存档起始的电影不支持（同 BizHawk 导入器）")
    m.pal = ((flags >> 2) & 1) != 0
    pos += 3                                           # 3 个保留字节
    frame_count = struct.unpack_from("<I", data, pos)[0]; pos += 4
    m.rerecord = struct.unpack_from("<I", data, pos)[0]; pos += 4
    # 20-23 输入记录字节长度 / 24-27 内嵌 FCS 存档块起始 / 28-31 输入记录真正起始
    input_len = struct.unpack_from("<I", data, pos)[0]; pos += 4
    state_offset = struct.unpack_from("<I", data, pos)[0]; pos += 4
    first_frame = struct.unpack_from("<I", data, pos)[0]; pos += 4
    m.md5 = data[pos:pos + 16].hex(); pos += 16
    pos += 4                                           # emu version
    header_end = min([x for x in (state_offset, first_frame) if x] or [len(data)])
    for field in ("game_name", "author"):
        if pos >= header_end or b"\x00" not in data[pos:header_end]:
            break
        end = data.index(b"\x00", pos)
        setattr(m, field, data[pos:end].decode("utf-8", "replace")); pos = end + 1
    if not first_frame or first_frame >= len(data):
        m.errors.append(f"FCM 输入记录起始越界：{first_frame}>={len(data)}")
    elif state_offset and data[state_offset:state_offset + 4] != b"FCS\x00":
        m.errors.append(f"FCM 存档块标记缺失（{state_offset} 处不是 'FCS'）")
    if state_offset and first_frame - state_offset > 16:
        m.errors.append("FCM 内嵌存档非空：从存档起始的电影不支持")
    if first_frame + input_len > len(data):
        m.errors.append(f"FCM 输入长度越界：{first_frame}+{input_len}>{len(data)}")

    pos = first_frame
    p1, p2 = set(), set()
    players = {1: p1, 2: p2}
    pending_cmd = ""                                   # 本条记录的命令，落在紧随其后的第一帧
    emitted = 0
    end = min(len(data), first_frame + input_len if input_len else len(data))

    # 一条记录 = 「之后 gap 帧沿用当前输入状态」，命令/按键的改变从第 gap+1 帧起生效。
    # 每条记录若额外多产 1 帧，总帧数就比头里声明的多出「记录条数」（515M 实测多 4684 帧），
    # 后果是整条轨道逐记录后移 ⇒ 回放停在第一屏不动，看着像 ROM 不配对。
    while emitted < frame_count and pos < end:
        update = data[pos]; pos += 1
        delta = (update >> 5) & 3
        if pos + delta > end:
            m.errors.append(f"FCM 输入体在第 {emitted} 帧处截断：还差 {pos + delta - end} 个间隔字节")
            break
        gap = 0
        for b in range(delta):
            gap += data[pos] << (b * 8); pos += 1
        for _ in range(gap):
            if emitted >= frame_count:
                break
            m.frames.append(_frame(pending_cmd, p1, p2))
            pending_cmd = ""
            emitted += 1
        if (update >> 7) & 1:                          # 控制命令
            command = update & 0x1F
            if command == 1:
                pending_cmd = "reset"
            elif command == 2:
                pending_cmd = "reset" if emitted == 0 else "power"
            elif command in (7, 8):
                m.warnings.append(f"VS System 命令 {command} 未支持（帧 {emitted}）")
            elif command in (24, 25, 26):
                m.fds = True
                m.warnings.append(f"FDS 命令 {command} 未支持（帧 {emitted}）")
            elif command not in (0, 1, 2):
                m.warnings.append(f"未知控制命令 {command}（帧 {emitted}）")
            if pending_cmd == "" and emitted == 0:
                m.errors.append("FCM 首条非空闲命令不是 Reset/Power：疑似从存档起始，不支持")
        else:                                          # 控制器切换
            player = ((update >> 3) & 3) + 1
            button = update & 7
            if player > 2:
                m.errors.append("FCM four score 未支持")
                break
            btn = FCM_BUTTONS[button]
            target = players[player]
            if btn in target:
                target.discard(btn)
            else:
                target.add(btn)
    if not m.frames:
        m.errors.append("未解析到任何输入帧")
    if emitted != frame_count:
        m.errors.append(f"FCM 帧数不符：解出 {emitted}，头里声明 {frame_count}（差 {frame_count - emitted}）")
    elif pos != end:
        m.errors.append(f"FCM 输入体没吃完：解到 {pos}，声明区间终点 {end}（剩 {end - pos} 字节）")
    return m


def parse_movie(path):
    ext = Path(path).suffix.lower()
    if ext == ".fcm":
        return parse_fcm(path)
    if ext in (".fm2", ".fm3"):
        return parse_fm2(path)
    # 扩展名不明时按内容探测
    text = _read_fm2_text(path)
    if text is not None:
        return parse_fm2(path)
    if Path(path).read_bytes()[:4] == b"FCM\x1a":
        return parse_fcm(path)
    raise ConversionError(f"无法识别的电影格式: {path}")


def _sync_settings(port0, port1):
    return {"o": {
        "$type": NESSYNC_TYPE,
        "BoardProperties": {},
        "RegionOverride": 0,
        "Controls": {
            "Famicom": False,
            "NesLeftPort": "ControllerNES" if port0 else "UnpluggedNES",
            "NesRightPort": "ControllerNES" if port1 else "UnpluggedNES",
            "FamicomExpPort": "UnpluggedFam",
        },
        "InitialWRamStatePattern": None,
        "VSDipswitches": {f"Dip_Switch_{i}": False for i in range(1, 9)},
    }}


def _quicknes_sync_settings(port0, port1, style="connected"):
    """QuickNes/quickerNES 的 SyncSettings 与 NesHawk 完全不同一套类，且有两种写法：
    BizHawk 2.9 的 5441 用 LeftPortConnected/RightPortConnected 布尔，
    2.10 的 6725 用 Port1/Port2 整数。style 由参照片决定，不猜。"""
    if style == "port":
        return {"o": {"$type": QUICKNES_SYNC_TYPES, "Port1": 1 if port0 else 0,
                      "Port2": 1 if port1 else 0}}
    return {"o": {"$type": QUICKNES_SYNC_TYPES, "LeftPortConnected": bool(port0),
                  "RightPortConnected": bool(port1)}}


def _open_bk2(path):
    """打开 .bk2（可能是 zip 外套 zip），返回内层 ZipFile；打不开返回 None。"""
    try:
        z = zipfile.ZipFile(str(path))
    except Exception:
        return None
    names = z.namelist()
    if len(names) == 1 and names[0].lower().endswith(".bk2"):
        try:
            import io
            return zipfile.ZipFile(io.BytesIO(z.read(names[0])))
        except Exception:
            return None
    return z


_NATIVE_INDEX_CACHE = {}


def native_bk2_index(lib, plat="NES"):
    """{ROM SHA1: [参照片…]}，同 SHA1 内按 pub_id 升序；一次扫库后按 lib 缓存。"""
    from . import registry as R
    key = (str(Path(lib)), plat)
    if key in _NATIVE_INDEX_CACHE:
        return _NATIVE_INDEX_CACHE[key]
    idx = {}
    pubs = [p for p in R.load_publications(lib)
            if (p.get("movie_ext") or "").lower() == "bk2"
            and (p.get("platform") or "NES") == plat and p.get("local_movie")]
    for p in sorted(pubs, key=lambda x: int(x["id"])):
        z = _open_bk2(Path(lib) / p["local_movie"])
        if z is None or "Header.txt" not in z.namelist():
            continue
        hdr = {}
        # 与 registry.read_bk2_header 同一条规矩：BizHawk 原生件可能带 BOM，
        # 不剥掉就读不到 SHA1，整张参照索引会安静地变成空表（继承臂于是永远不触发）。
        for line in z.read("Header.txt").decode("utf-8-sig", "replace").splitlines():
            if " " in line:
                k, v = line.split(" ", 1)
                hdr[k.strip()] = v.strip()
        sha1 = R.norm_sha1(hdr.get("SHA1"))
        if not sha1:
            continue
        o = {}
        if "SyncSettings.json" in z.namelist():
            try:
                o = (json.loads(z.read("SyncSettings.json").decode("utf-8", "replace"))
                     or {}).get("o") or {}
            except Exception:
                o = {}
        idx.setdefault(sha1, []).append({
            "pub_id": str(p["id"]),
            "core": hdr.get("Core", ""),
            "board": hdr.get("BoardName", ""),
            "emu_version": (hdr.get("emuVersion") or "").replace("Version", "").strip(),
            "sync_type": o.get("$type", ""),
            "quicknes_style": ("port" if "Port1" in o else
                               "connected" if "LeftPortConnected" in o else None),
            "n_frames": _bk2_rows(z),
        })
    _NATIVE_INDEX_CACHE[key] = idx
    return idx


def native_reference(sha1, lib, plat="NES", exclude=None, bizhawk_dirs=None):
    """在同一 ROM SHA1 的原生 .bk2 出版物里找参照片，取它的核心/板型/版本/端口写法。

    依据 11-21 的 7429 A/B：fm2 逐行转 bk2 后输入内容与帧数都对（33059 行 Δ=0），
    但 NesHawk 臂停在 3-2 SCORE 000000，QuickNes 臂（= 同 ROM 原生片 5441 的核心）
    走到 7-5 终 Boss，和 5441 自己的末帧同场景。差的是核心选择，不是转换。
    所以选核不靠猜，照抄社区在该 ROM 上已验证的原生片。找不到参照返回 None。

    同一 ROM 常有多部原生片：DK 的 SHA1 下 3789 是 NesHawk 2.3.0（本机实测卡核）、
    5254 是 NesHawk 2.9（可驱动）。给了 bizhawk_dirs 就优先选本机装好且未卡核的那部，
    否则照最小 pub_id（保持可复现）。
    """
    from . import registry as R
    if not sha1:
        return None
    cands = [e for e in native_bk2_index(lib, plat).get(R.norm_sha1(sha1), [])
             if str(e["pub_id"]) != str(exclude)]
    if not cands:
        return None
    if bizhawk_dirs:
        from .control import driver_stall_version, _version_trim

        def drivable(e):
            ver = _version_trim(e.get("emu_version") or "")
            if not ver or ver not in bizhawk_dirs:
                return False
            return driver_stall_version(ver) is None

        pref = [e for e in cands if drivable(e)]
        if pref:
            return pref[0]
    return cands[0]


def _bk2_rows(z):
    if "Input Log.txt" not in z.namelist():
        return None
    lines = z.read("Input Log.txt").decode("utf-8", "replace").splitlines()
    return max(0, len(lines) - 2)


def input_log_digest(path):
    """电影输入层的字节摘要。两臂摘要相同=放的确实是同一份输入，剩下的差异只可能来自
    核心/版本本身；这条对照把「转换器把输入改坏了」和「核心之间不同步」分开。"""
    z = _open_bk2(Path(path))
    if z is None or "Input Log.txt" not in z.namelist():
        raise ConversionError(f"无法读取电影输入层: {path}")
    return hashlib.sha256(z.read("Input Log.txt")).hexdigest()


def _render_player(pressed):
    return "".join(BK2_MNEMONIC[b] if b in pressed else "." for b in BK2_ORDER)


def to_bk2(m, out_path, sha1=None, game_name=None, author=None, bizhawk_version="2.8",
           core="NesHawk", board=None, quicknes_style="connected", core_source=None):
    """写 BizHawk .bk2（zip）。返回写入路径。m.errors 非空则拒绝。

    core/board 由调用方决定（见 native_reference）：FCEUX 电影换核心结果不同，
    写死 NesHawk 会把能通关的片子判成 desync（11-21 的 7429 实测）。
    """
    if m.errors:
        raise ConversionError("; ".join(m.errors))
    if m.fourscore:
        raise ConversionError("fourscore（四手柄）电影未支持")
    if str(core).lower().startswith("sub"):
        raise ConversionError(
            f"子帧核心 {core} 不能吃帧量化输入：fm2 一行就是一帧，而 SubNESHawk 的 Input Log 一行是一个时间片"
            "（实测原生 6012：5,788,209 行 / 17,588 帧 = 329.1 行每帧）。这样写出来的文件既没有 CycleCount "
            "也没有 VBlankCount，控制层折不出帧数（_bk2_frames 直接拒），硬编一个假帧数又会把整片缩成 329 分之一。"
            "要么显式换帧量化核心（--core NesHawk/QuickNes，注意换核心就换时间线），要么直接用原生子帧片。")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    two_player = m.port1 == 1

    # 输入记录起点错位（FCM 曾把 24-27 的内嵌存档偏移当输入起始）会让整片变成"全中立 62 帧千"，
    # 模拟器照样播放、帧数照样对，只有画面不动 ⇒ 必须在写盘前拦。
    quiet = 0
    for f in m.frames[:QUIET_START_LIMIT]:
        if f.get("p1") or f.get("p2") or f.get("cmd"):
            break
        quiet += 1
    if m.frames and quiet >= min(QUIET_START_LIMIT, len(m.frames)):
        raise ConversionError(
            f"输入日志前 {quiet} 帧全中立（无按键、无 Power/Reset）⇒ 输入记录起点疑似错位，拒写 bk2。"
            "FCM 输入起始在头 28-31 字段，24-27 是内嵌存档(FCS)偏移。")

    header = ["MovieVersion BizHawk v2.0",
              f"Author {_one_line(author or m.author or 'default user')}",
              f"emuVersion Version {bizhawk_version}",
              "Platform NES",
              f"GameName {_one_line(game_name or m.game_name or 'NES game')}"]
    if sha1:
        header.append(f"SHA1 {sha1.strip().upper()}")
    if m.md5:
        header.append(f"MD5 {m.md5}")
    header.append(f"Core {core}")
    header.append(f"rerecordCount {m.rerecord}")
    if board:
        header.append(f"BoardName {board}")
    elif m.fds:
        header.append("BoardName FDS")
    if "palflag" in m.header:
        # 照抄 BizHawk 2.8 Fm2Import：HeaderEntries[Pal] = palFlag 原文（0/1）。
        # Bk2Movie.FrameRate 用 IsPal 选 50/60Hz，缺这个键就会把 PAL 电影按 60Hz 跑。
        header.append(f"PAL {m.header['palflag']}")

    logkey = ("LogKey:#Power|Reset|#P1 Up|P1 Down|P1 Left|P1 Right|"
              "P1 Start|P1 Select|P1 B|P1 A|")
    if two_player:
        logkey += ("#P2 Up|P2 Down|P2 Left|P2 Right|"
                   "P2 Start|P2 Select|P2 B|P2 A|")
    log = ["[Input]", logkey]
    for fr in m.frames:
        cmd = ("P" if fr["cmd"] == "power" else ".") + ("r" if fr["cmd"] == "reset" else ".")
        line = f"|{cmd}|{_render_player(fr['p1'])}|"
        if two_player:
            line += f"{_render_player(fr['p2'])}|"
        log.append(line)
    log.append("[/Input]")

    comments = [f"Movie origin .{m.source_format} (taspipe.fceux convert)",
                f"Emulation origin FCEUX/FCEU emuVersion={m.header.get('emuversion', '?')}",
                f"Replay core {core} via BizHawk {bizhawk_version}"
                + (f" (参照原生片 {core_source})" if core_source else " (默认核心)")]
    for k in ("newppu", "raminitoption", "raminitseed"):
        if k in m.header:
            comments.append(f"{k} {m.header[k]} (未映射到 NesHawk；desync 风险，须实测)")
    if m.pal:
        comments.append("PAL 电影：RegionOverride=0 自动判区，须实测确认时序")
    comments.extend(m.warnings)

    if core in ("QuickNes", "quickerNES", "SubQuickNes"):
        sync = _quicknes_sync_settings(m.port0, m.port1, quicknes_style)
    else:
        sync = _sync_settings(m.port0, m.port1)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Header.txt", "\n".join(header) + "\n")
        z.writestr("Input Log.txt", "\n".join(log) + "\n")
        z.writestr("SyncSettings.json", json.dumps(sync))
        z.writestr("Comments.txt", "\n".join(comments) + "\n")
    return str(out_path)


# ------------------------------------------------------------- 生产路径（配合 registry）

def _rom_md5(path):
    """FCEUX GameInfo->MD5 口径：.nes 去掉 16 字节 iNES 头后算 MD5。

    fm2/fcm 的 romChecksum 即此值（movie.cpp:952 romChecksum=GameInfo->MD5）。
    已用塞尔达实测核对：整文件 MD5=337bd6…，去头 MD5=d9a1631…==fm2 romChecksum。
    非 iNES 文件（无 NES\\x1a 魔数）则对整文件算。
    """
    with open(path, "rb") as fh:
        head = fh.read(16)
        h = hashlib.md5()
        if head[:4] != b"NES\x1a":
            h.update(head)
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def convert_pub(pub_id, lib=None, out_dir=None, bizhawk_version="2.8", core="auto",
                emu_root=None):
    """转换单条出版物。走 registry 索引定位电影与 ROM；写 _converted/<plat>/<id>.bk2。

    core="auto"（默认）= 先查同 ROM SHA1 的原生 bk2，照抄它的核心/板型/BizHawk 版本；
    查不到才退回 NesHawk。显式给核心名则只用它指定的核心，板型仍尽量从参照片取。
    """
    from . import registry as R
    lib = Path(lib or R.DEFAULT_LIB)
    pubs = {p["id"]: p for p in R.load_publications(lib)}
    if pub_id not in pubs:
        raise ConversionError(f"未知出版物 id: {pub_id}")
    pub = pubs[pub_id]
    rel = pub.get("local_movie")
    if not rel:
        raise ConversionError(f"pub {pub_id} 无 local_movie（尚未下载）")
    src = lib / rel
    if not src.is_file():
        raise ConversionError(f"电影文件不存在: {src}")
    m = parse_movie(src)
    if m.errors:
        raise ConversionError("; ".join(m.errors))

    sha1 = R.norm_sha1(pub.get("rom_sha1"))
    rom_idx = R.index_roms(lib)
    rom_match = rom_idx.get(sha1, []) if sha1 else []
    md5_check = "skip（无本地 ROM）"
    if rom_match:
        actual = _rom_md5(rom_match[0])
        if m.md5 and actual.lower() != m.md5.lower():
            raise ConversionError(
                f"ROM MD5 不符：电影需 {m.md5}，本地 {Path(rom_match[0]).name}={actual}"
                "（ROM 版本错配，转换会 desync）")
        md5_check = f"pass（{Path(rom_match[0]).name} MD5={actual}）"
    elif m.md5:
        md5_check = f"未校验（无匹配 ROM，电影 MD5={m.md5}）"

    plat = pub.get("platform") or "NES"
    use_core, use_board, use_ver, style, core_source = "NesHawk", None, bizhawk_version, "connected", None
    ref = native_reference(sha1, lib, plat=plat, exclude=pub_id,
                           bizhawk_dirs=R.discover_bizhawk(emu_root or R.DEFAULT_EMU)) if sha1 else None
    if core == "auto":
        if ref and ref.get("core"):
            use_core, use_board = ref["core"], ref.get("board") or None
            if ref.get("emu_version"):
                use_ver = ref["emu_version"]
            style = ref.get("quicknes_style") or "connected"
            core_source = ref["pub_id"]
        else:
            core_source = "无同 ROM 原生片，按 NesHawk 默认"
    elif core != "NesHawk":
        use_core = core
        use_board = (ref or {}).get("board") or None
        style = (ref or {}).get("quicknes_style") or "connected"
        core_source = f"用户显式指定核心 {core}"
    else:
        core_source = "用户显式指定核心 NesHawk"

    out = Path(out_dir) if out_dir else lib / "_converted" / plat
    out_path = out / f"{pub_id}.bk2"
    if use_core.lower().startswith("sub"):
        raise ConversionError(
            f"pub {pub_id}（{pub.get('game')}）的参照片 {core_source} 用子帧核心 {use_core}，"
            f"但 fm2 输入是帧量化的，转出来是废文件（详见 to_bk2 的说明）；"
            f"要跑就显式 --core 一个帧量化核心，或直接用原生片 {core_source}")
    to_bk2(m, out_path, sha1=sha1, game_name=pub.get("game"),
           bizhawk_version=use_ver, core=use_core, board=use_board,
           quicknes_style=style, core_source=core_source)
    return {
        "pub_id": pub_id, "game": pub.get("game"), "source": str(src),
        "source_format": m.source_format, "n_frames": m.n_frames,
        "rom_sha1": sha1, "rom_match": rom_match, "md5_check": md5_check,
        "core": use_core, "board": use_board, "bizhawk_version": use_ver,
        "core_source": core_source or ("显式指定" if core not in ("auto", "NesHawk")
                                       else "无同 ROM 原生片，按 NesHawk 默认"),
        "out": str(out_path), "warnings": m.warnings,
        "two_player": m.port1 == 1,
    }


def convert_all(lib=None, ready_only=True, bizhawk_version="2.8", core="auto",
                out_dir=None):
    """批量转换 FCEUX 出版物。ready_only=True 只转有本地 ROM 匹配的。"""
    from . import registry as R
    lib = Path(lib or R.DEFAULT_LIB)
    pubs = R.load_publications(lib)
    rom_idx = R.index_roms(lib)
    results = []
    for pub in pubs:
        emu = (pub.get("emulator") or "").lower()
        if not emu.startswith(("fceux", "fceu")):
            continue
        ext = Path(pub.get("local_movie") or "").suffix.lower()
        if ext not in (".fm2", ".fcm", ".fm3"):
            continue
        sha1 = R.norm_sha1(pub.get("rom_sha1"))
        if ready_only and not rom_idx.get(sha1):
            continue
        try:
            results.append(convert_pub(pub["id"], lib=lib, out_dir=out_dir,
                                       bizhawk_version=bizhawk_version, core=core))
        except ConversionError as e:
            results.append({"pub_id": pub["id"], "game": pub.get("game"),
                            "error": str(e)})
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("inspect", help="解析电影并报告（不写盘）")
    pi.add_argument("--pub", required=True)
    pi.add_argument("--lib", default=None)
    pc = sub.add_parser("convert", help="转换单条 → _converted/<plat>/<id>.bk2")
    pc.add_argument("--pub", required=True)
    pc.add_argument("--lib", default=None)
    pc.add_argument("--out", default=None, help="输出目录（默认 lib/_converted/<plat>）")
    pc.add_argument("--bizhawk-version", default="2.8")
    pc.add_argument("--core", default="auto",
                    help="auto=照抄同 ROM 原生片的核心（查不到退回 NesHawk）；也可显式给核心名")
    pa = sub.add_parser("convert-all", help="批量转换 FCEUX 出版物")
    pa.add_argument("--lib", default=None)
    pa.add_argument("--all", action="store_true", help="含无本地 ROM 的（默认只转有 ROM 的）")
    pa.add_argument("--bizhawk-version", default="2.8")
    pa.add_argument("--core", default="auto")
    pa.add_argument("--out", default=None, help="输出目录（默认 lib/_converted/<plat>，须显式才动库内件）")
    args = ap.parse_args()

    from . import registry as R
    lib = Path(args.lib or R.DEFAULT_LIB)

    if args.cmd == "inspect":
        pubs = {p["id"]: p for p in R.load_publications(lib)}
        if args.pub not in pubs:
            print(f"未知出版物 id: {args.pub}", file=sys.stderr)
            return 1
        src = lib / pubs[args.pub]["local_movie"]
        m = parse_movie(src)
        print(json.dumps({
            "pub_id": args.pub, "game": pubs[args.pub].get("game"),
            "source_format": m.source_format, "n_frames": m.n_frames,
            "md5": m.md5, "author": m.author, "port0": m.port0, "port1": m.port1,
            "pal": m.pal, "fds": m.fds, "rerecord": m.rerecord,
            "errors": m.errors, "warnings": m.warnings,
            "first_frame": sorted(m.frames[0]["p1"]) if m.frames else [],
        }, ensure_ascii=False, indent=1))
        return 0 if not m.errors else 2

    if args.cmd == "convert":
        try:
            r = convert_pub(args.pub, lib=lib, out_dir=args.out,
                            bizhawk_version=args.bizhawk_version, core=args.core)
        except ConversionError as e:
            print(f"转换失败: {e}", file=sys.stderr)
            return 2
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0

    if args.cmd == "convert-all":
        results = convert_all(lib=lib, ready_only=not args.all,
                              bizhawk_version=args.bizhawk_version, core=args.core,
                              out_dir=args.out)
        okc = sum(1 for r in results if "out" in r)
        err = sum(1 for r in results if "error" in r)
        print(json.dumps(results, ensure_ascii=False, indent=1))
        print(f"\n转换成功 {okc} | 失败 {err} | 共 {len(results)}", file=sys.stderr)
        return 0 if err == 0 else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())