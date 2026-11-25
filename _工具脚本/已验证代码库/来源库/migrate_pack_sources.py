# -*- coding: utf-8 -*-
"""一次性迁移：知识包自由文本来源 → 结构化 source_id 引用（2026-11-18）。

做三件事，全部幂等：
  1) 补「项目内文档与本机实测记录」层（local_docs）——这些是离线权威，以前散在包里的自由文本；
  2) 把包里出现过但库里没有的站 ingest 入库（默认 candidate，不冒充已验证）；
  3) 重写 15 个包的 sources：每条带 source_id/url/status/verified_date/element_ids/note，
     状态照库里的真值抄（403 站标 unreachable、只有快照标 snippet_only），不粉饰。

运行: py -3 F:/taspipe_scratch/migrate_sources_1118.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "F:/开源掌机教程/_工具脚本")
sys.stdout.reconfigure(encoding="utf-8")
from taspipe import sources as S

TODAY = S.today()

LOCAL_DOCS = [
    {
        "source_id": "local_project_manual",
        "name": "测试问题与闸门说明书（taspipe 实测口径与闸门口径）",
        "kind": "local", "layer": "local_docs", "platforms": ["ANY"],
        "element_types": ["攻略", "出招表", "必杀宏", "金手指", "隐藏要素", "bug", "基础档案"],
        "status": "verified_read", "last_verified": TODAY, "urls": [],
        "evidence": ["测试问题与闸门说明书.md"],
        "notes": "45,351B，26 节。§2 招式谱面符号编译闸门（KOF98）；§19–21 热血足球2 状态跳跃/看门狗/帧 parity；"
                 "§22–23 洛克人逐帧采集与选关门控；§24 showcase 全量盘点框架（原子前置态+反例+全量口径）；"
                 "§25 球权/必杀判据改 OAM 字节；§26 CN/hack 族必杀不可触发的负证据链。"
                 "要素真值以本机实测为准，网站只作名录。",
        "games_hit": ["kof98_arcade_kyo", "megaman1_nes_us", "nekketsu_soccer2_fc_jp",
                      "nekketsu_soccer2_fc_cn_hack"],
    },
    {
        "source_id": "local_route_template",
        "name": "要素盘点可复用生产路线模板（正确路线 + 错误阀门）",
        "kind": "local", "layer": "local_docs", "platforms": ["ANY"],
        "element_types": ["攻略", "基础档案", "必杀宏", "隐藏要素"],
        "status": "verified_read", "last_verified": TODAY, "urls": [],
        "evidence": ["_工具脚本/taspipe/要素盘点路线模板.md"],
        "notes": "12,065B。§1 有序步骤（S1 调研挂点已改为强制先跑 sources route）；§2 错误阀门；"
                 "§3 逐游戏填槽清单；§4 热血足球2 逐游戏卡示例（导航输入链 + 暂停金手指 AAABAAABAAAAAAA）；§5 举一反三。",
        "games_hit": ["nekketsu_soccer2_fc_jp"],
    },
    {
        "source_id": "local_soccer2_super_list",
        "name": "热血足球联盟必杀全清单 + honest gap manifest（证据级）",
        "kind": "local", "layer": "local_docs", "platforms": ["NES"],
        "element_types": ["必杀宏", "出招表", "隐藏要素", "攻略", "bug"],
        "status": "verified_read", "last_verified": TODAY, "urls": [],
        "evidence": ["_工具脚本/taspipe/游戏包/热血足球联盟_必杀全清单.md",
                     "_工具脚本/taspipe/游戏包/热血足球联盟_honest_gap_manifest.md"],
        "notes": "29,352B 全清单（23 必杀=日版12+对手11，一角色一必杀须换人；燕返仅小辫子；前B头/后B倒钩/平地步数/禁区高空球）。"
                 "gap manifest 记 CN/hack 族难度锁定+无人球同跳的 honest gap，不冒充可复现。",
        "games_hit": ["nekketsu_soccer2_fc_jp", "nekketsu_soccer2_fc_cn_hack"],
        "recipes": {"cn": "读 热血足球联盟_必杀全清单.md 找 {game} 的必杀编号与触发条件"},
    },
    {
        "source_id": "local_goal_plan",
        "name": "目标与实施路线（T1–T4 进度与验收口径）",
        "kind": "local", "layer": "local_docs", "platforms": ["ANY"],
        "element_types": ["基础档案", "攻略"],
        "status": "verified_read", "last_verified": TODAY, "urls": [],
        "evidence": ["_工具脚本/taspipe/目标与实施路线.md"],
        "notes": "9,194B。记 T1 名作通关出片已完成（忍者龙剑传 4751 → 验证/t1_ninja_gaiden/final_60s/），"
                 "但 §3 明写「T3 本体（忍者龙剑传忍术正负例包）尚未开工」⇒ 本文档不能当要素真值来源，只作进度与口径。",
        "games_hit": ["ninja_gaiden1_nes_us"],
    },
]

NEW_SITES = [
    dict(url="https://www.arcade-museum.com/game_detail.php?game_id=8675",
         name="KLOV / arcade-museum（街机基础档案与版本）", layer="en_tech",
         platforms="ARCADE", want="基础档案,版本对照", status="candidate",
         notes="合金弹头包引过此站；本轮未取正文，先入库当候选，遇到再验。"),
    dict(url="https://wiki.supermetroid.run/RAM_Map",
         name="supermetroid.run wiki（超级银河战士 RAM Map）", layer="en_tech",
         platforms="SNES", want="金手指,未使用内容,基础档案", status="candidate",
         notes="超级银河战士包引过此站；本轮未取正文，candidate。社区维护的逐地址表，比通用攻略站更细。"),
]

# eids: "all" = 该包全部要素；[] = 只登记来源不作要素支撑（避免拿无关文档顶包）
PACK_MAP = {
    "_template.showcase.json": [
        ("local_route_template", None, "all",
         "模板占位来源：真实包必须先跑 `sources route` 定身份+查库，再按 §3 填槽；禁止臆造条目。"),
    ],
    "arcade_kof98_kyo_moves.showcase.json": [
        ("local_fbneo_setlist", None, [],
         "身份层：本包 rom=F:/tas_rig/roms/kof98.zip（原版 kof98），与已实测的 kof98eck 不是同一 set；开搜前先定身份。"),
        ("local_fbneo_rig", None, "all",
         "rig.py 实测=指令真值兜底权威。⚠️ 已实测卡是 kof98eck（Easy Combo Edition, Hack，sha1 c5947d19…），本包指原版，指令须按原版重核。"),
        ("local_project_manual", None, "all", "§2 招式谱面排版符号编译闸门（谱面符号写错会浪费整轮采集）。"),
        ("gamersky_handbook", None, "all",
         "98UM 全角色出招表 53 页=名录级参考，不是这张卡的指令权威（版本不同）。"),
        ("strategywiki", "https://strategywiki.org/wiki/The_King_of_Fighters_%2798/Kyo_Kusanagi", "all",
         "本机直连 403，只有搜索快照，未全文核对。"),
    ],
    "arcade_mslug_weapons.showcase.json": [
        ("local_fbneo_setlist", None, [],
         "身份层：rom=F:/tas_rig/roms/mslug.zip；mslug 有多版（mslug/mslug2…），先定 set 再查表。"),
        ("strategywiki", "https://strategywiki.org/wiki/Metal_Slug/Weapons", "all",
         "本机直连 403，只有搜索快照，未全文核对。"),
        ("arcade_museum_com", "https://www.arcade-museum.com/game_detail.php?game_id=8675", "all",
         "KLOV 基础档案；本轮未取正文（candidate），不得当已验证来源。"),
    ],
    "contra_weapons.showcase.json": [
        ("local_libretro_cht", None, "all",
         "★本机实证：Contra (USA).cht 共 61 码，cheat43 原始码 `00AA:16`（Choose Your Weapon! All Rapid Fire）"
         "与包内 0x00AA 武器寄存器口径互证；cheat22/4/23/24 = 机枪/火焰/散弹/激光（Game Genie PEIIXZ/ZEIIXZ/LEIIXZ/GEIIXZ）。"
         "⚠️ 0x16 低 4 位=6 与包内『5 起为非法值且不开火』口径冲突，须本机实测复核，不得直接采信任何一方。"),
        ("datacrystal", "https://datacrystal.tcrf.net/wiki/Contra_(NES)/RAM_map", "all",
         "只有搜索快照，未全文核对。"),
        ("strategywiki", "https://strategywiki.org/wiki/Contra/Weapons", "all",
         "本机直连 403，只有搜索快照。"),
    ],
    "gba_aria_of_sorrow_souls.showcase.json": [
        ("datacrystal", "https://datacrystal.tcrf.net/wiki/Castlevania:_Aria_of_Sorrow/RAM_map", "all",
         "只有搜索快照，未全文核对。"),
        ("strategywiki", "https://strategywiki.org/wiki/Castlevania:_Aria_of_Sorrow/Souls", "all",
         "本机直连 403，只有搜索快照。"),
    ],
    "md_yu_yu_hakusho_moves.showcase.json": [
        ("strategywiki", "https://strategywiki.org/wiki/Yu_Yu_Hakusho:_Makyo_Toitsusen", "all",
         "本机直连 403，只有搜索快照。"),
        ("gamefaqs", "https://gamefaqs.gamespot.com/genesis/563235-yu-yu-hakusho-makyo-toitsusen", "all",
         "candidate：知道存在，本轮未取正文。"),
    ],
    "megaman1_weapons.catalog.json": [
        ("local_project_manual", None, "all",
         "§22 dump 逐帧采集 frameadvance 不能在 pcall 内；§23 本地洛克人 ROM 进不了 gameplay（选关 D-pad 无效＋未战斗直跳 CLEAR POINTS）的资源门控实测。"),
        ("datacrystal", "https://datacrystal.tcrf.net/wiki/Mega_Man_(NES)/RAM_map", "all",
         "只有搜索快照（fetch 403），未全文核对。"),
        ("nesmaps", "https://nesmaps.com/maps/MegaMan/MegaMan.html", "all",
         "内存码 006A/0055/005D 来自搜索快照，未全文核对。"),
        ("neoseeker", "https://www.neoseeker.com/mega-man-legacy-collection/faqs/85172-mega-man-m.html", "all",
         "本机直连 403；Clear Points / platform maker 只有快照。"),
    ],
    "megaman1_weapons.showcase.json": [
        ("local_project_manual", None, "all", "§22–23 洛克人逐帧采集与选关/资源门控实测记录。"),
        ("datacrystal", "https://datacrystal.tcrf.net/wiki/Mega_Man_(NES)/RAM_map", "all",
         "只有搜索快照，未全文核对。"),
        ("nesmaps", "https://nesmaps.com/maps/MegaMan/MegaMan.html", "all", "只有搜索快照。"),
        ("strategywiki", "https://strategywiki.org/wiki/Mega_Man/Weapons", "all",
         "本机直连 403，只有搜索快照。"),
    ],
    "nekketsu_soccer2_honest.showcase.json": [
        ("local_soccer2_super_list", None, "all",
         "全清单 + honest gap manifest：仅收录 CN/hack 可复现要素，23 必杀+13 通用技因难度锁定+无人球同跳标 honest gap。"),
        ("local_project_manual", None, "all", "§26 CN/hack 族必杀不可触发的负证据链（2026-11-14 实跑闭合）。"),
        ("local_live_capture", None, "all", "真人操作捕获通路（WSAD+JKL;），必杀真值宏的兜底权威。"),
        ("1ang_com", None, "all", "火光 FC 攻略镜像，已取正文（57,056B 取证）。"),
        ("sohu_game", None, "all", "已取正文：一直输球隐藏大结局 / 必杀最强小辫子 / 热血队队员必杀集锦。"),
        ("csdn_wangsitan_bug", None, "all", "已取正文（69,100B Bug 记录）；四件套另三篇仍只有快照。"),
        ("game_urawaza", None, "all", "日文裏技.com FC 热血足球页，已取正文（7,955B）。"),
    ],
    "nekketsu_soccer2_shots.showcase.json": [
        ("local_route_template", None, "all",
         "§4 逐游戏卡：导航输入链 + 暂停金手指 AAABAAABAAAAAAA（签名=得分框 OK）。"),
        ("local_project_manual", None, "all", "§19–21 状态跳跃前置件/看门狗/帧 parity；§25 球权与必杀判据改 OAM 字节。"),
        ("local_soccer2_super_list", None, "all", "23 必杀全清单（日12+opp11，一角色一必杀须换人）。"),
        ("local_live_capture", None, "all", "真人捕获通路=必杀真值宏来源。"),
        ("setsumei_cloudfree", None, "all", "官方说明书扫描，已取正文（22,061B）。"),
        ("1ang_com", None, "all", "火光镜像图文攻略，已取正文。"),
        ("strategywiki", "https://strategywiki.org/wiki/Kunio-kun_no_Nekketsu_Soccer_League", "all",
         "本机直连 403，只有搜索快照。"),
    ],
    "ninja_cats_elements.showcase.json": [
        ("strategywiki", "https://strategywiki.org/wiki/Kyatto_Ninden_Teyandee", "all",
         "本机直连 403，只有搜索快照。"),
        ("datacrystal", "https://datacrystal.tcrf.net/wiki/Kyatto_Ninden_Teyandee", "all",
         "只有搜索快照，未全文核对。"),
    ],
    "ninja_gaiden_elements.showcase.json": [
        ("datacrystal", "https://datacrystal.tcrf.net/wiki/Ninja_Gaiden_(NES)/RAM_map", "all",
         "只有搜索快照；包内 0x00C5 忍术 ID / 0x0064 灵力值尚未本机实测复核。"),
        ("strategywiki", "https://strategywiki.org/wiki/Ninja_Gaiden/Items", "all",
         "本机直连 403，只有搜索快照。"),
        ("local_goal_plan", None, [],
         "只作进度口径：T1 通关出片已完成，但 §3 明写 T3 忍术要素正负例包尚未开工 ⇒ 不能当要素真值来源。"),
    ],
    "ps1_sotn_alucard_powers.showcase.json": [
        ("datacrystal", "https://datacrystal.tcrf.net/wiki/Castlevania:_Symphony_of_the_Night/RAM_map", "all",
         "只有搜索快照，未全文核对。"),
        ("strategywiki", "https://strategywiki.org/wiki/Castlevania:_Symphony_of_the_Night/Spells", "all",
         "本机直连 403，只有搜索快照。"),
    ],
    "snes_megaman_x_arsenal.showcase.json": [
        ("datacrystal", "https://datacrystal.tcrf.net/wiki/Mega_Man_X/RAM_map", "all",
         "只有搜索快照，未全文核对。"),
        ("strategywiki", "https://strategywiki.org/wiki/Mega_Man_X/Weapons", "all",
         "本机直连 403，只有搜索快照。"),
    ],
    "snes_super_metroid_abilities.showcase.json": [
        ("wiki_supermetroid_run", "https://wiki.supermetroid.run/RAM_Map", "all",
         "candidate：本轮未取正文；社区逐地址表，值得优先真读。"),
        ("strategywiki", "https://strategywiki.org/wiki/Super_Metroid/Items", "all",
         "本机直连 403，只有搜索快照。"),
    ],
}


def main():
    reg = S.load_registry()
    added = []
    for rec in LOCAL_DOCS:
        if any(s["source_id"] == rec["source_id"] for s in reg["sources"]):
            continue
        S.validate_source(rec, ctx="local_docs")
        reg["sources"].append(rec)
        added.append(rec["source_id"])
    print(f"local_docs 新增 {len(added)}: {added}")

    ingested = []
    for kw in NEW_SITES:
        try:
            r = S.ingest(reg=reg, **kw)
            ingested.append(r["ingested"])
        except S.SchemaError as e:
            print(f"  入库跳过（已在库或非法）: {e}")
    print(f"新站入库 {len(ingested)}: {ingested}")

    by_id = {s["source_id"]: s for s in reg["sources"]}
    changed, skipped = [], []
    for name, mapping in PACK_MAP.items():
        p = S.PACKS_DIR / name
        doc = json.loads(p.read_text(encoding="utf-8"))
        eids_all = [e["element_id"] for e in doc.get("elements") or [] if e.get("element_id")]
        entries = []
        for sid, url, eids, note in mapping:
            src = by_id[sid]
            entries.append({
                "source_id": sid,
                "url": url or (src.get("urls") or [None])[0],
                "status": src["status"],
                "verified_date": src.get("last_verified"),
                "element_ids": eids_all if eids == "all" else list(eids),
                "note": note,
            })
        if isinstance(doc.get("catalog"), dict) and "sources" in doc["catalog"]:
            doc["catalog"]["sources"] = entries
        else:
            doc["sources"] = entries
        p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        covered = set()
        for e in entries:
            covered.update(e["element_ids"])
        missing = [x for x in eids_all if x not in covered]
        weak = [x for x in eids_all
                if x in covered and all(by_id[e["source_id"]]["status"] != "verified_read"
                                        for e in entries if x in e["element_ids"])]
        changed.append((name, len(entries), len(eids_all), missing, weak))
        if missing:
            skipped.append(f"{name}: 未覆盖 {missing}")

    S.save_registry(reg)
    print(f"\n迁移 {len(changed)} 个包：")
    for name, n, total, missing, weak in changed:
        flag = "★只有快照层支撑" if weak and len(weak) == total else ("部分快照" if weak else "有本机/已读支撑")
        print(f"  {name:<48} 来源{n:>2} 要素{total:>2} 未覆盖{len(missing)} {flag}")
    if skipped:
        print("\n未覆盖明细:", skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())