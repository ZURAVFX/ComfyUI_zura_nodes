"""Exercise the HDR output-to-paintout route with real local video metadata."""
import asyncio
import importlib
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import v2_bootstrap

name = 'ComfyUI_zura_nodes.artist_studio'
if name not in sys.modules:
    package = types.ModuleType(name)
    package.__path__ = [str(v2_bootstrap.ROOT / 'artist_studio')]
    sys.modules[name] = package
studio = importlib.import_module(name + '.studio')


class HDRHandoffRouteTests(unittest.TestCase):
    def test_real_hlg_output_and_reject_sdr_and_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / 'genj' / 'hdr'; output.mkdir(parents=True)
            for name, hdr in [('hdr.mp4', True), ('sdr.mp4', False)]:
                cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                       'testsrc2=s=64x64:r=24', '-frames:v', '9', '-c:v', 'libx264']
                if hdr:
                    cmd += ['-pix_fmt', 'yuv420p10le', '-x264-params',
                            'colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc',
                            '-color_primaries', 'bt2020', '-color_trc', 'arib-std-b67', '-colorspace', 'bt2020nc']
                else:
                    cmd += ['-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709']
                subprocess.run(cmd + [str(output / name)], check=True)
            server = types.SimpleNamespace(routes=studio.web.RouteTableDef())
            module = types.ModuleType('server'); module.PromptServer = types.SimpleNamespace(instance=server)
            class Request:
                headers = {}; host = 'localhost'
                def __init__(self, ref): self.ref = ref
                async def json(self): return {'output_ref':self.ref}
            with patch.dict('os.environ', {'ZURA_HDR_LONG_PREVIEW':'0'}), \
                 patch.dict(sys.modules, {'server':module}), patch.object(studio, 'Studio'), \
                 patch.object(studio.folder_paths, 'get_folder_paths', return_value=[], create=True), \
                 patch.object(studio.folder_paths, 'get_output_directory', return_value=tmp):
                studio.register()
                handler = next(route.handler for route in server.routes if route.path == '/zura/studio/hdr/output/paintout')
                def call(ref):
                    response = asyncio.run(handler(Request(ref)))
                    return response.status, json.loads(response.text)
                ref = {'type':'output', 'subfolder':'genj/hdr', 'filename':'hdr.mp4'}
                status, result = call(ref)
                self.assertEqual(status, 200)
                self.assertEqual(result['colour_space'], 'hlg_rec2020')
                self.assertEqual(Path(result['path']), output / 'hdr.mp4')
                status, result = call({**ref, 'filename':'sdr.mp4'})
                self.assertEqual(status, 400)
                status, result = call({**ref, 'filename':'../hdr.mp4'})
                self.assertEqual(status, 400)


if __name__ == '__main__': unittest.main()
