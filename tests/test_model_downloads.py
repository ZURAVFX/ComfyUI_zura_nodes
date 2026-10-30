import hashlib
import importlib.util
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('model_downloads', Path(__file__).resolve().parents[1] / 'artist_studio' / 'model_downloads.py')
downloads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloads)


class Response:
    status_code = 200
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def raise_for_status(self): pass
    def iter_content(self, chunk_size): yield self.data


class ModelDownloadTest(unittest.TestCase):
    def test_optional_model_folder_can_register_after_routes_load(self):
        class Folders:
            paths = {'loras': ['/models/loras']}
            def get_folder_paths(self, name): return self.paths[name]
        folders = Folders()
        self.assertEqual(downloads.folder_locations(folders, {'detection', 'loras'})['detection'], [])
        folders.paths['detection'] = ['/models/detection']
        self.assertEqual(downloads.folder_locations(folders, {'detection'})['detection'], ['/models/detection'])

    def test_starting_image_and_hdr_packages_include_workflow_dependencies(self):
        packages = downloads.CATALOG
        opening = {(f['folder'], f['filename']) for f in packages['flux2_klein_start']['files']}
        self.assertIn(('text_encoders', 'qwen_3_8b_fp8mixed.safetensors'), opening)
        self.assertIn(('vae', 'full_encoder_small_decoder.safetensors'), opening)
        self.assertEqual(packages['flux2_klein_start']['files'][0], packages['flux2_klein_9b']['files'][0])
        hdr = {(f['folder'], f['filename']) for f in packages['ltx25_sdr_hdr']['files']}
        self.assertIn(('embeddings', 'ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors'), hdr)
        self.assertEqual(packages['ltx25_text_encoder']['files'][0]['filename'], 'gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors')
        self.assertEqual(packages['ltx25_outpaint']['files'][0]['filename'], 'ltx-2.3-22b-ic-lora-outpaint.safetensors')
        self.assertEqual(packages['ltx25_in_outpaint']['files'][0]['filename'], 'ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors')
        self.assertTrue(packages['ltx25_in_outpaint']['gated'])
        self.assertEqual(packages['h3_control']['files'][0]['folder'], 'model_patches')
        self.assertIn('CrossView', packages['h3_crossview']['files'][0]['filename'])
        wan22 = packages['wan22_animate_core']['files']
        self.assertEqual(wan22[0]['filename'], 'Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors')
        self.assertEqual(wan22[1:], packages['wan_animate_2']['files'][1:])
        self.assertIn('separately', packages['wan22_animate_core']['note'])
        self.assertEqual({f['folder'] for f in packages['wan22_pose']['files']}, {'detection'})
        self.assertEqual(packages['h3_birefnet']['files'][0]['folder'], 'background_removal')
        self.assertEqual(packages['h3_dmd_ref2va']['files'][0]['filename'], 'minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors')
        self.assertEqual(packages['h3_first_last']['files'][0]['filename'], 'minimax_h3_fl2va_pruned_int8_convrot.safetensors')
        self.assertEqual(packages['ltx25_text_int8']['files'][0]['filename'], 'gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors')
        self.assertTrue(packages['ltx25_clean_plate']['gated'])
        self.assertEqual({f['filename'] for f in packages['h3_head_adapters']['files']}, {'minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16.safetensors', 'camera_motion_h3_lora_v1_1000_pruned.safetensors'})
        relight = packages['wan21_relight']['files']
        self.assertEqual(relight[0]['filename'], 'wan_2.1_idv2v_int8_convrot.safetensors')
        self.assertEqual(relight[1:4], packages['wan_animate_2']['files'][1:])
        self.assertEqual(relight[-1]['filename'], 'lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors')
        for name in ('flux2_klein_start', 'ltx25_full_vae', 'ltx25_refine', 'ltx25_sdr_hdr', 'ltx25_text_encoder', 'ltx25_outpaint', 'ltx25_in_outpaint', 'ltx_control', 'ltx25_layout', 'h3_int8_vae', 'h3_control', 'h3_crossview', 'wan22_animate_core', 'wan22_pose', 'h3_birefnet', 'h3_head_acceleration', 'h3_head_adapters', 'h3_dmd_ref2va', 'wan21_relight', 'h3_first_last', 'ltx25_text_int8', 'ltx25_clean_plate'):
            for f in packages[name]['files']:
                self.assertEqual(len(f['revision']), 40)
                self.assertEqual(len(f['sha256']), 64)
                self.assertGreater(f['size_bytes'], 0)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.locations = {'diffusion_models': [self.directory.name]}
        data = b'test model bytes'
        self.data = data
        spec = downloads._file('diffusion_models', 'example.safetensors', 'author/model',
                               'a' * 40, 'example.safetensors', len(data),
                               hashlib.sha256(data).hexdigest())
        self.recipe = {'example': dict(name='Example', gated=False, license_url='', files=[spec])}

    def wait(self, manager, job):
        for _ in range(300):
            status = manager.status(job)
            if status['phase'] in ('done', 'cancelled', 'failed'):
                return status
            time.sleep(.01)
        self.fail('Download did not finish')

    def test_allowlisted_download_verifies_and_never_overwrites(self):
        with patch.dict(downloads.CATALOG, self.recipe, clear=True), \
             patch('requests.get', return_value=Response(self.data)) as get:
            plan = downloads.inspect('example', self.locations)
            self.assertEqual(plan['remaining_bytes'], len(self.data))
            manager = downloads.DownloadManager(self.locations)
            status = self.wait(manager, manager.start('example'))
            self.assertEqual(status['phase'], 'done')
            self.assertEqual(status['done_bytes'], len(self.data))
            path = Path(self.directory.name) / 'example.safetensors'
            self.assertEqual(path.read_bytes(), self.data)
            self.assertEqual(downloads.inspect('example', self.locations)['remaining_bytes'], 0)
            self.assertEqual(self.wait(manager, manager.start('example'))['phase'], 'done')
            self.assertEqual(get.call_count, 1)
            with self.assertRaises(ValueError): downloads.inspect('https://example.com/model', self.locations)

    def test_bad_hash_does_not_publish_partial_model(self):
        with patch.dict(downloads.CATALOG, self.recipe, clear=True), \
             patch('requests.get', return_value=Response(b'wrong model bytes')):
            manager = downloads.DownloadManager(self.locations)
            self.assertEqual(self.wait(manager, manager.start('example'))['phase'], 'failed')
            self.assertFalse((Path(self.directory.name) / 'example.safetensors').exists())
            self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_complete_copy_in_later_model_root_is_preferred(self):
        with tempfile.TemporaryDirectory() as second, patch.dict(downloads.CATALOG, self.recipe, clear=True):
            broken = Path(self.directory.name) / 'example.safetensors'
            complete = Path(second) / 'example.safetensors'
            broken.write_bytes(b'partial')
            complete.write_bytes(self.data)
            plan = downloads.inspect('example', {'diffusion_models': [self.directory.name, second]})
            self.assertTrue(plan['files'][0]['installed'])
            self.assertFalse(plan['files'][0]['incomplete'])
            self.assertEqual(plan['files'][0]['destination'], str(complete))
            self.assertEqual(plan['remaining_bytes'], 0)

    def test_hardlink_unavailable_uses_atomic_noreplace_rename(self):
        with patch.dict(downloads.CATALOG, self.recipe, clear=True), \
             patch('requests.get', return_value=Response(self.data)), \
             patch.object(downloads.os, 'link', side_effect=OSError('hard links unavailable')):
            manager = downloads.DownloadManager(self.locations)
            status = self.wait(manager, manager.start('example'))
            self.assertEqual(status['phase'], 'done', status)
            self.assertEqual((Path(self.directory.name) / 'example.safetensors').read_bytes(), self.data)
            self.assertEqual(len(list(Path(self.directory.name).iterdir())), 1)

    def test_noreplace_race_never_clobbers_destination(self):
        source = Path(self.directory.name) / '.complete'
        dest = Path(self.directory.name) / 'existing.safetensors'
        source.write_bytes(self.data)
        dest.write_bytes(b'existing')
        with patch.object(downloads.os, 'link', side_effect=OSError('hard links unavailable')):
            with self.assertRaises(OSError):
                downloads._publish_verified(source, dest)
        self.assertEqual(dest.read_bytes(), b'existing')
        self.assertEqual(source.read_bytes(), self.data)

    def test_incomplete_existing_file_is_not_installed_or_overwritten(self):
        path = Path(self.directory.name) / 'example.safetensors'
        path.write_bytes(b'incomplete')
        with patch.dict(downloads.CATALOG, self.recipe, clear=True), patch('requests.get') as get:
            result = downloads.inspect('example', self.locations)
            self.assertFalse(result['files'][0]['installed'])
            self.assertTrue(result['files'][0]['incomplete'])
            with self.assertRaisesRegex(ValueError, 'differs from this download'):
                downloads.DownloadManager(self.locations).start('example')
            self.assertEqual(path.read_bytes(), b'incomplete')
            get.assert_not_called()

    def test_unsupported_filesystem_fails_before_download(self):
        with patch.dict(downloads.CATALOG, self.recipe, clear=True), \
             patch('requests.get') as get, \
             patch.object(downloads.os, 'link', side_effect=OSError('hard links unavailable')), \
             patch.object(downloads, '_rename_noreplace', side_effect=OSError('unsupported')):
            manager = downloads.DownloadManager(self.locations)
            result = self.wait(manager, manager.start('example'))
            self.assertEqual(result['phase'], 'failed')
            self.assertIn('atomic installation', result['error'])
            self.assertEqual(list(Path(self.directory.name).iterdir()), [])
            get.assert_not_called()


if __name__ == '__main__': unittest.main()
