# -*- coding: utf-8 -*-
"""M1：资产索引 + Profile Registry（依据 _scratch/强模型方案回复.md §5 M1）。

职责：
  * 索引本地已有资产（movie / version 哈希 / ROM），不重复下载。
  * 对每条出版物给出"可回放 / 被阻塞"的解释（阻塞用 M0 错误码）。
  * 对就绪条目生成经 M0 校验的 Profile。

不做：下载、执行回放、猜测 RAM 地址。资料不足 => 标记阻塞留待补。
运行:
  python -m taspipe.registry build      # 全量评估，写 registry.json
  python -m taspipe.registry status     # 只看汇总
  python -m taspipe.registry assess 5246  # 单条解释
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from .schema import (Profile, Platform, FailureCode, SchemaError, to_dict)

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]                       # F:\开源掌机教程
DEFAULT_LIB = ROOT / "04-游戏资源库" / "TAS输入录像库"
DEFAULT_EMU = ROOT / "02-模拟器库"

# 平台写法有两套：BizHawk Header 的 System（`GEN`/`PSX`/`A26`）和站点 platform 显示名
# （`Genesis`/`GBA`/`Sega CD`）。只认一套会把显示名那一整批游戏白报成"平台未建模"——
# 11-21 全库 4694 部里 Genesis 366、GBA 336、GBC 182、GB 179 走的都是显示名分支。
PLATFORM_MAP = {
    "NES": Platform.NES,
    "FDS": Platform.NES,        # Famicom Disk System，BizHawk 走 NesHawk
    "SNES": Platform.SNES,
    "BSX": Platform.SNES,
    "SGB": Platform.SNES,
    "PSX": Platform.PS1,
    "PS1": Platform.PS1,
    "PLAYSTATION": Platform.PS1,
    "PSP": Platform.PSP,
    "GB": Platform.GB,
    "GAMEBOY": Platform.GB,
    "GBC": Platform.GBC,
    "GAMEBOYCOLOR": Platform.GBC,
    "GBA": Platform.GBA,
    "GAMEBOYADVANCE": Platform.GBA,
    "GEN": Platform.MD,
    "MD": Platform.MD,
    "SMD": Platform.MD,
    "GENESIS": Platform.MD,
    "MEGADRIVE": Platform.MD,
    "PCE": Platform.PCE,
    "PCENGINE": Platform.PCE,
}


# 站点标签里有一批"目标类别"标签，它们决定这部电影该不该有通关判据。
# 11-21 实测教训：Zelda 3232 末段是 Link 在 LEVEL-7 BOSS 房打转后 GAME OVER、停在
# CONTINUE 菜单，而标签写着 Uses a game restart sequence —— 拿末帧当"没通关"是判据错配，
# 结局帧在更早的地方；反过来 Playaround/Demonstration 这类片子本来就没有结局可判。
GOAL_CLASS_TAGS = {
    "Single level": "single_level",
    "Playaround": "playaround",
    "Demonstration": "demonstration",
    "Executes arbitrary code": "code_execution",
    "Aims for maximum score": "score_attack",
    "Second quest/Post game-completion": "post_completion",
    "100% completion": "full_collection",
    "Best ending": "best_ending",
}
NON_COMPLETION_CLASSES = {"single_level", "playaround", "demonstration",
                          "code_execution", "score_attack", "post_completion"}


def goal_class(pub):
    """从标签 + 标题引号里的目标名，判这部片子属不属于"该有通关结局"的那一类。"""
    tags = sorted(set(pub.get("tags") or []))
    classes = sorted({GOAL_CLASS_TAGS[t] for t in tags if t in GOAL_CLASS_TAGS})
    quoted = re.findall(r'"([^"]+)"', pub.get("title") or "")
    if any(c in NON_COMPLETION_CLASSES for c in classes):
        claim = "excluded"          # 站点自己就没说要打穿
    elif classes:
        claim = "explicit"          # 100% / Best ending：结局在，且要求更多
    else:
        claim = "implied"           # 无目标限定 = 默认打穿游戏
    return {"classes": classes, "completion_claim": claim, "quoted_goal": quoted,
            "tail_restart": "Uses a game restart sequence" in tags,
            "starts_from_save": "Starts from a saved state or SRAM" in tags,
            "tags": tags}


# 第三条轴：录制器保真度。它跟"资源齐不齐"是两回事——11-21 拿 3232 量清了：
# 输入流逐帧 0 处不一致、ROM 去头 MD5 与 fm2 头 romChecksum 逐字节相同（东西都齐、
# 转换也没错），可画面走到 GAME OVER 而不是加农。差的是内层录制器（FCEUX 2.2.2）的
# 敌人 RNG/掉落时序，本机没有 FCEUX 管线，所以这批片子即便拿到 ROM 也判不了通关。
# 报表层说过一次就被当成"临时结论"，所以这条轴落进台账：每个消费者都能看到同一句判定。
RECORDER_WHY = {
    "not_judgeable_locally": "内层是 FCEUX 的时序，本机无 FCEUX 管线：整片放得完，"
                             "但通关有风险——这一格只排「补 ROM 值不值得」的优先级，"
                             "不是逐片判决；实测 pass 覆盖它，它不覆盖实测",
    "judgeable_pending_evidence": "BizHawk 原生 bk2，同族核心：时序这一轴不是障碍，"
                                  "但「判得了」只在 NES 上实测过——其余平台还差判据表（看 predicate 那一格），"
                                  "而且仍要 §35 那类截图证词才算 pass",
    "no_movie": "电影不在本地，无从回放",
    "unproven_recorder": "内层录制器不是 BizHawk 也不是已实测的 FCEUX 转换件，本机没验过它的时序",
}

# 先验的已知反例，必须随台账走：只写在注释里就会被当成没有这回事。
# 7429 的 .bk2 由 FCEUX .fm2 转来，先验落在 not_judgeable_locally，但它有 11-21
# 实测的 completion=pass（attempt f4cf348f228f：证词 after_idle，末段 76 张采样
# 73 个互不相同的摘要＝画面一直在动，静止窗不成立）。
# 所以 3232 量出的是"这批有风险"，不是"这批必然判不了"。
FIDELITY_PRIOR_COUNTEREXAMPLES = {
    "not_judgeable_locally": [7429],
}

def fidelity_prior(verdict):
    """随每条 fidelity 走的先验说明：这一格是风险标签，逐片结论只认实测。"""
    return {
        "is_prior_only": True,
        "overridden_by_measured_pass": True,
        "known_counterexamples": list(FIDELITY_PRIOR_COUNTEREXAMPLES.get(verdict, [])),
    }

# 先验分档的已知反例见上面 FIDELITY_PRIOR_COUNTEREXAMPLES（随每条台账走）。
# 这里不再留第二份常量：上一份抄的是没核实过的证词文件名与摘要，死代码留着只会被人当证据。


# 第四条轴，和"资源齐不齐""录制器时序保真"都不是一回事：判据表在这台机器上实测过没有。
# 判据地址、QuickNes/NesHawk 可读窗口、帧量化换算全按 NES 那套映射写；同一个地址在
# SNES/GB/PSX 上不是同一个含义。control.plan 里那道可读窗口闸门对非 NES 是空转
# （NES_READABLE_WINDOWS 只有 NES 的核心），所以这一格必须单独入账，
# 否则 2530 部"待证词就能判"会被读成"补上证词就能判"——里面 NES 只有 401 部。
PREDICATE_TABLE_MEASURED = ("NES",)
PREDICATE_WHY = {
    "table_measured": "NES：判据地址、可读窗口、帧量化换算在这台机器上实测过"
                      "（7429 的 $0081＝HUD ENEMY 就是这么找到的）",
    "table_missing": "本平台没有本机实测过的判据表：地址/域/帧量化沿用 NES 那套映射，"
                     "换平台读到的不是同一个含义。放片和看图不受影响，"
                     "写通关判据要么补本平台判据表，要么只交 §35 截图证词；"
                     "control.plan 用 predicate_platform_unproven 拦在启动前",
}


def predicate_axis(platform_code):
    """判据侧能不能在这台机器上写对——按代码实测范围判，不看片子的资源与录制器。"""
    code = str(platform_code or "")
    verdict = "table_measured" if code in PREDICATE_TABLE_MEASURED else "table_missing"
    why = PREDICATE_WHY[verdict]
    return {"platform": code, "predicate_verdict": verdict,
            "why": why if verdict == "table_measured" else f"{code or '(未知平台)'}：{why}"}


def summarize_predicates(results):
    """台账头的判据表覆盖合计；同样只数已知的取值，缺格或陌生取值就报错。"""
    out = {}
    for r in results:
        verdict = (r.get("predicate") or {}).get("predicate_verdict")
        if verdict not in PREDICATE_WHY:
            raise SchemaError(f"评估条目 {r.get('id')} 的 predicate 缺 predicate_verdict "
                              f"或取值未知（{verdict}）：台账不许静默漏一格")
        out[verdict] = out.get(verdict, 0) + 1
    return out


def recorder_fidelity(movie, movie_note):
    """由电影文件的来源判定"这台录制器在本机能不能判通关"，不看资源齐不齐。"""
    path = (movie or "").replace("\\", "/")
    note = (movie_note or "").upper()
    if "_converted/" in path or "FCEUX" in note:
        recorder = "FCEUX 内层（已转 bk2）"
        verdict = "not_judgeable_locally"
    elif not movie:
        recorder = "电影不在本地"
        verdict = "no_movie"
    else:
        ext = Path(str(movie)).suffix.lower()
        recorder = "BizHawk 原生 bk2" if ext == ".bk2" else f"其它内层 {ext or '(无后缀)'}"
        verdict = "judgeable_pending_evidence" if ext == ".bk2" else "unproven_recorder"
    return {"recorder": recorder, "completion_verdict": verdict,
            "why": RECORDER_WHY[verdict], **fidelity_prior(verdict)}


def summarize_verdicts(results):
    """台账头的通关可判性合计；报表层不许自己再数一遍（数两遍就会有两个口径）。"""
    out = {}
    for r in results:
        verdict = (r.get("fidelity") or {}).get("completion_verdict")
        if verdict not in RECORDER_WHY:
            raise SchemaError(f"评估条目 {r.get('id')} 的 fidelity 缺 completion_verdict "
                              f"或取值未知（{verdict}）：台账不许静默漏一格")
        out[verdict] = out.get(verdict, 0) + 1
    return out


def norm_sha1(s):
    return (s or "").strip().upper()


def load_publications(lib):
    p = Path(lib) / "publications.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    pubs = d["publications"]
    return list(pubs.values()) if isinstance(pubs, dict) else list(pubs)


ROM_ROOTS_CONFIG = "rom_roots.json"
# 只在自有 ROM 池里按这些后缀取候选（压缩包逐条目展开），其余后缀一律不当 ROM。
POOL_ROM_SUFFIX = (".nes", ".fds", ".unf", ".nsf", ".sfc", ".smc", ".swc", ".fig", ".gb", ".gbc",
                   ".gba", ".md", ".smd", ".gen", ".bin", ".pce", ".sgx", ".a26", ".lnx", ".ngp",
                   ".ngc", ".ws", ".wsc", ".virtualboy", ".vb", ".nds", ".ids", ".iso", ".cue",
                   ".chd", ".32x", ".gg", ".sg")


def _sha1_file(path):
    import hashlib
    hh = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            hh.update(chunk)
    return hh.hexdigest().upper()


def pool_rom_roots(lib, extra=()):
    """自有 ROM 池根（不含 roms_verify）：lib/rom_roots.json 或 --rom-root 追加。

    单独成一个函数是因为 index_roms 里 `roots[1:]` 那种按位置切片会在 roms_verify
    不存在时（夹具、或部分索引路径）把第一个真实池根切掉——收录漏了却不报错。
    """
    cfg = Path(lib) / ROM_ROOTS_CONFIG
    roots = []
    if cfg.is_file():
        for item in json.loads(cfg.read_text(encoding="utf-8")):
            roots.append((Path(item["root"]), item.get("scan_archives", True)))
    roots += [(Path(p), True) for p in extra]
    return [(r, scan) for r, scan in roots if r.is_dir()]


def rom_search_roots(lib, extra=()):
    """ROM 搜索根：lib/roms_verify 永远是第一根，其余自有池见 pool_rom_roots。

    追加根只当候选来源，命中仍然只认 SHA-1；文件名或标题相近不算命中。
    """
    return [(Path(lib) / "roms_verify", False)] + pool_rom_roots(lib, extra)


_ROM_INDEX_CACHE = {}


def index_roms(lib, extra_roots=()):
    """各搜索根里 ROM 的 SHA-1 -> [path]（bk2 Header / version 页都用 SHA-1）。

    roms_verify 沿用旧口径：整文件哈希。自有池按后缀白名单收，压缩包展开到条目，
    条目记作 `包路径!条目名`，由控制层在运行时导出独立文件，不改写原包。

    批跑时这条是热点：每个矩阵格都会 resolve_job → index_roms，把整库 ROM 重哈希一遍
    （实测每格多花 2~4 分钟，10 格矩阵光解析就半小时）。这里按「扫描根的文件清单指纹」
    缓存结果：指纹只读元数据（路径+大小+mtime），不读内容；指纹变了就重算。
    """
    lib = Path(lib)
    targets = []          # (path, kind)：kind=None 表示整文件哈希，kind="zip" 表示展开条目
    base = lib / "roms_verify"
    if base.is_dir():
        for f in base.rglob("*"):
            if f.is_file() and f.suffix.lower() not in (".json", ".txt", ".md"):
                targets.append((f, None))
    for root, scan_archives in pool_rom_roots(lib, extra_roots):
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            suffix = f.suffix.lower()
            if scan_archives and suffix == ".zip":
                targets.append((f, "zip"))
            elif suffix in POOL_ROM_SUFFIX:
                targets.append((f, None))

    sig = []
    for f, kind in targets:
        try:
            st = f.stat()
        except OSError:
            continue
        sig.append((str(f), kind or "", st.st_size, st.st_mtime_ns))
    sig = tuple(sorted(sig))
    key = (str(lib.resolve()), tuple(str(r) for r in extra_roots))
    cached = _ROM_INDEX_CACHE.get(key)
    if cached is not None and cached[0] == sig:
        return dict(cached[1])

    idx = {}
    for f, kind in targets:
        if kind is None:
            idx.setdefault(_sha1_file(f), []).append(str(f))
            continue
        try:
            with zipfile.ZipFile(f) as z:
                for info in z.infolist():
                    if info.is_dir() or not info.filename.lower().endswith(POOL_ROM_SUFFIX):
                        continue
                    digest = _sha1_bytes(z.read(info))
                    idx.setdefault(digest, []).append(str(f) + "!" + info.filename)
        except (OSError, zipfile.BadZipFile):
            continue
    _ROM_INDEX_CACHE[key] = (sig, dict(idx))
    return idx


def _sha1_bytes(data):
    import hashlib
    return hashlib.sha1(data).hexdigest().upper()


def index_versions(lib):
    """versions/*.json -> {version_id: {sha1, md5, name, ...}}。"""
    idx = {}
    base = Path(lib) / "versions"
    if not base.is_dir():
        return idx
    for f in base.glob("*.json"):
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        idx[f.stem] = {
            "sha1": norm_sha1(v.get("SHA-1")),
            "md5": (v.get("MD5") or "").strip().upper(),
            "name": v.get("Name", ""),
            "system": v.get("System Code", ""),
        }
    return idx


def discover_bizhawk(emu_root):
    """扫描 BizHawk-<ver>/EmuHawk.exe -> {version: dir}。"""
    out = {}
    base = Path(emu_root) / "BizHawk"
    if not base.is_dir():
        return out
    for d in base.iterdir():
        m = re.fullmatch(r"BizHawk-(.+)", d.name)
        if m and (d / "EmuHawk.exe").is_file():
            out[m.group(1)] = str(d)
    return out


def read_bk2_header(path):
    """读 BizHawk .bk2（zip）的 Header.txt；.zip 外壳则取内部首个 .bk2。

    非 BizHawk 容器返回 None（不臆测）。
    """
    path = str(path)
    try:
        z = zipfile.ZipFile(path)
    except Exception:
        return None
    names = z.namelist()
    header_name = "Header.txt" if "Header.txt" in names else None
    if header_name is None:
        inner = [n for n in names if n.lower().endswith(".bk2")]
        if not inner:
            return None
        try:
            import io
            z = zipfile.ZipFile(io.BytesIO(z.read(inner[0])))
            names = z.namelist()
            header_name = "Header.txt" if "Header.txt" in names else None
        except Exception:
            return None
    if header_name is None:
        return None
    hdr = {}
    # BizHawk 有些版本把 Header.txt 写成带 BOM 的 UTF-8；用 utf-8 解就变成第一个键
    # 前面挂着一个 \ufeff，"SHA1" 读成 "\ufeffSHA1"，身份解析静默退回 version 页
    # （11-21 查臂继承时实测到，台账里 2033 条"version 页"有一部分是这么来的）。
    for line in z.read(header_name).decode("utf-8-sig", "replace").splitlines():
        if " " in line:
            k, v = line.split(" ", 1)
            hdr[k.strip()] = v.strip()
    return hdr or None


# 平台名 → BizHawk 槽位名的唯一权威。system 只决定「用哪个平台的槽位」，
# 核心名仍以台账/电影 Header 声明的为准。编排层（auto._nes_inputs）与三个 CLI
# （record full / pipeline run / backends run-nes）都从这里取，别各写一份默认值。
BIZHAWK_SYSTEMS = {"NES": "NES", "FC": "NES", "FAMICOM": "NES",
                   "SNES": "SNES", "SFC": "SNES", "SUPER NINTENDO": "SNES"}


def bizhawk_replay_inputs(assess, movie=None):
    """回放要用的平台槽位与核心名：台账 platform_code 优先，缺了才读电影 Header 自述。

    未知平台不许默认成 NES。11-22 实测到 record/pipeline 的 CLI 把 system 写死成 NES，
    于是一本 SNES 出版物走了 FC 封面分支（拿 SNES ROM 的 sha1 去查天马 FC 缓存），
    音频那一格也按「NES 发行版」出证——口径错了但产物照样绿灯退出，看不出来。
    """
    plat = str((assess or {}).get("platform_code") or "").strip().upper()
    hdr = read_bk2_header(movie) if movie else None
    source = "platform_code"
    if not plat and hdr:
        plat = str(hdr.get("Platform") or "").strip().upper()
        source = "bk2_header"
    system = BIZHAWK_SYSTEMS.get(plat)
    if system is None:
        raise SchemaError(
            f"无法确定 BizHawk 平台槽位：platform 名={plat or '空'}（取自 {source}）；"
            f"已登记的槽位 {sorted(set(BIZHAWK_SYSTEMS.values()))}，"
            f"不给它兜底成 NES 是要挡住「SNES 被当 NES 出证」")
    core = str((assess or {}).get("core") or "").strip()
    if not core and hdr:
        core = str(hdr.get("Core") or "").strip()
    if not core:
        raise SchemaError(f"平台槽位已定为 {system}，但台账与电影 Header 都没声明 Core，"
                          f"不猜核心名（猜错=用错核心跑片）")
    return {"system": system, "core": core, "platform_source": source}


def resolve_movie(pub, lib):
    """定位真正可回放的 movie 文件。

    local_movie 可能是 .zip 外壳；若同目录有同名 .bk2 优先用它。
    FCEUX .fm2/.fcm/.fm3 不能直接回放：查 _converted/<plat>/<id>.bk2 缓存，
    有则用转换件，无则返回 None + 转换提示（阻塞留待补）。
    返回 (path|None, note)。
    """
    rel = pub.get("local_movie")
    if not rel:
        return None, "索引未记录 local_movie（尚未下载）"
    p = Path(lib) / rel
    if not p.is_file():
        return None, f"索引记录的 movie 不存在: {rel}"
    suf = p.suffix.lower()
    if suf in (".fm2", ".fcm", ".fm3"):
        plat = pub.get("platform") or "NES"
        conv = Path(lib) / "_converted" / plat / f"{pub['id']}.bk2"
        if conv.is_file():
            return str(conv), "FCEUX 电影已转换为 .bk2"
        return None, (f"FCEUX {suf} 需先转换："
                      f"python -m taspipe.fceux convert --pub {pub['id']}")
    if suf == ".smv":
        plat = pub.get("platform") or "SNES"
        conv = Path(lib) / "_converted" / plat / f"{pub['id']}.bk2"
        if conv.is_file():
            return str(conv), "Snes9x SMV 已转换为带 CoreState 的 .bk2"
        return None, (f"Snes9x {suf} 需先转换："
                      f"python -m taspipe.movie_converters convert-pub --pub {pub['id']}")
    if suf == ".zip":
        bk2 = p.with_suffix(".bk2")
        if bk2.is_file():
            return str(bk2), "使用已解压的同名 .bk2"
        try:
            with zipfile.ZipFile(p) as zf:
                if any(name.lower().endswith(".smv") for name in zf.namelist()):
                    plat = pub.get("platform") or "SNES"
                    conv = Path(lib) / "_converted" / plat / f"{pub['id']}.bk2"
                    if conv.is_file():
                        return str(conv), "ZIP 内 Snes9x SMV 已转换为带 CoreState 的 .bk2"
                    return None, (f"ZIP 内 Snes9x SMV 需先转换："
                                  f"python -m taspipe.movie_converters convert-pub --pub {pub['id']}")
        except (OSError, zipfile.BadZipFile):
            pass
        return str(p), "movie 为 .zip 外壳，回放前需解压内部 .bk2"
    return str(p), ""


_BIZHAWK_RE = re.compile(r"(?:bizhawk|emuhawk)\s+([0-9][0-9.]*)", re.I)


def emulator_match(emulator_str, bizhawk_dirs):
    """把 'BizHawk 2.8' 之类映射到本地目录，返回 (目录, 说明, 错误码)。

    错误码只在目录为 None 时有意义，且必须与"缺 ROM"分开：分层统计里把版本问题报成
    missing_resource，会让人误以为补 ROM 就能跑（11-21 我就是这样读错了 SNES 那批）。

    FCEUX 原生管线未接入，但其 .fm2/.fcm 可经 taspipe.fceux 转成 .bk2 走 BizHawk；
    转换后 assess 会改按 bk2 Header 的 emuVersion 匹配本地 BizHawk。

    tasvideos 的 emulator 字段是人工填的自由文本：'Bizhawk 2.9.0'（小写 h）和
    'EmuHawk 2.9.0 (Core: QuickNES)'（可执行文件名）都是 BizHawk 管线，11-21 之前
    被大小写敏感的匹配白挡成“非 BizHawk 管线”。
    """
    s = (emulator_str or "").strip()
    m = _BIZHAWK_RE.match(s)
    if not m:
        if s.lower().startswith(("fceux", "fceu")):
            return None, ("非 BizHawk 原生管线；FCEUX .fm2/.fcm 可经 taspipe.fceux "
                          "转换为 .bk2 后走本地 BizHawk"), FailureCode.UNSUPPORTED_CAPABILITY
        return None, ("非 BizHawk 管线（本 registry 暂未接入）；"
                      f"登记文本 {s!r} 既不是 BizHawk/EmuHawk 写法也不是 FCEUX"), \
            FailureCode.UNSUPPORTED_CAPABILITY
    ver = m.group(1).rstrip(".")
    if ver in bizhawk_dirs:
        return bizhawk_dirs[ver], "", None
    trimmed = re.sub(r"\.0+$", "", ver)
    if trimmed != ver and trimmed in bizhawk_dirs:
        return bizhawk_dirs[trimmed], (f"声明 {ver}，按本地 BizHawk-{trimmed} 目录回放"
                                       f"（同一次发布的两种写法）"), None
    return None, f"本地无 BizHawk {ver}（已有: {', '.join(sorted(bizhawk_dirs)) or '无'}）", \
        FailureCode.EMULATOR_VERSION_ABSENT


def map_platform(pub, header):
    code = (header or {}).get("Platform") or pub.get("platform", "")
    plat = PLATFORM_MAP.get(str(code).strip().upper())
    if plat is not None:
        return plat, code, ""
    if str(code).strip().lower() == "arcade":
        emu = (pub.get("emulator") or "").lower()
        if "mame" in emu:
            return Platform.ARCADE_MAME, code, ""
        if "fbneo" in emu or "finalburn" in emu or "fba" in emu:
            return Platform.ARCADE_FBNEO, code, ""
        return None, code, "Arcade 需先确定 FBNeo/MAME 后端"
    return None, code, (f"平台 {code!r} 尚未在 schema 建模"
                        f"（PLATFORM_MAP 两种写法都没有：Header System 与站点显示名）")


def resolve_identity(pub, lib, ver_idx, bizhawk_dirs):
    """出版物 → 回放身份：电影、平台/核心、本地 BizHawk 目录、所需 ROM 哈希、Profile。

    刻意不看本地有没有 ROM —— 资源就绪是 acquire 的职责。两件事混在 assess 里时，
    ROM 只在网盘的游戏会在 resolve 阶段就被判死，acquire 的网盘钩子永远轮不到
    （11-14 修的死锁）。身份未解析 = 电影缺失/哈希未知/平台未建模/无对应 BizHawk，
    这才是 resolve 阶段该拦的；ROM 缺位只该在 acquire 里拦。
    """
    pid = pub["id"]
    movie, movie_note = resolve_movie(pub, lib)
    header = read_bk2_header(movie) if movie else None

    plat, plat_code, plat_note = map_platform(pub, header)

    # 所需 ROM 哈希：bk2 Header 优先，其次 version 页
    req_sha1 = norm_sha1((header or {}).get("SHA1"))
    hash_src = "bk2 Header" if req_sha1 else ""
    if not req_sha1:
        v = ver_idx.get(pub.get("version_id", ""))
        if v and v["sha1"]:
            req_sha1 = v["sha1"]
            hash_src = "version 页"

    core = (header or {}).get("Core", "")
    emu_ver = (header or {}).get("emuVersion", "")
    emu_str = pub.get("emulator", "")
    pipeline_note = ""
    # FCEUX 电影一旦转换成 .bk2（resolve_movie 命中 _converted 缓存），
    # 回放走的是 BizHawk：按转换件 Header 的 emuVersion 匹配本地 BizHawk，
    # 而不是原出版物登记的 FCEUX 版本。
    if emu_str.lower().startswith(("fceux", "fceu")) and header and core:
        mv = re.search(r"([0-9][0-9.]*)", emu_ver)
        if mv:
            emu_str = f"BizHawk {mv.group(1)}"
    elif header and core and not _BIZHAWK_RE.match(emu_str.strip()):
        # 有 Header 就是 .bk2，而 .bk2 只有 BizHawk 读写得出来；站点 emulator 字段填的是
        # 核心自己的版本号（'Snes9x 1.43 v12'、'BSNES 0.73'），拿它当"非 BizHawk 管线"是白挡。
        mv = re.search(r"([0-9][0-9.]*)", emu_ver)
        if mv:
            pipeline_note = (f"出版物 emulator={emu_str!r} 是核心版本写法；电影文件本身是 .bk2"
                             f"（Header Core={core}），属 BizHawk 管线，改按 Header "
                             f"emuVersion={emu_ver} 选本地臂")
            emu_str = f"BizHawk {mv.group(1)}"
        else:
            # 同为 .bk2，但连 emuVersion 都读不出数字：管线没变，缺的是"按哪个本地臂放"的依据。
            emu_str = ""
            pipeline_note = (f"电影是 .bk2（Core={core}）但 Header emuVersion={emu_ver!r} "
                             f"读不出版本号，选臂需按该核心实测")
    if not emu_str and header and core:
        emu_dir, emu_note, emu_code = None, pipeline_note, FailureCode.EMULATOR_VERSION_UNVERIFIED
    else:
        emu_dir, emu_note, emu_code = emulator_match(emu_str, bizhawk_dirs)
    if emu_dir and pipeline_note:
        emu_note = (emu_note + "；" + pipeline_note) if emu_note else pipeline_note

    # 站点登记的 BizHawk 版本本机没装：先看同一 ROM SHA1 上别的原生 .bk2 用哪个臂，
    # 照抄那台已装且未卡核的臂。把 895 部一律报成"版本没装"是台账在骗人——
    # 11-21 用户实测口径就是"跟版本没关系"，NES 的 DK 3789@2.3.0→5254@2.9 已经这么走通过。
    # 这条不叫通过，叫继承：落成 emulator_version_inherited，跑之前必须显式放行。
    inherited = None
    if emu_dir is None and emu_code is FailureCode.EMULATOR_VERSION_ABSENT and header and req_sha1:
        from .control import _version_trim  # 延迟导入：control 顶层 import registry
        from .fceux import native_reference
        ref = native_reference(req_sha1, lib, plat=pub.get("platform") or "NES",
                               exclude=pid, bizhawk_dirs=bizhawk_dirs)
        if ref:
            used = _version_trim(ref.get("emu_version") or "")
            cand = bizhawk_dirs.get(used)
            if cand:
                inherited = {"pub_id": str(ref["pub_id"]), "declared": emu_str,
                             "used": used, "core": ref.get("core") or core}
                emu_dir = cand
                emu_note = (f"登记 {emu_str} 本机没装，按同 ROM(SHA1={req_sha1[:12]}…) 的原生片 "
                            f"{ref['pub_id']} 改用 BizHawk {used}（Core={inherited['core']}）；"
                            f"跨版本臂需实测确认，未确认前不登记为可回放")

    blockers = []
    if not movie:
        blockers.append((FailureCode.MISSING_RESOURCE, movie_note))
    if not req_sha1:
        blockers.append((FailureCode.MISSING_RESOURCE,
                         "未知所需 ROM 哈希（version 页未抓取且非 bk2）"))
    if plat is None:
        blockers.append((FailureCode.UNSUPPORTED_CAPABILITY, plat_note))
    if not emu_dir and emu_code is not None:
        blockers.append((emu_code, emu_note))
    if inherited:
        blockers.append((FailureCode.EMULATOR_VERSION_INHERITED, emu_note))

    profile = None
    if not [b for b in blockers if b[0] is not FailureCode.EMULATOR_VERSION_INHERITED]:
        try:
            profile = Profile(
                profile_id=f"tasvideos_{pid}",
                game_revision_id=pub.get("version_id") or f"game_{pub.get('game_id')}",
                backend_id="nes_bizhawk" if plat == Platform.NES else f"bizhawk_{plat_code.lower()}",
                platform=plat,
                emulator_fingerprint=emu_ver or pub.get("emulator", ""),
                core=core,
                rom_sha1=req_sha1,
                capability_report={"source": "tasvideos", "movie_ext": pub.get("movie_ext"),
                                   "bizhawk_dir": emu_dir},
            ).validate()
        except SchemaError as e:
            blockers.append((FailureCode.SCHEMA_INVALID, str(e)))
            profile = None

    return {
        "id": pid,
        "game": pub.get("game"),
        "title": pub.get("title"),
        "platform_code": plat_code,
        "platform": plat.value if plat else None,
        "status": "resolved" if not blockers else "unresolved",
        "movie": movie,
        "movie_note": movie_note,
        "required_rom_sha1": req_sha1,
        "hash_source": hash_src,
        "core": core,
        "emulator": pub.get("emulator"),
        "emulator_dir": emu_dir,
        "arm_inherited_from": inherited,
        "profile": to_dict(profile) if profile else None,
        "blockers": [{"code": c.value, "reason": r} for c, r in blockers],
    }


def assess(pub, lib, rom_idx, ver_idx, bizhawk_dirs):
    """身份 + 本地 ROM 命中 = 可回放性评估（不执行、不下载）。

    status 只描述「本地现在就绪」；blocked 不等于身份不清，缺 ROM 的那一类应由
    acquire（本地索引 → 自有网盘钩子 → 外部门控）继续判，registry.build 的汇总口径不变。
    """
    ident = resolve_identity(pub, lib, ver_idx, bizhawk_dirs)
    req_sha1 = ident["required_rom_sha1"]
    rom_match = (rom_idx or {}).get(req_sha1, []) if req_sha1 else []
    blockers = [(FailureCode(b["code"]), b["reason"]) for b in ident["blockers"]]
    if req_sha1 and not rom_match:
        blockers.append((FailureCode.MISSING_RESOURCE,
                         f"无匹配 ROM（需 SHA1={req_sha1}，来源 {ident['hash_source']}）"))
    from .control import PLATFORMS_DRIVER_PROVEN as _PROVEN, driver_stall_version, platform_driver_proven  # 延迟导入：control 顶层就 import registry，绕开环
    stalled = driver_stall_version(Path(ident["emulator_dir"] or "").name)
    if stalled:
        blockers.append((FailureCode.DRIVER_STALL_MEASURED,
                         f"BizHawk {stalled} 在本驱动下不进放映（实测 2.3/2.3.1 两档 0 帧），不启动也不报就绪"))
    if ident["platform"] and not platform_driver_proven(ident["platform"]):
        # ROM 和版本齐只说明资源到位；控制运行器在这个平台跑没跑通过整片是另一件事，
        # 混在一起报就会把「没实测」说成「只差 ROM」（11-21 SNES 那 9 部差点这么登记出去）。
        blockers.append((FailureCode.DRIVER_PLATFORM_UNPROVEN,
                         f"资源/版本齐，但控制运行器实测过整片的平台只有 "
                         f"{', '.join(_PROVEN)}；"
                         f"{ident['platform']} 还没跑过一部，实测用 control run --allow driver_platform_unproven"))
    status = "replayable" if not blockers else "blocked"
    return {
        "id": ident["id"],
        "game": ident["game"],
        "title": ident["title"],
        "platform_code": ident["platform_code"],
        "status": status,
        "identity_status": ident["status"],
        "movie": ident["movie"],
        "movie_note": ident["movie_note"],
        "required_rom_sha1": req_sha1,
        "hash_source": ident["hash_source"],
        "rom_match": rom_match,
        "core": ident["core"],
        "emulator": ident["emulator"],
        "emulator_dir": ident["emulator_dir"],
        "arm_inherited_from": ident.get("arm_inherited_from"),
        "blockers": [{"code": c.value, "reason": r} for c, r in blockers],
        "profile": ident["profile"],
        "goal": goal_class(pub),
        "fidelity": recorder_fidelity(ident["movie"], ident["movie_note"]),
        "predicate": predicate_axis(ident["platform_code"]),
    }


def build(lib, emu_root, out=None, only_ready=False, extra_rom_roots=()):
    pubs = load_publications(lib)
    rom_idx = index_roms(lib, extra_rom_roots)
    ver_idx = index_versions(lib)
    bh = discover_bizhawk(emu_root)
    results = [assess(p, lib, rom_idx, ver_idx, bh) for p in pubs]
    if only_ready:
        results = [r for r in results if r["status"] == "replayable"]
    ready = [r for r in results if r["status"] == "replayable"]
    summary = {
        "total": len(results),
        "replayable": len(ready),
        "blocked": len(results) - len(ready),
        "completion_verdict": summarize_verdicts(results),
        "predicate_verdict": summarize_predicates(results),
        "roms_indexed": sum(len(v) for v in rom_idx.values()),
        "versions_indexed": len(ver_idx),
        "bizhawk_available": sorted(bh),
    }
    doc = {"summary": summary, "assessments": results}
    if out:
        Path(out).write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    return doc


def _fmt_blockers(r):
    return "; ".join(f"[{b['code']}] {b['reason']}" for b in r["blockers"]) or "无"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["build", "status", "assess"])
    ap.add_argument("pub_id", nargs="?", help="assess 用的出版物 id")
    ap.add_argument("--lib", default=str(DEFAULT_LIB))
    ap.add_argument("--emu", default=str(DEFAULT_EMU))
    ap.add_argument("--out", default=None, help="build 输出 json（默认 lib/registry.json）")
    ap.add_argument("--ready", action="store_true", help="build 只输出可回放条目")
    ap.add_argument("--rom-root", action="append", default=[],
                    help="追加自有 ROM 池根（可重复）；不做文件名猜测，命中仍只认 SHA-1")
    args = ap.parse_args()

    if args.cmd == "assess":
        if not args.pub_id:
            ap.error("assess 需要 pub_id")
        pubs = {p["id"]: p for p in load_publications(args.lib)}
        if args.pub_id not in pubs:
            print(f"未知出版物 id: {args.pub_id}", file=sys.stderr)
            return 1
        r = assess(pubs[args.pub_id], args.lib, index_roms(args.lib, args.rom_root),
                   index_versions(args.lib), discover_bizhawk(args.emu))
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0

    out = args.out or str(Path(args.lib) / "registry.json")
    doc = build(args.lib, args.emu, out if args.cmd == "build" else None,
                only_ready=args.ready, extra_rom_roots=args.rom_root)
    s = doc["summary"]
    print(f"总 {s['total']} | 可回放 {s['replayable']} | 阻塞 {s['blocked']}")
    print(f"ROM 索引 {s['roms_indexed']} | version 索引 {s['versions_indexed']} "
          f"| 本地 BizHawk {', '.join(s['bizhawk_available']) or '无'}")
    print("通关可判性（第三条轴，与资源齐不齐无关）: "
          + " | ".join(f"{k}={n}" for k, n in sorted(s["completion_verdict"].items())))
    print("判据表覆盖（第四条轴，录制器保真不等于判据写对）: "
          + " | ".join(f"{k}={n}" for k, n in sorted(s["predicate_verdict"].items())))
    if args.cmd == "build":
        print(f"已写 {out}")
        for r in doc["assessments"]:
            if r["status"] == "replayable":
                print(f"  [READY] {r['id']} {r['game']} core={r['core']} "
                      f"rom={r['rom_match'][0] if r['rom_match'] else '?'}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())