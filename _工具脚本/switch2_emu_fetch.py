# -*- coding: utf-8 -*-
r"""Switch 2 模拟器仓库镜像器。

为什么要它：2026-02 任天堂对 GitHub 上几乎所有 Switch 模拟器发了一轮 DMCA（400+ 仓库），
Citron / Eden / Suyu / Sudachi / MeloNX / Ryujinx 的官方仓库全被清空，现在活跃的这波
（Eglantine 2026-10-29 才开仓）同样随时会没。所以按仓库连**完整提交历史**镜像到本地，
而不是只抓一个 zipball——历史没了就真没了。

红线照旧：只收源码。仓库里如果 commit 了密钥/固件/游戏镜像（prod.keys、title.keys、
*.nsp/*.xci/*.nca 这类），检出后当场删掉并在台账点名，不留在盘上，更不外发。

这一份同时服务两个档（MIRROR_AREA 环境变量点名，默认 Switch2模拟器）：
「成品移植游戏库」的登记表比 Switch2 那档多一列 policy——仓库大小从几十 MB 到 37GB
（PortMaster-New）都有，一刀切连历史 clone 会把盘吃穿，所以按元数据分 full/blobless/meta。

    MIRROR_AREA=Switch2模拟器 py -3 _工具脚本/switch2_emu_fetch.py all     # 缺的补、旧的更新（幂等）
    MIRROR_AREA=成品移植游戏库 py -3 _工具脚本/switch2_emu_fetch.py all    # 按 policy 分档镜像
    py -3 _工具脚本/switch2_emu_fetch.py bundle     # 每仓打一个整仓 bundle，供网盘推
    py -3 _工具脚本/switch2_emu_fetch.py ledger     # 不联网，重扫本地重算台账
    py -3 _工具脚本/switch2_emu_fetch.py sweep      # 用当前红线判据重扫已镜像的工作树并处置
    py -3 _工具脚本/switch2_emu_fetch.py list       # 看登记表
"""
import csv
import datetime as dt
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))          # F:\开源掌机教程
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import net_proxy        # 代理口不写死（7890→7891 换过一次），见该文件
AREA_NAME = os.environ.get("MIRROR_AREA", "Switch2模拟器")
AREA = os.path.join(ROOT, "06-资讯监控", AREA_NAME)
REG = os.path.join(AREA, "仓库登记表.tsv")
META = os.path.join(AREA, "仓库元数据.tsv")
SRC = os.path.join(AREA, "源码")
LEDGER = os.path.join(AREA, "抓取台账.tsv")
LOG = os.path.join(AREA, "抓取日志.txt")
BUNDLE_DIR = os.path.join(AREA, "整仓bundle")
BUNDLE_LEDGER = os.path.join(AREA, "bundle台账.tsv")
BUNDLE_HDR = ["repo", "file", "head", "bytes", "sha256", "verify", "made_at"]

GIT = shutil.which("git") or r"D:\Git\cmd\git.exe"
GH = shutil.which("gh") or os.path.expanduser(r"~\.workbuddy\gh-cli\bin\gh.exe")

HDR = ["repo", "url", "tier", "branch", "commit", "commit_at", "stars", "license",
       "worktree_files", "worktree_bytes", "gitdir_bytes", "suspect_files",
       "largest_file", "fetched_at", "note"]

# 密钥/固件/游戏本体：这些不是源码，检出到就删。
# 判据只看"像不像二进制资产"，不看文件名里有没有 firmware 这种词——上一版就是栽在
# 这里：模拟器自己的固件下载界面源码（FirmwareAvatarAdapter.kt、ic_firmware.xml）被当
# 固件删掉 12 个文件。源码后缀一律放行。
ROM_EXT = {".xci", ".nsp", ".nsz", ".nca", ".nro", ".nkd", ".tik", ".keys"}
# 换了名字的打包体：媒体后缀 + 体积够大才算
# 后半截是 11-04 给「成品移植游戏库」补的：这批仓库是游戏移植体，仓库里直接 commit
# 原厂音视频容器的概率比模拟器仓库高得多（Bink/Smacker/RAD 视频、DOOM WAD、MPQ、CHD），
# 后缀表里没有它们，90MB 的 .bk2 就会原样留在盘上——单测就是这么抓出来的。
# 仍然只在 >BIG 时才动手，免得误杀自制的小样本文件。
MEDIA_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".xz", ".bin", ".dat", ".iso",
             ".bk2", ".usm", ".sgi", ".pck", ".fpk", ".big", ".mpq", ".wad",
             ".chd", ".cso", ".gcm", ".xa", ".adb"}
