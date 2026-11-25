# -*- coding: utf-8 -*-
"""B站需求探针（P3 主动版，零LLM，说明书§11）。拿选题词搜 B 站已有视频，量真实受众
需求代理：供给/播放/互动率/近期热度。制作前验证，不替代原 P3 自家后台终判。

口径：测的是「该词在 B 站已有视频的热度」＝本选题需求的代理，不等于「我这条视频会火」。
网络走环境代理（禁写死口）；buvid cookie 零登录；非 WBI search/type 端点；限速防风控；
只缓存 ok；聚合只存数值+bvid locator+短标题（版权，不搬描述/全文）。
探针/selftest 离线 mock，patch 路径常量到 tempdir，不真联网不写真实状态。"""
import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MODDIR = Path(__file__).resolve().parent
OUT_ROOT = MODDIR / "B站热度实验"
CACHE = MODDIR / "B站缓存"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HOME = "https://www.bilibili.com/"
SEARCH_EP = "https://api.bilibili.com/x/web-interface/search/type"
MIN_INTERVAL = 1.5        # 每词间隔秒，防风控
RETRY_MAX = 2             # 412 退避重试上限
TIMEOUT = 20
RECENT_DAYS = 90          # 近期热度窗口
TITLE_MAX = 60            # 短标题引（版权）
PAGES = 1                 # 试点取 top1 页≈20 视频
CACHE_MAX_AGE_H = 24      # ok 缓存复用时效（过期重取）
# 相关度闸门：B站 search/type 对任何词都做词元级模糊兜底（连 nonsense 词都返回
# 20条 loosely-related 视频、numResults 恒 capped 1000）。核心命中率<此值＝标题
# 根本不含关键词核心词＝兜底无关内容（model2-nx→UG NX CAD、toniisound→ASMR），
# 播放中位不可信→需求未知。0.3 落在实测污染(0.0)与真相关(≥0.5)的空档（推算）。
RELEVANCE_MIN = 0.3

_TAG = re.compile(r"<[^>]+>")

# 试点词表（手 map：点名IP中文别名＋入口B＋今日优先＋频道核心＋生僻反证）。
# card→keyword 自动映射接 IP 别名表是后续；本期试点用此代表集，不 blast 全量。
# ★取词消歧（11-19 实测试点翻出）：中文别名「星之海」在 B 站被裙子/游戏BOSS/MMO玩家名
# 占据（字面全命中但语义无关，播放中位虚高114084）→改用英文原名 Sea of Stars（真游戏，
# 中位2862）。生僻反证词 model2-nx 被模糊匹配到 UG NX CAD（非冷词）→改用 toniisound
# （核心命中0，真兜底）。教训：歧义别名须换无歧义词，零LLM相关度过滤治不了语义歧义。
PILOT_WORDS = [
    ("热血足球", "入口B/retro_soccer", "大盘"),
    ("拳皇98", "入口B/kof98", "大盘"),
    ("街机改版", "入口B/arcade", "大盘"),
    ("星之卡比", "Kirby", "大盘"),
    ("皮克敏", "Pikmin", "大盘"),
    ("塞尔达传说", "Zelda/时之笛", "大盘"),
    ("异度之刃", "Xenoblade", "大盘"),
    ("龙珠", "Dragon Ball", "大盘"),
    ("剑星", "Stellar Blade", "大盘"),
    ("Sea of Stars", "Sea of Stars/星之海(消歧)", "大盘"),
    ("Switch2 破解", "NS2越狱", "角度"),
    ("shadPS4", "PS4模拟器", "大盘"),
    ("Batocera", "今日优先/固件", "大盘"),
    ("Dolphin模拟器", "今日优先/dolphin-nx", "大盘"),
    ("开源掌机", "频道核心", "大盘"),
    ("toniisound", "生僻反证(应未知/不可靠)", "大盘"),
]

