# -*- coding: utf-8 -*-
"""往 06-资讯监控/源登记表.tsv 追加两条本轮确认过的源（幂等：按 id 去重）。"""
import io, os

REG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "06-资讯监控", "源登记表.tsv")

ROWS = [
    ("gh_adg_commits",
     "awesome-decomp-games 提交流（移植/反编译总索引，本看板的第 1 层）",
     "https://github.com/SubmitGame/awesome-decomp-games/commits/main.atom", "1",
     "2026-11-03 实测 http=200 解析=20 条；★2835 push 2026-11-03。它每天自动重算 data/games.json 并提交，"
     "所以**提交流=索引更新流**；releases.atom 实测 0 条（这仓库不发 release），别挂错。"),
    ("adg_games_json",
     "awesome-decomp-games 的 data/games.json（非 feed，走专用脚本）",
     "https://raw.githubusercontent.com/SubmitGame/awesome-decomp-games/main/data/games.json", "0",
     "2026-11-03 实测 http=200 size≈3.9 MB，2629 项目/2235 游戏，带 stars·release·last_commit·needs_assets。"
     "enabled=0 的原因同 ps5store_catalog：load_registry() 把非 github.com 的 url 一律当 rss 解析，"
     "JSON 会天天报失败 → 由 _工具脚本/major_ports_board.py --refresh 单独抓，喂 06-资讯监控/移植大作/ 那张看板。"),
]


def main():
    with io.open(REG, encoding="utf-8-sig") as fh:
        lines = fh.read().splitlines()
    have = {l.split("\t")[0] for l in lines[1:] if l.strip()}
    add = [r for r in ROWS if r[0] not in have]
    if not add:
        print("nothing to add, registry rows=%d" % (len(lines) - 1))
        return
    clean = ["\t".join(c.replace("\t", " ").replace('"', "'") for c in r) for r in add]
    with io.open(REG, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(clean) + "\n")
    print("added %d, registry rows now=%d" % (len(add), len(lines) - 1 + len(add)))


if __name__ == "__main__":
    main()
