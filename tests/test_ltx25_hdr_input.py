"""Actual EXR input ownership and opening approval identity, without inference."""
import copy
import hashlib
import importlib
import types
from unittest.mock import patch
import unittest

import test_ltx_hdr_endpoint_routes as fixtures

hdr = importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx25_hdr_input')
opening = importlib.import_module('ComfyUI_zura_nodes.artist_studio.opening')
appearance = importlib.import_module('ComfyUI_zura_nodes.artist_studio.appearance')


class NativeOpeningTests(unittest.TestCase):
    def setUp(self):
        fixtures.EndpointAssetTests.setUp(self)
        del self.check
        self.flag = patch.dict('os.environ', {'ZURA_LTX_HDR_PERFORMANCE': '1'})
        self.flag.start(); self.addCleanup(self.flag.stop)
        self.identity = 'e' * 32
        self.asset.update(id=self.identity, kind='asset', file=self.manifest.relative_to(self.root).as_posix())
        self.records = {self.identity: self.asset}
        self.store = types.SimpleNamespace(load=self.records.__getitem__, save=lambda a: self.records.__setitem__(a['id'], copy.deepcopy(a)))
        self.config = {'engine': 'local', 'workflow_mode': 'motion', 'edit_area': 'scene', 'ltx_output': 'hlg_and_exr'}

    def check(self, asset):
        path = (self.root / asset['file']).resolve()
        if not path.is_relative_to((self.root / 'genj_studio').resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != asset['sha']:
            raise ValueError('changed asset')
        return path

    def make(self):
        return hdr.make_opening_asset(self.store, self.check, self.identity)

    def test_verified_exr_is_retained_separately_from_display_proxy(self):
        asset = self.make()
        self.assertEqual(asset['asset_kind'], 'image')
        self.assertEqual(asset['native_hdr']['asset_id'], self.identity)
        self.assertTrue(asset['file'].endswith('.png'))
        self.assertEqual(hashlib.sha256(self.file.read_bytes()).hexdigest(), self.original_sha)
        self.assertIn(asset['id'], self.records)
        endpoint = hdr.resolve_asset(asset, self.config, self.store, self.check)
        self.assertEqual(endpoint['manifest'], str(self.manifest))

    def test_binding_identity_includes_exr_and_revokes_only_changed_approval(self):
        asset = self.make()
        project = {'id': 'a' * 32, 'config': self.config, 'phase': 'approved'}
        def bind():
            return opening.bind_uploaded_opening(project, asset, self.root, store=self.store,
                assert_approved=lambda _: None, check_asset=self.check, media_url=lambda a: a['filename'])
        self.assertTrue(bind())
        self.assertNotEqual(project['opening_key'], asset['sha'])
        self.assertEqual(project['opening_input']['native_hdr'], asset['native_hdr'])
        key = project['opening_key']; project['opening_approval'] = key
        self.assertFalse(bind()); self.assertEqual(project['opening_approval'], key)
        endpoint = hdr.resolve_opening(project, self.store, self.check)
        self.assertEqual(endpoint['opening_key'], key)
        asset['native_hdr']['colour_space'] = 'acescg'
        self.assertTrue(bind()); self.assertNotEqual(project['opening_key'], key)
        self.assertIsNone(project['opening_approval'])

    def test_modified_original_is_rejected_even_when_png_is_unchanged(self):
        asset = self.make()
        self.file.write_bytes(self.file.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            hdr.resolve_asset(asset, self.config, self.store, self.check)

    def test_no_sdr_fallback_and_no_other_model_or_masked_route(self):
        asset = self.make()
        for change in ({'engine': 'h3'}, {'edit_area': 'mask'}, {'viewport_render': True},
                       {'workflow_mode': 'relight'}, {'ltx_output': 'sdr'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                hdr.resolve_asset(asset, {**self.config, **change}, self.store, self.check)
        with patch.dict('os.environ', {'ZURA_LTX_HDR_PERFORMANCE': '0'}), self.assertRaisesRegex(ValueError, 'opt-in'):
            hdr.resolve_asset(asset, self.config, self.store, self.check)
        self.assertIsNone(hdr.resolve_asset({'file': 'sdr.png'}, {}, self.store, self.check))

    def test_references_cannot_silently_use_hdr_preview_as_sdr(self):
        asset = self.make()
        with self.assertRaisesRegex(ValueError, 'finished LTX HDR'):
            appearance.resolve_appearance({'references': [asset['id']], 'config': self.config}, self.store.load, self.check)
        resolved = appearance.resolve_appearance({'look_mode': 'ready', 'starting_image': asset['id'],
            'references': [], 'config': self.config}, self.store.load, self.check)
        self.assertEqual(resolved['starting_asset']['native_hdr'], asset['native_hdr'])

    def test_invalid_marker_and_manifest_identity(self):
        asset = self.make()
        with self.assertRaisesRegex(ValueError, 'identity'):
            hdr.opening_identity(asset['sha'], {**asset['native_hdr'], 'asset_id': 42})
        asset['native_hdr']['manifest_sha'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'original HDR image changed'):
            hdr.resolve_asset(asset, self.config, self.store, self.check)

    def test_readiness_uses_full_vae_and_actual_graph_classes(self):
        all_nodes = {}
        # First inspect to obtain the actual missing class set, then supply it.
        result = hdr.inspect_readiness(lambda *_: 'installed', all_nodes)
        mappings = {name: object() for name in result['missingNodes']}
        ready = hdr.inspect_readiness(lambda *_: 'installed', mappings,
            detector_paths={'bbox_detector': 'yolo', 'pose_estimator': 'pose'})
        self.assertTrue(ready['ready'])
        names = [f['filename'] for f in ready['files']]
        self.assertIn('ltx-2.5-video-vae-bf16.safetensors', names)
        self.assertNotIn('ltx-2.5-video-vae-conv-bf16.safetensors', names)
        self.assertIn('LTXVVAEForceFloat32', mappings)
        self.assertIn('ZuraHDRSelectNativeTimeline', mappings,'Native source frames must appear in graph-derived setup')


if __name__ == '__main__':
    unittest.main()
