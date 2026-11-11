# -*- coding: utf-8 -*-
"""M7：短窗口搜索（依据 _scratch/强模型方案回复.md §A2 / §C2 / §5 M7）。

验收口径：能修复一个人为扰动的已知动作；超预算正确退出；解可复播。
方法：人工示范＋参数搜索——只搜"几个动作宏"的时序/距离/资源参数，不从每帧所有
按键组合盲搜（成本随 b^h 爆炸）。

落实方案规则：
  * 搜索任务只分配给已验证具备相应能力的后端；不合格能力 => UNSUPPORTED_CAPABILITY，
    不开放给搜索（§4.3 / M3）。FBNeo 走 rig.capture_move 的 reset→advance→HUD判分，
    是墙上时间驱动的参数搜索，不是帧精确交互步进（interactive_step 仍 False）。
  * 判分走受控插件（detect 的 metric/frame registry），不执行网页/模型给的任意代码；
    证据不足 => inconclusive，不是通过。
  * 先尝试原动作（seed），再围绕参数局部搜索；命中即冻结输入。
  * 解必须可复播：冻结后从声明起点再跑一遍，复现才算解；同配置多次结果不同 =>
    NONDETERMINISM，不冒充解（§C1 重试规则）。
  * 超预算 => SEARCH_BUDGET_EXHAUSTED，明确"不是证明无解"（§4.4 台账规则）。
  * 必测吞吐：save/load/advance/判分的完整 wall 时间记进结果（§A2）。
  * 台账 GENERATE 阶段：登记只记元数据；成功对应可校验产物；失败保留历史。

运行:
  python -m taspipe.search demo                 # 确定性参考模型：修复扰动+超预算+复播
  python -m taspipe.search fbneo --notation "→+B" --char kyo \
      --state F:/tas_rig/states/base_kyo.fs --out <dir> --budget 6
"""
import argparse
import itertools
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .schema import (Verification, CheckResult, CheckSpec, Verdict, Stage,
                     FailureCode, to_dict)
from .ledger import Ledger, fingerprint
from . import detect


# ------------------------------------------------------------- 观察 / 环境契约

@dataclass
class Observation:
    """一次 evaluate 的产物：数值观察 + 可选帧 + 冻结输入引用。"""
    metrics: dict = field(default_factory=dict)
    frame: object = None          # 截图路径（frame 插件用）；数值搜索可为 None
    input_ref: str = ""           # 冻结输入（电影/计划）引用，解可复播的载体
    raw: dict = field(default_factory=dict)


class SearchEnv:
    """搜索环境契约（对齐 §4.3 Session：load_state/advance/observe）。

    子类必须声明 search_capability；引擎据此决定是否开放搜索。evaluate 从声明起点
    跑冻结输入并观察；replay 再跑一遍验证确定性（默认同 evaluate）。
    """
    start_ref = ""

    def search_capability(self):
        return {"supported": False, "evidence": "基类未实现，不开放给搜索"}

    def evaluate(self, params):
        raise NotImplementedError

    def replay(self, params):
        return self.evaluate(params)


def _run_checks(checks, obs):
    """受控判分：plugin_id 命中 metric registry 走数值，命中 frame registry 走帧；
    都未命中 => inconclusive（不静默通过）。"""
    results = []
    for spec in checks:
        if not isinstance(spec, CheckSpec):
            spec = CheckSpec(**spec)
        spec.validate()
        pid = spec.plugin_id
        if pid in detect.METRIC_PLUGINS:
            results.append(detect.run_metric_check(spec, obs.metrics))
        elif pid in detect.PLUGINS:
            if obs.frame:
                results.append(detect.run_check(spec, obs.frame))
            else:
                results.append(CheckResult(spec.check_id, Verdict.INCONCLUSIVE,
                                           reason=f"帧插件 {pid} 缺观察帧"))
        else:
            results.append(CheckResult(spec.check_id, Verdict.INCONCLUSIVE,
                                       reason=f"未注册插件 {pid}"))
    return results


def _verdict(checks, obs, vid, subject):
    results = _run_checks(checks, obs)
    v = Verification(vid, subject, Stage.VERIFY, results).validate()
    return v, results


# ------------------------------------------------------------- 候选空间 / 预算

