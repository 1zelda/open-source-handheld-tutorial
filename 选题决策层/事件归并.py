# -*- coding: utf-8 -*-
"""事件归并：规范化URL为主键，同标题跨源再并；不同 release tag 不并。
转载≠独立证据：独立来源数按 source_id 去重计，且卡上注明转载性质。"""
import hashlib
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_TRACK = re.compile(r"^(utm_|fbclid$|gclid$|spm$|ref$|from$|share_)")
_PUNCT = re.compile(r"[^0-9a-z一-鿿]+")


def norm_url(u):
    u = (u or "").strip()
    if not u:
        return ""
    try:
        s = urlsplit(u)
    except ValueError:
        return u.lower()
    host = (s.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = s.path.rstrip("/")
    q = [(k, v) for k, v in parse_qsl(s.query) if not _TRACK.match(k)]
    return urlunsplit((s.scheme.lower(), host, path, urlencode(sorted(q)), ""))


def norm_title(t):
    return _PUNCT.sub("", (t or "").lower())


def _parse_pub(s):
    try:
        return datetime.strptime((s or "")[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_seen(s):
    try:
        return datetime.strptime((s or "")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def merge_events(rows):
    groups = {}
    for r in rows:
        nu = norm_url(r.get("url"))
        nt = norm_title(r.get("title"))
        key = nu or ("T:" + nt + "|" + (r.get("pub") or "")[:10])
        groups.setdefault(key, []).append(r)
    # 同标题跨源再并（标题太短不并，防 "Update" 这类泛标题误吞）
    by_title = {}
    for key, items in list(groups.items()):
        nt = norm_title(items[0].get("title"))
        if len(nt) >= 8:
            if nt in by_title:
                groups[by_title[nt]].extend(items)
                del groups[key]
                continue
            by_title[nt] = key
    events = []
    for key, items in groups.items():
        seen = [d for d in (_parse_seen(r.get("first_seen_utc")) for r in items) if d]
        pubs = [d for d in (_parse_pub(r.get("pub")) for r in items) if d]
        srcs = sorted({r.get("source_id") or r.get("source") or "?" for r in items})
        focus = sorted({t for r in items for t in (r.get("flag_focus") or "").split("+") if t})
        events.append({
            "event_id": hashlib.sha1(key.encode("utf-8")).hexdigest()[:16],
            "key": key,
            "items": items,
            "titles": sorted({r.get("title") or "" for r in items}),
            "urls": sorted({r.get("url") or "" for r in items if r.get("url")}),
            "sources": srcs,
            "source_count": len(srcs),
            "item_count": len(items),
            "kinds": sorted({r.get("kind") or "" for r in items}),
            "first_seen": min(seen).strftime("%Y-%m-%dT%H:%M:%SZ") if seen else "",
            "pub_latest": max(pubs).strftime("%Y-%m-%d") if pubs else "",
            "flag_hot_any": any((r.get("flag_hot") or "") == "HOT" for r in items),
            "focus": focus,
            "evidence_note": "独立来源按source_id去重计；跨源转载不等于独立证据",
        })
    events.sort(key=lambda e: e["first_seen"], reverse=True)
    return events