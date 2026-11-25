"""API key 池 + 模型路由（平台 → 账号 → 密钥 三层）。

密钥明文只存 Windows 凭据管理器（CRED_TYPE_GENERIC / LOCAL_MACHINE）。
配置文件 apikey池.json、台账 _apikey池台账.json、以及本脚本的打印输出里
都不出现密钥值，只有凭据名和掩码。

路由口径（本会话实测 + 参考 VideoLingo 那套 provider 配置得出，改之前先看 --selftest）：
  1. 默认只用已登记为免费的模型。价格 >0、实测 429 零用量、paid key、未知价格都算收费。
  2. 收费一律垫到链尾，且默认不进链；要 --allow-paid（或配置 allow_paid_by_default）才追加。
     点名型号不绕过收费开关；无完整预算/额度配置时，收费候选在执行前全部拦死。
  3. 型号从最新往旧用（Gemini 按版本号；国产 OpenAI 兼容口按 provider 的 prefer 顺序 = 质量偏好）。
     同一型号的额度真用完，才降到下一个型号 —— 同型号先横着换 key。
  4. 零用量即 429 ⇒ 判「上限 0」而不是「撞了限」（本会话 --recheck 实测证明过）。
  5. 429 分钟级 / 503 拥塞 ⇒ 冷却后重试，不当成额度用完。冷却时长照搬 VideoLingo：
     rate_limit 8 分钟、付费余额不足 24 小时、免费日额度耗尽等厂商自己的重置点。
  6. 任务路由：文案默认交 Gemini（tasks 表可改可加），批量打标只走 flash-lite 家族。
  7. 付费调用按“每轮/每日金额、token、请求”硬上限预检；成功后将真实 usage 和成本回填台账。

用法：
  python apikey池.py --init
  python apikey池.py --add --platform gemini-aistudio --account 邮箱 --label key-A
  python apikey池.py --add --platform deepseek --account 主号 --label key-B --tier paid
  python apikey池.py --rm   --platform deepseek --account 主号 --label key-B
  # 没有终端可输入时（管道喂不进 getpass）：把值放环境变量，再 --key-env 变量名
  python apikey池.py --show [--platform X]
  python apikey池.py --refresh [--platform X]
  python apikey池.py --ask "写条封面文案" --task 文案 [--dry-run] [--allow-paid]
                     [--model gemini-4-hydrogen] [--platform X] [--thinking 0]
  python apikey池.py --new-task 改写 --platform gemini-aistudio --families flash
  python apikey池.py --selftest
"""

import argparse
import contextlib
import ctypes
import ctypes.wintypes as wt
import getpass
import io
import json
import math
import msvcrt
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

try:  # 让中文在 UTF-8 终端和重定向文件里都不翻车
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "apikey池.json")
LEDGER_PATH = os.path.join(HERE, "_apikey池台账.json")
CRED_PREFIX = "QoderAPIKey"


# ---------------------------------------------------------------- 凭据管理器
_advapi = ctypes.windll.advapi32
_kernel32 = ctypes.windll.kernel32
_kernel32.GetLastError.restype = wt.DWORD
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class _CREDENTIALW(ctypes.Structure):
    """wincred.h 的 WINCREDENTAILW，字段顺序与个数必须逐字对上（x64 有隐式补齐）。

    实测本机（19045）CredWriteW 要 Flags 在前、Type 在后：按 Type 在前写会得 GLE=87，
    而读 cmdkey 写的 GENERIC 凭据时这两个 DWORD 也会读出互换 —— 自检 #13 就是这道闸门。
    """
    _fields_ = [
        ("Flags", wt.DWORD),
        ("Type", wt.DWORD),
        ("TargetName", wt.LPWSTR),
        ("Comment", wt.LPWSTR),
        ("LastWritten", wt.FILETIME),
        ("CredentialBlobSize", wt.DWORD),
        ("CredentialBlob", ctypes.c_void_p),
        ("Persist", wt.DWORD),
        ("AttributeCount", wt.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wt.LPWSTR),
        ("UserName", wt.LPWSTR),
    ]


PCRED = ctypes.POINTER(_CREDENTIALW)
_advapi.CredWriteW.argtypes = [PCRED, wt.DWORD]
_advapi.CredWriteW.restype = wt.BOOL
_advapi.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(PCRED)]
_advapi.CredReadW.restype = wt.BOOL
_advapi.CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
_advapi.CredDeleteW.restype = wt.BOOL
_advapi.CredFree.argtypes = [ctypes.c_void_p]


def cred_target(platform: str, account: str, label: str) -> str:
    return f"{CRED_PREFIX}/{platform}/{account}/{label}"


def cred_write(target: str, secret: str, comment: str = "") -> None:
    blob = secret.encode("utf-16-le")  # 局部变量活到调用返回，指针不会悬空
    c = _CREDENTIALW()
    c.Type = CRED_TYPE_GENERIC
    c.Persist = CRED_PERSIST_LOCAL_MACHINE
    c.TargetName = target
    c.Comment = comment or ""
    c.UserName = target.rsplit("/", 1)[-1]
    c.CredentialBlobSize = len(blob)
    c.CredentialBlob = ctypes.cast(ctypes.c_char_p(blob), ctypes.c_void_p)
    if not _advapi.CredWriteW(ctypes.byref(c), 0):
        raise OSError(f"CredWriteW 失败 GLE={_kernel32.GetLastError()}（blob={len(blob)} 字节）")


def cred_read(target: str):
    p = PCRED()
    if not _advapi.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
        gle = _kernel32.GetLastError()
        if gle == ERROR_NOT_FOUND:
            return None
        raise OSError(f"CredReadW 失败 GLE={gle}")
    try:
        c = p.contents
        raw = ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize)
        return raw.decode("utf-16-le")
    finally:
        _advapi.CredFree(p)


def cred_delete(target: str) -> bool:
    return bool(_advapi.CredDeleteW(target, CRED_TYPE_GENERIC, 0))


def mask(secret: str) -> str:
    if not secret:
        return "(凭据缺失)"
    return f"已配置（{len(secret)} 字符）"