# ★编辑track表（草案待用户核，说明书§11.10，版本 bili-track-2026-11-19-v1）。
# 两条受欢迎逻辑：新游(通关即终·热度一时·时效敏感) vs 怀旧(质量几十年已过关·enduring·
# 近期冷=供给缺口机会，成败看齐全盘点+文案画面匹配+共鸣)。工具/固件非游戏→中性track不套两轨；
# 跨代IP须人工判；反证=非IP控制词。分类是编辑判断(同知名IP表性质)，零LLM用显式表。
TRACK_VERSION = "bili-track-2026-11-19-v1"
WORD_TRACK = {
    "热血足球": "怀旧", "拳皇98": "怀旧", "街机改版": "怀旧",
    "异度之刃": "新游", "星之卡比": "新游", "剑星": "新游",
    "皮克敏": "新游", "Sea of Stars": "新游",
    "塞尔达传说": "跨代", "龙珠": "跨代",
    "开源掌机": "工具", "Batocera": "工具", "Dolphin模拟器": "工具",
    "shadPS4": "工具", "Switch2 破解": "工具",
    "toniisound": "反证",
}


def word_track(kw):
    """词→track。未列入→未分类(不套用游戏两轨)。"""
    return WORD_TRACK.get(kw, "未分类")


def channel_fit(rec):
    """频道适配判读标签（track-aware 单一权威，§11.10）。信息性，不改需求档/队列。
    怀旧：近期冷+总高=供给缺口机会(enduring受众·近期供给少；成败=齐全盘点+文案画面匹配+共鸣，
    非当前平台热度)；新游：近期冷=热度消退(通关即终·窗口收窄)，近期热=trending(时效窗口)；
    工具：版本新闻时效/教程evergreen自有逻辑，不套用游戏两轨；跨代：须人工判，不自动套任一轨。
    cold=rc==0或rpm<pm*0.3；hot=rc>=5且rpm>=pm*0.5。需求回流._channel_fit 委托本函数。"""
    track = word_track(rec.get("keyword", ""))
    pm = rec.get("relevant_play_median", 0) or 0
    rpm = rec.get("recent_play_median", 0) or 0
    rc = rec.get("recent_count", 0) or 0
    cold = rc == 0 or (pm > 0 and rpm < pm * 0.3)
    hot = rc >= 5 and pm > 0 and rpm >= pm * 0.5
    if track == "怀旧":
        if pm <= 0:
            return "无受众量级数据,须核(不冒充enduring)"
        if cold:
            return "供给缺口机会(enduring受众·近期供给少;成败=齐全盘点+文案画面匹配+共鸣,非当前平台热度)"
        if hot:
            return "近期有人盘点(trending);怀旧enduring,仍看执行质量"
        return "近期供给一般;怀旧enduring,看执行质量"
    if track == "新游":
        if cold:
            return "热度消退(通关即终·窗口收窄)"
        if hot:
            return "当前活跃(trending·时效窗口)"
        return "近期一般"
    if track == "工具":
        if hot:
            return "当前活跃(版本新闻/教程需求)"
        if cold:
            return "近期冷(教程evergreen/版本间歇)"
        return "近期一般"
    if track == "跨代":
        return "跨代IP(怀旧enduring+新游事件驱动),须人工判近期冷=供给缺口还是热度消退"
    return "未分类/反证,不套用游戏两轨"


def _strip_em(s):
    return _TAG.sub("", s or "").strip()


def _kw_cores(kw):
    """关键词核心词元：拉丁≥3字符token（model2/toniisound/shadps4，滤掉泛词nx）
    ＋CJK全词及2字子词（街机改版→街机/改版，避免复合词全词包含太严假旗）。"""
    lat = re.findall(r"[a-z0-9]{3,}", kw.lower())
    cjk = set()
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", kw):
        cjk.add(run)
        for i in range(len(run) - 1):
            cjk.add(run[i:i + 2])
    return lat, sorted(cjk)


