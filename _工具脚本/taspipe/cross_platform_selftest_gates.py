# -*- coding: utf-8 -*-
"""33 条跨平台（SNES/GBA/GB/MD/PCE/PS1/ARCADE_FBNEO）自检闸门独立模块与自动注入器。

保存位置：F:\\开源掌机教程\\_工具脚本\\taspipe\\cross_platform_selftest_gates.py
运行方式（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.cross_platform_selftest_gates          # 独立跑 33 条跨平台自检断言
  py -3 -u -m taspipe.cross_platform_selftest_gates --inject # 自动将本模块挂载进 selftest.py 尾部并跑全量自检
"""
import argparse
import gzip
import hashlib
import json
import struct
import sys
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw

from . import detect
from . import movie_converters as MC
from . import retro_platforms as RP
from . import universal_authoring as UA
from .schema import CheckSpec, SchemaError, Verdict
import tas_replay

PASS = 0


def _ok(cond, msg, ok_fn=None):
    global PASS
    if ok_fn is not None:
        return ok_fn(cond, msg)
    if not cond:
        raise AssertionError(msg)
    PASS += 1
    print(f"  [{PASS}] {msg}")


def _raises(fn, msg, raises_fn=None, ok_fn=None):
    if raises_fn is not None:
        return raises_fn(fn, msg)
    try:
        fn()
    except SchemaError:
        _ok(True, msg, ok_fn)
        return
    raise AssertionError(f"应抛 SchemaError: {msg}")


