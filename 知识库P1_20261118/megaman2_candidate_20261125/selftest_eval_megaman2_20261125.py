# -*- coding: utf-8 -*-
"""构建并验收洛克人2隔离候选；只写候选目录，反查生产文件未变。"""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

BASE = Path(__file__).resolve().parent
P1 = BASE.parent
ROOT = BASE.parent.parent
TOOLS = ROOT / "_工具脚本"
sys.path.insert(0, str(TOOLS))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import kb_megaman2 as M
from taspipe import kb_route as KR
from taspipe import sources as S

EVIDENCE = BASE / "evidence"
INDEX = BASE / "index.json"
MAP = BASE / "corpus_map.json"
REGISTRY = BASE / "sources.json"
CONTRACT = BASE / "contract.json"
PROVENANCE = BASE / "provenance.json"
SCOPE = BASE / "scope.json"
BUILD_REPORT = BASE / "build_report.json"
EVAL_REPORT = BASE / "eval_report.json"
LOG = BASE / "eval_query_log.jsonl"

TECH_SOURCE = "tasvideos_rockman_data_mm2_extract"
MEMORY_SOURCE = "local_megaman2_memory_dictionary"
CATALOG_SOURCE = "local_megaman2_title_catalog"
TAS_SOURCE = "local_megaman2_tas_publications"

TECH_PATH = ROOT / "_工具脚本/taspipe/游戏包/来源库/取证/tasvideos_gameresources_rockman_data_2026-11-23.txt"
MEMORY_PATH = ROOT / "_工具脚本/taspipe/游戏数据字典/expanded_50_games_memory_maps.json"
CATALOG_PATH = ROOT / "_工具脚本/taspipe/popular_titles.json"
TAS_PATH = ROOT / "04-游戏资源库/TAS输入录像库/publications.json"

PRODUCTION_GUARDS = [
    K.INDEX_JSON,
    K.CORPUS_MAP,
    S.REG_JSON,
    K.KB_DIR / "index_hybrid.json",
    K.KB_DIR / "query_log.jsonl",
    KE.DB_PATH,
    TOOLS / "taspipe/kb.py",
    TOOLS / "taspipe/kb_route.py",
    TOOLS / "taspipe/kb_esports.py",
    TOOLS / "taspipe/kb_selftest_gates.py",
]

REVISIONS = {
    M.TECHNICAL_REVISION: {
        "game_id": "megaman2", "platform": "NES",
        "name": "洛克人2 / Rockman 2 — TASVideos 技术文档范围（未绑定地区 ROM 哈希）",
        "note": "authoritative 仅限 TASVideos GameResources 原文明确记载的 Rockman 2 技术事实；不等于 PAL/美版/日版 ROM 等价。",
    },
    M.MEMORY_REVISION: {
        "game_id": "megaman2", "platform": "NES",
        "name": "洛克人2 NES — 本地二手内存字典（身份与逐字段来源未核）",
        "note": "reference_only；不得把 stable-retro/libretro/DataCrystal/Pugsy 的整合字段当作本机实测或地区权威。",
    },
    M.CATALOG_REVISION: {
        "game_id": "megaman2", "platform": "NES",
        "name": "洛克人2 NES — 本地标题目录（二手元数据）",
        "note": "reference_only；仅保留目录中的标题、平台、别名与 basis 字段。",
    },
    M.TAS_REVISION: {
        "game_id": "megaman2", "platform": "NES",
        "name": "洛克人2 NES — 本地 TAS 出版物元数据（reference_only）",
        "note": "只证明本地目录记录了哪些 TAS/声明版本；不证明 ROM 在本机可用，也不证明玩法事实。",
    },
}

