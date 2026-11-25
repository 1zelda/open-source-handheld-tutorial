# -*- coding: utf-8 -*-
"""选题闸门：只测最有名、大家玩得多的作品。

用户口径（2026-11-22）：「只测试最出名的游戏，大家玩的多的，不要再测试一些冷门作品了。」
规则同时写进根目录说明书《选题规则_只测热门作品_2026-11-22.md》和本模块，实跑只能走这里。

档位（名单文件 popular_titles.json 是唯一权威，本模块不内置任何标题）：
  T1  该平台维基百科畅销表里有 >=1,000,000 的实数行 —— 行上写了 demote 的照样不算（销量买不到门票）。
  T2  中文怀旧/合集层点名过的作品，或 T1 系列的正传编号续作（初代与 2/3/4 这种）。
  其余一律 off_list：既没销量行，也没中文层点名，就不占测试格。

匹配口径：只做「规范化后精确相等」，绝不用子串。子串会把 ROM hack / 同人 / 改版
（Rockman Claw、Kaizo Mario World、Super Metroid: Kaizo Edition、I Wanna Be the Guy）
当成正作放行。规范化=全角转半角 + 小写 + 去变音符 + 标点折叠。

两把键防误合：Dragon Quest III 与 Dragon Quest I & II 去掉标点会撞成 dragonquestiii，
所以先按「保留词边界」的 word 键匹配，只在没有歧义时才退回 tight 键（吃 R.C. Pro-Am / RC Pro-Am
这类差别）。撞车的 tight 键自动作废，宁可漏判也不能错判成另一部作品。

拦点：control.plan() 出 title_off_popularity_list（可用 --allow 降级成 warning，产物里留痕）。
选景点：matrix.famous_playthrough_cells()、local_bootstrap 的 FCEUX 转换与名作通关两条循环。
"""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIST_PATH = HERE / "popular_titles.json"
ROM_FIELD_ORDER = ("game", "title", "name")
# control.window_spec 会把「— 只看 x..y 帧」这段观察说明拼在 game 后面。它是本机代码
# 自己写的固定标记，不是标题的一部分；闸门先把这层剥掉，否则每个窗口任务的标题都变成
# 「Super Mario Bros. — 只看 0..100 帧」，白名单再全也匹配不上，整条窗口链会被误杀。
WINDOW_NOTE = " — 只看 "


def spec_title(spec):
    """从 spec 里取用于判定热门与否的作品名（game/title/name 三选一，按此顺序）。"""
    for field in ROM_FIELD_ORDER:
        value = str(spec.get(field) or "").strip()
        if value:
            return value
    return ""


def title_candidates(spec):
    raw = spec_title(spec)
    if not raw:
        return []
    if raw.startswith(WINDOW_NOTE.strip()) or raw == WINDOW_NOTE.strip():
        # 「— 只看 …」被拼在了一个本来没名字的 game 上：这不是冷门，是 spec 没写名字
        return []
    cut = raw.split(WINDOW_NOTE, 1)[0].strip()
    return [raw] if cut == raw else [raw, cut]


def norm(value):
    """全角->半角、小写、去变音符；标点先换成空格。"""
    s = unicodedata.normalize("NFKC", str(value or "")).casefold()
    for a, b in (("ō", "o"), ("ū", "u"), ("ī", "i"), ("ē", "e"), ("ā", "a"), ("ü", "u"),
                 ("é", "e"), ("è", "e"), ("á", "a"), ("ñ", "n"), ("ǔ", "u"), ("ǎ", "a"),
                 ("’", " "), ("‘", " "), ("“", " "), ("”", " ")):
        s = s.replace(a, b)
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def keys(value):
    """返回 (word 键, tight 键)；tight 键把空格也去掉，用来吃标点差异。"""
    w = norm(value)
    return w, w.replace(" ", "")


_STATE = {"path": None, "mtime": None, "data": None, "word": {}, "tight": {}, "ambiguous": set()}


