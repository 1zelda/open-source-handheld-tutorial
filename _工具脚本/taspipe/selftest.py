# -*- coding: utf-8 -*-
"""离线自检（M0 起逐步累加）。运行: python -m taspipe.selftest"""
import sys
import hashlib
import tempfile
from pathlib import Path
from .schema import (Profile, Element, State, InputPlan, Verification, LedgerJob,
                     CheckSpec, CheckResult, Platform, StateOrigin, ClockUnit,
                     Verdict, Stage, JobStatus, FailureCode, SchemaError)

PASS = 0

# 选题闸门（2026-11-22：只测最有名、大家玩得多的作品）会把没听过的标题拦在启动前。
# 夹具按平台各取一个名单上的名作，这样每条用例的 blockers 里只剩它自己要测的那根轴。
_FAMOUS_FOR = {"NES": "Super Mario Bros.", "SNES": "Super Metroid"}


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
    ok(plat == R.Platform.GBA and not note, "map_platform GBA 已建模（11-21 实测到盘里有 GBA ROM 后补进 schema）")
    plat, _, note = R.map_platform({"platform": "ChannelF"}, None)
    ok(plat is None and note, "map_platform 未建模平台返回 None+说明")

    d, note, code = R.emulator_match("BizHawk 2.8", {"2.8": "/x"})
    ok(d == "/x" and code is None, "emulator_match 命中本地 BizHawk")
    d, note, code = R.emulator_match("BizHawk 2.9", {"2.8": "/x"})
    ok(d is None and note, "emulator_match 缺版本=>None+说明")
    d, note, code = R.emulator_match("FCEUX 2.2.3", {"2.8": "/x"})
    ok(d is None and "非 BizHawk" in note, "emulator_match 非 BizHawk 管线")
    # 11-21：tasvideos 的 emulator 文本大小写混写，旧规则把 BizHawk 管线自己拦死
    d, note, code = R.emulator_match("Bizhawk 2.9.1", {"2.9.1": "/y"})
    ok(d == "/y", "emulator_match 小写 h 的 'Bizhawk' 也算 BizHawk 管线")
    d, note, code = R.emulator_match("EmuHawk 2.9.0 (Core: QuickNES)", {"2.9": "/z"})
    ok(d == "/z" and note, "emulator_match 'EmuHawk <版本> (Core: …)' 命中并可说明写法差")
    d, note, code = R.emulator_match("bizhawk 2.11 x64", {"2.11": "/w"})
    ok(d == "/w", "emulator_match 全小写+后缀文本仍解析版本")
    d, note, code = R.emulator_match("BizHawk 2.9.1", {"2.9": "/z"})
    ok(d is None and "本地无" in note,
       "emulator_match 反证—2.9.1 不许被裁成 2.9(只有尾巴 .0 才是同一次发布)")
    # 11-21：版本类阻塞不许再冒用 missing_resource——它曾把"补 ROM 就能跑"的假象
    # 带进分层统计（SNES 那 454 部就是这么被我读成"只差 ROM"的）。
    ok(code is FailureCode.EMULATOR_VERSION_ABSENT,
       "emulator_match 版本没装=>emulator_version_absent，不是 missing_resource")
    d, note, code = R.emulator_match("Snes9x 1.43 v12 (beta 10)", {"2.9": "/z"})
    ok(d is None and code is FailureCode.UNSUPPORTED_CAPABILITY and "非 BizHawk" in note,
       "emulator_match 非 BizHawk 文本=>unsupported_capability，不是 missing_resource")

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
    import tempfile
    from pathlib import Path
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

    # 网络壳路径探测闸门（说明书 §32.1）：1326 等按不存在，不炸夹具
    ok(B._is_file_probe(r"Z:\no_such_bizhawk\EmuHawk.exe") is False,
       "路径探测：网络壳错误(1326等)=>不存在不抛异常")
    with tempfile.TemporaryDirectory() as td:
        fake = Path(td) / "EmuHawk.exe"
        fake.write_bytes(b"")
        ok(B._is_file_probe(fake) is True,
           "路径探测：真实文件=>True（反证格，防恒 False）")
        ok(B.BizHawkNESBackend(td).probe()["available"] is True,
           "NES 探针：含 EmuHawk.exe 目录=>available True（反证格）")

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

        missing = dict(pack)
        missing["frames"] = {"pos": str(sky)}
        ri = G.run_element(missing, pack["elements"][0])
        ok(ri["verification"]["verdict"] == "inconclusive"
           and ri["negatives"][0]["rejected"] is False,
           "游戏包：负例证据缺失=>未验，不得当成已拒绝")


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

        # 成功必须对应实际存在、可校验的产物，且只有明确 pass 可复用
        led.complete(j1, [art], Verdict.PASS)
        ok(led.entries[-1]["status"] == "done", "台账：complete 校验产物后 done")
        ok(led.reusable(Stage.CAPTURE, "capture", fp) is not None,
           "台账：done+指纹+产物校验+pass => 可复用")
        ji = led.register(Stage.VERIFY, "verify_inc", fp)
        led.complete(ji, [art], Verdict.INCONCLUSIVE)
        ok(led.reusable(Stage.VERIFY, "verify_inc", fp) is None,
           "台账：inconclusive 产物存在也不得复用")
        ok(led.reusable(Stage.CAPTURE, "capture", fp + "x") is None,
           "台账：指纹变 => 不复用")

        other = Ledger(td / "ledger.json")
        other.register(Stage.CAPTURE, "other_writer", fp)
        ok(led.summary()["attempts"] == 3,
           "台账：旧实例重新读取锁内最新内容，不覆盖其他写入者的 attempt")
        ok(not list(td.glob("ledger.json.*.tmp")),
           "台账：原子替换后不留临时文件")

        import json
        import subprocess
        concurrent_path = td / "concurrent_ledger.json"
        worker = ("import sys; sys.path.insert(0, sys.argv[1]); "
                  "from taspipe.ledger import Ledger; from taspipe.schema import Stage; "
                  "ledger = Ledger(sys.argv[2]); "
                  "[ledger.register(Stage.PROFILE, 'concurrent', 'fp') for _ in range(8)]")
        writers = [subprocess.Popen([sys.executable, "-c", worker,
                                     str(Path(__file__).resolve().parents[1]), str(concurrent_path)])
                   for _ in range(4)]
        codes = [writer.wait() for writer in writers]
        concurrent_entries = json.loads(concurrent_path.read_text(encoding="utf-8"))["entries"]
        attempts = sorted(entry["attempt"] for entry in concurrent_entries)
        ok(codes == [0] * 4 and len(concurrent_entries) == 32
           and len({entry["job_id"] for entry in concurrent_entries}) == 32
           and attempts == list(range(1, 33)),
           "台账：四个进程同时构造并写入，attempt 连续且无丢失或覆盖")

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
        rom_zip = td / "roms.zip"
        with zipfile.ZipFile(rom_zip, "w") as z:
            z.writestr("snes/game.sfc", b"SNES-ROM")
        rom_dst = td / "rom.sfc"
        rom_spec = str(rom_zip) + "!snes/game.sfc"
        ok(tas_replay.materialize_rom(rom_spec, str(rom_dst)) is True
           and rom_dst.read_bytes() == b"SNES-ROM",
           "T1 zip!ROM 条目解出到工作目录且字节一致")

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
        ok(conf.get("DontTryOtherCores") is True, "force_core 禁止首选核心失败后静默换核")
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
    ok(set(WD.STARTUP_DIALOG_TITLES) == {"privileged", "Mismatched version"},
       "启动即时点框只含已知警告；Error/Exception 必须留给取证，不能自动吞掉")
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

    # 框证据落进产物（11-22 洛克人X2 stalled_killed 只有 dismissed=1、正文全丢）：
    rec: list = []
    WD._note_dialog(rec, "Warning", ["Firmware file not found"])
    WD._note_dialog(rec, "Warning", ["Firmware file not found"])
    ok(len(rec) == 1, "框证据:同标题同正文去重(轮询重复不灌满产物)")
    WD._note_dialog(rec, "Warning", ["Core not found for SNES_Firmware_CX4"])
    ok(len(rec) == 2 and rec[1]["texts"][0].startswith("Core not found"),
       "框证据:同标题不同正文各留一条(去重键含正文)")
    ok(len(rec) == len({(r["title"], tuple(r["texts"])) for r in rec}),
       "恒量反证:去重后条数==唯一(标题,正文)组合数")
    naive: list = []
    naive.append({"title": "Warning", "texts": ["x"]})
    naive.append({"title": "Warning", "texts": ["x"]})
    ok(len(naive) == 2, "反证:不去重时同一框会重复入账(夹具有效)")
    empty: list = []
    ok(WD.dismiss_bizhawk_dialog(0, records=empty) == 0 and empty == [],
       "无效 PID 不点框也不臆造证据记录")
    ok(isinstance(WD.dismiss_bizhawk_dialog(99999999), int),
       "向后兼容:旧调用不传 records 仍返回 int(statejump/control_runtime 靠它累加)")

    class _ExitedProc:
        pid = 99999999
        returncode = 0

        def poll(self):
            return 0

    with tempfile.TemporaryDirectory() as td2:
        info = WD.watch_process(_ExitedProc(), td2, poll=0.01)
    ok("dismissed_dialogs" in info and isinstance(info["dismissed_dialogs"], list),
       "产物字段在册:watch_process 恒返回 dismissed_dialogs(哪怕空)")
    ok("stall_windows" in info and isinstance(info["stall_windows"], list),
       "产物字段在册:watch_process 恒返回 stall_windows(表外窗口也留证据)")
    ok("windows_at_kill" in info and isinstance(info["windows_at_kill"], list),
       "产物字段在册:watch_process 恒返回 windows_at_kill(放弃那一刻还剩什么)")
    try:
        json.dumps(info)
        ok(True, "框证据可 JSON 落盘(不会因元组/句柄炸产物)")
    except TypeError as e:
        ok(False, f"框证据可 JSON 落盘: {e}")

    # 停滞现场快照：抄的是"可见+非主窗口"，框表认不出的也抄，且绝不臆造。
    ok(WD.stall_windows(0) == [], "无效 PID 不臆造停滞窗口")
    ok(WD.stall_windows(99999999) == [], "不存在的 PID 返回空窗口列表")
    acc: list = []
    item = {"title": "Some Core Dialog", "class": "WindowsForms10.Window.8",
            "texts": ["Firmware for SNES_Firmware_CX4 not found"]}
    WD._note_unique(acc, dict(item))
    WD._note_unique(acc, dict(item))
    ok(len(acc) == 1, "窗口证据:同内容去重(每轮轮询不灌满产物)")
    WD._note_unique(acc, {"title": item["title"], "class": item["class"],
                          "texts": ["Another message"]})
    ok(len(acc) == 2, "窗口证据:正文不同各留一条(去重键含正文)")
    naive2: list = []
    for _ in range(3):
        naive2.append(dict(item))
    ok(len(naive2) == 3, "反证:不去重时同一窗口会重复三次(夹具有效)")

    # 链式弹窗回归（11-22 洛克人X2 windows_at_kill 实证：privileged 点掉之后
    # 才弹 "Couldn't find firmware SNES+CX4"，旧逻辑一轮停滞只点一次，永远点不到第二个）。
    DIA = {"title": "This EmuHawk is privileged", "class": "c", "texts": ["bad idea"]}
    DIB = {"title": "Warning", "class": "#32770", "texts": ["Couldn't find firmware SNES+CX4"]}
    orig_sw, orig_dm, orig_kl = WD.stall_windows, WD.dismiss_bizhawk_dialog, WD.tree_kill
    try:
        for rounds_expect, screen in (("chained", {0: [DIA], 1: [DIB]}),
                                      ("static", {0: [DIA]}),
                                      ("reappear", {0: [DIA], 1: [DIA], 2: []})):
            state = {"clicks": 0}

            def fake_sw(_pid, _screen=screen, _state=state):
                # 超出剧本后就停在最后一屏：静止臂里那个框点了还在，才是「点不掉」
                return _screen.get(_state["clicks"], list(_screen.values())[-1])

            def fake_dm(_pid, titles=None, records=None, _state=state):
                _state["clicks"] += 1
                return 1

            class _StallingProc:
                pid = 4242
                returncode = None

                def poll(self):
                    # 回放只有把挡路的框清掉才走得下去：屏幕相对第一屏变了/空了，
                    # 且至少点过两轮（链式臂第二个框、复现臂同一张框的第二下）才放行。
                    # 静止臂屏幕永远不变，所以只能靠看门狗补点后收手。
                    cur = screen.get(state["clicks"], list(screen.values())[-1])
                    return 0 if state["clicks"] >= 2 and cur != list(screen.values())[0] else None

                def wait(self, timeout=None):
                    return 0

                def kill(self):
                    pass

            WD.stall_windows, WD.dismiss_bizhawk_dialog = fake_sw, fake_dm
            WD.tree_kill = lambda pid: None
            with tempfile.TemporaryDirectory() as td3:
                got = WD.watch_process(_StallingProc(), td3, poll=0.01,
                                       stall_timeout=0.05, dismiss_grace=0.05,
                                       auto_dismiss=True, hard_timeout=5)
            if rounds_expect == "chained":
                ok(state["clicks"] == 2, f"链式框:窗口集合一变就再点一轮(实点 {state['clicks']} 轮)")
                ok(got["termination"] == "exited", "链式框:点完第二个框后回放走完，不再被误杀")
                ok(len(got["stall_windows"]) == 2,
                   "链式框:两种窗口都进产物(旧逻辑只会留第一种)")
            elif rounds_expect == "static":
                ok(state["clicks"] == 1 + WD.MAX_REPEAT_CLICKS,
                   f"恒量反证:屏幕一点不变就补点到上限即收手(实点 {state['clicks']} 轮，"
                   f"上限 1+{WD.MAX_REPEAT_CLICKS}，不是无限重试)")
                ok(got["termination"] == "stalled_killed", "恒量反证:同一窗口反复出现仍按停滞收手")
                ok(got["windows_at_kill"] == [DIA],
                   "windows_at_kill 记下放弃那一刻的窗口(归因用)")
            else:
                # 11-22 实测 7406 F-Zero：privileged 框点掉一次后屏幕上还是同一张，
                # 旧逻辑"集合没变就认输"，60.3s 直接把整格打死、0 帧。
                ok(state["clicks"] == 2,
                   f"同一张框再出现:补点到第二方才走(实点 {state['clicks']} 轮)")
                ok(got["termination"] == "exited",
                   "同一张框再出现:补点后回放走完，不再被 0 帧误杀")
                ok(len(got["stall_windows"]) == 1,
                   "同一张框再出现:去重后仍只留一条窗口证据")
    finally:
        WD.stall_windows, WD.dismiss_bizhawk_dialog, WD.tree_kill = orig_sw, orig_dm, orig_kl
    ok(WD.MAX_STALL_ROUNDS >= 2, "链式框重试轮次上限在册(防两个框互相反复弹时不收手)")
    ok(WD.MAX_REPEAT_CLICKS >= 1, "同一张框的补点上限在册(补满就收手，不无限点)")

    # 整窗有没有画面（11-22 热门矩阵：MM7 那格 600 帧几乎全黑却 6/7 pass，
    # 七项里没有任何一项看过图。picture_content 补的是"看图"这一格）。
    from PIL import Image as _Img
    import os as _os
    from .record import picture_content as PC, PICTURE_LUMA_MIN as _LM
    with tempfile.TemporaryDirectory() as td_pic:
        def _mk(i, v):
            _Img.new("RGB", (64, 48), (v, v, v)).save(_os.path.join(td_pic, "f%04d.png" % i))
        for i in range(60):
            _mk(i, 0)
        v, why, idx = PC(td_pic, 60)
        ok(str(v).endswith("INCONCLUSIVE") and "全黑" in why,
           "整窗全黑=inconclusive(不是 pass，也不是 fail：黑场可能只是淡入)")
        _mk(55, 200)
        v2, why2, idx2 = PC(td_pic, 60)
        ok(str(v2).endswith("PASS") and 55 in idx2, "有一帧亮就 pass，reason 点名第几帧")
        ok("mean_luma" in why2, "reason 带实测亮度，阈值判错了看得见")
        v3, why3, _ = PC(td_pic, 0)
        ok(str(v3).endswith("INCONCLUSIVE") and "0 帧" in why3, "0 帧窗=无图可看，不猜")
        v4, why4, seen4 = PC(td_pic, 900)   # 虚报 900 帧，实际只有 0..59 号
        ok(str(v4).endswith("INCONCLUSIVE") and seen4 == [0],
           "帧数虚报时只按真存在的 PNG 判定，全黑照旧 inconclusive(不许拿缺图当有图)")
        ok(_LM > 0, "黑场阈值在册(恒量反证:阈值 0 时全黑也算有画面)")

    # ---- 缺芯片固件的静默降级。11-22 的设想是「BizHawk 弹框、点掉后照跑」，这条
    # 夹具保留只为覆盖弹框通道；11-23 真机臂1 证明 BSNES 这条路径根本不弹框，证据
    # 只在 stdout 一句 Served libsnes request（见下面 FW_SERVED29）----
    MMX2_DLG = {"title": "Warning", "texts": ["确定",
                "Couldn't find firmware SNES+CX4.  Will attempt to continue: "
                "Game may function incorrectly without the requested firmware."]}
    PRIV_DLG = {"title": "This EmuHawk is privileged",
                "texts": ["OK", "EmuHawk detected it has Administrator privileges."]}
    fv = WD.firmware_verdict({"dismissed_dialogs": [PRIV_DLG, MMX2_DLG]})
    ok(fv[0] == "inconclusive", "固件闸门:洛克人X2 真实弹框正文=>inconclusive，不是 pass")
    ok(fv[2] == ["SNES+CX4"], "固件闸门:点名固件规格 SNES+CX4")
    ok("降级方式" not in fv[1] and "HLE" not in fv[1],
       "固件闸门:reason 不许替 BizHawk 编降级机制（HLE 是我 11-22 的臆测，dll 字面量没这句）")
    ok("desync=false" in fv[1], "固件闸门:reason 讲明 desync 通过不等于芯片被复刻")
    ok(WD.firmware_verdict({"dismissed_dialogs": [PRIV_DLG], "console_texts": []})[0] == "pass",
       "固件闸门:管理员特权框不算固件降级(恒量反证:见框就降档会连 FC 一起拖下水)")
    # 11-23 ab17/ab18 实测：同一套注册参数，一批 0 框 9.0s、另一批 3 框 91.6s，
    # 两条路径写盘的 config 还逐字节相同 ⇒ 「没弹框」本身不稳定，不能单独当正证。
    # 生产链路里 tas_replay.run_replay 总会写 console_texts（第 515 行，NES 也写），
    # 所以「键都不存在」只可能是绕过 run_replay 直接喂 watch_process 的探针件。
    ok(WD.firmware_verdict({"console_texts": []})[0] == "pass",
       "固件闸门:控制台渠道看过且空的=真无降级证据（NES 这类无固件平台不误伤）")
    ok(WD.firmware_verdict({})[0] == "inconclusive"
       and WD.firmware_verdict(None)[0] == "inconclusive",
       "固件闸门:连渠道都没有=不许 pass（ab17 的 gate:pass 就是直接调 watch_process 少了 console_texts）")
    ok("console_texts" in WD.firmware_verdict({})[1],
       "固件闸门:缺渠道那条 reason 必须点名缺的是哪个渠道，不许只写「无证据」")
    ok(WD.firmware_verdict({"dismissed_dialogs": [{"texts": ["Firmware file not found"]}]})[0] == "inconclusive",
       "固件闸门:正文没点出具体芯片也照样拦(缺证据不等于通过)")
    ok(WD.firmware_specs([{"texts": ["Core not found for SNES_Firmware_CX4, firmware not found"]}])
       == ["SNES_Firmware_CX4"], "固件闸门:BizHawk 固件库键名写法也认")
    ok(WD.firmware_specs("Couldn't find firmware GBA_Firmware_Bios.") == ["GBA_Firmware_Bios"],
       "固件闸门:纯字符串记录也吃得下(旧产物/自测)")
    both = WD.firmware_verdict({"dismissed_dialogs": [MMX2_DLG], "stall_windows": [MMX2_DLG],
                                "windows_at_kill": [MMX2_DLG]})
    ok(both[2] == ["SNES+CX4"], "固件闸门:三处记录同一规格只计一次，不重复刷")

    # ---- 文案换成实测字面量：下面每条正文都从本机 BizHawk 2.9.1 各 dll 的 #US 堆
    # （UTF-16LE）里抠出来，另核 2.3/2.8/2.9/2.10/2.11/2.11.1 一致（说明书 §45）。
    # MMX2_DLG 那句 "SNES+CX4" 是 11-22 凭印象写的：全盘 json 里没有任何跑片产物
    # 出现过固件正文，所以真机证据只有裸名 CX4 这一种写法，判据按真文案重立。----
    FW_MIS = ("Couldn't find firmware CX4.  Will attempt to continue: Game may function "
              "incorrectly without the requested firmware.")
    FW_FATAL29 = "Couldn't find required firmware CX4.  This is fatal because none was provided."
    FW_FATAL211 = "Couldn't find required firmware CX4.  This prevents the core from loading"
    FW_HACKED = "Hacked firmware detected! Firmware might not work!"
    FW_BADLEN = "Bad firmware length detected! Firmware might not work!"
    FW_SATISFY = "Couldn't satisfy firmware request CX4 because none was provided."
    FW_QUOTED23 = "Couldn't find firmware \"SNES:CX4\".  Will attempt to continue: x"
    FW_ASKED = "Core asked for firmware `CX4`"
    FW_SS = "Savestate internal firmware mismatch"
    FW_CONFIG = "Firmware files are usually required and may stop your game from loading"
    for lbl, lit in (("缺失仍继续", FW_MIS), ("名字对内容不对", FW_HACKED),
                     ("坏长度", FW_BADLEN), ("satisfy 请求", FW_SATISFY),
                     ("反引号请求", FW_ASKED), ("存档内固件不符", FW_SS),
                     ("2.3 带引号", FW_QUOTED23)):
        v, w, _sp = WD.firmware_verdict({"console_texts": [lit]})
        ok(v == "inconclusive", f"固件闸门(实测文案):{lbl}=>inconclusive")
        ok("desync=false" in w, f"固件闸门(实测文案):{lbl} reason 仍写清 desync 不背书芯片")
    for lbl, lit in (("2.9 致命", FW_FATAL29), ("2.11 核心加载不了", FW_FATAL211)):
        ok(WD.firmware_verdict({"console_texts": [lit]})[0] == "fail",
           f"固件闸门(实测文案):{lbl}=>fail，不是降一档就完事")
    ok(WD.firmware_specs([FW_QUOTED23]) == ["SNES:CX4"],
       "固件闸门:2.3 的 \"SNES:CX4\" 不被冒号截成 SNES，且长名吃掉短名不重复列")
    ok(WD.firmware_specs([FW_MIS]) == ["CX4"] and WD.firmware_specs([FW_ASKED]) == ["CX4"],
       "固件闸门:BizHawk 真正的请求名是裸 CX4，两种句式都点得出名")
    FW_SERVED29 = 'Served libsnes request for firmware "cx4.rom"'
    ok(WD.firmware_verdict({"console_texts": [FW_SERVED29]})[0] == "inconclusive",
       "固件闸门:11-23 臂1 实测（Firmware 目录清空）只有这句，必须拦成 inconclusive")
    ok(WD.firmware_specs([FW_SERVED29]) == ["cx4.rom"],
       "固件闸门:这句的请求名是裸文件名 cx4.rom，照字面抽，不写成 SNES+CX4")
    ok("HLE" not in WD._FIRMWARE_CLASS_WHY["missing"]
       and "HLE" not in WD._FIRMWARE_CLASS_WHY["served"],
       "固件闸门:两档 reason 的措辞都只准引用 dll 字面量，不准出现我编的机制名")

    ok(WD.firmware_verdict({"console_texts": [FW_CONFIG]})[0] == "pass",
       "固件闸门(恒量反证):固件配置页那句 advisory 不算降级证据")
    # 11-23 ab16 第一版踩的坑：config 的 FirmwareUserSpecifications 被我写成 `"字段": `（空值），
    # BizHawk 解析失败后 BSNES 加载 ROM 抛空引用，弹的是异常框，堆栈里带
    # `BizHawk.Client.Common.FirmwareManager.Do…`。探针正文用子串 firmware 过滤就会把
    # **类名**数成固件警告。生产 marker 全是短语而不是裸 firmware，这里把这点钉住。
    FW_NRE = ("A core accepted the rom, but threw an exception while loading it:\n\n"
              "System.NullReferenceException: 未将对象引用设置到对象的实例。\n"
              "   在 BizHawk.Client.Common.FirmwareManager.DoGetFirmware(String identifier)")
    ok(WD.firmware_verdict({"dismissed_dialogs": [{"texts": [FW_NRE]}],
                            "console_texts": []})[0] == "pass",
       "固件闸门(恒量反证):核心加载异常堆栈里的类名 FirmwareManager 不算固件降级证据")
    ok(WD.firmware_specs([FW_NRE]) == [],
       "固件闸门(恒量反证):异常正文不许抽出固件规格名(抽出来就会去点掉别的芯片的账)")
    ok(WD.firmware_verdict({"dismissed_dialogs": [MMX2_DLG]})[0]
       == WD.firmware_verdict({"console_texts": [MMX2_DLG]})[0],
       "固件闸门:弹框与控制台日志同判据(只盯框会把「压根没弹框」当成「没降级」)")
    _fw_log = Path(tempfile.mkdtemp(prefix="fw_console_")) / "emulator.log"
    _fw_log.write_text("".join("f%04d.png saved.\n" % i for i in range(300))
                       + FW_MIS + "\n" + FW_FATAL29 + "\n", encoding="utf-8")
    _picked = WD.firmware_console_lines(str(_fw_log))
    ok(len(_picked) == 2 and FW_MIS in _picked[0],
       "固件闸门:从每帧刷屏里只挑固件行(300 行噪音不进产物)，命中行去重保序")
    ok(WD.firmware_console_lines(str(_fw_log.parent / "nope.log")) == [],
       "固件闸门:没有日志就返回空，不拿缺文件当有证据")

    # 走真实装配路径：run_full 的检查表里必须有这一格，且缺固件时整片不被洗成 pass。
    from unittest.mock import patch as _patch
    import types as _types
    import tas_replay as _TR
    from . import record as _REC

    # 证据通道必须落在生产回放里：run_replay 得把模拟器控制台日志里的固件行带进
    # watchdog 记录，否则闸门只认弹框、headless 一句话都收不到（11-23 §45 实测：
    # 真机产物里从来没有固件弹框，而 stdout 当初是 DEVNULL 直接丢掉的）。
    with tempfile.TemporaryDirectory() as td_wire:
        wroot = Path(td_wire)
        wmovie = wroot / "m.bk2"
        wmovie.write_bytes(b"fake movie shell")

        class _FakeProc:
            pid = 4242

            def poll(self):
                return 0

            def wait(self, timeout=None):
                return 0

        def _fake_popen(cmd, cwd=None, stdout=None, stderr=None, **kw):
            stdout.write((FW_MIS + "\n").encode("utf-8"))
            stdout.flush()
            return _FakeProc()

        def _fake_watch(proc, work, **kw):
            return {"termination": "exited", "elapsed": 1.0, "dismissed": 0, "stalls": 0,
                    "last_frame": 3, "dismissed_dialogs": [], "stall_windows": [],
                    "windows_at_kill": []}

        with _patch.object(_TR.subprocess, "Popen", _fake_popen), \
             _patch.object(_TR.watchdog, "watch_process", _fake_watch), \
             _patch.object(_TR, "force_core", lambda *a, **k: None), \
             _patch.object(_TR, "assert_rom_matches_movie", lambda *a: None), \
             _patch.object(_TR, "materialize_movie", lambda s, d: False), \
             _patch.object(_TR, "materialize_rom", lambda s, d: False):
            _wres = _TR.run_replay(str(wmovie), str(wmovie), "BSNES", "SNES",
                                   str(wroot / "bizhawk"), 3, work=str(wroot / "w"))
        ok(_wres["watchdog"].get("console_texts")
           and FW_MIS in _wres["watchdog"]["console_texts"][0],
           "固件闸门(生产路径):run_replay 真把控制台固件行带进了 watchdog 记录")
        ok(WD.firmware_verdict(_wres["watchdog"])[0] == "inconclusive",
           "固件闸门(生产路径):这份 watchdog 记录真能把该跑判成 inconclusive")
        ok((wroot / "w" / "emulator.log").is_file(),
           "固件闸门(生产路径):模拟器控制台有落盘件可查，不再 DEVNULL 丢掉")

    # ---- work 目录必须全 ASCII（11-23 连踩两次：中文 work 让 cap.lua 的 io.open
    # 返回 nil，整跑只出 1 帧，外层看着像模拟器死了）----
    _hit = {"popen": 0}

    def _sentinel_popen(*a, **k):
        _hit["popen"] += 1
        raise RuntimeError("SENTINEL_POPEN")

    with tempfile.TemporaryDirectory() as td_asc:
        for wname, want, lbl in (("work_ok", RuntimeError, "纯 ASCII"),
                                 ("中文work", ValueError, "含中文")):
            got = None
            try:
                with _patch.object(_TR.subprocess, "Popen", _sentinel_popen),                      _patch.object(_TR.watchdog, "watch_process", lambda *a, **k: {}),                      _patch.object(_TR, "force_core", lambda *a, **k: None),                      _patch.object(_TR, "assert_rom_matches_movie", lambda *a: None),                      _patch.object(_TR, "materialize_movie", lambda s, d: False),                      _patch.object(_TR, "materialize_rom", lambda s, d: False):
                    _TR.run_replay("m.bk2", "r.sfc", "BSNES", "SNES", td_asc, 10,
                                   work=str(Path(td_asc) / wname))
            except Exception as _ge:
                got = _ge
            ok(type(got) is want,
               "ASCII 闸门:%s work 应抛 %s（实得 %s）" % (lbl, want.__name__, type(got).__name__))
        ok(_hit["popen"] == 1,
           "ASCII 闸门:拦在 Popen 之前（只有 ASCII 那臂摸得到进程，中文臂不留半个模拟器）")

    # ---- ROM md5 闸门（2026-11-24：515M 用错镜像回放 16 分钟整段脱轨，画面看着
    # 像正常游玩。Header.txt 声明的 md5 与实件两种口径都对不上就拒跑，拦在启动前）----
    import zipfile as _zf

    def _md5hex(b):
        return hashlib.md5(b).hexdigest().upper()

    with tempfile.TemporaryDirectory() as td_rmd:
        _rr = Path(td_rmd)
        _head = b"NES\x1a" + bytes(range(12))
        _body = bytes(range(32, 64))
        _exp = _md5hex(_body)
        _bk2 = _rr / "m.bk2"
        with _zf.ZipFile(_bk2, "w") as _z:
            _z.writestr("Header.txt", "MD5 %s\nSHA1 deadbeef\n" % _exp)
            _z.writestr("Input Log.txt", "x\n")
        _rom_ok = _rr / "ok.nes"
        _rom_ok.write_bytes(_head + _body)
        _rom_bad = _rr / "bad.nes"
        _rom_bad.write_bytes(_head + bytes(range(200, 232)))
        ok(_TR.expected_rom_md5(str(_bk2)) == _exp,
           "ROM md5 闸门:合成 bk2 Header.txt 的 MD5 行可读出(去头口径)")
        ok(_TR.expected_rom_md5(str(_rr / "nope.bk2")) == "",
           "ROM md5 闸门:录像读不到声明时返回空串(不设闸,未知格式不拦)")
        ok(_TR.assert_rom_matches_movie(str(_bk2), str(_rom_ok)) == _exp,
           "ROM md5 闸门:去头 md5 命中 → 放行并返回期望值")
        _got = None
        try:
            _TR.assert_rom_matches_movie(str(_bk2), str(_rom_bad))
        except Exception as _ge:
            _got = _ge
        ok(type(_got) is RuntimeError and "ROM 与录像不匹配" in str(_got),
           "ROM md5 闸门:错镜像臂 RuntimeError 且报文点名期望/实件 md5")
        _rom_raw = _rr / "raw.bin"
        _rom_raw.write_bytes(bytes(range(10)))
        _exp_raw = _md5hex(bytes(range(10)))
        _bk2_raw = _rr / "raw.bk2"
        with _zf.ZipFile(_bk2_raw, "w") as _z:
            _z.writestr("Header.txt", "MD5 %s\n" % _exp_raw)
        ok(_TR.assert_rom_matches_movie(str(_bk2_raw), str(_rom_raw)) == _exp_raw,
           "ROM md5 闸门:非 iNES 实件按整文件 md5 口径命中")

        _hit = {"popen": 0}

        def _sentinel_popen_md5(*a, **k):
            _hit["popen"] += 1
            raise RuntimeError("SENTINEL_ROMMD5")

        def _rmd_arm(mv, rm):
            with _patch.object(_TR.subprocess, "Popen", _sentinel_popen_md5), \
                 _patch.object(_TR.watchdog, "watch_process", lambda *a, **k: {}), \
                 _patch.object(_TR, "force_core", lambda *a, **k: None):
                _TR.run_replay(str(mv), str(rm), "BSNES", "SNES",
                               str(_rr / "bh"), 3, work=str(_rr / "w"))

        _got = None
        try:
            _rmd_arm(_bk2, _rom_bad)
        except Exception as _ge:
            _got = _ge
        ok(type(_got) is RuntimeError and "ROM 与录像不匹配" in str(_got)
           and _hit["popen"] == 0,
           "ROM md5 闸门(生产路径):错镜像在 run_replay 里拦在 Popen 之前")
        _got = None
        try:
            _rmd_arm(_bk2, _rom_ok)
        except Exception as _ge:
            _got = _ge
        ok(type(_got) is RuntimeError and "SENTINEL_ROMMD5" in str(_got)
           and _hit["popen"] == 1,
           "ROM md5 闸门(生产路径):匹配臂穿过闸门一路走到 Popen(SENTINEL)")
    with tempfile.TemporaryDirectory() as td_fw:
        froot = Path(td_fw)
        fdir = froot / "frames"
        fdir.mkdir()
        from PIL import Image as _FImg
        for i in range(60):
            _FImg.new("RGB", (32, 24), (200, 200, 200)).save(fdir / f"f{i:04d}.png")
        (froot / "cap.txt").write_text("status=complete\n", encoding="utf-8")
        (froot / "game.sfc").write_bytes(b"SNES fixture rom")
        bk2 = froot / "movie.bk2"
        bk2.write_bytes(b"not a real zip")   # slot_conflict 读不到 Header 就不拦
        be = _types.SimpleNamespace(bizhawk_dir=str(froot))

        def _fake_replay(dialogs):
            def _inner(*a, **k):
                return {"desync": False, "termination": "complete",
                        "report": "status=complete n=60 mode=PLAY",
                        "work": str(froot), "frames_dir": str(fdir), "n_frames": 60,
                        "watchdog": {"dismissed": len(dialogs), "dismissed_dialogs": dialogs,
                                     "stall_windows": [], "windows_at_kill": [],
                                     "console_texts": [],
                                     "stalls": 0, "elapsed": 1.0, "returncode": 0}}
            return _inner

        def _enc(fd, fps, out, ffmpeg=None, **kw):
            Path(out).write_bytes(b"synthetic clip")
            return out

        probe = {"streams": [{"codec_type": "video", "nb_frames": 60}],
                 "format": {"duration": 1.0}}
        for arm, dialogs, want in (("缺固件", [PRIV_DLG, MMX2_DLG], "inconclusive"),
                                   ("无降级", [PRIV_DLG], "pass")):
            with _patch.object(_TR, "run_replay", _fake_replay(dialogs)), \
                 _patch.object(_TR, "encode_video", _enc), \
                 _patch.object(_REC, "_probe_video", lambda *a, **k: probe):
                run = _REC.run_full(be, {"profile_id": "fw_fixture"}, str(bk2),
                                    str(froot / "game.sfc"), str(froot / arm),
                                    frames=60, system="SNES", core="BSNES")
            rows = {c["check_id"]: c for c in run["verification"]["checks"]}
            ok("chip_firmware_missing" in rows, f"固件闸门({arm}):生产装配路径真的产出了这一格")
            ok(rows["chip_firmware_missing"]["verdict"] == want,
               f"固件闸门({arm}):该格判 {want}")
            if want == "inconclusive":
                ok("SNES+CX4" in rows["chip_firmware_missing"]["reason"],
                   "固件闸门(缺固件):规格名落在产物 reason 里")
                ok(run["verification"]["verdict"] != "pass",
                   "固件闸门(缺固件):出片也没把整片验收费洗成 pass")