@dataclass
class CandidateSpace:
    """动作宏参数的有界离散空间。seed 先试，再按轴笛卡尔积展开（去重、硬上限）。

    axes = [(name, [values...]), ...]；这是"搜几个参数"，不是"每帧盲搜按键"。
    """
    axes: list = field(default_factory=list)
    seed: dict = field(default_factory=dict)
    hard_cap: int = 4096

    def candidates(self):
        seen = set()

        def key(p):
            return json.dumps(p, sort_keys=True, ensure_ascii=False)

        out = []
        if self.seed:
            out.append(dict(self.seed))
            seen.add(key(self.seed))
        names = [a[0] for a in self.axes]
        values = [list(a[1]) for a in self.axes]
        for combo in itertools.product(*values) if values else []:
            p = dict(self.seed)
            p.update(dict(zip(names, combo)))
            k = key(p)
            if k in seen:
                continue
            seen.add(k)
            out.append(p)
            if len(out) >= self.hard_cap:
                break
        return out


@dataclass
class SearchBudget:
    max_candidates: int = 16


# ------------------------------------------------------------- 搜索结果

@dataclass
class SearchResult:
    verdict: Verdict
    failure_code: object = None
    solution: object = None       # {params, input_ref, observation, verification}
    attempts: list = field(default_factory=list)
    candidates_tried: int = 0
    budget: int = 0
    timing: dict = field(default_factory=dict)
    reason: str = ""

    def to_dict(self):
        return {
            "schema_version": 1,
            "verdict": self.verdict.value,
            "failure_code": self.failure_code.value if self.failure_code else None,
            "solution": self.solution,
            "attempts": self.attempts,
            "candidates_tried": self.candidates_tried,
            "budget": self.budget,
            "timing": self.timing,
            "reason": self.reason,
        }


def search(env, space, checks, budget=None, ledger=None, key="search",
           fingerprint=None, on_attempt=None):
    """短窗口搜索主循环。返回 SearchResult（不抛业务异常；能力/预算/确定性如实分类）。

    ledger 给定时按 GENERATE 阶段登记/复用/失败分类；on_attempt(rec) 可选回调（进度）。
    """
    budget = budget or SearchBudget()
    checks = [CheckSpec(**c) if isinstance(c, dict) else c for c in checks]
    for c in checks:
        c.validate()
    t_start = time.time()
    per = []

    # ---- 能力闸门：不合格不开放给搜索 ----
    cap = env.search_capability()
    if not cap.get("supported"):
        res = SearchResult(Verdict.INCONCLUSIVE, FailureCode.UNSUPPORTED_CAPABILITY,
                           budget=budget.max_candidates,
                           reason=f"环境未开放搜索能力: {cap.get('evidence')}")
        if ledger:
            job = ledger.register(Stage.GENERATE, key, fingerprint or "")
            ledger.fail(job, FailureCode.UNSUPPORTED_CAPABILITY, res.reason)
        return res

    cands = space.candidates()
    job = ledger.register(Stage.GENERATE, key, fingerprint or "") if ledger else None
    tried = 0
    attempts = []
    for params in cands:
        if tried >= budget.max_candidates:
            break
        tried += 1
        t0 = time.time()
        try:
            obs = env.evaluate(params)
        except Exception as e:
            # 评估本身炸了（缺资源/后端异常）：不是"无解"，记失败现场，停下交人复核。
            per.append(round(time.time() - t0, 3))
            rec = {"params": params, "verdict": Verdict.INCONCLUSIVE.value,
                   "error": f"{type(e).__name__}: {e}"}
            if on_attempt:
                on_attempt(rec)
            res = SearchResult(Verdict.INCONCLUSIVE, FailureCode.UNSUPPORTED_CAPABILITY,
                               attempts=[rec], candidates_tried=tried,
                               budget=budget.max_candidates,
                               timing=_timing(t_start, per),
                               reason=f"evaluate 异常: {rec['error']}")
            if ledger:
                ledger.fail(job, FailureCode.UNSUPPORTED_CAPABILITY, res.reason)
            return res
        dt = round(time.time() - t0, 3)
        per.append(dt)
        v, results = _verdict(checks, obs, f"ver_try{tried}", key)
        rec = {"params": params, "verdict": v.verdict.value, "sec": dt,
               "metrics": obs.metrics, "input_ref": obs.input_ref,
               "checks": [to_dict(c) for c in results]}
        if on_attempt:
            on_attempt(rec)

        if v.verdict == Verdict.PASS:
            # ---- 冻结 + 复播验证确定性 ----
            tr0 = time.time()
            try:
                obs2 = env.replay(params)
                v2, results2 = _verdict(checks, obs2, "ver_replay", key)
            except Exception as e:
                v2 = None
                results2 = []
                obs2 = Observation()
                replay_err = f"{type(e).__name__}: {e}"
            else:
                replay_err = ""
            per.append(round(time.time() - tr0, 3))
            if v2 is not None and v2.verdict == Verdict.PASS:
                sol = {
                    "params": params,
                    "input_ref": obs2.input_ref or obs.input_ref,
                    "start_ref": env.start_ref,
                    "observation": {"metrics": obs2.metrics, "frame": obs2.frame},
                    "verification": {**to_dict(v2), "verdict": v2.verdict.value},
                    "replay_reproduced": True,
                }
                res = SearchResult(Verdict.PASS, None, solution=sol,
                                   candidates_tried=tried, budget=budget.max_candidates,
                                   timing=_timing(t_start, per),
                                   reason=f"第 {tried} 个候选命中并复播复现")
                res.attempts = attempts + [rec]
                if ledger:
                    arts = _write_solution(ledger, key, job, res)
                    ledger.complete(job, arts, Verdict.PASS)
                return res
            # 复播没复现 => 非确定性，不冒充解
            res = SearchResult(Verdict.INCONCLUSIVE, FailureCode.NONDETERMINISM,
                               candidates_tried=tried, budget=budget.max_candidates,
                               timing=_timing(t_start, per),
                               reason=f"命中但复播未复现（{replay_err or 'verdict=' + v2.verdict.value}）；同配置多次结果不同，须调查确定性")
            res.attempts = attempts + [rec]
            if ledger:
                ledger.fail(job, FailureCode.NONDETERMINISM, res.reason)
            return res

        attempts.append(rec)

    # ---- 超预算：正确退出，明确不是证明无解 ----
    res = SearchResult(Verdict.INCONCLUSIVE, FailureCode.SEARCH_BUDGET_EXHAUSTED,
                       attempts=attempts, candidates_tried=tried,
                       budget=budget.max_candidates, timing=_timing(t_start, per),
                       reason=f"展开 {tried}/{len(cands)} 候选未命中；SEARCH_BUDGET_EXHAUSTED 不是证明无解，可加预算/换起点/换参数轴再试")
    if ledger:
        ledger.fail(job, FailureCode.SEARCH_BUDGET_EXHAUSTED, res.reason)
    return res


