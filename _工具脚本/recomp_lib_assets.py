# -*- coding: utf-8 -*-
r"""成品移植游戏库：成品包（release 资产）获取器。

先说清楚这里下的是什么：静态重编译那一波出的**原生可执行程序包**，跑之前要你自己 dump
正版游戏（README 里叫 BYO-dump）。包里不含商业 ROM/BIOS，也不含泄露源码，所以落在
2026-11-03 定的口径内：可以批量下、自己用、进自己网盘，但不外发链接。

为什么要 --plan 先跑：这批仓的历史 release 资产加起来 122.28 GB（11-04 实测，见 README），
全量肯定不行。所以默认只取每个仓**最新一条 release**，再按单资产上限筛。先把计划落盘、
把体积算出来，再决定下不下。

    py -3 _工具脚本/recomp_lib_assets.py plan      # 只列计划，不下载（先看量）
    py -3 _工具脚本/recomp_lib_assets.py pull      # 按计划下载 + sha256 + 解包复检
    py -3 _工具脚本/recomp_lib_assets.py verify     # 不联网重扫本地，逐格对账

红线闸门（和源码档同一套判据）：资产名带 .xci/.nsp/.nsz/.nca/.nro/.nkd/.tik/.keys 的
一律不下；下完解包扫成员，命中原厂数据特征（.usm/.pak/.arb/.xexp 等）的**不删**，
挪到 待复核/ 并点名，由人判——自动删掉过源码里的 FirmwareAvatarAdapter.kt 那次教训在这里同样适用。
"""
import csv
import ctypes
import datetime as dt
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.parse
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net_proxy          # 代理口不写死，见该文件
AREA_NAME = os.environ.get("MIRROR_AREA", "成品移植游戏库")
AREA = os.path.join(ROOT, "06-资讯监控", AREA_NAME)
REG = os.path.join(AREA, "仓库登记表.tsv")
CATJSON = os.path.join(AREA, "RecompHub目录.json")
BIN_DIR = os.path.join(AREA, "成品包")
HOLD_DIR = os.path.join(AREA, "待复核")
PLAN = os.path.join(AREA, "成品包计划.tsv")
LEDGER = os.path.join(AREA, "成品包台账.tsv")
LEDGER_PREV = os.path.join(AREA, "成品包台账.上一轮.tsv")
LOG = os.path.join(AREA, "成品包日志.txt")

ASSET_MAX_MB = 3000          # 单个资产上限：11-04 从 500 提到 3000。口径改成"全库游戏都要"之后，
                             # 500MB 那档拦住的是真游戏包（Project-2099 三片 1.0GB+1.3GB、
                             # RE Code Veronica 507MB、Alone in the Dark 763MB、PortMaster 全量安装器 823MB）
REPO_MAX_MB = 8000           # 单仓最新一版全资产合计上限：1200 会把"同一游戏出 win/linux/apk/mac 多平台包"
                             # 的仓整本拦掉，放开后按仓拦等于按平台拦
RESERVE_GB = 60.0            # 写盘前必须给别的线留出的余量：端口包树（实测 16~22 GB）、
                             # 源码镜像（621 个克隆目标）、bundle 和 git 对象都在同一块 F 盘上写。


def run_max_gb(free_gb):
    """单轮允许写入的字节上限：盘余量减预留。没有托底的死数。
    原来这里写的是 max(一个 200 GB 的死地板, 盘余 − 预留)，那个地板会顶掉预留：
    11-05 09:3x 实测盘余 231 GB，按地板算本轮允许写 200 GB，只剩 31 GB 在盘上——
    而端口包那条线正往同一块 F 盘里灌一个 20 GB 上下的 tar.gz（codeload 不认 Range，
    在途整包被盘挤掉就是十几 GB 白跑，还得从头再来）。地板删掉，"盘大就多下、
    盘紧就少下"这句本意才真的生效。"""
    return max(0.0, free_gb - RESERVE_GB)


def pid_alive(pid):
    """这个 PID 现在是不是一个真进程。只查，不碰。
    OpenProcess 拿 QUERY_LIMITED 权限就够（不开调试权限，免得撞上杀软），
    拿到句柄后看退出码：259 = STILL_ACTIVE。"""
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
            return True          # 查不到退出码（多半是没权限），宁可当它还活着
        return code.value == 259
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def hold_lock(name):
    """同一档只许一个进程动盘/烧 API，第二个直接退出。
    11-05 06:40 我自己同时起了两份 pull：那会儿 plan 正在把计划文件从头重写，
    一份 pull 读到的是重写一半的 214 行、另一份读到的是完整的 5,567 行，
    两份往同一个目录写同名文件、各烧一份带宽、各记一份台账，还互相把对方的半成品当"已下"。
    判活要同时看两条：① 锁里的 PID 还在不在，② 锁文件的 mtime 新不新（持有者每写一行日志
    就 touch 一次，见 log() 与 beat）。只看 PID 不够——Windows 会回收 PID，锁的主人半路没了、
    PID 被别的进程拿去，这一档就永远起不来；只看 mtime 也不够——进程活着但卡死两小时，
    那正是需要下一轮接手的时候。"""
    lk = os.path.join(AREA, ".锁_%s.txt" % name)
    global _LOCK
    if os.path.exists(lk):
        raw = io.open(lk, encoding="utf-8", errors="replace").read().strip()
        try:
            victim = int(raw.split()[0])
        except (IndexError, ValueError):
            victim = 0
        age = time.time() - os.path.getmtime(lk)
        if victim and victim != os.getpid() and age < LOCK_FRESH_S and pid_alive(victim):
            log("闸门：%s 档已有进程 %d 在跑（锁 %.0f s 前还在跳）——本档退出，不抢它的活"
                % (name, victim, age))
            return False
        log("锁 .锁_%s.txt 不成立了（锁里写着 %r，%.0f s 没跳）：接过来"
            % (name, raw, age))
    os.makedirs(AREA, exist_ok=True)
    io.open(lk, "w", encoding="utf-8").write("%d\n" % os.getpid())
    _LOCK = lk
    return True


def beat():
    """持有者的心跳：把锁的 mtime 推到当下。没拿到锁（探针直接调 cmd_*）就是空操作。"""
    if _LOCK:
        try:
            os.utime(_LOCK, None)
        except OSError:
            pass

GH = shutil.which("gh") or os.path.expanduser(r"~\.workbuddy\gh-cli\bin\gh.exe")
CURL = shutil.which("curl") or "curl"
ROM_EXT = {".xci", ".nsp", ".nsz", ".nca", ".nro", ".nkd", ".tik", ".keys"}
SUSPECT = [".usm", ".pak", ".bf", ".wtf", ".mod", ".fgc", ".xexp", ".arb",
           "audio_bank", "movies/", ".ogg.patch"]