def test_fceux():
    import base64
    import hashlib
    import json
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
            ok(log[4] == "|P.|...R....|", "fceux：power+Right 帧渲染 |P.|...R....|")
            ok("|p.|" not in "\n".join(log),
               "fceux：反证—小写 p 不是 BizHawk 的 Power 助记符(Bk2MnemonicLookup Power='P')")
            ok(log[3] == "|.r|........|", "fceux：reset 帧渲染 |.r|")
            ok("PAL 0" in hdr, "fceux：palFlag 原文进 Header(照抄 Fm2Import，缺键会按 60Hz 跑)")
            ss = z.read("SyncSettings.json").decode()
            ok('"NesLeftPort": "ControllerNES"' in ss
               and '"NesRightPort": "UnpluggedNES"' in ss,
               "fceux：SyncSettings 端口映射(port0=1/port1=0)")
            ok(json.loads(ss)["o"] == {
                "$type": "BizHawk.Emulation.Cores.Nintendo.NES.NES+NESSyncSettings, "
                         "BizHawk.Emulation.Cores",
                "BoardProperties": {}, "RegionOverride": 0,
                "Controls": {"Famicom": False, "NesLeftPort": "ControllerNES",
                             "NesRightPort": "UnpluggedNES", "FamicomExpPort": "UnpluggedFam"},
                "InitialWRamStatePattern": None,
                "VSDipswitches": {f"Dip_Switch_{i}": False for i in range(1, 9)}},
               "fceux：SyncSettings 与 BizHawk 2.8 原生 NES bk2 逐字段相同(11-21 实测样本 4751)")
        # PAL 电影：palFlag 1 必须写成 PAL 1，而不是只留注释
        pal = td / "pal.fm2"
        pal.write_text(fm2.replace("palFlag 0", "palFlag 1"), encoding="utf-8")
        with zipfile.ZipFile(F.to_bk2(F.parse_fm2(pal), td / "pal.bk2",
                                      bizhawk_version="2.8")) as z:
            ok("PAL 1" in z.read("Header.txt").decode(), "fceux：palFlag 1→Header PAL 1")
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

        # ---- D. FCM 二进制 v2 解析（11-23 用 5 份真片逐字段钉死；前两版夹具都把当时实现的 bug 供成了"通过"）----
        # 真表：12 帧数 / 16 rerecord / 20 输入字节长度 / 24 内嵌 FCS 存档块起始 / 28 输入记录起始 / 32 MD5 / 48 emuVersion
        # RLE：update 位 7=命令/控制、位 5-6=后面跟几个间隔字节。一条记录 = 上一条的状态沿用 gap 帧，
        #      本条状态从第 gap+1 帧起生效 ⇒ sum(gap)==声明帧数（418M/715M/726M 实测字节正好吃到终点）。
        fmd5 = bytes.fromhex("00112233445566778899aabbccddeeff")
        RST = bytes([0x81])                            # bit7=1 + 命令 1 = Reset，delta=0

        def ctrl(button, gap):
            """控制器记录：bit7=0，低 3 位=按钮号(0=A/1=B)，位 3-4=手柄，位 5-6=间隔字节个数。"""
            if gap == 0:
                return bytes([button])
            if gap < 256:
                return bytes([0x20 | button, gap])
            return bytes([0x40 | button, gap & 0xFF, (gap >> 8) & 0xFF])

        def fcm_bytes(recs, nframes, first_frame_field=None, input_len=None,
                      state_pad=0, author_field=b"Auth\x00"):
            pre = b"FCM\x1a" + struct.pack("<I", 2) + bytes([2]) + b"\x00\x00\x00"
            pre += struct.pack("<I", nframes) + struct.pack("<I", 7)
            pre += struct.pack("<I", len(recs) if input_len is None else input_len)
            ff_pos = len(pre)                      # 24 = FCS 块起始, 28 = 输入记录起始
            pre += struct.pack("<I", 0) + struct.pack("<I", 0)
            pre += fmd5 + struct.pack("<I", 21040) + b"TestGame\x00" + author_field
            state_off = len(pre)
            pre += b"FCS\x00" + b"\x00" * (12 + state_pad)
            ff = len(pre)
            pre = (pre[:ff_pos] + struct.pack("<I", state_off)
                   + struct.pack("<I", ff if first_frame_field is None else first_frame_field)
                   + pre[ff_pos + 8:])
            return pre + recs, state_off, ff

        recs = RST + ctrl(0, 1) + ctrl(0, 3)          # 帧 0=Reset 中立，帧 1..3=A，共 4 帧
        pre, state_off, ff = fcm_bytes(recs, 4)
        fcm = td / "t.fcm"
        fcm.write_bytes(pre)
        fm = F.parse_fcm(fcm)
        ok(fm.n_frames == 4 and fm.source_format == "fcm", "fceux：FCM v2 帧数/格式")
        ok(not fm.errors, "fceux：合规 FCM 不报错(空存档块 16 字节)")
        ok(fm.frames[0]["cmd"] == "reset" and not fm.frames[0]["p1"],
           "fceux：Reset 命令落在第 0 帧")
        ok([f["p1"] for f in fm.frames[1:]] == [{"A"}] * 3,
           "fceux：FCM 记录的状态从 gap 之后第一帧起生效(1 帧中立 + 3 帧 A)")
        ok(fm.md5 == fmd5.hex() and fm.game_name == "TestGame"
           and fm.author == "Auth" and fm.rerecord == 7,
           "fceux：FCM MD5@32/游戏名/作者/rerecord")
        ok(struct.unpack_from("<I", pre, 28)[0] == ff and struct.unpack_from("<I", pre, 24)[0] == state_off,
           "fceux：反证—24 是 FCS 块、28 才是输入起始(旧代码把 24-27 当 first_frame 会错 16 字节)")
        # 相位：按下与松开各占 2 帧，变化不许算进自己那条的 gap（算进去就整片提前一记录）
        pre_ph, _, _ = fcm_bytes(RST + ctrl(0, 2) + ctrl(0, 2), 4)
        (td / "phase.fcm").write_bytes(pre_ph)
        ph = F.parse_fcm(td / "phase.fcm")
        ok([("r" if f["cmd"] else "") + ("A" if f["p1"] else "") for f in ph.frames] == ["r", "", "A", "A"],
           "fceux：反证—gap 帧沿用上一条状态(第 0 帧只有 Reset，A 从第 2 帧起)")
        # 帧数不变量：声明 10 帧但记录只覆盖 4 帧 => 拒（旧实现每条记录多产 1 帧，515M 多出 4684 帧）
        pre_short, _, _ = fcm_bytes(recs, 10)
        (td / "short.fcm").write_bytes(pre_short)
        ok(any("帧数不符" in e for e in F.parse_fcm(td / "short.fcm").errors),
           "fceux：解出帧数 != 头声明帧数 => 记 error")
        # 内嵌存档非空 => 从存档起始，拒
        pre_state, _, _ = fcm_bytes(recs, 4, state_pad=64)
        (td / "state.fcm").write_bytes(pre_state)
        ms = F.parse_fcm(td / "state.fcm")
        ok(any("从存档起始" in e for e in ms.errors),
           "fceux：FCM 内嵌存档非空(>16 字节)=>记 error")
        # 输入长度越界 => 拒
        pre_ov, _, _ = fcm_bytes(recs, 4, input_len=99999)
        (td / "over.fcm").write_bytes(pre_ov)
        ok(any("越界" in e for e in F.parse_fcm(td / "over.fcm").errors),
           "fceux：FCM 输入长度越界=>记 error")
        # 把输入起始写成 FCS 块偏移（=11-23 修复前的口径）：'F'=0x46 的 delta=2 折出 67 帧中立，且帧数对不上
        pre_bad, _, _ = fcm_bytes(recs, 3000, first_frame_field=state_off)
        (td / "shift.fcm").write_bytes(pre_bad)
        mshift = F.parse_fcm(td / "shift.fcm")
        ok(mshift.n_frames == 3000 and any("没吃完" in e for e in mshift.errors)
           and not any(f["p1"] for f in mshift.frames[:60]),
           "fceux：反证—起点错位时输入体吃不完且前 60 帧无按键(闸门抓得到)")
        # 输入体全中立（没有任何命令、只有一条超长 gap）：帧数对得上，但 bk2 必须拒
        pre_q, _, _ = fcm_bytes(ctrl(0, 3000), 3000)
        (td / "quiet.fcm").write_bytes(pre_q)
        mq = F.parse_fcm(td / "quiet.fcm")
        ok(mq.n_frames == 3000 and not mq.errors and
           not any(f["p1"] or f["p2"] or f["cmd"] for f in mq.frames[:F.QUIET_START_LIMIT]),
           "fceux：反证—死输入日志的帧数照样对得上，只有中立判据抓得到")
        try:
            F.to_bk2(mq, td / "quiet.bk2"); ok(False, "fceux：全中立输入应拒绝写 bk2")
        except F.ConversionError as e:
            ok("全中立" in str(e), "fceux：to_bk2 拦下死输入日志")
        # 头部字段里的换行不许把一行头变成两行
        pre_nl, _, _ = fcm_bytes(recs, 4, author_field=b"Title A\nTitle B\x00")
        nl = td / "nl.fcm"
        nl.write_bytes(pre_nl)
        mn = F.parse_fcm(nl)
        with zipfile.ZipFile(F.to_bk2(mn, td / "nl.bk2", bizhawk_version="2.8")) as z:
            lines = z.read("Header.txt").decode().splitlines()
            ok("Title A Title B" in "".join(l for l in lines if l.startswith("Author ")),
               "fceux：FCM 影片名含换行=>压平成一行 Author")
            ok(not any(l.startswith("Title B") for l in lines),
               "fceux：反证—换行不产生第二条无键名头行")

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
        ed, en, ec = R.emulator_match("FCEUX 2.2.3", {"2.8": "/x"})
        ok(ed is None and "非 BizHawk" in en and "taspipe.fceux" in en
           and ec is FailureCode.UNSUPPORTED_CAPABILITY,
           "fceux接线：emulator_match FCEUX 提示转换且保留'非 BizHawk'，码是管线不是缺资源")
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

        # ---- G. 核心选择：照抄同 ROM 原生片，不写死 NesHawk（11-21 7429 A/B）----
        import zipfile as _zf
        qn_sync = json.dumps({"o": {
            "$type": "BizHawk.Emulation.Cores.Consoles.Nintendo.QuickNES."
                     "QuickNES+QuickNESSyncSettings, BizHawk.Emulation.Cores",
            "LeftPortConnected": True, "RightPortConnected": False}})
        sib = lib / "movies" / "NES" / "8888.bk2"
        with _zf.ZipFile(sib, "w") as z:
            z.writestr("Header.txt", "Platform NES\nSHA1 " + sha1 +
                       "\nCore QuickNes\nBoardName mmc3\nemuVersion Version 2.9\n")
            z.writestr("SyncSettings.json", qn_sync)
            z.writestr("Input Log.txt", "[Input]\n|0|........|\n[/Input]\n")
        sib_pub = {"id": "8888", "platform": "NES", "emulator": "EmuHawk 2.9.0 (Core: QuickNES)",
                   "movie_ext": "bk2", "local_movie": "movies/NES/8888.bk2",
                   "rom_sha1": sha1, "game": "Test Game", "version_id": "v9999"}
        pubs_doc = json.loads((lib / "publications.json").read_text(encoding="utf-8"))
        pubs_doc["publications"]["8888"] = sib_pub
        (lib / "publications.json").write_text(json.dumps(pubs_doc), encoding="utf-8")
        F._NATIVE_INDEX_CACHE.clear()
        ref = F.native_reference(sha1, lib=lib, exclude="9999")
        ok(ref and ref["pub_id"] == "8888" and ref["core"] == "QuickNes"
           and ref["board"] == "mmc3" and ref["emu_version"] == "2.9"
           and ref["quicknes_style"] == "connected",
           "fceux核心：native_reference 取到同 SHA1 原生片的 Core/Board/版本/端口写法")
        ok(F.native_reference("0" * 40, lib=lib) is None,
           "fceux核心：SHA1 无原生片时 native_reference 给 None(不臆造)")
        # 同 ROM 有两部原生片：低 id 那部落在实测卡核的 2.3.0，须优先选可驱动的那部
        with _zf.ZipFile(lib / "movies" / "NES" / "7777.bk2", "w") as z:
            z.writestr("Header.txt", "Platform NES\nSHA1 " + sha1 +
                       "\nCore NesHawk\nemuVersion Version 2.3.0\n")
            z.writestr("SyncSettings.json", json.dumps({"o": {"$type": "x"}}))
            z.writestr("Input Log.txt", "[Input]\n|0|........|\n[/Input]\n")
        pubs_doc["publications"]["7777"] = {
            "id": "7777", "platform": "NES", "emulator": "BizHawk 2.3.0",
            "movie_ext": "bk2", "local_movie": "movies/NES/7777.bk2",
            "rom_sha1": sha1, "game": "Test Game", "version_id": "v9999"}
        (lib / "publications.json").write_text(json.dumps(pubs_doc), encoding="utf-8")
        F._NATIVE_INDEX_CACHE.clear()
        ok(F.native_reference(sha1, lib=lib, exclude="9999")["pub_id"] == "7777",
           "fceux核心：不给 bizhawk_dirs 时按最小 pub_id 取参照(可复现)")
        picked = F.native_reference(sha1, lib=lib, exclude="9999",
                                    bizhawk_dirs={"2.3": "/e/BizHawk-2.3",
                                                  "2.9": "/e/BizHawk-2.9"})
        ok(picked["pub_id"] == "8888" and picked["core"] == "QuickNes",
           "fceux核心：同 ROM 多张原生片时优先本机已装且未卡核的(避开实测 0 帧的 2.3.x)")
        ok(F.native_reference(sha1, lib=lib, exclude="9999",
                              bizhawk_dirs={"2.3": "/e/BizHawk-2.3"})["pub_id"] == "7777",
           "fceux核心：反证—只有卡核版本可选时仍给参照，不静默换成别的")
        (lib / "movies" / "NES" / "7777.bk2").unlink()
        del pubs_doc["publications"]["7777"]
        (lib / "publications.json").write_text(json.dumps(pubs_doc), encoding="utf-8")
        F._NATIVE_INDEX_CACHE.clear()
        F.convert_pub("9999", lib=lib)          # 默认 core=auto
        with _zf.ZipFile(lib / "_converted" / "NES" / "9999.bk2") as z:
            h = z.read("Header.txt").decode()
            ss_auto = z.read("SyncSettings.json").decode()
            log_auto = z.read("Input Log.txt").decode()
        ok("Core QuickNes" in h and "BoardName mmc3" in h
           and "emuVersion Version 2.9" in h,
           "fceux核心：auto 写 QuickNes+mmc3+2.9(而非硬写 NesHawk/2.8)")
        ok(json.loads(ss_auto)["o"].get("$type", "").endswith("QuickNESSyncSettings, "
                                                             "BizHawk.Emulation.Cores")
           and json.loads(ss_auto)["o"]["LeftPortConnected"] is True
           and json.loads(ss_auto)["o"]["RightPortConnected"] is False,
           "fceux核心：QuickNes 件写 QuickNES+QuickNESSyncSettings，端口照 fm2 port0/port1")
        F.convert_pub("9999", lib=lib, core="NesHawk")
        with _zf.ZipFile(lib / "_converted" / "NES" / "9999.bk2") as z:
            h_legacy = z.read("Header.txt").decode()
            log_legacy = z.read("Input Log.txt").decode()
        ok("Core NesHawk" in h_legacy and "BoardName mmc3" not in h_legacy,
           "fceux核心：显式 core=NesHawk 保持旧字节口径(不带原生片板型)")
        ok(log_auto == log_legacy,
           "fceux核心：反证—换核心只动 Header/Sync，输入日志逐字节不变(问题不在转换内容)")
        # ---- G2. 子帧核心不能吃帧量化输入（11-21 SMB 1715 继承 6012 的 SubNESHawk 实测）----
        with _zf.ZipFile(sib, "w") as z:
            z.writestr("Header.txt", "Platform NES\nSHA1 " + sha1 +
                       "\nCore SubNESHawk\nBoardName NROM\nemuVersion Version 2.9.1\n")
            z.writestr("SyncSettings.json", json.dumps({"o": {"$type": "x"}}))
            z.writestr("Input Log.txt", "[Input]\nLogKey:#Reset Cycle|Power|Reset|#P1 Up|\n"
                                        "|    0,..|.....|\n[/Input]\n")
        F._NATIVE_INDEX_CACHE.clear()
        ok(F.native_reference(sha1, lib=lib, exclude="9999")["core"] == "SubNESHawk",
           "fceux核心：参照片确实是 SubNESHawk(下面拒绝的前提成立)")
        (lib / "_converted" / "NES" / "9999.bk2").unlink()
        raised = None
        try:
            F.convert_pub("9999", lib=lib)
        except F.ConversionError as exc:
            raised = str(exc)
        ok(raised and "子帧核心" in raised and "8888" in raised,
           "fceux核心：auto 继承到子帧核心=>拒写并点名参照片，不产出废文件")
        ok(not (lib / "_converted" / "NES" / "9999.bk2").exists(),
           "fceux核心：拒写=真没落盘，不是写完再报错")
        rc_sub = None
        try:
            F.to_bk2(F.parse_movie(lib / "movies" / "NES" / "9999.fm2"),
                     lib / "_converted" / "NES" / "直写.bk2", core="SubNESHawk")
        except F.ConversionError as exc:
            rc_sub = str(exc)
        ok(rc_sub and "329" in rc_sub,
           "fceux核心：绕过 convert_pub 直接 to_bk2 也一样拦(闸门在写手上，不在调用方)")
        ok(not (lib / "_converted" / "NES" / "直写.bk2").exists(),
           "fceux核心：直写被拦时也没留下半个文件")
        rc = F.convert_pub("9999", lib=lib, core="NesHawk")
        ok(rc["core"] == "NesHawk" and (lib / "_converted" / "NES" / "9999.bk2").is_file(),
           "fceux核心：反证—同一部片显式换帧量化核心照旧能转(拦的是核心不是这部片)")
        del pubs_doc["publications"]["8888"]
        (lib / "publications.json").write_text(json.dumps(pubs_doc), encoding="utf-8")
        sib.unlink()
        F._NATIVE_INDEX_CACHE.clear()
        rc = F.convert_pub("9999", lib=lib)
        ok(rc["core"] == "NesHawk" and rc["bizhawk_version"] == "2.8"
           and "无同 ROM 原生片" in rc["core_source"],
           "fceux核心：查不到参照片=>退回 NesHawk/2.8 并如实登记 core_source")
        port_sync = json.dumps({"o": {"$type": "BizHawk.Emulation.Cores.Consoles."
                                          "Nintendo.QuickNES.QuickNES+QuickNESSyncSettings, "
                                          "BizHawk.Emulation.Cores",
                                      "Port1": 1, "Port2": 1}})
        with _zf.ZipFile(sib, "w") as z:
            z.writestr("Header.txt", "Platform NES\nSHA1 " + sha1 +
                       "\nCore quickerNES\nBoardName mmc1\nemuVersion Version 2.10\n")
            z.writestr("SyncSettings.json", port_sync)
            z.writestr("Input Log.txt", "[Input]\n|0|........|\n[/Input]\n")
        pubs_doc["publications"]["8888"] = sib_pub
        (lib / "publications.json").write_text(json.dumps(pubs_doc), encoding="utf-8")
        F._NATIVE_INDEX_CACHE.clear()
        rp = F.convert_pub("9999", lib=lib)
        with _zf.ZipFile(lib / "_converted" / "NES" / "9999.bk2") as z:
            ssp = json.loads(z.read("SyncSettings.json").decode())["o"]
        ok(rp["core"] == "quickerNES" and rp["board"] == "mmc1"
           and rp["bizhawk_version"] == "2.10" and ssp.get("Port1") == 1
           and "LeftPortConnected" not in ssp,
           "fceux核心：2.10 的 quickerNES 用 Port1/Port2 写法(两种 QuickNES 写法不混用)")
        F._NATIVE_INDEX_CACHE.clear()


def _synthetic_nes_lib(td, game="Contra", pid="9999", rom_sha1=None):
    """隔离夹具：建一个只含一条 NES 出版物的 lib（真 bk2 + 真 ROM + publications.json）。
    不写任何真实状态；返回 (lib, pub, sha1, rom_path, bk2_path)。rom_sha1 可指定为不匹配值
    以测预筛/阻塞。BizHawk 目录由调用方 patch R.discover_bizhawk 注入（不依赖真机安装）。
    默认作品名用名单上的《魂斗罗》：编排层的选题闸门按作品身份判冷门，
    冷门名会把本夹具的「应 ready」断言变成 blocked，测的就不是原来那件事了。"""
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


def test_replay_speed_tier():
    """unthrottled 档只改墙钟、不改帧序；档位必须进 report 且非法值当场拒。"""
    from . import control_runtime as CR
    cfg = {"Unthrottled": False, "ClockThrottle": True, "SoundEnabled": True}
    CR.apply_speed(cfg, "realtime")
    ok(cfg == {"Unthrottled": False, "ClockThrottle": True, "SoundEnabled": True},
       "speed=realtime 不动节流配置(默认臂字节不变)")
    out = CR.apply_speed({"Unthrottled": False, "ClockThrottle": True}, "unthrottled")
    ok((out["Unthrottled"], out["ClockThrottle"], out["VSyncThrottle"], out["SoundEnabled"],
        out["RunLuaDuringTurbo"]) == (True, False, False, False, True),
       "speed=unthrottled 关时钟节流+关声音+允许 turbo 期跑 Lua")
    try:
        CR.apply_speed({}, "max")
        ok(False, "speed 未知档位应抛 RuntimeBlocked")
    except CR.RuntimeBlocked:
        ok(True, "speed 未知档位当场 RuntimeBlocked，不静默退回 realtime")
    base = {"Unthrottled": False, "ClockThrottle": True, "FrameSkip": 0}
    ok(CR.apply_speed(dict(base), "unthrottled", 0)["FrameSkip"] == 0,
       "frameskip=0 不动 _configure 已写的 FrameSkip=0")
    ok(CR.apply_speed(dict(base), "unthrottled", 8)["FrameSkip"] == 8,
       "frameskip=8 写进 config（只跳渲染，实测截图与 RAM 仍逐帧同源）")
    for bad in (61, -1, "8", 8.0):
        try:
            CR.apply_speed(dict(base), "unthrottled", bad)
            ok(False, f"frameskip={bad!r} 应拒绝")
        except CR.RuntimeBlocked:
            ok(True, f"frameskip={bad!r} 当场 RuntimeBlocked，不静默夹紧")


