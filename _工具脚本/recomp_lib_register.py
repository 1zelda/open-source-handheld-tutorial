# -*- coding: utf-8 -*-
r"""成品移植游戏库：登记表生成器。

这一档收的是"成品移植体"——静态重编译（static recompilation）那一波：把游戏可执行文件
反编译/重编译成原生 PC/掌机程序的仓库，以及它们的目录/商店（RecompHub、RecompStore、
Decomp Buddy、PortMaster 一族）。来源到 11-05 已经是七路并集：
  1. GitHub topic:static-recompilation 搜索（>=30 星，_recomp_scene.tsv）
  2. RecompHub 的 catalog.json 里点名的仓库（_cat_repos.txt）
  3. EXTRA 里手点名的目录/商店（PortMaster 一族不在上面两路里，因为它们不打这个 topic）
  4. recompiled-games 总索引（82 条）
  5. awesome-decomp-games data/games.json（2629 款 / 2317 仓）
  6. recomphub.com 种子（227 条）
  7. 11-05 新接：recomp-games(6544) + recomp.fyi(3050) + ProsperoStore(177) + RecompStore 在线目录(171)

     第 5/7 里的"批量库"（ADG、recomp-games、recomp.fyi）只登记不 clone：policy 钉成 meta，
     成品包照走 releases 资产。商店那两路（Prospero/RecompStore）按真实大小定 policy，
     因为它们是 PS5 上真能装的东西，下架风险最高。

跑之前先想清楚两件事，不然会白干：
  - 隔壁 PS5移植商店/源码、Switch2模拟器/源码 已经有的仓库，这里一律 enable=0 并注明，
    免得同一份源码下两遍（上一版判重写错，全 196 行都成了"要下"）。
  - 仓库大小差异极大（PortMaster-New 的 .git 是 37GB），不能一刀切连历史全 clone。
    所以按元数据给每行定 policy：full / blobless / meta，抓取脚本只认这一列。

    py -3 _工具脚本/recomp_lib_register.py            # 重新生成登记表（联网补元数据）
    py -3 _工具脚本/recomp_lib_register.py --offline   # 不联网，用缓存的元数据重算
"""
import csv
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # F:\开源掌机教程
ROOT = HERE
AREA = os.path.join(ROOT, "06-资讯监控", "成品移植游戏库")
# 三路来源的原始清单就存在本档 清单来源/ 里：这三份是登记表的可复现输入，
# 不是临时垃圾，别跟着 _工具脚本 一起清。
SCRATCH = os.path.join(AREA, "清单来源")
SCENE = os.path.join(SCRATCH, "topic-static-recompilation.tsv")
RELEASES = os.path.join(SCRATCH, "release资产统计.tsv")
CAT = os.path.join(SCRATCH, "RecompHub目录仓库.txt")
CATJSON = os.path.join(AREA, "RecompHub目录.json")
# 第三方维护的"移植游戏总索引"（331 条，含 Xbox360/PS2/N64 等 RecompHub 没收的平台）。
# 11-04 用户指出"人家的库都是几百几千个游戏"，我的 82 条目录根本不算库——这份索引里
# 245 个仓我原先压根没登记过，所以把它当第四路输入接进来，原文存盘可复现。
INDEX = os.path.join(SCRATCH, "recompiled-games.json")
# SubmitGame/awesome-decomp-games 的 data/games.json（2860★，自动生成、每天刷新）：
# 11-04 实测 2629 条 / 2235 款游戏，其中 static-recomp 849 / decompilation 712 /
# source-port 283 / engine-remake 253 / browser-port 54 / disassembly 110 / tool 11。
# 这才是用户说的"几百几千个游戏的库"。它 11-03 就抓到过盘（_scratch/adg_games.json），
# 但只喂了看板、没喂登记表——所以库里 2000 多个仓我一个包都没下。这次接进来。
ADG = os.path.join(SCRATCH, "awesome-decomp-games.json")
# recomphub.com（cefege 那个"可搜索的重编译/原生移植数据库"站）的种子数据：227 条。
# 和 ADG 重合 190 条，另有 37 个仓不在前几路里（11-04 对着登记表实测的差集）。
# 它的字段跟别的路不同轴：runs_on（linux/windows/mac/android）+ playable + kind。
SEED = os.path.join(SCRATCH, "recomphub-seed-curated-ports.json")
# disassembly 只有反汇编数据、没有可玩移植体，tool 是工具，这两档不进"游戏库"
ADG_TYPES = {"static-recomp", "decompilation", "source-port", "engine-remake", "browser-port"}
# ---- 11-05 第四次扩容：研究代理找到的四个聚合目录 + 一个"只能登记条数"的库 ----
# 上一版我登记的 2462 个仓被用户当场驳回："人家的库都是几百几千个游戏的。"
# 这四份就是那种库的本体，原文全部存盘（下面每个 loader 都会点名打印丢掉的条目）：
#   recomp-games  6544 条（葡语站，type=recomp/decomp/port/reimpl，status=ativo/parado/lento），
#                 其中 6396 条给的是 github 仓，148 条压根没有仓、另有 40 条指向 gitlab/sourceforge。
#   recomp.fyi    3050 条（repo 是完整 URL；3049 个 github + 1 个 gitlab），带 status/builds/license。
#   ProsperoStore 177 个 PS5 侧载 app（source_repo + artifact_url + sha256 + titleid，包是钉死的）。
#   RecompStore   在线目录 171 个 app（apps18 + newerStoreApps51 + v2Apps102）——比 11-04 缓存的
#                 那份 162 条更新，而且 repo 藏在 source['repo'] 里，不是顶层字段。
RGCAT = os.path.join(SCRATCH, "recomp-games-projects.json")
FYI = os.path.join(SCRATCH, "recomp-fyi-projects.json")
PROS = os.path.join(SCRATCH, "prosperostore-catalog-v1.json")
RSTORE = os.path.join(SCRATCH, "recompstore-catalog-live.json")
# unbaked.games：6517 款，但**没有内联 repo**——每款只有一个 https://unbaked.games/api/games/<slug>.json。
# 要拿到仓名就是 6517 次请求，所以这一路只登记条数和"新增周报"（additions.json），
# 不假装它已经进了库。它是用来跟下架赛跑时盯增量的，不是仓名来源。
UNBAKED = os.path.join(SCRATCH, "unbaked-games.json")
UNBAKED_ADD = os.path.join(SCRATCH, "unbaked-additions.json")
REG = os.path.join(AREA, "仓库登记表.tsv")
META = os.path.join(AREA, "仓库元数据.tsv")

