# -*- coding: utf-8 -*-
"""TAS 回看看门狗离线自检：不启动 BizHawk，验「弹框堵死」那条链的三道防线。

背景（2026-11-07 实测）：45472 帧 17:08 全采完，最后一帧的 frameadvance
触发 BizHawk "end of the movie ... missing a cycle count" 模态框，Lua 卡住，
client.exit() 到不了，Python 白等 1635s 超时；0 字节 cap.txt 还被判成
replay_no_desync=pass。这里逐条钉住修复。

跑法：python _工具脚本/test_tas_watchdog.py
"""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tas_replay  # noqa: E402
from taspipe import watchdog as wd  # noqa: E402


class TestLuaTemplate(unittest.TestCase):
    def setUp(self):
        self.body = tas_replay.LUA_TMPL.format(dir="F:/tmp/x", n=180)

    def test_heartbeat_written_every_frame(self):
        self.assertIn("heartbeat.txt", self.body)
        self.assertIn("hb:flush()", self.body)
        # 定宽，避免 seek(0) 覆写时尾部残留上一帧的字符
        self.assertIn("%08d %-10s", self.body)

    def test_last_frame_does_not_frameadvance(self):
        """最后一帧截图完就 break，不给 BizHawk 弹电影结束框的机会。"""
        guard = self.body.index("if i == N - 1 then")
        advance = self.body.index("emu.frameadvance()")
        self.assertLess(guard, advance, "break 必须排在 frameadvance 前面")
        self.assertIn("break", self.body[guard:advance])

    def test_cap_txt_always_gets_a_status(self):
        self.assertIn("status=%s n=%d mode=%s", self.body)
        self.assertIn("f:flush()", self.body)
        self.assertIn("client.exit()", self.body)


class TestParseReport(unittest.TestCase):
    """空证据必须返回 None，不许被当成「没发现 desync」。"""

    def test_missing_or_empty_cap_is_unknown(self):
        for text in ("", "   ", "(no cap.txt)"):
            self.assertEqual(tas_replay.parse_report(text), (None, None))

    def test_complete_is_clean(self):
        self.assertEqual(
            tas_replay.parse_report("status=complete n=180 mode=PLAY\n"),
            ("complete", False))

    def test_desync_is_confirmed_failure(self):
        self.assertEqual(
            tas_replay.parse_report("desync at 42 mode=FINISHED\nstatus=desync n=43\n"),
            ("desync", True))

    def test_timeout_and_watchdog_are_unknown(self):
        for text in ("TIMEOUT after 1635s (target 45472 frames)",
                     "WATCHDOG stalled_killed after 30.2s"):
            self.assertEqual(tas_replay.parse_report(text), ("timeout", None))


class TestVerdict(unittest.TestCase):
    def test_11_07_false_green_is_blocked(self):
        """复现那次事故：空 cap.txt + 超时，绝不能是 pass。"""
        self.assertEqual(wd.replay_verdict(None, "timeout"), "inconclusive")
        self.assertEqual(wd.replay_verdict(False, "timeout"), "inconclusive")
        self.assertEqual(wd.exit_verdict("timeout"), "fail")

    def test_only_clean_complete_passes(self):
        self.assertEqual(wd.replay_verdict(False, "complete"), "pass")
        self.assertEqual(wd.replay_verdict(False, "movie_end"), "pass")
        self.assertEqual(wd.replay_verdict(True, "desync"), "fail")
        self.assertEqual(wd.exit_verdict("complete"), "pass")
        self.assertEqual(wd.exit_verdict("stalled_killed"), "fail")
        self.assertEqual(wd.exit_verdict("unknown"), "inconclusive")


