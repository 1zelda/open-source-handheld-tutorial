# -*- coding: utf-8 -*-
"""来源库：先查库 → 未命中延伸 → 命中入库分类（S1 的强制入口）。

治的病：来源库以前是一份没人读的 Markdown，每次调研都从零自由搜；知识包里的
`catalog.sources` 是自由文本 URL（还把 403 状态塞在括号里），没有 ID/验证日期/
逐要素归属，也没有命中与未命中台账。

本模块把来源变成主数据 + 可执行路由：
  * route：先定 ROM 身份（本地 FBNeo ini / 本地 sha1），身份不明 => blocked，不出搜索计划；
    库内来源按 层×要素×机种×状态 排序，verified_read 优先，unreachable 只走快照，
    dead 一律禁用；candidate 只能进「延伸段」。
  * log：命中(hit)必须带真实存在且非空的正文产物，否则判 inconclusive（不算命中）；
    快照(snippet)同样要落产物但永远升不到 verified_read；未命中(miss)留失败现场。
    台账复用 ledger.Ledger（产物 sha256+大小校验、追加式不覆盖历史）。
  * claim-absence：下「查不到/不存在」结论前，必须已有中文网盘层 + B站 的 miss 记录
    （用户 2026-11-16 立的规矩，落成代码门）。
  * ingest：新站去重入库、自动分类，默认 candidate；拿到正文才升 verified_read。
  * render：由主数据单向生成 Markdown 的 GENERATED 块（人读清单是产物，不是手改源）。
  * audit：野来源 / 要素无来源 / 只有快照支撑 / dead 站被引用 / 生成块漂移 / 无据的
    「不存在」声称，逐条判 pass/fail/inconclusive。
  * recheck：探活并记录 reachability；升 dead 必须人给当期证据，不自动判死。

运行（在 F:\\开源掌机教程\\_工具脚本 下）:
  py -3 -m taspipe.sources show
  py -3 -m taspipe.sources route --game "拳皇98" --set kof98eck --platform ARCADE --want 出招表,金手指,彩蛋
  py -3 -m taspipe.sources log --source-id hackrom_cn --game kof98eck --want 金手指 --verdict snippet --evidence <正文文件>
  py -3 -m taspipe.sources ingest --url https://example.com/x --name "新站" --layer cn_community --platforms ANY --want 攻略
  py -3 -m taspipe.sources claim-absence --game kof98eck --want 彩蛋
  py -3 -m taspipe.sources render --write
  py -3 -m taspipe.sources audit
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .schema import SchemaError, Verdict, Stage, FailureCode
from .ledger import Ledger, fingerprint

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
REG_DIR = ROOT / "游戏包" / "来源库"
REG_JSON = REG_DIR / "sources.json"
LEDGER_JSON = REG_DIR / "检索台账.json"
MD_PATH = ROOT / "游戏包" / "复古游戏文献来源库.md"
PACKS_DIR = ROOT / "游戏包"
FBNEO_CFG = Path("F:/工具链/fbneo/nightly/config")

BEGIN_MARK = "<!-- BEGIN GENERATED: sources -->"
END_MARK = "<!-- END GENERATED: sources -->"

LAYERS = {
    "identity": "定身份层（版本/set/哈希，最先走）",
    "local_emu": "本地模拟器与本地库（离线权威）",
    "local_docs": "项目内文档与本机实测记录（离线权威）",
    "cn_arcade_hack": "街机 hack 中文层（改版独有内容只在这里）",
    "cn_arcade": "街机中文攻略层（官方表/玩家实战口径）",
    "cn_console": "FC/主机中文攻略层",
    "cn_community": "中文社区/论坛层",
    "cn_netdisk": "网盘中文层（判不存在前必扫）",
    "cn_print": "中文纸媒全文层",
    "jp_urawaza": "日文裏技/隠しコマンド层",
    "en_tech": "英文技术层（未使用内容/帧数据）",
    "cheat_db": "金手指码库层",
    "tas_macro": "TAS/必杀宏真值层",
    "video": "视频验证层（判不存在前必扫 B站）",
    "official_manual": "官方说明书层",
}

ELEMENT_TYPES = ("身份", "版本对照", "攻略", "出招表", "必杀宏", "金手指", "彩蛋",
                 "隐藏要素", "帧数据", "未使用内容", "bug", "说明书", "基础档案",
                 "纸媒原文", "视频验证")

STATUSES = ("verified_read", "snippet_only", "unreachable", "candidate", "dead")
ACCESS = {"verified_read": "direct", "snippet_only": "snapshot",
          "unreachable": "snapshot", "candidate": "unverified", "dead": "forbidden"}
STATUS_W = {"verified_read": 100, "snippet_only": 60, "unreachable": 40,
            "candidate": 10, "dead": -1000}

PREFERRED = {
    "身份": ("identity", "local_emu", "local_docs", "cn_arcade_hack"),
    "版本对照": ("identity", "local_emu", "local_docs", "cn_arcade_hack"),
    "攻略": ("local_docs", "cn_console", "cn_arcade", "cn_community", "jp_urawaza", "cn_print"),
    "出招表": ("local_docs", "cn_arcade_hack", "cn_arcade", "local_emu", "jp_urawaza", "en_tech", "video"),
    "必杀宏": ("local_docs", "tas_macro", "local_emu", "cn_arcade_hack", "video"),
    "金手指": ("local_docs", "cheat_db", "local_emu", "cn_arcade_hack", "cn_console"),
    "彩蛋": ("local_docs", "cn_console", "cn_community", "video", "cn_print", "en_tech"),
    "隐藏要素": ("local_docs", "cn_console", "cn_community", "video", "en_tech"),
    "帧数据": ("en_tech",),
    "未使用内容": ("en_tech", "identity"),
    "bug": ("local_docs", "cn_console", "cn_community", "en_tech"),
    "说明书": ("official_manual", "jp_urawaza", "cn_print"),
    "基础档案": ("local_docs", "cn_console", "jp_urawaza"),
    "纸媒原文": ("cn_print",),
    "视频验证": ("video", "local_emu"),
}

PLATFORMS = ("ANY", "NES", "SNES", "MD", "GBA", "GB", "N64", "PS1", "PSP",
             "PCE", "ARCADE", "PC_DOS", "MOBILE")
PLATFORM_ALIASES = {"FC": "NES", "FAMICOM": "NES", "SFC": "SNES", "MEGADRIVE": "MD",
                    "GENESIS": "MD", "ARCADE_FBNEO": "ARCADE", "ARCADE_MAME": "ARCADE",
                    "FBNEO": "ARCADE", "MAME": "ARCADE", "N64": "N64", "DOS": "PC_DOS"}

SOURCE_KEYS = {"source_id", "name", "kind", "layer", "platforms", "element_types",
               "status", "last_verified", "urls", "evidence", "reachability",
               "recipes", "notes", "games_hit", "sets", "closure"}
REG_KEYS = {"schema_version", "updated", "note", "sources", "absence_claims"}
ABSENCE_LEDGER_KEYS = {"game", "want", "date", "support"}
ABSENCE_ACCESS_KEYS = {"claim", "checked_on", "method", "result", "not_a_claim_of"}
PACK_SOURCE_KEYS = {"source_id", "url", "status", "verified_date", "element_ids", "note",
                   "evidence_report"}


def today():
    return time.strftime("%Y-%m-%d")


def norm_platform(p):
    if not p:
        return None
    key = str(p).strip().upper().replace(" ", "")
    key = PLATFORM_ALIASES.get(key, key)
    if key not in PLATFORMS:
        raise SchemaError(f"未知平台 {p!r}，允许 {PLATFORMS}（别名 {sorted(PLATFORM_ALIASES)}）")
    return key


def resolve_path(p):
    path = Path(str(p))
    return path if path.is_absolute() else (REPO_ROOT / path)


def validate_source(d, ctx="source"):
    if not isinstance(d, dict):
        raise SchemaError(f"{ctx}: 记录须为对象")
    unknown = sorted(set(d) - SOURCE_KEYS)
    if unknown:
        raise SchemaError(f"{ctx}: 未知字段 {unknown}；允许 {sorted(SOURCE_KEYS)}")
    sid = d.get("source_id", "")
    if not re.fullmatch(r"[a-z0-9_]+", sid or ""):
        raise SchemaError(f"{ctx}: source_id 非法 {sid!r}（只允许小写字母数字下划线）")
    if not (d.get("name") or "").strip():
        raise SchemaError(f"{ctx} {sid}: 缺 name")
    if d.get("layer") not in LAYERS:
        raise SchemaError(f"{ctx} {sid}: layer 非法 {d.get('layer')!r}，允许 {list(LAYERS)}")
    if d.get("status") not in STATUSES:
        raise SchemaError(f"{ctx} {sid}: status 非法 {d.get('status')!r}，允许 {STATUSES}")
    plats = d.get("platforms") or []
    if not plats:
        raise SchemaError(f"{ctx} {sid}: platforms 不能为空")
    for p in plats:
        norm_platform(p)
    wants = d.get("element_types") or []
    if not wants:
        raise SchemaError(f"{ctx} {sid}: element_types 不能为空")
    for w in wants:
        if w not in ELEMENT_TYPES:
            raise SchemaError(f"{ctx} {sid}: element_types 含未知要素 {w!r}，允许 {ELEMENT_TYPES}")
    if d.get("kind", "site") not in ("site", "local", "netdisk", "video", "print"):
        raise SchemaError(f"{ctx} {sid}: kind 非法 {d.get('kind')!r}")
    status = d["status"]
    if status != "candidate" and not d.get("last_verified"):
        raise SchemaError(f"{ctx} {sid}: status={status} 必须带 last_verified（验证日期）")
    if status == "verified_read":
        ev = d.get("evidence") or []
        if not ev:
            raise SchemaError(f"{ctx} {sid}: verified_read 必须带 evidence 取证文件")
        for e in ev:
            f = resolve_path(e)
            if not f.is_file() or f.stat().st_size == 0:
                raise SchemaError(f"{ctx} {sid}: 取证文件缺失或为空 {e}")
    if status == "dead":
        c = d.get("closure") or {}
        if not c.get("date") or not c.get("reason"):
            raise SchemaError(f"{ctx} {sid}: dead 必须带 closure.date + closure.reason（当期证据）")
    return d


def validate_absence_claim(claim, ctx="absence_claim"):
    if not isinstance(claim, dict):
        raise SchemaError(f"{ctx}: 须为对象")
    keys = set(claim)
    if keys == ABSENCE_LEDGER_KEYS:
        if not str(claim["game"] or "").strip():
            raise SchemaError(f"{ctx}: game 不能为空")
        if not isinstance(claim["want"], list) or not claim["want"] or not all(
                isinstance(w, str) and w.strip() for w in claim["want"]):
            raise SchemaError(f"{ctx}: want 必须是非空字符串列表")
        if not str(claim["date"] or "").strip():
            raise SchemaError(f"{ctx}: date 不能为空")
        if not isinstance(claim["support"], list) or not claim["support"] or not all(
                isinstance(job, str) and job.strip() for job in claim["support"]):
            raise SchemaError(f"{ctx}: support 必须是非空 job_id 列表")
        return claim
    if keys == ABSENCE_ACCESS_KEYS:
        if not all(isinstance(claim[key], str) and claim[key].strip()
                   for key in ABSENCE_ACCESS_KEYS):
            raise SchemaError(f"{ctx}: 取回限制记录字段必须是非空字符串")
        return claim
    raise SchemaError(
        f"{ctx}: 字段 {sorted(keys)} 不符合两种口径；"
        f"不存在声称用 {sorted(ABSENCE_LEDGER_KEYS)}，取回限制用 {sorted(ABSENCE_ACCESS_KEYS)}")


def load_registry(path=None):
    p = Path(path or REG_JSON)
    if not p.is_file():
        raise SchemaError(f"来源库主数据不存在: {p}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    unknown = sorted(set(doc) - REG_KEYS)
    if unknown:
        raise SchemaError(f"sources.json 未知顶层字段 {unknown}；允许 {sorted(REG_KEYS)}")
    seen = set()
    for s in doc.get("sources", []):
        validate_source(s)
        if s["source_id"] in seen:
            raise SchemaError(f"source_id 重复: {s['source_id']}")
        seen.add(s["source_id"])
    doc.setdefault("absence_claims", [])
    for i, claim in enumerate(doc["absence_claims"]):
        validate_absence_claim(claim, f"absence_claims[{i}]")
    return doc


def save_registry(doc, path=None):
    p = Path(path or REG_JSON)
    for s in doc.get("sources", []):
        validate_source(s)
    doc["updated"] = today()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return str(p)


def find_source(reg, sid):
    for s in reg["sources"]:
        if s["source_id"] == sid:
            return s
    raise SchemaError(f"来源库无此 source_id: {sid}（先 ingest 入库，别引用野来源）")


def _fbneo_identity(set_name):
    """本地 FBNeo 自己的记录 = 街机身份最权威且离线可用的口。"""
    ini = FBNEO_CFG / "games" / f"{set_name}.ini"
    dat = FBNEO_CFG / "fbneo64.roms.dat"
    out = {"authority": "fbneo_local", "set": set_name, "ini": str(ini),
           "in_setlist": False, "full_name": None, "rom": None}
    if ini.is_file():
        first = ini.read_text(encoding="utf-8", errors="replace").splitlines()
        out["full_name"] = first[0].strip() if first else None
    if dat.is_file():
        txt = dat.read_text(encoding="utf-8", errors="replace")
        out["in_setlist"] = bool(re.search(rf"^{re.escape(set_name)}\s*\+", txt, re.M))
    rom = FBNEO_CFG.parent / "roms" / f"{set_name}.zip"
    if rom.is_file():
        import hashlib
        h = hashlib.sha1()
        with open(rom, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out["rom"] = {"path": str(rom), "byte_size": rom.stat().st_size, "sha1": h.hexdigest()}
    out["resolved"] = bool(out["full_name"] or out["in_setlist"])
    return out


def resolve_identity(game, set_name=None, platform=None, rom=None):
    """身份未定 => 不出搜索计划。同名异版（几十种拳皇98）是第一坑。"""
    plat = norm_platform(platform) if platform else None
    info = {"game": game, "platform": plat, "status": "unresolved", "authority": None}
    if set_name:
        ident = _fbneo_identity(set_name)
        info.update(ident)
        info["platform"] = plat or "ARCADE"
        info["status"] = "resolved" if ident["resolved"] else "unresolved"
        if not ident["resolved"]:
            info["reason"] = (f"本地 FBNeo 无 {set_name} 的 ini/setlist 记录；"
                              "先确认 set 名（archive_fbnarcade / hbmame），别拿中文叫法当身份")
        return info
    if rom:
        p = resolve_path(rom)
        if not p.is_file():
            info["reason"] = f"ROM 不存在: {p}"
            return info
        import hashlib
        h = hashlib.sha1()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        ext = p.suffix.lower().lstrip(".")
        guess = {"nes": "NES", "sfc": "SNES", "smc": "SNES", "md": "MD", "bin": "MD",
                 "gba": "GBA", "gb": "GB", "gbc": "GB", "z64": "N64", "n64": "N64",
                 "iso": "PS1", "cue": "PS1", "zip": "ARCADE"}.get(ext)
        info.update({"authority": "local_sha1", "rom": str(p), "sha1": h.hexdigest(),
                     "byte_size": p.stat().st_size,
                     "platform": plat or guess,
                     "status": "resolved" if (plat or guess) else "unresolved"})
        info["note"] = ("字节身份已定（sha1）；卡带版本名仍需 No-Intro/Redump 比对"
                        if info["status"] == "resolved" else "缺平台，无法定身份")
        return info
    info["reason"] = "缺 --set（街机）或 --rom（主机）：身份未定不得开搜"
    return info


def build_queries(src, game, set_name=None, platform=None):
    subs = {"game": game, "set": set_name or game, "platform": platform or "ANY",
            "rom名": set_name or game, "日版名": game, "游戏名": game, "游戏前缀": game}
    out = []
    for lang, tpl in (src.get("recipes") or {}).items():
        q = str(tpl)
        for k, v in subs.items():
            q = q.replace("{" + k + "}", str(v))
        out.append({"lang": lang, "query": q})
    if not out:
        out.append({"lang": "cn", "query": f"{game} " + "/".join(src["element_types"][:2])})
        if set_name:
            out.append({"lang": "set", "query": f'"{set_name}"'})
    return out


def _score(src, wants, plat, game, set_name):
    s = STATUS_W[src["status"]]
    if any(src["layer"] in PREFERRED.get(w, ()) for w in wants):
        s += 30
    if game in (src.get("games_hit") or []):
        s += 20
    if set_name and set_name in (src.get("sets") or []):
        s += 25
    if plat and plat in src["platforms"]:
        s += 10
    return s


def _cn_sweep_ids(reg):
    """判「不存在」前必扫的两层，从库里现查（不写死站名）。"""
    netdisk = [s["source_id"] for s in reg["sources"]
               if s["layer"] == "cn_netdisk" and s["status"] != "dead"]
    video_cn = [s["source_id"] for s in reg["sources"]
                if s["layer"] == "video" and s["status"] != "dead"
                and ("bilibili" in s["source_id"] or "B站" in s["name"])]
    return {"cn_netdisk": netdisk, "cn_video_bili": video_cn}


def route(game, want, set_name=None, platform=None, rom=None, reg=None, out=None):
    reg = reg or load_registry()
    if isinstance(want, str):
        want = [w.strip() for w in want.split(",") if w.strip()]
    if not want:
        raise SchemaError("route 需 --want（要素类型），别漫无目的搜")
    for w in want:
        if w not in ELEMENT_TYPES:
            raise SchemaError(f"未知要素类型 {w!r}，允许 {ELEMENT_TYPES}")
    ident = resolve_identity(game, set_name, platform, rom)
    if ident["status"] != "resolved":
        return {"status": "blocked", "game": game, "want": want, "identity": ident,
                "reason": ident.get("reason") or "身份未定",
                "rule": "先定 ROM 身份再查库：同名异版指令与阵容不同，身份不明开搜等于白搜"}
    plat = ident["platform"]
    matches = [s for s in reg["sources"]
               if (plat in s["platforms"] or "ANY" in s["platforms"])
               and set(want) & set(s["element_types"])]
    primary, extension, forbidden = [], [], []
    for s in matches:
        entry = {"source_id": s["source_id"], "name": s["name"], "layer": s["layer"],
                 "status": s["status"], "access": ACCESS[s["status"]],
                 "last_verified": s.get("last_verified"), "urls": s.get("urls") or [],
                 "evidence": s.get("evidence") or [],
                 "queries": build_queries(s, game, set_name, plat),
                 "score": _score(s, want, plat, game, set_name),
                 "notes": s.get("notes", "")}
        if s["status"] == "dead":
            entry["closure"] = s.get("closure")
            forbidden.append(entry)
        elif s["status"] == "candidate":
            extension.append(entry)
        else:
            primary.append(entry)
    primary.sort(key=lambda e: (-e["score"], e["source_id"]))
    extension.sort(key=lambda e: (-e["score"], e["source_id"]))
    forbidden.sort(key=lambda e: e["source_id"])
    from . import kb as _kb
    try:
        kb_stats = _kb.stats_for(revision=set_name, platform=plat)
    except SchemaError as e:
        kb_stats = {"status": "not_built", "chunks": 0, "reason": str(e), "query_cmd": None}
    plan = {
        "status": "ready", "game": game, "want": want, "identity": ident,
        "steps": ["①定身份（已完成）", "②先查本地知识库正文（kb query，命中带 source_id+status）",
                  "③库内优先（primary，按序查）",
                  "④未命中才走延伸段（extension，未验证候选）",
                  "⑤判『不存在』前必扫中文网盘层+B站并留 miss 记录",
                  "⑥命中即 log 落产物；新站 ingest 入库分类；新正文进 corpus_map 后 kb build"],
        "kb": kb_stats,
        "primary": primary, "extension": extension, "forbidden": forbidden,
        "absence_gate": _cn_sweep_ids(reg),
        "counts": {"primary": len(primary), "extension": len(extension),
                   "forbidden": len(forbidden), "kb_chunks": kb_stats.get("chunks", 0)},
        "rule": "primary 未查完不得自由扩大搜索；dead 站禁止直连；candidate 不得当已验证来源引用",
    }
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        plan["plan_file"] = str(p)
    return plan


def _ledger(path=None):
    return Ledger(str(path or LEDGER_JSON))


def log(source_id, game, want, verdict, evidence=None, url=None, note=None,
        element_ids=None, reg=None, ledger_path=None, reg_path=None):
    """命中/快照/未命中三态落台账。hit 无正文产物 => inconclusive，不算命中。"""
    reg = reg or load_registry()
    src = find_source(reg, source_id)
    if isinstance(want, str):
        want = [w.strip() for w in want.split(",") if w.strip()]
    for w in want:
        if w not in ELEMENT_TYPES:
            raise SchemaError(f"未知要素类型 {w!r}")
    if verdict not in ("hit", "miss", "snippet"):
        raise SchemaError(f"verdict 非法 {verdict!r}，允许 hit/miss/snippet")
    key = f"src:{source_id}:{game}:{','.join(want)}"
    led = _ledger(ledger_path)
    ev = [str(resolve_path(e)) for e in (evidence or [])]
    params = {"source_id": source_id, "game": game, "want": want, "verdict": verdict,
              "url": url or "", "note": note or "", "element_ids": element_ids or []}
    if verdict == "miss":
        job = led.register(Stage.GENERATE, key, fingerprint([], params))
        led.fail(job, FailureCode.MISSING_RESOURCE, note or "该站未检得所要内容")
        return {"source_id": source_id, "game": game, "want": want, "verdict": "miss",
                "ledger_job": job, "reason": note or "未检得", "promoted": None}
    if not ev:
        job = led.register(Stage.GENERATE, key, fingerprint([], params))
        led.fail(job, FailureCode.MISSING_RESOURCE,
                 f"{verdict} 声称缺正文产物：证据不足不是通过")
        return {"source_id": source_id, "game": game, "want": want,
                "verdict": Verdict.INCONCLUSIVE.value, "ledger_job": job,
                "reason": "hit/snippet 必须带真实存在且非空的正文取证文件", "promoted": None}
    bad = [e for e in ev if not Path(e).is_file() or Path(e).stat().st_size == 0]
    if bad:
        job = led.register(Stage.GENERATE, key, fingerprint([], params))
        led.fail(job, FailureCode.MISSING_RESOURCE, f"取证文件缺失或为空: {bad}")
        return {"source_id": source_id, "game": game, "want": want,
                "verdict": Verdict.INCONCLUSIVE.value, "ledger_job": job,
                "reason": f"取证文件缺失或为空: {bad}", "promoted": None}
    fp = fingerprint(ev, params)
    job = led.register(Stage.GENERATE, key, fp)
    v = Verdict.PASS if verdict == "hit" else Verdict.INCONCLUSIVE
    led.complete(job, ev, v)
    promoted = None
    if verdict == "hit" and src["status"] == "candidate":
        src["status"] = "verified_read"
        promoted = "candidate->verified_read"
    elif verdict == "snippet" and src["status"] == "candidate":
        src["status"] = "snippet_only"
        promoted = "candidate->snippet_only"
    if promoted:
        src["last_verified"] = today()
    for e in (evidence or []):
        if e not in (src.get("evidence") or []):
            src.setdefault("evidence", []).append(e)
    if game not in (src.get("games_hit") or []):
        src.setdefault("games_hit", []).append(game)
    if url and url not in (src.get("urls") or []):
        src.setdefault("urls", []).append(url)
    save_registry(reg, reg_path)
    return {"source_id": source_id, "game": game, "want": want,
            "verdict": Verdict.PASS.value if verdict == "hit" else Verdict.INCONCLUSIVE.value,
            "claimed": verdict, "ledger_job": job, "evidence": ev, "promoted": promoted}


def claim_absence(game, want, reg=None, ledger_path=None, reg_path=None):
    """判「查不到/不存在」的门：中文网盘层 + B站 必须已有 miss 记录。"""
    reg = reg or load_registry()
    if isinstance(want, str):
        want = [w.strip() for w in want.split(",") if w.strip()]
    for w in want:
        if w not in ELEMENT_TYPES:
            raise SchemaError(f"未知要素类型 {w!r}")
    sweep = _cn_sweep_ids(reg)
    led = _ledger(ledger_path)
    support, missing = [], []
    for layer_name, ids in sweep.items():
        if not ids:
            missing.append({"layer": layer_name, "reason": "库里这层没有可用来源，先 ingest"})
            continue
        hits = []
        for sid in ids:
            key = f"src:{sid}:{game}:{','.join(want)}"
            for e in reversed(led.entries):
                if e["idempotency_key"] == key and e["stage"] == Stage.GENERATE.value:
                    if e["status"] == "failed" and e.get("failure_code") == FailureCode.MISSING_RESOURCE.value:
                        hits.append(e["job_id"])
                    break
        if hits:
            support.extend(hits)
        else:
            missing.append({"layer": layer_name, "sources": ids,
                            "reason": "尚无 miss 记录：先真扫这层再下结论"})
    if missing:
        return {"status": "blocked", "game": game, "want": want, "missing": missing,
                "rule": "搜不到别说成不存在（2026-11-16）：判『不存在』前必扫 B站+网盘中文层并留 miss 记录"}
    claim = {"game": game, "want": want, "date": today(), "support": support}
    reg.setdefault("absence_claims", []).append(claim)
    save_registry(reg, reg_path)
    return {"status": "allowed", **claim}


def _domain(url):
    host = urllib.parse.urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def ingest(url, name, layer, platforms, want, status="candidate", evidence=None,
           notes=None, recipes=None, kind="site", reg=None, reg_path=None):
    """新站入库分类：按域名+路径去重，默认 candidate；verified_read 必须带正文取证。"""
    reg = reg or load_registry()
    if isinstance(platforms, str):
        platforms = [p.strip() for p in platforms.split(",") if p.strip()]
    if isinstance(want, str):
        want = [w.strip() for w in want.split(",") if w.strip()]
    platforms = [norm_platform(p) for p in platforms]
    if layer not in LAYERS:
        raise SchemaError(f"layer 非法 {layer!r}，允许 {list(LAYERS)}")
    dom = _domain(url) if url else ""
    path = urllib.parse.urlsplit(url).path if url else ""
    for s in reg["sources"]:
        for u in s.get("urls") or []:
            if _domain(u) == dom and urllib.parse.urlsplit(u).path == path:
                raise SchemaError(f"已入库，别重复建条目: {s['source_id']} ({u})")
    base = re.sub(r"[^a-z0-9]+", "_", dom).strip("_") or "source"
    sid, n = base, 2
    while any(s["source_id"] == sid for s in reg["sources"]):
        sid, n = f"{base}_{n}", n + 1
    rec = {"source_id": sid, "name": name, "kind": kind, "layer": layer,
           "platforms": platforms, "element_types": want, "status": status,
           "last_verified": today() if status != "candidate" else None,
           "urls": [url] if url else [], "evidence": list(evidence or []),
           "notes": notes or ""}
    if recipes:
        rec["recipes"] = recipes
    validate_source(rec, ctx="ingest")
    reg["sources"].append(rec)
    save_registry(reg, reg_path)
    return {"ingested": sid, "status": status, "layer": layer, "record": rec}


def _cell(x):
    return str(x).replace("|", "\\|").replace("\n", " ")


def render_block(reg=None):
    """人读清单 = 主数据的产物。确定性排序，便于 audit 逐字节比对。"""
    reg = reg or load_registry()
    srcs = reg["sources"]
    lines = [BEGIN_MARK,
             f"> 本块由 `python -m taspipe.sources render --write` 从主数据 `来源库/sources.json` 生成"
             f"（{len(srcs)} 条，updated {reg.get('updated')}）。**手改无效**，`sources audit` 会报漂移。",
             "> 状态口径：`verified_read`=本机取到正文并核对（带取证文件）；`snippet_only`=只有搜索快照；"
             "`unreachable`=本机直连失败但站点活着（走快照）；`candidate`=知道存在、本轮未验；`dead`=已关停（带当期证据）。",
             ""]
    counts = {s: sum(1 for x in srcs if x["status"] == s) for s in STATUSES}
    lines.append("**状态计数**：" + "、".join(f"{k} {v}" for k, v in counts.items())
                 + f"；层 {len(LAYERS)} 个、要素类型 {len(ELEMENT_TYPES)} 种。")
    lines.append("")
    lines.append("### 查什么 → 用什么（要素选站表，由 PREFERRED 层序 + 库内状态生成）")
    lines.append("")
    lines.append("| 要素 | 首选层 | 库内首选（状态） | 次选 | 延伸候选 |")
    lines.append("|---|---|---|---|---|")
    for w in ELEMENT_TYPES:
        pref = PREFERRED.get(w, ())
        cands = [s for s in srcs if w in s["element_types"] and s["status"] != "dead"]
        cands.sort(key=lambda s: (-(STATUS_W[s["status"]]
                                    + (30 if s["layer"] in pref else 0)), s["source_id"]))
        ready = [s for s in cands if s["status"] != "candidate"]
        ext = [s for s in cands if s["status"] == "candidate"]
        first = "、".join(f"`{s['source_id']}`({s['status']})" for s in ready[:2]) or "（库内暂无已验证来源）"
        second = "、".join(f"`{s['source_id']}`({s['status']})" for s in ready[2:5]) or "—"
        third = "、".join(f"`{s['source_id']}`" for s in ext[:4]) or "—"
        lines.append(f"| {w} | {' > '.join(pref) or '—'} | {first} | {second} | {third} |")
    lines.append("")
    for layer, title in LAYERS.items():
        group = sorted([s for s in srcs if s["layer"] == layer], key=lambda x: x["source_id"])
        if not group:
            continue
        lines.append(f"### {title}（`{layer}`）")
        lines.append("")
        lines.append("| source_id | 站 | 状态 | 机种 | 要素 | URL | 取证 | 备注 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for s in group:
            urls = "<br>".join(_cell(u) for u in (s.get("urls") or [])) or "（本地/无 URL）"
            ev = "<br>".join(_cell(e) for e in (s.get("evidence") or [])) or "—"
            lines.append("| `{sid}` | {name} | {st} | {pl} | {el} | {u} | {ev} | {note} |".format(
                sid=s["source_id"], name=_cell(s["name"]), st=s["status"],
                pl=_cell("/".join(s["platforms"])), el=_cell("/".join(s["element_types"])),
                u=urls, ev=ev, note=_cell(s.get("notes", ""))))
        lines.append("")
    dead = sorted([s for s in srcs if s["status"] == "dead"], key=lambda x: x["source_id"])
    unreach = sorted([s for s in srcs if s["status"] == "unreachable"], key=lambda x: x["source_id"])
    lines.append("### 禁用与降级清单（route 自动执行）")
    lines.append("")
    for s in dead:
        c = s.get("closure") or {}
        lines.append(f"- **禁用直连** `{s['source_id']}` {s['name']}：{c.get('date')} {c.get('reason')}；"
                     f"报道 {' '.join(c.get('report_urls') or [])}；历史索引 {c.get('historical_index', '—')}")
    for s in unreach:
        r = s.get("reachability") or {}
        lines.append(f"- **只走快照** `{s['source_id']}` {s['name']}：直连 {r.get('direct', '?')}"
                     f"（{r.get('checked', '?')}）{r.get('note', '')}；引用一律标「未全文核对」")
    lines.append("")
    lines.append("### 缺口层（candidate，遇到好站立即 `ingest` 回填）")
    lines.append("")
    for s in sorted([x for x in srcs if x["status"] == "candidate"], key=lambda x: x["source_id"]):
        lines.append(f"- `{s['source_id']}` {s['name']}（{s['layer']}／{'/'.join(s['platforms'])}）")
    lines.append("")
    lines.append(END_MARK)
    return "\n".join(lines)


def render_write(md_path=None, reg=None):
    reg = reg or load_registry()
    p = Path(md_path or MD_PATH)
    if not p.is_file():
        raise SchemaError(f"人读清单不存在: {p}")
    txt = p.read_text(encoding="utf-8")
    if BEGIN_MARK not in txt or END_MARK not in txt:
        raise SchemaError(f"{p} 缺生成块标记，先插入 {BEGIN_MARK} / {END_MARK} 再 render")
    pre, rest = txt.split(BEGIN_MARK, 1)
    _, post = rest.split(END_MARK, 1)
    new = pre + render_block(reg) + post
    if new != txt:
        p.write_text(new, encoding="utf-8")
    return {"md": str(p), "changed": new != txt, "sources": len(reg["sources"])}


def _pack_source_entries(doc):
    cat = doc.get("catalog") or {}
    entries = cat.get("sources") if isinstance(cat, dict) else None
    if entries is None:
        entries = doc.get("sources")
    return entries or []


def audit(reg=None, packs_dir=None, md_path=None, ledger_path=None):
    """覆盖反查 + 一致性闸门。逐条判 pass/fail/inconclusive，不用总数减失败倒推。"""
    checks = []

    def add(cid, verdict, reason="", detail=None):
        checks.append({"check_id": cid, "verdict": verdict, "reason": reason,
                       "detail": detail or []})

    try:
        reg = reg or load_registry()
        add("registry_schema", Verdict.PASS.value, f"{len(reg['sources'])} 条来源全部通过 schema")
    except SchemaError as e:
        add("registry_schema", Verdict.FAIL.value, str(e))
        return {"status": "fail", "checks": checks}

    by_id = {s["source_id"]: s for s in reg["sources"]}
    bad_ev = []
    for s in reg["sources"]:
        if s["status"] == "verified_read":
            for e in s.get("evidence") or []:
                f = resolve_path(e)
                if not f.is_file() or f.stat().st_size == 0:
                    bad_ev.append(f"{s['source_id']}: {e}")
    add("verified_read_evidence", Verdict.FAIL.value if bad_ev else Verdict.PASS.value,
        "verified_read 的取证文件必须真实存在且非空" if not bad_ev else "取证缺失", bad_ev)

    packs_dir = Path(packs_dir or PACKS_DIR)
    packs = sorted(p for p in packs_dir.glob("*.json") if not p.name.endswith(".bak"))
    wild, uncovered, weak, dead_ref, unmigrated = [], [], [], [], []
    covered_total = 0
    supported = 0
    for p in packs:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            wild.append(f"{p.name}: 读不出 JSON ({e})")
            continue
        entries = _pack_source_entries(doc)
        elements = doc.get("elements") or []
        seen_element_ids = set()
        covered_total += len(elements)
        if not entries and not elements:
            continue
        if not entries:
            uncovered.append(f"{p.name}: 有 {len(elements)} 个要素但没有任何来源")
            continue
        good = []
        for e in entries:
            if not isinstance(e, dict):
                unmigrated.append(f"{p.name}: 自由文本来源 {str(e)[:80]}")
                continue
            unknown = sorted(set(e) - PACK_SOURCE_KEYS)
            if unknown:
                wild.append(f"{p.name}: 来源字段未知 {unknown}")
                continue
            sid = e.get("source_id")
            if sid not in by_id:
                wild.append(f"{p.name}: 野来源 source_id={sid!r}（库里没有，先 ingest）")
                continue
            if e.get("status") != by_id[sid]["status"]:
                wild.append(f"{p.name}: source_id={sid} 状态不一致 "
                            f"（包 {e.get('status')!r} / 库 {by_id[sid]['status']!r}）")
                continue
            if "evidence_report" in e:
                report = e["evidence_report"]
                valid = isinstance(report, str) and bool(report.strip())
                if valid:
                    f = resolve_path(report)
                    valid = f.is_file() and f.stat().st_size > 0
                if not valid:
                    wild.append(f"{p.name}: source_id={sid} 的 evidence_report 缺失或为空")
                    continue
            if by_id[sid]["status"] == "dead":
                dead_ref.append(f"{p.name}: 引用已关停站 {sid}")
            good.append((sid, e))
        for index, el in enumerate(elements):
            eid = el.get("element_id")
            if not eid:
                uncovered.append(f"{p.name}/element[{index}]: 缺 element_id（不得用序号代替或静默跳过）")
                continue
            if eid in seen_element_ids:
                uncovered.append(f"{p.name}/{eid}: element_id 重复（须为包内稳定唯一标识）")
                continue
            seen_element_ids.add(eid)
            own = el.get("sources") or []
            support = [sid for sid, e in good if eid in (e.get("element_ids") or [])]
            support += [s for s in own if isinstance(s, str) and s in by_id]
            if not support:
                uncovered.append(f"{p.name}/{eid}: 无来源支撑")
                continue
            supported += 1
            if all(by_id[s]["status"] != "verified_read" for s in support):
                weak.append(f"{p.name}/{eid}: 只有 {'/'.join(sorted({by_id[s]['status'] for s in support}))} 支撑")
    add("pack_sources_migrated", Verdict.FAIL.value if unmigrated else Verdict.PASS.value,
        "知识包来源须为结构化引用（source_id/url/status/verified_date/element_ids）"
        if not unmigrated else "仍有自由文本来源", unmigrated)
    add("no_wild_sources", Verdict.FAIL.value if wild else Verdict.PASS.value,
        "每个 source_id 都在库内，状态一致且取证报告有效" if not wild else "存在野来源或无效来源引用", wild)
    add("no_dead_reference", Verdict.FAIL.value if dead_ref else Verdict.PASS.value,
        "不得引用已关停站" if not dead_ref else "引用了 dead 站", dead_ref)
    add("element_coverage", Verdict.FAIL.value if uncovered else Verdict.PASS.value,
        f"{covered_total} 个要素全部有来源支撑" if not uncovered else "要素缺来源或声称与证据不符",
        uncovered)
    if not supported:
        vs_v = Verdict.INCONCLUSIVE.value
        vs_why = (f"{covered_total} 个要素中 0 个取得来源支撑，无法判 verified"
                  "（空支撑/零要素都不算已验证）")
    elif weak:
        vs_v = Verdict.INCONCLUSIVE.value
        vs_why = ("以下要素只有快照/不可达/候选层支撑，不得声称已全文核对"
                  "（升 verified 须真读正文落取证，或本机实测落记录）")
    else:
        vs_v, vs_why = Verdict.PASS.value, f"{supported} 个要素均有 verified_read 来源"
    add("verified_support", vs_v, vs_why, weak)

    p = Path(md_path or MD_PATH)
    if not p.is_file():
        add("render_sync", Verdict.FAIL.value, f"人读清单不存在: {p}")
    else:
        txt = p.read_text(encoding="utf-8")
        if BEGIN_MARK not in txt or END_MARK not in txt:
            add("render_sync", Verdict.FAIL.value, "缺生成块标记（人读清单必须是 render 产物）")
        else:
            block = txt.split(BEGIN_MARK, 1)[1].split(END_MARK, 1)[0]
            want = render_block(reg)
            want_block = want.split(BEGIN_MARK, 1)[1].split(END_MARK, 1)[0]
            add("render_sync", Verdict.PASS.value if block == want_block else Verdict.FAIL.value,
                "生成块与主数据一致" if block == want_block else "生成块漂移：跑 render --write")

    led = _ledger(ledger_path)
    bad_claims = []
    for c in reg.get("absence_claims") or []:
        for job in c.get("support") or []:
            if not any(e["job_id"] == job and e["status"] == "failed" for e in led.entries):
                bad_claims.append(f"{c.get('game')}/{c.get('want')}: 支撑 job 不在台账 {job}")
    add("absence_claims_supported", Verdict.FAIL.value if bad_claims else Verdict.PASS.value,
        "每条「不存在」声称都有 miss 台账支撑" if not bad_claims else "无据的不存在声称", bad_claims)

    fails = sum(1 for c in checks if c["verdict"] == Verdict.FAIL.value)
    incon = sum(1 for c in checks if c["verdict"] == Verdict.INCONCLUSIVE.value)
    passes = sum(1 for c in checks if c["verdict"] == Verdict.PASS.value)
    return {"status": "fail" if fails else ("inconclusive" if incon else "pass"),
            "counts": {"pass": passes, "fail": fails, "inconclusive": incon,
                       "sources": len(reg["sources"]), "packs": len(packs),
                       "elements_checked": covered_total, "elements_supported": supported},
            "checks": checks}


def probe(url, timeout=15):
    """探活。失败≠站没了：只记录事实，升 dead 要人给当期证据。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (sources.py recheck)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"direct": "ok", "http_status": r.status, "checked": today()}
    except urllib.error.HTTPError as e:
        return {"direct": str(e.code), "http_status": e.code, "checked": today()}
    except Exception as e:
        return {"direct": "fail", "error": f"{type(e).__name__}: {e}", "checked": today()}


