#!/usr/bin/env python3
"""列出镜像里第一个 FAT32 分区（BOOT）的根目录文件——用来核实"刷完卡后 Windows 能看到什么"。
用法: py -3 _工具脚本/列出BOOT分区.py <img或img前缀文件>
"""
import sys, struct

def rd(f, off, n):
    f.seek(off); return f.read(n)

def main(path):
    with open(path, 'rb') as f:
        mbr = rd(f, 0, 512)
        parts = []
        for i in range(4):
            e = mbr[0x1BE + i*16: 0x1BE + (i+1)*16]
            typ = e[4]
            lba = struct.unpack('<I', e[8:12])[0]
            sectors = struct.unpack('<I', e[12:16])[0]
            if typ and lba:
                parts.append((i+1, hex(typ), lba, sectors))
        print("分区表:")
        for p in parts:
            print("  p%d type=%s start_lba=%d sectors=%d (字节偏移 %d, %.2f GB)" %
                  (p[0], p[1], p[2], p[3], p[2]*512, p[3]*512/1024**3))
        if not parts:
            print("  没找到 DOS 分区表（可能是纯 GPT 镜像）"); return
        fat_parts = [p for p in parts if int(p[1], 16) in (0x0b, 0x0c, 0x06, 0x07, 0x0e)]
        if not fat_parts:
            print("  第一个分区不是 FAT，跳过解析"); return
        base = fat_parts[0][2] * 512
        bs = rd(f, base, 512)
        bps = struct.unpack('<H', bs[11:13])[0]
        spc = bs[13]
        reserved = struct.unpack('<H', bs[14:16])[0]
        nfats = bs[16]
        huge = struct.unpack('<I', bs[32:36])[0]
        fatsz = struct.unpack('<I', bs[36:40])[0]
        rootcl = struct.unpack('<I', bs[44:48])[0]
        print("\nFAT32: 扇区大小=%d 每簇扇数=%d 保留扇数=%d FAT数=%d 总扇数=%d FAT大小=%d 根簇=%d"
              % (bps, spc, reserved, nfats, huge, fatsz, rootcl))
        fat_off = base + reserved * bps
        clu_bytes = spc * bps

        def chain(cl):
            out = []
            while 2 <= cl < 0x0FFFFFF8:
                out.append(cl)
                ent = struct.unpack('<I', rd(f, fat_off + cl*4, 4))[0] & 0x0FFFFFFF
                cl = ent
            return out

        root = chain(rootcl)
        data0 = fat_off + fatsz * nfats * bps   # cluster 2 起点
        names = []
        frags = []
        for cl in root:
            off = data0 + (cl - 2) * clu_bytes
            blob = rd(f, off, clu_bytes)
            for j in range(0, clu_bytes, 32):
                ent = blob[j:j+32]
                if ent[0] == 0x00 or ent[0] == 0xE5:
                    continue
                if ent[11] == 0x0F:      # 长文件名片段（同一文件的片段逆序存放）
                    u = ent[1:11] + ent[14:26] + ent[28:32]
                    try:
                        frags.insert(0, u.decode('utf-16-le', 'ignore').replace('\x00', ''))
                    except Exception:
                        pass
                    continue
                size = struct.unpack('<I', ent[28:32])[0]
                long_name = ''.join(frags)
                if not long_name:   # 纯 8.3 短名（boot.ini / Image 这类）
                    s = ent[0:8].rstrip(b' ').decode('cp437', 'replace')
                    x = ent[8:11].rstrip(b' ').decode('cp437', 'replace')
                    long_name = (s + ('.' + x if x and x != ' ' else '')).lower()
                names.append((long_name, size, ent[11] == 0x10))
                frags = []
        print("\n根目录条目:")
        tot = 0
        for nm, size, is_dir in names:
            if not nm:
                continue
            print("  %-40s %12d B  %.2f MB%s" % (nm, size, size/1024/1024, '   <目录>' if is_dir else ''))
            tot += size
        print("合计 %d 个条目, %.1f MB" % (len(names), tot/1024/1024))

if __name__ == '__main__':
    main(sys.argv[1])