def test_zero_frame_core_identity_gate():
    import json
    import tempfile
    import zipfile
    from pathlib import Path
    from unittest.mock import patch
    from . import control_runtime as CR
    from .schema import core_identity_expectation

    expected = core_identity_expectation("SNES", "BSNES")
    sync = {"o": {"$type": expected["sync_type"], "LeftPort": 1, "RightPort": 1}}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source, clone, work = root / "source", root / "clone", root / "work"
        source.mkdir(); clone.mkdir(); work.mkdir()
        (source / "config.ini").write_text("{}", encoding="utf-8")
        program = {"system": "SNES", "core": "BSNES", "core_identity": expected,
                   "bizhawk": str(source), "speed": "unthrottled", "frameskip": 0}
        with patch("tas_replay.force_core"):
            CR._configure(source, clone, program, state_sync=sync)
        cfg = json.loads((clone / "config.ini").read_text(encoding="utf-8"))
        adopted = cfg["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.SNES.LibsnesCore"]
        ok(adopted == sync["o"] and adopted["RightPort"] == 1,
           "状态同步设置在启动前原样采用，右端口不再被隔离默认值覆盖")
        wrong = {"o": {"$type": core_identity_expectation("SNES", "Snes9x")["sync_type"]}}
        try:
            with patch("tas_replay.force_core"):
                CR._configure(source, clone, program, state_sync=wrong)
            ok(False, "状态 CLR 类型不符应在启动前拒绝")
        except CR.RuntimeBlocked:
            ok(True, "状态 CLR 类型不符在启动前拒绝")

        identity = work / "identity.state"
        with zipfile.ZipFile(identity, "w") as state:
            state.writestr("SyncSettings.json", json.dumps(sync))
        (work / "emuhawk.log").write_text("Mouting `libsnes.wbx` @123\n", encoding="utf-8")
        report = {"core_identity_expectation": expected}
        request = {"token": "a" * 32, "state": str(identity), "frame": 0}
        CR._verify_identity_request(request, work, "a" * 32, report)
        reply = json.loads((work / "identity_reply.json").read_text(encoding="utf-8"))
        ok(reply["allow"] is True and report["core_identity"] == "pass",
           "零帧状态 CLR 类型与 Waterbox 日志一致才回复身份放行")

        (work / "identity_reply.json").unlink()
        (work / "identity_request.json").write_text(json.dumps(request), encoding="utf-8")
        class WaitingProcess:
            def poll(self):
                return 0 if (work / "identity_reply.json").exists() else None
            def wait(self, timeout=None):
                return 0
        waiting_report = {"core_identity": "unverified", "core_identity_expectation": expected}
        CR._wait(WaitingProcess(), work, "a" * 32, CR.time.monotonic() + 5, waiting_report)
        ok(waiting_report["core_identity"] == "pass",
           "报告预置 unverified 时仍处理首个身份请求，不能误判已经回复")

        (work / "emuhawk.log").write_text("Mouting `snes9x.wbx` @123\n", encoding="utf-8")
        report = {"core_identity_expectation": expected}
        try:
            CR._verify_identity_request(request, work, "a" * 32, report)
            ok(False, "请求 BSNES 实际加载 Snes9x 必须拒绝")
        except CR.RuntimeBlocked:
            ok(report["core_identity"] == "fail" and
               json.loads((work / "identity_reply.json").read_text(encoding="utf-8"))["allow"] is False,
               "请求 BSNES 实际加载 Snes9x 时身份回执为 fail")

    src = (Path(__file__).resolve().parent / "control_runtime.lua").read_text(encoding="utf-8")
    init = src[src.index("local function initialize()"):src.index("local function start_session()")]
    ok("identity_request.json" in init and "frame() ~= 0" in init,
       "Lua 在加载起始状态或电影之前保存并请求核验零帧身份")
    ok(src.index("if identity_gate and not identity_poll()") < src.index("if gate and not gate_poll()"),
       "身份闸先于状态准入闸，未通过不能继续加载或推进")


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

        # ---- 第三条轴接进获取层：补 ROM 值不值得，跟能不能判通关是两件事 ----
        (td / "movies" / "NES").mkdir(parents=True)
        pub_native = {"id": "2", "game": "Test2", "platform": "NES", "rom_sha1": sha1,
                      "local_movie": "movies/NES/2.bk2"}
        (td / "movies" / "NES" / "2.bk2").write_bytes(b"BK2")
        a5 = AQ.acquire(pub_native, lib=td, rom_idx={}, cheat_lib=clib)
        ok(a5["fidelity"]["completion_verdict"] == "judgeable_pending_evidence"
           and a5["acquire_advice"] is None,
           "acquire：原生 bk2 缺 ROM 照常进清单，不劝退（恒量正对照）")
        pub_fceux = {"id": "1", "game": "Test", "platform": "NES", "rom_sha1": sha1,
                     "local_movie": "movies/NES/1.fm2"}
        (td / "movies" / "NES" / "1.fm2").write_bytes(b"FM2")
        (td / "_converted" / "NES").mkdir(parents=True)
        (td / "_converted" / "NES" / "1.bk2").write_bytes(b"CONV")
        a6 = AQ.acquire(pub_fceux, lib=td, rom_idx={}, cheat_lib=clib)
        ok(a6["fidelity"]["completion_verdict"] == "not_judgeable_locally",
           "acquire：FCEUX 内层片记 not_judgeable_locally，与 registry 同一支函数")
        ok(a6["acquire_advice"] and "通关风险高" in a6["acquire_advice"]
           and "别拿这一格当判决" in a6["acquire_advice"],
           "acquire：FCEUX 内层+缺 ROM → 只说风险，不说必然（先验不许冒名判决）")
        ok(a6["fidelity"]["is_prior_only"] is True
           and 7429 in a6["fidelity"]["known_counterexamples"],
           "acquire：反例 7429 随 fidelity 一起到手，读清单的人看得见它被推翻过")
        ok(a4["fidelity"]["completion_verdict"] == "no_movie" and a4["acquire_advice"] is None,
           "acquire：没登记 local_movie 就是 no_movie，不硬套保真度")

        # ---- 候选哈希链：站点登记过期不许盖掉能对上本地文件的那一份 ----
        # 真实形态（11-22 实测 5231 吃豆人、4776/4831 Alwa）：出版物 rom_sha1 是过期值，
        # 电影 Header 与本地 .nes 都是另一个值，旧代码只取第一个「有值」的来源，
        # 结果把跑得动的任务报成「本地无匹配 ROM」——像缺资源，其实是只认了一份错账。
        import zipfile
        stale = hashlib.sha1(b"STALE-SITE-HASH").hexdigest().upper()
        mov_dir = td / "movies" / "NES"
        mov_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(mov_dir / "9.bk2", "w") as z:
            z.writestr("Header.txt", f"Platform NES\nSHA1 {sha1}\n")
            z.writestr("Input Log.txt", "|\n|\n")
        pub_stale = {"id": "9", "game": "Stale", "platform": "NES",
                     "rom_sha1": stale, "local_movie": "movies/NES/9.bk2"}
        cands = AQ.rom_sha1_candidates(pub_stale, td)
        ok([c[1] for c in cands] == ["出版物 rom_sha1", "bk2 Header"],
           "acquire：候选链按 出版物→Header 顺序给全，不丢掉 Header 那一份")
        r6 = AQ.resolve_rom(pub_stale, lib=td, rom_idx={sha1: [str(rom)]})
        ok(r6["status"] == "ready" and r6["hash_source"] == "bk2 Header"
           and r6["required_sha1"] == sha1,
           "acquire：过期站点哈希挡不住本地命中 => 仍 ready，采信 Header")
        ok(r6["hash_note"] and stale in r6["hash_note"] and sha1 in r6["hash_note"],
           "acquire：两份账不一致要同时点名（只报一个，下个人还会去找那个错的）")
        # 恒量反证：同一份 fixture 只改 rom_idx 的键，首选能对上时不该越序也不该有 note
        r7 = AQ.resolve_rom(pub_stale, lib=td, rom_idx={stale: [str(rom)]})
        ok(r7["status"] == "ready" and r7["hash_source"] == "出版物 rom_sha1"
           and r7["hash_note"] is None,
           "acquire：首选真能对上时不采信后面的来源（恒量反证：只有 rom_idx 键变）")
        r8 = AQ.resolve_rom(pub_stale, lib=td, rom_idx={})
        ok(r8["status"] == "blocked"
           and all(c["sha1"] in r8["blockers"][0]["reason"] for c in r8["candidates"])
           and "bk2 Header" in r8["blockers"][0]["reason"],
           "acquire：全候选都不中才 blocked，并逐个点名候选哈希与来源")
        r9 = AQ.resolve_rom(pub_stale, lib=td, rom_idx={}, netdisk_resolver=lambda req, p: str(rom))
        ok(r9["status"] == "ready" and r9["source"] == "own_netdisk"
           and r9["hash_source"] == "bk2 Header",
           "acquire：门控 resolver 给的文件对上 Header 候选也认（逐候选验哈希，不锁首选）")
        r10 = AQ.resolve_rom(pub_stale, lib=td, rom_idx={}, netdisk_resolver=lambda req, p: str(wrong))
        ok(r10["status"] == "blocked" and r10["rom"] is None,
           "acquire：resolver 给的哈希不在任何候选里 => 仍 blocked（哈希闸门没因此放松）")
        ok(AQ.acquire(pub_stale, lib=td, rom_idx={sha1: [str(rom)]}, cheat_lib=clib)["status"] == "ready",
           "acquire：整链（ROM+保真度+金手指）在过期站点哈希下照样 ready")

        # version 页那一格：批量扫描要能注入索引，否则每条都 glob 一遍 versions/（11-22 扫全库超时）
        (td / "versions").mkdir(exist_ok=True)
        other = hashlib.sha1(b"OTHER-VERSION-ROM").hexdigest().upper()
        (td / "versions" / "v1.json").write_text(
            json.dumps({"SHA-1": sha1, "Name": "V1"}), encoding="utf-8")
        pub_v = {"id": "3", "game": "V", "platform": "NES", "version_id": "v1"}
        ok(AQ.rom_sha1_candidates(pub_v, td) == [(sha1, "version 页")],
           "acquire：只有 version 页有哈希时照样收进候选（不因为来源靠后就丢）")
        ok(AQ.rom_sha1_candidates(pub_v, td, versions={"v1": {"sha1": other}}) == [(other, "version 页")],
           "acquire：注入 versions 索引真的被用上（反证：换一个索引结果就跟着变）")


def test_state_registry():
    """状态资产仓：登记 → 可消费闸门 → 复用命中 → 旁路档位。全程只写临时目录。"""
    import tempfile
    import zipfile
    from pathlib import Path
    from . import state_registry as SR
    from .schema import sha256_file

    def _raises_state(fn, msg):
        try:
            fn()
        except SR.StateAssetError:
            ok(True, msg)
            return
        raise AssertionError(f"应抛 StateAssetError: {msg}")

    profile = {"profile_id": "nes_bizhawk_test", "rom_sha1": "A" * 40,
               "core": "NesHawk", "emulator": "BizHawk 2.8"}

    def _state_file(path, core=b"CORE", ram=b"RAM"):
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("Core.bin", core)
            z.writestr("Ram.bin", ram)
        return str(path)

    recipe = {"game_id": "test_game", "steps": [{"step": 1, "spec": "B,,", "expect": {"ram": "0x0A=1"}}]}
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        orig_root = SR.ASSET_ROOT
        SR.ASSET_ROOT = td / "状态资产"
        try:
            # ---- 建包：身份不齐不许登记 ----
            _raises_state(lambda: SR.create("g", {"profile_id": "p", "core": "NesHawk"}),
                          "状态资产：profile 缺 rom_sha1/emulator 不许建包（复用范围无法界定）")
            _raises_state(lambda: SR.create("g", {**profile, "profile_id": "p/x"}),
                          "状态资产：profile_id 带路径分隔符被拒")
            pkg = SR.create("test_game", profile, revision="r0001", note="夹具")
            ok(pkg["status"] == "candidate" and SR.package_dir("test_game", profile["profile_id"], "r0001").is_dir(),
               "状态资产：建包落在 <game>/<profile>/<revision>，初始档位 candidate")
            _raises_state(lambda: SR.create("test_game", profile, revision="r0001"),
                          "状态资产：同 revision 重复建包被拒（不覆盖已冻结资产）")

            # ---- 登记实物：拷进包 + sha256 封条 ----
            src_state = _state_file(td / "scratch.state")
            _raises_state(lambda: SR.add_state("test_game", profile["profile_id"], "r0001", "base", str(td / "nope.state")),
                          "状态资产：源文件不存在不许登记")
            _raises_state(lambda: SR.add_state("test_game", profile["profile_id"], "r0001", "Base One", src_state),
                          "状态资产：存档名不合 [a-z0-9_] 被拒")
            doc = SR.add_state("test_game", profile["profile_id"], "r0001", "base", src_state)
            stored = SR.package_dir("test_game", profile["profile_id"], "r0001") / doc["states"]["base"]["path"]
            ok(stored.is_file() and doc["states"]["base"]["sha256"] == sha256_file(str(stored)),
               "状态资产：登记是拷贝不是引用 scratch，并记 sha256 封条")
            input_src = td / "equipment.json"
            input_src.write_text('{"macro":"Start,A"}', encoding="utf-8")
            doc = SR.add_input("test_game", profile["profile_id"], "r0001",
                               "equipment", input_src, kind="navigation")
            ok(doc["inputs"]["equipment"]["kind"] == "navigation"
               and (stored.parent.parent / doc["inputs"]["equipment"]["path"]).is_file(),
               "状态资产：导航/装备配方作为 input 入包并留实物封条")

            # ---- 可消费闸门：candidate 不许被生产路径取用 ----
            _raises_state(lambda: SR.resolve_state("test_game", profile["profile_id"], "r0001", "base"),
                          "状态资产：candidate 不许被生产消费（未验证不当已验证用）")
            _raises_state(lambda: SR.resolve_state("test_game", profile["profile_id"], "r0001", "nope"),
                          "状态资产：无该场景名被拒")
            SR.set_status("test_game", profile["profile_id"], "r0001", "state_verified")
            got = SR.resolve_state("test_game", profile["profile_id"], "r0001", "base")
            ok(got.is_file(), "状态资产：state_verified 后生产可取件")
            got.write_bytes(b"tampered")
            _raises_state(lambda: SR.resolve_state("test_game", profile["profile_id"], "r0001", "base"),
                          "状态资产：实物被改动 => sha256 不符，不返回坏路径")
            got.write_bytes(Path(src_state).read_bytes())

            # ---- 旁路档位：降级必须写理由 ----
            _raises_state(lambda: SR.set_status("test_game", profile["profile_id"], "r0001", "failed"),
                          "状态资产：旁路档位无 blockers 被拒（没出处的降级不算测过）")
            _raises_state(lambda: SR.set_status("test_game", profile["profile_id"], "r0001", "whatever"),
                          "状态资产：未知档位被拒")
            bypassed = SR.set_status("test_game", profile["profile_id"], "r0001", "blocked_resource",
                                     blockers=("ROM 哈希不符",))
            ok(bypassed["status"] == "blocked_resource" and bypassed["blockers"] == ["ROM 哈希不符"],
               "状态资产：旁路档位与 blockers 落进 package")
            _raises_state(lambda: SR.resolve_state("test_game", profile["profile_id"], "r0001", "base"),
                          "状态资产：旁路档位立刻不可消费（不是「测过没通过还能用」）")
            SR.set_status("test_game", profile["profile_id"], "r0001", "state_verified")

            # ---- 导航链登记 + 复用命中 ----
            shot = td / "step1.png"; shot.write_bytes(b"PNGSHOT")
            ram = td / "step1.bin"; ram.write_bytes(b"\x01\x02")
            root_state = _state_file(td / "root.state", core=b"BOOT")
            nav = {"state": {"path": str(stored), "content": SR.state_content_fingerprint(stored),
                             "sha256": sha256_file(str(stored)), "ram_sha256": "R", "ref_shot_sha1": "S"},
                   "root": {"path": root_state, "kind": "power_on", "boot_frame": 0,
                            "nav_frames": 120, "sha256": sha256_file(root_state)},
                   "steps": [{"step": 1, "label": "标题→开始", "frames": 120, "pass": True,
                              "checks": [{"check_id": "c1", "verdict": "pass"}],
                              "shot": str(shot), "ram_bin": str(ram)}],
                   "reload": {"pass": True, "detail": "跨进程重载帧对齐"},
                   "control": {"controllable": True, "action_effective": True,
                               "menu_effective": True, "ram_diff_bytes": 7,
                               "screenshots": {"before": str(shot), "after": str(shot)}}}
            doc = SR.attach_nav("test_game", profile["profile_id"], "r0001", recipe, nav)
            ok(doc["nav_recipe"] == recipe["steps"] and doc["inputs"]["nav"]["sha256"],
               "状态资产：attach_nav 把配方写进包（自带重建方法，不靠人记忆）")
            ok(doc["states"]["boot_root"]["kind"] == "root",
               "状态资产：引导态随包走（NesHawk 上电 RAM 随机，冷启动重跑不可字节复现）")
            ver = doc["verification"]
            ok(ver["nav:1:nav01"]["verdict"] == "pass"
               and len(ver["nav:1:nav01"]["evidence"]) == 2,
               "状态资产：逐步验收带画面+RAM 证据入包（中文标签退化成 navNN 槽名）")
            ok(doc["verification"]["nav:1:nav01"]["evidence"][0].startswith("evidence/nav01_"),
               "状态资产：全中文标签用 fallback 槽名，真实标签仍在 note 里")
            ok(ver["nav:controllability"]["verdict"] == "pass"
               and ver["nav:reload_cross_process"]["verdict"] == "pass"
               and ver["nav:root_shipped"]["verdict"] == "pass",
               "状态资产：可控性/跨进程重载/引导件三条一起记")
            SR.set_status("test_game", profile["profile_id"], "r0001", "state_verified")
            hit = SR.find_verified_nav("test_game", profile["profile_id"], recipe["steps"])
            ok(hit and hit["revision"] == "r0001" and Path(hit["state_path"]).is_file(),
               "状态资产复用：同一条已验证导航链直接命中，不重跑模拟器")
            ok(SR.find_verified_nav("test_game", profile["profile_id"],
                                    [{"step": 1, "spec": "A,,"}]) is None,
               "状态资产复用：配方不同 => 不命中（不许拿别的链的存档顶）")
            ok(SR.find_verified_nav("test_game", profile["profile_id"], recipe["steps"],
                                    state_name="nope") is None,
               "状态资产复用：要的槽位不在包里 => 不命中")
            SR.set_status("test_game", profile["profile_id"], "r0001", "stale",
                          blockers=("被 r0002 取代",))
            ok(SR.find_verified_nav("test_game", profile["profile_id"], recipe["steps"]) is None,
               "状态资产失效传播：stale 的包不再计入复用（已验证数不重复计数）")
            ok(SR.latest("test_game", status_in=SR.CONSUMABLE) is None,
               "状态资产：latest 按可消费档位过滤，stale 不会被当最新可用")
            SR.set_status("test_game", profile["profile_id"], "r0001", "element_verified")

            # ---- 反查台账（验收口径「新增已验证可复用状态数」的数据源）----
            rows = SR.list_packages()
            ok(len(rows) == 1 and rows[0]["status"] == "element_verified"
               and rows[0]["states"] == ["base", "boot_root"],
               "状态资产：list_packages 逐包现查状态与槽位，不写死名单")
            ok(rows[0]["verdicts"]["nav:root_shipped"] == "pass",
               "状态资产：台账能反查每条验收结论")

            # ---- 内容指纹 vs 文件哈希（11-14 定的复现判据）----
            za, zb = td / "a.state", td / "b.state"
            for p, dt in ((za, (2026, 11, 14, 4, 37, 40)), (zb, (2026, 11, 14, 4, 37, 44))):
                with zipfile.ZipFile(p, "w") as z:
                    z.writestr(zipfile.ZipInfo("Core.bin", date_time=dt), b"CORE")
                    z.writestr(zipfile.ZipInfo("Ram.bin", date_time=dt), b"RAM")
            fa, fb = SR.state_content_fingerprint(za), SR.state_content_fingerprint(zb)
            ok(fa["content_sha256"] == fb["content_sha256"] and fa["core_crc32"] == fb["core_crc32"],
               "状态资产：只差 ZIP 时间戳的两份存档内容指纹相同 => 复现判据用指纹")
            ok(sha256_file(str(za)) != sha256_file(str(zb)),
               "状态资产：文件 sha256 会随时间戳变，只当实物封条，不当复现判据")
            zc = td / "compressed.state"
            with zipfile.ZipFile(zc, "w") as z:
                z.writestr("Core.bin.zst", b"COMPRESSED-CORE")
                z.writestr("BizVersion.txt", "Version 2.11.1")
            fc = SR.state_content_fingerprint(zc)
            ok(fc["core_entry"] == "Core.bin.zst" and fc["core_crc32"] is not None,
               "状态资产：GBA/BizHawk 2.11 的 Core.bin.zst 也进入核心内容指纹")
            not_zip = td / "x.state"; not_zip.write_bytes(b"nope")
            _raises_state(lambda: SR.state_content_fingerprint(not_zip),
                          "状态资产：非 ZIP 容器取指纹被拒（不静默给空指纹）")
            ok(not (orig_root / "test_game").exists(),
               "状态资产：夹具反查真实资产仓，没有多出 test_game（探针不写真实状态）")
        finally:
            SR.ASSET_ROOT = orig_root


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
    ok(os.path.isabs(SJ.StateSession("r.nes", "bh", work="rel/work").work),
       "StateSession：相对 work 归一绝对（Lua io.open 按 EmuHawk cwd 解析，相对路径启动即崩）")

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
       == "5 ramdump C:/ram.bin 2048 0", "指令：ramdump 线格式显式补零起点")
    ok(SJ.format_command(5, "ramdump", path="C:/ram.bin", length=2048,
                         platform="GBA", domain="EWRAM")
       == "5 ramdump C:/ram.bin 2048 0 EWRAM",
       "指令：ramdump 仅给域名也保留起点位，避免域名被当成起点")
    ok(SJ.format_command(8, "ramdump", path="C:/iwram.bin", length=4096,
                         platform="GBA", start=0x03000000, domain="System Bus")
       == "8 ramdump C:/iwram.bin 4096 50331648 System%20Bus",
       "指令：ramdump 32位起点与域名线格式")
    raises(lambda: SJ.format_command(8, "ramdump", path="C:/iwram.bin",
                                     platform="GBA", start=-1),
           "指令：ramdump 负起点被拒")
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

    # ---- BizHawk 单实例预检（坑：旧 EmuHawk 没退净时新进程立刻退出，看门狗只报 dead，
    #      11-23 连踩两次都是自己起的探针没退净，白等两轮启动）----
    from unittest.mock import patch as _patch
    _csv = ('"EmuHawk.exe","31504","Console","1","631,232 K","Unknown","X","0:01:00","N/A"\r\n'
            '"python.exe","12","Console","1","1 K","Unknown","X","0:00:01","N/A"\r\n'
            '"brokenline\r\n'
            '"EmuHawk.exe","notapidad","Console","1","1 K"\r\n'
            '"EmuHawk.exe","27096","Console","1","822,516 K","Unknown","X","0:00:02","N/A"\r\n')
    with _patch.object(SJ.subprocess, "run",
                       lambda *a, **k: type("R", (), {"stdout": _csv})()):
        ok([r["pid"] for r in SJ._tasklist_emuhawk_processes()] == [31504, 27096],
           "单实例预检：tasklist 只点名 EmuHawk 的 PID，忽略别的进程与坏行")
    with _patch.object(SJ.subprocess, "run",
                       lambda *a, **k: (_ for _ in ()).throw(OSError("tasklist 挂了"))):
        ok(SJ._tasklist_emuhawk_processes() == [],
           "单实例预检：tasklist 量不到就返回空，不在这里编造结论")
    _emu_rows = [{"pid": 31504, "name": "EmuHawk.exe", "exe": None},
                 {"pid": 27096, "name": "EmuHawk.exe", "exe": None}]
    with _patch.object(SJ, "emuhawk_processes", lambda: _emu_rows):
        ok(SJ.emuhawk_pids() == [31504, 27096],
           "单实例预检：进程枚举只返回 EmuHawk PID，不依赖本机是否安装 psutil")
    with tempfile.TemporaryDirectory() as td2:
        s2 = SJ.StateSession("dummy.nes", "dummy_bh", work=td2)
        with _patch.object(SJ, "emuhawk_pids", lambda *a, **k: [4321]):
            msg = ""
            try:
                s2.start()
            except RuntimeError as exc:
                msg = str(exc)
            ok("4321" in msg and "单实例" in msg,
               "单实例预检：有活实例时启动前就拒，报错带 PID（不再让看门狗报含糊的 dead）")
        with _patch.object(SJ, "emuhawk_pids", lambda *a, **k: []), \
                _patch.object(SJ.subprocess, "Popen",
                              lambda *a, **k: (_ for _ in ()).throw(
                                  FileNotFoundError("假：没起真模拟器"))):
            msg2 = ""
            try:
                SJ.StateSession("dummy.nes", "dummy_bh", work=td2).start()
            except Exception as exc:
                msg2 = str(exc)
            ok("单实例" not in msg2,
               "单实例预检：反证格——空闲时不该报单实例，失败要来自后面的真步骤")

    # ---- 模板内容闸门 ----
    tmpl = tas_replay.STATE_LUA_TMPL
    ok("\r" not in tmpl, "模板闸门：无字面 CR（Python 三引号 \\r 转义坑会编译失败）")
    ok('string.gsub(line, "[\\r\\n]+$", "")' in tmpl, "模板闸门：Lua 侧 read(*a) 后剥尾 CR/LF 在册（>1024B 修复配套）")
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
    ok('string.find(name, "^P%d+ ")' in tmpl and "joypad.set(inputs)" in tmpl,
       "模板闸门：无端口前缀的 GBA 控件走无 port 参数分支")
    ok(tmpl.index("event.onframestart(apply_frame_controls") < tmpl.rindex("while true do"),
       "模板闸门：输入在 framestart 应用且处理器先于轮询注册")
    ok("__SWAP_SHOULDERS__" not in tmpl and 'joypad.set(inputs)' in tmpl,
       "模板闸门：已校准 mGBA 的 L/R 原样透传，不再反置")

    # ---- GBA 原生肩键校准：只认实测二进制哈希，未知构建不放行 ----
    with tempfile.TemporaryDirectory() as td3:
        import zipfile
        bh = Path(td3) / "BizHawk-2.11.1"
        (bh / "dll").mkdir(parents=True)
        (bh / "dll" / "mgba.dll").write_bytes(b"calibrated")
        with _patch.object(SJ, "sha1_file", return_value=SJ.GBA_MGBA_SHOULDER_DIRECT_SHA1):
            cal = SJ.gba_mgba_calibration(bh)
            ok(cal["shoulder_mapping"] == "direct" and cal["shoulder_input"] == "allowed",
               "GBA 校准：实测哈希命中才允许 L/R 原样发送")
            s_cal = SJ.StateSession("r.gba", bh, core="mGBA", system="GBA", work=td3)
            SJ.check_shoulder_calibration("GBA", "L+R,,", s_cal.input_calibration)
            ok(True, "GBA 校准：命中构建的 L/R 和弦可发送")
        with _patch.object(SJ, "sha1_file", return_value="0" * 40):
            cal = SJ.gba_mgba_calibration(bh)
            ok(cal["shoulder_mapping"] == "uncalibrated" and cal["status"] == "uncalibrated",
               "GBA 校准：未知哈希保持未校准，不猜映射")
            raises(lambda: SJ.check_shoulder_calibration("GBA", "L+R,,", cal),
                   "GBA 校准：未知构建的 L/R 在发送前拒绝")
            SJ.check_shoulder_calibration("GBA", "Right+LT,,A", cal)
            ok(True, "GBA 校准：未知构建仍允许已确认的方向与 A 键")
        raises(lambda: SJ.StateSession("r.gba", bh, core="VBA-Next", system="GBA", work=td3),
               "GBA 核心：不存在的 VBA-Next 在构造时拒绝，不允许静默回退")
        state = Path(td3) / "core.state"
        with zipfile.ZipFile(state, "w") as z:
            z.writestr("SyncSettings.json", json.dumps({"o": {"$type": SJ.GBA_MGBA_CORE_TYPE + "+SyncSettings, BizHawk.Emulation.Cores"}}))
        ok(SJ.saved_core_type(state) == SJ.GBA_MGBA_CORE_TYPE,
           "GBA 核心：存档 SyncSettings 能识别真实 mGBA 身份")
        ok(SJ.saved_core_type(Path(td3) / "missing.state") is None,
           "GBA 核心：缺存档身份不冒充已核验")

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


