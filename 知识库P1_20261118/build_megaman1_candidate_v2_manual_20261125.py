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

OLD_CANDIDATE = BASE / "megaman1_candidate_20261125"
CANDIDATE = BASE / "megaman1_candidate_v2_manual_20261125"
EVIDENCE = CANDIDATE / "evidence"
CANDIDATE_MAP = CANDIDATE / "corpus_map.json"
CANDIDATE_REGISTRY = CANDIDATE / "sources.json"
CANDIDATE_INDEX = CANDIDATE / "index.json"
REPORT = BASE / "megaman1_candidate_v2_manual_build_20261125.json"
REVISION = "megaman1_nes_us"
MANUAL_SOURCE_ID = "archive_mega_man_nes_us_manual"
MANUAL_PDF_SHA256 = "0fa36c585743a67e76839a67a4fee88894d64eecc455e6b1bf9c4ae7f7937445"
MANUAL_PDF_SHA1 = "4e5dd2d36bdd2f592eded91f996e7a751862d24b"

MANUAL_EXCERPTS = [
    {
        "name": "mm1_manual_controls_20261125.txt",
        "pages": [8],
        "heading": "洛克人1 官方说明书：A键 B键 控制动作 跳跃 射击 十字键操作（美国NES手册第8页）",
        "facts": [
            "Button A：按 A 键使 MEGA MAN 跳跃。",
            "Button B：按 B 键射击。",
            "Control Pad：左使 MEGA MAN 向左移动，右使其向右移动，上使其向上跳，下使其蹲下。",
        ],
        "quotes": [
            "Button A: Press to make MEGA MAN jump.",
            "Button B: Press to fire.",
            "MEGA MAN moves left. MEGA MAN moves right. MEGA MAN leaps upward. MEGA MAN crouches down.",
        ],
    },
    {
        "name": "mm1_manual_stage_select_20261125.txt",
        "pages": [9],
        "heading": "洛克人1 官方说明书：START 选关 开始遭遇战（美国NES手册第9页）",
        "facts": [
            "按 START 后显示六名 Robot Master 敌人；用控制 pad 的右端选择要挑战的敌人。",
            "再次按 START 开始与玩家选定的敌人角色遭遇。",
            "每击败一个关键角色，其背景变黑；Dr. Wily 的六个机器人手下全部消灭且所有背景出现后，Dr. Wily 自动出现，进入第七最终关。",
        ],
        "quotes": [
            "Press START Button. Six of MEGA MAN's seven empire enemies will be displayed on the TV/monitor screen.",
            "Re-press START Button. To begin encounter with the enemy character selected by the player.",
            "Every time a key character is defeated by MEGA MAN, the background of enemy's regime becomes black.",
            "When all of Dr. Wily's re-programmed humanoids are eliminated, and all backgrounds appear, Dr. Wily appears automatically.",
        ],
    },
    {
        "name": "mm1_manual_energy_20261125.txt",
        "pages": [4],
        "heading": "洛克人1 官方说明书：Energy Meter 生命能量 受伤 能量胶囊（美国NES手册第4页）",
        "facts": [
            "游戏画面左上方的 Energy Meter 用于监测 MEGA MAN 的能量水平。",
            "MEGA MAN 被敌人击中时能量会减少；赢得 energy capsule 可恢复并提升能量。",
        ],
        "quotes": [
            "A thermometer-shaped MEGA MAN \"Energy Meter\" appearing upper left in game-playing scenes serves to monitor MEGA MAN's power levels.",
            "If and when MEGA MAN is bodily struck or hit with enemy projectiles, degrees of energy are lost.",
            "Conversely, the player's MEGA MAN power is boosted by winning energy capsules.",
        ],
    },
    {
        "name": "mm1_manual_bonus_items_20261125.txt",
        "pages": [15],
        "heading": "洛克人1 官方说明书：1UP 生命能量 武器能量 Yashichi 奖励符号（美国NES手册第15页）",
        "facts": [
            "1 UP 增加一名玩家。",
            "life energy 图标增加玩家生命能量；weapon energy 图标增加玩家武器能量。",
            "Yashichi 是 100,000 points bonus。",
        ],
        "quotes": [
            "1 UP. It adds one player.",
            "The player's life energy increases. The player's weapon energy increases.",
            "Yashichi. 100,000 points bonus.",
        ],
    },
    {
        "name": "mm1_manual_magnet_beam_20261125.txt",
        "pages": [5, 15],
        "heading": "洛克人1 官方说明书：Magnet Beam 出现关卡 制造台阶 向上攀爬（美国NES手册第5及15页）",
        "facts": [
            "Magnet Beam 在 Elecman 关卡中途出现。",
            "取得 Magnet Beam 后可制造台阶，用于向上攀爬。",
        ],
        "quotes": [
            "A Magnet Beam will appear at the middle of the Elecman stage. Snare the Magnet Beam to create steps for climbing upward.",
            "Magnet Beam. The player can create a step to go up.",
        ],
    },
    {
        "name": "mm1_manual_robot_masters_20261125.txt",
        "pages": [6, 7],
        "heading": "洛克人1 官方说明书：六名 Robot Master 身份 职业 专长（美国NES手册第6至7页）",
        "facts": [
            "Cutman 设计为 lumberjack，使用强力锯状工具并能穿过巨大森林。",
            "Iceman 用于 sub-zero 极寒环境，能在极端气候下行动。",
            "Gutsman 能举起并搬运巨大石块。",
            "Bombman 能徒手掀翻强力爆炸物，为 Dr. Wright 的建设项目开垦土地。",
            "Fireman 用火焰融化并铸造金属。",
            "Elecman 计划承担电气操作及超级核电厂供电。",
        ],
        "quotes": [
            "Cutman: Designed to function as a lumberjack ... capable of gnawing through giant forest timbers.",
            "Iceman: Impervious to chilling sub-zero temperatures ... under extreme climatic conditions.",
            "Gutsman: ... capable of lifting and transporting huge boulders.",
            "Bombman: ... utilizes intensely explosive explosives to clear lands for Dr. Wright's construction projects.",
            "Fireman: Melts and molds metals with flame-throwing torch ...",
            "Elecman: ... planned for conducting electrical operations ... supervising nuclear power plants.",
        ],
    },
    {
        "name": "mm1_manual_progression_rewards_20261125.txt",
        "pages": [5, 9],
        "heading": "洛克人1 官方说明书：击败六名 Robot Master 获得新火力 Wily 最终关 仅用一次（美国NES手册第5及9页）",
        "facts": [
            "每次 MEGA MAN 成功单挑击败六名对手之一，就会获得一种新 firepower，进入最终关挑战 Dr. Wily 时使用。",
            "新获得的武器只能在与 Dr. Wily 的战斗中使用一次。",
            "击败 Wily 所有机器人手下且全部背景出现后，Wily 自动出现，第七最终关开始。",
        ],
        "quotes": [
            "Each time MEGA MAN successfully out-duels each of his six foes, he acquires new firepower as MEGA MAN enters final stage to defeat evil Dr. Wily.",
            "All MEGA MAN must use the newly-acquired armament wisely, for he can use them just once while engaged in battle with Dr. Wily.",
            "Dr. Wily appears automatically. It is now time for the player to conquer Dr. Wily in his seventh and final stage.",
        ],
    },
    {
        "name": "mm1_manual_victory_scores_20261125.txt",
        "pages": [10, 14],
        "heading": "洛克人1 官方说明书：Robot Master 胜利得分 Dr. Wily 200000 分（美国NES手册第10及14页）",
        "facts": [
            "每击败一名 Robot Master 可得 50,000 至 100,000 points。",
            "Dr. Wily 价值 200,000 Points，出现在最终关。",
        ],
        "quotes": [
            "Earn From 50,000 To 100,000 Points Per Victory.",
            "Dr. Wily. 200,000 Points. It appears on the final stage.",
        ],
    },
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(path):
    path = Path(path)
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": sha(path)}


def rel(path):
    return Path(path).relative_to(ROOT).as_posix()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_manual_excerpt(spec):
    lines = [spec["heading"], "", "来源：Capcom 美国 NES 官方说明书扫描件。",
             "核验：已读扫描页；中文为说明，英文为短引文；未收全本。", ""]
    for fact, quote in zip(spec["facts"], spec["quotes"]):
        lines.extend([fact, f"> {quote}", ""])
    target = EVIDENCE / spec["name"]
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "target": rel(target),
        "target_sha256": sha(target),
        "scan_pdf_pages": spec["pages"],
        "printed_manual_pages": spec["pages"],
        "scan_visually_read": True,
        "fact_count": len(spec["facts"]),
        "quotes": spec["quotes"],
    }


