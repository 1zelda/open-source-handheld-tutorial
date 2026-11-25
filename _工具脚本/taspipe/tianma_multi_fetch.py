# -*- coding: utf-8 -*-
"""天马6T网盘（OpenList 代理）全平台名作 ROM + 封面自动检索、拉取与双口径 SHA-1 校验器。

直接复用 _工具脚本/netdisk_upload.py 与 tianma_fetch.py 的已验证 OpenList 通道：
  * 严守《测试问题与闸门说明书.md》§8 / §17 / §18：走 OpenList 服务端代理 (/d + sign)，不裸抓夸克直链；
  * 自动扫描 /quark-tuiuw33s/天马6t合集/750A218G 下的全平台目录（FC-HD、SFC、GBA、MD、PS1、街机等）；
  * 对 NES ROM 同时计算「整文件 SHA-1」与「去 16 字节 iNES 头 SHA-1」，自动对齐 TASVideos 出版物要求；
  * 自动拦截已知的 2 个《洛克人 1》异常坏 ROM（d8b8c5e2... / 2f883815...），确保拉下来的 ROM 可进真实 Gameplay。

运行方式（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.tianma_multi_fetch list-dirs
  py -3 -u -m taspipe.tianma_multi_fetch pull --query "Mega Man" --platform NES
  py -3 -u -m taspipe.tianma_multi_fetch pull-pack-roms
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT_ROOT = HERE.parent
PROJECT_ROOT = SCRIPT_ROOT.parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

TIANMA_BASE = "/quark-tuiuw33s/天马6t合集/750A218G"
TAS_LIB = PROJECT_ROOT / "04-游戏资源库" / "TAS输入录像库"
ROMS_VERIFY = TAS_LIB / "roms_verify"
COVERS_DIR = TAS_LIB / "covers"

KNOWN_BAD_MM1_SHA1 = {
    "d8b8c5e2ee76f2ec1820123bb9f8c70f5e603923",
    "2f88381557339a14c20428455f6991c1eb902c99",
}

# 天马合集子目录名 -> 标准平台码与 ROM 扩展名映射
PLATFORM_DIR_CANDIDATES = {
    "NES": {
        "dirs": ["FC-HD", "FC", "NES", "Famicom"],
        "exts": (".nes", ".unf", ".fds"),
    },
    "SNES": {
        "dirs": ["SFC", "SNES", "SFC-HD", "Super Famicom"],
        "exts": (".sfc", ".smc"),
    },
    "GBA": {
        "dirs": ["GBA", "GBA-HD", "Game Boy Advance"],
        "exts": (".gba",),
    },
    "GB": {
        "dirs": ["GB", "GBC", "Game Boy"],
        "exts": (".gb", ".gbc"),
    },
    "MD": {
        "dirs": ["MD", "MD-HD", "Genesis", "Mega Drive"],
        "exts": (".md", ".gen", ".bin", ".smd"),
    },
    "PS1": {
        "dirs": ["PS1", "PSX", "PlayStation"],
        "exts": (".chd", ".pbp", ".cue", ".iso", ".bin"),
    },
    "ARCADE_FBNEO": {
        "dirs": ["FBNeo", "ARCADE", "MAME", "NeoGeo", "CPS1", "CPS2", "街机"],
        "exts": (".zip",),
    },
}


def _auth():
    import netdisk_upload as nu
    a = nu.Auth()
    a.token()
    return a, nu


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _sha1_Pair(data: bytes, ext: str) -> tuple[str, str]:
    """返回 (全文件SHA1大写, 去iNES头SHA1大写)。"""
    full = hashlib.sha1(data).hexdigest().upper()
    if ext.lower() == ".nes" and len(data) > 16 and data[:4] == b"NES\x1a":
        hdrless = hashlib.sha1(data[16:]).hexdigest().upper()
    else:
        hdrless = full
    return full, hdrless


def fetch_file(a, nu_mod, remote_path: str, local_path: Path) -> Path:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if local_path.is_file() and local_path.stat().st_size > 0:
        return local_path
    d = a.api("/api/fs/get", {"path": remote_path})
    if d.get("code") != 200:
        raise RuntimeError(f"OpenList fs/get 失败 {remote_path}: {d.get('message')}")
    x = d.get("data") or {}
    url = (
        nu_mod.BASE
        + "/d"
        + urllib.parse.quote(remote_path)
        + "?sign="
        + urllib.parse.quote(x.get("sign") or "")
    )
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=300) as r, open(local_path, "wb") as f:
        f.write(r.read())
    print(f"[已下载] {remote_path} -> {local_path} ({local_path.stat().st_size} B)")
    return local_path


def list_remote_dir(a, remote_dir: str, per_page: int = 1000) -> list[dict]:
    d = a.api("/api/fs/list", {"path": remote_dir, "page": 1, "per_page": per_page})
    if d.get("code") != 200:
        return []
    return (d.get("data") or {}).get("content") or []


def discover_platform_dirs(a, base: str = TIANMA_BASE) -> dict[str, list[str]]:
    """探测网盘天马根目录下真实存在的平台子目录。"""
    top = list_remote_dir(a, base)
    dir_names = {item["name"]: f"{base}/{item['name']}" for item in top if item.get("is_dir")}
    out = {}
    for plat, spec in PLATFORM_DIR_CANDIDATES.items():
        matched = []
        for cand in spec["dirs"]:
            for actual_name, full_path in dir_names.items():
                if actual_name.lower() == cand.lower() or cand.lower() in actual_name.lower():
                    if full_path not in matched:
                        matched.append(full_path)
        if matched:
            out[plat] = matched
    return out


def search_and_pull(query: str, platform_filter: str = "ALL", max_Pull: int = 3, base: str = TIANMA_BASE) -> dict:
    """在天马网盘中按游戏名关键词搜索对应平台 ROM + 封面，解压并校验 SHA-1 后落盘到 roms_verify/<plat>/。"""
    a, nu_mod = _auth()
    plat_dirs = discover_platform_dirs(a, base=base)
    q_low = query.strip().lower()
    pulled = []
    skipped = []

    for plat, rdirs in plat_dirs.items():
        if platform_filter.upper() != "ALL" and plat != platform_filter.upper():
            continue
        exts = PLATFORM_DIR_CANDIDATES[plat]["exts"]
        for rdir in rdirs:
            items = list_remote_dir(a, rdir)
            for it in items:
                if it.get("is_dir"):
                    continue
                fname = it["name"]
                if q_low not in fname.lower():
                    continue
                if not fname.lower().endswith((".zip",) + exts):
                    continue

                stem = os.path.splitext(fname)[0]
                slug = _slugify(stem)
                cover_dir = COVERS_DIR / slug
                rom_out_dir = ROMS_VERIFY / plat
                rom_out_dir.mkdir(parents=True, exist_ok=True)
                remote_file = f"{rdir}/{fname}"
                tmp_dl = cover_dir / f"_dl_{fname}"

                try:
                    fetch_file(a, nu_mod, remote_file, tmp_dl)
                    # 若为街机 FBNeo，保留原 .zip；若为主机 zip，解出内部 ROM
                    if plat == "ARCADE_FBNEO":
                        rom_bytes = tmp_dl.read_bytes()
                        rom_ext = ".zip"
                        final_rom = Path("F:/tas_rig/roms") / fname
                        final_rom.parent.mkdir(parents=True, exist_ok=True)
                        final_rom.write_bytes(rom_bytes)
                    elif fname.lower().endswith(".zip"):
                        with zipfile.ZipFile(tmp_dl) as zf:
                            members = [n for n in zf.namelist() if n.lower().endswith(exts)]
                            if not members:
                                skipped.append({"file": remote_file, "reason": f"zip 内未找到 {exts}"})
                                continue
                            rom_ext = os.path.splitext(members[0])[1].lower()
                            rom_bytes = zf.read(members[0])
                        final_rom = rom_out_dir / f"{slug}{rom_ext}"
                    else:
                        rom_ext = os.path.splitext(fname)[1].lower()
                        rom_bytes = tmp_dl.read_bytes()
                        final_rom = rom_out_dir / f"{slug}{rom_ext}"

                    full_sha1, hdrless_sha1 = _sha1_Pair(rom_bytes, rom_ext)
                    if full_sha1.lower() in KNOWN_BAD_MM1_SHA1:
                        skipped.append({
                            "file": remote_file,
                            "sha1": full_sha1,
                            "reason": "拦截已知坏 Mega Man 1 dump（开机能量预满/直跳 CLEAR POINTS）",
                        })
                        continue

                    final_rom.write_bytes(rom_bytes)
                    # 尝试拉取同目录 media/<stem>/boxFront.png 与 logo.png
                    box_path = ""
                    logo_path = ""
                    for m_name, attr in [("boxFront.png", "box"), ("logo.png", "logo")]:
                        try:
                            dst_m = cover_dir / m_name
                            fetch_file(a, nu_mod, f"{rdir}/media/{stem}/{m_name}", dst_m)
                            if attr == "box":
                                box_path = str(dst_m)
                            else:
                                logo_path = str(dst_m)
                        except Exception:
                            pass

                    meta = {
                        "game": stem,
                        "slug": slug,
                        "platform": plat,
                        "rom_path": str(final_rom),
                        "rom_sha1": full_sha1,
                        "rom_headerless_sha1": hdrless_sha1,
                        "boxFront": box_path,
                        "logo": logo_path,
                        "source": remote_file,
                    }
                    (cover_dir / "cover.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                    pulled.append(meta)
                    if len(pulled) >= max_Pull:
                        break
                except Exception as e:
                    skipped.append({"file": remote_file, "reason": str(e)})
            if len(pulled) >= max_Pull:
                break

    res = {"query": query, "platform_filter": platform_filter, "pulled": pulled, "skipped": skipped}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def pull_all_showcase_pack_roms():
    """一键为游戏包目录下的洛克人1、洛克人X、合金弹头、恶魔城晓月/月下、幽游白书自动拉取干净 ROM 并回写路径。"""
    targets = [
        ("megaman1_weapons.showcase.json", "Mega Man", "NES"),
        ("contra_weapons.showcase.json", "Contra", "NES"),
        ("snes_megaman_x_arsenal.showcase.json", "Mega Man X", "SNES"),
        ("snes_super_metroid_abilities.showcase.json", "Super Metroid", "SNES"),
        ("gba_aria_of_sorrow_souls.showcase.json", "Aria of Sorrow", "GBA"),
        ("md_yu_yu_hakusho_moves.showcase.json", "Yu Yu Hakusho", "MD"),
        ("arcade_mslug_weapons.showcase.json", "mslug", "ARCADE_FBNEO"),
        ("ps1_sotn_alucard_powers.showcase.json", "Symphony of the Night", "PS1"),
    ]
    pack_dir = HERE / "游戏包"
    updated = []
    for pack_name, q, plat in targets:
        pfile = pack_dir / pack_name
        if not pfile.is_file():
            continue
        res = search_and_pull(q, platform_filter=plat, max_Pull=1)
        if res["pulled"]:
            rom_p = res["pulled"][0]["rom_path"].replace("\\", "/")
            doc = json.loads(pfile.read_text(encoding="utf-8"))
            doc["rom"] = rom_p
            pfile.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            updated.append({"pack": pack_name, "rom": rom_p, "sha1": res["pulled"][0]["rom_sha1"]})
    print(json.dumps({"updated_packs": updated}, ensure_ascii=False, indent=2))
    return updated


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-dirs", help="探测天马6T网盘下的真实平台目录结构")

    p_pull = sub.add_parser("pull", help="按关键词从天马网盘拉取干净 ROM + 封面并核验 SHA-1")
    p_pull.add_argument("--query", required=True)
    p_pull.add_argument("--platform", default="ALL")
    p_pull.add_argument("--max", type=int, default=3)

    sub.add_parser("pull-pack-roms", help="一键为所有 .showcase.json 盘点包拉取对应平台干净 ROM 并绑定路径")

    args = ap.parse_args()
    if args.cmd == "list-dirs":
        a, _ = _auth()
        print(json.dumps(discover_platform_dirs(a), ensure_ascii=False, indent=2))
    elif args.cmd == "pull":
        search_and_pull(args.query, platform_filter=args.platform, max_Pull=args.max)
    elif args.cmd == "pull-pack-roms":
        pull_all_showcase_pack_roms()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
