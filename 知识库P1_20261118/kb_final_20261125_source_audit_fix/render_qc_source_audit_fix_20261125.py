from pathlib import Path
import hashlib
import html
import json
import re

import pymupdf
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path("F:/开源掌机教程")
MD_PATH = ROOT / "知识库改进优化指导_2026-11-25_来源审计修正回填.md"
PDF_PATH = ROOT / "知识库改进优化指导_2026-11-25_来源审计修正回填.pdf"
OUT = ROOT / "知识库P1_20261118/kb_final_20261125_source_audit_fix"
QC = OUT / "report_qc_source_audit_fix_20261125"
MANIFEST_PATH = OUT / "final_manifest_source_audit_fix_20261125.json"


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
            body.append(f'<h{level} id="h{heading_no}">{inline(title)}</h{level}>')
            i += 1
            continue
        if re.fullmatch(r"\s*---+\s*", line):
            body.append("<hr>")
            i += 1
            continue
        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].startswith(">"):
                buf.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            body.append("<blockquote>" + "".join(f"<p>{inline(x)}</p>" for x in buf if x.strip()) + "</blockquote>")
            continue
        if line.lstrip().startswith("|") and i + 1 < len(lines) and re.fullmatch(
                r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*", lines[i + 1]):
            def cells(s):
                return [x.strip() for x in s.strip().strip("|").split("|")]
            headers = cells(line)
            i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            body.append('<div class="table-wrap"><table><thead><tr>' +
                        "".join(f"<th>{inline(x)}</th>" for x in headers) + "</tr></thead><tbody>")
            for row in rows:
                body.append("<tr>" + "".join(f"<td>{inline(x)}</td>" for x in row) + "</tr>")
            body.append("</tbody></table></div>")
            continue
        if re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$", line):
            tag = "ol" if re.match(r"^\s*\d+\.", line) else "ul"
            items = []
            while i < len(lines):
                found = re.match(r"^\s*(?:[-*+]|\d+\.)\s+(.+)$", lines[i])
                if not found:
                    break
                items.append(f"<li>{inline(found.group(1))}</li>")
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
        body.append(f"<p>{inline(' '.join(buf))}</p>")
    return "".join(body)


CSS = """
@page { size: A4; }
* { box-sizing: border-box; }
html { font-size: 9.5pt; }
body { margin: 0; color: #182230; font-family: "Microsoft YaHei", "Meiryo", "Noto Sans CJK SC", Arial, sans-serif; line-height: 1.48; }
h1 { font-size: 22pt; line-height: 1.25; color: #102a43; margin: 0 0 12pt; padding-bottom: 9pt; border-bottom: 3px solid #2f6feb; }
h2 { font-size: 15pt; color: #102a43; margin: 18pt 0 8pt; padding-bottom: 4pt; border-bottom: 1px solid #b8c7d9; break-after: avoid; }
h3 { font-size: 12.5pt; color: #174a7e; margin: 15pt 0 6pt; break-after: avoid; }
p { margin: 5pt 0 8pt; orphans: 3; widows: 3; }
ul,ol { margin: 4pt 0 9pt 18pt; padding: 0; }
li { margin: 2pt 0; }
blockquote { margin: 10pt 0; padding: 8pt 11pt; background: #eef4ff; border-left: 4px solid #2f6feb; color: #243b53; break-inside: avoid; }
blockquote p { margin: 2pt 0; }
code { font-family: Consolas, "Courier New", monospace; font-size: 0.9em; background: #f1f4f8; color: #7a271a; padding: 0.5pt 2pt; border-radius: 2px; overflow-wrap: anywhere; word-break: break-all; }
pre { margin: 8pt 0 11pt; padding: 8pt 10pt; background: #f5f7fa; border: 1px solid #d9e2ec; border-radius: 4px; white-space: pre-wrap; overflow-wrap: anywhere; break-inside: avoid; }
pre code { background: transparent; color: #243b53; padding: 0; word-break: normal; }
a { color: #175cd3; text-decoration: none; overflow-wrap: anywhere; }
strong { color: #102a43; }
.table-wrap { width: 100%; margin: 8pt 0 12pt; }
table { width: 100%; border-collapse: collapse; table-layout: fixed; font-size: 8pt; line-height: 1.38; }
th,td { border: 1px solid #b8c7d9; padding: 5pt; vertical-align: top; overflow-wrap: anywhere; word-break: break-word; }
th { background: #dce9fb; color: #102a43; font-weight: 700; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
"""


def main():
    QC.mkdir(parents=True, exist_ok=True)
    text = MD_PATH.read_text(encoding="utf-8")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    doc = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
           "<title>知识库改进优化指导（2026-11-25）来源审计修正回填</title>"
           f"<style>{CSS}</style></head><body>{render_markdown(text)}</body></html>")
    html_path = QC / "report.html"
    html_path.write_text(doc, encoding="utf-8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
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
                 header_template='<div style="font-size:8px;color:#64748b;width:100%;padding:0 15mm;">知识库改进优化指导 · 2026-11-25 来源审计修正回填</div>',
                 footer_template='<div style="font-size:8px;color:#64748b;width:100%;padding:0 15mm;"><span>来源审计独立副本</span><span style="float:right;"><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
        browser.close()
    pdf = pymupdf.open(PDF_PATH)
    texts = [page.get_text() for page in pdf]
    all_text = "\n".join(texts)
    compact = re.sub(r"\s+", "", all_text)
    source_page = next((n for n, value in enumerate(texts, 1)
                        if "2.来源事实核对" in re.sub(r"\s+", "", value)), None)
    outside = []
    for n, page in enumerate(pdf, 1):
        rect = page.rect
        for block in page.get_text("blocks"):
            x0, y0, x1, y1 = block[:4]
            if x0 < -1 or y0 < -1 or x1 > rect.width + 1 or y1 > rect.height + 1:
                outside.append({"page": n, "bbox": [round(x, 1) for x in (x0, y0, x1, y1)], "text": block[4][:80]})
    checks = {
        "pages_positive": len(pdf) > 0,
        "source_section_present": "2.来源事实核对" in compact,
        "four_arm_section_present": "7.四臂逐题审计" in compact,
        "dense_section_present": "9.未批准稠密层" in compact,
        "final_fingerprint_section_present": "15.最终代码与数据指纹" in compact,
        "base_sha_present": manifest["index"]["sha256"] in compact,
        "hybrid_sha_present": manifest["hybrid_probe_index"]["sha256"] in compact,
        "code_sha_present": manifest["code"]["kb_provenance"]["sha256"] in compact,
        "gates_sha_present": manifest["code"]["kb_selftest_gates"]["sha256"] in compact,
        "sources_code_sha_present": manifest["code"]["sources_audit"]["sha256"] in compact,
        "sources_gates_sha_present": manifest["code"]["sources_selftest_gates"]["sha256"] in compact,
        "project_gate_present": f"{manifest['gates']['project_selftest']['passed']}/{manifest['gates']['project_selftest']['total']}" in compact,
        "kb_gate_present": f"{manifest['gates']['kb_selftest']['passed']}/{manifest['gates']['kb_selftest']['total']}" in compact,
        "cross_gate_present": f"{manifest['gates']['cross_platform_selftest']['passed']}/{manifest['gates']['cross_platform_selftest']['total']}" in compact,
        "sources_gate_present": f"{manifest['gates']['sources_selftest']['passed']}/{manifest['gates']['sources_selftest']['total']}" in compact,
        "topic_gate_present": f"{manifest['gates']['topic_selftest']['passed']}/{manifest['gates']['topic_selftest']['total']}" in compact,
        "strict_grade_present": "21/26" in compact,
        "x23_conflict_present": "frozen_annotation_conflict" in compact and "insufficient_source" in compact,
        "q18_separated": "两源并不一致" in compact,
        "sources_audit_disclosed": "pass8/fail0/inconclusive1" in compact and "evidence_report" in compact,
        "manifest_matches_index": hashlib.sha256(Path(manifest["index"]["path"]).read_bytes()).hexdigest() == manifest["index"]["sha256"],
        "manifest_matches_hybrid": hashlib.sha256(Path(manifest["hybrid_probe_index"]["path"]).read_bytes()).hexdigest() == manifest["hybrid_probe_index"]["sha256"],
        "no_replacement_char": "\ufffd" not in all_text,
        "no_blank_pages": all(len(value.strip()) > 80 for value in texts),
        "no_outside_blocks": not outside,
        "no_dom_overflow": not overflow,
    }
    thumbs = []
    for n, page in enumerate(pdf, 1):
        pix = page.get_pixmap(matrix=pymupdf.Matrix(0.75, 0.75), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        canvas = Image.new("RGB", (image.width + 8, image.height + 28), "white")
        canvas.paste(image, (4, 24))
        ImageDraw.Draw(canvas).text((8, 5), f"Page {n}", fill="black")
        thumbs.append(canvas)
    cols = 3
    rows = (len(thumbs) + cols - 1) // cols
    cw = max(image.width for image in thumbs)
    ch = max(image.height for image in thumbs)
    sheet = Image.new("RGB", (cols * cw, rows * ch), (220, 225, 230))
    for n, image in enumerate(thumbs):
        sheet.paste(image, ((n % cols) * cw, (n // cols) * ch))
    sheet.save(QC / "contact_sheet.png")
    for stale in QC.glob("page_*.png"):
        stale.unlink()
    snapshots = sorted({1, max(1, len(pdf) - 1), len(pdf)} | ({source_page} if source_page else set()))
    for n in snapshots:
        pdf[n - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(QC / f"page_{n:02d}.png")
    report = {"pages": len(pdf), "source_section_page": source_page, "snapshot_pages": snapshots,
              "check_count": len(checks), "checks": checks, "dom_overflow": overflow,
              "outside_blocks": outside, "page_text_lengths": [len(value) for value in texts],
              "pdf_bytes": PDF_PATH.stat().st_size,
              "pdf_sha256": hashlib.sha256(PDF_PATH.read_bytes()).hexdigest()}
    (QC / "render_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    pdf.close()
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
