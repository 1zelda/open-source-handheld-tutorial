# -*- coding: utf-8 -*-
"""移植大作看板：三个源合成一张 PS5 / Switch 大作移植仓库表。
  1. awesome-decomp-games  data/games.json  2629 个项目，每天自动刷新，带 star/release/评分
  2. RecompStore           06-资讯监控/PS5移植商店/catalog.json  PS5 homebrew 商店目录
  3. SwitchPorts           _scratch/sp_rows.json（由 switchports_parse.py 解析 README 得到）
判"大作"用 IP 词表 + 星标双闸；目标平台从描述/仓库名认——games.json 的 platform 字段说的是**源**平台。
"""
import io, json, os, re, subprocess, sys, time, urllib.request

import net_proxy   # 代理口不写死（7890→7891 换过）；这行 11-04 补：之前只有 net_proxy.env() 调用、没有导入

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SCRATCH = os.path.join(ROOT, "_scratch")
# ADG 的落点从 _scratch 挪到 成品移植游戏库/清单来源/：这份 JSON 同时是 recomp_lib_register.py
# 的第五路输入（11-04 实测 2629 条 / 2317 仓）。留在 _scratch 就会被"临时垃圾"清掉，
# 上一版正是因为这个，看板天天刷新、登记表却一个包都没跟着下。
ADG_LOCAL = os.path.join(ROOT, "06-资讯监控", "成品移植游戏库", "清单来源", "awesome-decomp-games.json")
SP_LOCAL = os.path.join(SCRATCH, "sp_rows.json")
STORE_CAT = os.path.join(ROOT, "06-资讯监控", "PS5移植商店", "catalog.json")
STORE_INV = os.path.join(ROOT, "06-资讯监控", "PS5移植商店", "仓库底账.tsv")
OUT_DIR = os.path.join(ROOT, "06-资讯监控", "移植大作")
ADG_URL = "https://raw.githubusercontent.com/SubmitGame/awesome-decomp-games/main/data/games.json"
SP_URL = "https://raw.githubusercontent.com/robzilla10001/SwitchPorts/main/README.md"
FLOOR = "2026-09-01"   # 只看这一档之后还动过的项目

