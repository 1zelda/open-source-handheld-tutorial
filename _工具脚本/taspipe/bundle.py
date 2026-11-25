# -*- coding: utf-8 -*-
"""画面交接包（bundle）：把 showcase/playthrough 的真实产物打成解说工厂可消费的契约包。

计划书 §9 的落地。跨项目只传素材与契约，不导入对方 Python 内部模块，也不维护第二套
gameplay 规则；所以这里只从"实际产物 + 知识包"生成 manifest，并配一个独立校验器：
  * 路径一律相对 bundle 根，拒绝绝对路径、`../` 逃逸与越界 symlink；
  * 实物、哈希、事件、证据必须能互相反查（哈希现算，不手填）；
  * 不含 ROM/BIOS/完整存档/cookie/令牌——看到目录不代表包已完成，manifest 最后原子写入；
  * package_status=ready 要求逐层结论都有出处，占位 null 一律拦下。

红线：facts 只从知识包字段与实测产物生成，绝不臆造招式效果；许可/发布政策是
"未审查"状态而不是 self_produced 自动放行（§10.7 safety 相位仍要人工确认）。

运行:
  python -m taspipe.bundle build --pack 游戏包/contra_weapons.showcase.json --run <showcase输出目录> --out <bundle根>
  python -m taspipe.bundle verify --bundle <bundle目录> [--require-status ready]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .schema import sha256_file
from . import showcase as SC

SCHEMA_VERSION = "gameplay_bundle/1.0"
PRODUCER = "taspipe.bundle/1.0"
GROUPS = ("schema_version", "bundle_id", "package_status", "producer", "created",
          "job", "game", "profile", "clips", "clock", "time_map", "events",
          "facts", "tas", "rights", "verification", "files")
_NAME_RE = re.compile(r"^[a-z0-9_]{1,64}$")
#: 交接包里禁止出现的键（防凭据/整份存档外流）
FORBIDDEN_KEY_HINTS = ("cookie", "token", "password", "secret", "rom_path", "state_path")


class BundleError(RuntimeError):
    pass


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _rel(path, root):
    """相对 bundle 根的路径；越界/绝对/盘符逃逸一律拒。"""
    p = Path(str(path))
    if p.is_absolute() or (len(p.parts) > 1 and p.parts[0] == "\\\\") or re.match(r"^[A-Za-z]:", str(p)):
        raise BundleError(f"bundle 不许写绝对路径: {path}")
    parts = [part for part in p.parts if part != "."]
    if any(part == ".." for part in parts):
        raise BundleError(f"bundle 路径含 .. 逃逸: {path}")
    return "/".join(parts)


def _inside(root, rel):
    """解析后必须仍在 bundle 根内（挡 symlink 与 junction 指出去）。"""
    real = Path(os.path.realpath(os.path.join(str(root), rel)))
    base = Path(os.path.realpath(str(root)))
    return real == base or str(real).startswith(str(base) + os.sep)


def _probe(path, ffprobe="ffprobe"):
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,nb_frames,"
                        "avg_frame_rate,sample_rate,channels:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise BundleError(f"ffprobe 失败: {path}")
    return json.loads(r.stdout or "{}")


def _fps_rational(avg):
    m = re.match(r"^(\d+)/(\d+)$", str(avg or ""))
    if not m or int(m.group(2)) == 0:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _clip_entry(bundle_root, src, clip_id, kind, ffprobe):
    rel = _rel(f"clips/{clip_id}{Path(str(src)).suffix.lower()}", bundle_root)
    dst = bundle_root / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(src), str(dst))
    d = _probe(dst, ffprobe)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
    num, den = _fps_rational(v.get("avg_frame_rate"))
    frame_count = int(v.get("nb_frames") or 0)
    dur = float(d.get("format", {}).get("duration") or 0)
    return {
        "clip_id": clip_id, "kind": kind, "path": rel,
        "sha256": sha256_file(str(dst)), "byte_size": dst.stat().st_size,
        "frame_count": frame_count, "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "pixel_aspect": "1:1（逐帧 PNG 直出，未做非等比缩放）",
        "codec": v.get("codec_name"),
        "media_fps": {"num": num, "den": den, "decimal": round(frame_count / dur, 6) if dur else None},
        "time_base": {"num": den, "den": num} if num and den else None,
        "duration_seconds": round(dur, 6),
        "has_audio": a is not None,
        "audio": ({"codec": a.get("codec_name"), "sample_rate": a.get("sample_rate"),
                   "channels": a.get("channels")} if a else None),
    }


def _write_clock(bundle_root, c):
    """逐帧时刻表：clip 帧号 → 源秒/PTS，解说端对齐句子不必自己推算 fps 小数。

    写成品粒度的映射（不是"用 60fps 算一下"），是为了 verify 能反查每条
    帧号真的存在、PTS 连续，错帧/错时间基一眼露馅。
    """
    fps = c.get("media_fps") or {}
    num, den = fps.get("num"), fps.get("den")
    if not num or not den:
        return None
    rel = _rel(f"clock/{c['clip_id']}.json", bundle_root)
    p = bundle_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    tb = c["time_base"]
    rows = [{"clip_frame": i, "pts": i,
             "source_seconds": round(i * den / num, 6)} for i in range(c["frame_count"])]
    doc = {"clip_id": c["clip_id"], "path": c["path"],
           "fps": fps, "time_base": tb, "frame_count": c["frame_count"],
           "rule": "pts = clip_frame（time_base 下逐帧 +1）；source_seconds = clip_frame * den / num",
           "rows": rows}
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return rel


def build(pack_path, run_dir, bundle_root, bundle_id=None, ffprobe="ffprobe",
          job_kind="elements"):
    """从 showcase 的真实产物生成 bundle；report 不是 pass 全量时只出 draft。"""
    doc = SC.load_spec(pack_path)
    run_dir = Path(run_dir)
    report = json.loads((run_dir / "showcase_report.json").read_text(encoding="utf-8"))
    plan_res = SC.plan(str(pack_path))
    bundle_root = Path(bundle_root)
    bundle_root.mkdir(parents=True, exist_ok=True)
    game_id = doc["game_id"]
    bid = bundle_id or f"{game_id}_{time.strftime('%Y%m%dT%H%M%S')}"

    clips, events, facts, evidence_files = [], [], [], []
    reel = next((c for c in [report.get("deliverable_ref")] if c and Path(c).is_file()), None)
    if reel:
        clips.append(_clip_entry(bundle_root, reel, "reel_full", "full_coverage_reel", ffprobe))
    for el in report.get("elements", []):
        eid = el["element_id"]
        if not _NAME_RE.match(eid):
            raise BundleError(f"element_id 不合 bundle 命名: {eid}")
        pack_el = next((e for e in doc["elements"] if e["element_id"] == eid), {})
        ev_refs = []
        entry = None
        if Path(el.get("deliverable_ref") or "").is_file():
            entry = _clip_entry(bundle_root, el["deliverable_ref"], eid, "element_demo", ffprobe)
            clips.append(entry)
        if Path(el.get("negative_clip_ref") or "").is_file():
            clips.append(_clip_entry(bundle_root, el["negative_clip_ref"],
                                     f"{eid}_negative", "negative_control", ffprobe))
        for side in ("positive", "negative"):
            node = el.get("detection", {}).get(side) or {}
            src = node.get("frame") if isinstance(node, dict) else node
            if src and Path(src).is_file():
                rel = _rel(f"evidence/{eid}_{side}{Path(src).suffix.lower()}", bundle_root)
                (bundle_root / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, str(bundle_root / rel))
                evidence_files.append({"path": rel, "sha256": sha256_file(str(bundle_root / rel)),
                                       "byte_size": (bundle_root / rel).stat().st_size,
                                       "role": f"detection_{side}", "element_id": eid,
                                       "verdict": node.get("verdict")})
                ev_refs.append(rel)
        trig = pack_el.get("trigger", {})
        win = el.get("reel_window") or {}
        events.append({
            "event_id": f"{eid}_display", "element_id": eid, "label": el.get("label"),
            "clip_id": eid, "kind": el.get("kind"),
            "frame_range": [0, entry["frame_count"]] if entry else None,
            "anchor_frame": pack_el.get("detection", {}).get("frame"),
            "input": {"macro": trig.get("macro"), "extra_frames": trig.get("extra"),
                      "ram_patches": trig.get("patches") or []},
            "reel_window": win or None,
            "evidence_refs": ev_refs,
            "verdict": el.get("verdict"), "export_verdict": el.get("export_verdict"),
        })
        facts.append({
            "fact_id": f"{eid}_catalog", "type": "element_catalog",
            "statement": f"{el.get('label')}：{el.get('kind')}，由 RAM 写入 "
                         f"{json.dumps(trig.get('patches') or [], ensure_ascii=False)} "
                         f"+ 宏「{trig.get('macro')}」在 base 状态上触发",
            "source": {"pack": os.path.basename(str(pack_path)),
                       "catalog_sources": doc["catalog"].get("sources", [])},
            "verification": "measured_capture",
            "evidence_refs": ev_refs,
        })
        for chk in pack_el.get("detection", {}).get("success_checks", []):
            facts.append({
                "fact_id": f"{eid}_{chk['check_id']}", "type": "detection_rule",
                "statement": f"{chk['check_id']}={chk['plugin_id']} "
                             f"params={json.dumps(chk['params'], ensure_ascii=False)}",
                "source": {"pack": os.path.basename(str(pack_path)), "calibrated_on": "本次实采帧"},
                "verification": "measured_pixels",
                "evidence_refs": ev_refs,
            })

    facts.append({
        "fact_id": "coverage", "type": "catalog_coverage",
        "statement": str(doc["catalog"].get("coverage_note") or ""),
        "source": {"pack": os.path.basename(str(pack_path)),
                   "catalog_sources": doc["catalog"].get("sources", [])},
        "verification": "authored_reference",
        "evidence_refs": [f"reports/showcase_report.json"],
    })

    reports_dir = bundle_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(run_dir / "showcase_report.json"), str(reports_dir / "showcase_report.json"))
    for extra in ("ledger.json",):
        if (run_dir / extra).is_file():
            shutil.copyfile(str(run_dir / extra), str(reports_dir / extra))

    state_rev = None
    m = re.search(r"/([^/]+)/r\d{8}T\d{6}/", str(plan_res["resources"]["base_state"]).replace("\\", "/"))
    if m:
        state_rev = m.group(0).strip("/")

    for c in clips:
        c["clock_ref"] = _write_clock(bundle_root, c)

    origins = {}
    for e in report.get("elements", []):
        origins[e.get("state_origin")] = origins.get(e.get("state_origin"), 0) + 1
    pack_sha = sha256_file(str(pack_path))
    job_fp = SC.fingerprint([str(pack_path), str(plan_res["resources"]["base_state"])] +
                            [str(bundle_root / c["path"]) for c in clips],
                            {"kind": "gameplay_bundle", "schema": SCHEMA_VERSION,
                             "elements": [e["element_id"] for e in events]})

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": bid,
        "package_status": "draft",
        "producer": {"tool": PRODUCER, "pipeline": "taspipe.showcase",
                     "pack_schema_version": doc.get("schema_version"),
                     "pack_ref": {"name": os.path.basename(str(pack_path)), "sha256": pack_sha}},
        "created": _now(),
        "job": {"kind": job_kind, "game_id": game_id,
                "coverage_scope": doc["catalog"].get("coverage_note", "")[:120],
                "complete": bool(reel),
                "declared_total": doc["catalog"]["expected_total"],
                "delivered_total": len(report.get("elements", [])),
                "job_fingerprint": job_fp},
        "game": {"game_id": game_id, "title": doc.get("game_title"),
                 "platform": doc.get("platform"), "region": None,
                 "revision_id": None,
                 "rom_identity": {"sha1": doc.get("rom_sha1"),
                                  "source": plan_res.get("rom_source")}},
        "profile": {"backend": "bizhawk", "core": doc.get("core"),
                    "system": doc.get("system"),
                    "emulator_dir_kind": "local_install",
                    "profile_fingerprint": None,
                    "state_package_revision": state_rev,
                    "fps_declared": doc.get("fps")},
        "clips": clips,
        "clock": {"fps_declared": doc.get("fps"),
                  "fps_measured": (clips[0]["media_fps"] if clips else None),
                  "frame_axis": "clip 帧号 = 模拟器帧号（逐帧 PNG 定帧编码，无时间基重采样）",
                  "audio_axis": "本包采集为逐帧 dump，无与帧轴同步的原声轨",
                  "per_clip_map_dir": "clock/"},
        "time_map": {"kind": "identity_frame",
                     "emu_frame_to_clip_frame": "same_index",
                     "emu_frame_to_source_seconds": "clip_frame * fps.den / fps.num",
                     "map_files": [c["clock_ref"] for c in clips if c.get("clock_ref")],
                     "note": "reel 内绝对位置 = 段起点 + 段内帧号；events[].reel_window 已给出换算结果"},
        "events": events,
        "facts": facts,
        "tas": {"mode": "elements_adaptive", "present": False,
                "author": None, "movie_ref": None, "movie_sha1": None,
                "category": None, "timing": None, "route_notes": None,
                "note": "本包是要素展示线，不含速通主片；full_clear 包另发 mode=tas_fixed"},
        "rights": {"self_produced": True,
                   "state_origin": origins,
                   "cheat_disclosure": "要素触发使用 RAM 写入（等效金手指），发布时需说明为演示而非正常游玩成绩",
                   "license_basis": None,
                   "publish_policy_review": "not_reviewed",
                   "forbidden_contents": "不含 ROM/BIOS/完整存档/账号凭据"},
        "verification": {
            "gameplay": {"verdict": report.get("verdict"),
                         "detail": f"要素 {report.get('passed')}/{report.get('total')} 通过受控检测"},
            "element": {e["element_id"]: {"verdict": e["verdict"],
                                          "export": e["export_verdict"]} for e in events},
            "media": {"verdict": "pending", "detail": "由 verify() 现算实物哈希/帧数/时长一致性"},
            "manifest": {"verdict": "pending", "detail": "由 verify() 检查契约完整性"},
            "evidence": evidence_files,
        },
        "files": [],
    }
    _finalize_files(bundle_root, manifest)
    _write_manifest(bundle_root, manifest)
    return manifest


def _finalize_files(bundle_root, manifest):
    """files[] 是整包清单：verify 用它确认没有多余/缺失实物。"""
    entries = []
    for p in sorted(bundle_root.rglob("*")):
        if not p.is_file() or p.name == "manifest.json" or p.name.endswith(".tmp"):
            continue
        rel = _rel(p.relative_to(bundle_root), bundle_root)
        entries.append({"path": rel, "sha256": sha256_file(str(p)),
                        "byte_size": p.stat().st_size})
    manifest["files"] = entries


def _write_manifest(bundle_root, manifest):
    """manifest 最后写、原子替换：半截 manifest 会让解说端把未完成包当已完成。"""
    tmp = bundle_root / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(bundle_root / "manifest.json"))


def load(bundle_dir):
    return json.loads((Path(bundle_dir) / "manifest.json").read_text(encoding="utf-8"))


def verify(bundle_dir, ffprobe="ffprobe", require_status="ready"):
    """独立校验器：字段/路径/实物/时间轴/引用逐条查，返回 {ok, errors, notes}。

    未知字段直接拒（不静默忽略），缺证据不是 pass。require_status=ready 时占位 null、
    未审查的发布政策、draft 包都会被拦——解说端拿到的必须是已经过闸的包。
    """
    root = Path(bundle_dir)
    errors, notes = [], []
    try:
        m = load(root)
    except (OSError, json.JSONDecodeError) as e:
        return {"ok": False, "errors": [f"manifest 不可读: {e}"], "notes": []}
    if m.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version 不符: {m.get('schema_version')!r} != {SCHEMA_VERSION!r}")
    unknown = [k for k in m if k not in GROUPS]
    if unknown:
        errors.append(f"未知顶层字段: {unknown}")
    missing = [k for k in GROUPS if k not in m]
    if missing:
        errors.append(f"缺必填字段组: {missing}")

    blob = json.dumps(m, ensure_ascii=False).lower()
    for hint in FORBIDDEN_KEY_HINTS:
        if f'"{hint}' in blob:
            errors.append(f"包内出现禁用字段线索: {hint}")

    # ---- 实物：files[] 与磁盘现算必须逐一对上 ----
    on_disk = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            on_disk[str(p.relative_to(root)).replace("\\", "/")] = p
    declared = {}
    for f in m.get("files", []):
        try:
            rel = _rel(f["path"], root)
        except BundleError as e:
            errors.append(str(e))
            continue
        declared[rel] = f
        p = on_disk.get(rel)
        if not p:
            errors.append(f"清单文件缺失: {rel}")
            continue
        if not _inside(root, rel):
            errors.append(f"文件解析后越出 bundle 根（symlink/junction）: {rel}")
            continue
        if sha256_file(str(p)) != f["sha256"] or p.stat().st_size != f["byte_size"]:
            errors.append(f"文件与清单不符（被改动/截断）: {rel}")
    extra = sorted(set(on_disk) - set(declared))
    if extra:
        errors.append(f"包内有未登记文件（不完整的交接）: {extra[:5]}")

    # ---- clips：路径/哈希/帧数/时长/音频声明 ----
    clip_ids = set()
    for c in m.get("clips", []):
        cid = c.get("clip_id")
        if cid in clip_ids:
            errors.append(f"clip_id 重复: {cid}")
        clip_ids.add(cid)
        try:
            rel = _rel(c["path"], root)
        except (BundleError, KeyError) as e:
            errors.append(f"clip {cid}: {e}")
            continue
        p = root / rel
        if not p.is_file():
            errors.append(f"clip 文件缺失: {rel}")
            continue
        if sha256_file(str(p)) != c.get("sha256"):
            errors.append(f"clip 哈希不符: {rel}")
        if p.stat().st_size != c.get("byte_size"):
            errors.append(f"clip 大小不符: {rel}")
        if p.stat().st_size == 0:
            errors.append(f"clip 是 0 字节: {rel}")
            continue
        try:
            d = _probe(p, ffprobe)
        except BundleError as e:
            errors.append(f"clip {cid}: {e}")
            continue
        v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
        has_audio = any(s.get("codec_type") == "audio" for s in d.get("streams", []))
        if int(v.get("nb_frames") or 0) != int(c.get("frame_count") or -1):
            errors.append(f"clip {cid} 帧数不符: 声明 {c.get('frame_count')} 实测 {v.get('nb_frames')}")
        if (int(v.get("width") or 0), int(v.get("height") or 0)) != \
                (int(c.get("width") or 0), int(c.get("height") or 0)):
            errors.append(f"clip {cid} 尺寸不符: 声明 {c.get('width')}x{c.get('height')} "
                          f"实测 {v.get('width')}x{v.get('height')}")
        if has_audio != bool(c.get("has_audio")):
            errors.append(f"clip {cid} 原声声明与实物不符: 声明 {c.get('has_audio')} 实测 {has_audio}")
        num, den = _fps_rational(v.get("avg_frame_rate"))
        fps = (num / den) if num and den else None
        dur = float(d.get("format", {}).get("duration") or 0)
        if fps and abs(int(c["frame_count"]) / fps - dur) > 1.5 / fps + 0.02:
            errors.append(f"clip {cid} 时长与帧数/fps 不自洽: {dur}s vs "
                          f"{c['frame_count']}帧@{fps:.4f}")
        # 逐帧时刻表：解说端就是照这张表对句子的，行数/PTS/秒数必须与实物一致
        cref = c.get("clock_ref")
        if not cref or not (root / cref).is_file():
            errors.append(f"clip {cid} 缺帧→时刻映射文件: {cref}")
        else:
            try:
                ck = json.loads((root / cref).read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                errors.append(f"clip {cid} 映射文件损坏: {cref}: {e}")
                continue
            rows = ck.get("rows") or []
            if len(rows) != int(c["frame_count"]):
                errors.append(f"clip {cid} 映射行数 {len(rows)} != 实物帧数 {c['frame_count']}")
            if ck.get("clip_id") != cid or ck.get("path") != c["path"]:
                errors.append(f"clip {cid} 映射文件指错素材: {ck.get('path')}")
            if rows and any(r["clip_frame"] != i or r["pts"] != i for i, r in enumerate(rows)):
                errors.append(f"clip {cid} 映射帧号/PTS 不连续（错帧风险）")
            mf = (c.get("media_fps") or {})
            if rows and mf.get("num") and abs(rows[-1]["source_seconds"] -
                                              (len(rows) - 1) * mf["den"] / mf["num"]) > 1e-4:
                errors.append(f"clip {cid} 映射秒轴与 fps 不符")

    # ---- 身份字段：ready 不许留空 ----
    for path, val in (("game.game_id", (m.get("game") or {}).get("game_id")),
                      ("game.title", (m.get("game") or {}).get("title")),
                      ("game.platform", (m.get("game") or {}).get("platform")),
                      ("game.rom_identity.sha1", ((m.get("game") or {}).get("rom_identity") or {}).get("sha1")),
                      ("profile.core", (m.get("profile") or {}).get("core")),
                      ("profile.system", (m.get("profile") or {}).get("system")),
                      ("profile.state_package_revision", (m.get("profile") or {}).get("state_package_revision")),
                      ("job.job_fingerprint", (m.get("job") or {}).get("job_fingerprint")),
                      ("producer.pack_ref.sha256", ((m.get("producer") or {}).get("pack_ref") or {}).get("sha256"))):
        if not str(val or "").strip():
            errors.append(f"身份字段为空: {path}")
    declared_fps = (m.get("clock") or {}).get("fps_declared")
    meas = ((m.get("clock") or {}).get("fps_measured") or {}).get("decimal")
    if declared_fps and meas and abs(float(declared_fps) - meas) > 0.01:
        errors.append(f"媒体帧率与声明不符: 声明 {declared_fps} 实测 {meas}（可能被重采样）")

    # ---- events：clip 引用存在、锚点落在范围内、证据在包内 ----
    reel_clip = next((c for c in m.get("clips", []) if c.get("kind") == "full_coverage_reel"), None)
    for e in m.get("events", []):
        if e.get("clip_id") not in clip_ids:
            errors.append(f"event {e.get('event_id')} 引用未知 clip: {e.get('clip_id')}")
        rng, anchor = e.get("frame_range"), e.get("anchor_frame")
        if rng and anchor is not None and not (rng[0] <= anchor < rng[1]):
            errors.append(f"event {e.get('event_id')} 锚点 {anchor} 不在帧窗 {rng} 内")
        win = e.get("reel_window") or {}
        if win and reel_clip:
            if win.get("end_frame") > reel_clip["frame_count"]:
                errors.append(f"event {e.get('event_id')} 合辑窗口越界 "
                              f"{win.get('end_frame')} > {reel_clip['frame_count']}")
            seg = next((c for c in m["clips"] if c["clip_id"] == e.get("clip_id")), None)
            if seg and win.get("end_frame", 0) - win.get("start_frame", 0) != seg["frame_count"]:
                errors.append(f"event {e.get('event_id')} 合辑窗口长度 != 段长（时间映射不可信）")
        for ref in e.get("evidence_refs", []):
            if not (root / ref).is_file():
                errors.append(f"event {e.get('event_id')} 证据缺失: {ref}")
        if e.get("verdict") != "pass":
            errors.append(f"event {e.get('event_id')} 未过检测: {e.get('verdict')}")

    # ---- facts：必须有出处与证据，statement 不许空 ----
    for fct in m.get("facts", []):
        if not str(fct.get("statement") or "").strip():
            errors.append(f"fact {fct.get('fact_id')} 无原句")
        if not (fct.get("source") or {}):
            errors.append(f"fact {fct.get('fact_id')} 无来源")
        for ref in fct.get("evidence_refs", []):
            if not (root / ref).is_file():
                errors.append(f"fact {fct.get('fact_id')} 证据缺失: {ref}")

    # ---- 覆盖：声明总数与实际交付一致才算完整包 ----
    job = m.get("job", {})
    if job.get("declared_total") != job.get("delivered_total"):
        errors.append(f"覆盖不足: 声明 {job.get('declared_total')}，交付 {job.get('delivered_total')}")
    if not job.get("complete"):
        errors.append("缺 full_coverage_reel，不能当完整交接包")

    ver = m.get("verification", {})
    if (ver.get("gameplay") or {}).get("verdict") != "pass":
        errors.append(f"gameplay 层未过: {(ver.get('gameplay') or {}).get('verdict')}")
    media_ok = not any("clip" in x or "时长" in x for x in errors)
    ver["media"] = {"verdict": "pass" if media_ok else "fail",
                    "detail": "实物哈希/帧数/尺寸/原声声明/时长自洽逐条现算"}
    ver["manifest"] = {"verdict": "pass" if not errors else "fail",
                       "detail": f"errors={len(errors)}"}
    m["verification"] = ver
    if require_status == "ready":
        if m.get("package_status") != "ready":
            errors.append(f"package_status={m.get('package_status')}，未达 ready")
        if (m.get("rights") or {}).get("publish_policy_review") != "approved":
            errors.append("发布政策未审查（self_produced 不能代替 safety 相位）")
        if not (m.get("game") or {}).get("rom_identity", {}).get("sha1"):
            errors.append("ROM 身份缺失，复用范围无法界定")
    if m.get("package_status") == "ready" and errors:
        m["package_status"] = "draft"
        notes.append("校验未过，package_status 已退回 draft")
    _write_manifest(root, m)
    return {"ok": not errors, "errors": errors, "notes": notes,
            "bundle_id": m.get("bundle_id"), "package_status": m.get("package_status")}


def publish(bundle_dir, reviewer=None):
    """人工审查后显式升格 ready：没有审查人署名不许标 ready。"""
    root = Path(bundle_dir)
    m = load(root)
    if not str(reviewer or "").strip():
        raise BundleError("升 ready 需要 reviewer 署名（safety 相位的人工结论）")
    m["rights"]["publish_policy_review"] = "approved"
    m["rights"]["reviewer"] = reviewer
    m["rights"]["reviewed_at"] = _now()
    res = verify(root, require_status="draft")
    if not res["ok"]:
        raise BundleError(f"未过校验，不能标 ready: {res['errors'][:3]}")
    m["package_status"] = "ready"
    _finalize_files(root, m)
    _write_manifest(root, m)
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--pack", required=True)
    b.add_argument("--run", required=True, help="showcase 输出目录")
    b.add_argument("--out", required=True, help="bundle 根目录")
    b.add_argument("--bundle-id", default=None)
    b.add_argument("--ffprobe", default="ffprobe")
    v = sub.add_parser("verify")
    v.add_argument("--bundle", required=True)
    v.add_argument("--require-status", default="ready", choices=["draft", "ready"])
    v.add_argument("--ffprobe", default="ffprobe")
    p = sub.add_parser("publish")
    p.add_argument("--bundle", required=True)
    p.add_argument("--reviewer", required=True)
    args = ap.parse_args()
    if args.cmd == "build":
        m = build(args.pack, args.run, args.out, bundle_id=args.bundle_id, ffprobe=args.ffprobe)
        print(json.dumps({"bundle_id": m["bundle_id"], "clips": len(m["clips"]),
                          "events": len(m["events"]), "facts": len(m["facts"]),
                          "package_status": m["package_status"]}, ensure_ascii=False, indent=1))
        return 0
    if args.cmd == "verify":
        res = verify(args.bundle, ffprobe=args.ffprobe, require_status=args.require_status)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["ok"] else 2
    m = publish(args.bundle, reviewer=args.reviewer)
    print(json.dumps({"package_status": m["package_status"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
