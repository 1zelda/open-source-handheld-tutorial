# -*- coding: utf-8 -*-
"""BizHawk 回放看门狗：模态框自动关闭 + 帧心跳停滞检测 + 树杀兜底。

2026-11-07 实测的卡点：整片 45472 帧在 17:08:24 就全采完了，最后一帧的
`emu.frameadvance()` 把 movie 推到末尾，BizHawk 弹出
"The end of the movie has been reached. The movie is currently missing a
cycle count..." 的 Win32 MessageBox。模态框堵住 Lua 线程，`client.exit()`
永远执行不到，Python 侧 `subprocess.run(timeout=1635)` 空等 27 分钟才杀进程；
更要命的是 cap.txt 被卡成 0 字节，编排层用「空文件里没有 desync 字样」
判了 `replay_no_desync = pass` —— 一个假绿灯。

三道防线，按优先级：
  1. Lua 侧不越界（见 tas_replay.LUA_TMPL）：最后一帧截图后不再 frameadvance，
     根本不给弹框机会；每帧写 heartbeat.txt 并 flush，进度随时可查。
  2. 看门狗发现心跳停滞，先按 PID 精确点掉那个 MessageBox（不误伤别的窗口）。
  3. 点框后仍停滞就树杀进程，并返回结构化 termination，绝不静默当成功。
"""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import time
from ctypes import wintypes as w

IS_WIN = sys.platform == "win32"

BM_CLICK = 0x00F5
WM_COMMAND = 0x0111
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
IDOK = 1
VK_RETURN = 0x0D

# 只认这些标题，避免把主窗口或别的程序的对话框一起点掉（chromeless 主窗口
# 不可见，dismiss 只命中可见模态框，故 "BizHawk" 不会误伤主渲染窗）。
# "Exception"：BizHawk 启动期加载失败（如 bk2 缺 Header）会弹这个标题的框，
# 漏认它会 dismissed=0 空等到停滞超时（11-09 忍者龙剑传 4751 实测）。
# "privileged"/"Mismatched version"：BizHawk 2.9+ 以 Administrator 运行必弹
# "This EmuHawk is privileged"；config 缺版本标记弹 "Mismatched version in
# config file"。两者堵死 Lua（11-10 矩阵 DK5254/KungFu/Metroid/SMB 全卡死实测）。
# 版本标记已由 tas_replay.force_core 补写消掉后者；privileged 无 config 抑制键，
# 只能靠这里点掉（点 OK 后正常进回放，已实证）。
# 不含裸 "BizHawk"：主窗口标题是 "{游戏} [NES] - BizHawk"，裸 BizHawk 子串会误匹配
# 主窗口，启动稍慢（首心跳 >5s）时看门狗对主窗口发回车/IDOK 会打断 Lua 初始化，
# 表现为间歇性「EmuHawk 启动失败」（11-10 热血足球2 实测，禁用点框后 3/3 稳定）。
# 真框都有具体标题（privileged/Mismatched version/Error/Exception/Warning），不靠裸 BizHawk。
STARTUP_DIALOG_TITLES = ("privileged", "Mismatched version")
DIALOG_TITLES = ("Warning", "Error", "Exception", "警告", "错误") + STARTUP_DIALOG_TITLES


def _is_emuhawk_main_window(title: str) -> bool:
    """主窗口签名（非模态框）：标题以 "- BizHawk" 结尾（已载游戏），或启动期裸 "BizHawk"。
    点框必须跳过它，否则误伤主窗口打断 Lua（纯函数，selftest 钉死）。"""
    t = (title or "").strip()
    return t == "BizHawk" or t.endswith("- BizHawk")


def _should_dismiss(title: str, visible: bool, titles=DIALOG_TITLES) -> bool:
    """点框判定（纯函数，selftest 钉死）：可见 + 非主窗口 + 标题命中框表，三者缺一不点。
    主窗口误伤是 11-10 热血足球2 启动间歇失败根因，故把整条判定抽出单测，
    而非只测零件——dismiss_bizhawk_dialog 的循环直接调它，夹具即生产口径。"""
    if not visible or _is_emuhawk_main_window(title):
        return False
    return any(t.lower() in (title or "").lower() for t in titles)