# 元数据阈值：超过这个 .git 体积的，连历史 clone 不划算（详见 README 第 3 节）
FULL_MAX_MB = 800
BLOBLESS_MAX_MB = 5120

# 手点名的目录/商店：不打 static-recompilation topic，但就是"游戏库"本身。
# 这一列只准写 GitHub 上真查得到的仓库——上一版我凭印象写了 4 个名字
# （DanielNigro/PortMaster-RGUI、leil-hagedorn/Portmaster-Tools、PortsMaster/PortMaster-TS、
# uup-dron/rom-map），API 全 404，等于往台账里掺假条目。现在改成先列组织真实仓库再点名。
EXTRA = [
    ("PortsMaster/PortMaster-New", "目录/商店", "掌机端口大集合：Switch/PS1/N64/GBA 等 500+ 游戏的启动脚本"),
    ("PortsMaster/PortMaster-GUI", "目录/商店", "PortMaster 的图形前端（在设备上选端口装）"),
    ("PortsMaster/PortMaster-Source", "目录/商店", "PortMaster 运行源码包（ports 的 .sh 脚本本体）"),
    ("PortsMaster/PortMaster-Releases", "目录/商店", "PortMaster 发布产物仓"),
    ("PortsMaster/gptokeyb", "目录/商店", "端口手柄映射层，PortMaster 依赖"),
    ("PortsMaster/gmloader-next", "目录/商店", "BIOS/CD 游戏加载器（gmloader 续作）"),
    ("christianhaitian/PortMaster", "目录/商店", "PortMaster 初代（Ark/Wayland 版，.git 8GB）"),
    ("get-starboard/starboard", "目录/商店", "PortMaster 的图形前端 Starboard（API 报 .git 0MB，仓库内容存疑）"),
    ("ben16w/minui-portmaster", "目录/商店", "MinUI + PortMaster 整合包"),
]

HDR = ["repo", "enable", "tier", "policy", "size_mb", "stars", "note"]
META_HDR = ["repo", "stars", "size_mb", "license", "default_branch", "pushed_at",
            "archived", "disabled", "open_issues", "probed_at"]


def gh_bin():
    import shutil
    return shutil.which("gh") or os.path.expanduser(r"~\.workbuddy\gh-cli\bin\gh.exe")


