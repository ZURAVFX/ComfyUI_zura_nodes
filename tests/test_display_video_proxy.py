"""Display video is a derivative; generation still addresses the exact original."""
import hashlib
import importlib
import io
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest

import av
import numpy as np
from PIL import Image

import v2_bootstrap

artist_package = types.ModuleType('ComfyUI_zura_nodes.artist_studio')
artist_package.__path__ = [str(Path(__file__).resolve().parents[1] / 'artist_studio')]
sys.modules['ComfyUI_zura_nodes.artist_studio'] = artist_package
paintout_package = types.ModuleType('ComfyUI_zura_nodes.paintout')
paintout_package.__path__ = [str(Path(__file__).resolve().parents[1] / 'paintout')]
sys.modules['ComfyUI_zura_nodes.paintout'] = paintout_package

display = importlib.import_module('ComfyUI_zura_nodes.artist_studio.display_view_routes')
proxy = importlib.import_module('ComfyUI_zura_nodes.artist_studio.display_video_proxy')
ocio = importlib.import_module('ComfyUI_zura_nodes.comfylink.display_view')


class Store:
    def __init__(self, path, digest):
        self.path, self.digest = path, digest

    def load(self, identity):
        if identity != 'a' * 32:
            raise ValueError('Unknown asset')
        return {'asset_kind': 'video', 'sha': self.digest, 'file': self.path.name}


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg tools are required')
class DisplayVideoTests(unittest.TestCase):
    def test_actual_ocio_pixels_timing_audio_cache_and_original_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'original.mp4'
            command = [shutil.which('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y',
                       '-f', 'lavfi', '-i', 'color=c=0x756341:size=64x48:rate=24:duration=2',
                       '-f', 'lavfi', '-i', 'sine=frequency=500:duration=2',
                       '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(source)]
            subprocess.run(command, check=True)
            original = source.read_bytes()
            digest = hashlib.sha256(original).hexdigest()
            store = Store(source, digest)
            roots = {'input': root, 'output': root, 'temp': root / 'temp'}
            selector = {'asset_id': 'a' * 32}
            config = ocio.describe()
            body = {'source': selector, 'colour_space': 'srgb_display', 'config': config['config'],
                    'display': config['display'], 'view': config['view']}
            result = proxy.prepare(body, store, lambda asset: source, roots)
            self.assertTrue(result['preview_only'])
            self.assertEqual(result['source_sha256'], digest)
            path = proxy.lookup(result['url'].rsplit('/', 1)[-1])
            with av.open(str(path)) as output:
                self.assertEqual(output.streams.video[0].average_rate.numerator, 24)
                self.assertEqual(output.streams.video[0].average_rate.denominator, 1)
                self.assertTrue(output.streams.audio)
                frames = list(output.decode(video=0))
                self.assertEqual(len(frames), 48)
                shown = frames[12].to_ndarray(format='rgb24').astype(np.int16)
            paused, _, _ = display.preview({**body, 'frame': 12}, store, lambda asset: source, roots,
                                            return_metadata=True)
            reference = np.asarray(Image.open(io.BytesIO(paused)).convert('RGB')).astype(np.int16)
            self.assertLessEqual(int(np.max(np.abs(shown - reference))), 12)
            repeated = proxy.prepare(body, store, lambda asset: source, roots)
            self.assertEqual(proxy.lookup(repeated['url'].rsplit('/', 1)[-1]), path)
            stamp = display._stamp(source)
            grants = []
            try:
                for colour in ('srgb_display', 'rec709_gamma24'):
                    token = 'different-interpretation-' + colour
                    grants.append(token)
                    display._sources[token] = {'path': source, 'stamp': stamp, 'files': [(source, stamp)],
                                               'colour': colour, 'expires': time.monotonic() + 120}
                variants = [proxy.prepare({**body, 'source': {'source_token': token}, 'colour_space': 'auto'},
                                          store, lambda asset: source, roots) for token in grants]
                paths = [proxy.lookup(item['url'].rsplit('/', 1)[-1]) for item in variants]
                self.assertNotEqual(paths[0], paths[1], 'Auto must cache by resolved colour, not the same request spelling')
                self.assertEqual([item['source_sha256'] for item in variants], [digest, digest])
                with av.open(str(paths[0])) as first, av.open(str(paths[1])) as second:
                    a = next(first.decode(video=0)).to_ndarray(format='rgb24')
                    b = next(second.decode(video=0)).to_ndarray(format='rgb24')
                    self.assertGreater(int(np.max(np.abs(a.astype(int) - b.astype(int)))), 3)
            finally:
                for token in grants:
                    display._sources.pop(token, None)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(store.load('a' * 32)['sha'], digest)
            with self.assertRaises(ValueError):
                proxy.prepare({**body, 'source': {'asset_id': 'b' * 32}}, store, lambda asset: source, roots)


if __name__ == '__main__':
    unittest.main()