def test_showcase():
    import copy
    import json
    import tempfile
    from pathlib import Path
    from PIL import Image
    from . import showcase as SC
    from . import statejump as SJ
    from . import auto as A

    ok(SJ.format_command(8, "dump", frames_dir="C:/fr", spec="B", extra=2,
                         state="C:/base.state",
                         patches=[{"addr": 106, "value": 28},
                                  {"addr": 107, "value": 1, "domain": "RAM"}])
       == "8 dump C:/fr B 2 C:/base.state 106:28;107:1@RAM",
       "showcase 指令：dump 原子携带 base+RAM patches")
    raises(lambda: SJ.format_command(1, "dump", frames_dir="C:/fr", extra=1,
                                     patches=[{"addr": 0x10000, "value": 1}]),
           "showcase 指令：非法 RAM patch 地址被拒")
    ok(SJ.format_command(9, "dump", frames_dir="C:/fr", extra=3,
                         patches=[{"addr": 106, "value": 28, "apply": "per_frame"}])
       == "9 dump C:/fr - 3 - 106:28 per_frame",
       "patch 指令：逐帧语义显式上线格式")
    raises(lambda: SJ.format_command(1, "dump", frames_dir="C:/fr", extra=1,
                                     patches=[{"addr": 1, "value": 1},
                                              {"addr": 2, "value": 1, "apply": "per_frame"}]),
           "patch 指令：一次性与逐帧补丁混用被拒")
    raises(lambda: SJ.format_command(1, "dump", frames_dir="C:/fr", extra=1,
                                     patches=[{"addr": 1, "value": 1, "apply": "sometimes"}]),
           "patch 指令：未知补丁时序被拒")
    import tas_replay
    tmpl = tas_replay.STATE_LUA_TMPL
    ok('if p[6] and p[6] ~= "-" then savestate.load(p[6]) end' in tmpl
       and 'split_keep(p[7], ";")' in tmpl,
       "showcase 模板：读档+patches 在逐帧采集前原子执行，无空闲帧漂移")
    ok('local patch_mode = p[8] or "one_shot"' in tmpl
       and 'apply_patches(dumping.patches)' in tmpl
       and 'apply_patches(flushing.patches)' in tmpl,
       "patch 模板：逐帧补丁在每帧结束后恢复并覆盖截图刷新帧，一次性补丁不跨帧")
    ok("data = tostring(dumping.total)" in tmpl and "flushing.data or" in tmpl,
       "showcase 契约：dump 返回实际采集帧数而非模拟器绝对 framecount")

    doc = {
        "kind": "statejump_showcase", "game_id": "synthetic", "platform": "NES",
        "rom": "game.nes", "bizhawk": "bh", "base_state": "base.state",
        "rom_sha1": hashlib.sha1(b"NES synthetic").hexdigest(),
        "fps": 60, "template": "none",
        "catalog": {"status": "complete", "expected_total": 1, "sources": ["synthetic spec"]},
        "elements": [{
            "element_id": "test_weapon", "label": "Test weapon", "kind": "weapon",
            "base_state": "weapon.state",
            "trigger": {"macro": "B,,", "extra": 2, "patches": [{"addr": 16, "value": 1}]},
            "detection": {"frame": 1, "success_checks": [{
                "check_id": "bright", "plugin_id": "frame_luma_range",
                "params": {"min": 200, "max": 255}, "required": True}]},
            "negative_control": {"macro": None}
        }]
    }
    SC.validate_spec(doc)
    ok(True, "showcase schema：完整单要素包通过校验")
    bad = copy.deepcopy(doc); bad["catalog"]["status"] = "draft"
    raises(lambda: SC.validate_spec(bad), "showcase schema：清单调研 draft 不得生产")
    bad = copy.deepcopy(doc); bad["elements"][0]["detection"]["frame"] = 5
    raises(lambda: SC.validate_spec(bad), "showcase schema：检测帧越出采集窗被拒")
    bad = copy.deepcopy(doc); bad["elements"][0]["detection"]["success_checks"][0]["plugin_id"] = "bogus"
    raises(lambda: SC.validate_spec(bad), "showcase schema：未知检测插件在采集前拒")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "game.nes").write_bytes(b"NES synthetic")
        (td / "base.state").write_bytes(b"STATE synthetic")
        (td / "weapon.state").write_bytes(b"STATE weapon specific")
        (td / "bh").mkdir()
        (td / "bh" / "EmuHawk.exe").write_bytes(b"MZ")
        pack = td / "game.showcase.json"
        pack.write_text(json.dumps(doc), encoding="utf-8")
        ready = SC.plan(pack)
        ok(ready["status"] == "ready" and ready["expected_total"] == 1,
           "showcase plan：ROM/base/EmuHawk/完整清单齐全才 ready")
        ok(A.expected_fingerprint(A.JobSpec("g", "items", source="showcase", pack=str(pack),
                                            template="none")) is not None,
           "auto/showcase：指纹输入含 pack+ROM+base")
        auto_plan = A.plan(A.JobSpec("g", "items", source="showcase", pack=str(pack),
                                     template="none"))
        ok(auto_plan["status"] == "ready" and auto_plan["elements"] == 1,
           "auto/showcase：plan 走 showcase 分支，不要求 TAS 出版物")

        # ---- showcase 取 ROM 与 acquire 同口径：包 pin 哈希，路径只是提示 ----
        moved = td / "moved_away.nes"
        moved.write_bytes((td / "game.nes").read_bytes())
        rom_sha = hashlib.sha1(moved.read_bytes()).hexdigest().upper()
        gone = copy.deepcopy(doc)
        gone["rom"], gone["rom_sha1"] = "gone.nes", rom_sha
        pack_gone = td / "gone.showcase.json"
        pack_gone.write_text(json.dumps(gone), encoding="utf-8")
        r_idx = SC.resolve_rom(pack_gone, rom_idx={rom_sha: [str(moved)]})
        ok(r_idx["status"] == "ready" and r_idx["rom"] == str(moved)
           and r_idx["source"] == "local_index",
           "showcase 获取：包内路径挪盘 => 按哈希命中本地索引，不判死")
        r_none = SC.resolve_rom(pack_gone, rom_idx={})
        ok(r_none["status"] == "blocked"
           and any("网盘" in b["reason"] for b in r_none["blockers"]),
           "showcase 获取：本地也没有且没注入钩子 => 诚实 blocked（不自动抓商业全集）")
        r_hook = SC.resolve_rom(pack_gone, rom_idx={},
                                netdisk_resolver=lambda req, d: str(moved))
        ok(r_hook["status"] == "ready" and r_hook["source"] == "own_netdisk",
           "showcase 获取：注入网盘 resolver 后走通（网盘优先）")
        r_hook2 = SC.resolve_rom(pack_gone, rom_idx={},
                                 netdisk_resolver=lambda req, d: str(td / "base.state"))
        ok(r_hook2["status"] == "blocked"
           and any("哈希不符" in b["reason"] for b in r_hook2["blockers"]),
           "showcase 获取：resolver 交回哈希不符件 => blocked，不拿错版本出片")
        wrong = copy.deepcopy(doc)
        wrong["rom_sha1"] = "0" * 40
        pack_wrong = td / "wrong.showcase.json"
        pack_wrong.write_text(json.dumps(wrong), encoding="utf-8")
        r_wrong = SC.resolve_rom(pack_wrong, rom_idx={})
        ok(r_wrong["status"] == "blocked"
           and "哈希不符" in r_wrong["blockers"][0]["reason"],
           "showcase 获取：包内件哈希不符仍 blocked（RAM 地址按版本标的）")
        ok(SC.plan(pack_gone, rom_idx={rom_sha: [str(moved)]})["resources"]["rom"] == str(moved),
           "showcase plan：resources 报解析后的 ROM，run 不再各判一套")
        ok(SC.plan(pack_gone, rom_idx={})["status"] == "blocked",
           "showcase plan：ROM 取不到 => blocked（不带着 None 路径往下跑）")
        # ---- 音频口径：逐帧 dump 没有同步原声，audio=True 必须显式拒 ----
        ar = SC.run(pack, td / "audio_out", audio=True)
        ok(ar["status"] == "blocked"
           and ar["blockers"][0]["code"] == "unsupported_capability",
           "showcase 音频：audio=True 显式 blocked（不静默出哑片给解说工厂）")
        ok(A.orchestrate(A.JobSpec("g", "items", source="showcase", pack=str(pack),
                                   audio=True), out_dir=str(td / "auto_audio"))["status"]
           == "blocked", "auto/showcase：spec.audio 透传到 showcase 并被诚实拦下")

        white = td / "white.png"; black = td / "black.png"
        Image.new("RGB", (8, 8), (255, 255, 255)).save(white)
        Image.new("RGB", (8, 8), (0, 0, 0)).save(black)
        det = SC.verify_detection(doc["elements"][0], str(white), str(black))
        ok(det["verdict"] == "pass" and det["negative"]["rejected"] is True,
           "showcase 检测：正例过+中立反例拒 => pass")
        det_bad = SC.verify_detection(doc["elements"][0], str(white), str(white))
        ok(det_bad["verdict"] == "fail", "showcase 反证：反例也过同检测器 => fail")
        bad_el = copy.deepcopy(doc["elements"][0])
        bad_el["detection"]["success_checks"][0]["plugin_id"] = "not_registered"
        det_inc = SC.verify_detection(bad_el, str(white), str(black))
        ok(det_inc["verdict"] == "inconclusive", "showcase 检测：证据不足不得算 pass")

        broken = td / "broken_frames"; broken.mkdir()
        (broken / "f0000.png").write_bytes(b"not a png")
        try:
            SC.validate_frames(broken, 1)
        except RuntimeError:
            ok(True, "showcase 帧闸：半 PNG/假 PNG 不得进入编码")
        else:
            raise AssertionError("showcase 帧闸：坏 PNG 未拒")

        class FakeSession:
            instances = []

            def __init__(self, rom, bizhawk, **kw):
                self.work = kw["work"]
                self.calls = []
                self.closed = False
                FakeSession.instances.append(self)

            def start(self):
                return self

            def check_state_profile(self, state_path, name="profile_check"):
                return {"match": True, "state_path": str(state_path)}

            def dump(self, frames_dir, spec=None, extra=0, state=None, patches=None):
                assert Path(state).is_file()
                total = SC._macro_frames(spec) + extra
                self.calls.append({"spec": spec, "extra": extra, "total": total,
                                   "state": state, "patches": patches})
                frames = Path(frames_dir); frames.mkdir(parents=True, exist_ok=True)
                color = (255, 255, 255) if spec else (0, 0, 0)
                for i in range(total):
                    Image.new("RGB", (8, 8), color).save(frames / f"f{i:04d}.png")
                return total

            def close(self):
                self.closed = True

        def fake_encode(frames_dir, fps, out, ffmpeg="ffmpeg"):
            Path(out).write_bytes(b"synthetic mp4")
            return out

        def fake_concat(clips, out, ffmpeg="ffmpeg"):
            Path(out).write_bytes(b"synthetic reel")
            return out

        orig_frames = SC._video_frames
        SC._video_frames = lambda path, ffprobe="ffprobe": 5
        out = td / "out"
        try:
            result = SC.run(pack, out, template="none", work_dir=str(td / "work"),
                            session_factory=FakeSession, encoder=fake_encode,
                            concatenator=fake_concat)
            ok(result["status"] == "done" and result["verdict"] == "pass"
               and result["coverage"]["expected_total"] == 1,
               "showcase 生产：单要素正/反例+编码+合辑全链 done")
            ok(Path(result["deliverable_ref"]).is_file()
               and (out / "controls" / "test_weapon_negative.mp4").is_file(),
               "showcase 产物：正式合辑与反例片段均真实落盘")
            calls = FakeSession.instances[0].calls
            ok(len(calls) == 2 and calls[0]["total"] == calls[1]["total"] == 5
               and calls[1]["spec"] is None,
               "showcase 对照：正/反例同 base 同总帧数，反例默认中立")
            ok(calls[0]["patches"] == calls[1]["patches"] == [{"addr": 16, "value": 1}],
               "showcase 对照：反例继承相同 RAM 前置补丁，隔离宏效果")
            ok(calls[0]["state"] == calls[1]["state"]
               and Path(calls[0]["state"]).name == "test_weapon.state",
               "showcase 逐要素 base：特殊场景覆盖公共 base，正反例仍共享同一快照")
            ok(FakeSession.instances[0].closed is True,
               "showcase 会话：生产结束关闭 EmuHawk")
            again = SC.run(pack, out, template="none", work_dir=str(td / "work"),
                           session_factory=FakeSession, encoder=fake_encode,
                           concatenator=fake_concat)
            ok(again["status"] == "done" and len(FakeSession.instances) == 1,
               "showcase 续跑：同指纹复用要素与合辑，不重启采集会话")

            partial_doc = copy.deepcopy(doc)
            partial_doc["catalog"]["expected_total"] = 2
            partial_pack = td / "partial.showcase.json"
            partial_pack.write_text(json.dumps(partial_doc), encoding="utf-8")
            blocked = SC.run(partial_pack, td / "partial_full", template="none",
                             work_dir=str(td / "work"), session_factory=FakeSession,
                             encoder=fake_encode, concatenator=fake_concat)
            ok(blocked["status"] == "blocked",
               "showcase 全量闸：清单 1/2 未 authoring 齐全，不许直接全量跑")
            partial = SC.run(partial_pack, td / "partial_one", only=["test_weapon"],
                             template="none", work_dir=str(td / "work"),
                             session_factory=FakeSession, encoder=fake_encode,
                             concatenator=fake_concat)
            ok(partial["status"] == "partial" and partial["passed"] == 1
               and partial["deliverable_ref"] is None,
               "showcase --only：单要素可试跑但不生成正式全量合辑")

            # ---- 交付缺口：点名批准后可以不出片，但不能静默消失 ----
            gap_delivery = {"status": "blocked_routing", "reason": "路线未成立",
                            "note": "缺分段跳 checkpoint，不缺地址表",
                            "decided_by": "用户批准推荐项 A", "decided_on": "2026-11-23"}
            gap_doc = copy.deepcopy(doc)
            gap_el = copy.deepcopy(gap_doc["elements"][0])
            gap_el.update({"element_id": "gap_weapon", "label": "Gap weapon",
                           "delivery": gap_delivery})
            gap_doc["elements"].append(gap_el)
            gap_doc["catalog"]["expected_total"] = 2
            SC.validate_spec(gap_doc)
            ok(True, "showcase 缺口：delivery 五字段齐全才过 schema")
            bad = copy.deepcopy(gap_doc); bad["elements"][1]["delivery"]["status"] = "gave_up"
            raises(lambda: SC.validate_spec(bad), "showcase 缺口：未注册的 status 被拒")
            bad = copy.deepcopy(gap_doc); del bad["elements"][1]["delivery"]["decided_on"]
            raises(lambda: SC.validate_spec(bad), "showcase 缺口：没写批准日期被拒")
            bad = copy.deepcopy(gap_doc); del bad["elements"][1]["delivery"]["note"]
            raises(lambda: SC.validate_spec(bad), "showcase 缺口：没说清缺哪一步被拒")
            gap_pack = td / "gap.showcase.json"
            gap_pack.write_text(json.dumps(gap_doc), encoding="utf-8")
            gap_plan = SC.plan(gap_pack)
            ok(gap_plan["status"] == "ready" and gap_plan["required"] == 1
               and gap_plan["delivery_gaps"] == ["gap_weapon"],
               "showcase 缺口：plan 把必交数减到 1 并点名缺口要素")
            gap_out = td / "gap_out"
            n_before = len(FakeSession.instances)
            gap_res = SC.run(gap_pack, gap_out, template="none", work_dir=str(td / "work"),
                             session_factory=FakeSession, encoder=fake_encode,
                             concatenator=fake_concat)
            ok(gap_res["status"] == "done" and gap_res["verdict"] == "pass"
               and Path(gap_res["deliverable_ref"]).is_file(),
               "showcase 缺口：7/8 型产物照出正式合辑，不必等最后一格")
            cov = gap_res["coverage"]
            ok(cov["expected_total"] == 2 and cov["required"] == 1 and cov["delivered"] == 1
               and gap_res["total"] == 2 and cov["full_collection"] is False,
               "showcase 缺口：分母仍是 2，full_collection=False 不许冒充全量")
            ok([g["element_id"] for g in cov["gaps"]] == ["gap_weapon"]
               and cov["gaps"][0]["decided_on"] == "2026-11-23"
               and cov["gaps"][0]["status"] == "blocked_routing",
               "showcase 缺口：产物里逐条点名谁挂起、谁批的、哪天")
            ok(not (gap_out / "elements" / "gap_weapon.json").exists()
               and not (gap_out / "clips" / "gap_weapon.mp4").exists()
               and [e["element_id"] for e in gap_res["elements"]] == ["test_weapon"],
               "showcase 缺口：挂起要素不采集、不进合辑")
            ok(len(FakeSession.instances) == n_before + 1,
               "showcase 缺口：只为本轮必交要素起一次会话")
            only_gap = SC.run(gap_pack, td / "gap_retry", only=["gap_weapon"], template="none",
                              work_dir=str(td / "work"), session_factory=FakeSession,
                              encoder=fake_encode, concatenator=fake_concat)
            ok(only_gap["status"] != "blocked"
               and [e["element_id"] for e in only_gap["elements"]] == ["gap_weapon"],
               "showcase 缺口：--only 显式点名仍可重试，挂起不等于封死")
            zero_doc = copy.deepcopy(doc)
            zero_doc["elements"][0]["delivery"] = gap_delivery
            zero_pack = td / "zero.showcase.json"
            zero_pack.write_text(json.dumps(zero_doc), encoding="utf-8")
            zero_res = SC.run(zero_pack, td / "zero_out", template="none",
                              work_dir=str(td / "work"), session_factory=FakeSession,
                              encoder=fake_encode, concatenator=fake_concat)
            ok(zero_res["status"] == "blocked" and "清零" in zero_res["blockers"][0]["reason"],
               "showcase 缺口：拿声明把必交要素清空 => 拦死")

            orig_run = SC.run
            try:
                SC.run = lambda *a, **k: {"status": "done", "verdict": "pass",
                                          "deliverable_ref": "synthetic.mp4"}
                auto_result = A.orchestrate(A.JobSpec("g", "items", source="showcase",
                                                      pack=str(pack), template="none"),
                                            out_dir=str(td / "auto"))
                ok(auto_result["status"] == "done" and auto_result["source"] == "showcase",
                   "auto/showcase：run 生产入口已接线")
            finally:
                SC.run = orig_run
        finally:
            SC._video_frames = orig_frames


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
    raises(lambda: A.JobSpec.from_dict({"game": "g", "job_type": "playthrough", "bogus_field": 1}),
           "auto：from_dict 未知字段被拒（不静默丢弃）")
    try:
        A.JobSpec.from_dict({"game": "g", "job_typ": "playthrough"})
        raise AssertionError("auto：from_dict 拼错的键应被拒并给近似名")
    except SchemaError as e:
        ok("job_type" in str(e), "auto：from_dict 报错里给出最接近的合法键")
    s = A.JobSpec.from_dict({"game": "g", "job_type": "playthrough", "frames": 120})
    ok(s.game == "g" and s.frames == 120, "auto：from_dict 合法键正常入库")
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
            spec = A.JobSpec("Contra", "playthrough", pub_id="9999")
            p, assess = A.resolve_job(spec, lib)
            ok(p and p["id"] == "9999" and assess["status"] == "replayable",
               "auto：resolve_job 合成 lib => replayable")
            pl = A.plan(spec, lib)
            ok(pl["status"] == "ready", "auto：plan 合成 ready（resolve+acquire+state 全过）")
            ok(pl["stages"]["acquire"]["status"] == "ready", "auto：plan acquire ready")
            ok(pl["stages"]["state"]["origin"] == "normal_prefix", "auto：plan movie => normal_prefix")
            fp = A.expected_fingerprint(spec, lib)
            ok(bool(fp), "auto：expected_fingerprint 不采集即算出指纹")
            spec_out = A.JobSpec("Contra", "playthrough", pub_id="9999", out=str(td / "x"))
            ok(A.expected_fingerprint(spec_out, lib) == fp, "auto：指纹与 out 无关（矩阵可跳过）")
            pl_ss = A.plan(A.JobSpec("Contra", "playthrough", pub_id="9999",
                                     source="savestate"), lib)
            ok(pl_ss["status"] == "blocked" and pl_ss["stages"]["showcase"]["status"] == "blocked",
               "auto：savestate 通关任务在契约层拒绝，不再索要无关金手指")
            # 未知游戏 => resolve blocked（合成 lib 无此名，不触真实 4694 条）
            doc = A.orchestrate(A.JobSpec("ZZZ_NO_SUCH_GAME", "playthrough"), lib=lib, dry_run=True)
            ok(doc["status"] == "blocked" and doc["stages"]["resolve"]["status"] == "blocked",
               "auto：orchestrate 未知游戏 => resolve blocked")

            # ---- 编排层的选题闸门：冷门作品连采集都不启动 ----
            # control.plan 只管 control CLI 这条入口；走 registry 的电影任务不经过它，
            # 冷门曾经能直接开跑。这里盯住编排层也拦（恒量反证：换成名单上的作品就放行）。
            cold_game = "Alwa's Awakening: The 8-Bit Edition"
            lib_cold, _pub_cold, _s1, _r1, _b1 = _synthetic_nes_lib(td, game=cold_game, pid="9998")
            spec_cold = A.JobSpec(cold_game, "playthrough", pub_id="9998")
            pl_cold = A.plan(spec_cold, lib_cold)
            ok(pl_cold["status"] == "blocked"
               and pl_cold["stages"]["popularity"]["blockers"][0]["code"] == "title_off_popularity_list",
               "auto：编排层拦冷门（闸门码=title_off_popularity_list）")
            doc_cold = A.orchestrate(spec_cold, lib=lib_cold, out_dir=str(td / "cold"))
            ok(doc_cold["status"] == "blocked" and doc_cold["failed_stage"] == "selection",
               "auto：冷门作品停在 selection，不进采集")
            ok(not list((td / "cold").glob("*.mp4")),
               "auto：冷门作品没产出任何视频")
            pl_cold_allow = A.plan(spec_cold, lib_cold, allow=("title_off_popularity_list",))
            ok(pl_cold_allow["status"] != "blocked"
               and pl_cold_allow["stages"].get("popularity", {}).get("warnings"),
               "auto：显式 allow 才放行冷门，且留下 warning 痕迹")

            # ---- job 级 verdict 必须如实反映台账，不再只看「没崩且有 mp4」----
            # 11-22 F-Zero 7406：capture/export 两格都记 inconclusive（音频没验），
            # job.json 却写 pass —— 读者据此以为这一格整体验过。
            ok(A._job_verdict(True, ["pass", "pass"]) == "pass",
               "auto：全阶段 pass => job pass")
            ok(A._job_verdict(True, ["pass", "inconclusive"]) == "inconclusive",
               "auto：任一格 inconclusive 时 job 不许升 pass")
            ok(A._job_verdict(True, ["pass", "fail"]) == "fail",
               "auto：任一格 fail 时 job 判 fail，不被同链的 pass 掩盖")
            # 恒量反证两格：空台账、以及「链路失败但阶段全 pass」都不许冒 pass
            ok(A._job_verdict(True, []) == "inconclusive",
               "auto：空台账不给 pass（有成片≠有证据）")
            ok(A._job_verdict(False, ["pass", "pass"]) == "fail",
               "auto：链路失败时阶段全 pass 仍判 fail（反证：verdict 不是唯一判据）")

            # 接线证明：run_playthrough 真从台账读 verdict（键名与 ledger.complete 同源），
            # 而不是只把 res['deliverable_ref'] 翻译成 pass。
            jd = Path(td) / "jobv"
            jd.mkdir(parents=True, exist_ok=True)
            mp4j = jd / "run.mp4"
            mp4j.write_bytes(b"\x00")
            led_path = str(jd / "ledger.json")
            LJ = A.Ledger(led_path)
            LJ.complete(LJ.register("capture", "cap", "fp1"), [str(mp4j)], Verdict.PASS)
            LJ.complete(LJ.register("export", "exp", "fp2"), [str(mp4j)], Verdict.INCONCLUSIVE)
            from . import pipeline as _P
            orig_nes, orig_chain = A._nes_inputs, _P.run_chain
            try:
                A._nes_inputs = lambda assess, rom: {
                    "movie": "m.bk2", "rom": rom, "bizhawk_dir": "biz",
                    "profile_id": "p", "core": "BSNESv115+", "system": "SNES"}
                _P.run_chain = lambda *a, **k: {
                    "failed_stage": None, "deliverable_ref": str(mp4j),
                    "reused_capture": False, "reused_export": False, "ledger": led_path}
                rj = A.run_playthrough(A.JobSpec("g", "playthrough"), None, {},
                                       {"rom": "x.sfc"}, str(jd))
                ok(rj["stage_verdicts"] == ["pass", "inconclusive"],
                   "auto：run_playthrough 逐格读出台账 verdict（capture=pass / export=inconclusive）")
                ok(rj["verdict"] == "inconclusive" and rj["status"] == "done",
                   "auto：成片在但 export 格未验 => job 判 inconclusive，不再冒 pass")
            finally:
                A._nes_inputs, _P.run_chain = orig_nes, orig_chain

            # ---- 身份解析 vs 资源就绪分档（ROM 只在网盘时不许在 resolve 判死）----
            orig_index_roms = R.index_roms
            try:
                R.index_roms = lambda l: {}
                a_net = R.assess(pub, lib, {}, R.index_versions(lib),
                                 R.discover_bizhawk(R.DEFAULT_EMU))
                ok(a_net["status"] == "blocked" and a_net["identity_status"] == "resolved"
                   and a_net["profile"], "registry：ROM 缺位只挡就绪，不挡身份（profile 仍解析出）")
                pl_net = A.plan(spec, lib)
                ok(pl_net["stages"]["resolve"]["status"] == "ready"
                   and pl_net["stages"]["acquire"]["status"] == "blocked"
                   and pl_net["status"] == "blocked",
                   "auto：网盘独占 ROM => resolve ready、拦在 acquire（没注入钩子时仍诚实 blocked）")
                pl_hook = A.plan(spec, lib, netdisk_resolver=lambda req, p: str(rom))
                ok(pl_hook["status"] == "ready"
                   and pl_hook["stages"]["acquire"]["rom_source"] == "own_netdisk",
                   "auto：注入 resolver 后同一格走通（acquire 死锁解除）")
                ok(A.expected_fingerprint(spec, lib) is None
                   and bool(A.expected_fingerprint(
                       spec, lib, netdisk_resolver=lambda req, p: str(rom))),
                   "auto：网盘独占时指纹也算得出（矩阵不把它当没做过反复重跑）")
                # resolver 交回哈希不符的件 => 仍 blocked，不拿错 ROM 出片
                pl_bad = A.plan(spec, lib, netdisk_resolver=lambda req, p: str(bk2))
                ok(pl_bad["status"] == "blocked"
                   and "哈希不符" in json.dumps(pl_bad["stages"]["acquire"], ensure_ascii=False),
                   "auto：resolver 返回哈希不符件 => acquire blocked（不伪装 ready）")
            finally:
                R.index_roms = orig_index_roms
        finally:
            R.discover_bizhawk, A._backend_caps = orig_disc, orig_caps


def test_state_capture_contract():
    import copy
    import json
    import tempfile
    from unittest.mock import patch
    from PIL import Image
    import tas_replay
    from . import auto as A, showcase as SC, state_registry as SR, registry as R

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "game.nes").write_bytes(b"NES contract fixture")
        (root / "base.state").write_bytes(b"STATE fixture")
        (root / "bh").mkdir()
        (root / "bh" / "EmuHawk.exe").write_bytes(b"MZ fixture")
        sha = hashlib.sha1((root / "game.nes").read_bytes()).hexdigest().upper()
        doc = {
            "kind": "statejump_showcase", "game_id": "contract_fixture", "platform": "NES",
            "rom": "game.nes", "rom_sha1": sha, "bizhawk": "bh", "base_state": "base.state",
            "catalog": {"status": "complete", "expected_total": 1, "sources": ["synthetic"]},
            "elements": [{
                "element_id": "probe", "label": "Probe", "kind": "weapon",
                "trigger": {"macro": "B,,", "extra": 1, "patches": [{"addr": 16, "value": 1}]},
                "negative_control": {"macro": "B,,", "patches": [{"addr": 16, "value": 0}]},
                "detection": {"frame": 1, "success_checks": [{
                    "check_id": "bright", "plugin_id": "frame_luma_range",
                    "params": {"min": 200, "max": 255}, "required": True}]}}]}

        def write_pack(name, value):
            path = root / f"{name}.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return str(path)

        pack = write_pack("valid", doc)
        calls, sessions = [], []

        class Session:
            def __init__(self, *args, **kwargs):
                self.closed = False
                sessions.append(self)

            def start(self):
                return self

            def check_state_profile(self, state_path, name="profile_check"):
                calls.append({"gate": str(state_path)})
                return {"match": True, "state_path": str(state_path)}

            def dump(self, frames_dir, spec=None, extra=0, state=None, patches=None):
                assert Path(state).read_bytes() == b"STATE fixture"
                calls.append({"macro": spec, "patches": patches})
                count = SC._macro_frames(spec) + extra
                color = 255 if spec and (not patches or patches[0]["value"] == 1) else 0
                directory = Path(frames_dir)
                directory.mkdir(parents=True)
                for i in range(count):
                    Image.new("RGB", (8, 8), (color,) * 3).save(directory / f"f{i:04d}.png")
                return count

            def close(self):
                self.closed = True

        def encode(frames_dir, fps, out, **kwargs):
            Path(out).write_bytes(b"synthetic encoded clip")
            return out

        def concat(clips, out, **kwargs):
            Path(out).write_bytes(b"synthetic encoded reel")
            return out

        with patch.object(A, "resolve_job", side_effect=AssertionError("不得解析 TAS 出版物")), \
             patch.object(A.AQ, "acquire", side_effect=AssertionError("不得获取电影/任意作弊候选")), \
             patch.object(A, "run_movie_elements", side_effect=AssertionError("不得回落电影采集")), \
             patch.object(SR, "ASSET_ROOT", root / "assets"), \
             patch.object(R, "index_roms", return_value={}), \
             patch.object(SC.SJ, "StateSession", Session), \
             patch.object(tas_replay, "encode_video", encode), \
             patch.object(SC, "_concat_videos", concat), \
             patch.object(SC, "_video_frames", return_value=4):
            for source in ("showcase", "savestate", "cheat"):
                spec = A.JobSpec("No TAS publication", "items", source=source, pack=pack, template="none")
                pre = A.plan(spec)
                ok(pre["status"] == "ready", f"状态契约：{source} 预检不访问电影库")
                start = len(calls)
                result = A.orchestrate(spec, out_dir=str(root / source))
                ok(result["status"] == "done" and result["passed"] == 1,
                   f"状态契约：{source} 经真实编排/采集/判定/台账路径完成合成样例")
                ok(calls[start].get("gate", "").endswith("base.state"),
                   f"状态契约：{source} 拓扑闸门先于任何采集执行")
                ok(calls[-2:][0]["patches"] == [{"addr": 16, "value": 1}]
                   and calls[-1]["patches"] == [{"addr": 16, "value": 0}],
                   f"状态契约：{source} 正反例补丁真实传到 dump 消费方")
                ok(result["execution"]["mechanism"] == "load_savestate_and_patch"
                   and result["execution"]["rom_sha1"] == sha
                   and result["fp"] == A.expected_fingerprint(spec),
                   f"状态契约：{source} 执行机制/ROM/复用指纹可对账")
                saved = json.loads((root / source / spec.slug() / "job.json").read_text(encoding="utf-8"))
                ok(saved["execution"] == result["execution"] and sessions[-1].closed,
                   f"状态契约：{source} 落盘执行记录且关闭会话")
            count = len(calls)
            resumed = A.orchestrate(spec, out_dir=str(root / "cheat"))
            ok(resumed["status"] == "done" and len(calls) == count,
               "状态契约：同指纹续跑不再采集正反例")

            plain = copy.deepcopy(doc)
            plain["elements"][0]["trigger"]["patches"] = []
            plain["elements"][0]["negative_control"] = {"macro": None, "patches": []}
            plain_pack = write_pack("plain_state", plain)
            plain_spec = A.JobSpec("g", "items", source="savestate", pack=plain_pack, template="none")
            ok(A.plan(plain_spec)["status"] == "ready", "状态契约：纯存档任务不要求金手指")
            plain_result = A.orchestrate(plain_spec, out_dir=str(root / "plain"))
            ok(plain_result["status"] == "done"
               and plain_result["execution"]["mechanism"] == "load_savestate"
               and calls[-2]["patches"] == [], "状态契约：纯存档真实经过无补丁采集路径")
            missing_patch = A.JobSpec("g", "items", source="cheat", pack=plain_pack)
            ok(A.plan(missing_patch)["status"] == "blocked"
               and A.expected_fingerprint(missing_patch) is None,
               "状态契约：声明 cheat 却无补丁不能假完成/复用")

            for options in ({"job_type": "playthrough"}, {"pub_id": "123"}, {"frames": 3},
                            {"elements": [{"element_id": "ignored"}]}, {"cheat_query": "all weapons"}):
                fields = {"game": "g", "job_type": "items", "source": "savestate", "pack": pack}
                fields.update(options)
                bad_spec = A.JobSpec(**fields)
                result = A.orchestrate(bad_spec, out_dir=str(root / "invalid_options"))
                ok(A.plan(bad_spec)["status"] == result["status"] == "blocked"
                   and result["failed_stage"] == "state_contract",
                   f"状态契约：不支持的任务参数明确拦截 {list(options)}")

            for name, changes in (("missing_hash", {"rom_sha1": ""}),
                                  ("wrong_hash", {"rom_sha1": "0" * 40}),
                                  ("unverified_platform", {"platform": "SNES"})):
                bad_doc = copy.deepcopy(doc)
                bad_doc.update(changes)
                bad_pack = write_pack(name, bad_doc)
                before = len(calls)
                pre = SC.plan(bad_pack)
                result = SC.run(bad_pack, root / name)
                ok(pre["status"] == result["status"] == "blocked" and len(calls) == before,
                   f"状态契约：{name} 在预检和直达生产入口一致拦截")
                bad_spec = A.JobSpec("g", "items", source="cheat", pack=bad_pack)
                ok(A.expected_fingerprint(bad_spec) is None,
                   f"状态契约：{name} 不能生成可复用作业指纹")
            no_hash = copy.deepcopy(doc)
            no_hash.pop("rom_sha1")
            raises(lambda: SC.validate_spec(no_hash), "状态契约：未声明 ROM 哈希直接拒绝")
            wrong_pack = str(root / "wrong_hash.json")
            raises(lambda: SC.resource_files(wrong_pack), "状态契约：错误版本文件存在也不能生成资源指纹")

            for source in ("showcase", "savestate", "cheat"):
                audio_spec = A.JobSpec("g", "items", source=source, pack=pack, audio=True)
                before = len(calls)
                result = A.orchestrate(audio_spec, out_dir=str(root / f"audio_{source}"))
                ok(A.plan(audio_spec)["status"] == result["status"] == "blocked"
                   and len(calls) == before, f"状态契约：{source} 原声请求不得在预检假 ready")

            for source in ("showcase", "savestate", "cheat"):
                library_spec = A.JobSpec("g", "items", source=source, pack=pack)
                library_result = A.orchestrate(library_spec, lib=str(root / "other_library"),
                                               out_dir=str(root / f"library_{source}"))
                ok(A.plan(library_spec, lib=str(root / "other_library"))["status"]
                   == library_result["status"] == "blocked"
                   and A.expected_fingerprint(library_spec, lib=str(root / "other_library")) is None,
                   f"状态契约：{source} 显式拒绝非本路线的 lib 参数")

            unavailable = copy.deepcopy(doc)
            unavailable["rom"] = "missing.nes"
            unavailable_pack = write_pack("unavailable", unavailable)
            with patch.object(SC, "resolve_rom", side_effect=AssertionError("硬阻塞后不得获取 ROM")):
                ok(SC.plan(unavailable_pack, audio=True)["status"] == "blocked"
                   and SC.run(unavailable_pack, root / "audio_no_fetch", audio=True)["status"] == "blocked",
                   "状态契约：原声硬阻塞在索引扫描/网盘调用前短路")
                unavailable["platform"] = "SNES"
                unavailable_pack = write_pack("unverified_unavailable", unavailable)
                ok(SC.plan(unavailable_pack)["status"] == "blocked"
                   and SC.run(unavailable_pack, root / "platform_no_fetch")["status"] == "blocked",
                   "状态契约：未核验平台在索引扫描/网盘调用前短路")

            moved = copy.deepcopy(doc)
            moved["rom"] = "gone.nes"
            moved_pack = write_pack("moved", moved)
            idx = {sha: [str(root / "gone.nes"), str(root / "base.state"), str(root / "game.nes")]}
            found = SC.plan(moved_pack, rom_idx=idx)
            ok(found["status"] == "ready" and found["blockers"] == []
               and found["rom_source"] == "local_index", "状态契约：跳过失效索引候选，真实命中后清除历史阻塞")
            poisoned = SC.resolve_rom(moved_pack, rom_idx={sha: [str(root / "base.state")]})
            ok(poisoned["status"] == "blocked", "状态契约：索引键哈希不能替代文件字节校验")
            hook = SC.plan(moved_pack, rom_idx={}, netdisk_resolver=lambda *args: str(root / "game.nes"))
            ok(hook["status"] == "ready" and hook["blockers"] == [],
               "状态契约：授权 resolver 命中后不遗留旧路径阻塞")


