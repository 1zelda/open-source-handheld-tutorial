from pathlib import Path
import hashlib
import html
import importlib.util
import json
import re
import sys

import pymupdf
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
MD = ROOT / "知识库改进优化指导_2026-11-25_晓月19项玩法证据回绑.md"
PDF = ROOT / "知识库改进优化指导_2026-11-25_晓月19项玩法证据回绑.pdf"
QC = OUT / "report_qc_gameplay_binding_20261125"
PREFLIGHT = OUT / "preflight_fingerprints_gameplay_binding_20261125.json"
OLD_RENDERER = ROOT / "知识库P1_20261118/kb_final_20261125_menu_visual_review/render_qc_menu_visual_review_20261125.py"


def load_renderer():
    spec = importlib.util.spec_from_file_location("previous_markdown_renderer", OLD_RENDERER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    renderer = load_renderer()
    renderer.CSS = renderer.CSS.replace("margin: 18pt 0 8pt;", "margin: 16pt 0 7pt;")
    renderer.CSS = renderer.CSS.replace("padding: 5pt; vertical-align", "padding: 4pt; vertical-align")
    QC.mkdir(parents=True, exist_ok=True)
    text = MD.read_text(encoding="utf-8")
    pre = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    doc = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
           "<title>知识库改进优化指导：晓月圆舞曲19项玩法证据回绑</title>"
           f"<style>{renderer.CSS}</style></head><body>{renderer.render_markdown(text)}</body></html>")
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
        page.pdf(path=str(PDF), format="A4", print_background=True,
                 display_header_footer=True, prefer_css_page_size=True,
                 margin={"top": "17mm", "bottom": "16mm", "left": "15mm", "right": "15mm"},
                 header_template='<div style="font-size:8px;color:#64748b;width:100%;padding:0 15mm;">知识库改进优化指导 · 2026-11-25 晓月19项玩法证据回绑</div>',
                 footer_template='<div style="font-size:8px;color:#64748b;width:100%;padding:0 15mm;"><span>玩法证据回绑独立副本</span><span style="float:right;"><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
        browser.close()
    pdf = pymupdf.open(PDF)
    texts = [page.get_text() for page in pdf]
    all_text = "\n".join(texts)
    compact = re.sub(r"\s+", "", all_text)
    outside = []
    for n, page in enumerate(pdf, 1):
        rect = page.rect
        for block in page.get_text("blocks"):
            x0, y0, x1, y1 = block[:4]
            if x0 < -1 or y0 < -1 or x1 > rect.width + 1 or y1 > rect.height + 1:
                outside.append({"page": n, "bbox": [round(x, 1) for x in (x0, y0, x1, y1)], "text": block[4][:80]})
    case_ids = ["red_soul_4_verify_vs_empty", "red_soul_5_verify_vs_empty", "red_soul_12_verify_vs_empty",
                "red_soul_24_verify_vs_empty", "red_soul_31_verify_vs_empty", "red_soul_37_verify_vs_empty",
                "blue_soul_2_verify_vs_empty", "blue_soul_4_verify_vs_empty", "blue_soul_6_verify_vs_empty",
                "blue_soul_13_verify_vs_empty", "blue_soul_22_verify_vs_empty", "red_soul_35_resource_verify",
                "red_soul_47_resource_verify", "yellow_soul_10_hp_advantage", "yellow_soul_15_hp_advantage",
                "yellow_soul_26_hp_advantage", "yellow_soul_27_hp_advantage", "yellow_soul_28_hp_advantage",
                "yellow_soul_29_hp_advantage"]
    checks = {
        "pages_positive": len(pdf) > 0,
        "conclusion_present": "1.本轮结论" in compact,
        "root_cause_present": "2.根因与修正" in compact,
        "matrix_present": "3.19项逐案矩阵" in compact,
        "evidence_present": "4.固化证据" in compact,
        "boundary_present": "5.资格边界" in compact,
        "audit_present": "6.审计与串行回归" in compact,
        "remaining_present": "7.当前仍未完成项" in compact,
        "fingerprints_present": "8.最终代码与数据指纹" in compact,
        "all_19_cases_present": all(case_id in compact for case_id in case_ids),
        "gameplay_counts_present": "19项" in compact and "95项" in compact and "114项" in compact,
        "copied_counts_present": "519" in compact and "14,958,586" in compact and "460" in compact,
        "source_counts_present": "来源104、包26、要素208/208" in compact,
        "weak_counts_present": "141项" in compact and "菜单95项" in compact,
        "candidate_boundary_present": "local_aria_menu_catalog_20261125" in compact and "candidate" in compact,
        "detector_boundary_present": "detector_verified=false" in compact,
        "platform_boundary_present": "PLATFORM_PROFILES.GBA.verified=false" in compact,
        "human_boundary_present": "human_visual_review=false" in compact,
        "old_delivery_protection_present": "1301/1301" in compact,
        "project_gate_present": "1551/1551" in compact,
        "kb_gate_present": "336/336" in compact,
        "cross_gate_present": "33/33" in compact,
        "sources_gate_present": "74/74" in compact,
        "topic_gate_present": "166/166" in compact,
        "index_sha_present": pre["data"]["index"]["sha256"] in compact,
        "registry_sha_present": pre["data"]["source_registry"]["sha256"] in compact,
        "menu_sha_present": pre["data"]["menu_catalog"]["sha256"] in compact,
        "corpus_sha_present": pre["data"]["corpus_map"]["sha256"] in compact,
        "binding_sha_present": pre["data"]["gameplay_binding"]["sha256"] in compact,
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
    for n in sorted({1, max(1, len(pdf) - 1), len(pdf)}):
        pdf[n - 1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(QC / f"page_{n:02d}.png")
    report = {"pages": len(pdf), "snapshot_pages": sorted({1, max(1, len(pdf) - 1), len(pdf)}),
              "check_count": len(checks), "checks": checks, "dom_overflow": overflow,
              "outside_blocks": outside, "page_text_lengths": [len(value) for value in texts],
              "markdown_sha256": hashlib.sha256(MD.read_bytes()).hexdigest(),
              "pdf_bytes": PDF.stat().st_size,
              "pdf_sha256": hashlib.sha256(PDF.read_bytes()).hexdigest()}
    (QC / "render_qa.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pdf.close()
    print(json.dumps({"pages": report["pages"], "checks": report["check_count"],
                      "passed": sum(checks.values()), "pdf_sha256": report["pdf_sha256"],
                      "failed": [key for key, value in checks.items() if not value]}, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