SPECS = [
    {"key": "coordinates", "source_id": TECH_SOURCE, "source": TECH_PATH,
     "target": "mm2_tasvideos_coordinates_20261125.txt", "ranges": [(122, 132), (167, 190)],
     "kind": "prose", "revision": M.TECHNICAL_REVISION, "authority": "authoritative",
     "title": "Rockman 2 coordinate system — verbatim extract",
     "qualification": "Source-scoped technical evidence; no PAL/US regional equivalence is asserted.",
     "element_types": ["帧数据", "基础档案"],
     "note": "TASVideos 原文：对象坐标属性、十六进制口径与坐标轴方向。"},
    {"key": "jump", "source_id": TECH_SOURCE, "source": TECH_PATH,
     "target": "mm2_tasvideos_jump_20261125.txt", "ranges": [(196, 208)],
     "kind": "prose", "revision": M.TECHNICAL_REVISION, "authority": "authoritative",
     "title": "Rockman 2 jump curve — verbatim extract",
     "qualification": "Source-scoped technical evidence; no PAL/US regional equivalence is asserted.",
     "element_types": ["帧数据", "基础档案"],
     "note": "TASVideos 原文：Rockman 1/2 起跳 Y speed 04.DF、重力与松开 A 的速度限制。"},
    {"key": "climb_transform", "source_id": TECH_SOURCE, "source": TECH_PATH,
     "target": "mm2_tasvideos_climb_transform_20261125.txt", "ranges": [(253, 261)],
     "kind": "prose", "revision": M.TECHNICAL_REVISION, "authority": "authoritative",
     "title": "Rockman 2 climbing and transforming — verbatim extract",
     "qualification": "Source-scoped technical evidence; no PAL/US regional equivalence is asserted.",
     "element_types": ["帧数据", "基础档案"],
     "note": "TASVideos 原文：Rockman 2 攀爬速度与暂停/变换状态行为。"},
    {"key": "jump_horizontal", "source_id": TECH_SOURCE, "source": TECH_PATH,
     "target": "mm2_tasvideos_jump_horizontal_20261125.txt", "ranges": [(271, 279)],
     "kind": "prose", "revision": M.TECHNICAL_REVISION, "authority": "authoritative",
     "title": "Rockman 2 horizontal motion while jumping — verbatim extract",
     "qualification": "Source-scoped technical evidence; no PAL/US regional equivalence is asserted.",
     "element_types": ["帧数据", "基础档案"],
     "note": "TASVideos 原文：Rockman 2 跳跃/下落方向速度与停止输入后的行为。"},
    {"key": "walking", "source_id": TECH_SOURCE, "source": TECH_PATH,
     "target": "mm2_tasvideos_walking_20261125.txt", "ranges": [(281, 287)],
     "kind": "prose", "revision": M.TECHNICAL_REVISION, "authority": "authoritative",
     "title": "Rockman 2 walking speed — verbatim extract",
     "qualification": "Source-scoped technical evidence; no PAL/US regional equivalence is asserted.",
     "element_types": ["帧数据", "基础档案"],
     "note": "TASVideos 原文：Rockman 1/2 walking X speed 01.60。"},
    {"key": "acceleration", "source_id": TECH_SOURCE, "source": TECH_PATH,
     "target": "mm2_tasvideos_acceleration_20261125.txt", "ranges": [(289, 305)],
     "kind": "prose", "revision": M.TECHNICAL_REVISION, "authority": "authoritative",
     "title": "Rockman 2 acceleration and deceleration — verbatim extract",
     "qualification": "Source-scoped technical evidence; no PAL/US regional equivalence is asserted.",
     "element_types": ["帧数据", "基础档案"],
     "note": "TASVideos 原文：Rockman 2 加速 7 帧、减速 8 帧（十进制帧数按原文）。"},
    {"key": "object_table", "source_id": TECH_SOURCE, "source": TECH_PATH,
     "target": "mm2_tasvideos_object_table_20261125.txt", "ranges": [(424, 432), (441, 443)],
     "kind": "table", "revision": M.TECHNICAL_REVISION, "authority": "authoritative",
     "title": "Rockman 2 object RAM table — verbatim extract",
     "qualification": "Source-scoped technical evidence; no PAL/US regional equivalence is asserted.",
     "element_types": ["帧数据", "基础档案"],
     "note": "TASVideos 反汇编表：Rockman 2 Screen/X/Xspd/Y/Yspd 地址与对象 n 规则。"},
    {"key": "memory_dictionary", "source_id": MEMORY_SOURCE, "source": MEMORY_PATH,
     "target": "mm2_local_memory_dictionary_20261125.txt", "ranges": [(15, 23)],
     "kind": "table", "revision": M.MEMORY_REVISION, "authority": "reference_only",
     "title": "MegaMan2_NES local memory dictionary — verbatim extract",
     "qualification": "Secondary local aggregate; per-field provenance and ROM identity are not established.",
     "element_types": ["金手指", "基础档案"],
     "note": "本地整合字典原始字段；缺逐字段原始来源、ROM SHA1 与本机实测，不能升 authoritative。"},
    {"key": "title_catalog", "source_id": CATALOG_SOURCE, "source": CATALOG_PATH,
     "target": "mm2_local_title_catalog_20261125.txt", "ranges": [(480, 490)],
     "kind": "table", "revision": M.CATALOG_REVISION, "authority": "reference_only",
     "title": "Mega Man 2 local title catalog — verbatim extract",
     "qualification": "Secondary local catalog; basis is retained, but no primary page snapshot is bundled.",
     "element_types": ["基础档案", "身份"],
     "note": "本地热门作品目录：NES、Mega Man 2、洛克人2、Rockman 2 与维基销量 basis。"},
    {"key": "tas_publications", "source_id": TAS_SOURCE, "source": TAS_PATH,
     "target": "mm2_local_tas_publications_20261125.txt",
     "ranges": [(96935, 96973), (96975, 97012)],
     "kind": "table", "revision": M.TAS_REVISION, "authority": "reference_only",
     "title": "Mega Man 2 local TAS publication metadata — verbatim extract",
     "qualification": "Local publication metadata; not proof of ROM availability or gameplay verification.",
     "element_types": ["基础档案", "身份", "视频验证"],
     "note": "本地 TAS 目录中 4057/4410 的版本名、声明 SHA1 与格式；registry 仍为 blocked/unresolved。"},
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path):
    return Path(path).relative_to(ROOT).as_posix()


