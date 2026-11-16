"""Offline direct-return contract tests; no ComfyUI or After Effects process."""
from fractions import Fraction
import hashlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink.studio_direct_video import inspect_video_master
try:
    from comfylink.studio_sessions import Session, StudioSessions
except ModuleNotFoundError as exc:
    if exc.name != 'aiohttp': raise
    Session = StudioSessions = None


class FakeFrame:
    def __init__(self, index, *, format='yuv420p10le', width=512, height=320, pts=None):
        self.format = types.SimpleNamespace(name=format)
        self.width, self.height = width, height
        self.pts = index if pts is None else pts
        self.time_base = Fraction(1001, 30000)


class FakeMovie:
    def __init__(self, frames, *, codec='h264', tag='avc1', rate=Fraction(30000, 1001)):
        context = types.SimpleNamespace(name=codec, codec_tag=tag)
        stream = types.SimpleNamespace(codec_context=context, average_rate=rate, width=512, height=320, type='video')
        self.streams = StreamList([stream])
        self.frames = frames

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def decode(self, *, video):
        assert video == 0
        return iter(self.frames)


class StreamList(list):
    @property
    def video(self): return [s for s in self if s.type == 'video']


class NativeVideoInspectorTest(unittest.TestCase):
    def inspect(self, movie, name='result.mp4', count=3):
        fake_av = types.SimpleNamespace(open=lambda _: movie)
        with patch.dict(sys.modules, av=fake_av):
            return inspect_video_master(name, width=512, height=320, frame_count=count,
                                        frame_rate={'numerator': 30000, 'denominator': 1001})

    def test_actual_precision_and_every_timestamp(self):
        movie = FakeMovie([FakeFrame(i) for i in range(3)])
        result = self.inspect(movie)
        self.assertEqual((result['codec'], result['bitDepth'], result['frameCount']), ('h264', 10, 3))
        for frame, message in ((FakeFrame(2, pts=5), 'cadence'),
                               (FakeFrame(2, format='yuv420p'), 'precision'),
                               (FakeFrame(2, width=500), 'raster')):
            with self.subTest(message=message):
                with self.assertRaises(ValueError):
                    self.inspect(FakeMovie([FakeFrame(0), FakeFrame(1), frame]))
        with self.assertRaises(ValueError):
            self.inspect(FakeMovie([FakeFrame(i) for i in range(4)]))
        with self.assertRaises(ValueError):
            self.inspect(FakeMovie([FakeFrame(0)]))

    def test_h264_8_and_prores_12_are_labelled_by_stored_pixels(self):
        eight = self.inspect(FakeMovie([FakeFrame(i, format='yuv420p') for i in range(3)]))
        self.assertEqual(eight['bitDepth'], 8)
        prores = self.inspect(FakeMovie([FakeFrame(i, format='yuv444p12le') for i in range(3)],
                                        codec='prores', tag='ap4h'), name='result.mov')
        self.assertEqual((prores['codec'], prores['bitDepth']), ('prores4444', 12))
        with self.assertRaises(ValueError):
            self.inspect(FakeMovie([FakeFrame(i, format='yuva444p12le') for i in range(3)],
                                   codec='prores', tag='ap4h'), name='result.mov')


@unittest.skipIf(StudioSessions is None, 'Studio service dependencies are unavailable in this Python')
class NativeVideoDescriptorTest(unittest.TestCase):
    def test_exact_selected_movie_is_published_without_conversion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs, outputs = root / 'input', root / 'output'
            inputs.mkdir(); outputs.mkdir()
            selected = outputs / 'finished.mp4'
            selected.write_bytes(b'physical master bytes')
            source_hash = 'a' * 64
            session = Session('b' * 32, 'c' * 64, 'http://127.0.0.1:1', 'd' * 64,
                              'http://127.0.0.1:2',
                              {'capabilities': {'transfer': True, 'nativeVideoReturn': True}}, 9999999999)
            session.source = {'sourceTransfer': {'kind': 'native_video',
                'file': {'sha256': source_hash}, 'width': 512, 'height': 320,
                'frameCount': 3, 'frameRate': {'numerator': 30000, 'denominator': 1001}}}
            service = StudioSessions(inputs, outputs, instance_id='instance')
            body = {'kind': 'native_video', 'master': {'filename': selected.name,
                    'subfolder': '', 'type': 'output'}}
            proof = {'codec': 'h264', 'pixelFormat': 'yuv420p10le', 'bitDepth': 10,
                     'width': 512, 'height': 320, 'frameCount': 3,
                     'frameRate': {'numerator': 30000, 'denominator': 1001}, 'hasAlpha': False}
            with patch('comfylink.studio_direct_video.inspect_video_master', return_value=proof):
                descriptor = service.prepare_result(session, body)
            self.assertEqual(descriptor['master']['filename'], 'finished.mp4')
            self.assertEqual(descriptor['sourceSha256'], source_hash)
            self.assertEqual(descriptor['video']['sha256'], hashlib.sha256(selected.read_bytes()).hexdigest())
            self.assertEqual(session.result_files[0][0], selected)
            self.assertEqual(session.result_files[0][2]['byteLength'], len(selected.read_bytes()))
            session.context['capabilities']['nativeVideoReturn'] = False
            with self.assertRaises(ValueError): service.prepare_result(session, body)


if __name__ == '__main__': unittest.main()
