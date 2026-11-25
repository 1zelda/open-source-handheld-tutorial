# -*- coding: utf-8 -*-
"""回填洛克人1候选消费方便绪度，并生成独立交付报告。"""
import hashlib
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
EVAL = BASE / "megaman1_candidate_consumer_eval_20261125.json"
READINESS = BASE / "megaman1_candidate_consumer_readiness_20261125.json"
REPORT = ROOT / "洛克人1候选路由与问答消费方交付_2026-11-25.md"
CONSUMER = ROOT / "_工具脚本" / "taspipe" / "kb_megaman1.py"
EVAL_SCRIPT = BASE / "eval_megaman1_candidate_consumer_20261125.py"
LOG = BASE / "megaman1_candidate_20261125" / "qc" / "consumer_query_log_20261125.jsonl"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main():
    e = json.loads(EVAL.read_text(encoding="utf-8"))
    s = e["summary"]
    assert s["route_ok"] == s["route_total"] == 13
    assert s["default_ok"] == s["strict_ok"] == 12
    assert s["default_wrong"] == s["strict_wrong"] == 0
    assert e["failure_close"]["ok"] == e["failure_close"]["total"] == 4
    assert e["isolation"]["ok"] and not e["isolation"]["changed_paths"]
    assert e["query_log"]["lines"] == 24
    assert sha(LOG) == e["query_log"]["sha256"]
    assert sha(BASE / "megaman1_candidate_20261125" / "index.json") == e["candidate_index_sha256"]
    readiness = {
        "status": "isolated_candidate_consumer_ready_for_ram_tooling_only",
        "date": "2026-11-25",
        "candidate_revision": e["candidate_revision"],
        "candidate_index": "知识库P1_20261118/megaman1_candidate_20261125/index.json",
        "candidate_index_sha256": e["candidate_index_sha256"],
        "index_chunks": 9,
        "index_files": 7,
        "terms": 504,
        "candidate_route_wired": True,
        "isolated_consumer_wired": True,
        "production_route_wired": False,
        "production_consumer_wired": False,
        "production_ready": False,
        "whole_game_knowledge_base": False,
        "production_defaults_unchanged": True,
        "external_generative_model_calls": 0,
        "paid_api_calls": 0,
        "consumer": {
            "module": "_工具脚本/taspipe/kb_megaman1.py",
            "entry_point": "taspipe.kb_megaman1.ask",
            "query_backend": "taspipe.kb.query",
            "candidate_domain": "megaman1_candidate",
            "explicit_revision_context": "megaman1_nes_us",
            "index_hash_pinned": True,
            "missing_or_mismatched_index": "fail_closed_no_production_fallback",
            "route_cases": "13/13",
            "failure_close_cases": "4/4",
            "query_log": "知识库P1_20261118/megaman1_candidate_20261125/qc/consumer_query_log_20261125.jsonl",
            "query_log_lines": 24,
            "retrieval_rows": e["query_log"]["retrieval_rows"],
            "pre_retrieval_refusal_rows": e["query_log"]["blocked_rows"],
        },
        "evaluation": {
            "frozen_questions": 12,
            "strict_pass_questions": 9,
            "refuse_questions": 3,
            "default_grade_v2": "12/12",
            "strict_grade_v2": "12/12",
            "wrong_evidence_default": s["default_wrong"],
            "wrong_evidence_strict": s["strict_wrong"],
            "missed_answer_default": s["default_missed"],
            "missed_answer_strict": s["strict_missed"],
            "real_state_unchanged": e["isolation"]["ok"],
        },
        "covered": ["对象RAM表", "坐标轴与对象编号", "BizHawk内存写机制",
                    "本机武器RAM实测", "本机对象表定位实测", "segmented TAS与FM2导入通用参考",
                    "显式别名候选路由", "隔离候选问答与失败关闭"],
        "remaining_gates": ["决定是否把候选域接入生产 kb_route.DOMAINS",
                            "决定是否把生产 corpus map/index 提升为正式内容域",
                            "专用生产问答消费方尚未接入知识对照.py",
                            "官方说明书级玩法语料未建立",
                            "整款游戏知识覆盖未建立",
                            "PAL-B 与 NTSC 美版跨版等价未验证",
                            "候选 dense/hybrid 富集件未生成",
                            "真实用户查询样本未建立"],
        "observed_shared_state": e["isolation"]["real_state_before"],
        "scope_note": "本就绪度只证明隔离候选路由与问答消费方可用；不证明整款游戏知识库完成，也不代表已接生产。",
    }
    atomic(READINESS, json.dumps(readiness, ensure_ascii=False, indent=2) + "\n")
    before = e["isolation"]["real_state_before"]
    prod_index = next(v["sha256"] for k, v in before.items() if k.endswith("游戏包\\知识库\\index.json"))
    prod_map = next(v["sha256"] for k, v in before.items() if k.endswith("游戏包\\知识库\\corpus_map.json"))
    sources = next(v["sha256"] for k, v in before.items() if k.endswith("来源库\\sources.json"))
    esports = next(v["sha256"] for k, v in before.items() if k.endswith("facts_v1.db"))
    news = next(v["sha256"] for k, v in before.items() if k.endswith("kb快照\\index.json"))
    lines = [
        "# 洛克人1候选路由与问答消费方交付（2026-11-25）", "",
        "## 1. 一页结论", "",
        "- 已新增独立候选域 `megaman1_candidate` 与隔离消费方 `taspipe.kb_megaman1.ask`。",
        "- 13 个路由用例全部通过：中英文、全角、大小写、系列泛词、其他作品、PAL-B/欧版、跨游戏合并问题均按边界处理。",
        "- 冻结 12 题经新消费方：default **12/12**，strict **12/12**，错误出证 **0/0**，漏答 **0/0**。",
        "- 失败关闭 **4/4**：缺索引、哈希不符、无显式上下文、显式上下文正确放行。",
        "- 候选消费日志 **24 行**：22 行进入生产 `kb.query()`，2 行 PAL-B 在检索前拒答；未写生产查询日志。",
        "- 当前状态是“隔离候选路由与问答可用”，**不是整款游戏知识库完成，也尚未接生产路由/消费方**。", "",
        "## 2. 这次新增了什么", "",
        "### 2.1 候选域路由", "",
        "- 显式别名：`洛克人1`、`洛克人 1`、`Mega Man 1`、`Rockman 1`，支持全角数字与大小写。",
        "- 只有系列名、`洛克人X`、`洛克人2` 等不明确指代时，判为 `ambiguous_series`，不借洛克人1候选库代答。",
        "- 点名 PAL-B/欧版时判为 `version_not_collected`，不把 NTSC 美版结论跨版照搬。",
        "- 同时点名拳皇98等其他内容域时判为 `multi_domain_needs_split`，不合并成总 pass。",
        "- 没有显式洛克人1别名时默认不路由；冻结题中的 MM06/MM07/MM08 由题集显式提供 `revision=megaman1_nes_us` 上下文。", "",
        "### 2.2 隔离问答消费方", "",
        "- `ask()` 固定读取候选 `index.json/corpus_map.json/sources.json`，并调用生产 `kb.query()`。",
        "- 候选索引 SHA 冻结为 `5e126eddf0eae98e6b8a446cd54f37400b861d5e93ecf89d3004f16d3a252581`；不符即失败关闭。",
        "- 返回 `status/refusal/reason/selected_evidence/answer/route`；没有自动合成无证据答案。",
        "- 日志只写调用方指定文件；本轮全部落在候选目录。",
        "- 未改生产 `kb_route.py`、生产 corpus map、生产 index、`知识对照.py`。", "",
        "## 3. 验证结果", "",
        "| 验收项 | 结果 |", "|---|---:|",
        "| 路由正例/反例 | 13/13 |", "| 冻结题 default | 12/12 |",
        "| 冻结题 strict | 12/12 |", "| 错误出证 default/strict | 0 / 0 |",
        "| 漏答 default/strict | 0 / 0 |", "| 失败关闭 | 4/4 |",
        "| 候选日志 | 24 行 |", "| 真实共享状态前后一致 | 是 |", "",
        "### 3.1 冻结题", "", "| 题 | 档 | default | strict |", "|---|---|---|---|",
    ]
    for row in e["questions"]:
        lines.append(f"| {row['id']} | {row['expect']} | {'通过' if row['default']['ok'] else '失败'} | "
                     f"{'通过' if row['strict']['ok'] else '失败'} |")
    lines += ["", "### 3.2 本轮隔离指纹", "",
              "共享工作区有并行会话。下表是**本次消费方验收前后**实际读取到的状态，不沿用上一份交付里的旧生产哈希；本次前后完全一致。", "",
              "| 真实文件 | 本轮 SHA-256 |", "|---|---|",
              f"| 生产 `index.json` | `{prod_index}` |",
              f"| 生产 `corpus_map.json` | `{prod_map}` |",
              f"| 来源 `sources.json` | `{sources}` |",
              f"| 电竞 `facts_v1.db` | `{esports}` |",
              f"| 新闻快照 `index.json` | `{news}` |", "",
              "## 4. 怎么使用", "",
              "```bash",
              "PYTHONUTF8=1 PYTHONPATH=\"F:/开源掌机教程/_工具脚本\" python -m taspipe.kb_megaman1 \"洛克人1 的 X 坐标对象表地址范围是什么？\"",
              "```", "",
              "需要 strict 片段策略时加 `--mode strict`；需要留候选日志时加 `--log \"F:/开源掌机教程/知识库P1_20261118/megaman1_candidate_20261125/qc/manual_query.jsonl\"`。", "",
              "## 5. 就绪度与下一步", "",
              "**已就绪：**隔离候选路由、隔离问答消费方、失败关闭、冻结题验收、候选日志与回填。", "",
              "**仍未完成：**", "",
              "- 是否把候选域接入生产 `kb_route.DOMAINS`；",
              "- 是否把生产 corpus map/index 从隔离候选提升为正式内容域；",
              "- 专用消费方接入 `知识对照.py`；",
              "- 官方说明书级玩法语料与整款游戏覆盖；",
              "- PAL-B 与 NTSC 美版跨版等价验证；",
              "- dense/hybrid 富集件与真实用户查询样本。", "",
              "因此，其他窗口若称“游戏主题知识库已完成”，应核对其完成的是**某个主题子域/索引构建**，还是**生产接线＋整款覆盖**；这两层不能等同。", "",
              "## 6. 交付索引", "",
              "- [候选路由与消费方代码](_工具脚本/taspipe/kb_megaman1.py)",
              "- [消费方验收脚本](知识库P1_20261118/eval_megaman1_candidate_consumer_20261125.py)",
              "- [消费方验收 JSON](知识库P1_20261118/megaman1_candidate_consumer_eval_20261125.json)",
              "- [消费方验收 MD](知识库P1_20261118/megaman1_candidate_consumer_eval_20261125.md)",
              "- [候选消费日志](知识库P1_20261118/megaman1_candidate_20261125/qc/consumer_query_log_20261125.jsonl)",
              "- [新就绪度副本](知识库P1_20261118/megaman1_candidate_consumer_readiness_20261125.json)",
              "- [原隔离候选索引](知识库P1_20261118/megaman1_candidate_20261125/index.json)",
              "- [冻结题集](知识库P1_20261118/megaman1_questions_frozen_20261125.json)",
              "- [原候选交付](洛克人1隔离候选子域交付_2026-11-25.pdf)", ""]
    atomic(REPORT, "\n".join(lines))
    print("READINESS_OK", readiness["status"])
    print(str(READINESS))
    print(str(REPORT))


if __name__ == "__main__":
    main()