# 认下来的"包形态"：11-04 之前只有前 7 个，掌机要的 Linux/Android 包全被"非压缩包"挡了
PKG_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".xz", ".zst",
           ".appimage", ".flatpak", ".squashfs", ".deb", ".rpm", ".apk", ".ipa",
           ".dmg", ".exe", ".msi", ".sh", ".pakz", ".vpk", ".elf", ".bin", ".aot"}
# 只是校验值/元数据的副产品，不是包，不下
SIDECAR_EXT = {".md5", ".sha1", ".sha256", ".sha512", ".sig", ".asc", ".blockmap",
               ".json", ".yml", ".yaml", ".txt", ".md", ".html", ".zsync",
               ".properties", ".version", ".log"}
PLAN_HDR = ["repo", "tier", "tag", "asset", "bytes", "why", "asset_id", "cat", "note"]
API_FAIL = {"net": 0, "404": 0, "限流": 0}
# 单实例锁：见 hold_lock()。300 s 是"持有者还在跳"的窗口——pull 落地一个资产通常几秒到几十秒，
# plan 问一个仓通常几秒，所以真活着的心跳不会老到 5 分钟；反过来真断了（进程没了/卡死）
# 5 分钟后下一轮就能接手，不会把整条线锁死。
LOCK_FRESH_S = 300
_LOCK = None                 # 只有拿到锁的进程会赋值；没拿到（比如探针直调 cmd_*）心跳就是空操作
# 撞限流时最多在一轮里等多久。放配额是按小时滚动的，等一小时以上不如把这一轮收掉：
# 计划现在是可续跑的（逐仓落盘 + 已问过不重问），下一轮接着问就行。
QUOTA_WAIT_S = 40 * 60
AGG_MARK = "聚合库｜"       # 计划行 note 的前缀，pull 靠它认"这仓的行来自全 release 枚举"，
                            # 好在单仓 8 GB 那道闸门前豁免——聚合库的 8 GB 拦的是"一款游戏
                            # 出四个平台的包"，对几百个端口完全不同的 zip 没有意义。
AGG_PAGE_TRIGGER = 100      # 第一页刚好问满 100 个 release ⇒ 这仓是"一天一个 build"的聚合库。
                            # 11-05 实测 PortsMaster/PortMaster-New 有 419 个 release / 8,759 个资产 /
                            # 272.54 GB，而照 releases/latest 只枚举得到 13 行 0.47 GB——每个 release
                            # 装的是不同的端口，不是同一款游戏的旧版本，所以"只取最新"在这里是漏，不是省。
AGG_RELEASE_PAGES = 12      # 每仓最多翻 12 页（1,200 个 release）。普通仓 1~3 个 release，
                            # 一道都没多花；只有问满一页的仓才付翻页的配额。
ENUM_VER = "枚举v2｜"        # 每条计划行都带这个前缀，读侧据此认"这行是哪一代枚举方式问出来的"。
                            # 11-05 换成全 release 枚举后，上一代的行必须整本重问：
                            # 不然 PortMaster-New 会永远停在 13 行，而它真有 8,759 个资产。
LEDGER_HDR = ["repo", "tag", "asset", "bytes", "sha256", "state", "audit", "got_at", "note"]


def log(msg):
    line = "[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    os.makedirs(AREA, exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    beat()          # 心跳挂在 log 上：plan/pull 每落地一格都会写一行，不用在各处单独记得跳


def env():
    """代理口是活的（7890→7891 换过），见 net_proxy.py：探到哪个用哪个，一个都不活就清空变量直连。
    写死口号或原样继承 shell 里那个旧 HTTPS_PROXY，都会让整批 gh 调用全线失败。"""
    return net_proxy.env()


