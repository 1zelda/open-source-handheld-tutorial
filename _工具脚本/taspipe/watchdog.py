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
DIALOG_TITLES = ("Warning", "Error", "Exception", "警告", "错误",
                 "privileged", "Mismatched version")


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


def dismiss_bizhawk_dialog(pid: int, titles=DIALOG_TITLES) -> int:
    """点掉该进程弹出的模态框，返回点了几个。按 PID 过滤，不碰别的程序。

    三条路一起发（都是 PostMessage，不阻塞看门狗线程）：
      * 对按钮发 BM_CLICK（中文系统按钮文本是「确定」，类名固定 Button）；
      * 对对话框发 WM_COMMAND/IDOK；
      * 对对话框发回车键。
    Windows MessageBox 会忽略多余的那两条，不会误触发两次。
    """
    if not IS_WIN or not pid:
        return 0
    u = ctypes.windll.user32
    child_cb = ctypes.WINFUNCTYPE(ctypes.c_bool, w.HWND, w.LPARAM)
    n = 0
    for hwnd, title, _cls, visible in windows_of_pid(pid):
        if not _should_dismiss(title, visible, titles):
            continue
        buttons: list[int] = []

        def on_child(h, _lparam):
            c = ctypes.create_unicode_buffer(128)
            u.GetClassNameW(h, c, 128)
            if c.value == "Button":
                buttons.append(h)
            return True

        u.EnumChildWindows(hwnd, child_cb(on_child), 0)
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

    返回 {termination, dismissed, stalls, last_frame, elapsed, returncode}。
    termination 取值：exited / stalled_killed / timeout / dismissed_recovered。
    正常退出时由调用方再读 cap.txt 判 status=complete，别在这里猜。
    """
    start = time.time()
    last_progress = start
    last_mtime = 0.0
    last_frame = 0
    stalls = 0
    dismissed = 0
    pending_since: float | None = None
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

        if now - last_progress > stall_timeout and pending_since is None:
            stalls += 1
            if auto_dismiss:
                dismissed += dismiss_bizhawk_dialog(proc.pid)
            pending_since = now
            last_progress = now          # 给 dismiss_grace 观察窗口
        elif (pending_since is not None
              and now - pending_since > dismiss_grace
              and now - last_progress > stall_timeout):
            kill()
            termination = "stalled_killed"
            break

        time.sleep(poll)

    return {"termination": termination, "dismissed": dismissed,
            "stalls": stalls, "last_frame": last_frame,
            "elapsed": round(time.time() - start, 1),
            "returncode": proc.returncode}
