# -*- coding: utf-8 -*-
"""当前新闻快照生产消费冒烟；查询日志隔离，真实状态只读。"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path("F:/开源掌机教程")
OUT = ROOT / "知识库P1_20261118/kb_final_20261124"
sys.path.insert(0, str(ROOT / "选题决策层"))
sys.path.insert(0, str(ROOT / "_工具脚本"))
import 知识对照 as X
from taspipe import kb as K

JSON_PATH = OUT / "news_snapshot_crosscheck_after_citation_authority_fix_20261124.json"
QLOG = OUT / "news_snapshot_crosscheck_after_citation_authority_fix_20261124.query_log.jsonl"


def info(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "mtime_ns": path.stat().st_mtime_ns,
            "sha256": hashlib.sha256(data).hexdigest()}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    events = [
        {"event_id": "smoke-soccer-broad", "titles": ["《热血足球联盟》燕返怎么触发？"]},
        {"event_id": "smoke-soccer-role", "titles": ["热血足球联盟双人合作模式下二号玩家操作什么位置？"]},
        {"event_id": "smoke-soccer-count", "titles": ["热血足球联盟每队上场几名球员？"]},
        {"event_id": "smoke-fighting", "titles": ["《热血格斗传说》角色创建有几种能力？"]},
        {"event_id": "smoke-kof98", "titles": ["KOF98 ECK 能不能关掉队友改成 1v1？"]},
        {"event_id": "smoke-unrouted", "titles": ["这条标题没有可识别的游戏实体"]},
        {"event_id": "smoke-multi", "titles": ["LOL 与 DOTA2 的赛制有什么不同？"]},
    ]
    protected = [Path(K.INDEX_JSON), X.SNAP / "index.json", X.QUERY_LOG]
    before = {str(p): info(p) if p.is_file() else {"path": str(p), "exists": False}
              for p in protected}
    old_log = X.QUERY_LOG
    X.QUERY_LOG = QLOG
    if QLOG.exists():
        QLOG.unlink()
    try:
        snapshot, source_sha = X.make_snapshot()
        results, stats = X.crosscheck(events, mode="bm25")
    finally:
        X.QUERY_LOG = old_log
    after = {str(p): info(p) if p.is_file() else {"path": str(p), "exists": False}
             for p in protected}
    changed = [p for p in before if before[p] != after[p]]
    rows = QLOG.read_text(encoding="utf-8").splitlines() if QLOG.exists() else []
    statuses = {event_id: value.get("status") for event_id, value in results.items()}
    golden = [event_id for event_id, value in results.items()
              if value.get("status") == "pass" and value.get("selected_evidence")]
    expected_golden = {"smoke-soccer-role", "smoke-soccer-count",
                       "smoke-fighting", "smoke-kof98"}
    index = json.loads(Path(K.INDEX_JSON).read_text(encoding="utf-8"))
    snap = json.loads(snapshot.read_text(encoding="utf-8"))
    payload = {
        "schema": "news_snapshot_consumer_smoke_after_citation_authority_fix_v1",
        "taken_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "consumer": "选题决策层/知识对照.py:crosscheck -> taspipe.kb:query_auto",
        "index": {**info(K.INDEX_JSON), "chunks": len(index["chunks"])},
        "news_snapshot": {**info(snapshot), "chunks": len(snap["chunks"]),
                          "synced": hashlib.sha256(snapshot.read_bytes()).hexdigest() == source_sha},
        "smoke": {"events": events, "results": results, "stats": stats,
                  "isolated_query_log": str(QLOG), "logged_queries": len(rows),
                  "golden_path_passes": golden, "statuses": statuses},
        "real_state": {"before": before, "after": after, "changed_paths": changed,
                       "unchanged": not changed},
        "ok": (len(rows) == 7 and set(golden) == expected_golden and not changed
              and payload_synced(snapshot, source_sha)),
    }
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(JSON_PATH), "logged_queries": len(rows),
                      "golden_path_passes": golden, "statuses": statuses,
                      "snapshot_synced": payload["news_snapshot"]["synced"],
                      "real_state_unchanged": not changed, "ok": payload["ok"]},
                     ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def payload_synced(snapshot, source_sha):
    return hashlib.sha256(snapshot.read_bytes()).hexdigest() == source_sha


if __name__ == "__main__":
    raise SystemExit(main())