def recheck(source_id=None, mark_dead=False, reason=None, reg=None, reg_path=None,
            probe_fn=None):
    reg = reg or load_registry()
    probe_fn = probe_fn or probe
    targets = [find_source(reg, source_id)] if source_id else [
        s for s in reg["sources"] if s.get("urls") and s.get("kind", "site") == "site"]
    results = []
    for s in targets:
        if mark_dead:
            if not reason:
                raise SchemaError("升 dead 必须给 --reason（当期证据：报道/直连结果）")
            s["status"] = "dead"
            s["last_verified"] = today()
            s.setdefault("closure", {}).update({"date": today(), "reason": reason})
            results.append({"source_id": s["source_id"], "marked_dead": True, "reason": reason})
            continue
        url = s["urls"][0]
        r = probe_fn(url)
        s["reachability"] = {**r, "note": (s.get("reachability") or {}).get("note", "")}
        if r["direct"] == "ok" and s["status"] == "unreachable":
            s["status"] = "snippet_only"
            s["last_verified"] = today()
            r["promoted"] = "unreachable->snippet_only（直连恢复，内容仍需真读才升 verified_read）"
        results.append({"source_id": s["source_id"], "url": url, **r})
    save_registry(reg, reg_path)
    return {"checked": len(results), "results": results}


