"""输入分流：只读扫描一个目录或文件，判定该走哪条移植路线。

这里只读文件头、文件名与目录结构，不解压、不执行、不加载任何游戏程序。
判定给出路线、证据、阻断与下一命令；它既不是执行授权，也不是成品资格等级。
"""
from __future__ import annotations

import json
import os
import zipfile
from collections import deque
from pathlib import Path

from ..sniff import sniff_file
from . import draft

MAX_DEPTH = 3
MAX_FILES = 4000
MAX_LINKS = 5
MAX_SNIFF = 64
MAX_SIGNALS = 40
MAX_PER_KIND = 6
MAX_ZIP_ENTRIES = 500

SKIP_DIRS = {".git", ".svn", ".hg", "node_modules", "_cache", "__pycache__",
             "build", "dist", "obj", "target", ".venv", "venv"}

BUILD_FILES = {
    "cmake": ("cmakelists.txt",),
    "meson": ("meson.build",),
    "autotools": ("configure", "configure.ac", "configure.in", "makefile.am"),
    "make": ("makefile", "gnumakefile"),
    "gradle": ("build.gradle", "build.gradle.kts", "settings.gradle",
               "settings.gradle.kts"),
    "cargo": ("cargo.toml",),
    "godot": ("project.godot",),
    "unity": ("assembly-csharp.csproj",),
}
BUILD_INDEX = {name: key for key, names in BUILD_FILES.items() for name in names}

DECOMP_FILES = {"symbols.txt", "splits.txt", "objdiff.json"}
DECOMP_DIRS = {"asm", "expected", "orig"}

SOURCE_EXTS = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx",
               ".rs", ".go", ".cs", ".java", ".kt", ".gd", ".lua", ".swift",
               ".m", ".mm"}

DATA_EXTS = {".grp", ".rts", ".mix", ".mpq", ".wad", ".pk3", ".pk4", ".bsa",
             ".ba2", ".dat", ".pak", ".swan", ".iwd", ".vl2", ".vpk", ".assets",
             ".bundle", ".rpa", ".big", ".hog", ".lvl", ".res", ".pod", ".arc"}

ROM_EXTS = {".nes", ".sfc", ".smc", ".gb", ".gbc", ".gba", ".nds", ".3ds",
            ".cia", ".n64", ".z64", ".v64", ".gen", ".sms", ".gg", ".pce",
            ".iso", ".gcm", ".rvz", ".wbfs", ".cso", ".cue", ".chd", ".pbp",
            ".xiso"}

ARCHIVE_EXTS = {".zip", ".apk", ".7z", ".rar", ".tar", ".gz", ".tgz", ".xz", ".bz2"}

BINARY_SNIFF_EXTS = {".exe", ".dll", ".sys", ".nro", ".nsp", ".xci", ".elf",
                     ".so", ".dylib", ".xex", ".xbe", ".dol", ".pkg", ".bin"}

ROUTE_TITLES = {
    "B-source": "源码移植（B）",
    "B-recomp": "反编译重建（B）",
    "A1-ghidra": "二进制逆向（A1）",
    "A2-rexglue": "Xbox 360 重编译（A2）",
    "data-only": "只有游戏数据",
    "existing-artifact": "现有自制程序制品",
    "emulation": "模拟器路线（不是原生移植）",
    "android-apk": "Android 安装包",
    "archive": "压缩包（尚未解压）",
    "unrouted": "无法判定",
}

LIMITS = [
    "只读扫描：不执行、不加载、不解压任何输入文件。",
    "判定不等于授权：安装 Ghidra/ReXGlue、真机部署与发布仍需单独授权。",
    "判定不等于资格等级：R0–R6 只由 `port status` 依据构建与运行记录评估。",
    f"扫描有界：最多 {MAX_DEPTH} 层、{MAX_FILES} 个文件，跳过链接与 build 类目录；结果可能不完整。",
]

A1_BLOCKER = ("Ghidra/JDK 21 与 GhidraMCP 尚未安装或未获授权（P1-A 未接入）；"
              "当前只能走自研 Capstone 的函数级研究，不能自动导出完整游戏工程。")
A2_BLOCKER = "ReXGlue 与 Xbox 360 运行时尚未接入，也没有取得安装/使用授权。"


