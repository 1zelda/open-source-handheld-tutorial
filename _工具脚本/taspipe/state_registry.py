# -*- coding: utf-8 -*-
"""状态资产仓：把「一次跑出来的存档」变成可复用、可反查、可失效的资产。

计划书 §3 的落地。一款游戏的可复现前提不只是一个 base.state，而是
profile（ROM/core/模拟器身份）+ 场景存档 + 重建导航链 + 补丁 + 证据 + 验收结论，
整体按 revision 冻结；旧 revision 只读保留，改动一律开新 revision。

目录（正式资产，不进 scratch）：
    04-游戏资源库/TAS输入录像库/状态资产/<game_id>/<profile_id>/<revision>/
        package.json states/ inputs/ evidence/

生命周期（旁路状态 blocked_*/failed/inconclusive/stale 由 blockers 表达）：
    candidate → resources_ready → state_verified → element_verified → production_ready

红线：
* `resolve_state` 必须按 sha256 校验实物，文件被移走/截断就报错，不返回坏路径。
* 状态文件的确定性范围只在 package 声明的 profile 内成立：跨模拟器/core 不自动可用。
* 只有 `state_verified` 及以上才许被生产路径消费；`candidate` 不能当已验证用。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import zipfile
from pathlib import Path

from .schema import sha256_file

ROOT = Path(__file__).resolve().parents[2]          # F:\开源掌机教程
ASSET_ROOT = ROOT / "04-游戏资源库" / "TAS输入录像库" / "状态资产"
SCHEMA_VERSION = "state_package/1.0"

STATUSES = ("candidate", "resources_ready", "state_verified",
            "element_verified", "production_ready")
#: 旁路档位：不在前进路线上，但必须能显式落进 package（计划书 §3.2 生命周期）。
#: stale 用于「同一条导航链被更新的 revision 取代」，让「已验证可复用状态数」不重复计数。
BYPASS_STATUSES = ("blocked_resource", "blocked_profile", "blocked_knowledge",
                   "failed", "inconclusive", "stale")
#: 生产路径可消费的最低状态：state_verified（起点可加载 + 跨进程确定性已过）。
CONSUMABLE = STATUSES[2:]


class StateAssetError(RuntimeError):
    pass


def _write_json(path: Path, doc: dict) -> None:
    """临时件 + atomic replace：半截 package.json 会让整包被当成坏资产。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict:
    if not path.is_file():
        raise StateAssetError(f"状态包不存在: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise StateAssetError(f"状态包 JSON 损坏: {path}: {e}") from None


def package_dir(game_id: str, profile_id: str, revision: str) -> Path:
    for name, val in (("game_id", game_id), ("profile_id", profile_id),
                      ("revision", revision)):
        if not val or "/" in val or "\\" in val or ".." in val:
            raise StateAssetError(f"{name} 非法: {val!r}")
    return ASSET_ROOT / game_id / profile_id / revision


def make_revision() -> str:
    return "r" + time.strftime("%Y%m%dT%H%M%S")


def create(game_id: str, profile: dict, revision: str | None = None,
           status: str = "candidate", note: str = "") -> dict:
    """建包。profile 必须带 rom_sha1 + core + emulator 身份，否则后面无法判定复用范围。"""
    for key in ("rom_sha1", "core", "emulator"):
        if not str(profile.get(key) or "").strip():
            raise StateAssetError(f"profile 缺 {key}（状态复用范围无法界定）")
    revision = revision or make_revision()
    d = package_dir(game_id, profile["profile_id"], revision)
    if (d / "package.json").exists():
        raise StateAssetError(f"revision 已存在: {d}")
    for sub in ("states", "inputs", "evidence"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    doc = {"schema_version": SCHEMA_VERSION, "game_id": game_id,
           "profile_id": profile["profile_id"], "revision": revision,
           "profile": profile, "status": status, "note": note,
           "created": time.strftime("%Y-%m-%d %H:%M:%S"),
           "states": {}, "inputs": {}, "evidence": {},
           "nav_recipe": [], "patches": {}, "facts": {},
           "verification": {}, "blockers": []}
    _write_json(d / "package.json", doc)
    return doc


def load(game_id: str, profile_id: str, revision: str) -> dict:
    return _read_json(package_dir(game_id, profile_id, revision) / "package.json")


def latest(game_id: str, profile_id: str | None = None,
           status_in: tuple = ()) -> dict | None:
    """取最新 revision（可按状态过滤）。目录不存在返回 None，不抛。"""
    base = ASSET_ROOT / game_id
    if not base.is_dir():
        return None
    profs = [base / profile_id] if profile_id else sorted(base.iterdir())
    found = []
    for p in profs:
        for d in sorted(p.iterdir(), reverse=True):
            pkg = d / "package.json"
            if pkg.is_file():
                found.append(_read_json(pkg))
    for want in reversed(STATUSES):
        if want not in (status_in or STATUSES):
            continue
        for doc in found:
            if doc["status"] == want:
                return doc
    return None


def list_packages() -> list[dict]:
    if not ASSET_ROOT.is_dir():
        return []
    out = []
    for pkg in sorted(ASSET_ROOT.glob("*/*/*/package.json")):
        d = _read_json(pkg)
        out.append({"game_id": d["game_id"], "profile_id": d["profile_id"],
                    "revision": d["revision"], "status": d["status"],
                    "states": sorted(d.get("states") or {}),
                    "rom_sha1": d["profile"].get("rom_sha1"),
                    "verdicts": {k: v.get("verdict") for k, v in
                                 (d.get("verification") or {}).items()}})
    return out


def _store(d: Path, src, sub: str, name: str, slot: str, extra: dict | None = None) -> dict:
    src = Path(src)
    if not src.is_file():
        raise StateAssetError(f"{slot} 源文件不存在: {src}")
    if not re_full(name):
        raise StateAssetError(f"{slot} 名字非法（要 [a-z0-9_]+）: {name!r}")
    dst = d / sub / (name + src.suffix.lower())
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.resolve() != src.resolve():
        shutil.copyfile(src, dst)
    entry = {"path": f"{sub}/{dst.name}".replace("\\", "/"),
             "sha256": sha256_file(str(dst)), "byte_size": dst.stat().st_size,
             "source": str(src)}
    entry.update(extra or {})
    return entry


def re_full(name: str) -> bool:
    import re
    return bool(re.fullmatch(r"[a-z0-9_]{1,48}", str(name or "")))


def add_state(game_id: str, profile_id: str, revision: str, name: str, src,
              kind: str = "scene", note: str = "") -> dict:
    """把实机跑出来的存档收进资产仓（拷贝，不引用 scratch）。"""
    d = package_dir(game_id, profile_id, revision)
    doc = _read_json(d / "package.json")
    doc["states"][name] = _store(d, src, "states", name, "state",
                                 {"kind": kind, "note": note})
    _write_json(d / "package.json", doc)
    return doc


def add_evidence(game_id: str, profile_id: str, revision: str, name: str, src,
                 kind: str, note: str = "") -> dict:
    d = package_dir(game_id, profile_id, revision)
    doc = _read_json(d / "package.json")
    doc["evidence"][name] = _store(d, src, "evidence", name, "evidence",
                                   {"kind": kind, "note": note})
    _write_json(d / "package.json", doc)
    return doc


def add_input(game_id: str, profile_id: str, revision: str, name: str, src,
              kind: str = "recipe", note: str = "") -> dict:
    d = package_dir(game_id, profile_id, revision)
    doc = _read_json(d / "package.json")
    doc["inputs"][name] = _store(d, src, "inputs", name, "input",
                                 {"kind": kind, "note": note})
    _write_json(d / "package.json", doc)
    return doc


def record(game_id: str, profile_id: str, revision: str, check: str, verdict: str,
           detail: str = "", evidence: tuple = ()) -> dict:
    """逐格记验收结论。verdict 用 schema.Verdict 的值（pass/fail/inconclusive）。"""
    d = package_dir(game_id, profile_id, revision)
    doc = _read_json(d / "package.json")
    doc["verification"][check] = {"verdict": verdict, "detail": detail,
                                  "evidence": list(evidence),
                                  "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    _write_json(d / "package.json", doc)
    return doc


def _slug(val, fallback):
    """把任意标签变成 [a-z0-9_] 文件名，避免证据落不进包。中文标签只留 ASCII 段，
    全中文会退化成 fallback（navNN），真实标签仍写进 evidence 条目的 note 里。"""
    s = "".join(ch if ch in "abcdefghijklmnopqrstuvwxyz0123456789" else "_"
                for ch in str(val or "").strip().lower())
    while "__" in s:
        s = s.replace("__", "_")
    s = s.strip("_")[:48]
    return s or fallback


def attach_nav(game_id: str, profile_id: str, revision: str, recipe: dict,
               nav: dict, state_name: str = "base") -> dict:
    """把 statebuild.run_nav 的配方与证据收进包：states/ 存档、inputs/nav.json、
    evidence/ 每步画面，verification 逐条 pass/fail。包因此自带重建方法，不靠人记忆。"""
    d = package_dir(game_id, profile_id, revision)
    doc = _read_json(d / "package.json")
    doc["states"][state_name] = _store(d, nav["state"]["path"], "states", state_name, "state",
                                       {"kind": "scene", "note": "statebuild.run_nav 冻结"})
    if (nav["state"].get("content") or {}).get("content_sha256"):
        doc["states"][state_name]["content"] = nav["state"]["content"]
    root = nav.get("root") or {}
    if root.get("path") and Path(root["path"]).is_file():
        # 引导态必须随包走：NesHawk 上电 RAM 是随机的，"从冷启动重跑导航"不可字节复现，
        # 只有从这个 root 出发才谈得上复现。
        doc["states"]["boot_root"] = _store(d, root["path"], "states", "boot_root", "state",
                                            {"kind": "root", "note": f"bootstrap={root.get('kind')}"})
        doc["verification"]["nav:root_shipped"] = {
            "verdict": "pass", "detail": json.dumps(
                {"kind": root.get("kind"), "boot_frame": root.get("boot_frame"),
                 "nav_frames": root.get("nav_frames"), "sha256": root.get("sha256")},
                ensure_ascii=False),
            "evidence": [doc["states"]["boot_root"]["path"]],
            "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    recipe_path = d / "inputs" / "nav.json"
    _write_json(recipe_path, recipe)
    doc["inputs"]["nav"] = {"path": "inputs/nav.json", "sha256": sha256_file(str(recipe_path)),
                            "byte_size": recipe_path.stat().st_size}
    doc["nav_recipe"] = recipe.get("steps") or []
    for st in nav.get("steps") or []:
        name = _slug(st.get("label"), f"nav{st['step']:02d}")
        check = {"verdict": "pass" if st.get("pass") else "fail",
                 "detail": f"frames={st.get('frames')} checks={json.dumps(st.get('checks') or [], ensure_ascii=False)}",
                 "evidence": [], "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
        if st.get("shot"):
            check["evidence"] = [_store(d, st["shot"], "evidence", f"nav{st['step']:02d}_{name}",
                                        "evidence", {"kind": "nav_step", "note": st.get("label") or ""})["path"]]
        if st.get("ram_bin") and Path(st["ram_bin"]).is_file():
            check["evidence"].append(_store(d, st["ram_bin"], "evidence",
                                            f"ram{st['step']:02d}_{name}", "evidence",
                                            {"kind": "ram_dump", "note": st.get("label") or ""})["path"])
        doc["verification"][f"nav:{st['step']}:{name}"] = check
    doc["verification"]["nav:reload_cross_process"] = {
        "verdict": "pass" if (nav.get("reload") or {}).get("pass") else "fail",
        "detail": (nav.get("reload") or {}).get("detail", ""),
        "evidence": [f"states/{state_name}{Path(nav['state']['path']).suffix}"],
        "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    ctrl = nav.get("control")
    if ctrl:
        paths = []
        for kind, p in (ctrl.get("screenshots") or {}).items():
            if Path(p).is_file():
                paths.append(_store(d, p, "evidence", f"ctrl_{_slug(kind, 'shot')}",
                                    "evidence", {"kind": "controllability", "note": kind})["path"])
        doc["verification"]["nav:controllability"] = {
            "verdict": "pass" if ctrl.get("controllable") else "fail",
            "detail": json.dumps({k: ctrl.get(k) for k in
                                  ("action_effective", "menu_effective", "ram_diff_bytes")},
                                 ensure_ascii=False),
            "evidence": paths, "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    det = nav["state"]
    doc["verification"]["nav:determinism_criterion"] = {
        "verdict": "pass",
        "detail": json.dumps({
            "复现判据": "内容指纹(ZIP 条目 CRC) + 冻结帧像素 + 帧对齐 RAM + 可控性行为",
            "不用文件 sha256 的原因": "BizHawk 存档是 ZIP，跨进程只有写入时间戳会变，"
                                     "文件哈希相等测的是时间戳不是机器态",
            "content_sha256": (det.get("content") or {}).get("content_sha256"),
            "core_crc32": (det.get("content") or {}).get("core_crc32"),
            "ref_shot_sha1": det.get("ref_shot_sha1"),
            "ram_sha256": det.get("ram_sha256"),
            "file_sha256_仅作实物封条": det.get("sha256"),
        }, ensure_ascii=False),
        "evidence": [doc["states"][state_name]["path"]],
        "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    _write_json(d / "package.json", doc)
    return doc


def set_status(game_id: str, profile_id: str, revision: str, status: str,
               blockers: tuple = ()) -> dict:
    """状态只能按生命周期前进；跳级或降级必须显式（stale 由失效传播调用方负责）。

    旁路档位（blocked_*/failed/inconclusive/stale）必须带 blockers 说明理由，
    否则一个没有出处的降级会被下游当成「测过了，只是没通过」。
    """
    if status not in STATUSES + BYPASS_STATUSES:
        raise StateAssetError(f"未知状态 {status!r}，允许 {STATUSES + BYPASS_STATUSES}")
    if status in BYPASS_STATUSES and not [b for b in blockers if str(b).strip()]:
        raise StateAssetError(f"旁路状态 {status} 必须写 blockers，说明为什么降级")
    d = package_dir(game_id, profile_id, revision)
    doc = _read_json(d / "package.json")
    doc["status"] = status
    doc["blockers"] = list(blockers)
    doc["status_ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_json(d / "package.json", doc)
    return doc


def resolve_state(game_id: str, profile_id: str, revision: str, name: str,
                  require_status: tuple = CONSUMABLE) -> Path:
    """生产路径取存档：包状态够格 + 实物 sha256 一致，才给路径。"""
    d = package_dir(game_id, profile_id, revision)
    doc = _read_json(d / "package.json")
    if doc["status"] not in require_status:
        raise StateAssetError(
            f"状态包 {game_id}/{profile_id}/{revision} 当前 {doc['status']}，"
            f"未达可消费级别 {require_status}")
    entry = (doc.get("states") or {}).get(name)
    if not entry:
        raise StateAssetError(f"状态包无场景 {name!r}（有: {sorted(doc.get('states') or {})}）")
    p = d / entry["path"]
    if not p.is_file():
        raise StateAssetError(f"场景存档缺失: {p}")
    if sha256_file(str(p)) != entry["sha256"]:
        raise StateAssetError(f"场景存档 sha256 不符（被改动/截断）: {p}")
    return p


def profile_of(game_id: str, profile_id: str, revision: str) -> dict:
    return _read_json(package_dir(game_id, profile_id, revision) / "package.json")["profile"]


def state_content_fingerprint(path) -> dict:
    """BizHawk 存档是 ZIP 容器：跨进程复现时只有写入时间戳会变，条目 CRC 不变。

    11-14 实测同一条原子导航跑两遍，两份 .state 差 8 个字节，全部落在 ZIP 本地头的
    DOS time 字段（a9/b1，差 4 秒）和中央目录的对应副本上；Core.bin 等四个条目的
    名字/CRC/解压长度逐字节相同。所以「文件 sha256 相等」不能当复现判据（它测的是
    时间戳），内容指纹才是机器态本身；文件 sha256 退化成「这一份实物的防篡改封条」。
    """
    p = Path(str(path))
    try:
        with zipfile.ZipFile(p) as z:
            items = sorted((i.filename, i.CRC, i.file_size) for i in z.infolist())
    except zipfile.BadZipFile as e:
        raise StateAssetError(f"存档不是 ZIP 容器，取不了内容指纹: {p}: {e}") from None
    if not items:
        raise StateAssetError(f"存档容器为空: {p}")
    core = next((c for c in items if c[0] in ("Core.bin", "Core.bin.zst")), None)
    return {"content_sha256": hashlib.sha256(
                json.dumps(items, sort_keys=True).encode()).hexdigest(),
            "core_entry": core[0] if core else None,
            "core_crc32": f"{core[1]:08x}" if core else None,
            "entries": [{"name": n, "crc32": f"{c:08x}", "size": s} for n, c, s in items]}


def sha1_file(path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def find_verified_nav(game_id: str, profile_id: str, steps: list,
                      state_name: str = "base") -> dict | None:
    """已验证过的同一条导航链直接复用，不再重跑模拟器（计划书：验证过的指纹复用、禁止重测）。

    命中条件全部是产物级的：同 game/profile、nav_recipe 逐步相同、包在可消费档位、
    实物在位且 sha256 与登记一致。任一条不满足就返回 None，由调用方重新导航。
    """
    if not ASSET_ROOT.is_dir():
        return None
    want = json.dumps(steps or [], sort_keys=True)
    for pkg in sorted(ASSET_ROOT.glob(f"{game_id}/{profile_id}/*/package.json"),
                      key=lambda p: p.parent.name, reverse=True):
        d = _read_json(pkg)
        if d["status"] not in CONSUMABLE:
            continue
        if json.dumps(d.get("nav_recipe") or [], sort_keys=True) != want:
            continue
        rec = (d.get("states") or {}).get(state_name)
        if not rec:
            continue
        real = pkg.parent / rec["path"]
        if not real.is_file() or sha256_file(str(real)) != rec["sha256"]:
            continue
        return {"game_id": game_id, "profile_id": profile_id, "revision": d["revision"],
                "state_name": state_name, "package": str(pkg.parent),
                "state_path": str(real), "content_sha256": (rec.get("content") or {}).get("content_sha256")}
    return None


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出全部状态包及验收摘要")
    p = sub.add_parser("show")
    p.add_argument("--game", required=True)
    p.add_argument("--profile", default=None)
    p.add_argument("--revision", default=None)
    args = ap.parse_args()
    if args.cmd == "list":
        rows = list_packages()
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    doc = (latest(args.game, args.profile) if not args.revision
           else load(args.game, args.profile, args.revision))
    if not doc:
        print(f"无状态包: {args.game} {args.profile or ''}", )
        return 2
    print(json.dumps(doc, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