def wait_quota():
    """撞上限流就去查余量，直接睡到解除，别把剩下几千次调用全烧成失败。
    为什么要主动睡而不是继续试：匿名口 60 次/小时、鉴端口 5,000 次/小时，
    11-05 06:0x 实测走 7890 那条隧道出去是 66.90.98.36 这个共享出口，匿名 60 次已经见底
    （`X-RateLimit-Remaining: 0`，约 27 分钟后放）。继续硬问等于让计划里每个仓都记一次失败。"""
    r = subprocess.run([GH, "api", "rate_limit"], capture_output=True, env=env(), timeout=60)
    try:
        core = json.loads(r.stdout.decode("utf-8", "replace"))["resources"]["core"]
    except Exception:
        time.sleep(60)
        return False
    if core.get("remaining", 0) > 0:
        return True
    reset = float(core.get("reset") or time.time() + 60)
    wait_s = max(0.0, reset - time.time()) + 5
    if wait_s > QUOTA_WAIT_S:
        log("  限流还要等 %.1f 分钟，超过单轮上限 %d 分钟：本轮就此收，已落盘的行留着，下一轮接着问"
            % (wait_s / 60.0, QUOTA_WAIT_S // 60))
        return False
    log("  被限流（本小时配额已用 %s/%s）：睡 %.1f 分钟到 %s 再继续"
        % (core.get("used"), core.get("limit"), wait_s / 60.0,
           dt.datetime.fromtimestamp(reset).strftime("%H:%M:%S")))
    time.sleep(wait_s)
    return True


def gh_api(path, fail=None):
    for attempt in (1, 2):
        r = subprocess.run([GH, "api", path], capture_output=True, env=env(), timeout=90)
        if r.returncode == 0:
            if fail is not None:
                fail["kind"] = "ok"
            try:
                return json.loads(r.stdout.decode("utf-8", "replace"))
            except Exception:
                return None
        # 三种失败要分开，混在一起代价不一样：
        #   404 = 这仓真没发过 release，要落一行负结果，下一轮不再问；
        #   限流 = 我方配额问题，不落行也不计成"没有包"，睡到解除再问一次；
        #   链路 = 不动盘，下一轮重问。
        err = (r.stderr or b"").decode("utf-8", "replace")
        low = err.lower()
        if "http 404" in low or "not found" in low:
            key = "404"
        elif "http 403" in low or "rate limit" in low or "http 429" in low:
            key = "限流"
        else:
            key = "net"
        API_FAIL[key] = API_FAIL.get(key, 0) + 1
        if fail is not None:
            fail["kind"] = key
        if key == "限流" and attempt == 1 and wait_quota():
            API_FAIL[key] -= 1
            if fail is not None:
                fail["kind"] = None
            continue
        if key == "net" and API_FAIL["net"] <= 3:
            log("  API 失败（链路类）：%s <- %s" % (path[:70], err.strip()[:120]))
        elif key == "限流":
            log("  API 限流，本轮不再问：%s" % path[:70])
        return None
    if fail is not None:
        fail["kind"] = "限流"
    return None


def read_reg():
    with io.open(REG, encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh, delimiter="\t")]


def read_plan():
    """逐行自己拆，不用 DictReader：计划现在是**边跑边追加**的（见 build_plan），
    追加的那一刻拉包循环正好读到半行，DictReader 会整本抛错、这一轮 pull 直接没命。
    半行丢掉只少一格，而且要点名——静默少一行等于静默少一个包。"""
    out, bad = [], 0
    if not os.path.exists(PLAN):
        return out
    with io.open(PLAN, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            if not line.strip():
                continue
            if not line.endswith("\n"):
                bad += 1
                continue
            p = line.rstrip("\n").split("\t")
            if len(p) != len(header):
                bad += 1
                continue
            out.append(dict(zip(header, p)))
    if bad:
        log("  计划里有 %d 行读不出（半行/字段数不对），已跳过并在下一轮重问" % bad)
    return out


# ---- 重发型仓的截断：11-05 07:46 现场量的 ----
# 全 release 枚举（AGG_PAGE_TRIGGER / 翻 12 页）之后计划从 4,952 个 / 263.94 GB 涨到
# 63,291 个 / 6,491.9 GB，其中 **75% 的字节来自三个 Cataclysm**：
#   cleverraven/cataclysm-dda   11,280 行 / 2,598.5 GB / 1,186 个 release
#   cataclysm-tlg/cataclysm-tlg  8,636 行 / 1,274.1 GB / 1,001 个 release
#   cataclysmbn/cataclysm-bn    10,541 行 /   999.3 GB / 1,084 个 release
# 这三家不是"每个 release 装一款不同的游戏"，是**同一款游戏每天出一个新 build**，
# 资产名去掉版本号之后只剩 12/25/62 个"族"（unique 名占行数比 ≈ 0%）。
# 对照 CommitteeOfZero/impacto：3,431 行 / 675 个 release，unique 名占 **98%**——
# 每个 release 装的是不同插件，按"最新几个"截就真丢了内容。
# 所以判据用**名字重样率**而不是"是不是聚合库"：名字基本不重样 ⇒ 全留；
# 名字高度重样 ⇒ 只留版本号最大的 FAM_KEEP_TAGS 个 release。
FAM_KEEP_TAGS = 3
FAM_UNIQ_FLOOR = 0.15


def fam_of(name):
    """资产名的"族"：小写、数字段并成一个 #、丢掉标点。
    cataclysmdda-0.I-64-windows.zip 和 cataclysmdda-0.J-64-windows.zip 落进同一个族，
    aerofoil.zip 和 100-lil-jumps.zip 落进不同族。"""
    n = re.sub(r"[0-9]+", "#", (name or "").lower())
    return re.sub(r"[^a-z#]", "", n)


def ver_key(tag):
    """版本号排序：数字段按数值比，非数字段按文本比（0.9 < 0.10，"DDA_0_62" 排得对）。
    元素统一成 (是否数字, 数值, 文本) 的元组，否则 py3 里 int 和 str 不能互相比较。"""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p)
            for p in re.split(r"(\d+)", tag or "") if p != ""]


def collapse_repeat_releases(rows):
    """把"同一款游戏反复出新 build"的仓截到最近几个 release，其余逐行留下。返回 (留下的行, 被截的仓)。"""
    by = {}
    for r in rows:
        by.setdefault(r["repo"], []).append(r)
    keep, cut = [], []
    for repo in sorted(by):
        v = by[repo]
        tags = {r["tag"] for r in v}
        if len(tags) <= FAM_KEEP_TAGS:
            keep.extend(v)
            continue
        uniq = float(len({fam_of(r["asset"]) for r in v})) / len(v)
        if uniq >= FAM_UNIQ_FLOOR:
            keep.extend(v)      # 名字基本不重样：每个 release 装的是不同东西，全留
            continue
        newest = set(sorted(tags, key=ver_key)[-FAM_KEEP_TAGS:])
        keep.extend([r for r in v if r["tag"] in newest])
        drop_gb = sum(int(r["bytes"]) for r in v
                      if r["tag"] not in newest) / 1073741824.0
        cut.append((repo, len(v), len(tags), uniq,
                    sum(int(r["bytes"]) for r in v) / 1073741824.0, drop_gb,
                    sorted(newest, key=ver_key)))
    return keep, cut


def order_by_breadth(rows):
    """每个仓自己的包按体积从大到小排，然后**仓与仓轮流出一个**。
    为什么不用单纯的"大的先下"：目标是"库里的游戏尽量多"，广度比体积值钱——
    照整本从大到小排，1,800 个仓里最大的那几个仓（聚合库不设单仓上限）会先把一轮的预算吃光，
    剩下的仓一个包都没摸到；反过来按字母序轮又会让 0.1 MB 的 installer 抢在前面。
    轮流出 + 每仓内部大的先：第一轮就把 1,800 个仓各自最大那块包拿到手，
    第二轮才拿它们的第二块。预算截断也走这个顺序（见 cmd_pull），两边口径一致。"""
    by = {}
    for r in rows:
        by.setdefault(r["repo"], []).append(r)
    for v in by.values():
        v.sort(key=lambda r: -int(r["bytes"]))
    out = []
    depth = 0
    while True:
        added = False
        for repo in sorted(by):
            v = by[repo]
            if depth < len(v):
                out.append(v[depth])
                added = True
        if not added:
            return out
        depth += 1


def fit_budget(pending, budget_gb):
    """在已经排好序的 pending 上贪心塞进预算：这一格放不下就**跳过它接着试下一格**，
    不是碰到第一个超预算的大包就收工（那样一个 8 GB 的聚合库包会把整轮堵死）。
    返回 (选中的行, 被跳过的行数, 选中体积 GB)。"""
    acc, chosen, skipped = 0.0, [], 0
    for r in pending:
        gb1 = int(r["bytes"]) / 1073741824.0
        if acc + gb1 > budget_gb:
            skipped += 1
            continue
        acc += gb1
        chosen.append(r)
    return chosen, skipped, acc


