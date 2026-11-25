# -*- coding: utf-8 -*-
"""正文采集（说明书§10.3）：urllib走环境代理（沿用sources.probe约定，禁写死端口）+bs4抽正文。
缓存只存截断正文（≤4000字，本层私有不分发）；卡只给snippet≤240+locator（版权§1.6）。
失败显式留痕（status=error+原因），不静默顶包。精修在 关注分层.score_event(body=...) 内做，
保证关注/队列一致重算。定向采top卡，不blast全窗口。"""
import hashlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from 事件归并 import norm_url

MODDIR = Path(__file__).resolve().parent
CACHE = MODDIR / "正文缓存"
UA = "Mozilla/5.0 (compatible; editorial-layer-body-collector/1.0; local)"
MAX_BYTES = 2_000_000
MAX_CACHE_TEXT = 4000
SNIPPET_MAX = 240
TIMEOUT = 20
ATT_RANK = {"高": 2, "中": 1, "低": 0}
TIME_RANK = {"高": 2, "中": 1, "未知": 0, "低": -1}


def _cache_path(url, cache_dir=None):
    d = Path(cache_dir or CACHE)
    return d / (hashlib.sha1(norm_url(url).encode("utf-8")).hexdigest()[:16] + ".json")


_BOILERPLATE = ("sorry, something went wrong", "uh oh", "there was an error while loading",
                "choose a tag to compare", "please reload this page", "loading complete",
                "you can’t perform that action", "you can't perform that action")


def _is_boilerplate(line):
    low = line.lower().strip()
    return any(b in low for b in _BOILERPLATE)


def _extract(html):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "form"]):
        t.decompose()
    main = (soup.find(class_="markdown-body") or soup.find("article")
            or soup.find("main") or soup.body or soup)
    paras = [p.get_text(" ", strip=True) for p in main.find_all(["p", "li", "h1", "h2", "h3"])]
    text = "\n".join(x for x in paras if x and not _is_boilerplate(x))
    return text or main.get_text(" ", strip=True)


def fetch(url, timeout=TIMEOUT, cache_dir=None, force=False):
    """取正文。返回 {status:ok/error, snippet≤240, locator, main_text≤4000, text_len,
    http_status, fetched_at, error}。缓存命中直接返回（force=True 跳过缓存）。"""
    cp = _cache_path(url, cache_dir)
    if cp.is_file() and not force:
        try:
            cached = json.loads(cp.read_text(encoding="utf-8"))
            if cached.get("status") == "ok" and (cached.get("snippet") or cached.get("main_text")):
                return cached
        except Exception:
            pass
    rec = {"url": url, "locator": url,
           "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(MAX_BYTES)
            status = r.status
            charset = r.headers.get_content_charset() or "utf-8"
        text = _extract(raw.decode(charset, errors="replace"))
        if text.strip():
            rec.update({"status": "ok", "http_status": status, "text_len": len(text),
                        "snippet": text[:SNIPPET_MAX], "main_text": text[:MAX_CACHE_TEXT]})
        else:
            rec.update({"status": "empty", "http_status": status, "text_len": 0, "snippet": "",
                        "error": f"HTTP {status} 但无可抽正文（JS壳/反爬/空页）"})
    except urllib.error.HTTPError as e:
        rec.update({"status": "error", "http_status": e.code,
                    "error": f"HTTPError {e.code}", "snippet": "", "text_len": 0})
    except Exception as e:
        rec.update({"status": "error", "error": f"{type(e).__name__}: {e}",
                    "snippet": "", "text_len": 0})
    if rec.get("status") == "ok":
        cp.parent.mkdir(parents=True, exist_ok=True)
        tmp = cp.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, cp)
    return rec


def select_targets(cards, n):
    """按(关注,时机)排序选 top N 有url的非B卡（B卡无新闻url）。返回卡引用列表。"""
    eligible = [c for c in cards if c.get("urls") and c.get("entry") != "B"]
    eligible.sort(key=lambda c: (-ATT_RANK.get(c["attention"], 0),
                                 -TIME_RANK.get(c["dims"]["时机与供给"]["level"], 0)))
    return eligible[:n]