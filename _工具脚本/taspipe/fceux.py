# -*- coding: utf-8 -*-
"""T2：FCEUX .fm2/.fcm/.fm3 → BizHawk .bk2 转换（镜像 BizHawk 2.8 Fm2Import/FcmImport）。

为什么逐行直转帧对齐：FCEUX 与 BizHawk 都是「每个模拟帧一条输入（含 lag 帧）」。
FCEUX src/movie.cpp 的 currFrameCounter++ 在 FCEUMOV_AddInputState 末尾无条件执行
（src/input.cpp FCEU_UpdateInput 每帧调用），录制时每帧 push 一条记录；BizHawk bk2
 likewise 每帧一行。故 fm2 行数 == 模拟帧数 == bk2 行数，无需插 lag 帧。
（已核 FCEUX 源码与 BizHawk 2.8 Fm2Import.cs/FcmImport.cs 参考实现。）

映射：
  * 按钮序 fm2 RLDUTSBA → bk2 UDLRTSBA（Start=T / Select=S 两边一致）。
  * 命令字段 fm2 0/1/2 → bk2 ../.r/p.（NesHawk LogKey=#Power|Reset，小写 p/r）。
  * romChecksum(base64 MD5) → Header MD5；SHA1 由出版物 rom_sha1 注入。
  * port0/port1 → SyncSettings.Controls 与 LogKey 的 P1/P2 列。

残留 desync 风险（BizHawk 官方导入器同样丢弃，必须实测回放验证、不打包票）：
  NewPPU / RAMInitOption / RAMInitSeed 标志、FCEUX vs NesHawk 核心时序差异。
  StartsFromSavestate=1 的电影不支持（与 BizHawk 导入器一致）。

运行（生产路径，配合 registry）:
  python -m taspipe.fceux inspect --pub 3232        # 解析+报告，不写盘
  python -m taspipe.fceux convert --pub 3232        # 写 _converted/<plat>/<id>.bk2
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

NESSYNC_TYPE = ("BizHawk.Emulation.Cores.Nintendo.NES.NES+NESSyncSettings, "
                "BizHawk.Emulation.Cores")


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
    pos += 4                                           # savestate offset
    first_frame = struct.unpack_from("<I", data, pos)[0]; pos += 4
    m.md5 = data[pos:pos + 16].hex(); pos += 16
    pos += 4                                           # emu version
    end = data.index(b"\x00", pos)
    m.game_name = data[pos:end].decode("utf-8", "replace"); pos = end + 1
    end = data.index(b"\x00", pos)
    m.author = data[pos:end].decode("utf-8", "replace"); pos = end + 1

    pos = first_frame
    p1, p2 = set(), set()
    reset = False
    power = False
    frame = 1
    players = {1: p1, 2: p2}

    def append():
        cmd = "power" if power else ("reset" if reset else "")
        m.frames.append(_frame(cmd, p1, p2))

    while frame <= frame_count and pos < len(data):
        update = data[pos]; pos += 1
        delta = (update >> 5) & 3
        gap = 0
        for b in range(delta):
            gap += data[pos] << (b * 8); pos += 1
        frame += gap
        for _ in range(gap):
            append()
            reset = False
            power = False
        if (update >> 7) & 1:                          # 控制命令
            command = update & 0x1F
            reset = command == 1
            if command == 2:
                reset = True
                if frame != 1:
                    power = True
            elif command in (7, 8):
                m.warnings.append(f"VS System 命令 {command} 未支持（帧 {frame}）")
            elif command in (24, 25, 26):
                m.fds = True
                m.warnings.append(f"FDS 命令 {command} 未支持（帧 {frame}）")
            elif command not in (0, 1, 2):
                m.warnings.append(f"未知控制命令 {command}（帧 {frame}）")
            if not reset and frame == 1:
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
        append()
        reset = False
        power = False
    if not m.frames:
        m.errors.append("未解析到任何输入帧")
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


def _render_player(pressed):
    return "".join(BK2_MNEMONIC[b] if b in pressed else "." for b in BK2_ORDER)


def to_bk2(m, out_path, sha1=None, game_name=None, author=None, bizhawk_version="2.8"):
    """写 BizHawk .bk2（zip）。返回写入路径。m.errors 非空则拒绝。"""
    if m.errors:
        raise ConversionError("; ".join(m.errors))
    if m.fourscore:
        raise ConversionError("fourscore（四手柄）电影未支持")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    two_player = m.port1 == 1

    header = ["MovieVersion BizHawk v2.0",
              f"Author {author or m.author or 'default user'}",
              f"emuVersion Version {bizhawk_version}",
              "Platform NES",
              f"GameName {game_name or m.game_name or 'NES game'}"]
    if sha1:
        header.append(f"SHA1 {sha1.strip().upper()}")
    if m.md5:
        header.append(f"MD5 {m.md5}")
    header.append("Core NesHawk")
    header.append(f"rerecordCount {m.rerecord}")
    if m.fds:
        header.append("BoardName FDS")

    logkey = ("LogKey:#Power|Reset|#P1 Up|P1 Down|P1 Left|P1 Right|"
              "P1 Start|P1 Select|P1 B|P1 A|")
    if two_player:
        logkey += ("#P2 Up|P2 Down|P2 Left|P2 Right|"
                   "P2 Start|P2 Select|P2 B|P2 A|")
    log = ["[Input]", logkey]
    for fr in m.frames:
        cmd = ("p" if fr["cmd"] == "power" else ".") + ("r" if fr["cmd"] == "reset" else ".")
        line = f"|{cmd}|{_render_player(fr['p1'])}|"
        if two_player:
            line += f"{_render_player(fr['p2'])}|"
        log.append(line)
    log.append("[/Input]")

    comments = [f"Movie origin .{m.source_format} (taspipe.fceux convert)",
                f"Emulation origin FCEUX/FCEU emuVersion={m.header.get('emuversion', '?')}"]
    for k in ("newppu", "raminitoption", "raminitseed"):
        if k in m.header:
            comments.append(f"{k} {m.header[k]} (未映射到 NesHawk；desync 风险，须实测)")
    if m.pal:
        comments.append("PAL 电影：RegionOverride=0 自动判区，须实测确认时序")
    comments.extend(m.warnings)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Header.txt", "\n".join(header) + "\n")
        z.writestr("Input Log.txt", "\n".join(log) + "\n")
        z.writestr("SyncSettings.json", json.dumps(_sync_settings(m.port0, m.port1)))
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


def convert_pub(pub_id, lib=None, out_dir=None, bizhawk_version="2.8"):
    """转换单条出版物。走 registry 索引定位电影与 ROM；写 _converted/<plat>/<id>.bk2。"""
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
    out = Path(out_dir) if out_dir else lib / "_converted" / plat
    out_path = out / f"{pub_id}.bk2"
    to_bk2(m, out_path, sha1=sha1, game_name=pub.get("game"),
           bizhawk_version=bizhawk_version)
    return {
        "pub_id": pub_id, "game": pub.get("game"), "source": str(src),
        "source_format": m.source_format, "n_frames": m.n_frames,
        "rom_sha1": sha1, "rom_match": rom_match, "md5_check": md5_check,
        "out": str(out_path), "warnings": m.warnings,
        "two_player": m.port1 == 1,
    }


def convert_all(lib=None, ready_only=True, bizhawk_version="2.8"):
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
            results.append(convert_pub(pub["id"], lib=lib,
                                       bizhawk_version=bizhawk_version))
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
    pa = sub.add_parser("convert-all", help="批量转换 FCEUX 出版物")
    pa.add_argument("--lib", default=None)
    pa.add_argument("--all", action="store_true", help="含无本地 ROM 的（默认只转有 ROM 的）")
    pa.add_argument("--bizhawk-version", default="2.8")
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
                            bizhawk_version=args.bizhawk_version)
        except ConversionError as e:
            print(f"转换失败: {e}", file=sys.stderr)
            return 2
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0

    if args.cmd == "convert-all":
        results = convert_all(lib=lib, ready_only=not args.all,
                              bizhawk_version=args.bizhawk_version)
        okc = sum(1 for r in results if "out" in r)
        err = sum(1 for r in results if "error" in r)
        print(json.dumps(results, ensure_ascii=False, indent=1))
        print(f"\n转换成功 {okc} | 失败 {err} | 共 {len(results)}", file=sys.stderr)
        return 0 if err == 0 else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())