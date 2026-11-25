# -*- coding: utf-8 -*-
"""任务A 独立验收测试：作弊候选无损解析 / 安全分类 / 完整检索。

只使用临时目录合成 .cht，不碰生产游戏包、原始作弊文件、模拟器、网络。
运行：py -3 -u -m taspipe.cheat_candidate_selftest
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from . import retro_cheat_runner as R
from . import statejump as SJ
from .schema import SchemaError

RESULTS = []
_OK_FN = None


def check(name, cond, detail=""):
    if _OK_FN is not None:
        _OK_FN(bool(cond), name if cond else f"{name} | {detail}")
        return
    RESULTS.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f" | {detail}" if detail and not cond else ""))


def write_cht(root, name, entries, extra=()):
    lines = [f"cheats = {len(entries)}"]
    for i, e in enumerate(entries):
        for k, v in e.items():
            lines.append(f'cheat{i}_{k} = "{v}"')
    lines.extend(extra)
    p = root / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def codes_of(entries):
    return [p.get("value") for e in entries for p in e["patches"]]


def t_value_width(root):
    p = write_cht(root, "Width (USA).cht", [
        {"desc": "Infinite Energy 999", "address": "170", "value": "999"},
        {"desc": "Infinite Energy neg", "address": "170", "value": "-1"},
        {"desc": "Infinite Energy wide", "code": "1234:ABCD"},
        {"desc": "Infinite Energy 255", "address": "170", "value": "255"},
        {"desc": "Infinite Energy 256", "address": "170", "value": "256"},
    ])
    es = R.parse_libretro_cht(p, platform="NES")
    check("A1 value999 不截断", es[0]["compile_status"] == "blocked" and es[0]["patches"] == []
          and es[0]["raw_fields"]["value"] == "999"
          and any(b["code"] == "value_exceeds_byte" for b in es[0]["blockers"]), str(es[0]))
    check("A2 value-1 不变255", es[1]["patches"] == [] and -1 not in codes_of(es)
          and 255 not in codes_of([es[1]])
          and any(b["code"] == "negative_value" for b in es[1]["blockers"]), str(es[1]))
    check("A3 1234:ABCD 不变205", es[2]["patches"] == [] and 205 not in codes_of(es)
          and es[2]["raw_fields"]["code"] == "1234:ABCD", str(es[2]))
    check("A4 255 边界可候选", es[3]["compile_status"] == "candidate"
          and es[3]["patches"][0]["value"] == 255
          and es[3]["patches"][0]["domain"] == "libretro_system_ram_offset", str(es[3]))
    check("A5 256 阻塞", es[4]["patches"] == [] and es[4]["compile_status"] == "blocked", str(es[4]))
    es_np = R.parse_libretro_cht(p)
    check("A6 无平台内存偏移不执行", all(e["patches"] == [] for e in es_np)
          and any(b["code"] == "platform_unproven" for b in es_np[3]["blockers"]), "")


def t_compound(root):
    p = write_cht(root, "Compound (USA).cht", [
        {"desc": "All Weapons half", "code": "006B:1C+ZZZZ:99"},
        {"desc": "All Weapons full", "code": "006B:1C+006C:28"},
        {"desc": "All Weapons mixed", "code": "006B:1C+CBAA-4704"},
    ])
    es = R.parse_libretro_cht(p, platform="NES")
    check("A7 复合码半截不输出", es[0]["patches"] == [] and es[0]["compile_status"] == "blocked"
          and len(es[0]["code_parts"]) == 2 and es[0]["compound"] is True, str(es[0]))
    check("A8 复合码全支持才候选", es[1]["compile_status"] == "candidate"
          and [q["addr"] for q in es[1]["patches"]] == [0x6B, 0x6C]
          and [q["value"] for q in es[1]["patches"]] == [0x1C, 0x28], str(es[1]))
    check("A9 复合混加密码整条阻塞", es[2]["patches"] == [] and es[2]["code_type"] == "compound_mixed", str(es[2]))


def t_encoded(root):
    p = write_cht(root, "Encoded (USA).cht", [
        {"desc": "Infinite Energy gg", "code": "SXIO-POVI"},
        {"desc": "Infinite Energy gg6", "code": "SXIPAS"},
        {"desc": "Infinite Energy gs", "code": "01FF99C0"},
        {"desc": "Infinite Energy hex8", "code": "ABCDEF12"},
        {"desc": "Infinite Energy dashed digits", "code": "CBAA-4704"},
    ])
    nes = R.parse_libretro_cht(p, platform="NES")
    check("A10 GameGenie 不当裸写", nes[0]["code_type"] == "game_genie" and nes[0]["patches"] == []
          and nes[1]["code_type"] == "game_genie" and nes[1]["patches"] == [], str(nes[:2]))
    check("A10b 带数字横杠码不猜 GG", nes[4]["patches"] == [] and nes[4]["code_type"] != "game_genie"
          and nes[4]["compile_status"] == "blocked", str(nes[4]))
    gb = R.parse_libretro_cht(p, platform="GB")
    check("A11 GB Gameshark 分类不执行", gb[2]["code_type"] == "gb_gameshark" and gb[2]["patches"] == []
          and any(b["code"] == "gb_gameshark_compile_not_implemented" for b in gb[2]["blockers"]), str(gb[2]))
    np_ = R.parse_libretro_cht(p)
    check("A12 无平台 hex8 不猜 SNES", np_[2]["code_type"] != "snes_par_compact" and np_[2]["patches"] == []
          and np_[3]["patches"] == [] and np_[3]["code_type"] == "encoded_hex8_unproven", str(np_[2:]))
    check("A13 NES 下 hex8 未知编码", nes[3]["patches"] == [] and nes[3]["code_type"] == "encoded_hex8_unknown", str(nes[3]))


def t_snes_domain(root):
    p = write_cht(root, "Snes Domain (USA).cht", [
        {"desc": "Infinite Energy wram", "code": "7E1F99:0F"},
        {"desc": "Infinite Energy rombus", "code": "801F99:0F"},
        {"desc": "Infinite Energy par", "code": "7E0BCF10"},
        {"desc": "Infinite Energy lowbus", "code": "001F99:0F"},
        {"desc": "Infinite Energy wram7f", "code": "7F1F99:0F"},
    ])
    snes = R.parse_libretro_cht(p, platform="SNES")
    check("A14 SNES 7E 段映射域偏移", snes[0]["compile_status"] == "candidate"
          and snes[0]["patches"][0]["addr"] == 0x1F99
          and snes[0]["patches"][0]["domain"] == "snes_wram_offset", str(snes[0]))
    check("A15 SNES ROM 总线不猜", snes[1]["patches"] == []
          and any(b["code"] == "snes_bus_domain_unproven" for b in snes[1]["blockers"]), str(snes[1]))
    check("A16 SNES PAR 紧凑码", snes[2]["compile_status"] == "candidate"
          and snes[2]["patches"][0]["addr"] == 0x0BCF and snes[2]["patches"][0]["value"] == 0x10, str(snes[2]))
    check("A17 SNES 低总线不猜", snes[3]["patches"] == [], str(snes[3]))
    check("A17b SNES 7F  bank=WRAM 高半", snes[4]["compile_status"] == "candidate"
          and snes[4]["patches"][0]["addr"] == 0x11F99, str(snes[4]))
    np_ = R.parse_libretro_cht(p)
    check("A18 无平台不做 SNES 映射", all(e["patches"] == [] for e in np_)
          and np_[0]["patches"] == [] and np_[2]["code_type"] != "snes_par_compact", str(np_[0]))
    nes = R.parse_libretro_cht(p, platform="NES")
    check("A19 NES 不套 SNES 映射", nes[0]["patches"] == []
          and any(b["code"] == "nes_bus_domain_unproven" for b in nes[0]["blockers"]), str(nes[0]))


def t_nes_domain(root):
    p = write_cht(root, "Nes Domain (USA).cht", [
        {"desc": "Infinite Energy ram", "code": "00AA:07"},
        {"desc": "Infinite Energy mirror", "code": "0AAA:07"},
        {"desc": "Infinite Energy badint", "address": "0xZZ", "value": "5"},
    ])
    es = R.parse_libretro_cht(p, platform="NES")
    check("A20 NES RAM 直映", es[0]["compile_status"] == "candidate"
          and es[0]["patches"][0] == {"addr": 0xAA, "value": 7, "domain": "nes_cpu_ram",
                                      "width_bits": 8, "apply": "one_shot_candidate"}, str(es[0]))
    check("A21 NES 镜像段阻塞", es[1]["patches"] == []
          and any(b["code"] == "nes_mirror_unproven" for b in es[1]["blockers"]), str(es[1]))
    check("A22 非法整数给原因", es[2]["patches"] == []
          and any(b["code"] == "invalid_integer" for b in es[2]["blockers"])
          and es[2]["raw_fields"]["address"] == "0xZZ", str(es[2]))


def t_gba_codebreaker(root):
    p = write_cht(root, "GBA CodeBreaker.cht", [
        {"desc": "Have All Items", "code": "42013294+0101+00000010+0002"},
        {"desc": "Have All Equipment", "code": "420132B4+0101+00000034+0002"},
        {"desc": "Complete Soul Set", "code": "4201331C+FFFF+00000032+0002"},
        {"desc": "Stats", "code": "8201327A+270F+3201327C+0050"},
        {"desc": "Slide value increment", "code": "42013310+0001+00010003+0002"},
        {"desc": "Bad domain", "code": "84000000+0001"},
        {"desc": "Odd address step", "code": "42013294+0101+00000002+0001"},
        {"desc": "Zero repetitions", "code": "42013294+0101+00000000+0002"},
        {"desc": "Byte value too wide", "code": "32013294+0101"},
        {"desc": "Conditional compound", "code": "74000130+03B7+32000064+0007"},
        {"desc": "Malformed slide", "code": "42013294+0101+00000010"},
        {"desc": "Excessive repetitions", "code": "42013294+0101+00001001+0002"},
        {"desc": "EWRAM end overflow", "code": "8203FFFF+0001"},
    ])
    es = R.parse_libretro_cht(p, platform="GBA")
    item_patches = es[0]["patches"]
    check("G1 CodeBreaker 物品滑动写逐字节编译", es[0]["compile_status"] == "candidate"
          and len(item_patches) == 32 and [q["addr"] for q in item_patches] == list(range(0x13294, 0x132B4))
          and [q["value"] for q in item_patches] == [1, 1] * 16
          and all(q["domain"] == "EWRAM" and q["write_width_bits"] == 16 for q in item_patches), str(es[0]))
    equipment = es[1]["patches"]
    check("G2 CodeBreaker 装备滑动写边界", es[1]["compile_status"] == "candidate"
          and len(equipment) == 104 and equipment[0]["addr"] == 0x132B4
          and equipment[-1]["addr"] == 0x1331B, str(es[1]))
    souls = es[2]["patches"]
    check("G3 CodeBreaker 全魂滑动写边界", es[2]["compile_status"] == "candidate"
          and len(souls) == 100 and souls[0]["addr"] == 0x1331C
          and souls[-1]["addr"] == 0x1337F and all(q["value"] == 255 for q in souls), str(es[2]))
    check("G4 CodeBreaker 16/8 位复合码全编译", es[3]["compile_status"] == "candidate"
          and len(es[3]["code_parts"]) == 2 and es[3]["compound"] is True
          and [(q["addr"], q["value"]) for q in es[3]["patches"]] == [(0x1327A, 0x0F), (0x1327B, 0x27), (0x1327C, 0x50)], str(es[3]))
    check("G5 CodeBreaker 值增量和地址步长", es[4]["compile_status"] == "candidate"
          and [q["value"] for q in es[4]["patches"]] == [1, 0, 2, 0, 3, 0]
          and [q["addr"] for q in es[4]["patches"]] == [0x13310, 0x13311, 0x13312, 0x13313, 0x13314, 0x13315], str(es[4]))
    check("G6 GBA 非 EWRAM 总线不猜", es[5]["patches"] == []
          and any(b["code"] == "gba_bus_domain_unproven" for b in es[5]["blockers"]), str(es[5]))
    check("G7 半字写奇数步长拒绝", es[6]["patches"] == []
          and any(b["code"] == "gba_codebreaker_slide_step_unproven" for b in es[6]["blockers"]), str(es[6]))
    check("G8 零重复拒绝", es[7]["patches"] == []
          and any(b["code"] == "gba_codebreaker_slide_count_unsafe" for b in es[7]["blockers"]), str(es[7]))
    check("G9 8 位值越界不截断", es[8]["patches"] == []
          and any(b["code"] == "gba_codebreaker_value_too_wide" for b in es[8]["blockers"]), str(es[8]))
    check("G10 条件码复合整条阻塞", es[9]["patches"] == [] and es[9]["compile_status"] == "blocked"
          and any(b["code"] == "gba_codebreaker_opcode_unsupported" for b in es[9]["blockers"]), str(es[9]))
    check("G11 缺行尾的滑动码不输出半截", es[10]["patches"] == []
          and es[10]["compile_status"] == "blocked", str(es[10]))
    check("G12 过量重复拒绝", es[11]["patches"] == []
          and any(b["code"] == "gba_codebreaker_slide_count_unsafe" for b in es[11]["blockers"]), str(es[11]))
    check("G13 EWRAM 末地址跨半字拒绝", es[12]["patches"] == []
          and any(b["code"] == "gba_bus_domain_unproven" for b in es[12]["blockers"]), str(es[12]))
    check("G14 CodeBreaker 补丁全部标为逐帧重写",
          all(q["apply"] == "per_frame" for q in item_patches + equipment + souls), "")
    check("G15 逐帧补丁进入生产 dump 线格式",
          SJ.format_command(1, "dump", frames_dir="C:/fr", extra=1,
                            patches=[{"addr": 1, "value": 2, "apply": "per_frame"}])
          == "1 dump C:/fr - 1 - 1:2 per_frame", "")
    try:
        SJ._patch_mode([{"addr": 1, "value": 2},
                        {"addr": 2, "value": 3, "apply": "per_frame"}])
        mixed_rejected = False
    except SchemaError:
        mixed_rejected = True
    check("G16 一次性与逐帧补丁混用拒绝", mixed_rejected, "")
    try:
        SJ._patch_mode([{"addr": 1, "value": 2, "apply": "sometimes"}])
        unknown_rejected = False
    except SchemaError:
        unknown_rejected = True
    check("G17 未知补丁时序拒绝", unknown_rejected, "")


def t_unknown_fields(root):
    p = write_cht(root, "Unknown (USA).cht", [
        {"desc": "Infinite Energy handler", "address": "170", "value": "7", "handler": "2"},
        {"desc": "Infinite Energy extra", "address": "170", "value": "7", "frobnicate": "1"},
        {"desc": "Infinite Energy be", "address": "170", "value": "7", "big_endian": "true"},
        {"desc": "Infinite Energy ok", "address": "170", "value": "7", "enable": "false"},
    ])
    es = R.parse_libretro_cht(p, platform="NES")
    check("A23 未知 handler 阻塞", es[0]["patches"] == []
          and any(b["code"] == "unknown_handler" for b in es[0]["blockers"]), str(es[0]))
    check("A24 未知字段保留且阻塞", es[1]["patches"] == []
          and es[1]["raw_fields"]["frobnicate"] == "1"
          and any(b["code"] == "unknown_field" for b in es[1]["blockers"]), str(es[1]))
    check("A25 大端阻塞", es[2]["patches"] == []
          and any(b["code"] == "big_endian_unsupported" for b in es[2]["blockers"]), str(es[2]))
    check("A26 enable 原样保留不阻塞", es[3]["compile_status"] == "candidate"
          and es[3]["raw_fields"]["enable"] == "false", str(es[3]))
    p2 = write_cht(root, "Declared (USA).cht", [{"desc": "Infinite Energy one", "code": "00AA:07"}],
                   extra=["cheats = 2"])
    es2 = R.parse_libretro_cht(p2, platform="NES")
    check("A27 声明数与条目数一致", len(es2) == 2 and es2[1]["compile_status"] == "blocked"
          and any(b["code"] == "no_code_or_address" for b in es2[1]["blockers"]), str(es2[1]))


def t_versions(root):
    d = root / "Nintendo - Nintendo Entertainment System"
    d.mkdir()
    write_cht(d, "Synthetic Game (USA).cht", [{"desc": "Infinite Energy usa", "code": "00AA:07"}])
    write_cht(d, "Synthetic Game (Japan).cht", [{"desc": "Infinite Energy jp", "code": "00AA:09"}])
    res = R.search_local_chts("NES", "Synthetic Game", cht_root=root)
    vals = []
    for row in res["results"]:
        vals.append(row["useful_element_cheats"][0]["patches"][0]["value"])
    check("A28 同名两版本都保留", res["files_found"] == 2 and res["files_returned"] == 2
          and sorted(vals) == [7, 9], str(vals))


def t_pagination(root):
    d = root / "Nintendo - Nintendo Entertainment System"
    d.mkdir()
    for v in range(12):
        write_cht(d, f"Bulk Game (v{v:02d}).cht",
                  [{"desc": f"Infinite Energy {i}", "code": "00AA:07"} for i in range(45)])
    d = R.search_local_chts("NES", "Bulk Game", cht_root=root)
    check("A29 默认截断可核对", d["files_found"] == 12 and d["files_returned"] == 10
          and d["files_truncated"] is True
          and all(r["useful_total"] == 45 and r["useful_returned"] == 40
                  and r["useful_truncated"] is True for r in d["results"]), "")
    full = R.search_local_chts("NES", "Bulk Game", cht_root=root,
                               file_limit=None, cheat_limit=None, include_all=True)
    ok_counts = (full["files_found"] == 12 and full["files_returned"] == 12
                 and full["files_truncated"] is False
                 and all(r["all_cheats_returned"] == 45 and r["useful_returned"] == 45
                         and r["useful_truncated"] is False for r in full["results"])
                 and full["totals_returned_files"] == {"parsed": 540, "useful": 540, "useful_returned": 540})
    check("A30 全量取回 12x45 逐格复算", ok_counts, json.dumps(full["totals_returned_files"]))
    recomputed = sum(len(r["all_cheats"]) for r in full["results"])
    check("A31 返回条数与实物一致", recomputed == 540
          and sum(r["useful_returned"] for r in full["results"]) == full["totals_returned_files"]["useful_returned"], str(recomputed))
    page2 = R.search_local_chts("NES", "Bulk Game", cht_root=root, file_offset=10)
    check("A32 文件翻页取回剩余", page2["files_returned"] == 2 and page2["files_truncated"] is False
          and [Path(r["cht_file"]).stem for r in page2["results"]] == ["Bulk Game (v10)", "Bulk Game (v11)"], "")
    tail = R.search_local_chts("NES", "Bulk Game", cht_root=root, cheat_offset=40, cheat_limit=None)
    check("A33 条目翻页取回剩余", all(r["useful_returned"] == 5 and r["useful_truncated"] is False
                                    for r in tail["results"]), "")
    bs = full["blocker_summary"]
    recount = {}
    for r in full["results"]:
        for e in r["all_cheats"]:
            for b in e["blockers"]:
                recount[b["code"]] = recount.get(b["code"], 0) + 1
    check("A34 blocker 汇总可复算", bs == recount, f"{bs} vs {recount}")


def t_auto_inject(root):
    cht_dir = root / "cht" / "Nintendo - Nintendo Entertainment System"
    cht_dir.mkdir(parents=True)
    write_cht(cht_dir, "Inject Game (USA).cht", [{"desc": "All Weapons raw", "code": "006B:1C"}])
    pack = root / "inject.showcase.json"
    pack.write_text(json.dumps({"game_id": "inject", "platform": "NES", "elements": []}), encoding="utf-8")
    sha_before = hashlib.sha256(pack.read_bytes()).hexdigest()
    out = root / "reports" / "candidates.json"
    rep = R.auto_inject_cht_into_pack(pack, "Inject Game", out_path=out,
                                      file_limit=None, cheat_limit=None,
                                      cht_root=root / "cht")
    sha_after = hashlib.sha256(pack.read_bytes()).hexdigest()
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    e0 = on_disk["results"][0]["all_cheats"][0]
    check("A35 报告写新路径且包不变", out.is_file() and sha_before == sha_after
          and rep["pack_unchanged"] is True and rep["injected"] is False
          and rep["verified_in_game"] is False and on_disk["report_kind"] == "cheat_candidates_only", "")
    check("A36 原码可追溯", e0["raw_fields"]["code"] == "006B:1C" and e0["code"] == "006B:1C"
          and e0["patches"][0]["addr"] == 0x6B and "source_sha256" in on_disk["results"][0], str(e0))
    check("A37 不默认 sibling 覆盖", not pack.with_suffix(".cht_candidates.json").exists(), "")


_SUITE = (t_value_width, t_compound, t_encoded, t_snes_domain, t_nes_domain,
          t_gba_codebreaker, t_unknown_fields, t_versions, t_pagination, t_auto_inject)


def run_cheat_candidate_gates(ok_fn, raises_fn=None):
    """共享 selftest 总入口适配：56 条检查走共享 ok 计数，失败即 AssertionError。"""
    global _OK_FN
    prev = _OK_FN
    _OK_FN = ok_fn
    try:
        with tempfile.TemporaryDirectory(prefix="cheat_candidate_") as td:
            root = Path(td)
            for fn in _SUITE:
                sub = root / fn.__name__
                sub.mkdir()
                fn(sub)
    finally:
        _OK_FN = prev


def main():
    with tempfile.TemporaryDirectory(prefix="cheat_candidate_") as td:
        root = Path(td)
        for fn in _SUITE:
            sub = root / fn.__name__
            sub.mkdir()
            fn(sub)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\nTOTAL {len(RESULTS)} PASS {len(RESULTS) - len(failed)} FAIL {len(failed)}")
    if failed:
        print("FAILED:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())