# 大作 IP 词表（全部小写比对）
AAA = [
    "zelda", "ocarina", "majora", "twilight princess", "wind waker", "windwaker", "skyward sword",
    "breath of the wild", "tears of the kingdom", "links awakening", "link's awakening",
    "echoes of wisdom", "minish cap", "paper mario", "super mario", "mario kart", "donkey kong",
    "diddy kong", "banjo", "metroid", "prime remastered", "zero mission", "super mario 64",
    "ghostship", "luigi's mansion", "sunshine", "eternal darkness", "star fox", "starfox",
    "f-zero", "animal crossing", "tomodachi", "kirby", "pikmin", "kid icarus", "bayonetta",
    "xenoblade", "astral chain", "smash bros", "super smash", "ssbu", "brawl", "smw",
    "mario maker", "maker 2", "3d world", "bowser", "odyssey", "strikers", "new super mario",
    "halo", "combat evolved", "ratchet", "clank", "sly cooper", "project cane", "jak and daxter",
    "gta", "grand theft", "san andreas", "vice city", "liberty city", "chinatown wars",
    "lost and damned", "red dead", "max payne", "ninja gaiden", "dead or alive", "shenmue",
    "yakuza", "lost odyssey", "phantasy star", "skies of arcadia", "valkyrie profile",
    "drakengard", "nier", "legend of dragoon", "suikoden", "mega man", "megaman", "rockman",
    "sonic", "jet set radio", "jsrf", "crazy taxi", "space channel", "house of the dead",
    "time crisis", "virtua fighter", "daytona", "outrun", "sega rally", "panzer", "initial d",
    "ace combat", "system 22", "model2", "model3", "namco", "god of war", "sons of sparta",
    "chains of olympus", "ascension", "shadow of the colossus", "metal gear", "revengeance",
    "metal slug", "silent hill", "resident evil", "code: veronica", "umbrella chronicles",
    "final fantasy", "fantasy tactics", "ffta", "dragon quest", "persona", "digital devil",
    "megami", "tales of", "star ocean", "dragon ball", "budokai", "tenkaichi", "dbz", "naruto",
    "one piece", "bleach", "jojo", "my hero academia", "demon slayer", "steven universe",
    "teen titans", "avengers", "spider-man", "spiderman", "spider man", "x-men", "xmen",
    "deadpool", "batman", "arkham", "lego", "star wars", "rogue squadron", "injustice",
    "darksiders", "dark souls", "devil may cry", "castlevania", "contra", "splinter cell",
    "ghost recon", "rainbow six", "just cause", "crackdown", "conker", "perfect dark",
    "goldeneye", "golden eye", "007", "james bond", "policenauts", "simpsons", "condemned",
    "doom", "quake", "half-life", "half life", "counter-strike", "counter strike", "left 4 dead",
    "portal", "diablo", "warcraft", "starcraft", "age of empires", "openaok", "civilization",
    "red alert", "freelancer", "minecraft", "terraria", "binding of isaac", "project zomboid",
    "borderlands", "assassins creed", "assassin's creed", "prince of persia", "sands of time",
    "far cry", "near chuckle", "battlefield", "call of duty", "black ops", "blackops",
    "modern warfare", "prototype", "shank", "burnout", "takedown", "need for speed",
    "midnight club", "skate", "rush 2", "asphalt", "split second", "real drift", "wip3",
    "wipeout", "wave race", "1080", "gran turismo", "forza", "gears of war", "spyro",
    "crash bandicoot", "tomb raider", "lara croft", "hitman", "payday", "watch dogs", "the crew",
    "dead island", "mass effect", "dragon age", "the sims", "wasteland", "fallout",
    "elder scrolls", "morrowind", "oblivion", "skyrim", "daggerfall", "new vegas",
    "the darkness", "cold fear", "crysis", "kingsglaive", "crisis core", "dirge of cerberus",
    "heavenly sword", "lost kingdom", "fable", "blue dragon", "red faction", "warriors",
    "guitar hero", "rock band", "beatmania", "just dance", "eye toy", "wii sports", "wii fit",
    "def jam", "tekken", "street fighter", "mortal kombat", "komplete edition", "shaolin monks",
    "soul calibur", "soulcalibur", "blazblue", "guilty gear", "king of fighters", "yugioh",
    "yu-gi-oh", "pokemon", "pokopia", "dusklight", "shipwright", "harkinian", "2ship",
    "paperboat", "bangai", "bangai-o", "katamari", "guardian heroes", "rampage", "nba street",
    "nba jam", "fifa", "wwe", "smackdown", "wrestlemania", "pro evolution", "winning eleven",
    "top spin", "marvel", "shinobi", "tenchu", "soul blade", "serious sam",
    "duke nukem", "shadow warrior", "deus ex", "system shock", "terminator", "robocop",
    "conan", "witcher", "gothic", "risen", "deadly premonition", "fire emblem", "hyrule",
    "total war", "company of heroes", "homeworld", "unreal", "bomberman",
    "crash team", "motogp", "mario",
    # 11-03 这轮 gh 现查捞到、词表原先没覆盖的：
    "command & conquer", "command and conquer", "generals", "darkwatch",
]
# gh 现查的关键词：宁可窄，只搜"大作移植体"，别把启动器/工具搜进来。
# 这十个词是 11-03 逐个试过返回量的（`ps5 port game`/`recompilation ps5`/中文"移植"都是 0 命中，别用）。
# `switch port` 返回 120 条顶到 limit，和 `nintendo switch port` 高度重合，不加。
GH_QUERIES = ["ps5-homebrew", "recomp ps5", "switch-port", "nintendo switch port",
              "switch recomp", "static recompilation",
              # 11-03 补：漏掉了 Swordpdf/PS5SX2（1620★，"A port of PCSX2 for PS5"）这种
              # 名字里没有 homebrew/recomp 的仓库，靠下面四个词兜回来。
              # 注意 GitHub 仓库搜索按整词匹配，"PS5SX2" 是一个词，所以 `port ps5`/`ps5 emulator`
              # 都搜不到它，必须原样写 ps5sx2；`pcsx2 ps5` 是 0 命中，别用。
              "port ps5", "ps5 emulator", "nx port", "ps5sx2"]

AAA = sorted({a.lower() for a in AAA if len(a) > 2})

# 商店层还要额外过这道闸：条目得是"移植体"，不是客户端/启动器/助手这类工具 App。
# （RecompStore 目录里两类都收，OpenNOW 云游戏客户端、Codex 助手这种会被 IP 词表误命中。）
PORT_RE = re.compile(r"port|recomp|decomp|remake|emulat|native .*(game|title)|disc|iso|rom", re.I)

