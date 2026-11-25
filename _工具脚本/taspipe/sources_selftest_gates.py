# -*- coding: utf-8 -*-
"""来源库系统自检闸门（身份门/库内优先门/hit 产物门/absence 中文层门/render 一致门/野来源门 + 恒量反证格）。

保存位置：F:\\开源掌机教程\\_工具脚本\\taspipe\\sources_selftest_gates.py
运行方式（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.sources_selftest_gates          # 独立跑本模块全部断言
  py -3 -u -m taspipe.sources_selftest_gates --inject # 挂载进 selftest.py 尾部并跑全量自检

探针隔离：所有路径常量（REG_JSON/LEDGER_JSON/MD_PATH/PACKS_DIR/FBNEO_CFG）在临时目录里 patch，
走的是 sources.py 的生产函数（不复制逻辑）；跑完反查真实文件 mtime+sha256 未被写。
每条"门"都配恒量反证格：把输入改成不该过的样子，断言门真的会红（证明不是死代码）。
"""
import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from .schema import Stage

PASS = 0


def _ok(cond, msg, ok_fn=None):
    global PASS
    if ok_fn is not None:
        return ok_fn(cond, msg)
    if not cond:
        raise AssertionError(msg)
    PASS += 1
    print(f"  [{PASS}] {msg}")


def _raises(fn, msg, raises_fn=None, ok_fn=None):
    if raises_fn is not None:
        return raises_fn(fn, msg)
    try:
        fn()
    except Exception as e:
        if type(e).__name__ == "SchemaError":
            _ok(True, msg, ok_fn)
            return
        raise AssertionError(f"{msg}: 抛了 {type(e).__name__} 而非 SchemaError")
    raise AssertionError(f"应抛 SchemaError: {msg}")


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _src(sid, layer, status, plats, wants, **kw):
    d = {"source_id": sid, "name": kw.pop("name", sid), "kind": kw.pop("kind", "site"),
         "layer": layer, "platforms": plats, "element_types": wants, "status": status,
         "last_verified": None if status == "candidate" else "2026-11-18",
         "urls": kw.pop("urls", []), "evidence": kw.pop("evidence", []),
         "notes": kw.pop("notes", "")}
    d.update(kw)
    return d


def _check(report, cid):
    for c in report["checks"]:
        if c["check_id"] == cid:
            return c["verdict"]
    return "missing"


PATCHED = ("REG_JSON", "LEDGER_JSON", "MD_PATH", "PACKS_DIR", "FBNEO_CFG")


