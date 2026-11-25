# -*- coding: utf-8 -*-
"""P8 再索引可行性只读诊断 —— 跑前规则（结果出来前不得修改）：

R1 假阳性一票否决：再索引后任一 trap/探针格出现新假阳（pass 但证据错），即否决上线。
R2 回归零容忍：再索引后任一冻结集格或探针格相对生产基线变差（pass→非pass、
   或 hits 排序把金标挤出窗口），即否决上线。Q08 在基线已 FAIL，维持 FAIL 不算回归，
   但须如实标注（再索引治不动 Q08：金标锚日文原件 L47，对照答案 L7-10 不重叠）。
R3 真救回≥1 才考虑上线：W03/W09/X18 至少一条由 inconclusive 转真 pass（权威可答件进 top3）。
R4 Q04 专项：对照必杀技节同块对 Q04「容易难度对手能不能发动必杀射门」也可答（P7 已标注），
   若再索引后该块排过 Q04 正确块致 Q04 假阳/回归，按 R1/R2 否决。
R5 生产零污染：诊断只写 scratch 临时索引/临时 corpus_map/临时 npz；生产
   index.json/corpus_map.json/sources.json/检索台账.json/生产 npz 的 mtime+sha256 必须不变。
   本脚本 build 前后各反查一次。

方法：复制生产 corpus_map，仅把 setsumei/urawaza 两条中文对照 index:false→true，
build 到 scratch 临时索引（force=True 全量重切，确定性）。其余 index:false 登记不动。
评测/探针走生产 kb.query，传 index_path/map_path 指向临时件（不碰生产默认路径）。
臂由环境决定：系统 py -3 = bm25_only；venv + 临时 npz = hybrid_union12。
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"F:\开源掌机教程\_工具脚本")
from taspipe import kb as K  # noqa: E402
from taspipe import sources as S  # noqa: E402

HERE = Path(__file__).resolve().parent
SCRATCH = HERE / "p8_scratch"
SCRATCH.mkdir(exist_ok=True)
TEMP_MAP = SCRATCH / "corpus_map_reindex.json"
TEMP_INDEX = SCRATCH / "index_reindex.json"
BASELINE = SCRATCH / "prod_baseline.json"

# 只翻这两条中文对照（其余 index:false 登记保持不动）
FLIP_PATHS = {
    "_工具脚本/taspipe/游戏包/来源库/取证/setsumei_热血足球说明书_编者中文对照_20261119.md",
    "_工具脚本/taspipe/游戏包/来源库/取证/urawaza_FC热血足球_编者中文对照_20261119.md",
}


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def prod_files():
    return [K.INDEX_JSON, K.CORPUS_MAP, S.REG_JSON, S.LEDGER_JSON,
            K.INDEX_JSON.with_name("embeddings_09096a016496.npz")]


def snapshot():
    out = {}
    for p in prod_files():
        p = Path(p)
        out[str(p)] = ({"mtime_ns": p.stat().st_mtime_ns, "sha256": _sha(p),
                        "bytes": p.stat().st_size} if p.is_file() else None)
    return out


def main():
    before = snapshot()
    BASELINE.write_text(json.dumps(before, ensure_ascii=False, indent=1), encoding="utf-8")
    print("生产基线指纹已落盘:", BASELINE)
    for k, v in before.items():
        print(f"  {Path(k).name}: {v['sha256'][:12] if v else 'MISSING'} "
              f"{v['bytes'] if v else ''}B")

    # 复制生产 corpus_map，仅翻两条对照
    m = json.loads(Path(K.CORPUS_MAP).read_text(encoding="utf-8"))
    flipped = []
    for e in m["entries"]:
        if e["path"] in FLIP_PATHS:
            assert e.get("index") is False, f"预期 index:false: {e['path']}"
            e.pop("index", None)
            e.pop("reason", None)
            flipped.append(e["path"])
    assert len(flipped) == 2, f"应翻 2 条，实翻 {len(flipped)}: {flipped}"
    TEMP_MAP.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n临时 corpus_map 已建（翻 {len(flipped)} 条对照 index:true）:", TEMP_MAP)

    # build 到临时索引（force=True 全量重切；生产 index_path 不被写）
    rep = K.build(map_path=str(TEMP_MAP), index_path=str(TEMP_INDEX), force=True)
    print(f"\n临时索引 built: chunks={rep['chunks']} terms={rep['terms']} "
          f"files_indexed={rep['files_indexed']} files_excluded={rep['files_excluded']} "
          f"bytes={rep['bytes']}")
    print("  临时索引:", TEMP_INDEX)
    # 对照块数与 lang 核实
    idx = json.loads(TEMP_INDEX.read_text(encoding="utf-8"))
    dz = [c for c in idx["chunks"] if "对照" in c["path"]]
    print(f"  对照块数={len(dz)}  lang分布="
          f"{ {l: sum(1 for c in dz if c['lang'] == l) for l in set(c['lang'] for c in dz)} }")
    for c in dz:
        if "必杀" in c["text"] or "龙卷风拳" in c["text"] or "守门员专用" in c["text"]:
            print(f"    [必杀节] {c['chunk_id']} {c['path'].split('/')[-1]} "
                  f"L{c['line_start']}-{c['line_end']} lang={c['lang']} auth={c['authority']}")

    # build 后反查生产零污染
    after = snapshot()
    diff = [k for k in before if before[k] != after.get(k)]
    print(f"\n[反查 R5] build 后生产文件变动: {len(diff)} 处")
    for k in diff:
        print(f"  变动! {Path(k).name}: {before[k]} -> {after.get(k)}")
    if diff:
        print("  !!! 生产被污染，诊断中止 !!!")
        sys.exit(1)
    print("  生产 index/corpus_map/sources/台账/npz mtime+sha256 全一致 OK")


if __name__ == "__main__":
    main()