# 索引 / 商店 / 启动器：★ 是 2026-11-03 用 `gh api repos/<r>` 现取的，不是抄来的。
AGGREGATORS = [
    ("SubmitGame/awesome-decomp-games", 2835,
     "总索引。本看板第 1 层的 `data/games.json` 就来自它，每天自动重算 star·链接存活·评分；只链源码，不链 ROM"),
    ("robzilla10001/SwitchPorts", 585,
     "Switch 移植总表，手维护、按**源**平台分节 435 行。本看板第 3 层"),
    ("darkxex/ProsperoStore", 484,
     "PS5 homebrew 商店（标题号 PPSA99000），ProsperoStore.net 的 PS5 原生壳"),
    ("elripalda/RecompStore", 330,
     "PS5 重编译体商店，本看板第 2 层读的 `catalog.json` 就是它的目录"),
    ("JVK3R/JobeesLair", 229,
     "PS5 homebrew 索引器 + 媒体框架，自称 content-neutral（只索引、不发内容）"),
    ("elripalda/RecompLauncher", 179,
     "给 PS5 上的重编译游戏做统一启动器"),
    ("TriwindBryan/fulton", 114,
     "PC / Mac 启动器，把 decomp·recomp·remake 的成品端口收进一个界面"),
    ("Lonviser/switch-ports", 0,
     "2026-10-21 新开的俄语 Switch 移植目录，每天自动更新，带搜索/筛选/收藏——星还少但更新勤"),
]


def tsv(path, table):
    """写 TSV：制表符/换行压成空格，双引号换单引号（下游按 TSV 逐列切）。"""
    out = ["\t".join(re.sub(r"[\t\r\n]+", " ", str(c)).replace('"', "'") for c in row)
           for row in table]
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    return len(out) - 1


def cell(s):
    return re.sub(r"\|", "/", re.sub(r"\s+", " ", str(s))).strip()


def load_adg():
    if not os.path.exists(ADG_LOCAL):
        return []
    with io.open(ADG_LOCAL, encoding="utf-8") as fh:
        return json.load(fh).get("games", [])


def load_store():
    if not os.path.exists(STORE_CAT):
        return []
    with io.open(STORE_CAT, encoding="utf-8") as fh:
        d = json.load(fh)
    rows = []
    for k in ("apps", "newerStoreApps", "v2Apps"):
        rows += d.get(k, [])
    return rows


def load_inv():
    """仓库底账：repo -> (star, pushed)"""
    inv = {}
    if os.path.exists(STORE_INV):
        with io.open(STORE_INV, encoding="utf-8-sig") as fh:
            for line in fh:
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3 and p[1].isdigit():
                    inv[p[0]] = (int(p[1]), p[2][:10])
    return inv


# 描述里光出现 "Switch" 不够——源平台是 Switch 的项目会在括号里写 "(Switch, v1.9.0)"，
# 那是**来源**不是目标。末尾的负向查再挡一种："Switch games ported to iOS"：Switch 是来源、iOS 才是目标。
SW_RE = re.compile(r"for (the )?(nintendo )?switch(?!\s+(?:games|titles|roms|dumps|cartridges))|"
                   r"on (the )?(nintendo )?switch(?!\s+(?:games|titles))|"
                   r"(nintendo )?switch port|port(ed)? to (the )?nintendo switch|"
                   r"native(ly)? (on )?(the )?(nintendo )?switch|switch-native|"
                   r"\bnro\b|for (the )?(nintendo )?switch 2|switch 2 (?:port|version|native)|"
                   r"\bswitch\b.{0,24}\b(?:vulkan|deko3d|tegra|hos)\b")
PS5_RE = re.compile(r"ps5|playstation 5|prospero|jailbroken (ps5|playstation)")

# 模拟器外壳 / 商店目录 / 启动器 / 工具包这一类：跟移植同属这波热度，但不是"某款大作的移植体"。
# 分两档判——正经移植仓库的长介绍里也爱写 "no emulator""Mesa driver" 这种技术套话，
# 所以 NAME 档（名字里就写着工具）谁都拦；DESC 档只看那一行短说明，且名字点到具体大作时让行。
NAME_TOOL_RE = re.compile(r"retroarch|rpcs3|dolphin|cemu|shadps|pcsx|emulator|\bcatalog(?:ue)?\b|"
                          r"launcher|\bstore\b|toolbox|\bsdk\b|\bdriver\b|\bmesa\b|benchmark|"
                          r"captive portal|overlay|\bhub\b|\bguide\b|agent skill", re.I)
DESC_TOOL_RE = re.compile(r"retroarch|rpcs3|dolphin|cemu|shadps|pcsx|\bemu\b|emulator|"
                          r"\bhomebrew\b.{0,26}\b(?:app|apps|catalog(?:ue)?|guide|scene|hub|store)\b|"
                          r"\bhub\b.{0,26}\bhomebrew\b|agent skill|toolbox|mod menu|"
                          r"\bsdk\b|captive portal|benchmark|overlay|\bmenu system\b|\bengine\b|"
                          r"web browser|webgpu|\blauncher\b|\bstore\b", re.I)
# 先把 "no emulation / 不用模拟器" 这类否定说法摘掉，否则正经重编译仓库会被当成模拟器。
NEG_RE = re.compile(r"(?:no|not|without|zero|none|免|不用|无需)\s*"
                    r"[A-Za-z一-鿿]{0,14}(?:emu\w*|模拟器)", re.I)


