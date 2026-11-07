# -*- coding: utf-8 -*-
"""掌机端口库（PortMaster 系）的"仓库内成品包"抓取器。

为什么单开一个脚本：这批游戏包不是 release 资产，是直接 commit 在工作树里的文件——
recomp_lib_assets.py 走的是 releases/latest + 资产下载，对这类仓库一条都抓不到。
11-04 用户点名的"人家的库都是几百几千个游戏"，PortMaster 系就是那个量级的东西：
  christianhaitian/PortMaster   298 个 zip（4.18 GB），zip 躺在仓库根
  PortsMaster-MV/PortMaster-MV-New  22,406 个松散文件（3.42 GB）在 ports/
  PortsMaster/PortMaster-New        489 个端口，tree API 已截断，13.7 GB 只是可见部分

只下工作树、不下历史：--depth 1（这些仓的 .git 是 8~38 GB，全量 clone 是把磁盘喂给历史）。
红线照旧：检出后用生产判据 suspect_reason 逐个文件判，命中就挪进 待复核/，不静默删——
"大媒体包"这一档是嫌疑不是定罪，由人圈（11-04 误杀 objdump 的教训还记着）。
"""
import csv
import hashlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import zlib

import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import net_proxy                      # noqa: E402
import psutil                          # noqa: E402  判活要用进程树的 CPU，不能只看体积
import switch2_emu_fetch as SF         # noqa: E402  复用生产判据：suspect_reason / scan_worktree / remote_sha

AREA = os.path.join(ROOT, "06-资讯监控", "成品移植游戏库")
TREE_DIR = os.path.join(AREA, "掌机端口包")
HOLD_DIR = os.path.join(AREA, "待复核", "掌机端口包")
LOG = os.path.join(AREA, "端口包日志.txt")
LEDGER = os.path.join(AREA, "端口包台账.tsv")
HOLD_TSV = os.path.join(AREA, "端口包待复核.tsv")
GIT = SF.GIT

# (仓库, 工作树预算 GB, 说明)；预算是 11-04 实测 tree API 得到的，超了会点名而不是闷着下
TARGETS = [
    ("christianhaitian/PortMaster", 5.0, "初代 Ark 版：298 个成品 zip 就在仓库根"),
    ("PortsMaster-MV/PortMaster-MV-New", 5.0, "MV 分支：ports/ 下 22k 个松散文件"),
    ("PortsMaster/PortMaster-New", 22.0, "主库：489 个端口（tree API 截断，实际更大）"),
]
LEDGER_HDR = ["repo", "head", "commit", "files", "bytes_gb", "suspect", "susp_gb",
              "state", "note"]
HOLD_HDR = ["repo", "rel", "bytes", "why", "moved_at"]
# 单仓克隆的墙钟上限。主库按实测 3 MB/s 算 22 GB ≈ 2 小时，留一倍余量；
# 到点杀掉并在日志写明「超预算不是卡死」，绝不让一条哑掉的克隆占着带宽过夜。
HANG_LIMIT_S = 4 * 3600
# 第一个字节到来之前的宽限期。服务端对 `PortsMaster/PortMaster-New` 这种仓要先算完
# object 计数才开口，11-05 实测这一段能空耗好几分钟；拿 3 分钟的卡死门去砍它，
# 就等于每轮都把同一条克隆杀一遍，永远下不完。
PRE_FIRST_BYTE_S = 20 * 60
# 连续多少次采样"体积和 CPU 都不动"才算卡死。每次采样 30 s，20 次 = 10 分钟。
# 为什么不看 TCP：11-05 现场，PortMaster-New 停在 16.45 GB、CPU 停在 285.8 s 整整两分钟
# 以上，而隧道 socket 一直是 ESTABLISHED——代理开着但后端已经断了，连接状态此时是假绿灯。
# 所以 TCP 只打进日志当证据，不参与判活。
FREEZE_LIMIT = 20
# 工作树预算到这个数以上，就不许再"一条 pack 梭哈"。
# 11-05 实测 PortMaster-New（预算 22 GB）三次跑到 16.45 GB 都被 `curl 56 SSL_ERROR_SYSCALL`
# 掀掉——隧道在收尾时断，而 pack 断在最后一公里等于 40 分钟白烧、下一轮从 0 开始。
# 改成先只取 commit+tree（几十 MB），再分轮往工作树落 blob：已经拿到的对象留在本地对象库，
# 每轮只下"这轮还缺的"，断一次只损失当前一批。
PARTIAL_FROM_GB = 8.0
BLOB_ROUNDS = 8
# 分批落 blob 的批次参数。BATCH_LIMIT 给够（150,423 个文件 / 300 = 502 批一轮的上限留余量），
# 到 STALL_GIVEUP 批零进展就收手，不拿着一副坏链路空转。
BATCH_LIMIT = 600
# 一批最多要多少个 blob。这个数只能按"这条隧道吃得下什么"定，不能按"几个目录堆"定：
# 11-05 06:5x 实测 12 堆一批照样整批 rc=128——一个端口动辄上千个文件（alephone-marathon2
# 解包 3,694 个成员、Smash64-3DS 11,105 个成员），12 堆凑一次 promisor 请求就是上万条 oid，
# 服务端算不完 ⇒ `unable to read sha1 file` ⇒ 整批作废，还顺手留下半截目录让人误报
# `Directory not empty`。300 个 blob ≈ 几十 MB ≈ 20~40 s 一跳，是这条隧道吃得下的尺寸。
CHUNK_BLOBS = 300
STALL_GIVEUP = 3
# "这一批有没有进展"不能只看"还缺多少个文件"。
# 11-05 06:4x 实测：PortMaster-New 连着 3 批被 `unable to read sha1 file` 掀断，读数纹丝不动
# 停在 150,423，于是本模块判"链路在拒、本轮收手"；而同一窗口记着"本轮新增 0.23 GB｜3.77 MB/s"
# ——对象库明明在涨。原因是 git 在**中断时不写索引**，已经落进对象库的 blob 依然被 status
# 报成缺失，所以"缺多少个"这个读数只在整批成功时才前进。
# 于是加一条并行判据：一批真拉回 BIG_GAIN 以上就算有进展，不许计入 stalled。
# 取 50 MB = 一批预期体量（12 堆 ≈ 0.5 GB）的十分之一；低于它就是真没动。
BIG_GAIN = 50 * 1048576

CURL = shutil.which("curl") or "curl"
# tar 只能用系统那份（bsdtar）。另外两条实测都是死路，别再试一遍：
#   D:\Git\usr\bin\tar.exe（msys GNU tar）把 `-f F:\x\y.tar.gz` 里的 `F:` 当远端主机名
#     ⇒ `tar (child): Cannot connect to F: resolve failed`；改成"cwd + 相对包名"之后
#     它又不吃绝对 `-C`：`F\:\开源掌机教程\...: Cannot open: No such file or directory`。
#   `shutil.which("tar")` 在这种机器上正指到那份 GNU tar，所以 here 不靠 which。
# bsdtar 两个都要 `-C` 和 `-f` 都给绝对路径，实测 rc=0、套壳层剥对、嵌套目录落对。
SYS_TAR = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
TAR = SYS_TAR if os.path.isfile(SYS_TAR) else ""
# tar.gz 的中转落点：放在 掌机端口包/ 下面、仓目录之外。
# verify() 扫的是仓目录本身，所以这个包不会被当成"仓库里的成品包"混进台账。
TAR_SUB = os.path.join(TREE_DIR, "_tar中转")
# codeload 不吃 Range：11-05 实测 `-H 'Range: bytes=0-99'` 回的是 200 + 整包 258 字节，
# 不是 206。所以这条没有断点续——一次要么整包到手，要么从头再来，
# 闸门只能按"整包"定，`curl -C -` 那种"接着下"的写法在这里是假把戏。
TAR_MAX_GB = 60.0        # 单个中转包的兜底上限（不是预算）——实际门见 tar_size_limit：按仓预算的两倍取
FREE_FLOOR_GB = 25.0     # 下载/解包期间 F 盘余量下限（同一时刻 pull 那条线要吃 210 GB）
TAR_MIN_GAP = 5000       # 缺口不到这个数就别下整包——promisor 落小文件是够用的（1,768 个 port.json 实测）
TAR_WAIT_S = 6 * 3600    # 一条 tar.gz 下载的墙钟上限；到点杀掉，判失败回退分批
TAR_STALL_S = 900        # 连续多少个采样（30 s/次）没有新字节就收手。11-05 从 300 提到 900：
                         # 那天 11:12 一条已经流到 33.34 GB 的包断了 5 分钟就被杀，而 codeload 不给
                         # Range，杀掉等于把 30 GB 带宽清零——6 小时一条的流上，5 分钟打嗝是常态。
                         # 真正的慢隧道不归这道门管：curl 自己的 --speed-limit 20480/--speed-time 60
                         # 会在 60 s 内退掉低于 20 KB/s 的连接，rc=28 交回外面那层。
TRUNC_KEEP_GB = 2.0      # 断流时留在 2 GB 以上的字节要保住（见 tar_download 的 .trunc 那条路）
TAR_PRECHECK_GB = 1.0    # 小包才值得先 `tar -t` 读一遍；大包让**解包自己当验收**（见下面 _needs_precheck）
PEND_SUFFIX = ".unverified"   # "流跑完了但还没人读到底"的包：解一遍，读到底就转正式名（见 land_from_tarball）
TAR_REAP_GB = 5.0        # 工作树确认落满后，中转盘上大于这个数的包才腾（几 MB 的留着省一趟下载，见 reap_stale_tars）


def log(msg):
    line = "[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    os.makedirs(AREA, exist_ok=True)
    with io.open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def dst_of(repo):
    return os.path.join(TREE_DIR, repo.replace("/", "__"))


def default_budget(repo):
    """这仓在 TARGETS 里登记的 GB 预算；补跑一条不在表上的仓时给个 20 GB 的兜底，
    省得 tarball 那条闸门拿到 None 就没法算盘。"""
    for name, gb, _why in TARGETS:
        if name == repo:
            return gb
    return 20.0


def worktree_bytes(path):
    """工作树体积（跳过 .git）。检出阶段 pack 是不动的，只看 pack 会把健康的检出误判成卡死。"""
    total = 0
    for dp, dn, fn in os.walk(path):
        if os.path.basename(dp) == ".git":
            dn[:] = []
            continue
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return total


def phase(path):
    """ clone 阶段的廉价进度：下载期看 pack 目录体积，检出期看工作树体积。
    不做全量 scan_worktree——那还要逐个文件跑红线判据，每 30 秒跑一遍会把这轮拖死。

    "正在下载"的那个文件叫 tmp_pack_XXXXXX（11-05 在 PortsMaster-Releases 里实测躺着一个
    314 MB 的 tmp_pack_kRKnn2），既不是 .pack 结尾也不含 ".tmp-"。前一版只数这两种名字，
    于是整条下载期读数恒为 0.00 GB，卡死闸门把一条 3 MB/s 健康跑的 22 GB 克隆连杀两次。
    现在直接对 pack 目录求和——git 在里面用什么名字都不影响判活。

    检出期还要把 pack 一起算上：`--filter=blob:none` 的仓在 reset --hard 里是"边下 blob
    边落文件"，只看工作树会在 git 攒够一批对象才动笔的间隙里读到 0.00 GB，
    被"等第一个字节"那条门误杀。"""
    pk = os.path.join(path, ".git", "objects", "pack")
    got = 0
    if os.path.isdir(pk):
        for f in os.listdir(pk):
            try:
                got += os.path.getsize(os.path.join(pk, f))
            except OSError:
                pass
    if os.path.exists(os.path.join(path, ".git", "index.lock")):
        # 取两者的大值而不是相加：整包克隆落满后 pack 和工作树是同一份内容的两个体（相加会虚报一倍），
        # 而 max 在"下载期"和"落文件期"两段都是单调往上的，冻结判据不会被阶段切换误触发。
        return "检出中", max(got, worktree_bytes(path))
    return "收包中", got


