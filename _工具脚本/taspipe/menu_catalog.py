"""配置驱动的真实菜单条目采集；截图与 RAM 回读共同落证。"""
import argparse
import concurrent.futures
import hashlib
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import statejump as SJ
from . import state_registry as SR
from .parallel import EmulatorSlots
from .schema import SchemaError

SCHEMA_VERSION = "menu_catalog/1.1"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_macro(steps, gap=16, tail=40):
    if not isinstance(steps, list) or not steps or any(not isinstance(x, str) or not x for x in steps):
        raise SchemaError("menu_steps 必须是非空字符串列表")
    if type(gap) is not int or gap < 0 or type(tail) is not int or tail < 0:
        raise SchemaError("key_gap/tail 必须为非负整数")
    tokens = [""]
    for step in steps:
        tokens.extend([""] * gap)
        tokens.append(step)
    tokens.extend([""] * tail)
    return ",".join(tokens)


def selection_macro(group, value, domain):
    navigate = group.get("navigate")
    if navigate is None:
        return build_macro(group["menu_steps"], int(group.get("key_gap", 16)), int(group.get("tail", 40))), [
            {"addr": group["slot_addr"], "value": value, "domain": domain}
        ]
    offset = value - int(navigate["start_id"])
    if offset < 0:
        raise SchemaError(f"{group['id']} ID={value} 必须不小于导航起点")
    row, column = divmod(offset, int(navigate["columns"]))
    steps = list(group["menu_steps"])
    steps.extend([navigate["row_step"]] * row)
    steps.extend([navigate["column_step"]] * column)
    steps.append(navigate["confirm"])
    return build_macro(steps, int(group.get("key_gap", 16)), int(group.get("tail", 40))), []


def identity_crop(shot, region, path):
    with Image.open(shot) as image:
        if image.width <= region[2] or image.height <= region[3]:
            raise SchemaError(f"身份区域超出截图尺寸: {region}")
        image.crop(tuple(region)).save(path)
    return sha256(path)


