# -*- coding: utf-8 -*-
"""Statejump 全量要素盘点生产器：共享 base → 逐要素正/反例采集 → 检测 → 合辑。

知识包离线 authored，运行时零 LLM。每个要素均从同一 base.state 原子读档、可选 RAM
前置补丁、逐帧宏采集；动作、效果、拍摄三类验收独立声明。动作/效果要求正例 pass、
反例 fail；拍摄要求正例检查 pass。三类缺检或 inconclusive 不静默放行，效果不适用须显式声明。
detection.success_checks 只保留为候选视觉判据，不能单独授权交付。

部分知识包可用 --only 做单要素生产试跑，但不会生成正式合辑或报全量 done。
完整知识包必须 catalog.expected_total == len(elements)，全部通过后才输出 reel.mp4。

运行:
  python -m taspipe.showcase plan --pack 游戏包/game.showcase.json
  python -m taspipe.showcase run --pack 游戏包/game.showcase.json --out F:/out --only mega_buster
  python -m taspipe.showcase run --pack 游戏包/game.showcase.json --out F:/out
"""
import argparse
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import detect
from . import state_registry as SR
from . import statejump as SJ
from .ledger import Ledger, fingerprint
from .schema import CheckSpec, FailureCode, SchemaError, Verdict, to_dict


# 平台档案：键集/地址宽度交给 statejump，「能否出片」独立由 verified 把关。
# NES(NesHawk) 与 GBA(mGBA) 已走通存档跳跃、RAM 域、逐帧宏和真实正反例；
# 其余核心虽有知识包，但后端未核验，schema 可过、run 必须 blocked。
# 这不是能力声明，是准入状态台账——避免"包能读 = 片能出"的静默错跑。
PLATFORM_PROFILES = {
    "NES":          {"cores": {"NesHawk"}, "systems": {"NES", "FC", "FAMICOM"},
                     "verified": True,  "note": "StateSession/NesHawk 已实测"},
    "SNES":         {"cores": {"BSNES", "Snes9x"}, "systems": {"SNES", "SFC"},
                     "verified": False, "note": "需核验 BSNES 键名/WRAM 域/存档格式"},
    "GBA":          {"cores": {"mGBA"}, "systems": {"GBA"},
                     "verified": False, "note": "mGBA 键名/WRAM 域与部分 Aria 要素已实测；平台级生产准入仍关闭"},
    "MD":           {"cores": {"GPGX"}, "systems": {"GEN", "MD", "GENESIS"},
                     "verified": False, "note": "需核验 GPGX 键名/68K RAM 域"},
    "ARCADE_FBNEO": {"cores": {"FBNeo"}, "systems": {"ARCADE"},
                     "verified": False, "note": "需核验 FBNeo 键名/m68K RAM 域"},
    "ARCADE_MAME":  {"cores": {"MAME"}, "systems": {"ARCADE"},
                     "verified": False, "note": "需核验 MAME 键名/内存域"},
    "PS1":          {"cores": {"Octoshock"}, "systems": {"PSX", "PS1"},
                     "verified": False, "note": "需核验 Octoshock 键名/MainRAM 域"},
    "PSP":          {"cores": {"PPSSPP"}, "systems": {"PSP"},
                     "verified": False, "note": "需核验 PPSSPP 键名/内存域"},
}


def _element_detect_frame(doc, element_id):
    """知识包里该要素的检测帧号（合辑事件窗口用它定位「这一格的高光帧」）。"""
    for el in doc["elements"]:
        if el["element_id"] == element_id:
            return int(el["detection"]["frame"])
    raise SchemaError(f"知识包缺要素 {element_id}")


def _macro_frames(macro, platform="NES"):
    return 0 if not macro or macro == "-" else len(SJ.parse_macro(macro, platform).split(","))


def _resolve(pack_path, value):
    p = Path(value)
    return str(p if p.is_absolute() else Path(pack_path).resolve().parent / p)


