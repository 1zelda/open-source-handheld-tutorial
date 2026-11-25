# -*- coding: utf-8 -*-
"""任务B 独立验收测试：stable-retro 统一只读资源发现与完整性报告。

只使用临时目录合成数据根，不碰真实克隆、不安装 stable-retro、不联网。
运行：py -3 -u -m taspipe.resource_discovery_selftest
共享挂入口：run_resource_discovery_gates(ok_fn, raises_fn)
"""
import json
import sys
import tempfile
import types
from pathlib import Path

from . import retro_cheat_runner as R

RESULTS = []
_OK_FN = None


def check(name, cond, detail=""):
    if _OK_FN is not None:
        _OK_FN(bool(cond), name if cond else f"{name} | {detail}")
        return
    RESULTS.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'} {name}" + (f" | {detail}" if detail and not cond else ""))


def mk_game(data_root, split, name, data=True, sha=True, states=("Level1",),
            scen=False, bad_data=False):
    g = data_root / split / name
    g.mkdir(parents=True)
    if data:
        (g / "data.json").write_text("{bad json" if bad_data else '{"info": {"x": 1}}',
                                     encoding="utf-8")
    if sha:
        (g / "rom.sha").write_text("abc123\n", encoding="utf-8")
    for s in states:
        (g / (s + ".state")).write_bytes(b"\x00")
    if scen:
        (g / "scenario.json").write_text("{}", encoding="utf-8")
    return g


def t_missing_root(root):
    res = R.discover_stable_retro(root=root / "nonexistent")
    check("B1 无效根结构化报错非空字典", res["status"] == "no_data_root"
          and res["roots"][0]["status"] == "error" and res["roots"][0]["reason"], str(res)[:200])
    empty = root / "empty"
    empty.mkdir()
    res2 = R.discover_stable_retro(root=empty)
    check("B2 空目录同样报缺 split", res2["status"] == "no_data_root", str(res2)[:200])


def t_bad_json(root):
    data = root / "data"
    mk_game(data, "stable", "GameA", bad_data=True)
    mk_game(data, "stable", "GameB")
    res = R.discover_stable_retro(root=data, limit=None)
    bad = res["bad_json"]
    check("B3 坏 JSON 点名路径", len(bad) == 1
          and bad[0]["path"].replace("\\", "/").endswith("GameA/data.json")
          and bad[0]["error"], str(bad))
    recs = {r["game"]: r for r in res["records"]}
    check("B4 坏 JSON 游戏不被丢弃", "GameA" in recs and recs["GameA"]["data_json"] is True
          and recs["GameA"]["data_json_valid"] is False, str(recs.get("GameA")))
    check("B5 好 JSON 反证格", recs["GameB"]["data_json_valid"] is True
          and res["counts"]["dirs_with_valid_data_json"] == 1
          and res["counts"]["dirs_with_data_json"] == 2, str(res["counts"]))


def t_duplicate_split(root):
    data = root / "data"
    mk_game(data, "stable", "DupGame")
    mk_game(data, "contrib", "DupGame")
    res = R.discover_stable_retro(root=data, limit=None)
    check("B6 重名跨 split 保留两条", res["counts"]["game_dirs_total"] == 2
          and res["counts"]["unique_game_names"] == 1, str(res["counts"]))
    dups = res["duplicates_within_root"]
    check("B7 重名点名 split", len(dups) == 1 and dups[0]["game"] == "DupGame"
          and set(dups[0]["splits"]) == {"stable", "contrib"}, str(dups))


def t_incomplete(root):
    data = root / "data"
    mk_game(data, "stable", "NoSha", sha=False)
    mk_game(data, "stable", "NoState", states=())
    mk_game(data, "stable", "NoData", data=False)
    mk_game(data, "stable", "Full")
    res = R.discover_stable_retro(root=data, limit=None)
    recs = {r["game"]: r for r in res["records"]}
    check("B8 缺 rom.sha 报缺", recs["NoSha"]["missing"] == ["rom.sha"], str(recs["NoSha"]))
    check("B9 无 state 报缺且仍列出", recs["NoState"]["missing"] == ["*.state"]
          and recs["NoState"]["state_count"] == 0, str(recs["NoState"]))
    check("B10 缺 data.json 报缺", recs["NoData"]["missing"] == ["data.json"], str(recs["NoData"]))
    check("B11 完整目录零缺项反证", recs["Full"]["missing"] == []
          and res["counts"]["incomplete_dirs"] == 3, str(res["counts"]))


def t_pagination(root):
    data = root / "data"
    for i in range(60):
        mk_game(data, "stable", f"G{i:02d}")
    res = R.discover_stable_retro(root=data)
    check("B12 默认页 50/总 60", res["returned_count"] == 50
          and res["total_records"] == 60, str((res["returned_count"], res["total_records"])))
    res2 = R.discover_stable_retro(root=data, offset=50)
    check("B13 翻页余 10", res2["returned_count"] == 10
          and res2["records"][0]["game"] == "G50", str(res2["returned_count"]))
    res3 = R.discover_stable_retro(root=data, limit=None)
    check("B14 limit=None 全量", res3["returned_count"] == 60, str(res3["returned_count"]))
    res4 = R.discover_stable_retro(root=data, offset=999)
    check("B15 越界页空但总数不变", res4["returned_count"] == 0
          and res4["total_records"] == 60, str(res4))