def _timing(t_start, per):
    total = round(time.time() - t_start, 3)
    return {"total_sec": total, "per_eval_sec": per,
            "evals": len(per),
            "avg_eval_sec": round(sum(per) / len(per), 3) if per else 0.0}


def _write_solution(ledger, key, job, res):
    """把解写成可校验产物（solution.json + 冻结输入引用），交给 ledger.complete 校验。"""
    base = Path(ledger.path).parent
    sol_path = base / f"{job.replace(':', '_')}.solution.json"
    sol_path.write_text(json.dumps(res.to_dict(), ensure_ascii=False, indent=1),
                        encoding="utf-8")
    arts = [str(sol_path)]
    iref = (res.solution or {}).get("input_ref")
    if iref and os.path.isfile(iref):
        arts.append(iref)
    return arts


def run_search(env, space, checks, budget=None, ledger=None, key="search",
               fingerprint=None, on_attempt=None):
    """公开入口：每次调用用独立的局部 attempts 缓冲，不串跨调用证据（并行隔离）。"""
    return search(env, space, checks, budget, ledger, key, fingerprint, on_attempt)


# ------------------------------------------------------------- 确定性参考模型
#
# 离线证明搜索语义用：一个格斗单招的距离/时序窗口模型。明确是模型，不是真实模拟器。
# 招是否打中 = approach 落在距离窗口 且 dir_frames 落在识别时序窗口。可确定性复播。

class ModelMoveEnv(SearchEnv):
    def __init__(self, approach_window=(60, 150), dir_window=(2, 4),
                 damage=0.12, start_ref="model://kyo/spawn"):
        self.approach_window = approach_window
        self.dir_window = dir_window
        self.damage = damage
        self.start_ref = start_ref
        self.calls = 0

    def search_capability(self):
        return {"supported": True,
                "evidence": "确定性参考模型（非真实模拟器；离线证明搜索/预算/复播语义）"}

    def _lands(self, params):
        a = int(params.get("approach", 0))
        d = int(params.get("dir_frames", 2))
        alo, ahi = self.approach_window
        dlo, dhi = self.dir_window
        return alo <= a <= ahi and dlo <= d <= dhi

    def evaluate(self, params):
        self.calls += 1
        hit = self._lands(params)
        dmg = self.damage if hit else 0.0
        return Observation(
            metrics={"damage": dmg, "hit": 1.0 if hit else 0.0,
                     "approach": int(params.get("approach", 0)),
                     "dir_frames": int(params.get("dir_frames", 2))},
            input_ref="model://frozen/" + json.dumps(params, sort_keys=True),
            raw={"lands": hit})

    def replay(self, params):
        # 确定性模型：复播 == 重新评估，必复现。
        return self.evaluate(params)