def _load_json(pack_path):
    try:
        return json.loads(Path(pack_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SchemaError(f"showcase 包不可读: {pack_path}: {e}")


# 交付缺口：创作者点名批准后，某个要素可以「本轮不出片」，但不能「静默消失」。
# 只有这三种码能把要素从全量必交里摘出去，且必须写清原因/谁批/哪天（11-23 用户批 A：
# MM1 Super Arm 认 7/8 交付）。没声明的要素照旧走全量闸，缺一个就拦死。
GAP_STATUSES = {"blocked_routing", "needs_external_tool", "version_unsupported"}
GAP_FIELDS = ("reason", "decided_by", "decided_on")
ACCEPTANCE_FIELDS = ("action_checks", "effect_requirement", "effect_checks", "capture_checks")
EFFECT_REQUIREMENTS = {"required", "not_applicable"}


def acceptance_declaration(element):
    return {key: element.get(key) for key in ACCEPTANCE_FIELDS}


def _validate_acceptance(element, eid):
    missing = [key for key in ACCEPTANCE_FIELDS if key not in element]
    if missing:
        raise SchemaError(f"{eid}: 缺三类验收声明 {missing}；像素候选不得自动晋升为交付")
    groups = []
    seen = set()
    for key in ("action_checks", "effect_checks", "capture_checks"):
        specs = element[key]
        if not isinstance(specs, list) or (key != "effect_checks" and not specs):
            raise SchemaError(f"{eid}: {key} 须为非空 CheckSpec 列表")
        for raw in specs:
            if not isinstance(raw, dict):
                raise SchemaError(f"{eid}: {key} 每项须为 CheckSpec 对象")
            check = CheckSpec(**raw).validate()
            if check.check_id in seen:
                raise SchemaError(f"{eid}: 三类验收 check_id 重复 {check.check_id}")
            seen.add(check.check_id)
            if check.required is not True:
                raise SchemaError(f"{eid}: 正式验收检查 {check.check_id} 必须 required=true")
            if check.plugin_id not in detect.PLUGINS:
                raise SchemaError(f"{eid}: 未注册验收插件 {check.plugin_id}")
            groups.append(check)
    requirement = element["effect_requirement"]
    if requirement not in EFFECT_REQUIREMENTS:
        raise SchemaError(f"{eid}: effect_requirement 须为 {sorted(EFFECT_REQUIREMENTS)}")
    if requirement == "required" and not element["effect_checks"]:
        raise SchemaError(f"{eid}: effect_requirement=required 时 effect_checks 不能为空")
    if requirement == "not_applicable" and element["effect_checks"]:
        raise SchemaError(f"{eid}: effect_requirement=not_applicable 时 effect_checks 必须为空")
    return groups



def delivery_gaps(doc):
    """已声明的交付缺口：{element_id: delivery}。要素仍留在清单里，expected_total 不改。"""
    return {el["element_id"]: el["delivery"] for el in doc["elements"] if el.get("delivery")}


def validate_spec(doc):
    if not isinstance(doc, dict) or doc.get("kind") != "statejump_showcase":
        raise SchemaError("showcase 包 kind 须为 statejump_showcase")
    for key in ("game_id", "rom", "bizhawk", "base_state"):
        if not isinstance(doc.get(key), str) or not doc[key].strip():
            raise SchemaError(f"showcase 包缺 {key}")
    if not isinstance(doc.get("rom_sha1"), str) or not re.fullmatch(r"[0-9a-fA-F]{40}", doc["rom_sha1"]):
        raise SchemaError("showcase rom_sha1 须为明确的 40 位 SHA-1；仅有路径不能绑定游戏版本")
    platform = str(doc.get("platform", "NES")).upper()
    profile = PLATFORM_PROFILES.get(platform)
    if not profile:
        raise SchemaError(
            f"未知 platform={platform!r}（已建模: {sorted(PLATFORM_PROFILES)}）")
    core = doc.get("core")
    if core and core not in profile["cores"]:
        raise SchemaError(
            f"platform={platform} 不认 core={core!r}（允许 {sorted(profile['cores'])}）")
    system = doc.get("system")
    if system and str(system).upper() not in {s.upper() for s in profile["systems"]}:
        raise SchemaError(
            f"platform={platform} 不认 system={system!r}（允许 {sorted(profile['systems'])}）")
    fps = doc.get("fps", 60.0988)
    if not isinstance(fps, (int, float)) or fps <= 0:
        raise SchemaError("showcase fps 须为正数")
    sync = doc.get("sync_settings")
    if sync is not None and (
            not isinstance(sync, dict)
            or not all(isinstance(k, str) and isinstance(v, (str, bool))
                       for k, v in sync.items())):
        raise SchemaError("sync_settings 须为 str→str/bool 映射（控制器拓扑声明）")
    catalog = doc.get("catalog")
    if not isinstance(catalog, dict) or catalog.get("status") != "complete":
        raise SchemaError("catalog.status 须为 complete（清单调研未完成不得生产）")
    expected = catalog.get("expected_total")
    if type(expected) is not int or expected < 1:
        raise SchemaError("catalog.expected_total 须为正整数")
    if not isinstance(catalog.get("sources"), list) or not catalog["sources"]:
        raise SchemaError("catalog.sources 不能为空（完整清单须有调研来源）")
    elements = doc.get("elements")
    if not isinstance(elements, list) or not elements:
        raise SchemaError("showcase elements 不能为空")
    if len(elements) > expected:
        raise SchemaError("elements 数超过 catalog.expected_total")
    seen = set()
    for el in elements:
        eid = el.get("element_id")
        if not isinstance(eid, str) or not re.fullmatch(r"[a-z0-9_]+", eid):
            raise SchemaError(f"element_id 非法: {eid!r}")
        if eid in seen:
            raise SchemaError(f"element_id 重复: {eid}")
        seen.add(eid)
        if not el.get("label") or not el.get("kind"):
            raise SchemaError(f"{eid}: 缺 label/kind")
        delivery = el.get("delivery")
        if delivery is not None:
            if not isinstance(delivery, dict):
                raise SchemaError(f"{eid}: delivery 须为对象（交付缺口声明）")
            if delivery.get("status") not in GAP_STATUSES:
                raise SchemaError(
                    f"{eid}: delivery.status 须是 {sorted(GAP_STATUSES)} 之一，"
                    f"收到 {delivery.get('status')!r}")
            for key in GAP_FIELDS:
                if not isinstance(delivery.get(key), str) or not delivery[key].strip():
                    raise SchemaError(f"{eid}: delivery.{key} 不能为空（缺口要点名原因与批准）")
            if not isinstance(delivery.get("note"), str) or not delivery["note"].strip():
                raise SchemaError(f"{eid}: delivery.note 不能为空（缺的是哪一步要说清）")
        if ("base_state" in el and el["base_state"] is not None
                and (not isinstance(el["base_state"], str) or not el["base_state"].strip())):
            raise SchemaError(f"{eid}: base_state 须为非空路径字符串或 null")
        trigger = el.get("trigger")
        if not isinstance(trigger, dict):
            raise SchemaError(f"{eid}: 缺 trigger")
        macro = trigger.get("macro")
        if macro:
            SJ.parse_macro(macro, platform)
        extra = trigger.get("extra", 0)
        if type(extra) is not int or extra < 0:
            raise SchemaError(f"{eid}: trigger.extra 须为 >=0 整数")
        total = _macro_frames(macro, platform) + extra
        if total < 1:
            raise SchemaError(f"{eid}: 采集总帧数至少为 1")
        SJ._format_patches(trigger.get("patches") or [], platform)
        detection = el.get("detection")
        if not isinstance(detection, dict):
            raise SchemaError(f"{eid}: 缺 detection")
        frame = detection.get("frame")
        if type(frame) is not int or not 0 <= frame < total:
            raise SchemaError(f"{eid}: detection.frame 须落在 0..{total - 1}")
        specs = detection.get("success_checks")
        if not isinstance(specs, list) or not specs:
            raise SchemaError(f"{eid}: success_checks 不能为空")
        for raw in specs:
            check = CheckSpec(**raw).validate()
            if check.plugin_id not in detect.PLUGINS:
                raise SchemaError(f"{eid}: 未注册检测插件 {check.plugin_id}")
        _validate_acceptance(el, eid)
        negative = el.get("negative_control") or {}
        if not isinstance(negative, dict):
            raise SchemaError(f"{eid}: negative_control 须为对象")
        nmacro = negative.get("macro")
        if nmacro:
            SJ.parse_macro(nmacro, platform)
        if _macro_frames(nmacro, platform) > total:
            raise SchemaError(f"{eid}: 反例宏长于正例总帧数")
        SJ._format_patches(negative.get("patches") or [], platform)
    return doc


def load_spec(pack_path):
    return validate_spec(_load_json(pack_path))


def resolve_rom(pack_path, doc=None, rom_idx=None, netdisk_resolver=None):
    """知识包 pin 的是 ROM 哈希，路径只是提示。按 acquire 同口径找 ROM：
    包内路径（哈希相符）→ 本地 SHA-1 索引 → 门控网盘钩子。

    以前只认包内那条路径：ROM 挪盘或只在网盘时，整条 showcase 在 resolve 阶段就判死，
    和 auto 的获取链两套口径（11-14 修）。哈希不符一律 blocked，不拿错版本开跑——
    RAM 地址/导航是按某个版本标的，换版本出来的画面不能当验证证据。
    """
    doc = validate_spec(doc) if doc is not None else load_spec(pack_path)
    want = doc["rom_sha1"].upper()
    pinned = _resolve(pack_path, doc["rom"])
    blockers = []
    if Path(pinned).is_file():
        got = SJ.sha1_file(pinned)
        if got.upper() == want:
            return {"status": "ready", "rom": pinned, "source": "pack_path",
                    "required_sha1": want, "blockers": []}
        blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                         "reason": f"ROM 哈希不符：知识包声明 {want}，实际 {got.upper()}"
                                   f"（{pinned}）；请用同版本 ROM 或另开一份知识包"})
    else:
        blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                         "reason": f"包内 ROM 路径不存在: {pinned}"
                                   + (f"（改走哈希 {want} 查本地索引/网盘）" if want else "")})
    if rom_idx is None:
        from . import registry as R
        rom_idx = R.index_roms(R.DEFAULT_LIB)
    for hit in rom_idx.get(want, []):
        if Path(hit).is_file() and SJ.sha1_file(hit).upper() == want:
            return {"status": "ready", "rom": str(hit), "source": "local_index",
                    "required_sha1": want, "blockers": []}
        blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                         "reason": f"ROM 索引候选缺失或哈希不符: {hit}"})
    if netdisk_resolver is not None:
        got = netdisk_resolver(want, doc)
        if got and Path(got).is_file() and SJ.sha1_file(got).upper() == want:
            return {"status": "ready", "rom": str(got), "source": "own_netdisk",
                    "required_sha1": want, "blockers": []}
        blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                         "reason": "自有网盘未命中或哈希不符（用户门控；不自动抓商业全集）"})
    else:
        blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                         "reason": "自有网盘获取未配置（需用户登录 + 逐款门控后注入 resolver）"})
    return {"status": "blocked", "rom": None, "source": None,
            "required_sha1": want, "blockers": blockers}


