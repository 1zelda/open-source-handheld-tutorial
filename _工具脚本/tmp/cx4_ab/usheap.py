# -*- coding: utf-8 -*-
""".NET 元数据堆读取（ECMA-335 II.24）：BizHawk 固件表的字面量在 #US 堆里，UTF-16LE。

ASCII 字节扫描会 0 命中（11-23 踩过：'CX4' ascii=0 / utf16=1），所以固件文案与
固件表三元组（文件名, 描述, SHA1）只能按 #US 堆逐条解出来、再按索引看邻居。
"""
import struct


def heap_map(blob):
    i = blob.find(b"BSJB")
    if i < 0:
        raise ValueError("不是 .NET 程序集")
    vl = struct.unpack_from("<I", blob, i + 12)[0]      # VersionLength 在 +12（实测布局）
    p = i + 16 + vl                                     # Version 串之后是 Flags(2)+Streams(2)
    n_streams = struct.unpack_from("<H", blob, p + 2)[0]
    q = p + 4
    out = {}
    for _ in range(n_streams):
        off, size = struct.unpack_from("<II", blob, q)
        q += 8
        name_start = q
        name = b""
        while blob[q] != 0:
            name += bytes([blob[q]])
            q += 1
        q = name_start + ((len(name) + 1 + 3) // 4) * 4   # 堆名按 4 字节对齐
        out[name.decode("latin1")] = (i + 0x14 + off, size)  # 实测：偏移以 +20 为基
    return out


def strings(blob, name="#US"):
    """解出指定堆的条目列表。#US 是 UTF-16LE + 变长前缀；#Strings 是 ASCII。"""
    off, size = heap_map(blob)[name]
    out, p, end = [], off, off + size
    while p < end:
        n = blob[p]
        if n == 0:
            p += 1
            continue
        if name == "#US":
            ln = struct.unpack_from("<I", blob, p)[0] & 0x1FFFFFFF if n & 0x80 else n
            p += 4 if n & 0x80 else 1
        else:
            ln = n
            p += 1
        if p + ln > len(blob):
            break
        raw = blob[p:p + ln]
        p += ln
        if name == "#US":
            body = raw[:-1]                      # ECMA：长度含 1 个多余终止字节
            if len(body) % 2:
                body += b"\x00"
            out.append(body.decode("utf-16-le", "replace"))
        else:
            out.append(raw.decode("latin1"))
    return out
