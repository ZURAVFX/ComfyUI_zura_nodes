"""Real file-format/colour proof; HTTP and HDR coordinator fixtures use no GPU."""
import importlib
import json
import os
from pathlib import Path
import sys
import stat
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
import OpenImageIO as oiio
from PIL import Image, ImageCms
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from test_studio_image_layers import layers

export = importlib.import_module('ComfyUI_zura_nodes.artist_studio.image_export')
hdr = importlib.import_module('ComfyUI_zura_nodes.artist_studio.image_export_hdr')
outputs = importlib.import_module('ComfyUI_zura_nodes.artist_studio.output_settings')
HDRJobs = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_jobs').HDRJobs


class ImageExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.roots = {kind: self.root / kind for kind in ('input', 'output')}
        for root in self.roots.values():
            root.mkdir()
        self.source = self.png('original.png', np.arange(4 * 6 * 3, dtype=np.uint8).reshape(4, 6, 3), 'input')
        layer = self.png('edit.png', np.full((4, 6, 3), [241, 130, 61], np.uint8))
        self.result = layers.compose(dict(schemaVersion=1, source=self.source, source_colour='srgb_display', width=6, height=4,
                                         layers=[dict(id='edit', file=layer, colour_space='srgb_display', enabled=True, opacity=.375)]), self.roots)
        self.master = self.clean(self.result['master'])
        self.service = outputs.OutputSettings(self.roots['output'], self.root / 'settings')

    def tearDown(self):
        self.temporary.cleanup()

    def png(self, filename, pixels, kind='output', folder='genj/studio_images', **options):
        path = self.roots[kind] / folder / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(pixels).save(path, **options)
        return dict(filename=filename, subfolder=folder, type=kind)

    def path(self, ref):
        return self.roots[ref['type']] / ref['subfolder'] / ref['filename']

    @staticmethod
    def clean(ref):
        return {key: ref[key] for key in ('filename', 'subfolder', 'type')}

    def request(self, format='png8', asset=None):
        return export.export_image(dict(asset=asset or self.master, format=format), self.roots['output'])

    def test_real_formats_quantisation_profiles_and_originals_unchanged(self):
        before = {path: path.read_bytes() for path in self.path(self.master).parent.iterdir()}
        pixels = layers._pixels(self.path(self.master), (4, 6))
        for format, bits, storage in (('png8', 8, oiio.UINT8), ('png16', 16, oiio.UINT16), ('tiff16', 16, oiio.UINT16), ('exr_float', 32, oiio.FLOAT)):
            with self.subTest(format=format):
                result = self.request(format)
                path = self.path(result['file'])
                reader = oiio.ImageInput.open(str(path))
                spec = reader.spec()
                actual = reader.read_image(format=storage)
                self.assertEqual(spec.format, storage)
                self.assertEqual(tuple(spec.channelnames), ('R', 'G', 'B'))
                self.assertEqual(spec.alpha_channel, -1)
                reader.close()
                expected = pixels if bits == 32 else np.round(np.clip(pixels, 0, 1) * (2 ** bits - 1)).astype(np.uint8 if bits == 8 else np.uint16)
                np.testing.assert_array_equal(actual, expected)
                self.assertEqual(result['bitDepth'], bits)
                self.assertEqual(result['sourceBitDepth'], 32)
                self.assertEqual(result['dynamicRange'], 'SDR')
                self.assertEqual(result['colour'], {'encoding': 'srgb_display', 'sceneLinear': False})
                self.assertFalse(result['hasAlpha'])
                if bits != 32:
                    with Image.open(path) as image:
                        profile = ImageCms.ImageCmsProfile(__import__('io').BytesIO(image.info['icc_profile']))
                        self.assertIn('srgb', ImageCms.getProfileDescription(profile).lower())
                self.assertEqual(self.service.source_file(result['file']), path)
                saved = Path(self.service.export([result['file']])[0])
                self.assertEqual(saved.read_bytes(), path.read_bytes())
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_normal_eight_bit_source_stays_truthful_and_can_be_reexported(self):
        source = self.png('generated.png', np.full((4, 6, 3), [10, 50, 230], np.uint8))
        original = self.path(source).read_bytes()
        first = self.request('png16', source)
        self.assertEqual(first['sourceBitDepth'], 8)
        self.assertEqual(first['bitDepth'], 16)
        self.assertEqual(first['precisionPolicy'], 'file_storage_only_no_precision_added')
        second = self.request('png8', first['file'])
        np.testing.assert_array_equal(np.asarray(Image.open(self.path(second['file']))), np.full((4, 6, 3), [10, 50, 230], np.uint8))
        self.assertEqual(self.path(source).read_bytes(), original)

    def test_actual_native_saveimage_prefix_is_exportable_without_parent_whitelist(self):
        source = self.png('flux3_00001_.png', np.full((4, 6, 3), [30, 80, 170], np.uint8), folder='ZURA STUDIO/images')
        result = self.request('png8', source)
        self.assertEqual(result['sourceBitDepth'], 8)
        self.assertEqual(self.service.source_file(source), self.path(source))
        for asset in ({**source, 'subfolder': 'ZURA STUDIO/images/private'}, {**source, 'filename': 'private.exr'}, {**source, 'subfolder': 'ZURA STUDIO/unknown'}):
            self.assertIsNone(self.service.source_file(asset))

    def test_embedded_srgb_icc_is_physically_read_and_storage_is_explicit(self):
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        pixels = np.full((4, 6, 3), [40, 120, 230], np.uint8)
        source = self.png('profiled.png', pixels, icc_profile=profile)
        result = self.request('png8', source)
        np.testing.assert_array_equal(np.asarray(Image.open(self.path(result['file']))), pixels)
        with patch.object(export, 'MAX_PIXELS', 16), self.assertRaisesRegex(ValueError, 'source-sized'):
            self.request('png8', source)

    def test_strict_product_allowlist_and_receipt_tamper(self):
        self.assertEqual(self.service.source_file(self.master), self.path(self.master))
        self.assertEqual(self.service.source_file(self.clean(self.result['preview'])), self.path(self.result['preview']))
        fake = self.png('unreceipted.png', np.zeros((4, 6, 3), np.uint8), folder='ZURA STUDIO/image-layers/' + 'a' * 32)
        self.assertIsNone(self.service.source_file(fake))
        result = self.request('png8')
        self.path(result['file']).write_bytes(b'changed after verification')
        self.assertIsNone(self.service.source_file(result['file']))
        with self.assertRaises(ValueError):
            self.request('png8', result['file'])

    def test_invalid_sources_colour_alpha_nonfinite_and_references(self):
        transparent = np.ones((4, 6, 4), np.uint8) * 255
        transparent[0, 0, 3] = 0
        alpha = self.png('transparent.png', transparent)
        bad_icc = self.png('bad-icc.png', np.zeros((4, 6, 3), np.uint8), icc_profile=b'invalid ICC')
        for asset in (alpha, bad_icc, {**self.master, 'filename': '../master.exr'}, {**self.master, 'subfolder': '../output'}, {**self.master, 'type': 'input'}, {**self.master, 'colour': 'sdr'}):
            with self.subTest(asset=asset), self.assertRaises((ValueError, OSError, RuntimeError)):
                self.request('png8', asset)
        reader = oiio.ImageInput.open(str(self.path(self.master)))
        pixels = reader.read_image(format=oiio.FLOAT)
        reader.close()
        pixels[0, 0, 0] = np.nan
        layers._write_master(self.path(self.master), pixels)
        receipt = self.path(self.master).parent / 'image-layers.json'
        value = json.loads(receipt.read_text())
        for artifact in value['artifacts']:
            if artifact['filename'] == self.master['filename']:
                artifact['sha256'] = layers._identity(self.path(self.master))[1]
                artifact['byteLength'] = self.path(self.master).stat().st_size
        receipt.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'float samples'):
            self.request('png16')

    def test_linked_image_and_source_change_during_export_reject(self):
        linked = self.roots['output'] / 'genj' / 'studio_images' / 'linked.png'
        try:
            linked.symlink_to(self.path(self.result['preview']))
        except OSError as error:
            self.skipTest(str(error))
        with self.assertRaisesRegex(ValueError, 'outside|Linked'):
            self.request('png8', dict(filename=linked.name, subfolder='genj/studio_images', type='output'))
        original_write = export._write
        def changed(*args):
            result = original_write(*args)
            self.path(self.master).write_bytes(b'changed during write')
            return result
        with patch.object(export, '_write', side_effect=changed), self.assertRaisesRegex(ValueError, 'original image changed'):
            self.request('png8')
        parent = self.roots['output'] / 'ZURA STUDIO' / 'image-exports'
        self.assertFalse(list(parent.iterdir()))

    def hdr_fixture(self, *, bits=32, state='complete', colour='ACEScg', entries=1):
        job_id = 'c' * 32
        destination = self.roots['output'] / 'genj' / 'hdr' / ('sdr_' + job_id + '.zip')
        destination.parent.mkdir(parents=True, exist_ok=True)
        original = self.root / 'hdr.exr'
        pixels = np.full((4, 6, 3), [-.125, .18, 4.5], np.float32)
        spec = oiio.ImageSpec(6, 4, 3, oiio.FLOAT if bits == 32 else oiio.HALF)
        spec.channelnames = ('R', 'G', 'B')
        spec.attribute('oiio:ColorSpace', colour)
        spec.attribute('chromaticities', oiio.TypeDesc('float[8]'), hdr._AP1)
        writer = oiio.ImageOutput.create(str(original))
        self.assertTrue(writer.open(str(original), spec))
        self.assertTrue(writer.write_image(pixels))
        writer.close()
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.write(original, 'frame_00000.exr')
            if entries != 1:
                archive.writestr('extra.txt', 'not a still archive')
        asset = dict(filename=destination.name, subfolder='genj/hdr', type='output')
        source = self.master
        job = types.SimpleNamespace(store=types.SimpleNamespace(planning_mode='sdr', plan=[types.SimpleNamespace(count=1)]))
        job.snapshot = lambda: dict(state=state, result=dict(frames=1, files=[str(destination)]))
        jobs = HDRJobs()
        request = dict(mode='sdr', source_kind='output_image', frame_count=1, output_ref=source)
        pin = hdr.capture_still_source(request, self.roots['output'])
        model_pin = hdr.snapshot_still_model({'asset_kind': 'sdr_image'}, lambda asset: self.path(self.result['preview']), pin, self.roots['output'])
        jobs.jobs[job_id] = (job, dict(id=job_id, frames=1, width=6, height=4, exr_storage='float32' if bits == 32 else 'half', sourceMaster=pin, modelInput=model_pin))
        service = types.SimpleNamespace(jobs=jobs, _requests={'r' * 32: dict(id=job_id, fingerprint=json.dumps(request))})
        body = dict(asset=asset, format='hdr_exr', jobId=job_id, source=source)
        return service, body, original

    def hdr_alias_file(self, aliases):
        path = self.root / 'producer-alias.exr'
        spec = oiio.ImageSpec(6, 4, 3, oiio.FLOAT)
        spec.channelnames = ('R', 'G', 'B')
        spec.attribute('chromaticities', oiio.TypeDesc('float[8]'), hdr._AP1)
        for name, value in aliases.items():
            spec.attribute(name, value)
        writer = oiio.ImageOutput.create(str(path))
        self.assertTrue(writer.open(str(path), spec))
        self.assertTrue(writer.write_image(np.full((4, 6, 3), [-.125, .18, 4.5], np.float32)))
        writer.close()
        return path

    def test_hdr_real_producer_colorSpace_only_alias_is_valid(self):
        path = self.hdr_alias_file({'colorSpace': 'ACEScg'})
        reader = oiio.ImageInput.open(str(path))
        spec = oiio.ImageSpec(reader.spec())
        reader.close()
        self.assertIsNone(spec.getattribute('oiio:ColorSpace'))
        self.assertEqual(spec.getattribute('colorSpace'), 'ACEScg')
        self.assertIsNone(spec.getattribute('colorInteropID'))
        before = path.read_bytes()
        self.assertEqual(hdr._header(path), (6, 4, 32))
        self.assertEqual(path.read_bytes(), before, 'Validation must not retag the producer output')

    def test_hdr_all_present_standard_colour_aliases_must_agree(self):
        for aliases in ({'colorInteropID': 'lin_ap1_scene'},
                        {'oiio:ColorSpace': 'ACEScg', 'colorSpace': 'ACES - ACEScg', 'colorInteropID': 'lin_ap1_scene'}):
            with self.subTest(accepted=aliases):
                self.assertEqual(hdr._header(self.hdr_alias_file(aliases)), (6, 4, 32))
        for aliases in ({}, {'colorSpace': ''}, {'colorSpace': 'unknown'}, {'colorSpace': 'sRGB'},
                        {'oiio:ColorSpace': 'ACEScg', 'colorSpace': 'sRGB'},
                        {'oiio:ColorSpace': 'sRGB', 'colorSpace': 'ACEScg'},
                        {'colorSpace': 'ACEScg', 'colorInteropID': 'srgb_rec709_scene'},
                        {'colorSpace': 'ACEScg', 'colorInteropID': 'unknown'}, {'colorSpace': 17}):
            with self.subTest(rejected=aliases), self.assertRaisesRegex(ValueError, 'verified RGB HALF/FLOAT ACEScg'):
                hdr._header(self.hdr_alias_file(aliases))

    def test_hdr_owned_one_frame_job_verifies_actual_exr_and_reuses_durable_product(self):
        service, body, original = self.hdr_fixture()
        source_before = self.path(self.master).read_bytes()
        result = hdr.export_hdr_image(body, self.roots['output'], service)
        self.assertTrue(result['verifiedHDR'])
        self.assertEqual(result['hdrJobId'], body['jobId'])
        self.assertEqual(result['dynamicRange'], 'HDR')
        self.assertEqual(result['colour'], {'encoding': 'acescg', 'sceneLinear': True})
        self.assertEqual(result['bitDepth'], 32)
        self.assertEqual(self.path(result['file']).read_bytes(), original.read_bytes())
        self.assertEqual(self.service.source_file(result['file']), self.path(result['file']))
        self.assertEqual(self.path(self.master).read_bytes(), source_before)
        recovered = hdr.export_hdr_image({**body, 'asset': result['file']}, self.roots['output'], None)
        self.assertEqual(recovered['sha256'], result['sha256'])
        with self.assertRaisesRegex(ValueError, 'silently tone-map'):
            self.request('png8', result['file'])

    def test_hdr_rejects_unknown_incomplete_wrong_source_extra_files_and_sdr_tags(self):
        for kind in ('unknown', 'incomplete', 'wrong-source', 'extra-files', 'sdr-tags', 'wrong-mode', 'multiple-frames'):
            with self.subTest(kind=kind):
                service, body, _ = self.hdr_fixture(state='rendering' if kind == 'incomplete' else 'complete', colour='sRGB' if kind == 'sdr-tags' else 'ACEScg', entries=2 if kind == 'extra-files' else 1)
                if kind == 'unknown':
                    service = None
                elif kind == 'wrong-source':
                    body['source'] = self.clean(self.result['preview'])
                elif kind in ('wrong-mode', 'multiple-frames'):
                    job = service.jobs.jobs[body['jobId']][0]
                    if kind == 'wrong-mode':
                        job.store.planning_mode = 'native'
                    else:
                        job.store.plan[0].count = 2
                with self.assertRaises(ValueError):
                    hdr.export_hdr_image(body, self.roots['output'], service)

    def test_hdr_receipt_and_actual_file_tamper_never_ready(self):
        service, body, _ = self.hdr_fixture()
        result = hdr.export_hdr_image(body, self.roots['output'], service)
        self.path(result['file']).write_bytes(b'not an HDR image')
        self.assertIsNone(self.service.source_file(result['file']))
        with self.assertRaises(ValueError):
            hdr.export_hdr_image({**body, 'asset': result['file']}, self.roots['output'], None)

    def test_half_hdr_is_not_mislabelled_as_float_and_preview_cannot_substitute(self):
        service, body, original = self.hdr_fixture(bits=16)
        result = hdr.export_hdr_image(body, self.roots['output'], service)
        self.assertEqual((result['bitDepth'], result['sampleType']), (16, 'float16'))
        self.assertEqual(self.path(result['file']).read_bytes(), original.read_bytes())
        with self.assertRaises(ValueError):
            hdr.export_hdr_image({**body, 'asset': self.clean(self.result['preview'])}, self.roots['output'], service)

    def test_hdr_admitted_source_content_pin_rejects_same_path_replacement_and_legacy(self):
        service, body, _ = self.hdr_fixture()
        original = self.path(self.master).read_bytes()
        self.path(self.master).write_bytes(original + b'changed after render')
        with self.assertRaisesRegex(ValueError, 'source changed after HDR admission'):
            hdr.export_hdr_image(body, self.roots['output'], service)
        self.path(self.master).write_bytes(original)
        service.jobs.jobs[body['jobId']][1].pop('sourceMaster')
        with self.assertRaisesRegex(ValueError, 'older HDR job'):
            hdr.export_hdr_image(body, self.roots['output'], service)

    def test_changed_owned_model_input_is_never_ready(self):
        service, body, _ = self.hdr_fixture()
        model = service.jobs.jobs[body['jobId']][1]['modelInput']
        path = self.path(model['asset'])
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        path.write_bytes(b'changed private model input')
        with self.assertRaisesRegex(ValueError, 'owned HDR model input changed'):
            hdr.export_hdr_image(body, self.roots['output'], service)


class ImageExportRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = ImageExportTests('test_normal_eight_bit_source_stays_truthful_and_can_be_reexported')
        self.fixture.setUp()
        routes = web.RouteTableDef()
        export.register(routes)
        app = web.Application()
        app.add_routes(routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        folder = patch.object(sys.modules['folder_paths'], 'get_output_directory', return_value=str(self.fixture.roots['output']))
        folder.start()
        self.addCleanup(folder.stop)
        server = patch.dict(sys.modules, {'server': types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace()))})
        server.start()
        self.addCleanup(server.stop)

    async def asyncTearDown(self):
        await self.client.close()
        self.fixture.tearDown()

    async def test_registered_sdr_route_and_strict_body_origin(self):
        response = await self.client.post('/zura/studio/image-export', json=dict(asset=self.fixture.master, format='png8'))
        self.assertEqual(response.status, 200, await response.text())
        value = await response.json()
        self.assertEqual(value['dynamicRange'], 'SDR')
        self.assertEqual(value['file']['filename'], 'image.png')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        for body in ({'asset': self.fixture.master, 'format': 'png8', 'colour': 'HDR'}, {'asset': self.fixture.master, 'format': 'jpeg_hdr'}, {'asset': self.fixture.master, 'format': 'hdr_exr'}):
            rejected = await self.client.post('/zura/studio/image-export', json=body)
            self.assertEqual(rejected.status, 400)
        cross = await self.client.post('/zura/studio/image-export', json=dict(asset=self.fixture.master, format='png8'), headers={'Origin': 'https://other.example'})
        self.assertEqual(cross.status, 403)

    async def test_registered_hdr_route_requires_owned_completed_job(self):
        service, body, _ = self.fixture.hdr_fixture()
        sys.modules['server'].PromptServer.instance._zura_hdr_long_preview = service
        response = await self.client.post('/zura/studio/image-export', json=body)
        self.assertEqual(response.status, 200, await response.text())
        result = await response.json()
        self.assertTrue(result['verifiedHDR'])
        self.assertEqual(result['hdrJobId'], body['jobId'])
        too_big = await self.client.post('/zura/studio/image-export', data=b' ' * (export.MAX_BODY + 1))
        self.assertEqual(too_big.status, 400)

    async def test_hdr_admission_source_race_never_starts_job(self):
        import asyncio
        service_type = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_long_service').HDRLongService
        service = object.__new__(service_type)
        service.output_root = self.fixture.roots['output']
        service._preparing, service._requests = asyncio.Lock(), {}
        starts = []
        service.jobs = types.SimpleNamespace(tasks={}, start=lambda *args: starts.append(args))
        service.check_setup = lambda *args: None
        service.server = types.SimpleNamespace()
        def asset(body):
            self.fixture.path(self.fixture.master).write_bytes(b'changed during HDR preparation')
            return {'asset_kind': 'sdr_image'}, lambda value: self.fixture.path(self.fixture.master)
        service._asset = asset
        service.create_sdr = lambda *args, **kwargs: (object(), {'id': 'd' * 32})
        body = dict(mode='sdr', source_kind='output_image', frame_count=1, output_ref=self.fixture.master, output='acescg_exr')
        with self.assertRaisesRegex(ValueError, 'source changed after HDR admission'):
            await service.start(body)
        self.assertEqual(starts, [], 'A changed source never enters the model queue')

    async def test_queued_graph_reads_owned_exact_png16_snapshot_after_original_changes_and_restores(self):
        import asyncio
        service_type = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_long_service').HDRLongService
        builder = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_studio').build_asset_graph
        original_path = self.fixture.roots['output'] / 'genj' / 'studio_images' / 'ordinary16.png'
        pixels = np.full((128, 128, 3), [.12567, .5, .87521], np.float32)
        export._write(original_path, pixels, 'png16')
        original_bytes = original_path.read_bytes()
        source = dict(filename=original_path.name, subfolder='genj/studio_images', type='output')
        service = object.__new__(service_type)
        service.output_root = self.fixture.roots['output']
        service._preparing, service._requests = asyncio.Lock(), {}
        service.check_setup = lambda *args: None
        service.server = types.SimpleNamespace()
        captured = {}
        class Jobs:
            def __init__(self):
                self.jobs, self.tasks = {}, {}
            def start(self, job, details):
                self.jobs[details['id']] = (job, details)
                return details['id']
            def status(self, identity):
                return {**self.jobs[identity][1], 'state': 'queued'}
        service.jobs = Jobs()
        def factory(server, asset, body, check, output_root, **kwargs):
            graph, details = builder(asset, body, check)
            captured.update(asset=asset, check=check, graph=graph)
            return object(), {**details, 'id': 'e' * 32}
        service.create_sdr = factory
        body = dict(mode='sdr', source_kind='output_image', frame_count=1, start_frame=0, sequence_fps=25,
                    colour_space='srgb_display', output_ref=source, output='acescg_exr', exr_storage='float32')
        with patch('ComfyUI_zura_nodes.comfylink.studio_cancel.claim_work', lambda *args: None):
            admitted = await service.start(body)
        model = admitted['modelInput']
        snapshot = self.fixture.path(model['asset'])
        self.assertNotEqual(snapshot, original_path)
        self.assertEqual(snapshot.read_bytes(), original_bytes)
        self.assertEqual(model['storageBitDepth'], 16)
        self.assertFalse(snapshot.stat().st_mode & stat.S_IWRITE)
        self.assertEqual(captured['graph']['zura_hdr_source']['inputs']['source'], str(snapshot))
        original_path.write_bytes(b'artist changed the original after queue admission')
        later_graph, _ = builder(captured['asset'], body, captured['check'])
        self.assertEqual(later_graph['zura_hdr_source']['inputs']['source'], str(snapshot))
        self.assertEqual(snapshot.read_bytes(), original_bytes)
        original_path.write_bytes(original_bytes)
        self.assertEqual(captured['check'](captured['asset']), snapshot)
        with Image.open(snapshot) as copied, Image.open(original_path) as original:
            self.assertEqual(copied.info['icc_profile'], original.info['icc_profile'])
        reader = oiio.ImageInput.open(str(snapshot))
        self.assertEqual(reader.spec().format, oiio.UINT16)
        np.testing.assert_array_equal(reader.read_image(format=oiio.UINT16), np.round(pixels * 65535).astype(np.uint16))
        reader.close()


if __name__ == '__main__':
    unittest.main()