def tree_cpu(pid):
    """进程及其全部子进程的累计 CPU 秒。git clone 真正在收数据的是 git-remote-https.exe，
    只读父进程会拿到一条几乎不动的曲线，所以必须走进程树。"""
    try:
        procs = [psutil.Process(pid)] + psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return None
    tot = 0.0
    for p in procs:
        try:
            ct = p.cpu_times()
            tot += ct.user + ct.system
        except psutil.Error:
            continue
    return tot


def tree_established(pid):
    """进程树里是否挂着 ESTABLISHED 的 TCP 连接。
    为什么要这第三条腿：clone 大仓时服务端要先算完 objects 才吐第一个字节。00:35–00:37 实测
    `PortsMaster/PortMaster-New` 就是这个形状——`tmp_pack_1YNLGh` 建好了但 0 字节、CPU 不动、
    体积不动，而 `git-remote-https.exe` 到 127.0.0.1:7891 的连接是 ESTABLISHED。
    只看"体积和 CPU 都没动"会把这种**在等服务器**的克隆判成卡死，11-05 这样已经误杀两次了。"""
    try:
        procs = [psutil.Process(pid)] + psutil.Process(pid).children(recursive=True)
    except psutil.Error:
        return False
    for p in procs:
        try:
            for c in p.net_connections(kind="tcp"):
                if c.status == psutil.CONN_ESTABLISHED:
                    return True
        except (psutil.Error, OSError):
            continue
    return False