# ---------------------------------------------------------------- 配额日界
def _nth_weekday(year, month, weekday, n):
    d = datetime(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _us_dst(dt_utc) -> bool:
    """美国夏令时：3 月第二个周日 ~ 11 月第一个周日（按 UTC 粗算，边界差 1 小时无碍）。"""
    year = dt_utc.year
    naive = dt_utc.replace(tzinfo=None)
    return _nth_weekday(year, 3, 6, 2) <= naive < _nth_weekday(year, 11, 6, 1)


def _pacific_now(now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    return now_utc - timedelta(hours=7 if _us_dst(now_utc) else 8)


def quota_day(now_utc=None) -> str:
    """台账唯一的「配额日」标签：按太平洋时间（Gemini 的 RPD 重置点，本会话实测口径）。

    国产口的重置点（多为北京 00:10）不进日界，改用 until 时间戳表达，见 seconds_to_reset。
    """
    return _pacific_now(now_utc).strftime("%Y-%m-%d")


def seconds_to_reset(pnode, now_utc=None) -> float:
    """该平台的日额度还有多久重置（多留 3 分钟余量，卡在整点打过去照样 429）。"""
    if pnode.get("kind") != "gemini":
        r = pnode.get("quota_reset") or {"tz": 8, "hour": 0, "minute": 10}
        local = (now_utc or datetime.now(timezone.utc)) + timedelta(hours=r.get("tz", 8))
        target = local.replace(hour=r.get("hour", 0), minute=r.get("minute", 0),
                               second=0, microsecond=0)
        if target <= local:
            target += timedelta(days=1)
        return (target - local).total_seconds() + 180
    loc = _pacific_now(now_utc)
    target = (loc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (target - loc).total_seconds() + 180


# ---------------------------------------------------------------- 配置
def _gemini_plat(name, base, priority, note, extra=None):
    p = {"kind": "gemini", "name": name, "base": base, "priority": priority,
         "proxy": "env", "note": note, "quota_reset": None,
         "prices": [], "free_models": [], "block_patterns": [], "prefer": [], "catalog": [], "accounts": {}}
    p.update(extra or {})
    return p


def _openai_plat(name, base, priority, note, prefer=None, include=None, prices=None,
                 probe=False):
    return {"kind": "openai", "name": name, "base": base, "priority": priority,
            "proxy": "direct", "note": note, "quota_reset": {"tz": 8, "hour": 0, "minute": 10},
            "probe_models": probe, "model_include": include or "", "prefer": prefer or [],
            "prices": prices or [], "block_patterns": [], "catalog": [], "accounts": {}}


DEFAULT_CONFIG = {
    "platforms": {
        "gemini-aistudio": _gemini_plat(
            "Google AI Studio", "https://generativelanguage.googleapis.com/v1beta", 0,
            "免费层按太平洋时间午夜重置；实测 quotaValue 不返回，上限只能撞出来",
            extra={"free_models": ["gemini-3.1-flash-lite", "gemini-flash-lite-latest"]}),
        "qwenplan": _openai_plat(
            "Qwen Coding Plan 订阅网关", "https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1", 1,
            "订阅制配额（非按量计费），价格按近似零价登记；key 只在开会员的机器上有效",
            prefer=["qwen3.7-max", "qwen3.7-plus", "deepseek-v4.1-flash"],
            include=r"^qwen3|^glm-|^deepseek", probe=True,
            prices=[{"providers": ["self"], "pattern": ".", "input": 0.01, "output": 0.04,
                     "note": "订阅配额按近似零价参与排序（照 VideoLingo 表）"}]),
        "modelscope": _openai_plat(
            "魔搭 ModelScope（免费）", "https://api-inference.modelscope.cn/v1", 2,
            "每天 2000 次免费（单模型 500），全部 0 元",
            prefer=["Qwen/Qwen3.5-397B-A17B", "Qwen/Qwen3.5-122B-A10B", "Qwen/Qwen3.5-35B-A3B",
                    "MiniMax/MiniMax-M2.7", "ZhipuAI/GLM-4.7-Flash"],
            include=r"^Qwen/Qwen3\.5|^MiniMax/MiniMax-M[23]|^ZhipuAI/GLM-4\.7", probe=True,
            prices=[{"providers": ["self"], "pattern": ".", "input": 0.0, "output": 0.0,
                     "note": "魔搭全部模型免费"}]),
        "zhipu": _openai_plat(
            "智谱 BigModel", "https://open.bigmodel.cn/api/paas/v4", 3,
            "无 /models 接口，只能静态表",
            prefer=["glm-4.7-flash", "glm-5.3-flash", "glm-5.3"], probe=False,
            prices=[{"providers": ["self"], "pattern": r"^glm-4\.7-flash", "input": 0.0, "output": 0.0,
                     "note": "永久免费模型（并发 1）"},
                    {"providers": ["self"], "pattern": r"^glm-5\.3-flash", "input": 1.08, "output": 3.6},
                    {"providers": ["self"], "pattern": r"^glm-5\.3", "input": 8.0, "output": 28.0}]),
        "siliconflow": _openai_plat(
            "硅基流动 SiliconFlow", "https://api.siliconflow.cn/v1", 4,
            "新用户送 14 元；5 个模型共用 1 个账户，402 会连锁",
            prefer=["Qwen/Qwen3.5-35B-A3B", "Qwen/Qwen3.5-122B-A10B",
                    "deepseek-ai/DeepSeek-V4-Flash", "MiniMaxAI/MiniMax-M2.5"], probe=True,
            prices=[{"providers": ["self"], "pattern": "qwen3\\.5-35b-a3b", "input": 0.4, "output": 3.2},
                    {"providers": ["self"], "pattern": "qwen3\\.5-122b-a10b", "input": 1.26, "output": 1.26},
                    {"providers": ["self"], "pattern": "deepseek-v4-flash", "input": 0.4, "output": 1.6},
                    {"providers": ["self"], "pattern": "minimax-m2\\.5", "input": 2.0, "output": 8.0},
                    {"providers": ["self"], "pattern": ".", "input": 0.0, "output": 0.0,
                     "note": "送的金未耗尽前按免费登记"}]),
        "deepseek": _openai_plat(
            "DeepSeek 官方", "https://api.deepseek.com/v1", 5,
            "峰谷计价，登记的是闲时价（周末全天 + 工作日夜间）",
            prefer=["deepseek-flash", "deepseek-v4-pro"], probe=True,
            prices=[{"providers": ["self"], "pattern": "^deepseek-flash", "input": 1.0, "output": 4.0,
                     "note": "V4.1-Flash 闲时价，高峰 2/8"},
                    {"providers": ["self"], "pattern": "^deepseek-v4-pro", "input": 4.5, "output": 13.5,
                     "note": "闲时价，高峰 9/27"}]),
        "moonshot": _openai_plat(
            "月之暗面 Kimi", "https://api.moonshot.cn/v1", 6,
            "按量计费，无免费额度时整平台进收费链尾",
            prefer=["kimi-k2.6", "kimi-k2.5"], probe=True,
            prices=[{"providers": ["self"], "pattern": ".", "input": 4.0, "output": 16.0}]),
        "openrouter": _openai_plat(
            "OpenRouter（需代理）", "https://openrouter.ai/api/v1", 7,
            "第三方托管杂牌多 + 依赖代理，整体垫后做兜底；:free 模型每天仅 50-1000 次",
            include=r"^google/gemini|^deepseek/deepseek", probe=True),
    },
    "policy": {
        "_说明": ["价格单位 元/百万 tokens；综合价 = 输入×input_weight + 输出×output_weight",
                  "综合价 > max_blended_price 的型号 --refresh 时直接不收（照 VideoLingo model_prices.json）",
                  "收费判定有两个来源：价格表 >0，或实测「零用量即 429」；后者只在台账里，清台账即重判",
                  "免费额度耗尽 → 冷却到该平台自己的重置点；402 余额不足 → 冷却 24 小时等充值",
                  "退避用光仍拥塞 / 读超时 → 也挂起（8 分钟 / 120 秒），否则每次调用都白等同一格",
                  "付费预算/额度默认全为 0：必须同时配好每轮与每日金额、token、请求上限才允许付费；点名型号不绕过",
                  "未知价格按收费处理；没有输入/输出单价时拒绝付费调用，不把未知价当 0 元"],
        "newest_first": True,
        "allow_paid_by_default": False,
        "max_attempts_per_slot": 3,
        "backoff_base_s": 5,
        "input_weight": 2.0,
        "output_weight": 1.0,
        "min_context_tokens": 8192,
        "max_blended_price": 12,
        "run_budget_cny": 0.0,
        "daily_budget_cny": 0.0,
        "run_token_limit": 0,
        "daily_token_limit": 0,
        "run_request_limit": 0,
        "daily_request_limit": 0,
        "default_max_output_tokens": 2048,
        "cooldown_minutes_rate_limit": 8,
        "cooldown_hours_quota_paid": 24,
        "cooldown_seconds_transport": 120,
        "disabled_models": [],
        # 照 VideoLingo 的 block_patterns：非纯文本 / 小模型 / 思考特化 一律不进池
        "block_patterns": [
            r"embed|rerank|whisper|guard|moderation|sora|veo|kling|flux|video",
            r"vl-|-vl$|vision|internvl|robotics",
            r"antigravity",
            r":free$",
            r"(^|[^0-9a-z])(0\.5b|1b|1\.5b|2b|3b|4b|6b|7b|8b|9b)([^0-9a-z]|$)",
            r"thinking|reasoner|coder|-pt$|-base$",
        ],
        "_block说明": ["排除嵌入/重排/语音/生图/生视频等非纯文本型号",
                       "排除视觉（vl / vision）与 robotics 这类专用型号",
                       "排除 antigravity：实测 generateContent 一律 400「This model only supports Interactions API」",
                       "排除 OpenRouter :free 后缀（每天仅 50-1000 次，做主力会被打断；要放开删这行）",
                       "排除 <10B 小模型，防质量跳水（想用免费小模型删这行）",
                       "排除 thinking/reasoner（输出慢且带过程）、coder（代码特化）、-pt$/-base$（不能对话）"],
    },
    "tasks": {
        "文案": {"platforms": ["gemini-aistudio"], "families": ["any"], "note": "文案任务交给 Gemini"},
        "批量打标": {"platforms": ["gemini-aistudio"], "families": ["flash-lite"]},
        "翻译": {"platforms": ["modelscope", "zhipu", "gemini-aistudio"], "families": ["any"],
                 "note": "国产免费口优先，Gemini 兜底"},
    },
}


def load_bare(path):
    """台账用：读到什么就是什么，绝不掺模板（掺了会往台账里写进 policy 键）。"""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_config(path):
    """配置用：缺文件给全套模板；老配置只补缺字段，不改用户已有取值。"""
    if not os.path.exists(path):
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for plat, pnode in data.get("platforms", {}).items():
        for k, v in DEFAULT_CONFIG["platforms"].get(plat, {}).items():
            pnode.setdefault(k, json.loads(json.dumps(v)))
    for k, v in DEFAULT_CONFIG["policy"].items():
        data.setdefault("policy", {}).setdefault(k, v)  # 只补缺，别盖掉用户改过的阈值
    for t, v in DEFAULT_CONFIG["tasks"].items():
        data.setdefault("tasks", {}).setdefault(t, json.loads(json.dumps(v)))
    return data


SENSITIVE_FIELD_NAMES = {
    "key", "apikey", "token", "accesstoken", "refreshtoken", "secret",
    "password", "authorization", "credential", "credentials", "privatekey",
    "clientsecret",
}
CREDENTIAL_VALUE_RE = re.compile(
    r"(?:AIza[0-9A-Za-z_-]{10,}|AQ\.[0-9A-Za-z_-]{8,}|sk-[0-9A-Za-z_-]{8,}|"
    r"Bearer\s+[0-9A-Za-z._~+/-]{12,})"
)


def sensitive_finding(data, path="$"):
    if isinstance(data, dict):
        for key, value in data.items():
            here = f"{path}.{key}"
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if normalized in SENSITIVE_FIELD_NAMES:
                return here
            if isinstance(value, str) and CREDENTIAL_VALUE_RE.search(value):
                return here
            found = sensitive_finding(value, here)
            if found:
                return found
    elif isinstance(data, list):
        for i, value in enumerate(data):
            found = sensitive_finding(value, f"{path}[{i}]")
            if found:
                return found
    return None


def save(path, data):
    finding = sensitive_finding(data)
    if finding:
        raise ValueError(f"拒绝写入敏感字段：{finding}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)  # 原子写，中途崩不会留下半个文件


# ---------------------------------------------------------------- 型号属性
def family_of(model: str) -> str:
    """档位/模态归类（厂商名不算家族：qwen/glm/deepseek 一律 chat）。"""
    m = model.lower()
    if "image" in m or "nano-banana" in m:
        return "image"
    if "tts" in m:
        return "tts"
    if "transcribe" in m or "asr" in m:
        return "asr"
    if "omni" in m:
        return "video"
    if "lyria" in m or "music" in m:
        return "music"
    if "flash-lite" in m or "flash_lite" in m:
        return "flash-lite"
    if "pro" in m:
        return "pro"
    if "flash" in m:
        return "flash"
    if "gemma" in m:
        return "gemma"
    return "chat"


def version_key(model: str):
    """越大越新（Gemini 口径）。

    只认 gemini-N / gemma-N 前缀的版本号：antigravity-preview-09-2026、
    deep-research-pro-preview-12-2025 这种日期后缀会被读成 9 / 12 而冒充最新版，
    实测它们又不是普通生成口，必须排在真型号后面。别名（*-latest）指向最新，排最前。
    """
    m = model.lower()
    stable = 0 if "preview" in m else 1
    if m.endswith("-latest"):
        return (999, 999, stable, 1)
    fam = re.match(r"(?:gemini|gemma)-(\d+)(?:\.(\d+))?", m)
    if not fam:
        return (0, 0, stable, 0)
    return (int(fam.group(1)), int(fam.group(2) or 0), stable, 0)


def _num_ver(model: str):
    """国产型号的版本序：取 id 里第一个版本号（397B/A17B 这类参数量后缀不参与）。"""
    nums = re.findall(r"\d+(?:\.\d+)?", model) or ["0"]
    parts = nums[0].split(".")
    return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0,
            0 if "preview" in model.lower() else 1)


def model_sort(pnode):
    return version_key if pnode.get("kind") == "gemini" else _num_ver


def is_blocked(patterns, model: str) -> bool:
    return any(re.search(p, model, re.IGNORECASE) for p in patterns or [])


def price_hit(prices, model: str):
    """命中第一条 pattern（顺序即优先级），用于「具体规则在前、兜底在后」。"""
    for row in prices or []:
        try:
            if re.search(row.get("pattern", "."), model, re.IGNORECASE):
                return row
        except re.error:
            continue
    return None


def model_price(pnode, model: str):
    row = price_hit(pnode.get("prices"), model)
    if not row:
        return None
    try:
        input_price = float(row.get("input"))
        output_price = float(row.get("output"))
    except (TypeError, ValueError):
        return None
    if min(input_price, output_price) < 0 or not all(
            math.isfinite(v) for v in (input_price, output_price)):
        return None
    return input_price, output_price


def blended(pnode, model: str, policy=None) -> float:
    """综合价 = 输入价×2 + 输出价×1（元/百万 tokens），只用于排序。"""
    pol = policy or DEFAULT_CONFIG["policy"]
    price = model_price(pnode, model)
    if price is None:
        return 0.0
    return round(price[0] * float(pol.get("input_weight", 2.0))
                 + price[1] * float(pol.get("output_weight", 1.0)), 4)


# ---------------------------------------------------------------- 台账状态
STATE_OK = "ok"
STATE_EXHAUSTED = "exhausted"   # 日额度真用完，下个配额日自动回来
STATE_NO_FREE = "no_free"       # 免费层上限 0（实测判据），属收费型号
STATE_GONE = "unavailable"      # 404，对新用户已关
STATE_THROTTLED = "throttled"   # 分钟级限流 / 503 拥塞，冷却到 until 自动回来
STATE_NO_CREDIT = "no_credit"   # 402 账户没余额，冷却到 until（默认 24h 等充值）

TRANSIENT_STATES = (STATE_THROTTLED, STATE_NO_CREDIT, STATE_EXHAUSTED)


def slot(platform, account, label):
    return f"{platform}|{account}|{label}"


def new_day():
    return {"usage": {}, "state": {}, "note": {}, "until": {}}


def ledger_get(led, day):
    return led.setdefault(day, new_day())


def used_today(led, day, key, model) -> int:
    """该 key 在该型号上今天成功过几次（也是「零用量即 429」的判据来源）。"""
    return ledger_get(led, day)["usage"].get(f"{key}::{model}", {}).get("req", 0)


def note_attempt(led, day, key, model):
    rec = ledger_get(led, day)["usage"].setdefault(
        f"{key}::{model}", {"req": 0, "attempts": 0, "pending": 0,
                            "in": 0, "out": 0, "thought": 0,
                            "cost_cny": 0.0})
    rec["attempts"] = rec.get("attempts", 0) + 1
    rec["pending"] = rec.get("pending", 0) + 1
    return rec


def settle_attempt(rec):
    rec["pending"] = max(0, rec.get("pending", 0) - 1)


def bump(led, day, key, model):
    rec = ledger_get(led, day)["usage"].setdefault(
        f"{key}::{model}", {"req": 0, "attempts": 0, "pending": 0,
                            "in": 0, "out": 0, "thought": 0,
                            "cost_cny": 0.0})
    rec["req"] += 1
    return rec


def daily_totals(led, day):
    totals = {"requests": 0, "tokens": 0, "cost_cny": 0.0,
              "pending": 0, "unknown_cost": False}
    for rec in ledger_get(led, day)["usage"].values():
        attempts = rec.get("attempts", rec.get("req", 0))
        totals["requests"] += attempts
        totals["pending"] += rec.get("pending", 0)
        totals["tokens"] += rec.get("in", 0) + rec.get("out", 0) + rec.get("thought", 0)
        totals["cost_cny"] += rec.get("cost_cny", 0.0)
        if rec.get("pending", 0) or (attempts and "cost_cny" not in rec):
            totals["unknown_cost"] = True
    return totals


class LedgerBusy(RuntimeError):
    pass


@contextlib.contextmanager
def ledger_lock(path):
    lock_path = path + ".lock"
    handle = open(lock_path, "a+b")
    try:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise LedgerBusy("另一个 API 请求进程正在持有台账锁；为避免预算并发绕过，本次不启动") from exc
        try:
            yield
        finally:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
    finally:
        handle.close()


def set_state(led, day, key, model, state, note="", until=None):
    rec = ledger_get(led, day)
    skey = f"{key}::{model}"
    rec["state"][skey] = state
    if note:
        rec["note"][skey] = note[:300]
    if until:
        rec["until"][skey] = round(until, 1)
    else:
        rec["until"].pop(skey, None)


def get_state(led, key, model, now=None):
    """当前配额日内的状态。

    带 until 的（throttled / no_credit / 国产 exhausted）以 until 为准，没到点继续拦；
    不带 until 的随配额日自动失效；NO_FREE 是长期结论，跨日继承。
    """
    day = quota_day()
    rec = ledger_get(led, day)
    skey = f"{key}::{model}"
    st = rec["state"].get(skey)
    until = rec.get("until", {}).get(skey)
    if st in TRANSIENT_STATES and until is not None and (now or time.time()) >= until:
        st = None
    if st is None or (st in TRANSIENT_STATES and until is None):
        for d in sorted((x for x in led if x != day and "state" in led[x]), reverse=True):
            if led[d]["state"].get(skey) == STATE_NO_FREE:
                return STATE_NO_FREE
    return st


# ---------------------------------------------------------------- HTTP
def opener(proxy_mode):
    """国产口按参考项目口径直连；境外口走环境代理。"""
    if proxy_mode == "direct":
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def http_json(url, secret, body=None, timeout=90, proxy_mode="env", auth_header=None):
    headers = {"content-type": "application/json"}
    headers[auth_header or ("x-goog-api-key" if "/v1beta" in url else "Authorization")] = (
        secret if auth_header or "/v1beta" in url else f"Bearer {secret}")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    try:
        with opener(proxy_mode).open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"error": {"message": raw[:400]}}
    except Exception as e:  # TLS / DNS / 连接层失败
        return None, {"error": {"message": f"{type(e).__name__}: {e}"}}


def err_msg(payload):
    e = payload.get("error")
    if isinstance(e, dict):
        return str(e.get("message") or e.get("status") or "")
    return str(e or payload)


def violations(payload):
    out = []
    for d in payload.get("error", {}).get("details", []):
        for v in d.get("violations", []):
            out.append(v)
    return out


DAILY_HINTS = ("perday", "daily", "per_day", "day", "2000", "500", "余额", "quota", "limit")


def verdict_of(code, payload, prior_usage, kind="gemini"):
    """返回 (动作, 说明)。动作 ∈ call_ok / retry / throttled / day_exhausted /
    no_free / no_credit / gone / bad_arg / no_key / transport"""
    if code == 200:
        return "call_ok", ""
    if code is None:
        return "transport", err_msg(payload)[:180]
    if code == 503:
        return "retry", "服务端忙（实测同 key 同型号连打会 200→503 抖动，必须重试）"
    if code in (401, 403):
        return "no_key", err_msg(payload)[:180]
    if code == 402:
        return "no_credit", "账户余额不足，充值后自动回池"
    if code == 404:
        return "gone", "对新用户已关"
    if code == 400:
        return "bad_arg", err_msg(payload)[:180]
    if code == 429:
        msg = (err_msg(payload) + " " + json.dumps(payload, ensure_ascii=False)[:400]).lower()
        ids = [str(v.get("quotaId", "")) for v in violations(payload)]
        if kind == "gemini":
            # 本会话实测判据：用量为 0 就打 429 ⇒ 上限是 0，不是撞限
            if prior_usage == 0 or len(ids) >= 2:
                return "no_free", "; ".join(ids)[:200]
            if any("PerMinute" in q for q in ids):
                return "retry", "分钟级限流，退避后重试"
            if any("PerDay" in q or "Daily" in q for q in ids):
                return "day_exhausted", "; ".join(ids)[:200]
            return "retry", "429 " + ("; ".join(ids)[:150] or msg[:150])
        # OpenAI 兼容口没有计数器可读，只能看文案
        if prior_usage == 0 and not any(h in msg for h in ("minute", "rpm", "tpm", "分钟", "并发")):
            return "no_free", msg[:180]
        if any(h in msg for h in ("perminute", "minute", "rpm", "tpm", "分钟", "并发")):
            return "throttled", msg[:180]
        if any(h in msg for h in ("余额", "欠费", "充值", "insufficient balance", "arrears")):
            return "no_credit", msg[:180]
        if any(h in msg for h in ("perday", "daily", "day", "quota", "limit", "额度", "超限",
                                  "2000", "500")):
            return "day_exhausted", msg[:180]
        return "throttled", msg[:180]
    return "retry", f"HTTP {code} {err_msg(payload)[:120]}"


# ---------------------------------------------------------------- 池子遍历与选路
def all_slots(cfg, platforms=None):
    for plat, pnode in cfg["platforms"].items():
        if platforms and plat not in platforms:
            continue
        for acct, anode in pnode.get("accounts", {}).items():
            for k in anode.get("keys", []):
                yield plat, acct, k["label"], pnode, k


def platforms_in_scope(cfg, args, task_spec):
    """平台优先级：显式 --platform > 任务表 > 全部已登记账号的平台 > priority 序第一。"""
    if getattr(args, "platform", None):
        return [args.platform]
    if task_spec and task_spec.get("platforms"):
        return list(task_spec["platforms"])
    have = sorted({plat for plat, _a, _l, _p, _k in all_slots(cfg)})
    if have:
        return have
    return [min(cfg["platforms"], key=lambda p: cfg["platforms"][p].get("priority", 99))]


def platform_order(cfg, plat):
    """该平台的型号顺序：prefer（质量偏好，照参考项目）在前，其余按版本从新到旧。"""
    pnode = cfg["platforms"][plat]
    cat = list(pnode.get("catalog") or [])
    pref = [m for m in (pnode.get("prefer") or []) if m in cat]
    rest = [m for m in cat if m not in pref]
    rest.sort(key=model_sort(pnode), reverse=True)
    return pref + rest


def build_order(cfg, plats, fams=None, want=None):
    """候选型号序列：先按给定平台顺序，平台内 prefer 在前、其余从新到旧。

    不把不同厂商的版本号放一起比大小（kimi-k2.7 并不比 gemini-4 旧），
    厂商间的先后由任务表 / --platform 顺序决定 —— 这也是参考项目的做法。
    """
    pairs = [(plat, m) for plat in plats for m in platform_order(cfg, plat)]
    off = set(cfg["policy"].get("disabled_models", []))
    pairs = [(p, m) for p, m in pairs if m not in off]
    if fams:
        pairs = [(p, m) for p, m in pairs if family_of(m) in fams]
    if want:
        # 点名即「只用它」：不许偷偷回落到全链，否则用户以为在跑 A、实际跑了 B
        pairs = [(p, m) for p, m in pairs if m in want]
    return pairs


def cell_paid(cfg, pnode, knode, model, state):
    """收费口径：明确零价、显式免费名单才算免费；未知价格按收费处理。"""
    price = model_price(pnode, model)
    explicitly_free = price == (0.0, 0.0) or (
        price is None and model in (pnode.get("free_models") or []))
    return (not explicitly_free or state == STATE_NO_FREE
            or bool(knode.get("tier") == "paid"))


BUDGET_FIELDS = (
    "run_budget_cny", "daily_budget_cny", "run_token_limit",
    "daily_token_limit", "run_request_limit", "daily_request_limit",
)


def budget_limits(policy):
    try:
        amounts = [float(policy.get(k, 0)) for k in BUDGET_FIELDS[:2]]
        counts = [float(policy.get(k, 0)) for k in BUDGET_FIELDS[2:]]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) and v > 0 for v in amounts):
        return None
    if not all(math.isfinite(v) and v > 0 and v.is_integer() for v in counts):
        return None
    limits = {k: amounts[i] for i, k in enumerate(BUDGET_FIELDS[:2])}
    limits.update({k: int(counts[i]) for i, k in enumerate(BUDGET_FIELDS[2:])})
    return limits