# ------------------------------------------------------------- 真实 FBNeo 适配器

class FBNeoCaptureEnv(SearchEnv):
    """薄包 rig.capture_move 作 reset→advance→HUD判分 的真实搜索环境（不重写 rig）。

    每次 evaluate = 加载起手状态→放招（approach/dir_frames 为搜索自变量）→内录→
    从 HUD 量对手掉血。墙上时间驱动，非帧精确交互步进；吞吐记进 SearchResult.timing。
    """
    def __init__(self, notation, char, state_path, out_dir, slug_prefix="search",
                 lead=72, tail=120, dir_frames=2, unmute=True, avi3x=1,
                 rig_dir=None, ffmpeg="ffmpeg", neutral_lead=None):
        self.notation = notation
        self.char = char
        self.state_path = str(state_path)
        self.out_dir = str(out_dir)
        self.slug_prefix = slug_prefix
        self.lead = lead
        self.tail = tail
        self.dir_frames = dir_frames
        self.unmute = unmute
        self.avi3x = avi3x
        self.ffmpeg = ffmpeg
        # 远距/片头起点（如 base_kyo.fs）需要一段中立垫帧先放完开场动画，HUD 才画；
        # neutral_lead 给定时 lead=approach+neutral_lead（中立段恒定），否则按 approach 兜底。
        self.neutral_lead = neutral_lead
        self.start_ref = self.state_path
        self._rig_dir = rig_dir
        self._rig = None
        os.makedirs(self.out_dir, exist_ok=True)

    def _get_rig(self):
        if self._rig is None:
            from .backends import FBNeoBackend
            be = FBNeoBackend(self._rig_dir) if self._rig_dir else FBNeoBackend()
            self._rig = be._rig()
            self._rig_dir = be.rig_dir
        return self._rig

    def search_capability(self):
        try:
            rig = self._get_rig()
            import fbneo
            exe = fbneo.discover_exe()
            need = [exe, rig.REFERENCE_MOVIE, self.state_path]
            missing = [p for p in need if not os.path.isfile(p)]
            ok = not missing
            ev = ("rig.capture_move 生产验证 reset→advance→HUD判分；墙上时间驱动，非帧精确步进"
                  if ok else f"缺: {missing}")
            return {"supported": ok, "evidence": ev}
        except Exception as e:
            return {"supported": False, "evidence": f"探针异常 {type(e).__name__}: {e}"}

    def _capture(self, params, suffix=""):
        rig = self._get_rig()
        approach = int(params.get("approach", 0))
        dir_frames = int(params.get("dir_frames", self.dir_frames))
        # rig.padded 要求 approach<=lead；走近帧数变大时垫帧同步加大（对齐 rig.build_plans）。
        if self.neutral_lead is not None:
            lead = approach + self.neutral_lead
        else:
            lead = max(self.lead, approach + rig.HEAD_MARGIN)
        slug = f"{self.slug_prefix}_a{approach}_d{dir_frames}{suffix}"
        rec, log = rig.capture_move(
            self.notation, slug, out_dir=self.out_dir, char=self.char,
            state_path=self.state_path, lead=lead, tail=self.tail,
            approach=approach, dir_frames=dir_frames, unmute=self.unmute,
            avi3x=self.avi3x, log=[])
        return rec

    def evaluate(self, params):
        rec = self._capture(params)
        return Observation(
            metrics={"damage": float(rec.get("damage", 0.0)),
                     "hit": 1.0 if rec.get("hit") else 0.0,
                     "approach": int(rec.get("approach", 0)),
                     "dir_frames": int(rec.get("dir_frames", self.dir_frames))},
            frame=rec.get("hud_end", {}).get("png") if isinstance(rec.get("hud_end"), dict) else None,
            input_ref=rec.get("movie", ""),
            raw={"slug": rec.get("slug"), "out": rec.get("out"),
                 "damage": rec.get("damage"), "hit": rec.get("hit"),
                 "state_gap": rec.get("state_gap")})

    def replay(self, params):
        rec = self._capture(params, suffix="_replay")
        return Observation(
            metrics={"damage": float(rec.get("damage", 0.0)),
                     "hit": 1.0 if rec.get("hit") else 0.0},
            input_ref=rec.get("movie", ""),
            raw={"slug": rec.get("slug"), "out": rec.get("out"),
                 "damage": rec.get("damage"), "hit": rec.get("hit")})