def wait(proc, path, repo, base=0):
    """每 30 s 报一次进度。卡死 = 体积和 CPU 两条同时不动（TCP 连不连只写进日志，不参与判定）。
    只有一条没动可能是量法瞎（pack 改名、index-pack 在算校验、管道写满、服务端在算包），不算死。
    两条一起冻结够 FREEZE_LIMIT 次才是 11-04 那次 PIPE 僵住的形状（CPU 恒定 24.765625 s、管道满）。

    `base` 是这一轮开始前盘上已有的体积，进度按**本轮新增**算。不传 base 会出两个毛病：
    blobless 仓落文件时骨架 pack 已有 4.66 MB，读数恒 >0 就绕过了"等第一个字节"那条 20 分钟宽限，
    反过来被 10 分钟的冻结门先杀掉（11-05 06:0x 实测：服务端在算 16 GB 的过滤包，
    5 分钟一个新字节都没吐，看着就是"双冻结"）。按新增算之后，没来货 = got 0 = 走宽限期门。"""
    t0 = time.time()
    last = -1
    last_cpu = -1.0
    still = 0
    prev = None
    while proc.poll() is None:
        time.sleep(30)
        st, raw = phase(path)
        got = max(0, raw - base)
        cpu = tree_cpu(proc.pid)
        el = time.time() - t0
        if st != prev:
            log("  %s %s（%.2f GB，%.0f s）" % (repo, st, got / 1073741824.0, el))
            prev = st
        cpu_moved = False
        if cpu is not None:
            # 进程树的 CPU **不是单调量**：子进程一退出，它那份 CPU 秒就从总和里消失了。
            # 00:34 实测同一个 clone 两次采样 0.531 s → 0.344 s（树从 4 个进程缩到 2 个）。
            # 所以基线只往上涨：拿历史最大值当参照，缩树不会假装成"没动"，涨了才是真干了活。
            peak = max(last_cpu or 0.0, cpu)
            cpu_moved = peak > (last_cpu or 0.0) + 0.5
            last_cpu = peak
        sock = tree_established(proc.pid)
        # TCP 只当证据报出来，**不参与"活着"的判定**。
        # 11-05 01:0x 现场：PortMaster-New 收到 16.45 GB 后体积和 CPU 双双冻结，
        # 但到 7891 那条隧道一直没关，socket 全程 ESTABLISHED。上一版写成
        # "体积/CPU/TCP 任一还在就 reset"，结果这个半死的连接能把闸门永远喂下去
        # ——只有 4 小时预算能收尸，而预算是"慢"的判据，不该拿来给"死"收尸。
        if got != last or cpu_moved:
            still = 0
            log("  %s %s 本轮新增 %.2f GB｜%.0f s｜%.2f MB/s｜CPU %.1f s｜%s"
                % (repo, st, got / 1073741824.0, el, got / 1048576.0 / max(el, 1),
                   cpu if cpu is not None else -1, "TCP 连着" if sock else "无连接"))
        else:
            still += 1
            log("  %s %s 本轮新增 %.2f GB｜%.0f s｜体积和 CPU 全没动（%d 次 / %.0f s）｜TCP %s"
                % (repo, st, got / 1073741824.0, el, still, still * 30,
                   "还挂着（隧道半死）" if sock else "已断"))
        last = got
        # 一个字节都没收到时，不能拿"3 分钟没动"当死刑：大仓光是服务端算包就要几分钟。
        if got == 0 and el > PRE_FIRST_BYTE_S:
            log("  %s 等第一个字节等了 %.0f 分钟（上限 %d 分钟）还没来，杀掉判失败——"
                "这种是链路或对端的问题，不是本地卡死" % (repo, el / 60.0, PRE_FIRST_BYTE_S // 60))
            proc.kill()
            return -9
        if got > 0 and still >= FREEZE_LIMIT:
            log("  %s 卡死：连续 %d 次采样（%.0f 分钟）体积和 CPU 两条都不动，杀掉重来"
                % (repo, still, still * 30 / 60.0))
            proc.kill()
            return -9
        if el > HANG_LIMIT_S:
            log("  %s 超预算：跑了 %.0f 分钟还没结束（上限 %.0f 分钟），杀掉判失败——"
                "这条不是卡死，是预算；下轮从头再来" % (repo, el / 60.0, HANG_LIMIT_S / 60.0))
            proc.kill()
            return -9
    return proc.returncode


def same_bytes(a, b):
    """两份拷贝是不是逐字节相同。只比大小不行——这里要的是"敢删工作树那份"的依据。"""
    ha = hashlib.sha256()
    hb = hashlib.sha256()
    try:
        for h, p in ((ha, a), (hb, b)):
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                    h.update(chunk)
    except OSError:
        return False
    return ha.hexdigest() == hb.hexdigest()


def hold_rows(repo, path, suspects):
    """把嫌疑文件挪出工作树并在索引里抹掉，git status 才不会长期挂一堆 D。
    返回 (本轮真挪走的行, 与存档重名因此删掉的副本)。"""
    moved = []
    cleaned = []
    for rel, sz in suspects:
        clean = rel.split("（")[0]
        src = os.path.join(path, clean)
        if not os.path.exists(src):
            continue
        hd = os.path.join(HOLD_DIR, repo.replace("/", "__"))
        dst = os.path.join(hd, clean)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.exists(dst):
            # 上一轮挪走之后，这一轮的 reset --hard 又把它从本地 pack 原样落回工作树了
            # （11-05 实测 8 个 zip 在 待复核/ 和仓库根各存一份）。内容一致就删工作树这份——
            # blob 还在 pack 里，随时能再检出，待复核/ 那份才是等人圈的存档；
            # 字节不一致是真出岔子，两份都留着并大声报，绝不静默覆盖。
            if same_bytes(src, dst):
                os.remove(src)
                cleaned.append((clean, sz))
            else:
                log("  %s：待复核/ 已有一份但字节不同，两份都留着，需要人工判定" % clean)
            continue
        try:
            shutil.move(src, dst)
        except OSError as ex:
            log("  挪待复核失败：%s：%s" % (clean, type(ex).__name__))
            continue
        subprocess.run([GIT, "-C", path, "update-index", "--force-remove", clean],
                       capture_output=True)
        why = rel.split("（", 1)[1].rstrip("）") if "（" in rel else ""
        moved.append({"repo": repo, "rel": clean, "bytes": sz, "why": why,
                      "moved_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    return moved, cleaned


def rmtree_checked(path):
    """删干净才算成功。**不能 ignore_errors=True**：那会把"没删掉"这件事整个吞了。
    11-05 实测被打断的 clone 留下 `.git/objects/pack/tmp_pack_381cH7`——0 字节但**只读**
    （git 给 pack 加只读位保护对象库，Windows 上只读文件挡住 rmtree），目录于是还在，
    下一轮 clone 直接 `fatal: destination path ... already exists and is not an empty directory`
    退出码 128，而日志上写着"清掉重下"，读起来像我们已经处理过了。"""
    def _force(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=_force)
    return not os.path.exists(path)


def prior_holds(repo):
    """这个仓历史上挪进 待复核/ 的（笔数, 字节, 相对路径集合）。
    重扫时那些文件已经不在工作树里了，本轮 moved=0 ⇒ 台账的 suspect 列退回 0，
    读起来像"这棵树干净"，而实际是 8 个 90 MB 的 zip 正躺在 待复核/ 里等人圈。
    台账要能查出累计挪了多少，不能只报最后一次。
    相对路径集合另一个用途是从 missing_rels() 的读数里剔掉——见那边的注释。"""
    if not os.path.exists(HOLD_TSV):
        return 0, 0, set()
    with io.open(HOLD_TSV, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh, delimiter="\t") if r.get("repo") == repo]
    # 同一个 rel 可能被记了两笔（11-05 那次 reset --hard 把已挪走的 zip 落回工作树，
    # 于是红线又判了一次），累计必须按 rel 去重取最后一笔，否则台账会写出
    # suspect=16 / 1.40 GB 这种"盘上只有 9 个文件"的数。
    latest = {}
    for r in rows:
        latest[r["rel"]] = int(r["bytes"] or 0)
    return len(latest), sum(latest.values()), set(latest)


def write_hold(new_rows):
    """待复核清单整本重写，键是 (仓, 相对路径)，一格只许有一行。
    11-05 00:13 和 00:29 两轮把同样 8 个 zip 各记了一行，清单读出来 17 行 / 1.49 GB，
    而 待复核/ 目录里实际只有 9 个文件 / 0.76 GB。这张表是拿来给人圈"留哪个、删哪个"的，
    体积翻倍会让人对缺口做错的判断，所以重复行不是难看，是假证据。
    同一格再来一笔时按"新的覆盖旧的"：盘上现在那份才算数。"""
    rows = []
    if os.path.exists(HOLD_TSV):
        with io.open(HOLD_TSV, encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh, delimiter="\t") if r.get("rel")]
    out = []
    idx = {}

    def keep(row):
        k = (row["repo"], row["rel"])
        if k in idx:
            out[idx[k]] = row          # 同格后来的覆盖旧的：盘上现在那份才算数
        else:
            idx[k] = len(out)
            out.append(row)

    for r in rows:
        keep({h: (r.get(h) or "") for h in HOLD_HDR})
    for m in new_rows:
        keep({h: str(m[h]) for h in HOLD_HDR})
    tmp = HOLD_TSV + ".tmp"
    with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(HOLD_HDR) + "\n")
        for r in out:
            fh.write("\t".join((r.get(h) or "").replace("\t", " ") for h in HOLD_HDR) + "\n")
    os.replace(tmp, HOLD_TSV)
    return out


def in_ledger(repo):
    if not os.path.exists(LEDGER):
        return False
    with io.open(LEDGER, encoding="utf-8") as fh:
        return any(r.get("repo") == repo for r in csv.DictReader(fh, delimiter="\t"))


def clear_stale_lock(path, max_age=600):
    """被杀掉的 git 会把 .git/index.lock 留在盘上，之后任何 reset/checkout 都秒退
    （fatal: Unable to create ... index.lock: File exists）——11-04 那棵半树就是这么修不动的。
    只删超过 max_age 秒的：还要更年轻的说明真有 git 在跑，不能抢它的锁。"""
    lk = os.path.join(path, ".git", "index.lock")
    if not os.path.exists(lk):
        return True
    age = time.time() - os.path.getmtime(lk)
    if age < max_age:
        log("  %s 的 index.lock 只有 %.0f s，判有 git 在跑，不动它" % (os.path.basename(path), age))
        return False
    try:
        os.remove(lk)
        log("  抹掉 %s 留下的过期 index.lock（%.0f s 前）" % (os.path.basename(path), age))
        return True
    except OSError as ex:
        log("  index.lock 删不掉：%s" % type(ex).__name__)
        return False


def _nul(path, args):
    """跑一条只读 git 命令，拿 NUL 分隔的路径清单。
    为什么走 -z：默认输出会把带空格、方括号、非 ASCII 的路径套上 C 引号
    （`"ports/2048plus/.../All Night - Roa .mp3"` 这种），手工剥引号迟早剩半截
    `":(literal)…"` 喂进 pathspec。-z 下 git 从不加引号，路径原样进清单。"""
    r = subprocess.run([GIT, "-C", path] + args, capture_output=True, env=net_proxy.env())
    return [x.decode("utf-8", "replace") for x in r.stdout.split(b"\0") if x]


def verify(repo, path, head, state, note=""):
    hist_n, hist_b, hist_rels = prior_holds(repo)
    files, total, suspects, largest = SF.scan_worktree(path)
    gb = total / 1073741824.0
    log("  %s %s：%.2f GB / %d 文件｜最大 %s %.1f MB"
        % (repo, state, gb, files, largest[0][:60], largest[1] / 1048576.0))
    moved, cleaned = (hold_rows(repo, path, suspects) if suspects else ([], []))
    # 本轮挪走的格子里，凡是清单上早就记过的（待复核/ 那份被 reset --hard 又落回工作树、
    # 于是红线又判了一次），台账的 suspect 计数不许把它算两遍。
    again = [m for m in moved if m["rel"] in hist_rels]
    fresh = [m for m in moved if m["rel"] not in hist_rels]
    # 每轮都重写一遍清单：既把本轮挪走的格子并进去，也顺手把历史上记重的那几格压平
    # （11-05 那份 17 行 / 1.49 GB 的清单，盘上其实只有 9 个文件 / 0.76 GB）。
    hold_rows_now = write_hold(moved)
    if moved:
        log("  红线复检：%d 个文件 / %.2f GB 挪到 %s｜清单压到 %d 行（本仓新增 %d，重写旧格 %d）"
            % (len(moved), sum(m["bytes"] for m in moved) / 1073741824.0,
               os.path.join(HOLD_DIR, repo.replace("/", "__")),
               len(hold_rows_now), len(fresh), len(again)))
    if cleaned:
        log("  重名副本：%d 个 / %.2f GB 与 待复核/ 那份逐字节相同，只删工作树副本"
            % (len(cleaned), sum(s for _, s in cleaned) / 1073741824.0))
    # 台账的 bytes_gb/files 一律记"处理完之后盘上还剩多少"：
    # 本轮挪走和去重删掉的都要从扫描数里扣下去，否则这一格读起来像树里还躺着那些包。
    out_files = files - len(moved) - len(cleaned)
    out_bytes = total - sum(m["bytes"] for m in moved) - sum(s for _, s in cleaned)
    put(repo, head, out_files, out_bytes, len(fresh) + hist_n,
        sum(m["bytes"] for m in fresh) + hist_b,
        state, (note or big_note(largest)) +
        ("｜另含历史挪出 %d 个 %.2f GB（不在工作树体积里）" % (hist_n, hist_b / 1073741824.0)
         if hist_n else "") +
        ("｜去重删副本 %d 个" % len(cleaned) if cleaned else ""))
    return gb, files


def big_note(largest):
    """台账里那句「最大 xx」。**必须换算**：largest[1] 是字节，
    11-05 直接把字节拼上 "MB" 写进了台账，读出来是「chaoresortisland.por 94854155.0MB」
    这种 900 万 MB 的鬼话——台账是给人做取舍用的，单位写错就等于制造假证据。"""
    if not largest or not largest[1]:
        return "工作树为空"
    return "最大 %s %.1f MB" % (largest[0][:60], largest[1] / 1048576.0)


def is_partial(path):
    """这棵是不是 blobless 克隆：标记写在 .git/config 里（partialclonefilter / promisor）。
    必须从仓本来看，不能从"预算多大"看——补跑一轮时预算那条线根本不知道上次是什么形态下的。"""
    cfg = os.path.join(path, ".git", "config")
    try:
        with io.open(cfg, encoding="utf-8", errors="replace") as fh:
            t = fh.read()
    except OSError:
        return False
    return "blob:none" in t or "promisor = true" in t


_HEAD_CACHE = {}   # 补跑期间 HEAD 不动，150,416 条清单不重读第二遍（每批都要重新取"已经有了"那部分）
# 进程内那份缓存跨不了轮：一条循环 30 轮就是 30 次 `ls-tree -r`。
# 11-05 实测同一棵树冷盘 + 两条下载线压着 IO 时，ls-tree 走了 12 分钟（09:09:53 起、09:2x 才回），
# 而机器空一点的 08:43:31 只花 2 s——读数尺子本身成了这一轮最大的开销，比下 20 GB 还慢。
# 所以把它落成 sidecar，**文件名带 head 的 sha**：清单只跟 sha 走，换 commit 就换文件，
# 结构上不存在"过期缓存顶替新清单"这回事（探针 _probe_head_cache.py 第 3 组盯这条）。
HEAD_CACHE_DIR = os.path.join(TREE_DIR, "_HEAD清单")


def head_rels(path):
    """HEAD 那棵树的文件名清单（相对路径）。优先吃盘上 sidecar，没有才跑 git。"""
    if path in _HEAD_CACHE:
        return _HEAD_CACHE[path]
    head = SF.local_head(path)
    side = ""
    if head:
        try:
            os.makedirs(HEAD_CACHE_DIR, exist_ok=True)
            side = os.path.join(HEAD_CACHE_DIR, "%s__%s.nul" % (os.path.basename(path), head[:12]))
        except OSError as ex:
            log("  %s HEAD 清单目录建不出来（%s）——不影响读数，只是每轮都要重跑一次 ls-tree" % (path, ex))
            side = ""
        if side and os.path.isfile(side) and os.path.getsize(side) > 0:
            names = [x.decode("utf-8", "replace") for x in io.open(side, "rb").read().split(b"\0") if x]
            if names:
                _HEAD_CACHE[path] = names
                return names
    names = _nul(path, ["ls-tree", "-r", "--name-only", "-z", "HEAD"])
    _HEAD_CACHE[path] = names
    if side and names:
        # 先写 .part 再改名：中途断电/被杀只会留下一个没人认的 .part，不会留半截清单当"完整的"用。
        tmp = side + ".part"
        fh = io.open(tmp, "wb")
        fh.write(b"\0".join(n.encode("utf-8") for n in names))
        fh.close()
        os.replace(tmp, side)
    return names


def missing_rels(path, hist_rels=()):
    """还缺的文件 = HEAD 里有、盘上没有（相对路径，已排序）。
    为什么**不**拿 `git status --porcelain` 当读数——11-05 07:0x 每批 rc=128 的根因就在这：
    blobless + --no-checkout 的仓索引几乎是空的（实测索引只 2 条而 HEAD 有 150,416 条），
    于是 status 把同一批路径报**两遍**（一遍 `D ` = HEAD 有索引没、一遍 `??` = 盘上有但没进索引），
    更糟的是未跟踪的目录会被**塌成一条带尾斜杠的条目**（实测多出 `ports/`、`.github/workflows/`、
    `.github/ISSUE_TEMPLATE/` 三条）。尾斜杠 pathspec 的语义是"整个目录"，`ports/` 一条就把
    150,414 个 blob 全塞进同一次按需取 ⇒ 服务端算不完 ⇒ `unable to read sha1 file` ⇒ 整批作废。
    改成照 HEAD 的 tree 点名：`ls-tree -r` 天然只列 blob（不可能给出目录），
    `ls-files` 当"已经落进索引"的证据——实测 `checkout HEAD -- <文件>` 成功时正好把这些条目写进索引
    （探针：2 条 -> 5 条、rc=0），`ls-files -d` 再补上"进了索引但盘上没落全"的那批。
    `hist_rels` 必须剔掉：已经挪进 待复核/ 的文件在 HEAD 里还在、索引里被 --force-remove 过，
    不剔就永远归不了 0，每一轮都会把它们从对象库原样落回工作树、再判一遍红线
    （11-05 实测 8 个 zip 同时在 待复核/ 和仓库根各存一份，白占 0.70 GB）。"""
    need = set(head_rels(path))
    cached = set(_nul(path, ["ls-files", "-z"]))
    gone = set(_nul(path, ["ls-files", "-d", "-z"]))
    return sorted(((need - cached) | (need & gone)) - set(hist_rels))


def group_of(rel):
    """前两级目录当一堆（`ports/<游戏名>` 正好一级一堆）；根目录散文件算 `.` 一堆。
    只用来让一批落在同一个端口里，见 plan_batch 为什么要整堆凑。"""
    parts = rel.split("/")
    if len(parts) >= 3:
        return "/".join(parts[:2])
    if len(parts) == 2:
        return parts[0]
    return "."


def plan_batch(rels, cap=CHUNK_BLOBS):
    """从「还缺的清单」切一批：整堆（同一个端口）优先凑到上限，装不下就把这堆留给下一批。
    为什么要整堆：一个端口落一半，git 重落时会对半截目录报
    `unable to unlink 'ports/abombniball': Directory not empty`，白折腾一趟。
    单堆超上限（alephone-marathon2 解包 3,694 个成员）就切它前 cap 个，下一批接着切。
    为什么批内是具体文件而不是堆名：堆名当 pathspec 会连子树一起吞，见 missing_rels。"""
    groups = {}
    for rel in rels:
        groups.setdefault(group_of(rel), []).append(rel)
    batch = []
    for k in sorted(groups):
        g = groups[k]
        if len(batch) + len(g) > cap:
            return batch if batch else g[:cap]
        batch.extend(g)
    return batch


META_NAMES = ("port.json",)      # 每个端口的元数据：arch / min_glibc / 作者 / 授权说明
_meta_logged = [False]


def is_meta(rel):
    return rel.rsplit("/", 1)[-1] in META_NAMES


def pick_groups(path, hist_rels):
    """这一批的 pathspec 清单 + 个数。
    先落 port.json 再落其余：这条线原本要 150,416 个文件全过一遍 promisor 按需取，
    而"哪些端口能上 R36S/RG353P"这份判据只吃 1,900 来个 port.json（约 0.5~1 MB/千个）。
    链路在几十分钟尺度上抖（11-05 07:40 起 TLS connect error / Empty reply from server 连片），
    把最值钱的那 1% 排在队首，才不会因为对端断流而连判据都拿不到。"""
    missing = missing_rels(path, hist_rels)
    meta = [r for r in missing if is_meta(r)]
    if meta:
        if not _meta_logged[0]:
            _meta_logged[0] = True
            log("  优先档：还缺 %d 个 port.json（能装/不能装的判据），先把这些落完再落其余 %d 个"
                % (len(meta), len(missing) - len(meta)))
        specs = plan_batch(meta)
        return specs, len(specs)
    if _meta_logged[0]:
        _meta_logged[0] = False
        log("  优先档已齐，转入其余文件（还缺 %d 个）" % len(missing))
    specs = plan_batch(missing)
    return specs, len(specs)


def run_batch(path, repo, keys, base):
    """一次 `git checkout HEAD -- <文件...>`：只要这些文件的 blob，走 promisor 按需取。
    返回 (rc, 日志尾巴, 本轮落进对象库的字节)。
    为什么带 HEAD：blobless + --no-checkout 的仓索引是空的（实测只 2 条），而裸 pathspec
    是照着索引找文件的，于是 `git checkout -- ports/xxx` 整批报
    "pathspec did not match any file(s) known to git" 并 rc=1。写成 `checkout HEAD -- <文件>`
    才是"照 HEAD 的 tree 取"，成功时顺带把这些条目补进索引（11-05 07:12 实测 rc=0、索引 2 条 -> 5 条）
    —— 下一批的"还缺多少个"读数因此是准的，见 missing_rels。
    为什么每个都加 `:(literal)`：PortMaster 树里的文件名有 `[]`、`*`、空格
    （`assets/data[0]` 这种），默认 pathspec 会按 glob 解释，一个方括号能把整批匹配歪掉。
    为什么不用 sparse-checkout：它给没选中的条目打 SKIP_WORKTREE，
    那些条目从此不再算"缺"，落文件的循环会假装已经落满。"""
    dirs = [k for k in keys if k.endswith("/")]
    if dirs:
        log("  %s 这批混进 %d 个目录前缀（%s），当场拦掉——目录 pathspec 连子树一起吞，"
            "一整棵树的 blob 塞一次请求就是 rc=128（清单本不该有目录，有就是上游 bug）"
            % (repo, len(dirs), ", ".join(dirs[:3])))
        keys = [k for k in keys if not k.endswith("/")]
    if not keys:
        return 1, "这批被目录前缀拦空了", 0
    clog = os.path.join(TREE_DIR, "_落文件_%s.log" % repo.replace("/", "__"))
    fh = io.open(clog, "wb")
    # gc.auto=0：分批按需取会攒出成百上千个小 pack，git 自己看不过眼就会在批尾拉起
    # `maintenance --auto` → `gc --auto` → `repack -d --cruft`（11-05 07:17 实测，一批刚落完就冒出来）。
    # 那玩意儿一边重排对象库一边握锁，下一批只能等或撞 PermissionError，还把"对象库进了多少字节"
    # 这把进度尺子搅浑（repack 会让 .git/objects 的体积缩水）。这条链要的是"落文件"，不要它顺手做大扫除。
    proc = subprocess.Popen([GIT, "-c", "gc.auto=0", "-C", path, "checkout", "HEAD", "--"]
                            + [":(literal)" + k for k in keys],
                            stdout=fh, stderr=fh, env=net_proxy.env())
    rc = wait(proc, path, repo, base=base)
    tail = io.open(clog, "rb").read()[-2000:].decode("utf-8", "replace").strip()[-180:]
    fh.close()
    return rc, tail, max(0, phase(path)[1] - base)


def materialize_chunked(path, repo, hist_rels, left):
    """blobless 仓分批落 blob，一批最多 CHUNK_BLOBS 个文件。
    11-05 06:0x 实测：一次 `reset --hard` 会让 git 把 150,416 个缺失 blob 打包成**一个**
    请求，服务端 270 秒一个字节没吐，最后 `fatal: could not fetch <oid> from promisor remote`；
    而之前整包 clone 也是三次跑到 16.45 GB 尾部被隧道掀掉。分批之后每批几十到几百 MB，
    断一批只损失一批，进度是累加的。"""
    n = stall = 0
    while left and n < BATCH_LIMIT:
        specs, want = pick_groups(path, hist_rels)
        if not specs:
            break
        n += 1
        if not clear_stale_lock(path, max_age=15):
            return left
        base = phase(path)[1]
        log("  %s 第 %d 批（这批 %d 个文件，还缺 %d 个）：%s%s"
            % (repo, n, want, left,
               ", ".join(s[:60] for s in specs[:3]), " …" if want > 3 else ""))
        rc, tail, gained = run_batch(path, repo, specs, base)
        now = len(missing_rels(path, hist_rels))
        if rc != 0:
            log("  %s 第 %d 批中断 rc=%d：%s" % (repo, n, rc, tail))
        if now >= left and gained < BIG_GAIN:
            stall += 1
            log("  %s 这批没有进展（还缺 %d 个，对象库只进 %.2f MB，连续 %d 次）"
                % (repo, now, gained / 1048576.0, stall))
            if stall >= STALL_GIVEUP:
                log("  %s 连 %d 批零进展，本轮收手——链路或对端在拒，不是本地能修的"
                    % (repo, stall))
                return now
        else:
            stall = 0
            st_now, raw_now = phase(path)
            log("  %s 第 %d 批：%s（还缺 %d -> %d）｜本轮对象库进 %.2f MB｜%s 到 %.2f GB"
                % (repo, n, "落地" if now < left else "半截但对象库在涨",
                   left, now, gained / 1048576.0, st_now, raw_now / 1073741824.0))
        left = now
    return left


def _unshell(name):
    """剥掉 GitHub 包顶上那层 `<repo>-<sha>/`，口径和 `--strip-components=1` 一致。
    两个工具必须说同一套路径，否则 short_files 拿包里的名字去盘上找文件会全找不到。"""
    parts = [p for p in (name or "").split("/") if p not in ("", ".")]
    return "/".join(parts[1:]) if len(parts) > 1 else ""


def _tar_of(repo, head):
    """中转包的名字里带 HEAD 的前 12 位：HEAD 一动就是另一个文件，
    绝不会出现"拿旧包解成 HEAD 的内容"这种错账。"""
    return os.path.join(TAR_SUB, "%s__%s.tar.gz" % (repo.replace("/", "__"), head[:12]))


def _needs_precheck(path):
    """这一份要不要先 `tar -t` 读一遍再碰工作树。
    这道门的价值是"坏包根本不进工作树"，代价是**把整包再读一遍**——
    11-05 15:0x 实测本机 F（ST3000VX000 监控盘，和 pull 那条线同时吃盘）单流只拿到 **6.7 MB/s**，
    33.34 GB 就是 85 分钟；而解包那一路本来就把流读到底，gzip 的 CRC/尾部一坏就 rc≠0
    （探针第 3 组：砍一半的包 `tar -t` 回 `Truncated input file`）。
    所以按体积分档：**小包先验（几秒钟的事，省得把工作树弄脏）；大包只解一遍，让解包当验收**。
    单独成函数是为了探针能直接调它，而不是照抄比较式。"""
    return os.path.getsize(path) < int(TAR_PRECHECK_GB * 1073741824)


def tar_verified(tar):
    """这个 tar.gz 是不是从头到尾完整的：`tar -t -z` 会把整个流读到底，
    gzip 尾部的 CRC/ISIZE 对不上就非零退出。
    为什么要单独验这一道：codeload 不给 Range，下载断在中间是个"看起来像文件"的半截包；
    而 tar 解到一半断在工作树里留下的是**残缺文件**，missing_rels 只看"在不在盘上"，
    会把残缺文件当成不缺——台账于是记一份坏包为已落地。先验再解，坏包根本进不了工作树。
    `-z` 必须写死：本机 `which tar` 是 bsdtar，它能自己嗅压缩格式，而 GNU tar 不嗅
    （中转文件名带 .part 时更是直接被当普通 tar 读）——两套 tar 都得吃同一份命令行才算这道门。
    stdout 走 DEVNULL、不走管道：`-t` 要把 15 万个成员名吐出来，父进程一旦被硬杀，
    管道 4 KB 写满之后 tar.exe 就永远卡在 write 上——文件句柄不还，下一轮的改名/删除
    全部撞 WinError 32（11-05 14:35–14:47 实测：孤儿 tar.exe 29932 CPU 只有 22.9 s，
    15 分钟没前进过一个字节，却把 33.34 GB 的包攥得死死的）。
    重定向到 DEVNULL 后，孤儿最多自己跑完十几分钟然后退出并放句柄，卡死变成"慢一点"。"""
    r = subprocess.run([TAR, "-t", "-z", "-f", tar],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3600)
    if r.returncode != 0:
        log("    tar -t 验包不过 rc=%d：%s"
            % (r.returncode, (r.stderr or b"").decode("utf-8", "replace").strip()[-200:]))
        return False
    return True


def watch_curl(proc, repo, part, gb_limit):
    """盯一条 tar.gz 下载的进度并守住两条盘/带宽的门：
    新字节、体积上限、盘余量下限、总时长。
    这里**不能**复用 phase()：这条路上 pack 不动、工作树也归 tar 落，
    phase() 会一路读到 0.00 GB，然后被冻结门把一条 13 MB/s 健康跑的下载杀掉
    ——11-05 06:0x 已经因为拿错尺子误杀过两次，别再犯一遍。"""
    t0 = time.time()
    last = -1
    peak = 0
    still = 0
    while proc.poll() is None:
        time.sleep(30)
        try:
            got = os.path.getsize(part)
        except OSError:
            got = 0
        el = time.time() - t0
        free = shutil.disk_usage(ROOT).free / 1073741824.0
        if got < peak:
            # 体积倒退不是"没进展"，是有人在把这个文件从头再开一遍（curl 自己的重试、或别的进程动了它）。
            # 这时候继续等只是在等一份已经被丢掉的重下——立刻收手，让外面那轮重新起一条。
            log("  %s tarball 从 %.2f GB 缩回 %.2f GB——在途的包被人重开/清零了（curl 的 --retry 就是这个形状），"
                "这条已经不是在续写，杀掉让下一轮从头起，不留假断点" % (repo, peak / 1073741824.0,
                                                                      got / 1073741824.0))
            proc.kill()
            return -9
        if got > last:
            log("  %s tarball %.2f GB｜%.0f s｜%.2f MB/s｜盘余 %.1f GB"
                % (repo, got / 1073741824.0, el, (got - max(last, 0)) / 1048576.0 / 30.0, free))
            still = 0
        else:
            still += 1
            log("  %s tarball %.2f GB｜%.0f s｜没新字节（连续 %.0f s）｜盘余 %.1f GB"
                % (repo, got / 1073741824.0, el, still * 30, free))
        last = got
        peak = max(peak, got)
        if peak == 0 and el > 15 * 60:
            # 用的是 peak 不是 got：got 会因为文件被重开而变回 0，那已经被上面那条接住了。
            log("  %s tarball 15 分钟一个字节没来，杀掉——codeload 是边压边吐的流，"
                "这形状是链路断了，不是服务端在算包" % repo)
            proc.kill()
            return -9
        if got > 0 and still * 30 >= TAR_STALL_S:
            log("  %s tarball 连续 %.0f s 没新字节，杀掉" % (repo, still * 30))
            proc.kill()
            return -9
        if got > gb_limit * 1073741824:
            log("  %s tarball 已经 %.2f GB > 上限 %.1f GB，杀掉——"
                "工作树预算判错了也不该让中转包把盘吃干" % (repo, got / 1073741824.0, gb_limit))
            proc.kill()
            return -9
        if free < FREE_FLOOR_GB:
            log("  %s 盘余 %.1f GB 跌破下限 %.1f GB，杀掉这条下载——"
                "同机 pull 那条线正在吃 210 GB，先把盘让给它，包下好也解不开"
                % (repo, free, FREE_FLOOR_GB))
            proc.kill()
            return -9
        if el > TAR_WAIT_S:
            log("  %s tarball 跑了 %.0f 分钟没完（上限 %.0f 分钟），杀掉判失败"
                % (repo, el / 60.0, TAR_WAIT_S / 60.0))
            proc.kill()
            return -9
    return proc.returncode


def tar_size_limit(budget_gb):
    """下载侧的体积门（GB）。单独成函数是为了让探针能直接调它判这条门，而不是照抄算式。"""
    # codeload 不认 Range，"判小了"要把已经收到的十几 GB 整包作废从头再来（11-05 实测同一棵
    # PortMaster-New 三次跑到 16.45 GB 都被掀断、每次都是零起步），而"判大了"只多占一会儿中转盘——
    # 真正守盘的是 watch_curl 里每 30 s 一次的 FREE_FLOOR_GB 采样，以及解包前那道按预算复查的 gate。
    # 系数从 2 提到 3：11-05 11:0x 这棵树的包已经流到 32 GB，而 GitHub 报整仓 .git 是 37.02 GB，
    # 按 budget*2 算出来的 44 GB 只剩 19% 余量——一棵树的 tar.gz 比它的打包预算大是常态，
    # 拿预算当尺子留一格余量不够，就会在终点线前把整包掀掉。
    return min(TAR_MAX_GB, max(budget_gb * 3.0, 10.0))


def _adopt_complete_part(repo, part, tar, pend, trunc, size):
    """把"流跑完了但还没人读到底"的 `.part` 收到正式通道上，返回下一步该解/该用的路径（None = 本轮收手）。
    小包先 `tar -t` 验一遍再给正式名；大包直接挂 `.unverified` 交给解包验收（见 `_needs_precheck`）——
    同一个 33.34 GB 在这台机器上读一遍是 85 分钟，读两遍就是白烧 85 分钟。"""
    gb = size / 1073741824.0
    try:
        os.replace(part, pend)
    except OSError as ex:
        log("  %s 孤儿 .part（%.2f GB）改名失败：%s｜%s——本轮收手：这几十 GB 既不删也不重下"
            % (repo, gb, type(ex).__name__, HELD_MSG))
        return None
    if not _needs_precheck(pend):
        log("  %s 收下跑完没验的整包（%.2f GB）→ %s：大包不再多读一遍 `tar -t`，"
            "解包读到底就转正式名，读不到头按半截处理" % (repo, gb, os.path.basename(pend)))
        return pend
    if tar_verified(pend):
        try:
            os.replace(pend, tar)
        except OSError as ex:
            log("  %s 验过了但转正式名失败：%s｜%s——留在 %s，下一轮直接解它"
                % (repo, type(ex).__name__, HELD_MSG, os.path.basename(pend)))
            return pend
        log("  %s 小包（%.2f GB）先验后收，转成整包 %s" % (repo, gb, os.path.basename(tar)))
        return tar
    log("  %s 小包（%.2f GB）`tar -t` 验不过（gzip 尾部/CRC 对不上）——按半截包处理" % (repo, gb))
    try:
        os.replace(pend, trunc)
    except OSError as ex:
        log("  %s 半截包改名失败：%s——%s 留在原地，下一轮开工前会认出它" % (repo, type(ex).__name__, pend))
        return None
    return trunc


def _keep_trunc(repo, part, trunc, min_keep, why):
    """断流/验不过时把收到的字节保住（改名成 .trunc），而不是整批删掉。
    codeload 不认 Range：删掉 = 这一趟的字节全作废，下一轮从 0 起步。
    11-05 实测 PortsMaster/PortMaster-New 三次流到 16.45 / 33.34 GB 都被掀断、每次删掉重来，
    盘余在 152↔181 GB 之间来回倒——烧的是带宽，换不到一个文件落地。
    两个例外要让路：字节太少（解不出东西）和盘已跌破 FREE_FLOOR_GB（保住包就是把盘占死，
    同机 pull 那条线还在等盘）。
    返回 .trunc 路径；返回 None 时 .part 要么已删，要么留在原地等下一轮的孤儿分支认领。"""
    size = os.path.getsize(part) if os.path.isfile(part) else 0
    free_now = shutil.disk_usage(ROOT).free / 1073741824.0
    if size < min_keep:
        log("  %s %s｜只收到 %.2f GB < 保底 %.1f GB，解不出东西——删掉 .part，下一轮从头重下"
            % (repo, why, size / 1073741824.0, TRUNC_KEEP_GB))
    elif free_now < FREE_FLOOR_GB:
        log("  %s %s｜收到 %.2f GB，但盘余 %.1f GB 已跌破下限 %.1f GB——保住包就是把盘占死，"
            "删掉让路，整包重下留给盘宽裕的那一轮"
            % (repo, why, size / 1073741824.0, free_now, FREE_FLOOR_GB))
    else:
        try:
            os.replace(part, trunc)
            log("  %s %s｜保住半截包 %s（%.2f GB）——本轮解它，落多少算多少，缺口交给分批补；"
                "它不记作「验过的整包」" % (repo, why, os.path.basename(trunc), size / 1073741824.0))
            return trunc
        except OSError as ex:
            log("  %s 半截包改名失败：%s——.part 留在原地，下一轮开工前会认出它"
                % (repo, type(ex).__name__))
            return None
    drop_or_bail(repo, part, "删掉 .part，下一轮从头重下（删不动就留在原地，"
                             "下一轮开工前的孤儿分支认领它）")
    return None


HELD_MSG = ("这个文件还被别的进程攥着。最可能的是上一轮 `tar -t` 验包留下的孤儿 tar.exe"
            "（父进程被硬杀后它卡在写满的管道上，句柄不还）。本轮不动它，也不另起一条下载抢同一个路径；"
            "点名用 `tasklist /FI \"IMAGENAME eq tar.exe\"`，确认是孤儿再 `taskkill /F /PID <那个>`（不带 /T）")


def drop_or_bail(repo, path, done_msg):
    """删掉一个中转文件。删不动时**返回 False 让调用方收手**，不把栈抛出去。
    11-05 14:47:29 第 13 轮就是这么死的：`os.replace` 撞 WinError 32 之后代码照样往下走
    `os.remove(part)`，同一道拒绝把它整条线程打断，日志里留下的是一行 traceback 而不是一句"本轮收手"。"""
    if not os.path.isfile(path):
        return True
    try:
        os.remove(path)
    except OSError as ex:
        log("  %s 删不掉 %s：%s｜%s" % (repo, os.path.basename(path), type(ex).__name__, HELD_MSG))
        return False
    log("  %s %s" % (repo, done_msg))
    return True


def reap_stale_tars(repo):
    """工作树确认落满之后，把这仓在中转盘上留下的字节腾掉（只动 >= TAR_REAP_GB 的）。

    判据只有一条，而且是从盘上读的：调用方已经确认 HEAD 对得上、索引里一个文件都不缺
    （fetch 里 gap 为空 / materialize 落回 0 那两条路）。这时候包里的每个字节都已经以文件的形式
    躺在树里了，留一份压缩着的同一批字节不换任何东西——11-05 15:3x 实测 F 盘余 91 GB，
    而这个中转包一个人就占 33.34 GB，而 pull 那条线排队要 210 GB。
    代价照实说：这棵树以后要是被整本清掉，同一个 HEAD 只能重新下一趟（codeload 不给 Range）。
    小包不碰：几 MB 留着让补跑少下一趟，它压根不占地方；阈值也因此能挡住"把有用的小包一起删光"。
    """
    if not os.path.isdir(TAR_SUB):
        return 0
    prefix = repo.replace("/", "__") + "__"
    min_bytes = int(TAR_REAP_GB * 1073741824)
    freed = 0
    for name in sorted(os.listdir(TAR_SUB)):
        if not name.startswith(prefix):
            continue
        p = os.path.join(TAR_SUB, name)
        size = os.path.getsize(p) if os.path.isfile(p) else 0
        if size < min_bytes:
            continue
        if drop_or_bail(repo, p, "工作树已落满，腾掉中转包 %s（%.2f GB）——"
                                   "包里的字节全都已经以文件躺在树里了，"
                                   "这盘要留给还没下过的那些仓" % (name, size / 1073741824.0)):
            freed += size
    return freed


def curl_reported_complete(clog, size):
    """`_tar_<仓>.log` 末行是不是 curl 跑完时写的那一行、且字节数对得上。
    curl 只在传输结束才写 `-w`，所以"末行 http_code=200 且 size_download == 文件大小"
    就是这份 .part 是全的的**盘上证据**——不需要问网络，也不需要猜 mtime。
    对不上就一律当半截：绝不把"验过的整包"这个签名贴在一个缺尾的包上。"""
    if not os.path.isfile(clog):
        return False
    lines = io.open(clog, "rb").read()[-200:].decode("utf-8", "replace").strip().splitlines()
    if not lines:
        return False
    cols = lines[-1].split()
    if len(cols) < 2 or cols[0] != "200":
        return False
    try:
        return int(cols[1]) == size
    except ValueError:
        return False


def tar_download(repo, head, budget_gb):
    """把 HEAD 那棵树的 tar.gz 弄到中转文件上，返回可用包的路径或 None。
    返回以 `.trunc` 结尾时是**半截包**：下载断了但收到的字节够多，值得解一次（调用方须按尽力对待，
    解完就删、绝不写成"验过的整包"）。小于 TRUNC_KEEP_GB 的残字节直接删，下一轮从头重下。
    验过的旧包直接复用：codeload 不给 Range，重下一遍同一条 HEAD 就是白烧十几 GB 带宽。"""
    tar = _tar_of(repo, head)
    pend = tar + PEND_SUFFIX
    if os.path.isfile(tar):
        # 正式名本身就是验收记录：只有"整包读到底 + rc=0 + 短文件 0 个"那一趟才配得上它，
        # 所以复用**不再重读一遍**——旧写法每轮拿 `tar_verified(tar)` 复检，而 11-05 15:0x 实测
        # 这台机器的 F（ST3000VX000）在并发下单流只吃 6.7 MB/s，33.34 GB 就是每轮白烧 85 分钟。
        log("  %s 复用已验过的中转包 %s（%.2f GB）——codeload 不给 Range，重下没有意义；"
            "这个名字是上一趟把它读到底换来的"
            % (repo, os.path.basename(tar), os.path.getsize(tar) / 1073741824.0))
        return tar
    os.makedirs(TAR_SUB, exist_ok=True)
    trunc = tar + ".trunc"
    part = tar + ".part"
    clog = os.path.join(TREE_DIR, "_tar_%s.log" % repo.replace("/", "__"))
    min_keep = int(TRUNC_KEEP_GB * 1073741824)
    if os.path.isfile(pend) and os.path.getsize(pend) >= min_keep:
        log("  %s 复用上一轮收下的未验包 %s（%.2f GB）——解它：读到底就转正式名，读不到头按半截处理"
            % (repo, os.path.basename(pend), os.path.getsize(pend) / 1073741824.0))
        return pend
    if os.path.isfile(trunc):
        gb = os.path.getsize(trunc) / 1073741824.0
        if gb >= TRUNC_KEEP_GB:
            log("  %s 用上一轮保住的半截包 %s（%.2f GB）——重下这条 HEAD 是把已收到的字节当垃圾，"
                "codeload 又不认 Range；本轮先解它，解多少算多少，剩下的缺口交给分批"
                % (repo, os.path.basename(trunc), gb))
            return trunc
        if not drop_or_bail(repo, trunc, "上一轮留下的半截包只有 %.2f GB（< 保底 %.1f GB），"
                                      "解不出什么——删掉重下" % (gb, TRUNC_KEEP_GB)):
            return None
    if os.path.isfile(part):
        # 孤儿 .part = 上一轮被硬杀（没走到下面那个失败分支）留下的真字节。
        # 先分清它是"跑完了没来得及验"还是"断在半路"——前者交给 _adopt_complete_part 收进正式通道，
        # 后者才当半截包解。判据在盘上（curl 末行），不用问网络。
        size = os.path.getsize(part)
        gb = size / 1073741824.0
        if size >= min_keep and curl_reported_complete(clog, size):
            log("  %s 孤儿 .part（%.2f GB）的 curl 末行报 200 且字节数对得上——这是跑完没验的整包，不重下"
                % (repo, gb))
            return _adopt_complete_part(repo, part, tar, pend, trunc, size)
        if size >= min_keep:
            try:
                os.replace(part, trunc)
                log("  %s 把孤儿 .part（%.2f GB）转成半截包 %s，本轮直接解它"
                    % (repo, os.path.getsize(trunc) / 1073741824.0, os.path.basename(trunc)))
                return trunc
            except OSError as ex:
                log("  %s 孤儿 .part 改名失败：%s｜%s——本轮收手，不重下也不抢同一个路径"
                    % (repo, type(ex).__name__, HELD_MSG))
                return None
        if not drop_or_bail(repo, part, "孤儿 .part 只有 %.2f GB（< 保底 %.1f GB），"
                                       "解不出东西——删掉从头重下" % (gb, TRUNC_KEEP_GB)):
            return None
    url = "https://codeload.github.com/%s/tar.gz/%s" % (repo, head)
    gb_limit = tar_size_limit(budget_gb)
    free = shutil.disk_usage(ROOT).free / 1073741824.0
    if free - FREE_FLOOR_GB < gb_limit:
        log("  %s 不下整包：盘余 %.1f GB，扣掉 %.1f GB 下限不够放 %.1f GB 的中转包"
            % (repo, free, FREE_FLOOR_GB, gb_limit))
        return None
    # --speed-limit/--speed-time 是 curl 自己的断流闸：低于 20 KB/s 连着 60 s 就退（rc=28），
    # 比等我们 30 s 一采样的监视器快一步，而且它算的是"这条连接的速度"，不用猜。
    # 不带 --retry：11-05 09:00 实测，`--retry 2` 触发的重试会**把 `-o` 那个文件重新开一遍（O_TRUNC）**，
    # 于是 11.57 GB 的在途进度当场清零——盘上留下的 `.part` 是 0 字节、盘余从 237.5 GB 弹回 249.1 GB，
    # 而监视器下一拍读到 0.00 GB 还会把它当成"一个字节都没来过"。
    # 续跑交给外面那条循环（每轮重起 python、先验包再解），绝不让 curl 自己悄悄从头再来。
    cmd = [CURL, "-sS", "-L", "--fail", "-o", part,
           "--speed-limit", "20480", "--speed-time", "60",
           "-w", "%{http_code} %{size_download} %{speed_download}", url]
    log("  %s 开始下整包 tar.gz（上限 %.1f GB，盘余 %.1f GB，%s）"
        % (repo, gb_limit, free, net_proxy.describe()))
    t0 = time.time()
    fh = io.open(clog, "wb")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=fh, env=net_proxy.env())
    rc = watch_curl(proc, repo, part, gb_limit)
    el = time.time() - t0
    fh.close()
    size = os.path.getsize(part) if os.path.isfile(part) else 0
    if rc != 0:
        tail = io.open(clog, "rb").read()[-1200:].decode("utf-8", "replace").strip()[-200:]
        log("  %s tarball 失败 rc=%d｜%.2f GB｜%.0f s｜%s"
            % (repo, rc, size / 1073741824.0, el, tail))
        return _keep_trunc(repo, part, trunc, min_keep, "下载中断")
    log("  %s tarball 下完：%d 字节｜%.2f GB｜%.0f s｜%.2f MB/s"
        % (repo, size, size / 1073741824.0, el, size / 1048576.0 / max(el, 1)))
    # 收尾不再无条件多读一遍 `tar -t`：小包（< TAR_PRECHECK_GB）验了才给正式名，
    # 大包直接挂 .unverified 交给解包那趟读到底当验收——见 _adopt_complete_part。
    return _adopt_complete_part(repo, part, tar, pend, trunc, size)