def snapshot(path):
    path = Path(path)
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": sha(path)}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def extract(spec):
    source = Path(spec["source"])
    if not source.is_file() or source.stat().st_size == 0:
        raise RuntimeError(f"真实来源缺失或为空: {source}")
    source_lines = source.read_text(encoding="utf-8").splitlines()
    ranges = spec["ranges"]
    range_text = "; ".join(f"{start}-{end}" for start, end in ranges)
    out = [f"# {spec['title']}", f"> Origin: {rel(source)}",
           f"> Original line ranges: {range_text}", f"> Qualification: {spec['qualification']}", ""]
    records = []
    cursor = len(out) + 1
    for i, (start, end) in enumerate(ranges):
        selected = source_lines[start - 1:end]
        if len(selected) != end - start + 1 or not any(line.strip() for line in selected):
            raise RuntimeError(f"摘录范围不可用或为空: {source} {start}-{end}")
        target_start = cursor
        out.extend(selected)
        cursor += len(selected)
        records.append({"source_line_start": start, "source_line_end": end,
                        "target_line_start": target_start, "target_line_end": cursor - 1,
                        "source_sha256": sha(source), "verbatim": True,
                        "nonempty": bool(any(line.strip() for line in selected))})
        if i != len(ranges) - 1:
            out.append("")
            cursor += 1
    target = EVIDENCE / spec["target"]
    write_text(target, "\n".join(out) + "\n")
    return {"key": spec["key"], "source_id": spec["source_id"],
            "source": rel(source), "source_sha256": sha(source),
            "target": rel(target), "target_sha256": sha(target),
            "target_bytes": target.stat().st_size, "ranges": records,
            "kind": spec["kind"], "revision": spec["revision"],
            "authority": spec["authority"]}


def source_records(evidence_by_source):
    return [
        {"source_id": TECH_SOURCE,
         "name": "TASVideos GameResources NES/Rockman/Data — Rockman 2 技术条目",
         "kind": "site", "layer": "en_tech", "platforms": ["NES"],
         "element_types": ["帧数据", "基础档案"], "status": "verified_read",
         "last_verified": "2026-11-25",
         "urls": ["https://tasvideos.org/GameResources/NES/Rockman/Data"],
         "evidence": evidence_by_source[TECH_SOURCE],
         "notes": "真实本地取证文件逐字摘录；原页 2026-11-23 取回。authoritative 只限原文技术条目，未建立 PAL/美版/日版 ROM 等价。",
         "games_hit": ["megaman2"]},
        {"source_id": MEMORY_SOURCE,
         "name": "本地 expanded_50_games_memory_maps.json 的 MegaMan2_NES 条目",
         "kind": "local", "layer": "local_docs", "platforms": ["NES"],
         "element_types": ["金手指", "基础档案"], "status": "verified_read",
         "last_verified": "2026-11-25", "urls": [],
         "evidence": evidence_by_source[MEMORY_SOURCE],
         "notes": "已读本地正文，但它是多来源二手整合；逐字段原始出处、ROM SHA1 和本机实测均缺，authority 保持 reference_only。",
         "games_hit": ["megaman2"]},
        {"source_id": CATALOG_SOURCE,
         "name": "本地 popular_titles.json 的 Mega Man 2 目录条目",
         "kind": "local", "layer": "local_docs", "platforms": ["NES"],
         "element_types": ["基础档案", "身份"], "status": "verified_read",
         "last_verified": "2026-11-25", "urls": [],
         "evidence": evidence_by_source[CATALOG_SOURCE],
         "notes": "已读本地目录；basis 指向 EN 维基但未附原页快照，authority 保持 reference_only。",
         "games_hit": ["megaman2"]},
        {"source_id": TAS_SOURCE,
         "name": "本地 TAS publications.json 的 Mega Man 2 / 4057 / 4410 元数据",
         "kind": "local", "layer": "local_docs", "platforms": ["NES"],
         "element_types": ["基础档案", "身份", "视频验证"], "status": "verified_read",
         "last_verified": "2026-11-25", "urls": [], "evidence": evidence_by_source[TAS_SOURCE],
         "notes": "已读本地出版物目录；只证明目录记录与声明哈希，不证明 ROM 可用、console_verified 或玩法事实。",
         "games_hit": ["megaman2"]},
    ]