def main():
    real_paths = [K.INDEX_JSON, K.CORPUS_MAP, S.REG_JSON, K.KB_DIR / "query_log.jsonl",
                  KE.DB_PATH, ROOT / "选题决策层" / "kb快照" / "index.json"]
    old_paths = [OLD_CANDIDATE / "index.json", OLD_CANDIDATE / "corpus_map.json",
                 OLD_CANDIDATE / "sources.json"]
    before = {str(p): snapshot(p) for p in real_paths + old_paths}
    old_map = K.load_map(OLD_CANDIDATE / "corpus_map.json")
    old_registry = S.load_registry(OLD_CANDIDATE / "sources.json")
    if REVISION not in old_map["revisions"]:
        raise RuntimeError("old candidate revision missing")

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    entries = []
    for old in old_map["entries"]:
        source = S.resolve_path(old["path"])
        target = EVIDENCE / source.name
        target.write_bytes(source.read_bytes())
        if sha(source) != sha(target):
            raise RuntimeError(f"inherited evidence copy mismatch: {source}")
        entry = dict(old)
        entry["path"] = rel(target)
        entries.append(entry)

    manual_records = [write_manual_excerpt(spec) for spec in MANUAL_EXCERPTS]
    for record in manual_records:
        entries.append({
            "path": record["target"],
            "source_id": MANUAL_SOURCE_ID,
            "revision": REVISION,
            "kind": "prose",
            "authority": "authoritative",
            "index": True,
            "element_types": ["说明书", "基础档案"],
            "note": "美国NES官方说明书扫描页短摘录；已逐页读图核对，不是转录件或整本手册再分发。",
        })

    registry = json.loads(json.dumps(old_registry, ensure_ascii=False))
    by_source = {}
    for entry in entries:
        by_source.setdefault(entry["source_id"], []).append(entry["path"])
    for source in registry["sources"]:
        if source["source_id"] in by_source:
            source["evidence"] = by_source[source["source_id"]]
    if any(s["source_id"] == MANUAL_SOURCE_ID for s in registry["sources"]):
        raise RuntimeError("manual source id already exists")
    registry["sources"].append({
        "source_id": MANUAL_SOURCE_ID,
        "name": "Capcom Mega Man 美国 NES Game Pak Instructions（Internet Archive 扫描核验短摘录）",
        "kind": "print",
        "layer": "official_manual",
        "platforms": ["NES"],
        "element_types": ["说明书", "基础档案"],
        "status": "verified_read",
        "last_verified": "2026-11-25",
        "urls": ["https://archive.org/details/mega-man-nes-manual"],
        "evidence": [r["target"] for r in manual_records],
        "notes": "仅保存8个短摘录文件；完整商业手册扫描未进入候选或交付目录。转录页只用于导航，入选事实均直接读扫描页。",
        "games_hit": ["megaman1"],
    })

    candidate_map = {
        "schema_version": 1,
        "revisions": {REVISION: dict(old_map["revisions"][REVISION])},
        "entries": entries,
    }
    candidate_map["revisions"][REVISION]["note"] = (
        "隔离候选v2：NTSC美版洛克人1的RAM/工具方法，以及经扫描核验的官方说明书级操作与流程短摘录；"
        "仍不是整款游戏知识库，不证明PAL-B或其他版本等价。"
    )
    write_json(CANDIDATE_REGISTRY, registry)
    write_json(CANDIDATE_MAP, candidate_map)
    write_json(CANDIDATE / "manual_source.json", {
        "status": "scan_verified_short_excerpts_only",
        "source_id": MANUAL_SOURCE_ID,
        "title": "MEGA MAN — Game Pak Instructions (US NES)",
        "creator": "Capcom",
        "archive_item": "https://archive.org/details/mega-man-nes-manual",
        "archive_pdf": "https://archive.org/download/mega-man-nes-manual/Mega-Man-Game-Manual.pdf",
        "archive_publication_date": "2024-02-20",
        "original_pdf_sha1": MANUAL_PDF_SHA1,
        "downloaded_pdf_sha256": MANUAL_PDF_SHA256,
        "downloaded_pdf_bytes": 1125792,
        "pdf_pages": 10,
        "printed_page_range": "1-19 (landscape folded spreads)",
        "region_identity_evidence": "Cover: Licensed For Play Only with the Nintendo Entertainment System; Capcom USA address; Printed in Japan.",
        "verification": "All 10 scan pages were rendered and visually read. Selected passages on printed pages 4-10, 14 and 15 were compared with the typed transcription; the scan is authoritative.",
        "typed_transcription_role": "navigation_only_not_indexed",
        "full_manual_stored_in_candidate": False,
        "excerpts": manual_records,
    })
    write_json(CANDIDATE / "scope.json", {
        "status": "isolated_candidate_v2_manual_not_production",
        "revision": REVISION,
        "coverage": ["对象RAM表", "BizHawk内存写机制", "本机武器RAM实测", "本机对象表定位实测",
                     "官方说明书操作按键", "官方说明书选关流程", "官方说明书能量与奖励道具",
                     "官方说明书Magnet Beam", "官方说明书Robot Master身份", "官方说明书进度奖励与得分"],
        "reference_only_coverage": ["FM2导入社区流程", "segmented TAS通用术语"],
        "not_covered": ["整款游戏内容知识库", "全部敌人与关卡数据", "PAL-B等价性", "目标时刻存档点续作", "生产路由切换"],
        "production_defaults_unchanged": True,
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
    })

    S.load_registry(CANDIDATE_REGISTRY)
    K.load_map(CANDIDATE_MAP)
    build = K.build(map_path=CANDIDATE_MAP, index_path=CANDIDATE_INDEX,
                    reg=registry, force=True)
    index = K.load_index(CANDIDATE_INDEX)
    after = {str(p): snapshot(p) for p in real_paths + old_paths}
    changed = [p for p in before if before[p] != after[p]]
    if changed:
        raise RuntimeError(f"guarded state changed during isolated build: {changed}")
    write_json(REPORT, {
        "status": "built_isolated_v2_manual",
        "candidate_revision": REVISION,
        "candidate_dir": str(CANDIDATE),
        "build": build,
        "index_sha256": sha(CANDIDATE_INDEX),
        "index_chunks": len(index["chunks"]),
        "index_stats": index["stats"],
        "manual_source_id": MANUAL_SOURCE_ID,
        "manual_excerpts": manual_records,
        "authority_counts": {a: sum(c["authority"] == a for c in index["chunks"])
                             for a in sorted({c["authority"] for c in index["chunks"]})},
        "source_status_counts": {s: sum(c["status"] == s for c in index["chunks"])
                                 for s in sorted({c["status"] for c in index["chunks"]})},
        "real_state_unchanged": all(before[str(p)] == after[str(p)] for p in real_paths),
        "old_candidate_unchanged": all(before[str(p)] == after[str(p)] for p in old_paths),
        "guarded_state_before": before,
        "guarded_state_after": after,
        "changed_paths": changed,
        "candidate_scope": "RAM/tooling plus scan-verified official-manual excerpts; not a whole-game knowledge base",
    })
    print(f"BUILD_OK chunks={len(index['chunks'])} files={build['files_indexed']} changed={changed}")
    print(str(CANDIDATE_INDEX))
    print(str(REPORT))


if __name__ == "__main__":
    main()