def load(force=False):
    """读名单文件；文件变了自动重载。缺失/损坏不抛给调用方，交给 gate_blocker 报闸门。

    索引按平台分格：NES 的《Super Mario World》不许顶掉 SNES 那一行，反之也一样。
    """
    if not LIST_PATH.is_file():
        if force:
            raise SystemExit(f"名单缺失：{LIST_PATH}")
        return None
    mtime = LIST_PATH.stat().st_mtime_ns
    if not force and _STATE["data"] is not None and _STATE["path"] == str(LIST_PATH) and _STATE["mtime"] == mtime:
        return _STATE["data"]
    data = json.loads(LIST_PATH.read_text(encoding="utf-8"))
    word, tight, seen_t, seen_w = {}, {}, {}, {}
    for row in data.get("rows", []):
        plat = (row.get("platform") or "").upper()
        for name in [row.get("title", "")] + list(row.get("aliases", []) or []):
            wk, tk = keys(name)
            if not wk:
                continue
            word.setdefault((plat, wk), row)
            tight.setdefault((plat, tk), row)
            # 记录「同一个键背后有几个不同作品」。撞车就整个键作废（宁漏不错认），
            # 典型例子：Dragon Quest I & II 与 Dragon Quest III 去掉空格后同名。
            seen_t.setdefault((plat, tk), set()).add(row["title"])
            seen_w.setdefault((plat, wk), set()).add(row["title"])
    ambiguous = ({k for k, titles in seen_t.items() if len(titles) > 1}
                 | {k for k, titles in seen_w.items() if len(titles) > 1})
    _STATE.update(path=str(LIST_PATH), mtime=mtime, data=data, word=word, tight=tight, ambiguous=ambiguous)
    return data


def list_version():
    data = load()
    if not data:
        return "名单缺失"
    rows = data["rows"]
    usable = sum(1 for r in rows if not r.get("demote") and not r.get("under_review"))
    held = sum(1 for r in rows if r.get("under_review"))
    return f"{data.get('version', '?')}（{len(rows)} 行 / 可用 {usable} 行 / 待核 {held} 行）"


def classify(game, platform):
    """给一个标题+平台，判它在名单上的位置。平台不在 platforms_gated 内 -> gate=False（不归本闸门管）。"""
    data = load()
    plat = (platform or "").upper()
    gated = bool(data) and plat in [p.upper() for p in data.get("platforms_gated", [])]
    out = {"game": (game or "").strip(), "platform": plat, "list_governed": gated,
           "on_list": False, "tier": None, "title": None, "sales": None, "cn": "",
           "basis": "", "demote": "", "under_review": ""}
    if not data:
        out["reason"] = "popularity_list_missing"
        return out
    if not gated:
        out["reason"] = "该平台不归选题闸门管（由 driver_platform_unproven 拦）"
        return out
    if not out["game"]:
        out["reason"] = "popularity_game_field_missing"
        return out
    row = None
    wk, tk = keys(out["game"])
    if (plat, wk) not in _STATE["ambiguous"]:
        row = _STATE["word"].get((plat, wk))
    if row is None and (plat, tk) not in _STATE["ambiguous"]:
        row = _STATE["tight"].get((plat, tk))
    if row is None:
        if (plat, wk) in _STATE["ambiguous"] or (plat, tk) in _STATE["ambiguous"]:
            out["reason"] = ("名单里有两个作品归一化后撞上同一个键（例：Dragon Quest I & II / Dragon Quest III），"
                             "闸门拒绝猜测，宁漏不错认")
        else:
            out["reason"] = "既没有 >=100万 的销量行，也没有中文层点名或 T1 系列正传续作身份"
        return out
    out.update(title=row.get("title"), sales=row.get("sales"), cn=row.get("cn", ""),
               basis=row.get("basis", ""), demote=row.get("demote", ""),
               under_review=row.get("under_review", ""))
    if row.get("demote"):
        out["reason"] = row["demote"]
        return out
    if row.get("under_review"):
        out["reason"] = (f"身份待核，核实前不占测试格：{row['under_review']}")
        return out
    out["on_list"] = True
    out["tier"] = row.get("tier")
    out["reason"] = f"{row.get('tier')}：{row.get('basis', '')}"
    return out