def _core_hit(kw, title):
    """标题是否含关键词任一核心词元（相关度代理；高命中≠语义相关，星之海歧义治不了）。"""
    lat, cjk = _kw_cores(kw)
    t = (title or "").lower()
    return bool((lat and any(l in t for l in lat))
                or (cjk and any(c in t for c in cjk)))


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_opener():
    """cookiejar opener，自动携带 buvid。走 urllib 默认环境代理（禁写死口）。"""
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA), ("Referer", HOME),
                     ("Accept", "application/json, text/plain, */*")]
    return op, cj


def bootstrap_cookie(op):
    """GET homepage 拿 buvid3（零登录）。返回 (ok, error)。cookie 名由调用方从 cj 读。"""
    try:
        with op.open(HOME, timeout=TIMEOUT) as r:
            r.read()
        return True, ""
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def search(keyword, op, page=1):
    """非 WBI search/type。返回 (data, status, error)；status ok/empty/error。
    412 风控退避重试≤RETRY_MAX；error/empty 不冒充 ok。"""
    url = SEARCH_EP + "?" + urllib.parse.urlencode(
        {"search_type": "video", "keyword": keyword, "page": page})
    for attempt in range(RETRY_MAX + 1):
        try:
            with op.open(url, timeout=TIMEOUT) as r:
                j = json.loads(r.read().decode("utf-8", "replace"))
            code = j.get("code")
            if code == -412:
                if attempt < RETRY_MAX:
                    time.sleep(MIN_INTERVAL * (attempt + 2))
                    continue
                return None, "error", "412风控(request was banned)，重试耗尽"
            if code != 0:
                return None, "error", f"code={code} msg={j.get('message')}"
            d = j.get("data") or {}
            res = d.get("result") or []
            if not res or not d.get("numResults", 0):
                return d, "empty", "numResults=0/result空，无供给"
            return d, "ok", ""
        except urllib.error.HTTPError as e:
            if e.code == 412 and attempt < RETRY_MAX:
                time.sleep(MIN_INTERVAL * (attempt + 2))
                continue
            return None, "error", f"HTTP {e.code}"
        except Exception as e:
            return None, "error", f"{type(e).__name__}: {e}"
    return None, "error", "重试耗尽"


def _num(v):
    return v if isinstance(v, (int, float)) else 0


def metrics(videos, num_results, now_ts, keyword=""):
    """从 top 视频算指标。★相关度过滤：B站模糊兜底会混入无关视频，需求指标只在
    标题核心命中关键词的子集(rel)上算（去污染）；原始 play_median 留作对照。
    core_hit_rate<RELEVANCE_MIN＝兜底无关内容（classify 判未知）。top3 取原始（诊断用，
    让人工看见 B站到底返回了什么）。中位抗头部异常值；互动率=(赞+藏+弹幕+评)/播放。"""
    n = len(videos)
    rel = [v for v in videos if _core_hit(keyword, _strip_em(v.get("title")))] if keyword else list(videos)
    full = re.sub(r"[\s\-]", "", keyword.lower())
    full_n = sum(1 for v in videos
                 if full and full in re.sub(r"[\s\-]", "", _strip_em(v.get("title")).lower()))
    raw_plays = [_num(v.get("play")) for v in videos if _num(v.get("play")) > 0]
    plays = [_num(v.get("play")) for v in rel if _num(v.get("play")) > 0]
    eng = []
    for v in rel:
        p = _num(v.get("play"))
        if p > 0:
            inter = (_num(v.get("like")) + _num(v.get("favorites"))
                     + _num(v.get("danmaku") or v.get("video_review"))
                     + _num(v.get("review")))
            eng.append(inter / p)
    cutoff = now_ts - RECENT_DAYS * 86400
    recent = [v for v in rel if _num(v.get("pubdate")) >= cutoff]
    recent_plays = [_num(v.get("play")) for v in recent if _num(v.get("play")) > 0]
    top = sorted(videos, key=lambda v: _num(v.get("play")), reverse=True)[:3]
    return {
        "supply_num_results": num_results,   # 恒 capped 1000，无区分度，仅展示
        "n_videos": n,
        "relevant_count": len(rel),
        "core_hit_rate": round(len(rel) / n, 3) if n else 0,
        "full_hit_rate": round(full_n / n, 3) if n else 0,
        "play_median": statistics.median(raw_plays) if raw_plays else 0,   # 原始(含兜底)对照
        "relevant_play_median": statistics.median(plays) if plays else 0,  # 去污染需求判据
        "play_mean": round(statistics.mean(plays), 1) if plays else 0,
        "play_max": max(plays) if plays else 0,
        "play_total": sum(plays),
        "engagement_median": round(statistics.median(eng), 4) if eng else 0,
        "recent_count": len(recent),
        "recent_play_median": statistics.median(recent_plays) if recent_plays else 0,
        "top3": [{"bvid": v.get("bvid"), "title": _strip_em(v.get("title"))[:TITLE_MAX],
                  "author": v.get("author"), "play": _num(v.get("play")),
                  "pubdate": datetime.fromtimestamp(_num(v.get("pubdate")), timezone.utc
                                                    ).strftime("%Y-%m-%d")
                  if _num(v.get("pubdate")) else ""}
                 for v in top],
    }


