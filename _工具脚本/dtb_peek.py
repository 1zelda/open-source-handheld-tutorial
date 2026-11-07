#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""最小 DTB 解析器: 打印 .dtb 的节点树与属性(含 display-timings 数值)。

为什么要自己写: 上游只给编译好的 .dtb, 没有 .dts 源码; 而"这块板子到底什么屏、
什么接口"全藏在 dtb 里。标准 dtc 在 Windows 上通常没装, 所以用这个只读解析器。

用法:
  py -3 _工具脚本/dtb_peek.py <路径.dtb> [路径2.dtb ...]
  py -3 _工具脚本/dtb_peek.py <路径.dtb> --grep timing
"""
import io
import struct
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DTS_MAGIC = 0xD00DFEED


class Reader:
    def __init__(self, buf):
        self.b = buf
        self.pos = 0

    def u32(self):
        v = struct.unpack_from(">I", self.b, self.pos)[0]
        self.pos += 4
        return v

    def bytes(self, n):
        v = self.b[self.pos:self.pos + n]
        self.pos += n
        return v

    def zstr(self):
        end = self.b.index(b"\0", self.pos)
        s = self.b[self.pos:end].decode("utf-8", "replace")
        self.pos = end + 1
        return s


def align4(r):
    while r.pos % 4:
        r.pos += 1


def parse(buf):
    r = Reader(buf)
    magic, totalsize, off_dt, off_str, _, _ = (r.u32() for _ in range(6))
    if magic != DTS_MAGIC:
        raise SystemExit("不是合法 DTB (magic=%08x)" % magic)
    r.pos = off_dt
    strings = buf[off_str:totalsize]

    def cstr(off):
        end = strings.index(b"\0", off)
        return strings[off:end].decode("utf-8", "replace")

    depth = 0
    stack = []

    def walk():
        nonlocal depth
        while True:
            tag = r.u32()
            if tag == 1:                      # FDT_BEGIN_NODE
                name = r.zstr()
                align4(r)
                stack.append(name)
                yield ("/" + "/".join(x for x in stack if x), depth)
                depth += 1
            elif tag == 2:                    # FDT_END_NODE
                depth -= 1
                stack.pop()
            elif tag == 3:                    # FDT_PROP
                length = r.u32()
                nameoff = r.u32()
                val = r.bytes(length)
                align4(r)
                yield (cstr(nameoff), val, stack[-1] if stack else "")
            elif tag == 4:                    # FDT_NOP
                continue
            elif tag == 9:                    # FDT_END
                return
            else:
                raise SystemExit("未知 tag %d @%d" % (tag, r.pos))

    return list(walk()), strings


# 这些属性在 DTB 里一定是数值 cell, 即使字节里含 0x00 也要按整数解
NUMERIC = {"hactive", "vactive", "clock-frequency", "hfront-porch", "hsync-len",
           "hback-porch", "vfront-porch", "vsync-len", "vback-porch", "width-mm",
           "height-mm", "reg", "phandle", "linux,phandle", "interrupts", "#address-cells",
           "#size-cells", "#interrupt-cells", "native-mode", "reset-gpios", "enable-gpios",
           "bus-width", "max-cur-supply-uA", "dcdc-switch-freq", "compatible"}


def decode(prop, val):
    if prop == "name" or len(val) == 0:
        return None
    if len(val) % 4 == 0 and len(val) <= 32 and (b"\x00" not in val or prop in NUMERIC):
        if prop != "compatible":
            ints = struct.unpack(">%dI" % (len(val) // 4), val)
            if not any(i > 1 << 30 for i in ints):
                return " ".join(str(i) for i in ints)
    printable = all(32 <= c < 127 or c == 0 for c in val)
    if printable:
        return val.split(b"\0")[0].decode("ascii", "replace")
    return val[:24].hex()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    grep = ""
    if "--grep" in sys.argv:
        grep = sys.argv[sys.argv.index("--grep") + 1]
    if not args:
        raise SystemExit(__doc__)

    for path in args:
        with open(path, "rb") as fh:
            buf = fh.read()
        items, _ = parse(buf)
        print("=" * 70)
        print(path)
        print("=" * 70)
        node = ""
        for item in items:
            if len(item) == 2:
                node, depth = item
                if grep and grep.lower() not in node.lower():
                    continue
                print("  " * depth + node)
            else:
                prop, val, parent = item
                if grep and grep.lower() not in parent.lower() and grep.lower() not in node.lower():
                    continue
                d = decode(prop, val)
                if d is not None:
                    print("      %s = %s" % (prop, d))


if __name__ == "__main__":
    main()
