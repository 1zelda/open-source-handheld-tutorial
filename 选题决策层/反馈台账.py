# -*- coding: utf-8 -*-
"""编辑反馈台账（SQLite）。编辑决策与观众效果分表；「没时间」scope=editor_capacity，
永不学成「观众不喜欢」。探针/试跑必须显式传 path，不得写真实状态。"""
import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MODDIR = Path(__file__).resolve().parent
DB_PATH = MODDIR / "反馈.db"
ACTIONS = {"采纳": "editorial_judgment", "改角度": "editorial_judgment",
           "拒绝": "editorial_judgment", "跟进": "editorial_judgment",
           "没时间": "editor_capacity"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions(
  id INTEGER PRIMARY KEY, card_id TEXT, event_id TEXT, profile_id TEXT,
  title TEXT, action TEXT, scope TEXT, reason TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS seen(card_id TEXT PRIMARY KEY, ts TEXT);
CREATE TABLE IF NOT EXISTS performances(
  id INTEGER PRIMARY KEY, event_id TEXT, work_id TEXT, platform TEXT,
  published_at TEXT, window_days INTEGER, impressions INTEGER, clicks INTEGER,
  avg_view_seconds REAL, completion_rate REAL, favorites INTEGER, shares INTEGER,
  follows INTEGER, boosted INTEGER, production_hours REAL, notes TEXT);
"""


def connect(path=None):
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.executescript(SCHEMA)
    return con


def mark_seen(card_id, path=None):
    con = connect(path)
    con.execute("INSERT OR REPLACE INTO seen VALUES(?,?)",
                (card_id, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    con.commit()
    con.close()


def mark(card_id, action, reason="", event_id="", profile_id="", title="", path=None):
    if action not in ACTIONS:
        raise SystemExit(f"未知动作 {action!r}，允许 {sorted(ACTIONS)}")
    con = connect(path)
    con.execute("INSERT INTO decisions(card_id,event_id,profile_id,title,action,scope,reason,ts) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (card_id, event_id, profile_id, title, action, ACTIONS[action], reason,
                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    con.execute("INSERT OR REPLACE INTO seen VALUES(?,?)",
                (card_id, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    con.commit()
    con.close()


def adopted_titles(path=None):
    """已采纳讲过的标题集合（供信息增量维度现查，不写死名单）。"""
    p = Path(path or DB_PATH)
    if not p.is_file():
        return frozenset()
    con = connect(p)
    rows = con.execute("SELECT title FROM decisions WHERE action='采纳' AND scope='editorial_judgment'").fetchall()
    con.close()
    from 事件归并 import norm_title
    return frozenset(norm_title(t) for (t,) in rows if t)


def rejected_decisions(path=None):
    """编辑已拒绝 event_id→reason（供制作动作轴降队，§3.1）。每 event_id 取**最新**决策
    (by id)，仅 action=拒绝 且 scope=editorial_judgment；「没时间」(editor_capacity) 永不纳入
    （永不学成观众不喜欢）；跟进/采纳/改角度不降。最新 wins（后来采纳/跟进可翻案）。只读。"""
    p = Path(path or DB_PATH)
    if not p.is_file():
        return {}
    con = connect(p)
    rows = con.execute("SELECT event_id, action, scope, reason FROM decisions ORDER BY id").fetchall()
    con.close()
    latest = {}
    for eid, action, scope, reason in rows:
        if eid:
            latest[eid] = (action, scope, reason)
    return {eid: reason for eid, (action, scope, reason) in latest.items()
            if action == "拒绝" and scope == "editorial_judgment"}


def main():
    ap = argparse.ArgumentParser(description="编辑反馈台账")
    ap.add_argument("cmd", choices=["mark", "list"])
    ap.add_argument("--card-id", default="")
    ap.add_argument("--action", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--event-id", default="")
    ap.add_argument("--profile-id", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--db", default=None, help="显式指定库路径（试跑必须给）")
    a = ap.parse_args()
    if a.cmd == "mark":
        mark(a.card_id, a.action, a.reason, a.event_id, a.profile_id, a.title, path=a.db)
        print(f"已记录 {a.card_id} {a.action}（scope={ACTIONS[a.action]}）")
    else:
        con = connect(a.db)
        for r in con.execute("SELECT ts,card_id,action,scope,reason,title FROM decisions ORDER BY id DESC LIMIT 50"):
            print("\t".join(str(x) for x in r))
        con.close()


if __name__ == "__main__":
    main()