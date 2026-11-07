#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_monitor.py —— 破解/移植资讯监控(可重复运行,幂等)

读 06-资讯监控/源登记表.tsv -> 抓 RSS/Atom -> 追加进 台账.tsv -> 生成当天日报。

设计上的三条硬规矩:
1. 不许静默跳过。每个源的 HTTP 码、条目数、新增数都写进 _last_run.json,失败的源在日报顶部点名。
2. 去重键 = guid/id -> link -> title+date。台账只追加,永不改写,所以重复跑同一天的量是 0。
3. 抓到什么就记什么,不做"这条大概是假的"的判断;爆款候选只按关键词表置顶,判定留给人。

用法: py -3 _工具脚本/scene_monitor.py            (全量跑)
      py -3 _工具脚本/scene_monitor.py --limit 3   (只跑前 3 个源,调试用)
      py -3 _工具脚本/scene_monitor.py --retry-failed  (跑完对 429/000/curl_err 的源错峰重试,默认 3 轮,见 RETRY_ROUNDS)

2026-10-20 聚焦层:每条入库条目按 FOCUS_RULES 打主题标签(台账第 12 列 flag_focus),
日报新增"今日聚焦"段按主题分档 —— Switch移植 / Vita-PSP / 开源掌机与固件 /
模拟器核心 / 引擎重实现 / PortMaster / FPGA / 中文源 / 源码泄露安全。
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MON = os.path.join(ROOT, "06-资讯监控")
REG = os.path.join(MON, "源登记表.tsv")
LEDGER = os.path.join(MON, "台账.tsv")
DAILY = os.path.join(MON, "日报")
RUNJSON = os.path.join(MON, "_last_run.json")
ARR_MD = os.path.join(MON, "大作登陆平台.md")
VERDICT = os.path.join(MON, "大作判定.tsv")


def load_verdicts():
    """大作判定.tsv: match<TAB>verdict<TAB>action<TAB>payload<TAB>note。人工维护。"""
    out = []
    if not os.path.exists(VERDICT):
        return out
    with open(VERDICT, encoding="utf-8", newline="") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            out.append(dict(zip(head, line.rstrip("\n").split("\t"))))
    return out


def verdict_for(url, vs):
    """按 URL 子串匹配;命中多条时取 match 更长(更具体)的那条。"""
    best = {}
    u = (url or "").lower()
    for v in vs:
        m = (v.get("match") or "").lower().strip()
        if m and m in u and len(m) > len((best.get("match") or "").lower()):
            best = v
    return best

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36 scene-monitor/1.0")

# 命中即置顶。这是"值得人看一眼"的粗筛,不是结论 —— 所以宁可窄,不要泛。
# 上一版把 switch/vita/core/release/vX.Y 这类每个源每天都在出现的词也算进去了,
# 结果 576 条里 420 条"爆款",等于没筛。
#
# 2026-10-10 扩机型(PS1/PS2/3DS/Wii/DC/FC/FPGA/掌机固件)后又栽了一次:
# HOT 从 88 冲到 302。原因不是词表太宽,而是**产品名在自己的源里必然自匹配** ——
# DuckStation 的 release 流每条标题都带 DuckStation,Atmosphere 同理,那叫历史不叫消息。
# 所以拆成两档:事件动词/具体作品名看全文;产品名先把"源名自带的词"挖掉再判。
HOT_VERB = re.compile(
    r"ported to|port for|port of|native port|runs on|running on|now plays|now runs|first playable|"
    r"移植|破解|自制固件|CFW|exploit|softmod|unbrick|translation patch|汉化|整合包|"
    r"移植成功|跑通了", re.I)
HOT_NAME = re.compile(
    r"GTA|Halo|Skyrim|Doom|Quake|Minecraft|Zelda|Mario|Pokemon|Elden Ring|"
    r"Sonic|Sega Rally|Panzer Dragoon|Shenmue|Oddworld|"
    r"Atmosph[eè]re|HENkaku|h-encore|HENlo|Ens[oō]|Luma3DS|MSET9|"
    r"DuckStation|Flycast|melonDS|PCSX2|RPCS3|Cemu\b|Project Dolphin|RetroArch|"
    r"(?-i:MiSTer)|Analogue Pocket|pocket-sync|pupdate|FreeMCBoot|BDMAssault|"
    r"spruceOS|CrossMix|muOS|TrimUI|Anbernic|Miyoo|RetroFW|Homebrew Channel|"
    r"塞尔达|马里奥|马力欧|宝可梦|口袋妖怪|皮卡丘|侠盗猎车|最终幻想|合金装备|生化危机|"
    r"恶魔城|银河战士|洛克人|星之卡比|索尼克|仙剑|轩辕剑|如龙|鬼泣|"
    r"adds support|emulates", re.I)
# 2026-10-20:`MiSTer` 改成大小写敏感(作用域标记 (?-i:MiSTer),需 Python 3.11+,本机 3.13)。原因是 GamesRadar 的
# "James Gunn officially confirms Mister Miracle casting" 被 re.I 的 `mister` 命中,
# 一条纯 DC 电影选角新闻混进爆款短名单。真身 MiSTer 在标题里从没写过小写 mister。
# 中文游戏 IP 名是给中文源(机核/少数派/吾爱/linux.do/ithome)用的:那层标题是中文,
# 不补这批词,中文源的产品名命中永远为零。
# 兼容旧引用(单正则版判定);跨源去噪请走 is_hot()
HOT = re.compile(HOT_VERB.pattern + "|" + HOT_NAME.pattern, re.I)

# 产品名在自己源里必然出现的"回填窗口":超过这些天的历史条目不算新消息。
# 例:首跑时 Atmosphere 的 release 流一次灌进 1.9.5~1.12.0 十条,昨天的那条才叫消息。
# 14 天是实测定的:GBAtemp 论坛 feed 里 [RELEASE] Flycast Vita(2026-09-29)这类真发版
# 会带着自己的建帖日期进来,窗口收到 7 天会把它当成历史丢掉。
BACKFILL_DAYS = 14


def _recent(pub, days=BACKFILL_DAYS):
    """发布日期解析得出来就按窗口判;**解析不出来按'不够新'处理**(空日期的条目不该进短名单)。
    实测所有 91 个源都给日期,所以这条只是兜底。"""
    if not pub:
        return False
    d = norm_date(pub)
    try:
        d = dt.datetime.strptime(d[:10], "%Y-%m-%d")
    except Exception:
        return False
    ref = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return (ref - d).days <= days