def asset_url(repo, tag, asset):
    """release 资产的浏览器下载地址（不用问 API）。
    tag 里的斜杠不转义：GitHub 对带 `/` 的 tag（brokenregistry/rotp-fusion 的
    `2026-11-01/2159` 那种）就是这么摆在路径里的。"""
    return "https://github.com/%s/releases/download/%s/%s" % (
        repo, urllib.parse.quote(tag or "", safe="/"),
        urllib.parse.quote(asset or "", safe="~"))


def curl_asset(url, dst, allow):
    """curl 直落一个资产。返回 (rc, http_code, curl 自己算的平均 B/s)。
    半截文件不进池子：下到 .part，rc=0 才改名。"""
    tmp = dst + ".part"
    if os.path.isfile(tmp):
        os.remove(tmp)      # 上一轮被杀的 curl 会把 .part 留在原地，先清掉再写
    try:
        p = subprocess.run(
            [CURL, "-sS", "-L", "--fail", "-o", tmp,
             "-w", "%{http_code} %{speed_download}", "--max-time", str(allow),
             "--retry", "2", "--retry-delay", "3", url],
            capture_output=True, env=env(), timeout=allow + 40)
    except subprocess.TimeoutExpired:
        if os.path.isfile(tmp):
            os.remove(tmp)
        return 124, "timeout", 0
    code, _, spd = (p.stdout or b"").decode("utf-8", "replace").strip().partition(" ")
    if p.returncode != 0:
        if os.path.isfile(tmp):
            os.remove(tmp)
        return p.returncode, code or "", 0
    try:
        os.replace(tmp, dst)
    except OSError:
        return 1, code or "", 0
    return 0, code, float(spd or 0)


def load_catalog():
    """RecompHub 目录给每个条目一个 asset_pattern（正则），用它挑对的那个包。"""
    if not os.path.exists(CATJSON):
        return {}
    with io.open(CATJSON, encoding="utf-8") as fh:
        d = json.load(fh)
    out = {}
    for e in d.get("entries", []):
        repo = (e.get("repo") or "").replace("https://github.com/", "").strip("/")
        if repo:
            out[repo] = e
    return out


def want_asset(name, size):
    """返回 (要不要, 理由)。不要就是红线、校验副产品或没认出来的后缀，点名进台账。

    11-04 改过一次口径：原来只收 `.zip/.7z/.tar/.gz/.xz/.tgz/.rar`，其余一律"非压缩包"挡掉，
    结果把 AppImage/flatpak/deb/apk/ipa/dmg/exe/sh 这些**真游戏包**全拦了 25+8+21+21+13+21 个
    （掌机那侧要的 Linux 包正好全在被拦的那批里）。现在是"认得的包形态都要，副产品不要"。
    """
    low = name.lower()
    ext = os.path.splitext(low)[1]
    if ext in ROM_EXT or low.endswith((".xci.zip", ".nsp.zip", ".nro.zip")):
        return False, "红线：游戏镜像/密钥后缀"
    if re.search(r"(prod|title|console|device)[-_]?keys?\b", low):
        return False, "红线：名字就是密钥"
    if ext in SIDECAR_EXT or low.endswith((".sha256.sig", ".provenance.json")):
        return False, "校验/元数据副产品"
    if ext not in PKG_EXT:
        return False, "后缀没认出来"
    if size > ASSET_MAX_MB * 1048576:
        return False, "单资产超 %dMB" % ASSET_MAX_MB
    return True, "最新 release 资产"