def resource_paths(pack_path, doc=None):
    doc = doc or load_spec(pack_path)
    return {
        "rom": _resolve(pack_path, doc["rom"]),
        "bizhawk": _resolve(pack_path, doc["bizhawk"]),
        "base_state": _resolve(pack_path, doc["base_state"]),
        "element_base_states": {
            el["element_id"]: _resolve(pack_path, el["base_state"])
            for el in doc["elements"] if el.get("base_state")
        },
    }


def resource_files(pack_path, netdisk_resolver=None):
    doc = load_spec(pack_path)
    paths = resource_paths(pack_path, doc)
    res = resolve_rom(pack_path, doc, netdisk_resolver=netdisk_resolver)
    if res["status"] != "ready":
        raise SchemaError("showcase ROM 身份未通过，不能生成可复用指纹")
    files = [str(Path(pack_path).resolve()), res["rom"], paths["base_state"]]
    files.extend(paths["element_base_states"].values())
    if not all(Path(p).is_file() for p in files):
        raise SchemaError("showcase 指纹输入缺失（pack/ROM/base_state/要素 base_state）")
    return files


def _asset_state_blockers(pairs):
    """状态资产仓里的存档必须先在台账登记、且档位可消费，才许被知识包指为 base。

    11-15 实测踩坑：手工把 scratch 的 live.state 复制成 状态资产/live_possess.state 指进
    知识包，台账里没有这条资产，也没跑过球权闸门；实测量出载入即 dist=103px（1P 根本没球），
    六个要素的宏全在给无球人按 B —— 生产器照跑不误，只是永远出不了片。
    仓外路径（验证目录/scratch）不归本闸门管，免得把历史包全拦死。
    """
    out = []
    try:
        index = {}
        for p in SR.list_packages():
            doc = SR.load(p["game_id"], p["profile_id"], p["revision"])
            d = SR.package_dir(p["game_id"], p["profile_id"], p["revision"])
            for name, entry in (doc.get("states") or {}).items():
                key = str((d / entry["path"]).resolve()).replace("\\", "/").lower()
                index[key] = (f"{p['game_id']}/{p['profile_id']}/{p['revision']}#{name}",
                              p["status"])
        root = str(SR.ASSET_ROOT.resolve()).replace("\\", "/").lower()
    except Exception as e:
        return [{"code": FailureCode.MISSING_RESOURCE.value,
                 "reason": f"状态资产台账不可读（{type(e).__name__}: {e}），无法核对 base_state 出处"}]
    for label, raw in pairs:
        rp = str(Path(raw).resolve()).replace("\\", "/").lower()
        if not rp.startswith(root + "/"):
            continue
        hit = index.get(rp)
        if hit is None:
            out.append({"code": FailureCode.MISSING_RESOURCE.value,
                        "reason": f"{label} 落在状态资产仓里但台账无登记: {raw}"
                                  f"——用 statebuild --register 正式登记，或别放进资产仓"})
        elif hit[1] not in SR.CONSUMABLE:
            out.append({"code": FailureCode.MISSING_RESOURCE.value,
                        "reason": f"{label} 出处 {hit[0]} 当前档位 {hit[1]}，"
                                  f"未达可消费档位 {SR.CONSUMABLE}"})
    return out