def fbneo_approach_space(seed_approach=0, approaches=(0, 40, 80, 120, 160),
                         dir_frames=2):
    """格斗单招距离搜索轴：approach（走近帧数）。可换成 rig.whiff_variants 的档位排序。"""
    return CandidateSpace(
        axes=[("approach", list(approaches))],
        seed={"approach": seed_approach, "dir_frames": dir_frames})


# ------------------------------------------------------------- CLI

def _demo():
    """确定性模型演示：修复人为扰动的已知动作 + 超预算正确退出 + 解可复播。"""
    import tempfile
    checks = [CheckSpec("hit", "metric_min", {"key": "damage", "min": 0.01})]
    out = {}
    with tempfile.TemporaryDirectory() as td:
        led = Ledger(os.path.join(td, "ledger.json"))
        # 已知动作窗口 approach∈[60,150]；人为扰动 seed=0（远距空放）。
        env = ModelMoveEnv(approach_window=(60, 150))
        space = CandidateSpace(axes=[("approach", [0, 30, 60, 90, 120, 150])],
                               seed={"approach": 0, "dir_frames": 2})
        res = run_search(env, space, checks, SearchBudget(8), ledger=led,
                         key="repair_demo", fingerprint="demo-fp")
        out["repair"] = res.to_dict()
        # 超预算：窗口外无解，预算 2 => SEARCH_BUDGET_EXHAUSTED（不是证明无解）
        env2 = ModelMoveEnv(approach_window=(900, 999))
        res2 = run_search(env2, space, checks, SearchBudget(2), ledger=led,
                          key="exhaust_demo", fingerprint="demo-fp2")
        out["exhaust"] = res2.to_dict()
        out["ledger"] = led.summary()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    ok = (out["repair"]["verdict"] == "pass"
          and out["repair"]["solution"]["replay_reproduced"]
          and out["exhaust"]["failure_code"] == "search_budget_exhausted")
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="确定性参考模型：修复扰动+超预算+复播")
    f = sub.add_parser("fbneo", help="真实 KOF98 参数搜索（薄包 rig.capture_move）")
    f.add_argument("--notation", required=True)
    f.add_argument("--char", default="kyo")
    f.add_argument("--state", required=True, help="起手状态（扰动起点，如 base_kyo.fs）")
    f.add_argument("--out", required=True)
    f.add_argument("--budget", type=int, default=6)
    f.add_argument("--approaches", default="0,40,80,120,160")
    f.add_argument("--dir-frames", type=int, default=2)
    f.add_argument("--lead", type=int, default=72)
    f.add_argument("--tail", type=int, default=120)
    f.add_argument("--neutral-lead", type=int, default=None,
                   help="远距/片头起点的恒定中立垫帧（放完开场动画）；lead=approach+此值")
    f.add_argument("--mute", action="store_true")
    f.add_argument("--rig-dir", default=None)
    f.add_argument("--ffmpeg", default="ffmpeg")
    args = ap.parse_args()

    if args.cmd == "demo":
        return _demo()

    approaches = [int(x) for x in args.approaches.split(",") if x.strip()]
    env = FBNeoCaptureEnv(args.notation, args.char, args.state, args.out,
                          lead=args.lead, tail=args.tail, dir_frames=args.dir_frames,
                          unmute=not args.mute, rig_dir=args.rig_dir, ffmpeg=args.ffmpeg,
                          neutral_lead=args.neutral_lead)
    space = fbneo_approach_space(seed_approach=approaches[0], approaches=approaches,
                                 dir_frames=args.dir_frames)
    checks = [CheckSpec("hit", "metric_min", {"key": "damage", "min": 0.01})]
    led = Ledger(os.path.join(args.out, "ledger.json"))
    fp = fingerprint([args.state], {"notation": args.notation, "char": args.char,
                                    "approaches": approaches, "dir_frames": args.dir_frames,
                                    "lead": args.lead, "tail": args.tail,
                                    "neutral_lead": args.neutral_lead})

    def prog(rec):
        print(f"  试 {rec['params']} => {rec['verdict']} "
              f"damage={rec.get('metrics', {}).get('damage')} ({rec.get('sec')}s)",
              flush=True)

    res = run_search(env, space, checks, SearchBudget(args.budget), ledger=led,
                     key="kof_repair", fingerprint=fp, on_attempt=prog)
    Path(args.out, "search_result.json").write_text(
        json.dumps(res.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=1))
    return 0 if res.verdict == Verdict.PASS else 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())