def bless_index(path, repo):
    """让索引等于 HEAD 的树——tar 落进来的文件从此算"已经有了"。
    read-tree 只碰树对象（blobless 克隆里树是全的），既不联网也不落文件，
    所以它不会被那条废掉的 promisor 通道拖住。
    为什么必须做这一步：tar 不认识 git，落完文件索引还是空的（实测 2 条 / 150,416 条），
    missing_rels 于是把 15 万个文件全报成缺，下一轮又去撞同一条死通道。"""
    r = subprocess.run([GIT, "-c", "gc.auto=0", "-C", path, "read-tree", "HEAD"],
                       capture_output=True, env=net_proxy.env())
    if r.returncode != 0:
        log("  %s read-tree HEAD 失败 rc=%d：%s"
            % (repo, r.returncode,
               (r.stderr or b"").decode("utf-8", "replace").strip()[-200:]))
        return False
    return True


def short_files(path, repo, tar):
    """解包中途失败时，把"字节数不够"的文件挑出来删掉，让它们重新算缺。返回删了几个。
    为什么只在 tar 非零退出时才付这一趟：中途断的形状是**最后一个文件半截**，
    它前面的都写完了、后面的根本没写。写完了的那个 missing_rels 看不见（它只认在不在盘上），
    于是残缺文件会冒充"已落地"进台账——这正是要防的坏账。
    应有字节数从包自己的清单里来（tarfile 顺着读一遍，顺便就是整包校验）。
    这里**不用** `git diff-files` / `git status` 比内容：11-05 实测本机全局
    `core.autocrlf=true`，一棵正常 checkout 出来的干净树（pypa/packaging，140 个文件）
    被 diff-files 报 43 个"已修改"，加 `-c core.autocrlf=false` 还是 43——
    它比的是"索引 OID vs 换行转换后的工作树"，跟"这个文件是不是半截"根本不是一件事。
    读不动清单（包本身坏了）就返回 None，让调用方退回分批，绝不猜。
    半截包（.trunc，见 tar_download）读到流末尾抛 EOF/压缩错是**预期形状**，
    按已读到的成员照常判，不当"读不动"——否则那半截文件会一路冒充已落地。"""
    try:
        tf = tarfile.open(tar, "r:gz")
    except Exception as ex:                       # noqa: BLE001  EOFError/ReadError 都算读不动
        log("  %s 解包失败后又读不出包的清单（%s）——这一轮不判短文件，退回分批"
            % (repo, type(ex).__name__))
        return None
    cut = 0
    seen = 0
    with tf:
        try:
            for mem in tf:
                if not mem.isfile():
                    continue
                rel = _unshell(mem.name)
                if not rel:
                    continue
                seen += 1
                try:
                    got = os.path.getsize(os.path.join(path, rel))
                except OSError:
                    continue          # 根本没落盘的：本来就算缺，不用管
                if got != mem.size:
                    try:
                        os.remove(os.path.join(path, rel))
                        cut += 1
                        if cut <= 8:
                            log("  %s 短文件：%s 盘上 %d ≠ 包里 %d，删掉重算缺"
                                % (repo, rel[:60], got, mem.size))
                    except OSError as ex:
                        log("  %s 短文件 %s 删不掉：%s——missing_rels 只认在不在盘上，"
                            "它会继续冒充已落地，这条要人工看" % (repo, rel[:60], type(ex).__name__))
        except (EOFError, OSError, tarfile.TarError, zlib.error) as ex:
            # 清单读到一半就断是**半截包（.trunc）的正常形状**，不是"读不动"。
            # 断点之前的成员头部都读到了（tarfile 给 info 时还没碰数据），
            # 所以最后那个半截文件照样能比字节、被删掉——这正是这道门要防的坏账。
            # 断点之后的成员根本没落盘，missing_rels 本来就报它们缺，不必猜。
            log("  %s 包清单读到第 %d 个文件处断（%s）——按已读到的 %d 个判短文件，"
                "断点之前该删的都删了" % (repo, seen, type(ex).__name__, seen))
    if seen == 0:
        log("  %s 一个成员头都没读到（包开头就坏）——这一轮不判短文件，退回分批" % repo)
        return None
    if cut > 8:
        log("  %s 短文件共删 %d 个（只点名了前 8 个）" % (repo, cut))
    return cut