def _env():
    """代理挂了要能降级，而且口不能写死（7890→7891 换过，见 net_proxy.py）：
    探不到活口就把代理变量清空直连，别把整批抓取卡死。"""
    import net_proxy
    return net_proxy.env()


def api(repo):
    r = subprocess.run([gh_bin(), "api", "repos/" + repo], capture_output=True, env=_env(), timeout=90)
    if r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        return {}


def read_tsv(path, cols):
    out = {}
    if not os.path.exists(path):
        return out
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) < len(cols):
                p += [""] * (len(cols) - len(p))
            out[p[0]] = dict(zip(cols, p))
    return out


def load_meta_cache():
    """缓存键统一成小写仓名：这一版有六路来源，同一个仓在 ADG 里是小写、
    在 recomp-games/recomp.fyi 里是原样大小写。键不归一，重跑就是拿已探过的仓再烧一次 API，
    而且 save_meta 按 order 里的名字找缓存会找不到——元数据表当场掉一批行。"""
    cache = {}
    if os.path.exists(META):
        with io.open(META, encoding="utf-8") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                cache[r["repo"].lower()] = r
    return cache


def save_meta(cache, order):
    """每探完一批就落盘：API 配额和 clone 时间都烧不起，中途崩了不能白跑。
    order 里的名字按小写找缓存，写出的 repo 列用 order 的名字（登记表和元数据表仓名对得上）。"""
    os.makedirs(AREA, exist_ok=True)
    tmp = META + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=META_HDR, delimiter="\t")
        w.writeheader()
        written = set()
        for repo in order:
            key = repo.lower()
            if key in cache and key not in written:
                written.add(key)
                w.writerow(dict(cache[key], repo=repo))
        # order 之外但缓存里有的（上一版登记过、这次来源变了不在了）不能丢：
        # 丢了就等于把探过的 size/license 抹掉，下次重跑再烧一遍 API。
        for key, v in cache.items():
            if key not in written:
                w.writerow(v)
    os.replace(tmp, META)


def flat_text(v):
    """RecompHub 目录里 description/hint 是 {"en": "..."} 这种多语言 dict，不是字符串。"""
    if isinstance(v, dict):
        for k in ("en", "zh", "ja"):
            if isinstance(v.get(k), str):
                return v[k]
        for x in v.values():
            if isinstance(x, str):
                return x
        return ""
    return v or ""


def held_elsewhere():
    """隔壁两档已经 clone 在盘上的仓库 -> owner/repo 集合 + 它在哪个档。"""
    held = {}
    for area, label in (("PS5移植商店", "PS5移植商店"), ("Switch2模拟器", "Switch2模拟器")):
        src = os.path.join(ROOT, "06-资讯监控", area, "源码")
        if not os.path.isdir(src):
            continue
        for d in os.listdir(src):
            if "__" not in d:
                continue
            owner, repo = d.split("__", 1)
            held[owner + "/" + repo] = label
    return held


