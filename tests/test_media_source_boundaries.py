"""CPU-only media picker file, browser-origin and no-remote-fetch boundaries."""
import ast
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from aiohttp import web
import v2_bootstrap

media = importlib.import_module('ComfyUI_zura_nodes.media_source')
import folder_paths


class MediaBoundaries(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.roots = {}
        for kind in ('input', 'output', 'temp'):
            directory = self.root / kind
            directory.mkdir()
            self.roots[kind] = directory
            handler = patch.object(folder_paths, 'get_' + kind + '_directory', return_value=str(directory), create=True)
            handler.start()
            self.addCleanup(handler.stop)
        self.clip = self.roots['input'] / 'uploads' / 'example.mp4'
        self.clip.parent.mkdir()
        self.clip.write_bytes(b'synthetic uploaded video fixture')

    def test_uploaded_relative_absolute_and_annotated_media_roots(self):
        self.assertEqual(media.local_path('uploads/example.mp4'), self.clip.resolve())
        for kind, root in self.roots.items():
            clip = root / 'clip.mp4'
            clip.write_bytes(b'neutral contained clip')
            self.assertEqual(media.local_path(str(clip)), clip.resolve())
            self.assertEqual(media.local_path('clip.mp4 [' + kind + ']'), clip.resolve())

    def test_traversal_absolute_outside_other_drive_unc_and_streams_rejected(self):
        outside = self.root / 'outside.mp4'
        outside.write_bytes(b'private fixture must never reach a decoder')
        for name in (str(outside), '../outside.mp4', '../output/clip.mp4', 'uploads/../../outside.mp4',
                     r'Q:\private\video.mp4', r'\\untrusted-host\share\video.mp4',
                     '//untrusted-host/share/video.mp4', 'uploads/example.mp4:hidden', ''):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Choose local video'):
                media.local_path(name)

    def test_symlink_escape_rejected_and_contained_symlink_supported(self):
        outside = self.root / 'outside.mp4'
        outside.write_bytes(b'private fixture')
        escaping = self.roots['input'] / 'outside-link.mp4'
        contained = self.roots['input'] / 'inside-link.mp4'
        try:
            escaping.symlink_to(outside)
            contained.symlink_to(self.clip)
        except (OSError, NotImplementedError):
            self.skipTest('Platform does not permit fixture symlinks')
        with self.assertRaisesRegex(ValueError, 'Choose local video'):
            media.local_path(escaping)
        self.assertEqual(media.local_path(contained), self.clip.resolve())

    def test_preview_and_decode_never_follow_direct_remote_sources(self):
        urls = ('http://127.0.0.1:8188/private', 'http://10.0.0.1/clip.mp4',
                'http://169.254.169.254/latest/meta-data', 'https://example.com/clip.mp4',
                'https://example.com/redirect-to-private', 'file:///outside/video.mp4')
        with patch.object(media.subprocess, 'check_output') as probe, \
                patch.object(media.subprocess, 'run') as encoder, \
                patch.object(media, 'download_video', wraps=media.download_video) as downloader:
            for url in urls:
                with self.subTest(url=url), self.assertRaisesRegex(ValueError, 'Choose local video'):
                    media.preview_clip(url, automatic=False)
                with self.assertRaisesRegex(ValueError, 'Choose local video'):
                    media.decode_clip(url, 0)
            downloader.assert_not_called()
            probe.assert_not_called()
            encoder.assert_not_called()

    def test_disabled_downloader_stops_before_yt_dlp_import(self):
        original_import = __import__
        def guarded_import(name, *args, **kwargs):
            if name in ('yt_dlp', 'requests'):
                raise AssertionError('A disabled download must not import a network client')
            return original_import(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=guarded_import):
            for url in ('http://127.0.0.1/private', 'https://example.com/video.mp4'):
                with self.assertRaisesRegex(ValueError, 'Choose local video'):
                    media.download_video(url)

    def test_uploaded_local_preview_keeps_temp_delivery_and_local_demux_limits(self):
        probe = json.dumps({'format': {'duration': '20'}}).encode()
        with patch.object(media.shutil, 'which', side_effect=lambda name: name), \
                patch.object(media.subprocess, 'check_output', return_value=probe) as inspect, \
                patch.object(media.subprocess, 'run') as encode:
            result = media.preview_clip('uploads/example.mp4', start=1, automatic=False, duration=5)
        self.assertEqual((result['start'], result['duration'], result['type'], result['subfolder']),
                         (1, 5, 'temp', 'zura_media'))
        for command in (inspect.call_args.args[0], encode.call_args.args[0]):
            self.assertIn('-protocol_whitelist', command)
            self.assertEqual(command[command.index('-protocol_whitelist') + 1], 'file,pipe')
            self.assertNotIn('hls', command[command.index('-format_whitelist') + 1].split(','))
            self.assertNotIn('concat', command[command.index('-format_whitelist') + 1].split(','))
            self.assertIn(str(self.clip.resolve()), command)

    def test_preview_cache_symlink_cannot_write_outside_temp(self):
        escape = self.root / 'outside-cache'
        escape.mkdir()
        try:
            (self.roots['temp'] / 'zura_media').symlink_to(escape, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Platform does not permit fixture symlinks')
        with self.assertRaisesRegex(ValueError, 'Choose local video'):
            media.cache_dir()

    def test_configured_media_root_alias_accepts_its_real_contained_path(self):
        alias = self.root / 'configured-input'
        try:
            alias.symlink_to(self.roots['input'], target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Platform does not permit fixture symlinks')
        with patch.object(folder_paths, 'get_input_directory', return_value=str(alias)):
            self.assertEqual(media.local_path('uploads/example.mp4'), self.clip.resolve())
            self.assertEqual(media.local_path(str(self.clip.resolve())), self.clip.resolve())

    def test_same_origin_and_nonbrowser_cli_are_allowed(self):
        for headers in ({}, {'Origin': 'http://127.0.0.1:8188'}, {'Origin': 'https://127.0.0.1:8188'}):
            media.require_same_origin(types.SimpleNamespace(headers=headers, host='127.0.0.1:8188'))
        for headers in ({'Origin': 'https://unrelated.example'}, {'Origin': 'null'},
                        {'Origin': 'http://127.0.0.1:8189'}, {'Sec-Fetch-Site': 'cross-site'}):
            with self.assertRaises(web.HTTPForbidden):
                media.require_same_origin(types.SimpleNamespace(headers=headers, host='127.0.0.1:8188'))


class Request:
    host = '127.0.0.1:8188'
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}
        self.body_reads = 0
    async def json(self):
        self.body_reads += 1
        return self.payload


class MediaHttpBoundaries(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        handlers = {}
        class Routes:
            def post(self, path):
                def add(handler):
                    handlers[path] = handler
                    return handler
                return add
        tree = ast.parse((v2_bootstrap.ROOT / '__init__.py').read_text(encoding='utf-8'))
        registration = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_register_routes')
        scope = {'__package__': 'ComfyUI_zura_nodes', 'asyncio': asyncio, 'web': web,
                 'PromptServer': types.SimpleNamespace(instance=types.SimpleNamespace(routes=Routes()))}
        exec(compile(ast.Module(body=[registration], type_ignores=[]), 'media-http-registration', 'exec'), scope)
        scope['_register_routes']()
        self.handlers = handlers

    async def test_http_remote_urls_rejected_before_network(self):
        with patch.object(media, 'download_video', wraps=media.download_video) as download, \
                patch.object(media.subprocess, 'check_output') as probe, \
                patch.object(media.subprocess, 'run') as encoder:
            for url in ('http://127.0.0.1:8188/private', 'http://192.168.1.1/private',
                        'http://169.254.169.254/private', 'https://example.com/video.mp4'):
                response = await self.handlers['/zura/preview_video'](Request({'url': url}))
                self.assertEqual(response.status, 400)
                self.assertIn('Choose local video', response.text)
            download.assert_not_called()
            probe.assert_not_called()
            encoder.assert_not_called()

    async def test_cross_origin_routes_reject_before_body_or_search(self):
        with patch.object(media, 'discover_video') as search, patch.object(media, 'preview_clip') as preview:
            for route in self.handlers.values():
                request = Request({'url': 'https://example.com'}, {'Origin': 'https://unrelated.example'})
                with self.assertRaises(web.HTTPForbidden):
                    await route(request)
                self.assertEqual(request.body_reads, 0)
            search.assert_not_called()
            preview.assert_not_called()


if __name__ == '__main__':
    unittest.main()
