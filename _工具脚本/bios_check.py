#!/usr/bin/env python3
"""扫描本地 BIOS 目录,输出文件名/大小/MD5/SHA1,方便与模拟器期望值对照。
用法: python _工具脚本/bios_check.py [目录]   默认扫描 ./03-BIOS库
"""
import hashlib, os, sys, json, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

TARGET = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "03-BIOS库")
EXTS = {".bin", ".exe", ".dat", ".stg", ".bmp", ".irx", ".pup", ".keys", ".cia", ".nds", ".ser", ".sgx", ".rom", ".prg", ".img"}
SKIP_NAMES = {"readme.md", "license", "license.txt"}

def digest(path):
    h5, hs = hashlib.md5(), hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h5.update(chunk); hs.update(chunk)
    return h5.hexdigest(), hs.hexdigest(), os.path.getsize(path)

rows = []
for root, _, files in os.walk(TARGET):
    for name in files:
        if name.lower() in SKIP_NAMES:
            continue
        if name.lower().endswith(tuple(e.lower() for e in EXTS)):
            p = os.path.join(root, name)
            try:
                md5, sha1, size = digest(p)
            except OSError as e:
                print(f"[跳过] {p}: {e}"); continue
            rows.append({"file": os.path.relpath(p, TARGET), "size": size, "md5": md5, "sha1": sha1})

if not rows:
    print("未发现任何 BIOS 文件。把你手头的 .bin / PSX.EXE / flash0 文件放进 03-BIOS库/<平台>/ 后重跑。")
    print("(说明:README.md 之类说明文档会被自动排除,只有 BIOS 相关文件参与统计。)")
    sys.exit(0)

for r in sorted(rows, key=lambda x: x["file"].lower()):
    print(f"{r['file']:<48} {r['size']:>10} B  md5={r['md5']}")

out = os.path.join(TARGET, "_bios_inventory.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False, indent=2)
print(f"\n共 {len(rows)} 个文件,清单已写入 {out}")
print("下一步:打开对应模拟器的 Settings → BIOS 页面,把它列出的期望 MD5 和上面这行比对。")