def windows_of_pid(pid: int) -> list[tuple[int, str, str, bool]]:
    """列出某个进程的顶层窗口 (hwnd, 标题, 类名, 可见)。非 Windows 返回空。"""
    if not IS_WIN or not pid:
        return []
    u = ctypes.windll.user32
    cb_type = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    out: list[tuple[int, str, str, bool]] = []

    def cb(hwnd, _lparam):
        p = w.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            title = ctypes.create_unicode_buffer(512)
            cls = ctypes.create_unicode_buffer(256)
            u.GetWindowTextW(hwnd, title, 512)
            u.GetClassNameW(hwnd, cls, 256)
            out.append((hwnd, title.value, cls.value, bool(u.IsWindowVisible(hwnd))))
        return True

    u.EnumWindows(cb_type(cb), 0)
    return out


def _note_unique(records: list, item: dict) -> None:
    """按整条内容去重收集窗口证据。停滞期每轮轮询都会撞同一个窗口，
    不去重的话产物里会出现 N 份重复证据，看不出到底挡了几种窗口。"""
    if item not in records:
        records.append(item)


def _note_dialog(records: list, title: str, texts: list) -> None:
    _note_unique(records, {"title": title, "texts": texts})


def _children(u, hwnd: int) -> tuple[list, list]:
    """枚举子控件，返回 (Button 句柄, 非空控件文本)。点框和抄证据共用一次遍历。"""
    buttons: list[int] = []
    texts: list[str] = []
    cb = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)

    def on_child(h, _lparam):
        c = ctypes.create_unicode_buffer(128)
        u.GetClassNameW(h, c, 128)
        if c.value == "Button":
            buttons.append(h)
        t = ctypes.create_unicode_buffer(2048)
        u.GetWindowTextW(h, t, 2048)
        if t.value.strip():
            texts.append(t.value.strip())
        return True

    u.EnumChildWindows(hwnd, cb(on_child), 0)
    return buttons, texts


# 链式弹窗最多重试几轮（每轮窗口集合必须变化）：真机见过 privileged → 固件警告两连，
# 给个上限防止两个框互相反复弹时看门狗永远不收手。
MAX_STALL_ROUNDS = 8
# 同一个框「点了还在」时的补点次数：_window_key 分不出"这次没点掉"和
# "同样的警告又弹了一张"（标题/类名/文本全同），所以先按上限补点，再认输。
MAX_REPEAT_CLICKS = 2


def _window_key(wins: list[dict]) -> tuple:
    """把一轮可见窗口压成可比较的键，用来判断「点完之后屏幕换了没有」。"""
    return tuple(sorted((w.get("title", ""), w.get("class", ""),
                         tuple(w.get("texts", []))) for w in wins))


def stall_windows(pid: int) -> list[dict]:
    """停滞现场快照：该进程所有「可见 + 非主窗口」的顶层窗口（标题/类名/正文）。

    与 dismiss 的区别是这里不点、只抄，所以框表认不出的窗口也留得下来——
    11-22 洛克人X2 dismissed=1 之后仍 0 帧，挡住它的正是表外窗口。
    """
    if not IS_WIN or not pid:
        return []
    u = ctypes.windll.user32
    out: list[dict] = []
    for hwnd, title, cls, visible in windows_of_pid(pid):
        if not visible or _is_emuhawk_main_window(title):
            continue
        _note_unique(out, {"title": title, "class": cls,
                           "texts": _children(u, hwnd)[1]})
    return out


def dismiss_bizhawk_dialog(pid: int, titles=DIALOG_TITLES,
                           records: list | None = None) -> int:
    """点掉该进程弹出的模态框，返回点了几个。按 PID 过滤，不碰别的程序。

    三条路一起发（都是 PostMessage，不阻塞看门狗线程）：
      * 对按钮发 BM_CLICK（中文系统按钮文本是「确定」，类名固定 Button）；
      * 对对话框发 WM_COMMAND/IDOK；
      * 对对话框发回车键。
    Windows MessageBox 会忽略多余的那两条，不会误触发两次。

    records 给了就顺手把「框标题 + 子控件正文」收进去（同标题同正文去重）。
    只数 dismissed 个数问不出「到底弹的是哪个框」——11-22 洛克人X2 0 帧
    stalled_killed 查不到根因，就是因为框一点掉、正文没落进产物。
    """
    if not IS_WIN or not pid:
        return 0
    u = ctypes.windll.user32
    n = 0
    for hwnd, title, _cls, visible in windows_of_pid(pid):
        if not _should_dismiss(title, visible, titles):
            continue
        buttons, texts = _children(u, hwnd)
        if records is not None:
            _note_dialog(records, title, texts)
        if buttons:
            u.PostMessageW(buttons[0], BM_CLICK, 0, 0)
        u.PostMessageW(hwnd, WM_COMMAND, IDOK, 0)
        u.PostMessageW(hwnd, WM_KEYDOWN, VK_RETURN, 0)
        u.PostMessageW(hwnd, WM_KEYUP, VK_RETURN, 0)
        n += 1
    return n


