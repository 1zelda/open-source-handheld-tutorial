#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""由 ports全量合法池/_manifest.tsv 生成本地池说明(清单从数据生成,不手抄)。

用法: py -3 _工具脚本/gen_ports_pool_readme.py
"""
import io
import json
import os
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POOL = os.path.join(ROOT, "04-游戏资源库", "公版与开源游戏", "ports全量合法池")
MAN = os.path.join(POOL, "_manifest.tsv")
DEST = os.path.join(POOL, "README.md")
AUDIT = os.path.join(ROOT, "04-游戏资源库", "公版与开源游戏", "portmaster_自备数据审计.tsv")
INFO = os.path.join(ROOT, "02-模拟器库", "已clone仓库", "R36S专用",
                    "PortMaster-Info", "ports.json")

KIND_CN = [
    ("self", "自带完整游戏(官方 `availability=full`)"),
    ("self_unmarked", "官方未标注, 但 zip 内无占位文件、说明里没要求自备"),
    ("demo", "自带可玩的 demo(`availability=demo`)"),
    ("needs_free", "需自备**免费可得**的素材(`availability=free`)"),
    ("needs_conflict", "官方标 full 却写明要自备 —— 以上游 `inst` 为准"),
    ("needs_unknown", "官方字段为空, 但占位文件或说明暴露了自备要求"),
]


def rtr_split(pkgs):
    """官方 attr.rtr 分组。
    消费方核实过: harbour.py:2458 只把它输出成 runtype 显示标签,
    pugscene.py:2350 把它当 GUI 筛选条件 —— 不做安装闸门。
    """
    ports = json.load(open(INFO, encoding="utf-8"))["ports"]
    yes, no = [], []
    for pkg in pkgs:
        rec = ports.get(pkg) or {}
        a = rec.get("attr") or {}
        size = int((rec.get("source") or {}).get("size") or 0)
        (yes if a.get("rtr") else no).append((pkg, a.get("title", ""), size))
    return yes, no


def cap_check(pkgs):
    """重算:池子里有没有包在 XF45V(RK3326, 1024x768)上因能力标签不够而装不了。

    字段名是 `attr.reqs`(列表), 不是 `requires` —— 上游 ports.json 里没有 requires。
    令牌含义: lowres=要 320x240 屏(XF45V 是 1024x768, 会被挡), power/ultra=要更强 SoC,
    !lowres=反过来要求高分辨率(XF45V 满足), opengl/analog_2=驱动与手柄能力。
    返回 (会被挡的分组, 全池令牌分布) —— 令牌分布一并打印, 好让"0 命中"可核。
    """
    ports = json.load(open(INFO, encoding="utf-8"))["ports"]
    bad = {"lowres": [], "power": [], "ultra": [], "分辨率": []}
    tokens = Counter()
    for pkg in pkgs:
        rec = ports.get(pkg)
        if not rec:
            continue
        for token in ((rec.get("attr") or {}).get("reqs") or []):
            tokens[token] += 1
            if token == "lowres":
                bad["lowres"].append(pkg)
            elif token in ("power", "ultra"):
                bad[token].append(pkg)
            elif "x" in token and token.split("x")[0].isdigit():
                bad["分辨率"].append(pkg)
    return bad, tokens


def audit_section(pkgs):
    """读 _自备数据审计.tsv, 逐包说清"到底要不要自备游戏数据"。"""
    if not os.path.exists(AUDIT):
        return (["## 到底哪些是真·解压即玩(每次生成本文件都重算)\n",
                 "> ⚠ 缺 `../portmaster_自备数据审计.tsv`,无法给结论。先跑 "
                 "`py -3 _工具脚本/portmaster_data_audit.py` 再重新生成本文件"
                 "—— 审计表缺位时这里不写\"整池解压即玩\"。\n"], None)
    rows = [l.rstrip("\n").split("\t") for l in open(AUDIT, encoding="utf-8")][1:]
    rows = [dict(zip(["name", "title", "kind", "evidence", "availability", "mb",
                      "markers", "downloads", "store", "inst"], r)) for r in rows]
    have = {r["name"] for r in rows}
    missing = [p[:-4] for p in pkgs if p[:-4] not in have]
    by = {}
    for r in rows:
        by.setdefault(r["kind"], []).append(r)
    need = [r for r in rows if r["kind"].startswith("needs_")]
    n_free = len(by.get("needs_free", []))

    lines = ["## 到底哪些是真·解压即玩(每次生成本文件都重算)\n",
             "判定用的是上游 `attr.availability` 字段, 它的语义写在官方表单里"
             "(`PortMaster-Website/website/port-json.html:222-227`), 不是我们自己定的:\n",
             "| availability | 官方原文 | 含义 |", "|---|---|---|",
             "| `full` | Free game, all files included | 文件全在里面 |",
             "| `demo` | Demo files included | 自带 demo, 完整版另需 |",
             "| `free` | **Free external assets needed** | 要自备, 但素材免费可得 |",
             "| `paid` | **Paid external assets needed** | 要自备已购买的原版 |",
             "| 空 | — | 老条目没这个字段, 只能靠证据推断 |",
             "\n**`free` 不等于\"免费包含\"** —— 官方原话是 external assets needed。"
             "本池早期版本按 `free`/`full` 一律算作自带, 所以混进了 %d 个 `availability=free` 的包; "
             "移植层本身仍有用, 保留不删, 但要按下面的表补数据。重算命令:"
             "`py -3 _工具脚本/portmaster_data_audit.py`(逐包读 zip 目录 + `inst` 文本 + 体积)。\n" % n_free,
             "| 分组 | 包数 | 合计 MB |", "|---|---|---|"]
    for key, cn in KIND_CN:
        g = by.get(key, [])
        lines.append("| %s | %d | %.0f |" % (cn, len(g), sum(float(r["mb"]) for r in g)))
    lines.append("\n**可直接落地即玩: %d 个;仍需自备数据: %d 个。**\n"
                 % (sum(len(by.get(k, [])) for k in ("self", "self_unmarked", "demo")), len(need)))
    top = sorted((r for r in rows if r["kind"] in ("self", "demo")),
                 key=lambda r: -int(r["downloads"]))[:40]
    if top:
        lines.append("### 先装这 %d 个(官方 `full`/`demo` 里下载量最高的, 就是被机器验证最多的一批)\n" % len(top))
        lines.append("| 包 | 标题 | 体积 MB | 下载量 |")
        lines.append("|---|---|---|---|")
        for r in top:
            lines.append("| %s | %s | %s | %s |" % (r["name"], r["title"][:32], r["mb"], r["downloads"]))
        lines.append("")
    if missing:
        lines.append("> ⚠ 审计表比当前池少 %d 个包(新下好后没重跑审计): %s\n"
                     % (len(missing), ", ".join(missing[:10])))
    if need:
        lines.append("### 仍需自备数据的包(怎么补, 官方说明原样抄在这里)\n")
        lines.append("| 包 | 分组 | 你要做的事 | 素材来源 |")
        lines.append("|---|---|---|---|")
        order = {k: i for i, (k, _) in enumerate(KIND_CN)}
        for r in sorted(need, key=lambda x: (order.get(x["kind"], 9), x["name"])):
            todo = (r["inst"] or r["markers"] or "(见包内 README)").replace("|", "/")[:150]
            lines.append("| %s | %s | %s | %s |" % (r["name"], r["kind"], todo, r["store"] or "—"))
        lines.append("\n这些素材绝大多数是 **itch.io / 作者站免费的原始数据文件**, 或已购原版目录 —— "
                     "不属于我们能替你下载的商业 ROM。补法都一样:解压到该端口目录里"
                     "(端口目录见包内占位文件名),不要改端口 `.sh` 的名字。\n")
    return lines, need


def main():
    rows = [l.rstrip("\n").split("\t") for l in open(MAN, encoding="utf-8")][1:]
    rows = [r for r in rows if len(r) >= 5]
    got = [r for r in rows if r[1] in ("downloaded", "already")]
    skip = [r for r in rows if r[1] not in ("downloaded", "already")]
    total = sum(int(r[2] or 0) for r in got)

    lines = []
    lines.append("# ports 全量合法池(本地已下载)\n")
    lines.append("PortMaster 官方 release 里 **r36s 档(RK3326)可安装、且不要求自备商业 ROM** 的端口包,"
                 "全部逐个按 `ports.json` 的 `source.md5` 校验后落地。本文件由 "
                 "`py -3 _工具脚本/gen_ports_pool_readme.py` 从 `_manifest.tsv` 生成。\n")
    lines.append("- 已落地 **%d** 个包,合计 **%.2f GB**" % (len(got), total / 1e9))
    lines.append("- 未取: **%d** 个%s" % (
        len(skip),
        "" if not skip else
        "(原因见下表;`too_big` = 超过脚本体积上限,`no_md5` = 上游没给校验值,`dl_fail`/`md5_mismatch` = 需重跑)\n"))
    lines.append("- 重跑(幂等,已存在的会按 MD5 跳过):`py -3 _工具脚本/portmaster_bulk_dl.py`\n")

    bad, tokens = cap_check([r[0] for r in got])
    blocked = sum(len(v) for v in bad.values())
    lines.append("## XF45V 能不能装(每次生成本文件都重算一遍)")
    lines.append("ArkOS 装 ports 时按**能力标签**过滤,不是按机型白名单。RK3326 拿不到 `power`/`ultra`,"
                 "而 XF45V 是 1024×768 → 拿到的是 `hires` 而不是 `lowres`。逐包比对 `ports.json` 的 `attr.reqs`:\n")
    lines.append("| 会被挡的要求 | 池内命中包数 |")
    lines.append("|---|---|")
    for k, v in bad.items():
        lines.append("| %s | %d |" % ("指定了具体分辨率" if k == "分辨率" else "需要 `%s`" % k, len(v)))
    lines.append("\n%s\n" % (
        "**结论:%d 个包一个都不涉及上面任何一条,整池在 XF45V 上都可安装。**" % len(got)
        if blocked == 0 else
        "有 %d 处命中,列出:%s" % (blocked, ", ".join(sorted({p for v in bad.values() for p in v})[:10]))))
    lines.append("全池 `attr.reqs` 令牌分布(空 = 整池没有任何要求): %s\n"
                 % (", ".join("`%s`×%d" % (t, n) for t, n in sorted(tokens.items(), key=lambda x: -x[1]))
                    if tokens else "无"))
    yes, no = rtr_split([r[0] for r in got])
    lines.append("## 官方 `rtr` 标记(只影响显示,不影响能不能装)")
    lines.append("`attr.rtr` = 官方在参考机型上确认过\"能全速跑\"。设备上 `harbour.py:2458` 只把它打印成 "
                 "`runtype` 标签、`pugscene.py:2350` 把它当 GUI 筛选条件,**不做安装过滤**;"
                 "所以下面这些 `rtr=False` 照样能装,只是官方没保证满帧 —— RK3326 + 1024×768(640×480 的 2.56 倍像素)"
                 "对 3D/大场景的包本来就更吃力。\n")
    lines.append("- `rtr=True`(官方确认实时):**%d** 个" % len(yes))
    lines.append("- `rtr=False`(未确认/需自备数据/重负载):**%d** 个\n" % len(no))
    if no:
        lines.append("| 包 | 标题 | 体积 MB |")
        lines.append("|---|---|---|")
        for pkg, title, size in sorted(no, key=lambda x: -x[2]):
            lines.append("| %s | %s | %.1f |" % (pkg, title[:34], size / 1e6))
        lines.append("")

    audit_lines, need_rows = audit_section([r[0] for r in got])
    lines.extend(audit_lines)

    lines.append("## 装到机器上\n")
    lines.append("每个 zip **顶层就是散装的 `<游戏名>.sh` + 数据文件**(抽查 2048 / Spelunky / Cave Story / "
                 "srb2kart 四个包确认),所以**一个包解到一个独立目录**:"
                 "`/roms/ports/<游戏名>/`,不要把整池全解到 `/roms/ports/` 平铺。"
                 "`<游戏名>.sh` 的名字**不要改**(ArkOS 就靠它列出端口)。"
                 "ports 的运行库永远在**卡 1**,换卡 2 的 ROM 不影响。\n")
    lines.append("详见 `../PortMaster移植游戏指南.md`(按能力 capability 判定能否安装,不是按机型白名单)。\n")
    lines.append("## 包清单(按体积降序)\n")
    lines.append("| 包 | 体积 MB | MD5 |")
    lines.append("|---|---|---|")
    for r in sorted(got, key=lambda x: -int(x[2] or 0)):
        lines.append("| %s | %.1f | `%s` |" % (r[0], int(r[2] or 0) / 1e6, r[4][:12]))
    if skip:
        lines.append("\n## 未取的包\n")
        lines.append("| 包 | 状态 | 说明 |")
        lines.append("|---|---|---|")
        for r in skip:
            lines.append("| %s | %s | %s |" % (r[0], r[1], (r[3] or "")[:40]))
    open(DEST, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("写入 %s: %d 个包 / %.2f GB, 未取 %d, 仍需自备数据 %s" % (
        DEST, len(got), total / 1e9, len(skip),
        "无审计表" if need_rows is None else len(need_rows)))


if __name__ == "__main__":
    main()
