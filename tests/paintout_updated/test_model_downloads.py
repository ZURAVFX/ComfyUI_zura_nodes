"""Tiny local HTTP fixtures exercise downloads; no model weights are fetched."""
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import requests

SOURCE = Path(__file__).resolve().parents[2] / 'paintout/model_downloads.py'
spec = importlib.util.spec_from_file_location('paintout_downloads_test', SOURCE)
downloads = importlib.util.module_from_spec(spec)
spec.loader.exec_module(downloads)


def tensor_file(size=128):
    payload = bytes(index % 251 for index in range(size))
    header = json.dumps({'weight': {'dtype': 'U8', 'shape': [size], 'data_offsets': [0, size]}}, separators=(',', ':')).encode()
    header += b' ' * (-len(header) % 8)
    return struct.pack('<Q', len(header)) + header + payload


@contextmanager
def server(data, *, fail_first=False, ignore_range=False, slow=False, status=200, wrong_range=False):
    state = {'requests': [], 'number': 0, 'data': data}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            state['number'] += 1
            raw_range = self.headers.get('Range')
            state['requests'].append(raw_range)
            if status != 200:
                self.send_response(status)
                self.end_headers()
                return
            start = int(raw_range.split('=')[1].split('-')[0]) if raw_range and not ignore_range else 0
            self.send_response(206 if start else 200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Length', str(len(data) - start))
            if start:
                self.send_header('Content-Range', f'bytes {start + int(wrong_range)}-{len(data)-1}/{len(data)}')
            self.end_headers()
            try:
                body = data[start:]
                if fail_first and state['number'] == 1:
                    self.wfile.write(body[:1024 * 1024])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                for index in range(0, len(body), 65536):
                    self.wfile.write(body[index:index+65536])
                    self.wfile.flush()
                    if slow:
                        time.sleep(.025)
            except OSError:
                pass
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    def fetch(_url, **kwargs):
        return requests.get(f'http://127.0.0.1:{http.server_port}/fixture', **kwargs)
    try:
        yield fetch, state
    finally:
        http.shutdown()
        http.server_close()
        thread.join()


class ModelDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = tensor_file()
        self.item = dict(folder='vae', filename='fixture.safetensors', repo='Example/fixture', revision='1'*40,
                         remote_path='vae/fixture.safetensors', size_bytes=len(self.data),
                         sha256=hashlib.sha256(self.data).hexdigest(), gated=False, model_card='https://huggingface.co/Example/fixture')
        self.recipe = dict(name='Fixture model', files=[self.item], license_url=self.item['model_card'])
        self.catalog = patch.object(downloads, 'CATALOG', {'fixture': self.recipe, 'shared': self.recipe})
        self.catalog.start()
        self.addCleanup(self.catalog.stop)
        token = patch.object(downloads, '_cached_token', return_value=None)
        token.start()
        self.addCleanup(token.stop)

    def manager(self, fetch=None, **kwargs):
        return downloads.DownloadManager({'vae': [str(self.root)]}, fetch=fetch, **kwargs)

    def wait(self, manager, identity, phases=('done', 'failed', 'cancelled')):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = manager.status(identity)
            if job['phase'] in phases:
                return job
            time.sleep(.01)
        self.fail('Download fixture did not finish: ' + str(manager.status(identity)))

    def test_success_atomic_hash_and_shared_files_deduplicate(self):
        callbacks = []
        with server(self.data) as (fetch, state):
            manager = self.manager(fetch, on_installed=lambda: callbacks.append(True))
            identity = manager.start(['fixture', 'shared'])
            job = self.wait(manager, identity)
        self.assertEqual(job['phase'], 'done')
        self.assertEqual(job['done_bytes'], len(self.data))
        self.assertEqual(job['total_bytes'], len(self.data))
        self.assertEqual((self.root / self.item['filename']).read_bytes(), self.data)
        self.assertEqual(state['number'], 1)
        self.assertEqual(callbacks, [True])
        self.assertFalse(list(self.root.glob('*.part')))

    def test_existing_subfolder_and_later_root_are_reused_without_network(self):
        second = self.root / 'second'
        nested = second / 'my-models'
        nested.mkdir(parents=True)
        (nested / self.item['filename']).write_bytes(self.data)
        manager = downloads.DownloadManager({'vae': [str(self.root), str(second)]}, fetch=lambda *_a, **_k: self.fail('Unexpected network'))
        model = manager.catalogue()['models'][0]
        self.assertTrue(model['files'][0]['installed'])
        self.assertFalse(model['files'][0]['incomplete'])
        self.assertEqual(model['remaining_bytes'], 0)
        self.assertNotIn('destination', model['files'][0])
        self.assertEqual(self.wait(manager, manager.start('fixture'))['phase'], 'done')
        self.assertFalse((self.root / self.item['filename']).exists())

    def test_broken_root_copy_hiding_valid_nested_copy_is_not_ready(self):
        broken = self.root / self.item['filename']
        broken.write_bytes(b'broken')
        nested = self.root / 'nested'
        nested.mkdir()
        healthy = nested / self.item['filename']
        healthy.write_bytes(self.data)
        manager = self.manager(lambda *_a, **_k: self.fail('Unexpected network'))
        file = manager.catalogue()['models'][0]['files'][0]
        self.assertFalse(file['installed'])
        self.assertTrue(file['incomplete'])
        with self.assertRaisesRegex(ValueError, 'may hide another valid copy'):
            manager.start('fixture')
        self.assertEqual(broken.read_bytes(), b'broken')
        self.assertEqual(healthy.read_bytes(), self.data)

    def test_broken_earlier_root_copy_hiding_valid_later_root_is_not_ready(self):
        broken = self.root / self.item['filename']
        broken.write_bytes(b'broken')
        with tempfile.TemporaryDirectory() as second:
            healthy = Path(second) / self.item['filename']
            healthy.write_bytes(self.data)
            manager = downloads.DownloadManager({'vae': [str(self.root), second]}, fetch=lambda *_a, **_k: self.fail('Unexpected network'))
            file = manager.catalogue()['models'][0]['files'][0]
            self.assertFalse(file['installed'])
            self.assertTrue(file['incomplete'])
            with self.assertRaisesRegex(ValueError, 'will not be overwritten'):
                manager.start('fixture')
            self.assertEqual(healthy.read_bytes(), self.data)
        self.assertEqual(broken.read_bytes(), b'broken')

    def test_valid_root_copy_wins_over_broken_nested_copy(self):
        nested = self.root / 'nested'
        nested.mkdir()
        (nested / self.item['filename']).write_bytes(b'broken')
        (self.root / self.item['filename']).write_bytes(self.data)
        manager = self.manager(lambda *_a, **_k: self.fail('Unexpected network'))
        file = manager.catalogue()['models'][0]['files'][0]
        self.assertTrue(file['installed'])
        self.assertFalse(file['incomplete'])
        self.assertEqual(self.wait(manager, manager.start('fixture'))['phase'], 'done')

    def test_conflicting_existing_file_is_never_overwritten(self):
        target = self.root / self.item['filename']
        target.write_bytes(b'artist-model')
        with self.assertRaisesRegex(ValueError, 'will not be overwritten'):
            self.manager().start('fixture')
        self.assertEqual(target.read_bytes(), b'artist-model')

    def test_existing_size_match_with_html_header_is_not_ready(self):
        (self.root / self.item['filename']).write_bytes(b'<' * len(self.data))
        file = self.manager().catalogue()['models'][0]['files'][0]
        self.assertFalse(file['installed'])
        self.assertTrue(file['incomplete'])

    def test_published_existing_variant_requires_full_hash_and_is_cached(self):
        alternate = tensor_file(256)
        self.item['existing_variants'] = [dict(repo='Example/alternate', revision='2' * 40,
                    remote_path='vae/fixture.safetensors', size_bytes=len(alternate),
                    sha256=hashlib.sha256(alternate).hexdigest())]
        target = self.root / self.item['filename']
        target.write_bytes(alternate)
        downloads._existing_sha256.cache_clear()
        manager = self.manager(lambda *_a, **_k: self.fail('Unexpected network'))
        first = manager.catalogue()['models'][0]['files'][0]
        self.assertTrue(first['installed'])
        self.assertNotIn('existing_variants', first)
        self.assertEqual(downloads._existing_sha256.cache_info().misses, 1)
        self.assertTrue(manager.catalogue()['models'][0]['files'][0]['installed'])
        self.assertEqual(downloads._existing_sha256.cache_info().misses, 1)
        self.assertGreater(downloads._existing_sha256.cache_info().hits, 0)
        self.assertEqual(self.wait(manager, manager.start('fixture'))['phase'], 'done')
        self.assertEqual(target.read_bytes(), alternate)
        # Same recognised size and valid header is insufficient after bytes change.
        target.write_bytes(alternate[:-1] + bytes([alternate[-1] ^ 1]))
        wrong = manager.catalogue()['models'][0]['files'][0]
        self.assertFalse(wrong['installed'])
        self.assertTrue(wrong['incomplete'])
        with self.assertRaisesRegex(ValueError, 'will not be overwritten'):
            manager.start('fixture')

    def test_existing_variant_with_unknown_size_still_blocks_download(self):
        alternate = tensor_file(256)
        self.item['existing_variants'] = [dict(repo='Example/alternate', revision='2' * 40,
                    remote_path='vae/fixture.safetensors', size_bytes=len(alternate),
                    sha256=hashlib.sha256(alternate).hexdigest())]
        target = self.root / self.item['filename']
        target.write_bytes(tensor_file(512))
        file = self.manager().catalogue()['models'][0]['files'][0]
        self.assertFalse(file['installed'])
        self.assertTrue(file['incomplete'])

    def test_interrupted_stream_retries_with_range(self):
        data = tensor_file(2 * 1024 * 1024)
        self.item.update(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        with server(data, fail_first=True) as (fetch, state):
            manager = self.manager(fetch)
            job = self.wait(manager, manager.start('fixture'))
        self.assertEqual(job['phase'], 'done', job)
        self.assertTrue(any(value and value.startswith('bytes=1048576-') for value in state['requests']))
        self.assertEqual((self.root / self.item['filename']).read_bytes(), data)

    def test_server_ignoring_range_restarts_instead_of_appending(self):
        partial = self.root / ('.zura-paintout-' + self.item['sha256'] + '.part')
        partial.write_bytes(self.data[:25])
        with server(self.data, ignore_range=True) as (fetch, state):
            manager = self.manager(fetch)
            job = self.wait(manager, manager.start('fixture'))
        self.assertEqual(job['phase'], 'done', job)
        self.assertEqual(state['requests'], ['bytes=25-'])
        self.assertEqual((self.root / self.item['filename']).read_bytes(), self.data)

    def test_wrong_range_does_not_publish(self):
        partial = self.root / ('.zura-paintout-' + self.item['sha256'] + '.part')
        partial.write_bytes(self.data[:25])
        with server(self.data, wrong_range=True) as (fetch, _):
            manager = self.manager(fetch)
            job = self.wait(manager, manager.start('fixture'))
        self.assertEqual(job['phase'], 'failed')
        self.assertIn('resumed download', job['error'])
        self.assertFalse((self.root / self.item['filename']).exists())

    def test_wrong_hash_and_malformed_header_never_publish(self):
        for wrong in (b'<' * len(self.data), self.data[:-1] + b'!'):
            with self.subTest(header=wrong.startswith(b'<')), server(wrong) as (fetch, _):
                manager = self.manager(fetch)
                job = self.wait(manager, manager.start('fixture'))
                self.assertEqual(job['phase'], 'failed')
                self.assertFalse((self.root / self.item['filename']).exists())
                self.assertFalse(list(self.root.glob('*.part')))

    def test_cancel_keeps_partial_for_explicit_retry(self):
        data = tensor_file(4 * 1024 * 1024)
        self.item.update(size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        with server(data, slow=True) as (fetch, state):
            manager = self.manager(fetch)
            identity = manager.start('fixture')
            deadline = time.monotonic() + 5
            while manager.status(identity)['done_bytes'] < 1024 * 1024 and time.monotonic() < deadline:
                time.sleep(.01)
            manager.cancel(identity)
            job = self.wait(manager, identity)
            self.assertEqual(job['phase'], 'cancelled')
            partial = self.root / ('.zura-paintout-' + self.item['sha256'] + '.part')
            self.assertGreater(partial.stat().st_size, 0)
            self.assertFalse((self.root / self.item['filename']).exists())
            resumed = self.wait(manager, manager.start('fixture'))
        self.assertEqual(resumed['phase'], 'done', resumed)
        self.assertTrue(any(value for value in state['requests']))

    def test_auth_error_never_exposes_token_url_or_machine_path(self):
        with server(self.data, status=403) as (fetch, _):
            manager = self.manager(fetch)
            identity = manager.start('fixture', token='hf_TestSecretToken')
            job = self.wait(manager, identity)
        self.assertTrue(job['auth_required'])
        public = json.dumps(job) + json.dumps(manager.catalogue())
        self.assertNotIn('TestSecretToken', public)
        self.assertNotIn(str(self.root), public)
        self.assertNotIn('/resolve/', public)
        self.assertIn('accept its terms', job['error'])

    def test_validation_rejects_url_path_and_token_injection(self):
        for identity in ('../../bad', 'https://evil.example/model', ['unknown'], None, []):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                self.manager().start(identity)
        for field, value in [('filename', '../escape.safetensors'), ('remote_path', '../escape'), ('folder', '../vae')]:
            original = self.item[field]
            self.item[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.manager().start('fixture')
            self.item[field] = original
        with self.assertRaises(ValueError) as error:
            self.manager().start('fixture', token='SECRET bad token')
        self.assertNotIn('SECRET', str(error.exception))

    def test_partial_symlink_cannot_write_outside_model_root(self):
        outside = self.root.parent / (self.root.name + '-outside')
        outside.write_bytes(b'keep')
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        partial = self.root / ('.zura-paintout-' + self.item['sha256'] + '.part')
        try:
            partial.symlink_to(outside)
        except OSError:
            self.skipTest('This Windows account cannot create symlinks.')
        manager = self.manager(lambda *_a, **_k: self.fail('Unexpected network'))
        job = self.wait(manager, manager.start('fixture'))
        self.assertEqual(job['phase'], 'failed')
        self.assertEqual(outside.read_bytes(), b'keep')
        self.assertFalse((self.root / self.item['filename']).exists())

    def test_pinned_catalogue_matches_runtime_and_omits_unused_models(self):
        with patch.object(downloads, 'CATALOG', self.catalog.temp_original):
            for recipe in downloads.CATALOG.values():
                for item in recipe['files']:
                    downloads._safe_item(item)
            names = {item['filename'] for recipe in downloads.CATALOG.values() for item in recipe['files']}
            self.assertEqual(len(names), 13)
            self.assertFalse(any('upscal' in name or 'refine' in name for name in names))
            hdr = {item['filename'] for item in downloads.CATALOG['targeted_hdr']['files']}
            self.assertIn('ltx-2.5-video-vae-bf16.safetensors', hdr)
            self.assertNotIn('ltx-2.5-video-vae-conv-bf16.safetensors', hdr)

    def test_catalogue_is_offline_and_disk_preflight_prevents_network(self):
        manager = self.manager(lambda *_a, **_k: self.fail('Unexpected network'))
        self.assertGreater(manager.catalogue()['models'][0]['remaining_bytes'], 0)
        with patch.object(downloads.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 0})()):
            job = self.wait(manager, manager.start('fixture'))
        self.assertEqual(job['phase'], 'failed')
        self.assertIn('free disk space', job['error'])
        self.assertFalse((self.root / self.item['filename']).exists())

    def test_concurrent_final_install_is_preserved(self):
        target = self.root / self.item['filename']
        publish = downloads._publish_verified
        def install_other_file(source, destination):
            if destination == target:
                target.write_bytes(b'another-install')
            publish(source, destination)
        with server(self.data) as (fetch, _), patch.object(downloads, '_publish_verified', side_effect=install_other_file):
            manager = self.manager(fetch)
            job = self.wait(manager, manager.start('fixture'))
        self.assertEqual(job['phase'], 'failed')
        self.assertIn('not overwritten', job['error'])
        self.assertEqual(target.read_bytes(), b'another-install')


if __name__ == '__main__':
    unittest.main()