def _free_gb():
    return shutil.disk_usage(ROOT).free / 1073741824.0


def local_disk_bail(tail, free_now):
    """解包非零退出时只判一件事：**这是盘的错，还是包的错**。
    包的错（流断在半路）只能腾盘，它永远过不了验收；盘的错必须把包原样留着——
    codeload 不给 Range，删掉就等于把这几十 GB 的带宽和两三个小时的流清零。
    `tail` 是 bsdtar 的 stderr 尾巴，`free_now` 是当下的盘余。"""
    low = (tail or "").lower()
    return (free_now < FREE_FLOOR_GB or "no space" in low or "disk full" in low
            or "cannot create" in low or "too large" in low)


def drop_last_written(path, repo, since):
    """把解包中途被杀掉时**正在写的那一个文件**删掉，返回删了几个（0 或 1）。
    为什么必须删：`missing_rels` 只认文件在不在盘上，半截的那一个会一路冒充已落地进台账。
    为什么照 ctime 找而不是 mtime：bsdtar 解包会把包里的 mtime 原样盖回文件上，
    按 mtime 找到的"最新"是提交时间而不是写入时间（实测盖得很准，一路会挑错人）；
    ctime 是本地写盘留下的，盖不掉。
    代价：一趟全树 stat（15 万个条目，实测一两分钟），但这条路只在盘被打爆时走。"""
    best, best_ct = None, since
    for dp, dn, fn in os.walk(path):
        if ".git" in dn:
            dn.remove(".git")
        for name in fn:
            p = os.path.join(dp, name)
            try:
                ct = os.stat(p).st_ctime
            except OSError:
                continue
            if ct > best_ct:
                best, best_ct = p, ct
    if not best:
        log("  %s 解包被杀后没找到比开工时间更新的写入痕迹（那半截可能压根没开写）" % repo)
        return 0
    try:
        size = os.path.getsize(best)
        os.remove(best)
    except OSError as ex:
        log("  %s 解包被杀留下的半截文件 %s 处理失败：%s——它可能还冒充已落地，这条要人工看"
            % (repo, best.replace(path + os.sep, "")[:60], type(ex).__name__))
        return 0
    log("  %s 解包被杀：按 ctime 挑出当时正在写的 %s（盘上留了 %.2f MB）删掉，它前面的都写完了"
        % (repo, best.replace(path + os.sep, "")[:60], size / 1048576.0))
    return 1


