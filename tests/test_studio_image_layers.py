"""Real, bounded image-layer recomposition without GPU inference or ComfyUI."""
import copy
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

import numpy as np
import OpenImageIO as oiio
from PIL import Image
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import v2_bootstrap

for name, directory in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'), ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(v2_bootstrap.ROOT / directory)]
        sys.modules[name] = package
layers = importlib.import_module('ComfyUI_zura_nodes.artist_studio.image_layers')
kernel = importlib.import_module('ComfyUI_zura_nodes.paintout.frame_layers')


class ImageLayersTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.roots = {kind: Path(self.temp.name) / kind for kind in ('input', 'output')}
        for root in self.roots.values(): root.mkdir()
        self.original = np.arange(8 * 12 * 3, dtype=np.uint8).reshape(8, 12, 3)
        self.candidate = np.full((8, 12, 3), [230, 40, 80], dtype=np.uint8)
        self.mask = np.zeros((8, 12), dtype=np.uint8)
        self.mask[2:6, 4:8] = 255
        self.source = self.png('source.png', self.original, 'input')
        self.file = self.png('layer.png', self.candidate)
        self.selection = self.png('mask.png', self.mask, 'input')
        self.body = dict(schemaVersion=1, source=self.source, source_colour='srgb_display', width=12, height=8,
                         layers=[dict(id='layer-1', file=self.file, mask=self.selection, colour_space='srgb_display', enabled=True)])

    def tearDown(self): self.temp.cleanup()

    def png(self, name, pixels, kind='output'):
        Image.fromarray(pixels).save(self.roots[kind] / name)
        return dict(filename=name, subfolder='', type=kind)

    def path(self, ref): return self.roots[ref['type']] / ref['subfolder'] / ref['filename']

    def pixels(self, ref, shape=(8, 12)): return layers._pixels(self.path(ref), shape)

    def assert_rgb_master(self, ref):
        reader=oiio.ImageInput.open(str(self.path(ref)))
        try:
            spec=reader.spec()
            self.assertEqual(spec.nchannels,3)
            self.assertEqual(tuple(spec.channelnames),('R','G','B'))
            self.assertEqual(spec.alpha_channel,-1)
        finally:reader.close()

    def test_real_float_master_exact_outside_mask_and_separate_sdr8_preview(self):
        before = self.path(self.source).read_bytes()
        result = layers.compose(self.body, self.roots)
        actual = self.pixels(result['master'])
        expected = self.pixels(self.source)
        expected[self.mask > 0] = self.pixels(self.file)[self.mask > 0]
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(self.path(self.source).read_bytes(), before)
        reader = oiio.ImageInput.open(str(self.path(result['master'])))
        spec = reader.spec()
        self.assertEqual(spec.format, oiio.FLOAT)
        self.assertIn(spec.getattribute('oiio:ColorSpace'), ('sRGB', 'srgb_rec709_scene'))
        self.assertEqual(spec.getattribute('zura:dynamicRange'), 'SDR')
        reader.close()
        self.assertEqual(result['dynamicRange'], 'SDR')
        self.assertFalse(result['hasAlpha'])
        self.assertNotIn('alphaAssociation',result)
        self.assert_rgb_master(result['master'])
        self.assertEqual(result['colour'], {'encoding': 'srgb_display', 'sceneLinear': False})
        self.assertNotEqual(result['master']['filename'], result['preview']['filename'])
        self.assertEqual(result['master']['sha256'], layers._identity(self.path(result['master']))[1])

    def test_reorder_visibility_delete_all_and_original_source_hash_pin(self):
        first = layers.compose(self.body, self.roots)
        self.body['expected_source_sha256'] = first['source_sha256']
        second = self.png('second.png', np.full_like(self.original, 80))
        self.body['layers'].append(dict(id='layer-2', file=second, mask=None, colour_space='srgb_display', enabled=True, opacity=.5))
        forward = self.pixels(layers.compose(self.body, self.roots)['master'])
        self.body['layers'].reverse()
        reverse = self.pixels(layers.compose(self.body, self.roots)['master'])
        self.assertFalse(np.array_equal(forward, reverse))
        for layer in self.body['layers']: layer['enabled'] = False
        restored = self.pixels(layers.compose(self.body, self.roots)['master'])
        np.testing.assert_array_equal(restored, self.pixels(self.source))
        self.body['layers'] = []
        cleared=layers.compose(self.body,self.roots)
        np.testing.assert_array_equal(self.pixels(cleared['master']), restored)
        self.assert_rgb_master(cleared['master'])
        self.png('source.png', np.zeros_like(self.original), 'input')
        with self.assertRaisesRegex(ValueError, 'original image changed'):
            layers.compose(self.body, self.roots)
        self.assertTrue(self.path(first['master']).is_file())

    def test_controls_reuse_kernel_once_and_delivery_resize_is_last(self):
        self.body['layers'][0].update(opacity=.4, expand_pixels=1, blend_pixels=2, brightness_ev=.5)
        self.body['delivery'] = dict(width=6, height=4)
        result = layers.compose(self.body, self.roots)
        canonical = self.pixels(result['canonicalMaster'])
        expected = kernel.compose_pixels(self.pixels(self.source),
            [(self.pixels(self.file), self.mask.astype(np.float32)/255, 2, .5, .4, 1)], linear=False)
        np.testing.assert_array_equal(canonical, expected)
        np.testing.assert_array_equal(self.pixels(result['master'], (4, 6)), layers._resize(expected, 6, 4))
        self.assert_rgb_master(result['master'])
        self.assert_rgb_master(result['canonicalMaster'])
        self.assertEqual((result['sourceWidth'], result['sourceHeight']), (12, 8))
        self.assertEqual((result['width'], result['height']), (6, 4))

    def test_invalid_paths_types_geometry_colour_alpha_and_nonfinite_rejected(self):
        for change in ('traversal', 'absolute', 'temp', 'extra-ref', 'duplicate', 'invalid-control', 'boolean-size', 'crop', 'hdr', 'hdr-exr', 'alpha', 'nonfinite'):
            with self.subTest(change=change):
                body = copy.deepcopy(self.body)
                if change == 'traversal': body['source']['subfolder'] = '../input'
                elif change == 'absolute': body['source']['filename'] = 'C:/source.png'
                elif change == 'temp': body['source']['type'] = 'temp'
                elif change == 'extra-ref': body['source']['path'] = str(self.path(self.source))
                elif change == 'duplicate': body['layers'].append(copy.deepcopy(body['layers'][0]))
                elif change == 'invalid-control': body['layers'][0]['opacity'] = float('nan')
                elif change == 'boolean-size': body['width'] = True
                elif change == 'crop': body['width'] = 11
                elif change == 'hdr': body['source_colour'] = 'acescg'
                elif change in {'hdr-exr', 'nonfinite'}:
                    pixels = self.candidate.astype(np.float32)/255
                    if change == 'nonfinite': pixels[0, 0, 0] = float('nan')
                    ref = dict(filename=change+'.exr', subfolder='', type='output')
                    layers._write_master(self.path(ref), pixels)
                    if change == 'hdr-exr':
                        # Write a genuine linear-tagged EXR which must not be relabelled sRGB.
                        spec = oiio.ImageSpec(12, 8, 3, oiio.FLOAT); spec.channelnames=('R','G','B'); spec.attribute('oiio:ColorSpace','ACEScg')
                        writer=oiio.ImageOutput.create(str(self.path(ref))); self.assertTrue(writer.open(str(self.path(ref)),spec));self.assertTrue(writer.write_image(pixels));writer.close()
                    body['layers'][0]['file'] = ref
                elif change == 'alpha': body['layers'][0]['file'] = self.png('alpha.png', np.zeros((8,12,4),np.uint8))
                with self.assertRaises((ValueError, OSError)):
                    layers.compose(body, self.roots)

    def test_mutation_during_composition_keeps_previous_result(self):
        first = layers.compose(self.body, self.roots)
        original_kernel = kernel.compose_pixels
        def mutate(*args, **kwargs):
            result = original_kernel(*args, **kwargs)
            self.png('source.png', np.zeros_like(self.original), 'input')
            return result
        with patch.object(kernel, 'compose_pixels', mutate), self.assertRaisesRegex(ValueError, 'changed while composing'):
            layers.compose(self.body, self.roots)
        self.assertTrue(self.path(first['master']).is_file())

    def test_float_sdr_values_are_retained_without_claiming_hdr_generation(self):
        pixels = self.pixels(self.source)
        pixels[0,0] = [-.125, 2.5, .18]
        source = dict(filename='float-source.exr', subfolder='', type='input')
        layers._write_master(self.path(source), pixels)
        self.body['source'] = source
        result = layers.compose(self.body, self.roots)
        np.testing.assert_array_equal(self.pixels(result['master'])[0,0], pixels[0,0])
        self.assertEqual(result['dynamicRange'], 'SDR')
        self.assertFalse(result['colour']['sceneLinear'])
        shown=np.asarray(Image.open(self.path(result['preview'])))
        np.testing.assert_array_equal(shown[0,0], [0,255,46])

    def test_hard_link_source_is_rejected_before_output_publication(self):
        import os
        linked=self.roots['input']/'other.png'
        os.link(self.path(self.source),linked)
        with self.assertRaisesRegex(ValueError,'unchanged image'):
            layers.compose(self.body,self.roots)


class ImageLayerRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_awaiter_does_not_release_a_running_workers_lock(self):
        started, finish = threading.Event(), threading.Event()
        def work(*_):
            started.set()
            if not finish.wait(3):raise RuntimeError('test worker was not released')
            return {}
        with patch.object(layers,'compose',work):
            task=asyncio.create_task(asyncio.to_thread(layers._compose_locked,{},{}))
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
            self.assertTrue(layers._writer.locked())
            finish.set()
            for _ in range(100):
                if not layers._writer.locked():break
                await asyncio.sleep(.005)
            self.assertFalse(layers._writer.locked())

    async def test_origin_and_body_cap_and_busy_do_not_start_composition(self):
        routes=web.RouteTableDef();layers.register(routes);app=web.Application(client_max_size=layers.MAX_BODY*2);app.add_routes(routes)
        async with TestClient(TestServer(app)) as client:
            response=await client.post('/zura/studio/image-layers/compose',json={},headers={'Origin':'https://another.invalid'})
            self.assertEqual(response.status,403)
            response=await client.post('/zura/studio/image-layers/compose',data=b' '* (layers.MAX_BODY+1))
            self.assertEqual(response.status,400)
            self.assertTrue(layers._writer.acquire(blocking=False))
            try:
                response=await client.post('/zura/studio/image-layers/compose',json={})
                self.assertEqual(response.status,409)
            finally:layers._writer.release()


if __name__ == '__main__': unittest.main()