def t_counts(root):
    data = root / "data"
    mk_game(data, "stable", "A", states=("L1", "L2"), scen=True)
    mk_game(data, "stable", "B")
    mk_game(data, "contrib", "C", sha=False, states=())
    res = R.discover_stable_retro(root=data, limit=None)
    c = res["counts"]
    check("B16 三种计数分开且现算", c["game_dirs_total"] == 3
          and c["state_files_total"] == 3 and c["scenario_files_total"] == 1
          and c["unique_game_names"] == 3, str(c))
    key = next(iter(res["per_split"]))
    ps = res["per_split"][key]
    check("B17 逐 split 计数", ps["stable"]["game_dirs"] == 2
          and ps["stable"]["state_files"] == 3
          and ps["contrib"]["game_dirs"] == 1, str(ps))
    check("B18 缺失 split 显式 exists=False", ps["experimental"]["exists"] is False
          and ps["experimental"]["game_dirs"] == 0, str(ps["experimental"]))


def t_filter(root):
    data = root / "data"
    mk_game(data, "stable", "Alpha-Nes")
    mk_game(data, "stable", "Beta-Nes")
    mk_game(data, "stable", "alpha2-Snes")
    res = R.discover_stable_retro(root=data, filter_str="alpha", limit=None)
    check("B19 过滤大小写不敏感", res["total_records"] == 2
          and all("alpha" in r["game"].lower() for r in res["records"]), str(res["total_records"]))
    res2 = R.discover_stable_retro(root=data, filter_str="zzz", limit=None)
    check("B20 无命中 total=0 非报错", res2["status"] == "ok"
          and res2["total_records"] == 0, str(res2["status"]))


def t_repo_root_norm(root):
    repo = root / "repo"
    mk_game(repo / "stable_retro" / "data", "stable", "X")
    res = R.discover_stable_retro(root=repo, limit=None)
    check("B21 仓库根自动定位 data", res["status"] == "ok"
          and res["roots"][0]["data_root"].replace("\\", "/").endswith("stable_retro/data"),
          str(res["roots"]))


def t_unified_roots(root):
    d1 = root / "installed" / "data"
    d2 = root / "clone" / "stable_retro" / "data"
    mk_game(d1, "stable", "SharedGame")
    mk_game(d2, "contrib", "SharedGame")
    mk_game(d2, "stable", "OnlyClone")
    fake = types.ModuleType("stable_retro")
    fake.data = types.SimpleNamespace(path=lambda: str(d1), list_games=lambda: [])
    prev_mod = sys.modules.get("stable_retro")
    prev_clone = R.STABLE_RETRO_CLONE
    sys.modules["stable_retro"] = fake
    R.STABLE_RETRO_CLONE = root / "clone"
    try:
        res = R.discover_stable_retro(limit=None)
        tags = {r["tag"]: r["status"] for r in res["roots"]}
        check("B22 包位置与克隆同套盘点", tags.get("installed_package") == "ok"
              and tags.get("source_clone") == "ok", str(tags))
        check("B23 双根计数聚合", res["counts"]["game_dirs_total"] == 3
              and res["total_records"] == 3, str(res["counts"]))
        check("B24 跨根重名点名", any(d["game"] == "SharedGame"
              for d in res["duplicates_across_roots"]), str(res["duplicates_across_roots"]))
        check("B25 显式 root 时不扫默认根",
              R.discover_stable_retro(root=d1, limit=None)["total_records"] == 1, "")
        wrap = R.list_stable_retro_games(limit=None)
        check("B26 旧入口兼容别名", wrap["matched_count"] == wrap["total_records"]
              and wrap["games"] == wrap["records"], "")
    finally:
        if prev_mod is None:
            sys.modules.pop("stable_retro", None)
        else:
            sys.modules["stable_retro"] = prev_mod
        R.STABLE_RETRO_CLONE = prev_clone


_SUITE = (t_missing_root, t_bad_json, t_duplicate_split, t_incomplete,
          t_pagination, t_counts, t_filter, t_repo_root_norm, t_unified_roots)


def run_resource_discovery_gates(ok_fn, raises_fn=None):
    """共享 selftest 总入口适配：检查走共享 ok 计数，失败即 AssertionError。"""
    global _OK_FN
    prev = _OK_FN
    _OK_FN = ok_fn
    try:
        with tempfile.TemporaryDirectory(prefix="resource_discovery_") as td:
            root = Path(td)
            for fn in _SUITE:
                sub = root / fn.__name__
                sub.mkdir()
                fn(sub)
    finally:
        _OK_FN = prev


def main():
    with tempfile.TemporaryDirectory(prefix="resource_discovery_") as td:
        root = Path(td)
        for fn in _SUITE:
            sub = root / fn.__name__
            sub.mkdir()
            fn(sub)
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"\nTOTAL {len(RESULTS)} PASS {len(RESULTS) - len(failed)} FAIL {len(failed)}")
    if failed:
        print("FAILED:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())