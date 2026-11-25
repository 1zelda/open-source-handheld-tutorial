# -*- coding: utf-8 -*-
"""通用多游戏「通关 + 要素盘点」自动探路、状态求解、RAM 差分与检测器自动标定流水线。

覆盖核心痛点：
1. 告别卡死在标题/选关/过场：
   - 自动探测开机「输入锁定期」（开头忽略按键帧窗）；
   - 转场/菜单统一采用「按住多帧宏」（破除单帧奇偶采样窗 parity 吞键）；
   - 「可控性黄金判据（Controllability Gate）」：在疑似进入关卡处自动做 A(中立)/B(移动+动作)/C(菜单)
     三分支快照实测对比，只有画面产生真实受控位移且不回退选关（拦截洛克人 CLEAR POINTS 假过场），
     才判定真正进入 Gameplay。
2. 告别「没来到特定游戏环节 / 拿不到要素」：
   - 洛克人 1 (Mega Man 1)：支持通用平地 base.state + 要素级专用快照（Super Arm 举块景仍缺，见说明书 §33.7）；
   - 热血足球 2 (Nekketsu Soccer League)：内置「KICK OFF 冻结态 -> 开球接球 -> 活 play 持球态 (possess_base.state)」
     自动球权求解器 + 暂停按键金手指 (AAABAAABAAAAAAA) 自动注入，解决无球权打不出必杀射门的痛点；
   - 忍者猫 (Kyatto Ninden Teyandee)：支持「忍法必杀槽满 + 角色/支援成员切换」多场景锚点构造；
   - 任意其他 FC/NES 名作（忍者龙剑传、银河战士、塞尔达、魂斗罗、恶魔城）：既可走 FCEUX .fm2/.fcm -> .bk2
     通关回放切片，也可走 statejump_showcase 正反例原子采集。
3. 告别手猜 RAM 地址与检测框参数：
   - A/B 状态回滚差分：在真实 Gameplay 中自动比对动作/菜单前后 2KB WRAM，锁定真实有效地址；
   - 正反例逐帧像素差分（Pos vs Neg Auto-Calibration）：从同一 base_state 和 patches 跑正例宏与中立反例，
     自动找出差异最大的帧号 frame、归一化包围盒 region（自动加防截断边距）和主色簇 rgb，
     并用生产级 detect.run_check 实测正反例占比，设定包过双闸的安全阈值 min_fraction。

运行方式（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.universal_authoring probe-rom --rom "F:/path/to/game.nes" --preset megaman1
  py -3 -u -m taspipe.universal_authoring solve-soccer2-base --rom "F:/path/to/soccer2.nes"
  py -3 -u -m taspipe.universal_authoring calibrate --pack "taspipe/游戏包/megaman1_weapons.showcase.json"
  py -3 -u -m taspipe.universal_authoring produce --pack "taspipe/游戏包/megaman1_weapons.showcase.json" --out "F:/taspipe_scratch/out"
  py -3 -u -m taspipe.universal_authoring playthrough --game "Zelda" --out "F:/taspipe_scratch/playthrough"
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import auto as AUTO
from . import detect
from . import fceux as FCEUX
from . import registry as R
from . import showcase
from . import statejump as SJ
from .schema import CheckSpec, SchemaError, Verdict

SCRATCH_ROOT = Path("F:/taspipe_scratch/universal")


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


MIN_KEY_FRAMES = 2      # 11-15 实测：热血足球联盟 KICK OFF 锁定态下单帧按键 100% 不生效


def hold(btn: str, frames: int, wait: int = 0) -> str:
    """生成按住多帧 + 等待空帧的规范宏谱（破除标题/转场单帧 parity 忽略问题）。

    下限锁 MIN_KEY_FRAMES=2：`soccer2_unlock_grid.py` 实测按键持续 1 帧时球/队长纹丝不动、
    持续 ≥2 帧才解锁，此前"约 60 触发链全负"就是栽在这里。
    """
    seq = ([btn] * max(MIN_KEY_FRAMES, int(frames))) + ([""] * max(0, int(wait)))
    return ",".join(seq)


def spec_violations(spec: str) -> list:
    """审计宏谱：返回连按不足 MIN_KEY_FRAMES 帧的键位（含段起始帧号），空列表=合规。"""
    toks = [t.strip() for t in str(spec).split(",")]
    bad, run, start = [], 0, 0
    for i, t in enumerate(toks + ["__END__"]):
        if t == run:
            continue
        if run and run != "__END__" and i - start < MIN_KEY_FRAMES:
            bad.append({"key": run, "at": start, "frames": i - start})
        run, start = t, i
    return bad


def chain_macros(*parts: str) -> str:
    """串联多段宏谱。"""
    return ",".join(p for p in parts if p is not None and p != "")


def _load_rgb_grid(png_path: Path):
    """通过 ffprobe/ffmpeg 读取 PNG 的真实宽高与 RGB24 原始字节流。"""
    p_probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(png_path)
        ],
        capture_output=True, text=True, check=True
    )
    info = json.loads(p_probe.stdout)["streams"][0]
    w, h = int(info["width"]), int(info["height"])
    p_raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(png_path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True
    )
    return w, h, p_raw.stdout


# ---------------------------------------------------------------------------
# 预设导航配方（针对各名作的开机锁定期与进关路线）
# ---------------------------------------------------------------------------
GAME_NAV_PRESETS = {
    "megaman1": {
        "title": "Mega Man 1 (NES)",
        "boot_wait": 240,
        "steps": [
            # 标题→选关切换实测约 90–140 帧（说明书 §23.1）：Start 后必须留 ≥150 帧，
            # 旧 wait=120 会让后续方向键落在标题页，正是旧"选关 D-pad 无效"假象的成因。
            {"desc": "标题屏按 Start 进入选关界面（留足转场帧）", "macro": hold("Start", 12, 180)},
            {"desc": "选关光标沿六宫格外圈循环：Right=顺时针(Cut→Guts→Ice→Bomb→Fire→Elec)、Left=逆时针、Up/Down 实测无效；现配方 Up+Right 净效果=Right×1=Guts（base 身份以画面+导航出处双证定）", "macro": hold("Up", 20, 10) + "," + hold("Right", 20, 20)},
            {"desc": "按 Start 确认选关并等待 Boss 登场动画与 Ready 落地", "macro": hold("Start", 12, 660)},
        ],
        "bad_rom_check": "mm1_clear_points",
    },
    "nekketsu_soccer2": {
        "title": "热血足球2 / Kunio-kun no Nekketsu Soccer League (FC)",
        "boot_wait": 1200,  # 前 ~780 帧信件画面锁定输入，1200 帧稳达标题屏
        "steps": [
            {"desc": "标题屏按 Start 到主菜单", "macro": hold("Start", 12, 90)},
            {"desc": "模式选择确认", "macro": hold("Start", 12, 90)},
            {"desc": "球队选择确认", "macro": hold("Start", 12, 90)},
            {"desc": "对阵 VS 画面确认", "macro": hold("Start", 12, 90)},
            {"desc": "休息室默认开球确认进入场地 KICK OFF", "macro": hold("Start", 12, 180)},
        ],
        "bad_rom_check": None,
    },
    "ninja_cats": {
        "title": "忍者猫 / Kyatto Ninden Teyandee (FC)",
        "boot_wait": 360,
        "steps": [
            {"desc": "跳过片头进入标题屏", "macro": hold("Start", 12, 120)},
            {"desc": "标题屏按 Start 开始游戏", "macro": hold("Start", 12, 180)},
            {"desc": "跳过剧情对话进入第一关可控地面", "macro": chain_macros(
                hold("Start", 12, 120), hold("A", 12, 120), hold("Start", 12, 360)
            )},
        ],
        "bad_rom_check": None,
    },
    "generic_nes": {
        "title": "通用 FC/NES 游戏",
        "boot_wait": 360,
        "steps": [
            {"desc": "标题屏按 Start", "macro": hold("Start", 12, 180)},
            {"desc": "二次按 Start 跳过菜单/过场", "macro": hold("Start", 12, 420)},
        ],
        "bad_rom_check": None,
    },
}


# ---------------------------------------------------------------------------
# 阶段 1：可控性黄金判据（验证是否真正进入受控 Gameplay，而非卡在菜单/过场）
# ---------------------------------------------------------------------------
def check_controllability(sess: SJ.StateSession, candidate_state: Path, work_dir: Path,
                          frames: int = 30) -> dict:
    """从 candidate_state 分三路测试：中立 vs 右移跳跃攻击 vs 暂停菜单，返回诊断字典。

    三路各是一条原子 attempt（load+输入+截图+RAM 同帧收尾）。旧写法把 load / run /
    ramdump 拆成三条指令，而 Lua 空闲循环每轮都在推帧，三条分支各自漂到不同帧上，
    「中立 vs 动作」根本不是同一帧号的对照 —— 11-14 实测同一份 base 状态在四个进程里
    action_effective 翻转三次，就是这个原因。
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    p_neu = work_dir / "ctrl_neutral.png"
    p_act = work_dir / "ctrl_action.png"
    p_men = work_dir / "ctrl_menu.png"
    r_neu = work_dir / "ram_neutral.bin"
    r_act = work_dir / "ram_action.bin"
    st = str(candidate_state)

    act_spec = hold("Right+A+B", frames - 5, 5)
    men_spec = hold("Start", 5, frames - 5)
    sess.attempt(st, spec="-", extra=frames, shot=str(p_neu), ram=str(r_neu))
    sess.attempt(st, spec=act_spec, extra=0, shot=str(p_act), ram=str(r_act))
    sess.attempt(st, spec=men_spec, extra=0, shot=str(p_men))

    _, _, raw_n = _load_rgb_grid(p_neu)
    _, _, raw_a = _load_rgb_grid(p_act)
    _, _, raw_m = _load_rgb_grid(p_men)

    b_neu = r_neu.read_bytes()
    b_act = r_act.read_bytes()
    ram_changed = sum(1 for x, y in zip(b_neu, b_act) if x != y)

    action_effective = (raw_n != raw_a)
    menu_effective = (raw_n != raw_m)
    return {
        "controllable": bool(action_effective and ram_changed >= 2),
        "action_effective": action_effective,
        "menu_effective": menu_effective,
        "ram_diff_bytes": ram_changed,
        "frames": frames,
        "screenshots": {
            "neutral": str(p_neu),
            "action": str(p_act),
            "menu": str(p_men),
        },
    }


