# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace

import numpy as np
from PIL import Image

from taspipe import native_av
from taspipe.schema import SchemaError

PASS = 0


def check(name, condition):
    global PASS
    if not condition:
        raise AssertionError(name)
    PASS += 1
    print(f"PASS {PASS:02d} {name}")


def reject(name, func):
    try:
        func()
    except (SchemaError, FileExistsError, RuntimeError):
        check(name, True)
    else:
        raise AssertionError(name)


def main():
    with tempfile.TemporaryDirectory(prefix='native_av_selftest_') as tmp:
        root = Path(tmp)
        lua = native_av.render_capture_lua(
            'Up+B', 'GBA', 2,
            [{'addr': 78429, 'value': 47, 'domain': 'EWRAM'}],
            root, speed=100, joypad_port=1)
        check('N01 GBA 宏规范展开为三帧', 'local inputs = {{["Up"]=true, ["B"]=true}, {}, {}}' in lua)
        check('N02 一次性补丁写入指定 EWRAM 地址', 'memory.write_u8(78429, 47, "EWRAM")' in lua)
        check('N03 导出脚本每帧写心跳', 'hb:write(string.format("%08d native_av\\n", i))' in lua)
        check('N04 导出脚本使用同步逐帧推进', 'client.unpause()\n    emu.frameadvance()\n    client.pause()' in lua)
        reject('N05 拒绝负 extra', lambda: native_av.render_capture_lua('-', 'GBA', -1, [], root))
        reject('N06 拒绝零帧导出', lambda: native_av.render_capture_lua('-', 'GBA', 0, [], root))
        reject('N07 拒绝未知平台按键', lambda: native_av.render_capture_lua('X', 'GBA', 1, [], root))
        reject('N08 拒绝非法补丁值', lambda: native_av.render_capture_lua('-', 'GBA', 1,
                   [{'addr': 1, 'value': 256, 'domain': 'EWRAM'}], root))
        command = native_av.build_command(root / 'BizHawk', root, root / 'out.avi',
                                          root / 'base.state', root / 'rom.gba', 42)
        check('N09 命令使用正确 FFmpeg writer 短名', '--dump-type=ffmpeg' in command)
        check('N10 命令绑定 42 帧自动收尾', '--dump-length=42' in command and '--dump-close' in command)
        check('N11 命令启用同步声音模式', '--audiosync=true' in command)
        check('N12 命令同时加载状态和 Lua', any(x.startswith('--load-state=') for x in command)
              and any(x.startswith('--lua=') for x in command))
        reject('N13 拒绝非法 dump-length', lambda: native_av.build_command(
            root, root, root / 'o.avi', root / 's.state', root / 'r.gba', 0))
        volume = native_av._volume('[Parsed_volumedetect_0] mean_volume: -32.4 dB\n'
                                   '[Parsed_volumedetect_0] max_volume: -19.4 dB\n')
        check('N14 音量解析取最终峰值与均值', volume == {'max_db': -19.4, 'mean_db': -32.4})
        missing = native_av.inspect_output(root / 'missing.avi', 42, 59.7275, 'ffmpeg', 'ffprobe')
        check('N15 缺文件不得通过', missing['status'] == 'fail' and not missing['checks']['file_nonempty'])

        fake = root / 'fake.avi'
        fake.write_bytes(b'not-empty')
        original_run = native_av._run
        calls = []
        probe_document = {
            'streams': [
                {'codec_type': 'video', 'codec_name': 'ffv1', 'width': 240,
                 'height': 160, 'start_pts': 0, 'nb_frames': '42'},
                {'codec_type': 'audio', 'codec_name': 'pcm_s16le', 'start_pts': 0,
                 'sample_rate': '44100', 'channels': 2,
                 'nb_frames': str(round(42 / 59.7275 * 44100))},
            ],
            'format': {'duration': str(42 / 59.7275)},
        }

        def fake_run(command, timeout=60, text=True):
            calls.append(command)
            if '-show_entries' in command:
                return SimpleNamespace(returncode=0, stdout=json.dumps(probe_document), stderr='')
            return SimpleNamespace(returncode=0, stdout='', stderr=
                '[Parsed_volumedetect_0] mean_volume: -32.4 dB\n'
                '[Parsed_volumedetect_0] max_volume: -19.4 dB\n')

        native_av._run = fake_run
        try:
            good = native_av.inspect_output(fake, 42, 59.7275, 'ffmpeg', 'ffprobe', (240, 160))
            check('N16 完整音视频证据全部通过', good['status'] == 'pass' and all(good['checks'].values()))
            bad = native_av.inspect_output(fake, 41, 59.7275, 'ffmpeg', 'ffprobe', (240, 160))
            check('N17 帧数不符不得通过', bad['status'] == 'fail' and not bad['checks']['video_frames'])
            bad = native_av.inspect_output(fake, 42, 59.7275, 'ffmpeg', 'ffprobe', (256, 224))
            check('N18 分辨率不符不得通过', bad['status'] == 'fail' and not bad['checks']['resolution'])
            probe_document['streams'][1]['nb_frames'] = str(round(42 / 59.7275 * 44100) - 5)
            near = native_av.inspect_output(fake, 42, 59.7275, 'ffmpeg', 'ffprobe', (240, 160))
            check('N19 音频块对齐的 5 采样差在 1ms 内可通过', near['status'] == 'pass'
                  and near['timing']['sample_delta'] == -5)
            probe_document['streams'][1]['nb_frames'] = str(round(
                round(42 / 59.7275 * 44100) + native_av.AV_AUDIO_TOLERANCE_SECONDS * 44100 + 1))
            bad = native_av.inspect_output(fake, 42, 59.7275, 'ffmpeg', 'ffprobe', (240, 160))
            check('N20 音频样本跨度偏离超过 1ms 不得通过', bad['status'] == 'fail'
                  and not bad['checks']['audio_sample_span'])
            probe_document['streams'][1]['nb_frames'] = str(round(42 / 59.7275 * 44100))
            probe_document['streams'][1]['start_pts'] = 1
            bad = native_av.inspect_output(fake, 42, 59.7275, 'ffmpeg', 'ffprobe', (240, 160))
            check('N21 音频起点非零不得通过', bad['status'] == 'fail'
                  and not bad['checks']['audio_start_zero'])
            probe_document['streams'][1]['start_pts'] = 0
            probe_document['streams'][0]['start_pts'] = 1
            bad = native_av.inspect_output(fake, 42, 59.7275, 'ffmpeg', 'ffprobe', (240, 160))
            check('N22 视频起点非零不得通过', bad['status'] == 'fail'
                  and not bad['checks']['video_start_zero'])
        finally:
            native_av._run = original_run

        frames = root / 'frames'
        frames.mkdir()
        for index in range(2):
            Image.new('RGB', (2, 2), (index, 1, 0)).save(frames / f'f{index:04d}.png')
        raw = bytes([0, 1, 0] * 4 + [1, 1, 0] * 4)

        def pixel_run(command, timeout=60, text=True):
            if '-show_entries' in command:
                return SimpleNamespace(returncode=0, stdout=json.dumps({
                    'streams': [{'width': 2, 'height': 2, 'nb_frames': '2'}]}), stderr='')
            return SimpleNamespace(returncode=0, stdout=raw, stderr=b'' if not text else '')

        native_av._run = pixel_run
        try:
            same = native_av.compare_to_png(fake, frames, 2, 'ffmpeg', 'ffprobe')
            check('N23 逐帧像素完全一致才通过', same['exact'] and same['exact_frames'] == 2)
            Image.new('RGB', (2, 2), (9, 9, 9)).save(frames / 'f0001.png')
            different = native_av.compare_to_png(fake, frames, 2, 'ffmpeg', 'ffprobe')
            check('N24 单帧像素差异不得通过', not different['exact'] and different['exact_frames'] == 1)
            def truncated_run(command, timeout=60, text=True):
                if '-show_entries' in command:
                    return pixel_run(command, timeout=timeout, text=text)
                return SimpleNamespace(returncode=0, stdout=raw[:-1], stderr=b'')

            native_av._run = truncated_run
            reject('N25 解码像素长度不足不得通过', lambda: native_av.compare_to_png(
                fake, frames, 2, 'ffmpeg', 'ffprobe'))
        finally:
            native_av._run = original_run

        wrong = root / 'wrong.exe'
        wrong.write_bytes(b'wrong')
        reject('N26 拒绝错误 FFmpeg 哈希', lambda: native_av.validate_ffmpeg(wrong))
        reject('N27 拒绝不存在的 FFmpeg', lambda: native_av.validate_ffmpeg(root / 'none.exe'))

    print(f'NATIVE AV SELFTEST {PASS}/{PASS}')


if __name__ == '__main__':
    main()
