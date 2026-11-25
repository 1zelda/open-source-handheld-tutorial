# -*- coding: utf-8 -*-
"""本地文献知识库自检闸门（清洗/切块/分词/身份分区/三态检索/索引同步 + 恒量反证格）。

运行（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.kb_selftest_gates           # 独立跑
  py -3 -u -m taspipe.kb_selftest_gates --inject  # 幂等挂载进 selftest.py

探针隔离：kb.KB_DIR/CORPUS_MAP/INDEX_JSON 与 sources.REG_JSON/LEDGER_JSON 全部 patch 进临时目录，
走 kb.py / sources.py 的生产函数（不复制逻辑）；跑完反查真实索引与主数据 mtime+sha256 未被写。
"""
import argparse
import copy
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

from . import sources_selftest_gates as _G
from .sources_selftest_gates import _ok, _raises, _sha, _src, _check

PATCHED_KB = ("KB_DIR", "CORPUS_MAP", "INDEX_JSON")
PATCHED_S = ("REG_JSON", "LEDGER_JSON")


def run_kb_gates(ok_fn=None, raises_fn=None):
    from . import kb as K
    from . import kb_route as KR
    from . import sources as S
    start = _G.PASS

    def ok(cond, msg):
        return _ok(cond, msg, ok_fn)

    def raises(fn, msg):
        return _raises(fn, msg, raises_fn, ok_fn)

    real = [K.INDEX_JSON, K.CORPUS_MAP, S.REG_JSON, S.LEDGER_JSON]
    before = {str(p): (p.stat().st_mtime_ns, _sha(p)) if p.is_file() else None for p in real}
    old_k = {k: getattr(K, k) for k in PATCHED_KB}
    old_s = {k: getattr(S, k) for k in PATCHED_S}
    old_pipeline = K.PIPELINE
    try:
        with tempfile.TemporaryDirectory(prefix="kb_gates_") as tmp:
            td = Path(tmp)
            corpus = td / "corpus"
            corpus.mkdir()
            K.KB_DIR = td
            K.CORPUS_MAP = td / "corpus_map.json"
            K.INDEX_JSON = td / "index.json"
            S.REG_JSON = td / "sources.json"
            S.LEDGER_JSON = td / "检索台账.json"

            manual = corpus / "manual.md"
            manual.write_text(
                "# 说明书夹具\n\n"
                "*   [首页](https://x.example/)\n"
                "var foo = 1;\n"
                "| | | | |\n\n"
                "燕返只在小辫子（赖常）身上出现，其他角色不会。\n"
                "持球跳 A+B 到最高点按 B 就是必杀射门。\n\n"
                "## 难度\n\n"
                "やさしい 容易难度下敌我都不能发动必杀射门。\n", encoding="utf-8")
            ours = corpus / "ours.md"
            ours.write_text(
                "# 我方汇总\n\n"
                "## 发动规则（S1）\n"
                "秘技输入是 A×3 B×1。\n\n"
                "## 本机实测\n"
                "我方实测：燕返 触发窗在最高点，球权必须先解决。$3F6 是事件脉冲不是坐标。\n",
                encoding="utf-8")
            um = corpus / "um_moves.md"
            um.write_text("玛丽 俱乐部飞标 ↓↘→+B或D\n真正反击 ↓↙←+A或C\n垂直之箭 →↓↘+B或D\n",
                          encoding="utf-8")
            table = corpus / "hack_table.md"
            table.write_text("".join(f"kof98hh{i:02d} 拳皇98 改版第{i}号\n" for i in range(30)),
                             encoding="utf-8")
            mobile = corpus / "mobile.md"
            mobile.write_text("手游《热血足球》：积攒奥义槽，满奥义后跳+射即可放出终结射门。\n",
                              encoding="utf-8")
            code = corpus / "tool.py"
            code.write_text("print('identity')\n", encoding="utf-8")
            extra = corpus / "extra.md"
            extra.write_text("这份正文存在但只作二手线索，没有权威结论。\n", encoding="utf-8")
            eck = corpus / "eck_notes.md"
            eck.write_text("我方实测：↓↘→ 指令在 ECK 卡上成立，或 用简化连招版。\n", encoding="utf-8")
            nes = corpus / "game.nes"
            nes.write_bytes(b"NES\x1a" + b"\x00" * 64)

            reg = {"schema_version": 1, "sources": [
                _src("s_manual", "official_manual", "verified_read", ["NES"], ["说明书", "攻略"],
                     games_hit=["testgame"], evidence=[str(manual)]),
                _src("s_ours", "local_docs", "verified_read", ["NES"], ["必杀宏", "攻略"],
                     games_hit=["testgame"], evidence=[str(ours)]),
                _src("s_um", "cn_arcade", "verified_read", ["ARCADE"], ["出招表"],
                     games_hit=["kof98"], evidence=[str(um)]),
                _src("s_table", "cn_arcade_hack", "verified_read", ["ARCADE"], ["版本对照"],
                     games_hit=["kof98"], evidence=[str(table)]),
                _src("s_mobile", "cn_console", "verified_read", ["MOBILE"], ["攻略"],
                     games_hit=["testmobile"], evidence=[str(mobile)]),
                _src("s_code", "local_emu", "verified_read", ["ANY"], ["身份"],
                     evidence=[str(code)]),
                _src("s_extra", "cn_community", "verified_read", ["NES"], ["攻略"],
                     games_hit=["testgame"], evidence=[str(extra)]),
                _src("s_eck", "local_docs", "verified_read", ["ARCADE"], ["出招表"],
                     games_hit=["kof98"], evidence=[str(eck)]),
                _src("s_snap", "cn_community", "snippet_only", ["NES"], ["攻略"]),
            ]}
            S.save_registry(reg, path=S.REG_JSON)

            def entry(p, sid, rev, kind, auth, **kw):
                return {"path": str(p), "source_id": sid, "revision": rev,
                        "kind": kind, "authority": auth, **kw}

            m = {"schema_version": 1,
                 "revisions": {
                     "tg_jp": {"game_id": "testgame", "platform": "NES", "name": "夹具日版"},
                     "tg_multi": {"game_id": "testgame", "platform": "NES", "name": "夹具我方实测"},
                     "kof98um": {"game_id": "kof98", "platform": "ARCADE", "name": "夹具UM"},
                     "kof98eck": {"game_id": "kof98", "platform": "ARCADE", "name": "夹具ECK"},
                     "arcade_multi": {"game_id": "multi", "platform": "ARCADE", "name": "夹具总表"},
                     "mobile_rev": {"game_id": "testmobile", "platform": "MOBILE", "name": "夹具手游"},
                     "tooling": {"game_id": "multi", "platform": "ANY", "name": "夹具代码"},
                 },
                 "entries": [
                     entry(manual, "s_manual", "tg_jp", "prose", "authoritative"),
                     entry(ours, "s_ours", "tg_multi", "prose", "authoritative",
                           citations={"S1": str(extra)}),
                     entry(um, "s_um", "kof98um", "prose", "cross_version"),
                     entry(table, "s_table", "arcade_multi", "table", "reference_only"),
                     entry(mobile, "s_mobile", "mobile_rev", "prose", "not_applicable"),
                     entry(extra, "s_extra", "tg_jp", "prose", "reference_only"),
                     entry(eck, "s_eck", "kof98eck", "prose", "authoritative"),
                     entry(code, "s_code", "tooling", "code", "authoritative",
                           index=False, reason="代码不是文献正文"),
                 ]}

            def write_map(mm, name="corpus_map.json"):
                p = td / name
                p.write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")
                return p

            mp = write_map(m)
            K.CORPUS_MAP = mp

            # ---------- 清洗与切块 ----------
            lines, dropped = K.clean(manual.read_text(encoding="utf-8"))
            kept_text = "\n".join(t for _, t in lines)
            ok(dropped >= 3 and "燕返只在小辫子" in kept_text,
               "知识库 [1] 清洗丢导航/JS/空表格行且保留正文（丢弃计数可见）")
            ok("[首页]" not in kept_text and "var foo" not in kept_text,
               "知识库 [2] 反证格：纯链接行与 JS 行不得进正文")
            ok("| | |" not in kept_text,
               "知识库 [3] 反证格：空表格行（| | |）不得当正文切进索引")
            short_lines, _ = K.clean("燕返\n登录\n")
            ok(any(t == "燕返" for _, t in short_lines)
               and not any(t == "登录" for _, t in short_lines),
               "知识库 [4] 反证格：短正文词（燕返）保留、导航词（登录）丢弃——不许过度清洗")
            cs = K.chunk_prose(lines)
            ok(cs and cs[0]["line_start"] >= 1 and cs[0]["line_end"] >= cs[0]["line_start"],
               "知识库 [5] prose 切块带原文行号（可回指 path#L）")
            ok(any(c["heading"] == "难度" for c in cs),
               "知识库 [6] 标题进 heading 字段（检索结果能报小节）")
            tc = K.chunk_table(K.clean(table.read_text(encoding="utf-8"))[0])
            ok(len(tc) == 2 and tc[0]["text"].count("\n") == K.ROWS_PER_CHUNK - 1,
               f"知识库 [7] table 按 {K.ROWS_PER_CHUNK} 行切（30 行 => 2 块）")
            long_lines = [(1, "字" * (K.HARD_MAX + 50))]
            ok(len(K.chunk_prose(long_lines)) >= 2,
               "知识库 [8] 反证格：超长段按 HARD_MAX 强制断块（不产出巨块）")

            # ---------- 分词 ----------
            tk = set(K.tokens("燕返 kof98eck $3F6 00AA BD18 ↓↘→+A或C"))
            tk2 = set(K.tokens("燕返触发窗"))
            ok("燕返" in tk and "燕返触发窗" in tk2 and "触发" in tk2 and "燕返" in tk2,
               "知识库 [9] 中文长串整词 + 全部 bigram 成词（燕返/触发 都能命中）")
            ok("kof98eck" in tk, "知识库 [10] ASCII 标识符小写成词（set 名可命中）")
            ok("$3f6" in tk and "00aa" in tk and "bd18" in tk,
               "知识库 [11] 十六进制/RAM 地址成词（$3F6 / 00AA / BD18）")
            ok("↓↘→" in tk and "↓↘→" not in set(K.tokens("普通正文没有指令")),
               "知识库 [12] 反证格：箭头指令序列成词，无箭头文本不产生箭头 token")

            # ---------- 语料 schema ----------
            ok(K.load_map(mp)["entries"], "知识库 [13] corpus_map 通过 schema")
            raises(lambda: K.load_map(write_map({**m, "野字段": 1}, "bad1.json")),
                   "知识库 [14] 反证格：corpus_map 未知字段 => SchemaError")
            bad = copy.deepcopy(m)
            bad["entries"][0]["revision"] = "不存在的版本"
            raises(lambda: K.load_map(write_map(bad, "bad2.json")),
                   "知识库 [15] 反证格：revision 未定义 => SchemaError")
            bad = copy.deepcopy(m)
            bad["entries"][0]["authority"] = "我说了算"
            raises(lambda: K.load_map(write_map(bad, "bad3.json")),
                   "知识库 [16] 反证格：authority 非法 => SchemaError")
            bad = copy.deepcopy(m)
            bad["entries"][0]["kind"] = "视频"
            raises(lambda: K.load_map(write_map(bad, "bad4.json")),
                   "知识库 [17] 反证格：kind 非法 => SchemaError")
            bad = copy.deepcopy(m)
            bad["entries"][-1].pop("reason")
            raises(lambda: K.load_map(write_map(bad, "bad5.json")),
                   "知识库 [18] 反证格：排除索引不给 reason => SchemaError（不许静默跳过）")
            bad = copy.deepcopy(m)
            bad["entries"].append(copy.deepcopy(bad["entries"][0]))
            raises(lambda: K.load_map(write_map(bad, "bad6.json")),
                   "知识库 [19] 反证格：同一份正文登记两次 => SchemaError")
            bad = copy.deepcopy(m)
            bad["revisions"]["tg_jp"]["platform"] = "FC2"
            raises(lambda: K.load_map(write_map(bad, "bad7.json")),
                   "知识库 [20] 反证格：平台不在 PLATFORMS => SchemaError")
            good = copy.deepcopy(m)
            ok(K.load_map(write_map(good, "citations_ok.json"))["entries"],
               "知识库 [20a] 引用别名指向已登记正文时通过 schema")
            bad = copy.deepcopy(m)
            next(e for e in bad["entries"] if e["path"] == str(ours))["citations"]["S1"] = "missing.md"
            raises(lambda: K.load_map(write_map(bad, "bad_citation_target.json")),
                   "知识库 [20b] 引用别名指向未登记正文 => SchemaError，禁止静默洗白")
            bad = copy.deepcopy(m)
            next(e for e in bad["entries"] if e["path"] == str(ours))["citations"]["S1"] = str(ours)
            raises(lambda: K.load_map(write_map(bad, "bad_citation_self.json")),
                   "知识库 [20c] 引用别名不得指向自身来源")

            # ---------- 构建与增量 ----------
            r = K.build(map_path=mp, index_path=K.INDEX_JSON, reg=reg)
            ok(r["chunks"] > 0 and r["files_indexed"] == 7 and r["files_excluded"] == 1,
               "知识库 [21] build 产出块且区分入索引/显式排除（7 入 1 排除）")
            idx = K.load_index(K.INDEX_JSON)
            ok(not any(c["path"] == str(code) for c in idx["chunks"])
               and idx["files"][str(code)]["indexed"] is False
               and idx["files"][str(code)]["reason"],
               "知识库 [22] 反证格：声明排除的正文不得偷偷进索引，且理由留档")
            r2 = K.build(map_path=mp, index_path=K.INDEX_JSON, reg=reg)
            ok(all(f.get("reused") for f in r2["report"] if f["indexed"]),
               "知识库 [23] 增量：源文件未变 => 全部复用（不重复切块）")
            ours_bytes = ours.read_bytes()
            ours.write_bytes(ours_bytes + "追加一行实测。\n".encode("utf-8"))
            r3 = K.build(map_path=mp, index_path=K.INDEX_JSON, reg=reg)
            row = next(x for x in r3["report"] if x["path"] == str(ours))
            ok(row["reused"] is False,
               "知识库 [24] 反证格：源文件 sha256 变了 => 不复用旧块")
            ours.write_bytes(ours_bytes)
            K.build(map_path=mp, index_path=K.INDEX_JSON, reg=reg)
            K.PIPELINE = "clean999|tok999"
            r4 = K.build(map_path=mp, index_path=K.INDEX_JSON, reg=reg)
            ok(all(not f.get("reused") for f in r4["report"] if f["indexed"]),
               "知识库 [25] 反证格：清洗/分词流水线版本变了 => 强制重建（旧块不许冒充新口径）")
            K.PIPELINE = old_pipeline
            K.build(map_path=mp, index_path=K.INDEX_JSON, reg=reg)
            idx = K.load_index(K.INDEX_JSON)
            ok(all(c.get("source_id") and c.get("revision") and c.get("status")
                   and c.get("authority") and c.get("text_sha") for c in idx["chunks"]),
               "知识库 [26] 每块都带 source_id/revision/status/authority/text_sha（可溯源可验篡改）")
            ok(not list(td.glob("*.tmp")),
               "知识库 [27] 索引原子写：不留 .tmp 残件")
            ok(max(len(c["text"]) for c in idx["chunks"]) <= K.HARD_MAX,
               f"知识库 [27b] 产物级：全库无巨块（最长块 ≤ HARD_MAX {K.HARD_MAX}）")
            bad = copy.deepcopy(m)
            bad["entries"][0]["source_id"] = "ghost_sid"
            raises(lambda: K.build(map_path=write_map(bad, "bad8.json"),
                                   index_path=td / "bad8.index.json", reg=reg),
                   "知识库 [28] 反证格：语料绑定野 source_id => build 拒（先 ingest 再入库）")

            # ---------- 检索三态与身份门 ----------
            q = K.query("燕返 最高点 必杀", revision="tg_jp", index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "pass" and q["counts"]["strong"] >= 1,
               "知识库 [29] verified_read + authoritative 命中 => pass")
            ok(any(h["revision"] == "tg_multi" and h["revision_match"] for h in q["hits"]),
               "知识库 [30] 我方跨版本实测件（*_multi）对同游戏任一版本算本版本证据")
            q = K.query("拳皇98 改版", revision="arcade_multi", index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "inconclusive" and q["hits"],
               "知识库 [31] 三态门：只有二手件命中 => inconclusive（不是 pass 也不是 miss）")
            q = K.query("俱乐部飞标", revision="kof98eck", index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "inconclusive" and q["authority_warnings"]
               and q["hits"][0]["authority"] == "cross_version"
               and q["hits"][0]["revision"] == "kof98um",
               "知识库 [32] 反证格：跨版本出招表不得当本地卡权威（ECK 问 UM 表 => inconclusive + 警告）")
            q = K.query("俱乐部飞标 ↓↘→", revision="kof98um", index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "pass",
               "知识库 [33] 同一份表问它自己的版本（UM）=> pass（版本对了才是权威）")
            q = K.query("或", revision="kof98eck", index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "inconclusive" and q["hits"],
               "知识库 [33b] 反证格：权威件确有命中但只匹配单字（或）=> 不算证据，不得升 pass")
            q = K.query("俱乐部飞标 ↓↘→+B或D", revision="kof98eck",
                        index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "pass" and q.get("condition") and q["counts"]["strong"] >= 1
               and q["hits"][0]["authority"] == "cross_version" and q["authority_warnings"],
               "知识库 [33c] top3 附条件（P1 批准口径）：本版本权威可答件在第2位 => pass 必带 condition，"
               "最高分仍是跨版本表且警告保留")
            q = K.query("俱乐部飞标 ↓↘→+B或D", revision="kof98um",
                        index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "pass" and q["hits"][0]["revision"] == "kof98um"
               and "condition" not in q,
               "知识库 [33d] 正对照：同一查询问 UM，最高分即本版本权威 => pass 且不带条件")
            q = K.query("奥义槽 终结射门", platform="NES", index_path=K.INDEX_JSON, map_path=mp)
            ok(all(h["game_id"] != "testmobile" for h in q["hits"]),
               "知识库 [34] 反证格：手游正文不得混进 NES 查询（平台分区生效）")
            q = K.query("随便什么", game="no_such_game", index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "miss" and q["counts"]["candidates"] == 0,
               "知识库 [35] 无候选 => miss（本地没收集，不等于『不存在』）")
            q = K.query("zzzzqqqq", game="testgame", index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "miss" and q["counts"]["candidates"] > 0,
               "知识库 [36] 有候选但无词命中 => miss（并提示换术语/走延伸段）")
            q = K.query("拳皇98 改版", revision="arcade_multi", require_verified=True,
                        index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "inconclusive",
               "知识库 [37] 反证格：require_verified 下无权威命中不得放行")
            raises(lambda: K.query("  ", index_path=K.INDEX_JSON, map_path=mp),
                   "知识库 [38] 空查询 => SchemaError（别空检索）")
            raises(lambda: K.query("燕返", revision="不存在的版本",
                                   index_path=K.INDEX_JSON, map_path=mp),
                   "知识库 [39] 反证格：未定义 revision => SchemaError（不许静默当全库检索）")

            # ---------- P1 接线：v3 日文小段 / 域路由 / 可答性 / top3 窗口 / 检索路径明示 ----------
            ok(K.kana_ratio("完全中文没有假名") == 0.0
               and K.kana_ratio("あいうえお漢字") == 5 / 7,
               "知识库 [53] kana 占比函数：纯中文=0、5假名2汉字=5/7（阈值判据可复算）")
            ja = corpus / "ja_manual.md"
            ja.write_text("＜ゲームモード説明＞\n"
                          "これはサッカーのゲームです。モードをえらんでください。\n"
                          "* * *\n"
                          "＜たいりょくについて＞\n"
                          "たいりょくは選手のスタミナです。"
                          + "走り続けるとたいりょくが減っていきます。" * 20 + "\n",
                          encoding="utf-8")
            sha1fact = corpus / "sha1_fact.md"
            sha1fact.write_text("我方实测：热血足球联盟卡带 ROM 的 SHA1 校验和是 "
                                "0123456789abcdef0123456789abcdef01234567。\n", encoding="utf-8")
            decoys = []
            for i in range(3):
                d = corpus / f"decoy{i}.md"
                d.write_text("暗号词 暗号词 暗号词 暗号词 暗号词\n", encoding="utf-8")
                decoys.append(d)
            realfile = corpus / "real.md"
            realfile.write_text("这是一段很长的背景正文，用来把目标词压到长块低分位。" * 12
                                + "暗号词只在末尾出现一次。\n", encoding="utf-8")
            jap = corpus / "ja_params.md"
            jap.write_text("＜パラメータ一覧＞\n"
                           "たいりょく\n\n強いシュートが打てる。\n\n"
                           "しゅーと・りょく\n\nシュートの威力。\n\n"
                           "ぼうぎょ・りょく\n\n防御する力。\n"
                           "* * *\n"
                           "＜ながいパラメータ＞\n" + "あ" * 200 + "\n\n" + "い" * 200 + "\n",
                           encoding="utf-8")
            reg_ja = copy.deepcopy(reg)
            reg_ja["sources"] += [
                _src("s_ja", "official_manual", "verified_read", ["NES"], ["说明书"],
                     games_hit=["testgame"], evidence=[str(ja)]),
                _src("s_sha", "local_docs", "verified_read", ["NES"], ["身份"],
                     games_hit=["testgame"], evidence=[str(sha1fact)]),
                _src("s_decoy", "cn_community", "verified_read", ["NES"], ["攻略"],
                     games_hit=["testgame"], evidence=[str(d) for d in decoys]),
                _src("s_real", "local_docs", "verified_read", ["NES"], ["攻略"],
                     games_hit=["testgame"], evidence=[str(realfile)]),
                _src("s_jap", "official_manual", "verified_read", ["NES"], ["说明书"],
                     games_hit=["testgame"], evidence=[str(jap)]),
            ]
            m_ja = copy.deepcopy(m)
            m_ja["entries"] += [
                entry(ja, "s_ja", "tg_jp", "prose", "authoritative"),
                entry(jap, "s_jap", "tg_jp", "prose", "authoritative"),
                entry(sha1fact, "s_sha", "tg_jp", "prose", "authoritative"),
                entry(realfile, "s_real", "tg_jp", "prose", "authoritative"),
            ] + [entry(d, "s_decoy", "tg_jp", "prose", "reference_only") for d in decoys]
            mpja = write_map(m_ja, "ja_map.json")
            ij = td / "ja.index.json"
            K.build(map_path=mpja, index_path=ij, reg=reg_ja)
            idxja = K.load_index(ij)
            jach = [c for c in idxja["chunks"] if c["path"] == str(ja)]
            ok(len(jach) >= 3 and all(c["lang"] == "ja" for c in jach),
               "知识库 [54] v3 切块：kana 主导件按章节切成小段且标 lang=ja（不是 700 字大块）")
            ok(all(c["text"].startswith("＜")
                   and len(c["text"][len(c["heading"]) + 1:]) <= K.JA_BODY_MAX
                   for c in jach if c["heading"]),
               "知识库 [55] v3 切块：章节标题前置进块文本，正文 ≤300 字")
            ok(all(c.get("lang") == "zh" for c in idxja["chunks"] if c["path"] == str(manual)),
               "知识库 [56] 反证格：中文主导件（夹少量日文词）不重切，仍走原切块标 zh")
            q = K.query("2025年MSI季中冠军赛冠军是哪支战队", index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "miss" and q.get("refusal") == "out_of_scope"
               and q["route"]["domain"] == "esports_lol",
               "知识库 [57] 域外零语料 => miss+out_of_scope（不许拿本地足球语料冒充电竞答案）")
            q = K.query("原神纳西妲圣遗物搭配推荐", index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "miss" and q.get("refusal") == "out_of_scope"
               and q["route"]["domain"] == "modern_games",
               "知识库 [58] 第二个域外语料同样拒答（路由不是只认一个域）")
            q = K.query("2025年MSI季中冠军赛冠军是哪支战队", revision="tg_jp",
                        index_path=K.INDEX_JSON, map_path=mp)
            ok(q.get("refusal") != "out_of_scope" and q["route"]["domain"] == "esports_lol",
               "知识库 [59] 反证格：显式 revision 过滤优先于域限制（用户点名查本地不误拒）")
            q = K.query("燕返 指纹 SHA1 是多少", game="testgame",
                        index_path=K.INDEX_JSON, map_path=mp)
            ok(q["status"] == "inconclusive" and q.get("refusal") == "unanswerable" and q["hits"],
               "知识库 [60] 可答性：词命中但库内无 40 位 hex => 证据不足拒答（词命中≠回答问题）")
            q = K.query("燕返 指纹 SHA1 是多少", game="testgame", index_path=ij, map_path=mpja)
            ok(q["status"] == "pass"
               and any(re.search(r"[0-9a-f]{40}", h["snippet"]) for h in q["hits"]),
               "知识库 [61] 正对照：同一问法、库里真有 SHA1 事实 => pass（拒答不是摆烂）")
            ok(K.annotate("热血联赛一共多少场比赛", "本作是6人制足球，每队6人。",
                          K.tokens)["answerable"] is False,
               "知识库 [62] 反证格：问场数不许拿『6人制』串答（量词映射）")
            ok(K.annotate("热血联赛一共多少场比赛", "リーグモードは全部で３６試合あります。",
                          K.tokens)["answerable"] is True
               and K.annotate("热血联赛一共多少场比赛", "联赛模式一共36场比赛。",
                              K.tokens)["answerable"] is True,
               "知识库 [63] 跨语量词映射：日文『試合』与中文『场』都能答场数")
            ok(K.annotate("加速需要多少帧？", "Rockman 2 accelerates for 7 frames.", K.tokens)["answerable"] is True
               and K.annotate("减速需要多少帧？", "Rockman 2 decelerates for 8 (decimal) frames.", K.tokens)["answerable"] is True
               and K.annotate("加速需要多少帧？", "加速需要 7 条。", K.tokens)["answerable"] is False,
               "知识库 [63b] 帧数量词映射：多少帧只接受帧/frames（含十进制括注），不许条/场串答")
            ok(KR.classify_intent("步行速度是多少？") == "value_lookup"
               and K.annotate("步行速度是多少？", "In Rockman 2, during walking, Rockman’s X speed is 01.60.", K.tokens)["answerable"] is True
               and K.annotate("步行速度是多少？", "步行速度是 7 条。", K.tokens)["answerable"] is False,
               "知识库 [63c] 速度取值意图：速度多少按数值取值而非数数，答案必须含十六进制速度/坐标值")
            q = K.query("暗号词", game="testgame", revision="tg_jp", index_path=ij, map_path=mpja)
            ok(q["status"] == "inconclusive" and "top3" in q["reason"]
               and q["counts"]["strong"] >= 1,
               "知识库 [64] 反证格：权威可答件被压到第4位（top3 外）=> 仍 inconclusive（附条件不是无底线）")
            q = K.query("燕返 最高点 必杀", revision="tg_jp", index_path=K.INDEX_JSON, map_path=mp)
            ok(q.get("retrieval") == "bm25_only" and q.get("retrieval_note"),
               "知识库 [65] 无稠密指纹件 => 明示退回 BM25 主干（不静默顶包）")
            import numpy as np
            fake_npz = K.INDEX_JSON.with_name(
                f"embeddings_{_sha(K.INDEX_JSON)[:12]}.npz")
            np.savez(fake_npz, vecs=np.zeros((1, 4)), index_sha=np.array("deadbeef"))
            q = K.query("燕返 最高点 必杀", revision="tg_jp", index_path=K.INDEX_JSON, map_path=mp)
            ok(q.get("retrieval") == "bm25_only" and "不一致" in q.get("retrieval_note", ""),
               "知识库 [66] 反证格：稠密指纹与索引漂移 => 不用稠密且明示原因（不加载模型）")
            fake_npz.unlink()

            # ---------- P2：假名成词 / 全角归一 / 真贪心打包 / 跨语扩展 / 日文形态关 / top 窗口 ----------
            ts = K.tokens("＜ステータスについて＞\nたいりょく")
            ok("たいりょく" in ts and "ステ" in ts
               and "ステータスについて" not in ts
               and "ステータス" in K.tokens("ステータス"),
               "知识库 [67] 假名串成词：短串整词+bigram、长串只 bigram（与汉字同待遇，纯假名块不再 dl=0）")
            ok("2p" in K.tokens("２Ｐ") and K.tokens("２Ｐ") == K.tokens("2p")
               and "1p" in K.tokens("1p") and K.tokens("２Ｐ") != K.tokens("1p"),
               "知识库 [68] 全角字母数字归一：２Ｐ/2p 都产出完整2p词元，且1p可区分")
            ok("2p" not in K.tokens("2") and "1p" not in K.tokens("1")
               and "2p" not in K.tokens("2 p") and "2p" not in K.tokens("20p"),
               "知识库 [68b] 词元反证：纯数字、分隔书写和其他编号不得伪造2p/1p词元")
            jpch = [c for c in idxja["chunks"] if c["path"] == str(jap)]
            ok(any("たいりょく" in c["text"] and "ぼうぎょ・りょく" in c["text"] for c in jpch),
               "知识库 [69] 真贪心打包：短参数段合并进同一块（首尾参数同块，不再散落零分小块）")
            ok(not any("あ" * 200 in c["text"] and "い" * 200 in c["text"] for c in jpch)
               and all(len(c["text"][len(c["heading"]) + 1:]) <= K.JA_BODY_MAX
                       for c in jpch if c["heading"]),
               "知识库 [70] 反证格：两段合计超 300 不得合并，块正文仍 ≤300（贪心不是无上限塞块）")
            expset = KR.expand_terms("双人合作模式下二号玩家操作什么位置？", K.tokens)
            ok(set(K.tokens("協力")) <= expset and set(K.tokens("モード")) <= expset
               and set(K.tokens("ポジション")) <= expset
               and "2p" in expset and "1p" not in expset,
               "知识库 [71] 跨语扩展：中文触发词追加日文表层形式，并保留完整2p玩家编号")
            _exp1 = KR.expand_terms("一号玩家操作什么位置？", K.tokens)
            ok("1p" in _exp1 and "2p" not in _exp1
               and "2p" not in KR.expand_terms("只有两名球员", K.tokens),
               "知识库 [71b] 玩家编号反证：一号只扩1p，数量两名不得冒充玩家编号")
            _q6terms = set(K.tokens("热血足球联盟每队上场几名球员？")) | KR.expand_terms(
                "热血足球联盟每队上场几名球员？", K.tokens)
            _score6, _mode6, _removed6 = K._score_query_terms(
                "热血足球联盟每队上场几名球员？", _q6terms, False)
            _q8text = "双人合作模式下二号玩家操作什么位置？"
            _q8terms = set(K.tokens(_q8text)) | KR.expand_terms(_q8text, K.tokens)
            _score8, _mode8, _removed8 = K._score_query_terms(_q8text, _q8terms, False)
            _plain = "足球比赛怎么进行？"
            ok(_mode6 == "team_size" and "足球" in _removed6
               and {"サッカー", "選手", "上场"} <= _score6
               and _mode8 == "player_role" and {"2p", "協力"} <= _score8
               and "ポジション" not in _score8 and "模式" not in _score8
               and K._score_query_terms(
                   _plain, set(K.tokens(_plain)) | KR.expand_terms(_plain, K.tokens),
                   False)[1] is None,
               "知识库 [71c] 窄打分反证：人数/玩家分工去掉标题与框架词并保留跨语核心，普通问句不改打分")
            _q10text = "KOF98 ECK 能不能关掉队友改成 1v1？"
            _q10terms = set(K.tokens(_q10text)) | KR.expand_terms(_q10text, K.tokens)
            _score10, _mode10, _removed10 = K._score_query_terms(_q10text, _q10terms, True)
            ok(_mode10 == "team_battle" and {"kof98", "eck", "1v1"} <= set(_removed10)
               and "队友" in _score10
               and "サッカー" not in KR.expand_terms(
                   "热血足球联盟一共有多少种必杀射门？", K.tokens),
               "知识库 [71d] 标题词反证：1v1队战问句保留队友语义、去掉身份词；球队人数扩展不污染其他足球问句")
            ok(KR.expand_terms("俱乐部飞标 ↓↘→+B或D", K.tokens) == set()
               and KR.expand_terms("燕返 最高点 必杀", K.tokens) == set(),
               "知识库 [72] 反证格：无触发词的问句不扩展（不往查询里掺无关日文词）")
            ok(K.annotate("PK战模式怎么玩？",
                          "ＰＫ戦プレイ出場６チームの中から、チームをセレクトしたら、ＰＫ戦だけの対戦開始！",
                          K.tokens)["answerable"] is True,
               "知识库 [73] 日文 howto 形态关：セレクト/プレイ/開始 是操作证据（P22/P23 类不再误杀）")
            ok(K.annotate("PK战模式怎么玩？", "ＰＫ戦は面白いモードです。",
                          K.tokens)["answerable"] is False,
               "知识库 [74] 反证格：日文块没有任何操作形态词 => 仍不可答（形态关不是见日文就放）")
            q = K.query("暗号词", game="testgame", revision="tg_jp", index_path=ij,
                        map_path=mpja, top_window=5)
            ok(q["status"] == "pass" and "第4位" in q.get("condition", ""),
               "知识库 [75] top_window 旋钮：显式 5 让第4位权威件附条件出证（默认仍是 [64] 的 top3）")
            q = K.query("合作 模式", game="testgame", index_path=K.INDEX_JSON, map_path=mp)
            ok(q.get("query_expansion") and "協力" in q["query_expansion"],
               "知识库 [76] 扩展透明：query 结果带 query_expansion 字段（走了哪些日文词可查）")
            q3 = K.query("暗号词", game="testgame", revision="tg_jp", index_path=ij, map_path=mpja)
            q5 = K.query("暗号词", game="testgame", revision="tg_jp", index_path=ij,
                         map_path=mpja, top_window=5)
            passed5 = next(h for h in q5["hits"][:5]
                           if h["authority"] == "authoritative"
                           and h["answerability"]["answerable"])
            ok(q3["status"] == "inconclusive" and q5["status"] == "pass"
               and "第4位" in q5.get("condition", "")
               and "背景正文" in passed5["snippet"],
               "知识库 [77] 反证格：window5 会放行只沾话题词的长背景权威块（假阳性机制）"
               "⇒ 默认必须守 top3（2026-11-19 探针 3/4 翻转假阳性，用户授权实测后否决转默认）")

            # ---------- P3：来源清单结构关 + 中文块话题锚（堵窗口探针假阳性根因） ----------
            a = K.annotate("怎么换人？", "换人操作按键说明：https://a.example/x 与 "
                           "https://b.example/y 两条来源见上。", K.tokens)
            ok(a["answerable"] is False and a["url_list"] is True,
               "知识库 [78] 结构关：≥2 网址的块是来源清单不是答案正文 => 不可答"
               "（W14/W27 假阳性根因，形态词再像答案也拦）")
            a = K.annotate("怎么换人？", "换人操作按键说明：等候室作战会议换到MF，"
                           "详见 https://a.example/x 。", K.tokens)
            ok(a["answerable"] is True and a["url_list"] is False,
               "知识库 [79] 正对照：单网址不触发结构关（正文带一条出处链接不算来源清单）")
            a = K.annotate("一直输球会怎么样？", "必杀测量方法学：真阳性一定存在，"
                           "责任在测量方式不在 ROM，触发链按三条铁律重跑。", K.tokens)
            ok(a["answerable"] is False and a["topic_anchor_ok"] is False,
               "知识库 [80] 话题锚：中文 howto 块只沾泛话题词（必杀/触发）无焦点重叠"
               " => 不可答（W11 假阳性根因）")
            a = K.annotate("一直输球会怎么样？", "一直输球到底：全踢败后游戏卡住，"
                           "无法对战也无法退出，按键全失效。", K.tokens)
            ok(a["answerable"] is True and a["topic_anchor_ok"] is True,
               "知识库 [81] 正对照：同一问句、块真讲输球后果 => 可答（话题锚不是见 howto 就杀）")
            a = K.annotate("PK战模式怎么玩？",
                           "ＰＫ戦プレイ出場６チームの中から、チームをセレクトしたら、"
                           "ＰＫ戦だけの対戦開始！", K.tokens, lang="ja")
            ok(a["answerable"] is True,
               "知识库 [82] 日文块豁免话题锚：中文焦点词天然不重叠，跨语块仍由形态关把关"
               "（P22 类不误杀；lang=ja 显式传入）")

            # ---------- P4：词法锚（BM25 top1 保最终 top8 席位，治重排推翻主干） ----------
            from . import kb_dense as KD
            ranked = list(range(10, 19))  # 重排前9，BM25 top1=99 被挤出 top8
            top = KD.anchor_top8(ranked, [99, 10, 11])
            ok(len(top) == KD.TOPK and top[0] == 10 and top[-1] == 99
               and top.count(99) == 1 and 18 not in top,
               "知识库 [83] 词法锚：重排把 BM25 top1 挤出 top8 => 锚回第8席，"
               "top1 仍是重排选择、不重复占位（Q10 机制：gold BM25第1/重排第11）")
            ranked8 = list(range(8))
            ok(KD.anchor_top8(ranked8, [3, 0, 1]) == ranked8
               and KD.anchor_top8(ranked8, []) == ranked8
               and KD.anchor_top8([], []) == [],
               "知识库 [84] 反证格：BM25 top1 已在榜内/无 BM25 候选 => 原样返回"
               "（锚不是无条件加塞，空榜不造块）")

            # ---------- P5：可答性事实层（量词串答/属性焦点/域泛词停用，堵 w3 假阳性） ----------
            a = K.annotate("应援曲一共有几首？", "胜利姿势全 11 条，名称已知仍仅 3。", K.tokens)
            ok(a["answerable"] is False and a["intent"] == "count",
               "知识库 [85] 量词串答：问『几首』块答『11 条』(胜利姿势) => 不可答"
               "（X06 假阳性根因，count 量词须匹配『首』）")
            a = K.annotate("应援曲一共有几首？", "应援曲一共 8 首，逐队列出。", K.tokens)
            ok(a["answerable"] is True,
               "知识库 [86] 正对照：块真含『8 首』=> 可答（量词关不是见 count 就杀）")
            a = K.annotate("海月是什么射门？", "海月=Kaizuki，属性表体/射/防/走力型。", K.tokens)
            ok(a["answerable"] is False and a["pattern_ok"] is False,
               "知识库 [87] 属性焦点：问『X是什么射门』块只命中主语海月、缺『射门』=> 不可答"
               "（X07 假阳性根因）")
            a = K.annotate("海月是什么射门？", "海月的土佐鲣射门：球变鱼上下游动抛物线。", K.tokens)
            ok(a["answerable"] is True and a["pattern_ok"] is True,
               "知识库 [88] 正对照：块真讲射门种类 => 可答（属性焦点不是见射门问句就杀）")
            a = K.annotate("球员受伤了怎么治疗？", "必杀测量方法学：球员坐标按三条铁律重跑。", K.tokens)
            ok(a["answerable"] is False and a["topic_anchor_ok"] is False,
               "知识库 [89] 域泛词停用：howto 块只命中域泛词『球员』(已停用)、缺主语『治疗/受伤』"
               " => 不可答（X25 w3 假阳性根因）")
            a = K.annotate("球员受伤了怎么治疗？", "治疗选项：按键恢复体力。", K.tokens)
            ok(a["answerable"] is True and a["topic_anchor_ok"] is True,
               "知识库 [90] 正对照+反证 R3：块只 1 个焦点命中『治疗』仍可答 => 可答"
               "（证明未实施『≥2 焦点命中』一刀切——那会误杀同义换述真答案，模拟已否）")
            ok("球员" in KR.FOCUS_STOP and "射门" in KR.FOCUS_STOP
               and "eck" not in KR.FOCUS_STOP and "kof98" not in KR.FOCUS_STOP,
               "知识库 [91] 反证格：域泛词球员/射门已停用，但 KOF 域标识词 eck/kof98 不停用"
               "（全量停用版误杀 W18 八神庵连招被数据否决，p5_fix_sim_c3_out.txt）")

            # ---------- P6：yesno 焦点闸门 + 射门影响形态关 ----------
            a = K.annotate("打雷会不会把门将击倒？",
                           "控室里可以制定作战，也可以罚任意球。", K.tokens)
            ok(a["answerable"] is False and a["intent"] == "yesno"
               and a["intent_ok"] is True and a["focus_ok"] is False,
               "知识库 [92] yesno 焦点闸门：块含『可以』(YESNO_RE 命中)但不讲打雷/击倒/门将"
               " => 不可答（X16 假阳性根因：对照控室段冒充答案）")
            a = K.annotate("打雷会不会把门将击倒？",
                           "闪电有时会把门将击倒，不能忽视天气注意报。", K.tokens)
            ok(a["answerable"] is True and a["focus_ok"] is True,
               "知识库 [93] 正对照：块真讲打雷击倒门将+含『不能』=> 可答"
               "（yesno 焦点闸门不是见 yesno 就杀，有焦点重叠即放行）")
            a = K.annotate("雨天场地对射门有什么影响？",
                           "各国各有天气，雨天场地状况差要小心，影响团队配合。", K.tokens)
            ok(a["answerable"] is False and a["pattern_ok"] is False,
               "知识库 [94] 射门影响形态关：块含雨天/场地/影响但无『射门』=> 不可答"
               "（X26 假阳性根因：对照控室段沾天气词但不答射门影响）")
            a = K.annotate("雨天场地对射门有什么影响？",
                           "雨天场地湿滑，射门精度下降，球速变慢。", K.tokens)
            ok(a["answerable"] is True and a["pattern_ok"] is True,
               "知识库 [95] 正对照：块真讲射门+雨天影响 => 可答"
               "（射门影响形态关不是见影响问句就杀）")

            # ---------- P7：yesno 隐性肯定形态（专用必杀技） ----------
            a = K.annotate("守门员能不能用必杀？",
                           "守门员专用必杀技为龙卷风拳，各选手持有该技才能发出。", K.tokens)
            ok(a["answerable"] is True and a["intent_ok"] is True,
               "知识库 [96] yesno 隐性肯定：真答案『守门员专用必杀技为龙卷风拳』不含显性是非词"
               " => 专用必杀技 命中 YESNO_RE 判可答（W03 真答案根因：旧校验器把隐性肯定挡在门外）")
            a = K.annotate("守门员能不能用必杀？",
                           "2P 双人合作游玩时，2P 操作 GK（守门员）角色，守门员是左右胜负的重要位置。",
                           K.tokens)
            ok(a["answerable"] is False and a["intent_ok"] is False and a["focus_ok"] is True,
               "知识库 [97] 反证格：规则块讲守门员(焦点重叠)但不讲必杀、无是非词 => 不可答"
               "（W03 证据错机制：沾守门员冒充答案，intent_ok=False 挡住）")
            a = K.annotate("守门员能不能用必杀？",
                           "守门员才能发出必杀技，需要持有该技。", K.tokens)
            ok(a["answerable"] is False and a["intent_ok"] is False and a["focus_ok"] is True,
               "知识库 [98] 反证格：才能/持有 泛词未收进 YESNO_RE（即使焦点重叠仍 intent_ok=False）"
               "（模拟证 才能 会让 X16 球员数据块冒充答案引 2 假阳，E4 被否，p7_yesno_sim_out.txt）")
            a = K.annotate("守门员能不能用必杀？",
                           "守门员可以用必杀技，但需要持有该技。", K.tokens)
            ok(a["answerable"] is True and a["intent_ok"] is True,
               "知识库 [99] 正对照：既有显性是非词『可以』仍生效 => 可答"
               "（P7 只补隐性肯定形态，不废原有 YESNO_RE 词）")

            # ---------- 审计 ----------
            a = K.audit(map_path=mp, index_path=K.INDEX_JSON, reg=reg)
            ok(_check(a, "map_schema") == "pass" and _check(a, "evidence_coverage") == "pass"
               and _check(a, "source_binding") == "pass" and _check(a, "identity_conflict") == "pass"
               and _check(a, "index_sync") == "pass" and _check(a, "chunk_provenance") == "pass",
               "知识库 [40] 基线：覆盖/归属/身份/索引同步/溯源六门全绿")
            ok(_check(a, "authoritative_ready") == "inconclusive",
               "知识库 [41] 三态门：只有二手/跨版本正文的版本 => authoritative_ready inconclusive")
            bad = copy.deepcopy(m)
            bad["entries"] = [e for e in bad["entries"] if e["path"] != str(extra)]
            next(e for e in bad["entries"] if e["path"] == str(ours))["citations"] = {}
            a = K.audit(map_path=write_map(bad, "bad9.json"), index_path=K.INDEX_JSON, reg=reg)
            ok(_check(a, "evidence_coverage") == "fail",
               "知识库 [42] 反证格：verified_read 的取证正文未进 corpus_map => 覆盖门红（收而不入库＝白收）")
            bad = copy.deepcopy(m)
            bad["entries"].append(entry(extra, "s_manual", "tg_jp", "prose", "reference_only"))
            bad["entries"] = [e for e in bad["entries"]
                              if not (e["path"] == str(extra) and e["source_id"] == "s_extra")]
            a = K.audit(map_path=write_map(bad, "bad10.json"), index_path=K.INDEX_JSON, reg=reg)
            ok(_check(a, "source_binding") == "fail",
               "知识库 [43] 反证格：正文挂到别的来源名下（不在其 evidence 列表）=> 归属门红")
            bad = copy.deepcopy(m)
            bad["entries"][0]["source_id"] = "not_in_reg"
            a = K.audit(map_path=write_map(bad, "bad11.json"), index_path=K.INDEX_JSON, reg=reg)
            ok(_check(a, "source_binding") == "fail",
               "知识库 [44] 反证格：野 source_id => 归属门红")
            bad = copy.deepcopy(m)
            next(e for e in bad["entries"] if e["path"] == str(mobile))["revision"] = "tg_jp"
            a = K.audit(map_path=write_map(bad, "bad12.json"), index_path=K.INDEX_JSON, reg=reg)
            ok(_check(a, "identity_conflict") == "fail",
               "知识库 [45] 反证格：手游正文被判成 FC 版本（与 games_hit 冲突）=> 身份门红")
            tam = json.loads(K.INDEX_JSON.read_text(encoding="utf-8"))
            tam["chunks"][0]["text"] += "（手改篡改）"
            tamp = td / "tampered.json"
            tamp.write_text(json.dumps(tam, ensure_ascii=False), encoding="utf-8")
            a = K.audit(map_path=mp, index_path=tamp, reg=reg)
            ok(_check(a, "index_sync") == "fail",
               "知识库 [46] 反证格：手改索引块正文 => text_sha 不符判红")
            stale_reg = copy.deepcopy(reg)
            next(s for s in stale_reg["sources"] if s["source_id"] == "s_manual")["status"] = "snippet_only"
            a = K.audit(map_path=mp, index_path=K.INDEX_JSON, reg=stale_reg)
            ok(_check(a, "chunk_provenance") == "fail",
               "知识库 [47] 反证格：来源已降级但索引块仍写 verified_read => 溯源门红")
            manual_bytes = manual.read_bytes()
            manual.write_bytes(manual_bytes + "源文件改了但没重建。\n".encode("utf-8"))
            a = K.audit(map_path=mp, index_path=K.INDEX_JSON, reg=reg)
            ok(_check(a, "index_sync") == "fail",
               "知识库 [48] 反证格：源文件变了索引没重建 => 同步门红")
            manual.write_bytes(manual_bytes)
            K.build(map_path=mp, index_path=K.INDEX_JSON, reg=reg)
            a = K.audit(map_path=mp, index_path=td / "missing.json", reg=reg)
            ok(_check(a, "index_sync") == "inconclusive",
               "知识库 [49] 三态门：索引未建 => inconclusive（不假装核对过）")
            changed_citations = copy.deepcopy(m)
            next(e for e in changed_citations["entries"]
                 if e["path"] == str(ours))["citations"]["S1"] = str(manual)
            changed_mp = write_map(changed_citations, "changed_citations.json")
            a = K.audit(map_path=changed_mp, index_path=K.INDEX_JSON, reg=reg)
            ok(_check(a, "index_sync") == "fail" and _check(a, "chunk_provenance") == "fail",
               "知识库 [49a] 引用别名主数据变而索引未重建 => 同步门与溯源门双红")
            _qr = K.query("秘技输入是什么？", game="testgame", topk=30,
                          fragment_policy="strict", map_path=changed_mp, reg=reg)
            _ours_hit = next(h for h in _qr["hits"] if h["locator"].startswith(str(ours)))
            ok(_ours_hit["fragment_provenance"]["eligible"],
               "知识库 [49b] 查询时按当前 corpus_map 重绑别名，旧索引不绕过新来源资格")
            _old_citation_sha = K.load_index(K.INDEX_JSON)["files"][str(ours)]["citation_sha256"]
            r_alias = K.build(map_path=changed_mp, index_path=K.INDEX_JSON, reg=reg)
            _ours_row = next(f for f in r_alias["report"] if f["path"] == str(ours))
            ok(_ours_row["reused"] and K.load_index(K.INDEX_JSON)["files"][str(ours)]
               ["citation_sha256"] != _old_citation_sha,
               "知识库 [49c] 仅引用绑定变化时复用正文切块并刷新引用指纹")
            K.build(map_path=mp, index_path=K.INDEX_JSON, reg=reg)

            # ---------- 接进 sources.route ----------
            plan = S.route("testgame", "攻略", platform="NES", rom=str(nes))
            ok(plan["status"] == "ready" and plan["kb"]["chunks"] > 0
               and "知识库" in plan["steps"][1],
               "知识库 [50] route 第②步先查本地正文，并回报库内块数与 query 命令")
            saved_index = K.INDEX_JSON
            K.INDEX_JSON = td / "no_index.json"
            plan = S.route("testgame", "攻略", platform="NES", rom=str(nes))
            ok(plan["kb"]["status"] == "not_built" and plan["counts"]["kb_chunks"] == 0,
               "知识库 [51] 反证格：索引不存在 => route 如实报 not_built（不假装有正文）")
            K.INDEX_JSON = saved_index
            plan = S.route("testgame", "攻略")
            ok(plan["status"] == "blocked",
               "知识库 [52] 反证格：身份未定仍 blocked（知识库接线不得放宽身份门）")

            # ---------- P10：hybrid-only 双索引 + 域内 IDF（兜底臂构造零回归） ----------
            zh = corpus / "zh_contrast.md"
            zh.write_text("编者中文对照：燕返仅小辫子原生持有，其他角色不会。\n",
                          encoding="utf-8")
            reg_h = copy.deepcopy(reg)
            reg_h["sources"] += [
                _src("s_zh", "official_manual", "verified_read", ["NES"], ["说明书"],
                     games_hit=["testgame"], evidence=[str(zh)])]
            m_h = copy.deepcopy(m)
            m_h["entries"].append(entry(zh, "s_zh", "tg_jp", "prose", "authoritative",
                                        index=False, reason="中文对照撤回 base 索引（#23）",
                                        hybrid_only=True))
            mph = write_map(m_h, "hyb_map.json")
            ok(K.load_map(mph)["entries"][-1]["hybrid_only"] is True,
               "知识库 [108] hybrid_only 件通过 schema（index:false + hybrid_only:true 合法）")
            bad = copy.deepcopy(m_h)
            bad["entries"][-1]["hybrid_only"] = "yes"
            raises(lambda: K.load_map(write_map(bad, "bad_h1.json")),
                   "知识库 [109] 反证格：hybrid_only 非布尔 => SchemaError")
            bad = copy.deepcopy(m_h)
            bad["entries"][-1]["index"] = True
            bad["entries"][-1].pop("reason")
            raises(lambda: K.load_map(write_map(bad, "bad_h2.json")),
                   "知识库 [110] 反证格：hybrid_only 挂 index:true 件 => SchemaError（只能挂 index:false）")
            ih_base = td / "hyb_base.index.json"
            K.build(map_path=mph, index_path=ih_base, reg=reg_h)
            idxb = K.load_index(ih_base)
            ok(not any(c["path"] == str(zh) for c in idxb["chunks"])
               and idxb["files"][str(zh)]["indexed"] is False,
               "知识库 [111] base build 排除 hybrid_only 件（bm25 兜底零回归的构造保证）")
            ih_hyb = td / "index_hybrid.json"
            K.build(map_path=mph, index_path=ih_hyb, reg=reg_h, hybrid=True)
            idxh = K.load_index(ih_hyb)
            ok(any(c["path"] == str(zh) for c in idxh["chunks"])
               and idxh["files"][str(zh)]["indexed"] is True,
               "知识库 [112] hybrid build 收录 hybrid_only 对照件（富集索引独有）")
            base_sha = {c["text_sha"] for c in idxb["chunks"]}
            hyb_sha = {c["text_sha"] for c in idxh["chunks"]}
            ok(base_sha <= hyb_sha and len(idxh["chunks"]) > len(idxb["chunks"]),
               "知识库 [113] base ⊂ enriched：base 块全在富集索引且富集严格更多（再索引只增不改 base）")
            # 域内 IDF：同候选子池 True≠False（权重改池内统计）但召回块集不变
            cand_sub = [ci for ci, c in enumerate(idxh["chunks"]) if c["revision"] == "tg_jp"]
            qt2 = K.tokens("燕返")
            s_g, _, _ = K._bm25_scores(idxh, idxh["chunks"], cand_sub, qt2, False)
            s_l, _, _ = K._bm25_scores(idxh, idxh["chunks"], cand_sub, qt2, True)
            ok(set(s_g) == set(s_l) and s_g
               and any(abs(s_g[ci] - s_l[ci]) > 1e-6 for ci in s_g),
               "知识库 [114] 域内 IDF 隔离：同子池 True≠False（池内 N/df/avgdl）但召回块集不变")
            # 恒量反证：domain_local=False 逐块等于全局 BM25 原公式（兜底臂零改动）
            import math
            cand_full = list(range(len(idxb["chunks"])))
            qt3 = K.tokens("燕返 必杀")
            s_f, _, _ = K._bm25_scores(idxb, idxb["chunks"], cand_full, qt3, False)
            Ng = idxb["stats"]["N"]
            avgg = idxb["stats"]["avgdl"] or 1.0
            manual_s = {}
            for term in qt3:
                post = idxb["postings"].get(term)
                if not post:
                    continue
                idf = math.log(1 + (Ng - len(post) + 0.5) / (len(post) + 0.5))
                for ci, tf in post:
                    dl = idxb["chunks"][ci]["dl"] or 1
                    manual_s[ci] = manual_s.get(ci, 0.0) + idf * tf * (K.K1 + 1) / (
                        tf + K.K1 * (1 - K.B + K.B * dl / avgg))
            ok(set(s_f) == set(manual_s)
               and all(abs(s_f[ci] - v) < 1e-9 for ci, v in manual_s.items()),
               "知识库 [115] 反证：domain_local=False 逐块等于全局 BM25 原公式（兜底臂构造零改动）")
            # 自动选臂：富集件无稠密指纹 => 退回 base+全局
            sel_p, sel_dl = K._select_index(None)
            ok(sel_p == K.INDEX_JSON and sel_dl is False,
               "知识库 [116] 自动选臂：hybrid 富集件无稠密指纹 => 退回 base+全局（不静默顶包）")
            sel_p2, sel_dl2 = K._select_index(ih_hyb)
            ok(sel_p2 == ih_hyb and sel_dl2 is True,
               "知识库 [117] 显式 index_hybrid.json => 域内 IDF（尊重调用方文件名）")
            sel_p3, sel_dl3 = K._select_index(ih_base)
            ok(sel_p3 == ih_base and sel_dl3 is False,
               "知识库 [118] 反证：显式 base 索引名 => 全局 IDF（不因富集件存在误切域内）")
            # 正对照：富集件就绪 => 自动切富集+域内（patch ready 隔离重模型）
            from . import kb_dense as KD
            old_ready = KD.ready
            KD.ready = lambda p: (True, None)
            try:
                sel_p4, sel_dl4 = K._select_index(None)
                ok(sel_p4 == K.hybrid_index_path() and sel_dl4 is True,
                   "知识库 [119] 正对照：hybrid 富集件就绪 => 自动切富集索引+域内 IDF（默认检索随环境升级）")
            finally:
                KD.ready = old_ready

            # ---------- 阶段1：运行与出证契约（反例闸门 [120]+） ----------
            from unittest.mock import patch
            qpass = "燕返 最高点 必杀"
            # numpy 缺席：ready/enhance 返回原因不抛异常，兜底臂全程可走
            with patch.dict(sys.modules, {"numpy": None}):
                r_ready, why_ready = KD.ready(ih_hyb)
                ok(r_ready is False and "numpy" in why_ready,
                   "知识库 [120] 缺 numpy：ready 返回 (False,原因) 不抛（可选依赖隔离）")
                e_pick, e_dev, e_note = KD.enhance(qpass, idxh["chunks"], [0], [0], ih_hyb)
                ok(e_pick is None and e_dev is None and "numpy" in e_note,
                   "知识库 [121] 缺 numpy：enhance 返回 (None,None,原因) 不抛")
                r_np = K.query(qpass, revision="tg_jp", map_path=mph)
                ok(r_np["status"] == "pass" and r_np["retrieval"] == "bm25_only",
                   "知识库 [122] 缺 numpy 环境全链路 query 仍走 bm25 兜底并 pass")
            # 运行中降级：已选富集索引但 enhance 失败 => 完整重跑 base+全局，逐格等于冷启动 bm25
            cold = K.query(qpass, revision="tg_jp", index_path=ih_base, map_path=mph)
            with patch.object(KD, "enhance", return_value=(None, None, "模拟运行故障")):
                fb = K.query(qpass, revision="tg_jp", index_path=ih_hyb, map_path=mph)
            ok(fb["status"] == cold["status"]
               and [(h["chunk_id"], h["score"]) for h in fb["hits"]]
               == [(h["chunk_id"], h["score"]) for h in cold["hits"]]
               and fb["counts"] == cold["counts"],
               "知识库 [123] 故障注入降级与冷启动 bm25 逐格一致（status/hits/score/counts）")
            ok(fb["retrieval"] == "bm25_only"
               and fb["index_used"] == Path(K.INDEX_JSON).name
               and "scoring_note" not in fb
               and "完整退回" in fb.get("retrieval_note", ""),
               "知识库 [124] 降级身份一致：bm25_only+base 索引名+无域内注记+原因明示（不静默顶包）")
            # topk 契约：两臂同一返回数量
            r_t3 = K.query(qpass, revision="tg_jp", topk=3, index_path=ih_base, map_path=mph)
            ok(0 < len(r_t3["hits"]) <= 3,
               "知识库 [125] topk 契约 bm25 臂：topk=3 返回 ≤3")
            with patch.object(KD, "enhance",
                              side_effect=lambda q, cs, cand, bo, ip: (list(reversed(cand)), "mock", None)):
                r_h3 = K.query(qpass, revision="tg_jp", topk=3, index_path=ih_hyb, map_path=mph)
            ok(len(r_h3["hits"]) == 3 and r_h3["retrieval"] == "hybrid_union12"
               and r_h3["index_used"] == "index_hybrid.json",
               "知识库 [126] topk 契约 hybrid 臂：mock 增强全序也只返回 topk=3（两臂同契约）")
            # 出证绑定：pass 必须携带放行依据块，且在 top_window 内
            r_sel = K.query(qpass, revision="tg_jp", index_path=ih_base, map_path=mph)
            sel = r_sel.get("selected_evidence") or []
            pos = next((i for i, h in enumerate(r_sel["hits"])
                        if sel and h["chunk_id"] == sel[0]["chunk_id"]), 99)
            ok(r_sel["status"] == "pass" and len(sel) == 1 and pos < 3,
               "知识库 [127] selected_evidence：pass 恰带 1 块放行依据且位于 top_window 内")
            r_miss = K.query("zzzzqqqq", game="testgame", index_path=ih_base, map_path=mph)
            ok(r_miss["status"] == "miss" and "selected_evidence" not in r_miss,
               "知识库 [128] 反证格：miss 不出 selected_evidence（无放行不得伪造出证）")
            # 审计认识 hybrid_only：富集收录合法、base 排除合法、两边漂移都抓
            a_h = K.audit(map_path=mph, index_path=ih_hyb, reg=reg_h)
            ok(_check(a_h, "index_sync") == "pass",
               "知识库 [129] 富集索引审计：hybrid_only 合法收录不再误报漂移")
            a_b = K.audit(map_path=mph, index_path=ih_base, reg=reg_h)
            ok(_check(a_b, "index_sync") == "pass",
               "知识库 [130] base 审计：hybrid_only 排除在外仍判同步")
            th_dir = td / "t_hyb"
            th_dir.mkdir()
            idxh_t = copy.deepcopy(idxh)
            idxh_t["chunks"] = [c for c in idxh_t["chunks"] if c["path"] != str(zh)]
            (th_dir / "index_hybrid.json").write_text(
                json.dumps(idxh_t, ensure_ascii=False), encoding="utf-8")
            a_t = K.audit(map_path=mph, index_path=th_dir / "index_hybrid.json", reg=reg_h)
            ok(_check(a_t, "index_sync") == "fail",
               "知识库 [131] 反证格：富集索引丢了 hybrid_only 块 => 同步门红（不是无脑放行）")
            idxb_t = copy.deepcopy(idxb)
            idxb_t["chunks"] += [c for c in idxh["chunks"] if c["path"] == str(zh)]
            idxb_t["files"][str(zh)] = {**idxb_t["files"][str(zh)], "indexed": True}
            tb = td / "tampered_base.json"
            tb.write_text(json.dumps(idxb_t, ensure_ascii=False), encoding="utf-8")
            a_tb = K.audit(map_path=mph, index_path=tb, reg=reg_h)
            ok(_check(a_tb, "index_sync") == "fail",
               "知识库 [132] 反证格：base 误收 hybrid_only 块 => 同步门红")
            # 问句版本钉：信息层解析 + 词边界反证 + 不改过滤/打分
            ok(KR.version_hints("KOF98 ECK 这张卡 ROM 的 SHA1 指纹是多少？") == ["kof98eck"]
               and KR.version_hints("拳皇98 98UM 出招表") == ["kof98um"]
               and KR.version_hints("热血足球 燕返") == [],
               "知识库 [133] 版本钉解析：ECK/98UM 各自命中，无版本词不报")
            ok(KR.version_hints("checkeck 98umx") == [],
               "知识库 [134] 反证格：拉丁词边界（checkeck/98umx 子串不误报）")
            r_plain = K.query(qpass, revision="tg_jp", index_path=ih_base, map_path=mph)
            r_eck = K.query(qpass + " ECK", revision="tg_jp", index_path=ih_base, map_path=mph)
            ok(r_eck.get("version_hints") == ["kof98eck"]
               and r_eck["status"] == r_plain["status"]
               and [(h["chunk_id"], h["score"]) for h in r_eck["hits"]]
               == [(h["chunk_id"], h["score"]) for h in r_plain["hits"]],
               "知识库 [135] 版本钉只暴露信息：显式 revision 问句加 ECK 后 hits/score/status 逐格不变")
            # 阶段2 判分器 v2：strict_pass 绑定实际出证（评审§1.1 Q10 假 pass 反例）
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "知识库小样_20261118"))
            import eval_common as E
            _gold = {"path_contains": "规范", "line_start": 185, "line_end": 190}
            _qsp = {"id": "T1", "expect": "strict_pass", "gold": _gold}
            _hw = {"locator": "F:/x/素材生产规范.md#L18-L31", "chunk_id": "aaa"}
            _hg = {"locator": "F:/x/素材生产规范.md#L185-L190", "chunk_id": "bbb"}
            _r_q10 = {"status": "pass", "hits": [_hw, _hg], "selected_evidence": [_hw]}
            ok(E.grade(_qsp, _r_q10)["ok"] is True
               and E.grade_v2(_qsp, _r_q10)["ok"] is False
               and E.grade_v2(_qsp, _r_q10)["wrong_evidence"] is True,
               "知识库 [136] v2 反例：金标在 hits 但放行依据是无关块 => v1 过/v2 不过（Q10 型假 pass）")
            _r_ok = {"status": "pass", "hits": [_hw, _hg], "selected_evidence": [_hg]}
            ok(E.grade_v2(_qsp, _r_ok)["ok"] is True
               and E.grade_v2(_qsp, _r_ok)["correct_evidence"] is True,
               "知识库 [137] v2 正格：放行依据就是金标块 => 正确出证")
            _r_nosel = {"status": "pass", "hits": [_hg]}
            ok(E.grade_v2(_qsp, _r_nosel)["ok"] is False,
               "知识库 [138] v2 反例：pass 无 selected_evidence => 不过（契约缺失不放行）")
            _qrf = {"id": "T4", "expect": "refuse", "gold": None}
            ok(E.grade(_qrf, {"status": "miss", "hits": []})["ok"]
               and E.grade_v2(_qrf, {"status": "miss", "hits": []})["ok"]
               and not E.grade_v2(_qrf, {"status": "pass", "hits": [_hg]})["ok"]
               and E.grade_v2(_qrf, {"status": "pass", "hits": [_hg]})["wrong_evidence"],
               "知识库 [139] v2 拒答档与 v1 同口径：miss 过/pass 不过且记错误出证")
            _qvg = {"id": "T5", "expect": "version_guard", "gold": None}
            _um = {"locator": "F:/gamersky_kof98um.md#L1-L10", "chunk_id": "uuu"}
            _r_vg = {"status": "pass", "hits": [_hg, _um], "selected_evidence": [_um],
                     "authority_warnings": ["跨版本"]}
            ok(E.grade(_qvg, _r_vg)["ok"] is True and E.grade_v2(_qvg, _r_vg)["ok"] is False,
               "知识库 [140] v2 版本守卫收紧：top1 非 UM 但放行依据是 UM 块 => v2 不过")
            _qgt = {"id": "T6", "expect": "gold_in_topk", "gold": _gold}
            _g2s = [E.grade_v2(_qsp, _r_q10), E.grade_v2(_qsp, _r_ok),
                    E.grade_v2(_qrf, {"status": "miss", "hits": []}),
                    E.grade_v2(_qgt, _r_ok)]
            _s2 = E.summarize_v2(_g2s)
            ok(_s2["split_table"]["correct_evidence"] == sum(g["correct_evidence"] for g in _g2s)
               and _s2["split_table"]["wrong_evidence"] == sum(g["wrong_evidence"] for g in _g2s)
               and _s2["split_table"]["direct_recall"] == sum(g["direct_recall"] for g in _g2s)
               and E.grade(_qgt, _r_ok)["ok"] == E.grade_v2(_qgt, _r_ok)["ok"],
               "知识库 [141] v2 分表逐格计数==逐题求和；gold_in_topk 档 v1/v2 同口径")
            _r_badloc = {"status": "pass", "hits": [_hg],
                         "selected_evidence": [{"locator": "no_line_anchor", "chunk_id": "c"}]}
            ok(E.grade_v2(_qsp, _r_badloc)["citation_valid"] is False,
               "知识库 [142] v2 引用有效性反证：放行块 locator 无行号锚 => citation_valid=False")

            # ---- 自动跨域调用（用户 11-24：文章/新闻不得先手选一个知识库） ----
            _rm = KR.route_many("LOL 与 DOTA2 联动角色是谁")
            ok([x["domain"] for x in _rm] == ["esports_lol", "esports_dota"]
               and all(x["tier"] == "strong" for x in _rm),
               "知识库 [199] 自动路由：LOL+DOTA2 同时命中两域，不挑单一域")
            ok(KR.route_many("Final Fantasy checkeck Lolita")[0]["domain"] == "unrouted"
               and [x["domain"] for x in KR.route_many("LOL 赛程")] == ["esports_lol"],
               "知识库 [200] 反证格：拉丁子串不误报；强词命中时不被共享弱词拖进第二域")
            _ra = K.query_auto("LOL 与 DOTA2 联动角色是谁", topk=3,
                               index_path=ih_base, map_path=mph)
            ok(_ra["status"] == "miss" and _ra.get("refusal") == "out_of_scope"
               and _ra["auto_routing"]["mode"] == "multi"
               and [d["domain"] for d in _ra["domain_results"]] == ["esports_lol", "esports_dota"]
               and all(d["status"] == "miss" and d.get("refusal") == "out_of_scope"
                       for d in _ra["domain_results"]),
               "知识库 [201] 生产路径：LOL+DOTA2 自动查两域且都诚实报本地无料，不落全库泛搜")
            _old_rs = KR.DOMAINS["retro_soccer"]["game_ids"]
            KR.DOMAINS["retro_soccer"]["game_ids"] = ["testgame"]
            try:
                _rmu = K.query_auto("燕返 拳皇98", topk=3, index_path=ih_base, map_path=mph)
            finally:
                KR.DOMAINS["retro_soccer"]["game_ids"] = _old_rs
            ok(_rmu["auto_routing"]["mode"] == "multi"
               and [d["domain"] for d in _rmu["domain_results"]] == ["retro_soccer", "kof98"]
               and _rmu["status"] == "inconclusive"
               and _rmu.get("refusal") == "multi_domain_needs_split"
               and _rmu.get("selected_evidence") == []
               and any(d["status"] == "pass" and len(d["selected_evidence"]) == 1
                       for d in _rmu["domain_results"]),
               "知识库 [202] 多域正例：一域有权威证据也不合并成总pass；逐域证据保留且总体要求拆分")
            _logp = K.append_query_log(r_sel, caller="fixture")
            _logrows = [json.loads(x) for x in Path(_logp).read_text(encoding="utf-8").splitlines()]
            ok(Path(_logp) == K.KB_DIR / "query_log.jsonl" and len(_logrows) == 1
               and _logrows[0]["caller"] == "fixture"
               and len(_logrows[0]["selected_evidence"]) == 1
               and "text" not in _logrows[0],
               "知识库 [203] 查询留痕：动态落到探针KB目录，记出证定位不记全文（真实目录零污染）")
            _diag_rows = []
            _diag_res = K.query_auto("燕返 拳皇98", topk=3, index_path=ih_base, map_path=mph,
                                     log_sink=_diag_rows.append,
                                     log_context={"request_id": "req_multi", "entry_point": "test"})
            _log_lines_before = len(Path(_logp).read_text(encoding="utf-8").splitlines())
            K.query_auto("燕返", topk=1, index_path=ih_base, map_path=mph)
            _log_lines_after = len(Path(_logp).read_text(encoding="utf-8").splitlines())
            ok(len(_diag_rows) == 1 and _diag_rows[0]["schema_version"] == 2
               and _diag_rows[0]["api"] == "query_auto"
               and _diag_rows[0]["route_mode"] == "multi"
               and _diag_rows[0]["request_id"] == "req_multi"
               and _diag_rows[0]["call_id"] and _diag_rows[0]["elapsed_ms"] >= 0
               and [d["domain"] for d in _diag_rows[0]["domains"]] == ["retro_soccer", "kof98"]
               and _diag_res["status"] == "inconclusive"
               and all(h.get("domain") for h in _diag_rows[0]["selected_evidence"])
               and _log_lines_before == _log_lines_after,
               "知识库 [203b] 多域诊断只记外层一次：逐域状态/证据不丢，未传log_sink不写真实日志")
            ok(KR.route_many("SCS 2026年度总决赛落幕，选手MadkoF、XiaoHai分获《拳皇15》《饿狼传说：群狼之城》冠军")[0]["domain"] == "unrouted",
               "知识库 [204] 真实标题反证：拳皇15+冠军不被泛词拖成KOF98或LOL（版本未登记须诚实留空）")

            _nk_manual = corpus / "nk_manual.md"
            _nk_manual.write_text(
                "# 热血格斗传说说明书夹具\n\n"
                "角色创建需输入姓名、生日、血型、类型。个人必杀共10种，合体技共2种。\n",
                encoding="utf-8")
            _nk_faq = corpus / "nk_faq.md"
            _nk_faq.write_text(
                "二手FAQ：KT# = (出生月 + 出生日 - 1) mod 20。名字与血型的能力公式未明。\n",
                encoding="utf-8")
            _nk_revb = corpus / "nk_revb.md"
            _nk_revb.write_text(
                "DvD Rev.B：NES 4-Score/Satellite 支持第3、第4玩家，仅 Rumble 模式。\n",
                encoding="utf-8")
            _nk_reg = {"schema_version": 1, "sources": [
                _src("s_nk_manual", "official_manual", "verified_read", ["NES"], ["说明书"],
                     games_hit=["testgame"], evidence=[str(_nk_manual)]),
                _src("s_nk_faq", "cn_community", "verified_read", ["NES"], ["公式"],
                     games_hit=["testgame"], evidence=[str(_nk_faq)]),
                _src("s_nk_revb", "cn_community", "verified_read", ["NES"], ["补丁"],
                     games_hit=["testgame"], evidence=[str(_nk_revb)]),
            ]}
            _nk_map = {"schema_version": 1, "revisions": {
                "tg_jp": {"game_id": "testgame", "platform": "NES", "name": "夹具原版"},
                "tg_revb": {"game_id": "testgame", "platform": "NES", "name": "夹具Rev.B"},
            }, "entries": [
                entry(_nk_manual, "s_nk_manual", "tg_jp", "prose", "authoritative"),
                entry(_nk_faq, "s_nk_faq", "tg_jp", "prose", "reference_only"),
                entry(_nk_revb, "s_nk_revb", "tg_revb", "prose", "reference_only"),
            ]}
            _nk_mp = write_map(_nk_map, "nk_map.json")
            _nk_idx = td / "nk_index.json"
            K.build(map_path=_nk_mp, index_path=_nk_idx, reg=_nk_reg)
            _old_nk = KR.DOMAINS["retro_fighting"]["game_ids"]
            KR.DOMAINS["retro_fighting"]["game_ids"] = ["testgame"]
            try:
                _nk_ok = K.query_auto("热血格斗传说 角色创建 哪些输入",
                                      index_path=_nk_idx, map_path=_nk_mp)
                _nk_formula = K.query_auto("熱血格闘伝説 KT# 出生月 出生日 公式",
                                           index_path=_nk_idx, map_path=_nk_mp, top_window=8)
                _nk_orig = K.query_auto("热血格斗传说 Rev.B 4-Score 第3 第4玩家",
                                        revision="tg_jp", index_path=_nk_idx, map_path=_nk_mp)
                _nk_patch = K.query_auto("热血格斗传说 Rev.B 4-Score 第3 第4玩家",
                                         revision="tg_revb", index_path=_nk_idx, map_path=_nk_mp)
            finally:
                KR.DOMAINS["retro_fighting"]["game_ids"] = _old_nk
            ok(_nk_ok["status"] == "pass"
               and _nk_ok["auto_routing"]["domains"][0]["domain"] == "retro_fighting"
               and _nk_formula["status"] == "inconclusive"
               and not _nk_formula.get("selected_evidence")
               and _nk_orig["status"] == "inconclusive"
               and not _nk_orig.get("selected_evidence")
               and _nk_patch["status"] == "inconclusive"
               and not _nk_patch.get("selected_evidence")
               and any(h["revision"] == "tg_revb" and not h["revision_match"]
                       for h in _nk_orig["hits"]),
               "知识库 [205] 热血格斗传说：官方四输入可答；KT公式二手不升pass；Rev.B原版不借补丁能力且补丁自身仍非权威")
    finally:
        for k, v in old_k.items():
            setattr(K, k, v)
        for k, v in old_s.items():
            setattr(S, k, v)
        K.PIPELINE = old_pipeline

    from . import nkd_kt as NK
    _kt_jan1 = NK.candidates_for_birthday(1, 1)
    ok(_kt_jan1["candidate_kt_number"] == 1
       and _kt_jan1["candidate_moves"] == ["Stone Guard", "Spin Attack", "Bomb Kick"]
       and _kt_jan1["status"] == "reference_only"
       and _kt_jan1["rom_recomputed"] is False
       and _kt_jan1["hard_evidence_eligible"] is False
       and "selected_evidence" not in _kt_jan1,
       "知识库 [206] KT候选计算：生日公式可算且始终reference_only，不产生硬证据")
    _kt_dec31 = NK.candidates_for_birthday(12, 31)
    _kt_feb29 = NK.candidates_for_birthday(2, 29)
    ok(_kt_dec31["candidate_kt_number"] == 2
       and _kt_feb29["candidate_kt_number"] == 10
       and NK.candidates_for_birthday(1, 21)["candidate_moves"] == _kt_jan1["candidate_moves"],
       "知识库 [207] KT候选边界：12/31与闰日2/29有效，公式按20项周期循环")
    _kt_invalid = []
    for _month, _day in ((0, 1), (13, 1), (1, 0), (1, 32), (2, 30), (4, 31),
                         (True, 1), (1, False), (1.0, 1), ("1", 1)):
        try:
            NK.candidates_for_birthday(_month, _day)
            _kt_invalid.append(False)
        except ValueError:
            _kt_invalid.append(True)
    ok(len(_kt_invalid) == 10 and all(_kt_invalid),
       "知识库 [208] 反证格：非法月份/日期、布尔与字符串不得混入KT候选")

    # 阶段2 审计新检查（真实只读审计，常量已恢复）：转述继承 + 撤回段识别
    _a = K.audit()
    _inh = _check(_a, "authority_inheritance")
    _ret = next(c for c in _a["checks"] if c["check_id"] == "retraction_markers")
    _ret_txt = "\n".join(_ret["detail"])
    ok(_inh in ("pass", "inconclusive")
       and any("必杀全清单" in d and ":L230:" in d for d in _ret["detail"])
       and any("必杀全清单" in d and ":L257:" in d for d in _ret["detail"])
       and any("必杀全清单" in d and ":L65:" in d for d in _ret["detail"]),
       "知识库 [143] 审计撤回段识别：必杀全清单 L65/L230/L257 三处撤回/作废均在册")
    _inh_detail = next(c for c in _a["checks"] if c["check_id"] == "authority_inheritance")["detail"]
    ok(all(not any(x in d for x in ("1ang_", "sohu_", "csdn_", "urawaza_FC"))
           for d in _inh_detail),
       "知识库 [144] 反证格：继承检查只扫 authoritative 件（reference_only 文件不进清单）")

    # ---- 阶段一第1天（全域KB实施计划）：电竞四游戏路由 + 冻结件验收 ----
    _ES_NEW = ("esports_cs2", "esports_valorant")
    _es_pairs = [("LOL全球总决赛冠军是谁", "esports_lol"),
                 ("DOTA2 TI14 赛程", "esports_dota"),
                 ("CS2 Major 决赛结果", "esports_cs2"),
                 ("VALORANT VCT CN 冠军", "esports_valorant"),
                 ("无畏契约最新补丁改了什么", "esports_valorant"),
                 ("反恐精英2 哪支队赢了", "esports_cs2")]
    ok(all(KR.route(q)["domain"] == d for q, d in _es_pairs)
       and all(KR.route(q)["corpus_available"] is False for q, _ in _es_pairs)
       and all(KR.route(q)["tier"] == "strong" for q, _ in _es_pairs),
       "知识库 [145] 四游戏明确路由：LOL/DOTA/CS2/VAL 各归其域（强词命中），空语料 corpus_available=False")
    _rc = K.query("CS2 Major 决赛哪支队赢了")
    _rv = K.query("VALORANT VCT CN 现在冠军是谁")
    ok(_rc["status"] == "miss" and _rc.get("refusal") == "out_of_scope"
       and _rc["counts"]["candidates"] == 0
       and _rv["status"] == "miss" and _rv.get("refusal") == "out_of_scope"
       and _rv["counts"]["candidates"] == 0,
       "知识库 [146] 生产路径：CS2/VAL 问句拒答 out_of_scope，candidates=0（不落全库泛搜）")
    _qfiles = [K.ROOT.parent.parent / "知识库P1_20261118" / n
               for n in ("p2_questions_ext.json", "probe_questions.json",
                         "probe_questions_ext.json")]
    _allq = []
    for _qf in _qfiles:
        _d = json.loads(_qf.read_text(encoding="utf-8"))
        _allq += [x["q"] for x in (_d if isinstance(_d, list) else _d["questions"])]
    _saved = {n: KR.DOMAINS.pop(n) for n in _ES_NEW}
    try:
        _old_routes = [KR.route(q) for q in _allq]
    finally:
        KR.DOMAINS.update(_saved)
    ok(len(_allq) == 86
       and all(KR.route(q) == r for q, r in zip(_allq, _old_routes)),
       "知识库 [147] 恒量反证：既有 86 题（26评测+60探针）路由逐格不变（新域不抢旧问句）")
    _td_root = K.ROOT.parent.parent
    if str(_td_root) not in sys.path:
        sys.path.insert(0, str(_td_root))
    import importlib
    _KC = importlib.import_module("选题决策层.知识对照")
    _cd_now = _KC.content_domains()
    _saved2 = {n: KR.DOMAINS.pop(n) for n in _ES_NEW}
    try:
        _cd_old = _KC.content_domains()
    finally:
        KR.DOMAINS.update(_saved2)
    ok(_cd_now == _cd_old and not (_ES_NEW[0] in _cd_now or _ES_NEW[1] in _cd_now),
       "知识库 [148] 选题层 content_domains 推导不受空语料新域影响（域锚点/入口B口径不变）")
    import sqlite3
    _ES_DIR = K.KB_DIR.parent / "电竞事实库"
    _ddl = (_ES_DIR / "schema_v2.sql").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="es_schema_") as _est:
        _econ = sqlite3.connect(Path(_est) / "t.db")
        _econ.executescript(_ddl)
        _tabs = {r[0] for r in _econ.execute(
            "select name from sqlite_master where type='table'")}
        _bt_ok = True
        for _t in ("series", "game_result", "membership", "transfer_event"):
            _cols = {r[1] for r in _econ.execute(f"PRAGMA table_info({_t})")}
            _bt_ok &= {"valid_from", "valid_to", "start_bound_kind", "end_bound_kind",
                       "time_precision", "recorded_at", "superseded_at",
                       "last_verified_at", "row_version_id"} <= _cols
        _enum_rejected = False
        try:
            _econ.execute("insert into source_policy(source_id,automated_access,"
                          "local_retention,commercial_use,quotation,redistribution) "
                          "values('X','maybe','allowed','allowed','allowed','allowed')")
        except sqlite3.IntegrityError:
            _enum_rejected = True
        _econ.execute("insert into competition(competition_id,game_id) "
                      "values('C','lol')")
        _econ.execute("insert into stage(stage_id,competition_id,stage_name) "
                      "values('ST','C','s')")
        _multi_ok = True
        try:
            for _rv in ("r1", "r2"):
                _econ.execute(
                    "insert into series(series_id,stage_id,status,row_version_id,"
                    "logical_record_id,recorded_at) "
                    "values('SX','ST','completed',?,'SX','2026-11-01T00:00:00Z')",
                    (_rv,))
        except sqlite3.IntegrityError:
            _multi_ok = False
        _econ.close()
    ok(len(_tabs) == 18 and _bt_ok and _enum_rejected and _multi_ok
       and _sha(_ES_DIR / "schema_v1.sql")[:16] == "b9c726bb1ea1789c",
       "知识库 [149] schema_v2 冻结件：18表+双时间列齐+权限非法值被拒+同业务ID多行版本可存（v1主键缺陷反证）；v1原件字节未动")
    _pol = json.loads((_ES_DIR / "source_policy_v1.json").read_text(encoding="utf-8"))
    _ps = {s["source_id"]: s for s in _pol["sources"]}
    _perm5 = ("automated_access", "local_retention", "commercial_use",
              "quotation", "redistribution")
    ok(len(_ps) == 19
       and all(s[k] in ("allowed", "denied", "unknown")
               for s in _ps.values() for k in _perm5)
       and _ps["E05"]["commercial_use"] == "denied"
       and _ps["E11"]["commercial_use"] == "denied"
       and _ps["E13"]["automated_access"] == "denied",
       "知识库 [150] source_policy_v1：E01–E19 齐全+五维枚举合法+GRID/Steam商用denied+VLR自动denied")
    ok(all(_ps["E06"][k] == "unknown" for k in _perm5)
       and _ps["E02"]["automated_access"] == "allowed"
       and _ps["E09"]["commercial_use"] == "unknown",
       "知识库 [151] 反证格：403未核=unknown非denied非allowed（E06）；免key官方渠道=allowed（E02）；代码MIT≠数据商用（E09）")

    # ---- 阶段一第2–3天：电竞事实库导入/查询（离线夹具+临时库，不碰真实件） ----
    from . import kb_esports as KE
    _es_real = [KE.DB_PATH, KE.SNAP_DIR]
    _es_before = {str(p): (p.stat().st_mtime_ns, _sha(p)) if p.is_file()
                  else ("dir", sorted(x.name for x in p.iterdir())) if p.is_dir()
                  else None for p in _es_real}
    _old_es = {k: getattr(KE, k) for k in ("ES_DIR", "DB_PATH", "SNAP_DIR")}
    _old_auto_k = {k: getattr(K, k) for k in ("KB_DIR", "CORPUS_MAP", "INDEX_JSON")}
    _old_auto_s = S.REG_JSON
    _es_con = None
    try:
        with tempfile.TemporaryDirectory(prefix="es_gates_") as _et:
            _etd = Path(_et)
            _auto_doc = _etd / "auto.md"
            _auto_doc.write_text("# 自动问答夹具\n\n燕返在最高点发动，属于必杀。\n",
                                 encoding="utf-8")
            _auto_reg = {"schema_version": 1, "sources": [
                _src("s_auto", "official_manual", "verified_read", ["NES"], ["说明书"],
                     games_hit=["testgame"], evidence=[str(_auto_doc)])]}
            _auto_map = {"schema_version": 1, "revisions": {
                "auto_jp": {"game_id": "testgame", "platform": "NES", "name": "自动问答夹具"}},
                "entries": [{"path": str(_auto_doc), "source_id": "s_auto",
                             "revision": "auto_jp", "kind": "prose",
                             "authority": "authoritative"}]}
            K.KB_DIR = _etd / "kb"
            K.CORPUS_MAP = _etd / "corpus_map.json"
            K.INDEX_JSON = _etd / "index.json"
            S.REG_JSON = _etd / "sources.json"
            K.CORPUS_MAP.write_text(json.dumps(_auto_map, ensure_ascii=False), encoding="utf-8")
            S.save_registry(_auto_reg, path=S.REG_JSON)
            K.build(map_path=K.CORPUS_MAP, index_path=K.INDEX_JSON, reg=_auto_reg)
            KE.ES_DIR = _etd
            KE.DB_PATH = _etd / "facts_v1.db"
            KE.SNAP_DIR = _etd / "snapshots"
            _off = _etd / "offline"
            (_off / "cdn" / "9.9.9" / "data" / "zh_CN").mkdir(parents=True)
            (_off / "api").mkdir()
            (_off / "api" / "versions.json").write_text('["9.9.9","9.9.8"]',
                                                        encoding="utf-8")
            _fx = {"type": "champion", "version": "9.9.9", "data": {
                "TestA": {"id": "TestA", "key": "1", "name": "甲之称号",
                          "title": "测试甲", "tags": ["刺客"]},
                "TestB": {"id": "TestB", "key": "2", "name": "甲之称号",
                          "title": "测试乙", "tags": ["法师"]},
                "TestC": {"id": "TestC", "key": "3", "name": "缺名者"}}}
            (_off / "cdn" / "9.9.9" / "data" / "zh_CN" / "champion.json").write_text(
                json.dumps(_fx, ensure_ascii=False), encoding="utf-8")
            KE.init_db()
            KE.init_db()
            _econ = sqlite3.connect(KE.DB_PATH)
            _nt = _econ.execute("select count(*) from sqlite_master "
                                "where type='table'").fetchone()[0]
            _np = _econ.execute("select count(*) from source_policy").fetchone()[0]
            _econ.close()
            ok(_nt == 18 and _np == 19,
               "知识库 [152] init_db 幂等：连建两次仍 18 表+权限种子 19 行")
            _r1 = KE.import_ddragon(offline_dir=_off)
            ok(_r1["version"] == "9.9.9" and _r1["entities_new"] == 2
               and _r1["evidence_new"] == 2 and _r1["snapshots_new"] == 1
               and len(_r1["skipped"]) == 1 and "TestC" in _r1["skipped"][0],
               "知识库 [153] 夹具导入：2实体2证据1快照，缺name者跳过不造空实体（反证）")
            _econ = sqlite3.connect(KE.DB_PATH)
            _evrow = _econ.execute("select locator, exact_text_or_value from "
                                   "evidence_block limit 1").fetchone()
            _fsn = _econ.execute("select count(*) from fact_support").fetchone()[0]
            _econ.close()
            _rt_ok = False
            for _k, _v in _fx["data"].items():
                if _evrow[0] == f"/data/{_k}":
                    _rt_ok = json.loads(_evrow[1]) == _v
            ok(_evrow[0].startswith("/data/") and _rt_ok and _fsn == 2,
               "知识库 [154] 证据可回溯：JSON Pointer 定位+原文往返一致+字段级绑定2条")
            _r2 = KE.import_ddragon(offline_dir=_off)
            ok(_r2["entities_new"] == 0 and _r2["evidence_new"] == 0
               and _r2["snapshots_new"] == 0 and _r2["aliases_new"] == 0,
               "知识库 [155] 幂等反证：同字节重复导入四计数全0（不增殖）")
            _qp = KE.query_champion("测试甲")
            _sel = _qp.get("selected_evidence", [])
            _snap_ok = False
            if _qp["status"] == "pass" and len(_sel) == 1:
                _sp = Path(_sel[0]["storage_ref"])
                _snap_ok = (_sp.is_file() and _sha(_sp)
                            == _sel[0]["snapshot_sha256"]
                            and _sel[0]["locator"] == "/data/TestA")
            ok(_qp["status"] == "pass" and len(_sel) == 1 and _snap_ok
               and _qp["claim"]["conditions"]["patch"] == "9.9.9"
               and _qp["claim"]["value"]["name"] == "测试甲"
               and _qp["claim"]["value"]["title"] == "甲之称号"
               and "截至补丁 9.9.9" in _qp["answer_text"]
               and "测试甲，称号「甲之称号」" in _qp["answer_text"]
               and _qp["dataset_revision"] == "ddragon:9.9.9:zh_CN",
               "知识库 [156] 唯一证据契约：pass恰1块+快照sha对得上+答案带截至补丁条件+zh_CN名/称号映射正确（实测语言包name/title语义相反）")
            _qvv = KE.query_champion("测试甲", patch="9.9.8")
            _qen = KE.query_champion("TestA")
            _qamb = KE.query_champion("甲之称号")
            ok(_qvv["status"] == "miss"
               and _qvv["reason_code"] == "version_not_collected"
               and _qen["status"] == "pass"
               and _qamb["status"] == "inconclusive"
               and _qamb["reason_code"] == "needs_clarification"
               and len(_qamb["candidates"]) == 2,
               "知识库 [157] 版本钉硬过滤：未导入补丁miss；英文别名可查；同名歧义要澄清不猜")
            _fi = {"type": "item", "version": "9.9.9", "data": {
                "1001": {"id": "TestBoots", "name": "测试鞋",
                         "description": "测试用装备说明", "plaintext": "移动更快",
                         "tags": ["Boots"], "gold": {"base": 300, "total": 300,
                                                     "purchasable": True, "sell": 210}}}}
            _fs = {"type": "summoner", "version": "9.9.9", "data": {
                "TestFlash": {"id": "TestFlash", "name": "测试闪现",
                              "description": "短距离传送", "cooldownBurn": "300",
                              "rangeBurn": "400", "summonerLevel": 7}}}
            (_off / "cdn" / "9.9.9" / "data" / "zh_CN" / "item.json").write_text(
                json.dumps(_fi, ensure_ascii=False), encoding="utf-8")
            (_off / "cdn" / "9.9.9" / "data" / "zh_CN" / "summoner.json").write_text(
                json.dumps(_fs, ensure_ascii=False), encoding="utf-8")
            _r3 = KE.import_ddragon(offline_dir=_off, kinds=("item", "summoner"))
            ok(_r3["entities_new"] == 2 and _r3["evidence_new"] == 2
               and _r3["snapshots_new"] == 2 and _r3["aliases_new"] == 2,
               "知识库 [215] 静态实体扩展：item/summoner 各1实体1证据1快照，英文ID别名可查")
            _qi = KE.query_static("1001", "item")
            _qs = KE.query_static("TestFlash", "summoner")
            ok(_qi["status"] == _qs["status"] == "pass"
               and len(_qi["selected_evidence"]) == len(_qs["selected_evidence"]) == 1
               and _qi["claim"]["value"]["gold"]["total"] == 300
               and _qs["claim"]["value"]["cooldown"] == "300"
               and _qs["claim"]["value"]["range"] == "400"
               and "售价 300 金币" in _qi["answer_text"],
               "知识库 [216] 静态查询：装备按external_id、技能按英文别名定位，各绑定唯一快照证据且售价/冷却/范围原样输出")
            raises(lambda: KE.query_static("测试鞋", "rune"),
                   "知识库 [217] 类型白名单：未登记的静态实体类型拒绝，不把装备伪装成英雄")

            # ----  Targeted：SQLite 静态事实接 query_auto / 写作消费链（零 LLM，只读库） ----
            mp = K.CORPUS_MAP  # 前面的构建探针已结束，后续文本回退必须用仍存在的夹具主数据
            _static_db_before = (KE.DB_PATH.stat().st_mtime_ns, _sha(KE.DB_PATH))
            _sa = K.query_auto("测试甲称号是什么", topk=3,
                               index_path=K.INDEX_JSON, map_path=mp)
            _sae = K.query_auto("TestA 称号是什么", topk=3,
                                index_path=K.INDEX_JSON, map_path=mp)
            ok(all(r.get("status") == "pass" and r.get("backend") == "esports_sqlite"
                   and "截至补丁9.9.9" in r.get("answer_text", "")
                   and "甲之称号" in r.get("answer_text", "")
                   and len(r.get("selected_evidence") or []) == 1
                   and r["selected_evidence"][0].get("locator") == "/data/TestA"
                   and r.get("dataset_revision") == "ddragon:9.9.9:zh_CN"
                   for r in (_sa, _sae))
               and _sa.get("auto_routing", {}).get("mode") == "single",
               "知识库 [264] Targeted 静态正例：canonical/external_id 均结构化pass，补丁+答案+唯一JSON Pointer+revision齐全")
            _samb = K.query_auto("甲之称号是什么", topk=3,
                                 index_path=K.INDEX_JSON, map_path=mp)
            _smulti_ent = K.query_auto("测试甲和测试乙的称号分别是什么", topk=3,
                                       index_path=K.INDEX_JSON, map_path=mp)
            _sunknown = K.query_auto("测试甲和不存在英雄的称号分别是什么", topk=3,
                                     index_path=K.INDEX_JSON, map_path=mp)
            ok(all(r.get("status") == "inconclusive"
                   and r.get("reason_code") == "needs_clarification"
                   and not r.get("selected_evidence")
                   for r in (_samb, _smulti_ent, _sunknown)),
               "知识库 [265] Targeted 歧义关闭：同名多实体、多实体连接、连接未知实体均澄清且零出证")
            _sv_q = K.query_auto("测试甲 patch=1.0.0 的称号是什么", topk=3,
                                 index_path=K.INDEX_JSON, map_path=mp)
            _sv_r = K.query_auto("测试甲称号是什么", revision="1.0.0", topk=3,
                                 index_path=K.INDEX_JSON, map_path=mp)
            ok(all(r.get("status") == "miss"
                   and r.get("reason_code") == "version_not_collected"
                   and not r.get("selected_evidence")
                   for r in (_sv_q, _sv_r)),
               "知识库 [266] Targeted 缺版本：问句补丁与显式revision均version_not_collected，绝不拿最新版顶包")
            _sfaker = K.query_auto("Faker 现在属于哪队", topk=3,
                                   index_path=K.INDEX_JSON, map_path=mp)
            ok(_sfaker.get("status") == "miss"
               and _sfaker.get("refusal") == "out_of_scope"
               and _sfaker.get("backend") != "esports_sqlite"
               and not _sfaker.get("answer_text")
               and not _sfaker.get("selected_evidence"),
               "知识库 [267] Targeted Faker拒答：动态队伍归属继续缺数据，静态英雄库不凭常识作答")
            _smd = K.query_auto("LOL 测试甲称号是什么；DOTA2 英雄呢？", topk=3,
                                index_path=K.INDEX_JSON, map_path=mp)
            ok(_smd.get("status") == "inconclusive"
               and _smd.get("refusal") == "multi_domain_needs_split"
               and _smd.get("auto_routing", {}).get("mode") == "multi"
               and _smd.get("selected_evidence") == []
               and [d["domain"] for d in _smd["domain_results"]] == ["esports_lol", "esports_dota"]
               and _smd["domain_results"][0].get("status") == "pass"
               and _smd["domain_results"][0].get("backend") == "esports_sqlite",
               "知识库 [268] Targeted 多域不合并：LOL静态域可逐域pass，DOTA2缺料，外层仍inconclusive且selected_evidence为空")
            _snons = K.query_auto("测试甲如何操作", topk=3,
                                  index_path=K.INDEX_JSON, map_path=mp)
            _swrong = K.query_auto("测试甲售价多少", topk=3,
                                   index_path=K.INDEX_JSON, map_path=mp)
            _sitem = K.query_auto("测试鞋售价多少", topk=3,
                                  index_path=K.INDEX_JSON, map_path=mp)
            _sspell = K.query_auto("LOL 召唤师技能 TestFlash 冷却多少", topk=3,
                                   index_path=K.INDEX_JSON, map_path=mp)
            ok(_snons.get("backend") != "esports_sqlite"
               and _swrong.get("backend") != "esports_sqlite"
               and _sitem.get("status") == "pass"
               and "售价 300 金币" in _sitem.get("answer_text", "")
               and _sitem["selected_evidence"][0]["locator"] == "/data/1001"
               and _sspell.get("status") == "pass"
               and "冷却 300" in _sspell.get("answer_text", "")
               and _sspell["selected_evidence"][0]["locator"] == "/data/TestFlash",
               "知识库 [269] Targeted 窄接管：非静态问句/英雄售价不接管，装备售价与召唤师技能冷却按正确静态类型出证")
            _txt = "燕返 最高点 必杀"
            _txt_direct = K.query(_txt, game="testgame", topk=3,
                                  index_path=K.INDEX_JSON, map_path=mp)
            _txt_auto = K.query_auto(_txt, game="testgame", topk=3,
                                     index_path=K.INDEX_JSON, map_path=mp)
            _txt_fields = ("status", "hits", "counts", "selected_evidence")
            ok(_txt_direct["status"] == "pass"
               and all(_txt_direct.get(k) == _txt_auto.get(k) for k in _txt_fields)
               and _txt_auto.get("backend") != "esports_sqlite",
               "知识库 [270] Targeted 文本恒量反证：显式game过滤保持旧文本pass的status/hits/counts/selected_evidence逐格一致")
            _bare = [K.query_auto(q, topk=3, index_path=K.INDEX_JSON, map_path=mp)
                     for q in ("测试甲 称号", "测试鞋 售价", "测试闪现 冷却")]
            ok(all(r.get("status") == "pass" and r.get("backend") == "esports_sqlite"
                   and len(r.get("selected_evidence") or []) == 1
                   and r.get("auto_routing", {}).get("mode") == "single"
                   for r in _bare)
               and [r["selected_evidence"][0]["locator"] for r in _bare]
                   == ["/data/TestA", "/data/1001", "/data/TestFlash"],
               "知识库 [272] Targeted 裸属性句：英雄/装备/技能无疑问词无LOL上下文仍按唯一实体出结构化证据")
            _bare_unknown = K.query_auto("不存在英雄 称号", topk=3,
                                         index_path=K.INDEX_JSON, map_path=mp)
            _lol_unknown = K.query_auto("LOL 不存在英雄 称号", topk=3,
                                        index_path=K.INDEX_JSON, map_path=mp)
            ok(_bare_unknown.get("backend") != "esports_sqlite"
               and _lol_unknown.get("status") == "miss"
               and _lol_unknown.get("refusal") == "out_of_scope"
               and _lol_unknown.get("backend") != "esports_sqlite"
               and _lol_unknown.get("auto_routing", {}).get("domains", [{}])[0].get("domain") == "esports_lol"
               and not _bare_unknown.get("selected_evidence")
               and not _lol_unknown.get("selected_evidence"),
               "知识库 [273] Targeted 未知实体：未唯一识别时不接管，继续原路由；LOL域仍诚实out_of_scope且不静态出证")
            _bare_missing_patch = K.query_auto("测试甲 补丁1.0.0 称号", topk=3,
                                              index_path=K.INDEX_JSON, map_path=mp)
            ok(_bare_missing_patch.get("status") == "miss"
               and _bare_missing_patch.get("reason_code") == "version_not_collected"
               and _bare_missing_patch.get("backend") == "esports_sqlite"
               and not _bare_missing_patch.get("selected_evidence"),
               "知识库 [274] Targeted 裸问句缺版本：点名未导入补丁即version_not_collected，不拿最新版顶包")
            _spell_no_ctx = K.query_auto("TestFlash 冷却", topk=3,
                                         index_path=K.INDEX_JSON, map_path=mp)
            _spell_ctx = K.query_auto("LOL TestFlash 冷却", topk=3,
                                      index_path=K.INDEX_JSON, map_path=mp)
            _item_id = K.query_auto("1001 售价", topk=3,
                                    index_path=K.INDEX_JSON, map_path=mp)
            ok(_spell_no_ctx.get("backend") != "esports_sqlite"
               and _spell_ctx.get("status") == "pass"
               and _spell_ctx.get("backend") == "esports_sqlite"
               and _item_id.get("status") == "pass"
               and _item_id.get("backend") == "esports_sqlite"
               and _spell_ctx["selected_evidence"][0]["locator"] == "/data/TestFlash"
               and _item_id["selected_evidence"][0]["locator"] == "/data/1001",
               "知识库 [275] Targeted 短别名上下文：裸英文技能不接管、LOL上下文接管；唯一装备外部ID可直接定位")
            _kc_log_old = _KC.QUERY_LOG
            _KC.QUERY_LOG = _etd / "consumer_query_log.jsonl"
            try:
                _cross, _cross_info = _KC.crosscheck(
                    [{"event_id": "ev_static", "titles": ["测试甲称号是什么"]}],
                    mode="bm25", index_path=K.INDEX_JSON)
            finally:
                _KC.QUERY_LOG = _kc_log_old
            _cr = _cross["ev_static"]
            _card = importlib.import_module("选题决策层.选题卡")
            _card_md = _card.render_card_md({
                "core_hook": "测试甲称号", "event_id": "ev_static", "profile_id": "test",
                "attention": "高", "evidence_status": "pass", "queue": "test",
                "sources": ["fixture"], "source_count": 1, "item_count": 1,
                "evidence_note": "fixture", "first_seen": "", "pub_latest": "",
                "title_only_note": "fixture", "core_hook_note": "fixture", "dims": {},
                "must_mention": "补丁与证据", "urls": [], "judged_at": "fixture",
                "rule_version": "fixture", "kb": _cr})
            ok(_cr.get("status") == "pass"
               and _cr.get("backend") == "esports_sqlite"
               and "截至补丁9.9.9" in _cr.get("answer_text", "")
               and _cr.get("dataset_revision") == "ddragon:9.9.9:zh_CN"
               and len(_cr.get("selected_evidence") or []) == 1
               and _cr.get("index_sha256") == ""
               and _cross_info.get("unanchored_downgraded") == 0
               and "KB出证" in _card_md and "/data/TestA" in _card_md,
               "知识库 [271] Targeted 消费方闭环：知识对照不降级unanchored且透传结构化字段，现有选题卡按hits显示出证")
            ok(_static_db_before == (KE.DB_PATH.stat().st_mtime_ns, _sha(KE.DB_PATH)),
               "知识库 [276] Targeted 只读反证：全部自动问答静态查询后临时SQLite字节与mtime不变")

            # ---- Targeted：洛克人2生产域自动路由与选题消费链 ----
            from . import kb_megaman2 as M
            _mm2_temp = tempfile.TemporaryDirectory(prefix="mm2_gates_")
            _mm2_td = Path(_mm2_temp.name)
            _mm2_file = _mm2_td / "mm2_tech.txt"
            _mm2_file.write_text(
                "# Rockman 2 technical fixture\n\n"
                "Walking speed\nIn Rockman 1 and 2, during walking, Rockman’s X speed is 01.60.\n\n"
                "Jumping\nIn Rockman 1 and 2, when Rockman jumps, his Y speed is set to 04.DF.\n\n"
                "Horizontal motion while jumping\nIn Rockman 1 and 2, during jumping/falling into some direction, Rockman’s X speed is 01.50.\n\n"
                "Acceleration\nIn Rockman 2, when Rockman accelerates from non-full speed, his X speed is 00.20 for 7 frames before gaining full speed.\n\n"
                "Deceleration\nIn Rockman 2, when Rockman decelerates from full speed, his X speed is 00.80 for 8 (decimal) frames before halting completely.\n\n"
                "Memory addresses\nGame Screen# X (hi,lo) Xspd (hi,lo) Y (hi,lo) Yspd (hi,lo)\n"
                "Rockman 2 $440 $460:$480 $600:$620 $4A0:$4C0 $640:$660\n",
                encoding="utf-8")
            _mm2_reg = {"schema_version": 1, "sources": [_src(
                M.PRODUCTION_SOURCE_ID, "en_tech", "verified_read", ["NES"],
                ["帧数据", "基础档案"], games_hit=["megaman2"], evidence=[str(_mm2_file)])]}
            _mm2_reg_path = _mm2_td / "mm2_sources.json"
            S.save_registry(_mm2_reg, path=_mm2_reg_path)
            _mm2_map = {"schema_version": 1, "revisions": {
                M.TECHNICAL_REVISION: {
                    "game_id": "megaman2", "platform": "NES", "name": "洛克人2生产技术夹具"}},
                "entries": [entry(
                    _mm2_file, M.PRODUCTION_SOURCE_ID, M.TECHNICAL_REVISION,
                    "prose", "authoritative")]}
            _mm2_map_path = _mm2_td / "mm2_map.json"
            _mm2_map_path.write_text(json.dumps(_mm2_map, ensure_ascii=False, indent=1) + "\n",
                                     encoding="utf-8")
            _mm2_index = _mm2_td / "mm2.index.json"
            K.build(map_path=_mm2_map_path, index_path=_mm2_index, reg=_mm2_reg)
            _mm2_kw = {"index_path": _mm2_index, "map_path": _mm2_map_path, "reg": _mm2_reg}
            _mm2_inputs = (M.INDEX_PATH, M.MAP_PATH, M.REGISTRY_PATH, M.CONTRACT_PATH)
            _mm2_prod_inputs = (_mm2_index, _mm2_map_path, _mm2_reg_path, _mm2_file)
            _mm2_before = {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm2_inputs}
            _mm2_prod_before = {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm2_prod_inputs}
            _mm2_expected = _sha(_mm2_index)
            _mm2_pos = [K.query_auto(q, topk=3, **_mm2_kw)
                        for q in ("洛克人2 的 walking speed 是什么？",
                                  "洛克人2 步行速度是多少",
                                  "洛克人2 跳跃 Y 速度是什么",
                                  "洛克人2 跳跃时 X speed 是什么？",
                                  "洛克人2 从静止加速需要多少帧？",
                                  "洛克人2 从全速停止需要多少帧？")]
            _mm2_strict = K.query_auto("洛克人2 的 walking speed 是什么？", topk=3,
                                       fragment_policy="strict", **_mm2_kw)
            _mm2_explicit = K.query_auto("X speed 内存地址是什么", topk=3,
                                         revision=M.TECHNICAL_REVISION, **_mm2_kw)
            ok(all(r.get("status") == "pass" and r.get("backend") == "megaman2"
                   and r.get("index_sha256") == _mm2_expected
                   and r.get("candidate_only") is False
                   and r.get("whole_game_knowledge_base") is False
                   and r.get("production_route_wired") is True
                   and r.get("auto_routing", {}).get("mode") == "single"
                   and len(r.get("selected_evidence") or []) == 1
                   and r["selected_evidence"][0].get("revision") == M.TECHNICAL_REVISION
                   and r["selected_evidence"][0].get("status") == "verified_read"
                   and r["selected_evidence"][0].get("authority") == "authoritative"
                   and r["selected_evidence"][0].get("source_id") == M.PRODUCTION_SOURCE_ID
                   and r["selected_evidence"][0].get("locator", "").startswith(str(_mm2_file) + "#L")
                   for r in (*_mm2_pos, _mm2_strict, _mm2_explicit))
               and "01.60" in _mm2_pos[0].get("answer_text", "")
               and "04.DF" in _mm2_pos[2].get("answer_text", "")
               and "01.50" in _mm2_pos[3].get("answer_text", "")
               and "7 frames" in _mm2_pos[4].get("answer_text", "")
               and "8 (decimal) frames" in _mm2_pos[5].get("answer_text", "")
               and "$600:$620" in _mm2_explicit.get("answer_text", ""),
               "知识库 [277] Targeted 生产正例：中英文/strict/显式revision/跳跃轴向/加速减速帧数均生产索引唯一出证，来源与路径受生产白名单约束")
            ok(M._speed_axis_ok("跳跃时 X speed 是什么？", "when Rockman jumps, his Y speed is set to 04.DF") is False
               and M._speed_axis_ok("跳跃时 Y speed 是什么？", "during jumping, Rockman’s X speed is 01.50") is False
               and M._speed_axis_ok("X speed 内存地址是什么？", "Xspd (hi,lo) $600:$620") is True,
               "知识库 [277b] Targeted 速度轴向反证：X/Y 轴不得互答，Xspd 地址字段仍可作 X 轴证据")
            _mm2_move = K.query_auto("洛克人2 出招表", topk=3, **_mm2_kw)
            _mm2_pal = K.query_auto("洛克人2 PAL 版 walking speed", topk=3, **_mm2_kw)
            _mm2_other = K.query_auto("Mega Man 2: The Power Fighters walking speed", topk=3, **_mm2_kw)
            _mm2_multi = K.query_auto("洛克人2 的 walking speed 和拳皇98 的必杀射门分别是什么？",
                                      topk=3, **_mm2_kw)
            _mm2_entry = next((d for d in _mm2_multi.get("domain_results") or []
                              if d["domain"] == "megaman2"), {})
            ok(_mm2_move.get("status") == "miss"
               and _mm2_move.get("reason_code") == "move_list_not_collected"
               and _mm2_pal.get("status") == "inconclusive"
               and _mm2_pal.get("reason_code") == "version_not_collected"
               and _mm2_other.get("status") == "miss"
               and _mm2_other.get("reason_code") == "ambiguous_series"
               and all(not r.get("selected_evidence") for r in (_mm2_move, _mm2_pal, _mm2_other))
               and _mm2_multi.get("status") == "inconclusive"
               and _mm2_multi.get("refusal") == "multi_domain_needs_split"
               and _mm2_multi.get("selected_evidence") == []
               and _mm2_entry.get("status") == "pass"
               and len(_mm2_entry.get("selected_evidence") or []) == 1
               and _mm2_entry.get("candidate_only") is False,
               "知识库 [278] Targeted 生产拒答与多域：缺出招表/PAL/近名作失败关闭，多域保留本域证据但外层绝不合并pass")
            _mm2_bad = K.query_auto(
                "洛克人2 的 walking speed 是什么？", topk=3,
                **{**_mm2_kw, "index_path": td / "missing_mm2.index.json"})
            _mm2_unproduced = K.query_auto(
                "洛克人2 内存地址是什么", topk=3,
                revision=M.MEMORY_REVISION, **_mm2_kw)
            ok(_mm2_bad.get("status") == "inconclusive"
               and _mm2_bad.get("reason_code") == "candidate_unavailable"
               and _mm2_bad.get("backend") == "megaman2"
               and not _mm2_bad.get("selected_evidence")
               and not _mm2_bad.get("hits")
               and _mm2_unproduced.get("status") == "inconclusive"
               and _mm2_unproduced.get("reason_code") == "revision_not_produced"
               and not _mm2_unproduced.get("selected_evidence"),
               "知识库 [279] Targeted 生产失败关闭：索引缺失与未生产revision均零出证，不借候选或技术文本顶包")
            _mm2_log_old = _KC.QUERY_LOG
            _mm2_k_old = (K.INDEX_JSON, K.CORPUS_MAP)
            _mm2_s_old = S.REG_JSON
            _KC.QUERY_LOG = _mm2_td / "mm2_consumer_query_log.jsonl"
            K.INDEX_JSON, K.CORPUS_MAP, S.REG_JSON = _mm2_index, _mm2_map_path, _mm2_reg_path
            try:
                _mm2_cross, _mm2_info = _KC.crosscheck(
                    [{"event_id": "ev_mm2", "titles": ["洛克人2 步行速度是多少"]}],
                    mode="bm25", index_path=_mm2_index)
            finally:
                _KC.QUERY_LOG = _mm2_log_old
                K.INDEX_JSON, K.CORPUS_MAP = _mm2_k_old
                S.REG_JSON = _mm2_s_old
            _mm2_cr = _mm2_cross["ev_mm2"]
            _mm2_card = _card.render_card_md({
                "core_hook": "洛克人2步行速度", "event_id": "ev_mm2", "profile_id": "test",
                "attention": "中", "evidence_status": "pass", "queue": "test",
                "sources": ["fixture"], "source_count": 1, "item_count": 1,
                "evidence_note": "fixture", "first_seen": "", "pub_latest": "",
                "title_only_note": "fixture", "core_hook_note": "fixture", "dims": {},
                "must_mention": "生产范围与证据", "urls": [], "judged_at": "fixture",
                "rule_version": "fixture", "kb": _mm2_cr})
            ok(_mm2_cr.get("status") == "pass"
               and _mm2_cr.get("index_sha256") == _mm2_expected
               and _mm2_cr.get("auto_routing", {}).get("domains", [{}])[0].get("domain") == "megaman2"
               and len(_mm2_cr.get("selected_evidence") or []) == 1
               and _mm2_info.get("unanchored_downgraded") == 0
               and _KC.QUERY_LOG == _mm2_log_old
               and (_mm2_td / "mm2_consumer_query_log.jsonl").is_file()
               and "KB出证" in _mm2_card
               and _mm2_cr["selected_evidence"][0]["locator"] in _mm2_card,
               "知识库 [280] Targeted 生产消费闭环：内容域锚点不降级，生产SHA/唯一证据透传选题卡，查询日志只落临时目录")
            _mm2_count = K.query_auto("洛克人2 有几个对象", topk=3, **_mm2_kw)
            _mm2_alias_ok = K.query_auto("洛克人  ２ 的 walking speed 是什么？", topk=3, **_mm2_kw)
            _mm2_alias_bad = K.query_auto("洛克人20 的 walking speed 是什么？", topk=3, **_mm2_kw)
            _mm2_checks = {
                "count_not_pass": _mm2_count.get("status") != "pass",
                "count_no_evidence": not _mm2_count.get("selected_evidence"),
                "fullwidth_alias_pass": _mm2_alias_ok.get("status") == "pass",
                "other_installment_not_megaman2": _mm2_alias_bad.get("backend") != "megaman2",
                "other_installment_unrouted": _mm2_alias_bad.get("auto_routing", {}).get("domains", [{}])[0].get("domain") == "unrouted",
                "candidate_inputs_unchanged": _mm2_before == {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm2_inputs},
                "production_fixture_unchanged": _mm2_prod_before == {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm2_prod_inputs},
            }
            ok(all(_mm2_checks.values()),
               "知识库 [281] Targeted 生产恒量反证：数量问句不假pass，全角/多空格别名可查而洛克人20不误路由，候选与生产夹具字节/mtime全未变 "
               + json.dumps(_mm2_checks, ensure_ascii=False))

            # ---- Targeted：洛克人1隔离候选接生产自动路由与选题消费链 ----
            from . import kb_megaman1 as M1
            _mm1_inputs = (M1.INDEX_PATH, M1.MAP_PATH, M1.REGISTRY_PATH)
            _mm1_before = {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm1_inputs}
            _mm1_expected = M1.expected_index_sha256()
            _mm1_pos = [K.query_auto(q, topk=3, index_path=K.INDEX_JSON)
                        for q in ("洛克人1 的 X 坐标对象表地址范围是什么？",
                                  "洛克人  １ 的坐标轴方向是什么？")]
            _mm1_strict = K.query_auto("洛克人1 的 X 坐标对象表地址范围是什么？",
                                       topk=3, fragment_policy="strict")
            _mm1_explicit = K.query_auto("owned 和 current_weapon 两个内存字段分别对应什么？",
                                         topk=3, revision=M1.REVISION)
            ok(all(r.get("status") == "pass" and r.get("backend") == "megaman1_candidate"
                   and r.get("index_sha256") == _mm1_expected
                   and r.get("candidate_only") is True
                   and r.get("whole_game_knowledge_base") is False
                   and r.get("production_route_wired") is True
                   and r.get("auto_routing", {}).get("mode") == "single"
                   and len(r.get("selected_evidence") or []) == 1
                   and r["selected_evidence"][0].get("revision") == M1.REVISION
                   and r["selected_evidence"][0].get("status") == "verified_read"
                   and r["selected_evidence"][0].get("authority") == "authoritative"
                   for r in (*_mm1_pos, _mm1_strict, _mm1_explicit))
               and "$480:$4A0" in _mm1_pos[0].get("answer_text", "")
               and "0x5D" in _mm1_explicit.get("answer_text", ""),
               "知识库 [283] Targeted 洛克人1候选生产正例：中文全角/strict/显式revision均候选唯一出证且保持非整款标记")
            _mm1_manual = K.query_auto("洛克人1官方说明书是否记载角色创建系统？", topk=3)
            _mm1_pal = K.query_auto("洛克人1 PAL-B 版的坐标表是否可以直接当作 NTSC 美版结论？", topk=3)
            _mm1_series = K.query_auto("洛克人的坐标轴方向是什么？", topk=3)
            _mm1_multi = K.query_auto("洛克人1 的 X 坐标对象表和拳皇98 的简化连招分别是什么？", topk=3)
            _mm1_entry = next((d for d in _mm1_multi.get("domain_results") or []
                               if d["domain"] == "megaman1"), {})
            ok(_mm1_manual.get("status") != "pass"
               and _mm1_pal.get("status") == "inconclusive"
               and _mm1_pal.get("reason_code") == "version_not_collected"
               and _mm1_series.get("status") == "miss"
               and _mm1_series.get("reason_code") == "ambiguous_series"
               and all(not r.get("selected_evidence") for r in (_mm1_manual, _mm1_pal, _mm1_series))
               and _mm1_multi.get("status") == "inconclusive"
               and _mm1_multi.get("refusal") == "multi_domain_needs_split"
               and _mm1_multi.get("selected_evidence") == []
               and _mm1_entry.get("status") == "pass"
               and len(_mm1_entry.get("selected_evidence") or []) == 1,
               "知识库 [284] Targeted 洛克人1拒答与多域：角色创建缺证/PAL/系列歧义关闭，多域只保留域内证据")
            _old_mm1_sha = M1.expected_index_sha256
            _old_mm1_index = M1.INDEX_PATH
            try:
                M1.expected_index_sha256 = lambda: "0" * 64
                _mm1_bad = K.query_auto("洛克人1 的 X 坐标对象表地址范围是什么？", topk=3)
                M1.expected_index_sha256 = _old_mm1_sha
                M1.INDEX_PATH = _etd / "missing_mm1_index.json"
                _mm1_missing = K.query_auto("洛克人1 的 X 坐标对象表地址范围是什么？", topk=3)
            finally:
                M1.expected_index_sha256 = _old_mm1_sha
                M1.INDEX_PATH = _old_mm1_index
            ok(all(r.get("status") == "inconclusive"
                   and r.get("backend") == "megaman1_candidate"
                   and not r.get("selected_evidence") and not r.get("hits")
                   for r in (_mm1_bad, _mm1_missing))
               and _mm1_bad.get("reason_code") == "candidate_hash_mismatch"
               and _mm1_missing.get("reason_code") == "candidate_unavailable",
               "知识库 [285] Targeted 洛克人1失败关闭：冻结哈希不符与候选索引缺失均零hit零出证且不回退生产文本")
            _mm1_log_old = _KC.QUERY_LOG
            _KC.QUERY_LOG = _etd / "mm1_consumer_query_log.jsonl"
            try:
                _mm1_cross, _mm1_info = _KC.crosscheck(
                    [{"event_id": "ev_mm1", "titles": ["洛克人1 X坐标对象表地址范围"]}],
                    mode="bm25", index_path=K.INDEX_JSON)
            finally:
                _KC.QUERY_LOG = _mm1_log_old
            _mm1_cr = _mm1_cross["ev_mm1"]
            _mm1_alias_bad = K.query_auto("洛克人10 的坐标轴方向是什么？", topk=3)
            raises(lambda: M1._append_log(_etd / "outside_mm1_log.jsonl", {}),
                   "知识库 [286b] 洛克人1候选日志拒绝写到候选目录外")
            ok(_mm1_cr.get("status") == "pass"
               and _mm1_cr.get("index_sha256") == _mm1_expected
               and _mm1_cr.get("auto_routing", {}).get("domains", [{}])[0].get("domain") == "megaman1"
               and len(_mm1_cr.get("selected_evidence") or []) == 1
               and _mm1_info.get("unanchored_downgraded") == 0
               and _KC.QUERY_LOG == _mm1_log_old
               and (_etd / "mm1_consumer_query_log.jsonl").is_file()
               and _mm1_alias_bad.get("backend") != "megaman1_candidate"
               and _mm1_alias_bad.get("auto_routing", {}).get("domains", [{}])[0].get("domain") == "unrouted"
               and _mm1_before == {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm1_inputs},
               "知识库 [286] Targeted 洛克人1消费闭环：内容域不降级、SHA与唯一证据透传，洛克人10不误路由且候选输入零写动")

            _mm1_manual_queries = (
                "洛克人1官方说明书里 A 键和 B 键分别控制什么动作？",
                "洛克人1 Energy Meter 监测的能量水平，受击与能量胶囊分别有什么影响？",
                "洛克人1官方说明书里 Magnet Beam 在哪个关卡出现，取得后能做什么？",
                "洛克人1官方说明书里六名 Robot Master 各自的设计用途或专长是什么？",
            )
            _mm1_manual_results = [K.query_auto(q, topk=5, fragment_policy="strict")
                                   for q in _mm1_manual_queries]
            ok(all(r.get("status") == "pass" and r.get("backend") == "megaman1_candidate"
                   and r.get("index_sha256") == _mm1_expected
                   and r.get("candidate_only") is True
                   and r.get("whole_game_knowledge_base") is False
                   and len(r.get("selected_evidence") or []) == 1
                   and r["selected_evidence"][0].get("source_id") == "archive_mega_man_nes_us_manual"
                   and r["selected_evidence"][0].get("status") == "verified_read"
                   and r["selected_evidence"][0].get("authority") == "authoritative"
                   and "mm1_manual_" in r["selected_evidence"][0].get("locator", "")
                   and (r["selected_evidence"][0].get("fragment_provenance") or {}).get("eligible") is True
                   for r in _mm1_manual_results),
               "知识库 [287] Targeted 洛克人1官方说明书：操作/能量/Magnet Beam/Robot Master均strict唯一出证且来源为扫描核验手册")
            _mm1_old_dir = M1.REPO_ROOT / "知识库P1_20261118" / "megaman1_candidate_20261125"
            _mm1_old_inputs = (_mm1_old_dir / "index.json", _mm1_old_dir / "corpus_map.json",
                               _mm1_old_dir / "sources.json")
            _mm1_old_before = {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm1_old_inputs}
            _mm1_inherited = (
                ("洛克人1 的坐标轴方向是什么？", "mm1_coordinate_facts_20261125.txt"),
                ("洛克人1 的 X 坐标对象表地址范围是什么？", "mm1_object_ram_table_20261125.txt"),
                ("BizHawk 为什么不能只每帧覆盖一次内存值，需要什么机制？", "mm1_bizhawk_memory_write_fact_20261125.txt"),
                ("洛克人1 写 $0480 和 $0600 为什么能移动角色？", "mm1_local_position_probe_excerpt_20261125.txt"),
            )
            _mm1_inherited_results = [K.query_auto(q, revision=M1.REVISION, topk=5)
                                      for q, _ in _mm1_inherited]
            _mm1_creation_refused = K.query_auto("洛克人1官方说明书是否记载角色创建系统？", topk=5)
            ok(all(r.get("status") == "pass" and len(r.get("selected_evidence") or []) == 1
                   and path in r["selected_evidence"][0].get("locator", "")
                   for r, (_, path) in zip(_mm1_inherited_results, _mm1_inherited))
               and _mm1_creation_refused.get("status") != "pass"
               and not _mm1_creation_refused.get("selected_evidence")
               and _mm1_old_before == {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm1_old_inputs},
               "知识库 [288] Targeted 洛克人1说明书扩展不回归：原坐标/BizHawk/定位题仍命中旧来源，角色创建仍拒答且旧候选零写动")
            _mm1_frozen = json.loads(M1.FROZEN_QUESTIONS.read_text(encoding="utf-8"))
            _mm1_frozen_index = K.load_index(M1.INDEX_PATH)
            _mm1_frozen_counts = {
                "total": len(_mm1_frozen["questions"]),
                "strict_pass": sum(q["expect"] == "strict_pass" for q in _mm1_frozen["questions"]),
                "refuse": sum(q["expect"] == "refuse" for q in _mm1_frozen["questions"]),
            }
            _mm1_chunks = {c["chunk_id"]: c for c in _mm1_frozen_index["chunks"]}
            _mm1_manual_reg = next((s for s in S.load_registry(M1.REGISTRY_PATH)["sources"]
                                    if s["source_id"] == "archive_mega_man_nes_us_manual"), {})
            _mm1_manual_source = json.loads((M1.CANDIDATE_DIR / "manual_source.json").read_text(encoding="utf-8"))
            ok(_mm1_frozen.get("status") == "frozen"
               and _mm1_frozen_counts == _mm1_frozen["expected_counts"]
               and _mm1_frozen["candidate_index_sha256"] == _mm1_expected
               and _mm1_manual_reg.get("status") == "verified_read"
               and _mm1_manual_reg.get("layer") == "official_manual"
               and _mm1_manual_source.get("full_manual_stored_in_candidate") is False
               and _mm1_manual_source.get("pdf_pages") == 10
               and len(_mm1_manual_source.get("excerpts") or []) == 8
               and not list(M1.CANDIDATE_DIR.rglob("*.pdf"))
               and all(q["gold"]["anchor_chunk"] in _mm1_chunks
                       and _mm1_chunks[q["gold"]["anchor_chunk"]]["source_id"] == "archive_mega_man_nes_us_manual"
                       for q in _mm1_frozen["questions"] if q.get("manual_pages")),
               "知识库 [289] Targeted 洛克人1说明书冻结契约：题数逐格守恒、手册金标可回溯、8个短摘录且完整PDF不入候选")

            _mm2_manual_queries = (
                ("洛克人2美版官方说明书里跳跃和射击：A 键和 B 键分别控制什么？", "mm2_manual_controls_", "A button is used for jumping"),
                ("洛克人2官方说明书里 STAGE SELECT 怎样用控制pad移动选择框，按 START 确认对手？", "mm2_manual_stage_select_", "flashing box"),
                ("洛克人2官方说明书里 Metal Blade 的投掷方向、数量和用途是什么？", "mm2_manual_weapons_", "best general purpose weapon"),
                ("洛克人2官方说明书里 Crash Bomber 有什么用途？", "mm2_manual_weapons_", "thrown at walls"),
            )
            _mm2_manual_results = [K.query_auto(q, topk=5, fragment_policy=policy)
                                   for q, _, _ in _mm2_manual_queries
                                   for policy in (None, "strict")]
            _mm2_manual_direct = M.ask(_mm2_manual_queries[0][0], mode="strict", production=True)
            ok(all(r.get("status") == "pass" and r.get("backend") == "megaman2"
                   and r.get("index_sha256") == M.expected_index_sha256()
                   and r.get("candidate_only") is True
                   and r.get("whole_game_knowledge_base") is False
                   and r.get("production_route_wired") is True
                   and len(r.get("selected_evidence") or []) == 1
                   and r["selected_evidence"][0].get("source_id") == M.MANUAL_SOURCE_ID
                   and r["selected_evidence"][0].get("revision") == M.MANUAL_REVISION
                   and r["selected_evidence"][0].get("status") == "verified_read"
                   and r["selected_evidence"][0].get("authority") == "authoritative"
                   and (policy != "strict" or
                        (r["selected_evidence"][0].get("fragment_provenance") or {}).get("eligible") is True)
                   and stem in r["selected_evidence"][0].get("locator", "")
                   and fact in r.get("answer_text", "")
                   for r, (_, stem, fact), policy in zip(
                       _mm2_manual_results,
                       [spec for spec in _mm2_manual_queries for _ in (None, "strict")],
                       [policy for _ in _mm2_manual_queries for policy in (None, "strict")]))
               and len(_mm2_manual_results) == 8
               and _mm2_manual_direct.get("status") == "pass"
               and _mm2_manual_direct.get("candidate_only") is True
               and len(_mm2_manual_direct.get("selected_evidence") or []) == 1,
               "知识库 [290] Targeted 洛克人2官方说明书：操作/选关/Metal Blade/Crash Bomber在自动路由default+strict唯一出证，direct同契约且仅限美国NES手册候选")
            _mm2_manual_pal = K.query_auto("洛克人2 PAL-B 官方说明书能直接照用吗？", topk=5)
            _mm2_manual_jp = K.query_auto("洛克人2 日版官方说明书里 Crash Bomber 有什么用途？", topk=5)
            _mm2_manual_rom = K.query_auto("MM2 美版ROM 的 walking speed 是什么？", topk=5)
            _mm2_manual_ntsc = K.query_auto("洛克人2 NTSC 官方说明书里 Crash Bomber 有什么用途？", topk=5)
            _mm2_manual_series = K.query_auto("洛克人的官方说明书里 Crash Bomber 有什么用途？", topk=5)
            _mm2_manual_moves = K.query_auto(
                "洛克人2 出招表", topk=5,
                index_path=_old_auto_k["INDEX_JSON"], map_path=_old_auto_k["CORPUS_MAP"],
                reg=S.load_registry(_old_auto_s))
            _mm2_manual_multi = K.query_auto(
                "洛克人2官方说明书里 Crash Bomber 有什么用途，以及拳皇98 出招表？", topk=5)
            _mm2_manual_entry = next((d for d in _mm2_manual_multi.get("domain_results") or []
                                      if d["domain"] == "megaman2"), {})
            ok(all(r.get("status") in {"miss", "inconclusive"}
                   and not r.get("selected_evidence") and not r.get("hits")
                   for r in (_mm2_manual_pal, _mm2_manual_jp, _mm2_manual_rom,
                             _mm2_manual_ntsc, _mm2_manual_series))
               and _mm2_manual_pal.get("reason_code") == "version_not_collected"
               and _mm2_manual_jp.get("reason_code") == "version_not_collected"
               and _mm2_manual_rom.get("reason_code") == "version_not_collected"
               and _mm2_manual_ntsc.get("reason_code") == "version_not_collected"
               and _mm2_manual_series.get("reason_code") == "ambiguous_series"
               and _mm2_manual_moves.get("status") == "miss"
               and _mm2_manual_moves.get("reason_code") == "move_list_not_collected"
               and not _mm2_manual_moves.get("selected_evidence")
               and _mm2_manual_multi.get("status") == "inconclusive"
               and _mm2_manual_multi.get("refusal") == "multi_domain_needs_split"
               and not _mm2_manual_multi.get("selected_evidence")
               and _mm2_manual_entry.get("status") == "pass"
               and len(_mm2_manual_entry.get("selected_evidence") or []) == 1
               and _mm2_manual_entry["selected_evidence"][0].get("source_id") == M.MANUAL_SOURCE_ID,
               "知识库 [291] Targeted 洛克人2版本与范围拒答：PAL/日版/美版ROM/单独NTSC/系列歧义零hit，出招表仍拒答，多域只留手册域证据")
            _mm2_frozen = json.loads(M.FROZEN_QUESTIONS.read_text(encoding="utf-8"))
            _mm2_frozen_index = K.load_index(M.INDEX_PATH)
            _mm2_frozen_counts = {
                "total": len(_mm2_frozen["questions"]),
                "strict_pass": sum(q["expect"] == "strict_pass" for q in _mm2_frozen["questions"]),
                "weak": sum(q["expect"] == "weak" for q in _mm2_frozen["questions"]),
                "refuse": sum(q["expect"] == "refuse" for q in _mm2_frozen["questions"]),
            }
            _mm2_chunks = {c["chunk_id"]: c for c in _mm2_frozen_index["chunks"]}
            _mm2_contract = json.loads(M.CONTRACT_PATH.read_text(encoding="utf-8"))
            _mm2_manual_reg = next((s for s in S.load_registry(M.REGISTRY_PATH)["sources"]
                                    if s["source_id"] == M.MANUAL_SOURCE_ID), {})
            _mm2_manual_source = json.loads((M.CANDIDATE_DIR / "manual_source.json").read_text(encoding="utf-8"))
            _mm2_old_dir = M.REPO_ROOT / "知识库P1_20261118" / "megaman2_candidate_20261125"
            _mm2_old_inputs = tuple(_mm2_old_dir / name for name in
                                    ("index.json", "corpus_map.json", "sources.json", "contract.json"))
            _mm2_v2_inputs = (M.INDEX_PATH, M.MAP_PATH, M.REGISTRY_PATH, M.CONTRACT_PATH, M.FROZEN_QUESTIONS)
            _mm2_old_before = {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm2_old_inputs}
            _mm2_v2_before = {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm2_v2_inputs}
            _mm2_old_contract = json.loads((_mm2_old_dir / "contract.json").read_text(encoding="utf-8"))
            from unittest.mock import patch
            with patch.multiple(M, CANDIDATE_DIR=_mm2_old_dir,
                                INDEX_PATH=_mm2_old_dir / "index.json",
                                MAP_PATH=_mm2_old_dir / "corpus_map.json",
                                REGISTRY_PATH=_mm2_old_dir / "sources.json",
                                CONTRACT_PATH=_mm2_old_dir / "contract.json",
                                expected_index_sha256=lambda: _mm2_old_contract["index_sha256"]):
                _mm2_old_results = [M.ask(q, mode=mode) for q in (
                    "洛克人2 的 walking speed 是什么？",
                    "Rockman 2 的 X speed 内存地址是什么？",
                    "MM2 的 jump Y speed 初始值是什么？",
                    "Mega Man 2 的 climbing speed 是什么？",
                    "Ｍｅｇａ　Ｍａｎ　２ 的 walking speed 是什么？",
                ) for mode in ("default", "strict")]
                with patch.object(M, "expected_index_sha256", lambda: "0" * 64):
                    _mm2_old_hash_bad = M.ask("洛克人2 的 walking speed 是什么？")
            with patch.object(M, "expected_index_sha256", lambda: "0" * 64):
                _mm2_v2_hash_bad = K.query_auto(
                    "洛克人2官方说明书里 Crash Bomber 有什么用途？", topk=5)
            ok(_mm2_frozen.get("status") == "frozen"
               and _mm2_frozen_counts == _mm2_frozen["expected_counts"]
               and _mm2_frozen["candidate_index_sha256"] == M.expected_index_sha256()
               and _mm2_contract.get("production_route_wired") is True
               and _mm2_manual_reg.get("status") == "verified_read"
               and _mm2_manual_reg.get("layer") == "official_manual"
               and _mm2_manual_source.get("full_manual_stored_in_candidate") is False
               and _mm2_manual_source.get("pdf_pages") == 20
               and len(_mm2_manual_source.get("excerpts") or []) == 8
               and not list(M.CANDIDATE_DIR.rglob("*.pdf"))
               and all(q["gold"]["anchor_chunk"] in _mm2_chunks
                       and _mm2_chunks[q["gold"]["anchor_chunk"]]["source_id"] == M.MANUAL_SOURCE_ID
                       for q in _mm2_frozen["questions"] if q.get("manual_pages"))
               and all(r.get("status") == "pass" and len(r.get("selected_evidence") or []) == 1
                       and r["selected_evidence"][0].get("source_id") == M.PRODUCTION_SOURCE_ID
                       and r["selected_evidence"][0].get("revision") == M.TECHNICAL_REVISION
                       and "megaman2_candidate_20261125" in r["selected_evidence"][0].get("locator", "")
                       for r in _mm2_old_results)
               and _mm2_old_hash_bad.get("refusal") == "candidate_hash_mismatch"
               and _mm2_v2_hash_bad.get("status") == "inconclusive"
               and _mm2_v2_hash_bad.get("reason_code") == "candidate_hash_mismatch"
               and not _mm2_v2_hash_bad.get("selected_evidence")
               and _mm2_old_before == {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm2_old_inputs}
               and _mm2_v2_before == {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in _mm2_v2_inputs},
               "知识库 [292] Targeted 洛克人2说明书冻结与旧候选回归：25题金标可回溯、8短摘录无PDF、旧技术题双臂全过、哈希失败关闭且新旧候选零写动")

            _mm2_tech_specs = (
                ("洛克人2 X 坐标向哪个方向增加？", "mm2_tasvideos_coordinates_20261125.txt", "right"),
                ("洛克人2 跳跃时 Y speed 初始值是什么？", "mm2_tasvideos_jump_20261125.txt", "04.DF"),
                ("洛克人2 攀爬速度是多少？", "mm2_tasvideos_climb_transform_20261125.txt", "00.C0"),
                ("洛克人2 跳跃时 X speed 是什么？", "mm2_tasvideos_jump_horizontal_20261125.txt", "01.50"),
                ("洛克人2 步行速度是多少？", "mm2_tasvideos_walking_20261125.txt", "01.60"),
                ("洛克人2 从静止加速需要多少帧？", "mm2_tasvideos_acceleration_20261125.txt", "7 frames"),
                ("洛克人2 从全速停止需要多少帧？", "mm2_tasvideos_acceleration_20261125.txt", "8 (decimal) frames"),
                ("洛克人2 Xspd 内存地址范围是什么？", "mm2_tasvideos_object_table_20261125.txt", "$600:$620"),
            )
            _mm2_tech_kw = {"index_path": old_k["INDEX_JSON"], "map_path": old_k["CORPUS_MAP"],
                            "reg": S.load_registry(old_s["REG_JSON"])}
            _mm2_tech_results = [K.query_auto(q, topk=5, **_mm2_tech_kw)
                                 for q, _, _ in _mm2_tech_specs]
            ok(all(r.get("status") == "pass" and r.get("backend") == "megaman2"
                   and r.get("index_sha256") == _sha(old_k["INDEX_JSON"])
                   and r.get("candidate_only") is False
                   and r.get("whole_game_knowledge_base") is False
                   and r.get("production_route_wired") is True
                   and len(r.get("selected_evidence") or []) == 1
                   and r["selected_evidence"][0].get("source_id") == M.PRODUCTION_SOURCE_ID
                   and r["selected_evidence"][0].get("revision") == M.TECHNICAL_REVISION
                   and stem in r["selected_evidence"][0].get("locator", "")
                   and fact in r.get("answer_text", "")
                   for r, (_, stem, fact) in zip(_mm2_tech_results, _mm2_tech_specs))
               and len({r["selected_evidence"][0]["locator"].split("#L", 1)[0]
                        for r in _mm2_tech_results}) == 7,
               "知识库 [293] Targeted 洛克人2生产技术七文件：坐标/跳跃Y/攀爬/跳跃X/步行/加减速/对象表逐文件命中，唯一出证且不冒充地区ROM等价")

            _v2db = _etd / "legacy_v2.db"
            _v2schema = Path(KE.__file__).resolve().parent / "游戏包" / "电竞事实库" / "schema_v2.sql"
            _vc = sqlite3.connect(_v2db)
            _vc.executescript(_v2schema.read_text(encoding="utf-8"))
            _vc.execute("insert into entity values('lol:champion:Old','game_character','lol','旧英雄')")
            _vc.commit()
            _vc.close()
            KE.init_db(_v2db)
            KE.init_db(_v2db)
            _vc = sqlite3.connect(_v2db)
            _mver = _vc.execute("select schema_version from schema_meta").fetchone()[0]
            _ment = _vc.execute("select canonical_name from entity where entity_id=?",
                                ("lol:champion:Old",)).fetchone()[0]
            _mfk = len(_vc.execute("pragma foreign_key_check").fetchall())
            _vc.execute("insert into entity values('lol:item:OldItem','game_item','lol','旧物品')")
            _vc.commit()
            _vc.close()
            ok(_mver == "v3" and _ment == "旧英雄" and _mfk == 0,
               "知识库 [218] v2→v3 在线迁移：原实体保留、外键零异常、新类型可写且重复初始化幂等")
            from . import kb_coverage as KC
            _cov_eval = _etd / "coverage_eval.json"
            _cov_eval.write_text(json.dumps({
                "questions": [{"q": "英雄联盟 世界冠军", "base": {"grade": {"ok": True}}}],
                "summary": {"base_v2_ok": 1, "modes": {}}}, ensure_ascii=False),
                encoding="utf-8")
            _cov_before = {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in
                           (K.INDEX_JSON, KE.DB_PATH)}
            _cov = KC.collect(db_path=KE.DB_PATH, eval_path=_cov_eval)
            _cov_after = {str(p): (p.stat().st_mtime_ns, _sha(p)) for p in
                          (K.INDEX_JSON, KE.DB_PATH)}
            ok(_cov_before == _cov_after and not _cov["errors"]
               and _cov["esports"]["schema"] == "v3"
               and _cov["esports"]["entity_evidence"]["game_character"]["evidence"] == 2
               and _cov["esports"]["entity_evidence"]["game_item"]["evidence"] == 1
               and _cov["esports"]["entity_evidence"]["game_spell"]["evidence"] == 1
               and all(n == 0 for n in _cov["esports"]["dynamic_tables"].values())
               and all(r["state"] in KC.STATES for r in _cov["rows"])
               and _cov["domain_evaluation"] == [
                   {"domain": "esports_lol", "questions": 1, "base_correct": 1, "rate": 1.0}]
               and all("questions" not in r for r in _cov["rows"])
               and "未获明确许可" in KC.render(_cov),
               "知识库 [219] 覆盖看板：只读生产聚合文本+三类电竞证据；动态表0不冒充真实覆盖；域级评测不重复摊到知识类型；输入mtime+sha不变")
            _econ = sqlite3.connect(KE.DB_PATH)
            _econ.execute("update source_policy set automated_access='denied' "
                          "where source_id='E02'")
            _econ.commit()
            _econ.close()
            raises(lambda: KE.import_ddragon(offline_dir=_off),
                   "知识库 [158] 权限闸门反证：automated_access=denied 时导入被拦")

            # ---- 阶段一第3–5天：双时间硬过滤（合成夹具仅用于时效/故障测试，计划§6明文；
            #      不冒充真实赛果覆盖，真实赛果仍记0待授权） ----
            _econ = sqlite3.connect(KE.DB_PATH)
            _es_con = _econ
            _econ.row_factory = sqlite3.Row
            _econ.execute("PRAGMA foreign_keys = ON")
            for _eid, _et, _cn in (("lol:person:TestP", "person", "测试选手"),
                                   ("lol:person:TestP2", "person", "测试选手乙"),
                                   ("lol:club:TeamA", "club", "甲队"),
                                   ("lol:club:TeamB", "club", "乙队")):
                _econ.execute("insert into entity values(?,?,?,?)",
                              (_eid, _et, "lol", _cn))
            _econ.execute("insert into competition(competition_id,game_id,season,region) "
                          "values('FIXTURE:comp','lol','2026','CN')")
            _econ.execute("insert into stage(stage_id,competition_id,stage_name) "
                          "values('FIXTURE:stage','FIXTURE:comp','常规赛')")
            _fxstate = _etd / "fixture_state.json"
            _fxstate.write_text('{"fixture": true}', encoding="utf-8")
            _econ.execute(
                "insert into source_snapshot(snapshot_id,source_id,original_url,"
                "fetched_at,content_sha256,storage_ref,parser_version,fetch_status) "
                "values('FIXTURE:state','E02','fixture://state',"
                "'2026-11-21T00:00:00Z',?,?,'fixture','ok')",
                (_sha(_fxstate), str(_fxstate)))

            def _mkev(evid, locator, payload):
                canon = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                _econ.execute(
                    "insert into evidence_block(evidence_id,snapshot_id,locator_type,"
                    "locator,exact_text_or_value,content_hash,language,authority_scope,"
                    "verification_status,retraction_status) values(?,?,?,?,?,?,?,?,?,?)",
                    (evid, "FIXTURE:state", "json_pointer", locator, canon,
                     hashlib.sha256(canon.encode()).hexdigest(), "zh_CN",
                     "fixture_synthetic", "verified", "active"))

            def _bind(rv, field, evid):
                _econ.execute("insert into fact_support values(?,?,?,?,?)",
                              (rv, field, evid, "states", "verified"))

            def _mkseries(sid, rv, status, winner, sa, sb, rec, sup=None,
                          rstatus="active"):
                _econ.execute(
                    "insert into series(series_id,stage_id,team_a_id,team_b_id,"
                    "best_of,status,winner_id,score_a,score_b,result_method,"
                    "row_version_id,logical_record_id,valid_from,start_bound_kind,"
                    "end_bound_kind,time_precision,recorded_at,superseded_at,"
                    "last_verified_at,verification_basis,record_status) "
                    "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, "FIXTURE:stage", "lol:club:TeamA", "lol:club:TeamB", 3,
                     status, winner, sa, sb, None, rv, sid, "2026-10-01T00:00:00Z",
                     "exact", "open", "second", rec, sup, "2026-11-01T00:00:00Z",
                     "fixture", rstatus))

            _mkseries("S1", "S1:v1", "completed", "lol:club:TeamA", 2, 0,
                      "2026-11-01T00:00:00Z", "2026-11-05T00:00:00Z", "superseded")
            _mkseries("S1", "S1:v2", "completed", "lol:club:TeamB", 1, 2,
                      "2026-11-05T00:00:00Z")
            _mkev("evS1v1", "/series/S1/v1", {"winner": "TeamA", "score": "2:0"})
            _mkev("evS1v2", "/series/S1/v2", {"winner": "TeamB", "score": "1:2"})
            _bind("S1:v1", "winner_id", "evS1v1")
            _bind("S1:v2", "winner_id", "evS1v2")
            _econ.commit()
            _qs = KE.query_series("S1")
            _qr = KE.query_series("S1", knowledge_as_of="2026-11-03T00:00:00Z")
            _qb = KE.query_series("S1", knowledge_as_of="2026-11-05T00:00:00Z")
            ok(_qs["status"] == "pass"
               and _qs["claim"]["value"]["winner_id"] == "lol:club:TeamB"
               and _qs["dataset_revision"] == "S1:v2"
               and len(_qs["selected_evidence"]) == 1
               and _qr["status"] == "pass"
               and _qr["claim"]["value"]["winner_id"] == "lol:club:TeamA"
               and _qr["dataset_revision"] == "S1:v1"
               and _qb["dataset_revision"] == "S1:v2"
               and "历史事件" in _qs["claim"]["conditions"]["fact_kind"],
               "知识库 [159] 修订链：当前查询用修正版；knowledge_as_of回放旧版；superseded_at当刻边界归新版")
            _mkseries("S2", "S2:v1", "cancelled", "lol:club:TeamA", 1, 0,
                      "2026-11-02T00:00:00Z")
            _mkseries("S3", "S3:v1", "pending", None, 0, 0,
                      "2026-11-02T00:00:00Z")
            _econ.commit()
            _qc = KE.query_series("S2")
            _qpd = KE.query_series("S3")
            ok(_qc["status"] == "inconclusive"
               and _qc["reason_code"] == "result_not_final"
               and _qc["selected_evidence"] == []
               and "不从比分推断" in _qc["answer_text"]
               and _qpd["status"] == "inconclusive"
               and _qpd["reason_code"] == "result_not_final",
               "知识库 [160] 赛果状态反证：cancelled/pending不pass，winner字段有值也不从比分推断")
            _mkseries("S4", "S4:v1", "completed", "lol:club:TeamA", 2, 0,
                      "2026-11-03T00:00:00Z")
            _mkev("evS4", "/series/S4", {"winner": "TeamA"})
            _bind("S4:v1", "winner_id", "evS4")
            _econ.execute("update evidence_block set retraction_status='retracted' "
                          "where evidence_id='evS4'")
            _mkseries("S5", "S5:v1", "completed", "lol:club:TeamA", 2, 0,
                      "2026-11-03T00:00:00Z")
            _econ.commit()
            _q4 = KE.query_series("S4")
            _q5 = KE.query_series("S5")
            ok(_q4["status"] == "inconclusive"
               and _q4["reason_code"] == "no_evidence_bound"
               and _q5["status"] == "inconclusive"
               and _q5["reason_code"] == "no_evidence_bound",
               "知识库 [161] 证据资格反证：撤稿证据/未绑定字段都不pass")
            raises(lambda: KE.select_versions(
                       _econ, "series", {"winner_id": "lol:club:TeamA"}),
                   "知识库 [162] 选择器白名单反证：非白名单过滤列被拒（注入面），表名同样走白名单")

            def _mkmem(mid, pid, tid, rv, vf, vt, ebk, rec):
                _econ.execute(
                    "insert into membership(membership_id,person_id,team_id,"
                    "membership_type,status,row_version_id,logical_record_id,"
                    "valid_from,valid_to,start_bound_kind,end_bound_kind,"
                    "time_precision,recorded_at,superseded_at,last_verified_at,"
                    "verification_basis,record_status) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (mid, pid, tid, "contract", "active", rv, mid, vf, vt,
                     "exact", ebk, "day", rec, None, "2026-11-01T00:00:00Z",
                     "fixture", "active"))

            _mkmem("M1", "lol:person:TestP", "lol:club:TeamA", "M1:v1",
                   "2026-01-01", "2026-06-01", "exact", "2026-01-02T00:00:00Z")
            _mkev("evM1", "/membership/M1", {"person": "TestP", "team": "TeamA"})
            _bind("M1:v1", "team_id", "evM1")
            _econ.commit()
            _qcur = KE.query_membership("测试选手")
            _qhist = KE.query_membership("测试选手", as_of="2026-03-01")
            ok(_qcur["status"] == "inconclusive"
               and _qcur["reason_code"] == "stale_state"
               and "无法确认当前阵容" in _qcur["answer_text"]
               and _qcur["selected_evidence"] == []
               and len(_qcur["historical_only"]) == 1
               and _qhist["status"] == "pass"
               and len(_qhist["selected_evidence"]) == 1
               and _qhist["claim"]["value"]["team"] == "甲队"
               and _qhist["claim"]["conditions"]["as_of"] == "2026-03-01",
               "知识库 [163] 阵容时效陷阱对：只有旧闭区间名单→现状拒冒充；同库历史as_of查询pass（正对照）")
            _mkmem("M2", "lol:person:TestP2", "lol:club:TeamA", "M2:v1",
                   "2026-01-01", None, "unknown", "2026-01-02T00:00:00Z")
            _mkev("evM2", "/membership/M2", {"person": "TestP2", "team": "TeamA"})
            _bind("M2:v1", "team_id", "evM2")
            _econ.commit()
            _qu = KE.query_membership("测试选手乙")
            _econ.execute("update membership set end_bound_kind='open' "
                          "where membership_id='M2'")
            _econ.commit()
            _qo = KE.query_membership("测试选手乙")
            _qedge = KE.query_membership("测试选手", as_of="2026-06-01")
            _qin = KE.query_membership("测试选手", as_of="2026-05-31")
            ok(_qu["status"] == "inconclusive" and _qu["reason_code"] == "stale_state"
               and _qo["status"] == "pass"
               and _qedge["status"] == "miss"
               and _qedge["reason_code"] == "no_record_valid_at"
               and _qin["status"] == "pass",
               "知识库 [164] 结束未知≠开放反证+区间左闭右开：as_of=valid_to已无效、前一日有效")
            _econ.execute(
                "insert into transfer_event(transfer_id,person_id,from_team_id,"
                "to_team_id,move_type,event_status,announced_at,effective_at,"
                "row_version_id,logical_record_id,valid_from,start_bound_kind,"
                "end_bound_kind,time_precision,recorded_at,record_status) "
                "values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("T1", "lol:person:TestP2", "lol:club:TeamA", "lol:club:TeamB",
                 "transfer", "announced", "2026-11-20", "2099-12-20", "T1:v1", "T1",
                 "2026-11-20", "exact", "open", "day", "2026-11-20T00:00:00Z",
                 "active"))
            _econ.commit()
            _qt = KE.query_membership("测试选手乙")
            ok(_qt["status"] == "pass" and _qt["claim"]["value"]["team"] == "甲队"
               and "官宣" in _qt["answer_text"]
               and "尚未生效" in _qt["answer_text"]
               and "乙队" in _qt["answer_text"],
               "知识库 [165] 官宣≠生效：未来生效的官宣转会不会切换当前归属，只进附注")
            _econ.execute("insert into patch(patch_id,game_id,patch_label) "
                          "values('P-16.20','lol','16.20.1')")
            _econ.execute("insert into patch(patch_id,game_id,patch_label) "
                          "values('P-16.23','lol','16.23.1')")

            def _mkgame(gid, pid):
                _econ.execute(
                    "insert into game_result(game_result_id,series_id,game_number,"
                    "status,score_unit,patch_id,team_a_id,team_b_id,score_a,score_b,"
                    "winner_id,row_version_id,logical_record_id,recorded_at,"
                    "record_status) values(?,?,1,'completed','map_rounds',?,?,?,?,?,?,?,?, "
                    "'2026-10-01T00:00:00Z','active')",
                    (gid, "S1", pid, "lol:club:TeamA", "lol:club:TeamB",
                     13, 7, "lol:club:TeamA", gid + ":v1", gid))

            _mkgame("G1", "P-16.20")
            _mkgame("G2", None)
            _econ.execute(
                "insert into patch_deployment(deployment_id,patch_id,region,"
                "server_type,deployed_at,row_version_id,recorded_at,record_status) "
                "values('D1','P-16.23','GLOBAL','public','2026-11-01','D1:v1',"
                "'2026-11-01T00:00:00Z','active')")
            _econ.commit()
            _pg1 = KE.patch_for_game("G1")
            _pg2 = KE.patch_for_game("G2")
            ok(_pg1 and _pg1["patch_id"] == "P-16.20"
               and _pg1["source"] == "game_result.patch_id" and _pg2 is None,
               "知识库 [166] 赛事补丁硬过滤：只认当局记录补丁，公网更新补丁不顶替；未记录返回None诚实")
            _lv_before = [tuple(r) for r in _econ.execute(
                "select membership_id,last_verified_at from membership "
                "order by membership_id").fetchall()]
            _ss_before = [tuple(r) for r in _econ.execute(
                "select snapshot_id,fetched_at,fetch_status from source_snapshot "
                "where fetch_status='ok' order by snapshot_id").fetchall()]
            _sid = KE.log_refresh_failure("E02", "https://example.invalid/roster.json")
            _lv_after = [tuple(r) for r in _econ.execute(
                "select membership_id,last_verified_at from membership "
                "order by membership_id").fetchall()]
            _ss_after = [tuple(r) for r in _econ.execute(
                "select snapshot_id,fetched_at,fetch_status from source_snapshot "
                "where fetch_status='ok' order by snapshot_id").fetchall()]
            _err = _econ.execute("select fetch_status from source_snapshot "
                                 "where snapshot_id=?", (_sid,)).fetchone()[0]
            ok(_err == "error" and _lv_before == _lv_after
               and _ss_before == _ss_after,
               "知识库 [167] 刷新失败只留痕：last_verified_at与既有ok快照逐字节一致，失败不刷核验时间")
            _econ.close()
    finally:
        if _es_con is not None:
            try:
                _es_con.close()
            except Exception:
                pass
        for k, v in _old_es.items():
            setattr(KE, k, v)
        for k, v in _old_auto_k.items():
            setattr(K, k, v)
        S.REG_JSON = _old_auto_s

    _unrouted_auto = [K.query_auto(q, topk=3) for q in
                      ("未登记游戏 的 walking speed 是什么？", "walking speed 是什么？")]
    _unrouted_manual = K.query("walking speed 是什么？", topk=3)
    _routed_control = K.query_auto("洛克人2 的 walking speed 是什么？", topk=3, **_mm2_kw)
    ok(all(r.get("status") == "inconclusive" and r.get("refusal") == "unanchored"
           and r.get("reason_code") == "unanchored" and r.get("auto_unanchored") is True
           and not r.get("selected_evidence") and r.get("hits")
           for r in _unrouted_auto)
       and _unrouted_manual.get("status") == "pass"
       and len(_unrouted_manual.get("selected_evidence") or []) == 1
       and _routed_control.get("status") == "pass",
       "知识库 [282] 自动路由恒量反证：unrouted全库假pass清空出证并拒答，手动全库与已锚定生产正例不受影响")
    _mm2_temp.cleanup()

    for p in _es_real:
        key = str(p)
        now = (p.stat().st_mtime_ns, _sha(p)) if p.is_file() \
            else ("dir", sorted(x.name for x in p.iterdir())) if p.is_dir() else None
        ok(now == _es_before[key],
           f"知识库 [反查] 电竞真实件未被探针写动 {p.name}（状态一致）")

    # ── 阶段3 最小证据选择器（候选层）：五类事实+七项核查+反例套件 ──
    # 纯合成夹具，零文件写入；不改 kb.query 默认。权威规格=评审路线 §阶段3。
    from . import kb_selector as KS
    from . import kb_answer as KA
    _tok = K.tokens
    _AUTH = {"authority": "authoritative", "status": "verified_read", "revision_match": True}
    _GOLD = "| 燕返 | つばめがえし | 带球跳跃立即出现(空中翻跟头) | 仅 Yoritsune 原生；秘技后全员 |"
    _METHOD = ("现状改成 untested。真采 23 必杀仍需正对照：先按三条铁律重跑触发链。"
               "秘技在联盟实测无燕返翻转（probe18 三段对照）。联盟采集改走角色原生必杀。"
               "旋转球≠必杀签名：OAM 签名相同。球坐标改用画面白色团块追踪。"
               "通用技（燕返/爆裂等）非原生者标 honest gap。每要素 trigger 宏 + dump 正例帧 + 反例。")
    _Q02 = "热血队内，燕返原生只有哪个角色会使？"

    def _hit(cid, meta=None, snippet=""):
        h = {"chunk_id": cid, "snippet": snippet}
        h.update(meta or _AUTH)
        return h

    def _sel(q, pairs, window=3):
        hits = [_hit(cid, meta) for cid, _, meta in pairs]
        texts = {cid: txt for cid, txt, _ in pairs}
        return KS.select(q, hits, texts, _tok, production_window=window)

    _r = _sel(_Q02, [("gold", _GOLD, _AUTH)])
    ok(_r["verdict"] == "pass" and _r["selected"] == "gold"
       and _r["fact_class"] == "role_attribution" and _r["parsed"]["exclusivity"]
       and _r["parsed"]["scope"] == "team" and _r["parsed"]["state_native"]
       and not _r["beyond_window"],
       "知识库 [168] 选择器正对照：金表行过七项核查被选中（排他/队内/原生条件正确解析）")

    _r = _sel(_Q02, [("method", _METHOD, _AUTH)])
    _mc = _r["per_block"][0]["checks"]
    ok(_r["verdict"] == "inconclusive" and not _mc["attribute_match"]
       and _mc["source_eligibility"],
       "知识库 [169] 方法学段不得承担归属出证：来源资格够但无归属行被拒（Q02 病假）")
    _am = KA.annotate(_Q02, _METHOD, _tok)
    _ag = KA.annotate(_Q02, _GOLD, _tok)
    ok(not _am["answerable"] and not _am["exclusive_attribution_ok"]
       and _ag["answerable"] and _ag["exclusive_attribution_ok"],
       "知识库 [169b] 生产初筛同步排他归属：方法学段有原生词但无同行排他归属被拒；金表同项恒量正对照放行")

    _r = _sel(_Q02, [("weak", "Yoritsune 会使燕返。", _AUTH)])
    ok(_r["verdict"] == "inconclusive"
       and not _r["per_block"][0]["checks"]["polarity"],
       "知识库 [170] 『会使』≠『只有他会』：排他问无仅/只有标志被肯否关拒")
    _r2 = _sel(_Q02, [("gold", _GOLD, _AUTH)])
    ok(_r2["verdict"] == "pass" and _r2["selected"] == "gold",
       "知识库 [170b] 恒量正对照：同块补『仅』即过肯否关（证明拒的是排他形态不是块本身）")

    _pref = KS.select(_Q02, [_hit("first"), _hit("incumbent")],
                      {"first": "燕返 仅 甲 原生。", "incumbent": "燕返 仅 Yoritsune 原生。"},
                      _tok, preferred_chunk_id="incumbent")
    ok(_pref["verdict"] == "pass" and _pref["selected"] == "incumbent",
       "知识库 [170c] 已有合格证据优先：两个块都过核查时保留 incumbent，不无理由换证")
    _blocked = dict(_hit("gold"), answerability={"answerable": False})
    _r = KS.select(_Q02, [_blocked], {"gold": _GOLD}, _tok)
    ok(_r["verdict"] == "inconclusive"
       and _r["per_block"][0]["checks"].get("initial_screen") is False,
       "知识库 [170d] 初筛反证：生产可答性已拒的块不得被选择器单独救活")

    _wrong = "| 燕返 | つばめがえし | 带球跳跃 | 仅 错误角色 原生；秘技后全员 |"
    _r = _sel(_Q02, [("wrongchar", _wrong, _AUTH), ("gold", _GOLD, _AUTH)])
    _eval_fail = _r["selected"] == "wrongchar" and "Yoritsune" not in _wrong
    ok(_r["selected"] == "wrongchar" and _eval_fail,
       "知识库 [171] 同技能错角色：选择器 mechanics 放行但金标角色核对判失败（评估层必须抓住）")

    _r = _sel(_Q02, [("wrongskill", "Yoritsune 仅原生会龙卷拳，秘技后全员。", _AUTH)])
    ok(_r["verdict"] == "inconclusive"
       and not _r["per_block"][0]["checks"]["subject_match"],
       "知识库 [172] 同角色错技能：问燕返而块只归属龙卷拳，主体一致关拒")

    _r = _sel("热血队有几人会燕返？", [("other", "巴西队有 3 人会燕返。", _AUTH)])
    ok(_r["fact_class"] == "count" and _r["verdict"] == "inconclusive"
       and not _r["per_block"][0]["checks"]["condition_coverage"],
       "知识库 [173] 同单位错对象：问热血队而块答巴西队，队内范围关拒")
    _r2 = _sel("热血队有几人会燕返？", [("own", "热血队有 3 人会燕返。", _AUTH)])
    ok(_r2["verdict"] == "pass",
       "知识库 [173b] 恒量正对照：同数量改热血队即过（证明拒的是范围不是数字）")

    _hex = "a" * 40
    _r = _sel("甲号 ROM 的 SHA1 指纹是多少？",
              [("wrongfile", f"乙号文件 指纹 {_hex}", _AUTH)])
    ok(_r["fact_class"] == "exact_value" and _r["verdict"] == "inconclusive"
       and not _r["per_block"][0]["checks"]["value_attribution"],
       "知识库 [174] 同哈希错文件：40位哈希在但对象词是乙号不是甲号，数值归属关拒")
    _r2 = _sel("甲号 ROM 的 SHA1 指纹是多少？",
               [("rightfile", f"甲号文件 指纹 {_hex}", _AUTH)])
    ok(_r2["verdict"] == "pass",
       "知识库 [174b] 恒量正对照：同哈希改甲号文件即过（证明拒的是对象不是哈希形态）")

    _r = _sel(_Q02, [("wrongrev", _GOLD, dict(_AUTH, revision_match=False))])
    ok(_r["verdict"] == "inconclusive"
       and not _r["per_block"][0]["checks"]["source_eligibility"],
       "知识库 [175] 同游戏错版本：revision_match=False 来源资格关拒")

    _r = _sel("双人合作模式下二号玩家操作什么位置？",
              [("wrongmode", "对战模式 2P 操作 MF。", _AUTH)])
    ok(_r["fact_class"] == "player_role" and _r["verdict"] == "inconclusive"
       and not _r["per_block"][0]["checks"]["condition_coverage"],
       "知识库 [176] 同玩家错模式：问合作而块答对战，条件覆盖关拒")
    _r2 = _sel("双人合作模式下二号玩家操作什么位置？",
               [("wrongplayer", "双人合作 1P 操作 GK。", _AUTH)])
    ok(_r2["verdict"] == "inconclusive",
       "知识库 [176b] 同模式错玩家：问二号而块答1P，玩家编号关拒")
    _r3 = _sel("双人合作模式下二号玩家操作什么位置？",
               [("right", "双人合作 2P 操作 GK。", _AUTH)])
    ok(_r3["verdict"] == "pass",
       "知识库 [176c] 恒量正对照：合作+2P+GK 同行即过")

    _r = _sel("燕返无法被门将使用吗？", [("affirm", "门将可以使用燕返。", _AUTH)])
    ok(_r["verdict"] == "inconclusive"
       and not _r["per_block"][0]["checks"]["polarity"],
       "知识库 [177] 肯否互换：否定问而块给肯定证据，肯否关拒")
    _r2 = _sel("燕返无法被门将使用吗？", [("neg", "门将无法使用燕返。", _AUTH)])
    ok(_r2["verdict"] == "pass",
       "知识库 [177b] 恒量正对照：同块改否定即过")

    _r = _sel(_Q02, [("retracted", _GOLD, dict(_AUTH, status="retracted"))])
    ok(_r["verdict"] == "inconclusive"
       and not _r["per_block"][0]["checks"]["source_eligibility"],
       "知识库 [178] 撤回旧结论：status=retracted 来源资格关拒（不冒充已验证）")

    _r = _sel(_Q02, [("method", _METHOD, _AUTH), ("gold", _GOLD, _AUTH)], window=1)
    ok(_r["verdict"] == "pass" and _r["selected"] == "gold"
       and _r["selected_rank"] == 2 and _r["beyond_window"],
       "知识库 [179] 正确块在列表但低分位：方法学第1被拒、金表第2被选中，beyond_window 标记策略调整（不偷翻默认）")

    _r = _sel("为什么燕返的触发窗口在最高点？", [("gold", _GOLD, _AUTH)])
    ok(_r["fact_class"] is None and _r["verdict"] == "inconclusive"
       and _r["selected"] is None,
       "知识库 [180] 复杂问题（因果）：不强行归类，返回材料+缺口不下结论")

    _brazil = "巴西队 ぶーにょ 速度很快，频繁使用燕返。"
    _r = _sel("全游戏唯一会使燕返的角色是谁？",
              [("gold", _GOLD, _AUTH), ("brazil", _brazil, _AUTH)])
    ok(_r["parsed"]["scope"] == "all" and _r["verdict"] == "inconclusive"
       and "brazil" in _r["counterexample_blocks"],
       "知识库 [181] 全游戏排他反证：巴西 Bûnyo 使用块推翻『全游戏唯一』主张，整问拒答")
    _r2 = _sel(_Q02, [("gold", _GOLD, _AUTH), ("brazil", _brazil, _AUTH)])
    ok(_r2["verdict"] == "pass" and _r2["selected"] == "gold"
       and not _r2["counterexample_blocks"],
       "知识库 [182] 队内范围恒量正对照：同巴西块在队内问下不构成反证，金表仍被选中")

    # 真实 Q02 候选（只读生产索引，不改默认）：问框架退评分后金表升至首位。
    _q02r = K.query(_Q02, game="nekketsu_soccer2", topk=30)
    _idx = K.load_index()
    _texts = {c["chunk_id"]: c["text"] for c in _idx["chunks"]}
    _cs = KS.select(_Q02, _q02r.get("hits", []), _texts, _tok, production_window=3)
    _gp = next((p for p in _cs["per_block"] if p["chunk_id"] == "f7f8e8316295"), None)
    _mp = next((p for p in _cs["per_block"] if p["chunk_id"] == "8996c7a159ef"), None)
    ok(_cs["verdict"] == "pass" and _cs["selected"] == "f7f8e8316295"
       and _cs["selected_rank"] == 1 and not _cs["beyond_window"]
       and _gp and _gp["checks"]["eligible"]
       and _mp and not _mp["checks"]["attribute_match"]
       and _q02r.get("status") == "pass"
       and [h["chunk_id"] for h in _q02r.get("selected_evidence", [])] == ["f7f8e8316295"]
       and _q02r["query_term_filter"]["mode"] == "attribution",
       "知识库 [183] 真实Q02修复：问框架退评分后金表第1位过七项核查，生产默认pass且方法学段仍被拒")

    _q02_default = K.query(_Q02, game="nekketsu_soccer2", topk=30)
    _q02_audit = K.query(_Q02, game="nekketsu_soccer2", topk=30, fact_selector="audit")
    _q02_scoped = K.query(_Q02, game="nekketsu_soccer2", topk=30, fact_selector="scoped")
    _q02_beyond = K.query(_Q02, game="nekketsu_soccer2", topk=30,
                          fact_selector="scoped", selector_beyond_window=True)
    ok(_q02_default["status"] == "pass" and "fact_selector" not in _q02_default
       and [h["chunk_id"] for h in _q02_default.get("selected_evidence", [])] == ["f7f8e8316295"],
       "知识库 [189] 生产默认修复：未启用选择器时 Q02 已由生产可答性直接判 pass，证据恰为金表")
    ok(_q02_audit["status"] == "pass"
       and [h["chunk_id"] for h in _q02_audit.get("selected_evidence", [])] == ["f7f8e8316295"]
       and _q02_audit["fact_selector"]["verdict"] == "pass"
       and _q02_audit["fact_selector"]["selected"] == "f7f8e8316295"
       and not _q02_audit["fact_selector"]["beyond_window"],
       "知识库 [190] audit 只报告不改判：看见窗口内金表后保留生产 pass/同一证据")
    ok(_q02_scoped["status"] == "pass"
       and [h["chunk_id"] for h in _q02_scoped.get("selected_evidence", [])] == ["f7f8e8316295"]
       and _q02_scoped["fact_selector"]["selected_rank"] == 1
       and not _q02_scoped["fact_selector"]["beyond_window"],
       "知识库 [191] scoped 窗口内正对照：金表已在 top3，无需扩窗即可放行")
    ok(_q02_beyond["status"] == "pass"
       and [h["chunk_id"] for h in _q02_beyond.get("selected_evidence", [])] == ["f7f8e8316295"]
       and not _q02_beyond["fact_selector"]["beyond_window"]
       and "显式允许跨出 top_window" not in _q02_beyond.get("condition", ""),
       "知识库 [192] 显式扩窗边界：候选本就在窗口内时不伪报跨窗，仍保持 pass/金表")
    _Q03 = "热血足球2 暂停秘技的按键输入是什么？"
    _q03 = K.query(_Q03, game="nekketsu_soccer2", topk=30)
    _q03_gold_rank = next((i for i, h in enumerate(_q03.get("hits", []), 1)
                          if h["chunk_id"] == "42b773880ef0"), None)
    ok(_q03["status"] == "pass"
       and [h["chunk_id"] for h in _q03.get("selected_evidence", [])] == ["42b773880ef0"]
       and _q03_gold_rank and _q03_gold_rank <= 3
       and _q03.get("query_term_filter", {}).get("mode") == "input_sequence",
       f"知识库 [197] 真实Q03修复：标题词退评分后按键序列金表第{_q03_gold_rank}位，生产默认pass")
    _seq_ok = K.annotate(_Q03, "Start暂停→A×3 B×1 A×3 B×1 A×7→Start", K.tokens)
    _seq_short = K.annotate(_Q03, "Start暂停→A×3→Start", K.tokens)
    _seq_none = K.annotate(_Q03, "Start暂停后使用必杀技。", K.tokens)
    ok(_seq_ok["input_sequence_ok"] and not _seq_short["input_sequence_ok"]
       and not _seq_none["input_sequence_ok"],
       "知识库 [198] 按键输入证据形态恒量反证：完整A/B计数序列通过，单A计数与纯方法描述被拒")
    _Q06 = "热血足球联盟每队上场几名球员？"
    _q06_suite = json.loads((Path(__file__).resolve().parents[2] / "知识库P1_20261118" /
                             "p2_questions_ext.json").read_text(encoding="utf-8"))
    _q06_gold_id = next(q for q in _q06_suite["questions"] if q["id"] == "Q06")["gold"]["anchor_chunk"]
    _q06 = K.query(_Q06, revision="nekketsu_soccer2_fc_jp", topk=30)
    _q06_gold_rank = next((i for i, h in enumerate(_q06.get("hits", []), 1)
                          if h["chunk_id"] == _q06_gold_id), None)
    ok(_q06_gold_rank and _q06_gold_rank <= 3
       and "プレイ" in _q06.get("query_expansion", [])
       and _q06["status"] == "pass"
       and [h["chunk_id"] for h in _q06.get("selected_evidence", [])] == [_q06_gold_id],
       f"知识库 [199] 真实Q06召回修复：上场→プレイ跨语扩展后日文金表第{_q06_gold_rank}位，生产pass且唯一证据为金表")
    _plain_terms = {"热血", "足球", "联盟", "要素", "盘点", "输入"}
    _plain_score, _plain_mode, _plain_removed = K._score_query_terms(
        "要素盘点的输入是什么？", _plain_terms, True)
    _exclusive_score, _exclusive_mode, _exclusive_removed = K._score_query_terms(
        _Q02, {"热血", "足球", "燕返", "只有", "会使"}, True)
    _unfiltered_score, _unfiltered_mode, _unfiltered_removed = K._score_query_terms(
        _Q03, {"热血", "足球", "暂停", "按键输入"}, False)
    ok(_plain_score == _plain_terms and _plain_mode is None and not _plain_removed
       and _exclusive_mode == "attribution" and "燕返" in _exclusive_score
       and "只有" in _exclusive_removed
       and _unfiltered_score == {"热血", "足球", "暂停", "按键输入"}
       and _unfiltered_mode is None,
       "知识库 [200] 评分词边界：仅显式过滤的排他/按键问退框架词，普通问与全库检索原样保留")
    _q22 = K.query("要素盘点的输入是什么？", revision="project_docs", topk=8)
    ok(_q22["status"] == "pass" and "query_term_filter" not in _q22
       and len(_q22.get("selected_evidence", [])) == 1,
       "知识库 [201] 非目标回归：W22要素盘点输入问仍由生产路径pass且未触发按键序列专用评分")
    _q05 = "我想控制队长以外的队员，该怎么换人？"
    _q05_base = K.query(_q05, game="nekketsu_soccer2", topk=8)
    _q05_scoped = K.query(_q05, game="nekketsu_soccer2", topk=8, fact_selector="scoped")
    _q05_replace = K.query(_q05, game="nekketsu_soccer2", topk=8, fact_selector="replace")
    ok(_q05_base["status"] == "pass" and _q05_scoped["status"] == "pass"
       and _q05_scoped.get("selected_evidence") == _q05_base.get("selected_evidence")
       and _q05_replace["status"] == "inconclusive"
       and not _q05_replace.get("selected_evidence")
       and _q05_replace.get("refusal") == "fact_selector_rejected",
       "知识库 [193] scoped/replace 边界：复杂问句 scoped 保留原判，replace 不强行下结论")
    _q10 = "KOF98 ECK 能不能关掉队友改成 1v1？"
    _q10_base = K.query(_q10, revision="kof98eck", topk=8)
    _q10_sel = K.query(_q10, revision="kof98eck", topk=8, fact_selector="scoped")
    ok(_q10_base["status"] == "pass" and _q10_sel["status"] == "pass"
       and _q10_sel.get("selected_evidence") == _q10_base.get("selected_evidence")
       and _q10_sel["fact_selector"]["selected"] == _q10_base["selected_evidence"][0]["chunk_id"],
       "知识库 [194] 真实Q10不换证：主体词修正后原3v3限制块过核查并保留为唯一证据")
    raises(lambda: K.query(_Q02, fact_selector="all"),
           "知识库 [195] 选择器模式反证：未知模式拒绝，不允许静默按 replace 执行")
    raises(lambda: K.query(_Q02, selector_beyond_window=True),
           "知识库 [196] 扩窗反证：未显式选择模式时单独打开扩窗开关拒绝")
    raises(lambda: K._selector_texts({"index_used": "__missing_index__.json", "hits": []},
                                     index_path=Path("__missing_index__.json")),
           "知识库 [196b] 选择器正文失败关闭：索引读不到时拒绝降级到截断 snippet")
    raises(lambda: K._selector_texts({"index_used": K.INDEX_JSON.name,
                                      "hits": [{"chunk_id": "__missing_chunk__"}]},
                                     index_path=K.INDEX_JSON),
           "知识库 [196c] 选择器缺块失败关闭：命中块正文不在索引时拒绝用 snippet 补证据")

    # 阶段4 跨语关联（Q08 主修）：中文问句穿透全角日文说明书块。
    _Q08 = "双人合作模式下二号玩家操作什么位置？"
    _JA_GOLD = ("＜ゲームのルール＞\n　１ＰプレイはＭＦのキャプテン・キャラ一人を操作してプレイするの。"
                "２Ｐ協力プレイでは、１ＰはＭＦ・キャラを、２ＰはＧＫ・キャラを操作するのよ。"
                "キーパーは勝敗を左右する大事な役目。")
    _JA_ROSTER = "ポジション ： ＧＫ\n身長 ： 175\nすばやさ ： 88"
    _r = _sel(_Q08, [("ja_gold", _JA_GOLD, _AUTH)])
    ok(_r["fact_class"] == "player_role" and _r["verdict"] == "pass"
       and _r["per_block"][0]["checks"]["attribute_match"]
       and _r["per_block"][0]["checks"]["condition_coverage"],
       "知识库 [184] 阶段4日文全角归一正对照：中文问句穿透２Ｐ協力/ＧＫ全角块，属性+条件双过")
    _r = _sel(_Q08, [("ja_wrongpos",
                      "２Ｐ協力プレイでは、２ＰはＦＷ・キャラを操作する。", _AUTH)])
    ok(_r["per_block"][0]["checks"]["attribute_match"]
       and _r["per_block"][0]["checks"]["condition_coverage"],
       "知识库 [184b] 日文块答2P=FW（位置值不同）：属性+条件仍过全角归一，答案对错属金标评估层非选择器")
    _r = _sel(_Q08, [("ja_roster", _JA_ROSTER, _AUTH)])
    ok(_r["verdict"] == "inconclusive"
       and not _r["per_block"][0]["checks"]["attribute_match"],
       "知识库 [185] 词面命中假pass反例：名单表只有ＧＫ/ポジション无玩家编号同行，属性关拒")
    _q08r = K.query(_Q08, revision="nekketsu_soccer2_fc_jp", topk=30)
    _idx2 = K.load_index()
    _texts2 = {c["chunk_id"]: c["text"] for c in _idx2["chunks"]}
    _g8chunk = next(c for c in _idx2["chunks"]
                    if c["path"].endswith("setsumei_热血足球说明书扫描_20261118.md")
                    and "２ＰはＧＫ" in c["text"] and "１ＰプレイはＭＦ" in c["text"])
    _g8id = _g8chunk["chunk_id"]
    _roster8 = next(c for c in _idx2["chunks"]
                    if c["path"] == _g8chunk["path"] and "ポジション ： ＧＫ" in c["text"])
    _c8 = KS.select(_Q08, _q08r.get("hits", []), _texts2, _tok, production_window=3)
    _g8 = next((p for p in _c8["per_block"] if p["chunk_id"] == _g8id), None)
    _r8 = next((p for p in _c8["per_block"] if p["chunk_id"] == _roster8["chunk_id"]), None)
    _rank8 = next((i for i, h in enumerate(_q08r["hits"], 1)
                   if h["chunk_id"] == _g8id), None)
    _sel8 = [h["chunk_id"] for h in _q08r.get("selected_evidence", [])]
    ok(_c8["verdict"] == "pass" and _c8["selected"] == _g8id
       and _c8["beyond_window"] == (_rank8 > 3)
       and _g8 and _g8["checks"]["eligible"]
       and _r8 and not _r8["checks"]["attribute_match"]
       and (_q08r["status"] != "pass" or _sel8 == [_g8id]),
       "知识库 [186] 真实Q08候选：玩家分工金标过七项并被选中，名单表词面假pass被拒；生产只按实际窗口判定")
    _g8ls, _g8le = _g8chunk["line_start"], _g8chunk["line_end"]
    _g8c = _g8chunk["text"]
    _src8 = Path(__file__).resolve().parents[2] / _g8chunk["path"]
    _src8lines = _src8.read_text(encoding="utf-8").splitlines()
    _l8 = next((i for i, ln in enumerate(_src8lines, 1)
                if "２ＰはＧＫ" in ln), None)
    _g8_last = _g8c.rsplit("\n", 1)[-1].lstrip()
    ok("２ＰはＧＫ" in _g8c and "協力" in _g8c and _l8 == 48
       and _g8ls <= _l8 <= _g8le
       and all(not ln.strip() or ln.strip() in _g8c
               for ln in _src8lines[_g8ls - 1:_g8le - 1])
       and _src8lines[_g8le - 1].strip().startswith(_g8_last),
       "知识库 [187] 精准引用覆盖：Q08决定性句在源文L48，块定位覆盖L47-L48；末行按300字上限截断且正文确为原文前缀")
    _packed = K._ja_pack(["あ" * 180 + "。", "", "い" * 180 + "。", "う" * 10 + "。"], 100)
    ok(_packed == [(100, 100, "あ" * 180 + "。"),
                   (102, 103, "い" * 180 + "。\n" + "う" * 10 + "。")],
       "知识库 [187b] 日文换行定位反证：跨空行合并的末块必须覆盖真实末行，不得少算也不得越界")
    _suite_root = Path(__file__).resolve().parents[2] / "知识库P1_20261118"
    _suite_rows = []
    for _suite_name in ("p1_questions.json", "p1_questions_ext.json", "p2_questions_ext.json"):
        _suite_data = json.loads((_suite_root / _suite_name).read_text(encoding="utf-8"))
        for _qid in ("Q06", "Q08"):
            _suite_rows.append(next(q for q in _suite_data["questions"] if q["id"] == _qid))
    ok(len(_suite_rows) == 6
       and all(q["gold"]["line_start"] <= _l8 <= q["gold"]["line_end"]
               and q["gold"]["anchor_chunk"] == _g8id for q in _suite_rows),
       "知识库 [187c] 题集金标同步：三套题集Q06/Q08均覆盖源文L48且锚点等于当前生产金标块")
    # 计划 §阶段4 L363 验收条：人物档案"擅长守门"≠玩家分工，能力陈述无玩家编号同行须拒。
    _JA_SKILL = "ＧＫが得意なキャラ。すばやさと身長に優れ、キーパー向き。"
    _r = _sel(_Q08, [("ja_skill", _JA_SKILL, _AUTH)])
    ok(_r["verdict"] == "inconclusive"
       and not _r["per_block"][0]["checks"]["attribute_match"],
       "知识库 [188] 人物档案擅长守门反例：全角ＧＫ/キーパー在但无玩家编号同行，属性关拒（答不了谁操作）")
    _r = _sel(_Q08, [("ja_skill_p", _JA_SKILL + "\n２Ｐ協力プレイでは２ＰはＧＫを操作する。", _AUTH)])
    ok(_r["per_block"][0]["checks"]["attribute_match"]
       and _r["per_block"][0]["checks"]["condition_coverage"],
       "知识库 [188b] 恒量正对照：同块补一行玩家编号+位置，属性+条件即过（拒的是缺编号非ＧＫ词面）")

    from . import kb_answer as KA
    from . import kb_provenance as KP

    _sig_q = "暂停秘技成功的判定签名是什么？"
    _sig_bad = KA.annotate(_sig_q, "等候室「作战会议→位置」可换人。", K.tokens)
    _sig_good = KA.annotate(_sig_q, "签名判据=得点表「ひっさつOK」。", K.tokens)
    ok(not _sig_bad["pattern_ok"] and _sig_good["pattern_ok"],
       "知识库 [220] 签名题恒量反证：任意引号不算签名，签名判据/ひっさつOK才算")
    _pos_q = "热血足球 元永在队里打什么位置？"
    _pos_bad = KA.annotate(_pos_q, "国夫是中场，赖常是前锋。", K.tokens)
    _pos_good = KA.annotate(_pos_q, "元永 #1 白底图标为门将标记。", K.tokens)
    ok(not _pos_bad["position_subject_ok"] and _pos_good["position_subject_ok"],
       "知识库 [221] 位置题主体恒量反证：被问人物不出现在证据行即拒，元永门将正对照过")

    with tempfile.TemporaryDirectory(prefix="kb_prov_") as prov_tmp:
        _prov = Path(prov_tmp) / "provenance.md"
        _prov.write_text(
            "# 片段资格夹具\n\n"
            "## 转述规则（S1 原文）\n"
            "旧说明：秘技输入是 A×3 B×1。\n"
            "我方实测：probe99 确认输入窗至少两帧。\n\n"
            "## 冲突表\n"
            "| 项目 | 旧结论 | 现状 |\n"
            "| 秘技 | probe18 负结果作废 | 签名判据=得点表「OK」 |\n",
            encoding="utf-8")
        _pc = {"path": str(_prov), "line_start": 1, "line_end": 9,
               "text": _prov.read_text(encoding="utf-8")}
        _pa = KP.assess("旧说明是什么？", _pc, K.tokens)
        ok(not _pa["eligible"] and _pa["reference_segments"] > 0,
           "知识库 [222] 片段资格：S1 小节下的无标记子句继承二手资格，不随整件权威放行")
        _pa = KP.assess("probe99 实测确认了什么？", _pc, K.tokens)
        ok(_pa["eligible"] and "probe99" in (_pa["evidence_excerpt"] or ""),
           "知识库 [223] 片段资格正对照：同小节显式我方实测可覆盖继承来源")
        _pa = KP.assess("probe18 负结果是什么？", _pc, K.tokens)
        ok(not _pa["eligible"] and _pa["retracted_segments"] > 0,
           "知识库 [224] 片段资格：作废句单独判 retracted，不得借同块其他句放行")
        _pa = KP.assess("probe18 负结果和秘技判定签名分别是什么？", _pc, K.tokens)
        ok(_pa["eligible"] and "签名判据" in (_pa["evidence_excerpt"] or "")
           and _pa["retracted_segments"] > 0,
           "知识库 [225] 混合块不连坐：撤回单元格排除，签名单元格仍可出证且摘录落到签名")

        _secondary = Path(prov_tmp) / "secondary.md"
        _secondary.write_text(
            "# 片段资格\n据攻略称，只有小辫子会燕返。\n"
            "## 据攻略称\n只有小辫子会燕返。\n"
            "## 我方实测\nprobe100 确认只有小辫子会燕返。\n",
            encoding="utf-8")
        _secondary_chunk = {"path": str(_secondary), "line_start": 1,
                            "text": _secondary.read_text(encoding="utf-8")}
        _pa = KP.assess("据攻略称，只有小辫子会燕返。",
                        {"path": str(_secondary), "line_start": 2,
                         "text": "据攻略称，只有小辫子会燕返。"}, K.tokens)
        ok(not _pa["eligible"] and _pa["reference_segments"] > 0,
           "知识库 [252] 显式转述资格：『据攻略称』不得继承整件权威")
        _pa = KP.assess("谁会燕返？", _secondary_chunk, K.tokens)
        ok(_pa["eligible"] and "probe100" in (_pa["evidence_excerpt"] or ""),
           "知识库 [253] 继承转述正对照：同块显式我方才实测可覆盖，摘录不落转述句")

        _conflict = Path(prov_tmp) / "retracted_conflict.md"
        _conflict.write_text(
            "# 片段资格\n只有小辫子会燕返。\n撤回：只有小辫子会燕返。\n",
            encoding="utf-8")
        _conflict_chunk = {"path": str(_conflict), "line_start": 1,
                           "text": _conflict.read_text(encoding="utf-8")}
        _pa = KP.assess("只有小辫子会燕返吗？", _conflict_chunk, K.tokens)
        ok(not _pa["eligible"] and _pa["reason"] == "retracted_claim_conflict"
           and _pa["retracted_segments"] > 0,
           "知识库 [254] 同主张撤回冲突：旧主张与撤回句同块时不得借前句放行")

        _citation = Path(prov_tmp) / "source_citation.md"
        _citation.write_text(
            "# 片段资格\n## 发动规则（S1 原文）\n"
            "秘技输入是 A×3 B×1。\n转述自 S7：秘技输入是 A×3 B×1。\n"
            "## 状态规则（S1）\n导航默认值待实测确认。\n秘技输入是 A×3 B×1。\n",
            encoding="utf-8")
        _citation_chunk = {"path": str(_citation), "line_start": 1,
                           "text": _citation.read_text(encoding="utf-8")}
        _pa = KP.assess("秘技输入是什么？", _citation_chunk, K.tokens)
        ok(_pa["eligible"] and "秘技输入是 A×3 B×1" in (_pa["evidence_excerpt"] or "")
           and "转述自" not in (_pa["evidence_excerpt"] or ""),
           "知识库 [255] 来源编号不等于二手：裸S1标题下事实可出证，摘录不落同块转述句")
        _pa = KP.assess("秘技输入是什么？",
                        {"path": str(_citation), "line_start": 4,
                         "text": "转述自 S7：秘技输入是 A×3 B×1。"}, K.tokens)
        ok(not _pa["eligible"] and _pa["reference_segments"] > 0,
           "知识库 [256] 显式带来源编号的转述仍降级：『转述自S7』不得因裸引用修正而放行")
        _pa = KP.assess("秘技输入是什么？",
                        {"path": str(_citation), "line_start": 5,
                         "text": "## 状态规则（S1）\n导航默认值待实测确认。\n秘技输入是 A×3 B×1。"},
                        K.tokens)
        ok(_pa["eligible"] and "秘技输入是 A×3 B×1" in (_pa["evidence_excerpt"] or "")
           and "待实测" not in (_pa["evidence_excerpt"] or ""),
           "知识库 [259] 普通条目的待实测不跨行继承：后一条独立事实仍可出证")

        _alias_doc = Path(prov_tmp) / "citation_alias.md"
        _alias_doc.write_text(
            "# 汇总件\n## 发动规则（S1）\n秘技输入是 A×3 B×1。\n"
            "## 本机实测（S1 更正）\nprobe100 确认输入窗至少两帧。\n",
            encoding="utf-8")
        _weak_alias = {"S1": {"authority": "reference_only", "status": "verified_read",
                               "revision": "tg_jp", "game_id": "testgame"}}
        _alias_chunk = {"path": str(_alias_doc), "line_start": 1,
                        "revision": "tg_multi", "game_id": "testgame",
                        "citation_authority": _weak_alias,
                        "text": _alias_doc.read_text(encoding="utf-8")}
        _alias_weak_chunk = {**_alias_chunk, "line_start": 3,
                             "text": "秘技输入是 A×3 B×1。"}
        _pa = KP.assess("A×3 B×1 是什么输入？", _alias_weak_chunk, K.tokens)
        ok(not _pa["eligible"] and _pa["reference_segments"] > 0,
           "知识库 [260] 已知二手别名沿标题继承：汇总件不得把S1转述升成权威")
        _pa = KP.assess("probe100 确认了什么？", _alias_chunk, K.tokens)
        ok(_pa["eligible"] and "probe100" in (_pa["evidence_excerpt"] or ""),
           "知识库 [261] 本机实测标题解除二手继承，同文档实测事实仍可出证")
        _unknown_chunk = {**_alias_chunk, "citation_authority": {}}
        _unknown_chunk["text"] = "## 状态规则（S99）\n秘技输入是 A×3 B×1。"
        _pa = KP.assess("A×3 B×1 是什么输入？", _unknown_chunk, K.tokens)
        ok(_pa["eligible"],
           "知识库 [262] 未登记裸编号不连坐：S99没有来源映射时仍按原片段规则判断")
        _strong_chunk = {**_alias_chunk, "citation_authority":
                         {"S1": {"authority": "authoritative", "status": "verified_read",
                                 "revision": "tg_jp", "game_id": "testgame"}}}
        _pa = KP.assess("秘技输入是什么？", _strong_chunk, K.tokens)
        ok(_pa["eligible"],
           "知识库 [263] 别名资格从主数据解析：同游戏权威来源可支撑汇总件片段")

        _pos_prov = Path(prov_tmp) / "positions.md"
        _pos_prov.write_text("よりつね\nポジション ： ＦＷ\nげんえい\nポジション ： ＧＫ\n",
                             encoding="utf-8")
        _pos_piece = {"path": str(_pos_prov), "line_start": 1, "line_end": 4,
                      "text": _pos_prov.read_text(encoding="utf-8")}
        _pos_assess = KP.assess("元永在队里打什么位置？", _pos_piece, K.tokens)
        ok(_pos_assess["eligible"] and "げんえい" in (_pos_assess["evidence_excerpt"] or "")
           and "ＧＫ" in (_pos_assess["evidence_excerpt"] or "")
           and "ＦＷ" not in (_pos_assess["evidence_excerpt"] or ""),
           "知识库 [229] 严格片段摘录绑定人物：元永须配げんえい的GK，不得误摘前一位球员FW")

    raises(lambda: K.query("燕返", fragment_policy="typo"),
           "知识库 [226] fragment_policy 非法值拒绝，禁止静默回落 legacy")
    _q18s = K.query(_sig_q, game="nekketsu_soccer2", topk=30, fragment_policy="strict")
    _q18b = K.query(_sig_q, game="nekketsu_soccer2", topk=30)
    ok(_q18b["status"] == "pass"
       and (_q18b.get("selected_evidence") or [{}])[0].get("locator", "").endswith("#L251-L259")
       and _q18s["status"] != "pass" and not _q18s.get("selected_evidence"),
       "知识库 [227] 真实Q18：默认保留金标定位，strict按S8二手资格拒答且不出证")
    _p24 = K.query("测试问题与闸门说明书里，ROM 修订版对不上该怎么办？", topk=30)
    ok(_p24["status"] == "pass"
       and (_p24.get("selected_evidence") or [{}])[0].get("locator", "").endswith("#L76-L79"),
       "知识库 [228] 真实P24：窄同义扩展把同口径/回放无法对齐金标提进生产窗口")
    _citation_cases = (
        ("Q02", "热血队内，燕返原生只有哪个角色会使？"),
        ("Q03", "热血足球2 暂停秘技的按键输入是什么？"),
        ("Q04", "容易难度下对手能不能发动必杀射门？"),
        ("Q05", "我想控制队长以外的队员，该怎么换人？"),
        ("X03", "热血足球 龙卷拳谁能用？"),
        ("X04", "热血足球 三倍加速怎么发动？"),
        ("X23", "热血足球 倒挂金钩怎么使出来？"),
    )
    _citation_results = []
    for _qid, _question in _citation_cases:
        _params = dict(game="nekketsu_soccer2", topk=30)
        _base = K.query(_question, **_params)
        _res = K.query(_question, fragment_policy="strict", **_params)
        _citation_results.append((_qid, _base["status"], _res["status"],
                                  _res.get("selected_evidence") or []))
    ok(all(_base == "pass" and _strict != "pass" and not _evidence
           for _qid, _base, _strict, _evidence in _citation_results),
       "知识库 [257] 真实Q02-Q05/X03/X04/X23：已知S1二手别名在strict拦截，默认臂行为不变")
    _q01_strict = K.query("热血足球联盟一共有多少种必杀射门？",
                          game="nekketsu_soccer2", topk=30, fragment_policy="strict")
    ok(_q01_strict["status"] != "pass",
       "知识库 [258] 真实Q01：搜狐二手总量口径仍不得因裸引用修正而升格放行")
    _x21 = K.query("热血足球 元永在队里打什么位置？", game="nekketsu_soccer2",
                   topk=30, fragment_policy="strict")
    ok(_x21["status"] == "pass"
       and (_x21.get("selected_evidence") or [{}])[0].get("source_id") == "setsumei_cloudfree"
       and all(term in ((_x21.get("selected_evidence") or [{}])[0]
                        .get("fragment_provenance", {}).get("evidence_excerpt") or "")
               for term in ("げんえい", "ＧＫ")),
       "知识库 [230] 真实X21：官方人物表出证且strict摘录绑定げんえい的GK，不误摘相邻球员")
    from . import kb_coverage as KC2
    with tempfile.TemporaryDirectory(prefix="kb_metrics_") as metrics_tmp:
        _log = Path(metrics_tmp) / "query_log.jsonl"
        _rows = [
            {"ts": "2026-11-24T01:00:00Z", "q": "燕返", "status": "pass",
             "index_sha256": "a" * 64, "selected_evidence": [{"chunk_id": "x"}]},
            {"ts": "2026-11-24T02:00:00Z", "q": "KOF98 SHA1", "status": "miss",
             "index_sha256": "b" * 64, "selected_evidence": []},
            {"ts": "2026-11-24T03:00:00Z", "q": "", "status": "inconclusive",
             "selected_evidence": []},
            {"ts": "2026-11-24T04:00:00Z", "q": "无证据问题", "status": "pass",
             "index_sha256": "c" * 64, "selected_evidence": []},
        ]
        _log.write_text("\n".join([json.dumps(r, ensure_ascii=False) for r in _rows] +
                                  ["{bad", "[]"]) + "\n", encoding="utf-8")
        _qm = KC2._read_query_metrics(_log)["summary"]
    ok(_qm["total_rows"] == 4 and _qm["unique_questions"] == 3
       and _qm["status_counts"] == {"pass": 2, "miss": 1, "inconclusive": 1}
       and _qm["selected_evidence_rows"] == 1 and _qm["evidence_selection_rate"] == 0.25
       and _qm["malformed_rows"] == 2 and _qm["empty_questions"] == 1
       and _qm["missing_index_fingerprints"] == 1 and _qm["missing_status"] == 0
       and _qm["pass_without_evidence"] == 1 and _qm["nonpass_with_evidence"] == 0
       and _qm["latest_ts"] == "2026-11-24T04:00:00Z",
       "知识库 [231] 查询日志聚合：总数/去重/状态/证据率/坏行/空问/缺指纹/契约异常逐格可复算")
    with tempfile.TemporaryDirectory(prefix="kb_metrics_v2_") as metrics_v2_tmp:
        _log2 = Path(metrics_v2_tmp) / "query_log.jsonl"
        _row2 = {"ts": "2026-11-24T05:00:00Z", "schema_version": 2,
                 "q": "燕返 拳皇98", "status": "inconclusive", "selected_evidence": [],
                 "index_sha256": "d" * 64, "route_mode": "multi",
                 "entry_point": "blind_eval", "elapsed_ms": 12.5,
                 "domains": [
                     {"domain": "retro_soccer", "status": "pass", "counts": {"hits": 1},
                      "index_sha256": "d" * 64, "selected_chunk_ids": ["soccer"]},
                     {"domain": "kof98", "status": "miss", "counts": {"hits": 0},
                      "index_sha256": "d" * 64, "selected_chunk_ids": []}]}
        _log2.write_text(json.dumps(_row2, ensure_ascii=False) + "\n", encoding="utf-8")
        _qm2 = KC2._read_query_metrics(_log2)
    ok(_qm2["summary"]["diagnostic_rows"] == 1
       and _qm2["summary"]["multi_domain_rows"] == 1
       and _qm2["summary"]["domain_evidence_rows"] == 1
       and _qm2["summary"]["route_modes"] == {"multi": 1}
       and _qm2["summary"]["elapsed_ms_avg"] == 12.5
       and _qm2["by_domain"]["retro_soccer"]["status_counts"] == {"pass": 1}
       and _qm2["by_domain"]["retro_soccer"]["selected_evidence_rows"] == 1
       and _qm2["by_domain"]["kof98"]["status_counts"] == {"miss": 1}
       and _qm2["last"]["kof98"]["status"] == "miss",
       "知识库 [231b] schema_v2多域聚合：采用日志逐域状态/证据，不把总体inconclusive摊给每域")
    _shot_q = "怎么射门才能让守门员扑不到？"
    _shot_bad = KA.annotate(_shot_q, "キーパーを操作する時は、パンチングやキャッチができる。",
                            K.tokens, lang="ja")
    _shot_good = KA.annotate(_shot_q, "必殺シュートの出し方：ジャンプしてからボタンを押す。",
                             K.tokens, lang="ja")
    _q16 = K.query(_shot_q, game="nekketsu_soccer2", topk=30)
    ok(not _shot_bad["shot_method_ok"] and _shot_bad["answerable"] is False
       and _shot_good["shot_method_ok"] and _q16["status"] != "pass"
       and not _q16.get("selected_evidence"),
       "知识库 [232] 射门方法题：日文守门员操作段不得冒充射门答案，真实Q16错误pass撤回")
    _role_q = "双人合作模式下二号玩家操作什么位置？"
    _role_bad = KA.annotate(_role_q, "よりつね\nポジション ： ＦＷ", K.tokens, lang="ja")
    _role_good = KA.annotate(
        _role_q,
        "２Ｐ協力プレイでは、１ＰはＭＦ・キャラを、２ＰはＧＫ・キャラを操作するのよ。",
        K.tokens, lang="ja")
    _q08 = K.query(_role_q, game="nekketsu_soccer2", topk=30)
    ok(not _role_bad["player_role_ok"] and _role_bad["answerable"] is False
       and _role_good["player_role_ok"] and _q08["status"] == "pass"
       and [h["chunk_id"] for h in _q08.get("selected_evidence", [])] == [_g8id]
       and (_q08.get("selected_evidence") or [{}])[0].get("locator", "").endswith("#L47-L48")
       and _roster8["chunk_id"] not in [h["chunk_id"] for h in _q08.get("selected_evidence", [])],
       "知识库 [233] 玩家分工题：位置名单无玩家编号仍不得出证；真实Q08由L47-L48金标正确修复")
    _ending_q = "一直输球会不会触发隐藏结局？"
    _ending_bad = KA.annotate(
        _ending_q, "秘技触发：S1+S8 两源一致；不会必杀运球者上下亦可。", K.tokens)
    _ending_good = KA.annotate(
        _ending_q, "一直输球不会触发隐藏结局，全踢败后游戏卡住。", K.tokens)
    _q17_sel = K.query(_ending_q, game="nekketsu_soccer2", topk=30,
                       fact_selector="scoped", selector_beyond_window=True)
    ok(not _ending_bad["ending_capability_ok"] and _ending_bad["answerable"] is False
       and _ending_good["ending_capability_ok"] and _ending_good["answerable"]
       and not _q17_sel.get("selected_evidence"),
       "知识库 [232c] 隐藏结局题：只谈秘技触发不得出证，扩窗选择器撤回Q17错证")
    for _pid, _pq in (
        ("X05", "热血足球 选手一闪一闪是故障吗？"),
        ("X17", "热血足球 全败结局画面显示的密码是什么？"),
        ("X19", "热血足球 美纱子的电话有什么用？"),
        ("X20", "热血足球 德国队为什么必杀概率低？"),
        ("X30", "热血足球 合体技有哪些发动方法？"),
    ):
        _legacy = K.query(_pq, game="nekketsu_soccer2", topk=30)
        _strict = K.query(_pq, game="nekketsu_soccer2", topk=30, fragment_policy="strict")
        ok(_legacy["status"] == "pass" and _strict["status"] != "pass",
           f"知识库 [229-{_pid}] 真实继承源探针：legacy假pass被strict片段资格拦截")

    from . import kb_nli as KN
    _cal_path = Path(__file__).with_name("nli_calibration.json")
    _cal = json.loads(_cal_path.read_text(encoding="utf-8"))
    ok(_cal.get("status") == "failed" and _cal.get("thresholds") is None
       and _cal.get("metrics", {}).get("samples") == 24
       and 0 <= _cal["metrics"]["macro_f1"] <= 1,
       "知识库 [232b] NLI 校准失败必须留档：24 样本不倒推绿灯，macro-F1 不越界")
    _ready_cal = {"status": "ready", "thresholds": {"entailment": 0.8, "contradiction": 0.8},
                  "sha256": "a" * 64}
    ok(KN.assess("", "证据")["reason"] == "claim_required",
       "知识库 [233b] NLI 缺完整 claim 不运行，禁止拿问题冒充主张")
    ok(KN.assess("SHA1 是 abc", "证据", calibration=_ready_cal)["status"] == "not_applicable"
       and KN.assess("スタート→A×3→B×1→スタート", "证据",
                     calibration=_ready_cal)["status"] == "not_applicable",
       "知识库 [234] 指纹/输入序列等结构化事实不交给 NLI 替代硬判据")
    ok(KN.assess("主张", "证据", eligible=False,
                 calibration=_ready_cal)["reason"] == "hard_gate_rejected",
       "知识库 [235] NLI 只能接在身份/版本/权限硬关之后")
    _old_cal, _old_pred = KN._load_calibration, KN.predict
    try:
        def _fake_entail(premise, hypothesis, device=None, max_length=512):
            return {"label": "entailment",
                    "probabilities": {"entailment": 0.99, "neutral": 0.005, "contradiction": 0.005},
                    "margin": 0.985, "device": "fake:cuda", "dtype": "float32",
                    "max_length": max_length, "premise_chars": len(premise),
                    "hypothesis_chars": len(hypothesis)}
        KN._load_calibration = lambda: _ready_cal
        KN.predict = _fake_entail
        _nli_q = "热血足球 元永在队里打什么位置？"
        _nli_base = K.query(_nli_q, game="nekketsu_soccer2", topk=30,
                            fragment_policy="strict")
        _nli_sup = K.query(_nli_q, game="nekketsu_soccer2", topk=30,
                           fragment_policy="strict", nli_shadow=True,
                           nli_claim="元永在队里打GK。")
        ok(_nli_sup["status"] == _nli_base["status"]
           and _nli_sup.get("selected_evidence") == _nli_base.get("selected_evidence")
           and _nli_sup["nli_shadow"]["decision"] == "supports_shadow",
           "知识库 [236] NLI 支持只附影子提示，不新增 pass、不改出证块")
        def _fake_contra(premise, hypothesis, device=None, max_length=512):
            return {"label": "contradiction",
                    "probabilities": {"entailment": 0.005, "neutral": 0.005, "contradiction": 0.99},
                    "margin": 0.985, "device": "fake:cuda", "dtype": "float32",
                    "max_length": max_length, "premise_chars": len(premise),
                    "hypothesis_chars": len(hypothesis)}
        KN.predict = _fake_contra
        _nli_veto = K.query(_nli_q, game="nekketsu_soccer2", topk=30,
                            fragment_policy="strict", nli_shadow=True,
                            nli_claim="元永在队里打FW。")
        ok(_nli_veto["status"] == _nli_base["status"]
           and _nli_veto.get("selected_evidence") == _nli_base.get("selected_evidence")
           and _nli_veto["nli_shadow"]["decision"] == "veto_candidate",
           "知识库 [237] NLI 矛盾只标 veto_candidate，绝不擅自推翻生产 pass")
        _nli_missing = K.query(_sig_q, game="nekketsu_soccer2", topk=30,
                               fragment_policy="strict", nli_shadow=True)
        ok(_nli_missing["nli_shadow"]["status"] == "not_run"
           and _nli_missing["nli_shadow"]["reason"] == "claim_required",
           "知识库 [238] 生产 query 缺 claim 返回 not_run，且不拖垮检索")
    finally:
        KN._load_calibration, KN.predict = _old_cal, _old_pred
    _nli_failed = K.query(_nli_q, game="nekketsu_soccer2", topk=30,
                          fragment_policy="strict", nli_shadow=True,
                          nli_claim="元永在队里打GK。")
    ok(_nli_failed["status"] == _nli_base["status"]
       and _nli_failed["nli_shadow"]["status"] == "not_run"
       and "校准" in _nli_failed["nli_shadow"]["reason"],
       "知识库 [239] 真实失败校准件让生产 NLI 保持关闭，不加载模型硬跑")
    _old_query = K.query
    _seen_kw = []
    try:
        def _capture_query(q, **kw):
            _seen_kw.append(kw)
            return {"status": "miss", "refusal": "out_of_scope", "reason": "x",
                    "counts": {}, "hits": [], "q": q}
        K.query = _capture_query
        K.query_auto("LOL 与 DOTA2 联动角色是谁", topk=3,
                     nli_shadow=True, nli_claim="联动角色是谁。")
    finally:
        K.query = _old_query
    ok(len(_seen_kw) >= 2
       and all(x.get("nli_shadow") is True and x.get("nli_claim") == "联动角色是谁。"
               for x in _seen_kw),
       "知识库 [240] query_auto 把 NLI 参数透传全部命中域，不漏域")
    with tempfile.TemporaryDirectory(prefix="kb_nli_log_") as nli_tmp:
        _nl = Path(nli_tmp) / "query_log.jsonl"
        K.append_query_log({"q": "测试", "status": "pass", "reason": "x",
                            "nli_shadow": {"status": "shadow", "decision": "uncertain",
                                           "claim": "不得落盘的主张正文",
                                           "premise": "不得落盘的证据正文"}}, path=_nl)
        _lt = _nl.read_text(encoding="utf-8")
    ok("不得落盘" not in _lt and '"nli_shadow"' in _lt,
       "知识库 [241] NLI 日志只落标签/概率/阈值，不落 claim 或 premise 正文")
    _error_rows = []
    raises(lambda: K.query("燕返", fact_selector="invalid", log_sink=_error_rows.append),
           "知识库 [242] 诊断不吞错：非法选择器仍抛 SchemaError")
    ok(len(_error_rows) == 1 and _error_rows[0]["status"] == "error"
       and _error_rows[0]["outcome"] == "error" and _error_rows[0]["call_id"]
       and _error_rows[0]["counts"]["hits"] == 0,
       "知识库 [242b] 异常诊断留痕：错误状态/调用ID/零计数入同一有界契约")
    _huge_hit = {"chunk_id": "chunk", "locator": "x#L1-L2", "snippet": "证" * 10000,
                 "fragment_provenance": {"eligible": True, "evidence_excerpt": "不得落盘的片段全文"}}
    _huge_result = {"q": "问" * 5000, "status": "pass", "reason": "因" * 5000,
                    "counts": {"candidates": 1, "hits": 1},
                    "selected_evidence": [{**_huge_hit, "chunk_id": f"c{i}"} for i in range(20)],
                    "domain_results": [{"domain": f"d{i}", "matched": ["词" * 500] * 10,
                                        "status": "pass", "selected_evidence": [_huge_hit]}
                                       for i in range(20)]}
    _bounded_row = K.build_query_log_row(
        _huge_result, elapsed_ms=-1, context={"request_id": "bounded"},
        params={"token": "不得落盘的凭证", "nli_claim": "不得落盘的主张",
                "want": ["要素" * 500] * 20}, event_ids=["e" * 500] * 40)
    with tempfile.TemporaryDirectory(prefix="kb_log_bound_") as bound_tmp:
        _bound_path = Path(bound_tmp) / "query_log.jsonl"
        K.write_query_log_row(_bounded_row, path=_bound_path)
        _bound_raw = _bound_path.read_text(encoding="utf-8")
    ok(len(_bounded_row["q"]) == 500 and len(_bounded_row["reason"]) == 500
       and len(_bounded_row["selected_evidence"]) == 8 and len(_bounded_row["domains"]) == 16
       and len(_bounded_row["event_ids"]) == 32 and _bounded_row["elapsed_ms"] == 0
       and all(len(h["snippet"]) <= 240 for h in _bounded_row["selected_evidence"])
       and "token" not in _bounded_row["params"] and "nli_claim" not in _bounded_row["params"]
       and all(len(v) <= 40 for v in _bounded_row["params"]["want"])
       and "不得落盘" not in _bound_raw and len(_bound_raw.encode("utf-8")) <= 16384,
       "知识库 [243] 日志边界恒量反证：超长问/原因/证据/域/事件全部截断，正文与凭证字段不落盘")
    with tempfile.TemporaryDirectory(prefix="kb_cli_log_") as cli_tmp:
        _old_kb_dir = K.KB_DIR
        try:
            K.KB_DIR = Path(cli_tmp)
            _cli_rc = K.main(["query", "--q", "热血队内，燕返原生只有哪个角色会使？",
                              "--game", "nekketsu_soccer2", "--topk", "30", "--json"])
            _cli_rows = [json.loads(x) for x in
                         (Path(cli_tmp) / "query_log.jsonl").read_text(encoding="utf-8").splitlines()]
        finally:
            K.KB_DIR = _old_kb_dir
    ok(_cli_rc == 0 and len(_cli_rows) == 1
       and _cli_rows[0]["caller"] == "cli" and _cli_rows[0]["entry_point"] == "cli"
       and _cli_rows[0]["params"]["game"] == "nekketsu_soccer2"
       and _cli_rows[0]["params"]["topk"] == 30
       and _cli_rows[0]["status"] == "pass" and _cli_rows[0]["elapsed_ms"] > 0,
       "知识库 [243b] CLI生产入口真跑：单条诊断落隔离目录，调用方/过滤参数/出证状态与耗时齐全")

    from . import kb_blind_eval as BE
    with tempfile.TemporaryDirectory(prefix="kb_blind_gate_") as blind_tmp:
        _blind_root = Path(blind_tmp)
        _source_suite = json.loads((K.ROOT.parent.parent / "知识库P1_20261118" /
                                    "p2_questions_ext.json").read_text(encoding="utf-8"))
        _q02 = next(q for q in _source_suite["questions"] if q["id"] == "Q02")
        _one_suite = _blind_root / "one.json"
        _one_suite.write_text(json.dumps({"questions": [_q02]}, ensure_ascii=False),
                              encoding="utf-8")
        _blind_prefix = _blind_root / "blind"
        _blind_rc = BE.main(["--suite", str(_one_suite), "--out", str(_blind_prefix),
                             "--api", "query", "--topk", "30", "--no-log"])
        _blind_data = json.loads(_blind_prefix.with_suffix(".json").read_text(encoding="utf-8"))
    ok(_blind_rc == 0 and _blind_data["summary"]["ok"] == 1
       and _blind_data["summary"]["total"] == 1 and _blind_data["isolation"]["ok"]
       and not _blind_prefix.with_suffix(".query_log.jsonl").exists()
       and _blind_data["questions"][0]["grade"]["correct_evidence"],
       "知识库 [244] 隔离盲测生产入口：真实Q02按grade_v2正确出证，no-log不造日志，真实状态零写动")
    with tempfile.TemporaryDirectory(prefix="kb_blind_iso_") as iso_tmp:
        _iso_root = Path(iso_tmp)
        _iso_suite = _iso_root / "refuse.json"
        _iso_suite.write_text(json.dumps({"questions": [
            {"id": "R", "q": "无答案问句", "expect": "refuse", "filters": {}}]},
            ensure_ascii=False), encoding="utf-8")
        _iso_real = _iso_root / "real.json"
        _iso_real.write_text("before", encoding="utf-8")
        _old_paths, _old_run = BE._protected_paths, BE.run
        try:
            BE._protected_paths = lambda: [_iso_real]
            def _mutate_run(questions, args, run_id, log_path):
                _iso_real.write_text("after", encoding="utf-8")
                return [{"id": "R", "tier": "refuse", "q": "无答案问句",
                         "grade": {"id": "R", "tier": "refuse", "ok": True, "why": "fixture"},
                         "result": {"status": "miss", "selected_evidence": []}}]
            BE.run = _mutate_run
            _iso_rc = BE.main(["--suite", str(_iso_suite), "--out", str(_iso_root / "out"),
                               "--no-log"])
            _iso_data = json.loads((_iso_root / "out.json").read_text(encoding="utf-8"))
        finally:
            BE._protected_paths, BE.run = _old_paths, _old_run
    ok(_iso_rc == 1 and not _iso_data["isolation"]["ok"]
       and _iso_data["isolation"]["changed_paths"] == [str(_iso_real)],
       "知识库 [244b] 隔离失败恒量反证：受保护文件mtime/hash变化即退出1并点名，不冒充盲测成功")
    with tempfile.TemporaryDirectory(prefix="kb_blind_input_") as input_tmp:
        _input_root = Path(input_tmp)
        _one_suite = _input_root / "one.json"
        _one_suite.write_text(json.dumps({"questions": [_q02]}, ensure_ascii=False),
                              encoding="utf-8")
        _bad_suite = _input_root / "bad_suite.json"
        _bad_suite.write_text(json.dumps({"questions": [
            {"id": "B", "q": "坏题", "expect": "not_a_tier"}]}), encoding="utf-8")
        _bad_rc = BE.main(["--suite", str(_bad_suite), "--out", str(_input_root / "bad_out"),
                           "--no-log"])
        _collision_rc = BE.main(["--suite", str(_one_suite),
                                 "--out", str(K.INDEX_JSON.with_suffix("")), "--no-log"])
        ok(_bad_rc == 2 and _collision_rc == 2
           and not (_input_root / "bad_out.json").exists()
           and not (_input_root / "bad_out.md").exists(),
           "知识库 [244c] 盲测输入边界：未知档位与覆盖真实索引均退出2，且不写半截产物")

    with tempfile.TemporaryDirectory(prefix="kb_blind_fail_") as fail_tmp:
        _fail_root = Path(fail_tmp)
        _fail_suite = _fail_root / "fail.json"
        _fail_suite.write_text(json.dumps({"questions": [
            {"id": "F", "q": "无答案问句", "expect": "strict_pass",
             "gold": {"path_contains": "__missing__", "line_start": 1, "line_end": 1},
             "filters": {}}]}, ensure_ascii=False), encoding="utf-8")
        _fail_rc = BE.main(["--suite", str(_fail_suite), "--out", str(_fail_root / "out"),
                            "--no-log"])
        _fail_data = json.loads((_fail_root / "out.json").read_text(encoding="utf-8"))
    ok(_fail_rc == 1 and _fail_data["isolation"]["ok"]
       and _fail_data["summary"]["ok"] == 0 and _fail_data["summary"]["total"] == 1
       and _fail_data["summary"]["errors"] == 0,
       "知识库 [244d] 评测退出码反证：隔离正常但题失败仍退出1，产物保留逐题结果不冒充成功")

    _crc_q = "KOF98 ECK 卡带的 CRC32 校验值是多少？"
    ok(KA.annotate(_crc_q, "SHA1 0123456789abcdef0123456789abcdef01234567", K.tokens)["intent_ok"] is False
       and KA.annotate(_crc_q, "CRC32 01234567", K.tokens)["intent_ok"] is True
       and KA.annotate(_crc_q, "CRC32 0123456789abcdef0123456789abcdef01234567", K.tokens)["intent_ok"] is False,
       "知识库 [245] CRC32字段反证：8位十六进制才可答，40位SHA1不得冒充CRC32")
    _mp_q = "热血足球联盟3P模式中第三人控制什么位置？"
    ok(KA.annotate(_mp_q, "某球员 ポジション：GK", K.tokens)["multiplayer_mode_ok"] is False
       and KA.annotate(_mp_q, "3P模式：3P操作1P队的キーパー", K.tokens)["multiplayer_mode_ok"] is True
       and KA.annotate("点球战1P模式能操作哪些选手？", "1P vs 2P 对战", K.tokens)["multiplayer_mode_ok"] is False
       and KA.annotate("点球战1P模式能操作哪些选手？", "PK战 1P模式操作所有选手", K.tokens)["multiplayer_mode_ok"] is True,
       "知识库 [246] 多人模式反证：玩家编号与PK模式必须同时对上，球员位置名单不得串答")
    _pos_q = "热血足球联盟日版说明书里元永的场上位置是什么？"
    ok(KA._position_subjects(_pos_q) == ["元永"]
       and KA.annotate(_pos_q, "げんえい\nポジション：GK", K.tokens)["answerable"] is True
       and KA.annotate(_pos_q, "よりつね\nポジション：FW", K.tokens)["position_subject_ok"] is False,
       "知识库 [247] 位置主语反证：元永↔げんえい别名可证，换别的球员即拒")
    _team_q = "热血足球联盟里巴西队的必杀射门叫什么名字？"
    ok(KA.team_shot_subject(_team_q) == "巴西"
       and KA.annotate(_team_q, "| 巴西 | 食人鱼射门 |", K.tokens)["team_shot_ok"] is True
       and KA.annotate(_team_q, "海月的必杀射门与巴西队的十分相似。", K.tokens)["team_shot_ok"] is False,
       "知识库 [248] 队伍射门归属反证：必须同句直接归属，别队射门与巴西队比较不得冒答")
    _cap_list_q = "热血格斗传说说明书列出的六项能力参数有哪些？"
    _cap_formula_q = "热血格斗传说的角色名字和生日怎样换算成六项能力？"
    ok(KA.annotate(_cap_list_q, "能力共6项：HP、手投、足投、投げ技、すばやさ、防御。", K.tokens)["answerable"] is True
       and KA.annotate(_cap_list_q, "说明书没有给出六项能力的公式。", K.tokens)["pattern_ok"] is False
       and KA.annotate(_cap_formula_q, "说明书没有给出名字或血型到六项能力的公式。", K.tokens)["answerable"] is True
       and KA.annotate(_cap_formula_q, "能力共6项：HP、手投、足投。", K.tokens)["pattern_ok"] is False,
       "知识库 [249] 能力清单/公式反证：清单必须列参数，公式缺失只能由明确无公式件出证")
    _heldout_modes = [
        ("4P模式怎样分队？", "multiplayer_mode"),
        ("巴西队的必杀射门叫什么名字？", "team_shot"),
        ("爆裂攻击在落地时要按哪个键？", "technique"),
        (_cap_list_q, "capability_list"),
    ]
    ok(all(K._score_query_terms(q, set(K.tokens(q)), True)[1] == mode
           for q, mode in _heldout_modes),
       "知识库 [250] 窄问法评分反证：多人/队伍射门/招式/能力清单各自进入对应聚焦模式")
    _eck_guard = K.query("草薙京在 KOF98 ECK 的燃烧之手出招指令是什么？",
                         revision="kof98eck", topk=30)
    ok(_eck_guard["status"] == "inconclusive"
       and not _eck_guard.get("selected_evidence")
       and any("跨版本" in warning for warning in _eck_guard.get("authority_warnings", [])),
       "知识库 [251] 早退版本守卫：不可答时仍保留跨版本警告，不得静默丢边界提示")

    for p in real:
        key = str(p)
        now = (p.stat().st_mtime_ns, _sha(p)) if p.is_file() else None
        ok(now == before[key],
           f"知识库 [反查] 真实文件未被探针写动 {p.name}（mtime+sha256 一致）")
    return _G.PASS - start