def hits(text):
    """命中的大作词，最多记 3 个——台账留这一列，日后能一眼看出某行凭什么进来的。
       数字词（007 / 1080）要卡住前后不是数字，否则 "2007 年的子弹地狱" 也算命中。"""
    t = (text or "").lower()
    out = []
    for a in AAA:
        if a.isdigit():
            if not re.search(r"(?<![0-9a-z])%s(?![0-9a-z])" % re.escape(a), t):
                continue
        elif a not in t:
            continue
        out.append(a)
        if len(out) >= 3:
            break
    return ",".join(out)


def big(text):
    return bool(hits(text))


def toolish(name, desc=""):
    """NAME 档在名字和那一行短说明上都算（EmuStore / MG-Menu SDK 这种一眼是工具）；
       DESC 档只算说明，并且名字先点到具体大作时给让行（Dusklight 那种借 Aurora 跑的）。"""
    n = NEG_RE.sub(" ", name or "")
    d = NEG_RE.sub(" ", desc or "")
    if NAME_TOOL_RE.search(n) or NAME_TOOL_RE.search(n + " " + d):
        return True
    if big(name):
        return False
    return bool(DESC_TOOL_RE.search(d))


def load_wave():
    """gh 现查缓存：repo<TAB>stars<TAB>created<TAB>pushed<TAB>description。缺文件就跳过这一层。"""
    path = os.path.join(SCRATCH, "gh_wave.tsv")
    rows = []
    if not os.path.exists(path):
        return rows
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 5:
                rows.append(p)
    return rows


def wave(queries, created, limit=60):
    """`gh search repos` 抓最近新开的仓库，缓存成 gh_wave.tsv（多个 query 取并集）。"""
    gh = os.environ.get("GH", r"C:/Users/Administrator/.workbuddy/binaries/gh/bin/gh.exe")
    if not os.path.exists(gh):
        gh = "gh"
    env = net_proxy.env()          # 代理口不写死（7890→7891 换过），见 net_proxy.py
    acc = {}
    for q in queries:
        cmd = [gh, "search", "repos", q, "--created", ">" + created, "--sort", "stars",
               "--order", "desc", "--limit", str(limit),
               "--json", "fullName,stargazersCount,createdAt,pushedAt,description"]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", env=env, timeout=180).stdout
        except Exception as e:
            print(("gh fail %s: %s" % (q, e)).encode("ascii", "backslashreplace").decode())
            continue
        try:
            data = json.loads(out or "[]")
        except ValueError:
            print(("gh unparseable for %s (%d B)" % (q, len(out or "")))
                  .encode("ascii", "backslashreplace").decode())
            continue
        for r in data:
            acc[r["fullName"]] = (r["fullName"], r.get("stargazersCount") or 0,
                                  (r.get("createdAt") or "")[:10], (r.get("pushedAt") or "")[:10],
                                  re.sub(r"[\t\r\n]+", " ", r.get("description") or ""))
    path = os.path.join(SCRATCH, "gh_wave.tsv")
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        for v in sorted(acc.values(), key=lambda x: -x[1]):
            fh.write("\t".join(str(c) for c in v) + "\n")
    print("gh_wave rows=%d" % len(acc))
    return list(acc.values())


def detect_target(blob):
    """目标平台只看描述/标题/仓库名；games.json 的 platform 字段是源平台，不参与判断。"""
    t = blob.lower()
    slug = t.rstrip("/").split("/")[-1].lower()
    out = []
    if PS5_RE.search(t):
        out.append("PS5")
    if SW_RE.search(t) or re.search(r"[-_]nx\d?\b", slug):
        out.append("Switch")
    for pat, lab in ((r"\bpc\b|windows|linux|steam", "PC"), (r"android", "Android"),
                     (r"ios|iphone|ipad|macos|apple silicon|\bmetal\b", "macOS/iOS"),
                     (r"\bvita\b|ps vita", "PSV"), (r"steam deck|\bdeck\b", "SteamDeck"),
                     (r"browser|webassembly|\bwasm\b", "浏览器")):
        if re.search(pat, t):
            out.append(lab)
    return out


