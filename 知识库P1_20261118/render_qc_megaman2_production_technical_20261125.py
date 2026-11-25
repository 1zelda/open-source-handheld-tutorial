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
MD_PATH = ROOT / "洛克人2生产技术域交付_2026-11-25.md"
PDF_PATH = ROOT / "洛克人2生产技术域交付_2026-11-25.pdf"
PACKAGE = ROOT / "知识库P1_20261118/megaman2_production_technical_20261125"
OUT = PACKAGE / "qc"
EVAL_PATH = PACKAGE / "eval_report.json"


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
            suffix = ""
            if sep:
                suffix = "#L" + frag[1:] if frag.startswith("L") else "#" + frag
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
            cls = ' class="major-break"' if level == 2 and title.startswith("3.") else ""
            body.append(f'<h{level} id="h{heading_no}"{cls}>{inline(title)}</h{level}>')
            i += 1
            continue
        if re.fullmatch(r"\s*---+\s*", line):
            body.append("<hr>")
            i += 1
            continue
        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(re.sub(r"^>\s?", "", line))
                i += 1
            body.append("<blockquote>" + "".join(f"<p>{inline(x)}</p>" for x in buf if x.strip()) + "</blockquote>")
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
            ordered = bool(re.match(r"^\s*\d+\.", line))
            tag = "ol" if ordered else "ul"
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
            if nxt.startswith(("#", ">", "```", "|")) or re.fullmatch(r"\s*---+\s*", nxt) or re.match(r"^\s*(?:[-*+]|\d+\.)\s+", nxt):
                break
            buf.append(nxt.strip())
            i += 1
        body.append(f'<p>{inline(" ".join(buf))}</p>')
    return "".join(body)


