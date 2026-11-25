# -*- coding: utf-8 -*-
"""把 BizHawk 存档（.m11 = zip，成员里 Core.bin / Framebuffer.bmp 又是 zstd 帧）解到最底层再比。

为什么必须有这一件：ab9 的 L 组「差异字节 109,853 / 122,062」是在 deflate 解压层比的，
而那一层字节还是 zstd 容器——压缩容器对上层任何一次落盘顺序都敏感，拿它当尺子会把
噪声读成信号。本件解到真实状态字节，再用同一对配对重算对照与处理两组数。

zstd 解码走本机现成的 libzstd.dll（BizHawk 自带），不装任何 Python 包。
"""
import ctypes
import glob
import os
import struct
import sys
import zipfile

SCR = r"F:\taspipe_scratch\cx4_ab"
ZDLL = os.path.join(SCR, "bizhawk", "dll", "libzstd.dll")
if not os.path.exists(ZDLL):
    ZDLL = r"C:\ProgramData\chocolatey\bin\libzstd.dll"
_z = ctypes.WinDLL(ZDLL)
_z.ZSTD_isError.restype = ctypes.c_uint
_z.ZSTD_getErrorName.restype = ctypes.c_char_p
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


def zstd(src, cap=1 << 26):
    """BizHawk 用流式压缩，帧头里没有内容长度（ZSTD_findDecompressedSize 返回 -1），
    所以只能给足目的缓冲、拿返回值当真实长度。"""
    if src[:4] != ZSTD_MAGIC:
        return src                       # 已经是裸数据，直接返回
    while True:
        dst = ctypes.create_string_buffer(cap)
        got = _z.ZSTD_decompress(dst, cap, src, len(src))
        if not _z.ZSTD_isError(got):
            return dst.raw[:got]
        if cap >= (1 << 30):
            raise RuntimeError("zstd 解码失败: %s" % _z.ZSTD_getErrorName(got))
        cap *= 4


def parts(state_path):
    z = zipfile.ZipFile(state_path)
    out = {}
    for i in z.infolist():
        if i.filename in ("Core.bin", "Framebuffer.bmp", "Input Log.txt",
                          "BizVersion.txt", "BizState 1.0"):
            out[i.filename] = zstd(z.read(i.filename))
    return out


def load():
    d = {}
    for p in glob.glob(os.path.join(SCR, "*", "*.m11")):
        d[(os.path.basename(os.path.dirname(p)),
           os.path.splitext(os.path.basename(p))[0])] = parts(p)
    return d


def bytediff(x, y):
    n = min(len(x), len(y))
    offs = [i for i in range(n) if x[i] != y[i]]
    runs = 1 + sum(1 for i in range(1, len(offs)) if offs[i] != offs[i - 1] + 1)
    return {"len_x": len(x), "len_y": len(y), "diff": len(offs), "runs": runs,
            "first": offs[:8], "head_x": x[:16].hex(" "), "head_y": y[:16].hex(" ")}


def main():
    F = load()
    print("解到最底层的状态数=", len(F), flush=True)
    print("\n=== 成员真实尺寸（L1_none s30000）")
    for k, v in F[("L1_none", "s30000")].items():
        print("   %-16s %9d  %s" % (k, len(v), v[:24]))

    print("\n=== 恒量反证格：都无固件、不同进程、同一帧(60)")
    ctl = [(("c1_same_proc", "s60_a"), ("c1_same_proc", "s60_b")),
           (("c1_same_proc", "s60_a"), ("c2_new_proc", "s60")),
           (("c2_new_proc", "s60"), ("c3_new_proc2", "s60")),
           (("n0_none", "s60"), ("c3_new_proc2", "s60")),
           (("L1_none", "s60"), ("n0_none", "s60")),
           (("st1_none", "snap"), ("n0_none", "s60"))]
    for a, b in ctl:
        d = bytediff(F[a]["Core.bin"], F[b]["Core.bin"])
        fb = F[a]["Framebuffer.bmp"] == F[b]["Framebuffer.bmp"]
        print("   %-22s vs %-20s 状态差异字节=%-6d 段=%-4d 帧缓冲相同=%s 尺寸=%d/%d"
              % ("/".join(a), "/".join(b), d["diff"], d["runs"], fb,
                 d["len_x"], d["len_y"]), flush=True)

    print("\n=== 处理：放 32K 假固件（4 种文件名）vs 不放")
    for t, kk in [("n1_bare_cx4rom", "s60"), ("n2_db_name", "s60"),
                  ("n3_both", "s60"), ("n4_wrong_len", "s60"),
                  ("st2_cx4rom_32k_CD", "snap"), ("st3_cx4rom_1k", "snap")]:
        base = "st1_none" if t.startswith("st") else "n0_none"
        d = bytediff(F[(base, "s60" if base == "n0_none" else "snap")][ "Core.bin"],
                     F[(t, kk)]["Core.bin"])
        print("   %-20s vs %-16s 状态差异字节=%-6d 段=%-4d 帧缓冲相同=%s"
              % (t, base, d["diff"], d["runs"],
                 F[(base, "s60" if base == "n0_none" else "snap")]["Framebuffer.bmp"]
                 == F[(t, kk)]["Framebuffer.bmp"]), flush=True)

    print("\n=== L 组：空 vs 32K 假固件，逐标记（解到最底层）")
    for m in ["s60", "s10000", "s20000", "s30000"]:
        a, b = ("L1_none", m), ("L2_dummy32k", m)
        d = bytediff(F[a]["Core.bin"], F[b]["Core.bin"])
        print("   %-8s 状态差异字节=%-7d 段=%-5d 帧缓冲相同=%s 帧缓冲尺寸=%d/%d 输入日志相同=%s"
              % (m, d["diff"], d["runs"],
                 F[a]["Framebuffer.bmp"] == F[b]["Framebuffer.bmp"],
                 len(F[a]["Framebuffer.bmp"]), len(F[b]["Framebuffer.bmp"]),
                 F[a]["Input Log.txt"] == F[b]["Input Log.txt"]), flush=True)

    out = os.path.join(SCR, "out_fb_decoded")
    os.makedirs(out, exist_ok=True)
    for (arm, mk), v in sorted(F.items()):
        if arm.startswith("L") and mk in ("s10000", "s20000", "s30000"):
            open(os.path.join(out, "%s_%s.bmp" % (arm, mk)), "wb").write(v["Framebuffer.bmp"])
    print("\n帧缓冲(BMP)导出到", out, "共", len(os.listdir(out)), "张")
    for f in sorted(os.listdir(out)):
        b = open(os.path.join(out, f), "rb").read(26)
        w, h = struct.unpack("<ii", b[18:26])
        print("   %-24s sig=%s %dx%d 字节=%d" % (f, b[:2], w, abs(h),
                                                os.path.getsize(os.path.join(out, f))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