class _Entry:
    __slots__ = ("rel", "path", "depth")

    def __init__(self, rel: str, path: Path, depth: int):
        self.rel = rel
        self.path = path
        self.depth = depth


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    checker = getattr(path, "is_junction", None)
    try:
        return bool(checker and checker())
    except OSError:
        return True


def _walk(root: Path) -> dict:
    files: list[_Entry] = []
    dirs: list[str] = []
    links: list[str] = []
    truncated = depth_limited = False
    queue = deque([(root, 0)])
    while queue and not truncated:
        base, depth = queue.popleft()
        try:
            with os.scandir(base) as listing:
                entries = sorted(listing, key=lambda item: item.name.lower())
        except OSError:
            continue
        for entry in entries:
            path = Path(entry.path)
            if _is_link(path):
                if len(links) < MAX_LINKS:
                    links.append(_rel(path, root))
                continue
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                continue
            if is_dir:
                if entry.name.lower() in SKIP_DIRS:
                    continue
                if depth + 1 > MAX_DEPTH:
                    depth_limited = True
                    continue
                dirs.append(_rel(path, root))
                queue.append((path, depth + 1))
            elif is_file:
                if len(files) >= MAX_FILES:
                    truncated = True
                    break
                files.append(_Entry(_rel(path, root), path, depth + 1))
    return {"files": files, "dirs": dirs, "truncated": truncated,
            "depth_limited": depth_limited, "links": links}


def _sniff(path: Path) -> dict | None:
    try:
        return sniff_file(path)
    except (OSError, ValueError, TypeError):
        return None


def _zip_names(path: Path) -> list[str] | None:
    try:
        if path.stat().st_size > 2**31:
            return None
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()[:MAX_ZIP_ENTRIES]
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError):
        return None


def _signal(kind: str, path: str, note: str = "") -> dict:
    return {"kind": kind, "path": path, "note": note}


def _collect(root: Path, tree: dict) -> dict:
    build: list[dict] = []
    decomp: list[dict] = []
    sources: list[dict] = []
    data: list[dict] = []
    archives: list[dict] = []
    binaries: list[dict] = []
    roms: list[dict] = []
    artifacts: list[dict] = []
    cautions: list[str] = []
    apk = False
    sniffed = 0
    archive_seen: set[str] = set()
    rom_seen: set[str] = set()

    for rel_dir in tree["dirs"]:
        name = rel_dir.rsplit("/", 1)[-1].lower()
        if name in DECOMP_DIRS and rel_dir.count("/") <= 1 and len(decomp) < MAX_PER_KIND:
            decomp.append(_signal("decomp", rel_dir + "/", "反编译工程目录"))

    for entry in sorted(tree["files"], key=lambda item: (item.depth, item.rel.lower())):
        lower = entry.path.name.lower()
        suffix = entry.path.suffix.lower()

        if lower in BUILD_INDEX and len(build) < MAX_PER_KIND:
            build.append(_signal("build", entry.rel, BUILD_INDEX[lower]))
        elif lower.endswith((".sln", ".vcxproj", ".csproj")) and len(build) < MAX_PER_KIND:
            build.append(_signal("build", entry.rel, "msbuild"))

        if lower in DECOMP_FILES and len(decomp) < MAX_PER_KIND:
            decomp.append(_signal("decomp", entry.rel, lower))

        if suffix in SOURCE_EXTS and len(sources) < MAX_PER_KIND:
            sources.append(_signal("source", entry.rel, suffix.lstrip(".")))

        if suffix in DATA_EXTS and len(data) < MAX_PER_KIND:
            data.append(_signal("data", entry.rel, suffix.lstrip(".")))

        if suffix in ROM_EXTS and entry.rel not in rom_seen and len(roms) < MAX_PER_KIND:
            rom_seen.add(entry.rel)
            roms.append(_signal("rom", entry.rel, suffix.lstrip(".")))

        if (suffix in ARCHIVE_EXTS or lower.endswith(".tar.gz")) and entry.rel not in archive_seen:
            archive_seen.add(entry.rel)
            record = _signal("archive", entry.rel, suffix.lstrip(".") or "tar.gz")
            if suffix in {".zip", ".apk"} and len(archives) < 3:
                names = _zip_names(entry.path)
                if names is not None:
                    record["entries"] = len(names)
                    flat = [name.lower().rsplit("/", 1)[-1] for name in names]
                    if "androidmanifest.xml" in flat and "classes.dex" in flat:
                        apk = True
                        record["note"] = "Android APK"
                    inner = sorted(set(flat) & set(BUILD_INDEX))
                    if inner:
                        record["note"] = ((record.get("note", "") + "；包内 " +
                                           "、".join(inner)).strip("；"))
                    for name in names:
                        if name.lower().endswith((".exe", ".nro", ".xex")):
                            record["note"] = (record.get("note", "") +
                                              f"；包内含 {name}").strip("；")
                            break
            if len(archives) < MAX_PER_KIND:
                archives.append(record)

        if (suffix in BINARY_SNIFF_EXTS or lower in {"default.xex", "default.xbe",
                                                     "eboot.bin"}) and sniffed < MAX_SNIFF:
            sniffed += 1
            info = _sniff(entry.path)
            if info is None:
                cautions.append(f"无法读取文件头：{entry.rel}")
                continue
            fmt = info.get("format")
            arch = info.get("arch")
            record = _signal("binary", entry.rel, f"{fmt} / {arch or '未知架构'}")
            record["format"] = fmt
            if fmt == "switch-nro":
                record["kind"] = "artifact"
                artifacts.append(record)
            elif fmt in ("switch-nsp", "switch-xci", "iso9660", "psp-pbp"):
                if entry.rel not in rom_seen and len(roms) < MAX_PER_KIND:
                    record["kind"] = "rom"
                    roms.append(record)
            elif fmt in ("pe", "mz-dos", "elf", "xbox360-xex", "xbox-xbe",
                         "gamecube-dol", "ps4-pkg"):
                if len(binaries) < MAX_PER_KIND:
                    binaries.append(record)
            elif fmt in ("zip", "rar", "7z"):
                if entry.rel not in archive_seen and len(archives) < MAX_PER_KIND:
                    archives.append(record)
            elif suffix == ".nro":
                cautions.append(f"{entry.rel} 的扩展名像 NRO，但魔数不匹配")
            elif suffix in {".exe", ".elf", ".so", ".dll"}:
                cautions.append(f"{entry.rel} 的扩展名像可执行文件，但文件头未识别")

    license_info = {"engine": "unknown", "file": None}
    if root.is_dir():
        license_info = draft.detect_license(root)

    return {"build": build, "decomp": decomp, "sources": sources, "data": data,
            "archives": archives, "binaries": binaries, "roms": roms,
            "artifacts": artifacts, "cautions": cautions, "apk": apk,
            "license": license_info}


