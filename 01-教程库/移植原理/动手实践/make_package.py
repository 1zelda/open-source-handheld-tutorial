import hashlib
import json
import os
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = r"F:\开源掌机教程\_scratch\port_build"
STAGE = os.path.join(HERE, "package", "fbcheck")

os.makedirs(HERE, exist_ok=True)
if os.path.isdir(os.path.join(HERE, "package")):
    shutil.rmtree(os.path.join(HERE, "package"))
os.makedirs(STAGE, exist_ok=True)
shutil.copy(os.path.join(BUILD, "fbcheck.c"), os.path.join(HERE, "fbcheck.c"))
shutil.copy(os.path.join(BUILD, "fbcheck_a64_musl_static"),
            os.path.join(STAGE, "fbcheck_a64_musl_static"))
shutil.copy(os.path.join(BUILD, "fbcheck_armv7_musl_static"),
            os.path.join(STAGE, "fbcheck_armhf_musl_static"))

info = json.load(open(os.path.join(HERE, "port.json"), encoding="utf-8"))
ROOT = ["version", "name", "items", "items_opt", "attr"]
ATTR = ["title", "desc", "inst", "genres", "porter", "image", "rtr", "exp",
        "runtime", "min_glibc", "reqs", "arch"]
print("port.json 顶层键齐全:", all(k in info for k in ROOT), list(info))
print("attr 键齐全:", all(k in info["attr"] for k in ATTR),
      "缺失:", [k for k in ATTR if k not in info["attr"]])
print("items 里的 .sh:", [i for i in info["items"] if i.lower().endswith(".sh")])

zip_path = os.path.join(HERE, "package", "fbcheck.zip")
if os.path.exists(zip_path):
    os.remove(zip_path)
with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(os.path.join(HERE, "fbcheck.sh"), "fbcheck.sh")
    for name in sorted(os.listdir(STAGE)):
        z.write(os.path.join(STAGE, name), "fbcheck/" + name)

print()
print("打包结果")
for f in [zip_path]:
    b = open(f, "rb").read()
    print("  %-34s %d B = %.1f KiB  sha256=%s" %
          (os.path.basename(f), len(b), len(b) / 1024,
           hashlib.sha256(b).hexdigest()[:16]))
with zipfile.ZipFile(zip_path) as z:
    for i in z.infolist():
        print("  内层 %-34s %d B" % (i.filename, i.file_size))
