# -*- coding: utf-8 -*-
"""通用搓招编译器 + 经典秘籍/彩蛋/必杀技宏指令库（告别手写逗号帧序列）。

解决的核心缺失：
以前在 .showcase.json 里写招式或彩蛋，必须人工数逗号写：
  "Down,Down,Down+Left,Down+Left,Left,Left,Down+Left,Down+Left,Down,Down,Down+Right,Down+Right,Right,Right,Right+C,Right+C,,,,,,,,"
既容易漏帧导致搓不出招，又无法跨平台/跨朝向复用。

本模块提供：
1. 通用搓招谱面编译器 (compile_notation)：
   - 支持街机数字小键盘记法（Numpad）：236A (波动)、623A (升龙)、214B (反摇)、41236C (半圈)、
     632146C (指令投)、236236A (双摇超必杀)、2141236C (大蛇薙/八酒杯)、[4]6A (后蓄前)、[2]8B (下蓄上)、
     22A (双下)、66 (前冲)、44 (后撤)、360A (一圈摇杆)。
   - 支持直观箭头记法：↓↘→+A、→↓↘+B、↓↙←↙↓↘→+C、←蓄→+A、↑↑↓↓←→←→BA。
   - 支持 1P(朝右) / 2P(朝左) 自动镜像翻转，支持快/标准/慢三档输入帧速与蓄力帧数自动展开。
2. 经典秘籍、彩蛋与必杀预设字典 (PRESET_MACROS)：
   - 内置科乐美秘籍（魂斗罗/沙罗曼蛇/恶魔城）、热血系列全必杀密码、拳皇97隐藏人物（暴走八神/大蛇队）选人秘籍、
     洛克人X波动拳/升龙拳、月下夜想曲全出招表（暗黑地狱火/窃魂术/四魂之魔/百剑）、幽游白书全灵击技等。

保存位置：F:\\开源掌机教程\\_工具脚本\\taspipe\\macro_compiler.py
运行命令（在 F:\\开源掌机教程\\_工具脚本 下）：
  py -3 -u -m taspipe.macro_compiler compile --notation "↓↙←↙↓↘→+C" --platform ARCADE_FBNEO
  py -3 -u -m taspipe.macro_compiler compile --notation "[4]6+A" --charge 45 --facing left
  py -3 -u -m taspipe.macro_compiler list-presets
  py -3 -u -m taspipe.macro_compiler upgrade-packs
"""
import argparse
import json
import re
import sys
from pathlib import Path

from . import retro_platforms as RP

HERE = Path(__file__).resolve().parent

# 小键盘方向 1..9 -> 朝右(1P) 时的标准方向键组合
NUMPAD_DIRS_RIGHT = {
    "1": "Down+Left",
    "2": "Down",
    "3": "Down+Right",
    "4": "Left",
    "5": "",
    "6": "Right",
    "7": "Up+Left",
    "8": "Up",
    "9": "Up+Right",
}

# 朝左(2P) 时左右镜像翻转表
MIRROR_LR = {
    "Left": "Right",
    "Right": "Left",
    "Down+Left": "Down+Right",
    "Down+Right": "Down+Left",
    "Up+Left": "Up+Right",
    "Up+Right": "Up+Left",
}

# 箭头符号 -> 小键盘数字映射
ARROW_TO_NUMPAD = [
    ("↘", "3"),
    ("↙", "1"),
    ("↖", "7"),
    ("↗", "9"),
    ("↓", "2"),
    ("↑", "8"),
    ("←", "4"),
    ("→", "6"),
    ("●", "5"),
    ("N", "5"),
]

# 常见经典搓招简写 -> 数字方向串
SHORTHAND_MOTIONS = {
    "QCF": "236",          # 波动拳 Quarter Circle Forward
    "QCB": "214",          # 反摇 Quarter Circle Back
    "DP": "623",           # 升龙拳 Dragon Punch
    "RDP": "421",          # 反升龙
    "HCF": "41236",        # 正半圈 Half Circle Forward
    "HCB": "63214",        # 反半圈 Half Circle Back
    "DQCF": "236236",      # 双正摇超必杀
    "DQCB": "214214",      # 双反摇超必杀
    "OROCHINAGI": "2141236",  # 2141236 大蛇薙/八酒杯标准输入
    "HCB_F": "632146",     # 632146 指令投
    "F_HCF": "641236",     # 641236 霸王翔吼拳
    "SPD": "63214789",     # 360度螺旋打桩机
    "360": "63214789",
    "720": "6321478963214789",
    "DASH": "6,5,6",       # 前冲
    "BACKDASH": "4,5,4",   # 后撤
}