def run_sources_gates(ok_fn=None, raises_fn=None):
    from . import sources as S

    def ok(cond, msg):
        return _ok(cond, msg, ok_fn)

    def raises(fn, msg):
        return _raises(fn, msg, raises_fn, ok_fn)

    real_files = [S.REG_JSON, S.LEDGER_JSON, S.MD_PATH]
    before = {str(p): (p.stat().st_mtime_ns, _sha(p)) if p.is_file() else None
              for p in real_files}
    old = {k: getattr(S, k) for k in PATCHED}
    try:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ev_ok = td / "ev_ok.md"
            ev_text = "# 取证正文\n热血足球联盟必杀：前B头球、后B倒钩。\n"
            ev_ok.write_text(ev_text, encoding="utf-8")
            ev_empty = td / "ev_empty.md"
            ev_empty.write_text("", encoding="utf-8")
            rom_bytes = b"PK\x03\x04 fake kof98eck rom"
            cfg = td / "fbneo" / "config"
            (cfg / "games").mkdir(parents=True)
            ini = cfg / "games" / "kof98eck.ini"
            ini.write_text("// FinalBurn Neo --- Config File for kof98eck (The King of Fighters '98 "
                           "(Easy Combo Edition, Hack))\n", encoding="utf-8")
            dat = cfg / "fbneo64.roms.dat"
            dat.write_text("kof98eck +\nkof98 +\n", encoding="utf-8")
            romdir = td / "fbneo" / "roms"
            romdir.mkdir(parents=True)
            (romdir / "kof98eck.zip").write_bytes(rom_bytes)
            nes_rom = td / "game.nes"
            nes_rom.write_bytes(b"NES\x1a fake contra")

            reg = {"schema_version": 1, "updated": "2026-11-18", "note": "探针夹具", "sources": [
                _src("s_ok", "cn_console", "verified_read", ["NES"], ["攻略", "彩蛋"],
                     evidence=[str(ev_ok)], games_hit=["testgame"],
                     recipes={"cn": "{game} 攻略"}, urls=["https://ok.example/a"]),
                _src("s_snap", "en_tech", "snippet_only", ["ANY"], ["出招表"],
                     urls=["https://snap.example/b"]),
                _src("s_unreach", "cn_arcade_hack", "unreachable", ["ARCADE"], ["金手指"],
                     reachability={"direct": "fail", "checked": "2026-11-18"},
                     urls=["http://unreach.example/c"]),
                _src("s_unreach2", "en_tech", "unreachable", ["ANY"], ["出招表"],
                     reachability={"direct": "403", "checked": "2026-11-18"},
                     urls=["http://unreach2.example/c"]),
                _src("s_cand", "cn_community", "candidate", ["ANY"], ["彩蛋"],
                     urls=["https://cand.example/d"]),
                _src("s_dead", "cn_netdisk", "dead", ["ANY"], ["攻略", "彩蛋"],
                     closure={"date": "2026-03-20", "reason": "律师函后整站关闭",
                              "report_urls": ["https://report.example/x"]},
                     urls=["https://dead.example/e"]),
                _src("s_netdisk", "cn_netdisk", "candidate", ["ANY"], ["彩蛋", "隐藏要素"],
                     urls=["https://pan.example/f"]),
                _src("s_menu_candidate", "local_emu", "candidate", ["GBA"], ["基础档案"],
                     kind="local", urls=[]),
                _src("bilibili_probe", "video", "snippet_only", ["ANY"], ["彩蛋", "视频验证"],
                     name="B站（实况/集锦）", urls=["https://search.bilibili.com/all?keyword={game}"]),
                _src("s_local", "local_emu", "verified_read", ["ARCADE"], ["身份", "出招表"],
                     kind="local", evidence=[str(ini), str(dat)]),
            ]}
            reg_path = td / "sources.json"
            reg_path.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
            packs = td / "packs"
            packs.mkdir()
            good_pack = {"schema_version": 1, "kind": "statejump_showcase", "game_id": "testgame",
                         "platform": "NES",
                         "catalog": {"status": "complete", "expected_total": 2, "sources": [
                             {"source_id": "s_ok", "url": "https://ok.example/a",
                              "status": "verified_read", "verified_date": "2026-11-18",
                              "element_ids": ["e1", "e2"], "note": "已取正文"}]},
                         "elements": [{"element_id": "e1"}, {"element_id": "e2"}]}
            good_path = packs / "good.showcase.json"
            good_path.write_text(json.dumps(good_pack, ensure_ascii=False), encoding="utf-8")
            md = td / "清单.md"
            md.write_text("# 人读清单\n\n" + S.BEGIN_MARK + "\n" + S.END_MARK + "\n\n## 尾注\n",
                          encoding="utf-8")

            S.REG_JSON = reg_path
            S.LEDGER_JSON = td / "检索台账.json"
            S.MD_PATH = md
            S.PACKS_DIR = packs
            S.FBNEO_CFG = cfg

            # ---------- 身份门 ----------
            plan = S.route("拳皇98", "出招表,金手指", set_name="kof98eck", platform="ARCADE")
            ok(plan["status"] == "ready", "来源库 [1] 身份门：本地 ini+setlist 命中 => resolved 并出检索计划")
            ok("Easy Combo Edition" in (plan["identity"]["full_name"] or ""),
               "来源库 [2] 身份门读出卡全名（不拿中文叫法当身份）")
            ok(plan["identity"]["rom"]["sha1"] == hashlib.sha1(rom_bytes).hexdigest(),
               "来源库 [3] 身份门给出 rom 级 sha1（可复算）")
            bad = S.route("拳皇98", "出招表", set_name="no_such_set", platform="ARCADE")
            ok(bad["status"] == "blocked" and "primary" not in bad,
               "来源库 [4] 反证格：setlist 查无此 set => blocked，不出检索计划")
            ok(S.route("某游戏", "攻略")["status"] == "blocked",
               "来源库 [5] 反证格：缺 set/rom => blocked（身份未定不得开搜）")
            rp = S.route("魂斗罗", "攻略", rom=str(nes_rom))
            ok(rp["status"] == "ready" and rp["identity"]["platform"] == "NES"
               and rp["identity"]["sha1"] == hashlib.sha1(nes_rom.read_bytes()).hexdigest(),
               "来源库 [6] 主机路径：本地 sha1 + 扩展名定身份")
            raises(lambda: S.route("x", "不存在的要素", set_name="kof98eck", platform="ARCADE"),
                   "来源库 [7] 未知要素类型 => SchemaError（不进执行）")
            raises(lambda: S.route("x", "攻略", platform="不存在的平台", rom=str(nes_rom)),
                   "来源库 [8] 未知平台枚举 => SchemaError")

            # ---------- 库内优先门 ----------
            p = S.route("testgame", "彩蛋", platform="NES", rom=str(nes_rom))
            prim = [e["source_id"] for e in p["primary"]]
            ext = [e["source_id"] for e in p["extension"]]
            forb = [e["source_id"] for e in p["forbidden"]]
            ok("s_ok" in prim and "s_cand" not in prim and "s_dead" not in prim,
               "来源库 [9] 库内优先门：verified_read 进 primary，candidate/dead 不进")
            ok("s_cand" in ext and "s_netdisk" in ext,
               "来源库 [10] candidate 只进延伸段（未命中才扩大搜索）")
            ok("s_dead" in forb and p["forbidden"][0]["closure"]["date"] == "2026-03-20",
               "来源库 [11] dead 站进禁用段并附关停当期证据")
            ok(prim[0] == "s_ok", "来源库 [12] 排序：已读+命中过该游戏+首选层 => 排第一")
            ok(p["primary"][0]["queries"][0]["query"] == "testgame 攻略",
               "来源库 [13] 逐站检索词由 recipes 渲染（不是每次现编）")
            ok(p["absence_gate"]["cn_netdisk"] == ["s_netdisk"]
               and p["absence_gate"]["cn_video_bili"] == ["bilibili_probe"],
               "来源库 [14] absence 必扫层从库里现查（不写死站名）")
            un = S.route("拳皇98", "金手指", set_name="kof98eck", platform="ARCADE")
            ok(all(e["access"] == "snapshot" for e in un["primary"] if e["status"] == "unreachable"),
               "来源库 [15] unreachable 只给快照通道，不冒充直连已读")
            ok("s_unreach" not in [e["source_id"] for e in S.route("testgame", "金手指", platform="NES", rom=str(nes_rom))["primary"]],
               "来源库 [16] 反证格：ARCADE 专属站不得进 NES 计划（平台过滤真在跑）")
            reg_down = S.load_registry()
            for s in reg_down["sources"]:
                if s["source_id"] == "s_ok":
                    s.update(status="candidate", evidence=[], last_verified=None)
            S.save_registry(reg_down)
            ok("s_ok" not in [e["source_id"] for e in S.route("testgame", "彩蛋", platform="NES", rom=str(nes_rom))["primary"]],
               "来源库 [17] 反证格：把已读来源降为 candidate => 必须落延伸段（优先门不是死代码）")
            reg_path.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")

            # ---------- hit 产物门 ----------
            r = S.log("s_cand", "testgame", "彩蛋", "hit", evidence=[str(ev_ok)])
            ok(r["verdict"] == "pass" and r["promoted"] == "candidate->verified_read",
               "来源库 [18] hit 带正文取证 => pass，candidate 自动升 verified_read")
            led = S._ledger()
            done = [x for x in led.entries if x["job_id"] == r["ledger_job"]][0]
            ok(done["status"] == "done" and done["artifact_refs"][0]["sha256"] == _sha(ev_ok),
               "来源库 [19] 台账产物门：done 必须对应真实产物且 sha256 一致")
            ok(S.log("s_cand", "testgame", "彩蛋", "hit")["verdict"] == "inconclusive",
               "来源库 [20] 反证格：hit 不带取证 => inconclusive，不算命中")
            ok(S.log("s_cand", "testgame", "彩蛋", "hit",
                     evidence=[str(td / "nope.md")])["verdict"] == "inconclusive",
               "来源库 [21] 反证格：取证文件不存在 => inconclusive")
            ok(S.log("s_cand", "testgame", "彩蛋", "hit",
                     evidence=[str(ev_empty)])["verdict"] == "inconclusive",
               "来源库 [22] 反证格：取证文件为空 => inconclusive")
            ok(S.find_source(S.load_registry(), "s_cand")["status"] == "verified_read",
               "来源库 [23] 失败尝试不得把已验证来源降级")
            led = S._ledger()
            same = [x for x in led.entries if x["idempotency_key"] == "src:s_cand:testgame:彩蛋"]
            ok(len(same) == 4 and [x["attempt"] for x in same] == [1, 2, 3, 4],
               "来源库 [24] 台账追加式：4 次尝试都留痕，不覆盖失败历史")
            rr = S.log("s_ok", "reusegame", "攻略", "hit", evidence=[str(ev_ok)])
            d2 = [x for x in S._ledger().entries if x["job_id"] == rr["ledger_job"]][0]
            ok(S._ledger().reusable(Stage.GENERATE, d2["idempotency_key"], d2["fingerprint"]) is not None,
               "来源库 [25] 复用门：最新 attempt 为 done + 指纹一致 + 产物校验通过 => 可复用")
            ev_ok.write_text("篡改后的正文", encoding="utf-8")
            tampered = S._ledger().reusable(Stage.GENERATE, d2["idempotency_key"], d2["fingerprint"]) is None
            ev_ok.write_text(ev_text, encoding="utf-8")
            ok(tampered and S._ledger().reusable(Stage.GENERATE, d2["idempotency_key"],
                                                d2["fingerprint"]) is not None,
               "来源库 [26] 反证格：产物字节被改 => 不可复用，还原后又可复用（sha256 校验真在跑）")
            summ = S._ledger().summary()
            ok(summ["attempts"] == 5 and summ["failed"] == 1 and summ["done"] == 1,
               "来源库 [27] 台账摘要按最新 attempt 逐条计数（s_cand 历史 done 不冒充当前可用，不用总数减失败倒推）")

            # ---------- snippet 三态 ----------
            rs = S.log("s_netdisk", "testgame", "彩蛋", "snippet", evidence=[str(ev_ok)])
            ok(rs["verdict"] == "inconclusive" and rs["promoted"] == "candidate->snippet_only",
               "来源库 [28] snippet => inconclusive + 只升 snippet_only")
            ok(S.find_source(S.load_registry(), "s_netdisk")["status"] == "snippet_only",
               "来源库 [29] 反证格：快照永不升 verified_read")

            # ---------- absence 中文层门 ----------
            ca = S.claim_absence("testgame", "隐藏要素")
            ok(ca["status"] == "blocked"
               and {m["layer"] for m in ca["missing"]} == {"cn_netdisk", "cn_video_bili"},
               "来源库 [30] absence 门：两层都无 miss => blocked 并点名缺哪层")
            S.log("s_netdisk", "testgame", "隐藏要素", "miss")
            ca2 = S.claim_absence("testgame", "隐藏要素")
            ok(ca2["status"] == "blocked" and [m["layer"] for m in ca2["missing"]] == ["cn_video_bili"],
               "来源库 [31] 反证格：只扫网盘缺 B站 => 仍 blocked（搜不到别说成不存在）")
            S.log("bilibili_probe", "testgame", "隐藏要素", "miss")
            ca3 = S.claim_absence("testgame", "隐藏要素")
            ok(ca3["status"] == "allowed" and len(ca3["support"]) == 2,
               "来源库 [32] 两层都有 miss => 允许下「不存在」结论并留支撑 job")
            ok(len(S.load_registry()["absence_claims"]) == 1,
               "来源库 [33] 「不存在」声称落库可追溯")

            # ---------- ingest 去重与分类 ----------
            raises(lambda: S.ingest("https://ok.example/a", "重复站", "cn_community", "ANY", "攻略"),
                   "来源库 [34] ingest 去重：同域名同路径 => SchemaError")
            ni = S.ingest("https://new.example/z", "新站", "cn_community", "ANY", "攻略")
            ok(ni["status"] == "candidate" and ni["ingested"] == "new_example",
               "来源库 [35] 新站默认 candidate 入库分类（不冒充已验证）")
            raises(lambda: S.ingest("https://v.example/q", "无证站", "cn_console", "NES", "攻略",
                                    status="verified_read"),
                   "来源库 [36] 反证格：verified_read 无取证 => SchemaError")
            raises(lambda: S.ingest("https://bad.example/q", "非法层", "不存在的层", "ANY", "攻略"),
                   "来源库 [37] 未知 layer => SchemaError")

            # ---------- render 一致门 ----------
            S.render_write()
            ok(_check(S.audit(), "render_sync") == "pass",
               "来源库 [38] render 产物与主数据一致 => render_sync 绿")
            md.write_text(md.read_text(encoding="utf-8").replace("verified_read", "verified_READ", 1),
                          encoding="utf-8")
            ok(_check(S.audit(), "render_sync") == "fail",
               "来源库 [39] 反证格：手改生成块一个词 => render_sync 红（两份真相会被抓）")
            S.render_write()
            md2 = td / "无标记.md"
            md2.write_text("# 没有标记\n", encoding="utf-8")
            raises(lambda: S.render_write(md_path=md2),
                   "来源库 [40] 无生成块标记 => SchemaError（不猜插入点）")

            # ---------- 野来源 / 覆盖 / dead 引用 / 三态 ----------
            a0 = S.audit()
            ok(_check(a0, "element_coverage") == "pass" and _check(a0, "no_wild_sources") == "pass"
               and _check(a0, "pack_sources_migrated") == "pass",
               "来源库 [41] 结构化来源 + 逐要素归属 => 覆盖门/野来源门/迁移门全绿")
            probe_pack = packs / "probe.showcase.json"

            def with_probe(sources, elements=None):
                doc = dict(good_pack)
                doc["catalog"] = {**good_pack["catalog"], "sources": sources}
                if elements is not None:
                    doc["elements"] = elements
                probe_pack.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
                try:
                    return S.audit()
                finally:
                    probe_pack.unlink()

            a = with_probe(["https://wild.example/x"])
            ok(_check(a, "pack_sources_migrated") == "fail",
               "来源库 [42] 反证格：自由文本来源 => 迁移门红")
            a = with_probe([{"source_id": "not_in_registry", "url": "https://x.example",
                             "status": "verified_read", "verified_date": "2026-11-18",
                             "element_ids": ["e1", "e2"], "evidence_report": str(ev_ok)}])
            ok(_check(a, "no_wild_sources") == "fail",
               "来源库 [43] 反证格：野 source_id（库里没有）=> 野来源门红")
            a = with_probe([{"source_id": "s_dead", "url": "https://dead.example/e",
                             "status": "dead", "verified_date": "2026-03-20",
                             "element_ids": ["e1", "e2"]}])
            ok(_check(a, "no_dead_reference") == "fail",
               "来源库 [44] 反证格：引用已关停站 => dead 引用门红")
            a = with_probe([{"source_id": "s_ok", "url": "https://ok.example/a",
                             "status": "verified_read", "verified_date": "2026-11-18",
                             "element_ids": ["e1"]}])
            ok(_check(a, "element_coverage") == "fail",
               "来源库 [45] 反证格：要素 e2 无来源支撑 => 覆盖门红")
            a = with_probe([{"source_id": "s_snap", "url": "https://snap.example/b",
                             "status": "snippet_only", "verified_date": "2026-11-18",
                             "element_ids": ["e1", "e2"]}])
            ok(_check(a, "verified_support") == "inconclusive" and _check(a, "element_coverage") == "pass",
               "来源库 [46] 三态门：只有快照支撑 => inconclusive（不是 pass 也不是 fail）")
            good_off = good_path.with_name("good.off")
            good_path.rename(good_off)
            try:
                a = with_probe([], elements=[{"element_id": "e1"}, {"element_id": "e2"}])
            finally:
                good_off.rename(good_path)
            ok(_check(a, "verified_support") == "inconclusive" and a["counts"]["elements_supported"] == 0,
               "来源库 [47] 反证格：零要素取得支撑时不得报 pass（空支撑不算已验证）")
            a = with_probe([{"source_id": "s_ok", "url": "https://ok.example/a",
                             "status": "verified_read", "verified_date": "2026-11-18",
                             "element_ids": ["e1", "e2"], "野字段": 1}])
            ok(_check(a, "no_wild_sources") == "fail",
               "来源库 [48] 反证格：来源条目含未知字段 => 红（不放任自由格式）")
            a = with_probe([{"source_id": "s_ok", "status": "verified_read",
                             "element_ids": ["e1"], "evidence_report": str(ev_ok)},
                            {"source_id": "s_snap", "status": "snippet_only",
                             "element_ids": ["e2"], "evidence_report": str(ev_ok)}])
            ok(_check(a, "no_wild_sources") == "pass"
               and _check(a, "verified_support") == "inconclusive",
               "来源库 [49] 合法 evidence_report 可引用，候选/快照资格不升级")
            a = with_probe([{"source_id": "s_snap", "status": "verified_read",
                             "element_ids": ["e1", "e2"], "evidence_report": str(ev_ok)}])
            ok(_check(a, "no_wild_sources") == "fail",
               "来源库 [50] 反证格：包内状态与注册表不一致 => 红")
            a = with_probe([{"source_id": "s_ok", "status": "verified_read",
                             "element_ids": ["e1", "e2"],
                             "evidence_report": str(td / "missing_report.json")}])
            ok(_check(a, "no_wild_sources") == "fail",
               "来源库 [51] 反证格：evidence_report 文件缺失 => 红")
            a = with_probe([{"source_id": "s_ok", "status": "verified_read",
                             "element_ids": ["e1", "e2"]}],
                           elements=[{"group": "red", "id": 1}, {"element_id": "e2"}])
            ok(_check(a, "element_coverage") == "fail"
               and a["counts"]["elements_checked"] == 4
               and any("缺 element_id" in x for x in next(
                   c["detail"] for c in a["checks"] if c["check_id"] == "element_coverage")),
               "来源库 [52] 反证格：要素只有 group/id、缺稳定 element_id => 覆盖门红")
            a = with_probe([{"source_id": "s_ok", "status": "verified_read",
                             "element_ids": ["e1", "e2"]}],
                           elements=[{"element_id": "e1"}, {"element_id": "e1"}])
            ok(_check(a, "element_coverage") == "fail"
               and any("element_id 重复" in x for x in next(
                   c["detail"] for c in a["checks"] if c["check_id"] == "element_coverage")),
               "来源库 [53] 反证格：重复 element_id => 覆盖门红")
            a = with_probe([{"source_id": "s_menu_candidate", "status": "candidate",
                             "verified_date": None, "element_ids": ["menu_red_001", "menu_blue_001"]}],
                           elements=[{"group": "red", "id": 1, "element_id": "menu_red_001"},
                                     {"group": "blue", "id": 1, "element_id": "menu_blue_001"}])
            ok(_check(a, "element_coverage") == "pass"
               and _check(a, "verified_support") == "inconclusive",
               "来源库 [54] 稳定ID+候选来源可完成覆盖，但资格仍为 inconclusive")

            # ---------- schema 门 ----------
            base = _src("s_ok", "cn_console", "verified_read", ["NES"], ["攻略"], evidence=[str(ev_ok)])
            cases = [
                ({**base, "野字段": 1}, "未知字段"),
                ({**base, "source_id": "Bad-ID"}, "source_id 非法"),
                ({**base, "layer": "不存在的层"}, "layer 未知"),
                ({**base, "status": "已读"}, "status 未知"),
                ({**base, "platforms": []}, "platforms 为空"),
                ({**base, "element_types": ["不存在的要素"]}, "要素类型未知"),
                ({**base, "evidence": []}, "verified_read 缺取证"),
                ({**base, "evidence": [str(td / "nope.md")]}, "取证文件不存在"),
                ({**base, "last_verified": None}, "非 candidate 缺验证日期"),
                (_src("s_d", "cn_netdisk", "dead", ["ANY"], ["攻略"]), "dead 缺 closure"),
            ]
            for i, (rec, why) in enumerate(cases, start=55):
                raises(lambda rec=rec: S.validate_source(rec), f"来源库 [{i}] schema 门拒：{why}")

            # ---------- recheck 不自动判死 ----------
            S.recheck(source_id="s_unreach",
                      probe_fn=lambda url, timeout=15: {"direct": "fail", "checked": S.today()})
            ok(S.find_source(S.load_registry(), "s_unreach")["status"] == "unreachable",
               "来源库 [66] 反证格：探活失败不得自动判 dead（失败≠站没了）")
            raises(lambda: S.recheck(source_id="s_unreach", mark_dead=True),
                   "来源库 [67] 升 dead 必须给 reason")
            S.recheck(source_id="s_unreach", mark_dead=True, reason="当期报道：整站关闭")
            sd = S.find_source(S.load_registry(), "s_unreach")
            ok(sd["status"] == "dead" and sd["closure"]["reason"] == "当期报道：整站关闭",
               "来源库 [68] 人给当期证据才升 dead，并落 closure")
            S.recheck(source_id="s_unreach2",
                      probe_fn=lambda url, timeout=15: {"direct": "ok", "http_status": 200,
                                                        "checked": S.today()})
            ok(S.find_source(S.load_registry(), "s_unreach2")["status"] == "snippet_only",
               "来源库 [69] 直连恢复只升 snippet_only，内容仍需真读才升 verified_read")

            # ---------- absence 两种口径 ----------
            legacy_access = {"claim": "本机无法取回正文", "checked_on": S.today(),
                             "method": "直连", "result": "403", "not_a_claim_of": "不代表页面不存在"}
            ok(S.validate_absence_claim(legacy_access) == legacy_access,
               "来源库 [71] 取回限制记录有独立 schema，不再被不存在声称审计静默跳过")
            raises(lambda: S.validate_absence_claim({"claim": "没有", "support": []}),
                   "来源库 [72] 反证格：混合或缺失字段的 absence 记录拒绝入库")

            # ---------- 台账支撑门 ----------
            reg_c = S.load_registry()
            reg_c["absence_claims"] = [{"game": "testgame", "want": ["隐藏要素"],
                                        "date": S.today(), "support": ["generate:假job:a1"]}]
            S.save_registry(reg_c)
            ok(_check(S.audit(), "absence_claims_supported") == "fail",
               "来源库 [70] 反证格：「不存在」声称的支撑 job 不在台账 => 红")
    finally:
        for k, v in old.items():
            setattr(S, k, v)

    for p in real_files:
        key = str(p)
        if before[key] is None:
            ok(not p.exists(), f"来源库 [反查] 探针未创建真实文件 {p.name}")
        else:
            mt, h = before[key]
            ok(p.is_file() and p.stat().st_mtime_ns == mt and _sha(p) == h,
               f"来源库 [反查] 真实文件未被探针写动 {p.name}（mtime+sha256 一致）")
    return PASS


