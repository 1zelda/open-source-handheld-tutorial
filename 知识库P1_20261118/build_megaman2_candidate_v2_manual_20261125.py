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

OLD_CANDIDATE = BASE / "megaman2_candidate_20261125"
CANDIDATE = BASE / "megaman2_candidate_v2_manual_20261125"
EVIDENCE = CANDIDATE / "evidence"
CANDIDATE_MAP = CANDIDATE / "corpus_map.json"
CANDIDATE_REGISTRY = CANDIDATE / "sources.json"
CANDIDATE_INDEX = CANDIDATE / "index.json"
CANDIDATE_CONTRACT = CANDIDATE / "contract.json"
FROZEN = BASE / "megaman2_questions_frozen_v2_manual_20261125.json"
REPORT = BASE / "megaman2_candidate_v2_manual_build_20261125.json"
MANUAL_REVISION = "megaman2_nes_us_manual"
MANUAL_SOURCE_ID = "nintendo_mega_man_2_nes_us_manual"
TECH_REVISION = "megaman2_nes_tasvideos_rockman2"
MEMORY_REVISION = "megaman2_nes_memory_dictionary_unverified"
CATALOG_REVISION = "megaman2_nes_title_catalog"
TAS_REVISION = "megaman2_nes_tas_publications"
TECH_SOURCE = "tasvideos_rockman_data_mm2_extract"
MEMORY_SOURCE = "local_megaman2_memory_dictionary"
CATALOG_SOURCE = "local_megaman2_title_catalog"
TAS_SOURCE = "local_megaman2_tas_publications"
MANUAL_PDF_SHA256 = "d3c7acf731d551dc6e1cb755b7f0d83289508598bd6d368620e950fbc373599d"
MANUAL_PDF_SHA1 = "0909b493a1a2092d7258eef952a8d4b461e5c781"
ARCHIVE_PDF_SHA256 = "268d08002ab673b2ff70a277ac532f376e6809fe6d1978ae5760c473dcd802ad"

