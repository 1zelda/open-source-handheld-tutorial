# -*- coding: utf-8 -*-
"""热度时序快照（说明书§10.2）：每轮对窗口候选追加一次观测；需求信号须≥2次不同ts
观测才可给值，<2次恒未知（不编造）。来源覆盖上升封顶中（媒体覆盖代理，非观众实测）。
探针/试跑必须显式传 path，不得写真实状态。"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MODDIR = Path(__file__).resolve().parent
SNAP_DB = MODDIR / "热度快照.db"
SCHEMA = """
CREATE TABLE IF NOT EXISTS observations(
  event_id TEXT, ts TEXT, source_count INTEGER, item_count INTEGER,
  flag_hot INTEGER, pub_latest TEXT, first_seen TEXT,
  PRIMARY KEY(event_id, ts));
"""


def _dim(level, reason, evidence=None):
    return {"level": level, "reason": reason, "evidence": evidence or []}


def connect(path=None):
    p = Path(path or SNAP_DB)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p))
    con.executescript(SCHEMA)
    return con


def record(events, ts=None, path=None):
    """对一批事件追加观测（同 event_id+ts 幂等）。返回 {ts, recorded}。"""
    ts = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    con = connect(path)
    for ev in events:
        con.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?,?,?)",
                    (ev["event_id"], ts, ev["source_count"], ev["item_count"],
                     1 if ev.get("flag_hot_any") else 0,
                     ev.get("pub_latest", ""), ev.get("first_seen", "")))
    con.commit()
    con.close()
    return {"ts": ts, "recorded": len(events)}


def history(event_id, path=None):
    """该事件的历史观测（按ts升序）。库不存在返回空。"""
    p = Path(path or SNAP_DB)
    if not p.is_file():
        return []
    con = connect(p)
    rows = con.execute(
        "SELECT ts,source_count,item_count,flag_hot FROM observations "
        "WHERE event_id=? ORDER BY ts", (event_id,)).fetchall()
    con.close()
    return [{"ts": r[0], "source_count": r[1], "item_count": r[2], "flag_hot": r[3]}
            for r in rows]


def demand_signal(ev, hist):
    """需求信号维。<2次不同ts恒未知；≥2次来源覆盖上升→中(封顶)，下降→低，持平→未知。
    hist 含本轮观测。来源覆盖是媒体代理，非观众实测热度。"""
    per_ts = {}
    for o in hist:
        per_ts[o["ts"]] = o
    obs = [per_ts[t] for t in sorted(per_ts)]
    hot_note = "；旧资源HOT规则命中（仅参考，非受众热度）" if ev.get("flag_hot_any") else ""
    if len(obs) < 2:
        return _dim("未知", f"时序观测{len(obs)}次(<2)，不编造需求信号" + hot_note, [])
    first, last = obs[0], obs[-1]
    span = (f"{first['ts']}→{last['ts']} 来源{first['source_count']}→{last['source_count']} "
            f"条目{first['item_count']}→{last['item_count']}")
    if last["source_count"] > first["source_count"] or last["item_count"] > first["item_count"]:
        return _dim("中", f"来源覆盖时序上升（{span}）——媒体覆盖代理，非观众实测热度，封顶中", [span])
    if last["source_count"] < first["source_count"] or last["item_count"] < first["item_count"]:
        return _dim("低", f"来源覆盖时序下降（{span}）——降温，媒体覆盖代理非观众实测", [span])
    return _dim("未知", f"时序持平（{span}），无升温证据" + hot_note, [span])