# ============ "大作/经典作品登陆某平台"专线(2026-10-11 按用户要求加) ============
# 词表只列"具体作品"和"具体引擎",绝不放 switch/vita/core/release 这类天天出现的泛词。
ARR_GAME = re.compile(
    r"Grand Theft Auto|\bGTA\b|San Andreas|GTA\s*(3|VC|IV|V)\b|Halo|Skyrim|Elder Scrolls|Fallout|"
    r"Ocarina of Time|Majora|Zelda|Mario Kart|Super Mario|\bSM64\b|\bSMG\b|Donkey Kong|"
    r"Pok(?:é|e)mon|Doom|Quake|Heretic|Hexen|Duke Nukem|Wolfenstein|Portal\b|Half[- ]?Life|Counter[- ]?Strike|"
    r"Minecraft|StarCraft|Brood\s?War|Warcraft|Diablo|Oddworld|Abe'?s|Sonic|"
    r"Panzer Dragoon|Shenmue|Jet Set Radio|Space Channel|Crazy Taxi|Sega Rally|Virtua (Fighter|Cop|Tennis)|"
    r"Castlevania|Metroid|F[- ]?Zero|Punch[- ]?Out|Kirby|Fire Emblem|Super Smash|"
    r"Final Fantasy|Chrono (Trigger|Cross)|Dragon Quest|Kingdom Hearts|"
    r"Metal Gear|Resident Evil|Silent Hill|Devil May Cry|Tekken|Street Fighter|Mega ?Man|"
    r"Prince of Persia|Tomb Raider|Crash Bandicoot|Spyro|Jak [aA]nd Daxter|Jak & Daxter|Ratchet|"
    r"God of War|Halo|Age of Empires|Civilization|SimCity|ScummVM|Full Throttle|Grim Fandango|"
    r"System Shock|Thief\b|Deus Ex|X[- ]?COM|Homeworld|Baldur'?s Gate|Planescape|Icewind|"
    r"Redneck Rampage|Ion Fury|Blood\b|Descent|Command & Conquer|Dune 2000|Need for Speed|Ridge Racer|"
    r"Burnout|GTA[ :]?|Sonic Robo Blast|\bSRB2\b|Celeste|VVVVVV|Undertale|Deltarune|"
    r"仙剑奇侠传|轩辕剑|金庸群侠传|幻想三国志|大富翁|三国群英传|星际争霸|反恐精英|半条命|毁灭战士|"
    r"侠盗猎车手|塞尔达|马力欧|马里奥|宝可梦|口袋妖怪|恶魔城|银河战士|最终幻想|合金装备|生化危机", re.I)
# 引擎/模拟器本身"登陆某平台"也是用户要的同类消息(Flycast Vita、PS4 RetroArch 这种)
ARR_ENGINE = re.compile(
    r"RetroArch|DuckStation|PCSX2|PCSX1?RPCS|RPCS3|Flycast|redream|\bDemul\b|melonDS|Citra|Azahar|Lime3DS|"
    r"PPSSPP|\bCemu\b|Project ?64|Mupen|ScummVM|xash3d|OpenMW|OpenRA|OpenTTD|OpenRCT|ioquake3|OpenArena|"
    r"sparkfl|SwiftyMC?|\bYabause\b|Mednafen|Ruffle|Daphne|Supermodel|Model ?2|Flycast|odometer|"
    r"Corsair32|OpenSourcing|reDux|DevilutionX|Cave|ioQuake|"
    r"\bCarafe\b|Autorun|Wine-?NX", re.I)
# 平台按 (标签, 正则) 有序表存,便于按"出现在动词前/后"判方向。
# 注意 \b 对中文不生效,所以中文平台名单独用字符匹配。
ARR_PLAT = [
    ("Switch2", r"\bswitch\s*2\b"),
    ("Switch", r"\bswitch\b|\bnintendo\s*switch\b|\bnx\b(?![a-z])"),
    ("PS5", r"\bps5\b|playstation\s*5"),
    ("PS4", r"\bps4\b|playstation\s*4"),
    ("PS3", r"\bps3\b|playstation\s*3"),
    ("PS2", r"\bps2\b|playstation\s*2|\bpsx2\b"),
    ("PS1", r"\bps1\b|\bpsx\b|playstation\s*1|\bpsone\b"),
    ("PSP", r"\bpsp\b"),
    ("Vita", r"\bvita\b|playstation\s*vita|\bps ?vita\b"),
    ("3DS", r"\b3ds\b|\b2ds\b|nintendo\s*3ds"),
    ("DS", r"\bnds\b|\bdsi\b"),
    ("WiiU", r"\bwii\s*u\b"),
    ("Wii", r"\bwii\b"),
    ("GameCube", r"\bgamecube\b|\bgc\b(?![a-z])"),
    ("N64", r"\bn64\b|nintendo\s*64"),
    ("Dreamcast", r"\bdreamcast\b"),
    ("Saturn", r"\bsaturn\b"),
    ("GBA", r"\bgba\b"),
    ("SNES", r"\bsnes\b|super\s*nintendo"),
    ("Genesis", r"\bgenesis\b|mega\s*drive"),
    ("NES", r"\bnes\b|famicom|nintendo\s*entertainment"),
    ("MiSTer", r"\bmister\b"),
    ("Pocket", r"analogue\s*pocket"),
    ("Anbernic", r"\banbernic\b|\brg3\d{3}\w*|\brg\d{3,4}[a-z]*\b"),
    ("Miyoo", r"\bmiyoo\b|\bmm\d{3}\b"),
    ("XF45V", r"\bxf45\b|rk3326"),
    ("Android", r"\bandroid\b"),
    ("Linux", r"\blinux\b"),
    ("Windows", r"\bwindows\b|\bwin\d{2}\b"),
    ("macOS", r"\bmacos\b|\bmac\b(?![a-z])"),
    ("Xbox", r"\bxbox\b"),
    ("Web", r"\bbrowser\b|\bhtml5\b|\bwebassembly\b|\bwasm\b"),
    ("掌机", r"开源掌机|复古掌机|retro\s*handheld"),
]
# "PCSX2-Wii"、"Flycast Vita" 这类**引擎名紧挨平台名**的写法本身就在说登陆:
# 标题常不带 ported/running 这种动词,只按动词会漏(实测漏掉 PCSX2-Wii Alpha)。
# 中间只允许极短间隔(分隔符 + 可选 for/in/on),不许任意远,否则天天泛匹配。
_PLAT_ALT = "|".join("(?:%s)" % p for _, p in ARR_PLAT)
ARR_ADJ = re.compile(r"(?:%s)[\s\-_/]{0,4}(?:for|in|on)?[\s\-_/]{0,2}(?:%s)"
                     % (ARR_ENGINE.pattern, _PLAT_ALT), re.I)
# 档②的领域上下文闸门(2026-10-13 按实测加,只对**非 GitHub 综合源**生效)。
# 起因:这轮把综合媒体与大论坛(GamesRadar / Dexerto / VG247 / Resetera / Push Square)挂上之后,
# 624 条新入库里冒出 43 条 HOT,一大半是"复仇者电影海报泄露"、"宝可梦卡牌卖了 15.6 万"、
# "GTA6 又泄露了"这类纯娱乐新闻 —— 老档②只要求"标题里有产品名 + 够新",
# 而综合媒体天天提 GTA / Zelda / Pokemon,产品名本身不再等于"本库要的资源消息"。
# 所以对这些源,产品名之外还必须出现**平台 / 引擎 / 设备 / 移植类领域词**。
# 为什么不砍 GitHub 源:仓库流一条标题就是资源本身(SwitchPorts 清单更新、muOS 的
# "Added TrimUI EGL library for PPSSPP"、libretro-super 的 "Add rar for flycast"),
# 按同一把尺子砍会把真信号一起砍掉 —— 实测过,所以闸门按 kind 分档,上下文也只在**原标题**上找
# (挖过源名词的标题里 "MiSTer Subsonic for MiSTer" 会连平台都被挖没)。
HOT_CTX_DEVICE = re.compile(
    r"atmosph[eè]re|hekate|fusee|luma3ds|nintendo\s*2ds|henkaku|h[- ]?encore|henlo|\bmset9\b|"
    r"freemcboot|muos|trimui|crossmix|spruceos|retrofw|retropie|batocera|recalbox|emuelec|arkos|"
    r"vitashell|adrenaline|pro[- ]?psp|homebrew|\bcfw\b|firmware|\bsdk\b|softmod|jailbreak|exploit|usbloader", re.I)
