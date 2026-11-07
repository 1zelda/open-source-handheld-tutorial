import re, html, pathlib, urllib.parse, subprocess, sys

SRC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path(r"F:\开源掌机教程\Sunshine部署运行说明书.md")
OUT = SRC.with_suffix(".html")
PDF = SRC.with_suffix(".pdf")
EDGE = pathlib.Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
text = SRC.read_text(encoding="utf-8")
_title = re.search(r"^#\s+(.*)$", text, re.M)
TITLE = _title.group(1).strip() if _title else SRC.stem


def inline(s):
    s = html.escape(s, quote=False)
    store = []

    def stash(h):
        store.append(h)
        return "\x00%d\x00" % (len(store) - 1)

    # images then links (both may sit inside other spans)
    s = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)",
               lambda m: stash('<img alt="%s" src="%s">' % (m.group(1), m.group(2))), s)
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
               lambda m: stash('<a href="%s">%s</a>' % (m.group(2), m.group(1))), s)
    s = re.sub(r"`([^`]+)`", lambda m: stash("<code>%s</code>" % m.group(1)), s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    # autolinks survive escaping as &lt;url&gt; ; bare urls stay plain text
    s = re.sub(r"&lt;(https?://[^\s&]+)&gt;",
               lambda m: stash('<a href="%s">%s</a>' % (m.group(1), m.group(1))), s)
    s = re.sub(r"\x00(\d+)\x00", lambda m: store[int(m.group(1))], s)
    return s


lines = text.split("\n")
out, i = [], 0
in_code = False


def flush_list(buf, ordered):
    if not buf:
        return
    tag = "ol" if ordered else "ul"
    out.append("<%s>" % tag)
    out.extend(buf)
    out.append("</%s>" % tag)


while i < len(lines):
    ln = lines[i]

    if ln.strip().startswith("```"):
        if not in_code:
            out.append("<pre><code>")
            in_code = True
        else:
            out.append("</code></pre>")
            in_code = False
        i += 1
        continue
    if in_code:
        out.append(html.escape(ln))
        i += 1
        continue

    stripped = ln.strip()

    if not stripped:
        i += 1
        continue

    if stripped == "---":
        out.append("<hr>")
        i += 1
        continue

    m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
    if m:
        lvl = len(m.group(1))
        out.append("<h%d>%s</h%d>" % (lvl, inline(m.group(2)), lvl))
        i += 1
        continue

    if stripped.startswith(">"):
        buf = []
        while i < len(lines) and lines[i].strip().startswith(">"):
            buf.append(inline(lines[i].strip().lstrip(">").strip()))
            i += 1
        out.append("<blockquote><p>%s</p></blockquote>" % " ".join(buf))
        continue

    if stripped.startswith("|") and stripped.endswith("|"):
        rows = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            rows.append(lines[i].strip())
            i += 1
        cells = lambda r: [c.strip() for c in r.strip("|").split("|")]
        head = cells(rows[0])
        body = [r for r in rows[2:] if not re.match(r"^\|[\s:|-]+\|$", r)]
        t = ["<table>", "<thead><tr>"]
        t += ["<th>%s</th>" % inline(c) for c in head]
        t.append("</tr></thead><tbody>")
        for r in body:
            t.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in cells(r)) + "</tr>")
        t += ["</tbody></table>"]
        out.append("\n".join(t))
        continue

    m = re.match(r"^[-*]\s+(.*)$", stripped)
    if m:
        buf = ["<li>%s</li>" % inline(m.group(1))]
        i += 1
        while i < len(lines):
            n = lines[i].strip()
            mm = re.match(r"^[-*]\s+(.*)$", n)
            if not mm:
                break
            buf.append("<li>%s</li>" % inline(mm.group(1)))
            i += 1
        out.append("<ul>" + "".join(buf) + "</ul>")
        continue

    m = re.match(r"^\d+\.\s+(.*)$", stripped)
    if m:
        buf = ["<li>%s</li>" % inline(m.group(1))]
        i += 1
        while i < len(lines):
            mm = re.match(r"^\d+\.\s+(.*)$", lines[i].strip())
            if not mm:
                break
            buf.append("<li>%s</li>" % inline(mm.group(1)))
            i += 1
        out.append("<ol>" + "".join(buf) + "</ol>")
        continue

    para = [stripped]
    i += 1
    while i < len(lines):
        n = lines[i].strip()
        if (not n or n.startswith(("#", "|", ">", "```")) or re.match(r"^[-*]\s", n)
                or re.match(r"^\d+\.\s", n) or n == "---"):
            break
        para.append(n)
        i += 1
    out.append("<p>%s</p>" % "<br>".join(inline(p) for p in para))