def tree_kill(pid: int) -> None:
    """Windows 下 taskkill /F /T 连子进程一起收，避免留下半死不活的 EmuHawk。"""
    if not pid:
        return
    if IS_WIN:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, timeout=15)
    else:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


def replay_verdict(desync, termination: str) -> str:
    """回放是否算「确认无 desync」。返回 pass/fail/inconclusive。

    空 cap.txt（desync=None）或任何非干净退出都只能是不确定 ——
    11-07 那次 TIMEOUT 1635s 被杀却判 pass，就是漏了这一条。
    """
    if desync is True:
        return "fail"
    if desync is False and termination in ("complete", "movie_end"):
        return "pass"
    return "inconclusive"


def exit_verdict(termination: str) -> str:
    """回放是否干净退出。返回 pass/fail/inconclusive。"""
    if termination in ("complete", "movie_end"):
        return "pass"
    if termination in ("stalled_killed", "timeout", "incomplete", "desync"):
        return "fail"
    return "inconclusive"


# 下面这些文案不是照印象写的，是从本机 BizHawk 2.9.1（另核 2.3/2.8/2.9/2.10/2.11/2.11.1）
# 各 dll 的 #US 堆里逐条抠出来的 UTF-16LE 字面量（取证脚本见 说明书 §45）：
#   缺了仍继续  Couldn't find firmware {0}.  Will attempt to continue: {1}
#   缺了且致命  Couldn't find required firmware {0}.  This is fatal{1}
#              （2.11 起同一条改成 …This prevents the core from loading{1}）
#   名字对内容不对  Hacked firmware detected! / Potentially bad firmware dump! /
#              Bad firmware length detected! / Bad Firmware CRC16(s) detected! /
#              Firmware could not be decryped for verification! /
#              Savestate internal firmware mismatch
#              ⚠ 11-23 本机 2.9.1 字节级复核：这几句在 BizHawk.Emulation.Cores.dll 的
#              #US 堆里紧挨 `ARM9 r15` / `Wifi AP1 AP2 AP3` / `USER0 USER1` / `CRC16` /
#              `Firmware could not be decryped for`  ⇒ 它们是 **NDS 固件路**的文案。
#              BSNES 的芯片固件（CX4/DSP1…）**没有**「内容不对」这一类提示，所以 CX4 臂
#              里没出现 Hacked/Bad length 一句话信息量都没有，别拿它当「字节进了核心」的
#              反证（ab15 前言就是这么写错的，已在说明书 §45 撤回）。bad_dump 档留着是给
#              NDS 那条路的，SNES 永远走不到这里。
#   核心要的固件不认识  Unrecognized SNES firmware request "…".
#   回了但内容未验  Served libsnes request for firmware "{0}"
#              （同一段 #US 堆里紧邻 cx4.rom/dsp1.rom/... 与 CX4/DSP1/... 两个表，
#              说明这句就是 SNES 核心的固件服务回调；它不等于「服务对了」）
# 请求名的字面量是裸名 CX4（BizHawk.Emulation.Common.dll 里 'CX4' / 'CX4 Rom' /
# 'SNES_cx4.rom' 三连），既不是 "SNES:CX4" 也不是 "SNES+CX4"，所以三种写法都得吃。
# 上面说的是**本看门狗解析提示文本**要认三种形状；别把它当成「往 config 里随便写哪个键
# 都行」。11-23 真机 bisect（ab11/ab15，ab16 正在复测文件名那一格，见说明书 §45）实测：
#   * 往配置声明的固件目录扔文件 = 按**内容**认（先长度后哈希），假字节一律「Couldn't find」；
#   * `FirmwareUserSpecifications` 只有键名写裸芯片名 `CX4`（或 `SNES+CX4`）才影响提示，
#     `SNES_cx4.rom`/`cx4.rom`/`SNES CX4`/`SNES/CX4`/`SNESFIRMWARE_CX4` 都不吃；
#   * 而注册的目标**文件名**换成非 `cx4.rom` 时连提示都压不住 ⇒ 这扇门很可能还是按名字认。
# ⇒ 结论到 11-23 为止：本看门狗的两条证据渠道（框 + 控制台）**都无法证明固件字节进了核心**，
#   所以「没弹框」永远不够翻 pass，芯片固件缺失只能由 record.py 的 chip_firmware_missing
#   结合电影 Header 声明判 inconclusive，不许拿压掉提示当「固件已就位」。
# 看门狗一点掉「缺了仍继续」那条就照常跑完整片，replay_no_desync 只看电影自身的
# 校验和，对「复刻的是不是那块芯片」一无所知 —— 11-22 洛克人X2 5628 就是这么以
# 全绿姿态出了降级片的。
_FIRMWARE_CLASS_MARKERS = (
    ("fatal", ("couldn't find required firmware", "this is fatal",
               "prevents the core from loading", "firmware files are required")),
    ("missing", ("couldn't find firmware", "could not find firmware",
                 "firmware file not found", "firmware not found", "missing firmware",
                 "because none was provided", "at least one of these firmware",
                 "game may function incorrectly without")),
    # 11-23 实测（臂1 Firmware 目录清空）：BSNES 走的是 libsnes 固件回调，BizHawk
    # 回一句 Served libsnes request for firmware "cx4.rom" 就继续跑，既不弹框也不
    # 报缺文件。「服务过」不等于「服务对了」——它给的是哪个字节来源没验，所以单独
    # 成一档，绝不当 pass。
    ("served", ("served libsnes request", "served firmware request")),
    ("bad_dump", ("hacked firmware", "potentially bad firmware", "bad firmware length",
                  "bad firmware crc16", "could not be decryped",
                  "internal firmware mismatch", "invalid firmware length")),
    ("unknown", ("unrecognized snes firmware request", "unrecognized firmware request",
                 "core asked for firmware", "couldn't satisfy firmware request")),
)
_FIRMWARE_MARKERS = tuple(m for _cls, ms in _FIRMWARE_CLASS_MARKERS for m in ms)
_FIRMWARE_SPEC_RES = (
    # 冒号是合法名字字符（BizHawk 2.3 的写法是 "SNES:CX4"），所以它不能出现在
    # 收尾断言里，否则 "SNES:CX4" 会被截成 "SNES"。
    re.compile(r"find (?:required )?firmware\s+\"?([A-Za-z0-9_+\-.:]+?)(?=$|[.,;\s\"])", re.I),
    re.compile(r"\b([A-Za-z0-9]+_Firmware_[A-Za-z0-9_+\-.]+)\b"),
    re.compile(r"firmware [`\"]([A-Za-z0-9_.\-]+)[`\"]"),
    re.compile(r"firmware request [`\"]?([A-Za-z0-9_.\-:]+)[`\"]?\s+because", re.I),
    re.compile(r"\b(SNES_[a-z0-9]+\.rom)\b", re.I),
)
_FIRMWARE_CLASS_WHY = {
    "fatal": "固件缺失且 BizHawk 判为致命（核心没加载或明确要求固件文件）",
    "missing": "缺固件仍继续（Couldn't find firmware…，由 dll 字面量核实）",
    "served": "核心向 BizHawk 要了固件、BizHawk 回了「已服务」，但回的是哪个来源/内容没验证",
    "bad_dump": "固件按名字对上但内容被判可疑（Hacked/bad dump 类提示）",
    "unknown": "核心发出的固件请求 BizHawk 认不出来，该芯片未按请求行为复刻",
}