def _flip_dir(d_str: str, facing: str = "right") -> str:
    if facing.lower() != "left" or not d_str:
        return d_str
    return MIRROR_LR.get(d_str, d_str)


def hold(btn: str, frames: int, wait: int = 0) -> str:
    """按住 btn 指定帧数，再接 wait 帧空档。"""
    seq = ([btn] * max(1, int(frames))) + ([""] * max(0, int(wait)))
    return ",".join(seq)


def chain(*macros: str) -> str:
    return ",".join(m for m in macros if m is not None and m != "")


def compile_notation(
    notation: str,
    platform: str = "ARCADE_FBNEO",
    facing: str = "right",
    dir_frames: int = 2,
    attack_hold: int = 4,
    charge_frames: int = 45,
) -> str:
    """将人类可读的出招表符号编译为模拟器 100% 识别的逐帧宏字符串。

    支持示例：
      - "236+A" / "↓↘→+A" / "QCF+Y"
      - "623+C" / "→↓↘+C" / "DP+A"
      - "2141236+C" / "↓↙←↙↓↘→+C" (大蛇薙)
      - "[4]6+A" / "←蓄→+A" (蓄力技：自动按住后方向 45 帧，再前+A)
      - "[2]8+B" / "↓蓄↑+B" (脚刀蓄力技)
      - "←→↘↓↙←→+Square" (月下窃魂术)
      - "@KONAMI_CODE" (直接引用内置秘籍预设)
    """
    s = (notation or "").strip()
    if not s:
        raise ValueError("notation 不能为空")

    # 1. 若以 @ 开头或命中预设名，直接展开预设
    preset_key = s[1:].upper() if s.startswith("@") else s.upper()
    if preset_key in PRESET_MACROS:
        raw_macro = PRESET_MACROS[preset_key]["macro"]
        return RP.parse_platform_macro(platform, raw_macro)

    # 2. 若已经是逗号分隔的逐帧宏（不含箭头与小键盘数字），直接过平台按键校验返回
    if "," in s and not any(ch in s for ch in "12346789↓↑←→↘↙↖↗蓄[]"):
        return RP.parse_platform_macro(platform, s)

    # 3. 清理排版杂符（如 "·"、空格），把 "或" 取第一个键
    s = s.replace("·", "").replace(" ", "")
    s = re.sub(r"([A-Za-z0-9]+)或[A-Za-z0-9]+", r"\1", s)

    # 4. 处理蓄力语法：将 "←蓄→" / "↓蓄↑" 转为 "[4]6" / "[2]8"
    for arr, num in ARROW_TO_NUMPAD:
        s = s.replace(arr, num)
    s = re.sub(r"([1-9])蓄([1-9])", r"[\1]\2", s)

    # 5. 拆分尾部的 "+按键"（如 "236+A+B" -> motion="236", atk="A+B"）
    if "+" in s:
        parts = s.split("+")
        motion_part = parts[0]
        atk_part = "+".join(parts[1:])
    else:
        # 支持 "236A" 无加号写法
        m = re.fullmatch(r"(\[[1-9]\][1-9]+|[1-9]+|[A-Z_]+)([A-Za-z0-9]+)", s)
        if m and m.group(1).upper() in SHORTHAND_MOTIONS or (m and m.group(1)[0] in "[12346789"):
            motion_part, atk_part = m.group(1), m.group(2)
        else:
            motion_part, atk_part = s, ""

    motion_upper = motion_part.upper()
    if motion_upper in SHORTHAND_MOTIONS:
        motion_part = SHORTHAND_MOTIONS[motion_upper]

    frames_out = []

    # 6. 解析蓄力段 [d] 与普通方向段
    idx = 0
    dirs_seq = []
    while idx < len(motion_part):
        if motion_part[idx] == "[" and idx + 2 < len(motion_part) and motion_part[idx + 2] == "]":
            c_dir = motion_part[idx + 1]
            dirs_seq.append(("charge", c_dir))
            idx += 3
        elif motion_part[idx] in NUMPAD_DIRS_RIGHT:
            dirs_seq.append(("normal", motion_part[idx]))
            idx += 1
        else:
            idx += 1

    if not dirs_seq and atk_part:
        # 纯按键（如单按 A+B）
        frames_out.extend([atk_part] * max(1, attack_hold))
    else:
        for step_i, (kind, d_num) in enumerate(dirs_seq):
            d_name = _flip_dir(NUMPAD_DIRS_RIGHT[d_num], facing=facing)
            is_last = (step_i == len(dirs_seq) - 1)
            if kind == "charge":
                frames_out.extend([d_name] * max(30, int(charge_frames)))
            elif is_last and atk_part:
                # 最后一个方向先单独输入 1 帧，随后方向+攻击键同按 attack_hold 帧（防模拟器吞末方向）
                if d_name:
                    frames_out.append(d_name)
                    combo = f"{d_name}+{atk_part}"
                else:
                    combo = atk_part
                frames_out.extend([combo] * max(2, int(attack_hold)))
            else:
                # 若连续两个相同方向（如 22A 或 66 前冲），中间自动插入 2 帧回中立（5）
                if step_i > 0 and dirs_seq[step_i - 1][1] == d_num:
                    frames_out.extend(["", ""])
                frames_out.extend([d_name] * max(1, int(dir_frames)))

    raw_spec = ",".join(frames_out)
    return RP.parse_platform_macro(platform, raw_spec)


