"""Real CPU media evidence for Wan's AE return; generated frames are fixtures.

No diffusion, GPU execution, live Studio installation or AE process is used.
"""
import ast
from contextlib import contextmanager
from fractions import Fraction
import hashlib
import importlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import av
import numpy as np
import test_artist_studio as fixture
import test_wan21_relight as recipe_fixture

studio = fixture.studio
wan21 = importlib.import_module(studio.__package__ + '.wan21_relight')


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                    *map(str, args)], check=True, timeout=45)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(path):
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        frames = [float(frame.to_ndarray(format='rgb24').mean())
                  for frame in container.decode(video=0)]
        return dict(fps=stream.average_rate, width=stream.width, height=stream.height,
                    frames=len(frames), levels=frames, audio=len(container.streams.audio))


def contract(rate, count=9):
    return dict(schemaVersion=1, sessionId='a' * 32, frameCount=count,
                modelFrames=count, trimFrames=count, width=1920, height=1080,
                frameRate=dict(numerator=rate.numerator, denominator=rate.denominator))


def native_adapters(directory, details):
    tree = ast.parse((Path(studio.__file__).parent / '__init__.py').read_text(encoding='utf-8'))
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)
               and node.name in ('GenjLoadReviewedShot', 'GenjRestoreSoundtrack')]
    namespace = dict(CATEGORY='Test', __package__=studio.__package__,
                     verify_review=lambda identity: (directory, {'clip': details, 'files': {}}),
                     Path=Path, av=av, Fraction=Fraction, np=np, re=re, json=json,
                     ffmpeg=ffmpeg, digest_file=digest, source_path=Path,
                     root=lambda: directory, InputImpl=SimpleNamespace(VideoFromFile=lambda path: path))
    exec(compile(ast.Module(body=classes, type_ignores=[]), 'wan_ae_native_adapters', 'exec'), namespace)
    return namespace['GenjLoadReviewedShot'](), namespace['GenjRestoreSoundtrack']()


@contextmanager
def approved_source(rate):
    count = 9
    with tempfile.TemporaryDirectory() as folder:
        directory = Path(folder)
        original = directory / 'original.mov'
        with av.open(str(original), 'w') as container:
            stream = container.add_stream('libx264', rate=rate)
            stream.width, stream.height, stream.pix_fmt = 1920, 1080, 'yuv420p'
            stream.options = {'crf': '0', 'preset': 'ultrafast'}
            for index in range(count):
                frame = av.VideoFrame.from_ndarray(
                    np.full((1080, 1920, 3), 20 + index * 20, np.uint8), format='rgb24')
                frame.pts, frame.time_base = index, 1 / rate
                for packet in stream.encode(frame):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
        source = directory / 'source_with_audio.mp4'
        ffmpeg('-i', original, '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
               '-map', '0:v:0', '-map', '1:a:0', '-t', float(count / rate),
               '-c:v', 'copy', '-c:a', 'aac', source)
        ffmpeg('-i', source, '-vf', 'fps=24,scale=256:144', '-c:v', 'libx264',
               '-preset', 'ultrafast', '-c:a', 'aac', directory / 'source.mp4')
        for name in ('mask.mp4', 'guide.mp4'):
            ffmpeg('-i', directory / 'source.mp4', '-c', 'copy', directory / name)
        details = dict(source=str(source), source_hash=digest(source), start=0,
                       duration=float(count / rate), selected_duration=float(count / rate),
                       frames=round(count / rate * 24), fps=24, full_source=True)
        project = recipe_fixture.Wan21RelightTests().project()
        project['source'] = {'file': str(source), 'sha': digest(source)}
        project['config'] = studio.clean_config({
            **project['config'], 'ae_frame_contract': contract(rate),
            'relight_shape': 'source', 'duration': 2,
        })
        loader, exporter = native_adapters(directory, details)
        yield directory, project, loader, exporter


