# -*- coding: utf-8 -*-
"""选题决策层自检：恒量反证格+探针隔离+产物计数。全部写临时目录，
patch 各模块路径常量；跑完反查真实 反馈.db/产出/查询日志 未被污染。
用法：py -3 自检.py（退出码0=全绿）。"""
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MODDIR = Path(__file__).resolve().parent
sys.path.insert(0, str(MODDIR))
import 台账读取
import 事件归并
import 知识对照
import 关注分层
import 系列归并
import 选题卡
import 反馈台账
import 热度时序
import 入口B挖题
import 正文采集
import B站热度探针
import 需求回流
import urllib.error
from unittest.mock import patch

TODAY = datetime(2026, 11, 19, tzinfo=timezone.utc)
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))


def mkrow(key, title, url, source_id, kind="rss", pub="2026-11-18",
          seen="2026-11-18T03:00:00Z", hot="", focus=""):
    return {"key": key, "first_seen_utc": seen, "source_id": source_id, "kind": kind,
            "source": source_id, "pub": pub, "title": title, "url": url,
            "flag_hot": hot, "flag_note": "", "flag_arrival": "", "flag_focus": focus}


def main():
    real_db = 反馈台账.DB_PATH
    real_out = 选题卡.OUT_ROOT
    real_snap = 热度时序.SNAP_DB
    real_cache = 正文采集.CACHE
    real_query_log = 知识对照.QUERY_LOG
    real_kb_index = 知识对照.SNAP / "index.json"
    real_bili_out = B站热度探针.OUT_ROOT
    real_bili_cache = B站热度探针.CACHE
    db_before = (real_db.exists(), real_db.stat().st_mtime if real_db.exists() else None)
    out_before = (real_out.exists(),
                  sorted(str(p) for p in real_out.rglob("*")) if real_out.exists() else [])
    snap_before = (real_snap.exists(), real_snap.stat().st_mtime if real_snap.exists() else None)
    cache_before = (real_cache.exists(),
                    sorted(str(p) for p in real_cache.rglob("*")) if real_cache.exists() else [])
    query_log_before = (real_query_log.exists(), real_query_log.stat().st_mtime if real_query_log.exists() else None,
                        real_query_log.read_bytes() if real_query_log.exists() else None)
    bili_out_before = (real_bili_out.exists(),
                       sorted(str(p) for p in real_bili_out.rglob("*")) if real_bili_out.exists() else [])
    bili_cache_before = (real_bili_cache.exists(),
                         sorted(str(p) for p in real_bili_cache.rglob("*")) if real_bili_cache.exists() else [])
    real_bili_probe = 需求回流.PROBE_RESULTS
    probe_before = (real_bili_probe.exists(),
                    real_bili_probe.stat().st_mtime if real_bili_probe.exists() else None,
                    real_bili_probe.read_bytes() if real_bili_probe.exists() else None)
    profiles = 关注分层.load_profiles()
    prof = profiles[0]

    with tempfile.TemporaryDirectory(prefix="选题自检_") as td:
        td = Path(td)
        反馈台账.DB_PATH = td / "反馈.db"
        选题卡.OUT_ROOT = td / "产出"
        知识对照.SNAP = td / "kb快照"
        热度时序.SNAP_DB = td / "热度快照.db"
        正文采集.CACHE = td / "正文缓存"
        知识对照.QUERY_LOG = td / "查询日志.jsonl"
        B站热度探针.OUT_ROOT = td / "B站热度实验"
        B站热度探针.CACHE = td / "B站缓存"
        需求回流.PROBE_RESULTS = td / "探针结果.json"

        # T1 台账读取：12列与老10列兼容
        p12 = td / "t12.tsv"
        p12.write_text("key\tfirst_seen_utc\tsource_id\tkind\tsource\tpub\ttitle\turl\tflag_hot\tflag_note\tflag_arrival\tflag_focus\n"
                       "k1\t2026-11-18T03:00:00Z\ts1\trss\tS1\t2026-11-18\t标题甲\thttps://a/1\tHOT\t\t\t开源掌机与固件\n",
                       encoding="utf-8")
        p10 = td / "t10.tsv"
        p10.write_text("key\tfirst_seen_utc\tsource_id\tkind\tsource\tpub\ttitle\turl\tflag_hot\tflag_note\n"
                       "k2\t2026-11-18T03:00:00Z\ts2\trss\tS2\t2026-11-18\t标题乙\thttps://a/2\t\t\n",
                       encoding="utf-8")
        r12, r10 = 台账读取.read_ledger(p12), 台账读取.read_ledger(p10)
        check("T1a 12列台账读回", len(r12) == 1 and r12[0]["flag_focus"] == "开源掌机与固件")
        check("T1b 老10列缺列补空不崩", len(r10) == 1 and r10[0]["flag_focus"] == "" and r10[0]["flag_arrival"] == "")

        # T2 转载归并：3源同标题=1事件，独立来源3但不等于3份独立证据
        rows = [mkrow("a", "热血足球隐藏结局终于被触发", "https://x/1", "s1"),
                mkrow("b", "热血足球隐藏结局终于被触发", "https://y/2", "s2"),
                mkrow("c", "热血足球隐藏结局终于被触发", "https://z/3", "s3")]
        evs = 事件归并.merge_events(rows)
        check("T2 转载3篇归1事件", len(evs) == 1 and evs[0]["source_count"] == 3 and evs[0]["item_count"] == 3)
        check("T2b 转载性质注明", "转载" in evs[0]["evidence_note"])
        ev_story = evs[0]

        # T3 不同 release tag 不并
        evs_tag = 事件归并.merge_events([
            mkrow("t44", "batocera-44", "https://github.com/batocera-linux/batocera.linux/releases/tag/batocera-44", "gh_batocera", "github_atom"),
            mkrow("t43", "batocera-43", "https://github.com/batocera-linux/batocera.linux/releases/tag/batocera-43", "gh_batocera", "github_atom")])
        check("T3 不同tag不合并", len(evs_tag) == 2)

        # T4 旧闻不进今日优先（pub 79天前，官方release+高匹配）
        ev_old = 事件归并.merge_events([mkrow(
            "o", "开源掌机固件发布 支持 PSP 移植", "https://github.com/x/y/releases/tag/v1",
            "gh_x", "github_atom", pub="2026-09-01", focus="开源掌机与固件")])[0]
        c_old = 关注分层.score_event(ev_old, prof, {"status": "off"}, TODAY)
        check("T4 旧闻不进今日优先", c_old["queue"] != "今日优先" and c_old["dims"]["时机与供给"]["level"] == "低",
              f"queue={c_old['queue']}")

        # T5 恒量反证：旧HOT商业八卦（无受众词）不许自动高
        ev_gossip = 事件归并.merge_events([mkrow(
            "g", "某明星恋情曝光 综艺官宣结婚", "https://ent/1", "ent", hot="HOT")])[0]
        c_gossip = 关注分层.score_event(ev_gossip, prof, {"status": "off"}, TODAY)
        check("T5 反证:HOT商业八卦关注=低", c_gossip["attention"] == "低" and c_gossip["queue"] == "低优先归档",
              f"attention={c_gossip['attention']} queue={c_gossip['queue']}")

        # T6 维护性提交影响=低
        ev_maint = 事件归并.merge_events([mkrow(
            "m", "fix typo in readme", "https://github.com/x/y/commit/abc", "gh_x", "github_atom")])[0]
        c_maint = 关注分层.score_event(ev_maint, prof, {"status": "off"}, TODAY)
        check("T6 维护提交影响=低", c_maint["dims"]["实际影响"]["level"] == "低")

        # T7 官方release+影响+匹配+近期 → 今日优先（KB off 时证据=官方发布件）
        ev_rel = 事件归并.merge_events([mkrow(
            "r", "Batocera 44 发布 支持开源掌机 PSP 移植",
            "https://github.com/batocera-linux/batocera.linux/releases/tag/batocera-44",
            "gh_batocera", "github_atom", focus="开源掌机与固件")])[0]
        c_rel = 关注分层.score_event(ev_rel, prof, {"status": "off"}, TODAY)
        check("T7 官方release近期→今日优先", c_rel["queue"] == "今日优先" and c_rel["evidence_status"] == "官方发布件",
              f"queue={c_rel['queue']} evidence={c_rel['evidence_status']}")

        # T8 恒量反证：需求信号无时序恒=未知（即使HOT）
        allcards = [c_old, c_gossip, c_maint, c_rel]
        check("T8 反证:需求信号恒未知", all(c["dims"]["需求信号"]["level"] == "未知" for c in allcards))
        check("T8b HOT只作参考注明", "非受众热度" in c_gossip["dims"]["需求信号"]["reason"])

        # T9 KB生产路径（bm25快照，显式退回；域内/域外各一题）
        ev_in = 事件归并.merge_events([mkrow("ki", "热血足球 世界杯 触发条件", "https://k/1", "kb_src")])[0]
        ev_out = 事件归并.merge_events([mkrow("ko", "LOL MSI 决赛 冠军是谁", "https://k/2", "kb_src")])[0]
        kb_map, kb_info = 知识对照.crosscheck([ev_in, ev_out], mode="bm25")
        rin, rout = kb_map[ev_in["event_id"]], kb_map[ev_out["event_id"]]
        check("T9a bm25快照走生产路径显式退回",
              kb_info["mode"] == "bm25" and rin.get("retrieval") == "bm25_only" and rin.get("retrieval_note"),
              f"retrieval={rin.get('retrieval')} note={rin.get('retrieval_note')}")
        check("T9b 域内题有候选非error", rin["status"] in ("pass", "inconclusive", "miss") and rin["status"] != "error",
              f"status={rin['status']} reason={rin.get('reason')}")
        check("T9c 反证:域外零语料拒答", rout["status"] == "miss" and rout.get("refusal") == "out_of_scope",
              f"status={rout['status']} refusal={rout.get('refusal')}")
        check("T9d 快照sha已记录", bool(kb_info.get("index_sha256")))

        # T29 域锚点闸门：unrouted问句全库bm25词面pass不可当硬证据
        # （治的病：Kirby标题Switch撞FBNeo输入配置 switch 0x4081 token，kof98eck.ini假pass顶进今日优先）
        # mock强制kb.query返回pass，确定性测闸门本身，不依赖真实语料漂移；route走真实生产代码。
        kbmod = 知识对照._import_kb()
        fake_pass = {"status": "pass", "retrieval": "bm25_only", "retrieval_note": "mock",
                     "reason": "2 条 verified_read + authoritative 可答命中，权威件在第 1 位",
                     "hits": [{"locator": "F:/工具链/fbneo/nightly/config/games/kof98eck.ini#L1-L32",
                               "snippet": 'input "P2 Button B"      switch 0x4081',
                               "authority": "authoritative", "status": "verified_read",
                               "answerability": {"answerable": True}}]}
        mock_idx = str(td / "mock_index.json")
        Path(mock_idx).write_text('{"chunks": []}', encoding="utf-8")
        ev_un = 事件归并.merge_events([mkrow(
            "ku", "Nintendo Officially Reveals New Kirby Game for Switch 2", "https://k/u", "s")])[0]
        ev_rt = 事件归并.merge_events([mkrow(
            "kr", "热血足球 必杀射门 燕返 小辫子", "https://k/r", "s")])[0]
        ev_un2 = 事件归并.merge_events([mkrow(
            "ku2", "Pikmin 4 announced for Switch 2", "https://k/u2", "s")])[0]
        with patch.object(kbmod, "query", return_value=fake_pass):
            km_u, ki_u = 知识对照.crosscheck([ev_un], mode="bm25", index_path=mock_idx)
        ru = km_u[ev_un["event_id"]]
        check("T29a 反证:unrouted+kb pass→降级unanchored不当硬证据",
              ru["status"] == "inconclusive" and ru.get("refusal") == "unanchored"
              and ki_u["unanchored_downgraded"] == 1,
              f"status={ru['status']} refusal={ru.get('refusal')} n={ki_u['unanchored_downgraded']}")
        with patch.object(kbmod, "query", return_value=fake_pass):
            km_r, ki_r = 知识对照.crosscheck([ev_rt], mode="bm25", index_path=mock_idx)
        rr = km_r[ev_rt["event_id"]]
        check("T29b routed域内pass保留(不误降)",
              rr["status"] == "pass" and rr.get("refusal") != "unanchored"
              and ki_r["unanchored_downgraded"] == 0,
              f"status={rr['status']} n={ki_r['unanchored_downgraded']}")
        with patch.object(kbmod, "query", return_value=fake_pass):
            km_m, ki_m = 知识对照.crosscheck([ev_un, ev_rt, ev_un2], mode="bm25", index_path=mock_idx)
        check("T29c 降级计数按受影响卡计(2域外+1域内=2)",
              ki_m["unanchored_downgraded"] == 2 and km_m[ev_rt["event_id"]]["status"] == "pass",
              f"n={ki_m['unanchored_downgraded']}")
        # T29e 反证:弱词子串撞进内部文档域("tas"⊂"Fantasy"→project_docs)的pass也降级
        ev_ff = 事件归并.merge_events([mkrow(
            "kf", "Final Fantasy VIII Remastered & Final Fantasy IX - 16:9 Fullscreen Mod (Nintendo Switch)",
            "https://k/f", "s")])[0]
        with patch.object(kbmod, "query", return_value=fake_pass):
            km_f, ki_f = 知识对照.crosscheck([ev_ff], mode="bm25", index_path=mock_idx)
        rf = km_f[ev_ff["event_id"]]
        check("T29e 反证:meta文档域(project_docs)pass降级(弱词tas⊂Fantasy)",
              rf["status"] == "inconclusive" and rf.get("refusal") == "unanchored"
              and ki_f["unanchored_downgraded"] == 1,
              f"status={rf['status']} refusal={rf.get('refusal')}")
        if real_kb_index.is_file():
            km_real, _ = 知识对照.crosscheck([ev_un], mode="bm25", index_path=str(real_kb_index))
            rreal = km_real[ev_un["event_id"]]
            check("T29d 真实语料:Kirby绝不pass(域锚点闸门现查)", rreal["status"] != "pass",
                  f"status={rreal['status']} refusal={rreal.get('refusal')}")
            km_ff, _ = 知识对照.crosscheck([ev_ff], mode="bm25", index_path=str(real_kb_index))
            check("T29f 真实语料:FF新闻绝不靠内部文档域pass",
                  km_ff[ev_ff["event_id"]]["status"] != "pass",
                  f"status={km_ff[ev_ff['event_id']]['status']}")
        else:
            check("T29d 真实语料:Kirby绝不pass(域锚点闸门现查)", False, "真实kb快照缺失")
            check("T29f 真实语料:FF新闻绝不靠内部文档域pass", False, "真实kb快照缺失")

        # T29g/h 出证绑定透传（阶段1）：pass 凭哪块放行必须带到下游；旧mock无字段容忍为空
        h2 = {**fake_pass["hits"][0], "locator": "F:/工具链/fbneo/nightly/config/games/kof98eck.ini#L99-L100"}
        fake_pass_sel = {**fake_pass, "hits": [fake_pass["hits"][0], h2],
                         "selected_evidence": [fake_pass["hits"][0]]}
        with patch.object(kbmod, "query", return_value=fake_pass_sel):
            km_s, _ = 知识对照.crosscheck([ev_rt], mode="bm25", index_path=mock_idx)
        rs = km_s[ev_rt["event_id"]]
        check("T29g crosscheck透传selected_evidence(放行依据块)",
              len(rs.get("selected_evidence") or []) == 1
              and rs["selected_evidence"][0]["locator"] == fake_pass["hits"][0]["locator"],
              f"sel={rs.get('selected_evidence')}")
        check("T29h 反证:旧结果无selected_evidence容忍为空(不拿全部hits冒充)",
              rr.get("selected_evidence") == [],
              f"sel={rr.get('selected_evidence')}")
        c_sel = 关注分层.score_event(ev_rt, prof, fake_pass_sel, TODAY)
        md_sel = 选题卡.render_card_md(c_sel)
        check("T29i 卡面:选中证据叫'KB出证',其余命中降为'相关命中(非出证)'",
              "KB出证" in md_sel and "KB相关命中（非出证" in md_sel
              and "证据口径" in md_sel and c_sel["evidence_scope"],
              md_sel[:200])
        c_nosel = 关注分层.score_event(ev_rt, prof, fake_pass, TODAY)
        md_nosel = 选题卡.render_card_md(c_nosel)
        check("T29j 反证:无放行依据块记录时整组降为相关命中,不冒充证据",
              "KB出证" not in md_nosel and "不得当证据" in md_nosel,
              md_nosel[:200])

        # T10 反馈scope：没时间≠观众负反馈；采纳进历史
        反馈台账.mark("card_rel", "采纳", event_id=ev_rel["event_id"], title=ev_rel["titles"][0])
        反馈台账.mark("card_x", "没时间", reason="本周排满")
        反馈台账.mark("card_y", "拒绝", reason="角度不对")
        con = 反馈台账.connect()
        scopes = dict(con.execute("SELECT card_id,scope FROM decisions").fetchall())
        con.close()
        check("T10a 没时间scope=editor_capacity", scopes.get("card_x") == "editor_capacity")
        check("T10b 拒绝scope=editorial_judgment", scopes.get("card_y") == "editorial_judgment")
        adopted = 反馈台账.adopted_titles()
        check("T10c 采纳标题进历史(现查)", 事件归并.norm_title(ev_rel["titles"][0]) in adopted)
        c_again = 关注分层.score_event(ev_rel, prof, {"status": "off"}, TODAY, adopted)
        check("T10d 讲过的信息增量=低", c_again["dims"]["信息增量"]["level"] == "低")

        # T11 长期选题：旧时效+高匹配+反差标记不被埋
        ev_cold = 事件归并.merge_events([mkrow(
            "c", "热血足球 隐藏角色 冷知识", "https://retro/9", "retro", pub="2026-08-01")])[0]
        c_cold = 关注分层.score_event(ev_cold, prof, {"status": "off"}, TODAY)
        check("T11 冷知识进长期选题", c_cold["queue"] == "长期选题", f"queue={c_cold['queue']}")

        # T12 卡字段契约+仅标题标注
        need = ["event_id", "profile_id", "attention", "dims", "evidence_status", "queue",
                "core_hook", "must_mention", "title_only", "rule_version", "judged_at", "kb"]
        check("T12a 卡字段齐全", all(k in c_rel for k in need))
        check("T12b 仅标题判断必标", c_rel["title_only"] is True and "仅标题" in c_rel["title_only_note"])
        check("T12c 八维齐全", set(c_rel["dims"]) == {"受众匹配", "实际影响", "信息增量", "反差与故事性", "需求信号", "表达与素材", "时机与供给", "知名度与重大性"})

        # T13 原子写+产物计数（计数从产物现查）
        cards = [c_rel, c_gossip, c_cold, c_old, c_maint]
        runinfo = {"date": "2026-11-19", "rule_version": 关注分层.RULE_VERSION}
        written, counts = 选题卡.write_cards(cards, runinfo, outdir=td / "产出" / "2026-11-19")
        disk = json.loads((td / "产出" / "2026-11-19" / "选题卡.json").read_text(encoding="utf-8"))
        check("T13a 产物7件齐全", len(written) == 7 and all(Path(p).is_file() for p in written))
        check("T13b JSON卡数=队列和=输入数", len(disk) == sum(counts.values()) == len(cards))
        check("T13c 无tmp残留", not list((td / "产出").rglob("*.tmp")))
        ri = json.loads((td / "产出" / "2026-11-19" / "运行记录.json").read_text(encoding="utf-8"))
        check("T13d 运行记录带队列计数", ri["queue_counts"] == counts and ri["cards_total"] == len(cards))

        # T14 hybrid内存闸门（反证：闸门常量存在且resolve显式降级）
        check("T14a hybrid闸门常量在", 知识对照.HYBRID_MIN_RAM_GB >= 8.0)
        m, why = 知识对照.resolve_mode("off")
        check("T14b off模式原样保留", m == "off" and why is None)

        # T16 反证：无pub但first_seen近期的新闻不许误判长尾（用first_seen代理）
        ev_nopub = 事件归并.merge_events([mkrow(
            "np", "Switch 模拟器 发布 新版 移植", "https://forum/1", "forum_src", pub="")])[0]
        c_nopub = 关注分层.score_event(ev_nopub, prof, {"status": "off"}, TODAY)
        check("T16a 无pub用first_seen代理", c_nopub["dims"]["时机与供给"]["level"] == "高"
              and "first_seen代理" in c_nopub["dims"]["时机与供给"]["reason"])
        check("T16b 反证:近期无pub不进长期选题", c_nopub["queue"] != "长期选题",
              f"queue={c_nopub['queue']}")

        # T17 反证：不知名项目常规发布不许进今日优先（知名度低→关注高被闸）
        ev_unknown = 事件归并.merge_events([mkrow(
            "u", "SomeRandomEmu v0.1 发布 新版", "https://github.com/foo/SomeRandomEmu/releases/tag/v0.1",
            "gh_foo", "github_atom", focus="开源掌机与固件")])[0]
        c_unknown = 关注分层.score_event(ev_unknown, prof, {"status": "off"}, TODAY)
        check("T17 反证:不知名项目常规发布不进今日优先",
              c_unknown["dims"]["知名度与重大性"]["level"] == "低" and c_unknown["queue"] != "今日优先",
              f"rec={c_unknown['dims']['知名度与重大性']['level']} queue={c_unknown['queue']}")

        # T18 知名IP（Kirby）知名度高，官宣可上浮
        ev_kirby = 事件归并.merge_events([mkrow(
            "kb", "Kirby 新作 公布 任天堂 Switch", "https://n/1", "n_src", focus="Switch移植")])[0]
        c_kirby = 关注分层.score_event(ev_kirby, prof, {"status": "off"}, TODAY)
        check("T18 Kirby知名度高+关注高",
              c_kirby["dims"]["知名度与重大性"]["level"] == "高" and c_kirby["attention"] == "高",
              f"rec={c_kirby['dims']['知名度与重大性']['level']} att={c_kirby['attention']}")

        # T19 重大事件（下架/takedown）标记+知名度高
        ev_takedown = 事件归并.merge_events([mkrow(
            "td", "Nintendo takes down Switch emulator Yuzu", "https://n/2", "n_src", focus="下架抢救")])[0]
        c_td = 关注分层.score_event(ev_takedown, prof, {"status": "off"}, TODAY)
        check("T19 takedown重大事件标记+知名度高",
              c_td["major_event"] is True and c_td["dims"]["知名度与重大性"]["level"] == "高",
              f"major={c_td['major_event']} rec={c_td['dims']['知名度与重大性']['level']}")

        # T20 同项目3个常规release→1张系列跟踪卡
        shad_rows = [mkrow(f"sh{i}", f"shadPS4 v0.{i}.0 released",
                           f"https://github.com/shadps4/shadps4/releases/tag/v0.{i}.0",
                           "gh_shad", "github_atom", focus="模拟器与核心") for i in (8, 9, 10)]
        shad_cards = [关注分层.score_event(e, prof, {"status": "off"}, TODAY)
                      for e in 事件归并.merge_events(shad_rows)]
        folded, n_series = 系列归并.fold(shad_cards)
        sc = next((c for c in folded if c["queue"] == "系列跟踪"), None)
        check("T20 shadPS4×3归1系列卡", n_series == 1 and sc is not None and len(folded) == 1,
              f"n_series={n_series} folded={len(folded)}")

        # T21 反证：不同repo不许误并（shadps4+rpcs3各1→0系列）
        two_rows = [mkrow("s1", "shadPS4 v0.9.0 released",
                          "https://github.com/shadps4/shadps4/releases/tag/v0.9.0", "gh_shad", "github_atom"),
                    mkrow("r1", "rpcs3 v0.0.30 released",
                          "https://github.com/RPCS3/rpcs3/releases/tag/v0.0.30", "gh_rpcs3", "github_atom")]
        two_cards = [关注分层.score_event(e, prof, {"status": "off"}, TODAY)
                     for e in 事件归并.merge_events(two_rows)]
        folded2, n2 = 系列归并.fold(two_cards)
        check("T21 反证:不同repo不并系列", n2 == 0 and len(folded2) == 2, f"n2={n2} len={len(folded2)}")

        # T22 反证：重大事件不许被系列折叠吞掉
        maj_rows = [mkrow("m1", "shadPS4 v0.9.0 released",
                          "https://github.com/shadps4/shadps4/releases/tag/v0.9.0", "gh_shad", "github_atom"),
                    mkrow("m2", "shadPS4 DMCA takedown 下架",
                          "https://github.com/shadps4/shadps4/releases/tag/v0.9.1", "gh_shad", "github_atom",
                          focus="下架抢救")]
        maj_cards = [关注分层.score_event(e, prof, {"status": "off"}, TODAY)
                     for e in 事件归并.merge_events(maj_rows)]
        folded3, n3 = 系列归并.fold(maj_cards)
        maj_card = next((c for c in folded3 if c.get("major_event")), None)
        check("T22 反证:重大事件不折叠", n3 == 0 and maj_card is not None and maj_card["queue"] != "系列跟踪",
              f"n3={n3} maj_queue={maj_card['queue'] if maj_card else None}")

        # T23 系列卡契约：成员/时间线/事件id前缀
        check("T23 系列卡契约",
              sc is not None and sc["event_id"].startswith("series:")
              and len(sc["series_members"]) == 3 and 1 <= len(sc["series_timeline"]) <= 10
              and sc["queue"] == "系列跟踪",
              f"members={len(sc['series_members']) if sc else 0}")

        # T24 反证：平台名(PS5)不作系列身份，两条PS5新闻不许误并
        plat_rows = [mkrow("p1", "PS5 独占游戏甲 发布", "https://n/p1", "n_src"),
                     mkrow("p2", "PS5 独占游戏乙 发布", "https://n/p2", "n_src")]
        plat_cards = [关注分层.score_event(e, prof, {"status": "off"}, TODAY)
                      for e in 事件归并.merge_events(plat_rows)]
        check("T24a 平台名project_key=None", all(系列归并.project_key(c) is None for c in plat_cards))
        folded4, n4 = 系列归并.fold(plat_cards)
        check("T24b 反证:PS5两条不并系列", n4 == 0 and len(folded4) == 2, f"n4={n4} len={len(folded4)}")

        # T25 反证：Kirby标题含Switch 2仍自成卡（不被平台桶吞），知名度高
        ev_kirby2 = 事件归并.merge_events([mkrow(
            "k2", "Kirby and the Forgotten Land Switch 2 Edition 公布 任天堂",
            "https://n/k2", "n_src", focus="Switch移植")])[0]
        c_kirby2 = 关注分层.score_event(ev_kirby2, prof, {"status": "off"}, TODAY)
        check("T25 Kirby含Switch2自成卡+知名度高",
              系列归并.project_key(c_kirby2) is None and c_kirby2["dims"]["知名度与重大性"]["level"] == "高",
              f"key={系列归并.project_key(c_kirby2)} rec={c_kirby2['dims']['知名度与重大性']['level']}")

        # ===== P2a 零LLM三件闸门 =====
        # T26 热度时序：<2次恒未知；升温→中(媒体覆盖代理,封顶)；下降→低
        ev_single = 事件归并.merge_events([mkrow("h0", "热血足球 攻略甲", "https://x/h0", "s1")])[0]
        热度时序.record([ev_single], ts="2026-11-10T00:00:00Z")
        d1 = 热度时序.demand_signal(ev_single, 热度时序.history(ev_single["event_id"]))
        check("T26a 反证:<2次观测需求恒未知", d1["level"] == "未知", f"level={d1['level']}")
        ev_up = 事件归并.merge_events([mkrow("h1", "热血足球 攻略乙", "https://x/h1", "s1")])[0]
        热度时序.record([ev_up], ts="2026-11-10T00:00:00Z")
        热度时序.record([dict(ev_up, source_count=3, item_count=5)], ts="2026-11-18T00:00:00Z")
        d2 = 热度时序.demand_signal(ev_up, 热度时序.history(ev_up["event_id"]))
        check("T26b 2次升温→中+媒体覆盖代理", d2["level"] == "中" and "媒体覆盖代理" in d2["reason"],
              f"level={d2['level']} reason={d2['reason']}")
        check("T26c 反证:升温封顶中不许高", d2["level"] != "高")
        ev_dn = 事件归并.merge_events([mkrow("h2", "热血足球 攻略丙", "https://x/h2", "s1")])[0]
        热度时序.record([dict(ev_dn, source_count=3, item_count=5)], ts="2026-11-10T00:00:00Z")
        热度时序.record([ev_dn], ts="2026-11-18T00:00:00Z")
        d3 = 热度时序.demand_signal(ev_dn, 热度时序.history(ev_dn["event_id"]))
        check("T26d 下降→低", d3["level"] == "低", f"level={d3['level']}")
        c_dem = 关注分层.score_event(ev_up, prof, {"status": "off"}, TODAY, demand_override=d2)
        check("T26e score_event接demand_override", c_dem["dims"]["需求信号"]["level"] == "中")

        # T27 入口B：只挖权威verified/域外不挖/版本差异/entry=B长期选题/去重
        def mkchunk(g, r, auth, text, plat="NES", ets=None, status="verified_read"):
            return {"chunk_id": f"{g}{r}{auth}", "game_id": g, "revision": r, "platform": plat,
                    "authority": auth, "status": status, "element_types": ets or ["攻略"],
                    "heading": "", "text": text, "path": f"{g}.md", "line_start": 1, "source_id": "kb"}
        idx = td / "synth_index.json"
        idx.write_text(json.dumps({"chunks": [
            mkchunk("nekketsu_soccer2", "fc_jp", "authoritative", "热血足球 攻略 必杀 隐藏要素"),
            mkchunk("nekketsu_soccer2", "multi", "reference_only", "热血足球 二手 攻略")]}), encoding="utf-8")
        bc, bi = 入口B挖题.mine(prof, index_path=idx)
        check("T27a 反证:reference_only不挖",
              bi["mined"] == 1 and all(h["authority"] == "authoritative" for c in bc for h in c["kb"]["hits"]),
              f"mined={bi['mined']}")
        # 域过滤后，无受众匹配反证须用内容域块(arcade_hack_multi revision锚定)；否则unknown_game/r1
        # 在auth阶段就被域排除、到不了受众skip逻辑(skipped=0)。meta=0证明是受众skip而非域排除。
        idx.write_text(json.dumps({"chunks": [
            mkchunk("unknown_arcade", "arcade_hack_multi", "authoritative", "xyz completely unrelated content", plat="ANY", ets=[])]}),
            encoding="utf-8")
        bc2, bi2 = 入口B挖题.mine(prof, index_path=idx)
        check("T27b 反证:内容域块无受众匹配不挖", bi2["mined"] == 0 and bi2["skipped"] >= 1
              and bi2["meta_blocks_excluded"] == 0,
              f"mined={bi2['mined']} skipped={bi2['skipped']} meta={bi2['meta_blocks_excluded']}")
        idx.write_text(json.dumps({"chunks": [
            mkchunk("nekketsu_soccer2", "fc_jp", "authoritative", "热血足球 攻略 必杀 隐藏要素"),
            mkchunk("nekketsu_soccer2", "multi", "authoritative", "热血足球 改版 攻略 必杀")]}), encoding="utf-8")
        bc3, bi3 = 入口B挖题.mine(prof, index_path=idx)
        check("T27c 同game≥2revision版本差异中",
              bi3["mined"] == 2 and all(c["dims"]["反差与故事性"]["level"] == "中" for c in bc3)
              and any("版本对照" in c["core_hook"] for c in bc3))
        check("T27d 挖题卡entry=B且长期选题(不许今日优先)",
              all(c["entry"] == "B" and c["queue"] == "长期选题" for c in bc3))
        nt0 = 事件归并.norm_title(bc3[0]["core_hook"])
        bc4, bi4 = 入口B挖题.mine(prof, news_titles={nt0}, index_path=idx)
        check("T27e 与新闻标题去重", bi4["mined"] == bi3["mined"] - 1, f"{bi3['mined']}->{bi4['mined']}")
        check("T27g 挖题不硬编码pass(status=mined+证据标签不入HARD+出证恒空)",
              all(c["kb"]["status"] == "mined" and c["kb"]["selected_evidence"] == []
                  and c["evidence_status"] not in 系列归并.HARD and c["evidence_scope"]
                  for c in bc3),
              f"kb0={bc3[0]['kb'].get('status')} ev0={bc3[0]['evidence_status']}")
        md_mined = 选题卡.render_card_md(bc3[0])
        check("T27h 挖题卡面:权威块标'未经问句对照,非出证',不冒充KB出证",
              "KB挖题权威块" in md_mined and "非出证" in md_mined and "KB出证" not in md_mined,
              md_mined[:200])
        if real_kb_index.is_file():
            bcr, bir = 入口B挖题.mine(prof, index_path=real_kb_index)
            need_b = ["event_id", "entry", "queue", "dims", "kb", "core_hook", "evidence_status", "title_only_note"]
            check("T27f 真实快照挖题卡字段齐全+域守恒(现查)",
                  bir["mined"] >= 1 and all(k in c for c in bcr for k in need_b)
                  and all(c["queue"] == "长期选题" for c in bcr)
                  and all(c["kb"]["status"] != "pass" for c in bcr)
                  and bir["content_chunks"] + bir["meta_blocks_excluded"] == bir["authoritative_chunks"]
                  and bir["meta_blocks_excluded"] >= 1
                  and all("project_docs" not in c["core_hook"] for c in bcr),
                  f"mined={bir['mined']} auth={bir['authoritative_chunks']} content={bir['content_chunks']} meta={bir['meta_blocks_excluded']}")
        else:
            check("T27f 真实快照挖题卡字段齐全(现查)", False, "真实kb快照缺失")

        # T28 正文采集：离线mock（不碰真实网络），失败显式/ok翻title_only/snippet≤240/抽取去噪
        class FakeHeaders:
            def get_content_charset(self):
                return "utf-8"

        class FakeResp:
            def __init__(self, html, status=200):
                self._b = html.encode("utf-8")
                self.status = status
                self.headers = FakeHeaders()
            def read(self, n):
                return self._b[:n]
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        html_ok = ("<html><body><script>badjs</script><nav>menu</nav>"
                   "<article><p>热血足球 隐藏结局 终于 被触发 攻略 发布</p></article></body></html>")
        with patch.object(正文采集.urllib.request, "urlopen", return_value=FakeResp(html_ok)):
            rec_ok = 正文采集.fetch("https://example.test/ok", cache_dir=td / "正文缓存")
        check("T28a 抽取去script/nav留正文",
              rec_ok["status"] == "ok" and "badjs" not in rec_ok["main_text"]
              and "menu" not in rec_ok["main_text"] and "隐藏结局" in rec_ok["main_text"])
        check("T28b 版权:snippet≤240", len(rec_ok["snippet"]) <= 240)
        ev_b = 事件归并.merge_events([mkrow("b", "热血足球 隐藏结局", "https://example.test/ok", "s1")])[0]
        c_ok = 关注分层.score_event(ev_b, prof, {"status": "off"}, TODAY, body=rec_ok)
        check("T28c body ok翻title_only=False+snippet≤240",
              c_ok["title_only"] is False and c_ok["body_status"] == "ok" and len(c_ok["body_snippet"]) <= 240)
        check("T28d body精修反差维→中", c_ok["dims"]["反差与故事性"]["level"] == "中")
        with patch.object(正文采集.urllib.request, "urlopen", side_effect=urllib.error.URLError("probe fail")):
            rec_err = 正文采集.fetch("https://example.test/err", cache_dir=td / "正文缓存")
        check("T28e 反证:fetch失败显式error留痕", rec_err["status"] == "error" and bool(rec_err.get("error")),
              f"status={rec_err['status']}")
        c_err = 关注分层.score_event(ev_b, prof, {"status": "off"}, TODAY, body=rec_err)
        check("T28f body error保持title_only=True", c_err["title_only"] is True and "失败" in c_err["title_only_note"])
        try:
            正文采集.UA.encode("latin-1")
            ua_ok = True
        except UnicodeEncodeError:
            ua_ok = False
        check("T28g 反证:UA头latin-1可编(防中文头复发)", ua_ok, f"UA={正文采集.UA}")
        err_cp = 正文采集._cache_path("https://example.test/err", td / "正文缓存")
        check("T28h 反证:fetch错误不写缓存(允许重试)", not err_cp.exists())
        with patch.object(正文采集.urllib.request, "urlopen",
                          return_value=FakeResp("<html><body><script>onlyjs</script></body></html>")):
            rec_empty = 正文采集.fetch("https://example.test/empty", cache_dir=td / "正文缓存")
        check("T28i 反证:HTTP200无正文标empty不冒ok", rec_empty["status"] == "empty" and rec_empty.get("error"),
              f"status={rec_empty['status']}")
        c_empty = 关注分层.score_event(ev_b, prof, {"status": "off"}, TODAY, body=rec_empty)
        check("T28j empty不翻title_only", c_empty["title_only"] is True)
        stale_url = "https://example.test/stale"
        scp = 正文采集._cache_path(stale_url, td / "正文缓存")
        scp.parent.mkdir(parents=True, exist_ok=True)
        scp.write_text(json.dumps({"url": stale_url, "status": "ok", "snippet": "",
                                   "main_text": "", "locator": stale_url}), encoding="utf-8")
        with patch.object(正文采集.urllib.request, "urlopen", return_value=FakeResp(html_ok)):
            rec_stale = 正文采集.fetch(stale_url, cache_dir=td / "正文缓存")
        check("T28k 反证:ok-空文本陈旧缓存不信任(重取)",
              rec_stale["status"] == "ok" and bool(rec_stale.get("snippet")),
              f"status={rec_stale['status']} snippet空={not rec_stale.get('snippet')}")

        # T30 B站需求探针：离线mock search（不真联网不写真实状态）。恒量反证格守
        # 相关度污染闸门/去污染中位/412不冒0/empty不冒高/互动率/recency/缓存只ok/限速/版权。
        B = B站热度探针
        T_TS = 1785000000          # 固定 recency 参考时刻（与 ts_epoch 解耦）
        TH = {"play_median_high": 35000, "play_median_mid": 8000}

        def _bv(title, play, pub, like=0, fav=0, dan=0, rev=0, bvid="BV1x"):
            return {"title": title, "play": play, "pubdate": pub, "like": like,
                    "favorites": fav, "danmaku": dan, "review": rev,
                    "bvid": bvid, "author": "up"}

        def _mock_search(data, status, error=""):
            return patch.object(B, "search", return_value=(data, status, error))

        hot_vids = [_bv("热血足球全必杀排名", 50000 + i * 1000, T_TS - 10 * 86400) for i in range(20)]
        with _mock_search({"numResults": 1000, "result": hot_vids}, "ok"):
            r_hot = B.measure("热血足球", None, now_ts=T_TS, use_cache=False)
        lvl_hot, why_hot = B.classify(r_hot, TH)
        check("T30a 热IP词(热血足球)真相关视频→高需求",
              r_hot["core_hit_rate"] == 1.0 and r_hot["relevant_play_median"] == 59500 and lvl_hot == "高",
              f"chr={r_hot['core_hit_rate']} rpm={r_hot['relevant_play_median']} lvl={lvl_hot}")
        # 反证：model2-nx 被 B站兜底到 UG NX CAD（标题不含 model2）→核心命中0→未知，不冒充中
        cold_vids = [_bv("UG-NX10.0软件安装教程", 14587, T_TS - 10 * 86400) for i in range(20)]
        with _mock_search({"numResults": 1000, "result": cold_vids}, "ok"):
            r_cold = B.measure("model2-nx", None, now_ts=T_TS, use_cache=False)
        lvl_cold, why_cold = B.classify(r_cold, TH)
        check("T30b 反证:模糊兜底(model2-nx→NX CAD)核心命中0→未知不冒充中",
              r_cold["core_hit_rate"] == 0.0 and lvl_cold == "未知" and "兜底" in why_cold,
              f"chr={r_cold['core_hit_rate']} lvl={lvl_cold}")
        with _mock_search(None, "error", "412风控(request was banned)"):
            r_412 = B.measure("热血足球", None, now_ts=T_TS, use_cache=False)
        lvl_412, _ = B.classify(r_412, TH)
        check("T30c 反证:412风控→error→未知不冒充0需求",
              r_412["status"] == "error" and lvl_412 == "未知", f"status={r_412['status']}")
        with _mock_search({"numResults": 0, "result": []}, "empty", "numResults=0"):
            r_empty = B.measure("某词", None, now_ts=T_TS, use_cache=False)
        lvl_empty, _ = B.classify(r_empty, TH)
        check("T30d 反证:空结果→empty→未知不冒充高",
              r_empty["status"] == "empty" and lvl_empty == "未知", f"status={r_empty['status']}")
        eng_vids = [_bv("热血足球", 1000, T_TS - 10 * 86400, like=10, fav=20, dan=30, rev=40) for i in range(20)]
        with _mock_search({"numResults": 1000, "result": eng_vids}, "ok"):
            r_eng = B.measure("热血足球", None, now_ts=T_TS, use_cache=False)
        check("T30e 互动率=(赞+藏+弹幕+评)/播放=0.1",
              abs(r_eng["engagement_median"] - 0.1) < 1e-9, f"eng={r_eng['engagement_median']}")
        rec_vids = ([_bv("热血足球", 5000, T_TS - 10 * 86400) for i in range(10)]
                    + [_bv("热血足球", 90000, T_TS - 200 * 86400) for i in range(10)])
        with _mock_search({"numResults": 1000, "result": rec_vids}, "ok"):
            r_rec = B.measure("热血足球", None, now_ts=T_TS, use_cache=False)
        check("T30f recency只算近90天(老视频排除)",
              r_rec["recent_count"] == 10 and r_rec["recent_play_median"] == 5000,
              f"rc={r_rec['recent_count']} rpm={r_rec['recent_play_median']}")
        mix_vids = ([_bv("热血足球必杀", 50000, T_TS - 10 * 86400) for i in range(10)]
                    + [_bv("无关搞笑视频", 100, T_TS - 10 * 86400) for i in range(10)])
        with _mock_search({"numResults": 1000, "result": mix_vids}, "ok"):
            r_mix = B.measure("热血足球", None, now_ts=T_TS, use_cache=False)
        check("T30g 去污染中位剔除兜底(相关50000≠原始25050,核心命中0.5)",
              r_mix["relevant_play_median"] == 50000 and r_mix["play_median"] == 25050
              and r_mix["core_hit_rate"] == 0.5,
              f"rpm={r_mix['relevant_play_median']} raw={r_mix['play_median']} chr={r_mix['core_hit_rate']}")
        with _mock_search(None, "error", "net"):
            B.measure("缓存err", None, now_ts=T_TS, use_cache=True)
        with _mock_search({"numResults": 1000, "result": hot_vids}, "ok"):
            B.measure("热血足球", None, now_ts=T_TS, use_cache=True)
        check("T30h 反证:缓存只ok(error不写,允许重试)",
              not B._cache_path("缓存err").exists() and B._cache_path("热血足球").exists())
        check("T30i 限速/退避常量在(防风控)",
              B.MIN_INTERVAL >= 1.5 and B.RETRY_MAX <= 2 and B.TIMEOUT > 0 and B.RECENT_DAYS == 90,
              f"interval={B.MIN_INTERVAL} retry={B.RETRY_MAX}")
        lvl_none, _ = B.classify(r_hot, None)
        check("T30j 反证:阈值未定→未知(先跑数据不写死)", lvl_none == "未知", f"lvl={lvl_none}")
        check("T30k CJK复合词2字子词命中(街机改版不假旗/拳皇无街机词不算)",
              B._core_hit("街机改版", "街机游戏：三国志2 修改版合集")
              and not B._core_hit("街机改版", "是不是你印象中的《拳皇》")
              and B._core_hit("开源掌机", "盘点适合新手的掌机"))
        check("T30l 诚实边界:高命中≠语义相关警示在reason(星之海歧义须人工核)",
              "语义相关" in why_hot and "top3" in why_hot, why_hot)
        check("T30m 版权:top3短标题≤TITLE_MAX",
              all(len(t["title"]) <= B.TITLE_MAX for t in r_hot["top3"]))
        low_vids = [_bv("拳皇98 combo", 3000, T_TS - 10 * 86400) for i in range(20)]
        with _mock_search({"numResults": 1000, "result": low_vids}, "ok"):
            r_low = B.measure("拳皇98", None, now_ts=T_TS, use_cache=False)
        lvl_low, _ = B.classify(r_low, TH)
        check("T30n 反证:供给capped1000不抬高需求(低播放→低)",
              r_low["supply_num_results"] == 1000 and lvl_low == "低", f"lvl={lvl_low}")
        ever_vids = ([_bv("星之卡比攻略", 90000, T_TS - 200 * 86400) for i in range(18)]
                     + [_bv("星之卡比新作", 2000, T_TS - 10 * 86400) for i in range(2)])
        with _mock_search({"numResults": 1000, "result": ever_vids}, "ok"):
            r_ever = B.measure("星之卡比", None, now_ts=T_TS, use_cache=False)
        check("T30o 总中位/近期播放指标可区分(原始量,track判读另见T34)",
              r_ever["relevant_play_median"] >= 8000 and r_ever["recent_play_median"] == 2000
              and r_ever["recent_count"] == 2,
              f"rpm={r_ever['relevant_play_median']} recent={r_ever['recent_play_median']}")

        # T31 B站需求回流（§11.8）：离线，只读合成探针结果（PROBE_RESULTS已patch到tempdir），
        # 不联网不写真实状态。恒量反证格守：映射可靠档/优先级/污染退回/未映射退回/粒度警示/
        # 消歧/★demand不进关注队列/版权/频道适配/可靠低不冒充/计数一致。
        R = 需求回流

        def _prec(kw, lvl, pm_, chr_, eng, rc, rpm_, bvid="BV1test", title="短标题"):
            return {"keyword": kw, "status": "ok", "ts": "2026-11-19T00:00:00Z",
                    "demand_level": lvl, "relevant_play_median": pm_, "core_hit_rate": chr_,
                    "engagement_median": eng, "recent_count": rc, "recent_play_median": rpm_,
                    "top3": [{"bvid": bvid, "title": title, "play": pm_, "pubdate": "2026-11-01"}]}

        synth = [
            _prec("星之卡比", "高", 63136, 1.0, 0.026, 0, 0),
            _prec("热血足球", "高", 35184, 0.9, 0.045, 4, 365),
            _prec("塞尔达传说", "中", 18212, 0.75, 0.027, 12, 15308),
            _prec("shadPS4", "中", 11409, 0.75, 0.037, 3, 1644),
            _prec("拳皇98", "低", 5221, 1.0, 0.032, 10, 596),
            _prec("Sea of Stars", "低", 2531, 0.95, 0.076, 3, 3264),
            _prec("Switch2 破解", "中", 8286, 0.75, 0.023, 15, 8286),
            _prec("toniisound", "未知", 0, 0.0, 0, 0, 0),
        ]
        (td / "探针结果.json").write_text(json.dumps(synth, ensure_ascii=False), encoding="utf-8")
        pm = R.load_probe()
        check("T31pre load_probe只读合成探针(8词,不联网)",
              len(pm) == 8 and pm["星之卡比"]["demand_level"] == "高", f"words={len(pm)}")

        def _ev(titles, eid="e1", focus=None):
            return {"event_id": eid, "titles": titles, "focus": focus or []}

        ts_mid = {"level": "中", "reason": "热度时序来源上升(媒体覆盖代理)", "evidence": ["span"]}
        d_kirby = R.demand_for_event(_ev(["Nintendo Reveals New Kirby Game"]), pm)
        check("T31a 映射可靠高(kirby→星之卡比,带代理/粒度)",
              d_kirby["level"] == "高" and "B站已有视频热度代理" in d_kirby["reason"]
              and "星之卡比" in d_kirby["reason"] and "粒度" in d_kirby["reason"], d_kirby["reason"])
        d_prec = R.demand_for_event(_ev(["Kirby new game"]), pm, ts_mid)
        check("T31b 优先级:B站高优先于热度时序中",
              d_prec["level"] == "高" and "优先于热度时序" in d_prec["reason"], d_prec["reason"])
        pm_contam = {**pm, "星之卡比": _prec("星之卡比", "未知", 0, 0.0, 0, 0, 0)}
        d_contam = R.demand_for_event(_ev(["Kirby new game"]), pm_contam, ts_mid)
        check("T31c 反证:污染词(核心命中0)退回热度时序中,不冒充未知/高",
              d_contam["level"] == "中" and "不冒充" in d_contam["reason"] and "退回" in d_contam["reason"],
              d_contam["reason"])
        d_ff = R.demand_for_event(_ev(["Final Fantasy VIII Remastered"]), pm, ts_mid)
        check("T31d 反证:未映射IP(final fantasy)退回热度时序,标未探针",
              d_ff["level"] == "中" and "未探针" in d_ff["reason"], d_ff["reason"])
        d_noprobe = R.demand_for_event(_ev(["Kirby new game"]), {}, None)
        check("T31e 反证:映射词不在探针结果→未探针未知",
              d_noprobe["level"] == "未知" and "不在本轮探针结果" in d_noprobe["reason"], d_noprobe["reason"])
        d_sw = R.demand_for_event(_ev(["Switch 2 jailbreak exploit"]), pm)
        d_kof = R.demand_for_event(_ev(["King of Fighters 98 update"]), pm)
        check("T31f 粒度警示:switch2角度/拳皇细分",
              "角度" in d_sw["reason"] and "细分" in d_kof["reason"], d_sw["reason"] + " | " + d_kof["reason"])
        d_sos = R.demand_for_event(_ev(["Sea of Stars new patch"]), pm)
        kw_used = d_sos["reason"].split("实测词「")[1].split("」")[0]
        check("T31g 消歧:sea of stars实测词=英文Sea of Stars(非星之海)",
              kw_used == "Sea of Stars" and "英文原名" in d_sos["reason"], kw_used)
        # ★T31h 安全反证：demand_override仅信息维，不进关注合成/队列（§3）
        low_ev = 事件归并.merge_events(
            [mkrow("k1", "quarterly infrastructure typo cleanup", "https://x/1", "s1", kind="github_atom")])[0]
        hi_dim = {"level": "高", "reason": "B站高需求", "evidence": []}
        c_none = 关注分层.score_event(low_ev, prof, None, TODAY)
        c_hi = 关注分层.score_event(low_ev, prof, None, TODAY, demand_override=hi_dim)
        check("T31h ★反证:喂高demand低匹配事件队列不变(仅信息维,不进关注/队列)",
              c_hi["dims"]["需求信号"]["level"] == "高"
              and c_hi["attention"] == c_none["attention"] == "低"
              and c_hi["queue"] == c_none["queue"] == "低优先归档",
              f"att={c_hi['attention']} queue={c_hi['queue']} demand={c_hi['dims']['需求信号']['level']}")
        ev_k = d_kirby["evidence"]
        titles_ok = all(len(e.split("｜")[1]) <= 60 for e in ev_k if e.startswith("BV"))
        check("T31i 版权:evidence带bvid+探针ts+短标题≤60",
              any("B站探针" in e and "@" in e for e in ev_k)
              and any(e.startswith("BV") for e in ev_k) and titles_ok, str(ev_k))
        d_soccer = R.demand_for_event(_ev(["热血足球必杀排名"]), pm)
        d_zelda = R.demand_for_event(_ev(["Zelda Ocarina of Time remake"]), pm)
        check("T31j 频道适配track-aware:热血足球怀旧供给缺口机会/塞尔达跨代待核(非旧警示)",
              "供给缺口机会" in d_soccer["reason"] and "跨代" in d_zelda["reason"]
              and "非当前热" not in d_soccer["reason"],
              d_soccer["reason"][-40:] + " | " + d_zelda["reason"][-40:])
        check("T31k 反证:可靠低(拳皇98)不冒充中",
              d_kof["level"] == "低" and "需求低" in d_kof["reason"], d_kof["reason"])
        dm, info = R.build_demand_map(
            [_ev(["Kirby game"], "e1"), _ev(["热血足球"], "e2"),
             _ev(["无名项目 commit"], "e3"), _ev(["Final Fantasy"], "e4")], pm, {})
        check("T31l build_demand_map计数一致(映射2可靠2/未映射2)",
              info["mapped_cards"] == 2 and info["reliable_override"] == 2
              and info["unmapped_fallback"] == 2 and len(dm) == 4
              and info["map_version"] == R.MAP_VERSION, str(info))

        # T32 回流接进入口B挖题链：mine(probe_map)→B卡需求信号取实测B站档(仅信息维,queue恒长期选题)。
        # 复用T31合成探针pm(热血足球高/拳皇98低)+T27 mkchunk/prof合成索引,不碰真实快照/探针。
        BILI = "B站已有视频热度代理"
        idx.write_text(json.dumps({"chunks": [
            mkchunk("nekketsu_soccer2", "fc_jp", "authoritative", "热血足球 攻略 必杀 隐藏要素"),
            mkchunk("kof98", "arcade", "authoritative", "拳皇98 连招 攻略 必杀", plat="ARCADE")]}),
            encoding="utf-8")
        bc_off, _ = 入口B挖题.mine(prof, index_path=idx)
        bc_on, bi_on = 入口B挖题.mine(prof, index_path=idx, probe_map=pm)
        soc_off = next((c for c in bc_off if c["ip_name"] == "热血系列"), None)
        soc_on = next((c for c in bc_on if c["ip_name"] == "热血系列"), None)
        kof_on = next((c for c in bc_on if c["ip_name"] == "king of fighters"), None)
        check("T32a 入口B热血足球卡接回流→需求高(实测词热血足球/粒度细分)",
              soc_on is not None and soc_on["dims"]["需求信号"]["level"] == "高"
              and BILI in soc_on["dims"]["需求信号"]["reason"]
              and "热血足球" in soc_on["dims"]["需求信号"]["reason"]
              and "细分" in soc_on["dims"]["需求信号"]["reason"],
              soc_on["dims"]["需求信号"]["reason"] if soc_on else "热血足球B卡未挖出")
        check("T32b 反证:默认mine(probe_map=None)需求未知KB挖题无热度时序(不静默顶包)",
              soc_off is not None and soc_off["dims"]["需求信号"]["level"] == "未知"
              and "KB挖题无热度时序" in soc_off["dims"]["需求信号"]["reason"]
              and BILI not in soc_off["dims"]["需求信号"]["reason"],
              soc_off["dims"]["需求信号"]["reason"] if soc_off else "off卡未挖出")
        check("T32c 入口B拳皇98卡可靠低不冒充中/高",
              kof_on is not None and kof_on["dims"]["需求信号"]["level"] == "低"
              and "需求低" in kof_on["dims"]["需求信号"]["reason"],
              kof_on["dims"]["需求信号"]["reason"] if kof_on else "拳皇98B卡未挖出")
        check("T32d ★反证:B卡需求高但queue恒长期选题entry=B且attention on==off(信息维不进队列)",
              soc_on is not None and soc_off is not None
              and soc_on["dims"]["需求信号"]["level"] == "高"
              and soc_on["queue"] == "长期选题" and soc_on["entry"] == "B"
              and soc_on["attention"] == soc_off["attention"],
              f"queue={soc_on['queue'] if soc_on else '?'} att={soc_on['attention'] if soc_on else '?'}/{soc_off['attention'] if soc_off else '?'}")
        bc_empty, _ = 入口B挖题.mine(prof, index_path=idx, probe_map={})
        soc_empty = next((c for c in bc_empty if c["ip_name"] == "热血系列"), None)
        check("T32e 反证:probe_map空(映射词不在探针)→B卡未知未探针留痕,不编造",
              soc_empty is not None and soc_empty["dims"]["需求信号"]["level"] == "未知"
              and "未探针" in soc_empty["dims"]["需求信号"]["reason"]
              and BILI not in soc_empty["dims"]["需求信号"]["reason"],
              soc_empty["dims"]["需求信号"]["reason"] if soc_empty else "empty卡未挖出")
        pm_ct = {**pm, "热血足球": _prec("热血足球", "未知", 0, 0.0, 0, 0, 0)}
        bc_ct, _ = 入口B挖题.mine(prof, index_path=idx, probe_map=pm_ct)
        soc_ct = next((c for c in bc_ct if c["ip_name"] == "热血系列"), None)
        check("T32f 反证:污染词(热血足球核心命中0)→B卡退回未知KB context,不冒充高",
              soc_ct is not None and soc_ct["dims"]["需求信号"]["level"] == "未知"
              and "不冒充" in soc_ct["dims"]["需求信号"]["reason"]
              and "KB挖题无热度时序" in soc_ct["dims"]["需求信号"]["reason"],
              soc_ct["dims"]["需求信号"]["reason"] if soc_ct else "ct卡未挖出")
        idx.write_text(json.dumps({"chunks": [
            mkchunk("nekketsu_soccer2", "fc_jp", "authoritative", "热血足球 攻略 必杀 隐藏要素"),
            mkchunk("nekketsu_soccer2", "multi", "authoritative", "热血足球 改版 攻略 必杀")]}),
            encoding="utf-8")
        bc_ver, bi_ver = 入口B挖题.mine(prof, index_path=idx, probe_map=pm)
        check("T32g 版本对照B卡仍接回流高+info.bili_demand_wired计数一致",
              bi_ver["mined"] == 2 and bi_ver["bili_demand_wired"] == 2
              and all(c["dims"]["需求信号"]["level"] == "高" for c in bc_ver)
              and any("版本对照" in c["core_hook"] for c in bc_ver),
              f"mined={bi_ver['mined']} wired={bi_ver['bili_demand_wired']}")

        # T33 入口B域过滤(说明书§10.1)：meta域(project_docs/tooling内部文档)块不挖，即使文本含受众词/IP；
        # 内容域块仍挖且回流不断。与域锚点闸门同源content_block。复用T31 pm/T27 mkchunk合成索引,不碰真实快照。
        idx.write_text(json.dumps({"chunks": [
            mkchunk("multi", "project_docs", "authoritative", "热血足球 攻略 必杀 隐藏要素"),
            mkchunk("nekketsu_soccer2", "fc_jp", "authoritative", "热血足球 攻略 必杀 隐藏要素")]}),
            encoding="utf-8")
        bc_a, bi_a = 入口B挖题.mine(prof, index_path=idx, probe_map=pm)
        check("T33a ★反证:project_docs内部文档块不挖(即使含热血足球IP/受众词),只挖内容域块",
              bi_a["mined"] == 1 and bi_a["meta_blocks_excluded"] == 1
              and bi_a["content_chunks"] == 1 and bi_a["authoritative_chunks"] == 2
              and all("project_docs" not in c["core_hook"] for c in bc_a),
              f"mined={bi_a['mined']} meta={bi_a['meta_blocks_excluded']} content={bi_a['content_chunks']} auth={bi_a['authoritative_chunks']}")
        soc_a = next((c for c in bc_a if c["ip_name"] == "热血系列"), None)
        check("T33b 内容域块仍挖且回流不断(热血足球高/queue恒长期选题entry=B)",
              soc_a is not None and soc_a["dims"]["需求信号"]["level"] == "高"
              and BILI in soc_a["dims"]["需求信号"]["reason"]
              and soc_a["queue"] == "长期选题" and soc_a["entry"] == "B",
              soc_a["dims"]["需求信号"]["reason"] if soc_a else "内容域热血足球卡未挖出")
        idx.write_text(json.dumps({"chunks": [
            mkchunk("multi", "project_docs", "authoritative", "TAS 金手指 改版 攻略"),
            mkchunk("kof98", "kof98eck", "authoritative", "拳皇98 连招 攻略 必杀", plat="ARCADE")]}),
            encoding="utf-8")
        bc_c, bi_c = 入口B挖题.mine(prof, index_path=idx, probe_map=pm)
        kof_c = next((c for c in bc_c if c["ip_name"] == "king of fighters"), None)
        check("T33c ★反证:project_docs(TAS金手指)不挖,kof98内容块仍挖可靠低不冒充",
              bi_c["mined"] == 1 and bi_c["meta_blocks_excluded"] == 1
              and kof_c is not None and kof_c["dims"]["需求信号"]["level"] == "低"
              and BILI in kof_c["dims"]["需求信号"]["reason"]
              and all("project_docs" not in c["core_hook"] for c in bc_c),
              f"mined={bi_c['mined']} meta={bi_c['meta_blocks_excluded']} kof={kof_c['dims']['需求信号']['level'] if kof_c else '未挖出'}")

        # T34 两条受欢迎逻辑 track-aware 判读（§11.10，只改判读标签；需求档/队列不动）。
        # 复用 T31 pm（合成探针）/TH/soc_a（T33 热血足球内容卡）。channel_fit 纯函数不写盘。
        fit_soccer = B.channel_fit(pm["热血足球"])   # 怀旧 cold(365<35184*0.3)
        fit_kirby = B.channel_fit(pm["星之卡比"])     # 新游 cold(rc=0)
        check("T34a 怀旧近期冷→供给缺口机会(非警示/非当前热)",
              "供给缺口机会" in fit_soccer and "警示" not in fit_soccer
              and "非当前热" not in fit_soccer, fit_soccer[:50])
        check("T34b 新游近期冷→热度消退(通关即终·窗口收窄,非供给缺口)",
              "热度消退" in fit_kirby and "供给缺口机会" not in fit_kirby, fit_kirby[:50])
        # ★恒量反证：同 pm/rpm/rc 数字、不同 track → 不同标签（证明 track 驱动判读非数字）
        same = {"relevant_play_median": 35184, "recent_play_median": 366, "recent_count": 4}
        fit_retro = B.channel_fit({"keyword": "热血足球", **same})
        fit_new = B.channel_fit({"keyword": "剑星", **same})
        check("T34c ★恒量反证:同数字不同track→不同标签(怀旧机会vs新游消退)",
              "供给缺口机会" in fit_retro and "热度消退" in fit_new and fit_retro != fit_new,
              f"retro={fit_retro[:16]} new={fit_new[:16]}")
        fit_tool = B.channel_fit(pm["shadPS4"])       # 工具 cold
        check("T34d 工具中性track不套游戏两轨(无供给缺口机会/热度消退)",
              "供给缺口机会" not in fit_tool and "热度消退" not in fit_tool, fit_tool[:50])
        fit_cross = B.channel_fit(pm["塞尔达传说"])   # 跨代
        check("T34e 跨代IP须人工判(不自动套任一轨)",
              "跨代" in fit_cross and "须人工判" in fit_cross, fit_cross[:50])
        # 需求档与 track 无关（classify 只看播放中位）：同 pm 同档；热血足球高/拳皇98低不变
        lvl_r, _ = B.classify({"keyword": "热血足球", "status": "ok", "core_hit_rate": 0.9,
                               "relevant_play_median": 35184}, TH)
        lvl_n, _ = B.classify({"keyword": "剑星", "status": "ok", "core_hit_rate": 0.95,
                               "relevant_play_median": 35184}, TH)
        lvl_k, _ = B.classify({"keyword": "拳皇98", "status": "ok", "core_hit_rate": 1.0,
                               "relevant_play_median": 5221}, TH)
        check("T34f 需求档与track无关(只改判读标签):同pm同档,热血足球高/拳皇98低",
              lvl_r == lvl_n == "高" and lvl_k == "低", f"retro={lvl_r} new={lvl_n} kof={lvl_k}")
        check("T34g 怀旧B卡reason带供给缺口机会但queue恒长期选题entry=B(标签重构不提拔)",
              soc_a is not None and "供给缺口机会" in soc_a["dims"]["需求信号"]["reason"]
              and soc_a["queue"] == "长期选题" and soc_a["entry"] == "B",
              f"soc_queue={soc_a['queue'] if soc_a else None}")
        # render_stats 产物按 track 分组、retro 无旧警示 framing（生产渲染路径，返回字符串不写盘）
        rend = []
        for kw in ["热血足球", "星之卡比", "shadPS4", "塞尔达传说", "Switch2 破解"]:
            rr = dict(pm[kw])
            rr.update(play_median=pm[kw]["relevant_play_median"], source="test",
                      granularity="大盘", demand_reason="x")
            rr["top3"] = [{**t, "author": "testUP"} for t in pm[kw].get("top3", [])]
            rend.append(rr)
        ri_min = {"ts": "2026-11-19T00:00:00Z", "words": len(rend), "cookie_ok": True,
                  "cookie_names": ["buvid3"], "pages_per_word": 1, "min_interval_s": 1.5,
                  "note": "test", "status_counts": {"ok": len(rend)},
                  "demand_counts": {"高": 2, "中": 2, "低": 1}, "thresholds": TH,
                  "relevance_min": 0.3, "contaminated_words": [],
                  "relevant_play_median_distribution": {"min": 8286, "median": 18212, "max": 63136}}
        md = B.render_stats(rend, ri_min)
        check("T34h render_stats按track分组:怀旧供给缺口机会/新游热度消退,无旧evergreen警示framing",
              "供给缺口机会" in md and "热度消退" in md and "怀旧游戏" in md
              and "长尾老爆款(evergreen)警示" not in md and "非当前热" not in md, f"len={len(md)}")
        check("T34i track表覆盖全部探针词(无未分类)",
              all(B.word_track(kw) != "未分类" for kw, _, _ in B.PILOT_WORDS),
              f"n={len(B.PILOT_WORDS)}")
        check("T34j 回流_channel_fit委托探针channel_fit单一权威(track-aware)",
              R._channel_fit(pm["热血足球"]) == B.channel_fit(pm["热血足球"])
              and "供给缺口机会" in R._channel_fit(pm["热血足球"]), "delegation mismatch")
        # ★T34k 反证:render新游trending/fading须同channel_fit口径不重叠
        # (剑星总49491近期9560:相对冷→只fading;旧绝对med_all口径会误入both,真实数据翻出过)
        ov = []
        for kw, lvl, pm_, chr_, eng, rc, rpm_ in [
                ("剑星", "高", 49491, 0.95, 0.019, 6, 9560),
                ("拳皇98", "低", 5221, 1.0, 0.032, 10, 596),
                ("Sea of Stars", "低", 2531, 0.95, 0.076, 3, 3264),
                ("Batocera", "低", 5671, 0.85, 0.063, 6, 1153)]:
            rr = _prec(kw, lvl, pm_, chr_, eng, rc, rpm_)
            rr.update(play_median=pm_, source="t", granularity="大盘", demand_reason="x")
            rr["top3"] = [{**t, "author": "u"} for t in rr["top3"]]
            ov.append(rr)
        md2 = B.render_stats(ov, {**ri_min, "words": len(ov), "status_counts": {"ok": len(ov)},
                                  "demand_counts": {"高": 1, "低": 3},
                                  "relevant_play_median_distribution": {"min": 2531, "median": 5446, "max": 49491}})
        trend_line = next((l for l in md2.splitlines() if "新游·当前活跃" in l), "")
        fade_line = next((l for l in md2.splitlines() if "新游·热度消退" in l), "")
        check("T34k ★反证:render新游trending/fading同口径不重叠(剑星只fading非both)",
              "剑星" in fade_line and "剑星" not in trend_line,
              f"trend={trend_line[-24:]} fade={fade_line[-24:]}")

        # T35 扩词表(card→keyword零LLM prep,§11.11)：自动取大盘候选词+surface高关注未探针IP,不改demand/queue,不联网。
        def _card(ip, att, queue="潜力待验证", major=False, hook="某新闻标题", eid="c1", **extra):
            d = {"event_id": eid, "ip_name": ip, "attention": att, "queue": queue,
                 "major_event": major, "core_hook": hook}
            d.update(extra)
            return d

        w_m, k_m, _ = R._candidate_word("metroid")
        check("T35a 自动取词IP大盘=组首个中文别名(metroid→银河战士,非英文)",
              w_m == "银河战士" and k_m == "IP大盘", f"{w_m}/{k_m}")
        w_b, k_b, _ = R._candidate_word("batocera")
        check("T35b 自动取词项目/平台名原样(batocera,中文品类词须人工补)",
              w_b == "batocera" and k_b == "项目/平台", f"{w_b}/{k_b}")
        exp_c, info_c = R.build_expansion_list([_card("metroid", "高", eid="m1")], pm)
        check("T35c 高关注未映射IP进扩词表(metroid候选银河战士)",
              any(g["ip_name"] == "metroid" and g["candidate_word"] == "银河战士" for g in exp_c),
              str([g["ip_name"] for g in exp_c]))
        exp_d, _ = R.build_expansion_list([_card("kirby", "高", eid="k1")], pm)
        check("T35d ★恒量反证:已映射且词已探针(kirby→星之卡比)不进扩词表(非覆盖缺口)",
              not any(g["ip_name"] == "kirby" for g in exp_d) and len(exp_d) == 0,
              str([g["ip_name"] for g in exp_d]))
        exp_e, _ = R.build_expansion_list([_card("metroid", "低", eid="m2")], pm)
        check("T35e 低关注未映射不进扩词表(无名项目不值得测)", len(exp_e) == 0, f"n={len(exp_e)}")
        exp_f, _ = R.build_expansion_list([_card("zelda", "高", eid="z1")], {})
        check("T35f 映射词未探针进表且用编辑词(zelda→塞尔达传说,非自动draft覆盖)",
              any(g["ip_name"] == "zelda" and g["candidate_word"] == "塞尔达传说"
                  and "未探针" in g["gap_kind"] for g in exp_f),
              str([(g["ip_name"], g["candidate_word"], g["gap_kind"]) for g in exp_f]))
        cg = [_card("metroid", "高", eid="g1", queue="潜力待验证",
                    dims={"需求信号": {"level": "未知", "reason": "未探针"}})]
        cg_before = json.dumps(cg, ensure_ascii=False, sort_keys=True)
        R.build_expansion_list(cg, pm)
        cg_after = json.dumps(cg, ensure_ascii=False, sort_keys=True)
        check("T35g ★反证:扩词表不改demand/queue(卡前后字节一致,只读reporting)",
              cg_before == cg_after, "card mutated" if cg_before != cg_after else "unchanged")
        md_exp = R.render_expansion_md(exp_c, info_c)
        check("T35h render产物带人工核/批准联网/不改队列/draft flags",
              "人工" in md_exp and "联网" in md_exp and "不改" in md_exp and "draft" in md_exp,
              f"len={len(md_exp)}")
        exp_i, _ = R.build_expansion_list(
            [_card("metroid", "中", queue="长期选题", entry="B", eid="kbmine:m")], pm)
        check("T35i 入口B卡也进扩词表(entry=B,长期选题)",
              any(g["ip_name"] == "metroid" and "B" in g["entries"] for g in exp_i),
              str([g["entries"] for g in exp_i]))
        exp_j, info_j = R.build_expansion_list(
            [_card("metroid", "中", eid="c1"), _card("metroid", "高", eid="c2"),
             _card("sonic", "高", eid="c3")], pm)
        check("T35j 排名高before中+卡数desc+info计数一致(metroid2卡高居首)",
              exp_j[0]["ip_name"] == "metroid" and info_j["candidate_ips"] == 2
              and info_j["cards_covered"] == 3 and info_j["high_attention_ips"] == 2,
              f"order={[g['ip_name'] for g in exp_j]} info={info_j['candidate_ips']}/{info_j['cards_covered']}")

        # T36 探针就绪度结构预检(§11.12)：复用探针_kw_cores单一权威暴露词元/字符类,引先例提示风险类别,不预测命中率/不判语义/不自动改词/不碰卡。
        pf_a = R._preflight("portmaster")
        check("T36a 纯拉丁portmaster:script纯拉丁+cores_lat[portmaster]+无CJK",
              pf_a["script_class"] == "纯拉丁" and pf_a["cores_lat"] == ["portmaster"]
              and pf_a["cores_cjk"] == [], str(pf_a["script_class"]) + str(pf_a["cores_lat"]))
        pf_b = R._preflight("银河战士")
        check("T36b CJK银河战士:cores暴露泛2字子词战士(假旗风险可见)",
              pf_b["script_class"] == "含CJK" and "战士" in pf_b["cores_cjk"]
              and "战士" in pf_b["cjk_sub2"], str(pf_b["cores_cjk"]))
        pf_c = R._preflight("Dolphin模拟器")
        check("T36c 混合Dolphin模拟器:lat+cjk皆非空",
              pf_c["script_class"] == "混合" and pf_c["cores_lat"] and pf_c["cores_cjk"],
              str(pf_c["script_class"]))
        cg36 = [_card("metroid", "高", eid="p1", queue="潜力待验证",
                      dims={"需求信号": {"level": "未知", "reason": "未探针"}})]
        before36 = json.dumps(cg36, ensure_ascii=False, sort_keys=True)
        R.build_expansion_list(cg36, pm)
        after36 = json.dumps(cg36, ensure_ascii=False, sort_keys=True)
        check("T36d ★恒量反证:预检不改卡(承T35g,卡前后字节一致,只读reporting)",
              before36 == after36, "card mutated" if before36 != after36 else "unchanged")
        exp36e, _ = R.build_expansion_list([_card("portmaster", "高", eid="pm1")], pm)
        g_pm = next(g for g in exp36e if g["ip_name"] == "portmaster")
        check("T36e ★反证:预检不自动改candidate_word(portmaster原样,只加preflight注解)",
              g_pm["candidate_word"] == "portmaster" and g_pm["preflight"]["script_class"] == "纯拉丁",
              f"{g_pm['candidate_word']}/{g_pm['preflight']['script_class']}")
        check("T36f match_note引已实测先例+须人工/不预测/不自动改词留痕(纯拉丁兜底/CJK假旗)",
              "兜底" in pf_a["match_note"] and "model2-nx" in pf_a["match_note"]
              and "不预测" in pf_a["match_note"] and "不自动改词" in pf_a["match_note"]
              and "街机改版" in pf_b["match_note"] and "假阳" in pf_b["match_note"]
              and "须人工" in pf_b["match_note"], f"a={pf_a['match_note'][:20]} b={pf_b['match_note'][:20]}")
        exp36h, info36h = R.build_expansion_list(
            [_card("portmaster", "高", eid="h1"), _card("metroid", "高", eid="h2")], pm)
        md36 = R.render_expansion_md(exp36h, info36h)
        check("T36g render md含就绪度列+结构预检段+逐词探针词元暴露",
              "就绪度" in md36 and "结构预检" in md36 and "探针词元" in md36 and "纯拉丁" in md36,
              f"len={len(md36)}")
        sc_recount = {}
        for g in exp36h:
            s = g["preflight"]["script_class"]
            sc_recount[s] = sc_recount.get(s, 0) + 1
        cores_ok = all(g["preflight"]["cores_lat"] == B._kw_cores(g["candidate_word"])[0]
                       and g["preflight"]["cores_cjk"] == B._kw_cores(g["candidate_word"])[1]
                       for g in exp36h)
        pf_info = info36h["preflight"]
        check("T36h cores==_kw_cores单一权威+info preflight计数逐格从产物现查一致",
              cores_ok and pf_info["script_class_counts"] == sc_recount
              and pf_info["pure_latin"] == sc_recount.get("纯拉丁", 0)
              and pf_info["cjk_with_sub2"] == sum(1 for g in exp36h if g["preflight"]["cjk_sub2"]),
              f"cores_ok={cores_ok} counts={pf_info['script_class_counts']} recount={sc_recount}")

        # T37 编辑拒绝回流(§3.1)：拒绝→制作动作轴降队,三轴/需求不动;仅editorial_judgment,没时间永不降;最新wins;系列全拒降/部分标志。
        ev_rej = 事件归并.merge_events([mkrow(
            "rej1", "Batocera 45 发布 支持开源掌机 PSP 移植",
            "https://github.com/batocera-linux/batocera.linux/releases/tag/batocera-45",
            "gh_batocera", "github_atom", focus="开源掌机与固件")])[0]
        c_base = 关注分层.score_event(ev_rej, prof, {"status": "off"}, TODAY)
        反馈台账.mark("rej_card", "拒绝", event_id=ev_rej["event_id"], reason="小众不知名/标题看不出功能亮点")
        rej_map = 反馈台账.rejected_decisions()
        c_rej = 关注分层.score_event(ev_rej, prof, {"status": "off"}, TODAY, rejected=rej_map)
        check("T37a 拒绝卡降队低优先归档+editorial_rejected+reason携带",
              c_base["queue"] == "今日优先" and c_rej["queue"] == "低优先归档"
              and c_rej.get("editorial_rejected") is True
              and "小众不知名" in c_rej.get("rejection_reason", ""),
              f"base={c_base['queue']} rej={c_rej['queue']}")
        check("T37b ★恒量反证:拒绝只改queue/标志,dims/attention/evidence/需求逐字节同",
              c_rej["attention"] == c_base["attention"]
              and c_rej["evidence_status"] == c_base["evidence_status"]
              and json.dumps(c_rej["dims"], ensure_ascii=False, sort_keys=True)
              == json.dumps(c_base["dims"], ensure_ascii=False, sort_keys=True),
              f"att={c_rej['attention']}/{c_base['attention']}")
        ev_cap = 事件归并.merge_events([mkrow(
            "cap1", "DArkOS 发布 支持开源掌机固件",
            "https://github.com/x/darkos/releases/tag/v1", "gh_x", "github_atom",
            focus="开源掌机与固件")])[0]
        反馈台账.mark("cap_card", "没时间", event_id=ev_cap["event_id"], reason="本周排满")
        rej_map2 = 反馈台账.rejected_decisions()
        c_cap = 关注分层.score_event(ev_cap, prof, {"status": "off"}, TODAY, rejected=rej_map2)
        check("T37c ★反证:没时间(editor_capacity)不进拒绝表不降队",
              ev_cap["event_id"] not in rej_map2 and c_cap["queue"] == "今日优先",
              f"in_rej={ev_cap['event_id'] in rej_map2} queue={c_cap['queue']}")
        ev_fol = 事件归并.merge_events([mkrow(
            "fol1", "Model2 发布 支持开源掌机移植",
            "https://github.com/x/model2/releases/tag/v1", "gh_x", "github_atom",
            focus="开源掌机与固件")])[0]
        ev_ado = 事件归并.merge_events([mkrow(
            "ado1", "Dolphin 发布 支持开源掌机移植",
            "https://github.com/x/dolphin/releases/tag/v1", "gh_x", "github_atom",
            focus="开源掌机与固件")])[0]
        反馈台账.mark("fol_card", "跟进", event_id=ev_fol["event_id"], reason="有兴趣")
        反馈台账.mark("ado_card", "采纳", event_id=ev_ado["event_id"], title=ev_ado["titles"][0])
        rej_map3 = 反馈台账.rejected_decisions()
        check("T37d 跟进/采纳不进拒绝表不降队",
              ev_fol["event_id"] not in rej_map3 and ev_ado["event_id"] not in rej_map3,
              f"fol={ev_fol['event_id'] in rej_map3} ado={ev_ado['event_id'] in rej_map3}")
        ev_flip = 事件归并.merge_events([mkrow(
            "flip1", "Cemu 发布 支持开源掌机移植",
            "https://github.com/x/cemu/releases/tag/v1", "gh_x", "github_atom",
            focus="开源掌机与固件")])[0]
        反馈台账.mark("flip_card", "拒绝", event_id=ev_flip["event_id"], reason="先拒")
        rej_mid = 反馈台账.rejected_decisions()
        反馈台账.mark("flip_card", "跟进", event_id=ev_flip["event_id"], reason="后跟进")
        rej_after = 反馈台账.rejected_decisions()
        c_flip = 关注分层.score_event(ev_flip, prof, {"status": "off"}, TODAY, rejected=rej_after)
        check("T37e 最新wins:先拒绝后跟进→翻案出拒绝表不降队",
              ev_flip["event_id"] in rej_mid and ev_flip["event_id"] not in rej_after
              and c_flip["queue"] == "今日优先",
              f"mid={ev_flip['event_id'] in rej_mid} after={ev_flip['event_id'] in rej_after} queue={c_flip['queue']}")

        def _rel_ev(key, repo, tag, title):
            return 事件归并.merge_events([mkrow(
                key, title, f"https://github.com/foo/{repo}/releases/tag/{tag}",
                "gh_foo", "github_atom", focus="开源掌机与固件")])[0]
        s1 = _rel_ev("s1", "bar", "v1", "Bar 发布 v1 支持开源掌机")
        s2 = _rel_ev("s2", "bar", "v2", "Bar 发布 v2 支持开源掌机")
        反馈台账.mark("s1c", "拒绝", event_id=s1["event_id"], reason="拒")
        反馈台账.mark("s2c", "拒绝", event_id=s2["event_id"], reason="拒")
        p1 = _rel_ev("p1", "baz", "v1", "Baz 发布 v1 支持开源掌机")
        p2 = _rel_ev("p2", "baz", "v2", "Baz 发布 v2 支持开源掌机")
        反馈台账.mark("p1c", "拒绝", event_id=p1["event_id"], reason="拒一个")
        rej_s = 反馈台账.rejected_decisions()
        cs37 = [关注分层.score_event(e, prof, {"status": "off"}, TODAY, rejected=rej_s)
                for e in (s1, s2, p1, p2)]
        folded37, _ = 系列归并.fold(cs37)
        ser_bar = next(c for c in folded37 if c.get("series_key") == "gh:bar")
        ser_baz = next(c for c in folded37 if c.get("series_key") == "gh:baz")
        check("T37f 系列全成员拒→降低优先归档;部分拒→系列跟踪+series_rejected_count",
              ser_bar["queue"] == "低优先归档" and ser_bar.get("editorial_rejected") is True
              and ser_baz["queue"] == "系列跟踪" and ser_baz.get("series_rejected_count") == 1,
              f"bar={ser_bar['queue']} baz={ser_baz['queue']}/{ser_baz.get('series_rejected_count')}")
        check("T37g 系列best优先未被拒成员代表(部分拒系列标题取未拒p2)",
              ser_baz["titles"][0] == p2["titles"][0],
              f"ser={ser_baz['titles'][0]} p2={p2['titles'][0]}")
        rej_cards37 = [c for c in folded37 if c.get("editorial_rejected")]
        rej_full37 = [c for c in rej_cards37 if str(c.get("event_id", "")).startswith("series:")]
        rej_direct37 = [c for c in rej_cards37 if not str(c.get("event_id", "")).startswith("series:")]
        rej_partial37 = [c for c in folded37 if c.get("series_rejected_count")]
        check("T37h 拒绝计数从产物现查守恒(direct+full==demoted,设计full1/partial1/direct0)+tempdb隔离",
              len(rej_cards37) == len(rej_direct37) + len(rej_full37)
              and len(rej_full37) == 1 and len(rej_partial37) == 1 and len(rej_direct37) == 0
              and 反馈台账.DB_PATH != real_db,
              f"demoted={len(rej_cards37)} full={len(rej_full37)} partial={len(rej_partial37)} direct={len(rej_direct37)}")

        # T38 自动跨域（§11.13）：识别到几个域就查几个；多域不合并成 pass，查询留痕且探针隔离。
        ev_multi = 事件归并.merge_events([mkrow(
            "km2", "LOL 与 DOTA2 联动角色是谁", "https://k/m2", "s")])[0]
        calls38 = []

        def _fake_domain(q, **kw):
            calls38.append(kw.get("domain"))
            if kw.get("domain") == "esports_lol":
                return {**fake_pass_sel, "q": q, "domain": "esports_lol"}
            return {"q": q, "domain": kw.get("domain"), "status": "miss", "refusal": "out_of_scope",
                    "reason": "fixture empty", "hits": [], "selected_evidence": []}

        with patch.object(kbmod, "query", side_effect=_fake_domain):
            km38, ki38 = 知识对照.crosscheck([ev_multi], mode="bm25", index_path=mock_idx)
        rm38 = km38[ev_multi["event_id"]]
        check("T38a 生产入口自动扇出LOL+DOTA2并逐域调用(调用方未传domain)",
              calls38 == ["esports_lol", "esports_dota"]
              and rm38["auto_routing"]["mode"] == "multi"
              and [d["domain"] for d in rm38["domain_results"]] == ["esports_lol", "esports_dota"]
              and ki38["multi_domain_queries"] == 1,
              f"calls={calls38} info={ki38}")
        check("T38b ★反证:一域pass多域仍inconclusive；总selected_evidence空,逐域证据不丢",
              rm38["status"] == "inconclusive" and rm38.get("refusal") == "multi_domain_needs_split"
              and rm38.get("selected_evidence") == []
              and len(rm38["domain_results"][0]["selected_evidence"]) == 1
              and rm38["domain_results"][1]["status"] == "miss",
              f"status={rm38['status']} refusal={rm38.get('refusal')}")
        check("T38c 反证格:ASCII子串不误路由(Fantasy/checkeck/Lolita→unrouted)",
              [d["domain"] for d in kbmod.route_many("Final Fantasy checkeck Lolita")] == ["unrouted"]
              and [d["domain"] for d in kbmod.route_many("LOL 赛程")] == ["esports_lol"],
              str([d["domain"] for d in kbmod.route_many("Final Fantasy checkeck Lolita")]))
        with patch.object(kbmod, "query", return_value={"status": "miss", "hits": []}) as qm38:
            rexplicit = kbmod.query_auto("LOL 与 DOTA2 联动角色是谁", game="manual-game",
                                         topk=1, index_path=mock_idx)
        check("T38d 显式game/revision/platform仍是权威覆盖:绕开自动路由只查指定身份",
              qm38.call_count == 1 and "domain" not in qm38.call_args.kwargs
              and qm38.call_args.kwargs.get("game") == "manual-game"
              and "auto_routing" not in rexplicit,
              f"calls={qm38.call_count} kwargs={qm38.call_args.kwargs}")
        qlog = Path(知识对照.QUERY_LOG)
        log_before38 = len(qlog.read_text(encoding="utf-8").splitlines()) if qlog.exists() else 0
        ev_alias = {**ev_rt, "event_id": "alias-of-ev-rt"}
        with patch.object(kbmod, "query", return_value=fake_pass_sel):
            kmlog, kilog = 知识对照.crosscheck([ev_rt, ev_alias], mode="bm25", index_path=mock_idx)
        rows38 = [json.loads(x) for x in qlog.read_text(encoding="utf-8").splitlines()]
        row38 = rows38[-1]
        check("T38e 查询日志按题去重并绑定全部event_id+出证定位;不落全文",
              len(rows38) == log_before38 + 1
              and row38["event_ids"] == [ev_rt["event_id"], ev_alias["event_id"]]
              and row38["auto_domains"] == ["retro_soccer"]
              and len(row38["selected_evidence"]) == 1 and "text" not in row38
              and row38["index_sha256"] == hashlib.sha256(Path(mock_idx).read_bytes()).hexdigest()
              and kilog["logged_queries"] == 1,
              f"rows={len(rows38)} before={log_before38} events={row38['event_ids']}")
        check("T38f 多域运行记录点名路由/日志路径/计数,下游卡保留逐域结果",
              ki38["routing"] == "auto_multi" and ki38["logged_queries"] == 1
              and ki38["query_log"] == str(知识对照.QUERY_LOG)
              and all(d["domain"] for d in rm38["domain_results"]),
              str(ki38))
        real_title38 = "SCS 2026年度总决赛落幕，选手MadkoF、XiaoHai分获《拳皇15》《饿狼传说：群狼之城》冠军"
        check("T38g 真实标题反证:拳皇15+冠军不误路由到KOF98/LOL(泛词不能证明版本)",
              [d["domain"] for d in kbmod.route_many(real_title38)] == ["unrouted"],
              str([d["domain"] for d in kbmod.route_many(real_title38)]))
        ev38h = {"event_id": "ev38h", "titles": [real_title38]}
        with patch.object(kbmod, "query", return_value=fake_pass_sel):
            km38h, _ = 知识对照.crosscheck([ev38h], mode="bm25", index_path=mock_idx)
        row38h = json.loads(qlog.read_text(encoding="utf-8").splitlines()[-1])
        check("T38h 域外降级清空原pass证据且生产日志记最终裁决(不留假pass)",
              km38h["ev38h"]["status"] == "inconclusive"
              and km38h["ev38h"]["refusal"] == "unanchored"
              and km38h["ev38h"]["selected_evidence"] == []
              and row38h["status"] == "inconclusive"
              and row38h["refusal"] == "unanchored"
              and row38h["selected_evidence"] == []
              and row38h["q"] == real_title38,
              f"result={km38h['ev38h']['status']}/{km38h['ev38h']['refusal']} "
              f"log={row38h['status']}/{row38h['refusal']} q={row38h['q']!r}")

    # T15 探针隔离：真实状态未被试跑污染
    db_after = (real_db.exists(), real_db.stat().st_mtime if real_db.exists() else None)
    out_after = (real_out.exists(),
                 sorted(str(p) for p in real_out.rglob("*")) if real_out.exists() else [])
    check("T15a 真实反馈.db未被试跑写", db_before == db_after, f"{db_before} -> {db_after}")
    check("T15b 真实产出目录未被试跑写", out_before == out_after)
    snap_after = (real_snap.exists(), real_snap.stat().st_mtime if real_snap.exists() else None)
    cache_after = (real_cache.exists(),
                   sorted(str(p) for p in real_cache.rglob("*")) if real_cache.exists() else [])
    check("T15c 真实热度快照.db未被试跑写", snap_before == snap_after, f"{snap_before} -> {snap_after}")
    check("T15d 真实正文缓存未被试跑写", cache_before == cache_after)
    bili_out_after = (real_bili_out.exists(),
                      sorted(str(p) for p in real_bili_out.rglob("*")) if real_bili_out.exists() else [])
    bili_cache_after = (real_bili_cache.exists(),
                        sorted(str(p) for p in real_bili_cache.rglob("*")) if real_bili_cache.exists() else [])
    check("T15e 真实B站热度实验产出未被试跑写", bili_out_before == bili_out_after)
    check("T15f 真实B站缓存未被试跑写", bili_cache_before == bili_cache_after)
    probe_after = (real_bili_probe.exists(),
                   real_bili_probe.stat().st_mtime if real_bili_probe.exists() else None,
                   real_bili_probe.read_bytes() if real_bili_probe.exists() else None)
    check("T15g 真实探针结果.json未被回流试跑写(只读)", probe_before == probe_after)
    query_log_after = (real_query_log.exists(),
                       real_query_log.stat().st_mtime if real_query_log.exists() else None,
                       real_query_log.read_bytes() if real_query_log.exists() else None)
    check("T15h 真实KB查询日志未被试跑写(动态QUERY_LOG已隔离)", query_log_before == query_log_after,
          f"{query_log_before[:2]} -> {query_log_after[:2]}")

    total = len(RESULTS)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n自检合计 {total} 格：PASS {total - len(failed)} / FAIL {len(failed)}")
    if failed:
        print("失败格: " + ", ".join(failed))
        sys.exit(1)
    print("全绿")


if __name__ == "__main__":
    main()