def build_plan(wave=None, fresh=False):
    """问每个仓的全部 release（满一页的聚合库翻页），落成计划。

    11-05 改成**逐仓追加 + 可续跑 + 可分波**。三条理由，都是这晚上自己踩的：
      - 登记表从 2462 行涨到七千多行，一趟 plan 要烧一小时以上的 API，而这条 lane 从前晚开始
        反复在半路没命（计划只在结尾原子改名落盘，所以 7 次跑完全丢，盘上一直是 21:20 那版）。
      - 全库一轮跑不完不代表不能开工：按 tier 分波，先把 PS5/Switch2/掌机这几档问完。
      - "这仓真没发过 release"以前不留痕迹，每轮重跑都要为它再烧两次 API；现在落一行"不要"，
        下一轮直接跳过。
    """
    cat = load_catalog()
    reg_all = [e for e in read_reg() if (e.get("enable") or "1").strip() == "1"]
    if wave:
        reg = [e for e in reg_all if wave.lower() in (e.get("tier") or "").lower()]
        log("波：只处理 tier 含「%s」的仓 %d 个（启用仓共 %d 个）" % (wave, len(reg), len(reg_all)))
    else:
        reg = reg_all
    # 带版本前缀的行才认作"问过"；老行的枚举方式和现在不一样（只取 latest），整本作废重问。
    # 为什么按仓作废而不是逐行剔：一个仓要么全按新方式问过、要么没问过，留着半本
    # 旧行会让 pull 以为那些资产不存在。
    carried, stale = {}, set()
    for r in read_plan():
        k = r["repo"].lower()
        if ENUM_VER in (r.get("note") or ""):
            carried.setdefault(k, []).append(r)
        else:
            stale.add(k)
    for k in stale:
        carried.pop(k, None)
    if fresh:
        carried = {}
    if stale and not fresh:
        log("  上一代枚举方式的行涉及 %d 个仓，本轮按新枚举重问（同名资产只留最新一份）" % len(stale))
    keep, ask, carry_keys = [], [], set()
    for e in reg:
        k = e["repo"].lower()
        if k in carried:
            keep.extend(carried[k])
            carry_keys.add(k)
        else:
            ask.append(e)
    # 别的波/上次没重问的仓留下的行必须原样带走：换一波再落盘，等于把上一波的包从计划里删了
    for k, lst in carried.items():
        if k not in carry_keys:
            keep.extend(lst)
    log("计划开始：全量 release 列表（满一页的聚合库翻页），本次问 %d 个仓" % len(ask))
    os.makedirs(AREA, exist_ok=True)
    # 头一遍先把"这次不动的行"整体重写一遍（原子改名），之后逐仓追加。
    # 为什么不能只追加：--fresh 和字段数变化都得从干净表头开始，追加会让计划里留着上一代的行。
    tmp = PLAN + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=PLAN_HDR, delimiter="\t")
        w.writeheader()
        for r in keep:
            w.writerow(r)
    os.replace(tmp, PLAN)
    if keep:
        log("  复用旧计划：%d 行 / %d 个仓没再问 API" % (len(keep), len(carry_keys)))
    out = io.open(PLAN, "a", encoding="utf-8", newline="")
    writer = csv.DictWriter(out, fieldnames=PLAN_HDR, delimiter="\t")
    rows = []          # 内存里也留一份，只为最后那几行统计
    n_noasset = 0

    def emit(newrows):
        """一格一 flush：半路没命时盘上就是"已经真问到的那些"，下一轮从这条线接着问。"""
        for r in newrows:
            writer.writerow(r)
            rows.append(r)
        out.flush()

    def tick(i):
        if i % 25 == 0:
            log("  进度 %d/%d，本轮问到资产的仓 %d 个（已落盘 %d 行）"
                % (i, len(ask), len({r["repo"] for r in rows if r["why"] == "要"}),
                   len(keep) + len(rows)))

    def neg(repo, e, why):
        """负结果也带版本前缀：下一代枚举方式改了判据时，这一行照样会被重问，
        不会把"当时没问到"永久钉成"这仓没有包"。"""
        emit([{"repo": repo, "tier": e.get("tier", ""), "tag": "", "asset": "",
               "bytes": 0, "why": "不要", "asset_id": "",
               "cat": "1" if cat.get(repo) else "0", "note": ENUM_VER + why}])

    for i, e in enumerate(ask, 1):
        repo = e["repo"]
        f1 = {}
        rels = gh_api("repos/%s/releases?per_page=100" % repo, f1)
        if rels is None:
            # 只有 404（仓没了/改名）才配落负结果；链路类和限流都不落行，下一轮重问。
            if f1.get("kind") == "404":
                neg(repo, e, "仓库 404（release 列表问不到）")
                n_noasset += 1
            tick(i)
            continue
        pages = 1
        agg = len(rels) >= AGG_PAGE_TRIGGER
        while agg and pages < AGG_RELEASE_PAGES:
            more = gh_api("repos/%s/releases?per_page=100&page=%d" % (repo, pages + 1), f1)
            if not more:
                break
            rels = rels + more
            pages += 1
            if len(more) < AGG_PAGE_TRIGGER:
                break
        usable = [x for x in rels if not x.get("draft") and x.get("assets")]
        if not usable:
            neg(repo, e, "没有任何 release" if not rels else "有 release 但没有可用资产")
            n_noasset += 1
            tick(i)
            continue
        if agg:
            log("  %s 聚合库：翻 %d 页 / %d 个 release，可用 %d 个"
                % (repo, pages, len(rels), len(usable)))
        entry = cat.get(repo) or {}
        pat = entry.get("asset_pattern") or ""
        rx = None
        if pat:
            try:
                rx = re.compile(pat)
            except re.error:
                rx = None
        # 同名资产只留最新一份（API 按新→旧返回）：聚合库天天重发同名 zip，
        # 而落盘路径是 BIN_DIR/<owner>/<name>/<asset>，一个名字只有一个坑，收下层会互相覆盖。
        pairs, seen = [], set()
        for x in usable:
            for a in x.get("assets") or []:
                nm = a.get("name", "")
                if nm in seen:
                    continue
                seen.add(nm)
                pairs.append((x, a))
        newrows = []
        want_rows = []
        for x, a in pairs:
            name = a.get("name", "")
            size = int(a.get("size", 0) or 0)
            ok, why = want_asset(name, size)
            if not ok:
                newrows.append({"repo": repo, "tier": e.get("tier", ""), "tag": x.get("tag_name", ""),
                                "asset": name, "bytes": size, "why": "不要", "asset_id": "",
                                "cat": "1" if entry else "0", "note": ENUM_VER + why})
                continue
            hit = bool(rx and rx.search(name))
            base = (AGG_MARK + "%d 个 release 全枚举（同名留最新）" % len(usable)) if agg \
                else "最新 release 资产"
            want_rows.append((x, a, ENUM_VER + ("目录 asset_pattern 命中｜" + base if hit else base)))
        # 有 pattern 命中就只取命中的，避免同一款游戏下三个平台的包
        matched = [t for t in want_rows if "asset_pattern 命中" in t[2]]
        for x, a, why in (matched or want_rows):
            newrows.append({"repo": repo, "tier": e.get("tier", ""), "tag": x.get("tag_name", ""),
                            "asset": a.get("name", ""), "bytes": a.get("size", 0), "why": "要",
                            "asset_id": a.get("id", ""), "cat": "1" if entry else "0", "note": why})
        emit(newrows)
        tick(i)
    out.close()
    rows = keep + rows
    log("本轮 API：网络类失败 %d / 404 %d / 限流 %d｜问到没资产的仓 %d 个（已各落一行，下轮不再问）"
        % (API_FAIL["net"], API_FAIL["404"], API_FAIL["限流"], n_noasset))
    take = [r for r in rows if r["why"] == "要"]
    gb = sum(int(r["bytes"]) for r in take) / 1073741824.0
    if API_FAIL["net"] + API_FAIL["限流"] > max(20, len(ask) // 10):
        # 断网/限流这一轮都不会把"没问到"写成"没有包"（那种仓根本不落行，下一轮重问），
        # 但必须喊出来：否则看数字会以为这库就这么点资产。
        log("  警告：本轮链路/限流类 API 失败 %d 次（超过本次要问的 %d 个仓的十分之一），"
            "这些仓没落行，下一轮会重问；当前计划只覆盖真问到的部分"
            % (API_FAIL["net"] + API_FAIL["限流"], len(ask)))
    if not take and ask:
        # 一个资产都没问到，不当成"这批仓真没发过 release"：多半是 gh 链路/鉴权挂了。
        # 静默交出空计划比报错危险——pull 会"成功"地下 0 个文件。
        log("闸门：本轮 %d 个仓 0 个命中 release 资产（release 列表一个都没问到），判链路/鉴权故障，"
            "不当成'没有成品包'。先单独跑 gh api \"repos/<任一>/releases?per_page=3\" 看清原因" % len(ask))
        return rows
    per = {}
    for r in take:
        per[r["repo"]] = per.get(r["repo"], 0) + int(r["bytes"])
    over = {k: v for k, v in per.items() if v > REPO_MAX_MB * 1048576}
    log("计划：%s｜要 %d 个资产 / %.2f GB｜被拦 %d 个｜单仓超 %dMB 的 %d 个仓"
        % (os.path.basename(PLAN), len(take), gb, len(rows) - len(take), REPO_MAX_MB, len(over)))
    inc = [r for r in take if r["cat"] == "1"]
    log("  其中 RecompHub 目录点名的：%d 个资产 / %.2f GB（pull catalog 就只下这一批）"
        % (len(inc), sum(int(r["bytes"]) for r in inc) / 1073741824.0))
    for k, v in sorted(over.items(), key=lambda x: -x[1])[:8]:
        log("  超单仓预算：%s %.2f GB" % (k, v / 1073741824.0))
    free_gb = shutil.disk_usage(ROOT).free / 1073741824.0
    if gb > run_max_gb(free_gb):
        log("  闸门：整批 %.2f GB > 单轮预算 %.1f GB（盘余 %.1f GB − 预留 %.0f GB）。"
            "pull 会先按盘上已有量算待下量，真下不动时用 `pull <tier关键词>` 分波"
            % (gb, run_max_gb(free_gb), free_gb, RESERVE_GB))
    return rows


def audit(path):
    try:
        if path.lower().endswith(".zip"):
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                total = sum(i.file_size for i in z.infolist())
        elif path.lower().endswith((".tar.gz", ".tgz", ".tar")):
            with tarfile.open(path) as t:
                ms = t.getmembers()
                names = [m.name for m in ms]
                total = sum(m.size for m in ms)
        else:
            return (None, None, [])
    except Exception as ex:
        return (None, None, ["打不开:%s" % ex])
    low = [n.lower() for n in names]
    hits = sorted({s for s in SUSPECT for n in low if s in n})
    return (len(names), total, hits)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def cmd_plan(args):
    """plan [tier关键词] [--fresh]
    不给关键词就是全库续跑（只问计划里还没有的仓）；给关键词是按波跑，
    比如 `plan ps5` 先把 PS5 那档问完。--fresh 才是推倒重问（贵，几千次 API）。"""
    args = list(args or [])
    fresh = "--fresh" in args
    wave = next((a for a in args if not a.startswith("--")), None)
    build_plan(wave=wave, fresh=fresh)
    return 0


def split_by_repo_budget(take):
    """按单仓预算切一刀，返回 (留下的行, 被拦的仓, 豁免的聚合库仓)。
    单仓 8 GB 这道闸拦的是"一款游戏出 win/linux/apk/mac 四个包"那种重复；
    聚合库（PortMaster 一个 release 一个端口）超 8 GB 是它该有的体积，放行。"""
    per = {}
    for r in take:
        per[r["repo"]] = per.get(r["repo"], 0) + int(r["bytes"])
    agg_repos = {r["repo"] for r in take if AGG_MARK in (r.get("note") or "")}
    dropped = {k for k, v in per.items() if v > REPO_MAX_MB * 1048576 and k not in agg_repos}
    return [r for r in take if r["repo"] not in dropped], dropped, agg_repos


def cmd_pull(args):
    # 范围按用户 11-04 的要求放开："获取到所有的这些库里的游戏" —— 默认下整本计划，
    # `pull catalog` 那一档仍然留着，只下 RecompHub 目录点名的仓库，用来在链路差时先保小样。
    # 早期这里写过"全量 18 GB 太慢所以只下目录点名的 3.17 GB"，那是我对链路的妥协，不是你的要求。
    args = list(args or [])
    cat_only = "catalog" in args
    wave = next((a for a in args if a != "catalog" and not a.startswith("--")), None)
    if not os.path.exists(PLAN):
        build_plan()
    take = [r for r in read_plan() if r["why"] == "要"]
    take, cut = collapse_repeat_releases(take)
    for repo, n, ntag, uniq, gb, drop_gb, kept in cut:
        log("截断：%s %d 个 release / %d 行 / %.1f GB，名字重样率 %.0f%% —— 同一款游戏反复出新 build，"
            "只留 %s 这 %d 版，省下 %.1f GB"
            % (repo, ntag, n, gb, uniq * 100, ", ".join(kept), len(kept), drop_gb))
    if cut:
        log("截断合计：%d 个重发型仓被截，这一轮的范围从历史全量收到 %d 个 / %.1f GB"
            "（要看全历史就把 FAM_KEEP_TAGS 调大重跑；每个 release 装不同内容的聚合库不受影响）"
            % (len(cut), len(take), sum(int(r["bytes"]) for r in take) / 1073741824.0))
    if wave:
        n0, g0 = len(take), sum(int(r["bytes"]) for r in take) / 1073741824.0
        take = [r for r in take if wave.lower() in (r.get("tier") or "").lower()]
        log("范围：只取 tier 含「%s」的 %d/%d 个资产（%.2f GB / 全计划 %.2f GB）"
            % (wave, len(take), n0, sum(int(r["bytes"]) for r in take) / 1073741824.0, g0))
    if cat_only:
        n0, g0 = len(take), sum(int(r["bytes"]) for r in take) / 1073741824.0
        take = [r for r in take if (r.get("cat") or "0") == "1"]
        log("范围：只取 RecompHub 目录点名的仓库，%d/%d 个资产（%.2f GB / 全量 %.2f GB）"
            % (len(take), n0, sum(int(r["bytes"]) for r in take) / 1073741824.0, g0))
    take, dropped, agg_repos = split_by_repo_budget(take)
    if agg_repos:
        log("范围：聚合库 %d 个仓不受单仓 %d MB 限制（%s）"
            % (len(agg_repos), REPO_MAX_MB, ", ".join(sorted(agg_repos)[:4])))
    if dropped:
        log("范围：单仓超 %d MB 被拦 %d 个仓（%s）——这些是'同一款游戏多平台包'那种，要放开就人工圈"
            % (REPO_MAX_MB, len(dropped), ", ".join(sorted(dropped)[:4])))
    tot = sum(int(r["bytes"]) for r in take) / 1073741824.0
    # 闸门按"这一轮真要写多少字节"算，不按整本计划算。
    # 11-05 实测：登记表涨到 7718 行后计划变成 4468 个资产 / 247.32 GB，其中已经在盘上的
    # 那 31.97 GB 一轮都不用下——按整本算的话这条闸门会把 pull 永久锁死，
    # 而它本意是"别一口气把盘写爆"，不是"计划一大就不许干活"。
    pending = []
    for r in take:
        owner, name = r["repo"].split("/", 1)
        dst = os.path.join(BIN_DIR, owner, name, r["asset"])
        if os.path.isfile(dst) and os.path.getsize(dst) == int(r["bytes"]):
            continue
        pending.append(r)
    # 顺序按"每个仓先拿最大那块包，仓与仓轮流"排，见 order_by_breadth()
    pending = order_by_breadth(pending)
    pgb = sum(int(r["bytes"]) for r in pending) / 1073741824.0
    free_gb = shutil.disk_usage(ROOT).free / 1073741824.0
    log("盘量：F 盘当前余 %.1f GB｜计划要下 %d 个 / %.2f GB，其中盘上已有 %d 个、真要下 %d 个 / %.2f GB"
        % (free_gb, len(take), tot, len(take) - len(pending), len(pending), pgb))
    budget_gb = run_max_gb(free_gb)   # 只有一个口径：盘余减预留，不再另开一个 20 GB 的数
    capped = pgb > budget_gb          # 本轮被预算截断 = 队列没下完，不许写成"全落地"
    if pgb > budget_gb:
        # 预算不够不等于这轮不许干活。11-05 实测：计划涨到 492 GB（PortMaster 全 release 枚举后）
        # 而盘只剩 281 GB，原来的"整批超限就 return 1"会把 pull 永久锁死——一个字节都不下，
        # 而它本意只是"别把盘写爆"。改成在 breadth 顺序上贪心塞进预算（见 fit_budget），
        # 缺口点名报出来，剩下的等传网盘清盘后下一轮接着截（计划/台账都可续跑，截了不丢）。
        chosen, skipped, acc = fit_budget(pending, budget_gb)
        key = lambda r: (r["repo"], r["tag"], r["asset"])
        chosen_keys = {key(r) for r in chosen}
        pend_keys = {key(r) for r in pending}
        take = order_by_breadth([r for r in take
                                 if key(r) not in pend_keys or key(r) in chosen_keys])
        log("闸门：真要写 %.2f GB > 预算 %.1f GB（盘余 %.1f GB，给别的线留 %.0f GB），"
            "本轮在\"每仓先拿最大那块\"的顺序里塞进 %d 个 / %.2f GB｜被跳过的 %d 个 / %.2f GB 下一轮再接"
            % (pgb, budget_gb, free_gb, RESERVE_GB, len(chosen), acc, skipped, pgb - acc))
        if not chosen:
            log("闸门：预算 %.1f GB 连最小的一个包（%.2f GB）都放不下——这轮不动盘，先传网盘或清盘"
                % (budget_gb, int(min(pending, key=lambda x: int(x["bytes"]))["bytes"]) / 1073741824.0))
            return 1
    os.makedirs(BIN_DIR, exist_ok=True)
    tot = sum(int(r["bytes"]) for r in take) / 1073741824.0
    log("开始下载：%d 个资产 / %.2f GB（其中本轮真下 %d 个）"
        % (len(take), tot, len(chosen) if pgb > budget_gb else len(pending)))
    # 台账逐格落盘，不攒到最后一次写：11-04 这个任务两次在半路没命（一次我误杀父进程，
    # 一次原因不明），跑了两小时攒在内存里的 sha256/解包复检跟着一起没了，盘上还查不到下到第几个。
    # 先重写表头再逐行追加，中断留下的台账就是"已经真下完的那些"，重跑会覆盖同名行。
    os.makedirs(AREA, exist_ok=True)
    # 重写表头之前先保一份上一轮的。逐格落盘的代价就在这儿：表头一清，这一轮如果半路没命，
    # 上一轮记的 sha256/复检结果跟着一起没了。11-04 20:15 我用一条 NameError 现场演示了一次
    # （29 行掉到 25 行），而 py_compile 拦不住这种只在跑到那一行才炸的毛病。
    if os.path.exists(LEDGER):
        shutil.copyfile(LEDGER, LEDGER_PREV)
    with io.open(LEDGER, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(LEDGER_HDR) + "\n")
    done = skip = fail = held = 0
    streak = 0
    yielded = False
    def put(rec):
        with io.open(LEDGER, "a", encoding="utf-8", newline="") as fh:
            fh.write("\t".join(str(rec.get(k, "")).replace("\t", " ").replace("\n", " ")
                               for k in LEDGER_HDR) + "\n")

    # 顺序不再在这里改：take / pending 都已经过 order_by_breadth()
    # （每仓先拿最大那块、仓与仓轮流）。这里再 sort 一次会把那个顺序抹平。
    for i, r in enumerate(take, 1):
        owner, name = r["repo"].split("/", 1)
        spd = ""
        d = os.path.join(BIN_DIR, owner, name)
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, r["asset"])
        # 幂等依据是"本地字节数 == API 报的 size"，不是"文件存在"：上次中断会留半个文件。
        if os.path.isfile(dst) and os.path.getsize(dst) == int(r["bytes"]):
            state = "已相符"
            skip += 1
            streak = 0
        else:
            # 每格开工前重新看一眼盘。本轮预算是开头按当时的盘余算的，而端口包那条线
            # 正往同一块 F 盘里下载并解包（tar 中转包和解出来的树各占一份，实测 40 GB 上下）。
            # 两边被盘挤爆的代价不对称：这里停的只是没下完的队列，下一轮接着截；那边丢的是
            # 已在途又不能续传的整包。所以盘一紧，先收工的是这一条线。
            free_now = shutil.disk_usage(ROOT).free / 1073741824.0
            if free_now < RESERVE_GB:
                yielded = True
                log("闸门：第 %d/%d 个 %s/%s 还没开工，盘余已掉到 %.1f GB（给别的线留 %.0f GB）"
                    "——本轮到此收工，已下的都在台账里，剩下的下一轮再接"
                    % (i, len(take), r["repo"], r["asset"], free_now, RESERVE_GB))
                break
            if os.path.isfile(dst):
                os.remove(dst)
            # 时间按体积给，不给一小时：11-04 19:47–20:04 实测 release-assets 会掉到
            # ~19 KB/s（量一个 18 MB 的包花了 11 分钟），原来那个 timeout=3600 意味着
            # 一个卡住的包能吃掉一小时，55 个包就是两天。现在按 300 KB/s 的速度下限给时间，
            # 慢过这条线就当失败记一格，让熔断器（连 6 个失败就停）真的能熔断。
            t0 = time.time()
            allow = max(180, int(r["bytes"]) // 300000)
            rc, code, cs = curl_asset(asset_url(r["repo"], r["tag"], r["asset"]), dst, allow)
            err = "" if rc == 0 else "curl rc=%d http=%s" % (rc, code)
            if rc == 124:
                err = "低于 300 KB/s 的速度下限：%d 秒没下完 %.1f MB，这一格本轮放弃" % (
                    allow, int(r["bytes"]) / 1048576.0)
            if rc != 0:
                # 地址是我自己拼的，编码/带斜杠的 tag 万一和 API 给的不一样，就退回问过 API 的那条路。
                # 实测这条路的下载速度只有 curl 的 1/100（见第 23 条），所以它只当兜底，不当主力。
                try:
                    p = subprocess.run([GH, "release", "download", r["tag"], "-R", r["repo"],
                                        "--pattern", r["asset"], "-D", d],
                                       capture_output=True, env=env(), timeout=allow)
                    rc2 = p.returncode
                    err2 = (p.stderr or b"").decode("utf-8", "replace")[:150]
                except subprocess.TimeoutExpired:
                    rc2 = 124
                    err2 = "gh 兜底也超 %d s" % allow
                if rc2 == 0 and os.path.isfile(dst):
                    log("  兜底命中 %s/%s：curl 报 %s，gh 下下来了——这条的 URL 拼法要记一笔"
                        % (r["repo"], r["asset"], err))
                    rc, code, cs, err = 0, "200", 0, ""
                else:
                    rc, err = rc2, err or err2
            if rc != 0 or not os.path.isfile(dst):
                # 半截文件当场删掉：幂等判据是"字节数==API size"，重跑会当没下过，
                # 但网盘那一档是照后缀收 *.zip 的，留半个包在池子里就等于往外传坏包。
                if os.path.isfile(dst):
                    os.remove(dst)
                fail += 1
                streak += 1
                put(dict(r, sha256="", state="下载失败", audit="",
                         got_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), note=err))
                # 熔断：连着 6 个都失败，不是这些仓库没资产，是链路断了
                # （11-04 实测 release-assets.githubusercontent.com 会单独不通，而 api 还通）。
                # 没有这一条，526 个资产会一个个撞满超时，跑三小时交出一份"全失败"台账。
                if streak >= 6:
                    log("熔断：连续 %d 个下载失败，判链路断了，停在这（第 %d/%d 个）。"
                        "最后一条错误：%s" % (streak, i, len(take), err))
                    break
                log("  失败 %s/%s：%s" % (r["repo"], r["asset"], err))
                continue
            if os.path.getsize(dst) != int(r["bytes"]):
                fail += 1
                bad_sz = os.path.getsize(dst)
                os.remove(dst)   # 体积不符就是半个包，同样不许它留在池子里
                log("  体积不符 %s/%s：本地 %d，API %s（半个包已删）" % (r["repo"], r["asset"], bad_sz, r["bytes"]))
                put(dict(r, sha256="", state="体积不符", audit="",
                         got_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), note=""))
                continue
            state = "新下"
            done += 1
            streak = 0
            spd = "，实测 %.2f MB/s" % ((cs / 1048576.0) if cs else
                                       int(r["bytes"]) / 1048576.0 / max(time.time() - t0, 0.5))
        dg = sha256(dst)
        n, uz, hits = audit(dst)
        note = ""
        if hits:
            hd = os.path.join(HOLD_DIR, owner, name)
            os.makedirs(hd, exist_ok=True)
            hdst = os.path.join(hd, r["asset"])
            shutil.move(dst, hdst)
            held += 1
            note = "命中原厂数据特征，挪到待复核：%s" % "; ".join(hits[:5])
            log("  红线复检：%s/%s → 待复核（%s）" % (r["repo"], r["asset"], ", ".join(hits[:3])))
        if hits:
            state = "待复核"
        put(dict(r, sha256=dg, state=state, audit="%s 成员/%.0fMB" % (n, (uz or 0) / 1e6),
                 got_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), note=note))
        # 每个资产报一行，不攒到整十：11-04 两次把这任务当成死了——它其实只是在下一个
        # 几百 MB 的包，而屏幕上二十分钟不出一个字。进度可见性本身就是判活的手段。
        log("  %d/%d %s %s/%s（%.1f MB%s，复检 %s）" % (
            i, len(take), state, r["repo"], r["asset"], int(r["bytes"]) / 1048576.0, spd,
            (n and "%d 成员" % n) or "格式不扫"))
    log("完成：新下 %d / 已相符 %d / 失败 %d / 挪待复核 %d" % (done, skip, fail, held))
    n_led = max(sum(1 for _ in io.open(LEDGER, encoding="utf-8")) - 1, 0)
    log("台账：%s（%d 行，逐格落盘）" % (os.path.basename(LEDGER), n_led))
    if fail == 0 and (yielded or capped):
        log("本轮 0 失败，但队列没下完（%s）——退出码给 1 是让循环接着补剩下的，不等于失败"
            % ("；".join([x for x in ("预算截断，塞进 %.1f GB" % budget_gb if capped else "",
                                      "盘余跌破预留提前收工" if yielded else "") if x])))
    return 0 if fail == 0 and not yielded and not capped else 1


