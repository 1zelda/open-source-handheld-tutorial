from pathlib import Path
import hashlib
import html
import json
import re
from urllib.parse import unquote

import pymupdf
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path("F:/开源掌机教程")
MD_PATH = ROOT / "洛克人1候选路由与问答消费方交付_2026-11-25.md"
PDF_PATH = ROOT / "洛克人1候选路由与问答消费方交付_2026-11-25.pdf"
OUT = ROOT / "知识库P1_20261118/megaman1_candidate_20261125/qc/consumer"
EVAL_PATH = ROOT / "知识库P1_20261118/megaman1_candidate_consumer_eval_20261125.json"


def inline(s):
    codes = []

    def stash(match):
        codes.append(html.escape(match.group(1)))
        return f"@@CODE{len(codes) - 1}@@"

    s = re.sub(r"`([^`]+)`", stash, s)
    s = html.escape(s)

    def link(match):
        label, target = match.group(1), match.group(2)
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            path, sep, frag = target.partition("#")
            suffix = "#L" + frag[1:] if sep and frag.startswith("L") else ("#" + frag if sep else "")
            target = (ROOT / path).as_uri() + suffix
        return f'<a href="{html.escape(target, quote=True)}">{label}</a>'

    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    for i, code in enumerate(codes):
        s = s.replace(f"@@CODE{i}@@", f"<code>{code}</code>")
    return s


def render_markdown(text):
    lines = text.splitlines()
    body = []
    i = 0
    heading_no = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            lang = line[3:].strip()
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            body.append(f'<pre><code class="language-{html.escape(lang)}">{html.escape(chr(10).join(buf))}</code></pre>')
            continue
        match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if match:
            level = len(match.group(1))
            title = match.group(2).strip()
            heading_no += 1
            cls = ' class="major-break"' if level == 2 and title.startswith(("4.", "6.")) else ""
            body.append(f'<h{level} id="h{heading_no}"{cls}>{inline(title)}</h{level}>')
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.fullmatch(
            r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*", lines[i + 1]
        ):
            def cells(s):
                return [x.strip() for x in s.strip().strip("|").split("|")]

            headers = cells(line)
            i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            body.append('<div class="table-wrap"><table><thead><tr>' + "".join(f"<th>{inline(x)}</th>" for x in headers) + "</tr></thead><tbody>")
            for row in rows:
                body.append("<tr>" + "".join(f"<td>{inline(x)}</td>" for x in row) + "</tr>")
            body.append("</tbody></table></div>")
            continue
        if re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$", line):
            tag = "ol" if re.match(r"^\s*\d+\.", line) else "ul"
            items = []
            while i < len(lines):
                item = re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$", lines[i])
                if not item:
                    break
                items.append(f"<li>{inline(item.group(1))}</li>")
                i += 1
            body.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue
        buf = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip():
            nxt = lines[i]
            if nxt.startswith(("#", ">", "```", "|")) or re.match(r"^\s*(?:[-*+]|\d+\.)\s+", nxt):
                break
            buf.append(nxt.strip())
            i += 1
        body.append(f"<p>{inline(' '.join(buf))}</p>")
    return "".join(body)