def run_cross_platform_gates(ok_fn=None, raises_fn=None):
    """执行全部 33 条跨平台闸门断言（支持独立运行或挂载进 selftest.py 共享计数器）。"""
    # 1..8 多平台手柄按键与别名解析闸门
    snes_m = RP.parse_platform_macro("SNES", "LT+Y,RT+X,L+R,Select+Start,A+B")
    _ok(snes_m == "Left+Y,Right+X,L+R,Select+Start,A+B",
        "跨平台宏 [1/33]: SNES X/Y/L/R 与 LT/RT 别名正常展开", ok_fn)

    md_m = RP.parse_platform_macro("MD", "D,D+R,R+A,B+C,X+Y+Z,M")
    _ok(md_m == "Down,Down+Right,Right+A,B+C,X+Y+Z,Mode",
        "跨平台宏 [2/33]: MD 6 键手柄 A/B/C/X/Y/Z 与 Mode 别名正常展开", ok_fn)

    ps1_m = RP.parse_platform_macro("PS1", "Tr+O,X+Sq,L1+R1,L2+R2,Start")
    _ok(ps1_m == "Triangle+Circle,Cross+Square,L1+R1,L2+R2,Start",
        "跨平台宏 [3/33]: PS1 Triangle/Circle/Cross/Square 及肩键正常展开", ok_fn)

    arc_m = RP.parse_platform_macro("ARCADE_FBNEO", "Coin,,Start,,D,D+R,R+A,B+C+D")
    _ok(arc_m == "Coin,,Start,,Down,Down+Right,Right+A,B+C+D",
        "跨平台宏 [4/33]: 街机 FBNeo Coin/Start/A/B/C/D 正常展开", ok_fn)

    gba_m = RP.parse_platform_macro("GBA", "U+B,L+R,A,Select")
    _ok(gba_m == "Up+B,L+R,A,Select",
        "跨平台宏 [5/33]: GBA L/R 肩键与 Up+B 组合正常展开", ok_fn)

    _raises(lambda: RP.parse_platform_macro("NES", "Right+X"),
            "跨平台宏 [6/33]: NES 平台混入 X 键必抛 SchemaError", raises_fn, ok_fn)

    _raises(lambda: RP.parse_platform_macro("GBA", "B+C"),
            "跨平台宏 [7/33]: GBA 平台混入 C 键必抛 SchemaError", raises_fn, ok_fn)

    _raises(lambda: RP.get_platform_spec("VIRTUAL_BOY"),
            "跨平台宏 [8/33]: 未知怀旧平台名必抛 SchemaError", raises_fn, ok_fn)

    # 9..14 扩展内存地址空间（24-bit/32-bit）与空格内存域转义
    snes_p = RP.format_platform_patches("SNES", [{"addr": 0x1FFFF, "value": 28, "domain": "WRAM"}])
    _ok(snes_p == "131071:28@WRAM",
        "扩展内存 [9/33]: SNES 0x1FFFF WRAM 顶界地址放行", ok_fn)

    gba_p = RP.format_platform_patches("GBA", [{"addr": "0x3FFFF", "value": 99, "domain": "IWRAM"}])
    _ok(gba_p == "262143:99@IWRAM",
        "扩展内存 [10/33]: GBA 0x3FFFF 十六进制地址解析放行", ok_fn)

    ps1_p = RP.format_platform_patches("PS1", [{"addr": 0x1FFFFF, "value": 1, "domain": "MainRAM"}])
    _ok(ps1_p == "2097151:1@MainRAM",
        "扩展内存 [11/33]: PS1 2MB MainRAM 0x1FFFFF 顶界地址放行", ok_fn)

    md_p = RP.format_platform_patches("MD", [{"addr": 0xFF00, "value": 12, "domain": "68K RAM"}])
    _ok(md_p == "65280:12@68K%20RAM" and " " not in md_p,
        "扩展内存 [12/33]: 含空格内存域 '68K RAM' 按线格式编码为 '68K%20RAM'", ok_fn)

    _raises(lambda: RP.format_platform_patches("NES", [{"addr": 0x10000, "value": 1}]),
            "扩展内存 [13/33]: NES 地址超出 0xFFFF 必抛 SchemaError", raises_fn, ok_fn)

    _raises(lambda: RP.format_platform_patches("SNES", [{"addr": 0x20000, "value": 1}]),
            "扩展内存 [14/33]: SNES 地址超出 0x1FFFF 必抛 SchemaError", raises_fn, ok_fn)

    # 15..18 Lua 模板与多平台录像转换
    _ok("\r" not in tas_replay.STATE_LUA_TMPL and "flushing = {" in tas_replay.STATE_LUA_TMPL,
        "模板与转换 [15/33]: STATE_LUA_TMPL 无字面 CR 且保持 flushing 异步落盘状态机", ok_fn)

    with tempfile.TemporaryDirectory() as td:
        smv_path = Path(td) / "test.smv"
        hdr = bytearray(32)
        hdr[0:4] = b"SMV\x1a"
        struct.pack_into("<IIII", hdr, 4, 1, 0, 5, 2)
        struct.pack_into("<BBBB", hdr, 20, 0x01, 0, 0x01, 0)
        struct.pack_into("<II", hdr, 24, 32, 32)
        body = struct.pack("<HHH", 0, 0x4008, 0x8001)
        smv_path.write_bytes(bytes(hdr) + body)
        parsed_smv = MC.parse_smv(smv_path)
        _ok(parsed_smv["n_frames"] == 2
            and parsed_smv["frames"][0]["p1"] == {"Up", "Y"}
            and parsed_smv["frames"][1]["p1"] == {"Right", "B"},
            "模板与转换 [16/33]: Snes9x .smv 帧数与 16-bit 掩码按键精确解析", ok_fn)

        vbm_path = Path(td) / "test.vbm"
        vhdr = bytearray(256)
        vhdr[0:4] = b"VBM\x1a"
        struct.pack_into("<IIII", vhdr, 4, 1, 0, 1, 0)
        struct.pack_into("<BBBB", vhdr, 20, 0, 1, 1, 0)
        struct.pack_into("<II", vhdr, 56, 0, 256)
        vbm_path.write_bytes(bytes(vhdr) + struct.pack("<H", 0x0201))
        parsed_vbm = MC.parse_vbm(vbm_path)
        _ok(parsed_vbm["n_frames"] == 1 and parsed_vbm["frames"][0]["p1"] == {"A", "L"}
            and parsed_vbm["version"] == 1 and parsed_vbm["uid"] == "00000000"
            and parsed_vbm["start_flags"] == 0 and parsed_vbm["controller_flags"] == 1
            and parsed_vbm["system_flags"] == 1 and parsed_vbm["emu_flags"] == 0
            and parsed_vbm["from_savestate"] is False and parsed_vbm["from_sram"] is False
            and parsed_vbm["declared_frames"] == 1
            and parsed_vbm["savestate_offset"] == 0
            and parsed_vbm["controller_data_offset"] == 256
            and parsed_vbm["trailing_bytes"] == 0,
            "模板与转换 [17/33]: VBA .vbm 按 0x3C 偏移精确解析 GBA 帧与肩键", ok_fn)

        bad_smv = Path(td) / "bad.smv"
        bad_smv.write_bytes(b"NOT_A_MOVIE_FILE")
        try:
            MC.parse_smv(bad_smv)
            raise AssertionError("损坏的 .smv 未抛异常")
        except MC.MovieConvertError:
            _ok(True, "模板与转换 [18/33]: 非法 .smv 文件头被 MovieConvertError 拦截", ok_fn)

    # 19..24 多平台 Showcase 知识包 Schema 校验
    def _make_doc(platform, macro, patches=None):
        return {
            "schema_version": 1,
            "kind": "statejump_showcase",
            "game_id": f"test_{platform.lower()}",
            "game_title": f"Test {platform}",
            "platform": platform,
            "rom": "F:/tmp/rom.bin",
            "bizhawk": "F:/tmp/BizHawk",
            "base_state": "F:/tmp/base.state",
            "catalog": {
                "status": "complete",
                "expected_total": 1,
                "sources": ["https://strategywiki.org/"]
            },
            "elements": [{
                "element_id": "el_1",
                "label": "Element 1",
                "kind": "weapon",
                "trigger": {"macro": macro, "extra": 20, "patches": patches or []},
                "detection": {
                    "frame": 10,
                    "success_checks": [{
                        "check_id": "c1",
                        "plugin_id": "frame_region_color_fraction",
                        "params": {"region": [0.2, 0.2, 0.8, 0.8], "rgb": [248, 120, 48], "tol": 24, "min_fraction": 0.01},
                        "required": True
                    }]
                },
                "negative_control": {"macro": None, "patches": patches or []}
            }]
        }

    _ok(RP.validate_multiplatform_showcase(_make_doc("SNES", "X,X,L+R,,,,"))["platform"] == "SNES",
        "多平台包校验 [19/33]: SNES showcase.json 通过校验", ok_fn)

    _ok(RP.validate_multiplatform_showcase(_make_doc("GBA", "Up+B,R,,,,"))["platform"] == "GBA",
        "多平台包校验 [20/33]: GBA showcase.json 通过校验", ok_fn)

    _ok(RP.validate_multiplatform_showcase(
        _make_doc("MD", "Down,Right+C,,Z,,", [{"addr": 0xFF10, "value": 1, "domain": "68K RAM"}])
    )["platform"] == "MD", "多平台包校验 [21/33]: MD showcase.json 通过校验", ok_fn)

    _ok(RP.validate_multiplatform_showcase(_make_doc("ARCADE_FBNEO", "Down,Right+A,C+D,,,"))["platform"] == "ARCADE_FBNEO",
        "多平台包校验 [22/33]: 街机 ARCADE_FBNEO showcase.json 通过校验", ok_fn)

    bad_cat = _make_doc("SNES", "X,,,")
    bad_cat["catalog"]["status"] = "draft"
    _raises(lambda: RP.validate_multiplatform_showcase(bad_cat),
            "多平台包校验 [23/33]: catalog.status != complete 被拒（防半成品冒充全量）", raises_fn, ok_fn)

    bad_frame = _make_doc("GBA", "B,,,")
    bad_frame["elements"][0]["detection"]["frame"] = 24
    _raises(lambda: RP.validate_multiplatform_showcase(bad_frame),
            "多平台包校验 [24/33]: detection.frame 越界必抛 SchemaError", raises_fn, ok_fn)

    # 25..30 正反例像素差分自动标定纯函数闸门
    with tempfile.TemporaryDirectory() as td:
        pos_dir = Path(td) / "pos"
        neg_dir = Path(td) / "neg"
        pos_dir.mkdir()
        neg_dir.mkdir()
        for i in range(8):
            im_n = Image.new("RGB", (256, 224), (16, 24, 40))
            im_n.save(neg_dir / f"f{i:04d}.png")
            im_p = Image.new("RGB", (256, 224), (16, 24, 40))
            if i == 5:
                dr = ImageDraw.Draw(im_p)
                dr.rectangle([100, 90, 150, 130], fill=(248, 136, 48))
            im_p.save(pos_dir / f"f{i:04d}.png")

        cal = UA.calibrate_element_detector(pos_dir, neg_dir)
        _ok(cal["frame"] == 5,
            "自动标定 [25/33]: 正反例逐帧差分准确锁定峰值帧 f0005", ok_fn)

        rx0, ry0, rx1, ry1 = cal["region"]
        _ok(0.01 <= rx0 < rx1 <= 0.99 and 0.01 <= ry0 < ry1 <= 0.99,
            "自动标定 [26/33]: 归一化 region 落在 [0.01, 0.99] 安全界内", ok_fn)

        r_c, g_c, b_c = cal["rgb"]
        _ok(abs(r_c - 248) <= 8 and abs(g_c - 136) <= 8 and abs(b_c - 48) <= 8,
            "自动标定 [27/33]: 特效主色簇聚类 RGB 准确还原 (248, 136, 48)", ok_fn)

        _ok(cal["neg_fraction"] == 0.0 and 0.003 <= cal["min_fraction"] < cal["pos_fraction"],
            "自动标定 [28/33]: min_fraction 在正例与反例之间留有充足安全余量", ok_fn)

        spec = CheckSpec(
            check_id="cal_verify",
            plugin_id="frame_region_color_fraction",
            params={
                "region": cal["region"],
                "rgb": cal["rgb"],
                "tol": cal["tol"],
                "min_fraction": cal["min_fraction"]
            },
            required=True
        )
        res_pos = detect.run_check(spec, str(pos_dir / "f0005.png"))
        res_neg = detect.run_check(spec, str(neg_dir / "f0005.png"))
        _ok(res_pos.verdict == Verdict.PASS and res_neg.verdict == Verdict.FAIL,
            "自动标定 [29/33]: 标定参数经 detect.run_check 复核满足正例 PASS 且反例 FAIL", ok_fn)

        try:
            UA.calibrate_element_detector(neg_dir, neg_dir)
            raise AssertionError("正反例完全相同却未报错")
        except RuntimeError:
            _ok(True, "自动标定 [30/33]: 正反例无视觉差异时强制抛 RuntimeError 拦截假宏", ok_fn)

    with tempfile.TemporaryDirectory() as td:
        save = bytearray(128 * 1024)
        save[123:127] = b"SRAM"
        payload = gzip.compress(bytes(MC.VBM_BATTERY_HEADER_SIZE) + bytes(save), mtime=0)
        vhdr = bytearray(256)
        vhdr[0:4] = b"VBM\x1a"
        struct.pack_into("<IIII", vhdr, 4, 1, 0, 1, 0)
        struct.pack_into("<BBBB", vhdr, 20, 2, 1, 1, 0)
        struct.pack_into("<II", vhdr, 24, 0, 65536)
        struct.pack_into("<II", vhdr, 56, 256, 256 + len(payload))
        sram_path = Path(td) / "sram.vbm"
        sram_path.write_bytes(bytes(vhdr) + payload + struct.pack("<H", 0))
        parsed_sram = MC.parse_vbm(sram_path)
        conversion_error = ""
        try:
            MC.write_multiplatform_bk2(parsed_sram, Path(td) / "bad.bk2")
            raise AssertionError("SRAM 起始 VBM 缺 CoreState 却未拦截")
        except MC.MovieConvertError as exc:
            conversion_error = str(exc)
        _ok(parsed_sram["from_sram"] is True
            and parsed_sram["save_data"] == bytes(save)
            and parsed_sram["save_sha256"] == hashlib.sha256(save).hexdigest()
            and "CoreState" in conversion_error,
            "VBM 起始数据 [31/33]: 解出 128KB SRAM 且缺 CoreState 时拒绝降级开机直放", ok_fn)

        short_path = Path(td) / "short.vbm"
        short = bytearray(vhdr)
        short[20] = 0
        struct.pack_into("<I", short, 12, 2)
        struct.pack_into("<II", short, 56, 0, 256)
        short_path.write_bytes(bytes(short) + struct.pack("<H", 0))
        try:
            MC.parse_vbm(short_path)
            raise AssertionError("截断 VBM 未抛异常")
        except MC.MovieConvertError as exc:
            _ok("截断" in str(exc), "VBM 起始数据 [32/33]: 声明帧数超过实际输入体时强制拦截", ok_fn)

        sensor_path = Path(td) / "sensor.vbm"
        sensor = bytearray(vhdr)
        sensor[20] = 0
        struct.pack_into("<I", sensor, 12, 1)
        struct.pack_into("<II", sensor, 56, 0, 256)
        sensor_path.write_bytes(bytes(sensor) + struct.pack("<H", 0x1010))
        parsed_sensor = MC.parse_vbm(sensor_path)
        sensor_error = ""
        try:
            MC.write_multiplatform_bk2(parsed_sensor, Path(td) / "sensor.bk2")
            raise AssertionError("动作传感器输入未拦截")
        except MC.MovieConvertError as exc:
            sensor_error = str(exc)
        _ok(parsed_sensor["frames"][0]["p1"] == {"Right"}
            and parsed_sensor["sensor_frame_count"] == 1
            and parsed_sensor["sensor_bitmask"] == 0x1000
            and "传感器" in sensor_error,
            "VBM 起始数据 [33/33]: 传感器位可盘点但转换不得静默丢弃", ok_fn)