def navigate_and_verify_rom(rom_path: Path, bizhawk_dir: Path, preset_key: str, out_dir: Path) -> dict:
    """执行预设导航并在终点运行可控性搜索（若仍在过场则自动分段推进最多 4 轮）。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    preset = GAME_NAV_PRESETS.get(preset_key, GAME_NAV_PRESETS["generic_nes"])
    ascii_rom = out_dir / "rom_under_test.nes"
    shutil.copy2(rom_path, ascii_rom)

    report = {
        "rom": str(rom_path),
        "sha1": sha1_file(rom_path),
        "preset": preset_key,
        "status": "blocked_resource",
        "controllable": False,
        "base_state": None,
        "base_png": None,
        "notes": [],
    }

    with SJ.StateSession(str(ascii_rom), str(bizhawk_dir), work=str(out_dir / "sess")) as sess:
        sess.run(preset["boot_wait"], shot=str(out_dir / "step0_boot.png"))

        # 洛克人 1 专属坏 ROM 检测：开机武器能量是否异常预满、选关方向键是否失效
        if preset.get("bad_rom_check") == "mm1_clear_points":
            energies = [sess.read(a) for a in range(0x006B, 0x0072)]
            if all(e > 0 for e in energies):
                report["notes"].append("警告：开机 0x006B..0x0071 武器能量已预满，疑似修改版/坏 dump")

        for idx, st in enumerate(preset["steps"], 1):
            sess.macro(st["macro"], shot=str(out_dir / f"step{idx}.png"))

        # 响应式搜索（最多推进 4 轮 × 240 帧，跳过关卡开头 Ready 冻结期）
        for round_idx in range(5):
            # save() 会追加 .state 后缀并返回真实落盘路径；必须用返回值，
            # 自拼路径会指向不存在的文件（11-20 probe-rom 实测 FileNotFoundError）。
            cand = Path(sess.save(f"cand_r{round_idx}"))
            ctrl = check_controllability(sess, cand, out_dir / f"ctrl_r{round_idx}")
            if ctrl["controllable"] and ctrl["menu_effective"]:
                final_base = out_dir / "base.state"
                final_png = out_dir / "base.png"
                shutil.copy2(cand, final_base)
                shutil.copy2(ctrl["screenshots"]["neutral"], final_png)
                report.update(
                    status="ready",
                    controllable=True,
                    base_state=str(final_base),
                    base_png=str(final_png),
                    round_found=round_idx,
                    controllability=ctrl,
                )
                break
            # 若未受控，恢复到 cand 并继续推进 240 帧 + 点按 Start
            sess.load(str(cand))
            sess.macro(hold("Start", 8, 232))

    if not report["controllable"]:
        report["notes"].append("未能在导航后进入可控制角色的真实 Gameplay，请核查 step 截图或更换干净 [!] ROM。")
    (out_dir / "nav_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


# ---------------------------------------------------------------------------
# 阶段 2：热血足球 2 专属「活 play 持球态 + 全必杀解锁」状态求解器
# ---------------------------------------------------------------------------
# 热血足球 2 比赛中暂停后输入 AAABAAABAAAAAAA 解锁全员必杀技
SOCCER2_ALL_SKILLS_CHEAT_MACRO = chain_macros(
    hold("Start", 8, 20),
    hold("A", 4, 4), hold("A", 4, 4), hold("A", 4, 4), hold("B", 4, 4),
    hold("A", 4, 4), hold("A", 4, 4), hold("A", 4, 4), hold("B", 4, 4),
    hold("A", 4, 4), hold("A", 4, 4), hold("A", 4, 4), hold("A", 4, 4),
    hold("A", 4, 4), hold("A", 4, 4), hold("A", 4, 15),
    hold("Start", 8, 20),
)

# OAM 字节判据（11-14 标定，ramdump 2048B 含 $0200 OAM 页）：
# ⚠️ 11-15 实测：SOCCER2_BALL_TILES 命中的那组 sprite 在画面上是**隐形的**（透明像素/被后景压住），
#    只能当"存在性"信号，**不得再当球坐标**。球坐标请用下方 soccer2_ball_blobs()（画面白色团块）。
SOCCER2_BALL_TILES = {0xC3, 0xC4, 0xC5, 0xD3, 0xD4, 0xD5}
SOCCER2_BALL_TILES_EXTENDED = set(range(0xC0, 0xE0))
SOCCER2_LEG_TILES = {0x10, 0x11, 0x20, 0x21, 0x30, 0x31}
SOCCER2_POSSESS_DIST = 14  # 球心距队长脚底 <14px = 我方持球（真阳性实测 13.9，待更多样本复核）


# --------------------------------------------------------------- 球坐标（画面团块）
# 11-15 实测分类学（soccer2_ball_pixel.py，jf ROM 开球帧）：
#   球        = 12×12 近白团块，area 78–80
#   球员白衫  = 10×16 / 13×15，area 114      ← 只按面积筛会把人当球
#   球网/HUD  = 16×7；中圈标记 = 13×5        ← 只按宽高筛会把网当球
# ⇒ 必须同时卡宽高与面积下限，并把 HUD 带整条裁掉。
SOCCER2_BALL_YCUT = 190          # y≥190 是 HUD 带（近白条），一律不参与连通域
SOCCER2_BALL_MIN_RGB = 190       # 近白判据用 min(R,G,B)，不是亮度
SOCCER2_BALL_W = (9, 15)
SOCCER2_BALL_H = (9, 15)
SOCCER2_BALL_AREA = 45


def soccer2_ball_blobs(png_path, ycut=SOCCER2_BALL_YCUT):
    """从一帧截图里取"球"候选，返回 [{x,y,w,h,area,cx,cy}]（按面积降序）。

    纯 Python 实现，不引 numpy/cv2，保证出片链在生产依赖里可跑。
    """
    w, h, raw = _load_rgb_grid(Path(png_path))
    hmax = min(h, int(ycut))
    mask = bytearray(w * hmax)
    for j in range(hmax):
        base = j * w * 3
        for i in range(w):
            o = base + i * 3
            if raw[o] > SOCCER2_BALL_MIN_RGB and raw[o + 1] > SOCCER2_BALL_MIN_RGB and raw[o + 2] > SOCCER2_BALL_MIN_RGB:
                mask[j * w + i] = 1
    seen = bytearray(w * hmax)
    out = []
    for j0 in range(hmax):
        for i0 in range(w):
            p0 = j0 * w + i0
            if not mask[p0] or seen[p0]:
                continue
            stack, seen[p0] = [p0], 1
            area, minx, maxx, miny, maxy = 0, i0, i0, j0, j0
            while stack:
                p = stack.pop()
                x, y = p % w, p // w
                area += 1
                minx = min(minx, x); maxx = max(maxx, x)
                miny = min(miny, y); maxy = max(maxy, y)
                for q in (p - 1, p + 1, p - w, p + w):
                    if 0 <= q < len(mask) and mask[q] and not seen[q]:
                        if q == p - 1 and x == 0:
                            continue
                        if q == p + 1 and x == w - 1:
                            continue
                        seen[q] = 1
                        stack.append(q)
            bw, bh = maxx - minx + 1, maxy - miny + 1
            if (SOCCER2_BALL_W[0] <= bw <= SOCCER2_BALL_W[1]
                    and SOCCER2_BALL_H[0] <= bh <= SOCCER2_BALL_H[1]
                    and area >= SOCCER2_BALL_AREA):
                out.append({"x": minx, "y": miny, "w": bw, "h": bh, "area": area,
                            "cx": minx + bw // 2, "cy": miny + bh // 2})
    out.sort(key=lambda b: -b["area"])
    return out


def soccer2_ball_pos(png_path):
    """球心 (cx,cy)；无候选返回 None。多个候选时取面积最大者（球是全场最实的近白团块）。"""
    b = soccer2_ball_blobs(png_path)
    return (b[0]["cx"], b[0]["cy"]) if b else None


def _oam_sprites(ram: bytes):
    out = []
    for i in range(64):
        y, t, a, x = ram[0x200 + 4 * i : 0x204 + 4 * i]
        if y <= 239:
            out.append((i, y, t, a, x))
    return out


def soccer2_oam_parse(ram: bytes):
    """返回 {cap:(x,脚底y), ball:(x,y), dist, holder_dist, holder_team}；缺标记/球时 None。"""
    spr = _oam_sprites(ram)
    marker = [s for s in spr if s[2] == 0xC0]
    ball = [s for s in spr if s[2] in SOCCER2_BALL_TILES and (s[3] & 3) == 0]
    if not marker or len(ball) < 4:
        return None
    mx = marker[0][4] + 4
    legs = [s for s in spr if s[2] in SOCCER2_LEG_TILES and abs(s[4] + 4 - mx) <= 10 and s[1] > marker[0][1]]
    if not legs:
        return None
    cy = max(s[1] for s in legs) + 8
    bx = min(s[4] for s in ball) + 8
    by = min(s[1] for s in ball) + 8
    body = [s for s in spr if (s[3] & 3) in (1, 2, 3) and s[2] != 0xC0]
    groups = []
    for s in sorted(body, key=lambda s: s[4]):
        for g in groups:
            if abs(g["x"] - (s[4] + 4)) <= 12 and abs(g["y"] - s[1]) <= 44:
                g["xs"].append(s[4] + 4)
                g["ys"].append(s[1])
                g["pal"].append(s[3] & 3)
                g["x"] = sum(g["xs"]) / len(g["xs"])
                g["y"] = sum(g["ys"]) / len(g["ys"])
                break
        else:
            groups.append({"x": s[4] + 4.0, "y": float(s[1]), "xs": [s[4] + 4], "ys": [s[1]], "pal": [s[3] & 3]})
    holder, hd = None, 1e9
    for g in groups:
        fy = max(g["ys"]) + 8
        d = ((g["x"] - bx) ** 2 + (fy - by) ** 2) ** 0.5
        if d < hd:
            hd, holder = d, g
    team = max(set(holder["pal"]), key=holder["pal"].count) if holder else -1
    opp, od = None, 1e9
    for g in groups:
        if max(set(g["pal"]), key=g["pal"].count) == 1:
            continue
        fy = max(g["ys"]) + 8
        d = ((g["x"] - mx) ** 2 + (fy - cy) ** 2) ** 0.5
        if d < od:
            od, opp = d, (round(g["x"]), round(fy))
    return {"cap": (mx, cy), "ball": (bx, by), "dist": round(((mx - bx) ** 2 + (cy - by) ** 2) ** 0.5, 1),
            "holder_dist": round(hd, 1), "holder_team": team,
            "opp": opp, "opp_dist": round(od, 1) if opp else None}


def soccer2_dir_toward(cx, cy, bx, by) -> str:
    dx, dy = bx - cx, by - cy
    parts = []
    if abs(dx) > 6:
        parts.append("Right" if dx > 0 else "Left")
    if abs(dy) > 6:
        parts.append("Down" if dy > 0 else "Up")
    return "+".join(parts)


def soccer2_possess_ok(p, opp_min: float = 40.0) -> bool:
    """净持球判据（11-14 实测）：球在队长脚边且持球者就是队长本人且无贴脸对手。

    仅 dist<14 会误判（球在队友脚下 holder_dist≠dist、或邻敌即将铲断）。
    反证格：holder_dist−dist>=0.6（球非队长持）或 opp_dist<=opp_min（贴脸）均拒。
    """
    if p is None or p.get("dist") is None:
        return False
    if p["dist"] >= SOCCER2_POSSESS_DIST:
        return False
    if p.get("holder_team") != 1:
        return False
    hd = p.get("holder_dist")
    if hd is None or abs(hd - p["dist"]) >= 0.6:
        return False
    od = p.get("opp_dist")
    return od is None or od > opp_min


def solve_soccer2_possession_base(rom_path: Path, bizhawk_dir: Path, kickoff_state: Path,
                                  out_dir: Path, attack_dir: str = "Right",
                                  apply_cheat: bool = False) -> dict:
    """从热血足球 2 的 KICK OFF 快照出发，用 OAM 字节判据求「我方净持球」base。

    11-14 实测路线：仪式冻结须首个有效输入解除；1P 固定 MF 队长、球多在对手脚下，
    A+方向传给自己四候选均无效 ⇒ 改 RAM 反馈追球控制器（靠近+B 铲球 / 队友持球按 A 要球）。
    球权/球坐标只认 OAM（$0200 起 64×4B），整图像素差判据作废（天气粒子/镜头滚动假阳性）。
    净持球 = soccer2_possess_ok（holder_team==1 且 holder_dist≈dist 且 opp>40）。
    ⚠️ 必杀未验证：CN/hack 族难度锁定+无人球同跳，约 60 触发链全负（见说明书 §26）。
    本函数只产出持球 base；super 时间线仅作诊断，**不**作为必杀已验证依据（super_verified=False）。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    ascii_rom = out_dir / "soccer2.nes"
    shutil.copy2(rom_path, ascii_rom)
    base_in = out_dir / "kickoff.state"
    shutil.copy2(kickoff_state, base_in)

    with SJ.StateSession(str(ascii_rom), str(bizhawk_dir), work=str(out_dir / "sess")) as sess:
        # ★帧对齐检查点循环（11-15 重写）：Lua 主循环空闲时每轮都在推帧，「先 ramdump 再 save」
        # 两条指令之间会漂到不确定的帧上——实测判据认可时 dist=13.9，存出来的 base 却是 18.4
        # （6 帧后球已被踢飞）⇒ base 根本不是认可的那一拍。现在每步只发一条 attempt：
        # 载入 root → 跑该段宏 → 同一帧里落 RAM 样本 + 存快照；认可后把该快照当新 root 续跑。
        root = str(base_in)
        since = hold("A", 6, 10).split(",")   # 首个有效输入：解除 KICK OFF 仪式冻结
        chase_log = []
        possess_state = None
        for i in range(150):
            rp = out_dir / f"try_{i:03d}.bin"
            sp = out_dir / f"try_{i:03d}.state"
            sess.attempt(root, spec=",".join(since), ram=str(rp), save=str(sp))
            p = soccer2_oam_parse(rp.read_bytes())
            chase_log.append({"i": i, "seg": len(since), **(p or {})})
            if p is None:
                root, since = str(sp), hold("", 20, 0).split(",")
                continue
            if soccer2_possess_ok(p):
                # 贴脚复验：dist<14 也可能只是"刚碰到的滚球"⇒ 带 8 帧进攻方向后仍贴脚才算真 base；
                # 复验同样走 attempt，认可帧与落盘帧仍然同一个。
                rq = out_dir / f"drib_{i:03d}.bin"
                sq = out_dir / f"drib_{i:03d}.state"
                sess.attempt(str(sp), spec=hold(attack_dir, 8, 0), ram=str(rq), save=str(sq))
                q = soccer2_oam_parse(rq.read_bytes())
                chase_log.append({"i": i, "glue_recheck": True, **(q or {})})
                if soccer2_possess_ok(q, opp_min=24.0):
                    possess_state = Path(sq)
                    sess.shot(str(out_dir / "possess_raw"))
                    break
                root, since = str(sq), hold(attack_dir, 10, 0).split(",")
                continue
            d = soccer2_dir_toward(*p["cap"], *p["ball"])
            if (p["holder_team"] == 1 and p["dist"] < SOCCER2_POSSESS_DIST
                    and p.get("opp_dist") is not None and p["opp_dist"] <= 40):
                away = soccer2_dir_toward(*p["cap"], *p["opp"])
                rev = {"Left": "Right", "Right": "Left", "Up": "Down", "Down": "Up"}
                back = "+".join(rev[t] for t in away.split("+") if t in rev) or "Left"
                mac = hold(back, 16, 4)
            elif p["holder_team"] == 1:
                mac = chain_macros(hold("A", 6, 6), hold("", 12))
            elif p["dist"] < 24 and d:
                mac = chain_macros(hold(d, 10), hold("B", 6, 6))
            elif d:
                mac = hold(d, 14, 4)
            else:
                mac = hold("B", 6, 6)
            root, since = str(sp), mac.split(",")
        (out_dir / "chase_log.json").write_text(json.dumps(chase_log, ensure_ascii=False, indent=1), encoding="utf-8")
        if possess_state is None:
            return {"status": "inconclusive", "reason": "150 步追球控制器未让我方持球（OAM 球距队长始终 >=14px）"}

        if apply_cheat:
            # 持球中暂停输全必杀金手指（暂停冻结球权）；尾 Start 可能再暂停 ⇒ RAM 活性自检。
            sess.load(str(possess_state))
            sess.macro(SOCCER2_ALL_SKILLS_CHEAT_MACRO)
            cand = Path(sess.save(str(out_dir / "possess_cheat")))
            # 活性与球权合一循环：2 帧 RAM tick 判冻结（无输入长窗会让球滚离/被断），
            # 冻结补 Start；活则追球贴回队长，dist<14 即存最终 base。
            sess.load(str(cand))
            final = None
            p = None
            for _ in range(60):
                ra = out_dir / "post_a.bin"
                sess.ramdump(str(ra))
                sess.run(2)
                rb = out_dir / "post_b.bin"
                sess.ramdump(str(rb))
                if ra.read_bytes() == rb.read_bytes():
                    sess.macro(hold("Start", 8, 10))
                    continue
                p = soccer2_oam_parse(rb.read_bytes())
                if soccer2_possess_ok(p):
                    final = Path(sess.save(str(out_dir / "possess_final")))
                    sess.shot(str(out_dir / "possess_base"))
                    break
                if p is None:
                    sess.run(18)
                    continue
                d = soccer2_dir_toward(*p["cap"], *p["ball"])
                if p["holder_team"] == 1:
                    sess.macro(chain_macros(hold("A", 6, 6), hold("", 12)))
                elif p["dist"] < 24 and d:
                    sess.macro(chain_macros(hold(d, 10), hold("B", 6, 6)))
                elif d:
                    sess.macro(hold(d, 14, 4))
                else:
                    sess.macro(hold("B", 6, 6))
            if final is None:
                return {"status": "inconclusive", "reason": f"金手指后 60 步未恢复持球: {p}"}
            cand = final
        else:
            # 11-15 更正：联盟实测秘技码无效（必杀全清单 §2 probe18 三段对照均无燕返翻转），
            # 而输码必须进暂停菜单、出来球权已易手 ⇒ 默认不输码，追球认可的贴脚带球态即最终 base。
            sess.load(str(possess_state))
            rp0 = out_dir / "final_parse.bin"
            sess.ramdump(str(rp0))
            p = soccer2_oam_parse(rp0.read_bytes())
            if not soccer2_possess_ok(p, opp_min=24.0):
                return {"status": "inconclusive", "reason": f"贴脚 base 载入后判据复验失败: {p}"}
            sess.shot(str(out_dir / "possess_base"))
            cand = final = possess_state
        # 脱压带球：对手贴脸时 A+B 起跳前摇会被铲断（11-14 实测球被抢走⇒必杀空放）。
        safe = False
        for _ in range(8):
            rp = out_dir / "safe.bin"
            sess.ramdump(str(rp))
            q = soccer2_oam_parse(rp.read_bytes())
            if q is None:
                sess.run(10)
                continue
            if soccer2_possess_ok(q):
                safe = True
                break
            if q["dist"] >= SOCCER2_POSSESS_DIST:
                d = soccer2_dir_toward(*q["cap"], *q["ball"])
                sess.macro(hold(d or "B", 10, 2))
                continue
            away = soccer2_dir_toward(*q["opp"], *q["cap"]) if q["opp"] else "Right"
            sess.macro(hold(away or "Right", 20, 2))
        if not safe:
            return {"status": "possession_only", "reason": "8 步脱压带球仍被对手贴脸（opp_dist<=40），未跑必杀触发窗",
                    "possess_base_state": str(final), "possess_base_png": str(out_dir / "possess_base.png")}
        cand = Path(sess.save(str(out_dir / "possess_safe")))

        # 必杀触发窗：人球同跳 A+B → 最高点 B（无方向）。逐 3 帧 RAM+截图取球 tile 时间线。
        fdir = out_dir / "super_frames"
        fdir.mkdir(parents=True, exist_ok=True)
        sess.load(str(cand))
        sess.macro(hold("A+B", 6, 14), shot=str(fdir / "jump"))
        timeline = []
        fc = 20
        for k in range(34):
            if k == 20:
                sess.macro(hold("B", 6, 15))
                fc += 21
            sess.run(3)
            fc += 3
            tp = fdir / f"t{k:02d}.bin"
            sess.ramdump(str(tp))
            q = soccer2_oam_parse(tp.read_bytes())
            tiles = sorted({t for (_, _, t, a, _) in _oam_sprites(tp.read_bytes())
                            if t in SOCCER2_BALL_TILES_EXTENDED and (a & 3) == 0})
            timeline.append({"k": k, "frame": fc, "ball": q["ball"] if q else None, "tiles": tiles})
            if k % 2 == 0:
                sess.shot(str(fdir / f"t{k:02d}"))
        (out_dir / "super_timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1), encoding="utf-8")
        special = [t["k"] for t in timeline if t["tiles"] and not set(t["tiles"]) <= SOCCER2_BALL_TILES]
        final_state = out_dir / "possess_base.state"
        final_png = out_dir / "possess_base.png"
        shutil.copy2(cand, final_state)
        # 必杀声称闸门：special-tile 对旋转盲（正常飞行球同签名，11-14 实测）⇒ 不得据此判 ready。
        # CN/hack 族难度锁定+无人球同跳，必杀未验证；special 仅作诊断，super_verified 恒 False，
        # 直到有标定视觉检测器（全屏闪/球变形）+ 恒量反证格通过（见说明书 §26）。
        return {
            "status": "possession_only",
            "super_verified": False,
            "possession_dist": p["dist"],
            "super_special_tile_frames": special,
            "possess_base_state": str(final_state),
            "possess_base_png": str(final_png),
            "super_frames_dir": str(fdir),
            "apex_shot_preview": str(fdir / "t20.png"),
        }


# ---------------------------------------------------------------------------
# 阶段 3：正反例全帧采样 + 视觉检测器自动标定（彻底告别手猜 frame / region / rgb）
# ---------------------------------------------------------------------------
# 标定闸门（11-15 实测立规）：
#   镜头一滚，整片草坪都进 diff_pts，"最大色簇"就是背景绿，region 覆盖 97% 屏幕、
#   pos/neg 只差 0.007 —— 这种判据既不能区分要素，算出来的 min_fraction 还会 >1（永不满足）。
#   所以候选必须：局部（面积上限）、有绝对余量、并且存在能把正负例分开的阈值。
CALIB_MAX_REGION_AREA = 0.25
CALIB_MIN_MARGIN = 0.05
CALIB_MAX_FRACTION = 0.95
# 静态地物签名闸门（11-24 fire_storm 蓝瓦片案）：胜出签名在正例全程的
# 出现/消失幅度低于此值 = 背景瓦片被负臂物体遮挡的假区分度，拒绝写包。
CALIB_FLICKER_MIN = 0.04


def _parse_fraction(reason_str: str) -> float:
    """从 detect 的 reason 里取实测 fraction="... fraction=0.123 ..."。"""
    for tok in (reason_str or "").split():
        if tok.startswith("fraction="):
            return float(tok.split("=", 1)[1])
    return 0.0


def _calib_cluster(cluster, w, h, pos_png, neg_png):
    """把一个差异色簇试成检测器；区分不足/覆盖全屏/阈值不可分离时返回 None。"""
    xs = [pt[0] for pt in cluster]
    ys = [pt[1] for pt in cluster]
    avg_r = int(round(sum(pt[2] for pt in cluster) / len(cluster)))
    avg_g = int(round(sum(pt[3] for pt in cluster) / len(cluster)))
    avg_b = int(round(sum(pt[4] for pt in cluster) / len(cluster)))

    # 归一化 region，加垫防 int() 向下截断越界（见说明书 §15）
    x0 = max(0.01, round((min(xs) - 4) / w, 3))
    y0 = max(0.01, round((min(ys) - 4) / h, 3))
    x1 = min(0.99, round((max(xs) + 5) / w, 3))
    y1 = min(0.99, round((max(ys) + 5) / h, 3))
    if x1 - x0 < 0.05:
        x1 = min(0.99, round(x0 + 0.06, 3))
    if y1 - y0 < 0.05:
        y1 = min(0.99, round(y0 + 0.06, 3))
    if (x1 - x0) * (y1 - y0) > CALIB_MAX_REGION_AREA:
        return None

    probe = CheckSpec(
        check_id="auto_calibrated_visual",
        plugin_id="frame_region_color_fraction",
        params={"region": [x0, y0, x1, y1], "rgb": [avg_r, avg_g, avg_b],
                "tol": 26, "min_fraction": 0.001},
        required=True,
    )
    pos_frac = _parse_fraction(detect.run_check(probe, str(pos_png)).reason)
    neg_frac = _parse_fraction(detect.run_check(probe, str(neg_png)).reason)
    if pos_frac < 0.004 or pos_frac - neg_frac < CALIB_MIN_MARGIN:
        return None

    lo = neg_frac * 2.2 + 0.003
    if lo >= pos_frac * 0.9:
        return None
    min_frac = round(min(CALIB_MAX_FRACTION, max(lo, pos_frac * 0.45)), 3)
    if not (neg_frac < min_frac <= pos_frac * 0.9):
        return None

    return {
        "cluster_size": len(cluster),
        "region": [x0, y0, x1, y1],
        "rgb": [avg_r, avg_g, avg_b],
        "tol": 26,
        "min_fraction": min_frac,
        "pos_fraction": round(pos_frac, 4),
        "neg_fraction": round(neg_frac, 4),
        "margin": round(pos_frac - neg_frac, 4),
    }


def calibrate_element_detector(pos_dir: Path, neg_dir: Path) -> dict:
    """给定同一要素的正例帧目录与反例帧目录，自动寻找视觉差异峰值帧并计算 CheckSpec 参数。"""
    pos_frames = sorted(pos_dir.glob("f*.png"))
    neg_frames = sorted(neg_dir.glob("f*.png"))
    total = min(len(pos_frames), len(neg_frames))
    if total < 3:
        raise RuntimeError(f"正反例帧数不足 ({total})，无法标定")

    best = None
    # 从第 2 帧开始扫描，寻找弹幕/特效/动作差异最显著的一帧
    for idx in range(2, total):
        w, h, p_bytes = _load_rgb_grid(pos_frames[idx])
        _, _, n_bytes = _load_rgb_grid(neg_frames[idx])

        diff_pts = []
        for y in range(h):
            row_off = y * w * 3
            for x in range(w):
                i = row_off + x * 3
                pr, pg, pb = p_bytes[i], p_bytes[i + 1], p_bytes[i + 2]
                nr, ng, nb = n_bytes[i], n_bytes[i + 1], n_bytes[i + 2]
                if abs(pr - nr) + abs(pg - ng) + abs(pb - nb) > 42 and (pr + pg + pb) > 75:
                    diff_pts.append((x, y, pr, pg, pb))

        if len(diff_pts) < 10:
            continue

        # 颜色聚类，逐簇试成局部检测器（最大的三簇），取余量最宽的一枪
        buckets = {}
        for x, y, r, g, b in diff_pts:
            key = (r // 16, g // 16, b // 16)
            buckets.setdefault(key, []).append((x, y, r, g, b))

        for cluster in sorted(buckets.values(), key=len, reverse=True)[:3]:
            cand = _calib_cluster(cluster, w, h, pos_frames[idx], neg_frames[idx])
            if cand and (best is None or cand["margin"] > best["margin"]):
                cand["frame"] = idx
                best = cand

        # 稀薄签名（11-20 thunder_beam 实测：全屏三向闪电整簇外框占比≈0.03，
        # 过不了 CALIB_MIN_MARGIN，但弹体交汇结处 24×24 窗 pos=0.181/neg=0）：
        # 整簇外框失败不等于无签名，在簇内滑稠密子窗重试。闸门常数不动，
        # 子窗仍走 _calib_cluster 同一套余量/可分性/面积闸门。
        for cluster in sorted(buckets.values(), key=len, reverse=True)[:3]:
            if len(cluster) < 30:
                continue
            xs = [p[0] for p in cluster]
            ys = [p[1] for p in cluster]
            bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
            bw, bh = bx1 - bx0 + 1, by1 - by0 + 1
            # 整屏级簇（镜头滚动/背景换色）每个子窗都"稠密"，子窗搜索会绕过
            # 局部性闸门 => 外框本身超面积的簇不做子窗救援（selftest D 反证）。
            if (bw / w) * (bh / h) > CALIB_MAX_REGION_AREA:
                continue
            pre = [[0] * (bw + 1) for _ in range(bh + 1)]
            for x, y, _r, _g, _b in cluster:
                pre[y - by0 + 1][x - bx0 + 1] = 1
            for yy in range(1, bh + 1):
                row, prev, acc = pre[yy], pre[yy - 1], 0
                for xx in range(1, bw + 1):
                    acc += row[xx]
                    row[xx] = acc + prev[xx]
            wins = []
            for side in sorted({max(8, w // 10), max(12, w // 8), max(16, w // 6)}):
                for y0 in range(by0, by1 - side + 2, 8):
                    for x0 in range(bx0, bx1 - side + 2, 8):
                        ly, lx = y0 - by0, x0 - bx0
                        cnt = (pre[ly + side][lx + side] - pre[ly][lx + side]
                               - pre[ly + side][lx] + pre[ly][lx])
                        if cnt >= 30 and cnt / (side * side) >= CALIB_MIN_MARGIN + 0.03:
                            wins.append((cnt / (side * side), x0, y0, side))
            for _dens, x0, y0, side in sorted(wins, reverse=True)[:2]:
                sub = [p for p in cluster
                       if x0 <= p[0] < x0 + side and y0 <= p[1] < y0 + side]
                cand = _calib_cluster(sub, w, h, pos_frames[idx], neg_frames[idx])
                if cand and (best is None or cand["margin"] > best["margin"]):
                    cand["frame"] = idx
                    best = cand

    if not best:
        raise RuntimeError(
            "正反例之间没有可分离的局部视觉签名：要么触发宏/前置补丁未使要素生效，"
            "要么差异全是镜头滚动与背景色（整屏级差异不能当要素判据）")

    # 静态地物签名闸门：真特效随触发出现/消失；背景瓦片只在负臂被敌人物体
    # 遮挡时才"显得不同"，在正例全程恒定。用运行时同一插件在全部正例帧上
    # 重跑胜出签名，幅度不足即拒绝（11-24 fire_storm 蓝瓦片案）。
    probe = CheckSpec(
        check_id="auto_calibrated_visual",
        plugin_id="frame_region_color_fraction",
        params={"region": best["region"], "rgb": best["rgb"], "tol": best["tol"],
                "min_fraction": 0.001},
        required=True,
    )
    series = [_parse_fraction(detect.run_check(probe, str(p)).reason)
              for p in pos_frames]
    if max(series) - min(series) < CALIB_FLICKER_MIN:
        raise RuntimeError(
            "标定胜出签名在正例全程几乎恒定（max-min<%.2f）：静态地物/背景瓦片被"
            "负臂物体遮挡形成的假区分度（11-24 fire_storm 蓝瓦片案），不是随触发出现/"
            "消失的特效签名。换素材，或让 dump 窗口盖住特效出现前后的帧后重标"
            % CALIB_FLICKER_MIN)
    return best


def _frame_window(frames, frame_range):
    if frame_range is None:
        return list(range(len(frames)))
    start, end = frame_range
    if type(start) is not int or type(end) is not int or not (0 <= start <= end < len(frames)):
        raise RuntimeError(f"frame_range 越界: {frame_range}, 可用 0..{len(frames) - 1}")
    return list(range(start, end + 1))


def calibrate_region_color_detector(pos_dir: Path, neg_dir: Path, region: list,
                                     frame_range=None) -> dict:
    """在指定局部区域内标定颜色签名，适合 HUD 提示、回血数字等稀疏效果。"""
    pos_frames = sorted(pos_dir.glob("f*.png"))
    neg_frames = sorted(neg_dir.glob("f*.png"))
    total = min(len(pos_frames), len(neg_frames))
    if total < 3:
        raise RuntimeError(f"正反例帧数不足 ({total})，无法标定")
    w, h, _ = _load_rgb_grid(pos_frames[0])
    rx0, ry0, rx1, ry1 = detect._pixel_box(region, w, h)
    best = None
    for idx in _frame_window(pos_frames[:total], frame_range):
        _, _, p_bytes = _load_rgb_grid(pos_frames[idx])
        _, _, n_bytes = _load_rgb_grid(neg_frames[idx])
        cluster = []
        for y in range(ry0, ry1):
            for x in range(rx0, rx1):
                i = (y * w + x) * 3
                pr, pg, pb = p_bytes[i:i + 3]
                nr, ng, nb = n_bytes[i:i + 3]
                if abs(pr - nr) + abs(pg - ng) + abs(pb - nb) > 42 and pr + pg + pb > 75:
                    cluster.append((x, y, pr, pg, pb))
        if len(cluster) < 10:
            continue
        buckets = {}
        for point in cluster:
            key = tuple(value // 16 for value in point[2:])
            buckets.setdefault(key, []).append(point)
        for bucket in sorted(buckets.values(), key=len, reverse=True)[:3]:
            cand = _calib_cluster(bucket, w, h, pos_frames[idx], neg_frames[idx])
            if cand and (best is None or cand["margin"] > best["margin"]):
                cand["frame"] = idx
                best = cand
    if not best:
        raise RuntimeError("指定区域内没有可分离的颜色签名")
    probe = CheckSpec(
        check_id="auto_calibrated_visual",
        plugin_id="frame_region_color_fraction",
        params={"region": best["region"], "rgb": best["rgb"], "tol": best["tol"],
                "min_fraction": 0.001},
        required=True,
    )
    series = [_parse_fraction(detect.run_check(probe, str(path)).reason)
              for path in pos_frames[:total]]
    if max(series) - min(series) < CALIB_FLICKER_MIN:
        raise RuntimeError("标定颜色签名在正例全程几乎恒定，不能作为随触发出现的效果")
    return {**best, "plugin_id": "frame_region_color_fraction"}


def calibrate_aligned_element_detector(pos_dir: Path, neg_dir: Path, region: list,
                                       alignment_region=None, frame_range=None,
                                       max_shift=0, max_dy=0,
                                       max_global_changed_fraction=0.25) -> dict:
    """标定镜头平移补偿后的局部差分，并用全局变化上限拒绝全屏闪白。"""
    pos_frames = sorted(pos_dir.glob("f*.png"))
    neg_frames = sorted(neg_dir.glob("f*.png"))
    total = min(len(pos_frames), len(neg_frames))
    if total < 3:
        raise RuntimeError(f"正反例帧数不足 ({total})，无法标定")
    alignment_region = alignment_region or [0.0, 0.125, 1.0, 0.4875]
    rows = []
    for idx in range(total):
        current = detect._arr(pos_frames[idx])
        reference = detect._arr(neg_frames[idx])
        metrics = detect.aligned_difference_metrics(
            current, reference, region, alignment_region,
            max_shift=max_shift, max_dy=max_dy, diff_threshold=42,
        )
        rows.append({"frame": idx, **metrics})
    eligible = [row for row in rows if row["frame"] in _frame_window(pos_frames[:total], frame_range)
                and row["global_changed_fraction"] <= max_global_changed_fraction]
    if not eligible:
        raise RuntimeError("指定窗口内没有通过全局闪白上限的局部差异帧")
    best = max(eligible, key=lambda row: row["local_changed_fraction"])
    pos_frac = best["local_changed_fraction"]
    neg_metrics = detect.aligned_difference_metrics(
        detect._arr(neg_frames[best["frame"]]), detect._arr(neg_frames[best["frame"]]),
        region, alignment_region, max_shift=max_shift, max_dy=max_dy, diff_threshold=42,
    )
    neg_frac = neg_metrics["local_changed_fraction"]
    if pos_frac < 0.02 or pos_frac - neg_frac < CALIB_MIN_MARGIN:
        raise RuntimeError("对齐后局部差分余量不足，不能作为要素签名")
    lo = neg_frac * 2.2 + 0.003
    if lo >= pos_frac * 0.9:
        raise RuntimeError("对齐差分不存在可分离阈值")
    min_frac = round(min(CALIB_MAX_FRACTION, max(lo, pos_frac * 0.45)), 3)
    series = [row["local_changed_fraction"] for row in rows]
    if max(series) - min(series) < CALIB_FLICKER_MIN:
        raise RuntimeError("对齐签名在正例全程几乎恒定，可能是静态背景")
    return {
        "frame": best["frame"],
        "region": list(region),
        "alignment_region": list(alignment_region),
        "max_shift": max_shift,
        "max_dy": max_dy,
        "diff_threshold": 42,
        "min_changed_fraction": min_frac,
        "max_global_changed_fraction": max_global_changed_fraction,
        "pos_fraction": round(pos_frac, 4),
        "neg_fraction": round(neg_frac, 4),
        "margin": round(pos_frac - neg_frac, 4),
        "shift": [best["dx"], best["dy"]],
        "reference_frame": str(neg_frames[best["frame"]]),
        "plugin_id": "frame_pair_aligned_region_difference",
    }


def calibrate_showcase_pack(pack_path: Path, work_dir: Path, only_ids=None) -> dict:
    """对 showcase.json 中的每个要素实跑一次正反例 dump，自动标定并回写 detection 字段。"""
    doc = showcase.load_spec(str(pack_path))
    paths = showcase.resource_paths(str(pack_path), doc)
    work_dir.mkdir(parents=True, exist_ok=True)

    summary = []
    platform = str(doc.get("platform", "NES")).upper()
    if platform == "NES":
        session_cls = SJ.StateSession
        session_kwargs = {"core": doc.get("core", "NesHawk"),
                          "system": doc.get("system", "NES")}
    else:
        from .retro_platforms import MultiPlatformStateSession, get_platform_spec
        p_spec = get_platform_spec(platform)
        session_cls = MultiPlatformStateSession
        session_kwargs = {"platform": platform,
                          "core": doc.get("core", p_spec["default_core"]),
                          "system": doc.get("system", p_spec["system"])}
    with session_cls(
        paths["rom"], paths["bizhawk"],
        work=str(work_dir / "calib_sess"), **session_kwargs
    ) as sess:
        for el in doc["elements"]:
            eid = el["element_id"]
            if only_ids and eid not in only_ids:
                continue
            if any(key in el for key in showcase.ACCEPTANCE_FIELDS):
                raise RuntimeError(f"{eid}: 已有正式三类验收声明，拒绝自动标定覆盖")
            trig = el["trigger"]
            ctrl = el.get("negative_control") or {}
            macro = trig.get("macro") or ""
            extra = trig.get("extra", 0)
            total = showcase._macro_frames(macro, platform) + extra
            nmacro = ctrl.get("macro")
            nextra = total - showcase._macro_frames(nmacro, platform)
            patches = trig.get("patches") or []
            npatches = ctrl["patches"] if "patches" in ctrl else patches

            state_file = paths["element_base_states"].get(eid, paths["base_state"])
            pos_dir = work_dir / "frames" / eid / "pos"
            neg_dir = work_dir / "frames" / eid / "neg"

            # 资产仓是中文路径，Lua io 只认 ASCII：标定同样必须先过搬运这一步，否则 dump 直接 SchemaError
            state_ascii = sess.use_state(str(state_file), name=eid)
            sess.dump(str(pos_dir), spec=macro, extra=extra, state=state_ascii, patches=patches)
            sess.dump(str(neg_dir), spec=nmacro, extra=nextra, state=state_ascii, patches=npatches)

            cal = calibrate_element_detector(pos_dir, neg_dir)
            el["detection"] = {
                "frame": cal["frame"],
                "candidate_only": True,
                "success_checks": [
                    {
                        "check_id": f"{eid}_visual_sig",
                        "plugin_id": "frame_region_color_fraction",
                        "params": {
                            "region": cal["region"],
                            "rgb": cal["rgb"],
                            "tol": cal["tol"],
                            "min_fraction": cal["min_fraction"],
                        },
                        "required": True,
                    }
                ],
            }
            summary.append({"element_id": eid, **cal})
            print(
                f"[标定完成] {eid}: frame={cal['frame']} region={cal['region']} "
                f"rgb={cal['rgb']} pos={cal['pos_fraction']:.3f} neg={cal['neg_fraction']:.3f} "
                f"-> min_fraction={cal['min_fraction']}"
            )
            # 逐要素原子回写（11-20 实测：整轮结束才写盘 ⇒ 中途某要素标定抛错
            # 会把前面已标好的参数一起丢，生产 run 拿旧猜参全 fail）。
            tmp = pack_path.with_name(pack_path.name + ".calib_tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, pack_path)

    return {"pack": str(pack_path), "calibrated": summary,
            "acceptance_status": "candidate_only",
            "note": "自动视觉差分只生成 detection.success_checks 候选；action/effect/capture 必须另行显式声明并复验"}


# ---------------------------------------------------------------------------
# 阶段 4：全自动通关流水线（自动转换 FCEUX .fm2/.fcm + 录制 + 边框合成）
# ---------------------------------------------------------------------------
def run_auto_playthrough(game_query: str, out_dir: Path, frames: int = None, audio: bool = True, template: str = "fc_tianma_cover"):
    """一键跑通任意名作的 TAS 通关视频：若电影为 FCEUX .fm2/.fcm 则自动先转 .bk2 再走 auto 生产链。"""
    lib = R.DEFAULT_LIB
    pubs = R.load_publications(lib)
    q = game_query.strip().lower()
    cands = [p for p in pubs if q in p.get("game", "").lower()]
    if not cands:
        raise SystemExit(f"在 publications.json 中未找到匹配 '{game_query}' 的出版物")

    # 若存在 FCEUX 电影尚未转 .bk2，自动调用 fceux.convert_publication
    for pub in cands:
        rel = pub.get("local_movie") or ""
        if rel.lower().endswith((".fm2", ".fcm", ".fm3")):
            plat = pub.get("platform") or "NES"
            conv = Path(lib) / "_converted" / plat / f"{pub['id']}.bk2"
            if not conv.is_file() and (Path(lib) / rel).is_file():
                try:
                    FCEUX.convert_publication(pub, lib)
                    print(f"[FCEUX->BK2] 已自动转换出版物 {pub['id']} ({pub.get('game')}) -> {conv}")
                except Exception as e:
                    print(f"[FCEUX->BK2 跳过] {pub['id']}: {e}")

    spec = AUTO.JobSpec(
        game=game_query,
        job_type="playthrough",
        source="movie",
        frames=frames,
        audio=audio,
        template=template,
        out=str(out_dir),
    )
    res = AUTO.orchestrate(spec, lib=lib, out_dir=str(out_dir))
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_probe = sub.add_parser("probe-rom", help="自动导航并验证 ROM 是否能真正进入可控 Gameplay")
    p_probe.add_argument("--rom", required=True, help="ROM 路径")
    p_probe.add_argument("--preset", default="generic_nes", choices=sorted(GAME_NAV_PRESETS))
    p_probe.add_argument("--out", default=str(SCRATCH_ROOT / "probe"))
    p_probe.add_argument("--bizhawk", default=None,
                         help="默认取 registry 发现的 2.8；可指定隔离副本目录（原件 config 不动）")

    p_soc = sub.add_parser("solve-soccer2-base", help="从热血足球2 KICK OFF 快照自动求解贴脚带球 base")
    p_soc.add_argument("--rom", required=True)
    p_soc.add_argument("--kickoff-state", required=True)
    p_soc.add_argument("--out", default=str(SCRATCH_ROOT / "soccer2_possess"))
    p_soc.add_argument("--attack-dir", default="Right", choices=("Left", "Right", "Up", "Down"),
                       help="带球推进方向（1P 在左半场防守⇒Right 朝对方球门）")
    p_soc.add_argument("--apply-cheat", action="store_true",
                       help="额外输全必杀秘技码；联盟实测该码无效，默认关闭")

    p_cal = sub.add_parser("calibrate", help="对 showcase.json 执行正反例全帧采样并自动回写最佳检测框与颜色阈值")
    p_cal.add_argument("--pack", required=True)
    p_cal.add_argument("--only", default=None, help="逗号分隔的 element_id")
    p_cal.add_argument("--work", default=str(SCRATCH_ROOT / "calib_work"))

    p_prod = sub.add_parser("produce", help="先自动标定（可选）再调用 taspipe.showcase 正式生产全要素合辑 reel.mp4")
    p_prod.add_argument("--pack", required=True)
    p_prod.add_argument("--out", required=True)
    p_prod.add_argument("--work", default=str(SCRATCH_ROOT / "prod_work"))
    p_prod.add_argument("--template", default=None)
    p_prod.add_argument("--skip-calibrate", action="store_true")

    p_play = sub.add_parser("playthrough", help="一键转换 FCEUX 电影并跑通整游戏 TAS 通关视频出片")
    p_play.add_argument("--game", required=True)
    p_play.add_argument("--out", required=True)
    p_play.add_argument("--frames", type=int, default=None)
    p_play.add_argument("--audio", action="store_true")
    p_play.add_argument("--template", default="fc_tianma_cover")

    args = ap.parse_args()
    bh_map = R.discover_bizhawk(R.DEFAULT_EMU)
    bh_dir = bh_map.get("2.8") or next(iter(bh_map.values()), None)

    if args.cmd == "probe-rom":
        bh_dir = args.bizhawk or bh_dir
        if not bh_dir:
            raise SystemExit("未找到 BizHawk 目录")
        res = navigate_and_verify_rom(Path(args.rom), Path(bh_dir), args.preset, Path(args.out))
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["status"] == "ready" else 2

    if args.cmd == "solve-soccer2-base":
        if not bh_dir:
            raise SystemExit("未找到 BizHawk 目录")
        res = solve_soccer2_possession_base(Path(args.rom), Path(bh_dir), Path(args.kickoff_state),
                                            Path(args.out), attack_dir=args.attack_dir,
                                            apply_cheat=args.apply_cheat)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["status"] in ("ready", "possession_only") else 2

    if args.cmd == "calibrate":
        only = [x.strip() for x in args.only.split(",") if x.strip()] if args.only else None
        res = calibrate_showcase_pack(Path(args.pack), Path(args.work), only_ids=only)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.cmd == "produce":
        if not args.skip_calibrate:
            calibrate_showcase_pack(Path(args.pack), Path(args.work))
        rep = showcase.run(args.pack, args.out, template=args.template, work_dir=args.work)
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if rep.get("status") == "done" else 2

    if args.cmd == "playthrough":
        res = run_auto_playthrough(args.game, Path(args.out), frames=args.frames, audio=args.audio, template=args.template)
        return 0 if res.get("status") == "done" else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