def budget_ready(policy):
    return budget_limits(policy) is not None


def estimate_input_tokens(prompt):
    """保守上界：UTF-8 字节数，避免未接 tokenizer 时低估付费输入。"""
    return max(1, len((prompt or "").encode("utf-8")))


def estimated_call(price, prompt, max_output_tokens):
    input_tokens = estimate_input_tokens(prompt)
    return {
        "input_tokens": input_tokens,
        "output_tokens": max_output_tokens,
        "tokens": input_tokens + max_output_tokens,
        "cost_cny": (input_tokens * price[0]
                     + max_output_tokens * price[1]) / 1_000_000,
    }


def budget_block_reason(cfg, led, day, run_usage, pnode, model, prompt, max_output_tokens):
    pol = cfg["policy"]
    limits = budget_limits(pol)
    if limits is None:
        return "付费预算未配齐（每轮/每日金额、token、请求上限都必须大于 0；token/请求须为整数）"
    price = model_price(pnode, model)
    if price is None:
        return "未知价格，拒绝付费调用"
    est = estimated_call(price, prompt, max_output_tokens)
    daily = daily_totals(led, day)
    if daily["unknown_cost"]:
        return "历史台账有未知成本或待结算请求，拒绝继续付费调用"
    checks = (
        (run_usage["requests"] >= limits["run_request_limit"], "每轮请求上限"),
        (daily["requests"] >= limits["daily_request_limit"], "每日请求上限"),
        (run_usage["tokens"] + est["tokens"] > limits["run_token_limit"], "每轮 token 上限"),
        (daily["tokens"] + est["tokens"] > limits["daily_token_limit"], "每日 token 上限"),
        (run_usage["cost_cny"] + est["cost_cny"] > limits["run_budget_cny"], "每轮金额上限"),
        (daily["cost_cny"] + est["cost_cny"] > limits["daily_budget_cny"], "每日金额上限"),
    )
    for blocked, label in checks:
        if blocked:
            return label + "已触发"
    return None


def record_usage(rec, kind, payload, price):
    values = usage_of(kind, payload)
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in values):
        raise ValueError("供应商 usage 不是非负整数，成本无法确认；保留待结算标记并停止")
    input_tokens, output_tokens, thought_tokens = values
    rec["in"] = rec.get("in", 0) + input_tokens
    rec["out"] = rec.get("out", 0) + output_tokens
    rec["thought"] = rec.get("thought", 0) + thought_tokens
    if price is None or price == (0.0, 0.0):
        cost = 0.0
    else:
        billable_output = output_tokens + thought_tokens if kind == "gemini" else output_tokens
        cost = (input_tokens * price[0] + billable_output * price[1]) / 1_000_000
    rec["cost_cny"] = rec.get("cost_cny", 0.0) + cost
    return input_tokens, output_tokens, thought_tokens, cost


def park_throttled(cfg, led, day, key, model, note):
    """拥塞/限流挂起，到点自动回池。时长抄 VideoLingo：rate_limit 8 分钟。"""
    until = time.time() + 60 * cfg["policy"].get("cooldown_minutes_rate_limit", 8)
    set_state(led, day, key, model, STATE_THROTTLED, note, until)
    return until


def park_transport(cfg, led, day, key, model, note):
    """网络抖动/读超时用短冷却：8 分钟会把整池锁死，本机代理一抖就全格挂起。"""
    until = time.time() + cfg["policy"].get("cooldown_seconds_transport", 120)
    set_state(led, day, key, model, STATE_THROTTLED, note, until)
    return until