def is_famous(game, platform):
    return classify(game, platform)["on_list"]


def classify_spec(spec):
    """按 spec 判定：先拿原样标题，撞不上再把窗口说明剥掉重试。

    只要任一种写法命中名单就算命中；全没命中时返回「剥掉窗口说明」那一版的结果，
    这样拦下来的理由里挂的是干净标题，不是「X — 只看 0..100 帧」。
    """
    plat = (spec.get("platform") or "").upper()
    cands = title_candidates(spec)
    if not cands:
        return classify("", plat)
    results = [classify(c, plat) for c in cands]
    for res in results:
        if res["on_list"] or res["reason"] in ("popularity_list_missing",):
            return res
    return results[-1]


def gate_blocker(spec):
    """给一份 spec（normalized 后的配置），要拦就返回 blocker dict，不拦返回 None。"""
    data = load()
    plat = (spec.get("platform") or "").upper()
    if not data:
        return {"code": "popularity_list_missing",
                "reason": f"选题名单文件读不到（{LIST_PATH.name}），闸门宁可不跑也不放冷门过去"}
    if plat not in [p.upper() for p in data.get("platforms_gated", [])]:
        return None
    info = classify_spec(spec)
    if info["on_list"]:
        return None
    if info["reason"] == "popularity_game_field_missing":
        return {"code": "popularity_game_field_missing",
                "reason": f"平台 {plat} 的 spec 没写 game，闸门无法判断热不热门（名单 {list_version()}）"}
    game = info["game"] or "(空标题)"
    return {"code": "title_off_popularity_list",
            "reason": f"《{game}》不在热门名单（{list_version()}）。"
                      f"判定：{info['reason']}。"
                      f"确要跑这部冷门就加 --allow title_off_popularity_list，产物 plan.json 会留下这条降级记录"}


# ---------------------------------------------------------------------------
# 盘点
# ---------------------------------------------------------------------------
def _library_titles(lib=None):
    """从 registry.json 的 assessments 直接取 (platform, game, status)，不整盘扫 ROM。"""
    root = Path(lib) if lib else HERE.parent.parent / "04-游戏资源库" / "TAS输入录像库"
    f = root / "registry.json"
    if not f.is_file():
        raise SystemExit(f"读不到台账：{f}")
    data = json.loads(f.read_text(encoding="utf-8"))
    rows = data.get("assessments", data if isinstance(data, list) else [])
    out = []
    for r in rows:
        plat = (r.get("platform_code") or r.get("platform") or "").upper()
        game = r.get("game") or r.get("title") or ""
        if plat and game:
            out.append({"platform": plat, "game": game, "status": r.get("status", ""), "id": r.get("id", "")})
    return out


