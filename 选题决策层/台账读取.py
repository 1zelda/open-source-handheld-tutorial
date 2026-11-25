# -*- coding: utf-8 -*-
"""只读完整台账（不只读 HOT）。台账由 scene_monitor 并发追加，本层永不写它。"""
import hashlib
from pathlib import Path

MODDIR = Path(__file__).resolve().parent
ROOT = MODDIR.parent
LEDGER = ROOT / "06-资讯监控" / "台账.tsv"
COLS = ["key", "first_seen_utc", "source_id", "kind", "source", "pub",
        "title", "url", "flag_hot", "flag_note", "flag_arrival", "flag_focus"]


def read_ledger(path=None):
    p = Path(path or LEDGER)
    rows = []
    with open(p, encoding="utf-8", newline="") as fh:
        head = fh.readline().rstrip("\r\n").split("\t")
        ix = {c: i for i, c in enumerate(head)}
        for line in fh:
            parts = line.rstrip("\r\n").split("\t")
            if not parts or not parts[0].strip():
                continue
            rows.append({c: (parts[ix[c]] if c in ix and ix[c] < len(parts) else "")
                         for c in COLS})
    return rows


def ledger_sha(path=None):
    return hashlib.sha256(Path(path or LEDGER).read_bytes()).hexdigest()