def route(cfg, led, pairs, allow_paid, now=None):
    """产出 (model, slot, pnode, keynode) 候选序列。

    免费优先：所有平台+型号里判为免费的按新→旧排前面，同型号先挑今日用量少的 key。
    收费垫底：价格>0 或实测上限 0 的挂到链尾，allow_paid 为假时整段不进链。
    拦下不进链：gone（已关）、exhausted（日额度满）、throttled/no_credit（冷却中）。
    """
    usage = ledger_get(led, quota_day())["usage"]
    pol = cfg["policy"]
    free_c, paid_c = [], []
    for plat, m in pairs:
        pnode = cfg["platforms"][plat]
        rows = []
        for _pl, acct, label, node, k in all_slots(cfg, [plat]):
            key = slot(plat, acct, label)
            st = get_state(led, key, m, now)
            if st in (STATE_GONE, STATE_EXHAUSTED, STATE_THROTTLED, STATE_NO_CREDIT):
                continue
            used = usage.get(f"{key}::{m}", {}).get("req", 0)
            rows.append((used, blended(node, m, pol), node.get("priority", 99), key, k, st))
        rows.sort()
        for _u, _pb, _pr, key, k, st in rows:
            paid = cell_paid(cfg, pnode, k, m, st)
            (paid_c if paid else free_c).append((m, key, pnode, k))
    return free_c + (paid_c if allow_paid else [])


def call_once(pnode, secret, model, prompt, gen_cfg):
    if pnode.get("kind") == "gemini":
        url = f"{pnode['base']}/models/{model}:generateContent"
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        if gen_cfg:
            body.update(gen_cfg)
        return http_json(url, secret, body, proxy_mode=pnode.get("proxy", "env"))
    url = f"{pnode['base']}/chat/completions"
    body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    if gen_cfg:
        body.update(gen_cfg)
    return http_json(url, secret, body, proxy_mode=pnode.get("proxy", "env"))


def usage_of(kind, payload):
    if kind == "gemini":
        u = payload.get("usageMetadata", {})
        return (u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0),
                u.get("thoughtsTokenCount", 0))
    u = payload.get("usage", {})
    return (u.get("prompt_tokens", 0), u.get("completion_tokens", 0),
            u.get("reasoning_tokens", 0) or 0)


def text_of(kind, payload):
    if kind == "gemini":
        cand = payload.get("candidates", [{}])[0]
        return "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
    choices = payload.get("choices", [])
    return (choices[0].get("message", {}) or {}).get("content", "") if choices else ""


# ---------------------------------------------------------------- 命令
def cmd_init(cfg, led):
    save(CONFIG_PATH, cfg)
    save(LEDGER_PATH, led)
    print(f"配置：{CONFIG_PATH}")
    print(f"台账：{LEDGER_PATH}")
    print("平台模板已就位（境外 1 + 国产 7）。下一步加密钥（输入不回显，明文只进凭据管理器）：")
    print("  python apikey池.py --add --platform gemini-aistudio --account 邮箱 --label key-A")
    print("  python apikey池.py --add --platform modelscope      --account 你的用户名 --label key-A")


def add_key(cfg, plat, acct, label, secret, tier, path=CONFIG_PATH):
    """存一把钥匙：值进凭据管理器，配置只留凭据名 + tier。同 label 再存 = 换值。"""
    if not secret:
        sys.exit("空的，没存")
    target = cred_target(plat, acct, label)
    anode = cfg["platforms"][plat]["accounts"].setdefault(acct, {"keys": []})
    hit = [k for k in anode["keys"] if k["label"] == label]
    if hit:
        for k in hit:
            k["tier"] = tier
    else:
        anode["keys"].append({"label": label, "cred": target, "tier": tier})
    finding = sensitive_finding(cfg)
    if finding:
        raise ValueError(f"拒绝写入含敏感字段的配置：{finding}")
    cred_write(target, secret, comment=f"{plat}/{acct}/{label}")
    save(path, cfg)
    return target


def remove_key(cfg, plat, acct, label, path=CONFIG_PATH):
    """撤一把钥匙：配置条目连凭据一起删。台账留着，历史用量照旧可查。"""
    pnode = cfg["platforms"].get(plat)
    if not pnode:
        sys.exit(f"没有平台 {plat}。已有：" + ", ".join(sorted(cfg["platforms"])))
    anode = pnode.get("accounts", {}).get(acct)
    if not anode:
        sys.exit(f"{plat} 下没有账号 {acct}")
    hit = [k for k in anode["keys"] if k["label"] == label]
    if not hit:
        sys.exit(f"{plat}/{acct} 下没有 {label}，现有：" + ", ".join(k["label"] for k in anode["keys"]))
    for k in hit:
        if cred_read(k["cred"]) is not None and not cred_delete(k["cred"]):
            print(f"  ! 凭据没删掉（要手动清）：{k['cred']}")
    anode["keys"] = [k for k in anode["keys"] if k["label"] != label]
    if not anode["keys"]:
        del pnode["accounts"][acct]
    save(path, cfg)
    return len(hit)


def cmd_add(cfg, args):
    plat = args.platform
    if plat not in cfg["platforms"]:
        sys.exit(f"没有平台 {plat}。已有：" + ", ".join(sorted(cfg["platforms"])))
    if args.key_env:
        secret = (os.environ.get(args.key_env) or "").strip()
        if not secret:
            sys.exit(f"环境变量 {args.key_env} 是空的，没存")
    else:
        secret = getpass.getpass("粘贴 API key（不回显、不进文件）：").strip()
    target = add_key(cfg, plat, args.account, args.label, secret, args.tier)
    print(f"已存进 Windows 凭据管理器：{target}")
    print(f"登记为 {plat} / {args.account} / {args.label}  tier={args.tier}  读取校验：{mask(cred_read(target))}")


def _reset_text(pnode):
    if pnode.get("kind") == "gemini":
        return "太平洋午夜（北京 16:00）"
    r = pnode.get("quota_reset") or {}
    return f"北京 {r.get('hour', 0):02d}:{r.get('minute', 0):02d}"


def cmd_rm(cfg, args):
    n = remove_key(cfg, args.platform, args.account, args.label)
    print(f"已撤销 {args.platform}/{args.account}/{args.label}（{n} 条凭据已删）")


def cmd_show(cfg, led, args):
    day = quota_day()
    usage = ledger_get(led, day)["usage"]
    states = ledger_get(led, day)["state"]
    print(f"\n台账 {os.path.basename(LEDGER_PATH)}   当前配额日（境外口径）{day}")
    only = args.platform if args.platform in cfg["platforms"] else None
    plats = sorted(cfg["platforms"], key=lambda p: cfg["platforms"][p].get("priority", 99))
    for plat in (only and [only] or plats):
        pnode = cfg["platforms"][plat]
        accts = pnode.get("accounts", {})
        print(f"\n【平台】{plat:<16} {pnode.get('name')}")
        print(f"  kind={pnode.get('kind')}  出口={pnode.get('proxy')}  重置={_reset_text(pnode)}  "
              f"目录 {len(pnode.get('catalog') or [])} 型号  优先级 {pnode.get('priority')}")
        if pnode.get("note"):
            print(f"  备注：{pnode['note']}")
        if not accts:
            print("  （没有账号 —— 用 --add 加）")
            continue
        for acct, anode in sorted(accts.items()):
            print(f"  【账号】{acct}")
            for k in anode.get("keys", []):
                key = slot(plat, acct, k["label"])
                sec = cred_read(k["cred"])
                n = sum(v["req"] for kk, v in usage.items() if kk.startswith(f"{key}::"))
                bad = {}
                for kk, st in states.items():
                    if st != STATE_OK and kk.startswith(f"{key}::"):
                        bad.setdefault(st, []).append(kk.split("::", 1)[1])
                print(f"    【key】{k['label']:<8} {mask(sec):<26} tier={k.get('tier', 'free'):<5} "
                      f"今日已发 {n:>4}  异常 {sum(len(v) for v in bad.values())}")
                for st in (STATE_NO_FREE, STATE_EXHAUSTED, STATE_GONE, STATE_THROTTLED, STATE_NO_CREDIT):
                    if bad.get(st):
                        ids = sorted(set(bad[st]))
                        print(f"            {st:<11}{len(ids):>3} 个：{' '.join(ids[:5])}"
                              f"{' …' if len(ids) > 5 else ''}")
    total = sum(len(p.get("catalog") or []) for p in cfg["platforms"].values())
    print(f"\n合计 {total} 个型号   收费={'放开（仍垫底）' if cfg['policy'].get('allow_paid_by_default') else '默认拦死，要 --allow-paid'}")
    limits = budget_limits(cfg["policy"])
    totals = daily_totals(led, day)
    print(f"付费预算/额度：{'已配齐' if limits else '未配齐（付费执行会直接拒绝）'}")
    if limits:
        print(f"  每轮 ¥{limits['run_budget_cny']:.6f} / {limits['run_token_limit']} tokens / {limits['run_request_limit']} requests")
        print(f"  每日 ¥{limits['daily_budget_cny']:.6f} / {limits['daily_token_limit']} tokens / {limits['daily_request_limit']} requests")
    print(f"  今日已尝试 {totals['requests']} 次，tokens={totals['tokens']}，成本=¥{totals['cost_cny']:.6f}，"
          f"待结算={totals['pending']}，未知成本={'是' if totals['unknown_cost'] else '否'}")
    print("任务路由：")
    for t, v in sorted(cfg.get("tasks", {}).items()):
        print(f"  {t:<8} → {','.join(v.get('platforms') or [])}  families={','.join(v.get('families') or [])}")


def _fetch_catalog(pnode, secret, policy):
    """列型号：gemini 看 supportedGenerationMethods，OpenAI 兼容口看 data[].id。"""
    if pnode.get("kind") == "gemini":
        code, payload = http_json(f"{pnode['base']}/models?pageSize=200", secret,
                                  proxy_mode=pnode.get("proxy", "env"))
        if code != 200:
            return code, payload, []
        ids = [m["name"].replace("models/", "") for m in payload.get("models", [])
               if "generateContent" in m.get("supportedGenerationMethods", [])]
        return code, payload, ids
    code, payload = http_json(f"{pnode['base']}/models", secret,
                              proxy_mode=pnode.get("proxy", "env"))
    if code != 200:
        return code, payload, []
    rows = payload.get("data") or payload.get("models") or []
    floor = policy.get("min_context_tokens", 8192)
    ids = []
    for m in rows:
        mid = m.get("id") if isinstance(m, dict) else str(m)
        if not mid or mid in ids:
            continue
        cap = (m.get("context_length") or m.get("max_objective") or 0) if isinstance(m, dict) else 0
        if cap and cap < floor:
            continue
        ids.append(mid)
    return code, payload, ids


def cmd_refresh(cfg, args):
    plats = [args.platform] if args.platform else list(cfg["platforms"])
    blocked = cfg["policy"].get("block_patterns")
    for plat in sorted(plats, key=lambda p: cfg["platforms"][p].get("priority", 99)):
        pnode = cfg["platforms"][plat]
        keys = [k for _p, _a, _l, _n, k in all_slots(cfg, [plat])]
        if not keys:
            print(f"  · {plat:<16} 无 key，跳过")
            continue
        if not pnode.get("probe_models", True):
            ids = list(pnode.get("prefer") or [])
            pnode["catalog"] = ids
            save(CONFIG_PATH, cfg)
            print(f"  · {plat:<16} 静态表 {len(ids)} 型号（该口无 /models 或不探测）")
            continue
        got, last = [], (None, None)
        for k in keys:
            sec = cred_read(k["cred"])
            if not sec:
                continue
            code, payload, ids = _fetch_catalog(pnode, sec, cfg["policy"])
            last = (code, payload)
            if code == 200:
                got = ids
                break
            print(f"  · {plat:<16} {k['label']} 拉取失败 HTTP {code} {err_msg(payload)[:90]}")
        inc = pnode.get("model_include")
        kept = []
        for m in got:
            if is_blocked(blocked, m):
                continue
            if inc and not re.search(inc, m, re.IGNORECASE):
                continue
            if blended(pnode, m, cfg["policy"]) > float(cfg["policy"].get("max_blended_price", 12)):
                continue
            kept.append(m)
        kept.sort(key=model_sort(pnode), reverse=True)
        pnode["catalog"] = kept
        save(CONFIG_PATH, cfg)
        note = ""
        if last[0] not in (200, None):
            note = f"（探测未通：HTTP {last[0]} {err_msg(last[1])[:60]}）"
        print(f"  · {plat:<16} 探测 {len(got)} → 纳入 {len(kept)} {note}")
        for m in kept[:6]:
            print(f"       {m:<38} family={family_of(m):<11} 综合价={blended(pnode, m, cfg['policy'])}")
        if len(kept) > 6:
            print(f"       … 其余 {len(kept) - 6} 个见配置")


