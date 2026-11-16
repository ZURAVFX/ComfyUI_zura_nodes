"""Explicit numeric 8-bit transport through the normal asset loader. CPU only."""
import copy
import hashlib
import json
import sys
import tempfile
import time
import types
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink import float_io
from comfylink.studio_processing import validate_processing_input, model_input_processor, encode_sdr8
from comfylink.studio_sessions import StudioSessions, _require_raw_numeric_video_info


def authority(manifest):
    return {'schemaVersion': 1, 'precision': 8, 'conversion': 'raw_numeric_to_sdr8',
            'sourceProcessingPrecision': 'sdr8', 'samplePolicy': 'clamp_round_unorm8',
            'colourAssignment': 'numeric_sdr8_code_values',
            'sourceManifestSha256': hashlib.sha256(float_io.canonical_manifest_bytes(manifest)).hexdigest(),
            'sourceColour': copy.deepcopy(manifest['colour']),
            'colour': {'encoding': 'srgb_display', 'sceneLinear': False}, 'alphaAssociation': 'straight'}


def icc_colour(profile):
    return {'encoding': 'ae_project_icc', 'sceneLinear': True, 'management': 'icc',
            'profileDescription': 'Fixture linear RGB working profile',
            'profileSha256': hashlib.sha256(profile).hexdigest()}


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        rgba = np.array([[[[-.25, .18, 1.25, .5]]]], dtype=np.float32)
        _, self.manifest = float_io.write_transfer(self.root, 'ComfyLink/' + 'c' * 32, rgba,
            colour=icc_colour(b'profile identity'), frame_rate={'numerator': 24, 'denominator': 1})

    def test_explicit_numeric_authority_never_constructs_colour_processor(self):
        declared = authority(self.manifest)
        self.assertEqual(validate_processing_input(declared, self.manifest), declared)
        with patch('comfylink.display_view._config', side_effect=AssertionError('No colour transform permitted')):
            self.assertIsNone(model_input_processor(declared))
        original = np.array([[[-.25, .18, 1.25, .5]]], dtype=np.float32)
        before = original.view(np.uint32).copy()
        actual = encode_sdr8(original, derived=True, processor=model_input_processor(declared))
        np.testing.assert_array_equal(actual, [[[0, 46, 255, 128]]])
        np.testing.assert_array_equal(original.view(np.uint32), before)

    def test_authority_rejects_wrong_precision_identity_and_policy(self):
        declared = authority(self.manifest)
        patches = [{'precision': True}, {'precision': 16}, {'sourceProcessingPrecision': 'float32'},
                   {'sourceProcessingPrecision': 'prores12'}, {'samplePolicy': 'gamma_to_srgb'},
                   {'sourceManifestSha256': '0' * 64}, {'sourceEncoding': 'srgb8'},
                   {'sourceConfigSha256': 'a' * 64}, {'colourAssignment': 'verified_srgb_conversion'},
                   {'colour': {'encoding': 'unknown', 'sceneLinear': False}}]
        for value in patches:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_processing_input({**declared, **value}, self.manifest)
        for key in ('sourceProcessingPrecision', 'samplePolicy', 'colourAssignment'):
            broken = copy.deepcopy(declared); del broken[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                validate_processing_input(broken, self.manifest)
        broken = copy.deepcopy(declared); broken['sourceColour']['sceneLinear'] = False
        with self.assertRaises(ValueError): validate_processing_input(broken, self.manifest)
        for key, value in (('sourceBitDepth', 8), ('sampleType', 'uint16_ae'), ('alphaAssociation', 'premultiplied')):
            altered = {**self.manifest, key: value}
            with self.subTest(manifest=key), self.assertRaises(ValueError):
                validate_processing_input(authority(altered), altered)

    def test_normal_clip_requires_registered_editor_and_player_inputs(self):
        root = self.root / 'normal-input'; root.mkdir()
        clip = root / 'reference.mkv'; clip.write_bytes(b'fixture clip')
        asset = {'file': 'reference.mkv', 'preview_file': 'genj_studio/preview.mp4',
                 'preview_status': 'ready',
                 'preview_url': '/view?filename=preview.mp4&subfolder=genj_studio&type=input'}
        manifest = {'width': 512, 'height': 320, 'frameRate': {'numerator': 30000, 'denominator': 1001},
                    'frames': [{} for _ in range(17)]}
        info = {'path': str(clip), 'kind': 'video', 'width': 512, 'height': 320,
                'frames': 17, 'fps': 30000 / 1001, 'duration': 17 * 1001 / 30000}
        self.assertIs(_require_raw_numeric_video_info(asset, info, manifest, root), info)
        for broken in (None, {**info, 'path': str(root / 'other.mkv')},
                       {**info, 'frames': 16}, {**info, 'fps': 24}, {**info, 'width': 511},
                       {**info, 'duration': 2}, {**info, 'kind': 'image'}):
            with self.subTest(info=broken), self.assertRaises((ValueError, OSError)):
                _require_raw_numeric_video_info(asset, broken, manifest, root)
        for broken in ({**asset, 'preview_status': 'preparing'},
                       {**asset, 'preview_url': 'https://example.com/preview.mp4'},
                       {**asset, 'file': '../reference.mkv'}):
            with self.subTest(asset=broken), self.assertRaises((ValueError, OSError)):
                _require_raw_numeric_video_info(broken, info, manifest, root)


class NormalAssetTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_17_frame_numeric_clip_uses_normal_lossless_asset_and_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); inputs = root / 'input'; outputs = root / 'output'
            inputs.mkdir(); outputs.mkdir()
            width, height, count = 512, 320, 17
            yy, xx = np.mgrid[:height, :width]
            def source_frame(index):
                frame = np.ones((height, width, 4), dtype=np.float32)
                frame[..., 0] = xx / np.float32(width) * np.float32(1.2) - np.float32(.1)
                frame[..., 1] = yy / np.float32(height) * np.float32(.9) + np.float32(index / 300)
                frame[..., 2] = ((xx * 3 + yy * 5 + index) % 256) / np.float32(255)
                frame[:, 0, 3] = 0; frame[:, 1, 3] = np.float32(.5)
                return frame
            profile = bytearray(128); profile[:4] = (128).to_bytes(4, 'big'); profile[36:40] = b'acsp'
            relative, manifest = float_io.write_transfer_frames(inputs, 'ComfyLink/' + 'f' * 32,
                (source_frame(index) for index in range(count)), colour=icc_colour(profile),
                frame_rate={'numerator': 30000, 'denominator': 1001}, source_bit_depth=32, expected_count=count)
            folder = inputs / Path(relative).parent
            (folder / 'source.icc').write_bytes(profile)
            (folder / 'processing-input.json').write_bytes(float_io.canonical_manifest_bytes(authority(manifest)))
            before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in folder.iterdir()}
            uploaded = inputs / 'genj_studio' / ('e' * 32) / 'reference.mkv'
            uploaded.parent.mkdir(parents=True)
            preview_file = uploaded.with_name('preview.mp4')
            asset = {}
            calls = []
            async def upload(request):
                self.assertEqual(request.query.get('kind'), 'video')
                part = await (await request.multipart()).next()
                self.assertEqual(part.filename, 'source.mkv')
                with uploaded.open('xb') as destination:
                    while chunk := await part.read_chunk(): destination.write(chunk)
                with av.open(str(uploaded)) as media:
                    stream = media.streams.video[0]
                    self.assertEqual(stream.codec_context.name, 'ffv1')
                    self.assertEqual(stream.codec_context.colorspace, 0)
                    self.assertEqual(stream.codec_context.color_range, 2)
                    self.assertEqual(stream.codec_context.color_trc, 13)
                    self.assertEqual(stream.codec_context.color_primaries, 1)
                    self.assertEqual(stream.average_rate, Fraction(30000, 1001))
                    decoded = list(media.decode(video=0))
                    self.assertEqual(len(decoded), count)
                    for index, frame in enumerate(decoded):
                        expected = np.rint(np.clip(source_frame(index), 0, 1) * 255).astype(np.uint8)
                        np.testing.assert_array_equal(frame.to_ndarray(format='rgba'), expected)
                        # Matroska stores millisecond packet timestamps. The
                        # nominal rational rate and all source frames survive;
                        # packets round to the nearest half millisecond.
                        self.assertLessEqual(abs(Fraction(frame.pts) * frame.time_base - Fraction(index * 1001, 30000)), Fraction(1, 2000))
                asset.update(id='e' * 32, kind='asset', asset_kind='video', file=uploaded.relative_to(inputs).as_posix(),
                    sha=hashlib.sha256(uploaded.read_bytes()).hexdigest(), video_codec='ffv1',
                    preview_file=preview_file.relative_to(inputs).as_posix(), preview_status='preparing')
                return web.json_response(asset)
            async def preview(request):
                calls.append('preview')
                # The normal uploader owns proxy creation; this boundary test
                # checks registered preview readiness without replacing master.
                return web.json_response({**asset, 'preview_status': 'ready',
                    'preview_url': '/view?filename=preview.mp4&subfolder=genj_studio/' + 'e' * 32 + '&type=input'})
            async def info(request):
                return web.json_response({'path': str(uploaded), 'kind': 'video', 'width': width, 'height': height,
                    'frames': count, 'fps': 30000 / 1001, 'media_url': '/lossless-original'})
            app = web.Application()
            app.router.add_post('/zura/studio/upload', upload)
            app.router.add_get('/zura/studio/assets/' + 'e' * 32 + '/preview', preview)
            app.router.add_post('/zura/studio/assets/' + 'e' * 32 + '/ripple', info)
            server = TestServer(app, host='127.0.0.1'); await server.start_server()
            try:
                service = object.__new__(StudioSessions); service.roots = lambda: (inputs, outputs)
                session = types.SimpleNamespace(id='f' * 32, origin=str(server.make_url('/')).rstrip('/'),
                    closed=False, expires=time.time() + 600)
                service.sessions = {session.id: session}
                with patch.object(float_io, 'load_transfer', side_effect=AssertionError('Whole batch forbidden')):
                    result = await service.native_import(session, folder, manifest)
                self.assertEqual(calls, ['preview'])
                self.assertEqual(result['studioAsset']['file'], asset['file'])
                self.assertEqual(result['studioAsset']['sha'], asset['sha'])
                self.assertEqual(result['mediaInfo']['path'], str(uploaded))
                self.assertIn('preview.mp4', result['mediaInfo']['media_url'])
                self.assertEqual(result['mediaInfo']['frames'], count)
                self.assertEqual(result['studioAsset']['preview_status'], 'ready')
                for key, index in (('first', 0), ('last', 16)):
                    with Image.open(inputs / result['stills'][key]['file']) as image:
                        np.testing.assert_array_equal(np.array(image), np.rint(np.clip(source_frame(index), 0, 1) * 255).astype(np.uint8))
                for name, expected in before.items():
                    self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), expected)
            finally:
                await server.close()


if __name__ == '__main__': unittest.main()