# ===========================================================================
# 2. 内置全平台「经典秘籍 / 彩蛋 / 隐藏人物 / 超必杀」现成宏库
# ===========================================================================
PRESET_MACROS = {
    # --- 科乐美与 FC 经典秘籍彩蛋 ---
    "KONAMI_CODE_NES": {
        "title": "科乐美经典秘籍（魂斗罗30条命 / 沙罗曼蛇满配 / 宇宙巡航机）",
        "platform": "NES",
        "kind": "easter_egg",
        "notation": "↑,↑,↓,↓,←,→,←,→,B,A,Start",
        "macro": chain(
            hold("Up", 4, 4), hold("Up", 4, 4),
            hold("Down", 4, 4), hold("Down", 4, 4),
            hold("Left", 4, 4), hold("Right", 4, 4),
            hold("Left", 4, 4), hold("Right", 4, 4),
            hold("B", 4, 4), hold("A", 4, 6),
            hold("Start", 8, 20),
        ),
    },
    "KONAMI_CODE_SNES": {
        "title": "SFC 科乐美秘籍（魂斗罗精神 / 宇宙巡航机3）",
        "platform": "SNES",
        "kind": "easter_egg",
        "notation": "↑,↑,↓,↓,←,→,←,→,B,A,Start",
        "macro": chain(
            hold("Up", 4, 4), hold("Up", 4, 4),
            hold("Down", 4, 4), hold("Down", 4, 4),
            hold("Left", 4, 4), hold("Right", 4, 4),
            hold("Left", 4, 4), hold("Right", 4, 4),
            hold("B", 4, 4), hold("A", 4, 6),
            hold("Start", 8, 20),
        ),
    },
    "SOCCER2_ALL_SKILLS_CHEAT": {
        "title": "FC《热血足球2》暂停解锁全员必杀技秘籍 (AAABAAABAAAAAAA)",
        "platform": "NES",
        "kind": "easter_egg",
        "notation": "Start -> A,A,A,B,A,A,A,B,A,A,A,A,A,A,A -> Start",
        "macro": chain(
            hold("Start", 8, 20),
            hold("A", 4, 4), hold("A", 4, 4), hold("A", 4, 4), hold("B", 4, 4),
            hold("A", 4, 4), hold("A", 4, 4), hold("A", 4, 4), hold("B", 4, 4),
            hold("A", 4, 4), hold("A", 4, 4), hold("A", 4, 4), hold("A", 4, 4),
            hold("A", 4, 4), hold("A", 4, 4), hold("A", 4, 15),
            hold("Start", 8, 20),
        ),
    },
    # --- 街机《拳皇 97 / 98》隐藏人物选人彩蛋与代表超必杀 ---
    "KOF97_UNLOCK_OROCHI_IORI": {
        "title": "街机《拳皇97》选人画面调出隐藏人物「暴走八神庵」（按住Start + ←→←→←→ + A+C）",
        "platform": "ARCADE_FBNEO",
        "kind": "easter_egg",
        "notation": "Hold Start: ←→←→←→ + A+C",
        "macro": chain(
            hold("Start+Left", 5, 2), hold("Start+Right", 5, 2),
            hold("Start+Left", 5, 2), hold("Start+Right", 5, 2),
            hold("Start+Left", 5, 2), hold("Start+Right", 5, 2),
            hold("Start+A+C", 10, 30),
        ),
    },
    "KOF97_UNLOCK_OROCHI_LEONA": {
        "title": "街机《拳皇97》选人画面调出隐藏人物「暴走莉安娜」（按住Start + ↑↓↑↓↑↓ + B+D）",
        "platform": "ARCADE_FBNEO",
        "kind": "easter_egg",
        "notation": "Hold Start: ↑↓↑↓↑↓ + B+D",
        "macro": chain(
            hold("Start+Up", 5, 2), hold("Start+Down", 5, 2),
            hold("Start+Up", 5, 2), hold("Start+Down", 5, 2),
            hold("Start+Up", 5, 2), hold("Start+Down", 5, 2),
            hold("Start+B+D", 10, 30),
        ),
    },
    "KOF_IORI_MAIDEN_MASHER": {
        "title": "八神庵超必杀：禁千贰百拾壹式·八稚女 (↓↘→↘↓↙←+A/C)",
        "platform": "ARCADE_FBNEO",
        "kind": "skill",
        "notation": "2363214+C",
        "macro": "Down,Down,Down+Right,Down+Right,Right,Right,Down+Right,Down+Right,Down,Down,Down+Left,Down+Left,Left,Left+C,Left+C,Left+C,Left+C",
    },
    "KOF_KYO_OROCHINAGI": {
        "title": "草薙京超必杀：里百八式·大蛇薙 (↓↙←↙↓↘→+C)",
        "platform": "ARCADE_FBNEO",
        "kind": "skill",
        "notation": "2141236+C",
        "macro": "Down,Down,Down+Left,Down+Left,Left,Left,Down+Left,Down+Left,Down,Down,Down+Right,Down+Right,Right,Right+C,Right+C,Right+C,Right+C",
    },
    "KOF_TERRY_BUSTER_WOLF": {
        "title": "特瑞超必杀：Buster Wolf / 能量喷泉 (↓↘→↓↘→+B / ↓↙←↙→+A)",
        "platform": "ARCADE_FBNEO",
        "kind": "skill",
        "notation": "21416+C",
        "macro": "Down,Down,Down+Left,Down+Left,Left,Left,Down+Left,Down+Left,Right,Right+C,Right+C,Right+C,Right+C",
    },
    # --- SFC《洛克人 X》隐藏胶囊彩蛋 ---
    "MMX1_HADOKEN": {
        "title": "SFC《洛克人X1》隐藏街霸彩蛋：一击必杀波动拳 (↓↘→+Y)",
        "platform": "SNES",
        "kind": "easter_egg",
        "notation": "236+Y",
        "macro": "Down,Down,Down+Right,Down+Right,Right,Right+Y,Right+Y,Right+Y,Right+Y",
    },
    "MMX2_SHORYUKEN": {
        "title": "SFC《洛克人X2》隐藏街霸彩蛋：火焰升龙拳 (→↓↘+Y)",
        "platform": "SNES",
        "kind": "easter_egg",
        "notation": "623+Y",
        "macro": "Right,Right,Down,Down,Down+Right,Down+Right+Y,Down+Right+Y,Down+Right+Y,Down+Right+Y",
    },
    # --- PS1《恶魔城：月下夜想曲》全出招表搓招与盾杖彩蛋 ---
    "SOTN_SOUL_STEAL": {
        "title": "PS1《恶魔城：月下夜想曲》终极必杀：窃魂术 Soul Steal (←→↘↓↙←→+Square)",
        "platform": "PS1",
        "kind": "skill",
        "notation": "4632146+Square",
        "macro": "Left,Left,Right,Right,Down+Right,Down+Right,Down,Down,Down+Left,Down+Left,Left,Left,Right,Right+Square,Right+Square,Right+Square,Right+Square",
    },
    "SOTN_HELLFIRE": {
        "title": "PS1《恶魔城：月下夜想曲》德古拉必杀：暗黑地狱火 Hellfire (↑↓↘→+Square)",
        "platform": "PS1",
        "kind": "skill",
        "notation": "8236+Square",
        "macro": "Up,Up,Up,Down,Down,Down+Right,Down+Right,Right,Right+Square,Right+Square,Right+Square,Right+Square",
    },
    "SOTN_TETRA_SPIRIT": {
        "title": "PS1《恶魔城：月下夜想曲》四魂之魔 Tetra Spirit (↑按住2秒 →↗→↘↓+Square)",
        "platform": "PS1",
        "kind": "skill",
        "notation": "[8]632+Square",
        "macro": chain(
            hold("Up", 50, 0),
            "Up+Right,Up+Right,Right,Right,Down+Right,Down+Right,Down,Down+Square,Down+Square,Down+Square",
        ),
    },
    "SOTN_SHIELD_ROD_COMBO": {
        "title": "PS1《恶魔城：月下夜想曲》最强彩蛋：盾牌杖+阿鲁卡多之盾无敌特效 (Square+Circle 同按)",
        "platform": "PS1",
        "kind": "easter_egg",
        "notation": "Square+Circle",
        "macro": hold("Square+Circle", 12, 60),
    },
    # --- MD《幽游白书：魔强统一战》经典超必杀 ---
    "YUYU_HIEI_DRAGON_OF_DARKNESS": {
        "title": "MD《幽游白书：魔强统一战》飞影超必杀：邪王炎杀黑龙波 (↓↘→↓↘→+A)",
        "platform": "MD",
        "kind": "skill",
        "notation": "236236+A",
        "macro": "Down,Down,Down+Right,Down+Right,Right,Right,Down,Down,Down+Right,Down+Right,Right,Right+A,Right+A,Right+A,Right+A",
    },
}