class TestHeartbeat(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(wd.read_heartbeat(d), (0, ""))
            with open(wd.heartbeat_path(d), "w", encoding="utf-8") as fh:
                fh.write("00000042 PLAY     \n")
            self.assertEqual(wd.read_heartbeat(d), (42, "PLAY"))

    def test_corrupt_is_safe(self):
        with tempfile.TemporaryDirectory() as d:
            with open(wd.heartbeat_path(d), "w", encoding="utf-8") as fh:
                fh.write("garbage\n")
            self.assertEqual(wd.read_heartbeat(d), (0, ""))


class TestWatchProcess(unittest.TestCase):
    def test_clean_exit(self):
        with tempfile.TemporaryDirectory() as d:
            hb = wd.heartbeat_path(d)
            p = subprocess.Popen(
                [sys.executable, "-c",
                 "import sys;open(sys.argv[1],'w').write('00000007 PLAY\\n')", hb])
            info = wd.watch_process(p, d, poll=0.02, stall_timeout=0.3,
                                    dismiss_grace=0.2, auto_dismiss=False,
                                    hard_timeout=5)
            self.assertEqual(info["termination"], "exited")
            self.assertGreaterEqual(info["last_frame"], 0)

    def test_stalled_child_is_killed_not_waited_27_minutes(self):
        with tempfile.TemporaryDirectory() as d:
            hb = wd.heartbeat_path(d)
            p = subprocess.Popen(
                [sys.executable, "-c",
                 "import sys,time;open(sys.argv[1],'w').write("
                 "'00000042 PLAY\\n');time.sleep(60)", hb])
            t0 = __import__("time").time()
            info = wd.watch_process(p, d, poll=0.02, stall_timeout=0.3,
                                    dismiss_grace=0.2, auto_dismiss=False,
                                    hard_timeout=8)
            elapsed = __import__("time").time() - t0
            self.assertEqual(info["termination"], "stalled_killed")
            self.assertGreaterEqual(info["stalls"], 1)
            self.assertLess(elapsed, 5, "看门狗不该空等")
            self.assertIsNotNone(p.poll(), "子进程必须已经被收掉")

    def test_hard_timeout_still_works_when_heartbeat_keeps_moving(self):
        with tempfile.TemporaryDirectory() as d:
            hb = wd.heartbeat_path(d)
            p = subprocess.Popen(
                [sys.executable, "-c",
                 "import sys,time\n"
                 "for i in range(500):\n"
                 " open(sys.argv[1],'w').write('%08d PLAY\\n' % i)\n"
                 " time.sleep(0.02)\n", hb])
            info = wd.watch_process(p, d, poll=0.02, stall_timeout=0.3,
                                    dismiss_grace=0.2, auto_dismiss=False,
                                    hard_timeout=0.6)
            self.assertEqual(info["termination"], "timeout")
            self.assertIsNotNone(p.poll())


class TestRunReplayOffline(unittest.TestCase):
    """不启动 BizHawk：假子进程走完 run_replay 的组装、看门狗与三态判定。

    BizHawk 在沙箱里会因 REG.exe 黑名单起不来，所以这里把 Popen 换成
    一个会写 frames/heartbeat/cap.txt 的 Python 子进程，验证编排本身。
    """

    @staticmethod
    def _script(n, clean):
        tail = ("open(os.path.join(work, 'cap.txt'), 'w').write("
                "'status=complete n=%d mode=PLAY\\n' % n)\n") if clean \
            else "time.sleep(60)\n"
        return (
            "import os, sys, time\n"
            "work = sys.argv[1]\n"
            f"n = {n}\n"
            "fd = os.path.join(work, 'frames')\n"
            "os.makedirs(fd, exist_ok=True)\n"
            "for i in range(n):\n"
            "    open(os.path.join(fd, 'f%04d.png' % i), 'wb').write(b'x')\n"
            "    with open(os.path.join(work, 'heartbeat.txt'), 'w') as hb:\n"
            "        hb.write('%08d PLAY\\n' % (i + 1))\n"
            + tail)

    def _run(self, n, clean, stall=0.3, grace=0.2):
        with tempfile.TemporaryDirectory() as d:
            bh = os.path.join(d, "bh")
            os.makedirs(bh)
            movie, rom = os.path.join(d, "m.bk2"), os.path.join(d, "r.nes")
            with open(movie, "wb") as f:
                f.write(b"x")
            with open(rom, "wb") as f:
                f.write(b"x")
            work = os.path.join(d, "work")
            script = self._script(n, clean)
            real = subprocess.Popen

            def fake(cmd, **kw):
                # taskkill / 其它子进程照常放行，只替换 EmuHawk 这一条。
                if str(cmd[0]).lower().endswith("emuhawk.exe"):
                    return real([sys.executable, "-c", script, work],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
                return real(cmd, **kw)

            with mock.patch("tas_replay.subprocess.Popen", side_effect=fake):
                return tas_replay.run_replay(
                    movie, rom, "NesHawk", "NES", bh, n, work=work,
                    timeout=20, stall_timeout=stall, dismiss_grace=grace,
                    auto_dismiss=False)

    def test_clean_exit_reaches_complete_and_can_encode(self):
        res = self._run(24, clean=True)
        self.assertEqual(res["n_frames"], 24)
        self.assertIs(res["desync"], False)
        self.assertEqual(res["status"], "complete")
        self.assertEqual(res["termination"], "complete")
        self.assertFalse(res["timeout"])
        self.assertEqual(res["watchdog"]["termination"], "exited")
        self.assertEqual(wd.replay_verdict(res["desync"], res["termination"]), "pass")

    def test_stalled_keeps_captured_frames_for_next_step(self):
        """卡死也不能把已采到的帧扔掉：上层照样能编码，但证据等级是 inconclusive。"""
        res = self._run(24, clean=False)
        self.assertEqual(res["n_frames"], 24, "已采帧必须留下给下一步编码")
        self.assertEqual(res["termination"], "stalled_killed")
        self.assertIsNone(res["desync"])
        self.assertLess(res["watchdog"]["elapsed"], 5)
        self.assertEqual(wd.replay_verdict(res["desync"], res["termination"]),
                         "inconclusive")
        self.assertEqual(wd.exit_verdict(res["termination"]), "fail")


class TestDialogSafety(unittest.TestCase):
    def test_unknown_pid_is_a_noop(self):
        self.assertEqual(wd.dismiss_bizhawk_dialog(99999999), 0)
        self.assertEqual(wd.windows_of_pid(99999999), [])
        self.assertEqual(wd.dismiss_bizhawk_dialog(0), 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    unittest.main(verbosity=2)
