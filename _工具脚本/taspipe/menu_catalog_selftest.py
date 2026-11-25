"""menu_catalog 的离线最小自检；不启动模拟器。"""
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

from . import menu_catalog as MC
from .schema import SchemaError


def main():
    checks = []

    def ok(name, condition):
        checks.append({"name": name, "pass": bool(condition)})

    macro = MC.build_macro(["Start", "A", "A"], gap=16, tail=40)
    tokens = macro.split(",")
    ok("macro 帧数与键位顺序", len(tokens) == 92 and tokens[0] == ""
       and [tokens[i] for i in (17, 34, 51)] == ["Start", "A", "A"]
       and all(t == "" for t in tokens[52:]))
    for bad in ([], ["Start", ""], "Start"):
        try:
            MC.build_macro(bad)
            rejected = False
        except SchemaError:
            rejected = True
        ok(f"拒绝非法菜单序列 {bad!r}", rejected)
    try:
        MC.build_macro(["A"], gap=-1)
        rejected = False
    except SchemaError:
        rejected = True
    ok("拒绝负 key_gap", rejected)

    nav_group = {"id": "red", "slot_addr": 78429, "menu_steps": ["Start", "A", "A"],
                 "navigate": {"columns": 2, "start_id": 0, "row_step": "Down",
                              "column_step": "Right", "confirm": "A"}}
    nav_tokens = {value: [token for token in MC.selection_macro(nav_group, value, "EWRAM")[0].split(",") if token]
                  for value in (1, 2, 3)}
    ok("导航宏按两列生成且不写槽位", nav_tokens == {
        1: ["Start", "A", "A", "Right", "A"],
        2: ["Start", "A", "A", "Down", "A"],
        3: ["Start", "A", "A", "Down", "Right", "A"],
    } and MC.selection_macro(nav_group, 3, "EWRAM")[1] == [])
    first_group = {"id": "ability", "slot_addr": None, "slot_readback": False,
                   "menu_steps": ["Start", "A"],
                   "navigate": {"columns": 2, "start_id": 1, "row_step": "Down",
                                "column_step": "Right", "confirm": "A"}}
    first_tokens = [token for token in MC.selection_macro(first_group, 1, "EWRAM")[0].split(",") if token]
    ok("导航可从 start_id 本身开始", first_tokens == ["Start", "A", "A"]
       and MC.selection_macro(first_group, 1, "EWRAM")[1] == [])

    config_path = Path(__file__).resolve().parent / "校准配方" / "castlevania_aria_gba.menu_catalog_nav_probe.json"
    config = MC.load_config(config_path)
    ok("导航探针配置通过生产加载器", len(config["groups"]) == 3
       and {g["id"]: g["slot_addr"] for g in config["groups"]} ==
       {"red": 78429, "blue": 78430, "yellow": 78431}
       and all(g.get("navigate") for g in config["groups"]))
    base = MC.base_state_path(config)
    ok("基态经状态仓解析且哈希存在", base.is_file() and len(MC.sha256(base)) == 64)

    with tempfile.TemporaryDirectory(prefix="menu_catalog_selftest_") as td:
        root = Path(td)
        rows = []
        for index in range(2):
            shot = root / f"shot_{index}.png"
            Image.new("RGB", (240, 160), (index * 100, 20, 30)).save(shot)
            rows.append({"group_id": "red", "id": index + 1, "readback": index + 1, "shot": str(shot)})
        sheet = root / "sheet.png"
        MC.contact_sheet(rows, sheet)
        with Image.open(sheet) as image:
            ok("联系表按真实截图生成", image.size == (1920, 326))
        identity = root / "identity.png"
        identity_sha = MC.identity_crop(rows[0]["shot"], [0, 0, 12, 12], identity)
        with Image.open(identity) as image:
            ok("身份区域裁剪保存且哈希可复算", image.size == (12, 12)
               and identity_sha == MC.sha256(identity))
        try:
            MC.identity_crop(rows[0]["shot"], [0, 0, 999, 999], root / "bad.png")
            rejected = False
        except SchemaError:
            rejected = True
        ok("拒绝越界身份区域", rejected)
        bad_config = root / "bad_config.json"
        bad_doc = json.loads(config_path.read_text(encoding="utf-8"))
        bad_doc["groups"][0]["identity_region"] = [9, 9, 2, 2]
        bad_config.write_text(json.dumps(bad_doc), encoding="utf-8")
        try:
            MC.load_config(bad_config)
            rejected = False
        except SchemaError:
            rejected = True
        ok("加载期拒绝非法身份区域", rejected)
        ability_doc = json.loads(config_path.read_text(encoding="utf-8"))
        ability_doc["groups"] = [{
            "id": "ability", "slot_addr": None, "slot_readback": False, "count": 8,
            "menu_steps": ["Start", "Down", "Down", "Down", "Down", "A"],
            "identity_region": [8, 80, 232, 130],
            "base_patches": [{"addr": 78726 + index, "value": 255} for index in range(4)],
            "navigate": {"columns": 2, "start_id": 1, "row_step": "Down",
                         "column_step": "Right", "confirm": "A"},
        }]
        ability_config = root / "ability_config.json"
        ability_config.write_text(json.dumps(ability_doc, ensure_ascii=False), encoding="utf-8")
        loaded = MC.load_config(ability_config)
        ok("无装备槽菜单允许显式关闭回读", loaded["groups"][0]["slot_addr"] is None
           and loaded["groups"][0]["slot_readback"] is False
           and len(loaded["groups"][0]["base_patches"]) == 4)
        ability_doc["groups"][0]["slot_readback"] = True
        ability_config.write_text(json.dumps(ability_doc, ensure_ascii=False), encoding="utf-8")
        try:
            MC.load_config(ability_config)
            rejected = False
        except SchemaError:
            rejected = True
        ok("开启回读时拒绝缺失槽位", rejected)
        ability_doc["groups"][0]["slot_readback"] = False
        ability_doc["groups"][0]["base_patches"][0]["value"] = 256
        ability_config.write_text(json.dumps(ability_doc, ensure_ascii=False), encoding="utf-8")
        try:
            MC.load_config(ability_config)
            rejected = False
        except SchemaError:
            rejected = True
        ok("拒绝越界开荒补丁", rejected)

    failed = [row["name"] for row in checks if not row["pass"]]
    report = {"status": "pass" if not failed else "failed", "checks": len(checks), "failed": failed,
              "rows": checks}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