def _route(parts: dict) -> str:
    if parts["artifacts"] and not parts["sources"] and not parts["build"] \
            and not parts["decomp"] and not parts["binaries"]:
        return "existing-artifact"
    if parts["decomp"]:
        return "B-recomp"
    if parts["sources"] or parts["build"]:
        return "B-source"
    if parts["binaries"]:
        formats = {item.get("format") for item in parts["binaries"]}
        if "xbox360-xex" in formats:
            return "A2-rexglue"
        return "A1-ghidra"
    if parts["apk"]:
        return "android-apk"
    if parts["roms"]:
        return "emulation"
    if parts["data"]:
        return "data-only"
    if parts["archives"]:
        return "archive"
    return "unrouted"


def _first_binary(root: Path, parts: dict, path: Path) -> Path:
    if path.is_file():
        return path
    if parts["binaries"]:
        return root / parts["binaries"][0]["path"]
    if parts["artifacts"]:
        return root / parts["artifacts"][0]["path"]
    return root


def _next_steps(route_id: str, root: Path, parts: dict, path: Path) -> list[str]:
    quoted = f'"{path.as_posix()}"'
    if route_id == "B-source":
        return [
            f"py -3 工厂.py port new {quoted} --id <游戏id>",
            "py -3 工厂.py port plan specs/<游戏id>.json --target handheld",
            "py -3 工厂.py port build specs/<游戏id>.json --target handheld --work F:/_scratch/portkit",
            "py -3 工厂.py port status specs/<游戏id>.json --target handheld --work F:/_scratch/portkit",
        ]
    if route_id == "B-recomp":
        return [
            f"py -3 工厂.py port new {quoted} --id <游戏id>",
            "把 configure.py / ninja 等真实构建命令写进 build.commands，再用 port build",
            "py -3 工厂.py port status specs/<游戏id>.json --target handheld --work F:/_scratch/portkit",
        ]
    if route_id == "A1-ghidra":
        target = _first_binary(root, parts, path).as_posix()
        return [
            f'py -3 工厂.py research new "{target}" --target switch-homebrew',
            "py -3 工厂.py research analyze <run_id>",
            "完整工程导出需先获得授权安装 JDK 21 + Ghidra + GhidraMCP（P1-A）",
        ]
    if route_id == "A2-rexglue":
        return [
            "用 ReXGlue 把 default.xex 生成 C++ 工程（工具未接入，需单独授权）",
            "工程生成后按 B-source 走 port draft / port build",
            "重编译产物仍需真机验收，不能把生成工程当成品",
        ]
    if route_id == "existing-artifact":
        target = _first_binary(root, parts, path).as_posix()
        return [
            f'py -3 工厂.py game intake "{target}" --name <游戏名>',
            "这只是登记与指纹，不是移植；要原生移植仍需源码或可重建工程",
            "真机验收（R5）与发布（R6）不会因这个制品自动通过",
        ]
    if route_id == "data-only":
        return [
            "找到该游戏的引擎源码或原作者程序，放到 F 盘独立快照后重新扫描",
            "若它是某个开源重制工程的商业数据，按该工程源码走 B-source",
        ]
    if route_id == "emulation":
        return [
            "确认目标设备是否有可用模拟器前端；那属于另一条产品线",
            "本工厂不把模拟器前端当原生移植，也不会自动打包 ROM",
        ]
    if route_id == "android-apk":
        return [
            "解包检查 lib/ 原生库与 assets/（本工厂不自动解包）",
            "Android 目标尚未接入；需要源码或按目标平台原生重写",
        ]
    if route_id == "archive":
        return [
            "手工解压到 F 盘独立快照（本工厂不自动解压）",
            '对解压后的目录重新运行 py -3 工厂.py port route "<解压目录>"',
        ]
    return [
        "确认输入是否为游戏目录、原版程序或压缩包",
        "提供源码目录或原版可执行文件后重新扫描",
    ]


