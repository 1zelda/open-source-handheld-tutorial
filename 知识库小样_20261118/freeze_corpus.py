# -*- coding: utf-8 -*-
"""冻结语料副本 + 按事实文本重锚金标行段（生产索引正被并发会话重建，行号会漂）。"""
import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(r"F:\开源掌机教程\_工具脚本\taspipe\游戏包\知识库")
FROZEN = HERE / "frozen_corpus"
FROZEN.mkdir(exist_ok=True)

for name in ("index.json", "corpus_map.json"):
    dst = FROZEN / name
    if dst.exists():
        raise SystemExit(f"冻结副本已存在，不许覆盖: {dst}")
    shutil.copyfile(SRC / name, dst)

idx = json.loads((FROZEN / "index.json").read_text(encoding="utf-8"))
sha = hashlib.sha256((FROZEN / "index.json").read_bytes()).hexdigest()
spec = json.loads((HERE / "pilot_questions.json").read_text(encoding="utf-8"))

MARKERS = {
    "Q01": "23 种必杀射门", "Q02": "つばめがえし", "Q03": "A×3 B×1",
    "Q04": "やさしい", "Q05": "中场队长", "Q06": "６人制", "Q07": "３６試合",
    "Q08": "ＧＫ・キャラ", "Q10": "3v3 队战是 ROM 侧限制", "Q18": "ひっさつOK",
}

reanchor_log = []
for q in spec["questions"]:
    gold = q.get("gold")
    if not gold:
        continue
    cands = [c for c in idx["chunks"] if gold["path_contains"] in c["path"]]
    marker = MARKERS.get(q["id"])
    if marker:
        hit = [c for c in cands if marker in c["text"]]
        if not hit:
            raise SystemExit(f"{q['id']} 事实标记 {marker!r} 在冻结副本中找不到——金标失效，须人工复核")
        c = hit[0]
        old = (gold["line_start"], gold["line_end"])
        gold["line_start"], gold["line_end"] = c["line_start"], c["line_end"]
        gold["anchor_chunk"] = c["chunk_id"]
        reanchor_log.append(f"{q['id']} {old} -> ({c['line_start']},{c['line_end']}) chunk={c['chunk_id']}")
    else:
        if not cands:
            raise SystemExit(f"{q['id']} gold 路径 {gold['path_contains']!r} 无块")
        reanchor_log.append(f"{q['id']} 宽gold保持 {gold['path_contains']} ({len(cands)}块)")

spec["corpus_fingerprint"].update({
    "index_path": "知识库小样_20261118/frozen_corpus/index.json",
    "index_sha256": sha, "chunks": idx["stats"]["N"],
    "built_at": idx["built_at"], "pipeline": idx["pipeline"],
    "note": ("生产索引在 22:26→22:33 被并发会话重建两次；本副本为 22:33 版冻结件，"
             "两臂只读副本。金标行段已按事实文本重锚（见 reanchor_log）。"),
})
spec["reanchor_log"] = reanchor_log
(HERE / "pilot_questions.json").write_text(
    json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
print("frozen sha:", sha, "chunks:", idx["stats"]["N"])
print("\n".join(reanchor_log))