HOT_CONTEXT = re.compile(
    r"(?:%s)|(?:%s)|(?:%s)|\bports?\b|emulat\w*|\bengine\b|source[- ]code|\broots?\b|\broms?\b|"
    r"hack\w*|decompil\w*|recomp\w*|reverse[- ]?engineer|\bdump\b"
    r"|移植|模拟器|自制|固件|汉化|源码|开源|引擎|逆向|破解|整合包"
    % (_PLAT_ALT, ARR_ENGINE.pattern, HOT_CTX_DEVICE.pattern), re.I)
# 商业/娱乐噪音负闸门(2026-10-20,只对 kind != github_atom 生效,见 is_hot() 里的用法)。
# 产品名+平台名都齐、但整条是商业新闻/娱乐选角/带货时,不进爆款短名单。
# 词表刻意不碰 announce/offers/confirmed/price: "Anbernic Offers First Look at Incoming Handheld"、
# "AliExpress Leaks Price ... Anbernic RG DDS" 这类新机消息跟本库的机型线有关,要留
# (2026-10-20 差异审查实测:第一版带了 \bprices?\b,把两条 RG DDS 新机消息误杀,已拿掉)。
NEG_COMMERCIAL = re.compile(
    r"launch trailer|box ?office|\bfilms?\b|\bmovies?\b|casting|actors?\b|actress|"
    r"\bsold\b|\bcopies\b|\bsales\b|best[- ]?selling|restock|pre[- ]?orders?\b|"
    r"merch\b|\bdeals?\b|discount|price drop|giveaway", re.I)
# 论坛的 [RELEASE] 标签本身就等于"成品出货",动词表里没词也算
# (否则 "[RELEASE] Flycast Vita by Rinnegatamante" 这类最该收的条目会漏)。
ARR_TAG_RELEASE = re.compile(r"\[\s*release\s*\]", re.I)
LOADER_ARR_NAME = re.compile(r"\bCarafe\b|Autorun|Wine-?NX", re.I)
LOADER_ARR_VERB = re.compile(
    r"(?:turn|bring|play|run)[^.!?]{0,60}?\b(?:into|to|on)\b[^.!?]{0,40}?switch", re.I)
ARR_VERB = re.compile(
    r"ported to|port for|port of|native port|\bport\b|\bports\b|runs on|running on|now plays|now runs|"
    r"first playable|playable on|arrives|arriving|coming to|comes to|lands on|reaches|debut|"
    r"released for|out on|works on|booted on|reverse[- ]engineer|"
    r"移植|登陆|登录|上线|跑通|跑在|能用上|适配", re.I)

# ============ 聚焦层(2026-10-20 按用户"聚焦于我们喜欢的内容"加) ============
# 每条入库条目按这张表打主题标签,存台账第 12 列 flag_focus(多个标签用 + 连),
# 日报顶部新增"今日聚焦"段按主题分组 —— 爆款候选是粗筛,聚焦段是路由。
# 标签顺序即日报里的展示顺序。词表只放"我们确实在追的线":
# Switch 移植/Vita/开源掌机固件/模拟器核心/引擎重实现/PortMaster/FPGA/中文源/源码泄露。
FOCUS_RULES = [
    ("Switch移植", r"switch|大气层|atmosphere|hekate|\bnx\b|\bnro\b|port0r|switchports|missioncontrol|sphaira|ultrahand"),
    ("Vita/PSP", r"\bvita\b|\bpsp\b|adrenaline|henlo|h[- ]?encore|henkaku|vitashell|vitadb"),
    ("开源掌机与固件", r"arkos|jelos|rocknix|knulli|amberelec|muos|spruceos|crossmix|trimui|anbernic|rg35|rg40|miyoo|retroid|powkiddy|xf45|rk3326|rk3566|batocera|recalbox|emuelec|retropie|掌机|handheld"),
    ("模拟器核心", r"emulat|retroarch|duckstation|pcsx2|rpcs3|ppsspp|flycast|melonds|azahar|lime3ds|mgba|sameboy|mesen|desmume|cemu|dolphin|\bares\b|shadps4|mupen|libretro|snes9x|fceux|mame\b"),
    ("引擎重实现", r"recompil|decompil|reverse[- ]?engineer|openrw|\bre3\b|\brevc\b|opengoal|devilutionx|openmw|openrct|openttd|corsixth|vcmi|gzdoom|\braze\b|openbor|cannonball|rigelengine|theforceengine|openjkdf2|pcsx-redux|rsdkv3|switchwaker|sa2-nx|marathonrecomp|unleashedrecomp|futari|max_arm64|mgs_reversing|静态重编|反编译"),
    ("PortMaster/开源游戏", r"portmaster|harbourmaster|\bports?\b|开源游戏|公版|homebrew"),
    ("FPGA/复刻硬件", r"(?-i:MiSTer)|fpga|analogue pocket|pocket[- ]sync|pupdate"),
    ("源码泄露/安全", r"source[- ]code leak|leaked|breach|\bhacked?\b|dmca|takedown|泄露|入侵|漏洞|exploit|jailbreak"),
    ("下架抢救", r"taken down|takedown|dmca|cease and desist|\bc&d\b|shut down|shuts down|shutting down|"
              r"shut-down|pulled from|removed from github|delisted|lawsuit|"
              r"repo.*(?:deleted|gone)|no longer available|"
              r"下架|律师函|删库|仓库被删|停止维护|项目关闭"),
]
# 中文源:按 source_id 前缀 + 标题含 CJK 双重判定(中文源的名字也可能带英文,如 RetroDECK 中文报道)。
FOCUS_CN_SRC = re.compile(r"^cn_|机核|少数派|吾爱|中文", re.I)
FOCUS_CJK = re.compile(r"[一-鿿]")
FOCUS_ORDER = [name for name, _ in FOCUS_RULES] + ["中文源"]


def focus_of(title, url="", source="", source_id=""):
    """按 FOCUS_RULES 打主题标签,返回 'Switch移植+模拟器核心' 这种串(没有命中返回空串)。"""
    t = "%s %s" % (title or "", url or "")
    tags = [name for name, pat in FOCUS_RULES if re.search(pat, t, re.I)]
    if FOCUS_CN_SRC.search("%s %s" % (source_id or "", source or "")) or FOCUS_CJK.search(title or ""):
        tags.append("中文源")
    return "+".join(tags)


