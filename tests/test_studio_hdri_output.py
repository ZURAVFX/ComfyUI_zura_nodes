"""Native HDRI export producer proof; actual CPU files, no Comfy model job."""
import hashlib
import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import OpenImageIO as oiio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from test_studio_image_layers import layers

routes_module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdri_routes')
outputs_module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.output_settings')


class NativeHDRIOutput(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.input, self.output = self.root / 'input', self.root / 'output'
        self.input.mkdir(); self.output.mkdir()
        self.original = self.input / 'native.exr'
        self.pixels = np.full((8, 16, 3), [.125, .25, 3.5], np.float32)
        spec = oiio.ImageSpec(16, 8, 3, oiio.FLOAT)
        spec.channelnames = ('R', 'G', 'B')
        spec.attribute('oiio:ColorSpace', 'ACEScg')
        writer = oiio.ImageOutput.create(str(self.original))
        self.assertTrue(writer.open(str(self.original), spec))
        self.assertTrue(writer.write_image(self.pixels)); writer.close()
        self.source_bytes = self.original.read_bytes()
        self.asset = dict(id='a' * 32, file='native.exr', sha=hashlib.sha256(self.source_bytes).hexdigest(), color_space='acescg')

        def load(identity):
            if identity != self.asset['id']:
                raise ValueError('Unknown owned HDRI source.')
            return self.asset

        def check(asset):
            path = self.input / asset['file']
            if hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha']:
                raise ValueError('The owned HDRI source changed.')
            return path

        def response(handler):
            async def wrapped(request):
                try:
                    return await handler(request)
                except (ValueError, OSError, KeyError, TypeError) as error:
                    return web.json_response({'error': str(error)}, status=400)
            return wrapped

        folder = types.SimpleNamespace(get_input_directory=lambda: str(self.input), get_output_directory=lambda: str(self.output))
        self.folder_patch = patch.dict(sys.modules, {'folder_paths': folder})
        self.folder_patch.start(); self.addCleanup(self.folder_patch.stop)
        table = web.RouteTableDef()
        routes_module.register(types.SimpleNamespace(store=types.SimpleNamespace(load=load)), table, response, check)
        app = web.Application(); app.add_routes(table)
        self.client = TestClient(TestServer(app)); await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_actual_native_export_binds_original_and_retains_float_hdr_pixels(self):
        response = await self.client.post('/zura/studio/hdri/export', json={
            'source_id': self.asset['id'], 'color_space': 'acescg', 'export_space': 'acescg',
            'yaw': 0, 'exposure': 0, 'lights': [], 'view_exposure': -6})
        self.assertEqual(response.status, 200, await response.text())
        result = await response.json()
        self.assertEqual(result['source_id'], self.asset['id'])
        self.assertEqual(result['source_sha256'], self.asset['sha'])
        self.assertTrue(result['source_hdr'])
        self.assertEqual(result['colour'], {'encoding': 'acescg', 'sceneLinear': True})
        self.assertEqual((result['sampleType'], result['bitDepth'], result['hasAlpha']), ('float32', 32, False))
        path = self.output / result['file']['subfolder'] / result['file']['filename']
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result['sha256'])
        reader = oiio.ImageInput.open(str(path)); spec = reader.spec()
        self.assertEqual(spec.format, oiio.FLOAT)
        self.assertEqual(tuple(spec.channelnames), ('R', 'G', 'B'))
        self.assertIn(str(spec.getattribute('oiio:ColorSpace')).lower(), {'acescg', 'lin_ap1_scene'})
        np.testing.assert_array_equal(reader.read_image(format=oiio.FLOAT), self.pixels)
        reader.close()
        self.assertEqual(self.original.read_bytes(), self.source_bytes)
        service = outputs_module.OutputSettings(self.output, self.root / 'settings')
        self.assertEqual(service.source_file(result['file']), path)

    async def test_unknown_or_modified_source_cannot_claim_native_hdr_identity(self):
        body = dict(source_id='b' * 32, source_hdr=True, color_space='acescg', export_space='acescg')
        response = await self.client.post('/zura/studio/hdri/export', json=body)
        self.assertEqual(response.status, 400)
        body['source_id'] = self.asset['id']; self.original.write_bytes(b'changed source')
        response = await self.client.post('/zura/studio/hdri/export', json=body)
        self.assertEqual(response.status, 400)


if __name__ == '__main__':
    unittest.main()