def cmd_verify(_a):
    """不联网：逐格量盘上的文件，产出 state。下载失败/体积不符在这里会露出来。"""
    take = [r for r in read_plan() if r["why"] == "要"]
    # 和 pull 用同一档范围：不截的话 verify 会把三个 Cataclysm 的 3 万条历史 build
    # 全报成"缺"，对账数字就没法看了。
    take, cut = collapse_repeat_releases(take)
    if cut:
        log("对账范围同 pull：截了 %d 个重发型仓，剩下 %d 个 / %.1f GB 逐格量盘"
            % (len(cut), len(take), sum(int(r["bytes"]) for r in take) / 1073741824.0))
    ok = miss = bad = held = 0
    rows = []
    for r in take:
        owner, name = r["repo"].split("/", 1)
        dst = os.path.join(BIN_DIR, owner, name, r["asset"])
        hd = os.path.join(HOLD_DIR, owner, name, r["asset"])
        if os.path.isfile(hd):
            held += 1
            rows.append(dict(r, sha256=sha256(hd), state="待复核", audit="", got_at="",
                             note="盘上有但不在成品包池"))
        elif os.path.isfile(dst) and os.path.getsize(dst) == int(r["bytes"]):
            ok += 1
            rows.append(dict(r, sha256=sha256(dst), state="相符", audit="%s" % (audit(dst)[2] or ""),
                             got_at="", note=""))
        elif os.path.isfile(dst):
            bad += 1
            rows.append(dict(r, sha256="", state="体积不符", audit="", got_at="", note=""))
        else:
            miss += 1
            rows.append(dict(r, sha256="", state="缺档", audit="", got_at="", note=""))
    log("verify：相符 %d / 缺档 %d / 体积不符 %d / 待复核 %d（计划里要 %d 个）"
        % (ok, miss, bad, held, len(take)))
    with io.open(LEDGER, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_HDR, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow({k: str(r.get(k, "")).replace("\t", " ") for k in LEDGER_HDR})
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    rest = sys.argv[2:]
    fn = {"plan": cmd_plan, "pull": cmd_pull, "verify": cmd_verify}.get(cmd)
    if fn is None:
        print("用法：plan [tier关键词] [--fresh] / pull [catalog|tier关键词] / verify")
        return 2
    if not hold_lock(cmd):
        return 1
    return fn(rest)


if __name__ == "__main__":
    sys.exit(main())