def build():
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    adg, store, inv = load_adg(), load_store(), load_inv()
    rows = {}

    def add(repo, layer, game, src_plat, target, star, ver, when, own, url, origin, note="",
            thread="", ip=""):
        key = (repo or url or game).lower().strip().rstrip("/")
        cur = rows.get(key)
        if cur:
            if layer not in cur["layer"].split("+"):
                cur["layer"] += "+" + layer
            if origin not in cur["origin"].split("+"):
                cur["origin"] += "+" + origin
            cur["star"] = max(cur["star"] or 0, star or 0)
            cur["own"] = bool(cur["own"] or own)
            cur["when"] = max(cur["when"] or "", when or "")
            cur["ver"] = cur["ver"] or (ver or "")
            cur["thread"] = cur["thread"] or thread
            cur["note"] = cur["note"] or (note or "")
            cur["ip"] = cur["ip"] or ip
            return
        rows[key] = dict(repo=repo or game, layer=layer, game=game, src=src_plat or "",
                         target=target, star=star, ver=ver or "", when=when or "",
                         own=bool(own), url=url or "", origin=origin, note=note or "",
                         thread=thread or "", ip=ip)

    # 1) awesome-decomp-games
    for e in adg:
        blob = " ".join(str(e.get(k) or "") for k in
                        ("title", "description", "note", "homepage", "url", "repo"))
        tgt = detect_target(blob)
        if not {"PS5", "Switch"} & set(tgt) or e.get("inactive"):
            continue
        when = max((e.get("last_commit") or "")[:10], (e.get("release_date") or "")[:10])
        st = e.get("stars") or 0
        if when < FLOOR:
            continue
        # 模拟器外壳/目录这类不是"某款大作的移植体"；判据只看标题+仓库名，别拿长介绍里的套话
        tool = toolish("%s %s" % (e.get("title") or "", e.get("repo") or ""),
                       e.get("description") or "")
        if tool:
            if st < 40:
                continue
        elif not (big(blob) or st >= 150):
            continue
        na = e.get("needs_assets")
        if na is None:
            na = bool(re.search(r"no game data|your own|needs your|requires the game|"
                                r"bring your own|own copy|game files", blob, re.I))
        add(e.get("repo"), "周边" if tool else "+".join([x for x in tgt if x in ("PS5", "Switch")]),
            e.get("title"), e.get("platform"), "+".join(tgt), st,
            e.get("release"), when, na, e.get("url"), "adg", e.get("type"), ip=hits(blob))

    # 1b) 同一批数据里反方向的这波：源是 Switch / PS5 卡带，目标端是 PC·手机·浏览器
    for e in adg:
        plat = (e.get("platform") or "").lower()
        is_switch_src = "switch" in plat
        is_ps5_src = bool(re.search(r"ps5|playstation 5", plat))
        if not (is_switch_src or is_ps5_src) or e.get("inactive") or e.get("type") == "tool":
            continue
        blob = " ".join(str(e.get(k) or "") for k in
                        ("title", "description", "note", "homepage", "url", "repo"))
        if {"PS5", "Switch"} & set(detect_target(blob)):
            continue                      # 已经是第 2/3 节了，不重复收
        if toolish("%s %s" % (e.get("title") or "", e.get("repo") or ""),
                   e.get("description") or ""):
            continue                      # 工具/外壳的反向移植不算"大作"，第 4 节只放游戏
        when = max((e.get("last_commit") or "")[:10], (e.get("release_date") or "")[:10])
        st = e.get("stars") or 0
        if when < FLOOR or not (big(blob) or st >= 150):
            continue
        tgt = [x for x in detect_target(blob) if x not in ("PS5", "Switch")]
        layer = ("Switch源" if is_switch_src else "PS5源")
        add(e.get("repo"), layer, e.get("title"), e.get("platform"), "+".join(tgt or ["?"]),
            st, e.get("release"), when, e.get("needs_assets"), e.get("url"), "adg",
            "%s｜源=%s" % (e.get("type"), e.get("platform")), ip=hits(blob))

    # 1c) gh 现查：还没进任何索引的新仓库（只收目标端是 PS5/Switch 的移植体）。
    #     星数门槛比另外几层低——这层专门捞"刚开仓、还没来得及攒星"的，靠 IP 词表兜精度；
    #     模拟器外壳、商店目录、入门指南这类同属这波热度，但不是某款大作的移植体，改投"周边"层。
    for repo, st, created, pushed, desc in load_wave():
        blob = repo + " " + desc
        if not PORT_RE.search(blob):
            continue
        tgt = [x for x in detect_target(blob) if x in ("PS5", "Switch")]
        if not tgt or max(created, pushed) < FLOOR:
            continue
        star = int(st or 0)
        if toolish(repo, desc):
            if star >= 40:
                add(repo, "周边", repo.split("/")[-1], "", "+".join(tgt), star, "", pushed,
                    False, "https://github.com/" + repo, "gh",
                    "新开 %s｜%s" % (created, desc[:70]), ip=hits(blob))
            continue
        if not (big(blob) or star >= 50):
            continue
        m = re.search(r"(xbox 360|xbox one|original xbox|xbox|n64|gamecube|wii u|wii|ps2|ps3|ps4|psp|"
                      r"dreamcast|genesis|snes|gba|nds|switch)", blob, re.I)
        own = bool(re.search(r"your own|no game data|bring your own|disc|iso|rom|dump|game files",
                             blob, re.I))
        add(repo, "+".join(tgt), repo.split("/")[-1], m.group(1).title() if m else "",
            "+".join(detect_target(blob)), star, "", pushed, own,
            "https://github.com/" + repo, "gh", "新开 %s｜%s" % (created, desc[:70]),
            ip=hits(blob))

    # 2) RecompStore（整站都是 PS5 目标，目录里的重编译体就是"大作"候选）
    for e in store:
        nm, needs = e.get("name") or "", e.get("needs") or ""
        src = e.get("source") or {}
        repo = src.get("repo") or ""
        text = " ".join([nm, needs, e.get("blurb") or "", e.get("description") or ""])
        if not (big(nm) or big(needs)) or not PORT_RE.search(text):
            continue
        star, pushed = inv.get(repo, (0, ""))
        m = re.search(r"(Xbox 360|Xbox One|Xbox|N64|GameCube|Wii U|Wii|PS2|PS3|PS4|PSP|Dreamcast|"
                      r"Genesis|SNES|GBA|NDS)", needs, re.I)
        own = bool(re.search(r"iso|disc|rom|dump|own|your|game files|title update|wad|\.pak|pk3",
                             needs, re.I))
        add(repo, "周边" if toolish("%s %s" % (nm, repo)) else "PS5", nm,
            m.group(1) if m else "", "PS5", star, e.get("version"), pushed, own,
            "https://github.com/" + repo if repo else "https://recompstore.com/", "store",
            " ".join(x for x in ((e.get("kind") or ""), (e.get("size") or "")) if x),
            ip=hits(text))

    # 3) SwitchPorts 总表（目标平台=Switch，行里带更新日期）
    if os.path.exists(SP_LOCAL):
        with io.open(SP_LOCAL, encoding="utf-8") as fh:
            sp = json.load(fh)
        for sec, sysc, title, ver, upd, label, url, temp in sp:
            if not upd.startswith(("2026-09", "2026-10", "2026-11")):
                continue
            if not big((title or "") + " " + (label or "")):
                continue
            if sec.lower().startswith("emulator") or toolish("%s %s" % (title, label)):
                continue
            repo = label if "/" in label else (url or "").replace("https://github.com/", "")
            if not repo:
                continue
            add(repo, "Switch", title or repo, sysc, "Switch", inv.get(repo, (0, ""))[0],
                ver, upd, True, url, "sp", "", temp, ip=hits("%s %s" % (title, label)))

    return rows, now, len(adg), len(store)


