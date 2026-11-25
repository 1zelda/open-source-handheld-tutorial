import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
TOOLS = ROOT / "_工具脚本"
sys.path.insert(0, str(TOOLS))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import sources as S

CANDIDATE = BASE / "megaman1_candidate_20261125"
EVIDENCE = CANDIDATE / "evidence"
CANDIDATE_MAP = CANDIDATE / "corpus_map.json"
CANDIDATE_REGISTRY = CANDIDATE / "sources.json"
CANDIDATE_INDEX = CANDIDATE / "index.json"
REPORT = BASE / "megaman1_candidate_build_20261125.json"
REVISION = "megaman1_nes_us"
LOCAL_SOURCE_ID = "local_mm1_taspipe_measurements"

EXTERNAL = {
    "tasvideos_mm1_object_ram_table": {
        "source_name": "tasvideos_gameresources_rockman_data_2026-11-23.txt",
        "raw_name": "mm1_object_ram_source_20261125.txt",
        "curated": [
            ("mm1_coordinate_facts_20261125.txt", "prose", [(167, 190)],
             "TASVideos GameResources：洛克人1坐标系统（逐字摘录）"),
            ("mm1_object_ram_table_20261125.txt", "table", [(428, 443)],
             "TASVideos GameResources：洛克人1对象 RAM 表（逐字摘录）"),
        ],
    },
    "tasvideos_bizhawk_faq_write_refresh": {
        "source_name": "tasvideos_bizhawk_faq_refresh_2026-11-23.txt",
        "raw_name": "mm1_bizhawk_faq_source_20261125.txt",
        "curated": [
            ("mm1_bizhawk_memory_write_fact_20261125.txt", "prose", [(136, 144)],
             "TASVideos BizHawk FAQ：内存覆盖与 memory write callback（逐字摘录）"),
        ],
    },
    "tasvideos_forum_19912_fm2_import": {
        "source_name": "tasvideos_forum_19912_bizhawk_import_fm2_2026-11-23.txt",
        "raw_name": "mm1_fm2_import_reference_20261125.txt",
        "curated": [
            ("mm1_fm2_import_reference_fact_20261125.txt", "prose", [(135, 151)],
             "TASVideos Forum 19912：FM2 导入 BizHawk（参考性社区流程，逐字摘录）"),
        ],
    },
    "tasvideos_glossary_segmented": {
        "source_name": "tasvideos_glossary_segmented_tas_2026-11-23.txt",
        "raw_name": "mm1_segmented_tas_reference_20261125.txt",
        "curated": [
            ("mm1_segmented_tas_reference_fact_20261125.txt", "prose", [(455, 461)],
             "TASVideos Glossary：segmented movie 通用术语（参考性，逐字摘录）"),
        ],
    },
}