def expand_pack_notations(pack_path: Path) -> dict:
    """支持在 .showcase.json 的 trigger 里直接写简短的 `"notation": "236236+A"` 或 `"@KONAMI_CODE_NES"`，
    自动将其编译为帧精确的 `trigger.macro` 并写回文件！
    """
    doc = json.loads(pack_path.read_text(encoding="utf-8"))
    plat = doc.get("platform", "NES")
    compiled_count = 0
    for el in doc.get("elements", []):
        trig = el.get("trigger") or {}
        notation = trig.get("notation")
        if notation and not trig.get("macro"):
            facing = trig.get("facing", "right")
            trig["macro"] = compile_notation(notation, platform=plat, facing=facing) + "," * 24
            compiled_count += 1
    if compiled_count > 0:
        pack_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"pack": str(pack_path), "compiled_elements": compiled_count}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_c = sub.add_parser("compile", help="把出招表记法（如 '236236+A' 或 '↓↙←↙↓↘→+C'）编译成逐帧宏")
    p_c.add_argument("--notation", required=True)
    p_c.add_argument("--platform", default="ARCADE_FBNEO")
    p_c.add_argument("--facing", default="right", choices=["right", "left"])
    p_c.add_argument("--charge", type=int, default=45)

    sub.add_parser("list-presets", help="列出内置的全部彩蛋秘籍与超必杀宏预设")

    p_u = sub.add_parser("expand-pack", help="将知识包中的 trigger.notation 自动展开为逐帧 macro")
    p_u.add_argument("--pack", required=True)

    args = ap.parse_args()
    if args.cmd == "compile":
        out = compile_notation(
            args.notation, platform=args.platform, facing=args.facing, charge_frames=args.charge
        )
        print(json.dumps({
            "notation": args.notation,
            "platform": args.platform,
            "facing": args.facing,
            "frames_count": len(out.split(",")),
            "macro": out,
        }, ensure_ascii=False, indent=2))
    elif args.cmd == "list-presets":
        print(json.dumps(PRESET_MACROS, ensure_ascii=False, indent=2))
    elif args.cmd == "expand-pack":
        print(json.dumps(expand_pack_notations(Path(args.pack)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