def test_capture_judge_separation():
    """计划书 §10.3 + §2 未宣称能力：检测器改变只重判、不许重录；核心实物/初态出处必须进采集指纹。"""
    import copy
    import json
    import tempfile
    import zipfile
    from unittest.mock import patch
    from PIL import Image
    from . import showcase as SC

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "game.nes").write_bytes(b"NES separation fixture")
        state = root / "base.state"

        def write_state(bizversion):
            with zipfile.ZipFile(state, "w") as z:
                z.writestr("BizVersion.txt", bizversion)
                z.writestr("Core.bin", b"\x00" * 64)

        write_state("BizHawk 2.9.1")
        (root / "bh").mkdir()
        (root / "bh" / "EmuHawk.exe").write_bytes(b"MZ fixture")
        sha = hashlib.sha1((root / "game.nes").read_bytes()).hexdigest().upper()
        doc = {
            "kind": "statejump_showcase", "game_id": "separation_fixture", "platform": "NES",
            "rom": "game.nes", "rom_sha1": sha, "bizhawk": "bh", "base_state": "base.state",
            "catalog": {"status": "complete", "expected_total": 1, "sources": ["synthetic"]},
            "elements": [{
                "element_id": "probe", "label": "Probe", "kind": "weapon",
                "trigger": {"macro": "B,,", "extra": 1, "patches": [{"addr": 16, "value": 1}]},
                "negative_control": {"macro": "B,,", "patches": [{"addr": 16, "value": 0}]},
                "detection": {"frame": 1, "success_checks": [{
                    "check_id": "bright", "plugin_id": "frame_luma_range",
                    "params": {"min": 200, "max": 255}, "required": True}]}}]}
        pack = root / "sep.showcase.json"
        pack.write_text(json.dumps(doc), encoding="utf-8")
        element = doc["elements"][0]

        params = SC.capture_params(element, doc, "NES", 60.0, str(state))
        ok(params["bizversion"] == "BizHawk 2.9.1",
           "判据分离：采集指纹带上存这份初态的模拟器/核心实物身份")
        ok("detection" not in json.dumps(params),
           "判据分离：采集指纹参数里不许出现判据字段")
        alt = copy.deepcopy(doc)
        alt["core"] = "NestopiaUE"
        ok(SC.capture_params(element, alt, "NES", 60.0, str(state)) != params,
           "判据分离：声明核心变了采集指纹必须变")
        moved = copy.deepcopy(element)
        moved["detection"]["frame"] = 0
        ok(SC.capture_params(moved, doc, "NES", 60.0, str(state)) == params,
           "判据分离：只改判据取样帧不得改动采集指纹")
        ok(SC.judge_params(moved) != SC.judge_params(element),
           "判据分离：判据声明必须进判定指纹")
        before_impl = SC.judge_params(element)
        with patch.object(SC, "_detector_impl_sha", return_value="deadbeef"):
            after_impl = SC.judge_params(element)
        ok(before_impl != after_impl, "判据分离：判据实现(detect.py)字节变了必须重判")

        calls = []

        class Session:
            def __init__(self, *a, **k):
                pass

            def start(self):
                return self

            def check_state_profile(self, state_path, name="profile_check"):
                return {"match": True, "state_path": str(state_path)}

            def dump(self, frames_dir, spec=None, extra=0, state=None, patches=None):
                calls.append({"spec": spec, "patches": patches})
                count = SC._macro_frames(spec) + extra
                color = 255 if patches and patches[0]["value"] == 1 else 0
                directory = Path(frames_dir)
                directory.mkdir(parents=True)
                for i in range(count):
                    Image.new("RGB", (8, 8), (color,) * 3).save(directory / f"f{i:04d}.png")
                return count

            def close(self):
                pass

        def encode(frames_dir, fps, out, **kwargs):
            Path(out).write_bytes(b"synthetic clip")
            return out

        def concat(clips, out, **kwargs):
            Path(out).write_bytes(b"synthetic reel")
            return out

        def run(value, out_dir):
            target = root / f"{out_dir}.json"
            target.write_text(json.dumps(value), encoding="utf-8")
            before = len(calls)
            with patch.object(SC.SJ, "StateSession", Session), \
                 patch.object(SC, "_concat_videos", concat), \
                 patch.object(SC, "_video_frames", return_value=4), \
                 patch.object(SC, "verify_detection", wraps=SC.verify_detection) as vd:
                result = SC.run(str(target), root / out_dir, ffmpeg="false",
                                ffprobe="false", encoder=encode)
            return result, len(calls) - before, vd.call_count

        first, dumps, judged = run(doc, "sep")
        ok(first["status"] == "done" and dumps == 2 and judged == 1,
           f"判据分离：首轮采集正反例各一次并判定一次（实际 {dumps}/{judged}）")

        again, dumps, judged = run(doc, "sep")
        ok(again["status"] == "done" and again["passed"] == 1 and dumps == 0 and judged == 0,
           f"判据分离：同指纹续跑不重录也不重判（实际 {dumps}/{judged}）")

        loose = copy.deepcopy(doc)
        loose["elements"][0]["detection"]["success_checks"][0]["params"] = {"min": 0, "max": 10}
        flipped, dumps, judged = run(loose, "sep")
        ok(dumps == 0, f"判据分离：只改判据不得重录（实际重录 {dumps} 次）")
        ok(judged == 1 and flipped["elements"][0]["verdict"] == "fail",
           "判据分离：改宽的判据必须当场把要素判成 fail")

        strict, dumps, judged = run(doc, "sep")
        ok(dumps == 0 and judged == 1 and strict["elements"][0]["verdict"] == "pass",
           "判据分离：判据改回原样同样只重判，要素恢复 pass")

        write_state("BizHawk 2.3.0")
        _, dumps, judged = run(doc, "sep")
        ok(dumps == 2 and judged == 1,
           f"判据分离：初态出处/核心实物变了必须重录（实际 {dumps}/{judged}）")


def test_state_content_fingerprint_gate():
    import tempfile
    from unittest.mock import patch
    from . import statejump as SJ, state_registry as SR

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rom = root / "game.nes"
        state = root / "base.state"
        rom.write_bytes(b"content gate ROM")
        import zipfile
        with zipfile.ZipFile(state, "w") as z:
            z.writestr("Core.bin", b"content gate state")
        rom_sha1 = SJ.sha1_file(rom)
        state_sha256 = hashlib.sha256(state.read_bytes()).hexdigest()
        content_sha256 = SR.state_content_fingerprint(state)["content_sha256"]
        expected = {"px": 128, "scr": 0, "cur": 0, "owned": 0, "hp": 28}
        values = {SJ.STATE_CONTENT_PROBES[k]: v for k, v in expected.items()}

        s = SJ.StateSession.__new__(SJ.StateSession)
        s.platform = "NES"
        s.rom = str(rom)
        s.work = str(root)
        s._rom_sha1 = None
        s.use_state = lambda path, name=None: str(path)
        s.command = lambda op, **kw: {"data": ""}
        s.read = lambda addr: values[addr]
        profiles = {rom_sha1: {content_sha256: {"expected": expected, "source": "fixture"}}}

        physical_report = {"match": True, "core_identity_match": True}
        with patch.object(SJ, "compare_state_core",
                          side_effect=lambda *a: dict(physical_report)), \
             patch.object(SJ, "STATE_CONTENT_PROFILES", profiles):
            rep = s.check_state_profile(str(state))
            ok(rep["match"] is True and rep["content_fingerprint"]["checked"] is True
               and rep["content_fingerprint"]["actual"] == expected
               and rep["content_fingerprint"]["content_sha256"] == content_sha256
               and rep["match_basis"] == "serialized_core_bytes+state_content_fingerprint",
               "内容闸门：五键全相符 => 放行且证据带实际指纹")

            values[0x0480] = 129
            rep = s.check_state_profile(str(state))
            ok(rep["match"] is False and rep["content_fingerprint"]["match"] is False
               and rep["content_fingerprint"]["diff"]["px"] == {"expected": 128, "actual": 129},
               "内容闸门：单键不符 => 拒绝且逐键报差")

            other = root / "other.state"
            with zipfile.ZipFile(other, "w") as z:
                z.writestr("Core.bin", b"unprofiled state")
            rep = s.check_state_profile(str(other))
            ok(rep["match"] is False and rep["content_fingerprint"]["axis"] == "unprofiled_state",
               "内容闸门：已建档游戏的未登记状态 => fail closed")

            s._rom_sha1 = "F" * 40
            rep = s.check_state_profile(str(state))
            ok(rep["match"] is True and rep["content_fingerprint"]["checked"] is False
               and rep["content_fingerprint"]["axis"] == "unprofiled_game",
               "内容闸门：未建档游戏明确标记缺轴，不伪装成已验内容")

            restamped = root / "restamped.state"
            with zipfile.ZipFile(state) as src, zipfile.ZipFile(restamped, "w") as dst:
                for info in src.infolist():
                    dst.writestr(zipfile.ZipInfo(info.filename, date_time=(2026, 11, 24, 8, 0, 0)),
                                 src.read(info.filename))
            s._rom_sha1 = rom_sha1
            values[0x0480] = expected["px"]
            rep = s.check_state_profile(str(restamped))
            ok(rep["match"] is True
               and rep["content_fingerprint"]["content_sha256"] == content_sha256
               and rep["content_fingerprint"]["state_sha256"] != state_sha256,
               "内容闸门：只改 ZIP 时间戳仍命中同一内容指纹")
            physical_report.update(match=False, reason="Core.bin 序列化字节不一致")
            rep = s.check_state_profile(str(restamped))
            ok(rep["match"] is False and "Core.bin 序列化字节不一致" in rep["reason"]
               and rep["content_fingerprint"]["match"] is True
               and rep.get("match_basis") != "serialized_core_bytes+state_content_fingerprint",
               "内容闸门：物理层失败不被内容相符覆盖")


def test_state_profile_gate():
    import copy
    import json
    import tempfile
    import zipfile
    from unittest.mock import patch
    from PIL import Image
    from . import showcase as SC, statejump as SJ, state_registry as SR

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        def mkstate(name, core, ver=b"BizHawk 2.8"):
            p = root / name
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("Core.bin", core)
                z.writestr("BizVersion.txt", ver)
            return p

        a = mkstate("a.state", b"\x01\x02\x03\x04")
        rep = SJ.compare_state_core(a, mkstate("b.state", b"\x01\x02\x03\x04"))
        ok(rep["match"] is True and rep["first_diff_offset"] is None
           and rep["core_identity_match"] is True, "拓扑闸门：同字节 Core.bin => match")
        rep = SJ.compare_state_core(a, mkstate("c.state", b"\x01\x02\x99\x04"))
        ok(rep["match"] is False and rep["first_diff_offset"] == 2,
           "拓扑闸门：单字节差 => 首差异偏移 2")
        rep = SJ.compare_state_core(a, mkstate("d.state", b"\x01\x02\x03"))
        ok(rep["match"] is False and rep["first_diff_offset"] == 3
           and rep["core_bytes_roundtrip"] == 3, "拓扑闸门：长度差 => 短长度处报差异")
        rep = SJ.compare_state_core(a, mkstate("e.state", b"\x01\x02\x03\x04", ver=b"BizHawk 2.9"))
        ok(rep["match"] is True and rep["core_identity_match"] is False,
           "拓扑闸门：BizVersion 身份单独报告")
        bad = root / "f.state"; bad.write_bytes(b"not a zip")
        rep = SJ.compare_state_core(a, bad)
        ok(rep["match"] is False and rep["core_bytes_roundtrip"] is None,
           "拓扑闸门：坏 zip => 不 match 不抛异常")
        with zipfile.ZipFile(root / "g.state", "w") as z:
            z.writestr("Other.bin", b"x")
        ok(SJ.compare_state_core(a, root / "g.state")["match"] is False,
           "拓扑闸门：缺 Core.bin => 不 match")

        # ---- 生产入口契约：假会话 + 真实编排/判定/台账路径 ----
        (root / "game.nes").write_bytes(b"NES gate fixture")
        (root / "base.state").write_bytes(b"STATE gate fixture")
        (root / "alt.state").write_bytes(b"STATE alt fixture")
        (root / "bh").mkdir()
        (root / "bh" / "EmuHawk.exe").write_bytes(b"MZ fixture")
        sha = hashlib.sha1((root / "game.nes").read_bytes()).hexdigest().upper()
        doc = {
            "kind": "statejump_showcase", "game_id": "gate_fixture", "platform": "NES",
            "rom": "game.nes", "rom_sha1": sha, "bizhawk": "bh", "base_state": "base.state",
            "catalog": {"status": "complete", "expected_total": 1, "sources": ["synthetic"]},
            "elements": [{
                "element_id": "probe", "label": "Probe", "kind": "weapon",
                "trigger": {"macro": "B,,", "extra": 1, "patches": [{"addr": 16, "value": 1}]},
                "negative_control": {"macro": "B,,", "patches": [{"addr": 16, "value": 0}]},
                "detection": {"frame": 1, "success_checks": [{
                    "check_id": "bright", "plugin_id": "frame_luma_range",
                    "params": {"min": 200, "max": 255}, "required": True}]}}]}

        def write_pack(name, value):
            p = root / f"{name}.json"
            p.write_text(json.dumps(value), encoding="utf-8")
            return str(p)

        def encode(frames_dir, fps, out, **kw):
            Path(out).write_bytes(b"synthetic clip")
            return out

        def concat(clips, out, **kw):
            Path(out).write_bytes(b"synthetic reel")
            return out

        sessions = []

        def session_cls(gate_match=True, by_name=None, raise_on_gate=False, content_match=True):
            class Session:
                def __init__(self, *a, **k):
                    self.closed = False
                    self.gates = []
                    self.dumps = 0
                    sessions.append(self)

                def start(self):
                    return self

                def check_state_profile(self, state_path, name="profile_check"):
                    self.gates.append(Path(state_path).name)
                    if raise_on_gate:
                        raise RuntimeError("savestate.load 拒绝（核心不符）")
                    m = gate_match if by_name is None else by_name.get(Path(state_path).name, gate_match)
                    rep = {"match": m, "state_path": str(state_path),
                           "content_fingerprint": {
                               "axis": "state_fingerprint", "checked": True, "match": content_match,
                               "expected": {"px": 128, "scr": 0, "cur": 0, "owned": 0, "hp": 28},
                               "actual": {"px": 128 if content_match else 129, "scr": 0,
                                          "cur": 0, "owned": 0, "hp": 28}}}
                    if not m:
                        rep.update(reason="Core.bin 内容不一致（首差异偏移 14970，14982→14977 字节）",
                                   first_diff_offset=14970)
                    if not content_match:
                        rep["match"] = False
                        rep["reason"] = "状态内容指纹不符: px"
                    return rep

                def dump(self, frames_dir, spec=None, extra=0, state=None, patches=None):
                    self.dumps += 1
                    count = SC._macro_frames(spec) + extra
                    color = 255 if patches and patches[0]["value"] == 1 else 0
                    d = Path(frames_dir); d.mkdir(parents=True, exist_ok=True)
                    for i in range(count):
                        Image.new("RGB", (8, 8), (color,) * 3).save(d / f"f{i:04d}.png")
                    return count

                def close(self):
                    self.closed = True
            return Session

        pack = write_pack("gate_pack", doc)
        with patch.object(SR, "ASSET_ROOT", root / "assets"), \
             patch.object(SC, "_video_frames", return_value=4):
            # 1) 拓扑不符 => 采集前整体 blocked，零 dump，证据落盘，会话关闭
            r = SC.run(pack, root / "mismatch", template="none",
                       session_factory=session_cls(gate_match=False),
                       encoder=encode, concatenator=concat)
            s = sessions[-1]
            ok(r["status"] == "blocked"
               and r["blockers"][0]["code"] == "profile_mismatch"
               and r["blockers"][0]["first_diff_offset"] == 14970,
               "拓扑闸门：Core.bin 不符 => profile_mismatch 整体拒绝")
            ok(s.dumps == 0 and s.closed and not (root / "mismatch" / "clips" / "probe.mp4").exists(),
               "拓扑闸门：不符时零采集、无片段、会话已关")
            gates = list((root / "mismatch" / "evidence").glob("state_profile_gate_*.json"))
            ok(len(gates) == 1 and json.loads(gates[0].read_text(encoding="utf-8"))["match"] is False,
               "拓扑闸门：不符证据落盘可查")

            # 2) 加载失败（错核心）=> 同样 profile_mismatch，不崩成别的错
            r = SC.run(pack, root / "loadfail", template="none",
                       session_factory=session_cls(raise_on_gate=True),
                       encoder=encode, concatenator=concat)
            ok(r["status"] == "blocked" and r["blockers"][0]["code"] == "profile_mismatch"
               and sessions[-1].dumps == 0,
               "拓扑闸门：零帧加载失败 => profile_mismatch 不冒充其他失败")

            # 2b) 内容指纹不符 => 采集前整体 blocked，零 dump，证据带五键
            r = SC.run(pack, root / "content_bad", template="none",
                       session_factory=session_cls(content_match=False),
                       encoder=encode, concatenator=concat)
            s = sessions[-1]
            ok(r["status"] == "blocked" and r["blockers"][0]["code"] == "profile_mismatch"
               and r["blockers"][0]["content_fingerprint"]["actual"]["px"] == 129
               and s.dumps == 0,
               "内容闸门：五键不符 => profile_mismatch 整体拒绝且零采集")
            gates = list((root / "content_bad" / "evidence").glob("state_profile_gate_*.json"))
            ok(len(gates) == 1
               and json.loads(gates[0].read_text(encoding="utf-8"))["content_fingerprint"]["match"] is False,
               "内容闸门：不符证据落盘且保留 expected/actual")

            # 3) 拓扑相符 => 正常完成，base 只核一次（正反例共享缓存）
            r = SC.run(pack, root / "match", template="none",
                       session_factory=session_cls(gate_match=True),
                       encoder=encode, concatenator=concat)
            s = sessions[-1]
            ok(r["status"] == "done" and r["passed"] == 1 and s.dumps == 2
               and s.gates == ["base.state"],
               "拓扑闸门：相符 => 正常采集，同 sha 状态只核一次")
            ok(r["state_profile_gates"][0]["match"] is True
               and r["state_profile_gates"][0]["content_fingerprint"]["match"] is True,
               "拓扑/内容闸门：报告携带物理层与五键内容证据")

            # 4) 要素级 override 状态也要过闸
            alt_doc = copy.deepcopy(doc)
            alt_doc["elements"][0]["base_state"] = "alt.state"
            alt_pack = write_pack("gate_alt", alt_doc)
            r = SC.run(alt_pack, root / "alt_bad", template="none",
                       session_factory=session_cls(by_name={"probe.state": False}),
                       encoder=encode, concatenator=concat)
            ok(r["status"] == "blocked" and r["blockers"][0]["code"] == "profile_mismatch"
               and sessions[-1].dumps == 0 and sessions[-1].gates == ["base.state", "probe.state"],
               "拓扑闸门：要素 override 坏状态在 dump 前被拒")

            # 5) 声明层：sync_settings 与 config.ini 不符 => 启动模拟器前拒绝
            decl_doc = copy.deepcopy(doc)
            decl_doc["sync_settings"] = {"NesRightPort": "ControllerNES"}
            decl_pack = write_pack("gate_decl", decl_doc)
            cfg = {"CoreSyncSettings": {"BizHawk.Emulation.Cores.Nintendo.NES.NES": {
                "Controls": {"NesLeftPort": "ControllerNES", "NesRightPort": "UnpluggedNES"}}}}
            (root / "bh" / "config.ini").write_text(json.dumps(cfg), encoding="utf-8")
            n0 = len(sessions)
            r = SC.run(decl_pack, root / "decl_bad", template="none",
                       session_factory=session_cls(), encoder=encode, concatenator=concat)
            ok(r["status"] == "blocked" and r["blockers"][0]["code"] == "profile_mismatch"
               and len(sessions) == n0
               and (root / "decl_bad" / "evidence" / "state_profile_gate_declaration.json").is_file(),
               "拓扑闸门：声明与配置不符 => 不启动模拟器即拒")
            cfg["CoreSyncSettings"]["BizHawk.Emulation.Cores.Nintendo.NES.NES"]["Controls"]["NesRightPort"] = "ControllerNES"
            (root / "bh" / "config.ini").write_text(json.dumps(cfg), encoding="utf-8")
            r = SC.run(decl_pack, root / "decl_ok", template="none",
                       session_factory=session_cls(), encoder=encode, concatenator=concat)
            ok(r["status"] == "done" and r["state_profile_gates"][0]["sync_controls"]["NesRightPort"]
               == "ControllerNES", "拓扑闸门：声明相符 => 放行且证据含实际拓扑")

            # 6) 非法声明 schema 拒绝
            bad_decl = copy.deepcopy(doc)
            bad_decl["sync_settings"] = {"NesRightPort": 3}
            raises(lambda: SC.validate_spec(bad_decl), "拓扑闸门：sync_settings 非 str/bool 值被拒")


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

        # ---- rom_available：预筛必须走 acquire 那条候选链（11-22 接线缺口） ----
        # 旧预筛只看 出版物 rom_sha1 + version 页两处，acquire 已解开的假阻塞会在矩阵这层原样复发。
        import hashlib as _hl
        import zipfile as _zf
        good = _hl.sha1(b"MATRIX-LOCAL-ROM").hexdigest().upper()
        site_stale = _hl.sha1(b"MATRIX-STALE-SITE").hexdigest().upper()
        mdir = td / "movies" / "NES"
        mdir.mkdir(parents=True, exist_ok=True)
        with _zf.ZipFile(mdir / "7.bk2", "w") as z:
            z.writestr("Header.txt", f"Platform NES\nSHA1 {good}\n")
        pub_header_only = {"id": "7", "game": "Header Only", "platform": "NES",
                           "rom_sha1": site_stale, "local_movie": "movies/NES/7.bk2"}
        ok(M.rom_available(pub_header_only, td, {good}, versions={}) is True,
           "matrix：站点哈希过期、只有 bk2 Header 对得上本地 => 预筛放行（旧两处筛会误杀）")
        ok(M.rom_available(pub_header_only, td, set(), versions={}) is False,
           "matrix：两份候选都不在本地时预筛照样拦（恒量反证：只换 romset）")
        ok(M.rom_available({"id": "8", "game": "Site Hit", "platform": "NES",
                            "rom_sha1": good, "local_movie": "movies/NES/nope.bk2"},
                           td, {good}, versions={}) is True,
           "matrix：出版物 rom_sha1 直接命中仍放行（换候选顺序不许把首选弄丢）")

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
            M.orchestrate = lambda spec, lib=None, out_dir=None, dry_run=False, allow=(): (
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

        # ---- famous_playthrough_cells：预筛 + 排除 + 同名去重 + 热门名单（合成 lib）----
        lib, pub, sha1, rom, bk2 = _synthetic_nes_lib(td, game="Contra", pid="7001")
        # 追加：同名第二条（去重）、被排除名、ROM 不在索引（预筛掉）、名单外冷门
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
        # 名单外冷门：ROM、片子、版本全都齐，唯独作品不出名 => 一律不建格（用户 2026-11-22 口径）
        p_obscure = copy.deepcopy(pub); p_obscure["id"] = "7005"
        p_obscure["game"] = "Alwa's Awakening: The 8-Bit Edition"
        p_obscure["local_movie"] = "movies/NES/7005.bk2"
        shutil.copy(bk2, str(Path(lib) / "movies" / "NES" / "7005.bk2"))
        pubs["7005"] = p_obscure
        (lib / "publications.json").write_text(json.dumps({"publications": pubs}), encoding="utf-8")
        orig_disc = R.discover_bizhawk
        try:
            R.discover_bizhawk = lambda emu_root: {"2.8": str(td / "fake_bh")}
            cells = M.famous_playthrough_cells(lib, exclude=["Excluded"], frames=600)
            games = [c["game"] for c in cells]
            ok(games == ["Contra"], "matrix：famous 预筛掉无ROM+排除名+同名去重+名单外冷门 => 只剩 1 格")
            ok(cells[0]["frames"] == 600 and cells[0]["job_type"] == "playthrough",
               "matrix：famous 格带 frames/job_type")
            # 恒量反证：条件完全相同（ROM 齐、片子齐、同名唯一），只把作品换成名单上的
            # NES 名作「Metroid」，格子必须出现——证明筛子拦的是「冷门」而不是「这批资源没备齐」。
            p_control = copy.deepcopy(pub); p_control["id"] = "7006"
            p_control["game"] = "Metroid"
            p_control["local_movie"] = "movies/NES/7006.bk2"
            shutil.copy(bk2, str(Path(lib) / "movies" / "NES" / "7006.bk2"))
            pubs["7006"] = p_control
            (lib / "publications.json").write_text(json.dumps({"publications": pubs}), encoding="utf-8")
            games2 = sorted(c["game"] for c in M.famous_playthrough_cells(lib, exclude=["Excluded"], frames=600))
            ok(games2 == ["Contra", "Metroid"], "matrix：famous 反证——换成名作就建格（拦的是冷门不是资源）")

            # ---- 样片帧数按平台下限：SNES 片头实测比 NES 长得多 ----
            # 恒量反证：同样给 600 帧，NES 保持 600（上面那格就是证据），SNES 抬到 3000。
            ok(M.slice_frames("NES", 600) == 600, "matrix：slice_frames NES 不抬高（600 保持）")
            ok(M.slice_frames("SNES", 600) == 3000, "matrix：slice_frames SNES 600 => 抬到 3000 下限")
            ok(M.slice_frames("SFC", 600) == 3000, "matrix：slice_frames SFC 别名同样抬高")
            ok(M.slice_frames("SNES", 5000) == 5000, "matrix：slice_frames 已超下限就尊重原值")
            ok(M.slice_frames("SNES", None) is None, "matrix：slice_frames None=整片，不动")
            ok(M.slice_frames("GBA", 600) == 600, "matrix：slice_frames 未标定平台不臆造下限")
            ok(M.slice_frames("", 600) == 600, "matrix：slice_frames 空平台不臆造下限")
            # 上限：endpoint_reached 判 n==期望，被下限抬高的一档不许越过片长，否则自造假失败
            ok(M.slice_frames("SNES", 600, 1200) == 1200, "matrix：slice_frames 下限抬高后封顶到片长")
            ok(M.slice_frames("NES", 600, 400) == 600, "matrix：slice_frames 显式请求不被封顶改动")
            ok(M.slice_frames("SNES", None, 400) is None, "matrix：slice_frames 整片请求不封顶不抬高")
            ok(M.slice_frames("SNES", 600, None) == 3000, "matrix：slice_frames 读不到片长不臆造上限")
            ok(M.slice_frames("SNES", 600, 90000) == 3000, "matrix：slice_frames 片长充裕时下限生效")
        finally:
            R.discover_bizhawk = orig_disc


def test_audio_blocker_not_degradable():
    from pathlib import Path
    from . import control as C
    doc = {
        "version": 1, "id": "selftest-audio-required", "mode": "session",
        "purpose": "control", "game": "t", "platform": "NES",
        "rom": {"path": "F:/不存在/rom.nes", "sha1": "0" * 40},
        "profile": {"bizhawk": "F:/不存在/BizHawk", "core": "NesHawk", "system": "NES"},
        "start": {"kind": "movie", "path": "F:/不存在/movie.bk2", "sha256": "0" * 64},
        "steps": [{"id": "p1", "op": "replay", "frames": 1}], "completion": {},
        "record": {"video": True, "audio": True, "fps": 60.0988},
    }
    base = Path(__file__).resolve().parent
    blocked = C.plan(doc, base)
    downgraded = C.plan(doc, base, ("audio_not_wired",))
    ok("audio_not_wired" in {b["code"] for b in blocked["blockers"]},
       "正式录音任务：audio_not_wired 必须在启动前阻塞")
    ok("audio_not_wired" in {b["code"] for b in downgraded["blockers"]}
       and "audio_not_wired" not in {w["code"] for w in downgraded["warnings"]},
       "正式录音任务：--allow 不得把缺原声降级成 warning")


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
        ok(checks["audio_preserved"]["verdict"] == "inconclusive",
           "mask/showcase：无音轨采集保持音频未验，不得给出 audio_preserved=pass")
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


def test_bundle():
    """素材契约（gameplay_bundle/1.0）：生成 + 独立校验 + 篡改反例。

    合成小样（ffmpeg lavfi 真视频），不依赖模拟器；知识包用真实 contra 包的一份副本，
    因为「事实只从知识包来」这条只有拿真字段才测得出臆造。
    """
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path
    from PIL import Image
    from . import bundle as B

    pack_src = Path(__file__).resolve().parent / "游戏包" / "contra_weapons.showcase.json"
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        doc = json.loads(pack_src.read_text(encoding="utf-8"))
        pack = td / "mini.showcase.json"
        pack.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

        run = td / "run"
        for s in ("clips", "controls", "evidence"):
            (run / s).mkdir(parents=True)
        fps = "150247/2500"                            # 与魂斗罗成片同一时间基，不是凑整的 60

        def mp4(p, n=30, audio=False):
            cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                   "-i", f"testsrc2=size=256x224:rate={fps}"]
            if audio:
                cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
                        "-map", "0:v", "-map", "1:a", "-c:a", "aac",
                        "-t", f"{n * 2500 / 150247:.6f}"]
            cmd += ["-frames:v", str(n), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)]
            subprocess.run(cmd, check=True, capture_output=True)

        N = 36                                          # 每段帧数，要罩得住最晚的检测锚点(30)
        els, cur = [], 0
        for pe in doc["elements"]:
            eid = pe["element_id"]
            seg, neg = run / "clips" / f"{eid}.mp4", run / "controls" / f"{eid}_negative.mp4"
            mp4(seg, N), mp4(neg, N)
            pos_png, neg_png = run / "evidence" / f"{eid}_p.png", run / "evidence" / f"{eid}_n.png"
            Image.new("RGB", (256, 224), (254, 254, 254)).save(pos_png)
            Image.new("RGB", (256, 224), (0, 0, 0)).save(neg_png)
            a = pe["detection"]["frame"]
            els.append({"element_id": eid, "label": pe["label"], "kind": pe["kind"],
                        "state_origin": "display_patch", "total_frames": N,
                        "clip_ref": str(seg), "deliverable_ref": str(seg),
                        "negative_clip_ref": str(neg), "verdict": "pass", "export_verdict": "pass",
                        "detection": {"positive": {"frame": str(pos_png), "verdict": "pass"},
                                      "negative": {"frame": str(neg_png), "verdict": "fail"}},
                        "reel_window": {"start_frame": cur, "end_frame": cur + N,
                                        "start_seconds": round(cur * 2500 / 150247, 4),
                                        "end_seconds": round((cur + N) * 2500 / 150247, 4),
                                        "event_frame": cur + a,
                                        "event_seconds": round((cur + a) * 2500 / 150247, 4)}})
            cur += N
        reel = run / "reel.mp4"
        mp4(reel, cur)
        report = {"verdict": "pass", "passed": len(els), "total": len(els),
                  "game_id": doc["game_id"], "deliverable_ref": str(reel), "elements": els}
        (run / "showcase_report.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        orig_plan = B.SC.plan
        fake_state = td / "状态资产" / "contra_nes_us" / "contra_u_c9ea66bb" / \
            "r20261114T043740" / "states" / "base.state"
        fake_state.parent.mkdir(parents=True)
        fake_state.write_bytes(b"STATE")
        B.SC.plan = lambda p: {"resources": {"base_state": str(fake_state)},
                               "rom_source": "pack_path"}
        try:
            out = td / "bundle"
            m = B.build(str(pack), run, out, bundle_id="mini_elements_d1")
        finally:
            B.SC.plan = orig_plan
        ok(m["schema_version"] == "gameplay_bundle/1.0" and m["package_status"] == "draft",
           "bundle：生成即 draft，不是默认已放行")
        ids = [c["clip_id"] for c in m["clips"]]
        ok(ids[0] == "reel_full" and len(ids) == 1 + 2 * len(els) and
           all(e["element_id"] in ids and f"{e['element_id']}_negative" in ids for e in els),
           "bundle：合辑/要素段/负对照三类素材都入账")
        ok(all(c["has_audio"] is False for c in m["clips"]),
           "bundle：showcase 逐帧采集如实标 has_audio=false（不假装带原声）")
        ok(all(Path(c["path"]).parts[0] == "clips" and ":" not in c["path"] and ".." not in c["path"]
               for c in m["clips"]),
           "bundle：素材路径全相对、无盘符无 ..（可整目录搬走）")
        ok(len(m["files"]) == sum(1 for p in out.rglob("*") if p.is_file() and p.name != "manifest.json"),
           "bundle：files[] 与盘上实物一一对上（不含 manifest 自己）")
        ck = json.loads((out / m["clips"][0]["clock_ref"]).read_text(encoding="utf-8"))
        ok(len(ck["rows"]) == m["clips"][0]["frame_count"] == 180 and
           ck["rows"][19]["source_seconds"] == round(19 * 2500 / 150247, 6),
           "bundle：帧→时刻映射按真实时间基逐帧给出（解说对句不用自己推算 fps 小数）")
        ev = m["events"][0]
        ok(ev["anchor_frame"] == 19 and ev["reel_window"]["end_frame"] == 36 and
           ev["input"]["ram_patches"] == [{"addr": 170, "value": 0}],
           "bundle：事件带锚点帧/合辑窗口/触发输入（含 RAM 写入原值）")
        cat = next(f for f in m["facts"] if f["type"] == "element_catalog")
        ok("170" in cat["statement"] and cat["source"]["pack"] == "mini.showcase.json" and
           cat["verification"] == "measured_capture",
           "bundle：事实句只复述知识包字段并标出处，没编招式效果")
        ok(m["rights"]["publish_policy_review"] == "not_reviewed" and m["tas"]["mode"] == "elements_adaptive",
           "bundle：发布政策未审查 + 要素线时间轴模式如实声明")
        res = B.verify(out, require_status="draft")
        ok(res["ok"] and res["errors"] == [], "bundle：干净小样 verify(draft) 全通过")
        res_ready = B.verify(out, require_status="ready")
        ok(not res_ready["ok"] and any("发布政策" in x for x in res_ready["errors"]) and
           any("未达 ready" in x for x in res_ready["errors"]),
           "bundle：未审查的包不许当 ready 交付（self_produced 不算放行）")
        try:
            B.publish(out)
            signed = False
        except B.BundleError:
            signed = True
        ok(signed, "bundle：没有审查人署名不许升 ready")
        B.publish(out, reviewer="selftest")
        ok(B.verify(out, require_status="ready")["ok"] and B.load(out)["package_status"] == "ready",
           "bundle：署名审查后 ready 包能通过交付校验")

        good = td / "good"
        shutil.copytree(str(out), str(good))
        manifest_of = lambda r: json.loads((r / "manifest.json").read_text(encoding="utf-8"))

        def errs_after(root, mutate):
            """在副本上动手，返回校验意见；真实资产仓/干净小样都不受影响。"""
            work = Path(str(root) + "_t")
            if work.exists():
                shutil.rmtree(str(work))
            shutil.copytree(str(root), str(work))
            mutate(work)
            r = B.verify(work, require_status="draft")
            shutil.rmtree(str(work))
            return r["errors"]

        def trunc(p):
            (p / "clips" / "default_rifle.mp4").write_bytes(
                (p / "clips" / "default_rifle.mp4").read_bytes()[:200])

        ok(any("文件与清单不符" in x for x in errs_after(good, trunc)),
           "bundle 反例：实物被截断 => 拦下（哈希/大小现算，不信手填）")

        def drop(p):
            (p / "clips" / "default_rifle.mp4").unlink()

        e = errs_after(good, drop)
        ok(any("清单文件缺失" in x for x in e) and any("clip 文件缺失" in x for x in e),
           "bundle 反例：丢文件 => 拦下")

        def add(p):
            (p / "clips" / "extra.mp4").write_bytes(b"x" * 10)

        ok(any("未登记文件" in x for x in errs_after(good, add)),
           "bundle 反例：包里有没登记的东西 => 视为未完成交接")

        def bump_frame(root):
            mm = manifest_of(root)
            mm["clips"][1]["frame_count"] += 1
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("帧数不符" in x for x in errs_after(good, bump_frame)),
           "bundle 反例：声明帧数与实物差 1（错帧/被重采样）=> 拦下")

        def bump_window(root):
            mm = manifest_of(root)
            mm["events"][0]["reel_window"]["end_frame"] -= 5
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("段长" in x for x in errs_after(good, bump_window)),
           "bundle 反例：合辑窗口长度 != 段长（时间映射不可信）=> 拦下")

        def escape_files(root):
            mm = manifest_of(root)
            mm["files"][0]["path"] = "../../Windows/win.ini"
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any(".." in x for x in errs_after(good, escape_files)),
           "bundle 反例：清单写 .. 逃逸路径 => 拒收")

        def abs_clip(root):
            mm = manifest_of(root)
            mm["clips"][0]["path"] = "C:/abs/reel.mp4"
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("绝对路径" in x for x in errs_after(good, abs_clip)),
           "bundle 反例：clip 写绝对路径 => 拒收")

        def drop_clock_row(root):
            mm = manifest_of(root)
            cpath = root / mm["clips"][0]["clock_ref"]
            c = json.loads(cpath.read_text(encoding="utf-8"))
            c["rows"] = c["rows"][:-1]
            cpath.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")

        ok(any("映射行数" in x for x in errs_after(good, drop_clock_row)),
           "bundle 反例：帧映射少一行 => 拦下（末帧会被解说错位）")

        def skip_pts(root):
            mm = manifest_of(root)
            cpath = root / mm["clips"][0]["clock_ref"]
            c = json.loads(cpath.read_text(encoding="utf-8"))
            c["rows"][7]["clip_frame"] = 9
            cpath.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")

        ok(any("不连续" in x for x in errs_after(good, skip_pts)),
           "bundle 反例：映射帧号跳号 => 拦下")

        def wrong_clock(root):
            mm = manifest_of(root)
            mm["clock"]["fps_declared"] = 50.0
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("帧率与声明不符" in x for x in errs_after(good, wrong_clock)),
           "bundle 反例：声明 50Hz 而实物 60.0988（错区域/错时钟档）=> 拦下")

        def fake_pass(root):
            mm = manifest_of(root)
            mm["verification"]["gameplay"]["verdict"] = "fail"
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("gameplay 层未过" in x for x in errs_after(good, fake_pass)),
           "bundle 反例：gameplay 层没过 => 整包不算 pass")

        def elem_fail(root):
            mm = manifest_of(root)
            mm["events"][0]["verdict"] = "inconclusive"
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("未过检测" in x for x in errs_after(good, elem_fail)),
           "bundle 反例：把没测出的要素写成通过 => 拦下（假 pass）")

        def unknown_key(root):
            mm = manifest_of(root)
            mm["narration_already_written"] = True
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("未知顶层字段" in x for x in errs_after(good, unknown_key)),
           "bundle 反例：未知字段不静默忽略 => 契约漂移当场暴露")

        def no_facts(root):
            mm = manifest_of(root)
            del mm["facts"]
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("缺必填字段组" in x for x in errs_after(good, no_facts)),
           "bundle 反例：整组字段缺失 => 拦下")

        def null_identity(root):
            mm = manifest_of(root)
            mm["profile"]["state_package_revision"] = None
            mm["job"]["job_fingerprint"] = ""
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        e = errs_after(good, null_identity)
        ok(sum("身份字段为空" in x for x in e) == 2,
           "bundle 反例：状态包版本/任务指纹留空 => 两条各点名一次（复用范围无法界定）")

        def short_cover(root):
            mm = manifest_of(root)
            mm["job"]["declared_total"] = 9
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("覆盖不足" in x for x in errs_after(good, short_cover)),
           "bundle 反例：清单声明 9 只交付 5 => 不许当完整包")

        def no_reel(root):
            mm = manifest_of(root)
            mm["job"]["complete"] = False
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("完整交接包" in x for x in errs_after(good, no_reel)),
           "bundle 反例：缺全要素合辑 => 不算完整包")

        def fabricated(root):
            mm = manifest_of(root)
            mm["facts"][0]["statement"] = "   "
            mm["facts"][1]["source"] = {}
            mm["facts"][2]["evidence_refs"] = ["evidence/没有这张.png"]
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        e = errs_after(good, fabricated)
        ok(any("无原句" in x for x in e) and any("无来源" in x for x in e) and
           any("证据缺失" in x for x in e),
           "bundle 反例：无出处/无证据/空原句的事实 => 三条各拦一次")

        def smuggle(root):
            mm = manifest_of(root)
            mm["rights"]["rom_path"] = "D:/roms/Contra.nes"
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        ok(any("禁用字段" in x for x in errs_after(good, smuggle)),
           "bundle 反例：包内出现 ROM 路径线索 => 拦下（交接包不带游戏文件）")

        def lie_audio(root):
            mm = manifest_of(root)
            withsfx = Path(str(root) + "_sfx.mp4")
            mp4(withsfx, N, audio=True)
            shutil.copyfile(str(withsfx), str(root / "clips" / "default_rifle.mp4"))
            c = mm["clips"][1]
            real = root / c["path"]
            c["sha256"], c["byte_size"] = B.sha256_file(str(real)), real.stat().st_size
            c["has_audio"] = False
            mm["files"] = [f for f in mm["files"] if f["path"] != c["path"]]
            mm["files"].append({"path": c["path"], "sha256": c["sha256"], "byte_size": c["byte_size"]})
            (root / "manifest.json").write_text(json.dumps(mm, ensure_ascii=False), encoding="utf-8")

        e = errs_after(good, lie_audio)
        ok(any("原声声明与实物不符" in x for x in e),
           "bundle 反例：素材其实有声却声明无原声 => 拦下（解说排 ducking 会对不上）")
        ok(json.loads((good / "manifest.json").read_text(encoding="utf-8"))["package_status"] == "ready",
           "bundle：所有篡改反例都只在临时副本上动，干净小样本身没被改")