def _cache_path(keyword):
    h = hashlib.sha256(keyword.encode("utf-8")).hexdigest()[:16]
    return CACHE / f"{h}.json"


def _cache_hit(keyword, force):
    if force:
        return None
    p = _cache_path(keyword)
    if not p.is_file():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    # 只信 ok 且有指标；过期重取（防陈旧）
    if rec.get("status") != "ok" or "play_median" not in rec:
        return None
    ts = rec.get("ts_epoch", 0)
    if time.time() - ts > CACHE_MAX_AGE_H * 3600:
        return None
    return rec


def _cache_write(rec):
    if rec.get("status") != "ok":
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    p = _cache_path(rec["keyword"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def measure(keyword, op, pages=PAGES, now_ts=None, force=False, use_cache=True):
    """搜词→指标 record。status ok/empty/error；只缓存 ok。"""
    now_ts = now_ts if now_ts is not None else time.time()
    if use_cache:
        hit = _cache_hit(keyword, force)
        if hit:
            return {**hit, "cache_hit": True}
    videos, num_results, status, error = [], 0, "ok", ""
    for p in range(1, pages + 1):
        d, st, err = search(keyword, op, page=p)
        if st != "ok":
            status, error = st, err
            break
        num_results = d.get("numResults", 0)
        videos.extend(d.get("result") or [])
        if p < pages:
            time.sleep(MIN_INTERVAL)
    rec = {"keyword": keyword, "status": status, "ts": _now_iso(), "ts_epoch": time.time()}
    if status != "ok":
        rec["error"] = error
        rec["cache_hit"] = False
        return rec
    rec.update(metrics(videos, num_results, now_ts, keyword=keyword))
    rec["cache_hit"] = False
    if use_cache:
        _cache_write(rec)
    return rec


def classify(rec, thresholds):
    """需求分档。阈值从试点数据定（thresholds dict），未定→未知（先跑数据）。
    empty/error→未知，不冒充低或高。★相关度闸门：core_hit_rate<RELEVANCE_MIN＝B站
    模糊兜底无关内容→未知/不可靠（不拿兜底播放冒充需求）。分档用去污染 relevant_play_median。
    reason 标代理性质＋粒度＋相关度。"""
    base = "B站已有视频热度代理，非本选题实测"
    if rec.get("status") == "empty":
        return "未知", base + "；无供给(numResults=0)，不冒充低或高"
    if rec.get("status") != "ok":
        return "未知", base + f"；探测{rec.get('status')}({rec.get('error','')})，不冒充0需求"
    chr_ = rec.get("core_hit_rate", 0)
    if chr_ < RELEVANCE_MIN:
        return "未知", (base + f"；关键词模糊兜底·不可靠(核心命中率{chr_:.2f}<{RELEVANCE_MIN}，"
                        f"B站返回无关内容如model2-nx→NX CAD)，不拿兜底播放冒充需求")
    if not thresholds:
        return "未知", base + f"；核心命中率{chr_:.2f}；阈值未定(先跑数据看分布)"
    pm = rec.get("relevant_play_median", 0)
    hi = thresholds.get("play_median_high")
    mid = thresholds.get("play_median_mid")
    if hi is not None and pm >= hi:
        lvl = "高"
    elif mid is not None and pm >= mid:
        lvl = "中"
    else:
        lvl = "低"
    return lvl, (base + f"；核心命中率{chr_:.2f}；去污染播放中位{pm:.0f}"
                 + (f"≥高{hi:.0f}" if lvl == "高" else f"≥中{mid:.0f}" if lvl == "中"
                    else f"<中{mid:.0f}")
                 + "；高命中≠语义相关，歧义词须人工核top3")


def _atomic(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def run_pilot(words=None, outdir=None, thresholds=None, force=False, pages=PAGES):
    """跑试点：bootstrap cookie→逐词 measure(限速)→聚合统计→落产物。
    words: [(keyword, 来源, 粒度)]；默认 PILOT_WORDS。返回 (recs, runinfo)。"""
    words = words or PILOT_WORDS
    d = Path(outdir) if outdir else OUT_ROOT
    op, cj = build_opener()
    ok_cookie, cerr = bootstrap_cookie(op)
    cookie_names = [c.name for c in cj]
    recs = []
    for i, (kw, src, gran) in enumerate(words):
        rec = measure(kw, op, pages=pages, force=force)
        rec["source"] = src
        rec["granularity"] = gran
        lvl, why = classify(rec, thresholds)
        rec["demand_level"] = lvl
        rec["demand_reason"] = why
        recs.append(rec)
        if i < len(words) - 1:
            time.sleep(MIN_INTERVAL)
    from collections import Counter
    sc = Counter(r["status"] for r in recs)
    lc = Counter(r["demand_level"] for r in recs)
    # 分布只取「可靠」ok词（核心命中≥闸门），用去污染播放中位定阈值
    ok_recs = [r for r in recs if r["status"] == "ok"
               and r.get("core_hit_rate", 0) >= RELEVANCE_MIN]
    pms = sorted(r["relevant_play_median"] for r in ok_recs)
    contaminated = [r["keyword"] for r in recs if r["status"] == "ok"
                    and r.get("core_hit_rate", 0) < RELEVANCE_MIN]
    runinfo = {
        "ts": _now_iso(), "words": len(words), "cookie_ok": ok_cookie,
        "cookie_names": cookie_names, "cookie_error": cerr,
        "status_counts": dict(sc), "demand_counts": dict(lc),
        "thresholds": thresholds or "未定(先跑数据)",
        "relevance_min": RELEVANCE_MIN,
        "track_version": TRACK_VERSION,
        "contaminated_words": contaminated,
        "reliable_ok_words": len(ok_recs),
        "relevant_play_median_distribution": {
            "min": pms[0] if pms else None, "p25": pms[len(pms)//4] if pms else None,
            "median": statistics.median(pms) if pms else None,
            "p75": pms[3*len(pms)//4] if pms else None, "max": pms[-1] if pms else None},
        "pages_per_word": pages, "min_interval_s": MIN_INTERVAL,
        "note": "平台已有内容热度代理，非本选题实测；试点手map词，自动card→keyword回流后续；"
                "供给numResults恒capped1000无区分度；核心命中<闸门＝模糊兜底判未知；"
                "高命中≠语义相关(星之海歧义须换无歧义词+人工核top3)",
    }
    _atomic(d / "探针结果.json", json.dumps(recs, ensure_ascii=False, indent=1))
    _atomic(d / "运行记录.json", json.dumps(runinfo, ensure_ascii=False, indent=1))
    _atomic(d / "需求统计.md", render_stats(recs, runinfo))
    return recs, runinfo


def render_stats(recs, ri):
    lines = ["# B站需求探针 试点统计", "",
             f"> {ri['ts']}；{ri['words']}词；cookie={ri['cookie_ok']}({','.join(ri['cookie_names'])})；"
             f"每词top{ri['pages_per_word']}页；间隔{ri['min_interval_s']}s",
             f"> 口径：{ri['note']}", "",
             f"状态分布：{ri['status_counts']}；需求分档：{ri['demand_counts']}",
             f"阈值：{ri['thresholds']}；相关度闸门：{ri['relevance_min']}",
             f"模糊兜底·不可靠词(核心命中<闸门→未知)：{ri['contaminated_words']}", "",
             "## 逐词指标（按去污染播放中位降序）", "",
             "| 词 | 来源 | 粒度 | 状态 | 核心命中 | 去污染播放中位 | 原始播放中位 | 互动率中位 | 近90天数 | 近期播放中位 | 需求 |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(recs, key=lambda x: x.get("relevant_play_median", 0), reverse=True):
        if r["status"] == "ok":
            lines.append(
                f"| {r['keyword']} | {r.get('source','')} | {r.get('granularity','')} | ok "
                f"| {r['core_hit_rate']:.2f} | {r['relevant_play_median']:.0f} | {r['play_median']:.0f} "
                f"| {r['engagement_median']:.3f} | {r['recent_count']} | {r['recent_play_median']:.0f} "
                f"| {r['demand_level']} |")
        else:
            lines.append(
                f"| {r['keyword']} | {r.get('source','')} | {r.get('granularity','')} "
                f"| {r['status']} | - | - | - | - | - | - | {r['demand_level']} |")
    lines += ["", "## 去污染播放中位分布（可靠ok词，定阈值依据）", "",
              f"```{json.dumps(ri['relevant_play_median_distribution'], ensure_ascii=False)}```", "",
              "## 频道适配解读（两条受欢迎逻辑，track-aware，§11.10）", ""]
    reliable = [r for r in recs if r["status"] == "ok"
                and r.get("core_hit_rate", 0) >= RELEVANCE_MIN]
    if reliable:
        eng_top = sorted(reliable, key=lambda x: x.get("engagement_median", 0), reverse=True)[:4]
        lines.append("- **互动率领先**（忠诚受众，niche反超大众IP）："
                     + "、".join(f"{r['keyword']}({r['engagement_median']:.3f})" for r in eng_top))
        by_track = {}
        for r in reliable:
            by_track.setdefault(word_track(r["keyword"]), []).append(r)

        # 判读全部走单一权威 channel_fit（与回流同口径，trending/fading 不重叠）
        # 怀旧：近期冷=供给缺口机会(非需求死)；质量几十年已过关，成败看执行质量
        retro = by_track.get("怀旧", [])
        if retro:
            gap = [r for r in retro if "供给缺口机会" in channel_fit(r)]
            lines.append("- **怀旧游戏·供给缺口机会**（质量几十年已过关、enduring受众；近期供给少是蓝海。"
                         "成败=盘点齐全+文案画面匹配+共鸣，非当前平台热度）："
                         + ("、".join(f"{r['keyword']}(总{r['relevant_play_median']:.0f}/近期{r.get('recent_play_median', 0):.0f})"
                                      for r in sorted(gap, key=lambda x: x['relevant_play_median'], reverse=True))
                            or "无"))
        # 新游：trending(时效窗口) vs 热度消退(通关即终)
        new = by_track.get("新游", [])
        if new:
            trending = [r for r in new if "当前活跃" in channel_fit(r)]
            fading = [r for r in new if "热度消退" in channel_fit(r)]
            lines.append("- **新游·当前活跃(trending·时效窗口)**："
                         + ("、".join(f"{r['keyword']}(近期{r.get('recent_play_median', 0):.0f}/{r.get('recent_count', 0)}条)"
                                      for r in sorted(trending, key=lambda x: x.get('recent_play_median', 0), reverse=True))
                            or "无"))
            lines.append("- **新游·热度消退(通关即终·窗口收窄)**："
                         + ("、".join(f"{r['keyword']}(总{r['relevant_play_median']:.0f}/近期{r.get('recent_play_median', 0):.0f})"
                                      for r in sorted(fading, key=lambda x: x['relevant_play_median'], reverse=True))
                            or "无"))
        # 工具：中性track，不套用游戏两轨
        tool = by_track.get("工具", [])
        if tool:
            lines.append("- **工具/固件（中性track，不套用游戏两轨；版本新闻时效+教程evergreen）**："
                         + "、".join(f"{r['keyword']}({channel_fit(r)})" for r in tool))
        # 跨代：须人工判
        cross = by_track.get("跨代", [])
        if cross:
            lines.append("- **跨代IP（须人工判：怀旧enduring+新游事件驱动）**："
                         + "、".join(f"{r['keyword']}(总{r['relevant_play_median']:.0f}/近期{r.get('recent_play_median', 0):.0f})"
                                     for r in cross))
        lines.append("- **判读口径（两条受欢迎逻辑）**：新游/大IP天然会火、火多久看质量，动作类通关即终热度一时"
                     "→近期冷=热度消退(时效敏感)；怀旧游戏质量几十年已过关，那一代人怀旧滤镜反复回味，要的是当年没注意到的"
                     "机制/彩蛋/剧情齐全盘点→不管什么时候，只要盘点齐全+文案画面匹配正确且好+文案质量高引起共鸣就依然能火，"
                     "近期冷=供给缺口机会(非需求死)。工具/固件非游戏，不套用两轨。播放中位=受众量级代理(偏大众IP)，"
                     "互动率=忠诚(niche高)，近期播放须按track判读。终判仍留原P3自家后台performances。")
    lines += ["", "## top3 视频复核（原始返回，locator+短标题；人工核相关度/语义歧义）", ""]
    for r in recs:
        if r["status"] == "ok" and r.get("top3"):
            lines.append(f"- **{r['keyword']}**（核心命中{r['core_hit_rate']:.2f}）：")
            for t in r["top3"]:
                lines.append(f"  - {t['bvid']} ｜ {t['title']} ｜ {t['author']} ｜ 播放{t['play']} ｜ {t['pubdate']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="B站需求探针试点（说明书§11）")
    ap.add_argument("--outdir", default=None)
    ap.add_argument("--thresholds", default=None, help="阈值JSON路径(play_median_high/mid)")
    ap.add_argument("--force", action="store_true", help="忽略缓存重取")
    ap.add_argument("--pages", type=int, default=PAGES)
    ap.add_argument("--words", default=None, help="自定义词JSON [[kw,src,gran],...]")
    a = ap.parse_args()
    th = None
    if a.thresholds:
        th = json.loads(Path(a.thresholds).read_text(encoding="utf-8"))
    words = json.loads(Path(a.words).read_text(encoding="utf-8")) if a.words else None
    recs, ri = run_pilot(words=words, outdir=a.outdir, thresholds=th,
                         force=a.force, pages=a.pages)
    print(f"cookie={ri['cookie_ok']}({','.join(ri['cookie_names'])}) {ri['cookie_error']}")
    print(f"状态={ri['status_counts']} 需求={ri['demand_counts']}")
    print(f"去污染播放中位分布={ri['relevant_play_median_distribution']}")
    print(f"模糊兜底不可靠词={ri['contaminated_words']}")
    for r in sorted(recs, key=lambda x: x.get("relevant_play_median", 0), reverse=True):
        if r["status"] == "ok":
            print(f"  {r['keyword']:14s} 核心命中{r['core_hit_rate']:.2f} "
                  f"去污染中位{r['relevant_play_median']:9.0f} 原始{r['play_median']:9.0f} "
                  f"互动{r['engagement_median']:.3f} 近90天{r['recent_count']:2d} → {r['demand_level']}")
        else:
            print(f"  {r['keyword']:14s} {r['status']} {r.get('error','')} → {r['demand_level']}")
    print(f"产物: {Path(a.outdir) if a.outdir else OUT_ROOT}")


if __name__ == "__main__":
    main()