def load_config(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema_version") != SCHEMA_VERSION:
        raise SchemaError(f"schema_version 必须为 {SCHEMA_VERSION}")
    profile = doc.get("profile") or {}
    for key in ("rom", "rom_sha1", "bizhawk", "core", "system", "domain"):
        if not profile.get(key):
            raise SchemaError(f"profile.{key} 必填")
    rom, bizhawk = Path(profile["rom"]), Path(profile["bizhawk"])
    if not rom.is_file() or not (bizhawk / "EmuHawk.exe").is_file():
        raise SchemaError("ROM 或 BizHawk 不存在")
    if SJ.sha1_file(rom).upper() != str(profile["rom_sha1"]).upper():
        raise SchemaError("ROM SHA1 不符")
    if not doc.get("game_id"):
        raise SchemaError("game_id 必填")
    if not doc.get("base_state"):
        raise SchemaError("base_state 必填")
    groups = doc.get("groups")
    if not isinstance(groups, list) or not groups:
        raise SchemaError("groups 必须是非空列表")
    ids = set()
    for group in groups:
        gid = group.get("id")
        if not isinstance(gid, str) or not gid or gid in ids:
            raise SchemaError("group.id 必须唯一且非空")
        ids.add(gid)
        readback = group.get("slot_readback", True)
        if not isinstance(readback, bool):
            raise SchemaError(f"{gid}.slot_readback 必须为布尔值")
        slot_addr = group.get("slot_addr")
        if readback and (type(slot_addr) is not int or slot_addr < 0):
            raise SchemaError(f"{gid}.slot_addr 必须为非负整数")
        if not readback and slot_addr is not None and (type(slot_addr) is not int or slot_addr < 0):
            raise SchemaError(f"{gid}.slot_addr 为 null 或非负整数")
        base_patches = group.get("base_patches") or []
        if not isinstance(base_patches, list):
            raise SchemaError(f"{gid}.base_patches 必须为列表")
        for patch in base_patches:
            if (not isinstance(patch, dict) or type(patch.get("addr")) is not int or patch["addr"] < 0
                    or type(patch.get("value")) is not int or not 0 <= patch["value"] <= 255):
                raise SchemaError(f"{gid}.base_patches 每项必须含非负 addr 与 0..255 value")
        if type(group.get("count")) is not int or not 1 <= group["count"] <= 255:
            raise SchemaError(f"{gid}.count 必须为 1..255 整数")
        region = group.get("identity_region")
        if (not isinstance(region, list) or len(region) != 4
                or any(type(value) is not int or value < 0 for value in region)
                or region[0] >= region[2] or region[1] >= region[3]):
            raise SchemaError(f"{gid}.identity_region 必须为 [x0,y0,x1,y1]")
        build_macro(group.get("menu_steps"), int(group.get("key_gap", 16)), int(group.get("tail", 40)))
        navigate = group.get("navigate")
        if navigate is not None:
            if type(navigate.get("columns")) is not int or navigate["columns"] < 1:
                raise SchemaError(f"{gid}.navigate.columns 必须为正整数")
            if type(navigate.get("start_id")) is not int or not 0 <= navigate["start_id"] < 255:
                raise SchemaError(f"{gid}.navigate.start_id 必须为 0..254")
            if navigate["start_id"] + group["count"] - 1 > 255:
                raise SchemaError(f"{gid} 导航 ID 范围超出 0..255")
            for key in ("row_step", "column_step", "confirm"):
                if not isinstance(navigate.get(key), str) or not navigate[key]:
                    raise SchemaError(f"{gid}.navigate.{key} 必须为非空字符串")
        elif slot_addr is None:
            raise SchemaError(f"{gid} 非导航模式必须提供 slot_addr")
    workers = doc.get("workers", 1)
    if type(workers) is not int or workers < 1:
        raise SchemaError("workers 必须为正整数")
    return doc


def base_state_path(config):
    profile = config["profile"]
    ref = profile.get("state_package")
    if not ref:
        path = Path(str(profile["base_state_path"]))
        if not path.is_file():
            raise SchemaError("base_state_path 不存在")
        return path
    pkg = SR.load(ref["game_id"], ref["profile_id"], ref["revision"])
    if pkg["status"] not in SR.CONSUMABLE:
        raise SchemaError("状态包未达 state_verified，不可用于菜单采集")
    for key in ("rom_sha1", "core", "system", "domain"):
        if str(pkg["profile"].get(key, "")).upper() != str(profile[key]).upper():
            raise SchemaError(f"状态包 profile.{key} 与采集配置不符")
    return SR.resolve_state(ref["game_id"], ref["profile_id"], ref["revision"],
                            config["base_state"], require_status=SR.CONSUMABLE)


def _font(size):
    for name in ("msyh.ttc", "segoeui.ttf", "arial.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def contact_sheet(rows, path):
    cols, cw, ch = 4, 480, 326
    image = Image.new("RGB", (cw * cols, ch * ((len(rows) + cols - 1) // cols)), "#10141c")
    draw = ImageDraw.Draw(image)
    font = _font(16)
    for index, row in enumerate(rows):
        if not row.get("shot") or not Path(row["shot"]).is_file():
            continue
        frame = Image.open(row["shot"]).convert("RGB").resize((480, 320), Image.Resampling.NEAREST)
        x, y = index % cols * cw, index // cols * ch
        image.paste(frame, (x, y + 22))
        draw.text((x + 6, y + 3), f"{row['group_id']} ID={row['id']:03d} readback={row['readback']}", font=font, fill="white")
    image.save(path)


def capture_group(config, group, out_root, work_root):
    profile = config["profile"]
    gid = group["id"]
    group_out = out_root / gid
    group_out.mkdir(parents=True, exist_ok=True)
    slots = EmulatorSlots(workers=1, root=work_root / gid, system=profile["system"], core=profile["core"])
    rows = []
    with slots.lease(profile["bizhawk"], system=profile["system"], core=profile["core"]) as slot:
        with SJ.StateSession(profile["rom"], str(slot.path), core=profile["core"],
                             system=profile["system"], work=str(slot.work / "catalog")) as sess:
            base = sess.use_state(base_state_path(config), name="base")
            base_shot_ascii = Path(sess.work) / "catalog" / "base.png"
            sess.attempt(base, spec="-", shot=str(base_shot_ascii))
            base_shot = group_out / "base_gameplay.png"
            shutil.copyfile(base_shot_ascii, base_shot)
            macro_frames = 0
            for value in range(1, int(group["count"]) + 1):
                row = {"group_id": gid, "id": value, "slot_addr": group.get("slot_addr")}
                try:
                    stem = f"{gid}_{value:03d}"
                    shot_ascii = Path(sess.work) / "catalog" / f"{stem}.png"
                    state_ascii = Path(sess.work) / "catalog" / f"{stem}.state"
                    macro, patches = selection_macro(group, value, profile["domain"])
                    macro_frames = len(macro.split(","))
                    all_patches = [{**patch, "domain": patch.get("domain", profile["domain"])}
                                   for patch in list(group.get("base_patches") or []) + patches]
                    sess.attempt(base, spec=macro, shot=str(shot_ascii), save=str(state_ascii), patches=all_patches)
                    got = sess.read(group["slot_addr"], profile["domain"]) if group.get("slot_readback", True) else None
                    shot = group_out / f"{stem}.png"
                    state = group_out / f"{stem}.state"
                    identity = group_out / f"{stem}_identity.png"
                    shutil.copyfile(shot_ascii, shot)
                    shutil.copyfile(state_ascii, state)
                    shot_sha, menu_differs = sha256(shot), sha256(shot) != sha256(base_shot)
                    identity_sha = identity_crop(shot, group["identity_region"], identity)
                    if group.get("slot_readback", True):
                        status = "captured" if got == value and menu_differs else (
                            "readback_mismatch" if got != value else "menu_not_reached")
                    else:
                        status = "captured" if menu_differs else "menu_not_reached"
                    row.update(status=status, readback=got, shot=str(shot), state=str(state),
                               shot_sha256=shot_sha, state_sha256=sha256(state),
                               identity=str(identity), identity_sha256=identity_sha,
                               menu_differs_from_gameplay=menu_differs)
                except Exception as exc:
                    row.update(status="error", error=f"{type(exc).__name__}: {exc}")
                rows.append(row)
            final = sess.save("end")
            actual_core = SJ.saved_core_type(final)
    return {"group_id": gid, "label": group.get("label", gid), "count": group["count"],
            "menu_steps": group["menu_steps"], "macro_frames": macro_frames,
            "selection_mode": "navigate" if group.get("navigate") else "patch",
            "identity_region": group["identity_region"],
            "actual_core": actual_core, "bizhawk": str(slot.path), "cases": rows,
            "contact_sheet": str(out_root / f"{gid}_contact_sheet.png")}


def run(config_path, out_dir, work_root, force=False):
    config = load_config(config_path)
    out_root, work_root = Path(out_dir), Path(work_root)
    out_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    config_sha = sha256(config_path)
    report_path = out_root / "report.json"
    if report_path.is_file() and not force:
        old = json.loads(report_path.read_text(encoding="utf-8"))
        rows = [row for group in old.get("groups", []) for row in group.get("cases", [])]
        expected_total = sum(int(group["count"]) for group in config["groups"])
        if (old.get("schema_version") == SCHEMA_VERSION and old.get("status") == "complete"
                and old.get("config_sha256") == config_sha and old.get("expected_total") == expected_total
                and old.get("unique_menu_shots") == expected_total
                and old.get("unique_identity_shots") == expected_total and old.get("core_ok") is True
                and all(Path(row[key]).is_file() for row in rows for key in ("shot", "state", "identity"))):
            return {**old, "reused": True}
    groups = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(config.get("workers", 1))) as pool:
        futures = [(group["id"], pool.submit(capture_group, config, group, out_root, work_root))
                   for group in config["groups"]]
        for gid, future in futures:
            try:
                groups.append(future.result())
            except Exception as exc:
                groups.append({"group_id": gid, "count": 0, "cases": [],
                               "error": f"{type(exc).__name__}: {exc}",
                               "contact_sheet": str(out_root / f"{gid}_contact_sheet.png")})
    for group in groups:
        if group["cases"]:
            contact_sheet(group["cases"], group["contact_sheet"])
    rows = [row for group in groups for row in group["cases"]]
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    expected_total = sum(int(group["count"]) for group in config["groups"])
    unique_shots = len({row["shot_sha256"] for row in rows if row.get("shot_sha256")})
    unique_identity_shots = len({row["identity_sha256"] for row in rows if row.get("identity_sha256")})
    core_ok = all(group.get("actual_core") == SJ.GBA_MGBA_CORE_TYPE for group in groups)
    complete = (len(rows) == expected_total and counts == {"captured": expected_total}
                and unique_shots == expected_total and unique_identity_shots == expected_total and core_ok
                and not any(group.get("error") for group in groups))
    report = {"schema_version": SCHEMA_VERSION, "game_id": config["game_id"],
              "config": str(Path(config_path)), "config_sha256": config_sha,
              "out": str(out_root), "status": "complete" if complete else "incomplete",
              "total": len(rows), "expected_total": expected_total, "counts": counts,
              "unique_menu_shots": unique_shots, "unique_identity_shots": unique_identity_shots,
              "core_ok": core_ok, "groups": groups}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    report = run(args.config, args.out, args.work_root, args.force)
    print(json.dumps({k: report[k] for k in ("status", "total", "counts", "unique_menu_shots",
                                                "unique_identity_shots", "reused") if k in report},
                     ensure_ascii=False, indent=2))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