def plan(pack_path, rom_idx=None, netdisk_resolver=None, audio=False):
    try:
        doc = load_spec(pack_path)
        paths = resource_paths(pack_path, doc)
    except SchemaError as e:
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                "blockers": [{"code": FailureCode.SCHEMA_INVALID.value, "reason": str(e)}]}
    blockers = []
    platform = str(doc.get("platform", "NES")).upper()
    profile = PLATFORM_PROFILES[platform]
    if not profile["verified"]:
        blockers.append({"code": FailureCode.UNSUPPORTED_CAPABILITY.value,
                         "reason": f"platform={platform} 后端未核验：{profile['note']}"})
    if audio:
        blockers.append({"code": FailureCode.UNSUPPORTED_CAPABILITY.value,
                         "reason": "showcase 逐帧采集尚无同步原声；audio=True 不得降级为无声视频"})
    if blockers:
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                "game_id": doc["game_id"], "elements": len(doc["elements"]),
                "platform": platform, "blockers": blockers}
    rom_res = resolve_rom(pack_path, doc, rom_idx=rom_idx,
                          netdisk_resolver=netdisk_resolver)
    blockers.extend(rom_res["blockers"])
    if rom_res["status"] == "ready":
        paths = dict(paths, rom=rom_res["rom"])
    if not Path(paths["base_state"]).is_file():
        blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                         "reason": f"base_state 不存在: {paths['base_state']}"})
    for eid, state in paths["element_base_states"].items():
        if not Path(state).is_file():
            blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                             "reason": f"要素 {eid} base_state 不存在: {state}"})
    blockers.extend(_asset_state_blockers(
        [("base_state", paths["base_state"])]
        + [(f"要素 {eid} base_state", s) for eid, s in paths["element_base_states"].items()]))
    if not (Path(paths["bizhawk"]) / "EmuHawk.exe").is_file():
        blockers.append({"code": FailureCode.MISSING_RESOURCE.value,
                         "reason": f"EmuHawk.exe 不存在: {paths['bizhawk']}"})
    expected = doc["catalog"]["expected_total"]
    if len(doc["elements"]) != expected:
        blockers.append({"code": FailureCode.SCHEMA_INVALID.value,
                         "reason": f"清单只 authoring {len(doc['elements'])}/{expected}；可用 --only 试跑，不能全量验收"})
    patch_elements = [el["element_id"] for el in doc["elements"] if el["trigger"].get("patches")]
    gaps = delivery_gaps(doc)
    system = doc.get("system") or sorted(PLATFORM_PROFILES[platform]["systems"])[0]
    core = doc.get("core") or sorted(PLATFORM_PROFILES[platform]["cores"])[0]
    return {"status": "blocked" if blockers else "ready",
            "verdict": Verdict.INCONCLUSIVE.value if blockers else Verdict.PASS.value,
            "game_id": doc["game_id"], "elements": len(doc["elements"]),
            "platform": platform, "system": system, "core": core,
            "patch_elements": patch_elements,
            "mechanism": "load_savestate_and_patch" if patch_elements else "load_savestate",
            "expected_total": expected, "required": expected - len(gaps),
            "delivery_gaps": sorted(gaps), "resources": paths, "blockers": blockers,
            "rom_source": rom_res["source"], "required_rom_sha1": rom_res["required_sha1"]}


def _png_complete(path):
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            f.seek(max(0, os.path.getsize(path) - 12))
            tail = f.read(12)
        return head == b"\x89PNG\r\n\x1a\n" and b"IEND" in tail
    except OSError:
        return False


def validate_frames(frames_dir, expected):
    frames_dir = Path(frames_dir)
    names = [f"f{i:04d}.png" for i in range(expected)]
    actual = sorted(p.name for p in frames_dir.glob("f*.png"))
    if actual != names:
        raise RuntimeError(f"帧序列不符: 期望 {expected} 张，实际 {len(actual)} 张")
    bad = [name for name in names if not _png_complete(frames_dir / name)]
    if bad:
        raise RuntimeError(f"PNG 不完整: {bad[:3]}")
    return [str(frames_dir / name) for name in names]


def _check_verdict(checks):
    values = [c.verdict for c in checks]
    if not values:
        return Verdict.INCONCLUSIVE
    if Verdict.FAIL in values:
        return Verdict.FAIL
    if Verdict.INCONCLUSIVE in values:
        return Verdict.INCONCLUSIVE
    return Verdict.PASS


def _zip_member_text(path, name="BizVersion.txt"):
    """读 .state(zip) 里的 BizVersion.txt —— 存这份存档的模拟器/核心实物身份。"""
    import zipfile
    try:
        with zipfile.ZipFile(str(path)) as archive:
            raw = archive.read(name)
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    return raw.decode("utf-8", "replace").strip() or None


def _detector_impl_sha():
    """判据实现字节指纹：detect.py 变了必须重判，但不该重录。"""
    return hashlib.sha256(Path(detect.__file__).with_suffix(".py").read_bytes()).hexdigest()


def _acceptance_impl_sha():
    source = "\n".join(inspect.getsource(fn) for fn in (
        acceptance_declaration, _validate_acceptance, _check_verdict,
        _pair_verdict, _acceptance_dimension, _capture_dimension,
        _acceptance_verdict, verify_detection,
    ))
    return hashlib.sha256(source.encode("utf-8")).hexdigest()



def capture_params(element, doc, platform, fps, state_path):
    """采集指纹参数：只列能改变录制像素的输入。

    `detection` 故意不在这里（计划书 §10.3）：改判据只重判，不许重录；
    反过来核心实物、初态出处、宏/补丁/帧数必须进键，换了就得重录。
    """
    trigger = element.get("trigger") or {}
    control = element.get("negative_control") or {}
    return {
        "macro": trigger.get("macro"), "extra": trigger.get("extra", 0),
        "patches": trigger.get("patches") or [],
        "negative_macro": control.get("macro"), "negative_patches": control.get("patches"),
        "fps": fps, "platform": platform,
        "core": doc.get("core", "NesHawk"), "system": doc.get("system", "NES"),
        "bizversion": _zip_member_text(state_path),
        "total_frames": _macro_frames(trigger.get("macro"), platform) + trigger.get("extra", 0),
    }


def judge_params(element):
    """判定指纹参数 = 候选判据 + 三类验收声明 + 各自实现字节。"""
    return {"detection": element["detection"],
            "acceptance": acceptance_declaration(element),
            "detector_impl": _detector_impl_sha(),
            "acceptance_impl": _acceptance_impl_sha()}


def _pair_verdict(pos, neg):
    pv, nv = _check_verdict(pos), _check_verdict(neg)
    if pv == Verdict.FAIL or nv == Verdict.PASS:
        verdict = Verdict.FAIL
    elif pv == Verdict.PASS and nv == Verdict.FAIL:
        verdict = Verdict.PASS
    else:
        verdict = Verdict.INCONCLUSIVE
    return verdict, pv, nv