def _blockers(route_id: str) -> list[str]:
    return {
        "A1-ghidra": [A1_BLOCKER],
        "A2-rexglue": [A2_BLOCKER],
        "existing-artifact": ["已有制品只能登记、校验与封装检查，不能算移植；真机验收仍为零。"],
        "data-only": ["只有游戏数据，缺少引擎源码或可分析的原版程序，无法自动构建原生移植。"],
        "android-apk": ["Android 目标尚未接入；APK 不能直接变成 Switch/掌机原生程序。"],
        "archive": ["压缩包未被解压或扫描内部；本工厂不会自动解压。"],
        "emulation": ["模拟器不是目标平台原生程序；本工厂不把模拟器前端当移植成品。"],
        "unrouted": ["没有识别出源码、可分析程序、数据或可识别的制品。"],
    }.get(route_id, [])


def _cautions(route_id: str, parts: dict, path: Path) -> list[str]:
    notes = list(parts["cautions"])
    if parts["license"]["engine"] == "unknown" and path.is_dir():
        notes.append("未识别到许可文件：先确认引擎与素材许可，再决定能否随包分发。")
    if parts["data"] and route_id in ("B-source", "B-recomp", "A1-ghidra", "A2-rexglue"):
        notes.append("检测到游戏数据：数据政策需在 spec 里声明（bundled / free-download / user-supplied）。")
    if route_id == "B-source" and not parts["build"]:
        notes.append("没有识别到构建入口，需要手写 build.commands。")
    if route_id == "B-recomp":
        notes.append("反编译工程必须使用匹配版本的原版数据与编译器；符号/地址对不上就不算重建成功。")
        if not parts["build"]:
            notes.append("有反编译信号但没有构建入口，需要先确认构建方式。")
    if route_id == "A1-ghidra":
        if parts["data"]:
            notes.append("需要原版数据配合运行；成品包的数据政策要单独声明。")
        formats = {item.get("format") for item in parts["binaries"]}
        if "elf" in formats:
            notes.append("ELF 可能是 Linux 二进制或目标架构制品；来源与架构可核实时可另行评估现有制品封装。")
        if "gamecube-dol" in formats:
            notes.append("GameCube/Wii 重编译路线尚未接入。")
        if "ps4-pkg" in formats:
            notes.append("PS4 PKG 通常有加密，先确认能否合法解包。")
    if route_id == "existing-artifact":
        notes.append("若是商业游戏的自制加载器/前端，仍需数据与授权边界单独确认。")
    if route_id == "archive" and parts["data"]:
        notes.append("压缩包旁边已有散装数据，未解压的包可能重复或过期。")
    return notes


