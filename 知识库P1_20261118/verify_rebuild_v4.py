# -*- coding: utf-8 -*-
"""P2 重建验证（v4）：zh 块逐块同 v2 备份 sha；ja 块不再要求复现 v3（贪心打包是真改动），
改验形态+行覆盖+正文溯源；26 题金标行号范围必须被新块覆盖（检索评测的前置条件）。

只读核对，不写任何生产文件。用法：py -3 -u verify_rebuild_v4.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "_工具脚本"))
from taspipe import kb  # noqa: E402

NEW = ROOT / "_工具脚本" / "taspipe" / "游戏包" / "知识库" / "index.json"
OLD = HERE / "index_backup_v2_20261119.json"
V3 = HERE / "v3_index.json"
SPEC = HERE / "p1_questions_ext.json"


def main():
    new = json.loads(NEW.read_text(encoding="utf-8"))
    old = json.loads(OLD.read_text(encoding="utf-8"))
    v3 = json.loads(V3.read_text(encoding="utf-8"))
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    fails = []
    if new.get("pipeline") != kb.PIPELINE:
        fails.append(f"索引流水线 {new.get('pipeline')!r} ≠ 当前 {kb.PIPELINE!r}")

    def byfile(idx):
        d = {}
        for c in idx["chunks"]:
            d.setdefault(c["path"], []).append(c)
        return d

    nb, ob = byfile(new), byfile(old)
    if set(nb) != set(ob):
        fails.append(f"文件集不一致：新{len(nb)} 旧{len(ob)}")

    zh_same = zh_diff = zh_edited = 0
    for path, ochunks in ob.items():
        if path in v3["rechunked"]:
            continue
        # 源文件本身被合法编辑过（如说明书追加章节）=> 不参与零漂移对照
        cur_sha = __import__("hashlib").sha256(
            (ROOT / path).read_bytes()).hexdigest()
        if old["files"].get(path, {}).get("sha256") != cur_sha:
            zh_edited += 1
            continue
        nchunks = nb.get(path, [])
        okeys = sorted((c["line_start"], c["line_end"], c["text_sha"]) for c in ochunks)
        nkeys = sorted((c["line_start"], c["line_end"], c["text_sha"]) for c in nchunks)
        zh_same += len(ochunks)
        if okeys != nkeys:
            zh_diff += 1
            fails.append(f"zh 块漂移：{path}（旧{len(ochunks)}块 新{len(nchunks)}块）")

    ja_chunks = ja_files = 0
    for path in v3["rechunked"]:
        nchunks = sorted(nb.get(path, []), key=lambda c: (c["line_start"], c["line_end"]))
        ja_files += 1
        ja_chunks += len(nchunks)
        if not nchunks:
            fails.append(f"ja 文件零块：{path}")
            continue
        if not all(c.get("lang") == "ja" for c in nchunks):
            fails.append(f"ja 文件有块未标 lang=ja：{path}")
        prev_start = 0
        for c in nchunks:
            if c["text_sha"] != kb._sha1(c["text"]):
                fails.append(f"ja 块 text_sha 不符：{path} L{c['line_start']}")
            if c["heading"] and not c["text"].startswith(c["heading"]):
                fails.append(f"ja 块标题未前置：{path} L{c['line_start']}")
            body = c["text"][len(c["heading"]) + 1:] if c["heading"] else c["text"]
            if len(body) > kb.JA_BODY_MAX:
                fails.append(f"ja 块正文超 {kb.JA_BODY_MAX}：{path} L{c['line_start']} ({len(body)}字)")
            if c["line_start"] < prev_start:
                fails.append(f"ja 块行范围倒序：{path} L{c['line_start']}")
            prev_start = c["line_start"]
        # chunk_ja 走原文行号（不经网页清洗）；* * * 是章节边界不是内容。
        # 句切路径行号是近似值（v3 起如此，金标锚靠事实文本）⇒ 覆盖/溯源按内容判，不按行号
        src_lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
        kept_lines = {i + 1: t for i, t in enumerate(src_lines)
                      if t.strip() and not kb.JA_SEP_RE.match(t)}
        # 句切块各自前置标题，拼接查内容须去标题、按索引原序（打包顺序）
        all_text = "".join(
            (c["text"][len(c["heading"]) + 1:] if c["heading"] else c["text"])
            for c in nb.get(path, [])).replace("\n", "")
        uncovered = [ln for ln, t in kept_lines.items() if t.strip() not in all_text]
        if uncovered:
            fails.append(f"ja 源行内容未入块：{path} 行 {uncovered[:8]}")
        src_all = "\n".join(src_lines)
        for c in nchunks:
            body_lines = [t for t in c["text"].splitlines()
                          if t.strip() and t != c["heading"]]
            for t in body_lines:
                if t.strip() not in src_all:
                    fails.append(f"ja 块正文行不在源文件内：{path} L{c['line_start']} {t[:24]!r}")
                    break

    gold_ok = gold_bad = 0
    for q in spec["questions"]:
        gold = q.get("gold")
        if not gold:
            continue
        hit = any(gold["path_contains"] in c["path"]
                  and c["line_start"] <= gold["line_end"]
                  and c["line_end"] >= gold["line_start"]
                  for c in new["chunks"])
        if hit:
            gold_ok += 1
        else:
            gold_bad += 1
            fails.append(f"金标行无块覆盖：{q['id']} {gold['path_contains']} "
                         f"L{gold['line_start']}-{gold['line_end']}")

    langs = {"ja": 0, "zh": 0}
    for c in new["chunks"]:
        langs[c.get("lang", "zh")] += 1
    print(f"新索引总块数 {len(new['chunks'])}（ja={langs['ja']} zh={langs['zh']}）")
    print(f"zh 逐块同 v2 sha：{zh_same} 块，漂移文件 {zh_diff}，源已编辑跳过 {zh_edited}")
    print(f"ja 形态+行覆盖+正文溯源：{ja_files} 文件 {ja_chunks} 块")
    print(f"金标行覆盖：{gold_ok} 题有块覆盖，{gold_bad} 题落空")
    if fails:
        print("FAIL：")
        for f in fails:
            print("  " + f)
        sys.exit(1)
    print("VERIFY OK：zh 零漂移；ja 块形态/覆盖/溯源全过；全部金标行有新块覆盖")


if __name__ == "__main__":
    main()