def drop_trunc(tar, repo, kind="半截包"):
    """解过的残包/未验坏包就地删掉，把中转盘还给工作树和别的线。
    删不掉必须点名：它会一直占着几十 GB，而 missing_rels 看不见它——只有盘余会替我们喊疼。"""
    try:
        gb = os.path.getsize(tar) / 1073741824.0
    except OSError:
        return
    try:
        os.remove(tar)
        log("  %s %s %s 已消耗，腾回 %.2f GB——它不记作「验过的整包」，剩下的缺口由 missing_rels 报给分批"
            % (repo, kind, os.path.basename(tar), gb))
    except OSError as ex:
        log("  %s %s %s（%.2f GB）删不掉：%s——下一轮会照样认出它再解一遍；"
            "盘被它占死时人工删这一个文件即可" % (repo, kind, tar, gb, type(ex).__name__))


def bless_package(tar, repo):
    """`.unverified` → 正式名。这一趟把整包读到底（tar rc=0）且按包里的清单一个短文件都没揪出来，
    这跟 `tar -t` 从头验到尾是同一件事（gzip 的 CRC/尾部的坏了 bsdtar 就非零退出，探针第 3 组钉着），
    而它已经顺手把 33 GB 解完了——不必再多读一遍（见 _needs_precheck）。"""
    canon = tar[:-len(PEND_SUFFIX)]
    try:
        os.replace(tar, canon)
    except OSError as ex:
        log("  %s 解包已读到底但转正式名失败：%s｜%s——下一轮照样复用 %s，只是再解一遍"
            % (repo, type(ex).__name__, HELD_MSG, os.path.basename(tar)))
        return
    log("  %s 解包即验收：%s 读到底、短文件 0 个 → 转成整包 %s（下一轮起复用不必再读一遍）"
        % (repo, os.path.basename(tar), os.path.basename(canon)))


