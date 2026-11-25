# -*- coding: utf-8 -*-
"""《热血格斗传说》生日 KT 候选计算，仅用于 reference_only 本地参考。"""
from datetime import date

REVISION = "nekketsu_kakutou_densetsu_fc_jp"
SOURCE_ID = "dammit9x_nkd_faq"
SOURCE_LOCATOR = "_工具脚本/taspipe/游戏包/来源库/取证/dammit9x_熱血格闘伝説_角色公式参考_20261124.md#L9-L36"
FORMULA = "KT# = (出生月 + 出生日 - 1) mod 20"
ARCHIVED_SOURCES = (
    "https://web.archive.org/web/20010819104652id_/http://www.rahga.com/nkd/",
    "https://web.archive.org/web/20010215090626id_/http://yokohama.cool.ne.jp/tyaf/Games/kak.html",
)
WARNING = "二手 FAQ 候选，未经原版 ROM 复算；不得进入硬证据通道或自动文稿定论。"

_KT_TABLE = (
    ("Spin Attack", "Mach Kick"),
    ("Stone Guard", "Spin Attack", "Bomb Kick"),
    ("Jump Elbow", "Stone Guard", "Spin Attack"),
    ("Jump Guillotine", "Jump Elbow", "Stone Guard"),
    ("Mach Stomp", "Jump Guillotine", "Jump Elbow"),
    ("Spin Attack", "Bomb Kick", "High Spin Kick"),
    ("Mach Stomp", "Tornado Attack", "High Spin Kick"),
    ("Mach Punch", "Tornado Attack", "High Spin Kick"),
    ("Spin Attack", "Mach Punch"),
    ("Spin Attack", "Mach Punch", "Tornado Attack"),
    ("Jump Elbow", "Bomb Kick"),
    ("Tornado Attack", "High Spin Kick"),
    ("Mach Stomp", "Mach Kick", "Tornado Attack"),
    ("Jump Guillotine", "High Spin Kick"),
    ("Jump Elbow", "Mach Kick"),
    ("Bomb Kick", "Tornado Attack", "High Spin Kick"),
    ("High Spin Kick",),
    ("Spin Attack", "Bomb Kick", "Mach Kick"),
    ("Tornado Attack",),
    ("Bomb Kick", "Mach Kick"),
)


def candidates_for_birthday(month, day):
    if (isinstance(month, bool) or not isinstance(month, int)
            or isinstance(day, bool) or not isinstance(day, int)):
        raise ValueError("出生月和出生日必须是整数")
    try:
        date(2000, month, day)
    except ValueError as exc:
        raise ValueError(f"无效生日：{month}/{day}（{exc}）") from exc
    kt_number = (month + day - 1) % 20
    return {
        "schema_version": 1,
        "game": "熱血格闘伝説",
        "revision": REVISION,
        "input": {"month": month, "day": day},
        "formula": FORMULA,
        "candidate_kt_number": kt_number,
        "candidate_moves": list(_KT_TABLE[kt_number]),
        "status": "reference_only",
        "authority": "reference_only",
        "source_id": SOURCE_ID,
        "source_locator": SOURCE_LOCATOR,
        "archived_sources": list(ARCHIVED_SOURCES),
        "provenance": "FAQ 表注明 adapted from http://www.rahga.com/nkd/；Rahga 2001-08-19 与 Afric Acid 2001-02-15 快照同表，均为玩家攻略，原站正文不等于官方或 ROM 证据。",
        "rom_recomputed": False,
        "hard_evidence_eligible": False,
        "warning": WARNING,
    }