REAL_PATHS = [
    K.INDEX_JSON,
    K.CORPUS_MAP,
    S.REG_JSON,
    K.KB_DIR / "query_log.jsonl",
    KE.DB_PATH,
    ROOT / "选题决策层" / "kb快照" / "index.json",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(path):
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {
        "present": True,
        "bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "sha256": sha(path),
    }


def rel(path):
    return path.relative_to(ROOT).as_posix()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def excerpt(source, start, end, target, header):
    lines = source.read_text(encoding="utf-8").splitlines()
    selected = lines[start - 1:end]
    if len(selected) != end - start + 1:
        raise RuntimeError(f"excerpt range unavailable: {source} {start}-{end}")
    text = header.rstrip() + "\n" + "\n".join(selected) + "\n"
    target.write_text(text, encoding="utf-8")
    return {
        "source": rel(source),
        "source_line_start": start,
        "source_line_end": end,
        "target": rel(target),
        "target_sha256": sha(target),
        "verbatim_lines": selected,
    }


def curated_excerpt(source, ranges, target, header):
    lines = source.read_text(encoding="utf-8").splitlines()
    sections = []
    records = []
    for start, end in ranges:
        selected = lines[start - 1:end]
        if len(selected) != end - start + 1:
            raise RuntimeError(f"excerpt range unavailable: {source} {start}-{end}")
        sections.append("\n".join(selected))
        records.append({
            "source_line_start": start,
            "source_line_end": end,
            "verbatim_lines": selected,
        })
    text = header.rstrip() + "\n" + "\n\n".join(sections) + "\n"
    target.write_text(text, encoding="utf-8")
    return {
        "source": rel(source),
        "target": rel(target),
        "target_sha256": sha(target),
        "ranges": records,
    }


def main():
    before = {str(p): snapshot(p) for p in REAL_PATHS}
    real_map = json.loads(K.CORPUS_MAP.read_text(encoding="utf-8"))
    real_registry = json.loads(S.REG_JSON.read_text(encoding="utf-8"))
    draft_path = BASE / "megaman1_questions_draft_20261124.json"
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    if draft.get("candidate_revision") != REVISION:
        raise RuntimeError("draft revision mismatch")

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    copied = {}
    curated = []
    candidate_entries = []
    original_entries = {e["source_id"]: e for e in real_map["entries"]}

    for source_id, spec in EXTERNAL.items():
        original = original_entries[source_id]
        source_path = S.resolve_path(original["path"])
        raw_target = EVIDENCE / spec["raw_name"]
        raw_target.write_bytes(source_path.read_bytes())
        if sha(source_path) != sha(raw_target):
            raise RuntimeError(f"copy hash mismatch: {source_id}")
        copied[source_id] = {
            "source": rel(source_path),
            "target": rel(raw_target),
            "sha256": sha(raw_target),
            "bytes": raw_target.stat().st_size,
            "verbatim_copy": True,
        }
        for target_name, kind, ranges, header in spec["curated"]:
            target = EVIDENCE / target_name
            record = curated_excerpt(source_path, ranges, target, header)
            record["source_id"] = source_id
            record["kind"] = kind
            curated.append(record)
            entry = dict(original)
            entry["path"] = rel(target)
            entry["kind"] = kind
            entry["index"] = True
            entry.pop("reason", None)
            entry["note"] = "隔离候选逐字摘录；" + entry.get("note", "")
            candidate_entries.append(entry)

    weapon_target = EVIDENCE / "mm1_local_weapon_ram_excerpt_20261125.txt"
    weapon_excerpt = excerpt(
        ROOT / "测试问题与闸门说明书.md",
        712,
        716,
        weapon_target,
        "# 本机实测：洛克人1武器 RAM 地址与值表（隔离候选摘录）\n"
        "来源：测试问题与闸门说明书.md 第712-716行；逐字摘录，不含撤回段。",
    )
    position_target = EVIDENCE / "mm1_local_position_probe_excerpt_20261125.txt"
    position_excerpt = excerpt(
        ROOT / "场景取得方法_调研与设计_2026-11-23.md",
        44,
        58,
        position_target,
        "# 本机实测：洛克人1对象表定位 T1 五臂试验（隔离候选摘录）\n"
        "来源：场景取得方法_调研与设计_2026-11-23.md 第44-58行；逐字摘录。",
    )

    candidate_entries.extend([
        {
            "path": rel(weapon_target),
            "source_id": LOCAL_SOURCE_ID,
            "revision": REVISION,
            "kind": "prose",
            "authority": "authoritative",
            "index": True,
            "element_types": ["帧数据", "基础档案"],
            "note": "本机生产实测逐字摘录：owned/current_weapon 地址与 0-7 值表。",
        },
        {
            "path": rel(position_target),
            "source_id": LOCAL_SOURCE_ID,
            "revision": REVISION,
            "kind": "prose",
            "authority": "authoritative",
            "index": True,
            "element_types": ["帧数据", "基础档案"],
            "note": "本机 T1 五臂受控实测逐字摘录：权威对象表与派生显示量。",
        },
    ])

    candidate_registry = json.loads(json.dumps(real_registry, ensure_ascii=False))
    external_paths = {sid: rel(EVIDENCE / spec["raw_name"]) for sid, spec in EXTERNAL.items()}
    for source in candidate_registry["sources"]:
        sid = source["source_id"]
        if sid in external_paths:
            source["evidence"] = [external_paths[sid]]
    if any(s["source_id"] == LOCAL_SOURCE_ID for s in candidate_registry["sources"]):
        raise RuntimeError("local source id already exists")
    candidate_registry["sources"].append({
        "source_id": LOCAL_SOURCE_ID,
        "name": "本机实测：洛克人1武器 RAM 与对象表定位试验（隔离候选摘录）",
        "kind": "local",
        "layer": "local_docs",
        "platforms": ["NES"],
        "element_types": ["帧数据", "基础档案"],
        "status": "verified_read",
        "last_verified": "2026-11-25",
        "urls": [],
        "evidence": [rel(weapon_target), rel(position_target)],
        "notes": "仅收录已核本机实测段落；外部原文与参考性社区材料保持各自来源资格。",
        "games_hit": ["megaman1"],
    })

    candidate_map = {
        "schema_version": 1,
        "revisions": {REVISION: dict(real_map["revisions"][REVISION])},
        "entries": candidate_entries,
    }
    candidate_map["revisions"][REVISION]["note"] = (
        "隔离候选：只覆盖 NTSC 美版洛克人1的 RAM/工具方法；未接生产路由，"
        "不代表整款游戏知识库，也不证明 PAL-B 或未核候选可代答。"
    )

    write_json(CANDIDATE_REGISTRY, candidate_registry)
    write_json(CANDIDATE_MAP, candidate_map)
    write_json(CANDIDATE / "rom_identity.json", {
        "status": "metadata_only_not_indexed",
        "candidate_revision": REVISION,
        "rom_identity": draft["rom_identity"],
        "excluded_candidates": [
            {"path": "F:/BaiduNetdiskDownload/rom/nes/洛克人1.nes",
             "sha1": "0fe255649359ece8cb64b6f24acaf09f17af746c",
             "reason": "PAL-B身份与NTSC美版不同，未验证跨版等价"},
            {"path": "mega_man_usa.nes",
             "sha1": "d8b8c5e2ee76f2ec1820123bb9f8c70f5e603923",
             "reason": "身份未核"},
        ],
        "source_draft": rel(draft_path),
    })
    write_json(CANDIDATE / "scope.json", {
        "status": "isolated_candidate_not_production",
        "revision": REVISION,
        "coverage": ["对象RAM表", "BizHawk内存写机制", "本机武器RAM实测", "本机对象表定位实测"],
        "reference_only_coverage": ["FM2导入社区流程", "segmented TAS通用术语"],
        "not_covered": ["官方说明书级玩法", "整款游戏内容知识库", "PAL-B等价性", "生产路由"],
        "production_defaults_unchanged": True,
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
    })

    S.load_registry(CANDIDATE_REGISTRY)
    K.load_map(CANDIDATE_MAP)
    build = K.build(
        map_path=CANDIDATE_MAP,
        index_path=CANDIDATE_INDEX,
        reg=candidate_registry,
        force=True,
    )
    index = K.load_index(CANDIDATE_INDEX)
    after = {str(p): snapshot(p) for p in REAL_PATHS}
    unchanged = before == after
    if not unchanged:
        raise RuntimeError("real state changed during isolated build")

    write_json(REPORT, {
        "status": "built_isolated",
        "candidate_revision": REVISION,
        "candidate_dir": str(CANDIDATE),
        "build": build,
        "index_sha256": sha(CANDIDATE_INDEX),
        "index_chunks": len(index["chunks"]),
        "index_stats": index["stats"],
        "authority_counts": {
            authority: sum(1 for c in index["chunks"] if c["authority"] == authority)
            for authority in sorted({c["authority"] for c in index["chunks"]})
        },
        "revision_counts": {
            revision: sum(1 for c in index["chunks"] if c["revision"] == revision)
            for revision in sorted({c["revision"] for c in index["chunks"]})
        },
        "source_status_counts": {
            status: sum(1 for c in index["chunks"] if c["status"] == status)
            for status in sorted({c["status"] for c in index["chunks"]})
        },
        "external_verbatim_copies": copied,
        "external_curated_excerpts": curated,
        "local_excerpts": [weapon_excerpt, position_excerpt],
        "real_state_before": before,
        "real_state_after": after,
        "real_state_unchanged": unchanged,
        "production_index_untouched": str(K.INDEX_JSON),
        "candidate_scope": "RAM/tooling subdomain only; not a whole-game knowledge base",
    })
    print(f"BUILD_OK chunks={len(index['chunks'])} files={build['files_indexed']} unchanged={unchanged}")
    print(str(CANDIDATE_INDEX))
    print(str(REPORT))


if __name__ == "__main__":
    main()
