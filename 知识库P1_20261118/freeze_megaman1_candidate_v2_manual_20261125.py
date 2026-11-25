import copy
import hashlib
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))
sys.path.insert(0, str(ROOT / "知识库小样_20261118"))

from taspipe import kb as K
from taspipe import kb_esports as KE
from taspipe import sources as S
import eval_common as E

CANDIDATE = BASE / "megaman1_candidate_v2_manual_20261125"
INDEX = CANDIDATE / "index.json"
MAP = CANDIDATE / "corpus_map.json"
REGISTRY = CANDIDATE / "sources.json"
OLD_FROZEN = BASE / "megaman1_questions_frozen_20261125.json"
FROZEN = BASE / "megaman1_questions_frozen_v2_manual_20261125.json"
REVISION = "megaman1_nes_us"
MANUAL_SOURCE_ID = "archive_mega_man_nes_us_manual"

MANUAL_QUESTIONS = [
    {
        "id": "MM13",
        "q": "洛克人1官方说明书里 A 键和 B 键分别控制什么动作？",
        "path_contains": "mm1_manual_controls_20261125.txt",
        "fact": "A 键跳跃；B 键射击",
        "manual_pages": [8],
    },
    {
        "id": "MM14",
        "q": "洛克人1官方说明书里控制 pad 的上、下、左、右分别怎么操作？",
        "path_contains": "mm1_manual_controls_20261125.txt",
        "fact": "上跳、下蹲、左移、右移",
        "manual_pages": [8],
    },
    {
        "id": "MM15",
        "q": "洛克人1官方说明书里怎样选择 Robot Master 关卡并开始战斗？",
        "path_contains": "mm1_manual_stage_select_20261125.txt",
        "fact": "按 START 显示六名敌人，用控制 pad 右端选择，再按 START 开始遭遇战",
        "manual_pages": [9],
    },
    {
        "id": "MM16",
        "q": "洛克人1 Energy Meter 监测的能量水平，受击与能量胶囊分别有什么影响？",
        "path_contains": "mm1_manual_energy_20261125.txt",
        "fact": "Energy Meter 监测能量；受击损失能量；能量胶囊恢复并提升能量",
        "manual_pages": [4],
    },
    {
        "id": "MM17",
        "q": "洛克人1官方说明书里 1 UP 和 Yashichi 的效果分别是什么？",
        "path_contains": "mm1_manual_bonus_items_20261125.txt",
        "fact": "1 UP 增加一名玩家；Yashichi 为 100,000 分奖励",
        "manual_pages": [15],
    },
    {
        "id": "MM18",
        "q": "洛克人1官方说明书里生命能量和武器能量道具分别增加什么？",
        "path_contains": "mm1_manual_bonus_items_20261125.txt",
        "fact": "生命能量道具增加生命能量；武器能量道具增加武器能量",
        "manual_pages": [15],
    },
    {
        "id": "MM19",
        "q": "洛克人1官方说明书里 Magnet Beam 在哪个关卡出现，取得后能做什么？",
        "path_contains": "mm1_manual_magnet_beam_20261125.txt",
        "fact": "在 Elecman 关卡中途出现；可制造台阶向上攀爬",
        "manual_pages": [5, 15],
    },
    {
        "id": "MM20",
        "q": "洛克人1官方说明书里六名 Robot Master 各自的设计用途或专长是什么？",
        "path_contains": "mm1_manual_robot_masters_20261125.txt",
        "fact": "Cutman 伐木、Iceman 极寒、Gutsman 搬巨石、Bombman 爆破开路、Fireman 熔铸金属、Elecman 电气与核电",
        "manual_pages": [6, 7],
    },
    {
        "id": "MM21",
        "q": "洛克人1击败六名 Robot Master 后获得的新武器在 Wily 战有什么使用限制？",
        "path_contains": "mm1_manual_progression_rewards_20261125.txt",
        "fact": "击败对手获得新火力；与 Dr. Wily 战斗时每样只能使用一次",
        "manual_pages": [5],
    },
    {
        "id": "MM22",
        "q": "洛克人1官方说明书里 Robot Master 胜利和 Dr. Wily 的得分分别是多少？",
        "path_contains": "mm1_manual_victory_scores_20261125.txt",
        "fact": "Robot Master 每次胜利 50,000–100,000 分；Dr. Wily 200,000 分",
        "manual_pages": [10, 14],
    },
    {
        "id": "MM23",
        "q": "洛克人1击败六名 Robot Master 后 Dr. Wily 何时出现，他会出现在第几关？",
        "path_contains": "mm1_manual_progression_rewards_20261125.txt",
        "fact": "Wily 的机器人手下全部消灭且背景全部出现后自动出现；第七最终关",
        "manual_pages": [9],
    },
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(path):
    path = Path(path)
    if not path.is_file():
        return {"present": False}
    st = path.stat()
    return {"present": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
            "sha256": sha(path)}


def main():
    guarded = [INDEX, MAP, REGISTRY, OLD_FROZEN, K.INDEX_JSON, K.CORPUS_MAP,
               S.REG_JSON, K.KB_DIR / "query_log.jsonl", KE.DB_PATH,
               ROOT / "选题决策层" / "kb快照" / "index.json"]
    before = {str(p): snapshot(p) for p in guarded}
    old = json.loads(OLD_FROZEN.read_text(encoding="utf-8"))
    index = K.load_index(INDEX)
    registry = S.load_registry(REGISTRY)
    chunks = index["chunks"]
    questions = copy.deepcopy(old["questions"])

    for item in questions:
        gold = item.get("gold")
        if not gold:
            continue
        old_id = gold.get("anchor_chunk")
        matches = [c for c in chunks if gold["path_contains"] in c["path"]]
        anchored = next((c for c in matches if c["chunk_id"] == old_id), None)
        if anchored is None:
            anchored = next((c for c in matches if c["line_start"] <= gold["line_end"]
                             and c["line_end"] >= gold["line_start"]), None)
        if anchored is None:
            raise RuntimeError(f"cannot re-anchor inherited gold: {item['id']}")
        gold["anchor_chunk"] = anchored["chunk_id"]

    for spec in MANUAL_QUESTIONS:
        matches = [c for c in chunks if spec["path_contains"] in c["path"]]
        if len(matches) != 1:
            raise RuntimeError(f"manual gold chunk not unique: {spec['id']} {len(matches)}")
        chunk = matches[0]
        if chunk["source_id"] != MANUAL_SOURCE_ID or chunk["authority"] != "authoritative":
            raise RuntimeError(f"manual gold authority mismatch: {spec['id']}")
        questions.append({
            "id": spec["id"], "q": spec["q"],
            "filters": {"revision": REVISION}, "expect": "strict_pass",
            "gold": {"path_contains": spec["path_contains"],
                     "line_start": chunk["line_start"], "line_end": chunk["line_end"],
                     "anchor_chunk": chunk["chunk_id"]},
            "fact": spec["fact"], "manual_pages": spec["manual_pages"],
            "authority_basis": "Capcom 美国 NES 官方说明书 Internet Archive 扫描页；本轮直接读图核验的短摘录",
        })

    if len({q["id"] for q in questions}) != len(questions):
        raise RuntimeError("duplicate frozen question id")
    checks = []
    for item in questions:
        result = K.query(item["q"], revision=REVISION, topk=8, index_path=INDEX,
                         map_path=MAP, reg=registry, top_window=3,
                         fragment_policy="strict", require_verified=True)
        grade = E.grade_v2(item, result)
        selected = result.get("selected_evidence") or []
        gold_ok = (item["expect"] == "refuse" and not selected) or (
            item["expect"] == "strict_pass" and len(selected) == 1
            and item["gold"]["path_contains"] in selected[0].get("locator", ""))
        checks.append({"id": item["id"], "status": result.get("status"),
                       "grade_ok": grade["ok"], "gold_ok": gold_ok,
                       "selected_locator": selected[0].get("locator") if selected else None})
    failed = [c for c in checks if not c["grade_ok"] or not c["gold_ok"]]
    if failed:
        raise RuntimeError(f"frozen validation failed: {json.dumps(failed, ensure_ascii=False)}")

    expected_counts = {
        "total": len(questions),
        "strict_pass": sum(q["expect"] == "strict_pass" for q in questions),
        "refuse": sum(q["expect"] == "refuse" for q in questions),
    }
    doc = {
        "schema_version": 3,
        "status": "frozen",
        "frozen_at": "2026-11-25",
        "design_note": "洛克人1隔离候选v2：RAM/工具方法 + 扫描核验官方说明书短摘录。金标按本候选真实chunk重锚；不是整款游戏知识库。",
        "candidate_revision": REVISION,
        "candidate_index": CANDIDATE.relative_to(ROOT).as_posix() + "/index.json",
        "candidate_index_sha256": sha(INDEX),
        "source_draft": old.get("source_draft"),
        "inherited_frozen": OLD_FROZEN.relative_to(ROOT).as_posix(),
        "rom_identity": old["rom_identity"],
        "manual_source": {
            "source_id": MANUAL_SOURCE_ID,
            "archive_item": "https://archive.org/details/mega-man-nes-manual",
            "verification": "scan_visually_read_short_excerpts_only",
            "full_manual_in_candidate": False,
        },
        "expected_counts": expected_counts,
        "questions": questions,
        "freeze_validation": checks,
    }
    tmp = FROZEN.with_name(FROZEN.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(FROZEN)
    after = {str(p): snapshot(p) for p in guarded}
    if before != after:
        raise RuntimeError("guarded state changed while freezing")
    print(f"FREEZE_OK total={expected_counts['total']} pass={expected_counts['strict_pass']} "
          f"refuse={expected_counts['refuse']} sha256={doc['candidate_index_sha256']}")
    print(str(FROZEN))


if __name__ == "__main__":
    main()
