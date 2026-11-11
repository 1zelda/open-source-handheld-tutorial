# -*- coding: utf-8 -*-
"""离线自检（M0 起逐步累加）。运行: python -m taspipe.selftest"""
import sys
from pathlib import Path
from .schema import (Profile, Element, State, InputPlan, Verification, LedgerJob,
                     CheckSpec, CheckResult, Platform, StateOrigin, ClockUnit,
                     Verdict, Stage, JobStatus, FailureCode, SchemaError)

PASS = 0


def ok(cond, msg):
    global PASS
    if not cond:
        raise AssertionError(msg)
    PASS += 1
    print(f"  [{PASS}] {msg}")


def raises(fn, msg):
    try:
        fn()
    except SchemaError:
        ok(True, msg)
        return
    raise AssertionError(f"应抛 SchemaError: {msg}")


def test_schema():
    p = Profile("pf1", "g1", "nes_bizhawk", Platform.NES, core="NesHawk",
                rom_sha1="B6B0").validate()
    ok(p.platform == Platform.NES, "Profile 合法枚举通过")
    raises(lambda: Profile("x", "g", "b", "NOT_A_PLATFORM").validate(), "未知平台枚举被拒")
    raises(lambda: Profile("", "g", "b", "NES").validate(), "Profile 缺 profile_id 被拒")

    e = Element("el1", "g1", "skill",
                success_checks=[CheckSpec("c1", "hud_pixel")]).validate()
    ok(len(e.success_checks) == 1, "Element 带 CheckSpec 通过")
    raises(lambda: CheckSpec("c", "任意代码!").validate(), "CheckSpec 非法 plugin_id 被拒")
    raises(lambda: Element("e", "g", "k", negative_cases=[{"no_case_id": 1}]).validate(),
           "Element 负例缺 case_id 被拒")

    s = State("st1", "pf1", StateOrigin.TAS_CHECKPOINT).validate()
    ok(s.origin == StateOrigin.TAS_CHECKPOINT, "State origin 枚举通过")
    raises(lambda: State("st", "pf", "bogus").validate(), "未知 StateOrigin 被拒")

    ip = InputPlan("ip1", "pf1", "st1", ClockUnit.EMU_FRAME).validate()
    ok(ip.clock_unit == ClockUnit.EMU_FRAME, "InputPlan clock_unit 通过")

    v = Verification("v1", "clip1", Stage.VERIFY, [
        CheckResult("c1", Verdict.PASS), CheckResult("c2", Verdict.PASS)]).validate()
    ok(v.verdict == Verdict.PASS, "全 pass => pass")
    v2 = Verification("v2", "c", Stage.VERIFY, [
        CheckResult("c1", Verdict.PASS), CheckResult("c2", Verdict.FAIL)]).validate()
    ok(v2.verdict == Verdict.FAIL, "有 fail => fail")
    v3 = Verification("v3", "c", Stage.VERIFY, [
        CheckResult("c1", Verdict.PASS), CheckResult("c2", Verdict.INCONCLUSIVE)]).validate()
    ok(v3.verdict == Verdict.INCONCLUSIVE, "证据不足 => inconclusive 不是通过")
    v4 = Verification("v4", "c", Stage.VERIFY, []).validate()
    ok(v4.verdict == Verdict.INCONCLUSIVE, "空检查 => inconclusive")

    j = LedgerJob("j1", Stage.CAPTURE, JobStatus.FAILED,
                  failure_code=FailureCode.CAPTURE_WRONG_SEGMENT).validate()
    ok(j.failure_code == FailureCode.CAPTURE_WRONG_SEGMENT, "错误码枚举通过")
    raises(lambda: LedgerJob("j", Stage.CAPTURE, failure_code="nope").validate(), "未知错误码被拒")


def test_registry():
    import tempfile
    import zipfile
    from pathlib import Path
    from . import registry as R

    ok(R.norm_sha1(" abcd ") == "ABCD", "norm_sha1 规范化大写去空白")

    plat, code, note = R.map_platform({"platform": "NES"}, None)
    ok(plat == R.Platform.NES, "map_platform NES")
    plat, _, _ = R.map_platform({"platform": "PSX"}, None)
    ok(plat == R.Platform.PS1, "map_platform PSX->PS1")
    plat, _, _ = R.map_platform({"platform": "Arcade", "emulator": "MAME 0.2"}, None)
    ok(plat == R.Platform.ARCADE_MAME, "map_platform Arcade+MAME")
    plat, _, _ = R.map_platform({"platform": "Arcade", "emulator": "FBNeo"}, None)
    ok(plat == R.Platform.ARCADE_FBNEO, "map_platform Arcade+FBNeo")
    plat, _, note = R.map_platform({"platform": "GBA"}, None)
    ok(plat is None and note, "map_platform 未建模平台返回 None+说明")

    d, note = R.emulator_match("BizHawk 2.8", {"2.8": "/x"})
    ok(d == "/x", "emulator_match 命中本地 BizHawk")
    d, note = R.emulator_match("BizHawk 2.9", {"2.8": "/x"})
    ok(d is None and note, "emulator_match 缺版本=>None+说明")
    d, note = R.emulator_match("FCEUX 2.2.3", {"2.8": "/x"})
    ok(d is None and "非 BizHawk" in note, "emulator_match 非 BizHawk 管线")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bk2 = td / "m.bk2"
        with zipfile.ZipFile(bk2, "w") as z:
            z.writestr("Header.txt",
                       "Platform NES\nSHA1 abcd1234\nCore NesHawk\nemuVersion Version 2.8\n")
            z.writestr("Input Log.txt", "x")
        h = R.read_bk2_header(bk2)
        ok(h and h["SHA1"] == "abcd1234" and h["Core"] == "NesHawk",
           "read_bk2_header 解析 .bk2")
        # .zip 外壳包裹内部 .bk2
        wrap = td / "m.zip"
        with zipfile.ZipFile(wrap, "w") as z:
            z.write(bk2, "inner.bk2")
        h2 = R.read_bk2_header(wrap)
        ok(h2 and h2["Platform"] == "NES", "read_bk2_header 解开 .zip 外壳")
        ok(R.read_bk2_header(td / "missing.bk2") is None, "read_bk2_header 非容器=>None")

        # resolve_movie：同名 .bk2 优先于 .zip
        (td / "movies").mkdir()
        outer = td / "movies" / "9.zip"
        outer.write_bytes(b"")
        inner_bk2 = td / "movies" / "9.bk2"
        inner_bk2.write_bytes(b"")
        path, note = R.resolve_movie({"local_movie": "movies/9.zip"}, td)
        ok(path == str(inner_bk2), "resolve_movie 优先已解压 .bk2")
        path, note = R.resolve_movie({"local_movie": "movies/none.bk2"}, td)
        ok(path is None and note, "resolve_movie 缺失=>None+说明")


def test_backends():
    from . import backends as B
    from .schema import CheckResult, Verdict, Stage

    # 不存在的 BizHawk 目录 => available False，能力不开放
    probe = B.BizHawkNESBackend(r"Z:\no_such_bizhawk").probe()
    ok(probe["available"] is False, "NES 探针：缺目录=>available False")
    ok(probe["capabilities"]["audio_capture"]["supported"] is False,
       "NES 探针：截图链路 audio_capture=False（如实报缺口）")
    ok(probe["capabilities"]["interactive_step"]["supported"] is False,
       "NES 探针：缺目录 interactive_step=False（转真需可用+实跑证据，见 test_statejump）")
    ok(probe["clock_unit"] == "emu_frame", "NES 探针：时钟单位 emu_frame")

    c = B._cap(True, "x")
    ok(c == {"supported": True, "evidence": "x"}, "_cap 结构")

    # 验收聚合：有 inconclusive => 整体 inconclusive（不是通过）
    v = B._verification("v", "subj", Stage.CAPTURE, [
        CheckResult("a", Verdict.PASS), CheckResult("b", Verdict.INCONCLUSIVE)])
    ok(v["verdict"] == "inconclusive", "后端验收：证据不足=>inconclusive")
    v2 = B._verification("v", "s", Stage.CAPTURE, [
        CheckResult("a", Verdict.PASS), CheckResult("b", Verdict.FAIL)])
    ok(v2["verdict"] == "fail", "后端验收：有 fail=>fail")

    # 招式记法采集前闸门：谱面排版符号(·/或)必须在采集前拦下，不浪费一次采集
    fb = B.FBNeoBackend()
    ready_bad, why_bad = fb.compile_check("→↓↘·A或C")
    ok(not ready_bad and bool(why_bad), f"招式闸门：谱面符号·/或 采集前拦下（{why_bad}）")
    ready_good, _ = fb.compile_check("→↓↘+A")
    ok(ready_good, "招式闸门：编译器记法 →↓↘+A 放行")


def test_detect_gamepack():
    import tempfile
    from pathlib import Path
    from PIL import Image
    from . import detect as D
    from . import gamepack as G
    from .schema import CheckSpec, Verdict

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        sky = td / "sky.png"
        Image.new("RGB", (64, 64), (193, 224, 254)).save(sky)
        black = td / "black.png"
        Image.new("RGB", (64, 64), (0, 0, 0)).save(black)

        spec = CheckSpec("c", "frame_color_fraction",
                         {"rgb": [193, 224, 254], "tol": 12, "min_fraction": 0.3})
        ok(D.run_check(spec, sky).verdict == Verdict.PASS, "检测：天空帧=>pass")
        ok(D.run_check(spec, black).verdict == Verdict.FAIL, "检测：黑帧=>fail")
        unk = D.run_check(CheckSpec("c", "no_such_plugin"), sky)
        ok(unk.verdict == Verdict.INCONCLUSIVE, "检测：未注册插件=>inconclusive 不静默通过")

        pack = {"game_revision_id": "g", "frames": {"pos": str(sky), "neg": str(black)},
                "elements": [{"element_id": "e", "kind": "scene", "positive_frame": "pos",
                              "success_checks": [{"check_id": "c", "plugin_id": "frame_color_fraction",
                                                  "params": {"rgb": [193, 224, 254], "min_fraction": 0.3}}],
                              "negative_cases": [{"case_id": "n", "frame": "neg"}]}]}
        r = G.run_element(pack, pack["elements"][0])
        ok(r["verification"]["verdict"] == "pass", "游戏包：正例过+负例拒=>pass")

        # 坏检测器：负例也用天空帧（应被误放）=> 整包必须 FAIL
        bad = dict(pack)
        bad["frames"] = {"pos": str(sky), "neg": str(sky)}
        rb = G.run_element(bad, pack["elements"][0])
        ok(rb["verification"]["verdict"] == "fail", "游戏包：负例被误放=>fail（闸门有效）")


def test_clipper():
    from . import clipper as C
    from . import detect as D
    from .schema import CheckSpec, CheckResult, Verdict

    spec = CheckSpec("sky", "frame_color_fraction", {"rgb": [193, 224, 254]})
    orig_nb, orig_ex, orig_run = C._nb_frames, C._extract_frame, D.run_check
    try:
        C._extract_frame = lambda clip, n, png, ffmpeg="ffmpeg": png
        # 帧数对 + 检测过 => pass
        C._nb_frames = lambda clip, ffprobe="ffprobe": 60
        D.run_check = lambda s, p: CheckResult(s.check_id, Verdict.PASS)
        ck = C.verify_clip("x.mp4", 60, [spec], ".")
        ok(ck[0].verdict == Verdict.PASS and ck[1].verdict == Verdict.PASS,
           "切片：帧数对+目标在=>pass")
        # 帧数错 => clip_frames FAIL（重采样/错段）
        C._nb_frames = lambda clip, ffprobe="ffprobe": 50
        ck = C.verify_clip("x.mp4", 60, [spec], ".")
        ok(ck[0].verdict == Verdict.FAIL, "切片：帧数不符=>fail")
        # 帧数对但检测不到目标（错段）=> FAIL
        C._nb_frames = lambda clip, ffprobe="ffprobe": 60
        D.run_check = lambda s, p: CheckResult(s.check_id, Verdict.FAIL)
        ck = C.verify_clip("x.mp4", 60, [spec], ".")
        ok(ck[1].verdict == Verdict.FAIL, "切片：错段检测不到目标=>fail")
    finally:
        C._nb_frames, C._extract_frame, D.run_check = orig_nb, orig_ex, orig_run