def write_out(rows, now, n_adg, n_store):
    os.makedirs(OUT_DIR, exist_ok=True)
    items = sorted(rows.values(), key=lambda r: (-(r["star"] or 0), r["game"].lower()))
    hdr = ["layer", "game", "source_platform", "targets", "repo", "stars", "version",
           "last_activity", "needs_own_copy", "url", "origin", "note", "thread", "ip_hits"]
    table = [hdr] + [[r["layer"], r["game"], r["src"], r["target"], r["repo"], r["star"] or "",
                      r["ver"], r["when"], "1" if r["own"] else "0", r["url"], r["origin"],
                      r["note"], r["thread"], r.get("ip", "")] for r in items]
    n = tsv(os.path.join(OUT_DIR, "移植大作台账.tsv"), table)

    def rcell(r):
        return "[%s](%s)" % (cell(r["repo"]), r["url"]) if r["url"].startswith("http") else cell(r["repo"])

    def cls(layer):
        toks = layer.split("+")
        if "周边" in toks:
            return "extra"
        if any(t in ("PS5", "Switch") for t in toks):
            if "PS5" in toks and "Switch" in toks:
                return "both"
            return "ps5" if "PS5" in toks else "sw"
        return "rev"

    groups = {"both": [], "ps5": [], "sw": [], "rev": [], "extra": []}
    for r in items:
        groups[cls(r["layer"])].append(r)
    both, ps5, sw, rev, extra = (groups["both"], groups["ps5"], groups["sw"],
                                 groups["rev"], groups["extra"])
    layer_count = {}
    for r in items:
        layer_count[r["layer"]] = layer_count.get(r["layer"], 0) + 1

    L = ["# 最近冒出的移植大作仓库（PS5 / Switch）", "",
         "> 生成 %s ｜ 台账 `移植大作台账.tsv`（%d 行）｜ 生成脚本 `_工具脚本/major_ports_board.py`" % (now, n),
         "",
         "> 四个源：`awesome-decomp-games`（%d 个项目 / 每天自动刷新 / 带 star·版本·评分）、"
         "`RecompStore` 目录（%d 条 PS5 homebrew 成品）、`SwitchPorts` 总表（435 行）、"
         "`gh search repos` 现查（还没进索引的新仓库，缓存 `_scratch/gh_wave.tsv`）。" % (n_adg, n_store),
         "> 收进来要同时满足三条：命中 PS5/Switch 这一侧、命中 3A/大厂 IP 词表（或攒下足够多的星："
         "索引层 ★≥150、gh 现查层 ★≥50、周边层 ★≥40）、%s 之后还动过。"
         "同一仓库在多个源出现会合并成一行，`layer` 用 `+` 连；`ip_hits` 记的是它凭哪个词进的表。" % FLOOR,
         "> 分五个方向看：**跑到 PS5 上的**、**跑到 Switch 上的**、**两端都有人做的**、"
         "**反过来把 Switch/PS5 卡带上的大作移植到 PC·手机·浏览器的**（就是最近涨星最猛的那波）、"
         "以及**周边**（模拟器外壳·商店目录·入门指南，热度同源但不是某款大作的移植体，单独放一节别混进大作表）。",
         "> 「要自备盘」= 仓库二进制里不含那款游戏的素材，得拿自己正版盘/Dump 喂进去才跑得起来。",
         ""]
    L.append("**条数**：PS5 上跑 %d ／ Switch 上跑 %d ／ 两端都有 %d ／ Switch·PS5 卡带当源的反向移植 %d "
             "／ 周边 %d ／ 去重后合计 **%d**"
             % (len(ps5), len(sw), len(both), len(rev), len(extra), len(items)))
    L.append("")
    L.append("原始 `layer` 分布：" + " ／ ".join("`%s` %d" % (k, v) for k, v in sorted(layer_count.items())))
    L.append("")

    def tbl(rs, cols):
        L.append("| " + " | ".join(c[0] for c in cols) + " |")
        L.append("|" + "|".join(["---"] * len(cols)) + "|")
        for r in rs:
            L.append("| " + " | ".join(cell(fn(r)) for _, fn in cols) + " |")
        L.append("")

    L.append("## 1. PS5 上跑的移植大作（%d）" % len(ps5))
    L.append("")
    L.append("按 ★ 降序。★ 是 GitHub 实测值；RecompStore 里新开的仓库多数还没攒下星。")
    L.append("")
    tbl(ps5, [("游戏", lambda r: r["game"]), ("原平台", lambda r: r["src"]), ("仓库", rcell),
              ("★", lambda r: r["star"] or "-"), ("版本", lambda r: r["ver"]),
              ("最近", lambda r: r["when"]), ("要自备盘", lambda r: "是" if r["own"] else ""),
              ("备注", lambda r: r["note"]), ("来源", lambda r: r["origin"])])

    L.append("## 2. Switch 上跑的移植大作（%d）" % len(sw))
    L.append("")
    L.append("`原帖` 是 GBAtemp 上对应的发布帖（SwitchPorts 表里带的），要查作者原话或更新日志就从这里进。")
    L.append("")
    tbl(sw, [("游戏", lambda r: r["game"]), ("原平台", lambda r: r["src"]), ("仓库", rcell),
             ("★", lambda r: r["star"] or "-"), ("版本", lambda r: r["ver"]),
             ("最近", lambda r: r["when"]), ("类型", lambda r: r["note"]),
             ("原帖", lambda r: "[GBAtemp](%s)" % r["thread"] if r["thread"].startswith("http") else ""),
             ("来源", lambda r: r["origin"])])

    if both:
        L.append("## 3. 同一款游戏两端都有人做（%d）" % len(both))
        L.append("")
        L.append("PS5 和 Switch 各有一套仓库，通常是同一个 PC 母项目往下游分叉——做节目时这两端可以并排讲。")
        L.append("")
        tbl(both, [("游戏", lambda r: r["game"]), ("原平台", lambda r: r["src"]),
                   ("仓库", rcell), ("两端", lambda r: r["layer"]), ("★", lambda r: r["star"] or "-"),
                   ("目标端", lambda r: r["target"]), ("版本", lambda r: r["ver"]),
                   ("最近", lambda r: r["when"]), ("来源", lambda r: r["origin"])])

    L.append("## 4. 反向这波：Switch / PS5 卡带当源，移植到 PC·手机·浏览器（%d）" % len(rev))
    L.append("")
    L.append("这波才是最近涨星最狠的（TotK→PC 开仓一周 4000+★）。"
             "读法：`原平台` 是那款游戏**出自**哪台机器，`目标端` 是这份移植跑在哪。")
    L.append("")
    tbl(rev, [("游戏", lambda r: r["game"]), ("原平台", lambda r: r["src"]), ("仓库", rcell),
              ("★", lambda r: r["star"] or "-"), ("目标端", lambda r: r["target"]),
              ("版本", lambda r: r["ver"]), ("最近", lambda r: r["when"]),
              ("要自备盘", lambda r: "是" if r["own"] else ""),
              ("备注", lambda r: r["note"]), ("来源", lambda r: r["origin"])])

    L.append("---")
    L.append("")
    L.append("## 5. 周边：模拟器外壳、商店目录、入门指南（%d）" % len(extra))
    L.append("")
    L.append("这波热度里跟移植一起涨起来的，但不是「某款大作的移植体」——"
             "做节目时当背景板讲，别跟上面的大作表混着报。")
    L.append("")
    tbl(extra, [("名称", lambda r: r["game"]), ("仓库", rcell), ("★", lambda r: r["star"] or "-"),
                ("跑在", lambda r: r["target"]), ("最近", lambda r: r["when"]),
                ("说明", lambda r: r["note"]), ("来源", lambda r: r["origin"])])

    L.append("---")
    L.append("")
    L.append("## 6. 盯源：这四份数据怎么更新")
    L.append("")
    L.append("| 源 | 是什么 | 怎么拿 |")
    L.append("|---|---|---|")
    L.append("| awesome-decomp-games | 2629 个项目、2235 款游戏，每天自动重算 star / 链接存活 / 评分；"
             "只链源码与项目页，不链 ROM 和素材 | `data/games.json`（约 4 MB），`--refresh` 会拉 |")
    L.append("| RecompStore | PS5 homebrew 商店目录，重编译体成品包的索引 | "
             "`https://recompstore.com/catalog.json`，`ps5_catalog_diff.py` 做增量 |")
    L.append("| SwitchPorts | robzilla10001 手维护的 Switch 移植总表，435 行、按**源**平台分节 | "
             "README，`switchports_parse.py` 解析 |")
    L.append("| gh search repos | 还没被上面三个索引收进去的新仓库 | "
             "`_工具脚本/major_ports_board.py --gh`，缓存 `_scratch/gh_wave.tsv` |")
    L.append("")
    L.append("## 7. 顺带值得盯的索引页、商店与启动器（★ 为 2026-11-03 `gh api` 现取）")
    L.append("")
    L.append("| 仓库 | ★ | 是什么 |")
    L.append("|---|---|---|")
    for repo, star, what in AGGREGATORS:
        L.append("| [%s](https://github.com/%s) | %d | %s |" % (repo, repo, star, what))
    L.append("")
    L.append("> 另外两个常被当成索引转的仓库其实不是索引：`Shagg88/COGBox`（351★）是《战争机器》Xbox 360→PC "
             "的静态重编译本体，`i12bp8/decomp.wtf`（547★）是让 AI 智能体把你自己的游戏反编译成同字节 C 的工具链。")
    L.append("> 踩坑提醒：`Carter54git/Greates-Games-Decompilations-Lis`（曾 431★）本轮复查已经 404，"
             "仓库被删或改名了，别把它当索引引用。")
    L.append("")
    L.append("重跑：`C:\\Windows\\py.exe -3 _工具脚本\\major_ports_board.py --refresh`"
             "（`--refresh` 拉三份缓存数据，`--gh` 现查新仓库）")
    L.append("")

    path = os.path.join(OUT_DIR, "移植大作仓库.md")
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(L))
    print(("rows=%d ps5=%d switch=%d both=%d rev=%d extra=%d ledger=%d md_bytes=%d" %
           (len(items), len(ps5), len(sw), len(both), len(rev), len(extra), n,
            os.path.getsize(path)))
          .encode("ascii", "backslashreplace").decode())
    print(("wrote " + path).encode("ascii", "backslashreplace").decode())


def refresh():
    import shutil
    # urllib 走的是进程里那个 HTTPS_PROXY，而本机环境变量里挂的还是已经死掉的 7890：
    # 不显式装 opener 就会 "refresh 失败"，而 net_proxy.env() 只管子进程、管不到本进程。
    px = net_proxy.proxy_url()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": px, "https": px} if px else {}))
    for url, dst in ((ADG_URL, ADG_LOCAL), (SP_URL, os.path.join(SCRATCH, "sp_raw.md"))):
        req = urllib.request.Request(url, headers={"User-Agent": "kb-fetch"})
        with opener.open(req, timeout=180) as r:
            raw = r.read()
        with open(dst, "wb") as fh:
            fh.write(raw)
        print(("refreshed %s %d B" % (os.path.basename(dst), len(raw)))
              .encode("ascii", "backslashreplace").decode())
    shutil.copyfile(os.path.join(SCRATCH, "sp_raw.md"), os.path.join(SCRATCH, "sp.md"))
    subprocess.run([sys.executable, os.path.join(HERE, "switchports_parse.py")], check=False)


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh()
    if "--gh" in sys.argv:
        wave(GH_QUERIES, "2026-09-01", limit=120)
    write_out(*build())