def audit(lib=None, replayable_only=True):
    """台账 vs 名单：命中多少、拦掉多少、名单里哪些行在本库连名字都没出现过。

    命中判定全部走 classify()（和出片闸门同一条路径），不在这里另写一套匹配逻辑。
    空行反查扫全部台账标题（含 blocked），只有“本库压根没这条名字”才算空行。
    """
    load()
    titles = _library_titles(lib)
    gated = [p.upper() for p in (_STATE["data"] or {}).get("platforms_gated", [])]
    scoped = [t for t in titles if t["platform"] in gated]
    resolved = set()
    for t in scoped:
        info = classify(t["game"], t["platform"])
        if info.get("title"):
            resolved.add((t["platform"], info["title"]))
    scope = [t for t in scoped if t["status"] == "replayable"] if replayable_only else scoped
    hits, misses = [], []
    for t in scope:
        info = classify(t["game"], t["platform"])
        rec = {"id": t["id"], "platform": t["platform"], "game": t["game"], "tier": info["tier"],
               "sales": info["sales"], "title": info["title"],
               "why": "" if info["on_list"] else info["reason"]}
        (hits if info["on_list"] else misses).append(rec)
    unused = [{"platform": r["platform"], "title": r["title"], "tier": r["tier"], "sales": r["sales"],
               "demote": bool(r.get("demote"))}
              for r in _STATE["data"]["rows"] if not r.get("demote")
              and (r["platform"], r["title"]) not in resolved]
    per_plat = {}
    for t in hits:
        per_plat.setdefault(t["platform"], {"T1": 0, "T2": 0})[t["tier"]] += 1
    return {"list_version": list_version(), "gated_platforms": gated,
            "library_rows_scanned": len(scope), "library_titles_in_scope": len(scoped),
            "on_list": len(hits), "off_list": len(misses),
            "tier_by_platform": per_plat, "off_list_sample": misses[:20],
            "list_rows_without_local_rom": unused, "hits": hits}


def report():
    data = load(force=True)
    if not data:
        raise SystemExit(f"名单缺失：{LIST_PATH}")
    rows = data["rows"]
    live = [r for r in rows if not r.get("demote")]
    print(f"选题名单 {data.get('version')}  规则：{data.get('rule')}")
    for plat in sorted({r["platform"] for r in rows}):
        sub = [r for r in live if r["platform"] == plat]
        usable = [r for r in sub if not r.get("under_review")]
        dem = [r for r in rows if r["platform"] == plat and r.get("demote")]
        print(f"\n[{plat}] 可用 {len(usable)} 行（T1 {sum(1 for r in usable if r['tier']=='T1')} / "
              f"T2 {sum(1 for r in usable if r['tier']=='T2')}），"
              f"待核 {len(sub)-len(usable)} 行，另降级 {len(dem)} 行")
        for r in sorted(sub, key=lambda x: (x["tier"], -(x["sales"] or 0))):
            cn = f"《{r['cn']}》" if r.get("cn") else ""
            sales = format(r["sales"], ",") if r.get("sales") else "—"
            flag = "（待核）" if r.get("under_review") else ""
            print(f"  {r['tier']}  {sales:>11} | {r['title']}{cn}{flag}")
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(description="选题闸门：只测热门作品")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report", help="打印名单（按平台分档）")
    a = sub.add_parser("audit", help="对照本地台账，报命中/未命中/名单空行")
    a.add_argument("--lib", default=None)
    a.add_argument("--all", action="store_true", help="含 blocked 条目（默认只看 replayable）")
    a.add_argument("--json", action="store_true")
    c = sub.add_parser("check", help="判一个标题在不在名单上")
    c.add_argument("game")
    c.add_argument("--platform", default="NES")
    args = ap.parse_args(argv)
    if args.cmd == "report":
        report()
        return 0
    if args.cmd == "audit":
        rep = audit(args.lib, replayable_only=not args.all)
        if args.json:
            print(json.dumps(rep, ensure_ascii=False, indent=1))
        else:
            print(f"名单 {rep['list_version']} | 管辖平台 {rep['gated_platforms']} | "
                  f"台账条目 {rep['library_rows_scanned']} -> 命中 {rep['on_list']} / 未命中 {rep['off_list']}")
            print(f"分档：{json.dumps(rep['tier_by_platform'], ensure_ascii=False)}")
            print(f"名单里有、本地库没有的行：{len(rep['list_rows_without_local_rom'])}")
            for r in rep["list_rows_without_local_rom"][:40]:
                print(f"    {r['platform']:5s} {r['tier']} {r['title']}")
            print("未命中样例：")
            for r in rep["off_list_sample"]:
                print(f"    {r['platform']:5s} #{r['id']} {r['game']}  —— {r['why'][:70]}")
        return 0
    info = classify(args.game, args.platform)
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0 if info["on_list"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
