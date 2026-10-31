import asyncio, importlib, json, subprocess, sys, tempfile, types, unittest
from pathlib import Path
from unittest.mock import patch
import v2_bootstrap

for name, folder in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'), ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        package = types.ModuleType(name); package.__path__ = [str(v2_bootstrap.ROOT / folder)]; sys.modules[name] = package
hdr = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_studio')
paintout = importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')

class Routes:
    def __init__(self): self.handlers = {}
    def post(self, path):
        def decorator(handler): self.handlers[path] = handler; return handler
        return decorator

class HDRSourceInfoTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_video_frame_count_and_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            video=Path(tmp)/'take.mp4'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=black:s=96x64:r=24000/1001',
                            '-frames:v','72','-c:v','libx264','-pix_fmt','yuv420p',str(video)],check=True)
            route=Routes();hdr.register(types.SimpleNamespace(store=None),route,lambda f:f,lambda x:None)
            class Request:
                async def json(self):return {'source_kind':'output','output_ref':{'type':'output','filename':'take.mp4','subfolder':''}}
            with patch('folder_paths.get_output_directory',return_value=tmp):
                data=json.loads((await route.handlers['/zura/studio/hdr/source-info'](Request())).text)
            self.assertEqual((data['frames'],data['width'],data['height']),(72,96,64))
            self.assertAlmostEqual(data['fps'],24000/1001,places=6)

    async def test_selected_output_is_bounded_and_uses_real_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); video=root/'take.mp4';video.write_bytes(b'fixture')
            route=Routes();hdr.register(types.SimpleNamespace(store=None),route,lambda f:f,lambda x:None)
            handler=route.handlers['/zura/studio/hdr/source-info']
            class Request:
                def __init__(self,body):self.body=body
                async def json(self):return self.body
            body={'source_kind':'output','output_ref':{'type':'output','filename':'take.mp4','subfolder':''}}
            info={'kind':'video','count':72,'width':1280,'height':720,'fps':24}
            with patch('folder_paths.get_output_directory',return_value=tmp),patch.object(paintout,'describe',return_value=info):
                result=await handler(Request(body))
                self.assertEqual(json.loads(result.text),{'frames':72,'width':1280,'height':720,'fps':24})
                body['output_ref']['filename']='../outside.mp4'
                with self.assertRaises(ValueError):await handler(Request(body))
                with self.assertRaises(ValueError):await handler(Request({'source_kind':'other','path':str(video)}))

if __name__=='__main__':unittest.main()