def load_index(path):
    """总索引 JSON -> {owner/repo: 条目}。url 不是 github 仓库页的（外链官网/gitlab/发行版页面）
    当场点名打印，不静默丢——上一版我凭印象手点 EXTRA 掺了 4 个 404 名字，教训在这。"""
    out, skipped = {}, []
    with io.open(path, encoding="utf-8") as fh:
        items = json.load(fh)
    for it in items:
        url = (it.get("url") or "").strip()
        m = re.match(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", url)
        if not m:
            skipped.append((it.get("game") or it.get("id") or "?", url))
            continue
        repo = "%s/%s" % (m.group(1), m.group(2).rstrip("/"))
        if repo.endswith(".git"):
            repo = repo[:-4]
        out.setdefault(repo.lower(), it)
    print("索引 %s：%d 条 -> %d 个仓库，%d 条不是 github 仓库页"
          % (os.path.basename(path), len(items), len(out), len(skipped)))
    for g, u in skipped[:12]:
        print("  跳过（非仓库页）：%s <- %s" % (g, u[:90]))
    return out


def load_adg(path):
    """awesome-decomp-games 的 games 列表 -> {owner/repo: 条目}。
    一个仓可能对应多款游戏（同一引擎带多个游戏），保留第一条并点名重合数，别静默合并。"""
    with io.open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    games = raw.get("games", [])
    out, dup, norepo = {}, 0, []
    for g in games:
        if g.get("type") not in ADG_TYPES:
            continue
        repo = (g.get("repo") or "").strip().strip("/")
        if not repo or repo.count("/") != 1:
            r = (g.get("url") or "")
            m = re.match(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", r)
            repo = "%s/%s" % (m.group(1), m.group(2)) if m else ""
        if not repo:
            norepo.append(g.get("title") or g.get("id") or "?")
            continue
        key = repo.lower()
        if key in out:
            dup += 1
            continue
        out[key] = g
    print("索引 awesome-decomp-games：%d 条游戏 -> %d 个仓库（同仓多游戏合并 %d 条，非游戏档已排除）"
          % (len(games), len(out), dup))
    if norepo:
        print("  点名：%d 条既没有 repo 字段、url 也不是 github 仓库页，接不进登记表（不静默丢）" % len(norepo))
        for t in norepo[:10]:
            print("    - %s" % t[:90])
    return out


def gh_repo(url):
    """任意 URL -> owner/repo（不是 github 仓库页就返回空串）。"""
    m = re.match(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", (url or "").strip())
    if not m:
        return ""
    repo = "%s/%s" % (m.group(1), m.group(2).rstrip("/"))
    return repo[:-4] if repo.endswith(".git") else repo


def load_projects(path, label, repo_of, game_of):
    """聚合目录通用读法：items -> {owner/repo(小写): 条目}，一个仓多条时保留第一条并点名合并数。
    repo_of 拿不到仓名的条目**全部点名**（上一版凭印象手点名掺过 4 个 404，教训在这），
    超过 12 条就给非 github 主机名统计，别让人以为"丢了 148 条"是丢了 148 个游戏。"""
    with io.open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    items = raw.get("projects") or raw.get("apps") or raw
    if isinstance(items, dict):
        items = []
    out, dup, norepo = {}, 0, []
    for it in items:
        repo = repo_of(it)
        if not repo:
            norepo.append(str(game_of(it) or it.get("id") or "?"))
            continue
        if repo.lower() in out:
            dup += 1
            continue
        out[repo.lower()] = dict(it, _repo=repo)
    print("索引 %s：%d 条 -> %d 个 github 仓（同仓多条目合并 %d，非 github/无仓 %d）"
          % (label, len(items), len(out), dup, len(norepo)))
    for t in norepo[:12]:
        print("    跳过：%s" % t[:90])
    if len(norepo) > 12:
        print("    （其余 %d 条同类，见 %s 原文）" % (len(norepo) - 12, os.path.basename(path)))
    return out


def load_rg(path):
    """recomp-games：repo 列直接是 owner/repo；缺它才退回 url（url 有 40 条指向 gitlab/sourceforge，
    那 40 条本档抓不了，点名不当丢了——planner 和镜像只会说 github）。"""
    return load_projects(
        path, "recomp-games(6544)",
        lambda x: (x.get("repo") or "").strip().strip("/") if (x.get("repo") or "").count("/") == 1
        else gh_repo(x.get("url") or x.get("git")),
        lambda x: x.get("game") or x.get("name"))


def load_fyi(path):
    return load_projects(path, "recomp.fyi(3050)", lambda x: gh_repo(x.get("repo")),
                         lambda x: x.get("game") or x.get("project"))


def load_pros(path):
    return load_projects(path, "ProsperoStore(PS5)", lambda x: gh_repo(x.get("source_repo")),
                         lambda x: x.get("name"))


def load_rstore(path):
    """RecompStore 在线目录：仓名藏在 source['repo']，而且条目分在 apps / newerStoreApps / v2Apps
    三个列表里（11-04 只读了 apps 那 18 条，所以数成了 162 而不是 171）。"""
    def repo_of(a):
        src = a.get("source") or {}
        return (src.get("repo") or "").strip().strip("/") if (src.get("repo") or "").count("/") == 1 \
            else gh_repo(a.get("repo") or a.get("page"))

    def game_of(a):
        return a.get("name") or a.get("id")

    out = {}
    dups = 0
    with io.open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    total = 0
    for key in ("apps", "newerStoreApps", "v2Apps"):
        for a in raw.get(key) or []:
            total += 1
            a = dict(a, _list=key)
            repo = repo_of(a)
            if not repo:
                continue
            if repo.lower() in out:
                dups += 1
                continue
            out[repo.lower()] = dict(a, _repo=repo)
    print("索引 RecompStore 在线目录：%d 条 app（apps+newerStoreApps+v2Apps）-> %d 个仓，"
          "同仓多 app 合并 %d；目录版本 %s / 更新 %s"
          % (total, len(out), dups, raw.get("catalogVersion"), raw.get("updated")))
    return out


def report_unbaked(path, add_path):
    """unbaked.games 当"条数 + 增量哨"报，不进仓名：6517 款每款只有一个自己的 json 链接，
    要仓名就是 6517 次请求（约 3 小时 API）。这里只把"有多少、其中多少有公开代码/原生构建"
    和 additions.json 的周增量打印并落一行到 清单来源/，别让它冒充已经接进库。"""
    if not os.path.exists(path):
        print("索引 unbaked.games：没抓到盘，跳过")
        return {}
    with io.open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    games = raw.get("games", [])
    ncode = sum(1 for g in games if g.get("has_public_code"))
    nnat = sum(1 for g in games if g.get("native_build"))
    weeks = []
    if os.path.exists(add_path):
        with io.open(add_path, encoding="utf-8") as fh:
            add = json.load(fh)
        for w in add.get("weeks", []):
            pr = w.get("projects")
            weeks.append((w.get("week"), pr if isinstance(pr, int) else len(pr or []),
                          w.get("games_newly_opened")))
    print("索引 unbaked.games：%d 款（有公开代码 %d / 有原生构建 %d）——**没有内联 repo**，"
          "本档只登记条数，逐款仓名要 %d 次 API，未接" % (len(games), ncode, nnat, len(games)))
    print("  增量哨 additions.json：按周新增 %s" % (weeks or "（没抓到盘）"))
    return {"count": len(games), "has_public_code": ncode, "native_build": nnat,
            "updated": raw.get("updated"), "weeks": weeks}


def load_seed(path):
    """recomphub.com 种子数据 -> {owner/repo(小写): 条目}，条目里补一份原样大小写的 repo。"""
    with io.open(path, encoding="utf-8") as fh:
        items = json.load(fh)
    out = {}
    for x in items:
        m = re.match(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", (x.get("repo_url") or "").strip())
        if not m:
            continue
        repo = "%s/%s" % (m.group(1), m.group(2))
        out.setdefault(repo.lower(), dict(x, repo=repo))
    print("索引 recomphub.com 种子：%d 条 -> %d 个仓库" % (len(items), len(out)))
    return out


def main():
    offline = "--offline" in sys.argv
    scene = read_tsv(SCENE, ["repo", "stars", "n_tags", "pushed", "desc"])
    rel = read_tsv(RELEASES, ["repo", "stars", "n_release", "n_asset", "bytes", "sample_asset"])
    cat_list = [l.strip() for l in io.open(CAT, encoding="utf-8") if l.strip()]
    index = load_index(INDEX)
    adg = load_adg(ADG)
    seed = load_seed(SEED)
    rg = load_rg(RGCAT)
    fyi = load_fyi(FYI)
    pros = load_pros(PROS)
    rst = load_rstore(RSTORE)
    unbaked = report_unbaked(UNBAKED, UNBAKED_ADD)
    # 两堆来源分开对待，这是这次扩容唯一要紧的判据：
    #   store：PS5 商店目录点名的仓——真能装进主机的东西，下架风险最高，值得 clone 源码存档，
    #          所以允许探元数据、按 .git 大小定 policy。
    #   bulk ：批量总索引（ADG/recomp-games/recomp.fyi）——几千个仓，探一遍 API 就是几小时，
    #          clone 更是把盘喂给源码。只登记（note 里留原条目信息）+ 照旧抓 release 成品包。
    store, bulk = {}, {}
    for d in (pros, rst):
        for k, v in d.items():
            store.setdefault(k, v)
    for d in (adg, rg, fyi):
        for k, v in d.items():
            bulk.setdefault(k, v)
    with io.open(CATJSON, encoding="utf-8") as fh:
        cat_raw = json.load(fh)
    cat_entries = {}
    for e in cat_raw.get("entries", cat_raw if isinstance(cat_raw, list) else []):
        if isinstance(e, dict) and e.get("repo"):
            cat_entries[e["repo"].strip().strip("/").replace("https://github.com/", "")] = e

    # 档位：先按描述/目录判，再由元数据里的 topic 不管用（省一次 API），手工规则够用
    def tier_of(repo, desc):
        low = flat_text(desc).lower()
        name = repo.lower()
        # 商店/目录本身不是"移植体"，是按目录——上一版把 elripalda/RecompStore 归成了成品移植体
        if (any(k in name for k in ("store", "-hub", "awesome", "buddy", "catalog"))
                or repo in {r for r, _, _ in EXTRA}
                or repo in ("justxor/awesome-decomp-games-ru",
                            "maluramichael/awesome-reverse-engineer-anything",
                            "TanookiStudios/decomp-buddy")):
            return "目录/商店"
        if "switch 2" in low or "nx2" in low or repo in ("drakolordx7/pokopia-recomp",
                                                         "Lucas-blip-png/dkb-pc-recomp"):
            return "Switch2 移植体"
        if any(k in low for k in ("android", "termux", "mobile", "arm64", "portable",
                                  "掌机", "handheld", "reverse engineering for android")):
            return "掌机可玩"
        if any(k in low for k in ("toolkit", "tool", "recompiler for", "compiler", "sdk",
                                  "engine for porting", "skills", "catalog of tools")):
            return "移植工具链"
        if repo in ("2ship2harkinian/2ship2harkinian", "Morio-Project", "OpenRaft"):
            return "移植工具链"
        return "成品移植体"

    cache = load_meta_cache()
    held = held_elsewhere()
    # 归一到小写再比：隔壁档的目录名是当年从小写仓名建的，这次新仓名带原样大小写，
    # 大小写敏感地判"重复"会让同一个仓在两档各下一遍。
    held_key = {k.lower(): v for k, v in held.items()}
    rows = []
    all_repos = []
    seen = set()
    # 上一版登记表先读一遍，用来报"这次净新增多少个仓"——写完就查不到了。
    prev_reg = set()
    if os.path.exists(REG):
        with io.open(REG, encoding="utf-8") as fh:
            prev_reg = {r["repo"].lower() for r in csv.DictReader(fh, delimiter="\t") if r.get("repo")}
    # 每一路来源各自的仓名，用来判"只出现在批量库里"的仓（下面 policy 要区别对待）
    core = {r.lower() for r in list(scene) + cat_list + list(index) + [x[0] for x in EXTRA]
            + [v["repo"] for v in seed.values()] + [v["_repo"] for v in store.values()]}
    adg_only_set = {k for k in bulk if k not in core}
    for repo in (list(scene) + cat_list + list(index) + [r for r, _, _ in EXTRA]
                 + [v["repo"] for v in seed.values()]
                 + [v["_repo"] for v in rg.values()] + [v["_repo"] for v in fyi.values()]
                 + [v["_repo"] for v in pros.values()] + [v["_repo"] for v in rst.values()]
                 + list(adg)):
        if repo.lower() not in seen:
            seen.add(repo.lower())
            all_repos.append(repo)

    extra_note = {r: (t, n) for r, t, n in EXTRA}
    order = sorted(all_repos, key=str.lower)
    probed = 0
    for repo in order:
        # 批量库（ADG/recomp-games/recomp.fyi）里、别的路没点名的仓：policy 钉成 meta，
        # size 探来没用，却要 5000 多次 API（11-04 实测一次约 1.5 s = 两小时白烧）。
        # 存档/停更/平台信息目录里自带，note 里有。
        adg_only = repo.lower() in adg_only_set
        meta = cache.get(repo.lower())
        if not offline and not adg_only and (meta is None or not meta.get("size_mb")):
            m = api(repo)
            if m:
                meta = {"repo": repo,
                        "stars": str(m.get("stargazers_count", "")),
                        "size_mb": "%.0f" % (m.get("size", 0) / 1024.0),
                        "license": (m.get("license") or {}).get("spdx_id", "") or "NONE",
                        "default_branch": m.get("default_branch", ""),
                        "pushed_at": (m.get("pushed_at") or "")[:10],
                        "archived": str(m.get("archived", "")),
                        "disabled": str(m.get("disabled", "")),
                        "open_issues": str(m.get("open_issues_count", "")),
                        "probed_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                cache[repo.lower()] = meta
                probed += 1
                if probed % 20 == 0:
                    save_meta(cache, order)
                    print("  元数据已探 %d 个，落盘 %s" % (probed, os.path.basename(META)))
        if meta is None:
            meta = {"repo": repo, "stars": scene.get(repo, {}).get("stars", ""),
                    "size_mb": "", "license": "", "default_branch": "", "pushed_at": "",
                    "archived": "", "disabled": "", "open_issues": "", "probed_at": ""}
        desc = scene.get(repo, {}).get("desc", "")
        cat = cat_entries.get(repo)
        idx = index.get(repo.lower())
        g = adg.get(repo.lower())
        sd = seed.get(repo.lower())
        rgh = rg.get(repo.lower())
        fy = fyi.get(repo.lower())
        pr = pros.get(repo.lower())
        rs = rst.get(repo.lower())
        # 只出现在索引里的仓没有 desc/cat 可读，退回用索引条目自带的说明当描述
        idx_note = (flat_text((idx or {}).get("note", "")) or ((g or {}).get("description") or "")
                    or ((rgh or {}).get("description") or "") or ((fy or {}).get("description") or "")
                    or ((pr or {}).get("description") or "") or ((rs or {}).get("blurb") or ""))
        tier = extra_note[repo][0] if repo in extra_note else tier_of(
            repo, desc or (cat or {}).get("description", "") or idx_note)
        # 两个 PS5 商店目录点名的仓：按商店自带的 kind/category 定档，比拿描述猜准。
        # 但商店自己（RecompStore/ProsperoStore 本仓）还是按目录算，不许被这条盖掉。
        shop = pr or rs
        if shop and tier != "目录/商店" and repo not in extra_note:
            kind = str(shop.get("kind") or shop.get("category") or "").lower()
            tier = "移植工具链" if kind in ("tool", "tools", "utility") else "PS5 移植体"
        r = rel.get(repo, {})
        size_mb = meta.get("size_mb", "")
        try:
            sz = float(size_mb) if size_mb else None
        except ValueError:
            sz = None
        if sz is None:
            policy = "meta"
        elif sz <= FULL_MAX_MB:
            policy = "full"
        elif sz <= BLOBLESS_MAX_MB:
            policy = "blobless"
        else:
            policy = "meta"
        # 批量库里、别的来源没点名的仓：只认成品包，不 clone 源码。
        # 11-04 实测：登记 505 个仓时启用仓 .git 合计已经 67 GB，再按 size 判 full 放 2000 个进来
        # 就是把盘喂给源码；11-05 这两路进来的是 8000 多个。成品包走 releases 资产，
        # 跟 policy 无关（planner 只看 enable）。
        if adg_only:
            policy = "meta"
        parts = []
        if meta.get("stars"):
            parts.append("%s★" % meta["stars"])
        elif scene.get(repo, {}).get("stars"):
            parts.append("%s★" % scene[repo]["stars"])
        if r.get("n_release"):
            mb = int(r.get("bytes") or 0) / 1048576.0
            parts.append("release %s 个/资产 %s 个/%dMB" % (r["n_release"], r.get("n_asset", "0"), mb))
        if size_mb:
            parts.append(".git %.0fMB" % float(size_mb))
        if cat:
            parts.append("RecompHub 条目：%s（%s）" % (cat.get("name", ""), cat.get("system", "")))
        if idx:
            parts.append("索引条目：%s｜%s｜%s｜%s" % (idx.get("game", ""), idx.get("console", ""),
                                                  idx.get("method", ""), idx.get("stage", "")))
        if g:
            parts.append("ADG：%s｜%s｜%s｜%s★｜rel %s%s"
                         % (g.get("title", ""), g.get("platform", ""), g.get("type", ""),
                            g.get("stars", ""), g.get("release") or "-",
                            "｜停更" if g.get("archived") or (g.get("last_commit") or "")[:4] < "2025" else ""))
        if sd:
            parts.append("recomphub.com：%s｜%s｜%s｜可玩=%s｜跑在%s"
                         % (sd.get("game", ""), sd.get("original_platform", ""), sd.get("kind", ""),
                            sd.get("playable", ""), "/".join(sd.get("runs_on", []) or [])))
        if rgh:
            parts.append("recomp-games：%s｜%s→%s｜%s/%s｜最后提交%s｜需自备原版=%s%s"
                         % (rgh.get("game") or rgh.get("name") or "",
                            rgh.get("original_platform", ""),
                            "/".join(rgh.get("target_platforms") or [])[:38],
                            rgh.get("type", ""), rgh.get("status", ""),
                            rgh.get("last_commit", "-"),
                            rgh.get("requires_original_game", "-"),
                            "" if rgh.get("verified") else "｜目录未验证"))
        if fy:
            parts.append("recomp.fyi：%s｜%s｜%s｜%s/%s｜版本 %s｜构建 %s｜%s许可｜最后提交%s%s"
                         % (fy.get("game", ""), fy.get("system", ""), fy.get("project", ""),
                            fy.get("type", ""), fy.get("status", ""), fy.get("version", "-"),
                            "/".join(fy.get("builds") or [])[:30] or "-",
                            fy.get("license", "-"), fy.get("lastCommit", "-"),
                            "｜仓已归档" if fy.get("archived") else ""))
        if pr:
            parts.append("ProsperoStore(PS5)：%s｜%s/%s｜titleid %s｜v%s｜作者 %s｜包 %s｜sha256 %s｜钉链 %s"
                         % (pr.get("name", ""), pr.get("kind", ""), pr.get("category", ""),
                            pr.get("titleid", ""), pr.get("version", ""),
                            (pr.get("author") or "")[:24],
                            os.path.basename(str(pr.get("artifact_url") or "")),
                            (pr.get("sha256") or "")[:16] or "-",
                            "有" if pr.get("artifact_url") else "无"))
        if rs:
            src = rs.get("source") or {}
            parts.append("RecompStore(PS5)：%s｜%s/%s｜id %s｜源 %s｜包 %s｜%s"
                         % (rs.get("name", ""), rs.get("kind", ""), rs.get("category", ""),
                            rs.get("id", ""), src.get("type", ""), src.get("asset", "") or "-",
                            "需手动装" if rs.get("manualSetup") else ""))
        note = "｜".join(parts + [extra_note[repo][1] if repo in extra_note
                                 else flat_text(desc or (cat or {}).get("description") or idx_note)[:80]])
        enable = "1"
        if repo.lower() in held_key:
            enable = "0"
            note = "已在「%s/源码」档内，本档不重复下载" % held_key[repo.lower()] + ("｜" + note if note else "")
            policy = "skip"
        rows.append({"repo": repo, "enable": enable, "tier": tier, "policy": policy,
                     "size_mb": size_mb, "stars": meta.get("stars", ""), "note": note})

    os.makedirs(AREA, exist_ok=True)
    # 先写临时件再改名：镜像循环(_镜像循环.sh)每一轮都会重读这本登记表，
    # 半本文件被读到等于那一轮只镜像半本库，而且 csv 会当场抛错。
    tmp = REG + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HDR, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, REG)
    save_meta(cache, order)
    on = [r for r in rows if r["enable"] == "1"]
    dist = {}
    pol = {}
    for r in on:
        dist[r["tier"]] = dist.get(r["tier"], 0) + 1
        pol[r["policy"]] = pol.get(r["policy"], 0) + 1
    print("登记表：%s" % REG)
    print("  总 %d 行｜启用 %d｜停用（已在别的档）%d" % (len(rows), len(on), len(rows) - len(on)))
    print("  档位：%s" % dist)
    print("  策略：%s" % pol)
    n_adg = sum(1 for r in rows if r["repo"].lower() in adg)
    print("  ADG 库覆盖 %d 个仓（其中 %d 个是这次新接进来的，只登记+抓成品包、不 clone 源码）"
          % (n_adg, sum(1 for r in rows if r["repo"].lower() in adg_only_set)))
    # 这次净新增多少仓：登记表刚被覆盖，"上一版有什么"只能靠开写之前读的那份 prev_reg 说。
    now = {r["repo"].lower() for r in rows}
    print("  净新增（上一版登记表里没有的仓）%d 个：recomp-games %d｜recomp.fyi %d｜"
          "ProsperoStore %d｜RecompStore %d"
          % (len(now - prev_reg),
             len({k for k in rg if k not in prev_reg}),
             len({k for k in fyi if k not in prev_reg}),
             len({k for k in pros if k not in prev_reg}),
             len({k for k in rst if k not in prev_reg})))
    print("  只登记不下源码（policy=meta，批量库独有）%d 个仓｜商店目录点名、按大小定档 %d 个仓"
          % (len(adg_only_set & now), len({k for k in store if k in now})))
    if unbaked:
        print("  unbaked.games %d 款**没接进仓名**（每款只有一个自己的 json，逐款要 %d 次 API）；"
              "它的 additions.json 当增量哨：%s"
              % (unbaked["count"], unbaked["count"], unbaked["weeks"]))
    tot = sum(float(r["size_mb"]) for r in on if r["size_mb"])
    print("  启用仓库 .git 合计 %.2f GB（其中 policy=full 的部分才算要连历史下）" % (tot / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