def _acceptance_dimension(name, specs, positive_frame, negative_frame,
                          requirement="required", declared=True, paired=True,
                          positive_frames=None):
    if not declared:
        return {"requirement": requirement, "declared": False,
                "verdict": Verdict.INCONCLUSIVE.value, "checks": [],
                "reason": f"缺 {name} 验收声明"}
    if requirement == "not_applicable":
        return {"requirement": requirement, "declared": True,
                "verdict": Verdict.PASS.value, "checks": [],
                "reason": "要素作者显式声明效果不适用；不以缺检代替通过"}
    pos = [detect.run_check(s, positive_frame) for s in specs]
    if paired:
        neg = [detect.run_check(s, negative_frame) for s in specs]
        verdict, pv, nv = _pair_verdict(pos, neg)
        return {"requirement": requirement, "declared": True,
                "verdict": verdict.value, "scope": "checked_positive_and_negative_frame",
                "positive": {"verdict": pv.value, "checks": [to_dict(c) for c in pos]},
                "negative": {"verdict": nv.value, "rejected": nv == Verdict.FAIL,
                             "checks": [to_dict(c) for c in neg]}}
    pv = _check_verdict(pos)
    return {"requirement": requirement, "declared": True,
            "verdict": pv.value, "scope": "checked_positive_frame_only",
            "positive": {"verdict": pv.value, "checks": [to_dict(c) for c in pos]},
            "reason": "拍摄结论只覆盖显式检查的取证帧，不自动证明整段过程或声音同步"}


def _capture_dimension(specs, positive_frame, positive_frames):
    if positive_frames is None:
        return _acceptance_dimension("capture", specs, positive_frame, None, paired=False)
    if not positive_frames:
        return {"requirement": "required", "declared": True,
                "verdict": Verdict.INCONCLUSIVE.value, "checks": [],
                "reason": "拍摄检查缺正例帧序列"}
    results = [detect.run_check(spec, frame)
               for spec in specs for frame in positive_frames]
    verdict = _check_verdict(results)
    return {"requirement": "required", "declared": True,
            "verdict": verdict.value, "scope": "all_positive_frames",
            "checked_frames": len(positive_frames),
            "positive": {"verdict": verdict.value,
                         "checks": [to_dict(c) for c in results]},
            "reason": "拍摄检查覆盖全部正例帧；声音同步仍需独立音频能力，不以无声片代替"}


def _acceptance_verdict(dimensions):
    values = [Verdict(row["verdict"]) for row in dimensions.values()]
    if Verdict.FAIL in values:
        return Verdict.FAIL
    if Verdict.INCONCLUSIVE in values:
        return Verdict.INCONCLUSIVE
    return Verdict.PASS


def verify_detection(element, positive_frame, negative_frame, positive_frames=None):
    specs = element.get("detection", {}).get("success_checks", [])
    pos = [detect.run_check(s, positive_frame) for s in specs]
    neg = [detect.run_check(s, negative_frame) for s in specs]
    candidate, pv, nv = _pair_verdict(pos, neg)
    declared = any(key in element for key in ACCEPTANCE_FIELDS)
    dimensions = {
        "action": _acceptance_dimension(
            "action", element.get("action_checks", []), positive_frame, negative_frame,
            declared=declared),
        "effect": _acceptance_dimension(
            "effect", element.get("effect_checks", []), positive_frame, negative_frame,
            requirement=element.get("effect_requirement", "required"), declared=declared),
        "capture": (_capture_dimension(element.get("capture_checks", []),
                                       positive_frame, positive_frames)
                    if declared else _acceptance_dimension(
                        "capture", [], positive_frame, negative_frame, declared=False)),
    }
    return {
        "verdict": candidate.value,
        "candidate_only": True,
        "acceptance": {"verdict": _acceptance_verdict(dimensions).value,
                       "dimensions": dimensions},
        "positive": {"frame": positive_frame, "verdict": pv.value,
                     "checks": [to_dict(c) for c in pos]},
        "negative": {"frame": negative_frame, "verdict": nv.value,
                     "rejected": nv == Verdict.FAIL,
                     "checks": [to_dict(c) for c in neg]},
    }