MANUAL_EXCERPTS = [
    {
        "name": "mm2_manual_controls_20261125.txt",
        "pages": [4, 5],
        "heading": "洛克人2 官方说明书：A键 B键 跳跃 射击 爬梯 START 暂停 无敌（美国NES手册第4至5页）",
        "facts": [
            "左和右用于移动，跳跃或下落时仍可移动；上和下用于上下爬梯。",
            "A键用于跳跃，按住越久跳得越高；在梯顶按上起跳会跌下梯子。",
            "B键用于射击，跳跃或下落时也能射击。",
            "START用于切换武器、使用能量晶体、查看生命并暂停游戏。",
            "Mega Man受击后约有一到两秒无敌。",
        ],
        "quotes": [
            "Pushing RIGHT and LEFT on the controller moves Mega Man right and left. This works even when he is jumping or falling.",
            "The A button is used for jumping. The longer you hold the button down, the higher Mega Man will jump.",
            "The B button is used for shooting. ... Mega Man can shoot while he is jumping or falling.",
            "The START button is used for changing weapons, using energy crystals, ... It is also a convenient way to pause the game.",
            "When Mega Man is damaged, he is invulnerable for a second or two.",
        ],
    },
    {
        "name": "mm2_manual_stage_select_20261125.txt",
        "pages": [3],
        "heading": "洛克人2 官方说明书：NORMAL DIFFICULT START PASSWORD STAGE SELECT 八名 Robot Master Wily（美国NES手册第3页）",
        "facts": [
            "标题画面用SELECT选择NORMAL或DIFFICULT模式，再按START开始。",
            "玩家必须选择START或输入PASSWORD；PASSWORD选项在说明书后文说明。",
            "STAGE SELECT画面显示八名敌方机器人和中间为Dr. Wily预留的位置。",
            "用控制pad移动选择框，按START确认；初学者可先选Metal Man，或先试Air Man/Flash Man。",
        ],
        "quotes": [
            "Use SELECT to choose NORMAL or DIFFICULT mode. Press START to begin the game.",
            "You must now choose to START or enter a PASSWORD.",
            "This screen has pictures of all eight enemy robots plus a slot in the middle for Dr. Wily.",
            "Use the control pad to move the flashing box to the opponent of your choice and press START.",
        ],
    },
    {
        "name": "mm2_manual_energy_20261125.txt",
        "pages": [6, 7],
        "heading": "洛克人2 官方说明书：Energy Meter life energy pellet ball crystal 武器能量 1UP（美国NES手册第6至7页）",
        "facts": [
            "左上角Energy Meter显示还能承受多少伤害，归零时失去一条Mega Man生命。",
            "energy pellet和energy ball补充少量生命能量；energy crystal是满能量，可在电量低时使用。",
            "按START选择Energy crystal，再按START将能量补满，然后重新选武器并按START。",
            "选择标准Mega Man以外的武器时会出现第二能量表，表示当前武器剩余能量。",
            "1 UP增加一名玩家。",
        ],
        "quotes": [
            "When the meter reaches zero points, one Mega Man life will be lost.",
            "There is also an energy crystal. This is a full load of energy that Mega Man can carry around with him.",
            "Push the START button again to fill your energy back up to maximum.",
            "This tells how much charge remains in the current weapon.",
            "1 UP. Adds One Player.",
        ],
    },
    {
        "name": "mm2_manual_special_items_20261125.txt",
        "pages": [8],
        "heading": "洛克人2 官方说明书：Heat Man Air Man Flash Man 特殊交通工具 飞行平台 喷气雪橇 电梯（美国NES手册第8页）",
        "facts": [
            "击败Heat Man后取得悬浮平台，最多可同时发射三个。",
            "击败Air Man后取得喷气雪橇，可飞越困难区域。",
            "击败Flash Man后取得电梯，只能贴着墙使用，且能到达比悬浮平台更高的位置。",
        ],
        "quotes": [
            "Acquired when Heat Man is defeated. This is a levitation platform. Up to three may be launched at a time.",
            "Acquired when Air Man is defeated. This is a jet sled. Use it to fly over difficult areas.",
            "Acquired when Flash Man is defeated. This is an elevator and may only be used against a wall.",
        ],
    },
    {
        "name": "mm2_manual_passwords_20261125.txt",
        "pages": [9],
        "heading": "洛克人2 官方说明书：PASSWORD 气泡 续作 Stage Select（美国NES手册第9页）",
        "facts": [
            "每击败一个敌人后，可选择Stage Select或Password。",
            "选择Password会显示当前密码；记下气泡位置，下次可从同一游戏进度继续。",
            "下次开始选择Password，用控制pad移动光标，在原来有气泡的方格按A输入。",
        ],
        "quotes": [
            "After defeating each enemy, you will have a choice between either Stage Select or Password.",
            "Simply keep track of where the bubbles are and next time you begin the game, you can continue from that point.",
            "Move the cursor around with the control pad and hit the A button in each square that had a bubble in it before.",
        ],
    },
    {
        "name": "mm2_manual_airman_20261125.txt",
        "pages": [10, 11, 12, 13],
        "heading": "洛克人2 官方说明书：HOW TO BEAT AIRMAN Air Tikk Lightning Lord Air Flend 龙卷风（美国NES手册第10至13页）",
        "facts": [
            "选Air Man关卡后，在每节末尾按START暂停，再按START返回游戏。",
            "Air Tikk出现时跳上其角，射击Lump，并等待角降下后重复，五次后召唤下一只。",
            "射击Lightning Lord，跳上其战车；随后对付Air Flend并进入Air Man房间。",
            "Airman投出会偏转子弹并造成伤害的小龙卷风；接近后快速射击。",
        ],
        "quotes": [
            "Push the START button to pause at the end of each section. (Remember: You must push START again to return to the game.)",
            "Jump onto it as soon as it starts to lower its horns, run across and jump to the platform on the other side.",
            "Jump up and shoot him until he explodes. Then jump onto his Thunder Chariot.",
            "Airman throws small tornados which deflect your shots and damage you.",
        ],
    },
    {
        "name": "mm2_manual_robot_masters_20261125.txt",
        "pages": [14, 15],
        "heading": "洛克人2 官方说明书：八名 Robot Master Wood Clash Quick Heat Metal Air Flash Bubble（美国NES手册第14至15页）",
        "facts": [
            "说明书的Weapons页列出八名Robot Master：Wood Man、Clash Man、Quick Man、Heat Man、Metal Man、Air Man、Flash Man、Bubble Man。",
            "Mega Man每击败一个敌人就取得对方的力量。",
        ],
        "quotes": [
            "Wood Man Clash Man Quick Man Heat Man Metal Man Air Man Flash Man Bubble Man",
            "As Mega Man defeats each enemy, he acquires their powers.",
        ],
    },
    {
        "name": "mm2_manual_weapons_20261125.txt",
        "pages": [15],
        "heading": "洛克人2 官方说明书：Atomic Fire Air Shooter Leaf Shield Bubble Lead Quick Boomerang Time Stopper Metal Blade Crash Bomber 武器（美国NES手册第15页）",
        "facts": [
            "Heat Man的Atomic Fire可射出三种火球，按住B越久火球越大。",
            "Air Man的Air Shooter发射小龙卷风。",
            "Wood Man的Leaf Shield形成护盾，叶片按控制pad方向投掷。",
            "Bubble Man的Bubble Lead形成沿地面滚动的泡泡。",
            "Quick Man的Quick Boomerang最多连发三枚回旋镖。",
            "Flash Man的Time Stopper暂时冻结所有敌人，但会持续消耗能量且不能提前关闭。",
            "Metal Man的Metal Blade最多向任意方向投掷三枚，被说明书称为最佳通用武器且持续时间长。",
            "Crash Man的Crash Bomber可掷向墙壁，短暂延迟后爆炸，可用于穿过某些墙壁。",
        ],
        "quotes": [
            "The longer you hold the fire button, the bigger the fireball.",
            "Air Shooter throws small tornados.",
            "The leaves are then thrown in the direction the control pad is pushed.",
            "Bubble Lead is a bubble that rolls along the ground in front of you.",
            "Quick Boomerang can throw up to three boomerangs.",
            "It cannot be turned off early.",
            "This is probably the best general purpose weapon and the energy lasts a long time.",
            "Crash Bomber can be thrown at walls and will detonate after a short delay.",
        ],
    },
]

