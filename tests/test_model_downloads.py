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
            with self.assertRaisesRegex(ValueError, 'wrong size'):
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
