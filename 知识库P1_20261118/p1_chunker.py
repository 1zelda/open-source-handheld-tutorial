# -*- coding: utf-8 -*-
"""P1 切块 v3：语言同质小段。

治的病：pilot Q06-08——日文说明书 700-970 字大块里混着中文标题词，
跨语重排器偏好中文长块，日文金标进池也被压（Q07 稠密第1仍失败）。
规则： kana 占比 > 0.30 的文件判为日文主导，按 `* * *` 章节边界切，
章节内按空行段落贪心打包 ≤300 字（超长段落按。句切，再超硬切）；
每个小段前置章节标题行提供上下文。中文文件块原样保留 v2。
只读引用 pilot 冻结语料；重切文件先过 sha256 漂移闸门。
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PILOT = ROOT / "知识库小样_20261118"
KANA = re.compile(r"[\u3040-\u30ff]")
CJK = re.compile(r"[\u4e00-\u9fff]")
SEP = re.compile(r"^\* \* \*\s*$")
BODY_MAX = 300

MARKERS = {
    "Q01": "23 种必杀射门", "Q02": "つばめがえし", "Q03": "A×3 B×1",
    "Q04": "やさしい", "Q05": "中场队长", "Q06": "６人制", "Q07": "３６試合",
    "Q08": "ＧＫ・キャラ", "Q10": "3v3 队战是 ROM 侧限制", "Q18": "ひっさつOK",
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def kana_ratio(text):
    k, c = len(KANA.findall(text)), len(CJK.findall(text))
    return k / (k + c) if k + c else 0.0


def split_sections(lines):
    """按 * * * 切章，返回 (start_1based, end_1based, [lines])。"""
    bounds = [i for i, l in enumerate(lines) if SEP.match(l)]
    edges = [-1] + bounds + [len(lines)]
    out = []
    for a, b in zip(edges, edges[1:]):
        seg = lines[a + 1:b]
        if any(l.strip() for l in seg):
            out.append((a + 2, b, seg))
    return out


def pack_paragraphs(seg_lines, base_line):
    """段落贪心打包 ≤BODY_MAX；返回 (line_start, line_end, body_text)。"""
    paras, cur, cur_start = [], [], None
    for off, l in enumerate(seg_lines):
        if l.strip():
            if cur_start is None:
                cur_start = base_line + off
            cur.append(l)
        elif cur:
            paras.append((cur_start, base_line + off - 1, cur))
            cur, cur_start = [], None
    if cur:
        paras.append((cur_start, base_line + len(seg_lines) - 1, cur))

    pieces = []
    for s, e, pl in paras:
        text = "\n".join(pl)
        if len(text) <= BODY_MAX:
            pieces.append((s, e, text))
            continue
        # 超长按句切
        sents = re.split(r"(?<=。)", text)
        buf, buf_s = "", s
        pos = s
        for sent in sents:
            if not sent:
                continue
            if buf and len(buf) + len(sent) > BODY_MAX:
                pieces.append((buf_s, pos - 1, buf))
                buf, buf_s = "", pos
            if len(sent) > BODY_MAX:
                for i in range(0, len(sent), BODY_MAX):
                    frag = sent[i:i + BODY_MAX]
                    pieces.append((pos, pos, frag))
                pos += 0
            else:
                buf += sent
            # 行号按句内换行近似推进（金标重锚靠事实文本，不靠行号）
            pos += sent.count("\n")
        if buf:
            pieces.append((buf_s, max(buf_s, pos - 1), buf))
    return pieces


def rechunk_ja(path, raw_bytes, meta):
    lines = raw_bytes.decode("utf-8").splitlines()
    chunks = []
    for s, e, seg in split_sections(lines):
        heading = next((l.strip() for l in seg if "＜" in l and "＞" in l), "")
        heading = heading.strip("* ").strip()
        for ps, pe, body in pack_paragraphs(seg, s):
            text = (heading + "\n" + body) if heading else body
            cid = sha(f"{path}|{ps}|{pe}|{text}".encode("utf-8"))[:12]
            chunks.append({
                "chunk_id": cid, "path": path,
                "source_id": meta["source_id"], "revision": meta["revision"],
                "game_id": meta["game_id"], "platform": meta["platform"],
                "authority": meta["authority"], "status": meta["status"],
                "last_verified": meta["last_verified"],
                "element_types": meta["element_types"], "kind": meta["kind"],
                "heading": heading, "line_start": ps, "line_end": pe,
                "text": text, "text_sha": sha(text.encode("utf-8")),
                "dl": meta["dl"], "lang": "ja",
            })
    return chunks


def main():
    idx = json.loads((PILOT / "frozen_corpus" / "index.json").read_text(encoding="utf-8"))
    spec = json.loads((PILOT / "pilot_questions.json").read_text(encoding="utf-8"))
    byfile = {}
    for c in idx["chunks"]:
        byfile.setdefault(c["path"], []).append(c)

    v3, rechunked, log = [], [], []
    for path, chunks in sorted(byfile.items()):
        ratio = kana_ratio("".join(c["text"] for c in chunks))
        if ratio <= 0.30:
            for c in chunks:
                c2 = dict(c)
                c2["lang"] = "zh"
                v3.append(c2)
            continue
        raw_path = ROOT / path
        raw = raw_path.read_bytes()
        want = idx["files"][path]["sha256"]
        if sha(raw) != want:
            raise SystemExit(f"漂移闸门：{path} 现值 sha={sha(raw)[:12]} ≠ 冻结 {want[:12]}，"
                             "须重冻结语料再切块")
        meta = chunks[0]
        new = rechunk_ja(path, raw, meta)
        v3.extend(new)
        rechunked.append(path)
        log.append(f"{path.split('/')[-1]}: kana={ratio:.2f} {len(chunks)}块 -> {len(new)}块 "
                   f"(body≤{BODY_MAX}字)")

    # 金标重锚：事实标记必须在 v3 里找到唯一落点
    gold_out, fails = [], []
    for q in spec["questions"]:
        g = dict(q)
        gold = q.get("gold")
        if not gold:
            gold_out.append(g)
            continue
        marker = MARKERS.get(q["id"])
        ng = dict(gold)
        if marker:
            hit = [c for c in v3 if gold["path_contains"] in c["path"] and marker in c["text"]]
            if not hit:
                fails.append(f"{q['id']} 标记 {marker!r} 在 v3 找不到")
            else:
                c = hit[0]
                ng.update(line_start=c["line_start"], line_end=c["line_end"],
                          anchor_chunk=c["chunk_id"])
                log.append(f"{q['id']} 金标 -> {c['chunk_id']} L{c['line_start']}-{c['line_end']}")
        g["gold"] = ng
        gold_out.append(g)
    if fails:
        raise SystemExit("金标重锚失败：" + "；".join(fails))

    out = {
        "schema_version": "p1-v3", "built_at": datetime.now(timezone.utc).isoformat(),
        "base_fingerprint": spec["corpus_fingerprint"],
        "rechunked": rechunked,
        "stats": {"chunks": len(v3),
                  "ja": sum(1 for c in v3 if c["lang"] == "ja"),
                  "zh": sum(1 for c in v3 if c["lang"] == "zh")},
        "files": idx["files"], "chunks": v3,
    }
    (HERE / "v3_index.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    gold_spec = dict(spec)
    gold_spec["questions"] = gold_out
    gold_spec["v3_reanchor_log"] = log
    (HERE / "p1_questions.json").write_text(json.dumps(gold_spec, ensure_ascii=False, indent=1),
                                            encoding="utf-8")
    for l in log:
        print(l)
    print(f"v3 总块数 {len(v3)} (ja={out['stats']['ja']} zh={out['stats']['zh']})，"
          f"金标 {len(MARKERS)}/{len(MARKERS)} 重锚成功")


if __name__ == "__main__":
    main()