def land_from_tarball(path, repo, head, budget_gb, hist_rels=()):
    """用 codeload 的 tar.gz 一次把整棵工作树落盘，返回落完还缺多少个文件；None = 这条路没走成。
    为什么要另开一条通道：11-05 08:2x 实测 promisor 按需取在这条隧道上已经废了——
    PortsMaster/PortMaster-New 每批 250 s 只进 0.20 MB，批批 `unable to read sha1 file`，
    而同一时刻同一代理上的 codeload tar.gz 跑到 13.5 MB/s。
    同一台 GitHub、同一个代理，差别只在协议：按需取要服务端按上千个 oid 现算包，
    tar.gz 是一份流式归档，服务端只管压，不管你会点哪些文件。
    顺序是"下 → （小包才 `tar -t` 验，大包让解包自己读到底当验收）→ 解 → （解坏了就按包里的清单清短文件）
    → read-tree 对索引 → 报缺口"，每步失败都不碰工作树或只留可复用的东西。
    半截包（.trunc）是这条路的一部分，不是意外：解出来的每个文件都是**完整的文件**
    （最后那半截由 short_files 按包里的清单删掉，重新算缺），所以落地的照实算落地；
    但它永远不写进"验过的整包"那条复用通道，解完就地删，剩下的缺口交给分批补。
    未验包（.unverified）= curl 报完了但没人把流读到底：解它，读到底且一个短文件都没揪出来就
    `bless_package` 转成正式名，否则同上按残包处理。
    走不成时返回 None 让调用方回退分批——这条是新通道，不是新的单点故障。"""
    if not head:
        log("  %s 没有本地 HEAD，tarball 这条路没法定包是哪棵树的" % repo)
        return None
    if not TAR:
        log("  %s 这台机器没有 C:\\Windows\\System32\\tar.exe，tarball 这条路不开——"
            "msys 的 GNU tar 吃不下 F:\\ 绝对路径（实测两种写法都失败），不拿它试" % repo)
        return None
    tar = tar_download(repo, head, budget_gb)
    if not tar:
        return None
    is_trunc = tar.endswith(".trunc")
    is_pend = tar.endswith(PEND_SUFFIX)
    kind = "半截包" if is_trunc else ("未验包" if is_pend else "中转包")
    free = shutil.disk_usage(ROOT).free / 1073741824.0
    # 要多少盘：按仓预算和"包自己的体积"里更大的那个算。gz 永远不会比原树大，
    # 所以 33.34 GB 的包至少说明这棵树有 33.34 GB——TARGETS 里那个 22 GB 是老读数（tree API 截断时估的），
    # 只拿它当门就是把"解到一半盘没了"写成日程。
    pkg_gb = os.path.getsize(tar) / 1073741824.0 if os.path.isfile(tar) else 0.0
    need_gb = max(budget_gb, pkg_gb)
    if free - FREE_FLOOR_GB < need_gb:
        # 包已经到手了，但解完它要把工作树预算那么大的盘腾出来。
        # 这时候硬解会把盘写到 0（Windows 上是整机没命，不是这条线失败），
        # 所以包留着、本轮不解，下一轮盘让出来直接复用。
        # 半截包也一样按整棵树的预算要盘：它装着的是这棵树的前一大截，解多深取决于盘还剩多少，
        # 宁可不解也别一边占着自己的几十 GB 一边把盘写死。
        log("  %s %s已到手，但盘余 %.1f GB 不够解 %.1f GB 的工作树（按预算 %.1f GB 和包体积 %.2f GB 取大的，"
            "下限 %.1f GB）——包留着 %s，下一轮盘让出来直接解"
            % (repo, kind + " " if kind != "中转包" else "", free, need_gb, budget_gb, pkg_gb,
               FREE_FLOOR_GB, tar))
        return None
    t0 = time.time()
    # --strip-components=1：GitHub 的包顶上套一层 `<repo>-<sha>/`，不剥掉就落成一棵套壳树
    # （实测不剥时顶层就多一个 packaging-main/，整个树全在壳里，missing_rels 会判 15 万个全缺）。
    # 不带 --overwrite：bsdtar 不认这个选项（实测 rc=1 直接拒），而它默认就是盖——
    # 实测把一个文件写糊成 10 字节再原样重解一遍，它回到 2255 字节且 rc=0。
    # 这条"重解同一条 HEAD 没有副作用"就是这条路可续的依据。
    cmd = [TAR, "-x", "-z", "-C", path, "--strip-components=1", "-f", tar]
    clog = os.path.join(TREE_DIR, "_解包_%s.log" % repo.replace("/", "__"))
    fh = io.open(clog, "wb")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=fh)
    # 解包期间盯着盘：开工前那道门只能按"包有多大"估工作树，估不准（gzip 比率谁也不知道）。
    # 11-05 15:3x 实测这棵树解到 15 分钟就吃掉 7 GB、0.49 GB/分，而同一块 F 上还有 pull 那条线在排队——
    # 让它一路解到 0 就是整机没命。跌破下限就杀掉，**包留着**（这不是包的错）。
    free0 = shutil.disk_usage(ROOT).free
    disk_hit = ""
    while True:
        try:
            rc = proc.wait(30)
            break
        except subprocess.TimeoutExpired:
            pass
        free_raw = shutil.disk_usage(ROOT).free
        free_now = free_raw / 1073741824.0
        log("  %s 解包中：已落 %.2f GB｜%.0f s｜盘余 %.1f GB（跌破 %.1f GB 就收手）"
            % (repo, (free0 - free_raw) / 1073741824.0, time.time() - t0,
               free_now, FREE_FLOOR_GB))
        if free_now < FREE_FLOOR_GB:
            proc.kill()
            rc = proc.wait()
            disk_hit = "盘余 %.1f GB 跌破下限 %.1f GB" % (free_now, FREE_FLOOR_GB)
            break
    fh.close()
    tail = io.open(clog, "rb").read()[-1500:].decode("utf-8", "replace").strip()[-250:]
    if disk_hit:
        # 盘先动的手。三件事按这个判断改：
        #   1) 只清"当时正在写的那一个"（按 ctime 挑），不用再把 33 GB 的清单读一遍——盘已经没位置了；
        #   2) 包原样留着（它还是 .unverified / .tar.gz），下一轮盘宽裕时 tar_download 认同一个名字接着解；
        #   3) 本轮不写台账、不报缺口，剩下的交给下一轮。
        cut = drop_last_written(path, repo, t0)
        log("  %s tar 解包被本地盘拦停（%s）｜包 %s 留着不删——codeload 不给 Range，"
            "删它等于把这趟流清零｜已落盘的算落地，删掉 %d 个半截的"
            % (repo, disk_hit, os.path.basename(tar), cut))
        return None
    cut = 0
    if rc != 0 or is_trunc or is_pend:
        # 解包中途非零退出不能整个弃掉：验过的整包走到这里，剩下的失败只能是本地的
        # （盘满、路径撞了目录、没权限）；半截包走到这里更是**预期**——流到头了它必然非零。
        # 弃掉 = 退回分批 = 把已经落好的十几万个文件再撞一遍那条废掉的 promisor 通道。
        # 留着 = 必须先把"半截的那一个"揪出来，否则它冒充已落地——这就是 short_files 的活。
        # 半截包不论 rc 是几都要清这一遍：bsdtar 对截断的 gzip 尾部**未必**非零退出，
        # 它要是"安静地成功"，最后那半截就进了台账；多读一遍清单换掉这个可能，值。
        log("  %s tar 解包 rc=%d%s：%s｜先按包里的清单清短文件，再对齐索引"
            % (repo, rc, "（%s，本来就会停在流末尾）" % kind if is_trunc else "", tail))
        cut = short_files(path, repo, tar)
        if cut is None:
            if is_trunc or (is_pend and not local_disk_bail(tail, _free_gb())):
                drop_trunc(tar, repo, kind)
            return None
    else:
        log("  %s tar 解包收工：%.0f s" % (repo, time.time() - t0))
    if is_pend and rc == 0 and not cut:
        # 读到底 + 一个短文件都没揪出来 = 这一趟已经替 `tar -t` 把整包验完了
        bless_package(tar, repo)
    elif is_trunc or (is_pend and (rc != 0 or cut)):
        # 残包一次性消耗：它的字节要么已经变成工作树里的文件，要么根本没解出来；
        # 留在中转盘上只是占着几十 GB 让别的线无路可走，而它过不了整包那道验收、不存在"复用价值"。
        # 唯一的例外是盘先动的手（盘满/写不下）：那不是包的错，删掉等于把两三个小时的流清零，
        # 留着让下一轮盘宽裕时接着解——判据见 local_disk_bail。
        if is_pend and not is_trunc and local_disk_bail(tail, _free_gb()):
            log("  %s 未验包非零退出，但 stderr/盘余指向本地盘而不是包（%s）——包 %s 留着，"
                "下一轮盘让开接着解" % (repo, tail[:80], os.path.basename(tar)))
        else:
            drop_trunc(tar, repo, kind)
    if not bless_index(path, repo):
        return None
    # 对齐索引之后不必再碰索引条目：条目在索引里、文件不在盘上，正是 `ls-files -d` 报"缺"的形状，
    # missing_rels 会把这些捞回来交给分批补。这里要是 force-remove 了条目，
    # 反而多一层反查、多一处对不上的机会。
    left = len(missing_rels(path, hist_rels))
    log("  %s tarball 这条路落完：%s盘上 %.2f GB｜还缺 %d 个%s"
        % (repo, "%s尽力解过（没转成正式名）、" % kind if (is_trunc or is_pend) and
           not (is_pend and rc == 0 and not cut) else "",
           worktree_bytes(path) / 1073741824.0, left,
           "（按包里的清单删掉 %d 个短文件）" % cut if cut else ""))
    return left