def test_soccer2_oam():
    """热血足球2 OAM 球权闸门（11-14 实跑坑落成断言）：合成 OAM 正例 + 恒量反证格。"""
    from . import universal_authoring as UA

    def page(entries):
        ram = bytearray(2048)
        for i in range(64):
            ram[0x200 + 4 * i] = 248
        for i, e in enumerate(entries):
            ram[0x200 + 4 * i : 0x204 + 4 * i] = bytes(e)
        return bytes(ram)

    cap = [(70, 0xC0, 0x01, 49), (78, 0x00, 0x41, 45), (78, 0x01, 0x41, 53),
           (102, 0x30, 0x41, 45), (102, 0x31, 0x41, 53)]
    ball = [(100, 0xC5, 0x40, 49), (100, 0xC5, 0x00, 57), (108, 0xD5, 0x40, 49), (108, 0xD5, 0x00, 57)]
    p = UA.soccer2_oam_parse(page(cap + ball))
    ok(p is not None and p["cap"] == (53, 110) and p["ball"] == (57, 108), "OAM：队长脚底/球心坐标解码")
    ok(p is not None and p["dist"] < UA.SOCCER2_POSSESS_DIST and p["holder_team"] == 1, "OAM：球在脚边=我方持球")
    ok(p is not None and p["opp_dist"] is None, "OAM：场上无对手组时 opp_dist=None")
    far = [(y, t, a, x + 40) for (y, t, a, x) in ball]
    pf = UA.soccer2_oam_parse(page(cap + far))
    ok(pf is not None and pf["dist"] >= UA.SOCCER2_POSSESS_DIST, "OAM 反证：球离脚 40px 不得判持球")
    ok(UA.soccer2_oam_parse(page(cap + [(y, t, 0x41, x) for (y, t, a, x) in ball])) is None,
       "OAM 反证：球组 palette 非 0 不算球")
    ok(UA.soccer2_oam_parse(page(cap[1:] + ball)) is None, "OAM 反证：缺 0xC0 号码标记=None")
    ok(UA.soccer2_oam_parse(page(cap + ball[:3])) is None, "OAM 反证：球组不足 4 sprite=None")
    opp = [(92, 0x4B, 0x03, 53), (92, 0x4C, 0x03, 61), (100, 0x30, 0x03, 53), (100, 0x31, 0x03, 61)]
    cap2 = [(y, t, a, x - 30) for (y, t, a, x) in cap]
    po = UA.soccer2_oam_parse(page(cap2 + ball + opp))
    ok(po is not None and po["holder_team"] == 3, "OAM：对手贴球时 holder_team=3（白帽客队实测）")
    ok(po is not None and po["opp_dist"] is not None and po["opp_dist"] < 40, "OAM：opp_dist 量到贴脸对手")
    ok(UA.soccer2_dir_toward(0, 0, 30, 0) == "Right", "追球方向：右")
    ok(UA.soccer2_dir_toward(0, 0, 0, -30) == "Up", "追球方向：上")
    ok(UA.soccer2_dir_toward(0, 0, 20, 20) == "Right+Down", "追球方向：对角")
    ok(UA.soccer2_dir_toward(0, 0, 3, 3) == "", "追球方向：死区不按键")
    ok(not {0xD8} <= UA.SOCCER2_BALL_TILES and {0xD8} <= UA.SOCCER2_BALL_TILES_EXTENDED,
       "必杀球 tile 出正常集但在扩展集（变形球可被时间线捕获）")
    # 净持球判据（11-14 实测）：正例 + 恒量反证格（假持球/邻敌/客持/离脚）。
    ok(UA.soccer2_possess_ok(p), "净持球正例：队长本人持球且无贴脸对手")
    ok(UA.soccer2_possess_ok(dict(p, opp_dist=101.0)), "净持球：远敌(>40)不拒")
    ok(not UA.soccer2_possess_ok(dict(p, holder_dist=p["dist"] + 1.9)),
       "净持球反证：球在队友脚下(holder_dist≠dist)不得判持球")
    ok(not UA.soccer2_possess_ok(dict(p, opp_dist=19.6)), "净持球反证：邻敌贴脸(<=40)拒")
    ok(not UA.soccer2_possess_ok(dict(p, holder_team=3)), "净持球反证：客队持球拒")
    ok(not UA.soccer2_possess_ok(dict(p, dist=50.0)), "净持球反证：球离脚拒")
    ok(not UA.soccer2_possess_ok(None), "净持球反证：OAM 解析 None 拒")

    # ---- 11-15 三条铁律落成闸门（soccer2_unlock_grid / soccer2_ball_pixel 实跑坑）----
    ok(UA.MIN_KEY_FRAMES == 2, "单帧按键不生效：宏生成器帧数下限必须是 2")
    ok(UA.hold("B", 1) == "B,B" and UA.hold("B", 0).count("B") == 2,
       "hold() 把 0/1 帧抬到 2 帧（旧 max(1,..) 会静默产出吞键宏）")
    ok(UA.spec_violations("B,,A") == [{"key": "B", "at": 0, "frames": 1},
                                      {"key": "A", "at": 2, "frames": 1}],
       "宏谱审计：两处单帧都要点名（键名+起始帧+帧数）")
    ok(UA.spec_violations(UA.hold("A+B", 4, 6) + "," + UA.hold("B", 6)) == [],
       "宏谱审计反证：合规宏不得报违规")

    import tempfile
    from pathlib import Path as _P
    from PIL import Image as _Im, ImageDraw as _ImageDraw
    with tempfile.TemporaryDirectory() as td:
        def canvas(name, boxes, bg=(30, 120, 30)):
            im = _Im.new("RGB", (256, 224), bg)
            d = _ImageDraw.Draw(im)
            for (x, y, w, h, v) in boxes:
                d.rectangle([x, y, x + w - 1, y + h - 1], fill=(v, v, v))
            fp = _P(td) / name
            im.save(fp)
            return str(fp)

        # 真球 = 12×12 近白（实测 area 78–80）
        f = canvas("ball.png", [(60, 100, 12, 12, 245)])
        b = UA.soccer2_ball_blobs(f)
        ok(len(b) == 1 and b[0]["w"] == 12 and b[0]["h"] == 12 and UA.soccer2_ball_pos(f) == (66, 106),
           "画面团块球判据：12×12 近白命中并给球心")
        # 恒量反证格 1：球员白衫 10×16（实测 area 114）不得当球
        ok(UA.soccer2_ball_blobs(canvas("shirt.png", [(60, 96, 10, 16, 245)])) == [],
           "球判据反证：球员白衫 10×16 不得当球（只按面积筛就会误判）")
        # 恒量反证格 2：HUD 带内的近白条不得当球
        ok(UA.soccer2_ball_blobs(canvas("hud.png", [(20, 200, 12, 12, 245)])) == [],
           "球判据反证：y>=190 HUD 带整条裁掉，带内白块不得当球")
        # 恒量反证格 3：灰度不够（草地）不得当球 —— min(R,G,B) 判据而非亮度
        ok(UA.soccer2_ball_blobs(canvas("dim.png", [(60, 100, 12, 12, 180)])) == [],
           "球判据反证：180 灰不达标（判据用 min(R,G,B)>190）")
        # 中圈标记 13×5 不得当球
        ok(UA.soccer2_ball_blobs(canvas("mark.png", [(60, 100, 13, 5, 245)])) == [],
           "球判据反证：中圈标记 13×5 扁条不得当球")
        # OAM 球 tile 判据已降级为"仅存在性"，不许再冒充球坐标
        ok(UA.SOCCER2_BALL_TILES <= UA.SOCCER2_BALL_TILES_EXTENDED, "tile 集包含关系仍成立（扩展集只作诊断）")


def test_calibrate_gates():
    """标定闸门（11-15 实测立规）：草坪整屏差异不能当要素签名，阈值不能算成永不满足。"""
    import tempfile
    from pathlib import Path
    from PIL import Image
    from . import universal_authoring as UA

    W = H = 64
    BOX = [(x, y) for y in range(10, 30) for x in range(10, 30)]
    cluster = [(x, y, 200, 20, 200) for x, y in BOX]

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        def blob(name, count):
            """在 20×20 外框内铺 count 个同色像素；region 恒为 [6:33,6:33]=729px。"""
            im = Image.new("RGB", (W, H), (0, 0, 0))
            for x, y in BOX[:count]:
                im.putpixel((x, y), (200, 20, 200))
            im.save(td / name)
            return td / name

        # A. 真局部签名：正例 400/729=0.549、反例 0 => 接受且阈值夹在中间
        cal = UA._calib_cluster(cluster, W, H, blob("a_pos.png", 400), blob("a_neg.png", 0))
        ok(cal is not None, "标定：局部色块正例 vs 空反例 => 接受")
        ok(abs(cal["pos_fraction"] - 0.549) < 0.005, "标定：正例占比按 729px 区域实测 = 0.549")
        ok(cal["neg_fraction"] < cal["min_fraction"] <= cal["pos_fraction"] * 0.9,
           "标定：min_fraction 夹在反例之上、正例 0.9 之下（正过反拒有余量）")
        ok(cal["min_fraction"] <= 0.95, "标定：min_fraction 不越界 1（曾算出 1.334 的永不满足判据）")
        rx0, ry0, rx1, ry1 = cal["region"]
        ok((rx1 - rx0) * (ry1 - ry0) <= UA.CALIB_MAX_REGION_AREA,
           "标定：region 面积受限于局部，不吞整屏")

        # B. 余量闸门：47 vs 16 像素（0.064 vs 0.022）阈值区间本来是分得开的
        #    （lo=0.051 < 0.9*pos=0.058），只差在正负例余量不足 0.05 => 必须拒
        ok(UA._calib_cluster(cluster, W, H, blob("b_pos.png", 47), blob("b_neg.png", 16)) is None,
           "标定：正负例余量 < 0.05 => 拒（草坪级噪声不算要素签名）")

        # C. 可分性闸门：400 vs 340（余量 0.083 够）但 neg*2.2 顶穿 pos*0.9，无阈值可分 => 拒
        ok(UA._calib_cluster(cluster, W, H, blob("c_pos.png", 400), blob("c_neg.png", 340)) is None,
           "标定：不存在能分开正负例的阈值 => 拒，不写回不可用判据")

        # D. 整屏背景滚动：所有像素都"变了"但全是背景色 => 整帧标定必须失败
        pos_dir, neg_dir = td / "pos", td / "neg"
        pos_dir.mkdir(); neg_dir.mkdir()
        for i in range(4):
            Image.new("RGB", (W, H), (93, 229, 48)).save(pos_dir / f"f{i:03d}.png")
            Image.new("RGB", (W, H), (60, 180, 30)).save(neg_dir / f"f{i:03d}.png")
        try:
            UA.calibrate_element_detector(pos_dir, neg_dir)
            raise AssertionError("标定：整屏背景差异被当成了要素签名（闸门失效）")
        except RuntimeError as e:
            ok("没有可分离的局部视觉签名" in str(e),
               "标定：镜头滚动造成的整屏背景差异 => RuntimeError，不静默出参")

        # E. 正反例一模一样（宏没生效）=> 同样必须失败
        for i in range(4):
            Image.new("RGB", (W, H), (93, 229, 48)).save(neg_dir / f"f{i:03d}.png")
        try:
            UA.calibrate_element_detector(pos_dir, neg_dir)
            raise AssertionError("标定：正反例完全相同却出了参数（宏失效未被抓）")
        except RuntimeError as e:
            ok("没有可分离的局部视觉签名" in str(e),
               "标定：正反例逐帧相同（触发宏未生效）=> RuntimeError")

        # F. 稀薄签名+稠密结（11-20 thunder_beam 案）：整簇外框占比≈0.047 过不了
        #    余量闸门，但结处 8×8 子窗 0.56 => 子窗搜索必须救回，闸门常数不动。
        #    结只在帧 0-2 出现、帧 3 消失：真特效会出现/消失，静态签名过不了
        #    CALIB_FLICKER_MIN（11-24 新闸门，见 H）。
        thin_pos, thin_neg = td / "thin_pos", td / "thin_neg"
        thin_pos.mkdir(); thin_neg.mkdir()
        arms = [(16 + t, 16 + t) for t in range(0, 25, 3)] + \
               [(40 - t, 16 + t) for t in range(0, 25, 3)]
        knot = [(x, y) for y in range(28, 34) for x in range(28, 34)]
        for i in range(4):
            im = Image.new("RGB", (W, H), (0, 0, 0))
            for x, y in arms + (knot if i < 3 else []):
                im.putpixel((x, y), (200, 20, 200))
            im.save(thin_pos / f"f{i:03d}.png")
            Image.new("RGB", (W, H), (0, 0, 0)).save(thin_neg / f"f{i:03d}.png")
        cal = UA.calibrate_element_detector(thin_pos, thin_neg)
        ok(cal is not None and cal["margin"] >= UA.CALIB_MIN_MARGIN,
           "标定：稀薄臂+稠密结 => 子窗搜索救回且余量过闸")
        rx0, ry0, rx1, ry1 = cal["region"]
        ok((rx1 - rx0) * (ry1 - ry0) <= UA.CALIB_MAX_REGION_AREA,
           "标定：子窗 region 仍受局部面积上限")
        # G. 恒量反证：只有稀薄臂没有结 => 仍须 RuntimeError（子窗不是放宽闸门）
        for i in range(4):
            im = Image.new("RGB", (W, H), (0, 0, 0))
            for x, y in arms:
                im.putpixel((x, y), (200, 20, 200))
            im.save(thin_pos / f"f{i:03d}.png")
        try:
            UA.calibrate_element_detector(thin_pos, thin_neg)
            raise AssertionError("标定：无稠密结的稀薄签名被子窗放宽通过了")
        except RuntimeError as e:
            ok("没有可分离的局部视觉签名" in str(e),
               "标定：只有稀薄臂（无结）=> 仍 RuntimeError，子窗不放宽闸门")

        # H. 静态地物假签名（11-24 fire_storm 蓝瓦片案）：正例全程恒定的背景
        #    瓦片在负臂被物体遮挡 => 余量/阈值都分得开，但正例无出现/消失
        #    => CALIB_FLICKER_MIN 闸门必须拒，不写假签名进包
        st_pos, st_neg = td / "st_pos", td / "st_neg"
        st_pos.mkdir(); st_neg.mkdir()
        for i in range(6):
            Image.new("RGB", (W, H), (0, 0, 0)).save(st_neg / f"f{i:03d}.png")
            im = Image.new("RGB", (W, H), (0, 0, 0))
            for x, y in BOX:
                im.putpixel((x, y), (100, 176, 254))
            im.save(st_pos / f"f{i:03d}.png")
        try:
            UA.calibrate_element_detector(st_pos, st_neg)
            raise AssertionError("标定：正例全程恒定的静态瓦片签名通过了（静态地物闸门失效）")
        except RuntimeError as e:
            ok("静态地物" in str(e),
               "标定：正例全程恒定的背景瓦片（负臂被遮挡才显区分）=> RuntimeError 静态地物闸门")


def test_base_state_provenance():
    """base_state 出处闸门：丢进状态资产仓却没登记的存档，plan 必须拦（11-15 顶包 base 案）。

    现场：手工把 scratch 的 live.state 复制成 状态资产/live_possess.state 指进知识包，
    台账无记录、球权闸门没跑，实测量出 1P 载入即 dist=103px（根本没球）⇒ 六个要素白采。
    闸门只管网内的文件，仓外历史包（验证目录/scratch）不受影响。
    """
    import copy
    import json
    import tempfile
    from pathlib import Path
    from . import showcase as SC
    from . import state_registry as SR

    doc = {
        "kind": "statejump_showcase", "game_id": "synthetic", "platform": "NES",
        "rom": "game.nes", "bizhawk": "bh", "base_state": "base.state",
        "rom_sha1": hashlib.sha1(b"NES synthetic").hexdigest(),
        "fps": 60, "template": "none",
        "catalog": {"status": "complete", "expected_total": 1, "sources": ["synthetic"]},
        "elements": [{
            "element_id": "e1", "label": "E1", "kind": "weapon",
            "trigger": {"macro": "B,,", "extra": 2, "patches": []},
            "detection": {"frame": 1, "success_checks": [{
                "check_id": "bright", "plugin_id": "frame_luma_range",
                "params": {"min": 200, "max": 255}, "required": True}]},
            "negative_control": {"macro": None}
        }]
    }

    def asset_blockers(reasons):
        return [r for r in reasons if "台账" in r or "档位" in r]

    real_root = SR.ASSET_ROOT
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        SR.ASSET_ROOT = td / "assets"
        try:
            (td / "game.nes").write_bytes(b"NES synthetic")
            (td / "bh").mkdir()
            (td / "bh" / "EmuHawk.exe").write_bytes(b"MZ")

            # 1) 仓内裸文件：没有 package.json 记录 => 拦
            rogue_dir = SR.ASSET_ROOT / "dropin"
            rogue_dir.mkdir(parents=True)
            rogue = rogue_dir / "live.state"
            rogue.write_bytes(b"STATE rogue")
            d1 = copy.deepcopy(doc)
            d1["base_state"] = str(rogue)
            p1 = td / "p1.showcase.json"
            p1.write_text(json.dumps(d1), encoding="utf-8")
            r1 = SC.plan(str(p1))
            ok(len(asset_blockers([b["reason"] for b in r1["blockers"]])) == 1,
               "base 出处闸门：状态资产仓内未登记的存档 => plan 拦下")
            ok(r1["status"] == "blocked", "base 出处闸门：未登记 base 时整包 blocked，不进采集")

            # 2) 正式登记且达 state_verified => 放行
            src = td / "raw.state"
            src.write_bytes(b"STATE registered")
            prof = {"profile_id": "syn_prof", "rom_sha1": "DEADBEEF",
                    "core": "NesHawk", "emulator": "BizHawk-2.8"}
            SR.create("syn_game", prof, revision="r1", note="selftest")
            SR.add_state("syn_game", "syn_prof", "r1", "base", src, kind="scene")
            SR.set_status("syn_game", "syn_prof", "r1", "state_verified")
            pkg = SR.load("syn_game", "syn_prof", "r1")
            ok_path = SR.package_dir("syn_game", "syn_prof", "r1") / pkg["states"]["base"]["path"]
            d2 = copy.deepcopy(doc)
            d2["base_state"] = str(ok_path)
            p2 = td / "p2.showcase.json"
            p2.write_text(json.dumps(d2), encoding="utf-8")
            r2 = SC.plan(str(p2))
            ok(not asset_blockers([b["reason"] for b in r2["blockers"]]),
               "base 出处闸门：登记过且 state_verified 的存档 => 放行")

            # 3) 登记了但还停在 candidate：不能当已验证用
            SR.set_status("syn_game", "syn_prof", "r1", "candidate")
            r3 = SC.plan(str(p2))
            ok(len(asset_blockers([b["reason"] for b in r3["blockers"]])) == 1,
               "base 出处闸门：candidate 档位的资产被拒（未达可消费档位）")

            # 4) 反证：仓外路径不归本闸门管（历史包不被误杀）
            outside = td / "old.state"
            outside.write_bytes(b"STATE outside")
            d4 = copy.deepcopy(doc)
            d4["base_state"] = str(outside)
            p4 = td / "p4.showcase.json"
            p4.write_text(json.dumps(d4), encoding="utf-8")
            r4 = SC.plan(str(p4))
            ok(not asset_blockers([b["reason"] for b in r4["blockers"]]),
               "base 出处闸门：仓外 base_state 不受管（反证格，防误杀历史包）")

            # 5) run 也必须吃同一个闸门（不能只拦 plan）
            called = {}
            real_run_stage = SC._asset_state_blockers

            def spy(pairs):
                called["pairs"] = list(pairs)
                return real_run_stage(pairs)
            SC._asset_state_blockers = spy
            try:
                SC.plan(str(p1))
            finally:
                SC._asset_state_blockers = real_run_stage
            ok(any("base_state" in lbl for lbl, _ in called.get("pairs", [])),
               "base 出处闸门：plan 确实把 base_state 送进出处核对（不是死代码）")
        finally:
            SR.ASSET_ROOT = real_root


def test_rom_index_cache():
    """index_roms 缓存：同输入同结果；ROM 内容一改，索引必须跟着变（否则缓存就是假命中）。"""
    import hashlib
    from . import registry as R

    with tempfile.TemporaryDirectory() as td:
        lib = Path(td) / "lib"
        (lib / "roms_verify" / "NES").mkdir(parents=True)
        rom = lib / "roms_verify" / "NES" / "a.nes"
        rom.write_bytes(b"ROMVERSION1")
        sha1 = hashlib.sha1(b"ROMVERSION1").hexdigest().upper()

        idx1 = R.index_roms(lib)
        ok(sha1 in idx1, "registry：index_roms 命中本地 ROM")
        idx2 = R.index_roms(lib)
        ok(idx2 == idx1, "registry：index_roms 二次调用结果一致（走缓存不漂移）")

        # 恒量反证：同一路径换内容 ⇒ 旧 sha1 必须消失、新 sha1 必须出现
        rom.write_bytes(b"ROMVERSION2")
        sha2 = hashlib.sha1(b"ROMVERSION2").hexdigest().upper()
        idx3 = R.index_roms(lib)
        ok(sha2 in idx3 and sha1 not in idx3,
           "registry：ROM 内容改了索引跟着改（缓存按 mtime/大小失效）")

        import zipfile
        from .ledger import fingerprint
        from .schema import sha256_resource, sha1_resource
        archive = Path(td) / "packed.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("nested/game.sfc", b"PACKED-ROM")
        resource = str(archive) + "!nested/game.sfc"
        expected = hashlib.sha256(b"PACKED-ROM").hexdigest()
        ok(sha256_resource(resource) == expected,
           "资源指纹：zip!条目按条目字节计算 SHA-256")
        ok(sha1_resource(resource) == hashlib.sha1(b"PACKED-ROM").hexdigest(),
           "资源指纹：zip!条目按条目字节计算 SHA-1")
        ok(fingerprint([resource], {"kind": "rom"}),
           "资源指纹：ledger fingerprint 支持 zip!条目")