BIG = 80 * 1024 * 1024
# 本轮删了什么，按仓库记着：台账最后会重扫一遍工作树，重扫时文件已经没了，
# 不记这笔的话"删过密钥/镜像"这件事在台账里查不到。
PURGED = {}
# 这一轮没能确认远端 HEAD 的仓，按仓库记着原因。盘上的旧快照是真的，但"镜像=最新"这句话
# 不能说 —— 台账里要能查出哪一格是断链时留下的、比远端慢多少未知。
UNCONFIRMED = {}
# 名字里有 firmware/keys 但带这些后缀的，是代码或文档，不是资产
SOURCE_EXT = {
    ".kt", ".java", ".xml", ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".py", ".rs",
    ".go", ".swift", ".m", ".mm", ".rb", ".js", ".ts", ".tsx", ".jsx", ".json",
    ".md", ".txt", ".rst", ".html", ".css", ".scss", ".yml", ".yaml", ".toml",
    ".cfg", ".conf", ".ini", ".properties", ".gradle", ".cmake", ".in", ".po",
    ".sh", ".bash", ".ps1", ".bat", ".cmd", ".glsl", ".hglsl", ".frag", ".vert",
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".editorconfig",
    ".gitignore", ".gitattributes", ".patch", ".diff", ".desktop", ".service",
    ".ui", ".qml", ".plist", ".strings", ".resx", ".rc", ".def", ".excalidraw",
}
# 名字本身就说明是资产的文件（不靠后缀）
NAME_RE = re.compile(r"(^|[/\\_-])(prod|title|console|device)[/\\_-]?keys?\b", re.I)

# 换名的打包体：后缀不在 MEDIA_EXT 里，但文件头就是压缩包签名。
# 这条是 11-05 补的，起因是 PortsMaster-MV/PortMaster-MV-New 那个 21,347 文件的树报了
# suspect=0——可它最大的文件 ports/chaoresortisland/chaoresortisland/chaoresortisland.port
# 实测 94,854,155 字节，头四字节 PK\x03\x04，第一条目录项 lib/arm64-v8a/libyoyo.so：
# 一个把后缀改成 .port 的安卓安装包。只看后缀的判据对它完全瞎，而这批树里还有多少
# 这种"披着脚本外衣的成品包"没人知道——所以判据从后缀升级到字节。
CONTAINER_MAGIC = [(b"PK\x03\x04", "zip/apk"), (b"7z\xbc\xaf\x27\x1c", "7z"),
                   (b"Rar!\x1a\x07", "rar"), (b"\x1f\x8b\x08", "gz"),
                   (b"BZh", "bzip2")]


def container_kind(head):
    for sig, name in CONTAINER_MAGIC:
        if head.startswith(sig):
            return name
    return ""