def materialize(path, repo, hist_rels, budget_gb=None):
    """把工作树落到和 HEAD 一致，返回还缺的文件数（0 = 齐）。
    blobless 仓走 materialize_chunked 分目录要 blob；整包 clone 的仓本地已有全部 blob，
    一次 reset --hard 就从本地 pack 落满（不联网），只需防隧道断在检出中途。
    命令选 reset --hard 而不是 checkout -f：clone --no-checkout 之后索引是空的，
    `checkout -- .` 照着空索引办事等于什么都不做；而 11-04 实测 checkout -f 照着被中断的
    残缺索引办事，报"重检出后仍缺 1137 个文件"。reset --hard 先从 HEAD 的 tree 重建索引再落文件。
    11-05 08:2x 改序：blobless 仓先试 tarball 整棵落盘，promisor 分批只补 tar 落剩的尾巴。
    换序的原因在实测——`unable to read sha1 file` 批批复现、每批 250 s 只进 0.20 MB，
    而同一时刻同一代理上的 codeload tar.gz 是 13.5 MB/s。缺口小于 TAR_MIN_GAP 还走分批：
    11-05 那 1,768 个 port.json 就是分批落的（小文件 promisor 吃得下），
    为最后几十个文件去下十几 GB 整包是浪费。"""
    left = len(missing_rels(path, hist_rels))
    if left and is_partial(path) and left >= TAR_MIN_GAP:
        landed = land_from_tarball(path, repo, SF.local_head(path),
                                   budget_gb or default_budget(repo), hist_rels)
        if landed is not None:
            return landed
        left = len(missing_rels(path, hist_rels))
    if left and is_partial(path):
        return materialize_chunked(path, repo, hist_rels, left)
    n = 0
    while left and n < BLOB_ROUNDS:
        n += 1
        log("  %s 落文件第 %d/%d 轮：还缺 %d 个（已落盘的走本地对象库，不重下）" % (repo, n, BLOB_ROUNDS, left))
        # wait() 返回时我们的 git 已经没了，所以它留下的 index.lock 一定是死锁，可以直接抹。
        if not clear_stale_lock(path, max_age=15):
            return left
        # 基线 = 这一轮开始前盘上已有的体积：骨架 pack（blobless 仓是几 MB）不该算成"本轮在动"，
        # 否则服务端还在算过滤包时 got 恒 >0，20 分钟的等首字节宽限永远用不上。
        base = phase(path)[1]
        clog = os.path.join(TREE_DIR, "_落文件_%s.log" % repo.replace("/", "__"))
        fh = io.open(clog, "wb")
        proc = subprocess.Popen([GIT, "-C", path, "reset", "--hard", "HEAD"],
                                stdout=fh, stderr=fh, env=net_proxy.env())
        rc = wait(proc, path, repo, base=base)
        tail = io.open(clog, "rb").read()[-2000:].decode("utf-8", "replace").strip()[-180:]
        fh.close()
        if rc != 0:
            log("  %s 第 %d 轮中断 rc=%d：%s｜剩下的下一轮接着落" % (repo, n, rc, tail))
        left = len(missing_rels(path, hist_rels))
    return left


def fetch(repo, budget_gb):
    path = dst_of(repo)
    url = "https://github.com/" + repo
    head = SF.remote_sha(url)
    if not head:
        log("  %s 认不到远端 HEAD，跳过不动（不把「没确认」写成「已镜像」）" % repo)
        return None
    _hist_n, _hist_b, hist_rels = prior_holds(repo)
    if SF.local_head(path) == head:
        gap = missing_rels(path, hist_rels)
        if gap:
            log("  %s HEAD 相符但工作树缺 %d 个条目，先试整包 tar.gz，落剩的再分批补" % (repo, len(gap)))
            left = materialize(path, repo, hist_rels, budget_gb)
            if left:
                log("  %s 补跑到上限仍缺 %d 个文件，本轮判失败，不动台账" % (repo, left))
                return None
            verify(repo, path, head, "补检出")
            reap_stale_tars(repo)
            return "补检出"
        if not in_ledger(repo):
            verify(repo, path, head, "追认")
        else:
            log("  %s 已相符（HEAD %s，工作树对得上索引；另有 %d 个已挪进待复核，不算缺）"
                % (repo, head[:10], _hist_n))
        reap_stale_tars(repo)
        return "已相符"
    if os.path.isdir(path) and not SF.local_head(path):
        leftovers = os.listdir(path)
        log("  %s 是上次 clone 打断的残留（%d 个条目、无 HEAD），清掉重下" % (repo, len(leftovers)))
        if not rmtree_checked(path):
            log("  %s 残留目录删不掉（被占用？只读？），本轮不碰它——"
                "让 git 撞 'destination path already exists' 再猜一遍没意义" % repo)
            return None
    os.makedirs(TREE_DIR, exist_ok=True)
    # http.version=HTTP/1.1：curl 56 那类"读到一半连接被重置"在 HTTP/2 多路复用 + 代理隧道
    # 上更容易整条作废。只在这条命令上盖，不动全局 git 配置（那是机器级改动，不碰）。
    cmd = [GIT, "clone", "--depth", "1", "--single-branch", "--no-tags",
           "-c", "http.version=HTTP/1.1"]
    partial = budget_gb >= PARTIAL_FROM_GB
    if partial:
        # 空工作树：blob 全部留到 materialize() 里分轮要，断了也只损失当前一批。
        cmd += ["--filter=blob:none", "--no-checkout"]
    cmd += net_proxy.git_flags() + [url, path]
    log("  %s 开始浅克隆（预算 %.1f GB，%s，%s）"
        % (repo, budget_gb, "骨架+分轮落 blob" if partial else "一次落满", net_proxy.describe()))
    t0 = time.time()
    # 子进程输出必须落文件，不能挂 PIPE：11-04 实测挂 PIPE 时 git checkout 写到管道满就永久卡死
    # （CPU 停在 24.765625 s 不再动，工作树 212 个文件 / 2.79 GB 冻结 7 分钟，看不出来是在跑）。
    clog = os.path.join(TREE_DIR, "_clone_%s.log" % repo.replace("/", "__"))
    fh = io.open(clog, "wb")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=fh, env=net_proxy.env())
    rc = wait(proc, path, repo)
    el = time.time() - t0
    if rc != 0:
        fh.close()
        tail = io.open(clog, "rb").read()[-4000:].decode("utf-8", "replace")
        log("  %s clone 失败 rc=%d：%s" % (repo, rc, tail.strip()[-300:]))
        return None
    fh.close()
    if not SF.local_head(path):
        log("  %s clone 退出码 0 但没有 HEAD，按失败处理" % repo)
        return None
    left = materialize(path, repo, hist_rels, budget_gb)
    if left:
        log("  %s clone 之后补跑到上限仍缺 %d 个文件，按失败处理，不写台账" % (repo, left))
        return None
    log("  %s clone 用时 %.0f s" % (repo, el))
    gb, files = verify(repo, path, head, "新下")
    reap_stale_tars(repo)
    if gb > budget_gb * 1.2:
        log("  超预算：实测 %.2f GB > 预算 %.1f GB ×1.2（tree API 截断过的仓会这样）" % (gb, budget_gb))
    return "新下"


def put(repo, head, files, total, susp, susp_bytes, state, note):
    new = not os.path.exists(LEDGER)
    rows = []
    if not new:
        with io.open(LEDGER, encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh, delimiter="\t") if r["repo"] != repo]
    rows.append({"repo": repo, "head": head[:12] if head else "", "commit": SF.commit_at(dst_of(repo)),
                 "files": files, "bytes_gb": "%.2f" % (total / 1073741824.0),
                 "suspect": susp, "susp_gb": "%.2f" % (susp_bytes / 1073741824.0),
                 "state": state, "note": note.replace("\t", " ")})
    with io.open(LEDGER, "w", encoding="utf-8", newline="") as fh:
        fh.write("\t".join(LEDGER_HDR) + "\n")
        for r in rows:
            fh.write("\t".join(str(r.get(k, "")) for k in LEDGER_HDR) + "\n")


def cmd_list(_a):
    log("掌机端口包目标：%d 个" % len(TARGETS))
    for repo, gb, why in TARGETS:
        path = dst_of(repo)
        head = SF.local_head(path)
        mark = "已有 " + head[:10] + " / " + SF.commit_at(path) if head else "未下"
        log("  %-40s 预算 %4.1f GB｜%s｜%s" % (repo, gb, mark, why))
    return 0


def cmd_fetch(args):
    only = [a for a in (args or []) if "/" in a]
    log("== 端口包抓取开始（%s）==" % (", ".join(only) if only else "全部"))
    ok = fail = 0
    for repo, gb, _why in TARGETS:
        if only and repo not in only:
            continue
        r = fetch(repo, gb)
        if r is None:
            fail += 1
        else:
            ok += 1
    log("完成：成功 %d / 失败 %d｜盘上目录 %s" % (ok, fail, TREE_DIR))
    return 0 if fail == 0 else 1


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "list"
    args = argv[2:]
    if not net_proxy.alive():
        log(net_proxy.describe() + "｜这批是 4~22 GB 的树，直连（0.06 MB/s）下要下几个月，先不起代理就别跑")
        if "--force" not in args:
            log("  已停：加 --force 才允许直连硬跑")
            return 1
    return {"list": cmd_list, "fetch": cmd_fetch}.get(cmd, cmd_list)(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
