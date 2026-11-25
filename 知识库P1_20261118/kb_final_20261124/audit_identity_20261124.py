# -*- coding: utf-8 -*-
import collections
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(r"F:\开源掌机教程")
OUT = ROOT / "知识库P1_20261118" / "kb_final_20261124" / "version_identity_audit_20261124.json"
sys.path.insert(0, str(ROOT / "_工具脚本"))

from taspipe import registry as R
from taspipe import sources as S


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


corpus_path = ROOT / "_工具脚本" / "taspipe" / "游戏包" / "知识库" / "corpus_map.json"
corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
reg = S.load_registry()
by_source = {s["source_id"]: s for s in reg["sources"]}
entries = {e["revision"]: e for e in corpus["entries"] if e.get("revision")}

rom_idx = R.index_roms(R.DEFAULT_LIB)
known = {
    "nekketsu_soccer2_fc_jp": "05D9FBAA15EB1DD793563CA7BE74D0279A2AB94F",
    "megaman1_nes_us": "2F88381557339A14C20428455F6991C1EB902C99",
}
rom_hits = {rid: rom_idx.get(sha, []) for rid, sha in known.items()}
set_ids = {name: S.resolve_identity(name, set_name=name, platform="ARCADE")
           for name in ("kof98eck", "kof98um", "kof98umh", "kof98umhd")}

revisions = {}
for rid in (
    "arcade_hack_multi",
    "kof98um",
    "nekketsu_kakutou_densetsu_fc_revB_patch",
    "nekketsu_soccer2_fc_cn_hack",
    "nekketsu_soccer2_fc_unspecified",
    "nekketsu_soccer_mobile",
):
    es = [e for e in corpus["entries"] if e.get("revision") == rid]
    revisions[rid] = {
        "corpus_entries": [
            {
                "path": e["path"],
                "source_id": e.get("source_id"),
                "authority": e.get("authority"),
                "source_status": by_source.get(e.get("source_id"), {}).get("status"),
                "index": e.get("index", True),
            }
            for e in es
        ],
        "mechanism_authority_available": False,
        "promoted": False,
    }

revb_path = ROOT / "_工具脚本" / "taspipe" / "游戏包" / "来源库" / "取证" / "dvd_熱血格闘伝説_RevB版本边界_20261124.md"
revisions["nekketsu_kakutou_densetsu_fc_revB_patch"].update({
    "identity_status": "documented_patch_boundary",
    "identity_evidence": {"path": str(revb_path), "sha256": sha256(revb_path)},
    "identity_note": "DvD Rev.B 补丁边界有本机取证；它不是原版 FC ROM，身份证据不得回填原版能力。",
})
revisions["arcade_hack_multi"].update({
    "identity_status": "aggregate_not_single_identity",
    "identity_evidence": {"resolved_child_set": set_ids["kof98eck"]},
    "identity_note": "8200 款总表不是单卡身份；ECK 子集已解析不等于整表或任一未点名 hack 已解析。",
})
revisions["kof98um"].update({
    "identity_status": "unresolved_local_set",
    "identity_evidence": set_ids,
    "identity_note": "本地 setlist 有 kof98umh/kof98umhd 的占位行但无可用 ini；kof98um 本身未解析。UM 出招表对 ECK 仅跨版本参考。",
})
revisions["nekketsu_soccer2_fc_cn_hack"].update({
    "identity_status": "unresolved_exact_rom",
    "identity_evidence": {"required": "精确 ROM SHA-1 或官方/作者版本身份说明", "present": False},
    "identity_note": "现有汉化条目只有身份/下载线索，无逐帧机制正文；不能继承日版实测。",
})
revisions["nekketsu_soccer2_fc_unspecified"].update({
    "identity_status": "intentionally_unspecified",
    "identity_evidence": {"required": "逐来源锁定 JP/CN/hack", "present": False},
    "identity_note": "该 revision 专为未点名版本线索而设；升级前必须逐来源定版，不能整体提升。",
})
revisions["nekketsu_soccer_mobile"].update({
    "identity_status": "separate_mobile_title",
    "identity_evidence": {"source_id": "9game", "platform": "MOBILE"},
    "identity_note": "正文是 ARC SYSTEM WORKS 授权手游，不是 FC 联盟；not_applicable 是正确隔离而非缺口。",
})

result = {
    "schema_version": 1,
    "date": "2026-11-24",
    "criterion": "身份证据与机制权威分开；只有 verified_read + authoritative 且身份与机制正文相符才提升。",
    "production_paths": {
        "rom_index": "taspipe.registry.index_roms",
        "set_identity": "taspipe.sources.resolve_identity",
    },
    "rom_exact_hash_hits": rom_hits,
    "set_identity": set_ids,
    "revisions": revisions,
    "promoted": [],
    "summary": {
        "retained_unverified": len(revisions),
        "promoted": sum(bool(v.get("promoted")) for v in revisions.values()),
        "identity_status_counts": dict(collections.Counter(
            v.get("identity_status", "missing") for v in revisions.values())),
    },
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"out": str(OUT), "rom_hits": rom_hits, "set_status": {
    k: v["status"] for k, v in set_ids.items()}}, ensure_ascii=False))