def scan(path: str | Path) -> dict:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"输入不存在：{target}")
    if not target.is_file() and not target.is_dir():
        raise ValueError(f"只接受目录或普通文件：{target}")
    root = target.resolve()
    if root.is_file():
        if _is_link(target):
            raise ValueError(f"不接受链接：{target}")
        tree = {"files": [_Entry(root.name, root, 0)],
                "dirs": [], "truncated": False, "depth_limited": False, "links": []}
    else:
        tree = _walk(root)

    parts = _collect(root, tree)
    route_id = _route(parts)
    groups = [parts[key] for key in ("build", "decomp", "sources", "data",
                                     "binaries", "roms", "artifacts", "archives")]
    found = sum(1 for group in groups if group)
    confidence = "high" if found >= 2 else "medium" if found == 1 else "low"

    signals: list[dict] = []
    for key in ("build", "decomp", "sources", "data", "binaries", "roms",
                "artifacts", "archives"):
        signals.extend(parts[key])
    if parts["license"]["file"]:
        signals.append(_signal("license", parts["license"]["file"],
                               parts["license"]["engine"]))
    if len(signals) > MAX_SIGNALS:
        signals = signals[:MAX_SIGNALS] + [_signal("scan", "", "证据超过上限，已截断")]

    return {
        "schema": 1,
        "scanned": {
            "path": str(root),
            "kind": "dir" if root.is_dir() else "file",
            "files": len(tree["files"]),
            "dirs": len(tree["dirs"]),
            "truncated": tree["truncated"] or tree["depth_limited"],
            "links_skipped": tree["links"],
        },
        "route": route_id,
        "title": ROUTE_TITLES[route_id],
        "confidence": confidence,
        "signals": signals,
        "blockers": _blockers(route_id),
        "cautions": _cautions(route_id, parts, root),
        "next_steps": _next_steps(route_id, root, parts, target if target.is_file() else root),
        "limits": LIMITS,
    }


def to_json(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2) + "\n"


_CONFIDENCE = {"high": "高", "medium": "中", "low": "低"}
_KINDS = {"build": "构建入口", "decomp": "反编译信号",
          "source": "源码", "data": "游戏数据", "binary": "可执行文件",
          "artifact": "自制程序制品",
          "rom": "镜像/ROM", "archive": "压缩包", "license": "许可",
          "scan": "扫描"}


def render(result: dict) -> str:
    scanned = result["scanned"]
    kind = "目录" if scanned["kind"] == "dir" else "文件"
    lines = [
        f"# 路线判定：{result['title']}",
        "",
        f"- 扫描对象：`{scanned['path']}`（{kind}）",
        f"- 路线：**{result['route']} {result['title']}**",
        f"- 置信度：{_CONFIDENCE[result['confidence']]}",
        f"- 扫描：{scanned['files']} 个文件 / {scanned['dirs']} 个目录"
        + ("（已截断）" if scanned["truncated"] else ""),
    ]
    if scanned["links_skipped"]:
        lines.append("- 跳过链接：" + "、".join(f"`{item}`" for item in scanned["links_skipped"]))
    if result["signals"]:
        lines += ["", "## 证据", "", "| 类型 | 位置 | 说明 |", "|---|---|---|"]
        for item in result["signals"]:
            lines.append(f"| {_KINDS.get(item['kind'], item['kind'])} | "
                         f"`{item['path'] or '-'}` | {item['note'] or '-'} |")
    if result["blockers"]:
        lines += ["", "## 阻断", ""]
        lines += [f"- {item}" for item in result["blockers"]]
    if result["cautions"]:
        lines += ["", "## 注意事项", ""]
        lines += [f"- {item}" for item in result["cautions"]]
    lines += ["", "## 下一步", ""]
    for index, step in enumerate(result["next_steps"], 1):
        shown = f"`{step}`" if step.startswith("py -3 ") else step
        lines.append(f"{index}. {shown}")
    lines += ["", "## 边界", ""]
    lines += [f"- {item}" for item in result["limits"]]
    lines.append("")
    return "\n".join(lines)
