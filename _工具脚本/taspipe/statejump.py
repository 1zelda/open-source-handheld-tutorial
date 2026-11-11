# -*- coding: utf-8 -*-
"""T3 前置件：NES BizHawk 状态会话（存档跳跃 / RAM 读写 / 逐帧宏 / 帧精确截图）。

工作模式（用户 2026-11-10 拍板）：走位一次到「要素前一刻」→ save 存快照 →
之后每次尝试 = attempt（load+宏+空档+截图，单指令原子完成）→ 检测器验收，
单次尝试秒级，不必每次从头回放。金手指走 read/write 改 RAM。

机制：tas_replay.STATE_LUA_TMPL 起持久 EmuHawk + 文件指令通道（cmd.txt/resp.txt，
id 单调去重）；看门狗线程复用 watchdog 的点框/树杀。能力转真以
验证/t3_statejump/report.json 全 pass 为证据（backends.probe 证据门控，无证据不真）。

红线提醒：纯改 RAM 构造的状态须经检测器正负例验收，游戏逻辑不认的假状态
不能冒充真实复现；确定性（同快照+同输入=同画面）由 verify 实跑钉死。

运行: python -m taspipe.statejump verify --rom <rom.nes> --out <验证/t3_statejump>
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from . import watchdog
from .schema import SchemaError

# NES 手柄键名（BizHawk NesController）；Lua 侧还会用 joypad.get(1) 实测键名再验一道。
BUTTON_ALIASES = {"U": "Up", "D": "Down", "L": "Left", "R": "Right"}
KNOWN_BUTTONS = {"A", "B", "Select", "Start", "Up", "Down", "Left", "Right"}


def _clean_token(s, what):
    if not isinstance(s, str) or not s or any(c.isspace() for c in s):
        raise SchemaError(f"{what} 须为非空且不含空白的字符串: {s!r}")
    return s


def _path_arg(p):
    _clean_token(p, "路径")
    try:
        p.encode("ascii")
    except UnicodeEncodeError:
        raise SchemaError("路径须纯 ASCII（中文路径请先落到临时工作目录，Lua io 中文会转码损坏）")
    return p.replace("\\", "/")


def _addr(a):
    if not isinstance(a, int) or not 0 <= a <= 0xFFFF:
        raise SchemaError(f"地址须为 0..0xFFFF 整数: {a!r}")
    return str(a)


def _byte(v):
    if not isinstance(v, int) or not 0 <= v <= 255:
        raise SchemaError(f"字节值须为 0..255 整数: {v!r}")
    return str(v)


def parse_macro(spec):
    """宏谱 → 规范线格式。逗号分帧、+ 分同帧按键、空帧=中立。
    "Start,,A+B" => "Start,,A+B"；别名 U/D/L/R 展开。未知键/空白/空谱拒。"""
    _clean_token(spec, "宏谱")
    out = []
    for tok in spec.split(","):
        if tok == "":
            out.append("")
            continue
        names = []
        for b in tok.split("+"):
            b = BUTTON_ALIASES.get(b, b)
            if b not in KNOWN_BUTTONS:
                raise SchemaError(f"未知按键: {b!r}（允许 {sorted(KNOWN_BUTTONS)} 及别名 U/D/L/R）")
            names.append(b)
        out.append("+".join(names))
    return ",".join(out)


def _v_save(kw):
    return [_path_arg(kw["path"])]


def _v_load(kw):
    a = [_path_arg(kw["path"])]
    if kw.get("shot"):
        a.append(_path_arg(kw["shot"]))
    return a


def _v_read(kw):
    a = [_addr(kw["addr"])]
    if kw.get("domain"):
        a.append(_clean_token(kw["domain"], "内存域"))
    return a


def _v_write(kw):
    a = [_addr(kw["addr"]), _byte(kw["value"])]
    if kw.get("domain"):
        a.append(_clean_token(kw["domain"], "内存域"))
    return a


def _v_run(kw):
    n = kw["frames"]
    if not isinstance(n, int) or n < 1:
        raise SchemaError(f"run 帧数须为正整数: {n!r}")
    a = [str(n)]
    if kw.get("shot"):
        a.append(_path_arg(kw["shot"]))
    return a


def _v_macro(kw):
    a = [parse_macro(kw["spec"])]
    if kw.get("shot"):
        a.append(_path_arg(kw["shot"]))
    return a


def _v_attempt(kw):
    a = [_path_arg(kw["state"])]
    spec = kw.get("spec") or "-"
    a.append("-" if spec == "-" else parse_macro(spec))
    extra = kw.get("extra", 0)
    if not isinstance(extra, int) or extra < 0:
        raise SchemaError(f"attempt extra 须为 >=0 整数: {extra!r}")
    a.append(str(extra))
    if kw.get("shot"):
        a.append(_path_arg(kw["shot"]))
    return a


def _v_ramdump(kw):
    a = [_path_arg(kw["path"])]
    n = kw.get("length", 2048)
    if not isinstance(n, int) or not 1 <= n <= 0x10000:
        raise SchemaError(f"ramdump 长度须为 1..0x10000 整数: {n!r}")
    a.append(str(n))
    return a


def _v_dump(kw):
    a = [_path_arg(kw["frames_dir"])]
    spec = kw.get("spec") or "-"
    a.append("-" if spec == "-" else parse_macro(spec))
    extra = kw.get("extra", 0)
    if not isinstance(extra, int) or extra < 0:
        raise SchemaError(f"dump extra 须为 >=0 整数: {extra!r}")
    a.append(str(extra))
    return a


_OPS = {
    "ping": lambda kw: [], "quit": lambda kw: [], "stop_movie": lambda kw: [],
    "save": _v_save, "load": _v_load, "shot": _v_save,
    "read": _v_read, "write": _v_write,
    "ramtest": lambda kw: [_addr(kw["addr"])],
    "run": _v_run, "macro": _v_macro, "attempt": _v_attempt,
    "ramdump": _v_ramdump, "dump": _v_dump,
}


def format_command(cid, op, **kw):
    """指令 → 单行线格式（"id op args..."）。非法 op/参数在此拦下，不进模拟器。"""
    if not isinstance(cid, int) or cid < 1:
        raise SchemaError(f"指令 id 须为正整数: {cid!r}")
    if op not in _OPS:
        raise SchemaError(f"未知 op: {op!r}（允许 {sorted(_OPS)}）")
    return " ".join([str(cid), op] + _OPS[op](kw))


def parse_response(line):
    """resp.txt 单行 → {id, ok, data}。格式非法抛 SchemaError（不静默当成功）。"""
    parts = line.split(" ", 2)
    if len(parts) < 2 or parts[1] not in ("ok", "err"):
        raise SchemaError(f"响应格式非法: {line!r}")
    try:
        cid = int(parts[0])
    except ValueError:
        raise SchemaError(f"响应 id 非整数: {line!r}")
    return {"id": cid, "ok": parts[1] == "ok",
            "data": parts[2] if len(parts) > 2 else ""}


def sha1_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


class _Guard(threading.Thread):
    """非阻塞看门狗：心跳停滞先点框（PID 精确），再停滞就树杀并标 dead。"""

    def __init__(self, proc, work, stall_timeout=45.0):
        super().__init__(daemon=True)
        self.proc = proc
        self.work = work
        self.stall_timeout = stall_timeout
        self.stop_event = threading.Event()
        self.dead = False
        self.dismissed = 0

    def run(self):
        hb = watchdog.heartbeat_path(self.work)
        last_progress = time.time()
        last_mt = 0.0
        while not self.stop_event.is_set():
            if self.proc.poll() is not None:
                self.dead = True
                return
            try:
                mt = os.path.getmtime(hb)
            except OSError:
                mt = 0.0
            now = time.time()
            if mt > last_mt + 1e-6:
                last_mt = mt
                last_progress = now
            if now - last_progress > 5.0:
                self.dismissed += watchdog.dismiss_bizhawk_dialog(self.proc.pid)
            if now - last_progress > self.stall_timeout:
                watchdog.tree_kill(self.proc.pid)
                self.dead = True
                return
            self.stop_event.wait(0.5)


class StateSession:
    """持久 EmuHawk 状态会话。with 语法保证退出（quit → 等退出 → 树杀兜底）。

    所有截图/存档路径落在 ASCII 临时工作目录（Lua io 中文转码坑，沿用 tas_replay
    口径）；要长期保存由调用方 shutil 拷出。command 单飞（锁），id 单调递增。
    """

    def __init__(self, rom, bizhawk, core="NesHawk", system="NES", movie=None,
                 work=None, speed=400):
        self.rom = str(rom)
        self.bizhawk = str(bizhawk)
        self.core = core
        self.system = system
        self.movie = str(movie) if movie else None
        self.work = str(work or tempfile.mkdtemp(prefix="tas_state_"))
        self.speed = int(speed)
        self._proc = None
        self._guard = None
        self._lock = threading.Lock()
        self._cid = 0

    def start(self, boot_timeout=60.0):
        import tas_replay
        os.makedirs(self.work, exist_ok=True)
        r = os.path.join(self.work, "rom" + os.path.splitext(self.rom)[1])
        shutil.copyfile(self.rom, r)
        tas_replay.force_core(self.bizhawk, self.system, self.core)
        lua = os.path.join(self.work, "session.lua")
        body = (tas_replay.STATE_LUA_TMPL
                .replace("__DIR__", self.work.replace("\\", "/"))
                .replace("__SPEED__", str(self.speed)))
        with open(lua, "w", encoding="utf-8") as f:
            f.write(body)
        cmd = [os.path.join(self.bizhawk, "EmuHawk.exe"), "--chromeless"]
        if self.movie:
            m = os.path.join(self.work, "movie.bk2")
            tas_replay.materialize_movie(self.movie, m)
            cmd.append(f"--movie={m}")
        cmd += [f"--lua={lua}", r]
        self._proc = subprocess.Popen(cmd, cwd=self.bizhawk,
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
        self._guard = _Guard(self._proc, self.work)
        self._guard.start()
        deadline = time.time() + boot_timeout
        hb = watchdog.heartbeat_path(self.work)
        while time.time() < deadline:
            if self._guard.dead:
                raise RuntimeError("EmuHawk 启动失败（看门狗标 dead，见 session.log/heartbeat）")
            if os.path.isfile(hb):
                return self
            time.sleep(0.2)
        self.close()
        raise TimeoutError(f"EmuHawk {boot_timeout}s 未写出心跳（启动卡死）")

    def _send(self, line):
        tmp = os.path.join(self.work, "cmd.txt.tmp")
        # newline="" 钉死 LF：Windows 文本模式会把 \n 翻成 \r\n，Lua 按空格切词
        # 会把 "ping\r" 当成未知 op（11-10 实测）。自检有字节级闸门。
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(line + "\n")
        dst = os.path.join(self.work, "cmd.txt")
        for i in range(50):
            try:
                os.replace(tmp, dst)
                return
            except PermissionError:
                time.sleep(0.02)          # Lua 正持 cmd.txt 的极窄窗口，重试
        raise TimeoutError("cmd.txt 替换持续失败（Lua 侧文件锁异常）")

    def _wait_resp(self, cid, timeout):
        resp = os.path.join(self.work, "resp.txt")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._guard.dead or self._proc.poll() is not None:
                raise RuntimeError(f"会话已死（指令 {cid} 无响应；看 session.log）")
            try:
                with open(resp, encoding="utf-8") as f:
                    line = f.read()
            except OSError:
                line = ""
            if line.endswith("\n"):
                r = parse_response(line.strip())
                if r["id"] == cid:
                    try:
                        os.remove(resp)
                    except OSError:
                        pass
                    if not r["ok"]:
                        raise RuntimeError(f"Lua 拒绝指令 {cid}: {r['data']}")
                    return r
            time.sleep(0.02)
        raise TimeoutError(f"指令 {cid} 超时 {timeout}s 无响应")

    def command(self, op, timeout=None, **kw):
        if self._proc is None:
            raise RuntimeError("会话未 start")
        with self._lock:
            if self._guard.dead or self._proc.poll() is not None:
                raise RuntimeError("会话已死（看门狗树杀或进程退出）")
            self._cid += 1
            line = format_command(self._cid, op, **kw)
            if timeout is None:
                n = kw.get("frames", 0)
                if op == "macro":
                    n = len(parse_macro(kw["spec"]).split(","))
                elif op == "attempt":
                    spec = kw.get("spec") or "-"
                    n = (0 if spec == "-" else len(parse_macro(spec).split(","))) + kw.get("extra", 0)
                elif op == "dump":
                    spec = kw.get("spec") or "-"
                    n = (0 if spec == "-" else len(parse_macro(spec).split(","))) + kw.get("extra", 0)
                timeout = max(30.0, n / 30.0 + 10.0)
            self._send(line)
            return self._wait_resp(self._cid, timeout)

    # ---- 便捷封装（路径一律相对 work，纯 ASCII）----
    def _wpath(self, name, ext):
        _clean_token(name, "名字")
        return os.path.join(self.work, name + ext).replace("\\", "/")

    def ping(self):
        d = self.command("ping")["data"].split()
        return int(d[0]), d[1]

    def save(self, name):
        p = self._wpath(name, ".state")
        self.command("save", path=p)
        return p

    def load(self, path, shot=None):
        kw = {"path": path}
        if shot:
            kw["shot"] = shot
        return self.command("load", **kw)

    def shot(self, name):
        p = self._wpath(name, ".png")
        self.command("shot", path=p)
        return p

    def read(self, addr, domain=None):
        return int(self.command("read", addr=addr, domain=domain)["data"])

    def write(self, addr, value, domain=None):
        self.command("write", addr=addr, value=value, domain=domain)

    def ramtest(self, addr):
        o, v = self.command("ramtest", addr=addr)["data"].split()
        return int(o), int(v)

    def run(self, frames, shot=None):
        kw = {"frames": frames}
        if shot:
            kw["shot"] = shot
        return self.command("run", **kw)

    def macro(self, spec, shot=None):
        kw = {"spec": spec}
        if shot:
            kw["shot"] = shot
        return self.command("macro", **kw)

    def attempt(self, state, spec=None, extra=0, shot=None):
        """一次尝试 = load 快照 + 宏 + 空档 + 截图，单指令原子完成（帧精确）。"""
        kw = {"state": state, "spec": spec or "-", "extra": extra}
        if shot:
            kw["shot"] = shot
        return self.command("attempt", **kw)

    def dump(self, frames_dir, spec=None, extra=0):
        """连续逐帧截图（f%04d.png）+ 按宏逐帧给输入，供 encode_video 出平滑片段。
        frames_dir 须纯 ASCII（落在 work 下）；调用方负责后续拷出。返回帧数。"""
        os.makedirs(frames_dir, exist_ok=True)
        return int(self.command("dump", frames_dir=frames_dir,
                                spec=spec or "-", extra=extra)["data"])

    def ramdump(self, path, length=2048):
        """把默认内存域 0..length-1 原始字节落盘（RAM 搜索/经验标定做证据）。返回字节数。"""
        return int(self.command("ramdump", path=path, length=length)["data"])

    def stop_movie(self):
        return self.command("stop_movie")["data"]

    def close(self):
        if self._proc is None:
            return
        try:
            if self._proc.poll() is None and not self._guard.dead:
                try:
                    self.command("quit", timeout=5)
                except (RuntimeError, TimeoutError, ValueError):
                    pass
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                watchdog.tree_kill(self._proc.pid)
        finally:
            if self._guard is not None:
                self._guard.stop_event.set()
                self._guard.join(timeout=3)

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()


# ------------------------------------------------------------- 实跑验收

def _png_pixels_equal(a, b, ffmpeg="ffmpeg"):
    """PNG 字节不同不等于画面不同（编码器差异）。字节相同直接 True；
    不同则用 ffmpeg 解成原始像素再比，避免把编码差异误报成 desync。
    返回 (是否相等, 说明)。"""
    if sha1_file(a) == sha1_file(b):
        return True, "字节一致"
    try:
        ra = subprocess.run([ffmpeg, "-v", "error", "-i", str(a),
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            capture_output=True, timeout=30)
        rb = subprocess.run([ffmpeg, "-v", "error", "-i", str(b),
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"字节不一致且像素复核不可用: {e}"
    if ra.returncode == 0 and rb.returncode == 0 and ra.stdout and rb.stdout:
        return ra.stdout == rb.stdout, "字节不一致，按原始像素比对"
    return False, "字节不一致且 ffmpeg 解码失败"


def macro_is_effective(neutral_png, macro_png, ffmpeg="ffmpeg"):
    """宏有效 = 同快照同总帧数下，宏画面与中立画面「不同」。
    _png_pixels_equal 返回的是「相等」，故此处取反——11-10 曾误把相等当有效
    （假阳性绿灯），抽成纯函数锁住语义，自检用相同图必判无效钉死它。
    返回 (是否有效, 说明)。"""
    eq, how = _png_pixels_equal(neutral_png, macro_png, ffmpeg)
    return (not eq), how


def verify(rom, bizhawk, out_dir, core="NesHawk", system="NES", movie=None,
           ffmpeg="ffmpeg"):
    """实跑验收：存档/RAM/宏/确定性（同进程+跨进程）。全部产物拷到 out_dir，
    report.json 全 pass 才许 backends.probe 把能力转真（证据门控）。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    checks = []

    def add(name, passed, detail, evidence=()):
        checks.append({"name": name, "pass": bool(passed), "detail": detail,
                       "evidence": [str(p) for p in evidence]})

    # 热血足球2 实测：开场信屏有输入锁定期（约前 780 帧任何键无效），
    # 锁定期内「宏无效」是游戏行为不是注入失败。故逐轮 +600 帧找响应态，
    # 每轮先 Start 后全键 mash；4 轮（约 2600 帧）仍无反应才判 FAIL。
    macro_spec = "Start,,,,,,Start,,,,,,"   # 两次 Start 点按（帧数=逗号数+1）
    mash_spec = "A+B+Start+Select,,,,,,A+B+Start+Select,,,,,,"
    kept = {}

    def keep(name, src):
        dst = out_dir / (name + Path(src).suffix)
        shutil.copyfile(src, dst)
        kept[name] = dst
        return dst

    def cap(name, fn, **kw):
        """跑指令并帧精确截图，产物拷到 out_dir。"""
        p = kw.pop("shot")
        fn(shot=p, **kw)
        return keep(name, p)

    with StateSession(rom, bizhawk, core, system, movie=movie) as s:
        frame, mode = s.ping()
        add("boot_ping", True, f"frame={frame} mode={mode}")
        if movie:
            s.run(300)
            s.stop_movie()
        title = cap("title", s.run, frames=180, shot=s._wpath("title", ".png"))
        add("boot_frames", True, "启动后中立跑 180 帧并帧精确截图", [title])

        o, v = s.ramtest(0x0000)
        add("ram_roundtrip", v == (o + 1) % 256,
            f"addr=0x0000 原值={o} 写入={(o + 1) % 256} 读回={v}（同帧原子，已恢复原值）")
        rv = s.read(0x0000)
        add("ram_read", rv == o, f"独立 read 指令读回={rv}（与 ramtest 原值一致）")

        st = s.save("base")
        add("savestate_file", os.path.isfile(st) and os.path.getsize(st) > 0,
            f"快照 {os.path.getsize(st)} 字节")

        neut = mac = None
        responsive = False
        hit_spec = macro_spec
        hit_round = -1
        for round_i in range(4):
            neut = cap("neutral60", s.attempt, state=st, extra=60,
                       shot=s._wpath("neutral60", ".png"))
            for spec in (macro_spec, mash_spec):
                # extra 动态补齐：中立与宏总帧数严格相等（宏帧数=逗号数+1）
                n_mac = len(parse_macro(spec).split(","))
                mac = cap("macro60", s.attempt, state=st, spec=spec, extra=60 - n_mac,
                          shot=s._wpath("macro60", ".png"))
                effective, _ = macro_is_effective(neut, mac, ffmpeg)
                if effective:            # 画面不同 = 注入有效
                    responsive = True
                    hit_spec = spec
                    hit_round = round_i
                    break
            if responsive:
                break
            s.run(600)                   # 输入锁定期：推进后再存再试
            st = s.save("base")
        add("macro_effective", responsive,
            (f"round={hit_round} spec={hit_spec.split(',')[0]} 同快照同总帧数画面不同 "
             f"neut_sha1={sha1_file(neut)[:12]} mac_sha1={sha1_file(mac)[:12]}"
             if responsive else
             "推进约 2600 帧、Start/全键 mash 均无画面变化，无法证明注入有效"),
            [neut, mac])
        keep("base", st)
        # 确定性用「最终 base」（响应态搜索可能推进过快照），与跨进程比对同源
        a = cap("det_a", s.attempt, state=st, shot=s._wpath("det_a", ".png"))
        s.run(120)                       # 故意漂移，再 load 必须拉回同一画面
        b = cap("det_b", s.attempt, state=st, shot=s._wpath("det_b", ".png"))
        eq, how = _png_pixels_equal(a, b, ffmpeg)
        add("determinism_reload", eq, f"load→截图 vs 漂移120帧→load→截图（{how}）", [a, b])
        n_hit = len(parse_macro(hit_spec).split(","))
        mac2 = cap("macro60b", s.attempt, state=st, spec=hit_spec, extra=60 - n_hit,
                   shot=s._wpath("macro60b", ".png"))
        eq2, how2 = _png_pixels_equal(mac, mac2, ffmpeg)
        add("determinism_macro", eq2, f"同快照+同宏两次尝试画面一致（{how2}）", [mac, mac2])
        base_state = kept["base"]

    with StateSession(rom, bizhawk, core, system) as s2:
        st2 = os.path.join(s2.work, "base.state")
        shutil.copyfile(base_state, st2)
        c = cap("det_cross", s2.attempt, state=st2, shot=s2._wpath("det_cross", ".png"))
        eq3, how3 = _png_pixels_equal(kept["det_a"], c, ffmpeg)
        add("determinism_cross_process", eq3,
            f"进程1存档→进程2读档截图一致（{how3}）", [kept["det_a"], c])

    report = {"rom": str(rom), "bizhawk": str(bizhawk), "core": core,
              "system": system, "movie": str(movie) if movie else None,
              "created": time.strftime("%Y-%m-%d %H:%M:%S"),
              "checks": checks,
              "all_pass": all(c["pass"] for c in checks)}
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="实跑验收（存档/RAM/宏/确定性），产物+report.json")
    v.add_argument("--rom", required=True)
    v.add_argument("--bizhawk", default=None, help="默认取 registry 发现的 2.8")
    v.add_argument("--core", default="NesHawk")
    v.add_argument("--system", default="NES")
    v.add_argument("--movie", default=None, help="可选：先回放 300 帧再 stop_movie 取状态")
    v.add_argument("--out", required=True)
    v.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args()
    if args.cmd == "verify":
        bh = args.bizhawk
        if not bh:
            from . import registry as R
            bh = R.discover_bizhawk(R.DEFAULT_EMU).get("2.8")
        if not bh:
            raise SystemExit("未发现 BizHawk 2.8，请用 --bizhawk 指定")
        rep = verify(args.rom, bh, args.out, args.core, args.system,
                     args.movie, args.ffmpeg)
        for c in rep["checks"]:
            print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}: {c['detail']}")
        print(f"all_pass={rep['all_pass']} -> {Path(args.out) / 'report.json'}")
        return 0 if rep["all_pass"] else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())