def show(reg=None):
    reg = reg or load_registry()
    by_status, by_layer = {}, {}
    for s in reg["sources"]:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
        by_layer[s["layer"]] = by_layer.get(s["layer"], 0) + 1
    return {"total": len(reg["sources"]), "updated": reg.get("updated"),
            "by_status": by_status, "by_layer": by_layer,
            "absence_claims": len(reg.get("absence_claims") or []),
            "ledger": _ledger().summary()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="库概览（状态/层计数 + 台账摘要）")

    r = sub.add_parser("route", help="先定身份→库内优先→延伸段（S1 强制入口）")
    r.add_argument("--game", required=True)
    r.add_argument("--want", required=True, help="逗号分隔要素类型")
    r.add_argument("--set", dest="set_name", default=None)
    r.add_argument("--platform", default=None)
    r.add_argument("--rom", default=None)
    r.add_argument("--out", default=None)

    g = sub.add_parser("log", help="命中/快照/未命中落台账（hit 必须带正文产物）")
    g.add_argument("--source-id", required=True)
    g.add_argument("--game", required=True)
    g.add_argument("--want", required=True)
    g.add_argument("--verdict", required=True, choices=("hit", "miss", "snippet"))
    g.add_argument("--evidence", action="append", default=[])
    g.add_argument("--url", default=None)
    g.add_argument("--note", default=None)
    g.add_argument("--element-ids", default=None)

    c = sub.add_parser("claim-absence", help="下「不存在」结论前的中文层必扫门")
    c.add_argument("--game", required=True)
    c.add_argument("--want", required=True)

    i = sub.add_parser("ingest", help="新站去重入库分类")
    i.add_argument("--url", required=True)
    i.add_argument("--name", required=True)
    i.add_argument("--layer", required=True)
    i.add_argument("--platforms", required=True)
    i.add_argument("--want", required=True)
    i.add_argument("--status", default="candidate", choices=STATUSES)
    i.add_argument("--evidence", action="append", default=[])
    i.add_argument("--notes", default=None)
    i.add_argument("--kind", default="site")

    rd = sub.add_parser("render", help="由主数据生成人读清单的 GENERATED 块")
    rd.add_argument("--write", action="store_true")
    rd.add_argument("--md", default=None)

    a = sub.add_parser("audit", help="覆盖反查 + 一致性闸门")
    a.add_argument("--packs", default=None)
    a.add_argument("--md", default=None)
    a.add_argument("--out", default=None)

    k = sub.add_parser("recheck", help="探活并记录 reachability（不自动判死）")
    k.add_argument("--source-id", default=None)
    k.add_argument("--mark-dead", action="store_true")
    k.add_argument("--reason", default=None)

    args = ap.parse_args()
    if args.cmd == "show":
        res, code = show(), 0
    elif args.cmd == "route":
        res = route(args.game, args.want, set_name=args.set_name, platform=args.platform,
                    rom=args.rom, out=args.out)
        code = 0 if res["status"] == "ready" else 2
    elif args.cmd == "log":
        eids = [x.strip() for x in args.element_ids.split(",")] if args.element_ids else None
        res = log(args.source_id, args.game, args.want, args.verdict, evidence=args.evidence,
                  url=args.url, note=args.note, element_ids=eids)
        code = 0 if res["verdict"] == Verdict.PASS.value else 2
    elif args.cmd == "claim-absence":
        res = claim_absence(args.game, args.want)
        code = 0 if res["status"] == "allowed" else 2
    elif args.cmd == "ingest":
        res = ingest(args.url, args.name, args.layer, args.platforms, args.want,
                     status=args.status, evidence=args.evidence, notes=args.notes, kind=args.kind)
        code = 0
    elif args.cmd == "render":
        if args.write:
            res, code = render_write(args.md), 0
        else:
            print(render_block())
            return 0
    elif args.cmd == "audit":
        res = audit(packs_dir=args.packs, md_path=args.md)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")
        code = 0 if res["status"] == "pass" else 2
    elif args.cmd == "recheck":
        res = recheck(args.source_id, mark_dead=args.mark_dead, reason=args.reason)
        code = 0
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())