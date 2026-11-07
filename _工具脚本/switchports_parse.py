# -*- coding: utf-8 -*-
"""按小节解析 SwitchPorts README 的移植表。
README 里同一份表格有两种 schema：
  ### Emulators  -> 7 列（System | Title | Version | Last Updated | Link | GBATemp | Status）
  其余平台小节  -> 6 列（Game | Version | Last Updated | Link | GBATemp | Status）
另外 Emulators 表里同一系统的后续行会把 System 留空，需要向下填充。
"""
import io, json, os, re, sys, time

SRC = os.path.join(os.path.dirname(__file__), "..", "_scratch", "sp.md")
OUT = os.path.join(os.path.dirname(__file__), "..", "_scratch", "sp_rows.json")

LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)]+)\)")
DATE = re.compile(r"^\*?(\d{2})/(\d{2})/(\d{4})\*?$")


def cells(line):
    s = line.strip()
    if not s.startswith("|"):
        return None
    parts = [p.strip() for p in s.strip("|").split("|")]
    if all(set(p) <= set("-: ") for p in parts if p):
        return None
    return parts


def split_link(cell):
    m = LINK.search(cell)
    if not m:
        return re.sub(r"[*_`]", "", cell).strip(), ""
    label = re.sub(r"^[^\w]*", "", m.group(1)).strip()
    return (label or m.group(2)), m.group(2)


def parse(md):
    rows, section, schema, last_sys = [], "", None, ""
    for line in md.splitlines():
        h = re.match(r"^###\s+(.*\S)\s*$", line)
        if h:
            section, schema, last_sys = h.group(1), None, ""
            continue
        c = cells(line)
        if c is None:
            continue
        if schema is None:
            schema = len(c)
        if len(c) != schema:
            continue
        if schema == 7:
            syscell, title, ver, upd, link, temp = c[0], c[1], c[2], c[3], c[4], c[5]
            if syscell:
                last_sys = syscell
            else:
                syscell = last_sys
        else:
            syscell, title, ver, upd, link, temp = section, c[0], c[1], c[2], c[3], c[4]
        title = re.sub(r"^[^\w]*", "", title).strip()
        label, url = split_link(link)
        d = DATE.match(upd)
        rows.append([section, syscell, title, ver,
                     "%s-%s-%s" % (d.group(3), d.group(2), d.group(1)) if d else upd,
                     label, url, split_link(temp)[1]])
    return rows


def main():
    with io.open(SRC, encoding="utf-8", errors="replace") as fh:
        md = fh.read()
    rows = parse(md)
    got = [r for r in rows if r[6]]
    print("rows=%d with-link=%d sections=%d" % (len(rows), len(got),
                                                 len({r[0] for r in rows})))
    for sec in sorted({r[0] for r in rows}):
        sub = [r for r in rows if r[0] == sec]
        print("  %-40s %3d  newest=%s" % (sec, len(sub),
                                          max(r[4] for r in sub if re.match(r"^\d{4}", r[4]))))
    with io.open(OUT, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=0)
    print("wrote " + OUT)


if __name__ == "__main__":
    main()