def inject_into_selftest():
    """幂等挂载进同目录 selftest.py。"""
    st_path = Path(__file__).resolve().parent / "selftest.py"
    if not st_path.is_file():
        raise SystemExit(f"未找到 {st_path}")
    text = st_path.read_text(encoding="utf-8")
    hook = "from .sources_selftest_gates import run_sources_gates"
    if hook in text:
        print("[幂等跳过] selftest.py 已包含来源库闸门")
        return
    marker = 'if __name__ == "__main__":'
    addition = ("\ndef test_sources_registry():\n"
                "    from .sources_selftest_gates import run_sources_gates\n"
                "    run_sources_gates(ok_fn=ok, raises_fn=raises)\n\n\n")
    if marker not in text:
        print("[跳过] 未在 selftest.py 中定位到 __main__ 入口")
        return
    text = text.replace(marker, addition + marker)
    text = text.replace('print(f"SELFTEST OK {PASS}/{PASS}")',
                        'test_sources_registry()\n    print(f"SELFTEST OK {PASS}/{PASS}")')
    st_path.write_text(text, encoding="utf-8")
    print("[已注入] selftest.py 已挂载 test_sources_registry()（来源库闸门 + 恒量反证格）")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inject", action="store_true", help="自动挂载进 selftest.py")
    args = ap.parse_args()
    if args.inject:
        inject_into_selftest()
    run_sources_gates()
    print(f"SOURCES_SELFTEST OK {PASS}/{PASS}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())