def inject_into_selftest():
    st_path = Path(__file__).resolve().parent / "selftest.py"
    if not st_path.is_file():
        raise SystemExit(f"未找到 {st_path}")
    text = st_path.read_text(encoding="utf-8")
    hook = "from .kb_selftest_gates import run_kb_gates"
    if hook in text:
        print("[幂等跳过] selftest.py 已包含知识库闸门")
        return
    marker = 'if __name__ == "__main__":'
    addition = ("\ndef test_kb_corpus():\n"
                "    from .kb_selftest_gates import run_kb_gates\n"
                "    run_kb_gates(ok_fn=ok, raises_fn=raises)\n\n\n")
    if marker not in text:
        print("[跳过] 未在 selftest.py 中定位到 __main__ 入口")
        return
    text = text.replace(marker, addition + marker)
    text = text.replace('print(f"SELFTEST OK {PASS}/{PASS}")',
                        'test_kb_corpus()\n    print(f"SELFTEST OK {PASS}/{PASS}")')
    st_path.write_text(text, encoding="utf-8")
    print("[已注入] selftest.py 已挂载 test_kb_corpus()（知识库闸门 + 恒量反证格）")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inject", action="store_true")
    args = ap.parse_args()
    if args.inject:
        inject_into_selftest()
    n = run_kb_gates()
    print(f"KB_SELFTEST OK {n}/{n}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())