QUESTION_SPECS = [
    {"id": "MM101", "q": "洛克人2 的 walking speed 是什么？", "expect": "strict_pass",
     "revision": TECH_REVISION, "source_id": TECH_SOURCE,
     "target": "mm2_tasvideos_walking_20261125.txt", "contains": "01.60"},
    {"id": "MM102", "q": "Rockman 2 的 X speed 内存地址是什么？", "expect": "strict_pass",
     "revision": TECH_REVISION, "source_id": TECH_SOURCE,
     "target": "mm2_tasvideos_object_table_20261125.txt", "contains": "$460:$480"},
    {"id": "MM103", "q": "MM2 的 jump Y speed 初始值是什么？", "expect": "strict_pass",
     "revision": TECH_REVISION, "source_id": TECH_SOURCE,
     "target": "mm2_tasvideos_jump_20261125.txt", "contains": "04.DF"},
    {"id": "MM104", "q": "Mega Man 2 的 climbing speed 是什么？", "expect": "strict_pass",
     "revision": TECH_REVISION, "source_id": TECH_SOURCE,
     "target": "mm2_tasvideos_climb_transform_20261125.txt", "contains": "00.C0"},
    {"id": "MM105", "q": "Ｍｅｇａ　Ｍａｎ　２ 的 walking speed 是什么？", "expect": "strict_pass",
     "revision": TECH_REVISION, "source_id": TECH_SOURCE,
     "target": "mm2_tasvideos_walking_20261125.txt", "contains": "01.60"},
    {"id": "MM201", "q": "洛克人2美版官方说明书里跳跃和射击：A 键和 B 键分别控制什么？", "expect": "strict_pass",
     "revision": MANUAL_REVISION, "source_id": MANUAL_SOURCE_ID, "manual_pages": [4, 5],
     "target": "mm2_manual_controls_20261125.txt", "contains": "The A button is used for jumping"},
    {"id": "MM202", "q": "洛克人2官方说明书里 energy crystal 有什么作用，怎么使用？", "expect": "strict_pass",
     "revision": MANUAL_REVISION, "source_id": MANUAL_SOURCE_ID, "manual_pages": [6, 7],
     "target": "mm2_manual_energy_20261125.txt", "contains": "full load of energy"},
    {"id": "MM203", "q": "洛克人2官方说明书里 STAGE SELECT 怎样用控制pad移动选择框，按 START 确认对手？", "expect": "strict_pass",
     "revision": MANUAL_REVISION, "source_id": MANUAL_SOURCE_ID, "manual_pages": [3],
     "target": "mm2_manual_stage_select_20261125.txt", "contains": "This screen has pictures"},
    {"id": "MM204", "q": "洛克人2官方说明书里 PASSWORD 密码怎样记录和恢复进度？", "expect": "strict_pass",
     "revision": MANUAL_REVISION, "source_id": MANUAL_SOURCE_ID, "manual_pages": [9],
     "target": "mm2_manual_passwords_20261125.txt", "contains": "where the bubbles are"},
    {"id": "MM205", "q": "洛克人2官方说明书里击败 Heat Man、Air Man、Flash Man 分别获得什么交通工具？", "expect": "strict_pass",
     "revision": MANUAL_REVISION, "source_id": MANUAL_SOURCE_ID, "manual_pages": [8],
     "target": "mm2_manual_special_items_20261125.txt", "contains": "levitation platform"},
    {"id": "MM206", "q": "洛克人2官方说明书里 HOW TO BEAT AIRMAN 的基本步骤是什么？", "expect": "strict_pass",
     "revision": MANUAL_REVISION, "source_id": MANUAL_SOURCE_ID, "manual_pages": [10, 11, 12, 13],
     "target": "mm2_manual_airman_20261125.txt", "contains": "Air Tikk"},
    {"id": "MM207", "q": "洛克人2官方说明书里八名 Robot Master 分别是谁？", "expect": "strict_pass",
     "revision": MANUAL_REVISION, "source_id": MANUAL_SOURCE_ID, "manual_pages": [14, 15],
     "target": "mm2_manual_robot_masters_20261125.txt", "contains": "Wood Man"},
    {"id": "MM208", "q": "洛克人2官方说明书里 Metal Blade 的投掷方向、数量和用途是什么？", "expect": "strict_pass",
     "revision": MANUAL_REVISION, "source_id": MANUAL_SOURCE_ID, "manual_pages": [15],
     "target": "mm2_manual_weapons_20261125.txt", "contains": "best general purpose weapon"},
    {"id": "MM209", "q": "洛克人2官方说明书里 Time Stopper 的效果和能量限制是什么？", "expect": "strict_pass",
     "revision": MANUAL_REVISION, "source_id": MANUAL_SOURCE_ID, "manual_pages": [15],
     "target": "mm2_manual_weapons_20261125.txt", "contains": "cannot be turned off early"},
    {"id": "MM210", "q": "洛克人2官方说明书里 Crash Bomber 有什么用途？", "expect": "strict_pass",
     "revision": MANUAL_REVISION, "source_id": MANUAL_SOURCE_ID, "manual_pages": [15],
     "target": "mm2_manual_weapons_20261125.txt", "contains": "thrown at walls"},
    {"id": "MM301", "q": "洛克人2 的 HP 内存地址是什么？", "expect": "weak",
     "revision": MEMORY_REVISION, "source_id": MEMORY_SOURCE,
     "target": "mm2_local_memory_dictionary_20261125.txt", "contains": "hp"},
    {"id": "MM302", "q": "洛克人2 的 platform 是什么？", "expect": "weak",
     "revision": CATALOG_REVISION, "source_id": CATALOG_SOURCE,
     "target": "mm2_local_title_catalog_20261125.txt", "contains": "Mega Man 2"},
    {"id": "MM303", "q": "洛克人2 的 TAS 4057 用哪个版本？", "expect": "weak",
     "revision": TAS_REVISION, "source_id": TAS_SOURCE,
     "target": "mm2_local_tas_publications_20261125.txt", "contains": "4057"},
    {"id": "MM401", "q": "洛克人2 出招表", "expect": "refuse",
     "route_disposition": "candidate", "reason_code": "move_list_not_collected"},
    {"id": "MM402", "q": "洛克人2 PAL 版 walking speed 是什么？", "expect": "refuse",
     "route_disposition": "version_not_collected", "reason_code": "version_not_collected"},
    {"id": "MM403", "q": "MM2 美版ROM 的 walking speed 是什么？", "expect": "refuse",
     "route_disposition": "version_not_collected", "reason_code": "version_not_collected"},
    {"id": "MM404", "q": "洛克人 的 walking speed 是什么？", "expect": "refuse",
     "route_disposition": "ambiguous_series", "reason_code": "ambiguous_series"},
    {"id": "MM405", "q": "洛克人2 的作曲家是谁？", "expect": "refuse",
     "route_disposition": "candidate"},
    {"id": "MM406", "q": "洛克人2 的 walking speed 和拳皇98 的必杀射门分别是什么？", "expect": "refuse",
     "route_disposition": "multi_domain_needs_split", "reason_code": "multi_domain_needs_split"},
    {"id": "MM407", "q": "洛克人2 PAL-B 官方说明书能直接照用吗？", "expect": "refuse",
     "route_disposition": "version_not_collected", "reason_code": "version_not_collected"},
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


def rel(path):
    return Path(path).relative_to(ROOT).as_posix()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_manual_excerpt(spec):
    lines = [spec["heading"], "", "来源：Capcom《MEGA MAN 2》美国 NES 官方说明书，任天堂官方数字复刻。",
             "核验：已读扫描页；中文为说明，英文为短引文；未收全本。", ""]
    for fact, quote in zip(spec["facts"], spec["quotes"]):
        lines.extend([fact, f"> {quote}", ""])
    target = EVIDENCE / spec["name"]
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {"target": rel(target), "target_sha256": sha(target),
            "scan_pdf_pages": spec["pages"], "printed_manual_pages": spec["pages"],
            "scan_visually_read": True, "fact_count": len(spec["facts"]),
            "quotes": spec["quotes"]}


def anchor_question(spec, index):
    if spec["expect"] == "refuse":
        return {k: v for k, v in spec.items() if k not in {"target", "contains"}}
    target = EVIDENCE / spec["target"]
    lines = target.read_text(encoding="utf-8").splitlines()
    hit_lines = [i + 1 for i, line in enumerate(lines) if spec["contains"] in line]
    if not hit_lines:
        raise RuntimeError(f"gold text missing: {spec['id']} {spec['contains']}")
    line_no = hit_lines[-1] if spec["id"] in {"MM208", "MM209", "MM210"} else hit_lines[0]
    chunks = [c for c in index["chunks"]
              if c["path"] == rel(target) and c["line_start"] <= line_no <= c["line_end"]]
    if not chunks:
        raise RuntimeError(f"gold chunk missing: {spec['id']} line={line_no}")
    chunk = chunks[0]
    out = {k: v for k, v in spec.items() if k not in {"target", "contains"}}
    out["gold"] = {"anchor_chunk": chunk["chunk_id"], "path_contains": rel(target),
                   "line_start": line_no, "line_end": line_no,
                   "source_id": spec["source_id"], "revision": spec["revision"]}
    return out


def main():
    real_paths = [K.INDEX_JSON, K.CORPUS_MAP, S.REG_JSON, K.KB_DIR / "query_log.jsonl",
                  KE.DB_PATH, ROOT / "选题决策层" / "kb快照" / "index.json"]
    old_paths = [OLD_CANDIDATE / "index.json", OLD_CANDIDATE / "corpus_map.json",
                 OLD_CANDIDATE / "sources.json", OLD_CANDIDATE / "contract.json"]
    before = {str(p): snapshot(p) for p in real_paths + old_paths}
    old_map = K.load_map(OLD_CANDIDATE / "corpus_map.json")
    old_registry = S.load_registry(OLD_CANDIDATE / "sources.json")
    if TECH_REVISION not in old_map["revisions"]:
        raise RuntimeError("old candidate technical revision missing")

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
        entries.append({"path": record["target"], "source_id": MANUAL_SOURCE_ID,
                        "revision": MANUAL_REVISION, "kind": "prose",
                        "authority": "authoritative", "index": True,
                        "element_types": ["说明书", "基础档案"],
                        "note": "任天堂官方托管的美国NES说明书数字复刻短摘录；逐页读图核对，不是整本手册再分发。"})

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
        "name": "Capcom MEGA MAN 2 美国 NES Game Pak Instructions（任天堂官方数字复刻，短摘录）",
        "kind": "print", "layer": "official_manual", "platforms": ["NES"],
        "element_types": ["说明书", "基础档案"], "status": "verified_read",
        "last_verified": "2026-11-25",
        "urls": ["https://www.nintendo.co.jp/clv/manuals/en/pdf/CLV-P-NABBE.pdf",
                 "https://archive.org/details/mega-man-2-nes-manual"],
        "evidence": [r["target"] for r in manual_records],
        "notes": "仅保存8个短摘录文件；完整商业手册扫描未进入候选或交付目录。PDF无文本层，入选事实直接读页面图像。",
        "games_hit": ["megaman2"],
    })

    revisions = json.loads(json.dumps(old_map["revisions"], ensure_ascii=False))
    revisions[MANUAL_REVISION] = {
        "game_id": "megaman2", "platform": "NES",
        "name": "洛克人2 / Mega Man 2 — 美国 NES 官方说明书短摘录",
        "note": "authoritative 仅限任天堂官方数字复刻手册中直接读图的短摘录；不证明 PAL/日版 ROM 等价，也不是整款游戏知识库。",
    }
    candidate_map = {"schema_version": 1, "revisions": revisions, "entries": entries}
    write_json(CANDIDATE_REGISTRY, registry)
    write_json(CANDIDATE_MAP, candidate_map)
    write_json(CANDIDATE / "manual_source.json", {
        "status": "scan_verified_short_excerpts_only",
        "source_id": MANUAL_SOURCE_ID,
        "title": "MEGA MAN 2 — Game Pak Instructions (US NES)",
        "creator": "Capcom",
        "official_host": "Nintendo Co., Ltd.",
        "official_pdf": "https://www.nintendo.co.jp/clv/manuals/en/pdf/CLV-P-NABBE.pdf",
        "archive_item": "https://archive.org/details/mega-man-2-nes-manual",
        "archive_pdf": "https://archive.org/download/mega-man-2-nes-manual/Mega-Man-2-Game-Manual.pdf",
        "archive_publication_date": "2024-02-20",
        "official_pdf_sha1": MANUAL_PDF_SHA1,
        "downloaded_pdf_sha256": MANUAL_PDF_SHA256,
        "downloaded_pdf_bytes": 1554314,
        "archive_pdf_sha256": ARCHIVE_PDF_SHA256,
        "archive_pdf_bytes": 1063374,
        "pdf_pages": 20,
        "printed_page_range": "1-20 (PDF page equals printed page; page 20 is the digital-reproduction notice)",
        "region_identity_evidence": "Cover code NES-XR-USA; page 2 Licensed by Nintendo For Play On The Nintendo Entertainment System; Capcom branding; page 20 Printed in Japan.",
        "verification": "All 20 official PDF pages were rendered. Selected passages on pages 2-15 were visually read from the page images; the PDF has no text layer.",
        "typed_transcription_role": "not_used_image_only_pdf",
        "full_manual_stored_in_candidate": False,
        "excerpts": manual_records,
    })
    write_json(CANDIDATE / "scope.json", {
        "status": "candidate_v2_manual_production_route_wired",
        "revision": MANUAL_REVISION,
        "authoritative_scope": ["TASVideos明确技术条目", "美国NES官方说明书操作/选关/能量/道具/密码/Airman/Robot Master/武器短摘录"],
        "reference_only_scope": ["本地二手内存字典", "本地标题目录", "本地TAS出版物元数据"],
        "not_covered": ["整款游戏内容知识库", "全部敌人与关卡数据", "出招表", "PAL/日版等价", "目标时刻续作"],
        "production_defaults_unchanged": True,
        "production_route_wired": True,
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
    })

    S.load_registry(CANDIDATE_REGISTRY)
    K.load_map(CANDIDATE_MAP)
    build = K.build(map_path=CANDIDATE_MAP, index_path=CANDIDATE_INDEX,
                    reg=registry, force=True)
    index = K.load_index(CANDIDATE_INDEX)
    questions = [anchor_question(spec, index) for spec in QUESTION_SPECS]
    expected_counts = {
        "total": len(questions),
        "strict_pass": sum(q["expect"] == "strict_pass" for q in questions),
        "weak": sum(q["expect"] == "weak" for q in questions),
        "refuse": sum(q["expect"] == "refuse" for q in questions),
    }
    write_json(FROZEN, {
        "schema_version": 3,
        "status": "frozen",
        "frozen_at": "2026-11-25",
        "candidate_domain": "megaman2_candidate",
        "candidate_revision": MANUAL_REVISION,
        "candidate_index_sha256": sha(CANDIDATE_INDEX),
        "expected_counts": expected_counts,
        "manual_source": {"source_id": MANUAL_SOURCE_ID,
                          "official_pdf": "https://www.nintendo.co.jp/clv/manuals/en/pdf/CLV-P-NABBE.pdf",
                          "excerpt_files": len(MANUAL_EXCERPTS)},
        "questions": questions,
    })
    write_json(CANDIDATE_CONTRACT, {
        "schema_version": 2, "domain": "megaman2_candidate",
        "index_path": rel(CANDIDATE_INDEX), "index_sha256": sha(CANDIDATE_INDEX),
        "map_path": rel(CANDIDATE_MAP), "registry_path": rel(CANDIDATE_REGISTRY),
        "default_revision": TECH_REVISION, "manual_revision": MANUAL_REVISION,
        "frozen_questions": rel(FROZEN), "frozen_at": "2026-11-25",
        "production_route_wired": True,
    })

    after = {str(p): snapshot(p) for p in real_paths + old_paths}
    changed = [p for p in before if before[p] != after[p]]
    if changed:
        raise RuntimeError(f"guarded state changed during isolated build: {changed}")
    write_json(REPORT, {
        "status": "built_isolated_v2_manual",
        "candidate_revision": MANUAL_REVISION,
        "candidate_dir": str(CANDIDATE),
        "build": build,
        "index_sha256": sha(CANDIDATE_INDEX),
        "index_chunks": len(index["chunks"]),
        "index_stats": index["stats"],
        "revision_counts": {rid: sum(c["revision"] == rid for c in index["chunks"])
                            for rid in revisions},
        "authority_counts": {a: sum(c["authority"] == a for c in index["chunks"])
                             for a in sorted({c["authority"] for c in index["chunks"]})},
        "manual_source_id": MANUAL_SOURCE_ID,
        "manual_excerpts": manual_records,
        "frozen_questions": rel(FROZEN),
        "question_counts": expected_counts,
        "real_state_unchanged": all(before[str(p)] == after[str(p)] for p in real_paths),
        "old_candidate_unchanged": all(before[str(p)] == after[str(p)] for p in old_paths),
        "guarded_state_before": before,
        "guarded_state_after": after,
        "changed_paths": changed,
        "candidate_scope": "RAM/tooling plus scan-verified official-manual excerpts; not a whole-game knowledge base",
    })
    print(f"BUILD_OK chunks={len(index['chunks'])} files={build['files_indexed']} changed={changed}")
    print(str(CANDIDATE_INDEX))
    print(str(FROZEN))
    print(str(REPORT))


if __name__ == "__main__":
    main()