def _iter_texts(dialogs) -> list[str]:
    """把「窗口记录列表 / 控制台行列表 / 单个字符串」统一成正文列表。"""
    texts: list[str] = []
    if isinstance(dialogs, str):        # 单条正文当一条记录，别按字符迭代
        return [dialogs]
    for rec in dialogs or []:
        if isinstance(rec, str):
            texts.append(rec)
        else:
            texts += [str(t) for t in (rec.get("texts") or [])]
            texts.append(str(rec.get("title") or ""))
    return texts


def _drop_subsumed(specs: list[str]) -> list[str]:
    """同一条提示被多种写法各抽一次时（"SNES:CX4" 与 "CX4"），只留更全的那个。"""
    low = [s.lower() for s in specs]
    return [s for i, s in enumerate(specs)
            if not any(j != i and low[j].endswith(":" + low[i]) for j in range(len(specs)))]


def firmware_specs(dialogs) -> list[str]:
    """从固件相关提示里抽出「点名的固件规格」，去重保序。

    dialogs 可以是 dismissed_dialogs / stall_windows / windows_at_kill / console_texts
    任一，也可以是把它们拼起来的列表；纯字符串记录也吃（便于自测与旧产物回放）。
    认得出降级但不明说规格时返回 ["?"]，让调用方照样降档，不至于洗白。"""
    out: list[str] = []
    for text in _iter_texts(dialogs):
        low = text.lower()
        if not any(m in low for m in _FIRMWARE_MARKERS):
            continue
        named = []
        for pat in _FIRMWARE_SPEC_RES:
            named += [m.strip() for m in pat.findall(text)]
        for spec in (named or ["?"]):
            if spec and spec not in out:
                out.append(spec)
    return _drop_subsumed(out)


