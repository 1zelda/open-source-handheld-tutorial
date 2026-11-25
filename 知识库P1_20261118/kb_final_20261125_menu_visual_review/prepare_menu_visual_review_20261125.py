from pathlib import Path
import hashlib
import json
import textwrap
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
ASSETS = OUT / "review_assets"
OCR = ASSETS / "ocr"
SHEETS = ASSETS / "sheets"
PACK = ROOT / "_工具脚本/taspipe/游戏包/gba_aria_of_sorrow_souls.menu_catalog.json"
EVIDENCE = ROOT / "_工具脚本/taspipe/游戏包/证据/晓月圆舞曲/menu_catalog_nav_full_20261125"
NAMES = EVIDENCE / "menu_names_observed.json"
EFFECTS = EVIDENCE / "menu_effects_observed.json"
EFFECT_REGION = (45, 118, 238, 153)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def font(size):
    for name in ("msyh.ttc", "segoeui.ttf", "arial.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def ocr_asset(image, path, scale, pad=24):
    image = ImageOps.autocontrast(image.convert("L"))
    image = ImageOps.invert(image)
    image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
    canvas = Image.new("L", (image.width + pad * 2, image.height + pad * 2), 255)
    canvas.paste(image, (pad, pad))
    canvas.save(path)


def main():
    OCR.mkdir(parents=True, exist_ok=True)
    SHEETS.mkdir(parents=True, exist_ok=True)
    pack = json.loads(PACK.read_text(encoding="utf-8"))
    names = json.loads(NAMES.read_text(encoding="utf-8"))["names"]
    effects = json.loads(EFFECTS.read_text(encoding="utf-8"))["effects"]
    rows = []
    for element in pack["elements"]:
        group, item_id = element["group"], element["id"]
        stem = f"{group}_{item_id:03d}"
        shot_path = ROOT / element["evidence"]["shot"]["path"]
        identity_path = ROOT / element["evidence"]["identity"]["path"]
        state_path = ROOT / element["evidence"]["state"]["path"]
        checks = {
            "shot_hash": sha(shot_path) == element["evidence"]["shot"]["sha256"],
            "identity_hash": sha(identity_path) == element["evidence"]["identity"]["sha256"],
            "state_hash": sha(state_path) == element["evidence"]["state"]["sha256"],
            "observed_name": element["name_zh"] == names[group][item_id - 1],
            "observed_effect": element["effect_text"] == effects[group][item_id - 1],
            "readback": element["capture"]["readback"] == item_id,
            "gameplay_false": element["gameplay_verified"] is False,
            "detector_false": element["detector_verified"] is False,
        }
        with Image.open(shot_path) as source:
            shot = source.convert("RGB")
            region = next(g["identity_region"] for g in pack["groups"] if g["group"] == group)
            fresh_identity = shot.crop(tuple(region))
            with Image.open(identity_path) as identity:
                checks["identity_crop_exact"] = ImageChops.difference(fresh_identity, identity.convert("RGB")).getbbox() is None
            effect = shot.crop(EFFECT_REGION)
            checks["effect_nonblank"] = effect.convert("L").getextrema()[1] - effect.convert("L").getextrema()[0] > 32
            name_ocr = OCR / f"{stem}_name.png"
            effect_ocr = OCR / f"{stem}_effect.png"
            ocr_asset(fresh_identity, name_ocr, 8)
            ocr_asset(effect, effect_ocr, 4)
        row = {
            "element_id": element["element_id"], "group": group, "id": item_id,
            "name_zh": element["name_zh"], "effect_text": element["effect_text"],
            "checks": checks, "all_preparation_checks": all(checks.values()),
            "shot": str(shot_path), "identity": str(identity_path), "state": str(state_path),
            "name_ocr_asset": str(name_ocr), "effect_ocr_asset": str(effect_ocr),
        }
        rows.append(row)
    sheet_paths = []
    for start in range(0, len(rows), 6):
        batch = rows[start:start + 6]
        sheet = Image.new("RGB", (2000, 1800), "#111827")
        draw = ImageDraw.Draw(sheet)
        title_font, label_font, body_font = font(28), font(22), font(20)
        for index, row in enumerate(batch):
            x, y = index % 2 * 1000, index // 2 * 600
            draw.rectangle((x + 8, y + 8, x + 992, y + 592), outline="#64748b", width=2)
            draw.text((x + 18, y + 16), f"{row['element_id']}  {row['group_label'] if 'group_label' in row else row['group']}  ID={row['id']:03d}", font=title_font, fill="white")
            draw.text((x + 18, y + 52), "完整菜单截图（2x）", font=label_font, fill="#93c5fd")
            with Image.open(row["shot"]) as image:
                frame = image.convert("RGB").resize((480, 320), Image.Resampling.NEAREST)
            sheet.paste(frame, (x + 18, y + 84))
            draw.text((x + 520, y + 52), "名称区（8x，OCR用反转图）", font=label_font, fill="#93c5fd")
            with Image.open(row["name_ocr_asset"]) as image:
                name_image = image.convert("RGB")
                if name_image.width > 460:
                    name_image.thumbnail((460, 220), Image.Resampling.NEAREST)
            sheet.paste(name_image, (x + 520, y + 84))
            draw.text((x + 520, y + 320), "效果区（4x，OCR用反转图）", font=label_font, fill="#93c5fd")
            with Image.open(row["effect_ocr_asset"]) as image:
                effect_image = image.convert("RGB")
                if effect_image.width > 460:
                    effect_image.thumbnail((460, 170), Image.Resampling.NEAREST)
            sheet.paste(effect_image, (x + 520, y + 352))
            draw.text((x + 18, y + 424), f"登记名称：{row['name_zh']}", font=body_font, fill="#fde68a")
            lines = textwrap.wrap(f"登记效果：{row['effect_text']}", width=46) or [""]
            for line_index, line in enumerate(lines[:3]):
                draw.text((x + 18, y + 458 + line_index * 28), line, font=body_font, fill="#fde68a")
            draw.text((x + 18, y + 556), f"冻结哈希/裁切/观察一致性：{'通过' if row['all_preparation_checks'] else '失败'}", font=label_font,
                      fill="#86efac" if row["all_preparation_checks"] else "#fca5a5")
        path = SHEETS / f"menu_review_sheet_{start // 6 + 1:02d}.png"
        sheet.save(path)
        sheet_paths.append(str(path))
    result = {
        "schema": "aria_menu_visual_review_preparation/1.0",
        "prepared_on": "2026-11-25",
        "scope": "冻结截图的二次视觉复核准备；不加载ROM，不修改候选资格。",
        "elements": len(rows), "preparation_pass": sum(row["all_preparation_checks"] for row in rows),
        "preparation_fail": sum(not row["all_preparation_checks"] for row in rows),
        "effect_region": list(EFFECT_REGION), "sheets": sheet_paths,
        "ocr_assets": len(list(OCR.glob("*.png"))), "rows": rows,
    }
    (OUT / "visual_review_preparation_20261125.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("elements", "preparation_pass", "preparation_fail", "ocr_assets")}, ensure_ascii=False))
    if result["preparation_fail"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