def _first_hit(rx, text):
    m = rx.search(text or "")
    return m.group(0)[:28] if m else ""


# URL 里的 ID 段会把作品名"造"出来:Reddit 的 base36 帖子 ID(1wugtaf 里含着 gta)、
# GBAtemp 的楼层号(.684185)、GitHub 的 commit sha。arrival_of() 连 URL 一起扫,
# 所以扫之前先把这三类 ID 段挖掉。2026-10-20 实测:台账 3303 行
# `ES-DE 3.5.0 ... r/emulation/comments/1wugtaf/...` 就是这样被标成 ARR|gta|PS4|Android 的。
# 只挖 ID 段,不动域名/路径词(所以 switch2、rk3326 这种带数字的真词不受影响)。
URL_ID_SEG = re.compile(
    r"/comments/[0-9a-z]+|(?<=[./])[0-9]{4,}(?=[./?]|$)|[0-9a-f]{32,}(?=[./?]|$)", re.I)


def _scan_text(title, url):
    return "%s %s" % (title or "", URL_ID_SEG.sub(" ", url or ""))

# 台账里的 first_seen 存的是 **UTC**,而日报文件名/标题用的是本地日。
# 2026-10-11 凌晨跨 UTC 午夜时栽过一次:报表标题写 10-11、筛的是 first_seen 开头 "10-11",
# 结果"今日入库 0 条"、爆款整段消失。所以按本地日筛选前,必须先把 UTC 时间换算成本地日。
def local_day(utc_str):
    try:
        d = dt.datetime.strptime((utc_str or "")[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return ""
    return d.replace(tzinfo=dt.timezone.utc).astimezone().date().isoformat()


# 档③用的"像一次发版"的形状:标题里有 v?数字.数字 这种版本号。
# 只认形状不认内容,所以必须配合"这条目本身就是 GitHub 发版页"一起用。
VER_RELEASE = re.compile(r"(?:^|[^0-9a-z])v?\d+\.\d+[\w.\-]*", re.I)
# 注意:台账里存的是**条目自己的 URL**(spruceOS 的那条是 .../releases/tag/v4.5.2),
# 不是 feed 地址。第一次写这档时我判 `"/releases.atom" in url`,于是 v4.5.2 全部漏标 ——
# 判据要落在条目 URL 的形状上。commit 流给的是 /commit/<sha>,天然不会误命中。
IS_RELEASE_URL = re.compile(r"github\.com/[^/]+/[^/]+/releases/tag/", re.I)
# 天天出的滚动构建不算新消息,否则 DuckStation 这种每周出 nightly 的源会淹没短名单。
NOT_A_RELEASE = re.compile(r"nightly|rolling|preview|daily|snapshot|build \d|wip|dev build", re.I)


def is_hot(title, url="", source="", pub="", kind=""):
    """三档:
    ①事件动词看全文;
    ②产品名先把"源名自带的词"从标题里挖掉再判(跨源提及才算新闻), 且要落在 BACKFILL_DAYS 内;
      **非 GitHub 综合源(kind != github_atom)还要求原标题里有 HOT_CONTEXT 的领域词**;
    ③**专用 release 源的自己家发版**: 标题带版本号 + 够新, 也算。
      补这一档是因为只做 ①② 会**漏报**:spruceOS v4.5.2、TRAX 1.0.0 就在自己的源里,
      产品名被 ② 挖掉之后永远进不了短名单 —— 而那正是最该知道的"新资源"。
      同时 14 天窗口挡住了首跑回填(spruceOS v4.3.4 那种 8 月的旧版不报)。
    """
    if HOT_VERB.search("%s %s" % (title or "", url or "")):
        return True
    t = title or ""
    # 挖两类:①源名里长度>=5 的 token(专有名词级);②**源名里出现的产品名本身**——
    # r/MiSTerFPGA 的 token 是 "miSTERFPGA",挖不动标题里的 "MiSTer",结果 9 条
    # "你最爱玩什么游戏"式闲聊全进了短名单。专用版块的自己家产品必然自匹配,一律不算消息。
    strip = [tok for tok in re.split(r"[^\w-]+", (source or "").lower()) if len(tok) >= 5]
    # 长度门槛 5 只对 token 生效:原来 >=4 会把 "wii"(来自 GBAtemp Wii 版)这种
    # **本身就该算跨源提及**的名字挖掉,直接漏报 PCSX2-Wii Alpha。产品名走 findall,不受该门槛影响。
    strip += [m.lower() for m in HOT_NAME.findall(source or "")]
    for tok in strip:
        t = re.sub("(?i)" + re.escape(tok), " ", t)
    if HOT_NAME.search(t) and _recent(pub):
        # 综合源(媒体 / 论坛 / reddit / youtube / itch)还要过领域词这一关,GitHub 仓库流直接算。
        if kind != "github_atom" and not HOT_CONTEXT.search(title or ""):
            return False
        # 2026-10-20 再加一道商业/娱乐噪音负闸门(只对非 GitHub 源生效):
        # 实测 "James Gunn confirms Mister Miracle casting"、"GTA 6 Launch Trailer Not Using PS5's QSSR"、
        # "Nintendo Underestimated Zelda Switch 2 Console Sales" 这类纯商业娱乐新闻,
        # 产品名+平台名都齐,但跟"有资源可收"毫无关系。领域词闸门拦不住它们(PS5 本身就是平台词)。
        # GitHub 仓库流标题本身就是资源,不受这道闸门影响。
        if kind != "github_atom" and NEG_COMMERCIAL.search(title or ""):
            return False
        return True
    if IS_RELEASE_URL.search(url or "") and VER_RELEASE.search(title or "") \
            and not NOT_A_RELEASE.search(title or "") and _recent(pub):
        return True
    return False



def arrival_of(title, url=""):
    """"大作/经典作品登陆某平台"专线。三样同现才算:
      ①作品名(ARR_GAME) 或 引擎/模拟器名(ARR_ENGINE);
      ②平台名(ARR_PLAT);
      ③登陆类动词(ARR_VERB)。
    只中作品名(塞尔达 speedrun 资讯)或只中平台名(PS4 主机评测)都不算 ——
    上一版爆款就是栽在"泛词全进短名单",这条专线同样宁可窄。
    返回 "ARR|作品名|目的平台|来源平台"(没命中返回空串)。目的平台取**动词之后**最先出现的那个,
    所以 "OoT 3DS running on PS4" 会正确判成 3DS -> PS4,而不是把两个平台混为一谈。
    URL 参与扫描前先过 _scan_text() 挖掉 ID 段(见 URL_ID_SEG 的注释)。
    """
    t = _scan_text(title, url)
    # 加载器/运行时类标题("Carafe: turn Windows games into Switch apps")没有作品名,
    # 方向也是反写的(Windows 在介词前当来源、Switch 在介词后当目的地),通用动词表接不住。
    # 2026-10-28 补:GBAtemp 685140/684587 两条 10-10 就进了台账,却因没动词一直判不出登陆线。
    lm = LOADER_ARR_NAME.search(t)
    if lm and LOADER_ARR_VERB.search(t):
        return cell("ARR|%s|Switch|%s" % (lm.group(0), "Windows" if re.search(r"windows", t, re.I) else ""))
    g = _first_hit(ARR_GAME, t) or _first_hit(ARR_ENGINE, t)
    if not g:
        return ""
    if not (ARR_VERB.search(t) or ARR_TAG_RELEASE.search(t or "") or ARR_ADJ.search(t or "")):
        return ""
    # 动词优先于 [RELEASE] 标签,标签/邻接又优先于无:标签永远在句首,拿它会失去方向信息。
    mv = ARR_VERB.search(t) or ARR_TAG_RELEASE.search(t or "") or ARR_ADJ.search(t or "")
    vpos = mv.start()
    hits = []
    for label, pat in ARR_PLAT:
        m = re.search(pat, t, re.I)
        if m:
            hits.append((m.start(), len(m.group(0)), label))
    if not hits:
        return ""
    hits.sort()
    # 同一位置命中多个标签时("Wii U" 既中 WiiU 又中 Wii)只留匹配串更长的那个,
    # 否则 "Sonic ports for Wii U" 会被判成登陆到 Wii —— 这是实测踩出来的。
    dedup = []
    for pos, ln, lab in hits:
        if dedup and dedup[-1][0] == pos:
            if ln > dedup[-1][1]:
                dedup[-1] = (pos, ln, lab)
            continue
        dedup.append((pos, ln, lab))
    after = [lab for pos, ln, lab in dedup if pos > vpos]
    before = [lab for pos, ln, lab in dedup if pos <= vpos]
    if after:
        dest, src = "+".join(after), "+".join(before)
    else:
        # 动词在末尾("Oddworld Abe's Oddysee 3DS native port"):
        # 离动词最近的那个平台当目的地,更早的当来源。
        dest, src = (before[-1] if before else ""), "+".join(before[:-1])
    return cell("ARR|%s|%s|%s" % (g, dest, src))


# GitHub **作者级** .atom(https://github.com/<user>.atom)给的是活动流水,不是发布。
# 2026-10-13 实测踩坑:toniisound 那条流 28 条里 12 条是 pushed / created a branch / issue 评论,
# 而这些条目的 URL 自带 `model2-nx` 这种仓库 slug,arrival_of() 连 URL 一起扫 ——
# 作品名和目的平台全从 slug 里"造"出来,大作专线被假命中灌满。
# 所以作者流只留发布与开仓类事件;"created a branch" 精确到 branch/tag,免得把 "X created <repo>" 也杀掉。
AUTHOR_NOISE = re.compile(
    r"pushed|created a (?:branch|tag)|deleted|referenced|commented|labeled|unlabeled|"
    r"opened|closed|reopened|assigned|unassigned|reviewed|forked|starred|followed|installed", re.I)


def is_author_feed(url):
    u = (url or "").rstrip("/")
    return u.endswith(".atom") and "/releases.atom" not in u and "/commits.atom" not in u


# 泛词不进"爆款候选";上一版就是栽在这里
SUSPICIOUS = re.compile(r"free download|full game|crack(ed)?|ISO download|NSP dump|XCI|romset|整合包|warez", re.I)


def cell(s):
    """台账是 TSV,任何制表符/引号/换行都会破坏 csv 读回 —— 一律吃掉。"""
    return str(s or "").replace("\t", " ").replace("\r", " ").replace("\n", " ").replace('"', "'").strip()


def load_registry():
    if not os.path.exists(REG):
        raise SystemExit("缺登记表: %s" % REG)
    rows = []
    with open(REG, encoding="utf-8", newline="") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            r = dict(zip(head, parts + [""] * (len(head) - len(parts))))
            # 登记表不要求写 kind:GitHub 的 .atom 是仓库动态,其余按通用 RSS/Atom 处理
            r["kind"] = "github_atom" if "github.com/" in r.get("url", "") else "rss"
            if r.get("enabled", "1") == "1":
                rows.append(r)
    return rows


def load_seen():
    seen = set()
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8", newline="") as fh:
            head = fh.readline().rstrip("\n").split("\t")
            for line in fh:
                p = line.rstrip("\n").split("\t")
                r = dict(zip(head, p + [""] * (len(head) - len(p))))
                seen.add(r.get("key") or r.get("url"))
    return seen


def fetch(url, tries=2):
    last = ""
    for _ in range(tries):
        try:
            p = subprocess.run(["curl", "-s", "-L", "--max-time", "60", "-A", UA,
                                "-w", "\n@@%{http_code}", url],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            body, _, code = p.stdout.rpartition("\n@@")
            code = (code or "000").strip()
            # curl 超时(exit 28)照样打 200,大 feed 被砍成半截 -> parse_error -> "解析=0",
            # 看着像"这个源恰好没内容"。实测 ScummVM 1.4MB feed 两轮结果不一样(0/10 条),
            # 就是这一条。退出码非 0 一律判失败,半截 body 不许冒充成功。
            if p.returncode != 0:
                last = "curl_err_%d/http%s" % (p.returncode, code)
                continue
            if code == "200" and body.strip():
                return code, body
            last = code
        except Exception as e:
            last = "ERR:%s" % type(e).__name__
    return last, ""


def norm_date(s):
    """RSS 是 'Sat, 10 Oct 2026 12:00:00 +0800',Atom 是 ISO —— 统一成 YYYY-MM-DD,别让日报里出现 `Sat, 10 Oc`。"""
    s = (s or "").strip()
    if not s:
        return ""
    try:
        import email.utils
        d = email.utils.parsedate_to_datetime(s)
        if d:
            return d.date().isoformat()
    except Exception:
        pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return m.group(0) if m else s[:16]


def strip_ns(tag):
    return tag.split("}", 1)[1] if "}" in tag else tag


def parse_items(xmltext):
    """同时吃 RSS2.0(<item>) 和 Atom(<entry>),返回 [{title,url,pub,guid}]"""
    out = []
    head = (xmltext or "")[:2000]
    # 200 但给的是 HTML 落地页,比 429 更危险:看着成功、实际 0 条。
    # 实测 old.reddit.com/r/<sub>/.rss 就是这样(327 KB "Welcome to Reddit" 反爬页)。
    # 这类必须单独点名,不能让它在失败表里伪装成"这个 feed 恰好没内容"。
    if "<html" in head.lower() and "<rss" not in head.lower() and "<feed" not in head.lower():
        return out, "html_not_feed"
    try:
        root = ET.fromstring(xmltext)
    except ET.ParseError:
        # 有些站带非法控制字符,先洗一遍再试
        clean = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xmltext)
        try:
            root = ET.fromstring(clean)
        except ET.ParseError:
            return out, "parse_error"
    for node in root.iter():
        t = strip_ns(node.tag)
        if t not in ("item", "entry"):
            continue
        title = url = pub = guid = ""
        for ch in node:
            ct = strip_ns(ch.tag)
            txt = (ch.text or "").strip()
            if ct == "title" and not title:
                title = html.unescape(re.sub(r"\s+", " ", txt))
            elif ct == "link":
                if txt:
                    url = url or txt
                else:
                    a = ch.get("href")
                    if a:
                        url = url or a
            elif ct in ("pubDate", "published", "updated") and not pub:
                pub = txt
            elif ct in ("guid", "id") and not guid:
                guid = txt
        if title or url:
            out.append({"title": title[:220], "url": url, "pub": pub, "guid": guid})
    return out, "ok"


def key_of(it):
    basis = it.get("guid") or it.get("url") or ("%s|%s" % (it.get("title", ""), it.get("pub", "")))
    return hashlib.sha1(basis.encode("utf-8", "replace")).hexdigest()[:16]


def relabel():
    """改完 HOT/SUSPICIOUS/FOCUS 词表后按台账里已有的标题重算标记。
    只改 flag 各列,first_seen 与 key 一律不动 —— 调词表不该丢历史。
    2026-10-20 起多了第 12 列 flag_focus(聚焦主题),老台账首次 --relabel 自动补列。"""
    if not os.path.exists(LEDGER):
        raise SystemExit("还没有台账: %s" % LEDGER)
    with open(LEDGER, encoding="utf-8", newline="") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        rows = [line.rstrip("\n").split("\t") for line in fh if line.strip()]
    if "flag_arrival" not in head:          # 老台账只有 10 列,补第 11 列并给每行占位
        head.append("flag_arrival")
        for p in rows:
            while len(p) < len(head):
                p.append("")
    if "flag_focus" not in head:            # 2026-10-20 聚焦层:补第 12 列
        head.append("flag_focus")
        for p in rows:
            while len(p) < len(head):
                p.append("")
    ix = {c: head.index(c) for c in ("title", "url", "source", "source_id", "pub", "kind",
                                     "flag_hot", "flag_note", "flag_arrival", "flag_focus")}
    changed = 0
    for p in rows:
        while len(p) < len(head):
            p.append("")
        new_hot = "HOT" if is_hot(
            p[ix["title"]], p[ix["url"]], p[ix["source"]], p[ix["pub"]], p[ix["kind"]]) else ""
        new_note = "SUSPECT_PIRACY_WORDING" if SUSPICIOUS.search(p[ix["title"]]) else ""
        new_arr = arrival_of(p[ix["title"]], p[ix["url"]])
        new_focus = focus_of(p[ix["title"]], p[ix["url"]], p[ix["source"]], p[ix["source_id"]])
        if (p[ix["flag_hot"]] != new_hot or p[ix["flag_note"]] != new_note
                or p[ix["flag_arrival"]] != new_arr or p[ix["flag_focus"]] != new_focus):
            p[ix["flag_hot"]], p[ix["flag_note"]], p[ix["flag_arrival"]], p[ix["flag_focus"]] = (
                new_hot, new_note, new_arr, new_focus)
            changed += 1
    with open(LEDGER, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(head) + "\n")
        for p in rows:
            fh.write("\t".join(p) + "\n")
    focus_cnt = {}
    for p in rows:
        for tg in (p[ix["flag_focus"]] or "").split("+"):
            if tg:
                focus_cnt[tg] = focus_cnt.get(tg, 0) + 1
    print("重算标记:改 %d 行 / 共 %d 行;HOT 现有 %d 条;大作登陆 %d 条;聚焦分布 %s" % (
        changed, len(rows), sum(1 for p in rows if p[ix["flag_hot"]] == "HOT"),
        sum(1 for p in rows if p[ix["flag_arrival"]].startswith("ARR|")),
        "、".join("%s %d" % kv for kv in sorted(focus_cnt.items(), key=lambda x: -x[1]))))
    write_arrival_md([dict(zip(head, p)) for p in rows
                      if (p[ix["flag_arrival"]] or "").startswith("ARR|")], dt.date.today().isoformat())


def fmt_arr(flag):
    """'ARR|作品|目的平台|来源平台' -> (作品, 目的, 来源)。"""
    p = (flag or "").split("|")
    while len(p) < 4:
        p.append("")
    return p[1], p[2], p[3]


def arr_row_md(r, v):
    g, dst, src = fmt_arr(r.get("flag_arrival", ""))
    local = v.get("payload") or "—"
    verdict = v.get("verdict") or "待判定"
    url = r.get("url") or "#"
    return "| %s | %s | %s | `%s` | [%s](%s) | **%s** %s | `%s` |\n" % (
        cell(g), cell(dst) or "?", cell(src) or "—", (r.get("pub") or "")[:10],
        cell(r.get("title") or url)[:78], url, verdict, cell(v.get("action") or ""), local)


ARR_HEAD = ("| 作品/引擎 | 登陆到 | 从哪来 | 日期 | 消息(点开原文) | 判定 | 本地资源 |\n"
            "|---|---|---|---|---|---|---|\n")


def write_arrival_md(arr_all, today):
    """把台账里所有命中专线的大条目落成一份**累计**清单(每次运行整体重算,不是追加)。
    判定列来自 大作判定.tsv(人工维护,按 url 子串匹配),没写过判定的显示'待判定'。"""
    vs = load_verdicts()
    order = {"已下载": 0, "可下": 1, "待判定": 2, "只监控": 3, "拒收": 4}
    rows = []
    for r in arr_all:
        v = verdict_for(r.get("url", ""), vs)
        rows.append((order.get(v.get("verdict", ""), 2), r.get("pub") or "", v, r))
    rows.sort(key=lambda x: x[1], reverse=True)      # 先按日期倒序
    rows.sort(key=lambda x: x[0])                    # 再稳定地按判定分档(已下载/可下 顶到最上面)
    cnt = {}
    for _, _, v, _ in rows:
        cnt[v.get("verdict") or "待判定"] = cnt.get(v.get("verdict") or "待判定", 0) + 1
    with open(ARR_MD, "w", encoding="utf-8") as fh:
        fh.write("# 大作/经典作品登陆各平台 —— 累计清单(自动生成,%s)\n\n" % today)
        fh.write("- 命中 **%d** 条;判定分布:%s\n" % (len(rows), "、".join("%s %d" % (k, v) for k, v in sorted(cnt.items()))))
        fh.write("- 判据:标题/URL 里**作品名(或引擎名)+ 平台名 + 登陆类动词**三者同现才算,见 `_工具脚本/scene_monitor.py` 的 `arrival_of()`。\n")
        fh.write("- 判定列来自 `06-资讯监控/大作判定.tsv`(人工维护,按 URL 子串匹配;`match` 列写帖号或仓库名片段)。\n")
        fh.write("- **「已下载」和「可下」才是真能落进本地文件夹的**;"
                  "「拒收」指商业游戏本体、无哈希网盘包,或仓库把任天堂/世嘉等原厂素材提交进源码 —— 这三类本库不收,详见根目录指北 §6。\n\n")
        fh.write(ARR_HEAD)
        for _, _, v, r in rows[:200]:
            fh.write(arr_row_md(r, v))
        fh.write("\n> 上面按发布日期倒序,最多显示 200 条;更早的条目仍在台账里,加 `--relabel` 不会丢。\n")
    print("大作登陆清单: %d 条 -> %s" % (len(rows), ARR_MD))
    return rows


def dedupe():
    """删台账里同 key 的重复行(并发跑留下的历史包袱),保留 first_seen 最早的那一条。
    2026-10-12 08:30/08:31 两轮并发留下 73 组,共 73 行多余。"""
    with open(LEDGER, encoding="utf-8", newline="") as fh:
        head = fh.readline().rstrip("\n").split("\t")
        rows = [line.rstrip("\n").split("\t") for line in fh if line.strip()]
    best, order = {}, []
    for p in rows:
        k = p[0]
        if k not in best:
            best[k] = p
            order.append(k)
        elif p[1] < best[k][1]:
            best[k] = p
    with open(LEDGER, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(head) + "\n")
        for k in order:
            fh.write("\t".join(best[k]) + "\n")
    print("台账去重:删 %d 行重复(%d 行 -> %d 行),每组保留 first_seen 最早的那条" % (
        len(rows) - len(order), len(rows), len(order)))


RETRY_GAP = 120        # 错峰重试前先等多久(秒):Reddit 限流窗口一般要几分钟才退
RETRY_SPACING = 8      # 重试时每个源之间隔多久(秒):降频本身就是解法的一部分
# 2026-10-22 实测:同一出口 IP 间隔 20s 重试 r/PSP/.rss,6 发里 2 发 200(约 33%/发),
# 且 429 不是瞬态而是持续限流 —— 一轮只捞回三分之一,3 轮累计约七成。
# 代价:每轮 = RETRY_GAP + 源数×RETRY_SPACING(约 4~5 分钟),日跑总时长可接受。
RETRY_ROUNDS = 3


def process_source(r, ctx):
    """抓一个源、去重、入账。抽成函数是为了让错峰重试能原样重跑(2026-10-21)。

    ctx 是共享状态:seen(去重键集合)/append_lines(待写台账行)/new_items(本次新增)
    failures(失败清单)/per_source(每源统计)/now(UTC 时间戳)。
    """
    # 浏览器层源(bw_*,Discuz 要登录态的那批)由 browser_watch.py 每周抓,patchright 无头
    # chromium 才拿得到。scene_monitor 用 curl 抓首页只能是 html_not_feed —— 记 skip 占位
    # 保持"不许静默跳过"的可见性,但不进 failures(那会是每天两条假失败,还会进周报常败榜)。
    if r["id"].startswith("bw_"):
        ctx["per_source"].append({"name": r["name"], "http": "skip",
                                  "parsed": 0, "new": 0, "status": "browser_layer"})
        print("%-30s http=skip 浏览器层源(由 browser_watch.py 每周跑),不在每日抓取范围" % r["name"])
        return
    code, body = fetch(r["url"])
    items, status = ([], "empty") if not body else parse_items(body)
    fresh = []
    dropped = 0
    author_feed = is_author_feed(r["url"])
    r["kind"] = r.get("kind") or ("github_atom" if "github.com/" in r["url"] else "rss_atom")
    for it in items:
        if author_feed and AUTHOR_NOISE.search(it.get("title", "")):
            dropped += 1
            continue
        k = key_of(it)
        if k in ctx["seen"]:
            continue
        ctx["seen"].add(k)
        fresh.append(it)
        ctx["append_lines"].append("\t".join([
            cell(k), cell(ctx["now"]), cell(r["id"]), cell(r["kind"]), cell(r["name"]),
            cell(norm_date(it.get("pub"))), cell(it.get("title")), cell(it.get("url")),
            cell("HOT" if is_hot(it.get("title", ""), it.get("url", ""), r["name"],
                                 it.get("pub", ""), r["kind"]) else ""),
            cell("SUSPECT_PIRACY_WORDING" if SUSPICIOUS.search(it.get("title", "")) else ""),
            arrival_of(it.get("title", ""), it.get("url", "")),
            focus_of(it.get("title", ""), it.get("url", ""), r["name"], r["id"]),
        ]))
    if code != "200" or not items:
        ctx["failures"].append((r["name"], code, status, len(items)))
    ctx["per_source"].append({"name": r["name"], "http": code, "parsed": len(items), "new": len(fresh)})
    for it in fresh:
        ctx["new_items"].append((r["name"], it))
    print("%-30s http=%-4s 解析=%-4d 新增=%-4d%s" % (
        r["name"], code, len(items), len(fresh),
        ("  活动流丢弃=%d" % dropped) if dropped else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--relabel", action="store_true", help="只按词表重算台账标记(含聚焦列),不联网")
    ap.add_argument("--dedupe", action="store_true", help="只删台账里同 key 的重复行(并发跑留下的),不联网")
    ap.add_argument("--retry-failed", action="store_true",
                    help="跑完后对瞬失败源(429/000/curl_err)错峰重试,最多 %d 轮(每轮先等 %ds+每源间隔 %ds)"
                         % (RETRY_ROUNDS, RETRY_GAP, RETRY_SPACING))
    args = ap.parse_args()
    if args.dedupe:
        dedupe()
        return
    if args.relabel:
        relabel()
        return

    rows = load_registry()
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as fh:
            head_now = fh.readline().rstrip("\n").split("\t")
            if "flag_arrival" not in head_now or "flag_focus" not in head_now:
                print("台账缺 flag_arrival/flag_focus 列 -> 先补列并按现有词表重算标记(不联网)")
                relabel()
    if args.limit:
        rows = rows[:args.limit]
    seen = load_seen()
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = dt.date.today().isoformat()

    per_source, new_items, failures = [], [], []
    append_lines = []
    ctx = {"seen": seen, "append_lines": append_lines, "new_items": new_items,
           "failures": failures, "per_source": per_source, "now": now}
    for r in rows:
        process_source(r, ctx)

    # 错峰重试(2026-10-21 新增,2026-10-22 改多轮):Reddit 429 是本机 IP 持续限流,不是源死了。
    # 实测同一出口 IP 间隔 20s 重试,6 发中 2 发 200(约 33%/发)——一轮只捞回三分之一,
    # 所以默认 3 轮(累计约七成)。只重试瞬失败(429/000/curl_err_*),
    # 403(Cloudflare)重试没意义,不去火上浇油。
    if args.retry_failed:
        for rnd in range(1, RETRY_ROUNDS + 1):
            transient = []
            for r in rows:
                f = next((x for x in failures if x[0] == r["name"]), None)
                if f and (f[1] == "429" or f[1] == "000" or f[1].startswith("curl_err")):
                    transient.append(r)
            if not transient:
                break
            print("\n错峰重试第 %d/%d 轮:%d 个瞬失败源(先等 %ds,之后每个隔 %ds)..."
                  % (rnd, RETRY_ROUNDS, len(transient), RETRY_GAP, RETRY_SPACING))
            time.sleep(RETRY_GAP)
            for r in transient:
                failures[:] = [x for x in failures if x[0] != r["name"]]
                per_source[:] = [p for p in per_source if p["name"] != r["name"]]
                time.sleep(RETRY_SPACING)
                process_source(r, ctx)
            ok = sum(1 for r in transient if not any(x[0] == r["name"] for x in failures))
            print("第 %d 轮结果:捞回 %d/%d 个源" % (rnd, ok, len(transient)))

    os.makedirs(DAILY, exist_ok=True)
    if append_lines:
        fresh_file = not os.path.exists(LEDGER)
        # 落盘前按**磁盘现状**再过一遍 key。2026-10-12 08:30 与 08:31 两轮并发跑,
        # 两边都只拿自己开跑时的快照去重,结果同一条被写了两遍(台账里 73 组重复,
        # 全是跨运行、first_seen 相差 100 秒)。开跑时的快照只用来少拉几次网络,
        # **不能当幂等依据**,幂等要在真正写的那一瞬间对着文件判。
        disk = load_seen()
        kept, raced = [], 0
        for ln in append_lines:
            k = ln.split("\t", 1)[0]
            if k in disk:
                raced += 1
                continue
            disk.add(k)
            kept.append(ln)
        if raced:
            print("并发去重:落盘前丢弃台账里已存在的 %d 条" % raced)
        if kept or fresh_file:
            with open(LEDGER, "a", encoding="utf-8", newline="") as fh:
                if fresh_file:
                    fh.write("key\tfirst_seen_utc\tsource_id\tkind\tsource\tpub\ttitle\turl\tflag_hot\tflag_note\tflag_arrival\tflag_focus\n")
                if kept:
                    fh.write("\n".join(kept) + "\n")
        append_lines = kept

    rep = os.path.join(DAILY, "%s.md" % today)
    # 日报按"今天 first_seen 的全部条目"聚合,而不是本次运行新增 —— 一天跑两次也不会出现空报。
    today_items, arr_all = [], []
    if os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8", newline="") as fh:
            head = fh.readline().rstrip("\n").split("\t")
            for line in fh:
                p = line.rstrip("\n").split("\t")
                r = dict(zip(head, p + [""] * (len(head) - len(p))))
                if local_day(r.get("first_seen_utc") or "") == today:
                    today_items.append((r.get("source", ""), {
                        "title": r.get("title", ""), "url": r.get("url", ""),
                        "pub": r.get("pub", ""), "hot": r.get("flag_hot") == "HOT",
                        "note": r.get("flag_note", ""), "arr": r.get("flag_arrival", ""),
                        "focus": r.get("flag_focus", "")}))
                if (r.get("flag_arrival") or "").startswith("ARR|"):
                    arr_all.append(r)
    with open(rep, "w", encoding="utf-8") as fh:
        fh.write("# 资讯日报 %s\n\n" % today)
        fh.write("- 源:**%d** 个,失败/空:**%d** 个;本次新入库 **%d** 条;**今日入库合计 %d 条**;台账累计 **%d** 条\n\n"
                 % (len(rows), len(failures), len(new_items), len(today_items), len(seen)))
        if failures:
            fh.write("## 需要人看的失败(不许静默跳过)\n\n")
            fh.write("| 源 | HTTP | 状态 | 解析条目 |\n|---|---|---|---|\n")
            for n, c, s, ln in failures:
                fh.write("| %s | %s | %s | %d |\n" % (n, c, s, ln))
            fh.write("\n> 429 = Reddit 对本机 IP 限流(换时段或降频);403 = Cloudflare 反爬(站点活着);000 = 本机 TLS 层失败(不代表站点死亡);"
                     "`curl_err_N/httpM` = 传输本身没跑完(exit N,常见 28=超时),此时 httpM 是半截响应的码,内容不可信,重跑就好。\n\n")
        hot = [(n, it) for n, it in today_items if it["hot"]]
        arr_today = [(n, it) for n, it in today_items if (it.get("arr") or "").startswith("ARR|")]
        if arr_today:
            vs = load_verdicts()
            fh.write("## 大作/经典登陆平台(专线,今日 %d 条)\n\n" % len(arr_today))
            fh.write(ARR_HEAD)
            for n, it in arr_today[:40]:
                fh.write(arr_row_md({"flag_arrival": it["arr"], "pub": it["pub"],
                                     "title": it["title"], "url": it["url"]},
                                    verdict_for(it["url"], vs)))
            fh.write("\n> 完整累计清单(含判定与本地资源路径)看 `06-资讯监控/大作登陆平台.md`。\n\n")
        if hot:
            fh.write("## 爆款候选(%d 条,关键词粗筛,判定留给你)\n\n" % len(hot))
            for n, it in hot[:40]:
                note = "  ⚠ 措辞像盗版分发" if it["note"] else ""
                fh.write("- **%s** — [%s](%s) `%s`%s\n" % (n, it["title"] or "(无标题)", it["url"], it["pub"], note))
            fh.write("\n")
        # 聚焦段(2026-10-20 新增):按 FOCUS_RULES 的主题把今天入库的条目分档,
        # 同一条命中多个主题会在多个小节各出现一次 —— 这是路由不是筛选,
        # "没有命中任何主题"的条目不会进这里,往下看"今日入库全部条目"。
        focus_groups = {}
        for n, it in today_items:
            for tg in (it.get("focus") or "").split("+"):
                if tg:
                    focus_groups.setdefault(tg, []).append((n, it))
        if focus_groups:
            n_focus_items = sum(1 for _, it in today_items if it.get("focus"))
            fh.write("## 今日聚焦(%d 条带主题 / 共 %d 条入库;按你关注的主题分档)\n\n" % (n_focus_items, len(today_items)))
            for tg in FOCUS_ORDER:
                items = focus_groups.get(tg)
                if not items:
                    continue
                fh.write("### %s(%d)\n\n" % (tg, len(items)))
                for n, it in items[:20]:
                    marks = []
                    if it["hot"]:
                        marks.append("**[HOT]**")
                    if (it.get("arr") or "").startswith("ARR|"):
                        marks.append("**大作登陆**")
                    if it["note"]:
                        marks.append("⚠措辞像盗版分发")
                    fh.write("- **%s** — [%s](%s) `%s`%s\n" % (
                        n, it["title"] or "(无标题)", it["url"], it["pub"],
                        ("  " + " ".join(marks)) if marks else ""))
                if len(items) > 20:
                    fh.write("- …另 %d 条见下方按源分组全量\n" % (len(items) - 20))
                fh.write("\n")
        fh.write("## 今日入库全部条目(按源分组)\n\n")
        bysrc = {}
        for n, it in today_items:
            bysrc.setdefault(n, []).append(it)
        for n in sorted(bysrc):
            fh.write("### %s(%d)\n\n" % (n, len(bysrc[n])))
            for it in bysrc[n][:25]:
                fh.write("- [%s](%s) `%s`\n" % (it["title"] or it["url"], it["url"] or "#", it["pub"]))
            fh.write("\n")
    write_arrival_md(arr_all, today)
    with open(RUNJSON, "w", encoding="utf-8") as fh:
        json.dump({"run_utc": now, "sources": per_source,
                   "failures": [{"name": a, "http": b, "status": c, "parsed": d} for a, b, c, d in failures],
                   "new": len(new_items), "ledger_total": len(seen)}, fh, ensure_ascii=False, indent=1)
    print("\n新入库 %d 条 / 失败源 %d 个\n日报: %s" % (len(new_items), len(failures), rep))


if __name__ == "__main__":
    main()
