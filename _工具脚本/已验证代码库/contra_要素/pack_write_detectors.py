"""把标定结果写回 contra_weapons.showcase.json：检测帧 + 互斥判据 + 实测证据串。"""
import json
from pathlib import Path

PACK = Path(r"F:\开源掌机教程\_工具脚本\taspipe\游戏包\contra_weapons.showcase.json")
RULES = Path(r"F:/taspipe_scratch/detector_final.json")

doc = json.loads(PACK.read_text(encoding="utf-8"))
rules = json.loads(RULES.read_text(encoding="utf-8"))["elements"]

# 实测峰值（pack_calib 逐帧数据），写进包里当标定证据，免得下次还要重跑模拟器
PEAK = {
    "default_rifle":    "muzzle 白 0.0272 / 暖 0.0000（步枪弹头纯白，五枪里唯一暖色恒 0）",
    "machine_gun_m":    "muzzle 暖 0.0061、mid 0.0073、far 0.0083，upper/lower 恒 0（水平连射，不展开）",
    "fire_thrower_f":   "upper 暖 0.0092、lower 0.0109、far 0.0611、muzzle 0.0224（唯一上下都扫到的抛物线）",
    "spread_gun_s":     "muzzle 暖 0.0163 > mid 0.0073，upper 0.0050/lower 0.0059（近端扇形，射程短）",
    "laser_gun_l":      "far 暖 0.1000、muzzle 0.0816，upper/lower 恒 0（伸得最远的平直光束）",
}
NEGMAX = {e: "空按对照 5 区域暖/白占比全为 0.0000（写 0x00AA 不改变静止画面）"
            for e in rules}

for el in doc["elements"]:
    eid = el["element_id"]
    r = rules[eid]
    el["detection"]["frame"] = r["detection_frame"]
    el["detection"]["success_checks"] = r["success_checks"]
    el["calibration"] = {
        "measured_peaks": PEAK[eid],
        "negative_control": NEGMAX[eid],
        "cross_check": "五枪判据在彼此选定帧上互斥（逐帧命中表见 detector_final.json 同源数据）",
        "sampled": "2026-11-14 由 contra_u_c9ea66bb/r20261114T043740 base_state + 本包 trigger 宏逐帧采集",
    }

PACK.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("写回", PACK)
for el in doc["elements"]:
    print(f"  {el['element_id']:18s} frame={el['detection']['frame']:3d} "
          f"checks={len(el['detection']['success_checks'])}")