def inject_into_selftest():
    """自动把 run_cross_platform_gates 挂载进同目录 selftest.py（幂等，不重复追加）。"""
    st_path = Path(__file__).resolve().parent / "selftest.py"
    if not st_path.is_file():
        raise SystemExit(f"未找到 {st_path}")
    text = st_path.read_text(encoding="utf-8")
    hook = "from .cross_platform_selftest_gates import run_cross_platform_gates"
    if hook not in text:
        marker = 'if __name__ == "__main__":'
        addition = (
            "\ndef test_cross_platform_30():\n"
            "    from .cross_platform_selftest_gates import run_cross_platform_gates\n"
            "    run_cross_platform_gates(ok_fn=ok, raises_fn=raises)\n\n\n"
        )
        if marker in text:
            text = text.replace(marker, addition + marker)
            # 在 SELFTEST OK 打印前插入调用
            text = text.replace(
                'print(f"SELFTEST OK {PASS}/{PASS}")',
                'test_cross_platform_30()\n    print(f"SELFTEST OK {PASS}/{PASS}")'
            )
            st_path.write_text(text, encoding="utf-8")
            print("[已注入] selftest.py 已挂载 test_cross_platform_30()（+33 项跨平台闸门）")
        else:
            print("[跳过] 未在 selftest.py 中定位到 __main__ 入口")
    else:
        print("[幂等跳过] selftest.py 已包含跨平台 30 项闸门")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inject", action="store_true", help="自动挂载进 selftest.py")
    args = ap.parse_args()
    if args.inject:
        inject_into_selftest()
    run_cross_platform_gates()
    print(f"CROSS_PLATFORM_SELFTEST OK {PASS}/{PASS}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