def build_candidate():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    provenance = [extract(spec) for spec in SPECS]
    evidence_by_source = {sid: [] for sid in
                          (TECH_SOURCE, MEMORY_SOURCE, CATALOG_SOURCE, TAS_SOURCE)}
    entries = []
    for spec in SPECS:
        target = rel(EVIDENCE / spec["target"])
        evidence_by_source[spec["source_id"]].append(target)
        entries.append({"path": target, "source_id": spec["source_id"],
                        "revision": spec["revision"], "kind": spec["kind"],
                        "authority": spec["authority"], "index": True,
                        "element_types": spec["element_types"], "note": spec["note"]})
    registry = {"schema_version": 1, "updated": "2026-11-25",
                "note": "洛克人2候选专用来源库；不含生产来源，不写生产 sources.json。verified_read 表示真实本地正文已读且取证非空，不等同所有事实 authoritative。",
                "sources": source_records(evidence_by_source), "absence_claims": []}
    corpus_map = {"schema_version": 1, "revisions": REVISIONS, "entries": entries}
    write_json(REGISTRY, registry)
    write_json(MAP, corpus_map)
    write_json(PROVENANCE, {"schema_version": 1, "candidate_domain": M.DOMAIN,
                            "extraction_method": "line-range verbatim extraction from real local files",
                            "records": provenance})
    write_json(SCOPE, {
        "status": "isolated_candidate_not_production", "domain": M.DOMAIN,
        "authoritative_scope": ["TASVideos 原文明确记载的 Rockman 2 坐标/运动/对象 RAM 技术事实"],
        "reference_only_scope": ["本地二手内存字典", "本地标题目录", "本地 TAS 出版物元数据"],
        "not_covered": ["洛克人2出招表", "官方说明书级玩法", "整款游戏知识库",
                        "PAL/欧版与美版等价", "美版/日版 ROM SHA1 绑定", "生产路由接线"],
        "production_route_wired": False, "whole_game_knowledge_base": False,
        "external_generative_model_calls": 0, "paid_api_calls": 0,
        "commercial_rom_downloads": 0, "restricted_fetch_bypasses": 0,
    })
    S.load_registry(REGISTRY)
    K.load_map(MAP)
    build = K.build(map_path=MAP, index_path=INDEX, reg=registry, force=True)
    index = K.load_index(INDEX)
    index_sha = sha(INDEX)
    write_json(CONTRACT, {"schema_version": 1, "domain": M.DOMAIN,
                          "index_path": rel(INDEX), "index_sha256": index_sha,
                          "map_path": rel(MAP), "registry_path": rel(REGISTRY),
                          "default_revision": M.TECHNICAL_REVISION,
                          "frozen_at": "2026-11-25", "production_route_wired": False})
    write_json(BUILD_REPORT, {
        "status": "built_isolated", "candidate_domain": M.DOMAIN,
        "candidate_dir": str(BASE), "build": build,
        "index_chunks": len(index["chunks"]), "index_sha256": index_sha,
        "entries": len(entries), "sources": len(registry["sources"]),
        "revision_counts": {rid: sum(c["revision"] == rid for c in index["chunks"])
                            for rid in REVISIONS},
        "authority_counts": {a: sum(c["authority"] == a for c in index["chunks"])
                             for a in sorted({c["authority"] for c in index["chunks"]})},
        "verified_read_authoritative_chunks": sum(
            c["status"] == "verified_read" and c["authority"] == "authoritative"
            for c in index["chunks"]),
        "provenance": rel(PROVENANCE),
    })
    print(f"BUILD_OK entries={len(entries)} chunks={len(index['chunks'])} sha256={index_sha}")


def validate_provenance():
    doc = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    problems = []
    for rec in doc["records"]:
        source_lines = (ROOT / rec["source"]).read_text(encoding="utf-8").splitlines()
        target_lines = (ROOT / rec["target"]).read_text(encoding="utf-8").splitlines()
        if sha(ROOT / rec["source"]) != rec["source_sha256"]:
            problems.append(f"source hash changed: {rec['key']}")
        if sha(ROOT / rec["target"]) != rec["target_sha256"]:
            problems.append(f"target hash changed: {rec['key']}")
        for ran in rec["ranges"]:
            original = source_lines[ran["source_line_start"] - 1:ran["source_line_end"]]
            copied = target_lines[ran["target_line_start"] - 1:ran["target_line_end"]]
            if original != copied or not any(line.strip() for line in copied):
                problems.append(f"verbatim mismatch: {rec['key']} {ran}")
    return problems


ROUTE_CASES = [
    ("R01", "洛克人2 的 walking speed 是什么？", "candidate"),
    ("R02", "洛克人 ２ 的 walking speed 是什么？", "candidate"),
    ("R03", "Ｍｅｇａ　Ｍａｎ　２ 的 walking speed 是什么？", "candidate"),
    ("R04", "Rockman 2 的 climbing speed 是什么？", "candidate"),
    ("R05", "mm2 的 jump Y speed 初始值是什么？", "candidate"),
    ("R06", "MM2 的 walking speed 是什么？", "candidate"),
    ("R07", "洛克人 的 walking speed 是什么？", "ambiguous_series"),
    ("R08", "Mega Man 的 walking speed 是什么？", "ambiguous_series"),
    ("R09", "Mega Man 2: The Power Fighters 出招表", "ambiguous_series"),
    ("R10", "Rockman 2 Claw 的 walking speed 是什么？", "ambiguous_series"),
    ("R11", "MM20 的 walking speed 是什么？", "not_matched"),
    ("R12", "洛克人2 PAL 出招表", "version_not_collected"),
    ("R13", "洛克人2 欧版ROM 的 walking speed 是什么？", "version_not_collected"),
    ("R14", "MM2 美版ROM 的 walking speed 是什么？", "version_not_collected"),
    ("R15", "洛克人2 和拳皇98 的 walking speed 分别是什么？", "multi_domain_needs_split"),
    ("R16", "洛克人2 和洛克人3 的 walking speed 分别是什么？", "multi_domain_needs_split"),
    ("R17", "拳皇98 出招表", "not_matched"),
    ("R18", "出招表", "not_matched"),
    ("R19", "洛克人2 的 HP 内存地址是什么？", "candidate"),
    ("R20", "洛克人2 的 TAS 4057 用哪个版本？", "candidate"),
]

