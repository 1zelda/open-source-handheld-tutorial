"""枚举核对：把网盘清单复制一份、只把成品移植游戏库那两行 enable 改成 1，喂给生产函数
read_manifest() + walk()，看它们真能数出多少个文件、多少字节。
生产清单一个字节不动；临时副本放 %TEMP%，跑完删。

跑法：py -3 -X utf8 _工具脚本/_probe_netdisk_scope.py
"""
import csv
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import netdisk_upload as N

WANT = ("成品移植游戏库整仓bundle", "成品移植游戏库成品包", "自制产物")

src = N.MANIFEST
with io.open(src, encoding="utf-8-sig", newline="") as fh:
    rows = list(csv.DictReader(fh, delimiter="\t"))
    fields = rows[0].keys() if rows else []

tmp = os.path.join(tempfile.gettempdir(), "_网盘清单探针.tsv")
with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(fields), delimiter="\t")
    w.writeheader()
    for r in rows:
        if r["name"].strip() in WANT:
            r["enable"] = "1"
        w.writerow(r)

N.MANIFEST = tmp
try:
    scopes = N.read_manifest()
    print("read_manifest 给出 %d 档：%s" % (len(scopes), "、".join(s["name"] for s in scopes)))
    print("每档的键：%s" % sorted(scopes[0].keys()))
    for s in scopes:
        mount = s.get("mount") or s.get("mountpoint") or "/本地暂存"
        pairs = N.walk(s, mount)
        total = sum(os.path.getsize(lp) for lp, _rp in pairs)
        print("  %s → %d 个文件 / %.2f GB（include=%s）"
              % (s["name"], len(pairs), total / 1073741824.0, s["include"]))
finally:
    os.remove(tmp)
    print("临时副本已删：%s 存在=%s" % (tmp, os.path.exists(tmp)))