def suspect_reason(rel, size, head=b""):
    """返回嫌疑理由；不是嫌疑返回空串。head 是文件前 16 字节，只在够大的文件上才值得读。"""
    low = rel.lower()
    ext = os.path.splitext(low)[1]
    if ext in ROM_EXT or low.endswith(".nro.zip"):
        return "游戏镜像/密钥后缀"
    if NAME_RE.search(low) and ext not in SOURCE_EXT:
        return "名字就是 keys 资产"
    if ext in MEDIA_EXT and size > BIG:
        return "大媒体包（%d MB）" % (size // 1048576)
    # 后缀不在媒体表里、但字节证明它就是个打包体：这是改名躲判据的形状。
    if size > BIG and head:
        kind = container_kind(head)
        if kind:
            return "换名的打包体（%s，%d MB，后缀 %s）" % (kind, size // 1048576, ext or "无")
    # dump 必须是独立词：不带词边界时 objdump / objdump.exe 这类仓库自带的交叉工具链二进制会被
    # 当成"游戏 dump"删掉。11-04 实测 eandis/SDOJ-Recomp 的两个 objdump（1.6 MB + 8.8 MB）就是被
    # 上一版误杀的，而台账查不到这件事：文件不在工作树，只剩索引里两条 D 标记，靠 _audit_purge_fp.py 才翻出来。
    if re.search(r"(firmware|\.nro\b|(?<![a-z0-9])dump(?![a-z0-9]))", low) and ext not in SOURCE_EXT and size > 1024 * 1024:
        return "疑似固件/镜像 blob（%d MB）" % (size // 1048576)
    return ""



def log(msg):
    line = "[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    d = os.path.dirname(LOG)
    os.makedirs(d, exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


_PROXY_OK = None


def proxy_alive():
    """代理口是不是活着 —— 口不再写死，见 net_proxy.py（11-04 Clash Verge 从 7890 换到 7891，
    而 shell 继承的 HTTPS_PROXY 和 ~/.gitconfig 里的 http.proxy 还挂着旧口）。"""
    global _PROXY_OK
    if _PROXY_OK is None:
        _PROXY_OK = net_proxy.alive()
        log(net_proxy.describe())
    return _PROXY_OK


def run(cmd, timeout=1800):
    env = proxy_env()
    env["GIT_TERMINAL_PROMPT"] = "0"
    # git 还有一层 ~/.gitconfig 里的 http.proxy，环境变量清不掉它：
    # 两种状态都要显式 -c 覆盖 —— 走新口时要盖掉旧口，直连时要盖掉它写死的那个（11-04 就是这么全败）。
    if cmd and cmd[0] == GIT:
        cmd = [GIT] + net_proxy.git_flags() + cmd[1:]
    return subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)


def proxy_env():
    """代理只在活着的时候用，而且用探到的那个口。代理一停或口不对，写死 HTTPS_PROXY
    会让每一条 git/gh 命令直接失败，而 GitHub 本机直连其实是通的（11-04 就踩在这里）。"""
    return net_proxy.env()


def read_reg():
    with io.open(REG, encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh, delimiter="\t")]


def gh_meta(repo):
    """star/许可/默认分支/最近推送，从 GitHub API 现取，不写死。

    超时给 60 秒而不是默认的 1800：这一条是给台账补 stars 用的装饰性字段，
    链路断的时候不该让它把整轮重扫拖住（11-04 20:0x 就卡在 92 次 gh api 上）。
    """
    r = run([GH, "api", "repos/" + repo], timeout=60)
    if r.returncode != 0:
        return {}
    import json
    try:
        return json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        return {}


_META_CACHE = None


def meta_cache():
    """登记那一轮抓过的 star/许可就在盘上的 仓库元数据.tsv 里，别为每个仓再现取一遍。

    为什么值得省：镜像与台账重扫都要给每行补 meta，全部现取就是 N 次 api 调用。
    11-04 20:0x 实测主站断时，这一步（92 次 gh api）能把一轮重扫拖成十几分钟，
    而它拖出来的只有 stars 一列 —— commit、文件数、体积全是盘上就能算的。
    Switch2 那档没有 仓库元数据.tsv，meta_for 会自己退回现取，不会把 stars 写成空。
    """
    global _META_CACHE
    if _META_CACHE is None:
        _META_CACHE = {}
        if os.path.isfile(META):
            with io.open(META, encoding="utf-8") as fh:
                for r in csv.DictReader(fh, delimiter="\t"):
                    lic = (r.get("license") or "").strip()
                    _META_CACHE[r["repo"].strip()] = {
                        "stargazers_count": (r.get("stars") or "").strip(),
                        "license": ({"spdx_id": lic} if lic and lic != "NONE" else None),
                        "default_branch": (r.get("default_branch") or "").strip(),
                        "pushed_at": (r.get("pushed_at") or "").strip()}
    return _META_CACHE


def meta_for(repo):
    return meta_cache().get(repo) or gh_meta(repo)


def remote_sha(url):
    r = run([GIT, "ls-remote", url, "HEAD"], timeout=120)
    if r.returncode != 0:
        return ""
    out = r.stdout.decode("utf-8", "replace").split()
    return out[0] if out else ""


def local_head(path):
    r = subprocess.run([GIT, "-C", path, "rev-parse", "HEAD"], capture_output=True)
    return r.stdout.decode().strip() if r.returncode == 0 else ""


def local_branch(path):
    r = subprocess.run([GIT, "-C", path, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True)
    return r.stdout.decode().strip() if r.returncode == 0 else ""


def commit_at(path):
    r = subprocess.run([GIT, "-C", path, "log", "-1", "--format=%cI"], capture_output=True)
    return r.stdout.decode("utf-8", "replace").strip()[:10] if r.returncode == 0 else ""


def dir_bytes(path):
    total = 0
    for _dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(_dp, f))
            except OSError:
                pass
    return total


def scan_worktree(path):
    """数文件、找疑似密钥/ROM、记最大文件。返回 (文件数, 字节, [嫌疑], 最大文件名, 最大字节)。"""
    files = 0
    total = 0
    suspect = []
    largest = ("", 0)
    for dp, dn, fn in os.walk(path):
        if os.path.basename(dp) == ".git":
            dn[:] = []
            continue
        for f in fn:
            p = os.path.join(dp, f)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            files += 1
            total += sz
            rel = os.path.relpath(p, path).replace("\\", "/")
            why = suspect_reason(rel, sz)
            # 后缀没命中时才去读文件头，而且只在"大到值得怀疑"时读——
            # 21,347 个文件每个都 open 一遍会把扫盘拖成这一轮最慢的一段。
            if not why and sz > BIG:
                try:
                    with open(p, "rb") as fh:
                        why = suspect_reason(rel, sz, fh.read(16))
                except OSError:
                    pass
            if why:
                suspect.append((rel + "（" + why + "）", sz))
            if sz > largest[1]:
                largest = (rel, sz)
    return files, total, suspect, largest


def purge_suspect(path, suspect):
    """从工作树删掉检出的密钥/固件/镜像，并同步索引（update-index --force-remove），
    这样 git status 不会长期挂着一堆"未提交删除"。历史对象里还有没有是另一回事，
    台账会点名删了什么。"""
    removed = []
    for rel, _sz in suspect:
        clean = rel.split("（")[0]
        p = os.path.join(path, clean)
        try:
            os.remove(p)
            subprocess.run([GIT, "-C", path, "update-index", "--force-remove", clean],
                           capture_output=True)
            removed.append(rel)
        except OSError:
            pass
    return removed


def row_of(entry, meta, extra_note=""):
    path = os.path.join(SRC, entry["repo"].replace("/", "__"))
    files, total, suspect, largest = scan_worktree(path)
    note = entry.get("note", "")
    if suspect:
        note += "｜工作树里现存 %d 个疑似密钥/固件/镜像：%s" % (
            len(suspect), "; ".join(s for s, _ in suspect[:4]))
    gone = PURGED.get(entry["repo"]) or []
    if gone:
        note += "｜检出时删掉 %d 个：%s" % (len(gone), "; ".join(gone[:4]))
    miss = UNCONFIRMED.get(entry["repo"])
    if miss:
        note += "｜本轮未确认远端 HEAD（%s），盘上是之前的快照" % miss
    if extra_note:
        note += "｜" + extra_note
    return {"repo": entry["repo"], "url": "https://github.com/" + entry["repo"],
            "tier": entry.get("tier", ""), "branch": local_branch(path),
            "commit": local_head(path), "commit_at": commit_at(path),
            "stars": str(meta.get("stargazers_count", "")),
            "license": (meta.get("license") or {}).get("spdx_id", "") if meta.get("license") else "NONE",
            "worktree_files": str(files), "worktree_bytes": str(total),
            "gitdir_bytes": str(dir_bytes(os.path.join(path, ".git"))),
            "suspect_files": str(len(suspect)), "largest_file": "%s (%d B)" % largest if largest[0] else "",
            "fetched_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "note": note}


def fetch(entry, rows):
    repo = entry["repo"]
    path = os.path.join(SRC, repo.replace("/", "__"))
    url = "https://github.com/" + repo
    meta = meta_for(repo)
    # 认"有 HEAD"才算下过，不认"目录存在"：上次 clone 被中途打断会留下一个空壳目录，
    # 拿 .git 是否存在当幂等依据会永久判失败（11-04 就踩在 notsapinho 上）。
    if not local_head(path):
        if os.path.isdir(path):
            # git 允许 clone 进"已存在的空目录"，非空就先点名，别默默盖别人东西
            leftovers = os.listdir(path)
            if leftovers:
                # 但有一种残留是这台工具自己造的：clone 被中途打断，只剩下一个 .git 壳，
                # 没有 HEAD、也没有任何工作树文件。这种不处理就会"跳过不动"，那个仓从此
                # 再也不会被镜像——主站抽风的这半小时里正好会批量造出这种壳。
                if leftovers == [".git"]:
                    log("  %s 是上次 clone 打断留下的空壳（只有 .git，无 HEAD），清掉重下" % repo)
                    # 不能用 ignore_errors=True：22:12:27 实测它会让日志连着打两件相反的事
                    # ——先"清掉重下"、再"跳过不动"，因为 rmtree 静默失败了（句柄被别的进程占着），
                    # 而我看不出是哪一种。删不动就点名原因，这一格下轮再试。
                    try:
                        shutil.rmtree(path)
                    except OSError as ex:
                        log("  空壳没删掉：%s：%s" % (type(ex).__name__, str(ex)[:140]))
                        return False
                if os.path.isdir(path):
                    log("  %s 目录已存在但不是仓库，且有 %d 个残留条目，跳过不动：%s"
                        % (repo, len(os.listdir(path)), path))
                    return False
        os.makedirs(SRC, exist_ok=True)
        # policy=blobless：commit 图谱和 HEAD 都要，历史 blob 先不来。
        # 这类仓库单个就有几 GB（如 PortsMaster/PortMaster-New 的 .git 37GB），
        # 连 blob 全下会把 F 盘吃穿，而防 DMCA 要的"历史不丢"靠的是 commit 图。
        filt = ["--filter=blob:none"] if (entry.get("policy") or "full") == "blobless" else []
        log("clone %s（%s）" % (repo, "只到 commit 树，blob 按需" if filt else "连历史，可能几分钟"))
        r = run([GIT, "clone"] + filt + [url, path], timeout=3600)
        if r.returncode != 0:
            log("  失败：%s" % r.stderr.decode("utf-8", "replace")[:200])
            return False
    else:
        want = remote_sha(url)
        have = local_head(path)
        if want and have == want:
            log("跳过 %s（HEAD 就是最新 %s）" % (repo, have[:9]))
            rows.append(row_of(entry, meta, "已是最新"))
            return True
        log("更新 %s %s -> %s" % (repo, have[:9], want[:9]))
        r = run([GIT, "-C", path, "fetch", "--all", "--tags", "--prune"], timeout=3600)
        if r.returncode == 0:
            run([GIT, "-C", path, "reset", "--hard", "origin/" + (local_branch(path) or "HEAD")])
            UNCONFIRMED.pop(repo, None)
        else:
            # 这里不能顺着往下走，不然会把"没更新"报成"更新完成"：11-04 19:37 实测主站 443
            # 半路断时，remote_sha 拿不到 want（日志里 "-> " 后面是空的），fetch 也失败，
            # 但函数照样打 "ok：78 个文件" 并 return True —— 既骗过台账，也让熔断器（靠
            # return False 计数）永远不响，剩下的仓一个个白撞 21 秒超时。
            reason = "远端 HEAD 都没拿到（链路不通）" if not want else "远端 %s 没拉到" % want[:9]
            UNCONFIRMED[repo] = reason
            log("  fetch 失败：%s｜%s，这一格算未确认"
                % (r.stderr.decode("utf-8", "replace")[:120], reason))
            return False
    files, total, suspect, largest = scan_worktree(path)
    if files == 0:
        log("  闸门：clone 完工作树 0 个文件，判失败（%s）" % repo)
        return False
    if suspect:
        removed = purge_suspect(path, suspect)
        PURGED[repo] = removed
        log("  红线：删掉 %d 个疑似密钥/固件/镜像：%s" % (len(removed), "; ".join(removed[:4])))
    rows.append(row_of(entry, meta_for(repo) or meta))
    log("  ok：%d 个文件 / %.1f MB / HEAD %s" % (files, total / 1048576.0, local_head(path)[:9]))
    return True


def save_ledger(rows):
    os.makedirs(AREA, exist_ok=True)
    # "检出时删掉 X 个"是一次性事实：下次单跑 ledger 时 PURGED 是空的，
    # 不接过来的话这条审计会在台账里凭空消失。
    prev = {}
    prev_head = {}
    if os.path.exists(LEDGER):
        with io.open(LEDGER, encoding="utf-8") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                seg = [s for s in (r.get("note") or "").split("｜") if s.startswith("检出时删掉")]
                if seg:
                    prev[r["repo"]] = seg[0]
                if (r.get("commit") or "").strip():
                    prev_head[r["repo"]] = r["commit"].strip()
    inherited = 0
    for r in rows:
        old = prev.get(r["repo"])
        if old and "检出时删掉" not in r["note"]:
            r["note"] += "｜" + old
        # commit 是这一档最要紧的一列（"镜像到哪个提交"），可 11-04 19:04–19:08 那轮
        # 台账重扫里 git 调用整批失败，92 行 commit 全空——工作树明明在盘上，台账却把
        # "下到了什么"写成未知数，而日志一声没响。这里不装"当场复核过"：
        # 沿用上轮那个真观测到的 sha，同时在 note 点名它没被本轮确认，下一轮好的扫描会自己写回真值。
        if not (r["commit"] or "").strip() and prev_head.get(r["repo"]):
            r["commit"] = prev_head[r["repo"]]
            r["note"] += "｜HEAD 沿用上轮记录（本轮 git rev-parse 没返回，未当场复核）"
            inherited += 1
    if inherited:
        log("闸门：%d 行本轮取不到 HEAD，沿用上轮 sha 并在 note 点名 —— 这 %d 格没当场复核，"
            "别当成最新，git 正常时重跑 ledger 会写回真值" % (inherited, inherited))
    with io.open(LEDGER, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HDR, delimiter="\t")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log("台账：%s（%d 行）" % (LEDGER, len(rows)))


def bundle_measure(path, out, repo, head):
    """量一个已经在盘上的 bundle：自检 + 体积 + sha256，返回台账那一格。"""
    v = subprocess.run([GIT, "-C", path, "bundle", "verify", out], capture_output=True)
    sz = os.path.getsize(out)
    hs = hashlib.sha256()
    with open(out, "rb") as bf:
        for chunk in iter(lambda: bf.read(1 << 20), b""):
            hs.update(chunk)
    return (repo, os.path.basename(out), head, sz, hs.hexdigest(),
            "OK" if v.returncode == 0 else "校验失败")


def cmd_bundle(_args):
    """每个仓库压成一个 git bundle：连历史一个文件，网盘好传、坏了能原地还原。

    工作树里十几万个散文件不适合往网盘推（夸克/百度逐个文件建索引，慢且容易被扫），
    bundle 是 git 官方的"整仓单文件"格式：git clone xxx.bundle 就能恢复。
    """
    os.makedirs(BUNDLE_DIR, exist_ok=True)
    # 台账里已经记过的格：跳过重做时用它判断"这一格到底记没记"。
    done_rows = {}
    if os.path.exists(BUNDLE_LEDGER):
        with io.open(BUNDLE_LEDGER, encoding="utf-8") as fh:
            for r in csv.DictReader(fh, delimiter="\t"):
                done_rows[r["repo"]] = r
    rows = []
    for e in read_reg():
        repo = e["repo"]
        path = os.path.join(SRC, repo.replace("/", "__"))
        if not local_head(path):
            continue
        out = os.path.join(BUNDLE_DIR, repo.replace("/", "__") + ".bundle")
        head = local_head(path)
        if os.path.exists(out) and head in bundle_heads(out):
            # 跳过重做，但"跳过"不等于"不记账"：11-04 19:03 那一轮被打断，39 个 bundle
            # 已经在盘上却来不及追加台账，下一轮靠 bundle 自带的 head 认出"做过了"就跳过 ——
            # 于是台账 52 行、盘上 91 个文件，对不上数也没法回答"这个仓到底备没备"。
            if (done_rows.get(repo) or {}).get("head") == head:
                log("跳过 %s（bundle 里已含 %s，台账也记过了）" % (repo, head[:9]))
            else:
                rec = bundle_measure(path, out, repo, head)
                rows.append(rec)
                log("跳过 %s（bundle 里已含 %s）—— 台账缺这一格，量完补记："
                    "%.1f MB，verify %s" % (repo, head[:9], rec[3] / 1048576.0, rec[5]))
            continue
        log("bundle %s -> %s" % (repo, os.path.basename(out)))
        # git bundle create 先写 <out>.lock 再改名。进程被打断，路障就永久留在那儿：
        # 11-04 实测 eandis/SDOJ-Recomp 的 116 MB lock 让 19:44、20:10 两轮都只报
        # "File exists / Another git process seems to be running"，这个仓一直备不出来。
        # 判"陈旧"用 mtime——十分钟没动过就是上一具尸体的，不是同时在跑的那个 git 的。
        stale = out + ".lock"
        if os.path.exists(stale) and time.time() - os.path.getmtime(stale) > 600:
            log("  清掉上一轮被打断留下的路障：%s（%.1f MB）"
                % (os.path.basename(stale), os.path.getsize(stale) / 1048576.0))
            os.remove(stale)
        v = run([GIT, "-C", path, "bundle", "create", out, "--all"], timeout=3600)
        if v.returncode != 0:
            log("  失败：%s" % v.stderr.decode("utf-8", "replace")[:200])
            continue
        rec = bundle_measure(path, out, repo, head)
        rows.append(rec)
        log("  %s：%.1f MB，bundle verify %s" % (rec[1], rec[3] / 1048576.0, rec[5]))
    if rows:
        os.makedirs(AREA, exist_ok=True)
        # Windows 文本追加模式下 fh.tell() 不可靠，直接用文件大小判"要不要写表头"
        first = not os.path.exists(BUNDLE_LEDGER) or os.path.getsize(BUNDLE_LEDGER) == 0
        with io.open(BUNDLE_LEDGER, "a", encoding="utf-8", newline="") as fh:
            if first:
                fh.write("\t".join(BUNDLE_HDR) + "\n")
            for r in rows:
                fh.write("\t".join([str(x) for x in r] +
                                   [dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")]) + "\n")
        log("bundle 台账追加 %d 行：%s" % (len(rows), BUNDLE_LEDGER))
    return 0


def bundle_heads(out):
    """这份 bundle 里带了哪些提交的 SHA，用来判断它是不是最新那次的。"""
    r = subprocess.run([GIT, "bundle", "list-heads", out], capture_output=True)
    if r.returncode != 0:
        return set()
    return set(l.split()[0] for l in
               r.stdout.decode("utf-8", "replace").splitlines() if l.strip())


def cmd_sweep(_args):
    """用当前判据重扫所有已镜像的工作树并处置。

    为什么要有这一条：改红线表（比如 11-04 往 MEDIA_EXT 里补 .bk2/.wad 这些原厂音视频后缀）
    对在跑的进程不生效，对"HEAD 已最新"的仓库也不会再生效——fetch 一看到 HEAD 相同就 return，
    根本不进扫描段。没有这一条，判据升级只能管以后 clone 的仓，已经下完的一批永远带着旧判定。
    """
    purged_total = 0
    rows = []
    for e in read_reg():
        path = os.path.join(SRC, e["repo"].replace("/", "__"))
        if not local_head(path):
            continue
        _f, _t, suspect, _l = scan_worktree(path)
        if suspect:
            gone = purge_suspect(path, suspect)
            PURGED[e["repo"]] = gone
            purged_total += len(gone)
            log("sweep %s：处置 %d 个：%s" % (e["repo"], len(gone), "; ".join(gone[:3])))
        rows.append(e)
    ledger_rows = rescan_rows(rows, "sweep 后台账")
    save_ledger(ledger_rows)
    log("sweep 完成：复查 %d 仓，处置 %d 个文件" % (len(rows), purged_total))
    return 0


def probe_github():
    """clone 之前先探一次主站。11-04 实测：github.com 的 443 会单独断（api/codeload 还通），
    那时每条 clone 都要撞满 21 秒才失败——160 个仓就是 56 分钟空烧，还写出一屏"失败"看着像仓库没了。
    判不清就把话说清：主站断/代理断/api 断是三种不同的毛病。"""
    import urllib.request
    r = run([GIT, "ls-remote", "https://github.com/octocat/Hello-World.git", "HEAD"], timeout=45)
    if r.returncode == 0:
        return True
    api = ""
    try:
        # 这一路必须显式**不吃代理**：它和上面 clone 那一路分开判，才能把"api 断了"和
        # "代理停了"区分开 —— 合在一起判会说反话（11-04 18:18 就骗过一次：日志写
        # "api.github.com 也不通"，而同一分钟成品包正走 api 以 6 MB/s 下载，坏的是代理不是 api）。
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request("https://api.github.com/zen",
                                     headers={"User-Agent": "mirror-probe"})
        with opener.open(req, timeout=10) as resp:
            api = "api.github.com 通（HTTP %d）" % resp.status
    except Exception as ex:
        api = "api.github.com 也不通（%s）" % type(ex).__name__
    log("闸门：主站 clone 通道不通（%s），%s；本次不动盘。"
        "要么等 github.com 自己恢复，要么把代理起起来再跑（net_proxy 自己探 7891/7890 哪个活着）——重跑是幂等的，已镜像的会跳。"
        % (r.stderr.decode("utf-8", "replace").strip()[:120], api))
    return False


def cmd_all(_args):
    if not os.path.exists(GIT):
        log("找不到 git：%s" % GIT)
        return 1
    if not probe_github():
        return 1
    rows = []
    ok = bad = 0
    streak = 0
    aborted = False
    for e in read_reg():
        if (e.get("enable") or "1").strip() != "1":
            log("跳过（登记成停用）：%s — %s" % (e["repo"], e.get("note", "")[:40]))
            continue
        # policy=meta 的仓不 clone：要么 .git 超过 5GB（整仓不划算，只留登记 + 成品包），
        # 要么 API 没给到 size（判不了体积，不动盘）。Switch2 那档没这列，默认 full。
        if (e.get("policy") or "full").strip() == "meta":
            log("跳过（登记不下，policy=meta）：%s — %s" % (e["repo"], e.get("note", "")[:40]))
            continue
        rows.append(e)
    # 盘上一格都没有的仓排前面。11-04 实测链路是"几十秒通、几分钟断"，熔断后 watcher 从
    # 登记表第一行重跑：于是每一轮烧的都是"已经备齐、只是本轮没能确认它是不是最新"的那些仓，
    # 而真正一个文件都没落地的排在几百名之后，永远轮不到。防下架要的是"先落到盘上"。
    # 代价：已镜像仓的"确认最新"会排到后面，链路一直抖就先保住新仓 —— 全盘扫的活交给 sweep/bundle。
    def _prio(e):
        p = os.path.join(SRC, e["repo"].replace("/", "__"))
        return 1 if (os.path.isdir(p) and local_head(p)) else 0
    rows.sort(key=_prio)
    log("待处理 %d 个：其中盘上还没有的 %d 个（排前面先落地）"
        % (len(rows), sum(1 for e in rows if _prio(e) == 0)))
    for i, e in enumerate(rows, 1):
        out = []
        if fetch(e, out):
            ok += 1
            streak = 0
        else:
            bad += 1
            streak += 1
            # 开头探一次不算数：主站的 443 是跑到一半才断的（11-04 实测，16:47 起连续失败）。
            # 没有这一条，剩下的仓会一个个撞满 21 秒超时，一屏"失败"看着像这批仓库没了。
            # 判据不放在"错误文本像什么"，放在"当场再探一次主站"——探测不会说谎。
            if streak >= 4:
                log("连续 %d 个失败，重探主站（最后一个是 %s）" % (streak, e["repo"]))
                if not probe_github():
                    log("中止：链路已断，停在 %s（第 %d/%d 个）。已镜像的不动，"
                        "恢复后重跑 all 会接着补剩下的 %d 个" % (e["repo"], i, len(rows), len(rows) - i))
                    aborted = True
                    break
                streak = 0
    # 台账单独重扫一遍，保证记的是盘上真实状态
    ledger_rows = rescan_rows([e for e in rows
                               if os.path.isdir(os.path.join(SRC, e["repo"].replace("/", "__")))],
                               "台账")
    save_ledger(ledger_rows)
    log("完成：%s 成功 %d / 失败 %d（其中本轮没确认到远端的 %d 个，见台账 note）/ 工作树合计 %.2f GB" % (
        "中止" if aborted else "跑完", ok, bad, len(UNCONFIRMED),
        sum(int(r["worktree_bytes"]) for r in ledger_rows) / 1073741824.0))
    return 1 if (bad or aborted) else 0


def rescan_rows(entries, tag):
    """把盘上真实状态重算成台账行，每 20 个报一次进度。

    为什么要报：11-04 20:15 那轮中止后的重扫五分钟不出一个字，看不出是死了还是在走
    10 万个文件的目录树 —— 进度可见性本身就是判活的手段（成品包那边已经吃过一次这个教训）。
    """
    out = []
    for i, e in enumerate(entries, 1):
        out.append(row_of(e, meta_for(e["repo"])))
        if i % 20 == 0 or i == len(entries):
            log("%s：重扫 %d/%d" % (tag, i, len(entries)))
    return out


def cmd_ledger(_args):
    entries = []
    for e in read_reg():
        path = os.path.join(SRC, e["repo"].replace("/", "__"))
        if os.path.isdir(path):
            entries.append(e)
        elif (e.get("enable") or "1").strip() == "1" and (e.get("policy") or "full").strip() != "meta":
            log("登记要下但盘上没有：%s" % e["repo"])
    save_ledger(rescan_rows(entries, "台账"))
    return 0


def cmd_list(_args):
    for e in read_reg():
        print("%s  %-46s %-12s %-8s %s" % (
            "要下" if (e.get("enable") or "1") == "1" else "停用",
            e["repo"], e.get("tier", ""), e.get("policy", ""),
            e.get("note", "")[:60]))
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    fn = {"all": cmd_all, "ledger": cmd_ledger, "list": cmd_list, "bundle": cmd_bundle,
          "sweep": cmd_sweep}.get(cmd)
    if fn is None:
        print("用法：all / ledger / list / bundle / sweep")
        return 2
    # 两档共用这一个引擎，靠 MIRROR_AREA 点名要动哪一档。11-04 20:01 我就漏设了一次，
    # 结果把 Switch2 那档的台账整本重扫（39 个仓现取 api，白烧 8 分钟），还以为自己在处理
    # 成品移植游戏库。默认值不许悄悄生效 —— 每次动盘先在日志里点名目标档。
    log("目标档：%s ｜ 命令 %s%s" % (AREA_NAME, cmd,
        "" if os.environ.get("MIRROR_AREA") else
        " ← MIRROR_AREA 没设，这是默认档；要动别的档得先设"))
    return fn(None)


if __name__ == "__main__":
    sys.exit(main())