def test_bizhawk_slot_inputs():
    """回放平台槽位/核心名的唯一权威，以及 FC 封面分支的平台判定。

    起因（11-22 实测）：record full --pub 7406 的 CLI 吃函数默认值 system="NES"，
    一本 SNES 出版物走了 FC 封面分支，音频那格还按「NES 发行版」出证。
    """
    import zipfile
    from pathlib import Path
    import tempfile
    from . import registry as R
    from . import record as REC
    from .schema import SchemaError

    # 别名表：同一平台的各种写法收敛到同一个槽位
    for plat, want in (("NES", "NES"), ("fc", "NES"), ("Famicom", "NES"),
                       ("SNES", "SNES"), ("SFC", "SNES"), ("Super Nintendo", "SNES")):
        got = R.bizhawk_replay_inputs({"platform_code": plat, "core": "C"})
        ok(got["system"] == want, f"槽位：{plat} -> {want}（实测 {got['system']}）")

    # 恒量反证：未知平台不许悄悄兜底成 NES（兜底 = 用错核心跑片还说绿灯）
    for plat in ("GENESIS", "GBA", "", None):
        raises(lambda p=plat: R.bizhawk_replay_inputs({"platform_code": p, "core": "C"}),
               f"槽位：未知平台 {plat!r} 直接拒绝，不兜底 NES")
    try:
        R.bizhawk_replay_inputs({"platform_code": "3DO", "core": "C"})
        why = ""
    except SchemaError as e:
        why = str(e)
    ok("NES" in why and "3DO" in why,
       "槽位：拒绝理由点名「是谁」和「已知槽位」，不是空喊失败")

    # 核心名同样不许猜：台账没写、Header 也没写 => 拒
    raises(lambda: R.bizhawk_replay_inputs({"platform_code": "NES"}),
           "槽位：Core 两处都查不到时拒绝，不默认 NesHawk")

    with tempfile.TemporaryDirectory() as td:
        # 台账没给 platform 时读电影自己的 Header（bk2 是 zip，Header.txt 空格分隔）
        bk2 = Path(td) / "m.bk2"
        with zipfile.ZipFile(bk2, "w") as z:
            z.writestr("Header.txt", "Platform SNES\nCore BSNESv115+\n")
            z.writestr("Input Log.txt", "|\n|\n")
        got = R.bizhawk_replay_inputs({}, movie=str(bk2))
        ok(got["system"] == "SNES" and got["core"] == "BSNESv115+",
           "槽位：platform_code 缺失时退回 bk2 Header 自述（Platform/Core 都读出来）")
        ok(got["platform_source"] == "bk2_header",
           "槽位：产物写明平台名是从哪来的（Header 兜底不能伪装成台账声明）")
        ok(R.bizhawk_replay_inputs({"platform_code": "NES", "core": "NesHawk"},
                                   movie=str(bk2))["platform_source"] == "platform_code",
           "槽位：台账优先，Header 只在台账缺位时才说话（恒量反证：同文件两种口径不许翻）")

    # 启动前的槽位/电影一致性闸门：错槽位不再烧 60 秒才变成 stalled_killed
    with tempfile.TemporaryDirectory() as td2:
        def _mk(name, platform, nested=False):
            fp = Path(td2) / name
            if nested:
                inner = Path(td2) / (name + ".inner.bk2")
                with zipfile.ZipFile(inner, "w") as z:
                    z.writestr("Header.txt", f"Platform {platform}\nCore NesHawk\n")
                    z.writestr("Input Log.txt", "|\n|\n")
                with zipfile.ZipFile(fp, "w") as z:
                    z.write(inner, "x.bk2")
            else:
                with zipfile.ZipFile(fp, "w") as z:
                    z.writestr("Header.txt", f"Platform {platform}\nCore NesHawk\n")
                    z.writestr("Input Log.txt", "|\n|\n")
            return str(fp)

        snes_mov = _mk("snes.bk2", "SNES")
        nes_mov = _mk("nes.bk2", "NES")
        why = REC.slot_conflict(snes_mov, "NES")
        ok(bool(why) and "SNES" in why and "NES" in why,
           "槽位闸门：SNES 电影 + NES 槽位 => 拦下，理由点名两边是谁")
        ok(REC.slot_conflict(snes_mov, "SNES") is None,
           "槽位闸门：同一本电影配对了槽位不许亮（恒量反证：只有 system 变）")
        ok(REC.slot_conflict(nes_mov, "FC") is None,
           "槽位闸门：FC/NES 别名归一后不许误报（恒量反证：同 Platform 的写法差）")
        ok(REC.slot_conflict(snes_mov, None) is None and REC.slot_conflict(snes_mov, "") is None,
           "槽位闸门：槽位本身不认识时不拦（该由 bizhawk_replay_inputs 拒，不重复判）")
        ok(REC.slot_conflict(str(Path(td2) / "not_a_zip.bk2"), "NES") is None,
           "槽位闸门：文件读不到 Header 就不拦，不臆测非 BizHawk 容器")
        nohdr = Path(td2) / "nohdr.bk2"
        with zipfile.ZipFile(nohdr, "w") as z:
            z.writestr("Input Log.txt", "|\n|\n")
        ok(REC.slot_conflict(str(nohdr), "NES") is None,
           "槽位闸门：zip 里没 Header.txt 时返回 None（缺声明 ≠ 声明不符）")
        ok(bool(REC.slot_conflict(_mk("nest.bk2", "SNES", nested=True), "NES")),
           "槽位闸门：外层 zip 包内层 bk2 也要能读出 Platform（转换件就是这形状）")

        # 同一条闸门要接进每一种生产形态，只在回放侧拦等于没拦
        from .statejump import StateSession
        raises(lambda: StateSession(str(Path(td2) / "rom.sfc"), str(td2),
                                    core="BSNESv115+", system="NES", movie=snes_mov),
               "槽位闸门：StateSession 构造时就拒，不等 EmuHawk 起来跑到 0 帧")
        s_ok = StateSession(str(Path(td2) / "rom.sfc"), str(td2),
                            core="BSNESv115+", system="SNES", movie=snes_mov)
        ok(s_ok.system == "SNES",
           "槽位闸门：配对槽位的状态会话照常构造（恒量反证：只有 system 变）")

    # FC 封面分支的判定收成一个纯函数（这条线此前按默认 NES 走）
    for bezel, system, want in (("auto", "NES", True), ("auto", "FC", True),
                                ("auto", "SNES", False), ("auto", None, False),
                                ("on", "SNES", True), ("off", "NES", False),
                                ("off", "SNES", False)):
        ok(REC.fc_cover_branch(bezel, system) is want,
           f"边框分支：bezel={bezel} system={system} -> {want}")
    ok(REC.fc_cover_branch("auto", "SNES") is False
       and REC.fc_cover_branch("on", "SNES") is True,
       "边框分支反证：SNES 只在显式 --border on 时才进 FC 缓存这条路")

    # 无头音频闸门的文案必须点名实测所属平台，不许把 NES 的结论说成全体
    nes = REC.headless_audio_gate("NES")
    snes = REC.headless_audio_gate("SNES")
    ok(nes.verdict is Verdict.INCONCLUSIVE and snes.verdict is Verdict.INCONCLUSIVE,
       "音频闸门：任何平台都不给 pass（无头 A/V dump 未接通）")
    ok("未单独实测" not in nes.reason and "未单独实测" in snes.reason,
       "音频闸门：文案区分「NES 已实测不可用」与「SNES 未单独实测」")

    # 一份别名表，不开第二个端口（auto 与 registry 必须同源）
    from . import auto as A
    ok(A._BIZHAWK_SYSTEM is R.BIZHAWK_SYSTEMS,
       "槽位：auto 用的就是 registry 那张表（同一个对象），不是抄第二份")


def test_emulator_slot_platform_pools():
    import tempfile
    from contextlib import contextmanager
    from . import parallel as P

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        source = root / "BizHawk"
        source.mkdir()
        (source / "EmuHawk.exe").write_bytes(b"MZ")
        configured = []
        orig_copy, orig_configure = P._copy_runtime, P._configure
        P._copy_runtime = lambda source, path: None
        P._configure = lambda source, path, program, **kwargs: configured.append(dict(program))
        try:
            slots = P.EmulatorSlots(workers=2, root=root / "slots")
            with slots.lease(source) as nes_a:
                pass
            with slots.lease(source) as nes_b:
                ok(nes_a.path == nes_b.path and nes_a.system == "NES"
                   and nes_a.core == "NesHawk",
                   "并行槽：同源同平台同核心复用同一槽（旧调用默认 NES/NesHawk）")
            with slots.lease(source, system="GBA", core="mGBA") as gba:
                ok(gba.system == "GBA" and gba.core == "mGBA"
                   and gba.path != nes_a.path,
                   "并行槽：GBA/mGBA 与 NES/NesHawk 物理隔离，不共用已配置副本")
            with slots.lease(source, system="GBA", core="OtherCore") as other:
                ok(other.path != gba.path,
                   "并行槽：同平台不同核心也分池（恒量反证：只换 core）")
            ok(len(slots._slots) == 6 and len(slots._pools) == 3,
               "并行槽：池身份=源安装+system+core，三组各两个槽")
            ok(configured == [{"system": "NES", "core": "NesHawk"},
                              {"system": "GBA", "core": "mGBA"},
                              {"system": "GBA", "core": "OtherCore"}],
               "并行槽：_configure 收到各池真实 system/core，不再写死 NES")
            report = slots.report()
            ok({(s["system"], s["core"]) for s in report["slots"]}
               == {("NES", "NesHawk"), ("GBA", "mGBA"), ("GBA", "OtherCore")},
               "并行槽：report 逐槽暴露平台/核心，便于反查实际配置")
        finally:
            P._copy_runtime, P._configure = orig_copy, orig_configure


def test_auto_slot_forwarding():
    import tempfile
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import patch
    from . import auto as A
    from . import showcase as SC

    class FakeSlots:
        def __init__(self):
            self.calls = []

        @contextmanager
        def lease(self, source, system=None, core=None):
            self.calls.append((str(source), system, core))

            @contextmanager
            def exclusive():
                yield

            yield SimpleNamespace(path=Path(source) / "clone", work=Path(source) / "work",
                                  exclusive=exclusive)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        slots = FakeSlots()
        spec = A.JobSpec("Aria", "moves", source="showcase", pack="aria.json",
                         template="none")
        pre = {"status": "ready", "resources": {"bizhawk": str(root / "bh")},
               "system": "GBA", "core": "mGBA", "mechanism": "load_savestate_and_patch",
               "patch_elements": ["wingcutter"], "required_rom_sha1": "A" * 40}
        with patch.object(A, "_state_capture_plan", return_value=pre), \
             patch.object(SC, "run", return_value={"status": "done", "verdict": "pass",
                                                   "passed": 1, "total": 1}), \
             patch.object(SC, "resource_files", return_value=[]):
            A.orchestrate(spec, out_dir=str(root / "showcase"), emulator_slots=slots)
        ok(slots.calls[-1] == (str(root / "bh"), "GBA", "mGBA"),
           "auto 接线：showcase 租槽收到知识包解析出的 GBA/mGBA")

        slots = FakeSlots()
        rom, movie = root / "game.gba", root / "movie.vbm"
        rom.write_bytes(b"ROM")
        movie.write_bytes(b"MOVIE")
        pub = {"id": "1"}
        assess = {"identity_status": "resolved", "profile": {"profile_id": "aria"}}
        acq = {"status": "ready", "rom": str(rom), "cheat": {"status": "not_found"}}
        inputs = {"movie": str(movie), "rom": str(rom), "bizhawk_dir": str(root / "bh"),
                  "profile_id": "aria", "core": "mGBA", "system": "GBA"}
        with patch.object(A, "resolve_job", return_value=(pub, assess)), \
             patch.object(A, "_selection_gate", return_value=(None, [])), \
             patch.object(A.AQ, "acquire", return_value=acq), \
             patch.object(A, "_backend_caps", return_value=({}, "aria")), \
             patch.object(A.SB, "build_state", return_value={"status": "ready"}), \
             patch.object(A, "_nes_inputs", return_value=inputs), \
             patch.object(A, "fingerprint", return_value="FP"), \
             patch.object(A, "run_playthrough", return_value={"status": "done",
                                                               "verdict": "pass"}) as run:
            A.orchestrate(A.JobSpec("Aria", "playthrough", pub_id="1"),
                          out_dir=str(root / "movie"), emulator_slots=slots)
        ok(slots.calls[-1] == (str(root / "bh"), "GBA", "mGBA"),
           "auto 接线：普通电影任务也把 _nes_inputs 的 system/core 传入租槽")
        ok(run.call_args.kwargs["bizhawk_dir"] == Path(root / "bh") / "clone",
           "auto 接线：租到的隔离副本确实传给生产运行函数")


def test_calibrate_showcase_pack_gba():
    import json
    import tempfile
    from contextlib import contextmanager
    from unittest.mock import patch
    from . import universal_authoring as UA
    from . import retro_platforms as RP

    doc = {"platform": "GBA", "core": "mGBA", "system": "GBA",
           "elements": [{"element_id": "guardian",
                         "trigger": {"macro": "R", "extra": 2, "patches": []},
                         "negative_control": {"macro": None, "patches": []}}]}
    paths = {"rom": "game.gba", "bizhawk": "bh", "base_state": "base.state",
             "element_base_states": {}}
    sessions, dumps, macro_platforms = [], [], []

    class FakeSession:
        def __init__(self, *args, **kwargs):
            sessions.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def use_state(self, path, name=None):
            return path

        def dump(self, frames_dir, **kwargs):
            dumps.append(kwargs)
            return 3

    def frame_count(macro, platform="NES"):
        macro_platforms.append(platform)
        return 0 if not macro or macro == "-" else len(macro.split(","))

    cal = {"frame": 1, "region": [0.1, 0.1, 0.2, 0.2], "rgb": [1, 2, 3],
           "tol": 4, "min_fraction": 0.01, "pos_fraction": 0.2, "neg_fraction": 0.0}
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pack = root / "aria.showcase.json"
        pack.write_text(json.dumps(doc), encoding="utf-8")
        with patch.object(UA.showcase, "load_spec", return_value=doc), \
             patch.object(UA.showcase, "resource_paths", return_value=paths), \
             patch.object(UA.showcase, "_macro_frames", side_effect=frame_count), \
             patch.object(RP, "MultiPlatformStateSession", FakeSession), \
             patch.object(UA, "calibrate_element_detector", return_value=cal):
            UA.calibrate_showcase_pack(pack, root / "work")
        ok(sessions == [{"platform": "GBA", "core": "mGBA", "system": "GBA",
                         "work": str(root / "work" / "calib_sess")}],
           "自动标定：GBA 包用 MultiPlatformStateSession+mGBA/GBA，不再起 NES 会话")
        ok(macro_platforms == ["GBA", "GBA"],
           "自动标定：正反例帧数都按包平台解析宏（R 不会被 NES 口径解释）")
        ok(dumps[0]["extra"] == 2 and dumps[1]["extra"] == 3,
           "自动标定：负例补齐到与正例相同帧数，平台参数不改变对齐结果")


def test_smv_converter_contract():
    import gzip
    import io
    import json
    import struct
    import zipfile
    from . import movie_converters as MC
    from . import registry as R

    def make_smv(path, samples, declared=2, movie_opts=1, sync_opts=0):
        state = gzip.compress(b"\x60" * (128 * 1024), mtime=0) if movie_opts & 1 else b""
        hdr = bytearray(32)
        hdr[:4] = b"SMV\x1a"
        struct.pack_into("<IIII", hdr, 4, 1, 7, 9, declared)
        struct.pack_into("<BBBB", hdr, 20, 0x03, movie_opts, sync_opts, 0)
        struct.pack_into("<II", hdr, 24, 32, 32 + len(state))
        path.write_bytes(bytes(hdr) + state + b"".join(struct.pack("<HH", *row) for row in samples))

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        smv = root / "anchored.smv"
        make_smv(smv, [(0, 0), (0x4008, 0x8001), (0xFFFF, 0xFFFF), (0, 0)])
        parsed = MC.parse_smv(smv)
        ok(parsed["n_frames"] == 2 and parsed["frames"][0]["p1"] == {"Up", "Y"}
           and parsed["frames"][0]["p2"] == {"Right", "B"},
           "SMV 新契约：跳过基线样本，P1/P2 按钮逐位等价")
        ok(parsed["frames"][1]["cmd"] == "reset"
           and parsed["frames"][1]["p1"] == set() and parsed["frames"][1]["p2"] == set(),
           "SMV 新契约：双手柄全 FF 样本转成 reset，不把 FF 当全键按下")
        ok(parsed["from_reset"] and "from_savestate" not in parsed and parsed["extra_samples"] == 1
           and len(parsed["warnings"]) == 1 and len(parsed["savestate_data"]) == 128 * 1024,
           "SMV 新契约：movie_opts=1 表示 FROM_RESET，声明区间外样本只告警不混入正式帧")

        cold = root / "cold.smv"
        make_smv(cold, [(0, 0), (0x0040, 0)], declared=1, movie_opts=0)
        ok(not MC.parse_smv(cold)["from_reset"],
           "SMV 新契约反证：movie_opts=0 不再被误判成 FROM_RESET 启动")

        state_bytes = io.BytesIO()
        waterbox_core = b"ActivatedWaterboxHost_v1" + b"fixture-core"
        sync = {"o": {"$type": "BizHawk.Emulation.Cores.Nintendo.SNES9X.Snes9x+SyncSettings, BizHawk.Emulation.Cores",
                      "LeftPort": 1, "RightPort": 1}}
        with zipfile.ZipFile(state_bytes, "w") as z:
            z.writestr("Core.bin", waterbox_core)
            z.writestr("BizVersion.txt", "Version 2.9.1")
            z.writestr("SyncSettings.json", json.dumps(sync))
        state_blob = state_bytes.getvalue()
        state_file = root / "verified_anchor.state"
        state_file.write_bytes(state_blob)
        reused = MC.convert_movie_file(smv, root / "reused.bk2", core_state_path=state_file)
        with zipfile.ZipFile(root / "reused.bk2") as reused_zip:
            ok(reused["status"] == "converted" and reused_zip.read("Core.bin") == waterbox_core
               and reused["core_state"]["reused_core_state"] == str(state_file.resolve()),
               "SMV 复用入口：已校验 State 跳过烘焙仍走生产 writer，并登记来源")
        try:
            MC.convert_movie_file(cold, root / "cold_reused.bk2", core_state_path=state_file)
        except MC.MovieConvertError:
            ok(True, "SMV 复用入口反证：开机电影不得夹带 CoreState")
        else:
            ok(False, "SMV 复用入口反证：开机电影不得夹带 CoreState")
        state_211_bytes = io.BytesIO()
        with zipfile.ZipFile(state_211_bytes, "w") as z:
            z.writestr("Core.bin", waterbox_core)
            z.writestr("BizVersion.txt", "Version 2.11.1")
            z.writestr("SyncSettings.json", json.dumps(sync))
        state_211 = root / "verified_anchor_211.state"
        state_211.write_bytes(state_211_bytes.getvalue())
        converted_211 = MC.convert_movie_file(smv, root / "reused_211.bk2", core_state_path=state_211)
        with zipfile.ZipFile(root / "reused_211.bk2") as reused_211_zip:
            ok("emuVersion Version 2.11.1" in reused_211_zip.read("Header.txt").decode()
               and converted_211["core_state"]["reused_core_state"] == str(state_211.resolve()),
               "SMV 复用入口：emuVersion 跟随真实 CoreState 的 BizVersion，不把 2.11.1 冒充 2.9.1")
        out = root / "anchored.bk2"
        MC.write_multiplatform_bk2(parsed, out, rom_sha1="a" * 40,
                                   emu_version="Version 2.9.1", core_state=state_blob)
        with zipfile.ZipFile(out) as z:
            header = z.read("Header.txt").decode()
            log = z.read("Input Log.txt").decode()
            ok("StartsFromSavestate true" in header and "emuVersion Version 2.9.1" in header,
               "BK2 writer：锚点电影写 StartsFromSavestate 与 2.9.1 身份")
            ok("|P2 Up|" in log and sum(line.startswith("|") for line in log.splitlines()) == 2,
               "BK2 writer：P1/P2 各十二列，正式输入行数等于声明帧数")
            ok(z.read("Core.bin") == waterbox_core and "Snes9x+SyncSettings" in z.read("SyncSettings.json").decode(),
               "BK2 writer：只把 State 里的原始 Core.bin 写进外层 Core.bin，并保留 Snes9x 端口设置")
            ok("CoreState" not in z.namelist(),
               "BK2 writer 反证：不得使用 BizHawk 2.9.1 不读取的 CoreState 成员名")

        no_sync_bytes = io.BytesIO()
        with zipfile.ZipFile(no_sync_bytes, "w") as z:
            z.writestr("Core.bin", waterbox_core)
            z.writestr("BizVersion.txt", "Version 2.9.1")
        no_sync_blob = no_sync_bytes.getvalue()
        ok(MC._read_core_state(no_sync_blob)[2] is None,
           "BK2 writer：Snes9x 真实 State 可不含 SyncSettings，不能把缺成员误判成坏档")
        no_sync_out = root / "no_sync.bk2"
        MC.write_multiplatform_bk2(parsed, no_sync_out, rom_sha1="a" * 40,
                                   emu_version="Version 2.9.1", core_state=no_sync_blob)
        with zipfile.ZipFile(no_sync_out) as z:
            ok(z.read("Core.bin") == waterbox_core
               and "Snes9x+SyncSettings" in z.read("SyncSettings.json").decode(),
               "BK2 writer：无 SyncSettings 的 State 也只写原始 Core.bin，外层补齐 Snes9x 端口配置")
            ok(z.read("Core.bin") != no_sync_blob,
               "BK2 writer 反证：外层 Core.bin 恒不能是 BizHawk State ZIP")

        raw_state_bytes = io.BytesIO()
        with zipfile.ZipFile(raw_state_bytes, "w") as z:
            z.writestr("Core.bin", b"raw-snes9x-core")
            z.writestr("BizVersion.txt", "Version 2.9.1")
        try:
            MC.write_multiplatform_bk2(parsed, root / "raw_core.bk2", emu_version="Version 2.9.1",
                                       core_state=raw_state_bytes.getvalue())
            raise AssertionError("裸 Snes9x Core.bin 被写入电影")
        except MC.MovieConvertError as exc:
            ok("ActivatedWaterboxHost_v1" in str(exc),
               "BK2 writer 反证：裸 Snes9x 核心状态不是 Waterbox 电影宿主状态，必须拒绝")

        from unittest.mock import patch
        compressed_core_bytes = io.BytesIO()
        with zipfile.ZipFile(compressed_core_bytes, "w") as z:
            z.writestr("Core.bin", MC.ZSTD_FRAME_MAGIC + b"fixture-zstd")
            z.writestr("BizVersion.txt", "Version 2.9.1")
        with patch.object(MC, "_zstd_decompress", return_value=waterbox_core) as decompress:
            compressed_out = root / "decompressed.bk2"
            MC.write_multiplatform_bk2(parsed, compressed_out, emu_version="Version 2.9.1",
                                       core_state=compressed_core_bytes.getvalue(), zstd_dll="fixture-libzstd.dll")
            decompress.assert_called_once_with(MC.ZSTD_FRAME_MAGIC + b"fixture-zstd", "fixture-libzstd.dll")
        with zipfile.ZipFile(compressed_out) as z:
            ok(z.read("Core.bin") == waterbox_core,
               "BK2 writer：.state 的 Zstandard Core.bin 先解成 Waterbox 宿主状态再写入电影")

        bsnes_out = root / "bsnes_sram.bk2"
        bsnes_report = MC.convert_movie_file(smv, bsnes_out, core="BSNES")
        with zipfile.ZipFile(bsnes_out) as z:
            header = z.read("Header.txt").decode()
            ok(bsnes_report["core"] == "BSNES" and "Core BSNES" in header
               and "emuVersion Version 2.11.1" in header
               and "StartsFromSavestate false" in header and "StartsFromSaveRam" not in header,
               "BSNES writer：SRAM 锚点电影显式声明 BSNES 2.11.1 冷启动，不冒充 Snes9x 状态")
            ok("Core.bin" not in z.namelist() and "MovieSaveRam.bin" not in z.namelist(),
               "BSNES writer：初始 SRAM 留给生产控制层带哈希注入，不夹带核心状态或无效 SaveRAM 文件")
            ok("LibsnesCore+SnesSyncSettings" in z.read("SyncSettings.json").decode(),
               "BSNES writer：SyncSettings 身份与 BSNES/Libsnes 核心一致")
        try:
            MC.convert_movie_file(smv, root / "bsnes_with_state.bk2", core="BSNES", core_state_path=state_file)
        except MC.MovieConvertError:
            ok(True, "BSNES writer 反证：拒绝把 Snes9x CoreState 混入 BSNES SRAM 电影")
        else:
            ok(False, "BSNES writer 反证：拒绝把 Snes9x CoreState 混入 BSNES SRAM 电影")

        bsnes115_out = root / "bsnes115_sram.bk2"
        bsnes115_report = MC.convert_movie_file(smv, bsnes115_out, core="BSNESv115+")
        with zipfile.ZipFile(bsnes115_out) as z:
            header = z.read("Header.txt").decode()
            ok(bsnes115_report["core"] == "BSNESv115+" and "Core BSNESv115+" in header
               and "emuVersion Version 2.11.1" in header and "StartsFromSavestate false" in header,
               "BSNESv115+ writer：独立核心身份与 BSNES 2.11.1 冷启动头部一致")
            ok("BsnesCore+SnesSyncSettings" in z.read("SyncSettings.json").decode()
               and "Core.bin" not in z.namelist() and "MovieSaveRam.bin" not in z.namelist(),
               "BSNESv115+ writer：同步类型归属于 BsnesCore，不混入 Libsnes 状态或 SRAM 文件")

        compressed_member = io.BytesIO()
        with zipfile.ZipFile(compressed_member, "w") as z:
            z.writestr("Core.bin.zst", MC.ZSTD_FRAME_MAGIC + b"fixture-zstd")
            z.writestr("BizVersion.txt", "Version 2.11.1")
        with patch.object(MC, "_zstd_decompress", return_value=waterbox_core) as decompress_member:
            member_core, member_version, _ = MC._read_core_state(
                compressed_member.getvalue(), waterbox=True, zstd_dll="fixture-libzstd.dll")
            decompress_member.assert_called_once_with(
                MC.ZSTD_FRAME_MAGIC + b"fixture-zstd", "fixture-libzstd.dll")
        ok(member_core == waterbox_core and member_version == "Version 2.11.1",
           "SMV reader：BizHawk 2.11 的 Core.bin.zst 成员先解压再校验 Waterbox 宿主状态")

        try:
            MC.write_multiplatform_bk2(parsed, root / "missing.bk2", emu_version="Version 2.9.1")
            raise AssertionError("缺 CoreState 的锚点电影被放行")
        except MC.MovieConvertError:
            ok(True, "BK2 writer 反证：缺 CoreState 必须拒绝，不能降级开机直放")

        truncated = root / "truncated.smv"
        make_smv(truncated, [(0, 0)], declared=2)
        try:
            MC.parse_smv(truncated)
            raise AssertionError("截断 SMV 被放行")
        except MC.MovieConvertError:
            ok(True, "SMV 反证：基线+声明帧不足时严格报错，不静默缩短电影")

        inspected = MC.inspect_movie(smv)
        ok("savestate_data" not in inspected and "frames" not in inspected,
           "SMV inspect 不把 128KB SRAM 或逐帧数据塞进 JSON")

        lib = root / "lib"
        source = lib / "movies" / "SNES" / "9.smv"
        source.parent.mkdir(parents=True)
        source.write_bytes(cold.read_bytes())
        conv = lib / "_converted" / "SNES" / "9.bk2"
        conv.parent.mkdir(parents=True)
        conv.write_bytes(b"fixture")
        movie, note = R.resolve_movie({"id": "9", "platform": "SNES", "local_movie": "movies/SNES/9.smv"}, lib)
        ok(movie == str(conv) and "CoreState" in note,
           "registry 接线：SMV 只认 _converted/<plat>/<id>.bk2 缓存")

    import tas_replay
    from . import statejump as SJ

    ok('op == "seed_ram"' in tas_replay.STATE_LUA_TMPL
       and "client.reboot_core()" in tas_replay.STATE_LUA_TMPL
       and 'io.open(p[3], "rb")' in tas_replay.STATE_LUA_TMPL,
       "CoreState 烘焙：文件式批量写 SRAM、重启到零帧、回读后保存均在生产 Lua 模板")
    ok('emu.getsystemid() == "SNES" and not listed["Save RAM"]' in tas_replay.STATE_LUA_TMPL
       and 'memory.getmemorydomainsize("Save RAM")' in tas_replay.STATE_LUA_TMPL,
       "CoreState 烘焙：Snes9x 隐藏但可直读的 Save RAM 必须补进生产域列表")
    from .statejump import format_command
    ok(format_command(7, "seed_ram", path="F:/seed.bin", domain="Save RAM", state="F:/anchor.state")
       == "7 seed_ram F:/seed.bin Save%20RAM F:/anchor.state",
       "CoreState 烘焙：seed_ram 必须登记进 Python 线协议，路径与域名按生产格式转义")
    ok(format_command(8, "seed_ram", path="F:/seed.bin", domain="System Bus", state="F:/anchor.state", addr=0x700000)
       == "8 seed_ram F:/seed.bin System%20Bus F:/anchor.state 7340032",
       "CoreState 烘焙：seed_ram 非零地址必须显式传给 Lua，默认零地址仍保持旧线格式")
    dummy = SJ.StateSession("F:/rom.sfc", "F:/BizHawk", core="Snes9x", system="SNES")
    dummy._domain_sizes = {"System Bus": 0x800000}
    dummy._check_domain_range(0x7e0000, 0x20000, "System Bus")
    try:
        dummy._check_domain_range(0x7e0000, 0x20001, "System Bus")
    except SJ.SchemaError:
        ok(True, "CoreState 烘焙：非零 seed_ram 越界必须拒绝，不能截断或写穿内存域")
    else:
        ok(False, "CoreState 烘焙：非零 seed_ram 越界必须拒绝，不能截断或写穿内存域")

    class BrokenSession:
        def __init__(self, rom, bizhawk, core, system, work):
            self.work = Path(work)

        def __enter__(self):
            self.work.mkdir(parents=True, exist_ok=True)
            (self.work / "session.log").write_text("fixture-failure", encoding="utf-8")
            raise RuntimeError("fixture-failure")

        def __exit__(self, exc_type, exc, tb):
            return False

    diag_root = root / "diag"
    with patch.object(SJ, "emuhawk_processes", return_value=[]), \
         patch.object(tas_replay, "materialize_rom", side_effect=lambda src, dst: Path(dst).write_bytes(b"rom")), \
         patch.object(SJ, "StateSession", BrokenSession):
        try:
            MC.bake_snes9x_core_state(parsed, root / "rom.sfc", root / "BizHawk-2.9.1", work=diag_root)
            raise AssertionError("烘焙失败被放行")
        except MC.MovieConvertError as exc:
            marker = "诊断已保留: "
            ok(marker in str(exc) and (Path(str(exc).split(marker, 1)[1]) / "session" / "session.log").read_text() == "fixture-failure",
               "CoreState 烘焙失败：会话日志复制到持久诊断目录后才清理临时件")


REQUIRED_DEPS = ("pyaudiowpatch",)


def missing_deps(deps=()):
    """当前解释器缺哪些生产依赖（纯函数，启动前的报错文案与自检格共用这一份）。"""
    import importlib.util
    return [m for m in deps if importlib.util.find_spec(m) is None]


def test_selftest_env_gate():
    """解释器选错时要点名「缺什么、该用谁」，不许留一坨 traceback 让人以为代码改坏了。

    11-22 深夜实测：用 Anaconda 的 python 跑 selftest，在 test_audio 的
    `import pyaudiowpatch` 处崩，rc=1、日志只剩 71 行，看起来像刚加的闸门炸了。
    """
    ok(missing_deps(("os",)) == [], "环境闸门：装得上的包不许误报缺失")
    ok(missing_deps(("taspipe_no_such_pkg_zzz",)) == ["taspipe_no_such_pkg_zzz"],
       "环境闸门：缺的包要点名是谁")
    ok(missing_deps(REQUIRED_DEPS) == [],
       f"环境闸门：本解释器已装齐生产依赖（实测解释器 {sys.executable}）")