def firmware_classes(dialogs) -> list[str]:
    """这条固件证据属于哪一类（可多类），用来定 severity 和写 reason。"""
    blob = "\n".join(_iter_texts(dialogs)).lower()
    return [cls for cls, ms in _FIRMWARE_CLASS_MARKERS if any(m in blob for m in ms)]


def firmware_console_lines(log_path: str, limit: int = 200) -> list[str]:
    """从模拟器控制台日志里只挑固件相关行。

    逐行挑而不是整份塞进产物：BizHawk 每帧打一行 "xxx.png saved."，整片几万次，
    证据文件会被自己撑爆；命中行去重且封顶，判定用的还是同一套 marker。"""
    out: list[str] = []
    try:
        fh = open(log_path, encoding="utf-8", errors="replace")
    except OSError:
        return out
    with fh:
        for line in fh:
            low = line.lower()
            if not any(m in low for m in _FIRMWARE_MARKERS):
                continue
            s = line.strip()
            if s and s not in out:
                out.append(s)
            if len(out) >= limit:
                break
    return out


def firmware_verdict(watch: dict) -> tuple[str, str, list[str]]:
    """回放途中有没有「缺固件仍继续」的静默降级。返回 (verdict, reason, specs)。

    证据通道有两个：看门狗留下的窗口记录，和 tas_replay 落盘的控制台日志
    （console_texts）。后者是必需的 —— BizHawk 的固件提示走 Console.WriteLine，
    不保证一定有框，只盯框就会把「压根没弹框」当成「没降级」。

    11-23 实测把「弹框」这把尺子本身量坏了：注册键 `CX4`→`Firmware/cx4.rom`（32KB 0xCD）
    同样一套参数，ab17 的 r1 一臂 **0 张框、9.0s**（连每批都稳定出现的 Administrator 框都没有），
    ab18 用 ab11 自己的调用序列重跑两遍（x2/x4）却是 **3 张框、91.6/92.5s**，
    而且两条路径写盘的 config 逐字节相同（sha `7bffef5749a7`）。
    ⇒ 「框没出现」既可能是「找到了」也可能是「采集/时序没走到」，**永远不能单独当正证**；
       所以没有任何命中时，只有看得见「控制台渠道」（键存在，哪怕是空表）才允许 pass，
       渠道本身缺失就降 inconclusive——省得探针直接拿 `watch_process` 的返回值判 pass
       （ab17 的 `gate: pass` 就是这么来的，生产链路是 tas_replay 先并了 console_texts 才安全）。
    """
    specs: list[str] = []
    classes: list[str] = []
    for key in ("dismissed_dialogs", "stall_windows", "windows_at_kill", "console_texts"):
        recs = (watch or {}).get(key)
        for s in firmware_specs(recs):
            if s not in specs:
                specs.append(s)
        for c in firmware_classes(recs):
            if c not in classes:
                classes.append(c)
    if not specs and not classes:
        if "console_texts" not in (watch or {}):
            return ("inconclusive",
                    "没有控制台渠道（watch 里没有 console_texts 键），零弹框不能当正证"
                    " —— 同参数两批实测一次 0 框一次 3 框（ab17 r1 / ab18 x2·x4）",
                    [])
        return "pass", "未见固件缺失提示（无芯片降级证据）", []
    label = ", ".join("?（提示未点名）" if s == "?" else s for s in specs)
    # 命中任一 marker 必然归进某个 class（两张表同源），所以这里不需要兜底文案，
    # 更不许再写「走 HLE 兜底」那种我没验证过的降级机制（dll 字面量里只有
    # Couldn't find firmware … Will attempt to continue）。
    why = "；".join(_FIRMWARE_CLASS_WHY[c] for c in classes)
    verdict = "fail" if "fatal" in classes else "inconclusive"
    return (verdict,
            f"{why}: {label} —— "
            "desync=false 只代表电影自身校验过，不代表复刻了该芯片行为",
            _drop_subsumed(specs))