CSS = """
@page { size: A4; }
* { box-sizing: border-box; }
html { font-size: 10.5pt; }
body { margin: 0; color: #182230; font-family: "Microsoft YaHei", "Meiryo", "Noto Sans CJK SC", Arial, sans-serif; line-height: 1.62; }
h1 { font-size: 23pt; line-height: 1.25; color: #102a43; margin: 0 0 14pt; padding-bottom: 10pt; border-bottom: 3px solid #2f6feb; }
h2 { font-size: 16pt; color: #102a43; margin: 22pt 0 9pt; padding-bottom: 5pt; border-bottom: 1px solid #b8c7d9; break-after: avoid; }
h3 { font-size: 12.5pt; color: #174a7e; margin: 15pt 0 6pt; break-after: avoid; }
h4 { font-size: 11pt; margin: 12pt 0 5pt; break-after: avoid; }
p { margin: 5pt 0 8pt; orphans: 3; widows: 3; }
ul,ol { margin: 4pt 0 9pt 18pt; padding: 0; }
li { margin: 2pt 0; }
blockquote { margin: 10pt 0; padding: 8pt 11pt; background: #eef4ff; border-left: 4px solid #2f6feb; color: #243b53; break-inside: avoid; }
blockquote p { margin: 2pt 0; }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.9em; background: #f1f4f8; color: #7a271a; padding: 0.5pt 2pt; border-radius: 2px; overflow-wrap: anywhere; word-break: break-all; }
a { color: #175cd3; text-decoration: none; overflow-wrap: anywhere; }
strong { color: #102a43; }
hr { border: 0; border-top: 1px solid #cbd5e1; margin: 18pt 0; }
.table-wrap { width: 100%; margin: 8pt 0 12pt; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 8.4pt; line-height: 1.42; }
th,td { border: 1px solid #b8c7d9; padding: 5pt; vertical-align: top; overflow-wrap: anywhere; word-break: break-word; }
th { background: #dce9fb; color: #102a43; font-weight: 700; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; background: #f1f4f8; border: 1px solid #d7dee8; padding: 8pt; line-height: 1.45; break-inside: avoid; }
pre code { padding: 0; background: transparent; color: #243b53; }
.major-break { break-before: page; }
"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    text = MD_PATH.read_text(encoding="utf-8")
    evaluation = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    doc = (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>洛克人2生产技术域交付（2026-11-25）</title>"
        f"<style>{CSS}</style></head><body>{render_markdown(text)}</body></html>"
    )
    html_path = OUT / "report.html"
    html_path.write_text(doc, encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            headless=True,
            args=["--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1200, "height": 1600})
        page.goto(html_path.as_uri(), wait_until="load")
        page.emulate_media(media="print")
        overflow = page.evaluate(
            "() => Array.from(document.querySelectorAll('body *'))"
            ".filter(e => e.scrollWidth > e.clientWidth + 2 && getComputedStyle(e).overflowX === 'visible')"
            ".slice(0,20).map(e => ({tag:e.tagName, cls:e.className, sw:e.scrollWidth, cw:e.clientWidth, text:(e.innerText||'').slice(0,80)}))"
        )
        page.pdf(
            path=str(PDF_PATH),
            format="A4",
            print_background=True,
            display_header_footer=True,
            prefer_css_page_size=True,
            margin={"top": "17mm", "bottom": "16mm", "left": "15mm", "right": "15mm"},
            header_template='<div style="font-size:8px;color:#64748b;width:100%;padding:0 15mm;">洛克人2生产技术域交付 · 2026-11-25</div>',
            footer_template='<div style="font-size:8px;color:#64748b;width:100%;padding:0 15mm;"><span>BM25 生产技术子域 · 非整款游戏知识库</span><span style="float:right;"><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
        )
        browser.close()

    pdf = pymupdf.open(PDF_PATH)
    texts = [p.get_text() for p in pdf]
    all_text = "\n".join(texts)
    compact = re.sub(r"\s+", "", all_text)
    artifacts_page = next((n for n, value in enumerate(texts, 1)
                           if "5.交付物索引" in re.sub(r"\s+", "", value)), None)
    outside = []
    for n, p in enumerate(pdf, 1):
        rect = p.rect
        for block in p.get_text("blocks"):
            x0, y0, x1, y1 = block[:4]
            if x0 < -1 or y0 < -1 or x1 > rect.width + 1 or y1 > rect.height + 1:
                outside.append({"page": n, "bbox": [round(x, 1) for x in (x0, y0, x1, y1)], "text": block[4][:80]})
    pdf_links = [link for p in pdf for link in p.get_links()]
    link_targets = [Path(unquote(link["file"]).partition("#")[0].lstrip("/"))
                    for link in pdf_links if link.get("file")]
    expected_link_count = sum(not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)
                              for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text))
    base_sha = evaluation["indexes"]["base"]["sha256"]
    hybrid_sha = evaluation["indexes"]["hybrid"]["sha256"]
    checks = {
        "pages_positive": len(pdf) > 0,
        "conclusion_present": "一页结论" in compact,
        "scope_boundary_present": "不是整款游戏知识库" in compact
                                  and "PAL/美版/日版ROM等价未验证" in compact,
        "evaluation_present": "32/32" in compact and "14/14" in compact,
        "consumer_present": "crosscheck8/8" in compact and "选题卡8/8" in compact,
        "regression_present": "1551/1551" in compact and "336/336" in compact and "74/74" in compact,
        "detector_regression_present": "晋升器自检" in compact and "22/22" in compact,
        "source_audit_counts_present": "104sources/27packs/211个受支持要素" in compact,
        "base_sha_present": base_sha in compact,
        "hybrid_sha_present": hybrid_sha in compact,
        "base_sha_matches": base_sha == evaluation["production_index_sha256"],
        "all_eight_probes_present": all(f"MM2T{i:02d}" in compact for i in range(1, 9)),
        "artifacts_section_page_found": artifacts_page is not None,
        "no_replacement_char": "\ufffd" not in all_text,
        "no_blank_pages": all(len(t.strip()) > 80 for t in texts),
        "no_outside_blocks": not outside,
        "no_dom_overflow": not overflow,
        "delivery_links_present": len(link_targets) == expected_link_count,
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
    snapshot_pages = sorted({1, max(1, len(pdf) - 1), len(pdf)} | ({artifacts_page} if artifacts_page else set()))
    for n in snapshot_pages:
        pix = pdf[n - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
        pix.save(OUT / f"page_{n:02d}.png")
    report = {
        "pages": len(pdf),
        "artifacts_page": artifacts_page,
        "snapshot_pages": snapshot_pages,
        "check_count": len(checks),
        "all_ok": all(checks.values()),
        "checks": checks,
        "dom_overflow": overflow,
        "outside_blocks": outside,
        "delivery_link_targets": [str(path) for path in link_targets],
        "page_text_lengths": [len(t) for t in texts],
        "pdf_bytes": PDF_PATH.stat().st_size,
        "pdf_sha256": hashlib.sha256(PDF_PATH.read_bytes()).hexdigest(),
        "markdown_sha256": hashlib.sha256(MD_PATH.read_bytes()).hexdigest(),
    }
    (OUT / "render_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    pdf.close()
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