class WanAESourceContractTests(unittest.TestCase):
    def prepared_graph(self, project):
        # Approval is a fixture, but graph construction, file probing and frame
        # contract preparation below are the production implementations.
        with patch.object(studio, 'assert_approved'), \
                patch.object(studio, 'check_asset', side_effect=lambda asset: Path(asset['file'])):
            return studio.build_graph(project, 'wan21_relight', use_cache=False)

    @staticmethod
    def export_inputs(graph):
        values = dict(graph['wan21_export']['inputs'])
        values.pop('video')
        values.pop('clip_details')
        return values

    def test_ae_cadence_native_working_raster_and_exact_final_file(self):
        for rate in (Fraction(25), Fraction(30000, 1001)):
            with self.subTest(fps=str(rate)), approved_source(rate) as (directory, project, loader, exporter):
                config = project['config']
                self.assertEqual(config['relight_shape'], 'source_size')
                self.assertAlmostEqual(config['duration'], float(9 / rate), places=12)
                graph = self.prepared_graph(project)
                self.assertEqual(graph['wan21_export']['inputs']['output_width'], 1920)
                self.assertEqual(graph['wan21_export']['inputs']['output_height'], 1080)
                self.assertEqual(graph['wan21_video']['inputs']['images'], ['wan21_hold_result', 0],
                                 'Native working frames must reach their own verified final exporter')
                self.assertFalse(any(node.get('class_type') == 'ZuraComfyLinkMatchFrames'
                                     for node in graph.values()),
                                 'An upstream source-raster matcher would reject the smaller working raster')
                native = loader.load(**graph['wan21_shot']['inputs'])
                decoded = inspect(native[0])
                self.assertEqual((decoded['fps'], decoded['frames']), (rate, 9))
                self.assertLess(decoded['width'], 1920)
                self.assertTrue(all(b - a > 10 for a, b in zip(decoded['levels'], decoded['levels'][1:])),
                                'The 24 fps review proxy must not replace original RGB frame cadence')
                padded = directory / 'generated_fixture_padded.mp4'
                ffmpeg('-i', native[0], '-vf', 'tpad=stop_mode=clone:stop=3', '-an',
                       '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', 0, padded)
                result = exporter.restore(str(padded), native[3], **self.export_inputs(graph))
                actual = inspect(result['result'][0])
                self.assertEqual((actual['width'], actual['height'], actual['frames'], actual['fps'], actual['audio']),
                                 (1920, 1080, 9, rate, 1))
                self.assertTrue(all(b - a > 10 for a, b in zip(actual['levels'], actual['levels'][1:])),
                                'The final export must retain all nine source-ordered generated frames')

    def test_native_export_rejects_wrong_cadence_count_source_and_short_generation(self):
        rate = Fraction(25)
        with approved_source(rate) as (directory, project, loader, exporter):
            graph = self.prepared_graph(project)
            native = loader.load(**graph['wan21_shot']['inputs'])
            values = self.export_inputs(graph)
            for changed in (contract(Fraction(24)), contract(rate, 8)):
                with self.subTest(contract=changed), self.assertRaisesRegex(ValueError, 'match all AE source frames'):
                    exporter.restore(native[0], native[3], **{**values, 'ae_frame_contract': json.dumps(changed)})
            short = directory / 'generated_fixture_short.mp4'
            ffmpeg('-i', native[0], '-frames:v', 8, '-an', '-c:v', 'libx264', '-preset', 'ultrafast', short)
            with self.assertRaisesRegex(ValueError, 'shorter than the AE source'):
                exporter.restore(str(short), native[3], **values)
            with self.assertRaisesRegex(ValueError, 'original source changed'):
                exporter.restore(native[0], {**native[3], 'source_hash': '0' * 64}, **values)
            self.assertFalse((directory / 'final').exists(), 'Rejected outputs must not create a final result')

    def test_only_ae_wan_relight_receives_source_cadence_and_source_sized_delivery(self):
        normal = studio.clean_config({'engine': 'h3', 'workflow_mode': 'relight',
                                      'duration': 3, 'relight_shape': 'source'})
        self.assertEqual((normal['duration'], normal['relight_shape']), (3, 'source'))
        self.assertNotIn('ae_frame_contract', normal)
        legacy = studio.clean_config({'engine': 'h3', 'workflow_mode': 'relight',
                                      'relight_engine': 'h3', 'ae_frame_contract': contract(Fraction(25))})
        self.assertEqual((legacy['relight_engine'], legacy['duration'], legacy['relight_shape']),
                         ('wan21', 9 / 25, 'source_size'), 'Cadence policy follows the resolved route after migration')
        with self.assertRaisesRegex(ValueError, '24 fps'):
            studio.clean_config({'engine': 'h3', 'workflow_mode': 'motion',
                                 'ae_frame_contract': contract(Fraction(25))})
        for count in (2, 751):
            with self.subTest(count=count), self.assertRaisesRegex(ValueError, '0.1.*30'):
                studio.clean_config({'engine': 'h3', 'workflow_mode': 'relight',
                                     'ae_frame_contract': contract(Fraction(25), count)})


if __name__ == '__main__':
    unittest.main()