def heartbeat_path(work: str) -> str:
    return os.path.join(work, "heartbeat.txt")


def read_heartbeat(work: str) -> tuple[int, str]:
    """读 Lua 写的心跳「帧数 mode」。文件不存在/损坏返回 (0, "")。"""
    try:
        with open(heartbeat_path(work), encoding="utf-8", errors="replace") as fh:
            parts = fh.readline().split()
        return (int(parts[0]), parts[1] if len(parts) > 1 else "")
    except (OSError, ValueError, IndexError):
        return 0, ""


def watch_process(proc, work: str, *, poll: float = 0.5,
                  stall_timeout: float = 30.0, dismiss_grace: float = 8.0,
                  hard_timeout: float | None = None,
                  auto_dismiss: bool = True) -> dict:
    """盯着子进程直到退出；心跳停了先关框，再不行就树杀。

    返回 {termination, dismissed, dismissed_dialogs, stall_windows,
    windows_at_kill, stalls, last_frame, elapsed, returncode}。
    termination 取值：exited / stalled_killed / timeout / dismissed_recovered。
    dismissed_dialogs 是点过的框，stall_windows 是停滞瞬间所有可见非主窗口
    （含框表认不出的），归因只能靠这两样。
    正常退出时由调用方再读 cap.txt 判 status=complete，别在这里猜。
    停滞时同一个窗口集合点了还在：先按 MAX_REPEAT_CLICKS 补点（键相同的第二张框
    与"没点掉"分不出来），补满才 stalled_killed；stalls 记的是点击轮次。
    """
    start = time.time()
    last_progress = start
    last_mtime = 0.0
    last_frame = 0
    stalls = 0
    dismissed = 0
    dialogs: list[dict] = []
    stall_seen: list[dict] = []
    at_kill: list[dict] = []
    last_stall_key: tuple | None = None
    pending_since: float | None = None
    repeat = 0
    termination = "exited"
    hb = heartbeat_path(work)

    def kill() -> None:
        tree_kill(proc.pid)
        if proc.poll() is None:      # taskkill 不可用时别把进程留在那儿
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    while True:
        if proc.poll() is not None:
            break
        now = time.time()
        if hard_timeout is not None and now - start > hard_timeout:
            kill()
            termination = "timeout"
            break

        try:
            mt = os.path.getmtime(hb)
            if mt > last_mtime + 1e-6:
                last_mtime = mt
                last_progress = now
                last_frame, _ = read_heartbeat(work)
                if pending_since is not None:
                    # 关框之后又动起来了：这次是「自动退出后继续跑」，不是卡死。
                    pending_since = None
                    if not stalls:
                        termination = "dismissed_recovered"
        except OSError:
            pass

        if now - last_progress > stall_timeout:
            wins = stall_windows(proc.pid) if auto_dismiss else []
            for win in wins:
                _note_unique(stall_seen, win)
            key = _window_key(wins)
            # 链式框：privileged 点掉后才弹固件警告（11-22 洛克人X2 windows_at_kill 实证）。
            # 所以窗口集合一变就再点一轮；集合没变且过了宽限才认输。
            if pending_since is None or key != last_stall_key:
                if stalls >= MAX_STALL_ROUNDS:
                    at_kill = wins
                    kill()
                    termination = "stalled_killed"
                    break
                stalls += 1
                last_stall_key = key
                repeat = 0
                if auto_dismiss:
                    dismissed += dismiss_bizhawk_dialog(proc.pid, records=dialogs)
                pending_since = now
                last_progress = now      # 给 dismiss_grace 观察窗口
            elif now - pending_since > dismiss_grace:
                if stalls >= MAX_STALL_ROUNDS or repeat >= MAX_REPEAT_CLICKS:
                    at_kill = wins
                    kill()
                    termination = "stalled_killed"
                    break
                # 集合没变：分不清"这张没点掉"和"同样的警告又弹一张"，先补点，补满才认输。
                repeat += 1
                stalls += 1
                if auto_dismiss:
                    dismissed += dismiss_bizhawk_dialog(proc.pid, records=dialogs)
                pending_since = now
                last_progress = now

        time.sleep(poll)

    return {"termination": termination, "dismissed": dismissed,
            "dismissed_dialogs": dialogs, "stall_windows": stall_seen,
            "windows_at_kill": at_kill,
            "stalls": stalls, "last_frame": last_frame,
            "elapsed": round(time.time() - start, 1),
            "returncode": proc.returncode}