def test_audio():
    import tempfile
    import wave
    import numpy as np
    from pathlib import Path
    from . import audio as A

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rate = 48000
        # 前 0.2s 静音 + 之后 0.3s 正弦 => onset≈0.2, max_db 明显 > -60
        t = np.arange(int(rate * 0.5)) / rate
        sig = np.where(t < 0.2, 0.0, 0.5 * np.sin(2 * np.pi * 440 * t))
        pcm = (sig * 32767).astype(np.int16)
        wav = td / "tone.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            w.writeframes(pcm.tobytes())
        db = A.max_db(wav)
        ok(db is not None and db > -20, f"音频：有原声 max_db={db} > -20")
        on = A.onset_sec(wav)
        ok(on is not None and abs(on - 0.2) < 0.05, f"音频：onset={on}≈0.2s")
        # 立体声回归：交错采样时间基须按 rate*channels，旧 bug 会把 onset 翻倍成 0.4s
        st = np.repeat(pcm, 2)  # L/R 交错
        swav = td / "stereo.wav"
        with wave.open(str(swav), "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate)
            w.writeframes(st.tobytes())
        son = A.onset_sec(swav)
        ok(son is not None and abs(son - 0.2) < 0.05, f"音频：立体声 onset={son}≈0.2s（不翻倍）")
        # 全静音 => max_db≈-91, onset None
        sil = td / "sil.wav"
        with wave.open(str(sil), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            w.writeframes(np.zeros(rate // 2, dtype=np.int16).tobytes())
        ok(A.max_db(sil) <= -90, "音频：全静音 max_db<=-90")
        ok(A.onset_sec(sil) is None, "音频：全静音 onset=None")
        # 界尾闸门：录音停止晚于末帧的尾巴必须被 -t 界掉，否则时长闸误报
        tail_sig = np.concatenate([
            np.zeros(int(rate * 0.2)),
            0.5 * np.sin(2 * np.pi * 440 * np.arange(int(rate * 1.3)) / rate)])
        lwav = td / "long.wav"
        with wave.open(str(lwav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
            w.writeframes((tail_sig * 32767).astype(np.int16).tobytes())
        bounded = td / "bound.wav"
        A.trim_span(lwav, 0.2, 0.5, bounded)
        ok(abs(A.wav_duration(bounded) - 0.5) < 0.02,
           f"音频：trim_span 界尾后时长≈span（{A.wav_duration(bounded):.3f}s≈0.5s）")
        unbounded = td / "unbound.wav"
        A.trim_span(lwav, 0.2, None, unbounded)
        ok(A.wav_duration(unbounded) > 1.0,
           f"音频：反证 span=None 保留尾巴（{A.wav_duration(unbounded):.3f}s>1s），界尾非默认")


def test_ledger():
    import tempfile
    from pathlib import Path
    from .ledger import Ledger, fingerprint
    from .schema import asset

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        led = Ledger(td / "ledger.json")
        art = td / "out.mp4"
        art.write_bytes(b"fake-video-v1")
        fp = fingerprint([art], {"frames": 120})

        # 登记只记元数据，不触发生产、不带产物
        j1 = led.register(Stage.CAPTURE, "capture", fp)
        ok(led.entries[-1]["status"] == "pending" and not led.entries[-1]["artifact_refs"],
           "台账：register 只记元数据(pending/无产物)")
        ok(led.reusable(Stage.CAPTURE, "capture", fp) is None, "台账：pending 不可复用")

        # 成功必须对应实际存在、可校验的产物
        led.complete(j1, [art], Verdict.INCONCLUSIVE)
        ok(led.entries[-1]["status"] == "done", "台账：complete 校验产物后 done")
        ok(led.reusable(Stage.CAPTURE, "capture", fp) is not None,
           "台账：done+指纹+产物校验 => 可复用(inconclusive 不强制重跑)")
        ok(led.reusable(Stage.CAPTURE, "capture", fp + "x") is None,
           "台账：指纹变 => 不复用")

        # 旧/损坏文件不能冒充新产物
        art.write_bytes(b"corrupted")
        ok(led.reusable(Stage.CAPTURE, "capture", fp) is None,
           "台账：产物 sha256 不符 => 不复用(旧文件不冒充新产物)")
        art.write_bytes(b"fake-video-v1")   # 还原
        # 产物缺失 => 不复用（中断后只补缺失阶段）
        art.unlink()
        ok(led.reusable(Stage.CAPTURE, "capture", fp) is None, "台账：产物缺失 => 不复用")
        art.write_bytes(b"fake-video-v1")

        # complete 指向不存在产物 => 记 fail，不假 done
        j2 = led.register(Stage.EXPORT, "export", fp)
        led.complete(j2, [td / "missing.mp4"], Verdict.PASS)
        ok(led.entries[-1]["status"] == "failed", "台账：complete 产物缺失 => fail 不假 done")

        # 失败现场保留：fail 后重跑是新 attempt，旧 failed 不被覆盖
        j3 = led.register(Stage.CUT, "cut", fp)
        led.fail(j3, FailureCode.CAPTURE_WRONG_SEGMENT, "boom")
        j4 = led.register(Stage.CUT, "cut", fp)
        ok(led.attempt_no(Stage.CUT, "cut") == 3 and j4.endswith("a2"),
           "台账：fail 后重跑 attempt+1")
        cut_entries = [e for e in led.entries if e["stage"] == "cut"]
        ok(cut_entries[0]["status"] == "failed" and cut_entries[0]["failure_code"] == "capture_wrong_segment",
           "台账：旧失败现场保留不覆盖")

        # 已通过条目直接计数（不用总数减失败倒推）
        s = led.summary()
        ok(s["attempts"] == len(led.entries), "台账：summary attempts=历史条数")
        ok(s["failed"] >= 1 and s["done"] >= 1, "台账：summary 逐条直接计数 done/failed")


def test_region_plugin():
    import tempfile
    from pathlib import Path
    from PIL import Image
    from . import detect as D
    from . import gamepack as G
    from .schema import CheckSpec, Verdict

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # 顶部 13% 绿血条 + 其余黑：模拟 KOF 战斗 HUD 帧
        pos = td / "hud_pos.png"
        im = Image.new("RGB", (64, 64), (0, 0, 0))
        for y in range(int(64 * 0.13)):
            for x in range(64):
                im.putpixel((x, y), (71, 230, 0))
        im.save(pos)
        neg = td / "intro_neg.png"
        Image.new("RGB", (64, 64), (10, 10, 10)).save(neg)

        spec = CheckSpec("hud", "frame_region_color_fraction",
                         {"rgb": [71, 230, 0], "tol": 40,
                          "region": [0, 0, 1, 0.13], "min_fraction": 0.5})
        ok(D.run_check(spec, pos).verdict == Verdict.PASS, "区域插件：顶部绿血条 => pass")
        ok(D.run_check(spec, neg).verdict == Verdict.FAIL, "区域插件：无血条片头 => fail")
        # 整帧口径会稀释（绿只占 13%），区域口径才判得准
        whole = CheckSpec("h", "frame_region_color_fraction",
                          {"rgb": [71, 230, 0], "tol": 40, "min_fraction": 0.5})
        ok(D.run_check(whole, pos).verdict == Verdict.FAIL,
           "区域插件：省略 region 走整帧，绿占比被稀释 => fail")
        bad = CheckSpec("h", "frame_region_color_fraction",
                        {"rgb": [71, 230, 0], "region": [0, 0, 2, 1]})
        ok(D.run_check(bad, pos).verdict == Verdict.INCONCLUSIVE,
           "区域插件：region 越界 => inconclusive 不静默通过")
        bad2 = CheckSpec("h", "frame_region_color_fraction",
                         {"rgb": [71, 230, 0], "region": [0, 0, 1]})
        ok(D.run_check(bad2, pos).verdict == Verdict.INCONCLUSIVE,
           "区域插件：region 长度非法 => inconclusive")

        # 公共管线不重写：同一 gamepack 跑第二款游戏（合成 fixture），正例过+负例拒
        pack = {"game_revision_id": "kof98eck", "frames": {"pos": str(pos), "neg": str(neg)},
                "elements": [{"element_id": "kof98_fight_hud", "kind": "scene",
                              "positive_frame": "pos",
                              "success_checks": [{"check_id": "hud", "plugin_id": "frame_region_color_fraction",
                                                  "params": {"rgb": [71, 230, 0], "tol": 40,
                                                             "region": [0, 0, 1, 0.13], "min_fraction": 0.5}}],
                              "negative_cases": [{"case_id": "intro", "frame": "neg"}]}]}
        r = G.run_element(pack, pack["elements"][0])
        ok(r["verification"]["verdict"] == "pass", "M9：第二款游戏包走同一 gamepack => 正例过+负例拒")


def test_search():
    import tempfile
    from pathlib import Path
    from . import search as S
    from . import detect as D
    from .ledger import Ledger
    from .schema import CheckSpec, Verdict, Stage, FailureCode

    # ---- 受控数值插件：缺证据/未注册 => inconclusive，不静默通过 ----
    spec = CheckSpec("hit", "metric_min", {"key": "damage", "min": 0.01})
    ok(D.run_metric_check(spec, {"damage": 0.12}).verdict == Verdict.PASS,
       "搜索判分：damage>=min => pass")
    ok(D.run_metric_check(spec, {"damage": 0.0}).verdict == Verdict.FAIL,
       "搜索判分：damage<min => fail")
    ok(D.run_metric_check(spec, {}).verdict == Verdict.INCONCLUSIVE,
       "搜索判分：缺观察量 => inconclusive 不是通过")
    ok(D.run_metric_check(CheckSpec("x", "no_such_metric"), {"damage": 1}).verdict
       == Verdict.INCONCLUSIVE, "搜索判分：未注册插件 => inconclusive")

    checks = [spec]

    # ---- 能力闸门：不合格不开放给搜索，evaluate 不被调用 ----
    class UnsupportedEnv(S.SearchEnv):
        def search_capability(self):
            return {"supported": False, "evidence": "未接线"}

        def evaluate(self, params):
            raise AssertionError("不合格能力不应被调用 evaluate")

    r = S.run_search(UnsupportedEnv(), S.CandidateSpace(seed={"approach": 0}),
                     checks, S.SearchBudget(4))
    ok(r.failure_code == FailureCode.UNSUPPORTED_CAPABILITY and r.solution is None,
       "搜索：能力不合格 => UNSUPPORTED_CAPABILITY，不评估")

    # ---- 修复人为扰动的已知动作：seed(远距空放)先试，搜索走近帧数命中 ----
    env = S.ModelMoveEnv(approach_window=(60, 150))
    space = S.CandidateSpace(axes=[("approach", [0, 30, 60, 90, 120, 150])],
                             seed={"approach": 0, "dir_frames": 2})
    r = S.run_search(env, space, checks, S.SearchBudget(8))
    ok(r.verdict == Verdict.PASS and r.solution is not None, "搜索：修复扰动 => pass 有解")
    ok(r.solution["params"]["approach"] == 60, "搜索：命中窗口内 approach=60")
    ok(r.solution["replay_reproduced"] is True, "搜索：解可复播（复播复现）")
    ok(r.attempts[0]["params"]["approach"] == 0, "搜索：先尝试原动作 seed")
    ok(r.candidates_tried == 3, "搜索：seed+30+60 共 3 个候选命中")
    ok(r.timing["evals"] >= 3 and "total_sec" in r.timing, "搜索：吞吐被测量")

    # ---- 超预算正确退出：SEARCH_BUDGET_EXHAUSTED，不是证明无解 ----
    env2 = S.ModelMoveEnv(approach_window=(900, 999))
    r2 = S.run_search(env2, space, checks, S.SearchBudget(2))
    ok(r2.failure_code == FailureCode.SEARCH_BUDGET_EXHAUSTED and r2.solution is None,
       "搜索：超预算 => SEARCH_BUDGET_EXHAUSTED 无解")
    ok(r2.verdict == Verdict.INCONCLUSIVE and r2.candidates_tried == 2,
       "搜索：超预算 verdict=inconclusive，按预算停下")
    ok("不是证明无解" in r2.reason, "搜索：超预算明确不是证明无解")

    # ---- 命中但复播不复现 => 非确定性，不冒充解 ----
    class FlakyEnv(S.SearchEnv):
        start_ref = "model://flaky"

        def search_capability(self):
            return {"supported": True, "evidence": "test"}

        def evaluate(self, params):
            return S.Observation(metrics={"damage": 0.12}, input_ref="x")

        def replay(self, params):
            return S.Observation(metrics={"damage": 0.0}, input_ref="x")

    r3 = S.run_search(FlakyEnv(), S.CandidateSpace(seed={"approach": 0}),
                      checks, S.SearchBudget(4))
    ok(r3.failure_code == FailureCode.NONDETERMINISM and r3.solution is None,
       "搜索：复播不复现 => NONDETERMINISM，不冒充解")

    # ---- 受控判分：即使命中，未注册插件也不放行 ----
    env4 = S.ModelMoveEnv(approach_window=(0, 999))
    r4 = S.run_search(env4, S.CandidateSpace(seed={"approach": 0}),
                      [CheckSpec("h", "no_such_plugin")], S.SearchBudget(3))
    ok(r4.verdict != Verdict.PASS and r4.solution is None,
       "搜索：未注册插件命中也不放行（受控）")

    # ---- 台账 GENERATE 集成：成功 done / 超预算 failed，历史保留 ----
    with tempfile.TemporaryDirectory() as td:
        led = Ledger(Path(td) / "ledger.json")
        env5 = S.ModelMoveEnv(approach_window=(60, 150))
        rp = S.run_search(env5, space, checks, S.SearchBudget(8), ledger=led,
                          key="repair", fingerprint="fp-repair")
        ok(rp.verdict == Verdict.PASS, "搜索台账：修复 pass")
        e = led._latest(Stage.GENERATE, "repair")
        ok(e["status"] == "done" and e["artifact_refs"], "搜索台账：GENERATE done 带可校验产物")
        ok(any(a["uri"].endswith(".solution.json") for a in e["artifact_refs"]),
           "搜索台账：解写成 solution.json 产物")
        env6 = S.ModelMoveEnv(approach_window=(900, 999))
        S.run_search(env6, space, checks, S.SearchBudget(2), ledger=led,
                     key="exhaust", fingerprint="fp-exhaust")
        e2 = led._latest(Stage.GENERATE, "exhaust")
        ok(e2["status"] == "failed" and e2["failure_code"] == "search_budget_exhausted",
           "搜索台账：超预算记 SEARCH_BUDGET_EXHAUSTED")
        s = led.summary()
        ok(s["done"] >= 1 and s["failed"] >= 1, "搜索台账：done/failed 逐条直接计数")


def test_sync():
    import tempfile
    import zipfile
    import numpy as np
    from pathlib import Path
    from . import audio as A
    from .schema import Verdict

    with tempfile.TemporaryDirectory() as td:
        bk2 = Path(td) / "m.bk2"
        with zipfile.ZipFile(bk2, "w") as z:
            z.writestr("Input Log.txt",
                       "[Input]\nLogKey:#Power|Reset|#P1 Up|P1 Down|P1 Left|P1 Right|"
                       "P1 Start|P1 Select|P1 B|P1 A|\n"
                       "|..|........|\n|..|........|\n|..|.......A|\n"
                       "|..|.......A|\n|..|........|\n|..|......B.|\n")
        ok(A.press_frames(bk2) == [2, 5], "同步：LogKey 列位解析+按下沿（按住不算沿）")
        ok(A.press_frames(bk2, buttons=("P1 A",)) == [2], "同步：单键过滤")

    rate, fps = 48000, 60.0
    frames = list(range(60, 60 * 60, 30))   # ~118 个按键，超过 30 样本门槛
    pcm = np.zeros(rate * 64, dtype=np.float32)
    rng = np.random.default_rng(7)
    for f in frames:
        s = int(f / fps * rate)
        pcm[s:s + 240] = rng.standard_normal(240).astype(np.float32) * 0.5
    v, reason = A.judge_sync(A.sync_deltas(pcm, rate, frames, fps))
    ok(v == Verdict.PASS, f"同步：合成点击对准 => pass（{reason}）")
    # 反证格：整体迟 120ms（在搜索窗内、越容差）=> 必须 fail
    shifted = np.zeros_like(pcm)
    off = int(0.12 * rate)
    shifted[off:] = pcm[:-off]
    ok(A.judge_sync(A.sync_deltas(shifted, rate, frames, fps))[0] == Verdict.FAIL,
       "同步：音轨整体迟 120ms => fail（恒量反证）")
    # 反证格：线性漂移 0→140ms（整体中位仍在容差内）=> 三段漂移必须抓住
    drifted = np.zeros_like(pcm)
    for f in frames:
        s = int((f / fps + f / 3600.0 * 0.14) * rate)
        drifted[s:s + 240] = rng.standard_normal(240).astype(np.float32) * 0.5
    ok(A.judge_sync(A.sync_deltas(drifted, rate, frames, fps))[0] == Verdict.FAIL,
       "同步：累积漂移 => fail（三段检查抓住）")
    ok(A.judge_sync(A.sync_deltas(np.zeros_like(pcm), rate, frames, fps))[0]
       == Verdict.INCONCLUSIVE, "同步：无瞬态 => inconclusive 不冒充")
    ok(A.judge_sync([(1, 0.01)] * 10)[0] == Verdict.INCONCLUSIVE,
       "同步：有效样本<30 => inconclusive")


def test_warp_sync():
    """逐帧 mtime 锚点重采样 + 产物级同步闸门：合成非线性时钟，正例对齐 + 四条反证格。"""
    import os
    import wave
    import tempfile
    import numpy as np
    from pathlib import Path
    from . import audio as A
    from .schema import Verdict

    rate, fps, n = 48000, 60.0, 600
    # 非线性墙钟：瞬时速率 1±0.3 正弦起伏，单 atempo 中段残差必越 50ms（warp 才有必要）
    mt = [1000.0]
    for i in range(1, n):
        mt.append(mt[-1] + (1.0 / fps) * (1 + 0.3 * np.sin(2 * np.pi * i / n)))
    span = mt[-1] - mt[0]
    resid = A.clock_residual(mt, fps)
    ok(float(np.abs(resid).max()) > 0.05, "warp：非线性时钟残差>50ms（单 atempo 校不准）")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        fdir = td / "frames"
        fdir.mkdir()
        for i in range(n):
            p = fdir / f"f{i:04d}.png"
            p.write_bytes(b"")
            os.utime(p, (mt[i], mt[i]))

        def write_clicks(path, walls):
            pcm = np.zeros(int((span + 1.0) * rate), dtype=np.float32)
            rng = np.random.default_rng(11)
            for w in walls:
                s = int((w - mt[0]) * rate)
                pcm[s:s + 2400] = rng.standard_normal(2400).astype(np.float32) * 0.5
            with wave.open(str(path), "wb") as wv:
                wv.setnchannels(1)
                wv.setsampwidth(2)
                wv.setframerate(rate)
                wv.writeframes(np.clip(pcm * 32767, -32768, 32767).astype("<i2").tobytes())

        # 6 个静音->有声锚点，墙钟均匀散布在整片（查中段漂移，不止起点）
        walls = [mt[0] + span * f for f in (0.08, 0.24, 0.42, 0.6, 0.78, 0.93)]
        ref = td / "ref.wav"
        write_clicks(ref, walls)
        synced = td / "sync.wav"
        A.warp_to_frames(ref, mt, fps, mt[0], synced)
        ok(abs(A.wav_duration(synced) - n / fps) < 0.02, "warp：校正后时长==帧时间轴长")
        chk = A.verify_frame_sync(str(fdir), mt, str(synced), str(ref), mt[0], fps)
        ok(chk.verdict == Verdict.PASS, f"warp：正例对齐 => pass（{chk.reason}）")

        # 反证格1：用错/过期曲线（mt_used 与现场帧 mtime 不符）=> fail
        bad = A.verify_frame_sync(str(fdir), [t + 0.5 for t in mt], str(synced),
                                  str(ref), mt[0], fps)
        ok(bad.verdict == Verdict.FAIL, "warp：锚点与现场帧不符 => fail（防用错曲线）")

        # 反证格2：warp 起点偏 200ms（src_zero_wall 错）=> 声锚整体位移越 ±50ms => fail
        mis = td / "mis.wav"
        A.warp_to_frames(ref, mt, fps, mt[0] + 0.2, mis)
        b2 = A.verify_frame_sync(str(fdir), mt, str(mis), str(ref), mt[0], fps)
        ok(b2.verdict == Verdict.FAIL, "warp：起点偏 200ms => fail（多锚点抓住位移）")

        # 反证格3：现场帧目录被清 => 无法复核 => inconclusive（不冒充通过）
        b3 = A.verify_frame_sync(str(td / "nope"), mt, str(synced), str(ref), mt[0], fps)
        ok(b3.verdict == Verdict.INCONCLUSIVE, "warp：帧目录缺失 => inconclusive")

        # 反证格4：只有 1 个声锚 => 查不了中段漂移 => inconclusive
        ref1 = td / "ref1.wav"
        write_clicks(ref1, [mt[0] + span * 0.5])
        syn1 = td / "syn1.wav"
        A.warp_to_frames(ref1, mt, fps, mt[0], syn1)
        b4 = A.verify_frame_sync(str(fdir), mt, str(syn1), str(ref1), mt[0], fps)
        ok(b4.verdict == Verdict.INCONCLUSIVE, "warp：声锚<3 => inconclusive")


def test_m10_probes():
    import tempfile
    from pathlib import Path
    from . import backends as B

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # PS1 资源齐备夹具：前端 + 核心 dll + 真实 BIOS + 游戏镜像
        bh = td / "BizHawk-2.11.1"
        (bh / "dll").mkdir(parents=True)
        (bh / "EmuHawk.exe").write_bytes(b"MZ")
        (bh / "dll" / "octoshock.dll").write_bytes(b"MZ")
        bios = td / "bios"
        bios.mkdir()
        (bios / "scph5501.bin").write_bytes(b"\x00" * 16)
        gamedir = td / "games"
        gamedir.mkdir()
        (gamedir / "game.cue").write_text('FILE "game.bin" BINARY\n')
        (gamedir / "game.bin").write_bytes(b"\x00" * 16)

        full = B.BizHawkPS1Backend(bizhawk_dir=str(bh), bios_dirs=[str(bios)],
                                   game_dirs=[str(gamedir)]).probe()
        ok(full["available"] is True, "M10 PS1：前端+核心+BIOS+游戏齐 => available True")
        ok(full["resources"]["bios_present"] and full["resources"]["game_present"],
           "M10 PS1：BIOS/游戏检出")
        ok(all(c["supported"] is False for c in full["capabilities"].values()),
           "M10 PS1：资源齐但管线未接线 => 能力全 False（不冒充已验证）")

        # 缺资源夹具（空目录）=> 如实列 4 项缺失
        empty = td / "empty"
        empty.mkdir()
        miss = B.BizHawkPS1Backend(bizhawk_dir=str(empty), bios_dirs=[str(empty)],
                                   game_dirs=[str(empty)]).probe()
        ok(miss["available"] is False, "M10 PS1：缺资源 => available False")
        ok(len(miss["missing"]) == 4, "M10 PS1：如实列 4 项缺失（前端/核心/BIOS/游戏）")
        ok(any("BIOS" in m for m in miss["missing"]),
           "M10 PS1：缺失含 BIOS（Octoshock 无 HLE，必须）")

        # 仅缺 BIOS（有前端/核心/游戏）=> 仍 blocked
        nobios = td / "nobios"
        nobios.mkdir()
        nb = B.BizHawkPS1Backend(bizhawk_dir=str(bh), bios_dirs=[str(nobios)],
                                 game_dirs=[str(gamedir)]).probe()
        ok(nb["available"] is False and nb["resources"]["bios_present"] is False,
           "M10 PS1：仅缺 BIOS 也 => blocked（必须真实 BIOS）")

        # PSP 资源齐（无固件，HLE 可选非阻塞）
        pspexe = td / "PPSSPPWindows64.exe"
        pspexe.write_bytes(b"MZ")
        pspgame = td / "pspgames"
        pspgame.mkdir()
        (pspgame / "game.iso").write_bytes(b"\x00" * 16)
        fwdir = td / "fw_empty"
        fwdir.mkdir()
        pfull = B.PPSSPPBackend(exe=str(pspexe), game_dirs=[str(pspgame)],
                                firmware_dir=str(fwdir)).probe()
        ok(pfull["available"] is True, "M10 PSP：exe+游戏齐 => available True")
        ok(pfull["resources"]["firmware_present"] is False, "M10 PSP：无 flash0 => 固件 False")
        ok(not any("固件" in m or "flash0" in m for m in pfull["missing"]),
           "M10 PSP：固件可选，缺固件不列入阻塞缺失（HLE 替代）")
        ok(all(c["supported"] is False for c in pfull["capabilities"].values()),
           "M10 PSP：管线未接线 => 能力全 False")

        # PSP 缺构建 exe（仅源码）=> blocked
        pmiss = B.PPSSPPBackend(exe=str(td / "no_such.exe"), game_dirs=[str(pspgame)],
                                firmware_dir=str(fwdir)).probe()
        ok(pmiss["available"] is False, "M10 PSP：无构建 exe => available False")
        ok(any("PPSSPP" in m for m in pmiss["missing"]),
           "M10 PSP：缺失含已构建 PPSSPP（当前仅克隆源码）")

        # 诚实运行：缺资源 => MISSING_RESOURCE，绝不 PASS、不产出成片
        out = td / "out"
        r1 = B.BizHawkPS1Backend(bizhawk_dir=str(empty), bios_dirs=[str(empty)],
                                 game_dirs=[str(empty)]).run_batch("ps1", str(out))
        ok(r1["verification"]["verdict"] == "fail", "M10 运行：缺资源 => fail（不伪装成功）")
        ok(r1["failure"]["code"] == "missing_resource", "M10 运行：错误码 MISSING_RESOURCE")
        ok(r1["recording_refs"] == [], "M10 运行：缺资源不产出成片")
        # 资源齐但管线未接线 => UNSUPPORTED_CAPABILITY（仍不 PASS）
        r2 = B.BizHawkPS1Backend(bizhawk_dir=str(bh), bios_dirs=[str(bios)],
                                 game_dirs=[str(gamedir)]).run_batch("ps1", str(out))
        ok(r2["failure"]["code"] == "unsupported_capability",
           "M10 运行：资源齐但管线未接线 => UNSUPPORTED_CAPABILITY")
        ok(r2["verification"]["verdict"] == "fail", "M10 运行：未接线 => fail 不冒充通过")

    # 真机不变量（与资源无关）：采集能力恒未接线；available 与 missing 一致
    for be in (B.BizHawkPS1Backend(), B.PPSSPPBackend()):
        pr = be.probe()
        ok(all(c["supported"] is False for c in pr["capabilities"].values()),
           f"M10 真机 {be.backend_id}：采集能力恒未接线 supported=False")
        ok(pr["available"] is False or pr["missing"] == [],
           f"M10 真机 {be.backend_id}：available 与 missing 一致")


def test_replay_unwrap_mux():
    import io
    import subprocess
    import tempfile
    import wave
    import zipfile
    import numpy as np
    from pathlib import Path
    from PIL import Image
    import tas_replay
    from . import record as R

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        # 外壳 zip 套真 .bk2（TASVideos 下载形态）=> 解包后 BizHawk 才认 Header
        real = io.BytesIO()
        with zipfile.ZipFile(real, "w") as z:
            z.writestr("Header.txt", "MovieVersion BizHawk v2.0\nPlatform NES\n")
            z.writestr("Input Log.txt", "|0|........||\n")
        wrap = io.BytesIO()
        with zipfile.ZipFile(wrap, "w") as z:
            z.writestr("author-game.bk2", real.getvalue())
        src = td / "4751.bk2"; src.write_bytes(wrap.getvalue())
        dst = td / "movie.bk2"
        ok(tas_replay.materialize_movie(str(src), str(dst)) is True,
           "T1 外壳zip=>解出内部bk2")
        with zipfile.ZipFile(dst) as z:
            ok("Header.txt" in z.namelist(), "T1 解包后顶层含Header.txt(BizHawk可加载)")
        src2 = td / "real.bk2"; src2.write_bytes(real.getvalue())
        dst2 = td / "movie2.bk2"
        ok(tas_replay.materialize_movie(str(src2), str(dst2)) is False,
           "T1 真bk2原样拷贝不解包")
        src3 = td / "x.fm2"; src3.write_bytes(b"version 1\n")
        dst3 = td / "movie3.fm2"
        ok(tas_replay.materialize_movie(str(src3), str(dst3)) is False
           and dst3.read_bytes() == src3.read_bytes(), "T1 非zip(fm2)原样拷贝")

        # 音轨比视频短时 mux 不得截视频帧（apad）；反证格证明夹具真能触发截帧
        n, fps = 12, 60
        fdir = td / "frames"; fdir.mkdir()
        for i in range(n):
            Image.new("RGB", (64, 64), (i * 20 % 255, 40, 80)).save(fdir / f"f{i:04d}.png")
        video = str(td / "v.mp4")
        tas_replay.encode_video(str(fdir), fps, video)
        wav = str(td / "a.wav")
        sr = 44100
        with wave.open(wav, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
            w.writeframes((np.sin(np.arange(int(sr * 0.15)) / 8) * 20000).astype("<i2").tobytes())
        out = str(td / "av.mp4")
        R.mux_av(video, wav, out)

        def nbframes(p):
            r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=nb_frames", "-of",
                                "default=noprint_wrappers=1:nokey=1", p],
                               capture_output=True, text=True)
            return int(r.stdout.strip())

        ok(nbframes(out) == n, "T1 apad mux 保留全部视频帧(音轨短不截视频)")
        old = str(td / "old.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", wav,
                        "-c:v", "copy", "-c:a", "aac", "-shortest", old],
                       check=True, capture_output=True)
        ok(nbframes(old) < n, "T1 反证:无apad的-shortest确实截帧(夹具有效)")


def test_bizhawk29_compat():
    """回归：BizHawk 2.9+ 启动卡死修复（11-10 矩阵实证）。
    force_core 须按目录版本补写 LastWrittenFrom，消掉 'Mismatched version' 框；
    DIALOG_TITLES 须认得 'privileged' 框（Administrator 运行必弹，无 config 抑制键）。"""
    import json
    import tempfile
    from pathlib import Path
    import tas_replay
    from . import watchdog as WD

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bh29 = td / "BizHawk-2.9"; bh29.mkdir()
        tas_replay.force_core(str(bh29), "NES", "NesHawk")
        conf = json.loads((bh29 / "config.ini").read_text(encoding="utf-8"))
        ok(conf.get("LastWrittenFrom") == "2.9", "2.9 force_core 写 LastWrittenFrom=2.9")
        ok(conf.get("LastWrittenFromDetailed") == "Version 2.9", "2.9 写 Detailed=Version 2.9")
        ok(conf.get("PreferredCores", {}).get("NES") == "NesHawk", "2.9 仍强制 PreferredCores")
        ok(conf.get("FirstBoot") is False, "2.9 FirstBoot=False")
        # 合并保留已有键（不整本覆盖）
        (bh29 / "config.ini").write_text(
            json.dumps({"ExistingKey": 7, "PreferredCores": {"SNES": "Snes9x"}}),
            encoding="utf-8")
        tas_replay.force_core(str(bh29), "NES", "quickerNES")
        conf2 = json.loads((bh29 / "config.ini").read_text(encoding="utf-8"))
        ok(conf2.get("ExistingKey") == 7, "force_core 保留已有配置键")
        ok(conf2["PreferredCores"].get("SNES") == "Snes9x"
           and conf2["PreferredCores"].get("NES") == "quickerNES",
           "force_core 合并而非覆盖 PreferredCores")
        bh28 = td / "BizHawk-2.8"; bh28.mkdir()
        tas_replay.force_core(str(bh28), "NES", "NesHawk")
        ok(json.loads((bh28 / "config.ini").read_text(encoding="utf-8")).get("LastWrittenFrom") == "2.8",
           "2.8 目录写 2.8 标记(旧版同样安全)")
        other = td / "EmuDir"; other.mkdir()
        tas_replay.force_core(str(other), "NES", "NesHawk")
        ok("LastWrittenFrom" not in json.loads((other / "config.ini").read_text(encoding="utf-8")),
           "非BizHawk命名不臆造版本标记")

    def matches(title, titles):
        return any(t.lower() in title.lower() for t in titles)
    ok(matches("This EmuHawk is privileged", WD.DIALOG_TITLES), "DIALOG_TITLES 认得 privileged 框")
    ok(matches("Mismatched version in config file", WD.DIALOG_TITLES), "DIALOG_TITLES 认得 Mismatched version 框")
    ok("privileged" in WD.DIALOG_TITLES and "Mismatched version" in WD.DIALOG_TITLES,
       "回归锁:两个新标题在册")
    old_titles = ("Warning", "BizHawk", "Error", "Exception", "警告", "错误")
    ok(not matches("This EmuHawk is privileged", old_titles),
       "反证:旧标题表确实漏认 privileged(夹具能复现卡死)")

    # 主窗口误伤回归（11-10 热血足球2 启动间歇失败根因）：裸 "BizHawk" 子串会匹配
    # 主窗口标题 "{游戏} [NES] - BizHawk"，启动稍慢（首心跳 >5s）时看门狗对主窗口发
    # 回车/IDOK 打断 Lua 初始化。修复=去裸 BizHawk + _is_emuhawk_main_window 显式跳过。
    main_titles = ("Kunio-kun no Nekketsu Soccer League [NES] - BizHawk",
                   "Ninja Gaiden [NES] - BizHawk", "BizHawk")
    real_dialogs = ("Mismatched version in config file",
                    "This EmuHawk is privileged", "Warning", "Error")
    for t in main_titles:
        ok(WD._is_emuhawk_main_window(t), f"主窗口签名认得(点框须跳过): {t!r}")
        ok(not matches(t, WD.DIALOG_TITLES), f"修复后框表不再误匹配主窗口: {t!r}")
    for t in real_dialogs:
        ok(not WD._is_emuhawk_main_window(t), f"真框不被主窗口签名误吞: {t!r}")
        ok(matches(t, WD.DIALOG_TITLES), f"真框仍命中框表(须点掉): {t!r}")
    ok("BizHawk" not in WD.DIALOG_TITLES, "回归锁:裸 BizHawk 已从 DIALOG_TITLES 移除")
    ok(matches("Kunio-kun no Nekketsu Soccer League [NES] - BizHawk", old_titles),
       "反证:旧框表(含裸BizHawk)确实误匹配主窗口(夹具能复现误伤)")
    ok(not WD._is_emuhawk_main_window(""), "空标题不认作主窗口(chromeless 不可见,dismiss 本就不命中)")
    ok(not WD._is_emuhawk_main_window(None), "None 标题不崩")

    # 生产判定整条钉死（_should_dismiss = dismiss 循环实际调用的谓词）：
    # 可见 + 非主窗口 + 命中框表 才点；主窗口/不可见/无关窗口一律不点。
    ok(not WD._should_dismiss("Kunio-kun no Nekketsu Soccer League [NES] - BizHawk", True),
       "生产判定:可见主窗口不点(误伤根因已堵)")
    ok(not WD._should_dismiss("BizHawk", True), "生产判定:启动期裸 BizHawk 主窗口不点")
    ok(WD._should_dismiss("Mismatched version in config file", True), "生产判定:可见 Mismatched 框点掉")
    ok(WD._should_dismiss("This EmuHawk is privileged", True), "生产判定:可见 privileged 框点掉")
    ok(not WD._should_dismiss("Mismatched version in config file", False), "生产判定:不可见框不点(visibility 闸)")
    ok(not WD._should_dismiss("Lua Console", True), "生产判定:无关可见窗口(Lua Console)不点")
    ok(not WD._should_dismiss("", True), "生产判定:chromeless 空标题不点")

    def old_should(ti, vi):
        return vi and any(t.lower() in ti.lower() for t in old_titles)
    ok(old_should("Kunio-kun no Nekketsu Soccer League [NES] - BizHawk", True),
       "反证:旧口径(裸BizHawk+无主窗口跳过)确实判主窗口可点(夹具复现误伤)")


def test_fceux():
    import base64
    import hashlib
    import struct
    import tempfile
    import zipfile
    from pathlib import Path
    from . import fceux as F
    from . import registry as R

    # ---- A. fm2 解析：按钮序 RLDUTSBA→UDLRTSBA、命令、MD5 blob、作者 ----
    md5raw = bytes.fromhex("d9a1631d5c32d35594b9484862a26cba")
    b64 = "base64:" + base64.b64encode(md5raw).decode()
    fm2 = "\n".join([
        "version 3", "emuVersion 21040", "romFilename Test Game",
        f"romChecksum {b64}", "port0 1", "port1 0", "palFlag 0",
        "rerecordCount 5", "comment author TestAuthor",
        "|0|........|........|",      # 帧0 无命令
        "|1|........|........|",      # 帧1 reset
        "|2|R.......|........|",      # 帧2 power + Right(fm2 pos0)
        "|0|.......A|........|",      # 帧3 A(fm2 pos7)
        "|0|..DU....|........|",      # 帧4 Down+Up(fm2 pos2/3)
        "|0|....T...|........|",      # 帧5 Start(fm2 pos4)
    ]) + "\n"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        src = td / "t.fm2"; src.write_text(fm2, encoding="utf-8")
        m = F.parse_fm2(src)
        ok(m.n_frames == 6, "fceux：fm2 帧数==输入行数(含 lag 帧直转)")
        ok(m.md5 == md5raw.hex(), "fceux：romChecksum base64→16字节 hex")
        ok(F._decode_md5_blob("0x" + md5raw.hex()) == md5raw.hex(),
           "fceux：romChecksum 0x hex 口径也解析")
        ok(m.author == "TestAuthor" and m.port0 == 1 and m.port1 == 0,
           "fceux：作者/port0/port1 解析")
        ok(m.frames[1]["cmd"] == "reset" and m.frames[2]["cmd"] == "power",
           "fceux：命令 1→reset / 2→power")
        ok(m.frames[2]["p1"] == {"Right"} and m.frames[3]["p1"] == {"A"},
           "fceux：按钮位置映射 Right/A")
        ok(m.frames[4]["p1"] == {"Down", "Up"} and m.frames[5]["p1"] == {"Start"},
           "fceux：多键 Down+Up / Start")
        ok(F._render_player({"Right"}) == "...R...."
           and F._render_player({"Down", "Up"}) == "UD......",
           "fceux：bk2 渲染序 UDLRTSBA(R 在第4位/UD 在前两位)")

        # fm3 = zip 外壳包裹 fm2 文本
        wrap = td / "t.fm3"
        with zipfile.ZipFile(wrap, "w") as z:
            z.writestr("inner.fm2", fm2)
        ok(F.parse_movie(wrap).n_frames == 6, "fceux：fm3(zip 外壳)解出内部 fm2")

        # ---- B. _rom_md5 去 iNES 头（FCEUX GameInfo->MD5 口径，已修复的 bug）----
        payload = b"PRGCHRDATA-test"
        nes = td / "t.nes"
        nes.write_bytes(b"NES\x1a" + b"\x00" * 12 + payload)
        ok(F._rom_md5(nes) == hashlib.md5(payload).hexdigest(),
           "fceux：.nes 去 16 字节 iNES 头算 MD5(==fm2 romChecksum 口径)")
        ok(F._rom_md5(nes) != hashlib.md5(nes.read_bytes()).hexdigest(),
           "fceux：反证—去头 MD5 确实不同于整文件 MD5(夹具有效)")
        raw = td / "raw.bin"; raw.write_bytes(payload)
        ok(F._rom_md5(raw) == hashlib.md5(payload).hexdigest(),
           "fceux：非 iNES 文件对整文件算 MD5")

        # ---- C. to_bk2 结构 + LogKey 与真 BizHawk 一致 + 拒绝非法 ----
        out = td / "out.bk2"
        F.to_bk2(m, out, sha1="ABCD1234", game_name="Test Game", bizhawk_version="2.8")
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            ok(set(names) == {"Header.txt", "Input Log.txt", "SyncSettings.json", "Comments.txt"},
               "fceux：bk2 四件套齐")
            hdr = z.read("Header.txt").decode()
            ok("Platform NES" in hdr and "Core NesHawk" in hdr
               and "SHA1 ABCD1234" in hdr and f"MD5 {md5raw.hex()}" in hdr,
               "fceux：Header 含 Platform/Core/SHA1/MD5")
            log = z.read("Input Log.txt").decode().splitlines()
            ok(log[1] == ("LogKey:#Power|Reset|#P1 Up|P1 Down|P1 Left|P1 Right|"
                          "P1 Start|P1 Select|P1 B|P1 A|"),
               "fceux：LogKey 与真 BizHawk NesHawk 逐字一致")
            ok(log[4] == "|p.|...R....|", "fceux：power+Right 帧渲染 |p.|...R....|")
            ok(log[3] == "|.r|........|", "fceux：reset 帧渲染 |.r|")
            ss = z.read("SyncSettings.json").decode()
            ok('"NesLeftPort": "ControllerNES"' in ss
               and '"NesRightPort": "UnpluggedNES"' in ss,
               "fceux：SyncSettings 端口映射(port0=1/port1=0)")
        # 从存档起始 / fourscore => 拒绝转换
        bad = td / "bad.fm2"
        bad.write_text(fm2 + "startsFromSavestate 1\n", encoding="utf-8")
        mb = F.parse_fm2(bad)
        ok(bool(mb.errors), "fceux：StartsFromSavestate=1 记 error")
        try:
            F.to_bk2(mb, td / "bad.bk2"); ok(False, "fceux：应拒绝从存档起始")
        except F.ConversionError:
            ok(True, "fceux：to_bk2 拒绝从存档起始的电影")
        four = td / "four.fm2"
        four.write_text(fm2 + "fourscore 1\n", encoding="utf-8")
        try:
            F.to_bk2(F.parse_fm2(four), td / "four.bk2"); ok(False, "fceux：应拒绝 fourscore")
        except F.ConversionError:
            ok(True, "fceux：to_bk2 拒绝 fourscore(四手柄)")

        # ---- D. FCM 二进制 v2 解析（镜像 FcmImport 切换循环）----
        name = b"TestGame\x00"; author = b"Auth\x00"
        fmd5 = bytes.fromhex("00112233445566778899aabbccddeeff")
        pre = b"FCM\x1a" + struct.pack("<I", 2) + bytes([2]) + b"\x00\x00\x00"
        pre += struct.pack("<I", 3)          # frame_count
        pre += struct.pack("<I", 7)          # rerecord
        pre += struct.pack("<I", 0)          # savestate offset
        ff_pos = len(pre)
        pre += struct.pack("<I", 0)          # first_frame 占位
        pre += fmd5 + struct.pack("<I", 21040) + name + author
        first_frame = len(pre)
        pre = pre[:ff_pos] + struct.pack("<I", first_frame) + pre[ff_pos + 4:]
        fcm = td / "t.fcm"
        fcm.write_bytes(pre + bytes([0x00, 0x00, 0x01]))   # A on / A off / B on
        fm = F.parse_fcm(fcm)
        ok(fm.n_frames == 3 and fm.source_format == "fcm", "fceux：FCM v2 帧数/格式")
        ok(fm.frames[0]["p1"] == {"A"} and fm.frames[1]["p1"] == set()
           and fm.frames[2]["p1"] == {"B"}, "fceux：FCM 切换循环 A→空→B")
        ok(fm.md5 == fmd5.hex() and fm.game_name == "TestGame"
           and fm.author == "Auth" and fm.rerecord == 7,
           "fceux：FCM MD5/游戏名/作者/rerecord")

        # ---- E. convert_pub 生产路径：MD5 一致放行 / 错配拒绝（隔离 lib）----
        lib = td / "lib"; (lib / "movies" / "NES").mkdir(parents=True)
        (lib / "roms_verify" / "NES").mkdir(parents=True)
        rom = lib / "roms_verify" / "NES" / "game.nes"
        rom.write_bytes(b"NES\x1a" + b"\x00" * 12 + payload)   # 去头 MD5=md5(payload)
        good_md5 = "base64:" + base64.b64encode(hashlib.md5(payload).digest()).decode()
        sha1 = hashlib.sha1(rom.read_bytes()).hexdigest().upper()
        pub = {"id": "9999", "platform": "NES", "emulator": "FCEUX 2.2.3",
               "local_movie": "movies/NES/9999.fm2", "rom_sha1": sha1,
               "game": "Test Game", "version_id": "v9999"}
        (lib / "publications.json").write_text(
            __import__("json").dumps({"publications": {"9999": pub}}), encoding="utf-8")
        good_fm2 = fm2.replace(b64, good_md5)
        (lib / "movies" / "NES" / "9999.fm2").write_text(good_fm2, encoding="utf-8")
        res = F.convert_pub("9999", lib=lib)
        ok(res["md5_check"].startswith("pass") and Path(res["out"]).is_file(),
           "fceux：convert_pub MD5 一致=>pass 并写出 _converted bk2")
        # 错配：电影要另一个 MD5 => 拒绝（防 ROM 版本错配 desync）
        (lib / "movies" / "NES" / "9999.fm2").write_text(fm2, encoding="utf-8")
        try:
            F.convert_pub("9999", lib=lib); ok(False, "fceux：MD5 错配应拒绝")
        except F.ConversionError as e:
            ok("MD5 不符" in str(e), "fceux：convert_pub MD5 错配=>拒绝(防 desync)")
        (lib / "movies" / "NES" / "9999.fm2").write_text(good_fm2, encoding="utf-8")
        F.convert_pub("9999", lib=lib)   # 重建缓存供 F 段

        # ---- F. registry 接线：未转换阻塞→转换后可回放，路由本地 BizHawk ----
        mv, note = R.resolve_movie(pub, lib)
        ok(mv is not None and mv.endswith("9999.bk2"),
           "fceux接线：resolve_movie 命中 _converted 缓存")
        ed, en = R.emulator_match("FCEUX 2.2.3", {"2.8": "/x"})
        ok(ed is None and "非 BizHawk" in en and "taspipe.fceux" in en,
           "fceux接线：emulator_match FCEUX 提示转换且保留'非 BizHawk'")
        ri = R.index_roms(lib); bh = {"2.8": "/x"}
        r = R.assess(pub, lib, ri, {}, bh)
        ok(r["status"] == "replayable" and r["emulator_dir"] == "/x"
           and r["core"] == "NesHawk" and not r["blockers"],
           "fceux接线：assess 转换后 blocked→replayable 路由 BizHawk 2.8")
        ok(r["profile"]["backend_id"] == "nes_bizhawk",
           "fceux接线：profile backend=nes_bizhawk")
        # 未转换态：删缓存 => resolve_movie 给转换提示且 assess 阻塞
        Path(res["out"]).unlink()
        mv0, note0 = R.resolve_movie(pub, lib)
        ok(mv0 is None and "需先转换" in note0,
           "fceux接线：未转换=>resolve_movie None+转换提示")
        r0 = R.assess(pub, lib, ri, {}, bh)
        ok(r0["status"] == "blocked", "fceux接线：未转换=>assess blocked")


def _synthetic_nes_lib(td, game="Auto Test Game", pid="9999", rom_sha1=None):
    """隔离夹具：建一个只含一条 NES 出版物的 lib（真 bk2 + 真 ROM + publications.json）。
    不写任何真实状态；返回 (lib, pub, sha1, rom_path, bk2_path)。rom_sha1 可指定为不匹配值
    以测预筛/阻塞。BizHawk 目录由调用方 patch R.discover_bizhawk 注入（不依赖真机安装）。"""
    import hashlib
    import json
    import zipfile
    td = Path(td)
    lib = td / f"lib_{pid}"
    (lib / "movies" / "NES").mkdir(parents=True)
    (lib / "roms_verify" / "NES").mkdir(parents=True)
    rom_bytes = b"NES\x1a" + b"\x00" * 12 + f"ROMDATA-{pid}".encode()
    rom = lib / "roms_verify" / "NES" / "game.nes"
    rom.write_bytes(rom_bytes)
    sha1 = hashlib.sha1(rom_bytes).hexdigest().upper()
    bk2 = lib / "movies" / "NES" / f"{pid}.bk2"
    with zipfile.ZipFile(bk2, "w") as z:
        z.writestr("Header.txt",
                   f"Platform NES\nSHA1 {sha1}\nCore NesHawk\nemuVersion Version 2.8\n")
        z.writestr("Input Log.txt", "|0|........||\n")
    pub = {"id": pid, "platform": "NES", "emulator": "BizHawk 2.8",
           "local_movie": f"movies/NES/{pid}.bk2", "rom_sha1": rom_sha1 or sha1,
           "game": game, "version_id": f"v{pid}"}
    pubs = R_load_pubs(lib)
    pubs[pid] = pub
    (lib / "publications.json").write_text(
        json.dumps({"publications": pubs}), encoding="utf-8")
    return lib, pub, sha1, str(rom), str(bk2)


def R_load_pubs(lib):
    import json
    p = Path(lib) / "publications.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8")).get("publications", {})
    return {}


def test_acquire():
    import tempfile
    import json
    import hashlib
    from pathlib import Path
    from . import acquire as AQ
    from .schema import FailureCode

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rom = td / "game.nes"
        rom.write_bytes(b"ROM-acquire-test")
        sha1 = hashlib.sha1(rom.read_bytes()).hexdigest().upper()
        pub = {"id": "1", "game": "Test", "platform": "NES", "rom_sha1": sha1}

        # 本地 SHA-1 命中 => ready/local（注入 rom_idx，不触真实 lib）
        r = AQ.resolve_rom(pub, lib=td, rom_idx={sha1: [str(rom)]})
        ok(r["status"] == "ready" and r["source"] == "local" and r["rom"] == str(rom),
           "acquire：ROM 本地命中 => ready/local")
        # 未命中 + 无 resolver => blocked（绝不自动抓商业全集）
        r2 = AQ.resolve_rom(pub, lib=td, rom_idx={})
        ok(r2["status"] == "blocked" and r2["source"] is None,
           "acquire：ROM 未命中+无 resolver => blocked（不自动抓）")
        ok(any(b["code"] == FailureCode.MISSING_RESOURCE.value for b in r2["blockers"]),
           "acquire：阻塞码 MISSING_RESOURCE")
        # 门控 resolver 命中 + 哈希符 => ready/own_netdisk
        r3 = AQ.resolve_rom(pub, lib=td, rom_idx={}, netdisk_resolver=lambda req, p: str(rom))
        ok(r3["status"] == "ready" and r3["source"] == "own_netdisk",
           "acquire：门控 resolver 命中+哈希符 => ready/own_netdisk")
        # 反证格：resolver 给哈希不符的文件 => blocked（哈希闸门有效）
        wrong = td / "wrong.nes"
        wrong.write_bytes(b"Different-ROM-bytes")
        r4 = AQ.resolve_rom(pub, lib=td, rom_idx={}, netdisk_resolver=lambda req, p: str(wrong))
        ok(r4["status"] == "blocked", "acquire：resolver 哈希不符 => blocked（哈希闸门）")
        r5 = AQ.resolve_rom(pub, lib=td, rom_idx={}, netdisk_resolver=lambda req, p: None)
        ok(r5["status"] == "blocked", "acquire：resolver 未命中 => blocked")
        req, src = AQ.required_rom_sha1(pub, td)
        ok(req == sha1 and src == "出版物 rom_sha1", "acquire：required_rom_sha1 出版物优先")

        # ---- 金手指/存档索引（临时 cheat_lib，不触真实索引）----
        clib = td / "cheats"
        clib.mkdir()
        (clib / "zelda.cht").write_bytes(b"cheat-code")
        idx = {"entries": [
            {"platform": "NES", "game": "塞尔达", "kind": "金手指",
             "filename": "zelda.cht", "rel_path": "zelda.cht", "sha256": "x"},
            {"platform": "NES", "game": "absent", "kind": "存档",
             "filename": "nope.state", "rel_path": "nope.state", "sha256": "y"},
        ]}
        (clib / AQ.CHEAT_INDEX_NAME).write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
        ok(len(AQ.index_cheats(clib)) == 2, "acquire：index_cheats 读本地索引")
        ok(AQ.index_cheats(td / "no_index") == [], "acquire：index_cheats 缺索引 => []")
        rc = AQ.resolve_cheat("Zelda", "NES", cheat_lib=clib, query="塞尔达")
        ok(rc["status"] == "found" and len(rc["entries"]) == 1,
           "acquire：resolve_cheat query 命中中文索引 => found")
        ok(rc["entries"][0]["present"] is True, "acquire：命中项文件真在")
        # 反证格：索引有但文件缺 => present 过滤掉 => missing
        rc2 = AQ.resolve_cheat("absent", "NES", cheat_lib=clib)
        ok(rc2["status"] == "missing", "acquire：索引有但文件缺 => missing（present 过滤）")
        rc3 = AQ.resolve_cheat("NoMatch", "NES", cheat_lib=clib)
        ok(rc3["status"] == "missing" and rc3["blockers"],
           "acquire：无匹配 => missing（可选资源，非 blocked）")
        rc4 = AQ.resolve_cheat("塞尔达", "SNES", cheat_lib=clib, query="塞尔达")
        ok(rc4["status"] == "missing", "acquire：平台不符 => missing")

        # ---- acquire 集成：ROM 必需，金手指可选 ----
        a1 = AQ.acquire(pub, lib=td, rom_idx={sha1: [str(rom)]}, cheat_lib=clib,
                        cheat_query="塞尔达", need_cheat=False)
        ok(a1["status"] == "ready" and a1["cheat"]["status"] == "found",
           "acquire：ROM ready+cheat found => ready")
        a2 = AQ.acquire(pub, lib=td, rom_idx={sha1: [str(rom)]}, cheat_lib=clib,
                        cheat_query="NoMatch", need_cheat=False)
        ok(a2["status"] == "ready", "acquire：cheat 缺但 need_cheat=False => ready（金手指可选）")
        a3 = AQ.acquire(pub, lib=td, rom_idx={sha1: [str(rom)]}, cheat_lib=clib,
                        cheat_query="NoMatch", need_cheat=True)
        ok(a3["status"] == "blocked", "acquire：cheat 缺且 need_cheat=True => blocked")
        a4 = AQ.acquire(pub, lib=td, rom_idx={}, cheat_lib=clib)
        ok(a4["status"] == "blocked" and a4["rom"] is None, "acquire：ROM 缺 => blocked")


def test_statebuild():
    from . import statebuild as SB
    from .schema import StateOrigin, FailureCode

    caps_replay = {"batch_replay": {"supported": True, "evidence": "test"}}
    caps_full = {"batch_replay": {"supported": True}, "savestate": {"supported": True},
                 "ram_read": {"supported": True}}
    # 模拟能力不足（savestate/ram_read=False，对应「无实跑证据」态）：测 statebuild 诚实 blocked 路径
    caps_nes = {"batch_replay": {"supported": True},
                "savestate": {"supported": False, "evidence": "无实跑证据"},
                "ram_read": {"supported": False, "evidence": "无实跑证据"}}

    r = SB.build_state("movie", "pf", caps_replay)
    ok(r["status"] == "ready" and r["origin"] == StateOrigin.NORMAL_PREFIX.value,
       "statebuild：movie => normal_prefix ready")
    ok(r["mechanism"] == "replay_movie", "statebuild：movie 机制 replay_movie")
    r2 = SB.build_state("checkpoint", "pf", caps_replay)
    ok(r2["status"] == "ready" and r2["origin"] == StateOrigin.TAS_CHECKPOINT.value,
       "statebuild：checkpoint => tas_checkpoint")
    r3 = SB.build_state("arcade_move", "pf", caps_full)
    ok(r3["status"] == "ready" and r3["origin"] == StateOrigin.DISPLAY_PATCH.value,
       "statebuild：arcade_move => display_patch ready")
    # display_patch 即便能力接线，缺实际资源仍 blocked
    r4 = SB.build_state("savestate", "pf", caps_full)
    ok(r4["status"] == "blocked" and any(b["code"] == FailureCode.MISSING_RESOURCE.value
                                        for b in r4["blockers"]),
       "statebuild：savestate 缺文件 => blocked MISSING_RESOURCE")
    r5 = SB.build_state("savestate", "pf", caps_full, savestate="/x.state")
    ok(r5["status"] == "ready", "statebuild：savestate 有文件 => ready")
    r6 = SB.build_state("cheat", "pf", caps_full, cheat="ADDR=VAL")
    ok(r6["status"] == "ready" and r6["mechanism"] == "apply_cheat",
       "statebuild：cheat 有代码 => ready")
    r7 = SB.build_state("cheat", "pf", caps_full)
    ok(r7["status"] == "blocked", "statebuild：cheat 缺代码 => blocked")
    # 模拟 NES 无证据能力=False => UNSUPPORTED_CAPABILITY（诚实不伪装；真 NES 已接线见 test_statejump）
    r8 = SB.build_state("savestate", "pf", caps_nes, savestate="/x.state")
    ok(r8["status"] == "blocked" and r8["supported"] is False,
       "statebuild：NES savestate 无证据 => blocked supported=False")
    ok(any(b["code"] == FailureCode.UNSUPPORTED_CAPABILITY.value for b in r8["blockers"]),
       "statebuild：NES display_patch => UNSUPPORTED_CAPABILITY")
    r9 = SB.build_state("cheat", "pf", caps_nes, cheat="X")
    ok(r9["status"] == "blocked" and any(b["code"] == FailureCode.UNSUPPORTED_CAPABILITY.value
                                        for b in r9["blockers"]),
       "statebuild：NES cheat 无证据 => UNSUPPORTED_CAPABILITY")
    r10 = SB.build_state("movie", "pf", caps_nes)
    ok(r10["status"] == "ready", "statebuild：NES movie 仍 ready（无证据态下电影路径仍可用）")
    r11 = SB.build_state("bogus", "pf", caps_full)
    ok(r11["status"] == "blocked" and r11["state"] is None,
       "statebuild：未知 source => blocked state=None")
    ok(any(b["code"] == FailureCode.SCHEMA_INVALID.value for b in r11["blockers"]),
       "statebuild：未知 source => SCHEMA_INVALID")
    ok(SB._cap_supported({"k": {"supported": True}}, "k") == (True, ""),
       "statebuild：_cap_supported dict 形式")
    ok(SB._cap_supported({"k": True}, "k") == (True, ""), "statebuild：_cap_supported bool 形式")
    ok(SB._cap_supported({}, "k") == (False, ""), "statebuild：_cap_supported 缺键 => False")
    # 恒量反证格：缺 BizHawk 目录的真 NES 探针 savestate/ram_read 恒 False
    # （avail 闸锁住；能力转真另需实跑证据，见 test_statejump 的 probe 双闸）
    from .backends import BizHawkNESBackend
    real_caps = BizHawkNESBackend(r"Z:\no_such_bizhawk").probe()["capabilities"]
    ok(real_caps["savestate"]["supported"] is False and real_caps["ram_read"]["supported"] is False,
       "statebuild 反证：缺目录 NES 探针 savestate/ram_read 恒 False（avail 闸如实）")


def test_statejump():
    """T3 前置件闸门：协议纯函数 + 字节级 CRLF + 模板内容 + 宏有效语义 + 证据门控。
    每个断言对应一个 11-10 实跑踩过的坑（立规：坑必须落成代码闸门）。"""
    import json
    import os
    import shutil
    import tempfile
    from pathlib import Path
    import tas_replay
    from . import statejump as SJ
    from . import backends as B

    # ---- 宏谱解析 ----
    ok(SJ.parse_macro("Start,,A+B") == "Start,,A+B", "宏谱：规范透传")
    ok(SJ.parse_macro("U+D,L+R") == "Up+Down,Left+Right", "宏谱：U/D/L/R 别名展开")
    ok(SJ.parse_macro(",") == ",", "宏谱：空帧=中立保留")
    raises(lambda: SJ.parse_macro("A+X"), "宏谱：未知键被拒")
    raises(lambda: SJ.parse_macro("A B"), "宏谱：含空白被拒")
    raises(lambda: SJ.parse_macro(""), "宏谱：空谱被拒")

    # ---- 指令线格式 ----
    ok(SJ.format_command(1, "ping") == "1 ping", "指令：ping 线格式")
    ok(SJ.format_command(2, "read", addr=0x10) == "2 read 16", "指令：read 地址十进制")
    ok(SJ.format_command(3, "write", addr=0, value=255) == "3 write 0 255", "指令：write 线格式")
    ok(SJ.format_command(4, "attempt", state="C:/a.state", spec="-", extra=60)
       == "4 attempt C:/a.state - 60", "指令：attempt 线格式（spec=- 表无宏）")
    raises(lambda: SJ.format_command(1, "bogus"), "指令：未知 op 被拒")
    raises(lambda: SJ.format_command(0, "ping"), "指令：id<1 被拒")
    raises(lambda: SJ.format_command(1, "read", addr=0x10000), "指令：地址越界被拒")
    raises(lambda: SJ.format_command(1, "write", addr=0, value=256), "指令：字节越界被拒")
    raises(lambda: SJ.format_command(1, "run", frames=0), "指令：run 帧数<1 被拒")
    raises(lambda: SJ.format_command(1, "attempt", state="C:/a.state", extra=-1),
           "指令：attempt extra<0 被拒")
    raises(lambda: SJ.format_command(1, "save", path="C:/有中文.state"),
           "指令：中文路径被拒（Lua io 转码坑）")
    raises(lambda: SJ.format_command(1, "save", path="C:/a b.state"),
           "指令：含空白路径被拒")
    ok(SJ.format_command(5, "ramdump", path="C:/ram.bin", length=2048)
       == "5 ramdump C:/ram.bin 2048", "指令：ramdump 线格式")
    ok(SJ.format_command(6, "dump", frames_dir="C:/fr", spec="B,,", extra=30)
       == "6 dump C:/fr B,, 30", "指令：dump 线格式（宏+空档）")
    ok(SJ.format_command(7, "dump", frames_dir="C:/fr")
       == "7 dump C:/fr - 0", "指令：dump 缺省 spec=- extra=0")
    raises(lambda: SJ.format_command(1, "dump", frames_dir="C:/fr", extra=-1),
           "指令：dump extra<0 被拒")
    raises(lambda: SJ.format_command(1, "ramdump", path="C:/ram.bin", length=0),
           "指令：ramdump 长度<1 被拒")
    raises(lambda: SJ.format_command(1, "dump", frames_dir="C:/有中文"),
           "指令：dump 中文目录被拒")

    # ---- 响应解析 ----
    ok(SJ.parse_response("5 ok 12 INACTIVE") == {"id": 5, "ok": True, "data": "12 INACTIVE"},
       "响应：ok 解析")
    ok(SJ.parse_response("6 err boom")["ok"] is False, "响应：err 解析")
    raises(lambda: SJ.parse_response("7 maybe x"), "响应：非法状态被拒")
    raises(lambda: SJ.parse_response("x ok"), "响应：id 非整数被拒")

    # ---- 字节级 CRLF 闸门（坑：Windows 文本模式 \n→\r\n，Lua 切词得 ping\r）----
    with tempfile.TemporaryDirectory() as td:
        s = SJ.StateSession("dummy.nes", "dummy_bh", work=td)
        s._send("1 ping")
        raw = (Path(td) / "cmd.txt").read_bytes()
        ok(raw == b"1 ping\n", "CRLF 闸门：_send 落盘恰为 LF 结尾，无 \\r")
        ok(b"\r" not in raw, "CRLF 闸门：cmd.txt 不含任何 CR 字节")

    # ---- 模板内容闸门 ----
    tmpl = tas_replay.STATE_LUA_TMPL
    ok("\r" not in tmpl, "模板闸门：无字面 CR（Python 三引号 \\r 转义坑会编译失败）")
    ok('string.gsub(line, "\\r$", "")' in tmpl, "模板闸门：Lua 侧剥行尾 CR 在册")
    ok("png_complete" in tmpl and "flushing" in tmpl and "queue_shot" in tmpl,
       "模板闸门：截图 flushing 态在册（坑：截完即 respond 会拷到旧图/半截图→假阳性）")
    ok("flush_shot" not in tmpl,
       "模板闸门：旧 flush_shot 已除（坑：其 frameadvance 在 pcall 内会跨 C-call yield 崩溃）")
    ok('io.open(resp_path, "w")' in tmpl and "os.rename" not in tmpl,
       "模板闸门：resp 直写不用 rename（坑：rename 落盘 Python 侧不可见）")
    ok('op == "dump"' in tmpl and 'op == "ramdump"' in tmpl,
       "模板闸门：dump/ramdump op 在册（全量盘点逐帧采集 / 经验 RAM 标定）")
    ok("path = lastpath" in tmpl and "png_complete(flushing.path)" in tmpl,
       "模板闸门：dump 末帧交 flushing 过 IEND 完整性查（防半截图进 encode_video）")

    # ---- 宏有效语义回归（坑：把「相等」当「有效」→假阳性绿灯）----
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        same_a = td / "a.png"; same_b = td / "b.png"
        same_a.write_bytes(b"\x89PNG identical"); same_b.write_bytes(b"\x89PNG identical")
        eff, _ = SJ.macro_is_effective(same_a, same_b)
        ok(eff is False, "宏有效回归：相同画面必判无效（锁死反转 bug）")
        ok(SJ._png_pixels_equal(same_a, same_b)[0] is True, "像素比对：相同字节=>相等")
        if shutil.which("ffmpeg"):
            from PIL import Image
            red = td / "red.png"; blue = td / "blue.png"
            Image.new("RGB", (4, 4), (255, 0, 0)).save(red)
            Image.new("RGB", (4, 4), (0, 0, 255)).save(blue)
            eff2, _ = SJ.macro_is_effective(red, blue)
            ok(eff2 is True, "宏有效回归：不同画面判有效（ffmpeg 像素复核）")

    # ---- 证据门控（坑：凭 API 存在就标 supported；须实跑全 pass 才转真）----
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        rep = td / "report.json"
        ok(B.statejump_evidence(rep)[0] is False, "证据门：报告缺失=>False")
        rep.write_text("{bad json", encoding="utf-8")
        ok(B.statejump_evidence(rep)[0] is False, "证据门：报告损坏=>False")
        rep.write_text(json.dumps({"all_pass": False, "checks": [{"name": "x", "pass": False}]}),
                       encoding="utf-8")
        ok(B.statejump_evidence(rep)[0] is False, "证据门：未全 pass=>False")
        rep.write_text(json.dumps({"all_pass": True, "created": "t", "checks": []}),
                       encoding="utf-8")
        ok(B.statejump_evidence(rep)[0] is True, "证据门：全 pass=>True")

    # ---- probe 双闸：BizHawk 可用 + 证据全 pass 才转真 ----
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bh = td / "BizHawk-2.8"; bh.mkdir()
        (bh / "EmuHawk.exe").write_bytes(b"MZ")
        orig = B.statejump_evidence
        try:
            B.statejump_evidence = lambda *a, **k: (True, "test 全 pass")
            caps = B.BizHawkNESBackend(str(bh)).probe()["capabilities"]
            ok(caps["savestate"]["supported"] is True
               and caps["ram_read"]["supported"] is True
               and caps["interactive_step"]["supported"] is True,
               "probe 双闸：可用+证据全 pass => savestate/ram_read/interactive_step 转真")
            B.statejump_evidence = lambda *a, **k: (False, "无证据")
            caps2 = B.BizHawkNESBackend(str(bh)).probe()["capabilities"]
            ok(caps2["savestate"]["supported"] is False,
               "probe 双闸：可用但无证据 => 仍 False（不凭接线臆造）")
        finally:
            B.statejump_evidence = orig
    fake = B.BizHawkNESBackend(r"Z:\no_such_bizhawk").probe()["capabilities"]
    ok(fake["savestate"]["supported"] is False and fake["interactive_step"]["supported"] is False,
       "probe 双闸：缺 BizHawk 目录 => 能力 False（反证格仍立）")


def test_auto():
    import tempfile
    import json
    from pathlib import Path
    from . import auto as A
    from . import registry as R
    from .schema import SchemaError

    # ---- JobSpec 校验（纯逻辑）----
    raises(lambda: A.JobSpec("", "playthrough").validate(), "auto：JobSpec 缺 game 被拒")
    raises(lambda: A.JobSpec("g", "bogus").validate(), "auto：JobSpec 非法 job_type 被拒")
    raises(lambda: A.JobSpec("g", "playthrough", source="bogus").validate(),
           "auto：JobSpec 非法 source 被拒")
    raises(lambda: A.JobSpec("g", "moves").validate(), "auto：要素任务缺 pack/elements 被拒")
    raises(lambda: A.JobSpec("g", "playthrough", frames=0).validate(), "auto：JobSpec frames<=0 被拒")
    ok(A.JobSpec("g", "playthrough").validate().job_type == "playthrough",
       "auto：JobSpec 合法通关通过")
    s = A.JobSpec.from_dict({"game": "g", "job_type": "playthrough", "bogus_field": 1})
    ok(s.game == "g" and not hasattr(s, "bogus_field"), "auto：from_dict 过滤未知字段")
    s1 = A.JobSpec("Super Mario Bros.", "playthrough", pub_id="6012", out="/a")
    s2 = A.JobSpec("Super Mario Bros.", "playthrough", pub_id="6012", out="/b")
    ok(s1.slug() == s2.slug(), "auto：slug 与 out 无关")
    ok(A._spec_fp_params(s1) == A._spec_fp_params(s2), "auto：指纹参数排除 out（位置无关）")
    ok("out" not in A._spec_fp_params(s1), "auto：_spec_fp_params 不含 out")

    # ---- load_elements ----
    inline = A.JobSpec("g", "moves", elements=[{"element_id": "e1"}])
    ok(A.load_elements(inline) == [{"element_id": "e1"}], "auto：load_elements 内联优先")
    raises(lambda: A.orchestrate(A.JobSpec("g", "playthrough"), dry_run=False),
           "auto：orchestrate run 缺 out 被拒")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pack = td / "p.json"
        pack.write_text(json.dumps({"elements": [{"element_id": "e2"}]}), encoding="utf-8")
        ok(A.load_elements(A.JobSpec("g", "moves", pack=str(pack))) == [{"element_id": "e2"}],
           "auto：load_elements 读 pack")
        raises(lambda: A.load_elements(A.JobSpec("g", "moves", pack=str(td / "nope.json"))),
               "auto：load_elements 缺 pack 被拒")

        # ---- 合成 NES lib + patch 路径常量（隔离，不依赖真机 BizHawk）----
        lib, pub, sha1, rom, bk2 = _synthetic_nes_lib(td)
        orig_disc, orig_caps = R.discover_bizhawk, A._backend_caps
        try:
            R.discover_bizhawk = lambda emu_root: {"2.8": str(td / "fake_bh")}
            A._backend_caps = lambda assess, source: (
                {"batch_replay": {"supported": True, "evidence": "test"}}, "nes_bizhawk")
            spec = A.JobSpec("Auto Test Game", "playthrough", pub_id="9999")
            p, assess = A.resolve_job(spec, lib)
            ok(p and p["id"] == "9999" and assess["status"] == "replayable",
               "auto：resolve_job 合成 lib => replayable")
            pl = A.plan(spec, lib)
            ok(pl["status"] == "ready", "auto：plan 合成 ready（resolve+acquire+state 全过）")
            ok(pl["stages"]["acquire"]["status"] == "ready", "auto：plan acquire ready")
            ok(pl["stages"]["state"]["origin"] == "normal_prefix", "auto：plan movie => normal_prefix")
            fp = A.expected_fingerprint(spec, lib)
            ok(bool(fp), "auto：expected_fingerprint 不采集即算出指纹")
            spec_out = A.JobSpec("Auto Test Game", "playthrough", pub_id="9999", out=str(td / "x"))
            ok(A.expected_fingerprint(spec_out, lib) == fp, "auto：指纹与 out 无关（矩阵可跳过）")
            # savestate 源 + 无金手指 => acquire 阶段诚实 blocked（need_cheat 门控）
            pl_ss = A.plan(A.JobSpec("Auto Test Game", "playthrough", pub_id="9999",
                                     source="savestate"), lib)
            ok(pl_ss["status"] == "blocked" and pl_ss["stages"]["acquire"]["status"] == "blocked",
               "auto：plan NES savestate 无金手指 => acquire blocked（诚实）")
            # 未知游戏 => resolve blocked（合成 lib 无此名，不触真实 4694 条）
            doc = A.orchestrate(A.JobSpec("ZZZ_NO_SUCH_GAME", "playthrough"), lib=lib, dry_run=True)
            ok(doc["status"] == "blocked" and doc["stages"]["resolve"]["status"] == "blocked",
               "auto：orchestrate 未知游戏 => resolve blocked")
        finally:
            R.discover_bizhawk, A._backend_caps = orig_disc, orig_caps


def test_matrix():
    import tempfile
    import json
    from pathlib import Path
    from . import matrix as M
    from . import auto as A
    from . import registry as R

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        art = td / "out.mp4"
        art.write_bytes(b"video")
        # ---- _deliverable_present：量产物真在 ----
        ok(M._deliverable_present({"deliverable_ref": str(art)}) is True, "matrix：产物在 => present")
        ok(M._deliverable_present({"deliverable_ref": str(td / "nope.mp4")}) is False,
           "matrix：产物缺 => not present")
        ok(M._deliverable_present({}) is False, "matrix：无产物字段 => not present")
        e1 = td / "e1.mp4"
        e1.write_bytes(b"x")
        ok(M._deliverable_present({"elements": [{"deliverable_ref": str(e1)}]}) is True,
           "matrix：要素产物全在 => present")
        ok(M._deliverable_present({"elements": [{"deliverable_ref": str(e1)},
                                                {"deliverable_ref": str(td / "nope")}]}) is False,
           "matrix：要素产物缺一 => not present")

        # ---- _coverage：逐格直接计数，不总数减失败倒推 ----
        results = [
            {"action": "skipped", "status": "done", "verdict": "pass"},
            {"action": "ran", "status": "done", "verdict": "pass"},
            {"action": "ran", "status": "blocked", "verdict": "inconclusive"},
            {"action": "ran", "status": "failed", "verdict": "fail"},
            {"action": "invalid", "status": "blocked", "verdict": None},
            {"action": "planned", "status": "ready", "verdict": None},
        ]
        cov = M._coverage(results)
        ok(cov["pass"] == 2, "matrix：coverage pass 逐格直接计数=2")
        ok(cov["by_result"].get("skipped") == 1 and cov["by_result"].get("done") == 1,
           "matrix：coverage skipped/done 分开计")
        ok(cov["by_result"].get("blocked") == 1 and cov["by_result"].get("failed") == 1,
           "matrix：coverage blocked/failed 分开计")
        ok(cov["total"] == 6, "matrix：coverage total=6")

        # ---- cell_done：合成 job.json + patch expected_fingerprint ----
        spec = A.JobSpec("Cell Game", "playthrough", pub_id="1234")
        job_dir = td / spec.slug()
        job_dir.mkdir()
        jf = job_dir / "job.json"
        art2 = td / "cell.mp4"
        art2.write_bytes(b"cellvideo")
        orig_fp, orig_orch = M.expected_fingerprint, M.orchestrate
        try:
            M.expected_fingerprint = lambda s, lib=None: "FP123"
            ok(M.cell_done(spec, td)[0] is False, "matrix：cell_done 无 job.json => 未完成")
            jf.write_text(json.dumps({"status": "blocked", "verdict": "inconclusive",
                                      "fp": "FP123", "deliverable_ref": str(art2)}), encoding="utf-8")
            ok(M.cell_done(spec, td)[0] is False, "matrix：cell_done status!=done => 未完成")
            jf.write_text(json.dumps({"status": "done", "verdict": "fail",
                                      "fp": "FP123", "deliverable_ref": str(art2)}), encoding="utf-8")
            ok(M.cell_done(spec, td)[0] is False, "matrix：cell_done verdict!=pass => 未完成")
            jf.write_text(json.dumps({"status": "done", "verdict": "pass",
                                      "fp": "FP123", "deliverable_ref": str(td / "nope.mp4")}), encoding="utf-8")
            ok(M.cell_done(spec, td)[0] is False, "matrix：cell_done 产物缺 => 未完成")
            jf.write_text(json.dumps({"status": "done", "verdict": "pass",
                                      "fp": "OTHER", "deliverable_ref": str(art2)}), encoding="utf-8")
            ok(M.cell_done(spec, td)[0] is False, "matrix：cell_done 指纹不符 => 未完成")
            jf.write_text(json.dumps({"status": "done", "verdict": "pass",
                                      "fp": "FP123", "deliverable_ref": str(art2)}), encoding="utf-8")
            ok(M.cell_done(spec, td)[0] is True, "matrix：cell_done 全符 => 已完成")
            M.expected_fingerprint = lambda s, lib=None: None
            ok(M.cell_done(spec, td)[0] is False, "matrix：cell_done 指纹算不出(None) => 未完成")

            # ---- run_matrix：跳过已完成格（不重采集）----
            M.expected_fingerprint = lambda s, lib=None: "FP123"
            calls = []
            M.orchestrate = lambda spec, lib=None, out_dir=None, dry_run=False: (
                calls.append(spec.slug()) or {"status": "done", "verdict": "pass",
                                              "deliverable_ref": str(art2), "fp": "FP123"})
            cells = [{"game": "Cell Game", "job_type": "playthrough", "pub_id": "1234"}]
            rep = M.run_matrix(cells, td, skip_done=True)
            ok(rep["cells"][0]["action"] == "skipped" and len(calls) == 0,
               "matrix：run_matrix 已完成格跳过（不重采集）")
            rep2 = M.run_matrix(cells, td, skip_done=False)
            ok(rep2["cells"][0]["action"] == "ran" and len(calls) == 1,
               "matrix：run_matrix no-skip => 重跑")
            rep3 = M.run_matrix([{"game": "", "job_type": "playthrough"}], td, skip_done=False)
            ok(rep3["cells"][0]["action"] == "invalid", "matrix：run_matrix 非法格 => invalid")
        finally:
            M.expected_fingerprint, M.orchestrate = orig_fp, orig_orch

        # ---- famous_playthrough_cells：预筛 + 排除 + 同名去重（合成 lib）----
        lib, pub, sha1, rom, bk2 = _synthetic_nes_lib(td, game="Famous Game", pid="7001")
        # 追加：同名第二条（去重）、被排除名、ROM 不在索引（预筛掉）
        pubs = R_load_pubs(lib)
        import copy
        p_dup = copy.deepcopy(pub); p_dup["id"] = "7002"
        p_dup["local_movie"] = "movies/NES/7002.bk2"
        import shutil
        shutil.copy(bk2, str(Path(lib) / "movies" / "NES" / "7002.bk2"))
        pubs["7002"] = p_dup
        p_excl = copy.deepcopy(pub); p_excl["id"] = "7003"; p_excl["game"] = "Excluded Game"
        p_excl["local_movie"] = "movies/NES/7003.bk2"
        shutil.copy(bk2, str(Path(lib) / "movies" / "NES" / "7003.bk2"))
        pubs["7003"] = p_excl
        p_norom = copy.deepcopy(pub); p_norom["id"] = "7004"; p_norom["game"] = "No Rom Game"
        p_norom["rom_sha1"] = "DEADBEEF_NOT_IN_INDEX"; p_norom["version_id"] = "vnone"
        p_norom["local_movie"] = "movies/NES/7004.bk2"
        shutil.copy(bk2, str(Path(lib) / "movies" / "NES" / "7004.bk2"))
        pubs["7004"] = p_norom
        (lib / "publications.json").write_text(json.dumps({"publications": pubs}), encoding="utf-8")
        orig_disc = R.discover_bizhawk
        try:
            R.discover_bizhawk = lambda emu_root: {"2.8": str(td / "fake_bh")}
            cells = M.famous_playthrough_cells(lib, exclude=["Excluded"], frames=600)
            games = [c["game"] for c in cells]
            ok(games == ["Famous Game"], "matrix：famous 预筛掉无ROM+排除名+同名去重 => 只剩 1 格")
            ok(cells[0]["frames"] == 600 and cells[0]["job_type"] == "playthrough",
               "matrix：famous 格带 frames/job_type")
        finally:
            R.discover_bizhawk = orig_disc


def test_exporter_mask():
    import tempfile
    import subprocess
    from pathlib import Path
    from PIL import Image
    from . import exporter as E
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        m = Image.new("RGBA", (64, 48), (255, 0, 0, 255))
        for y in range(6, 42):
            for x in range(8, 56):
                m.putpixel((x, y), (0, 0, 0, 0))
        mp = td / "mask.png"; m.save(mp)
        tpl = {"name": "t_mask", "mode": "mask", "mask": str(mp), "fallback_bg": [0, 0, 0]}
        lay = E.build_bezel(None, 16, 14, str(td / "bez.png"), tpl)
        ok(lay["hole"] == [8, 6, 56, 42], "mask：屏洞由 alpha==0 自动量出")
        ok(lay["scale"] == 2 and lay["gameplay_scaled"] == [32, 28], "mask：画面整数倍贴合屏洞(x2)")
        ok(lay["overlay_xy"] == [16, 10], "mask：画面在屏洞内居中")
        m2 = Image.new("RGBA", (64, 48), (255, 0, 0, 255)); mp2 = td / "nohole.png"; m2.save(mp2)
        try:
            E.build_bezel(None, 16, 14, str(td / "b2.png"), dict(tpl, mask=str(mp2)))
            refused = False
        except SystemExit:
            refused = True
        ok(refused, "mask：无透明屏洞的遮罩被拒（不静默满铺）")
        clip = td / "clip.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        "color=c=0x00ff00:size=16x14:rate=10:duration=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
                       check=True, capture_output=True)
        orig_load = E.load_template
        E.load_template = lambda name=None: tpl
        try:
            run = E.compose(str(clip), str(td / "out.mp4"))
        finally:
            E.load_template = orig_load
        ver = run["verification"]
        ok(ver["verdict"] != "fail", "mask：compose 端到端非 fail")
        checks = {c["check_id"]: c for c in ver["checks"]}
        ok(checks["frames_preserved"]["verdict"] == "pass", "mask：帧数保留")
        frame = td / "f.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(td / "out.mp4"),
                        "-vf", "select=eq(n\\,5)", "-frames:v", "1", str(frame)],
                       check=True, capture_output=True)
        im = Image.open(frame).convert("RGB")
        ok(im.size == (64, 48), "mask：成片画幅=遮罩画幅")
        sp = im.getpixel((0, 0))
        ok(sp[0] > 150 and sp[1] < 80 and sp[2] < 80, "mask：四周环绕美术压在画面之上(角落=遮罩红,容编码损失)")
        px = im.getpixel((32, 24))
        ok(px[1] > 100 and px[0] < 100 and px[2] < 100, "mask：屏洞中心露出游戏画面(绿)")


def main():
    print("taspipe selftest (M0-M6 + audio + M8 ledger + M7 search + sync + warp + M10 probes + T1 unwrap/mux + T2 fceux + auto/acquire/statebuild/statejump/matrix + exporter mask)")
    test_schema()
    test_registry()
    test_backends()
    test_detect_gamepack()
    test_clipper()
    test_audio()
    test_sync()
    test_warp_sync()
    test_ledger()
    test_region_plugin()
    test_search()
    test_m10_probes()
    test_replay_unwrap_mux()
    test_bizhawk29_compat()
    test_fceux()
    test_acquire()
    test_statebuild()
    test_statejump()
    test_auto()
    test_matrix()
    test_exporter_mask()
    print(f"SELFTEST OK {PASS}/{PASS}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())