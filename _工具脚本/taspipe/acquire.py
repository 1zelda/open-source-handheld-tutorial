# -*- coding: utf-8 -*-
"""配置驱动获取层：ROM / 金手指 / 存档 —— 本地优先 + 诚实门控（auto 设计 acquire 阶段）。

口径（沿用项目红线，不在本层放松）：
  * ROM 先查本地 SHA-1 索引（registry.index_roms，live 不读 stale registry.json）。
    命中即用；未命中 → 自有网盘（用户门控钩子，默认未配置则诚实 blocked）→ 外部逐款确认。
  * 不自动抓商业 ROM/BIOS 全集；netdisk_resolver 是「用户已登录 + 逐款门控」后才注入的可调用，
    本模块绝不自行调用夸克 skill 或任何下载器。缺资源 => MISSING_RESOURCE，不伪装成功。
  * 金手指/存档只索引本地 `存档与金手指索引.json`（带 sha256），命中是本地文件；
    它们是可选资源（通关不需要），缺 => missing 不是 blocked。能否「用」由 statebuild 判（NES
    savestate/ram 已经 statejump.StateSession 接线，但能力转真须 验证/t3_statejump/report.json
    全 pass 证据；无证据/缺 BizHawk => 诚实 unsupported，不凭索引到存档就伪装能加载）。

运行: python -m taspipe.acquire --pub 3232          # 解析单条出版物的 ROM/金手指获取
      python -m taspipe.acquire --game "Zelda"    # 按名解析
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from .schema import FailureCode
from . import registry as R

CHEAT_LIB = R.ROOT / "04-游戏资源库" / "存档与金手指"
CHEAT_INDEX_NAME = "存档与金手指索引.json"

# cheat 索引平台名 -> schema/出版物平台码 的别名（索引用 NES/Switch/WII/NDS/通用）
_PLAT_ALIAS = {
    "NES": {"NES", "FDS"}, "FDS": {"NES", "FDS"},
    "SNES": {"SNES", "BSX", "SGB"}, "PSX": {"PS1", "PSX"},
    "PSP": {"PSP"}, "ARCADE_FBNEO": {"ARCADE", "ARCADE_FBNEO"},
}


def _sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def index_cheats(cheat_lib=CHEAT_LIB):
    """读本地金手指/存档索引 → entries（每项带 platform/game/kind/rel_path/sha256）。
    缺索引 => []（诚实，不臆造）。只读，不下载、不解压。"""
    p = Path(cheat_lib) / CHEAT_INDEX_NAME
    if not p.is_file():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    return d.get("entries", []) if isinstance(d, dict) else []


def rom_sha1_candidates(pub, lib, versions=None):
    """所需 ROM 哈希的**全部**候选，按 出版物 rom_sha1 → bk2 Header → version 页 排序并去重。

    站点登记会过期，电影 Header 里的 SHA1 是录制时算的、跟本地文件同源。11-22 实测台账
    4694 条里 3 条（5231 吃豆人、4776/4831 Alwa）出版物 rom_sha1 与 bk2 Header / 台账
    required_rom_sha1 不一致，而那两个一致且等于本地文件的真实哈希。只取第一个「有值」的
    来源当唯一需求哈希，过期的那格就会把能对上本地 ROM 的来源盖掉，报成
    「本地无匹配 ROM」——看着像缺资源，其实是调用方只认了一份错的账。

    versions: 批量扫描时注入 `registry.index_versions(lib)` 的结果。那一格每次调用都要
    glob 一遍 versions/，逐条扫全库时会变成平方级开销（11-22 实测扫 4694 条超时）。
    """
    lib = Path(lib)
    out, seen = [], set()

    def add(val, src):
        h = R.norm_sha1(val)
        if h and h not in seen:
            seen.add(h)
            out.append((h, src))

    add(pub.get("rom_sha1"), "出版物 rom_sha1")
    movie, _ = R.resolve_movie(pub, lib)
    if movie:
        add((R.read_bk2_header(movie) or {}).get("SHA1"), "bk2 Header")
    v = (R.index_versions(lib) if versions is None else versions).get(pub.get("version_id", ""))
    if v:
        add(v.get("sha1"), "version 页")
    return out


def required_rom_sha1(pub, lib, versions=None):
    """首选所需 ROM 哈希（出版物 rom_sha1 → bk2 Header → version 页，取第一个有值的）。

    返回 (sha1, 来源)；三者都没有 => ('', '未知')。判断本地能不能满足要走
    rom_sha1_candidates + resolve_rom 的逐候选比对，别把这一格的第一个值当唯一答案。
    """
    cands = rom_sha1_candidates(pub, lib, versions)
    return cands[0] if cands else ("", "未知")


def resolve_rom(pub, lib=None, rom_idx=None, netdisk_resolver=None, versions=None):
    """逐候选哈希比对本地索引，第一个能在本地对上文件的哈希算需求哈希；都不中才走门控钩子。

    返回 dict（不抛业务异常）。
    netdisk_resolver: 可选 callable(required_sha1, pub) -> 本地路径|None。
      仅在用户已登录自有网盘并逐款门控后由上层注入；本模块默认 None => 诚实 blocked，
      绝不自行下载（红线：不自动抓商业全集）。注入后仍校验 SHA-1 与**某个候选**一致才认 ready。
    """
    lib = Path(lib or R.DEFAULT_LIB)
    if rom_idx is None:
        rom_idx = R.index_roms(lib)
    cands = rom_sha1_candidates(pub, lib, versions)
    wanted = {h for h, _ in cands}
    for sha, src in cands:
        matches = rom_idx.get(sha, [])
        if matches:
            note = None
            if cands[0][0] != sha:
                note = (f"首选来源 {cands[0][1]} 记的是 {cands[0][0]}，本地没有对应文件；"
                        f"实际命中本地的是 {src} 记的 {sha}。这两份账对不上是出版物 rom_sha1 "
                        "过期（不是缺资源），已在 hash_source 里点名采信的那一份")
            return {"status": "ready", "rom": matches[0], "required_sha1": sha,
                    "hash_source": src, "source": "local", "blockers": [],
                    "candidates": [{"sha1": h, "source": s} for h, s in cands],
                    "hash_note": note}

    blockers = []
    if not cands:
        blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                         "reason": "未知所需 ROM 哈希（出版物/Header/version 页都没有）"})
    else:
        blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                         "reason": "本地无匹配 ROM（逐候选都试过："
                                   + "；".join(f"{src} SHA1={sha}" for sha, src in cands)
                                   + "）"})
    if netdisk_resolver is not None:
        got = netdisk_resolver(cands[0][0] if cands else "", pub)
        if got and Path(got).is_file():
            got_sha = _sha1(got)
            if not wanted or got_sha in wanted:
                src = dict(cands).get(got_sha, "未知") if cands else "未知"
                return {"status": "ready", "rom": str(got), "required_sha1": got_sha,
                        "hash_source": src, "source": "own_netdisk", "blockers": [],
                        "candidates": [{"sha1": h, "source": s} for h, s in cands],
                        "hash_note": None}
            blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                             "reason": f"自有网盘给的文件哈希 {got_sha} 与候选哈希不符（候选："
                                       + "、".join(f"{src}={sha}" for sha, src in cands)
                                       + "；用户门控；不自动抓商业全集）"})
        else:
            blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                             "reason": "自有网盘未命中（用户门控；不自动抓商业全集）"})
    else:
        blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                         "reason": "自有网盘获取未配置（需用户登录 + 逐款门控后注入 resolver）"})
    return {"status": "blocked", "rom": None,
            "required_sha1": cands[0][0] if cands else "",
            "hash_source": cands[0][1] if cands else "未知", "source": None,
            "candidates": [{"sha1": h, "source": s} for h, s in cands],
            "hash_note": None, "blockers": blockers}


def _plat_match(cheat_plat, want_plat):
    cp = (cheat_plat or "").upper()
    wp = (want_plat or "").upper()
    if not wp:
        return True
    if cp == wp:
        return True
    return cp in _PLAT_ALIAS.get(wp, set()) or wp in _PLAT_ALIAS.get(cp, set())


def resolve_cheat(game, platform, cheat_lib=CHEAT_LIB, query=None, kind=None):
    """按 platform + game/query 子串匹配本地金手指/存档索引。可选资源：缺 => missing 不是 blocked。

    query 显式给出时优先（解决英文出版物名 vs 中文索引名）；否则用 game 子串。
    返回 {status: found|missing, entries:[{...rel_path,sha256,abs_path}], blockers}。
    只索引本地文件，不下载、不解压、不判能否加载（那是 statebuild）。
    """
    entries = index_cheats(cheat_lib)
    q = (query or game or "").strip().lower()
    hits = []
    for e in entries:
        if not _plat_match(e.get("platform"), platform):
            continue
        if kind and e.get("kind") != kind:
            continue
        name = (e.get("game", "") + " " + e.get("filename", "")).lower()
        if q and q in name:
            abs_path = str(Path(cheat_lib) / e.get("rel_path", ""))
            hits.append({**e, "abs_path": abs_path,
                         "present": Path(abs_path).is_file()})
    hits = [h for h in hits if h["present"]]
    if hits:
        return {"status": "found", "entries": hits, "blockers": []}
    return {"status": "missing", "entries": [],
            "blockers": [{"code": FailureCode.MISSING_RESOURCE.value,
                          "reason": f"本地金手指/存档索引无匹配（platform={platform} query={q or '∅'}）；可选资源"}]}


def acquire(pub, lib=None, rom_idx=None, netdisk_resolver=None,
            cheat_lib=CHEAT_LIB, cheat_query=None, need_cheat=False):
    """auto 的 acquire 阶段：ROM 必需，金手指/存档可选（need_cheat 时缺则 blocked）。
    返回 {status: ready|blocked, rom, required_sha1, cheat, blockers, fidelity, acquire_advice}。

    `fidelity` 走台账同一支函数（registry.recorder_fidelity）：补 ROM 值不值得，
    跟这台录制器能不能判通关是两件事。FCEUX 内层那批即便 ROM 到手也仍是
    not_judgeable_locally，这里当场说清，别让获取清单把希望挂在拿不到结局的片子上。
    但这一格只是先验：7429 同出自 FCEUX .fm2 却实测拿到过 pass，所以话只能说"风险"，
    不能说"必然"，否则就是把先验冒名成判决。
    """
    lib = Path(lib or R.DEFAULT_LIB)
    rom = resolve_rom(pub, lib, rom_idx, netdisk_resolver)
    blockers = list(rom["blockers"])
    cheat = resolve_cheat(pub.get("game", ""), pub.get("platform", ""),
                          cheat_lib, query=cheat_query)
    if need_cheat and cheat["status"] != "found":
        blockers.extend(cheat["blockers"])
    status = "ready" if rom["status"] == "ready" and not blockers else "blocked"
    movie, movie_note = R.resolve_movie(pub, lib)
    fidelity = R.recorder_fidelity(movie, movie_note)
    advice = None
    if rom["status"] != "ready" and fidelity["completion_verdict"] == "not_judgeable_locally":
        advice = ("这台录制器是 FCEUX 内层，补到 ROM 也只能算「能跑」，通关风险高：" + fidelity["why"]
                  + "；要出片仍可用（回放照跑），要 pass 就按 §35 证词＋§36 静止窗逐片实测，"
                  + "别拿这一格当判决（已知反例 7429）")
    return {"status": status, "rom": rom["rom"],
            "required_sha1": rom["required_sha1"], "rom_source": rom["source"],
            "hash_source": rom["hash_source"], "candidates": rom["candidates"],
            "hash_note": rom["hash_note"],
            "cheat": cheat, "blockers": blockers,
            "fidelity": fidelity, "acquire_advice": advice}


def _resolve_pub_by_name(game, lib):
    """按名选出版物：本地就能回放的优先，其次身份解析得清的（ROM 只在网盘时也该被选中，
    再由 resolve_rom 走网盘钩子）；都不行才退回第一条同名。"""
    pubs = R.load_publications(lib)
    g = (game or "").strip().lower()
    cands = [p for p in pubs if g and g in (p.get("game", "").lower())]
    if not cands:
        return None
    ri, vi, bh = R.index_roms(lib), R.index_versions(lib), R.discover_bizhawk(R.DEFAULT_EMU)
    assessed = [(p, R.assess(p, lib, ri, vi, bh)) for p in cands]
    for key, want in (("status", "replayable"), ("identity_status", "resolved")):
        hit = [p for p, r in assessed if r.get(key) == want]
        if hit:
            return hit[0]
    return assessed[0][0]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pub", default=None)
    ap.add_argument("--game", default=None)
    ap.add_argument("--lib", default=str(R.DEFAULT_LIB))
    ap.add_argument("--cheat-query", default=None)
    ap.add_argument("--need-cheat", action="store_true")
    args = ap.parse_args()
    lib = Path(args.lib)
    if args.pub:
        pubs = {p["id"]: p for p in R.load_publications(lib)}
        pub = pubs.get(args.pub)
        if not pub:
            print(f"未知出版物 id: {args.pub}", file=sys.stderr)
            return 1
    elif args.game:
        pub = _resolve_pub_by_name(args.game, lib)
        if not pub:
            print(f"按名未找到出版物: {args.game}", file=sys.stderr)
            return 1
    else:
        ap.error("需 --pub 或 --game")
    res = acquire(pub, lib, cheat_query=args.cheat_query, need_cheat=args.need_cheat)
    print(json.dumps({"pub_id": pub["id"], "game": pub.get("game"), **res},
                     ensure_ascii=False, indent=1))
    return 0 if res["status"] == "ready" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())