def main():
    miss = missing_deps(REQUIRED_DEPS)
    if miss:
        print(f"SELFTEST 环境不合格：解释器 {sys.executable} 缺依赖 {miss}；"
              "taspipe 的生产口径是用 PATH 上的 python（3.13，这些包已装），"
              "不是 Anaconda 的 python。先换解释器再判代码。")
        return 1
    print("taspipe selftest (M0-M6 + audio + M8 ledger + M7 search + sync + warp + M10 probes + T1 unwrap/mux + T2 fceux + auto/acquire/state_registry/statebuild/statejump/showcase/matrix + exporter mask + bundle + calibrate gates + base provenance + cheat candidates + state profile gate + resource discovery)")
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
    test_replay_speed_tier()
    test_acquire()
    test_state_registry()
    test_statebuild()
    test_statejump()
    test_soccer2_oam()
    test_showcase()
    test_auto()
    test_state_capture_contract()
    test_capture_judge_separation()
    test_state_content_fingerprint_gate()
    test_state_profile_gate()
    test_cheat_candidates()
    test_resource_discovery()
    test_matrix()
    test_rom_index_cache()
    test_audio_blocker_not_degradable()
    test_exporter_mask()
    test_bundle()
    test_calibrate_gates()
    test_base_state_provenance()
    test_cross_platform_30()
    test_ram_calibration()
    test_scout_summary()
    test_detector_calibration()
    test_smv_converter_contract()
    test_sources_registry()
    test_kb_corpus()
    test_statejump_lua_contract()
    test_tail_stasis_gate()
    test_recorder_fidelity_ledger()
    test_predicate_platform_gate()
    test_timing_fields()
    test_runtime_dialog_diagnostics()
    test_dangling_call_gate()
    test_bizhawk_slot_inputs()
    test_emulator_slot_platform_pools()
    test_auto_slot_forwarding()
    test_calibrate_showcase_pack_gba()
    test_selftest_env_gate()
    print(f"SELFTEST OK {PASS}/{PASS}")
    return 0



def test_cross_platform_30():
    from .cross_platform_selftest_gates import run_cross_platform_gates
    run_cross_platform_gates(ok_fn=ok, raises_fn=raises)


def test_ram_calibration():
    from .ram_calibration_selftest import main as run_ram_calibration
    ok(run_ram_calibration() == 0, "RAM 校准配方、协议、缓存与归档自检通过")


def test_scout_summary():
    from .scout_summary_selftest import main as run_scout_summary
    ok(run_scout_summary() == 0, "scout 汇总区分全通过、部分视觉、相等基线失败与纯RAM")


def test_detector_calibration():
    from .detector_calibration_selftest import main as run_detector_calibration
    ok(run_detector_calibration() == 0, "对齐差分、闪白拒绝、颜色标定、样本分离与全时间轴审计自检通过")


def test_cheat_candidates():
    from .cheat_candidate_selftest import run_cheat_candidate_gates
    run_cheat_candidate_gates(ok_fn=ok, raises_fn=raises)


def test_resource_discovery():
    from .resource_discovery_selftest import run_resource_discovery_gates
    run_resource_discovery_gates(ok_fn=ok, raises_fn=raises)



def test_sources_registry():
    from .sources_selftest_gates import run_sources_gates
    run_sources_gates(ok_fn=ok, raises_fn=raises)



def test_kb_corpus():
    from .kb_selftest_gates import run_kb_gates
    run_kb_gates(ok_fn=ok, raises_fn=raises)


def test_statejump_lua_contract():
    # 2026-11-20 夜实测坑落闸门：KopiLua io.read("*l") 在 cmd 行 >1024B 时截断/死，
    # KopiLua io.read("*l") 在 cmd 行 >1024B 时截断/死；改为 read("*a")+gsub 去 CR。
    # attempt 与 dump 都接受一次性补丁，dump 额外支持逐帧补丁。
    import inspect
    import tas_replay
    from . import statejump as SJ
    tmpl = tas_replay.STATE_LUA_TMPL
    ok('read("*a")' in tmpl, "STATE_LUA_TMPL 用 read(*a) 整份读（>1024B cmd 不截断）")
    ok('read("*l")' not in tmpl, "STATE_LUA_TMPL 不再用 read(*l) 逐行（1024B 截断坑）")
    ok('gsub' in tmpl, "STATE_LUA_TMPL gsub 去 CR（Windows CRLF 坑）")
    ok('patches' in inspect.signature(SJ.StateSession.attempt).parameters,
       "attempt() 接受一次性 patches（补丁在加载状态后、推进前写入）")
    ok('patches' in inspect.signature(SJ.StateSession.dump).parameters,
       "dump() 有 patches 参数（授武器生产路径）")
    ok(':255' in SJ._format_patches([{'addr': 93, 'value': 255}]),
       "_format_patches dict→addr:byte 串")
    ok(SJ._format_patches([]) == '-', "_format_patches 空列表→'-'")
    raises(lambda: SJ._format_patches([93]), "_format_patches 非 dict 项被拒")

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        session = SJ.StateSession.__new__(SJ.StateSession)
        session.platform = "GBA"
        session._domain_sizes = {"EWRAM": 0x40000, "Combined WRAM": 0x48000}
        session._current_domain_name = "Combined WRAM"
        session.command = lambda *args, **kwargs: {"data": 1}
        session.dump(str(Path(td) / "valid"), spec="B",
                     patches=[{"addr": 0x1325D, "value": 4, "domain": "EWRAM"}])
        ok(True, "dump 补丁闸门：EWRAM 域内地址允许发送")
        raises(lambda: session.dump(str(Path(td) / "invalid"), spec="B",
                                    patches=[{"addr": 0x0201325D, "value": 4,
                                              "domain": "EWRAM"}]),
               "dump 补丁闸门：域外总线偏移在发送前拒绝")
        raises(lambda: session.dump(str(Path(td) / "missing"), spec="B",
                                    patches=[{"addr": 1, "value": 0,
                                              "domain": "IWRAM"}]),
               "dump 补丁闸门：mGBA 不存在的独立 IWRAM 域被拒绝")


def test_tail_stasis_gate():
    """11-21 晚4 从 3232 逼出来的第三轴：末段画面静止=跑完停在结算/菜单，要程序自己报。

    实测底子：死亡片尾段 74600–75400 共 41 个采样逐字节相同（800 帧静止），
    战斗过程中每 20 帧换一个摘要——所以 600 帧是量出来的，不是拍的。
    """
    from . import control as C
    import tempfile
    ok(C.TAIL_MIN_FROZEN_FRAMES == 600, "静止阈值 600 帧=实测 800 帧静止的 3/4")
    ok(C.TAIL_WINDOW_FRAMES == 1500 and C.TAIL_STRIDE == 20, "末段窗 1500 帧 / 步长 20")

    def probe(**kw):
        start = kw.pop("start", {"kind": "movie", "movie_frames": 33000})
        return C._tail_probe(kw.pop("ts", {}), start, kw.pop("checks", [{"id": "g"}]),
                             kw.pop("length", None))

    p = probe()
    ok(p and p["from"] == 33000 - C.TAIL_WINDOW_FRAMES, "movie 帧数能定末段窗（不必声明 verify.length）")
    ok(probe(length={"frames": 75400})["from"] == 75400 - C.TAIL_WINDOW_FRAMES, "声明长度优先于素材帧数")
    ok(probe(start={"kind": "boot", "path": "x"}) is None, "boot 又没声明长度＝预测不了末帧，明说不测")
    ok(probe(checks=[]) is None, "没有通关声称的任务不为末段多花截图")
    ok(probe(ts={"enabled": False}) is None, "显式关掉就不采样")
    ok(probe(ts={"stride": 25})["stride"] == 25, "stride 可覆盖")

    def measured(frames, same_from=None, min_frozen=None):
        with tempfile.TemporaryDirectory() as td:
            samples = []
            for i, f in enumerate(frames):
                blob = b"TAILFROZEN" if same_from is not None and f >= same_from else b"TAIL%05d" % f
                path = Path(td) / ("f%06d.png" % f)
                path.write_bytes(blob)
                samples.append({"frame": f, "screenshot": str(path)})
            cfg = {"min_frozen_frames": C.TAIL_MIN_FROZEN_FRAMES} if min_frozen is None \
                else {"min_frozen_frames": min_frozen}
            return C._tail_measurement({"tail_samples": samples}, cfg)

    tail = list(range(31800, 33001, 20))
    m = measured(tail, same_from=32400)
    ok(m["measured"] and m["frozen"], "尾段同一张图＝判出静止窗")
    ok(m["frozen_start_frame"] == 32400 and m["frozen_frames"] == 600, "只量尾部的连续同图段，中途重图不算")
    ok(m["frozen_samples"] == 31, "静止窗长度按采样数报出来")
    ok(measured(tail)["frozen_frames"] == 0, "画面一直在换＝没静止")
    ok(not measured(tail, same_from=32400, min_frozen=700)["frozen"], "阈值抬到 700 就不算静止（阈值真在用）")
    ok(measured([31800, 32000], same_from=31800)["frozen_frames"] == 200 and
       not measured([31800, 32000], same_from=31800)["frozen"], "两张同图=200 帧静止，不到阈值不算静止")
    ok(measured([31800])["measured"] is False, "单张采样不足，明说测不了而不是蒙一个数")
    with tempfile.TemporaryDirectory() as td:
        gone = str(Path(td) / "missing.png")
        m2 = C._tail_measurement({"tail_samples": [{"frame": 1, "screenshot": gone},
                                                   {"frame": 2, "screenshot": gone}]}, None)
        ok(not m2["measured"] and "采样不足" in m2["reason"], "图读不到＝不测，不许凭空造静止窗")

    def case(frozen_frames, evidence_frame, completion="pass"):
        stasis = {"measured": True, "frozen": frozen_frames >= C.TAIL_MIN_FROZEN_FRAMES,
                  "frozen_start_frame": 33000 - frozen_frames, "frozen_end_frame": 33000,
                  "frozen_samples": frozen_frames // 20 + 1, "frozen_frames": frozen_frames,
                  "min_frozen_frames": C.TAIL_MIN_FROZEN_FRAMES}
        program = {"completion": [{"id": "g", "evidence": {"checkpoint": "cp"}}]}
        runtime = {"completion": completion, "checkpoints": {"cp": {"frame": evidence_frame}}}
        return C._check_tail_stasis(program, runtime, stasis)

    # frozen_frames=800 ⇒ 静止窗 32200–33000；证词要落在 32200 之前才算"取自中途"。
    ok(case(800, 32100)[0] == "inconclusive", "证词取自静止窗之前 → 降档")
    ok("把 checkpoint 挪到末段" in case(800, 32100)[1], "降档理由要给出下一步该干什么")
    ok(case(800, 32990)[0] == "pass", "证词就在末屏 → 不冤枉（7429 形）")
    ok(case(200, 20000)[0] == "pass", "没到阈值的短暂定格不动声称")
    ok(case(800, 32500, completion="fail")[0] == "fail", "否证不需要证词，闸门不许反过来拦否证")
    ok(C._check_tail_stasis({"completion": []}, {"completion": "pass"}, {"frozen": True, "frozen_start_frame": 1,
                                                     "frozen_end_frame": 9, "frozen_samples": 2,
                                                     "frozen_frames": 8, "min_frozen_frames": 600})[0] == "pass",
       "没有判据的任务无从谈起证词位置")
    src = (Path(__file__).resolve().parent / "control_runtime.lua").read_text(encoding="utf-8")
    ok("tail_probe" in src and "result.tail_samples" in src, "Lua 侧采样器在位")
    ok("tail_samples" in (Path(__file__).resolve().parent / "control_runtime.py").read_text(encoding="utf-8"),
       "tail_samples 在 runtime→report 的搬运名单里（漏了就是静默丢数据）")
    # 11-21 深夜实测炸出来的回归：wire 把 Python None 编成 "z"→Lua 的 NULL 哨兵，不是 Lua nil。
    # §36 只判了 `~= nil`，于是所有"没有通关判据"的任务（包括每一个 window 观察任务）
    # 一帧没走就死在 integer(tail_probe.from)，报的是 invalid tail_probe.from: nil。
    from .control_runtime import _wire
    ok(_wire(None) == "z", "None 上线是 z 哨兵（这就是 Lua 侧 nil 判不到它的原因）")
    ok('if tag == "z" then return NULL end' in src,
       "Lua 解码器把 z 解成 NULL 哨兵——这句不在就说明 wire 约定改了，闸门要跟着改")
    ok("if tail_probe then" not in src and "tail_probe ~= nil" not in src,
       "Lua 里又出现只判 nil 的 tail_probe 守卫（NULL 哨兵会被当成有配置，整趟 0 帧失败）")
    ok(src.count("present(tail_probe)") == 2,
       "tail_probe 的两处守卫（采样循环与启动前校验）必须同时按 nil+NULL 双判，少一处就是半修")
    ok("local function present(v) return v ~= nil and v ~= NULL end" in src,
       "双判没有收敛成一个函数，而是各写一遍——下一处新增字段还会重犯")

    def wire_probe(spec_like):
        return C._tail_probe(spec_like.get("verify", {}).get("tail_stasis") or {},
                             spec_like["start"], (spec_like.get("completion") or {}).get("checks"),
                             (spec_like.get("verify") or {}).get("length"))

    win_like = {"start": {"kind": "movie", "movie_frames": 49782},
                "verify": {"length": {"frames": 49782}}, "completion": {}}
    ok(wire_probe(win_like) is None,
       "观察任务（无通关判据）的 tail_probe 应该是 None——这个形状就是 0 帧事故的现场")
    ok(_wire({"tail_probe": wire_probe(win_like)}) == _wire({"tail_probe": None}),
       "None 上线的字节形状变了，Lua 侧的哨兵判断得跟着重核")


def test_recorder_fidelity_ledger():
    """第三条轴不能只活在报表脚本里：registry 出的每条评估都要带 fidelity，台账头直接给合计。

    11-21 的教训是 561 部 FCEUX 内层片——输入流逐帧 0 处不一致、ROM 哈希也对得上，
    资源一格不缺，可本机没有 FCEUX 管线，通关判不了。这一格必须写在台账上，
    否则下一轮又有人把它算进"只差 ROM 就有希望"。
    反面教训同日出现：7429 也出自 FCEUX .fm2，却拿到了带证词的 pass，
    所以这根轴只能是先验（排获取优先级），不许被读成逐片判决。
    """
    import json
    from . import registry as R
    ok(R.recorder_fidelity("D:/lib/_converted/NES/3232.bk2", "")["completion_verdict"]
       == "not_judgeable_locally", "FCEUX 转出的 bk2＝本机通关有风险")
    ok(R.recorder_fidelity("D:/lib/_converted/NES/3232.bk2", "")["is_prior_only"] is True,
       "这一格自带『只是先验』的标记，消费者想当判决用也得先看见这行")
    ok(R.recorder_fidelity("D:\\lib\\_converted\\NES\\3232.bk2", "")["completion_verdict"]
       == "not_judgeable_locally", "反斜杠路径同样认得 _converted（Windows 写法不许漏）")
    ok(R.recorder_fidelity("D:/lib/movies/NES/3232.bk2",
                           "由 FCEUX 2.2.2 的 .fm2 转出")["completion_verdict"]
       == "not_judgeable_locally", "路径不在 _converted，但 movie_note 写了 FCEUX 也照样认")
    ok(R.recorder_fidelity("D:/lib/movies/NES/7429.bk2", "站点原生片")["completion_verdict"]
       == "judgeable_pending_evidence", "BizHawk 原生 bk2＝可判，但仍要截图证词")
    ok(R.recorder_fidelity("D:/lib/movies/NES/7429.BK2", "")["completion_verdict"]
       == "judgeable_pending_evidence", "大写后缀也认（不许因为 .BK2 掉进未实测）")
    ok(R.recorder_fidelity("D:/lib/movies/NES/6012.ltm", "")["completion_verdict"]
       == "unproven_recorder", "其它内层录制器记 unproven，不冒充可判")
    ok(R.recorder_fidelity(None, "电影不在本地")["completion_verdict"] == "no_movie",
       "没有电影就是 no_movie，不硬套保真度")
    ok(R.recorder_fidelity("", "")["completion_verdict"] == "no_movie",
       "空串路径同样算没电影（别掉进 .suffix 分支）")
    ok(R.recorder_fidelity("D:/lib/movies/NES/x.bk2", "")["why"].startswith("BizHawk 原生"),
       "每条判定都带一句人话理由，台账消费者不必自己猜")
    ok(set(R.RECORDER_WHY) == {R.recorder_fidelity(a, "")["completion_verdict"] for a in
                               ["x/_converted/y.bk2", "x.bk2", None, "x.ltm"]},
       "口径闭集：四种判定和理由表一一对应，报表层不许自加第五种")

    def row(mid, movie, note=""):
        return {"id": mid, "fidelity": R.recorder_fidelity(movie, note)}

    s = R.summarize_verdicts([row("a", "p/_converted/a.bk2"), row("b", "p/a.bk2"),
                               row("c", "p/a.bk2"), row("d", None), row("e", "p/a.ltm")])
    ok(s == {"not_judgeable_locally": 1, "judgeable_pending_evidence": 2,
             "no_movie": 1, "unproven_recorder": 1},
       "台账头合计走 registry.summarize_verdicts，与逐条判定同源（2 可判/1 不可判/1 无片/1 未实测）")
    raises(lambda: R.summarize_verdicts([{"id": "z"}]),
           "反证格：评估条目漏了 fidelity 就抛 SchemaError（不许静默少一格）")
    raises(lambda: R.summarize_verdicts([{"id": "z", "fidelity": {"completion_verdict": "maybe"}}]),
           "反证格：未知 verdict 也抛（口径漂移当场炸）")
    src = (Path(__file__).resolve().parent / "registry.py").read_text(encoding="utf-8")
    ok('"fidelity": recorder_fidelity(' in src, "assess() 出口真的带 fidelity（漏了就是台账没这根轴）")
    ok("summarize_verdicts(results)" in src, "build() 的合计调用同一个函数，不在两处各数一遍")
    ok('"completion_verdict"' in src, "registry.json 的 summary 里有这根轴的键名")
    # 先验落在权威台账上才算数，而且要带上它被推翻的那一条。
    reg = Path(R.DEFAULT_LIB) / "registry.json"
    ok(reg.is_file(), "先验入的是权威台账：registry.json 必须在（缺了就等于没落账）")
    d = json.loads(reg.read_text(encoding="utf-8"))
    f7429 = next((a["fidelity"] for a in d["assessments"] if str(a["id"]) == "7429"), None)
    ok(f7429 is not None and f7429["completion_verdict"] == "not_judgeable_locally",
       "台账里 7429 的先验确实是 FCEUX 内层——它不是漏判，是先验被实测推翻的那一条")
    ok(f7429 is not None and f7429["is_prior_only"] is True
       and 7429 in f7429["known_counterexamples"],
       "7429 的 pass 随台账一起走：读到这一格的人当场看见它被推翻过")
    ok(sum(d["summary"]["completion_verdict"].values()) == len(d["assessments"]),
       "台账头合计＝逐条同数（先验漏一格就对不上，当场红）")
    # 第四条轴：判据表在这台机器上实测过没有。录制器保真说的是"时序可不可信"，
    # 这一轴说的是"这个地址写出去读到的是什么"——待证词那 2530 部里 NES 只占 401，
    # 两轴混着报就是把"补上证词就能判"吹成全线可判。
    ok(R.PREDICATE_TABLE_MEASURED == ("NES",),
       f"判据表实测平台被改成 {R.PREDICATE_TABLE_MEASURED}：换成别的值就得同时交出该平台的"
       f"地址映射实测、可读窗口实测和帧量化实测，plan 与结果侧两处闸门会一起空转"
       "（判据表实测范围钉在 NES，放宽要连代码证据一起放宽）")
    for code, want in (("NES", "table_measured"), ("SNES", "table_missing"),
                       ("GB", "table_missing"), ("PSX", "table_missing"), ("", "table_missing")):
        pa = R.predicate_axis(code)
        ok(pa["predicate_verdict"] == want,
           f"predicate_axis({code!r})={pa['predicate_verdict']}，应为 {want}")
        ok(pa["platform"] == code, f"predicate_axis({code!r}) 没把平台原样带出来：{pa}")
    ok("predicate_platform_unproven" in R.predicate_axis("SNES")["why"],
       "SNES 那一格的 why 没点名启动前闸门码，读到台账的人不知道真跑会被拦"
       "（判据表文案与生产闸门必须同一名，台账才不是第二口径）")
    ok(R.summarize_predicates([{"id": "a", "predicate": R.predicate_axis("NES")},
                               {"id": "b", "predicate": R.predicate_axis("SNES")},
                               {"id": "c", "predicate": R.predicate_axis("GB")}])
       == {"table_measured": 1, "table_missing": 2},
       "判据表合计走 registry.summarize_predicates，与逐条同源（1 实测/2 缺表）")
    raises(lambda: R.summarize_predicates([{"id": "z"}]),
           "反证格：评估条目漏了 predicate 就抛 SchemaError（不许静默少一根轴）")
    raises(lambda: R.summarize_predicates([{"id": "z", "predicate": {"predicate_verdict": "maybe"}}]),
           "反证格：未知 predicate_verdict 也抛（口径漂移当场炸）")
    ok('"predicate": predicate_axis(' in src and '"predicate_verdict"' in src
       and "summarize_predicates(results)" in src,
       "assess()/build() 出口真的带这根轴（只在函数里算、不落台账=下一轮又没人知道）")
    p = next((a.get("predicate") for a in d["assessments"]), None)
    ok(isinstance(p, dict) and p.get("predicate_verdict") in R.PREDICATE_WHY,
       f"权威台账里没有 predicate 这根轴（p={p}）：改了生产者必须重建 registry.json，"
       f"python -m taspipe.registry build")


def test_predicate_platform_gate():
    """第四条轴的启动前闸门：非 NES 的"带判定内存断言"不许静默开工，也不许把 pass 买回来。

    11-21 查出来的事实是 `window = NES_READABLE_WINDOWS.get(core) if platform=="NES" else None`：
    可读窗口那道闸门对 SNES/GB/PSX 整段空转，而空转不等于放行——NES 的地址映射搬到
    别的平台上读回来的是另一个含义的数字，数字自洽冒充通关就是 §34/§35 那两个坑的重演。
    口径要分开：观察（watches/writes）与截图不受限制，补本平台判据表靠的正是读地址；
    只有会产出 pass/fail 的断言才拦。
    """
    import copy
    import json
    from . import control as C
    from . import registry as R
    chk = [{"id": "g", "domain": "System Bus", "addr": 129, "width": 1, "cmp": "eq", "value": 0}]

    def spec(plat, completion=None, step=None):
        d = {
            "version": 1, "id": "selftest-predicate-" + plat.lower(), "mode": "session",
            "purpose": "control", "game": _FAMOUS_FOR.get(plat, "t"), "platform": plat,
            "rom": {"path": "F:/不存在/rom.bin", "sha1": "0" * 40},
            "profile": {"bizhawk": "F:/不存在/BizHawk", "core": "NesHawk", "system": plat},
            "start": {"kind": "movie", "path": "F:/不存在/movie.bk2", "sha256": "0" * 64},
            "steps": [{"id": "p1", "op": "replay", "frames": 2}],
            "completion": ({"source": "movie", "checks": completion} if completion else {}),
        }
        if step:
            d["steps"].append(step)
        return d

    def codes(doc, allow=()):
        res = C.plan(doc, Path(__file__).resolve().parent, allow)
        return {b["code"] for b in res["blockers"]}, {w["code"] for w in res["warnings"]}

    hit, _ = codes(spec("SNES", chk))
    ok("predicate_platform_unproven" in hit,
       "SNES 的 completion 判据没被判据表闸门拦住——NES 地址冒充 SNES 通关就是假证据"
       "（非 NES 的判定断言必须拦在启动前）")
    hit2, _ = codes(spec("SNES", None, {"id": "a", "op": "assert", "checks": chk}))
    ok("predicate_platform_unproven" in hit2,
       "SNES 的 assert 步骤同样漏拦——判定不只活在 completion 里")
    ok_, _ = codes(spec("NES", chk))
    ok("predicate_platform_unproven" not in ok_,
       "NES 的正对照撞上了判据表闸门（实测范围写错，或闸门写反了）"
       "——NES 实测过判据表，不受这条限制")
    obs, _ = codes(spec("SNES", None, {"id": "o", "op": "observe",
                                       "watches": [{"id": "w", "domain": "System Bus",
                                                    "addr": 129, "width": 1}]}))
    ok("predicate_platform_unproven" not in obs,
       "SNES 只读地址的观察被判据表闸门挡了——补判据表本来就要读地址，看图流程不许受这条限制")
    blk, wrn = codes(spec("SNES", chk), ("predicate_platform_unproven",))
    ok("predicate_platform_unproven" not in blk and "predicate_platform_unproven" in wrn,
       f"--allow 没把它降级成 warning（blockers={sorted(blk)} warnings={sorted(wrn)}）——"
       f"放行只该买到「这一次真跑过」")
    warn = [{"code": "predicate_platform_unproven", "reason": "t"}]
    ok(C._check_predicate_platform("SNES", {"completion": "pass"}, warn)[0] == "inconclusive",
       "带警告时 pass 没被降级——非 NES 的 NES 地址数字能直接冒充通关")
    ok(C._check_predicate_platform("SNES", {"completion": "pass"}, [])[0] == "pass",
       "没有该警告却动了判定（闸门误伤已实测平台）")
    ok(C._check_predicate_platform("NES", {"completion": "pass"}, [])[0] == "pass",
       "NES 正对照被降级")
    ok(C._check_predicate_platform("SNES", {"completion": "fail"}, warn)[0] == "fail",
       "降级函数把 fail 翻成了别的——它只许往下走")
    src = (Path(__file__).resolve().parent / "control.py").read_text(encoding="utf-8")
    ok("R.PREDICATE_TABLE_MEASURED" in src,
       "control 侧自己抄了一份平台名单（两份口径迟早漂移，实测范围只认 registry 那一格）")
    ok(src.count("predicate_platform_unproven") >= 3,
       "闸门码在生产里的出现次数不够：启动前拦截与结果侧降级必须同时存在，少一处就是静默放行")


def test_timing_fields():
    # 11-22 SNES 三点（50/1200/2400 帧）互相打架，根因是产物里根本没有时间字段
    # （wall_seconds 一直是 None），过去所有 fps 都是 plan.json/result.json 的 mtime 相减，
    # 把"取 ROM 条目+配置隔离""模拟器冷启""回放"糊成一个数。这里钉死分段的算术。
    from .control_runtime import _timing_summary

    full = _timing_summary({"setup_seconds": 12.5, "process_seconds": 167.5,
                           "boot_seconds": 27.5, "frames_advanced": 1120})
    ok(full["wall_seconds"] == 180.0, "wall = setup + process，别的都不许算进去")
    ok(full["frames_per_second"] == 6.69, "fps 的分母是 process（含冷启），不是 wall")
    ok(full["frames_per_second_after_boot"] == 8.0,
       "扣掉冷启之后的稳态速率要单列，否则批跑节奏会被模拟器启动时间压低")

    no_boot_split = _timing_summary({"setup_seconds": 1.0, "process_seconds": 20.0,
                                     "boot_seconds": 20.0, "frames_advanced": 300})
    ok("frames_per_second_after_boot" not in no_boot_split,
       "心跳来得和退出一样晚，就没有稳态段可算，不许造一个除零/负数的速率")

    never_ran = _timing_summary({"setup_seconds": 8.0, "process_seconds": 30.0,
                                 "boot_seconds": 6.0, "frames_advanced": 0})
    ok("frames_per_second" not in never_ran,
       "0 帧（截断/没启动）不许带 fps——那正是 replay_never_started 与'跑得慢'长一样的地方")
    ok(never_ran["wall_seconds"] == 38.0, "没跑成也要留下耗时，否则故障趟在产物里是空白")

    crashed_early = _timing_summary({"frames_advanced": 100})
    ok("wall_seconds" not in crashed_early and "frames_per_second" not in crashed_early,
       "缺端点就缺端点，不许把不完整的段拼成一个看起来像实测的数")
    ok(_timing_summary({"setup_seconds": 2.0, "process_seconds": 3.0,
                        "frames_advanced": None})["wall_seconds"] == 5.0,
       "frames_advanced 为 None 时只少 fps，wall 照样落地")

    # 生产里这个函数会被调两次：finally 一次（那时 frames_advanced 还没搬过来），
    # 搬运后再一次。第二次必须只是覆盖，不许叠加或把已有字段弄丢。
    at_exit = _timing_summary({"setup_seconds": 12.5, "process_seconds": 167.5,
                               "boot_seconds": 27.5})
    ok("frames_per_second" not in at_exit, "finally 那次还没实到帧数，先不出 fps")
    carried = _timing_summary(dict(at_exit, frames_advanced=1120))
    ok(carried["wall_seconds"] == at_exit["wall_seconds"]
       and carried["frames_per_second"] == 6.69,
       "搬运后重算：wall 不变、fps 补上——覆盖而不是第二套口径")


def test_runtime_dialog_diagnostics():
    from .control_runtime import _dialog_error_message

    evidence = [{"title": "Exception", "class": "#32770",
                 "texts": ["See the inner exception for details.", "System.InvalidOperationException: fixture"]}]
    message = _dialog_error_message(evidence, ["Exception"])
    ok("Exception: See the inner exception" in message and "System.InvalidOperationException" in message,
       "EmuHawk 异常框必须把正文和内部异常带进产物，不能只报窗口标题")
    ok(_dialog_error_message([], ["Error", "Exception"]) == "EmuHawk error dialog: Error | Exception",
       "抄不到正文时保留所有危险窗口标题，不许静默丢证据")
    ok(_dialog_error_message([{"title": "Exception", "texts": []}], ["Exception"])
       == "EmuHawk error dialog: Exception",
       "空正文不拼出冒号或空斜杠")


def test_dangling_call_gate():
    # 11-21 实跑踩的坑：把 latch 闸门从 control_runtime.py 挪去 control.py 时删了函数体，
    # 调用点留下了。control_selftest 的隔离钩子禁止 import control_runtime（防误启模拟器），
    # 所以这条 NameError 只有真开一次 EmuHawk 才暴露——用静态名核对补上离线闸门。
    import ast
    import builtins
    pkg = Path(__file__).resolve().parent
    known_base = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__package__"}
    dangling = []
    for py in sorted(pkg.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        bound = set(known_base)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                bound.update(a.arg for a in list(node.args.args) + list(node.args.kwonlyargs)
                             + ([node.args.vararg] if node.args.vararg else [])
                             + ([node.args.kwarg] if node.args.kwarg else []))
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                bound.add(node.id)
            elif isinstance(node, ast.alias):
                bound.add(node.asname or node.name.split(".")[0])
            elif isinstance(node, ast.ExceptHandler) and node.name:
                bound.add(node.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id not in bound:
                dangling.append(f"{py.name}:{node.lineno} {node.func.id}()")
    ok(not dangling, "taspipe 各模块没有调用未定义的名字（挪函数忘删调用点=实跑才炸）: "
       + ", ".join(dangling[:6]))

    # 根目录说明书的字节卫生（11-22 实翻车：heredoc 里写 "F:\taspipe…" 的反斜杠，
    # \t 被解释成制表符、\f 成换页符，落进说明书变成看不见的控制字符）。
    # 一律用 chr() 而不是转义序列，免得这条闸门自己再犯同一个错。
    CTRL_CHARS = (chr(9), chr(12), chr(13))
    TOKENS = ("__CNT__", "__PROD__", "__FIXPROD__", "__SCREEN__")

    def doc_defects(text):
        bad = [f"控制字符{hex(ord(c))}x{text.count(c)}" for c in CTRL_CHARS if text.count(c)]
        bad += [f"占位符{t}" for t in TOKENS if t in text]
        return bad

    root = Path(__file__).resolve().parents[2]
    docs = [root / "测试问题与闸门说明书.md", root / "选题规则_只测热门作品_2026-11-22.md"]
    for d in docs:
        ok(d.is_file(), f"根目录交付文档在册: {d.name}")
        if d.is_file():
            body = d.read_text(encoding="utf-8")
            ok(not doc_defects(body), f"{d.name} 无控制字符/无未替换占位符: "
               + "; ".join(doc_defects(body)))
    ok(doc_defects("x" + chr(12) + "y __CNT__") == ["控制字符0xcx1", "占位符__CNT__"],
       "反证:换页符与占位符真出现时这条尺子必须抓到")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())