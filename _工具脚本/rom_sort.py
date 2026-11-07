#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把你自己的 dump 归到 ArkOS/dArkOS 能识别的 /roms/<目录> 里。

分类依据按可靠性从高到低:
  1) 命令行 --system 路径=平台   (人工指定, 最可靠, 光盘镜像必须用它)
  2) 文件头 magic                (卡带类决定性证据)
  3) 扩展名且全局唯一归属         (由 rom目录对照表.tsv 现算, .zip 这种共用 87 个目录的直接排除)
  4) .zip/.7z 时递归看包内第一个文件
  都不成立 -> 落到 _待确认/, 报告里写清为什么。

不会删原文件; 同名光盘文件(.cue/.bin/.sub 或 .m3u)会跟着主文件走同一个目录。

用法:
  py -3 _工具脚本/rom_sort.py --input "D:/我的dump" --output "04-游戏资源库/自己ROM放这里/整理结果" --dry-run
  py -3 _工具脚本/rom_sort.py --input "E:/psx盘"=psx --input "E:/dc盘"=dreamcast --output ...
"""
import argparse
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_TSV = os.path.join(ROOT, "04-游戏资源库", "自己ROM放这里", "rom目录对照表.tsv")
SEVENZ = os.path.expanduser("~/.qoder/bin/7zr.exe")

# (说明, 偏移, 前缀字节, 目标 ArkOS 目录)  偏移 None = 在文件头 512 字节内任意位置搜索
MAGICS = [
    ("NES iNES", 0, b"NES\x1a", "nes"),
    ("GB/GBC 任天堂logo", 0x104,
     b"\xCE\xED\x66\x66\xCC\x0D\x00\x0B\x03\x73\x00\x83\x00\x0C\x00\x0D"
     b"\x00\x08\x11\x1F\x88\x89\x00\x0E\xDC\xCC\x6E\xE6\xDD\xDD\xD9\x99"
     b"\xBB\xBB\x67\x63\x6E\x0E\xEC\xCC\xDD\xDC\x99\x9F\xBB\xB9\x33\x3E", None),
    ("GBA 任天堂logo", None,
     b"\x24\xFF\xBA\x6C\xC0\xDF\x11\xE9\xA4\x44\x72\x00\x53\x39\xA4\x1E", "gba"),
    ("Mega Drive", 0x100, b"SEGA ", None),
    ("N64 (z64 大端)", 0, b"\x80\x37\x12\x40", "n64"),
    ("N64 (v64 交叉)", 0, b"\x40\x12\x37\x80", "n64"),
    ("N64 (n64 小端)", 0, b"\x27\x05\x6C\x06", "n64"),
]

# 这些后缀虽然在前端某个系统里"合法", 但用户 dump 目录里出现它们基本是截图/源码/媒体,
# 按后缀归类会把一堆 png 塞进 pico-8/carts, 所以强制不看后缀(要归档请自己按需搬)。
NON_ROM_EXTS = {"png", "jpg", "jpeg", "gif", "bmp", "mp4", "avi", "mkv", "mov", "webm",
                "mp3", "ogg", "wav", "flac", "exe", "dll", "so", "jar", "apk", "txt", "md",
                "xml", "json", "html", "ini", "cfg", "conf", "sym", "map", "lang", "lua",
                "py", "js", "c", "h", "cpp", "sh", "bat", "gz", "bz2", "xz", "rar", "db"}
SKIP_EXT = {"txt", "md", "xml", "json", "ini", "cfg", "conf", "sym", "map", "db", "log",
            "gz", "bz2", "xz", "rar", "lang", "lua", "py", "js", "c", "h", "cpp", "nfo"}



def md5(path, limit=None):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        if limit:
            h.update(fh.read(limit))
            return h.hexdigest()
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# 这些后缀在 ArkOS 里同时挂在多个 system 下(都是同一硬件家族的变体目录),
# 归属其实没有歧义, 直接归一到主目录。目标不存在于对照表时会被丢弃并打印。
CANON = {
    "smc": "sfc", "sfc": "sfc", "fig": "sfc", "bs": "satellaview",
    "pce": "pcengine", "sgx": "supergrafx",
    "z64": "n64", "v64": "n64", "n64": "n64",
    "gb": "gb", "gbc": "gbc", "gba": "gba",
    "ngp": "ngp", "ngc": "ngpc",
    "ws": "wonderswan", "wsc": "wonderswancolor",
    "nds": "nds", "min": "pokemonmini", "tic": "tic80", "uze": "uzebox",
    "lnx": "atarilynx", "a78": "atari7800", "a26": "atari2600",
    "gg": "gamegear", "sms": "mastersystem", "md": "megadrive", "gen": "megadrive",
}


def load_map():
    """返回 (扩展名->唯一目录, 全部目录名集合)"""
    if not os.path.exists(MAP_TSV):
        sys.exit("x 缺 %s, 先跑 py -3 _工具脚本/gen_rom_dirs.py" % MAP_TSV)
    exts, folders = {}, set()
    with open(MAP_TSV, encoding="utf-8") as fh:
        for line in fh.readlines()[1:]:
            p = line.rstrip("\n").split("\t")
            if len(p) < 6 or p[0] != "ArkOS":
                continue
            folders.add(p[1])
            for e in p[5].split():
                exts.setdefault(e, set()).add(p[1])
    uniq = {e: next(iter(v)) for e, v in exts.items() if len(v) == 1}
    for e, target in CANON.items():
        if target in folders:
            uniq[e] = target
        else:
            print("! 同族归一目标 %s 不在对照表里, 忽略 .%s" % (target, e))
    return uniq, folders, exts


def sniff(path, uniq, ext_of):
    """返回 (目录, 依据, 还需人工确认的子类型提示)"""
    with open(path, "rb") as fh:
        head = fh.read(0x200)
        fh.seek(0x100)
        at100 = fh.read(0x20)
    for name, off, sig, folder in MAGICS:
        if sig == b"SEGA ":
            if at100.startswith((b"SEGA MEGA DRIVE", b"SEGA GENESIS", b"SEGA GA")):
                return folder or "megadrive", "magic: " + name, ""
            if at100.startswith((b"SEGA MARK III",)):
                return "mastersystem", "magic: " + name, ""
            if at100.startswith((b"SEGACD1", b"T Sega CD")):
                return "segacd", "magic: " + name, ""
            continue
        hit = (head[off:off + len(sig)] == sig) if off else (sig in head)
        if hit:
            if folder is None:  # GB 家族: 用 0x143 bit7 分 GB/GBC
                with open(path, "rb") as f2:
                    f2.seek(0x143)
                    flag = f2.read(1)
                if flag and flag[0] & 0x80:
                    return "gbc", "magic: " + name + " + 0x143 bit7", ""
                return "gb", "magic: " + name, ""
            return folder, "magic: " + name, ""
    # SNES: 在常见 header 偏移找 0x10 回车 + 校验互补对
    for off in (0x7FC0, 0xFFC0, 0x80C0, 0x100C0, 0xFFD0, 0x80D0):
        try:
            with open(path, "rb") as f:
                f.seek(off)
                h = f.read(0x30)
            if len(h) > 0x1D and h[0x10] == 0x10:
                if h[0x1E] == (h[0x1F] ^ 0xFF) or (h[0x1C] + h[0x1D]) & 0xFF == 0xFF:
                    return "sfc", "magic: SNES header @0x%X" % off, ""
        except OSError:
            pass
    e = ext_of(path)
    if e in uniq and e not in NON_ROM_EXTS:
        return uniq[e], "扩展名归属: ." + e, ""
    return None, "无法判定(扩展名 .%s 被多个平台共用或无 magic)" % e, e


def inner_of(path, uniq, ext_of):
    """压缩包: 看包内第一个文件"""
    e = ext_of(path)
    try:
        if e == "zip":
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if not n.endswith("/")]
                if not names:
                    return None, "zip 内为空", ""
                inner_ext = os.path.splitext(names[0])[1].lstrip(".").lower()
                if inner_ext in uniq and inner_ext not in NON_ROM_EXTS:
                    return uniq[inner_ext], "zip 内首个文件 .%s" % inner_ext, ""
                blob = z.read(names[0])[:0x200]
                for name, off, sig, folder in MAGICS:
                    hit = (blob[off:off + len(sig)] == sig) if off else (sig in blob)
                    if hit:
                        return (folder or "gb"), "zip 内 magic: " + name, ""
                return None, "zip 内文件为 .%s, 该后缀不唯一" % inner_ext, inner_ext
        if e == "7z" and os.path.exists(SEVENZ):
            out = subprocess.run([SEVENZ, "l", "-slt", path], capture_output=True, text=True,
                                 errors="replace").stdout
            m = re.search(r"Name = (.+)$", out, re.M)
            if m:
                inner_ext = os.path.splitext(m.group(1))[1].lstrip(".").lower()
                if inner_ext in uniq and inner_ext not in NON_ROM_EXTS:
                    return uniq[inner_ext], "7z 内首个文件 .%s" % inner_ext, ""
                return None, "7z 内文件为 .%s, 该后缀不唯一" % inner_ext, inner_ext
            return None, "7z 解析失败", ""
    except (zipfile.BadZipFile, OSError) as exc:
        return None, "压缩包打不开: %s" % exc, ""
    return None, "包格式 .%s 本机无法解析, 请用 --system 指定" % e, e


def selftest(uniq):
    """合成文件头, 证明每条 magic 规则的读取逻辑真的会触发(不是文档转述)。"""
    import tempfile
    tmp = tempfile.mkdtemp(prefix="romsort_selftest_")
    ext_of = lambda p: os.path.splitext(p)[1].lstrip(".").lower()

    def make(name, size, patches):
        buf = bytearray(size)
        for off, data in patches:
            buf[off:off + len(data)] = data
        p = os.path.join(tmp, name)
        open(p, "wb").write(bytes(buf))
        return p

    logo = next(s for n, o, s, f in MAGICS if n.startswith("GB/GBC"))
    gba_sig = next(s for n, o, s, f in MAGICS if n.startswith("GBA"))
    cases = [
        (make("t.nes", 0x200, [(0, b"NES\x1a" + bytes(12))]), "nes"),
        (make("t.gb", 0x200, [(0x104, logo)]), "gb"),
        (make("t2.gb", 0x200, [(0x104, logo), (0x143, b"\xC0")]), "gbc"),
        (make("x.gba", 0x200, [(0xC0, gba_sig)]), "gba"),
        (make("x.bin", 0x200, [(0x100, b"SEGA MEGA DRIVE\x00")]), "megadrive"),
        (make("x.sms", 0x200, [(0x100, b"SEGA MARK III\x00")]), "mastersystem"),
        (make("x.z64", 0x200, [(0, b"\x80\x37\x12\x40")]), "n64"),
        (make("x.sfc", 0xFFE0, [(0xFFC0 + 0x10, b"\x10"), (0xFFC0 + 0x1E, b"\xAA\x55")]), "sfc"),
    ]
    bad = 0
    probe = os.path.join(tmp, "probe.bin")  # .bin 不唯一归属, 逼 sniff 只能靠 magic
    for path, want in cases:
        shutil.copy2(path, probe)
        got, why, _ = sniff(probe, uniq, ext_of)
        ok = got == want and why.startswith("magic")
        bad += 0 if ok else 1
        print("  %s %-12s -> %-12s %s" % ("OK " if ok else "FAIL", want, got, why))
    shutil.rmtree(tmp, ignore_errors=True)
    print("自测: %d/%d 通过" % (len(cases) - bad, len(cases)))
    return bad


def main():
    ap = argparse.ArgumentParser(description="按 ArkOS 目录归类自己的 ROM dump")
    ap.add_argument("--input", action="append", default=[],
                    help="输入路径, 可写 路径=平台 强制指定")
    ap.add_argument("--output")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="只跑合成文件头自测")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    uniq, folders, all_exts = load_map()
    if args.selftest:
        sys.exit(1 if selftest(uniq) else 0)
    if not args.input or not args.output:
        sys.exit("用法: --input 路径[=平台] --output 目录   (或 --selftest)")
    forced, inputs = {}, []
    for spec in args.input:
        if "=" in spec:
            p, s = spec.rsplit("=", 1)
            if s not in folders:
                sys.exit("x 目录 %s 不在 ArkOS 的 134 个 /roms/ 目录里, 见对照表" % s)
            forced[os.path.abspath(p)] = s
        inputs.append(spec.rsplit("=", 1)[0])

    os.makedirs(args.output, exist_ok=True)
    items, seen = [], {}
    for base in inputs:
        if os.path.isfile(base):
            filelist = [base]
        elif os.path.isdir(base):
            filelist = [os.path.join(dp, fn) for dp, _, fs in os.walk(base) for fn in sorted(fs)]
        else:
            print("x 输入不存在: %s" % base)
            continue
        force = forced.get(os.path.abspath(base))
        for src in filelist:
            fn = os.path.basename(src)
            if fn.startswith("."):
                continue
            if os.path.splitext(fn)[1].lstrip(".").lower() in SKIP_EXT:
                continue
            if args.limit and len(items) >= args.limit:
                break
            rel = os.path.relpath(os.path.dirname(src), base)
            if rel == ".":
                rel = ""
            size = os.path.getsize(src)
            digest = md5(src)
            if digest in seen:
                items.append({"src": src, "fn": fn, "rel": rel, "size": size, "digest": digest,
                              "folder": None, "why": "跳过: 与 %s 内容相同(去重)" % seen[digest],
                              "dup": True})
                continue
            seen[digest] = fn
            ext = os.path.splitext(fn)[1].lstrip(".").lower()
            if force:
                folder, why = force, "--system 人工指定: " + force
            else:
                folder, why, _ = sniff(src, uniq, lambda p: os.path.splitext(p)[1].lstrip(".").lower())
                if folder is None and ext in ("zip", "7z"):
                    folder, why, _ = inner_of(src, uniq,
                                              lambda p: os.path.splitext(p)[1].lstrip(".").lower())
            items.append({"src": src, "fn": fn, "rel": rel, "size": size, "digest": digest,
                          "folder": folder, "why": why, "dup": False})

    # 第二阶段: 同目录同名的兄弟文件(.cue/.bin/.sub、.chd/.m3u)跟着已判定的那一个走,
    # 否则光盘镜像会被拆开, 到了机器上就读不出来。
    by_stem = {}
    for it in items:
        if it["folder"] and not it["dup"]:
            by_stem[(os.path.dirname(it["src"]).lower(),
                     os.path.splitext(it["fn"])[0].lower())] = it["folder"]
    sidecar = 0
    for it in items:
        if it["folder"] is None and not it["dup"]:
            k = (os.path.dirname(it["src"]).lower(), os.path.splitext(it["fn"])[0].lower())
            if k in by_stem:
                it["folder"] = by_stem[k]
                it["why"] += " | 同名主文件已判定, 跟随"
                sidecar += 1

    rows, counts, written = [], {}, set()
    for it in items:
        if it["dup"]:
            rows.append((it["src"], it["size"], it["digest"], "-", it["why"], ""))
            continue
        folder = it["folder"] or "_待确认"
        dest_dir = os.path.join(args.output, "roms", folder, it["rel"])
        dest = os.path.join(dest_dir, it["fn"])
        if dest in written:  # 同名不同内容: 用上级目录名区分, 绝不静默覆盖
            base_, ext_ = os.path.splitext(it["fn"])
            tag = os.path.basename(it["rel"].rstrip("/")) or "dup"
            dest = os.path.join(dest_dir, "%s [%s]%s" % (base_, tag, ext_))
        written.add(dest)
        counts[folder] = counts.get(folder, 0) + 1
        rows.append((it["src"], it["size"], it["digest"], folder, it["why"], dest))
        if not args.dry_run:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(it["src"], dest)

    rep = os.path.join(args.output, "整理报告.tsv")
    with open(rep, "w", encoding="utf-8", newline="") as fh:
        fh.write("源文件\t字节\tMD5\t归类目录\t判定依据\t目标\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")

    n_dup = sum(1 for it in items if it["dup"])
    print("\n%s: 处理 %d 个文件, 合计 %.2f GB (其中去重跳过 %d 个, 同名跟随 %d 个)" %
          ("预演" if args.dry_run else "已复制", len(items), sum(r[1] for r in rows) / 1e9,
           n_dup, sidecar))
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print("   %-14s %d" % (k, v))
    print("报告: %s" % rep)


if __name__ == "__main__":
    main()