def cmd_ask(cfg, led, args):
    task_spec = cfg.get("tasks", {}).get(args.task) if args.task else None
    if args.task and not task_spec:
        sys.exit(f"没有任务 {args.task}。已有：" + ", ".join(sorted(cfg.get("tasks", {}))))
    allow_paid = args.allow_paid or cfg["policy"].get("allow_paid_by_default", False)
    fams = None
    if task_spec and "any" not in (task_spec.get("families") or ["any"]):
        fams = set(task_spec.get("families"))
    plats = platforms_in_scope(cfg, args, task_spec)
    for p in plats:
        if p not in cfg["platforms"]:
            sys.exit(f"没有平台 {p}")
    want = [args.model] if args.model else None
    if want:
        print(f"点名 {args.model}：本轮只用它；不绕过收费开关与预算闸门，额度没有就直接失败而不偷换型号")
        listed = {m for p in plats for m in (cfg["platforms"][p].get("catalog") or [])}
        absent = [w for w in want if w not in listed]
        if absent:
            print("提示：点名型号不在这些平台的目录里（或被 block 了）：" + " ".join(absent))
    empty = [p for p in plats if not cfg["platforms"][p].get("catalog")]
    if empty and len(empty) < len(plats):
        print("空目录平台（没 key 或没 --refresh），本轮不参与：" + ", ".join(empty))
    pairs = build_order(cfg, plats, fams, want)
    if not any(cfg["platforms"][p].get("catalog") for p in plats):
        sys.exit(f"{','.join(plats)} 目录是空的，先跑 --refresh")
    chain = route(cfg, led, pairs, allow_paid)
    if not chain:
        sys.exit("链空：不是额度全满就是在冷却，或收费模型未放开。看 --show 的异常计数；"
                 "收费模型要 --allow-paid 且已配齐每轮/每日预算与额度")

    if args.max_tokens is not None and args.max_tokens <= 0:
        sys.exit("--max-tokens 必须大于 0")
    try:
        default_output_tokens = int(cfg["policy"].get("default_max_output_tokens", 2048))
    except (TypeError, ValueError):
        sys.exit("policy.default_max_output_tokens 必须是正整数")
    if default_output_tokens <= 0:
        sys.exit("policy.default_max_output_tokens 必须是正整数")
    max_output_tokens = args.max_tokens or default_output_tokens
    run_usage = {"requests": 0, "tokens": 0, "cost_cny": 0.0}
    gen_cfg_cache = {}

    def gen_cfg_for(kind):
        if kind not in gen_cfg_cache:
            g = {}
            if args.thinking is not None:
                g.update({"generationConfig": {"thinkingConfig": {"thinkingBudget": args.thinking}}}
                         if kind == "gemini" else {"enable_thinking": bool(args.thinking)})
            g.update({"generationConfig": {"maxOutputTokens": max_output_tokens}}
                     if kind == "gemini" else {"max_tokens": max_output_tokens})
            gen_cfg_cache[kind] = g
        return gen_cfg_cache[kind]

    print(f"范围：平台={','.join(plats)} 任务={args.task or '未指定'} "
          f"收费={'放开（垫底）' if allow_paid else '拦死'}  候选 {len(chain)} 格")
    if args.dry_run:
        print("将按此顺序尝试（不消耗额度）：")
        for i, (m, key, pnode, k) in enumerate(chain[:30], 1):
            tag = "收费" if cell_paid(cfg, pnode, k, m, get_state(led, key, m)) else "免费"
            print(f"  {i:>2}. [{tag}] {m:<38} ← {key}")
        if len(chain) > 30:
            print(f"  … 其余 {len(chain) - 30} 格")
        return

    max_try = args.max_try or len(chain)
    cells = 0
    for m, key, pnode, k in chain[:max_try]:
        secret = cred_read(k["cred"])
        day = quota_day()  # 台账只有一个日界口径；平台自己的重置点用 until 表达
        kind = pnode.get("kind", "openai")
        reset = None if kind == "gemini" else pnode.get("quota_reset")
        plat, acct, label = key.split("|")
        cells += 1
        if not secret:
            set_state(led, day, key, m, STATE_GONE, "凭据缺失")
            print(f"  ! {m} @ {plat}/{label}: 凭据读取失败 {k['cred']}")
            continue
        for attempt in range(1, cfg["policy"]["max_attempts_per_slot"] + 1):
            prior_ok = used_today(led, day, key, m)
            paid = cell_paid(cfg, pnode, k, m, get_state(led, key, m))
            if paid:
                reason = budget_block_reason(cfg, led, day, run_usage, pnode, m,
                                             args.ask, max_output_tokens)
                if reason:
                    print(f"  × {m} @ {plat}/{label}: {reason} → 不发起请求")
                    break
            attempt_rec = note_attempt(led, day, key, m)
            run_usage["requests"] += 1
            save(LEDGER_PATH, led)
            code, payload = call_once(pnode, secret, m, args.ask, gen_cfg_for(kind))
            act, note = verdict_of(code, payload, prior_ok, kind)
            if act == "call_ok":
                rec = bump(led, day, key, m)  # 只记成功次数：它是排序依据，也是「零用量」判据
                price = model_price(pnode, m)
                used_in, used_out, used_thought, cost = record_usage(rec, kind, payload, price)
                settle_attempt(attempt_rec)
                run_usage["tokens"] += used_in + used_out + used_thought
                run_usage["cost_cny"] += cost
                set_state(led, day, key, m, STATE_OK)
                save(LEDGER_PATH, led)
                print(f"\n成功：{m}  经 {plat}/{acct}/{label}  第 {attempt} 发"
                      f"（前面 {cells - 1} 格没吃下）")
                print(f"  in={rec['in']} out={rec['out']} 思考={rec['thought']}"
                      f"  本轮成本=¥{cost:.6f}（思考 token 也吃 TPM，批量要压）")
                print("\n" + text_of(kind, payload))
                return
            if code is not None:
                settle_attempt(attempt_rec)
            if act == "retry":
                budget = cfg["policy"]["max_attempts_per_slot"]
                if attempt >= budget:
                    park_throttled(cfg, led, day, key, m, f"连打 {attempt} 次仍拥塞")
                    print(f"  ~ {m} @ {plat}/{label}: 连打 {attempt} 次仍拥塞 → 冷却 "
                          f"{cfg['policy'].get('cooldown_minutes_rate_limit', 8)} 分钟，换下一格")
                    save(LEDGER_PATH, led)
                    break
                wait = min(cfg["policy"]["backoff_base_s"] * 2 ** (attempt - 1), 60)
                print(f"  · {m} @ {plat}/{label}: {note} → 等 {wait}s")
                save(LEDGER_PATH, led)
                time.sleep(wait)
                continue
            if act == "throttled":
                park_throttled(cfg, led, day, key, m, note)
                print(f"  ~ {m} @ {plat}/{label}: 限流，冷却 "
                      f"{cfg['policy'].get('cooldown_minutes_rate_limit', 8)} 分钟后再用")
            elif act == "no_credit":
                until = time.time() + 3600 * cfg["policy"].get("cooldown_hours_quota_paid", 24)
                set_state(led, day, key, m, STATE_NO_CREDIT, note, until)
                print(f"  ! {m} @ {plat}/{label}: 余额不足，24h 内不再投（充值后清台账该格）")
            elif act == "day_exhausted":
                # 记 until：国产口 00:10 重置比太平洋日界早，只靠换日回池会提前放行、白撞一次
                set_state(led, day, key, m, STATE_EXHAUSTED, note,
                          time.time() + seconds_to_reset(pnode))
                print(f"  × {m} @ {plat}/{label}: 日额度用完（{_reset_text(pnode)} 重置）→ 换下一格")
            elif act == "no_free":
                set_state(led, day, key, m, STATE_NO_FREE, note)
                print(f"  × {m} @ {plat}/{label}: 免费层上限 0（今天成功 {prior_ok} 次就打 429）→ 记进台账")
            elif act == "no_key":
                set_state(led, day, key, m, STATE_GONE, note)
                print(f"  ! {m} @ {plat}/{label}: key 被拒（HTTP {code}）{note[:120]}")
            elif act == "transport":
                park_transport(cfg, led, day, key, m, note[:120])
                print(f"  ~ {m} @ {plat}/{label}: 网络/超时 → 冷却 "
                      f"{cfg['policy'].get('cooldown_seconds_transport', 120)} 秒，换下一格"
                      f"（{note[:80]}）")
            else:
                print(f"  × {m} @ {plat}/{label}: {act} (HTTP {code}) {note[:150]}")
            save(LEDGER_PATH, led)
            break
    save(LEDGER_PATH, led)
    sys.exit("整条链都没吃下这个请求。--show 看异常型号；额度真用完要等 "
             "Gemini 北京 16:00 / 国产 00:10")


def cmd_new_task(cfg, args):
    if not args.task or not args.platform:
        sys.exit("--new-task 需要 --task 名字 和 --platform 平台（多个用逗号）")
    fams = (args.families or "any").split(",")
    cfg.setdefault("tasks", {})[args.task] = {
        "platforms": [p.strip() for p in args.platform.split(",") if p.strip()],
        "families": fams,
        "note": args.note or "",
    }
    save(CONFIG_PATH, cfg)
    print(f"任务 {args.task} → {cfg['tasks'][args.task]}")