body = "\n".join(out)
CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: "Microsoft YaHei","PingFang SC",sans-serif; font-size: 10.5pt;
       line-height: 1.62; color: #1c2430; max-width: none; margin: 0; }
h1 { font-size: 20pt; border-bottom: 3px solid #2f6fed; padding-bottom: 6px; margin: 0 0 14px; }
h2 { font-size: 15pt; color: #14418c; margin: 18px 0 8px; padding-left: 8px;
     border-left: 5px solid #2f6fed; page-break-after: avoid; }
h3 { font-size: 12.5pt; color: #1b1b1b; margin: 14px 0 6px; page-break-after: avoid; }
p { margin: 5px 0; }
h2 + p { page-break-inside: avoid; }
hr { border: 0; border-top: 1px solid #d3dae6; margin: 12px 0; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 10px; font-size: 9.6pt; }
th, td { border: 1px solid #c6cfdd; padding: 5px 7px; vertical-align: top; text-align: left; }
th { background: #eef3fb; font-weight: 600; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
tbody tr:nth-child(even) { background: #fafbfe; }
code { font-family: Consolas,"Courier New",monospace; background: #f1f3f7;
       padding: 1px 4px; border-radius: 3px; font-size: 9.4pt; color: #9d2233; }
pre { background: #f6f8fa; border: 1px solid #dfe4ec; border-left: 4px solid #2f6fed;
      padding: 7px 10px; border-radius: 4px; overflow-x: hidden; page-break-inside: avoid; }
pre code { background: none; color: #24292f; padding: 0; font-size: 9.2pt; }
blockquote { margin: 8px 0; padding: 6px 11px; background: #fff8e6;
             border-left: 4px solid #e0a800; border-radius: 3px; }
ul, ol { margin: 5px 0 8px; padding-left: 22px; }
li { margin: 2px 0; }
img { display: block; max-width: 100%; max-height: 200mm; margin: 12px auto;
      border: 1px solid #ccd5e2; border-radius: 4px; page-break-inside: avoid; }
a { color: #2f6fed; word-break: break-all; }
strong { color: #10233f; }
"""
OUT.write_text(
    "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
    "<title>%s</title><style>%s</style></head>"
    "<body>%s</body></html>" % (html.escape(TITLE), CSS, body), encoding="utf-8")
print("html bytes:", OUT.stat().st_size)
print("headings:", len(re.findall(r"<h[23]", body)), "tables:", body.count("<table>"),
      "images:", body.count("<img"), "code blocks:", body.count("<pre>"))

url = "file:///" + urllib.parse.quote(OUT.as_posix(), safe="/:")
subprocess.run([str(EDGE), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                "--print-to-pdf=" + str(PDF), url], check=False,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("pdf bytes:", PDF.stat().st_size)

try:
    import pymupdf
except ImportError:
    print("装 pymupdf 才能自动查页数：pip install pymupdf")
    raise SystemExit(0)

doc = pymupdf.open(str(PDF))
print("pages:", doc.page_count)
sparse = [i + 1 for i, p in enumerate(doc) if len(p.get_text().strip()) < 200 and not p.get_images()]
print("空白嫌疑页:", sparse or "无")