CSS = """
@page { size: A4; }
* { box-sizing: border-box; }
html { font-size: 10pt; }
body { margin: 0; color: #182230; font-family: "Microsoft YaHei", "Meiryo", "Noto Sans CJK SC", Arial, sans-serif; line-height: 1.58; }
h1 { font-size: 22pt; line-height: 1.25; color: #102a43; margin: 0 0 13pt; padding-bottom: 9pt; border-bottom: 3px solid #2f6feb; }
h2 { font-size: 15pt; color: #102a43; margin: 20pt 0 8pt; padding-bottom: 4pt; border-bottom: 1px solid #b8c7d9; break-after: avoid; }
h3 { font-size: 12pt; color: #174a7e; margin: 13pt 0 5pt; break-after: avoid; }
p { margin: 4pt 0 7pt; orphans: 3; widows: 3; }
ul,ol { margin: 4pt 0 8pt 18pt; padding: 0; }
li { margin: 2pt 0; }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.88em; background: #f1f4f8; color: #7a271a; padding: 0.5pt 2pt; border-radius: 2px; overflow-wrap: anywhere; word-break: break-all; }
pre { background: #f1f4f8; border: 1px solid #d6deea; padding: 8pt; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
pre code { background: transparent; padding: 0; color: #243b53; }
a { color: #175cd3; text-decoration: none; overflow-wrap: anywhere; }
strong { color: #102a43; }
.table-wrap { width: 100%; margin: 7pt 0 10pt; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 8.4pt; line-height: 1.4; }
th,td { border: 1px solid #b8c7d9; padding: 4.5pt; vertical-align: top; overflow-wrap: anywhere; word-break: break-word; }
th { background: #dce9fb; color: #102a43; font-weight: 700; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
.major-break { break-before: auto; }
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    text = MD_PATH.read_text(encoding="utf-8")
    evaluation = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    doc = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
           '<title>洛克人1候选路由与问答消费方交付（2026-11-25）</title>'
           f"<style>{CSS}</style></head><body>{render_markdown(text)}</body></html>")
    html_path = OUT / "report.html"
    html_path.write_text(doc, encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            headless=True, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1200, "height": 1600})
        page.goto(html_path.as_uri(), wait_until="load")
        page.emulate_media(media="print")
        overflow = page.evaluate(
            "() => Array.from(document.querySelectorAll('body *'))"
            ".filter(e => e.scrollWidth > e.clientWidth + 2 && getComputedStyle(e).overflowX === 'visible')"
            ".slice(0,20).map(e => ({tag:e.tagName, cls:e.className, sw:e.scrollWidth, cw:e.clientWidth, text:(e.innerText||'').slice(0,80)}))")
        page.pdf(path=str(PDF_PATH), format="A4", print_background=True,
                 display_header_footer=True, prefer_css_page_size=True,
                 margin={"top": "17mm", "bottom": "16mm", "left": "15mm", "right": "15mm"},
                 header_template='<div style="font-size:8px;color:#64748b;width:100%;padding:0 15mm;">洛克人1候选路由与问答消费方交付 · 2026-11-25</div>',
                 footer_template='<div style="font-size:8px;color:#64748b;width:100%;padding:0 15mm;"><span>隔离候选 · 未接生产</span><span style="float:right;"><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
        browser.close()

    pdf = pymupdf.open(PDF_PATH)
    texts = [p.get_text() for p in pdf]
    all_text = "\n".join(texts)
    compact = re.sub(r"\s+", "", all_text)
    outside = []
    for n, p in enumerate(pdf, 1):
        rect = p.rect
        for block in p.get_text("blocks"):
            x0, y0, x1, y1 = block[:4]
            if x0 < -1 or y0 < -1 or x1 > rect.width + 1 or y1 > rect.height + 1:
                outside.append({"page": n, "bbox": [round(x, 1) for x in (x0, y0, x1, y1)], "text": block[4][:80]})
    index_sha = hashlib.sha256((ROOT / "知识库P1_20261118/megaman1_candidate_20261125/index.json").read_bytes()).hexdigest()
    pdf_links = [link for p in pdf for link in p.get_links()]
    link_targets = [Path(unquote(link["file"]).lstrip("/")) for link in pdf_links if link.get("file")]
    expected_link_count = len(re.findall(r"^\- \[[^\]]+\]\([^)]+\)", text, re.M))
    checks = {
        "pages_positive": len(pdf) > 0,
        "conclusion_present": "一页结论" in compact,
        "routing_present": "候选域路由" in compact,
        "consumer_present": "隔离问答消费方" in compact,
        "verification_present": "验证结果" in compact,
        "isolation_present": "本轮隔离指纹" in compact,
        "usage_present": "怎么使用" in compact,
        "readiness_present": "就绪度与下一步" in compact,
        "delivery_index_present": "交付索引" in compact,
        "candidate_sha_present": index_sha in compact,
        "candidate_sha_matches": index_sha == evaluation["candidate_index_sha256"],
        "route_13_present": "13/13" in compact,
        "default_12_present": "default12/12" in compact,
        "strict_12_present": "strict12/12" in compact,
        "wrong_zero_present": "错误出证0/0" in compact,
        "logs_24_present": "24行" in compact,
        "not_production_present": "不是整款游戏知识库完成" in compact and "尚未接生产路由/消费方" in compact,
        "no_replacement_char": "\ufffd" not in all_text,
        "no_blank_pages": all(len(t.strip()) > 80 for t in texts),
        "no_outside_blocks": not outside,
        "no_dom_overflow": not overflow,
        "delivery_links_present": len(link_targets) == expected_link_count == 9,
        "delivery_links_resolve": all(path.is_file() for path in link_targets),
    }
    thumbs = []
    for n, p in enumerate(pdf, 1):
        pix = p.get_pixmap(matrix=pymupdf.Matrix(0.75, 0.75), alpha=False)
        im = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        canvas = Image.new("RGB", (im.width + 8, im.height + 28), "white")
        canvas.paste(im, (4, 24))
        ImageDraw.Draw(canvas).text((8, 5), f"Page {n}", fill="black")
        thumbs.append(canvas)
    cols = 3
    rows = (len(thumbs) + cols - 1) // cols
    cw = max(i.width for i in thumbs)
    ch = max(i.height for i in thumbs)
    sheet = Image.new("RGB", (cols * cw, rows * ch), (220, 225, 230))
    for n, im in enumerate(thumbs):
        sheet.paste(im, ((n % cols) * cw, (n // cols) * ch))
    sheet.save(OUT / "contact_sheet.png")
    for stale in OUT.glob("page_*.png"):
        stale.unlink()
    for n in range(1, len(pdf) + 1):
        pix = pdf[n - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
        pix.save(OUT / f"page_{n:02d}.png")
    report = {"pages": len(pdf), "snapshot_pages": list(range(1, len(pdf) + 1)),
              "check_count": len(checks), "candidate_index_sha256": index_sha,
              "checks": checks, "dom_overflow": overflow, "outside_blocks": outside,
              "delivery_link_targets": [str(path) for path in link_targets],
              "page_text_lengths": [len(t) for t in texts], "pdf_bytes": PDF_PATH.stat().st_size}
    (OUT / "render_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    pdf.close()
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