ASK_CASES = [
    {"id": "P01", "q": "洛克人2 的 walking speed 是什么？", "kind": "positive",
     "revision": M.TECHNICAL_REVISION, "source_id": TECH_SOURCE,
     "target": "mm2_tasvideos_walking_20261125.txt", "must_contain": ["Rockman 1 and 2", "01.60"]},
    {"id": "P02", "q": "Rockman 2 的 X speed 内存地址是什么？", "kind": "positive",
     "revision": M.TECHNICAL_REVISION, "source_id": TECH_SOURCE,
     "target": "mm2_tasvideos_object_table_20261125.txt", "must_contain": ["Rockman 2", "$460:$480"]},
    {"id": "P03", "q": "MM2 的 jump Y speed 初始值是什么？", "kind": "positive",
     "revision": M.TECHNICAL_REVISION, "source_id": TECH_SOURCE,
     "target": "mm2_tasvideos_jump_20261125.txt", "must_contain": ["04.DF"]},
    {"id": "P04", "q": "Mega Man 2 的 climbing speed 是什么？", "kind": "positive",
     "revision": M.TECHNICAL_REVISION, "source_id": TECH_SOURCE,
     "target": "mm2_tasvideos_climb_transform_20261125.txt", "must_contain": ["00.C0"]},
    {"id": "P05", "q": "Ｍｅｇａ　Ｍａｎ　２ 的 walking speed 是什么？", "kind": "positive",
     "revision": M.TECHNICAL_REVISION, "source_id": TECH_SOURCE,
     "target": "mm2_tasvideos_walking_20261125.txt", "must_contain": ["01.60"]},
    {"id": "N01", "q": "洛克人2 出招表", "kind": "movelist", "disposition": "candidate",
     "refusal": "move_list_not_collected", "index_expected": True},
    {"id": "N02", "q": "洛克人2 PAL 的 walking speed 是什么？", "kind": "blocked",
     "disposition": "version_not_collected", "refusal": "version_not_collected"},
    {"id": "N03", "q": "洛克人2 欧版ROM 的 walking speed 是什么？", "kind": "blocked",
     "disposition": "version_not_collected", "refusal": "version_not_collected"},
    {"id": "N04", "q": "MM2 美版ROM 的 walking speed 是什么？", "kind": "blocked",
     "disposition": "version_not_collected", "refusal": "version_not_collected"},
    {"id": "N05", "q": "洛克人2 和拳皇98 的 walking speed 分别是什么？", "kind": "blocked",
     "disposition": "multi_domain_needs_split", "refusal": "multi_domain_needs_split"},
    {"id": "N06", "q": "洛克人2 和洛克人3 的 walking speed 分别是什么？", "kind": "blocked",
     "disposition": "multi_domain_needs_split", "refusal": "multi_domain_needs_split"},
    {"id": "N07", "q": "洛克人 的 walking speed 是什么？", "kind": "blocked",
     "disposition": "ambiguous_series", "refusal": "ambiguous_series"},
    {"id": "N08", "q": "Mega Man 2: The Power Fighters 出招表", "kind": "blocked",
     "disposition": "ambiguous_series", "refusal": "ambiguous_series"},
    {"id": "N09", "q": "洛克人2 的作曲家是谁？", "kind": "unsupported", "disposition": "candidate"},
    {"id": "N10", "q": "洛克人2 的 HP 内存地址是什么？", "kind": "weak",
     "disposition": "candidate", "revision": M.MEMORY_REVISION,
     "source_id": MEMORY_SOURCE, "index_expected": True},
    {"id": "N11", "q": "洛克人2 的 weapon_select 地址是什么？", "kind": "weak",
     "disposition": "candidate", "revision": M.MEMORY_REVISION,
     "source_id": MEMORY_SOURCE, "index_expected": True},
    {"id": "N12", "q": "洛克人2 的 platform 是什么？", "kind": "weak",
     "disposition": "candidate", "revision": M.CATALOG_REVISION,
     "source_id": CATALOG_SOURCE, "index_expected": True},
    {"id": "N13", "q": "洛克人2 的 TAS 4057 用哪个版本？", "kind": "weak",
     "disposition": "candidate", "revision": M.TAS_REVISION,
     "source_id": TAS_SOURCE, "index_expected": True},
    {"id": "N14", "q": "出招表", "kind": "blocked", "disposition": "not_matched",
     "refusal": "candidate_domain_not_matched"},
    {"id": "N15", "q": "walking speed 是什么？", "kind": "blocked", "disposition": "not_matched",
     "refusal": "candidate_domain_not_matched"},
    {"id": "N16", "q": "Rockman 2 Claw 的 walking speed 是什么？", "kind": "blocked",
     "disposition": "ambiguous_series", "refusal": "ambiguous_series"},
    {"id": "N17", "q": "洛克人2 PAL-B 的 X speed 内存地址是什么？", "kind": "blocked",
     "disposition": "version_not_collected", "refusal": "version_not_collected"},
    {"id": "N18", "q": "MM20 的 walking speed 是什么？", "kind": "blocked",
     "disposition": "not_matched", "refusal": "candidate_domain_not_matched"},
]