# ---------------------------------------------------------------- 自检
def selftest():
    n = 0
    fails = []

    def ok(cond, msg):
        nonlocal n
        n += 1
        if not cond:
            fails.append(msg)

    # 1. 版本排序：新在前
    models = ["gemini-2.5-flash", "gemini-3.8-flash", "gemini-4-hydrogen",
              "gemini-3.1-flash-lite", "gemini-flash-latest"]
    srt = sorted(models, key=lambda m: version_key(m), reverse=True)
    ok(srt[0] == "gemini-flash-latest", f"别名该排最新：{srt}")
    ok(srt[1] == "gemini-4-hydrogen", f"4 该在 3.8 前：{srt}")
    ok(srt[-1] == "gemini-2.5-flash", f"2.5 该垫底：{srt}")
    # 日期后缀不许冒充新版（实测这些还不是普通生成口）
    srt2 = sorted(["antigravity-preview-09-2026", "gemini-4-hydrogen",
                   "deep-research-pro-preview-12-2025"], key=version_key, reverse=True)
    ok(srt2[0] == "gemini-4-hydrogen", f"真型号该压过日期后缀：{srt2}")
    ok(is_blocked(DEFAULT_CONFIG["policy"]["block_patterns"], "antigravity-preview-latest"),
       "antigravity 该被 block（实测 400 只支持 Interactions API）")
    ok(is_blocked(DEFAULT_CONFIG["policy"]["block_patterns"], "gemini-robotics-er-2-preview"),
       "robotics 该被 block")
    ok(_num_ver("Qwen/Qwen3.5-397B-A17B") > _num_ver("Qwen/Qwen3-235B-A22B"),
       "3.5 该比 3 新，参数量后缀不参与")
    ok(_num_ver("Qwen/Qwen3.5-397B-A17B") > _num_ver("MiniMax/MiniMax-M2.5"), "国产版本序")

    # 2. 家族归类：档位优先，厂商名一律 chat
    ok(family_of("gemini-3.5-flash-lite") == "flash-lite", "flash-lite 归类")
    ok(family_of("gemini-3-pro-image") == "image", "image 优先于 pro 归类")
    ok(family_of("glm-4.7-flash") == "flash", "glm-4.7-flash 按档位归 flash")
    ok(family_of("Qwen/Qwen3.5-35B-A3B") == "chat", "qwen 归 chat")
    ok(family_of("qwen3.7-max") == "chat", f"max 归 chat：{family_of('qwen3.7-max')}")

    # 3. 实测判据：零用量即 429 ⇒ 上限 0，不是撞限
    fake = {"error": {"details": [{"violations": [
        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"},
        {"quotaId": "GenerateContentInputTokensPerModelPerMinute-FreeTier"}]}]}}
    ok(verdict_of(429, fake, 0)[0] == "no_free", "零用量多计数器 429 应判 no_free")
    ok(verdict_of(429, fake, 5)[0] == "no_free", "≥2 个计数器同报也应判 no_free")
    one_min = {"error": {"details": [{"violations": [
        {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}]}}
    ok(verdict_of(429, one_min, 7)[0] == "retry", "单发分钟限流应退避重试")
    one_day = {"error": {"details": [{"violations": [
        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}
    ok(verdict_of(429, one_day, 9)[0] == "day_exhausted", "单发日额度应判 day_exhausted")

    # 4. 503 抖动必须重试（本会话实测 200→503 同 key 同型号）
    ok(verdict_of(503, {"error": {"message": "high demand"}}, 1)[0] == "retry", "503 该重试")
    ok(verdict_of(404, {"error": {"message": "no longer available"}}, 0)[0] == "gone", "404 该判已关")
    ok(verdict_of(401, {"error": {"message": "bad key"}}, 0)[0] == "no_key", "401 该判 key 被拒")
    ok(verdict_of(402, {"error": {"message": "insufficient balance"}}, 0)[0] == "no_credit", "402 该判余额不足")

    # 5. 配额日界只认太平洋午夜；国产重置点走 until
    ok(quota_day(datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc)) == "2026-11-17",
       "UTC 11-18 06:30 = 太平洋 11-17 22:30")
    ok(quota_day(datetime(2026, 11, 18, 8, 30, tzinfo=timezone.utc)) == "2026-11-18",
       "UTC 11-18 08:30 = 太平洋 11-18 00:30")
    ok(_us_dst(datetime(2026, 7, 1)) and not _us_dst(datetime(2026, 11, 18)), "夏令时判定")
    # 北京时间 00:00 整：距 00:10 重置 = 600s + 180s 余量
    s = seconds_to_reset(DEFAULT_CONFIG["platforms"]["modelscope"],
                         datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc))
    ok(770 < s < 790, f"国产口该在约 13 分钟后回池：{s}")
    # 太平洋 11-17 23:00（= UTC 11-18 07:00，冬令时）距午夜 3600s + 180s 余量
    sg = seconds_to_reset(DEFAULT_CONFIG["platforms"]["gemini-aistudio"],
                          datetime(2026, 11, 18, 7, 0, tzinfo=timezone.utc))
    ok(3770 < sg < 3790, f"Gemini 口该在约 63 分钟后回池：{sg}")

    # 6. 国产 OpenAI 口的 429 文案分档
    ok(verdict_of(429, {"error": {"message": "每分钟请求过多"}}, 3, "openai")[0] == "throttled", "分钟档")
    ok(verdict_of(429, {"error": {"message": "daily quota exceeded"}}, 3, "openai")[0] == "day_exhausted", "日额度档")
    ok(verdict_of(429, {"error": {"message": "Free limit reached"}}, 0, "openai")[0] == "no_free", "零用量档")
    ok(verdict_of(429, {"error": {"message": "账户余额不足"}}, 3, "openai")[0] == "no_credit", "余额档")

    # 7. 价格表 → 收费判定
    pol = DEFAULT_CONFIG["policy"]
    zp = DEFAULT_CONFIG["platforms"]["zhipu"]
    ok(blended(zp, "glm-4.7-flash", pol) == 0, f"glm-4.7-flash 该算免费：{blended(zp, 'glm-4.7-flash', pol)}")
    ok(blended(zp, "glm-5.3", pol) == 44.0, f"glm-5.3 综合价 = 8×2+28×1 = 44：{blended(zp, 'glm-5.3', pol)}")
    ok(blended(zp, "glm-5.3-flash", pol) < blended(zp, "glm-5.3", pol), "flash 该比 pro 便宜")
    ok(is_blocked(pol["block_patterns"], "bge-m3:embed") and not is_blocked(pol["block_patterns"], "qwen3.7-max"),
       "block_patterns 该拦嵌入模型")
    ok(is_blocked(pol["block_patterns"], "Qwen/Qwen3.5-4B"), "block_patterns 该拦 <10B 小模型")
    ok(not is_blocked(pol["block_patterns"], "Qwen/Qwen3.5-35B-A3B"), "35B 不该被拦")

    # 8. 路由：免费优先 + 收费默认排除 + 跨日恢复
    led = {}
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["platforms"]["gemini-aistudio"]["free_models"] = [
        "gemini-4-hydrogen", "gemini-3.5-flash-lite"]
    for plat in ("gemini-aistudio", "modelscope"):
        cfg["platforms"][plat]["accounts"] = {
            "me": {"keys": [{"label": "k1", "cred": "T/k1"}, {"label": "k2", "cred": "T/k2"}]}}
    cfg["platforms"]["gemini-aistudio"]["catalog"] = [
        "gemini-4-hydrogen", "gemini-3.5-flash-lite", "gemini-4-carbon"]
    cfg["platforms"]["modelscope"]["catalog"] = ["Qwen/Qwen3.5-35B-A3B"]
    cfg["platforms"]["modelscope"]["prefer"] = ["Qwen/Qwen3.5-35B-A3B"]
    day = quota_day()
    k1 = slot("gemini-aistudio", "me", "k1")
    k2 = slot("gemini-aistudio", "me", "k2")
    for kk in (k1, k2):
        set_state(led, day, kk, "gemini-4-carbon", STATE_NO_FREE)
    set_state(led, day, k1, "gemini-4-hydrogen", STATE_EXHAUSTED)
    ledger_get(led, day)["usage"][f"{k2}::gemini-4-hydrogen"] = {"req": 3}
    pairs = build_order(cfg, ["gemini-aistudio", "modelscope"])
    ok(pairs[0][1] == "gemini-4-hydrogen", f"链首该是最新：{pairs[0]}")
    ok(("modelscope", "Qwen/Qwen3.5-35B-A3B") in pairs, "国产免费口该进链")
    chain = route(cfg, led, pairs, False)
    got = [m for m, _k, _p, _l in chain]
    ok("gemini-4-carbon" not in got, "收费垫底默认必须拦住：no_free 型号不该进链")
    ok(got[0] == "gemini-4-hydrogen", f"最新型号该先试：{got}")
    ok([k.split('|')[2] for m, k, _p, _l in chain if m == "gemini-4-hydrogen"] == ["k2"],
       "k1 的 4-hydrogen 日额度已满，该只剩 k2：" + str(
           [k.split('|')[2] for m, k, _p, _l in chain if m == "gemini-4-hydrogen"]))
    lite = [(m, k.split('|')[0]) for m, k, _p, _l in chain]
    ok(lite.count(("gemini-3.5-flash-lite", "gemini-aistudio")) == 2, "没吃满的型号两张 key 都留着")
    chain_paid = route(cfg, led, pairs, True)
    ok(chain_paid[-1][0] == "gemini-4-carbon", f"放开收费后 no_free 该在链尾：{chain_paid[-1]}")
    ok(chain_paid[:len(chain)] == chain, "放开收费只该在链尾追加，前面的免费顺序不许变")
    cfg["platforms"]["gemini-aistudio"]["accounts"]["me"]["keys"][0]["tier"] = "paid"
    ch_mix = route(cfg, led, pairs, False)
    ok([k.split("|")[2] for m, k, _p, _l in ch_mix if m == "gemini-3.5-flash-lite"] == ["k2"],
       f"标了 tier=paid 的 key 默认不该进免费链：" + str(
           [(m, k) for m, k, _p, _l in ch_mix if m == "gemini-3.5-flash-lite"]))
    ok(any(k.split("|")[2] == "k1" for m, k, _p, _l in route(cfg, led, pairs, True)
           if m == "gemini-3.5-flash-lite"), "放开收费后付费 key 该回来")
    cfg["platforms"]["gemini-aistudio"]["accounts"]["me"]["keys"][0]["tier"] = "free"
    # 标签必须和分桶同源：价格 0 但实测上限 0 的，dry-run 不许再喊「免费」
    gp = cfg["platforms"]["gemini-aistudio"]
    ok(cell_paid(cfg, gp, gp["accounts"]["me"]["keys"][0], "gemini-4-carbon", STATE_NO_FREE),
       "价格 0 + no_free 该标收费")
    ok(not cell_paid(cfg, gp, gp["accounts"]["me"]["keys"][0],
                     "gemini-3.5-flash-lite", STATE_OK),
       "价格 0 + 有免费额度该标免费")
    # 8b. 点名收费模型不绕过 --allow-paid；dry-run 仍与分桶同源
    buf = io.StringIO()
    err = io.StringIO()
    exit_code = None
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        try:
            cmd_ask(cfg, led, argparse.Namespace(ask="x", task=None, model="gemini-4-carbon",
                                                platform=None, allow_paid=False, dry_run=True,
                                                thinking=None, max_tokens=None, max_try=None))
        except SystemExit as exc:
            exit_code = exc.code
    dry_blocked = buf.getvalue() + err.getvalue() + str(exit_code or "")
    ok("链空" in dry_blocked and "[收费] gemini-4-carbon" not in dry_blocked,
       f"点名收费模型仍绕过了 allow_paid：{dry_blocked.strip()[-200:]}")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_ask(cfg, led, argparse.Namespace(ask="x", task=None, model="gemini-4-carbon",
                                            platform=None, allow_paid=True, dry_run=True,
                                            thinking=None, max_tokens=None, max_try=None))
    dry = buf.getvalue()
    ok("[收费] gemini-4-carbon" in dry, f"dry-run 标签没跟分桶同源：" + dry.strip()[-160:])
    ok("候选 2 格" in dry and dry.count("[收费] gemini-4-carbon") == 2,
       f"点名型号该把两把 key 横着排：{dry.strip()[-160:]}")

    # 9. 冷却中的格子不进链，过点自己回池
    set_state(led, day, k2, "gemini-3.5-flash-lite", STATE_THROTTLED, "429", time.time() + 300)
    ch = [m + "|" + k.split('|')[2] for m, k, _p, _l in route(cfg, led, pairs, False)]
    ok("gemini-3.5-flash-lite|k2" not in ch, f"限流冷却中该跳过：{ch}")
    ok("gemini-3.5-flash-lite|k2" in [m + "|" + k.split('|')[2] for m, k, _p, _l in
                                      route(cfg, led, pairs, False, now=time.time() + 400)],
       "冷却结束该自动回池")

    # 9b. 拥塞退避用光 / 读超时都必须挂起：真跑 cmd_ask，只把 call_once、凭据、台账路径换成假件
    real_led_bytes = open(LEDGER_PATH, "rb").read() if os.path.exists(LEDGER_PATH) else b""

    def ask_stubbed(resp):
        ledx, cfgx = {}, json.loads(json.dumps(cfg))
        cfgx["policy"]["backoff_base_s"] = 0
        keep = {n: globals()[n] for n in ("call_once", "cred_read", "LEDGER_PATH")}
        tmp = os.path.join(HERE, f"_selftest_live_{os.getpid()}_{time.time_ns()}.json")
        globals()["call_once"] = lambda *a, **k: resp
        globals()["cred_read"] = lambda name: "SELFTEST-FAKE-KEY"
        globals()["LEDGER_PATH"] = tmp
        b = io.StringIO()
        try:
            with contextlib.redirect_stdout(b):
                cmd_ask(cfgx, ledx, argparse.Namespace(ask="x", task=None, model=None,
                                                      platform="gemini-aistudio", allow_paid=False,
                                                      dry_run=False, thinking=None,
                                                      max_tokens=None, max_try=1))
        except SystemExit:
            pass
        finally:
            globals().update(keep)
        wrote = os.path.exists(tmp)
        if wrote:
            os.remove(tmp)
        return ledx, b.getvalue(), wrote

    led2, live, wrote = ask_stubbed((503, {"error": {"message": "high demand"}}))
    st2 = ledger_get(led2, quota_day())["state"]
    ok(len(st2) == 1 and list(st2.values())[0] == STATE_THROTTLED,
       f"连打拥塞后该记 throttled，实际：{st2}")
    ok("连打 3 次仍拥塞" in live and "冷却 8 分钟" in live,
       f"退避用光该明说挂起多久：" + live.strip()[-200:])
    u2 = list(ledger_get(led2, quota_day())["until"].values())
    ok(u2 and 470 <= u2[0] - time.time() <= 481, f"拥塞冷却该是 8 分钟：{u2}")
    led3, live3, _w = ask_stubbed((None, {"error": {"message": "TimeoutError: read timed out"}}))
    st3 = ledger_get(led3, quota_day())["state"]
    ok(len(st3) == 1 and list(st3.values())[0] == STATE_THROTTLED,
       f"读超时也该挂起，否则每次调用白等一个超时：{st3}")
    u3 = list(ledger_get(led3, quota_day())["until"].values())
    ok(u3 and 110 <= u3[0] - time.time() <= 121, f"超时该短冷却 120 秒而不是锁 8 分钟：{u3}")
    ok(wrote, "挂起状态没落到临时台账")
    ok((open(LEDGER_PATH, "rb").read() if os.path.exists(LEDGER_PATH) else b"") == real_led_bytes,
       "自检改动了真实台账")

    # 9c. A3：敏感字段、未知价格、六项预算边界与真实生产调用路径（全程断网替身）
    real_cfg_bytes = open(CONFIG_PATH, "rb").read() if os.path.exists(CONFIG_PATH) else b""
    ok(sensitive_finding({"outer": {"api_key": "x"}}) == "$.outer.api_key",
       "嵌套敏感字段没被认出")
    ok(sensitive_finding({"note": "AIzaABCDEFGHIJKLMNOP"}) == "$.note",
       "疑似密钥值没被认出")
    ok(sensitive_finding({"cred": "QoderAPIKey/p/a/l", "run_token_limit": 1}) is None,
       "凭据名/预算字段被误判成密钥")
    with tempfile.TemporaryDirectory(prefix="_selftest_a3_guard_", dir=HERE) as td:
        for i, payload in enumerate((
                {"nested": {"password": "not-real"}},
                {"note": "sk-abcdefghijklmnop"},
                {"items": [{"clientSecret": "not-real"}]})):
            target = os.path.join(td, f"blocked-{i}.json")
            rejected = False
            try:
                save(target, payload)
            except ValueError:
                rejected = True
            ok(rejected and not os.path.exists(target) and not os.path.exists(target + ".tmp"),
               f"敏感写入没有在落盘前拒绝：{i}")
        safe_path = os.path.join(td, "safe.json")
        safe = {"cred": "QoderAPIKey/p/a/l", "keys": [{"label": "key-A"}],
                "run_token_limit": 1}
        save(safe_path, safe)
        ok(os.path.exists(safe_path) and not os.path.exists(safe_path + ".tmp"),
           "安全配置没写成原子文件")

    with tempfile.TemporaryDirectory(prefix="_selftest_a3_lock_", dir=HERE) as td:
        lock_target = os.path.join(td, "ledger.json")
        probe_code = (
            "import importlib.util, pathlib, sys\n"
            "p = next(pathlib.Path('.').glob('apikey*.py'))\n"
            "spec = importlib.util.spec_from_file_location('apikey_probe', p)\n"
            "a = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(a)\n"
            "try:\n"
            " with a.ledger_lock(sys.argv[1]): print('acquired')\n"
            "except a.LedgerBusy: print('blocked')"
        )
        with ledger_lock(lock_target):
            ok(os.path.exists(lock_target + ".lock"), "台账锁文件没建立")
            blocked = subprocess.run(
                [sys.executable, "-c", probe_code, lock_target], cwd=HERE,
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            ok(blocked.returncode == 0 and "blocked" in blocked.stdout,
               f"第二进程没被台账锁拦住：{blocked.stdout} {blocked.stderr}")
        released = subprocess.run(
            [sys.executable, "-c", probe_code, lock_target], cwd=HERE,
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        ok(released.returncode == 0 and "acquired" in released.stdout,
           f"锁释放后第二进程仍拿不到：{released.stdout} {released.stderr}")

    ok(model_price({"prices": []}, "unknown") is None, "缺价格没返回未知")
    ok(model_price({"prices": [{"pattern": ".", "input": -1, "output": 1}]}, "m") is None,
       "负价格没拒绝")
    ok(model_price({"prices": [{"pattern": ".", "input": "nan", "output": 1}]}, "m") is None,
       "NaN 价格没拒绝")
    ok(model_price({"prices": [{"pattern": ".", "input": 1, "output": "inf"}]}, "m") is None,
       "Infinity 价格没拒绝")
    free_node = {"prices": [], "free_models": ["free-model"]}
    ok(not cell_paid({}, free_node, {"tier": "free"}, "free-model", None),
       "显式免费名单仍被判收费")
    ok(cell_paid({}, free_node, {"tier": "free"}, "free-model", STATE_NO_FREE),
       "no_free 没覆盖显式免费名单")
    ok(cell_paid({}, free_node, {"tier": "paid"}, "free-model", None),
       "paid key 没覆盖显式免费名单")
    ok(cell_paid({}, {"prices": []}, {"tier": "free"}, "unknown-model", None),
       "未知价格没按收费处理")
    ok(not cell_paid({}, {"prices": [{"pattern": ".", "input": 0, "output": 0}]},
                     {"tier": "free"}, "free-model", None), "明确零价没判免费")

    paid_cfg = json.loads(json.dumps(cfg))
    dp = paid_cfg["platforms"]["deepseek"]
    dp["accounts"] = {"probe": {"keys": [
        {"label": "key-A", "cred": "T/probe/key-A", "tier": "paid"}]}}
    dp["catalog"] = ["deepseek-v4-pro"]
    dp["prefer"] = ["deepseek-v4-pro"]
    paid_cfg["policy"].update({
        "run_budget_cny": 1.0, "daily_budget_cny": 2.0,
        "run_token_limit": 100000, "daily_token_limit": 200000,
        "run_request_limit": 3, "daily_request_limit": 6,
    })
    ok(budget_ready(paid_cfg["policy"]), "完整预算没判 ready")
    for field in BUDGET_FIELDS:
        partial = dict(paid_cfg["policy"])
        partial[field] = 0
        ok(not budget_ready(partial), f"缺 {field} 仍允许付费")
    invalid = dict(paid_cfg["policy"])
    invalid["run_token_limit"] = 1.5
    ok(not budget_ready(invalid), "小数 token 上限仍允许付费")
    invalid = dict(paid_cfg["policy"])
    invalid["daily_budget_cny"] = float("nan")
    ok(not budget_ready(invalid), "NaN 金额上限仍允许付费")

    est = estimated_call((4.5, 13.5), "x", 10)
    ok(estimate_input_tokens("中") == 3, "输入 token 没按 UTF-8 字节取保守上界")
    ok(est["tokens"] == 11 and abs(est["cost_cny"] - 0.0001395) < 1e-12,
       f"预估成本算错：{est}")

    def urec(**patch):
        rec = {"attempts": 0, "req": 0, "pending": 0, "in": 0, "out": 0,
               "thought": 0, "cost_cny": 0.0}
        rec.update(patch)
        return rec

    def budget_reason(policy_patch=None, run_patch=None, usage_rec=None, node=None):
        c = json.loads(json.dumps(paid_cfg))
        c["policy"].update(policy_patch or {})
        r = {"requests": 0, "tokens": 0, "cost_cny": 0.0}
        r.update(run_patch or {})
        l = {}
        if usage_rec is not None:
            l["probe"] = {"usage": {"probe::deepseek-v4-pro": usage_rec},
                          "state": {}, "note": {}, "until": {}}
        return budget_block_reason(c, l, "probe", r, node or dp,
                                   "deepseek-v4-pro", "x", 10)

    ok(budget_reason() is None, "完整预算+已知价格仍被误拦")
    ok("每轮请求上限" in budget_reason({"run_request_limit": 1}, {"requests": 1}),
       "每轮请求边界没拦住")
    ok("每日请求上限" in budget_reason({"daily_request_limit": 1}, usage_rec=urec(attempts=1)),
       "每日请求边界没拦住")
    ok("每轮 token 上限" in budget_reason({"run_token_limit": 10}),
       "每轮 token 边界没拦住")
    ok("每日 token 上限" in budget_reason({"daily_token_limit": 10}, usage_rec=urec()),
       "每日 token 边界没拦住")
    ok("每轮金额上限" in budget_reason({"run_budget_cny": 0.0001}),
       "每轮金额边界没拦住")
    ok("每日金额上限" in budget_reason({"daily_budget_cny": 0.0001}, usage_rec=urec()),
       "每日金额边界没拦住")
    equal_limits = {
        "run_token_limit": est["tokens"], "daily_token_limit": est["tokens"],
        "run_budget_cny": est["cost_cny"], "daily_budget_cny": est["cost_cny"],
    }
    ok(budget_reason(equal_limits) is None, "恰好等于上限被误判为超支")
    ok("未知成本" in budget_reason(usage_rec={"req": 1}), "历史未知成本没拦住")
    ok("未知成本" in budget_reason(usage_rec=urec(attempts=1, pending=1)),
       "待结算请求没拦住")
    ok("未知价格" in budget_reason(node={"prices": []}), "未知价格+完整预算仍放行")

    paid_response = (200, {"choices": [{"message": {"content": "OK"}}],
                           "usage": {"prompt_tokens": 10, "completion_tokens": 20}})

    def ask_case(response, config, allow_paid, max_tokens=None):
        workcfg = json.loads(json.dumps(config))
        workcfg["policy"]["backoff_base_s"] = 0
        workled = {}
        calls, gens = [], []
        keep = {n: globals()[n] for n in ("call_once", "cred_read", "LEDGER_PATH")}
        with tempfile.TemporaryDirectory(prefix="_selftest_a3_live_", dir=HERE) as td:
            tmp = os.path.join(td, "ledger.json")

            def fake_call(pnode, secret, model, prompt, gen_cfg):
                calls.append(model)
                gens.append(json.loads(json.dumps(gen_cfg)))
                return response

            globals()["call_once"] = fake_call
            globals()["cred_read"] = lambda name: "SELFTEST-FAKE-KEY"
            globals()["LEDGER_PATH"] = tmp
            out, err = io.StringIO(), io.StringIO()
            exit_code = None
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    try:
                        cmd_ask(workcfg, workled, argparse.Namespace(
                            ask="x", task=None, model="deepseek-v4-pro",
                            platform="deepseek", allow_paid=allow_paid, dry_run=False,
                            thinking=None, max_tokens=max_tokens, max_try=1))
                    except SystemExit as exc:
                        exit_code = exc.code
            finally:
                globals().update(keep)
            wrote = os.path.exists(tmp)
            saved = load_bare(tmp) if wrote else {}
        return workled, calls, gens, out.getvalue() + err.getvalue(), wrote, exit_code, saved

    _l, calls, _g, text, wrote, _e, _s = ask_case(paid_response, paid_cfg, False)
    ok(not calls and not wrote and exit_code is not None and "链空" in str(exit_code),
       "点名收费模型在无 allow-paid 时仍发请求")
    zero_cfg = json.loads(json.dumps(paid_cfg))
    for field in BUDGET_FIELDS:
        zero_cfg["policy"][field] = 0
    _l, calls, _g, text, _w, _e, saved = ask_case(paid_response, zero_cfg, True)
    ok(not calls and not saved[quota_day()]["usage"] and "预算未配齐" in text,
       "allow-paid 但零预算仍发请求")
    unknown_cfg = json.loads(json.dumps(paid_cfg))
    unknown_cfg["platforms"]["deepseek"]["prices"] = []
    _l, calls, _g, text, _w, _e, _s = ask_case(paid_response, unknown_cfg, True)
    ok(not calls and "未知价格" in text, "未知价格仍发请求")
    _l, calls, gens, text, wrote, exit_code, saved = ask_case(paid_response, paid_cfg, True)
    ukey = f"{slot('deepseek', 'probe', 'key-A')}::deepseek-v4-pro"
    rec = saved[quota_day()]["usage"][ukey]
    ok(len(calls) == 1 and wrote and exit_code is None and "OK" in text,
       "完整预算的付费替身调用没走通")
    ok(gens[0].get("max_tokens") == 2048, "默认输出上限没送进生产请求体")
    ok(rec["attempts"] == 1 and rec["req"] == 1 and rec["pending"] == 0
       and rec["in"] == 10 and rec["out"] == 20 and rec["thought"] == 0,
       f"成功调用没记全 attempts/req/usage/pending：{rec}")
    ok(abs(rec["cost_cny"] - 0.000315) < 1e-12 and "本轮成本=¥0.000315" in text,
       f"成功调用成本没按人民币单价回填：{rec}")
    _l, calls, gens, _t, _w, _e, _s = ask_case(paid_response, paid_cfg, True, max_tokens=77)
    ok(len(calls) == 1 and gens[0].get("max_tokens") == 77,
       "显式 --max-tokens 被默认值覆盖")
    _l, calls, _g, _t, _w, _e, saved = ask_case(
        (None, {"error": {"message": "TimeoutError: read timed out"}}), paid_cfg, True)
    rec = saved[quota_day()]["usage"][ukey]
    ok(len(calls) == 1 and rec["attempts"] == 1 and rec["req"] == 0 and rec["pending"] == 1
       and daily_totals(saved, quota_day())["unknown_cost"],
       "传输层超时没保留未知成本，后续付费可能误放行")
    _l, calls, _g, _t, _w, _e, saved = ask_case(
        (503, {"error": {"message": "high demand"}}), paid_cfg, True)
    rec = saved[quota_day()]["usage"][ukey]
    ok(len(calls) == 3 and rec["attempts"] == 3 and rec["pending"] == 0,
       "明确 HTTP 503 没结算 pending")

    usage_rec = {"pending": 1, "in": 0, "out": 0, "thought": 0, "cost_cny": 0.0}
    used = record_usage(usage_rec, "openai", paid_response[1], (4.5, 13.5))
    ok(used == (10, 20, 0, 0.000315), f"OpenAI 真实用量成本算错：{used}")
    gemini_rec = {"in": 0, "out": 0, "thought": 0, "cost_cny": 0.0}
    used = record_usage(gemini_rec, "gemini", {"usageMetadata": {
        "promptTokenCount": 10, "candidatesTokenCount": 20, "thoughtsTokenCount": 5}}, (2.0, 4.0))
    ok(used == (10, 20, 5, 0.00012), f"Gemini 思考 token 没计费：{used}")
    bad_usage = {"pending": 1, "in": 0, "out": 0, "thought": 0, "cost_cny": 0.0}
    rejected = False
    try:
        record_usage(bad_usage, "openai", {"usage": {"prompt_tokens": None}}, (1.0, 1.0))
    except ValueError:
        rejected = True
    ok(rejected and bad_usage["pending"] == 1, "损坏 usage 没保留待结算状态")

    ok((open(LEDGER_PATH, "rb").read() if os.path.exists(LEDGER_PATH) else b"") == real_led_bytes,
       "A3 探针改动了真实台账")
    ok((open(CONFIG_PATH, "rb").read() if os.path.exists(CONFIG_PATH) else b"") == real_cfg_bytes,
       "A3 探针改动了真实配置")

    # 10. 跨配额日：EXHAUSTED 失效，NO_FREE 留着
    past = quota_day(datetime.now(timezone.utc) - timedelta(days=1))
    shifted = {past: led[day]}
    ok(get_state(shifted, k1, "gemini-4-hydrogen") != STATE_EXHAUSTED, "跨日后 exhausted 该失效")
    ok(get_state(shifted, k1, "gemini-4-carbon") == STATE_NO_FREE, "跨日后 no_free 该留着")

    # 11. 任务路由：文案必须落 Gemini
    plats = platforms_in_scope(cfg, argparse.Namespace(platform=None), cfg["tasks"]["文案"])
    ok(plats == ["gemini-aistudio"], f"文案该只走 Gemini：{plats}")
    ok(args_platform_priority(cfg), "--platform 显式指定要压过任务表")
    fam_pairs = build_order(cfg, ["gemini-aistudio"], fams={"flash-lite"})
    ok(all(family_of(m) == "flash-lite" for _p, m in fam_pairs), "families 过滤")
    named = build_order(cfg, ["gemini-aistudio"], want=["gemini-3.5-flash-lite"])
    ok([m for _p, m in named] == ["gemini-3.5-flash-lite"] * len(named) and named,
       f"点名即只用它，不许偷偷回落全链：{named}")
    ok(build_order(cfg, ["gemini-aistudio"], want=["不存在的型号"]) == [], "点名不存在的型号该给空链")

    # 12. 台账与配置里没有密钥值
    blob = json.dumps(led) + json.dumps(cfg)
    ok("AIza" not in blob and "AQ." not in blob, "台账/配置里混进了疑似密钥")
    ok(cred_target("p", "a", "l") == "QoderAPIKey/p/a/l", "凭据命名")
    ok(mask("AQ.ABCDEFGHIJKLMNOP") == "已配置（19 字符）",
       f"掩码：{mask('AQ.ABCDEFGHIJKLMNOP')}")
    ok("AQ.ABC" not in mask("AQ.ABCDEFGHIJKLMNOP") and "MNOP" not in mask("AQ.ABCDEFGHIJKLMNOP"),
       "掩码不许漏出首尾片段")

    # 13. 凭据管理器真写一条假密钥、读回、删掉（结构体错位在这里必炸）
    tgt = cred_target("_selftest", "local", "dummy")
    probe = "SELFTEST-NOT-A-KEY-0123456789"
    cred_write(tgt, probe, comment="自检用，随后即删")
    ok(cred_read(tgt) == probe, "凭据写入后读不回原值")
    ok(cred_read(cred_target("_selftest", "local", "不存在")) is None, "读不存在的凭据应返回 None")
    ok(cred_delete(tgt), "凭据删除失败")
    ok(cred_read(tgt) is None, "删除后仍可读到")

    # 13b. 登记 / 撤销：配置条目和凭据必须同时出现、同时消失，且都在临时配置里做
    tc = os.path.join(HERE, "_selftest_keys.json")
    save(tc, {"platforms": {"zhipu": {"accounts": {}}}, "policy": {}, "tasks": {}})
    kcfg = load_bare(tc)
    tgt2 = add_key(kcfg, "zhipu", "_probe", "key-X", probe, "free", path=tc)
    ok(cred_read(tgt2) == probe, "add_key 没把值写进凭据管理器")
    ok(kcfg["platforms"]["zhipu"]["accounts"]["_probe"]["keys"][0]["cred"] == tgt2,
       "配置里存的该是凭据名")
    ok(probe not in json.dumps(load_bare(tc)), "配置文件里出现了密钥明文")
    add_key(kcfg, "zhipu", "_probe", "key-X", probe + "-2", "paid", path=tc)
    ok(cred_read(tgt2) == probe + "-2", "同 label 再存该换值")
    ok(len(kcfg["platforms"]["zhipu"]["accounts"]["_probe"]["keys"]) == 1, "同 label 不该登记两条")
    ok(kcfg["platforms"]["zhipu"]["accounts"]["_probe"]["keys"][0]["tier"] == "paid", "换值要能改 tier")
    ok(remove_key(kcfg, "zhipu", "_probe", "key-X", path=tc) == 1, "remove_key 该报删了几条")
    ok(cred_read(tgt2) is None, "撤钥匙后凭据还留在管理器里")
    ok(kcfg["platforms"]["zhipu"]["accounts"] == {}, "撤光后账号节点该删掉")
    ok("_probe" not in json.dumps(load_bare(tc)), "撤钥匙后配置文件还有残留")
    os.remove(tc)

    # 14. 原子写不留 tmp
    tp = os.path.join(HERE, "_selftest_atomic.json")
    save(tp, {"a": 1})
    ok(not os.path.exists(tp + ".tmp"), "原子写没清 tmp")
    os.remove(tp)

    # 15. 老配置缺字段时从模板补齐，已有内容不动；台账读取绝不掺模板
    tmpcfg = os.path.join(HERE, "_selftest_cfg.json")
    save(tmpcfg, {"platforms": {"zhipu": {"accounts": {}}}, "policy": {}, "tasks": {}})
    merged = load_config(tmpcfg)
    ok(merged["platforms"]["zhipu"]["base"] == DEFAULT_CONFIG["platforms"]["zhipu"]["base"],
       "老配置缺字段该从模板补齐")
    ok("max_blended_price" in merged["policy"], "policy 缺键该补齐")
    ok(merged["platforms"]["zhipu"]["accounts"] == {}, "补齐不许覆盖已有内容")
    edited = {"policy": {"max_blended_price": 3}}
    save(tmpcfg, edited)
    ok(load_config(tmpcfg)["policy"]["max_blended_price"] == 3, "用户改过的阈值不该被模板盖回")
    os.remove(tmpcfg)
    tmpled = os.path.join(HERE, "_selftest_led.json")
    save(tmpled, {"2026-01-01": new_day()})
    ok(set(load_bare(tmpled)) == {"2026-01-01"},
       "load_bare 往台账里掺了键：" + str(sorted(load_bare(tmpled))))
    ok(load_bare(os.path.join(HERE, "_不存在.json")) == {}, "缺台账该给空字典")
    os.remove(tmpled)

    print(f"selftest：{n - len(fails)}/{n} 通过")
    for f in fails:
        print("  FAIL " + f)
    return 1 if fails else 0


def args_platform_priority(cfg):
    ok = platforms_in_scope(cfg, argparse.Namespace(platform="modelscope"), cfg["tasks"]["文案"])
    return ok == ["modelscope"]


# ---------------------------------------------------------------- 入口
def main():
    ap = argparse.ArgumentParser(description="API key 池 + 免费优先/收费垫底的模型路由")
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--add", action="store_true")
    ap.add_argument("--rm", dest="rm", action="store_true", help="撤掉一把钥匙（连凭据一起删）")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="拉型号目录（境外口要代理）")
    ap.add_argument("--ask")
    ap.add_argument("--task")
    ap.add_argument("--new-task", dest="task_name")
    ap.add_argument("--families")
    ap.add_argument("--note")
    ap.add_argument("--model")
    ap.add_argument("--platform")
    ap.add_argument("--account")
    ap.add_argument("--label", default="key-A")
    ap.add_argument("--tier", default="free", choices=["free", "paid"])
    ap.add_argument("--key-env", dest="key_env", metavar="NAME",
                    help="从这个名字的环境变量读密钥（没终端可用时用，别写进脚本）")
    ap.add_argument("--allow-paid", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-try", type=int, help="最多试几格（默认全链）")
    ap.add_argument("--thinking", type=int, help="thinkingBudget；0=关思考省 TPM")
    ap.add_argument("--max-tokens", type=int)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    cfg = load_config(CONFIG_PATH)
    led = load_bare(LEDGER_PATH)

    if args.init:
        try:
            with ledger_lock(LEDGER_PATH):
                cfg = load_config(CONFIG_PATH)
                led = load_bare(LEDGER_PATH)
                cmd_init(cfg, led)
        except LedgerBusy as exc:
            sys.exit(str(exc))
    elif args.add:
        if not args.account:
            sys.exit("--add 需要 --account 和 --label")
        cmd_add(cfg, args)
    elif args.rm:
        if not (args.platform and args.account):
            sys.exit("--rm 需要 --platform --account --label")
        cmd_rm(cfg, args)
    elif args.show:
        cmd_show(cfg, led, args)
    elif args.refresh:
        cmd_refresh(cfg, args)
    elif args.ask:
        try:
            with ledger_lock(LEDGER_PATH):
                cfg = load_config(CONFIG_PATH)
                led = load_bare(LEDGER_PATH)
                cmd_ask(cfg, led, args)
        except LedgerBusy as exc:
            sys.exit(str(exc))
    elif args.task_name:
        args.task = args.task_name
        cmd_new_task(cfg, args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
