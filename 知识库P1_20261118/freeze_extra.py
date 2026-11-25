# -*- coding: utf-8 -*-
"""P1 扩域题冻结：原18题 + 8新题（路由反证/可答性反证/跨语转正）。

冻结期断言（恒量反证格）：
  * refuse 新题必须在 v3 语料上结构性不可答（可答性全否 或 域外零语料），
    否则该题不配当反证格，拒绝冻结。
  * gold 新题的事实标记必须在 v3 找到落点。
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb  # noqa: E402
from p1_router import route  # noqa: E402
from p1_answerability import annotate  # noqa: E402

v3 = json.loads((HERE / "v3_index.json").read_text(encoding="utf-8"))
base = json.loads((HERE / "p1_questions.json").read_text(encoding="utf-8"))
chunks = v3["chunks"]

NEW = [
    {"id": "P19", "q": "热血足球的世界杯模式怎么触发？",
     "filters": {"game": "nekketsu_soccer2"}, "expect": "gold_in_topk",
     "gold_marker": ("sohu_一直输球", "16场内总积分达到70分"),
     "fact": "FC版世界杯触发条件在sohu结局文；9game那份是手游标签不可当FC金标"},
    {"id": "P20", "q": "2025年MSI季中冠军赛冠军是哪支战队？",
     "filters": {}, "expect": "refuse", "route_expect": "esports_lol"},
    {"id": "P21", "q": "热血足球联盟卡带 ROM 的 SHA1 校验和是多少？",
     "filters": {"game": "nekketsu_soccer2"}, "expect": "refuse",
     "fact": "全库无40位hex，可答性必须全否"},
    {"id": "P22", "q": "说明书里的 PK 战模式怎么玩？",
     "filters": {"revision": "nekketsu_soccer2_fc_jp"}, "expect": "gold_in_topk",
     "gold_marker": ("setsumei", "ＰＫ戦プレイ出場", "ＰＫ戦プレイ"), "fact": "日文PK战章节小段"},
    {"id": "P23", "q": "说明书里状态（ステータス）一节讲了哪些参数？",
     "filters": {"revision": "nekketsu_soccer2_fc_jp"}, "expect": "gold_in_topk",
     "gold_marker": ("setsumei", "たいりょく", "ステータスについて"), "fact": "日文状态章节小段"},
    {"id": "P24", "q": "测试问题与闸门说明书里，ROM 修订版对不上该怎么办？",
     "filters": {}, "expect": "gold_in_topk",
     "gold_marker": ("测试问题", "回放无法对齐"), "fact": "项目文档域路由"},
    {"id": "P25", "q": "热血足球联盟的转会窗口期是多久？",
     "filters": {"game": "nekketsu_soccer2"}, "expect": "refuse",
     "fact": "库内无转会事实，聚焦形态必须全否"},
    {"id": "P26", "q": "DOTA2 TI14 预选赛赛程安排",
     "filters": {}, "expect": "refuse", "route_expect": "esports_dota"},
]

log = []
for q in NEW:
    r = route(q["q"])
    if "route_expect" in q:
        assert r["domain"] == q["route_expect"] and not r["corpus_available"], \
            f"{q['id']} 路由反证失败: {r}"
        log.append(f"{q['id']} 域外零语料 route={r['domain']}")
        q["gold"] = None
        continue
    if q.get("gold_marker"):
        path_kw, marker, *rest = q["gold_marker"]
        head_kw = rest[0] if rest else None
        hit = [c for c in chunks if path_kw in c["path"] and marker in c["text"]
               and (head_kw is None or head_kw in c.get("heading", ""))]
        assert hit, f"{q['id']} 标记 {marker!r} 在 v3 找不到"
        c = hit[0]
        q["gold"] = {"path_contains": path_kw, "line_start": c["line_start"],
                     "line_end": c["line_end"], "anchor_chunk": c["chunk_id"]}
        log.append(f"{q['id']} gold -> {c['chunk_id']} L{c['line_start']}-{c['line_end']}")
    if q["expect"] == "refuse":
        # 结构性反证：域内全部块可答性必须全否
        scope = [c for c in chunks
                 if (r["game_ids"] is None or not r["game_ids"]
                     or c["game_id"] in r["game_ids"])
                 and (not r["revisions"] or c["revision"] in r["revisions"])]
        bad = [c for c in scope if annotate(q["q"], c["text"], kb.tokens)["answerable"]]
        assert not bad, f"{q['id']} 反证格不成立：{len(bad)} 块可答，如 {bad[0]['path']}"
        log.append(f"{q['id']} 可答性全否断言过（域内 {len(scope)} 块）")

ext = dict(base)
ext["questions"] = base["questions"] + NEW
ext["p1_extra_freeze_log"] = log
(HERE / "p1_questions_ext.json").write_text(
    json.dumps(ext, ensure_ascii=False, indent=1), encoding="utf-8")
for l in log:
    print(l)
print(f"冻结 {len(ext['questions'])} 题（原18 + 新{len(NEW)}）")