def _concat_videos(clips, out_path, ffmpeg="ffmpeg"):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    listing = out_path.parent / "reel.concat.txt"
    listing.write_text("".join("file '" + str(Path(p).resolve()).replace("\\", "/").replace("'", "'\\''") + "'\n"
                               for p in clips), encoding="utf-8")
    proc = subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "concat", "-safe", "0",
                           "-i", str(listing), "-c", "copy", str(out_path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode or not out_path.is_file() or out_path.stat().st_size == 0:
        raise RuntimeError(f"合辑 concat 失败 rc={proc.returncode}: {(proc.stderr or '')[-400:]}")
    return str(out_path)


def _video_frames(path, ffprobe="ffprobe"):
    proc = subprocess.run([ffprobe, "-v", "error", "-count_frames", "-select_streams", "v:0",
                           "-show_entries", "stream=nb_read_frames", "-of", "json", str(path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode:
        return None
    try:
        value = json.loads(proc.stdout)["streams"][0].get("nb_read_frames")
        return int(value) if value is not None else None
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_json(path, doc):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def run(pack_path, out_dir, only=None, template=None, work_dir=None, fps=None,
        ffmpeg="ffmpeg", ffprobe="ffprobe", session_factory=None, encoder=None,
        composer=None, concatenator=None, audio=False, netdisk_resolver=None,
        bizhawk_dir=None):
    try:
        doc = load_spec(pack_path)
        paths = resource_paths(pack_path, doc)
    except SchemaError as e:
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                "blockers": [{"code": FailureCode.SCHEMA_INVALID.value, "reason": str(e)}]}
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    platform = str(doc.get("platform", "NES")).upper()
    expected_total = doc["catalog"]["expected_total"]
    by_id = {e["element_id"]: e for e in doc["elements"]}
    gaps = delivery_gaps(doc)
    required = expected_total - len(gaps)
    if required < 1:
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                "blockers": [{"code": FailureCode.SCHEMA_INVALID.value,
                              "reason": f"声明缺口 {len(gaps)} 个把必交要素清零"
                                        f"（expected_total={expected_total}）"}]}
    selected = list(only) if only else [eid for eid in by_id if eid not in gaps]
    unknown = [eid for eid in selected if eid not in by_id]
    if unknown or len(set(selected)) != len(selected):
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                "blockers": [{"code": FailureCode.SCHEMA_INVALID.value,
                              "reason": f"--only 未知或重复: {unknown or selected}"}]}
    pre = plan(pack_path, netdisk_resolver=netdisk_resolver, audio=audio)
    missing = [b for b in pre["blockers"] if not b["reason"].startswith("清单只 authoring")]
    if missing:
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value, "blockers": missing}
    paths = pre["resources"]
    if bizhawk_dir is not None:
        isolated = Path(bizhawk_dir).resolve()
        if not (isolated / "EmuHawk.exe").is_file():
            return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                    "blockers": [{"code": FailureCode.MISSING_RESOURCE.value,
                                  "reason": f"隔离 BizHawk 副本缺 EmuHawk.exe: {isolated}"}]}
        paths = dict(paths, bizhawk=str(isolated))
    if not only and len(selected) != required:
        return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                "blockers": [{"code": FailureCode.SCHEMA_INVALID.value,
                              "reason": f"全量运行需 {required} 个必交要素"
                                        f"（expected_total={expected_total}，"
                                        f"声明缺口 {sorted(gaps)}），当前只有 {len(selected)}"}]}
    if work_dir:
        try:
            SJ._path_arg(work_dir)
        except SchemaError as e:
            return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                    "blockers": [{"code": FailureCode.SCHEMA_INVALID.value,
                                  "reason": f"work_dir: {e}"}]}
        Path(work_dir).mkdir(parents=True, exist_ok=True)

    if platform == "NES":
        default_fps, default_core, default_system = 60.0988, "NesHawk", "NES"
        if session_factory is None:
            session_factory = SJ.StateSession
    else:
        from .retro_platforms import MultiPlatformStateSession, get_platform_spec
        p_spec = get_platform_spec(platform)
        default_fps, default_core, default_system = p_spec["fps"], p_spec["default_core"], p_spec["system"]
        if session_factory is None:
            def session_factory(rom, bizhawk, core=None, system=None, work=None):
                return MultiPlatformStateSession(
                    rom=rom, bizhawk=bizhawk, platform=platform,
                    core=core or default_core, system=system or default_system, work=work)
    fps = float(fps if fps is not None else doc.get("fps", default_fps))
    template = doc.get("template", "none") if template is None else template
    if encoder is None:
        import tas_replay
        encoder = tas_replay.encode_video
    if composer is None:
        from . import exporter
        composer = exporter.compose
    concatenator = concatenator or _concat_videos
    led = Ledger(str(out_dir / "ledger.json"))
    elements_dir = out_dir / "elements"
    evidence_dir = out_dir / "evidence"
    clips_dir = out_dir / "clips"
    controls_dir = out_dir / "controls"
    for directory in (elements_dir, evidence_dir, clips_dir, controls_dir):
        directory.mkdir(parents=True, exist_ok=True)

    # resolve_rom 已按知识包声明的 SHA-1 验过件（不符就 blocked），这里只留一份哈希给导出指纹。
    rom_sha1 = SJ.sha1_file(paths["rom"])

    # P1 拓扑闸门（说明书 §32.4）：profile 绑定同步设置控制器拓扑。
    # 声明层：包声明 sync_settings 时，启动模拟器前先核 config.ini，不符即拒。
    declared = doc.get("sync_settings")
    if declared:
        actual = SJ.read_sync_controls(paths["bizhawk"])
        diffs = {k: {"declared": v, "actual": (actual or {}).get(k)}
                 for k, v in declared.items() if (actual or {}).get(k) != v}
        if diffs:
            rep = {"match": False, "stage": "declaration",
                   "reason": f"sync_settings 声明与模拟器配置不符: {diffs}",
                   "declared": declared, "actual_controls": actual,
                   "bizhawk": str(paths["bizhawk"])}
            _write_json(evidence_dir / "state_profile_gate_declaration.json", rep)
            return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                    "blockers": [{"code": FailureCode.PROFILE_MISMATCH.value,
                                  "reason": rep["reason"]}],
                    "state_profile_gates": [rep]}

    # 实物层：零帧加载→回存→Core.bin 核对，按状态 sha 缓存，任何采集前执行。
    gate_reports = {}

    def gate_state(s, state_path):
        sha = hashlib.sha256(Path(state_path).read_bytes()).hexdigest()
        if sha not in gate_reports:
            try:
                rep = dict(s.check_state_profile(str(state_path)))
            except (RuntimeError, TimeoutError, SchemaError) as e:
                rep = {"match": False,
                       "reason": f"零帧加载/回存失败: {type(e).__name__}: {e}"}
            rep["state_sha256"] = sha
            rep["state_path"] = str(state_path)
            rep["bizhawk"] = str(paths["bizhawk"])
            rep["sync_controls"] = SJ.read_sync_controls(paths["bizhawk"])
            gate_reports[sha] = rep
            _write_json(evidence_dir / f"state_profile_gate_{sha[:12]}.json", rep)
        if not gate_reports[sha].get("match"):
            raise SJ.StateProfileMismatch(gate_reports[sha])
        return gate_reports[sha]

    session = None
    results = []

    def close_session():
        nonlocal session
        if session is not None:
            session.close()
            session = None

    try:
        with tempfile.TemporaryDirectory(prefix="tas_showcase_", dir=work_dir) as tmp:
            session_work = Path(tmp) / "session"
            base_copy = session_work / "base.state"

            def ensure_session():
                nonlocal session
                if session is None:
                    session_work.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(paths["base_state"], base_copy)
                    session = session_factory(paths["rom"], paths["bizhawk"],
                                              core=doc.get("core", default_core),
                                              system=doc.get("system", default_system),
                                              work=str(session_work))
                    session.start()
                    gate_state(session, base_copy)
                return session

            def capture(element, negative=False):
                trigger = element["trigger"]
                control = element.get("negative_control") or {}
                total = _macro_frames(trigger.get("macro"), platform) + trigger.get("extra", 0)
                macro = control.get("macro") if negative else trigger.get("macro")
                extra = total - _macro_frames(macro, platform)
                patches = (control["patches"] if negative and "patches" in control
                           else trigger.get("patches") or [])
                side = "negative" if negative else "positive"
                frames_dir = Path(tmp) / "frames" / element["element_id"] / side
                s = ensure_session()
                state = base_copy
                override = paths["element_base_states"].get(element["element_id"])
                if override:
                    state = session_work / f"{element['element_id']}.state"
                    shutil.copyfile(override, state)
                gate_state(s, state)
                returned = s.dump(str(frames_dir), spec=macro, extra=extra,
                                  state=str(state), patches=patches)
                if returned != total:
                    raise RuntimeError(f"dump 返回 {returned}，预期采集 {total} 帧")
                frames = validate_frames(frames_dir, total)
                detect_frame = frames[element["detection"]["frame"]]
                evidence = evidence_dir / f"{element['element_id']}_{side}.png"
                shutil.copyfile(detect_frame, evidence)
                retained_frames = [str(evidence)]
                if not negative:
                    retained_dir = evidence_dir / f"{element['element_id']}_positive_frames"
                    retained_dir.mkdir(parents=True, exist_ok=True)
                    retained_frames = []
                    for index, frame in enumerate(frames):
                        retained = retained_dir / f"f{index:04d}.png"
                        shutil.copyfile(frame, retained)
                        retained_frames.append(str(retained))
                clip = (controls_dir / f"{element['element_id']}_negative.mp4" if negative
                        else clips_dir / f"{element['element_id']}.mp4")
                encoder(str(frames_dir), fps, str(clip), ffmpeg=ffmpeg)
                if not clip.is_file() or clip.stat().st_size == 0:
                    raise RuntimeError(f"编码产物缺失: {clip}")
                return str(clip), str(evidence), retained_frames

            profile_abort = None
            for eid in selected:
                element = by_id[eid]
                element_base = paths["element_base_states"].get(eid, paths["base_state"])
                cap_fp = fingerprint([paths["rom"], element_base],
                                     capture_params(element, doc, platform, fps, element_base))
                result_path = elements_dir / f"{eid}.json"
                reuse = led.reusable("capture", eid, cap_fp)
                if reuse:
                    cap_result = json.loads(result_path.read_text(encoding="utf-8"))
                    evidence = cap_result.get("evidence_ref") or {
                        "positive": cap_result["detection"]["positive"]["frame"],
                        "negative": cap_result["detection"]["negative"]["frame"]}
                    if not evidence.get("positive_frames"):
                        reuse = None
                if not reuse:
                    job = led.register("capture", eid, cap_fp)
                    try:
                        positive_clip, positive_evidence, positive_frames = capture(element, negative=False)
                        negative_clip, negative_evidence, _ = capture(element, negative=True)
                        evidence = {"positive": positive_evidence, "negative": negative_evidence,
                                    "positive_frames": positive_frames}
                        cap_result = {
                            "element_id": eid, "label": element["label"], "kind": element["kind"],
                            "state_origin": "display_patch" if element["trigger"].get("patches") else "normal_prefix",
                            "total_frames": _macro_frames(element["trigger"].get("macro"), platform) + element["trigger"].get("extra", 0),
                            "clip_ref": positive_clip, "negative_clip_ref": negative_clip,
                            "evidence_ref": evidence,
                        }
                        _write_json(result_path, cap_result)
                        # 采集条目只对"录到了规定帧数且画面完整"负责；要素过没过归判定条目。
                        led.complete(job, [positive_clip, negative_clip,
                                          positive_evidence, negative_evidence,
                                          *positive_frames], Verdict.PASS.value)
                    except SJ.StateProfileMismatch as e:
                        profile_abort = e.report
                        break
                    except Exception as e:
                        cap_result = {"element_id": eid, "label": element["label"],
                                      "kind": element["kind"], "verdict": Verdict.FAIL.value,
                                      "error": f"{type(e).__name__}: {e}"}
                        _write_json(result_path, cap_result)
                        led.fail(job, FailureCode.UNSUPPORTED_CAPABILITY, cap_result["error"])

                if "error" not in cap_result:
                    # 判定独立成条：判据/判据实现变了只重判这两张证据图，不重录（计划书 §10.3）。
                    judge_fp = fingerprint(evidence["positive_frames"] + [evidence["negative"]],
                                           judge_params(element))
                    if not led.reusable("verify", eid, judge_fp):
                        vjob = led.register("verify", eid, judge_fp, deps=[f"capture:{eid}"])
                        detection = verify_detection(element, evidence["positive"],
                                                     evidence["negative"],
                                                     positive_frames=evidence["positive_frames"])
                        cap_result["detection"] = detection
                        cap_result["verdict"] = detection["acceptance"]["verdict"]
                        _write_json(result_path, cap_result)
                        if cap_result["verdict"] == Verdict.FAIL.value:
                            led.fail(vjob, FailureCode.CAPTURE_WRONG_SEGMENT,
                                     f"{eid}: 动作/效果/拍摄至少一项失败")
                        else:
                            led.complete(vjob, [str(result_path)], cap_result["verdict"])

                result = dict(cap_result)
                result["deliverable_ref"] = None
                result["export_verdict"] = Verdict.INCONCLUSIVE.value
                if cap_result.get("verdict") == Verdict.PASS.value:
                    if template in (None, "", "none", "raw"):
                        result["deliverable_ref"] = cap_result["clip_ref"]
                        result["export_verdict"] = Verdict.PASS.value
                    else:
                        bordered = clips_dir / f"{eid}_bordered.mp4"
                        exp_fp = fingerprint([cap_result["clip_ref"]],
                                             {"template": template, "rom_sha1": rom_sha1})
                        reuse_e = led.reusable("export", eid, exp_fp)
                        if reuse_e:
                            result["deliverable_ref"] = str(bordered)
                            result["export_verdict"] = reuse_e["verification_verdict"]
                        else:
                            exp_job = led.register("export", eid, exp_fp, deps=[f"capture:{eid}"])
                            try:
                                composed = composer(cap_result["clip_ref"], str(bordered),
                                                    rom_sha1=rom_sha1, template=template,
                                                    ffmpeg=ffmpeg, ffprobe=ffprobe)
                                ev = composed["verification"]["verdict"]
                                result["export_verdict"] = ev
                                if ev == Verdict.FAIL.value or not bordered.is_file():
                                    led.fail(exp_job, FailureCode.CAPTURE_WRONG_SEGMENT,
                                             f"{eid}: export verdict={ev}")
                                else:
                                    result["deliverable_ref"] = str(bordered)
                                    led.complete(exp_job, [str(bordered)], ev)
                            except Exception as e:
                                result["export_verdict"] = Verdict.FAIL.value
                                result["export_error"] = f"{type(e).__name__}: {e}"
                                led.fail(exp_job, FailureCode.UNSUPPORTED_CAPABILITY, result["export_error"])
                results.append(result)
            # 会话必须在临时目录退出前关掉：EmuHawk 还握着 session/heartbeat.txt 时，
            # TemporaryDirectory 的清理在 Windows 上直接 PermissionError，把已经采好的
            # 五格结果连带合辑一起打断（11-14 实测：要素全 pass，reel 却没生成）。
            close_session()
            if profile_abort is not None:
                return {"status": "blocked", "verdict": Verdict.INCONCLUSIVE.value,
                        "blockers": [{"code": FailureCode.PROFILE_MISMATCH.value,
                                      "reason": profile_abort.get("reason", "state profile mismatch"),
                                      "state_sha256": profile_abort.get("state_sha256"),
                                      "first_diff_offset": profile_abort.get("first_diff_offset"),
                                      "content_fingerprint": profile_abort.get("content_fingerprint")}],
                        "state_profile_gates": list(gate_reports.values())}
    finally:
        close_session()

    full_coverage = not only and len(selected) == required
    passed = sum(1 for r in results
                 if r.get("verdict") == Verdict.PASS.value
                 and r.get("export_verdict") == Verdict.PASS.value)
    dimension_counts = {
        name: sum(1 for r in results
                  if r.get("detection", {}).get("acceptance", {}).get(
                      "dimensions", {}).get(name, {}).get("verdict") == Verdict.PASS.value)
        for name in ("action", "effect", "capture")
    }
    hard_fail = any(r.get("verdict") == Verdict.FAIL.value
                    or r.get("export_verdict") == Verdict.FAIL.value for r in results)
    deliverable = None
    reel_verdict = Verdict.INCONCLUSIVE.value
    if full_coverage and passed == required:
        reel = out_dir / "reel.mp4"
        clips = [r["deliverable_ref"] for r in results]
        # 事件窗口：合辑是逐格首尾相接出来的，所以每格在合辑里的帧区间可以精确算出来。
        # 解说工厂拿它排章节、把逐句字幕对到具体要素上，不需要再猜时间轴。
        seg_frames = [_video_frames(p, ffprobe) for p in clips]
        cursor, windows = 0, []
        for r, n in zip(results, seg_frames):
            if n is None:
                continue
            r["reel_window"] = {
                "start_frame": cursor, "end_frame": cursor + n,
                "start_seconds": round(cursor / fps, 4),
                "end_seconds": round((cursor + n) / fps, 4),
                "event_frame": cursor + _element_detect_frame(doc, r["element_id"]),
                "event_seconds": round((cursor + _element_detect_frame(doc, r["element_id"])) / fps, 4),
            }
            windows.append(r["reel_window"])
            cursor += n
        reel_fp = fingerprint(clips, {"kind": "statejump_showcase_reel", "fps": fps})
        reuse_r = led.reusable("export", "reel", reel_fp)
        if reuse_r:
            deliverable = str(reel)
            reel_verdict = reuse_r["verification_verdict"]
        else:
            reel_job = led.register("export", "reel", reel_fp,
                                    deps=[f"export:{r['element_id']}" for r in results])
            try:
                concatenator(clips, str(reel), ffmpeg=ffmpeg)
                actual = seg_frames + [_video_frames(str(reel), ffprobe)]
                if all(v is not None for v in actual):
                    reel_verdict = (Verdict.PASS.value if actual[-1] == sum(actual[:-1])
                                    else Verdict.FAIL.value)
                deliverable = str(reel)
                if reel_verdict == Verdict.FAIL.value:
                    led.fail(reel_job, FailureCode.CAPTURE_WRONG_SEGMENT,
                             f"reel 帧数={actual[-1]}，分段和={sum(actual[:-1])}")
                else:
                    led.complete(reel_job, [str(reel)], reel_verdict)
            except Exception as e:
                reel_verdict = Verdict.FAIL.value
                led.fail(reel_job, FailureCode.CAPTURE_WRONG_SEGMENT,
                         f"{type(e).__name__}: {e}")
    complete = bool(full_coverage and passed == required
                    and reel_verdict == Verdict.PASS.value and deliverable)
    full_collection = bool(complete and passed == expected_total)
    verdict = (Verdict.PASS.value if complete else Verdict.FAIL.value
               if hard_fail or reel_verdict == Verdict.FAIL.value else Verdict.INCONCLUSIVE.value)
    report = {
        "status": "done" if complete else "partial",
        "verdict": verdict, "game_id": doc["game_id"],
        "coverage": {"authored": len(doc["elements"]), "selected": len(selected),
                     "expected_total": expected_total, "required": required,
                     "delivered": passed, "full_collection": full_collection,
                     "acceptance_passed": dimension_counts,
                     "gaps": [{"element_id": eid, "status": gap["status"],
                               "reason": gap["reason"], "note": gap["note"],
                               "decided_by": gap["decided_by"],
                               "decided_on": gap["decided_on"]}
                              for eid, gap in sorted(gaps.items())]},
        "passed": passed, "total": expected_total, "elements": results,
        "deliverable_ref": deliverable if complete else None,
        "preview_ref": deliverable if deliverable and not complete else None,
        "reel_verdict": reel_verdict, "ledger": led.summary(),
        "state_profile_gates": list(gate_reports.values()),
        "note": "候选像素判据不等于正式验收；动作、效果、拍摄三类检查独立判定，"
                "效果不适用须显式声明，任一缺检或 inconclusive 均不交付。"
                "拍摄检查覆盖全部正例帧，不自动证明声音同步；audio=True 仍由平台能力闸拒绝。"
                "合辑只在必交要素（expected_total 减去已声明缺口）三类验收过、反例拒、导出过后生成；"
                "coverage.full_collection=False 表示清单仍有未出片要素，此时产物是缺口版而非全量，"
                "缺口逐条点名在 coverage.gaps，不许靠改 expected_total 或删要素掩盖",
    }
    _write_json(out_dir / "showcase_report.json", report)
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--pack", required=True)
        if name == "run":
            p.add_argument("--out", required=True)
            p.add_argument("--only", default=None, help="逗号分隔 element_id；只试跑，不算全量完成")
            p.add_argument("--template", default=None, help="none/raw 或 exporter 模板名")
            p.add_argument("--work", default=None, help="ASCII 临时目录；子目录结束自动清理")
            p.add_argument("--ffmpeg", default="ffmpeg")
            p.add_argument("--ffprobe", default="ffprobe")
    args = ap.parse_args()
    if args.cmd == "plan":
        result = plan(args.pack)
    else:
        only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else None
        result = run(args.pack, args.out, only=only, template=args.template,
                     work_dir=args.work, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get("status") in ("ready", "done") else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