def grade_case(case, result, chunks_by_id, mode):
    checks = []

    def check(name, ok):
        checks.append({"name": name, "ok": bool(ok)})

    route = result.get("route") or {}
    check("route_domain", route.get("domain") == (M.DOMAIN if case["disposition"] != "not_matched" else "unrouted")
          if case.get("disposition") else route.get("domain") == M.DOMAIN)
    if case.get("disposition"):
        check("route_disposition", route.get("disposition") == case["disposition"])
    selected = result.get("selected_evidence") or []
    check("no_kof_source", all(not str(h.get("source_id", "")).startswith("kof98")
                               for h in selected + (result.get("hits") or [])))
    if case["kind"] == "positive":
        check("status_pass", result.get("status") == "pass")
        check("one_selected", len(selected) == 1)
        check("candidate_index", result.get("index_used") == "index.json")
        check("revision", route.get("revision") == case["revision"])
        if selected:
            hit = selected[0]
            check("source", hit.get("source_id") == case["source_id"])
            check("authority", hit.get("status") == "verified_read" and hit.get("authority") == "authoritative")
            check("locator", case["target"] in hit.get("locator", ""))
            chunk = chunks_by_id.get(hit.get("chunk_id"), {})
            text = chunk.get("text", "")
            check("fact_text", all(term in text for term in case["must_contain"]))
            check("answer_excerpt", result.get("answer", {}).get("kind") == "evidence_excerpt"
                  and bool(result.get("answer", {}).get("text")))
            if mode == "strict":
                check("strict_fragment", (hit.get("fragment_provenance") or {}).get("eligible") is True)
    elif case["kind"] == "blocked":
        check("status", result.get("status") in {"miss", "inconclusive"})
        check("refusal", result.get("refusal") == case["refusal"])
        check("no_retrieval", result.get("index_used") is None and not result.get("hits"))
        check("no_evidence", not selected)
    elif case["kind"] == "movelist":
        check("status", result.get("status") in {"miss", "inconclusive"})
        check("refusal", result.get("refusal") == case["refusal"])
        check("candidate_index", result.get("index_used") == "index.json")
        check("no_evidence", not selected)
        check("no_kof_hits", all(not str(h.get("source_id", "")).startswith("kof98")
                                 for h in result.get("hits") or []))
    elif case["kind"] == "weak":
        check("status_inconclusive", result.get("status") == "inconclusive")
        check("candidate_index", result.get("index_used") == "index.json")
        check("revision", route.get("revision") == case["revision"])
        check("reference_hit", any(h.get("source_id") == case["source_id"]
                                   and h.get("authority") == "reference_only"
                                   for h in result.get("hits") or []))
        check("no_evidence", not selected)
    elif case["kind"] == "unsupported":
        check("status", result.get("status") in {"miss", "inconclusive"})
        check("no_evidence", not selected)
    return {"id": case["id"], "q": case["q"], "kind": case["kind"], "mode": mode,
            "ok": all(c["ok"] for c in checks), "checks": checks,
            "status": result.get("status"), "refusal": result.get("refusal"),
            "reason": result.get("reason"), "route": route,
            "index_used": result.get("index_used"),
            "selected_locator": selected[0].get("locator") if selected else None,
            "hit_sources": sorted({h.get("source_id") for h in result.get("hits") or []})}


def failure_close_cases():
    rows = []
    question = ASK_CASES[0]["q"]
    actual_sha = sha(INDEX)
    with tempfile.TemporaryDirectory(prefix="mm2-close-") as tmp:
        tmp = Path(tmp)
        bad = tmp / "bad_index.json"
        bad.write_text("{}", encoding="utf-8")
        missing = tmp / "missing_index.json"
        missing_contract = tmp / "missing_contract.json"
        with mock.patch.object(M, "INDEX_PATH", bad):
            r1 = M.ask(question)
        with mock.patch.object(M, "INDEX_PATH", missing):
            r2 = M.ask(question)
        with mock.patch.object(M, "CONTRACT_PATH", missing_contract):
            r3 = M.ask(question)
        fake = {"status": "pass", "index_used": "index.json", "index_sha256": actual_sha,
                "selected_evidence": [{"chunk_id": "fake", "source_id": "kof98_production",
                                       "status": "verified_read", "authority": "authoritative",
                                       "revision": M.TECHNICAL_REVISION,
                                       "locator": "_工具脚本/taspipe/游戏包/知识库/index.json#L1-L1"}],
                "hits": [], "counts": {}}
        with mock.patch.object(M.K, "query", return_value=fake):
            r4 = M.ask(question)
        try:
            M.ask("出招表", log_path=K.KB_DIR / "query_log.jsonl")
            outside_raised = False
        except ValueError:
            outside_raised = True
    rows.extend([
        {"id": "FC01", "ok": r1.get("refusal") == "candidate_hash_mismatch"
         and r1.get("index_used") is None and not r1.get("selected_evidence")},
        {"id": "FC02", "ok": r2.get("refusal") == "candidate_unavailable"
         and r2.get("index_used") is None and not r2.get("selected_evidence")},
        {"id": "FC03", "ok": r3.get("refusal") == "candidate_unavailable"
         and r3.get("index_used") is None and not r3.get("selected_evidence")},
        {"id": "FC04", "ok": r4.get("refusal") == "candidate_evidence_invalid"
         and r4.get("index_used") is None and not r4.get("selected_evidence")},
        {"id": "FC05", "ok": outside_raised},
    ])
    return rows


