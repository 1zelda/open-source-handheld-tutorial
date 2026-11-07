#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_topic.py —— 专题:**源码泄露 / 盗版打击** 的时间线跟踪(离线,只读台账)。

为什么单独一条专线,而不是塞进 HOT 或"大作登陆平台":
  * HOT 靠"产品名 + 时间窗",任何一句 "GTA 6 什么时候上 Switch 2" 都算爆款,拿来跟泄露事件混在一起就废了;
  * 大作专线要的是"作品名+登陆动词+平台名"三者同现,泄露报道根本不含平台目标。
  所以这类消息必须有**自己的一条窄口径**:标题里同时出现"被泄露的东西(source code / build / 源码)"
  和"泄露/下架/诉讼"这一类动作词才算。裸 leak 一律不算——游戏预告泄露是天天都有的谣言。

边界(2026-10-12 与用户重申过,写死在这里):本专线**只跟踪报道与时间线**。
台账里出现的任何指向"转存地址/网盘/Torrent/Telegram 群"的东西都不在这条线的能力范围内,
scene_dl.py 的 BAN 闸门也照样把它们挡在外面。要放宽必须先改代码,而我不改。

产物: 06-资讯监控/专题-源码泄露与盗版打击.md(整份重写,台账是唯一事实源)
"""
import csv
import datetime as dt
import os
import re
import sys

# 计划任务里不带 PYTHONUTF8 时,stdout 会按 cp936 编码,被 daily_run.py 以 utf-8 捕获后全是乱码
# (2026-10-12 第一次进 _schedule.log 就这样)。和 scene_monitor 一样,自己把自己钉成 utf-8。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "06-资讯监控", "台账.tsv")
OUT = os.path.join(ROOT, "06-资讯监控", "专题-源码泄露与盗版打击.md")

# 主语:被泄露/被打击的东西是什么。必须具体,不收裸 "leak"。
SUBJECT = re.compile(
    r"source code|源码|源代码|game build|stolen build|source dump|"
    r"unreleased (build|code)|内部构建", re.I)
# 动作:泄露本身
LEAK = re.compile(r"leak(?:ed|s)?|exposed|stolen|breach|hacked|泄露|外流|被黑", re.I)
# 动作:法律/平台层面的打击。
# 2026-10-12 第一版在这里栽过两次,都是**子串误命中**:`sue[sd]?` 命中 "issue",`court` 命中 "coreless"。
# 所以英文一律上词边界。DMCA / cease-and-desist / takedown 这三个词本身就够特异,可以独立成立。
# 2026-10-12 第一次修完又栽了一次:裸 `takedown` 把 "Burnout 3 Takedown Switch Port"(游戏名就叫 Takedown)
# 判成了盗版打击。所以 takedown 必须带法律上下文才成立,DMCA/律师函/下架 这类本身够特异的可以独立成立。
CRACKDOWN_STRONG = re.compile(
    r"\bDMCA\b|cease[- ]and[- ]desist|律师函|下架|"
    r"\btakedown (?:notice|request|demand)s?\b|\bremoved (?:following|after|on)\b", re.I)
CRACKDOWN = re.compile(
    r"\blawsuit\b|\bsues\b|\bsued\b|\bcourt\b|\bruling\b|\binjunction\b|"
    r"\blitigation\b|诉讼|判决", re.I)
# 光有"诉讼/判决"不够,还得落在盗版这条线上,否则游戏公司的商业互诉也算进来。
PIRACY = re.compile(
    r"pirat|warez|torrent|\bdump\b|\brom\b|\broms\b|\bnsp\b|\bxci\b|crack|盗版|破解", re.I)

HEAD = """# 专题:源码泄露与盗版打击 —— 时间线

- 生成:%s(本地) —— 由 `_工具脚本/scene_topic.py` 整份重写,事实源只有 `台账.tsv`
- 判据(窄口径,三次栽坑之后定下来的):
  1. **源码泄露** = 出现"被泄露的东西"(source code / 源码 / game build / source dump)且同时有泄露动作(leak / exposed / stolen / breach / 泄露);
  2. **盗版打击** = DMCA / cease-and-desist / 律师函 / 下架 / 带上下文的 takedown notice,
     或者(诉讼类词 + 盗版类词)同现;
  3. 裸 "leak" 不算(游戏预告泄露是谣言流水线),裸 "takedown" 也不算(有款游戏就叫 Burnout 3 **Takedown**),
     纯商业互诉、只涉作弊器的诉讼同样不进这条线 —— **宁可漏,不要污染短名单**。
- **边界:这里只有报道和讨论,没有任何被泄露的代码。** 本库不去找、也不收任何转存地址;
  要收成品的一律走 `合法收录登记表.tsv` + `scene_dl.py`,那里的 BAN 闸门会把 dump 包挡死。

| 日期 | 类别 | 源 | 标题 | 链接 |
|---|---|---|---|---|

"""


def classify(title, url):
    """判据只在这一处。裸 leak 不算;要嘛碰到"源码/构建"这类主语,要嘛落在盗版线上。"""
    t = "%s %s" % (title or "", url or "")
    subj = SUBJECT.search(t)
    if subj and CRACKDOWN.search(t):
        return "源码相关的打击/诉讼"
    if subj and LEAK.search(t):
        return "源码泄露"
    if CRACKDOWN_STRONG.search(t):
        return "盗版打击"
    if CRACKDOWN.search(t) and PIRACY.search(t):
        return "盗版打击"
    return ""


def main():
    if not os.path.exists(LEDGER):
        print("没有台账,先跑 scene_monitor.py")
        return 1
    rows = list(csv.DictReader(open(LEDGER, encoding="utf-8"), delimiter="\t"))
    hits = []
    for r in rows:
        cat = classify(r.get("title", ""), r.get("url", ""))
        if not cat:
            continue
        hits.append((r.get("pub") or r.get("first_seen_utc", "")[:10], cat,
                     r.get("source", ""), r.get("title", ""), r.get("url", "")))
    hits.sort(key=lambda x: x[0], reverse=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(HEAD % dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
        for d, cat, src, title, url in hits[:400]:
            fh.write("| `%s` | %s | %s | %s | [原文](%s) |\n"
                     % (d[:10], cat, src, title.replace("|", "/"), url))
        fh.write("\n> 共 %d 条。台账是唯一事实源,补源后重跑本脚本即可回填历史。\n" % len(hits))
    print("专题-源码泄露与盗版打击: %d 条 -> %s" % (len(hits), OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