def evaluate():
    if not all(p.is_file() for p in (INDEX, MAP, REGISTRY, CONTRACT)):
        raise RuntimeError("候选文件不齐；先运行 --build")
    registry = S.load_registry(REGISTRY)
    corpus_map = K.load_map(MAP)
    index = K.load_index(INDEX)
    if sha(INDEX) != M.expected_index_sha256():
        raise RuntimeError("候选索引与契约不一致")
    chunks_by_id = {c["chunk_id"]: c for c in index["chunks"]}
    source_ids = {s["source_id"] for s in registry["sources"]}
    binding_problems = []
    for entry in corpus_map["entries"]:
        path = ROOT / entry["path"]
        source = next((s for s in registry["sources"] if s["source_id"] == entry["source_id"]), None)
        if source is None or entry["path"] not in source.get("evidence", []):
            binding_problems.append(f"unbound: {entry['path']}")
        if not path.is_file() or path.stat().st_size == 0:
            binding_problems.append(f"empty: {entry['path']}")
    for source in registry["sources"]:
        if source["status"] == "verified_read":
            for evidence in source.get("evidence", []):
                path = ROOT / evidence
                if not path.is_file() or path.stat().st_size == 0:
                    binding_problems.append(f"verified_read empty: {source['source_id']} {evidence}")
    provenance_problems = validate_provenance()
    index_problems = [c["chunk_id"] for c in index["chunks"]
                      if c["game_id"] != "megaman2" or c["source_id"] not in source_ids
                      or not str(c["path"]).startswith("知识库P1_20261118/megaman2_candidate_20261125/")]
    audit = K.audit(map_path=MAP, index_path=INDEX, reg=registry)
    audit_checks = {c["check_id"]: c["verdict"] for c in audit["checks"]}
    audit_required = ["evidence_coverage", "source_binding", "identity_conflict",
                      "index_sync", "chunk_provenance"]
    audit_ok = all(audit_checks.get(k) == "pass" for k in audit_required)

    production_index = K.load_index()
    production_lm2_absent = bool(production_index) and not any(
        c.get("game_id") == "megaman2" or str(c.get("revision", "")).startswith("megaman2")
        for c in production_index["chunks"])
    standalone_before = KR.route("出招表")
    lm2_before = KR.route("洛克人2 出招表")
    route_rows = []
    for rid, q, expected in ROUTE_CASES:
        route = M.route_question(q)
        route_rows.append({"id": rid, "q": q, "expected": expected,
                           "actual": route["disposition"], "domain": route["domain"],
                           "revision": route["revision"],
                           "ok": route["disposition"] == expected})

    write_text(LOG, "")
    case_rows = []
    for case in ASK_CASES:
        for mode in ("default", "strict"):
            result = M.ask(case["q"], mode=mode, log_path=LOG)
            case_rows.append(grade_case(case, result, chunks_by_id, mode))
    failure_rows = failure_close_cases()
    log_rows = [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    log_problems = []
    if len(log_rows) != len(ASK_CASES) * 2:
        log_problems.append(f"log row count {len(log_rows)}")
    for row in log_rows:
        if row.get("entry_point") not in {"mm2-candidate-consumer-default", "mm2-candidate-consumer-strict"}:
            log_problems.append("unexpected entry_point")
        if row.get("index_used") not in {None, "index.json"}:
            log_problems.append("unexpected index")
        for hit in row.get("selected_evidence") or []:
            if hit.get("source_id") not in source_ids:
                log_problems.append("non-candidate selected source")
            if "megaman2_candidate_20261125" not in str(hit.get("locator", "")):
                log_problems.append("non-candidate locator")

    default_rows = [r for r in case_rows if r["mode"] == "default"]
    strict_rows = [r for r in case_rows if r["mode"] == "strict"]
    summary = {
        "route_total": len(route_rows), "route_ok": sum(r["ok"] for r in route_rows),
        "default_total": len(default_rows), "default_ok": sum(r["ok"] for r in default_rows),
        "strict_total": len(strict_rows), "strict_ok": sum(r["ok"] for r in strict_rows),
        "positive_default": sum(r["kind"] == "positive" and r["ok"] for r in default_rows),
        "positive_strict": sum(r["kind"] == "positive" and r["ok"] for r in strict_rows),
        "negative_default": sum(r["kind"] != "positive" and r["ok"] for r in default_rows),
        "negative_strict": sum(r["kind"] != "positive" and r["ok"] for r in strict_rows),
        "wrong_evidence_default": sum(bool(r["selected_locator"]) and r["kind"] != "positive"
                                      for r in default_rows),
        "wrong_evidence_strict": sum(bool(r["selected_locator"]) and r["kind"] != "positive"
                                     for r in strict_rows),
        "failure_close_total": len(failure_rows),
        "failure_close_ok": sum(r["ok"] for r in failure_rows),
    }
    return {
        "status": "evaluated_isolated_candidate", "consumer": "taspipe.kb_megaman2.ask",
        "candidate_domain": M.DOMAIN, "candidate_dir": str(BASE),
        "candidate_index": str(INDEX), "index_chunks": len(index["chunks"]),
        "index_sha256": sha(INDEX), "entries": len(corpus_map["entries"]),
        "sources": len(registry["sources"]),
        "verified_read_authoritative_chunks": sum(
            c["status"] == "verified_read" and c["authority"] == "authoritative"
            for c in index["chunks"]),
        "summary": summary, "route_cases": route_rows, "ask_cases": case_rows,
        "failure_close": failure_rows,
        "evidence_validation": {"binding_problems": binding_problems,
                                "provenance_problems": provenance_problems,
                                "index_problems": index_problems,
                                "ok": not (binding_problems or provenance_problems or index_problems)},
        "audit": audit, "audit_required_ok": audit_ok,
        "production": {"lm2_domain_absent": production_lm2_absent,
                       "megaman2_in_domains": "megaman2" in KR.DOMAINS,
                       "standalone_movelist_route_before": standalone_before,
                       "lm2_movelist_route_before": lm2_before,
                       "standalone_behavior_preserved": standalone_before["domain"] == "kof98"
                       and standalone_before["tier"] == "weak",
                       "known_misroute_unchanged": lm2_before["domain"] == "kof98"
                       and lm2_before["tier"] == "weak"},
        "query_log": {"path": str(LOG), "lines": len(log_rows), "sha256": sha(LOG),
                      "problems": log_problems},
        "core_generalization": {
            "generic_builder_reused": True, "generic_query_reused": True,
            "production_domains_modified": False, "production_route_wired": False,
            "candidate_paths_only_for_retrieval": True,
        },
        "remaining": ["洛克人2出招表正文未收集", "官方说明书级玩法未收集",
                      "PAL/欧版与美版等价未验证", "美版/日版 ROM SHA1 未绑定",
                      "内存字典缺逐字段原始来源与本机实测", "生产 DOMAINS/消费方接线未做"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="从真实本地文件重建候选索引")
    args = parser.parse_args(argv)
    before = {str(p): snapshot(p) for p in PRODUCTION_GUARDS}
    if args.build:
        build_candidate()
    candidate_before = {str(p): snapshot(p) for p in (INDEX, MAP, REGISTRY, CONTRACT)}
    report = evaluate()
    after = {str(p): snapshot(p) for p in PRODUCTION_GUARDS}
    candidate_after = {str(p): snapshot(p) for p in (INDEX, MAP, REGISTRY, CONTRACT)}
    changed = [p for p in before if before[p] != after[p]]
    candidate_changed = [p for p in candidate_before if candidate_before[p] != candidate_after[p]]
    report["isolation"] = {
        "ok": not changed and not candidate_changed and not report["query_log"]["problems"],
        "production_changed_paths": changed, "candidate_input_changed_paths": candidate_changed,
        "production_before": before, "production_after": after,
        "candidate_inputs_unchanged": not candidate_changed,
        "production_defaults_unchanged": not changed,
    }
    s = report["summary"]
    all_ok = (s["route_ok"] == s["route_total"]
              and s["default_ok"] == s["default_total"]
              and s["strict_ok"] == s["strict_total"]
              and s["failure_close_ok"] == s["failure_close_total"]
              and report["evidence_validation"]["ok"] and report["audit_required_ok"]
              and report["production"]["lm2_domain_absent"]
              and not report["production"]["megaman2_in_domains"]
              and report["production"]["standalone_behavior_preserved"]
              and report["isolation"]["ok"])
    report["all_ok"] = all_ok
    write_json(EVAL_REPORT, report)
    print(f"EVAL_OK route={s['route_ok']}/{s['route_total']} "
          f"default={s['default_ok']}/{s['default_total']} "
          f"strict={s['strict_ok']}/{s['strict_total']} "
          f"positive={s['positive_default']}/{s['positive_strict']} "
          f"negative={s['negative_default']}/{s['negative_strict']} "
          f"failclose={s['failure_close_ok']}/{s['failure_close_total']} "
          f"chunks={report['index_chunks']} logs={report['query_log']['lines']} "
          f"unchanged={report['isolation']['ok']}")
    print(str(EVAL_REPORT))
    return 0 if all_ok else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
