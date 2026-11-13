"""Typed still-to-HDR preparation preserves one frame and its selected clock."""
import importlib,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import v2_bootstrap

for name,folder in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/folder)];sys.modules[name]=package
output=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_output')
hdr=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_studio')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
service=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_long_service')

class Routes:
    def __init__(self):self.handlers={}
    def post(self,path):
        def add(handler):self.handlers[path]=handler;return handler
        return add

class StillHDRTests(unittest.IsolatedAsyncioTestCase):
    def make_image(self,root,name='result.png',alpha=False):
        path=Path(root)/name;Image.new('RGBA' if alpha else 'RGB',(512,288),(10,20,30,128) if alpha else (10,20,30)).save(path);return path
    async def test_output_image_is_explicit_and_never_discards_alpha(self):
        with tempfile.TemporaryDirectory() as root:
            path=self.make_image(root);ref={'filename':path.name,'type':'output'}
            self.assertEqual(output.selected_image_output(root,ref),path.resolve())
            with self.assertRaises(ValueError):output.selected_output(root,ref)
            for bad in ({**ref,'filename':'../result.png'},{**ref,'type':'input'},{**ref,'filename':'missing.png'}):
                with self.assertRaises(ValueError):output.selected_image_output(root,bad)
            self.make_image(root,'transparent.png',True)
            with self.assertRaisesRegex(ValueError,'alpha-preserving'):
                output.selected_image_output(root,{**ref,'filename':'transparent.png'})
            Image.new('RGB',(32,32)).save(Path(root)/'bad-profile.png',icc_profile=b'not a valid profile')
            with self.assertRaisesRegex(ValueError,'profile'):
                output.selected_image_output(root,{**ref,'filename':'bad-profile.png'})
    async def test_real_still_builds_one_frame_at_25_and_fractional_cadence(self):
        for numerator,denominator in ((25,1),(30000,1001)):
            with tempfile.TemporaryDirectory() as root:
                path=self.make_image(root)
                clock={'numerator':numerator,'denominator':denominator}
                contract={'schemaVersion':1,'frameCount':1,'modelFrames':1,'trimFrames':1,'width':512,'height':288,'frameRate':clock,'sessionId':'a'*32}
                info={'kind':'sequence','count':1,'width':512,'height':288,'files':[str(path)]}
                body={'frame_count':1,'sequence_fps':numerator/denominator,'colour_space':'srgb_display','output':'acescg_exr','exr_storage':'float32','ae_frame_contract':contract}
                with patch.object(paintout,'describe',return_value=info),patch.object(paintout,'selected_space',return_value='srgb_display'):
                    graph,details=hdr.build_asset_graph({'asset_kind':'sdr_image'},body,lambda _:path)
                    with self.assertRaisesRegex(ValueError,'exactly'):
                        hdr.build_asset_graph({'asset_kind':'sdr_image'},{**body,'frame_count':2},lambda _:path)
                self.assertEqual(details['frames'],1);self.assertFalse(details['has_audio']);self.assertEqual(details['fps'],numerator/denominator)
                self.assertEqual(graph['zura_hdr_source']['inputs']['frame_count'],1)
                self.assertEqual(graph['zura_hdr_source']['inputs']['sequence_fps'],numerator/denominator)
                guards=[node for node in graph.values() if node['class_type']=='ZuraComfyLinkMatchFrames']
                self.assertTrue(guards);self.assertTrue(all(node['inputs']['frame_count']==1 for node in guards))
    async def test_still_source_info_uses_real_raster_and_contract_clock(self):
        with tempfile.TemporaryDirectory() as root:
            path=self.make_image(root);route=Routes();hdr.register(types.SimpleNamespace(store=None),route,lambda f:f,lambda _:None)
            contract={'schemaVersion':1,'frameCount':1,'modelFrames':1,'trimFrames':1,'width':512,'height':288,'frameRate':{'numerator':30000,'denominator':1001},'sessionId':'a'*32}
            body={'source_kind':'output_image','output_ref':{'filename':path.name,'type':'output'},'sequence_fps':24,'ae_frame_contract':contract}
            class Request:
                async def json(self):return body
            with patch('folder_paths.get_output_directory',return_value=root),patch.object(paintout,'describe',return_value={'kind':'sequence','count':1,'width':512,'height':288}):
                data=json.loads((await route.handlers['/zura/studio/hdr/source-info'](Request())).text)
                self.assertEqual(data['frames'],1);self.assertEqual(data['fps'],30000/1001)
                body['ae_frame_contract']={**contract,'width':514}
                with self.assertRaises(ValueError):await route.handlers['/zura/studio/hdr/source-info'](Request())
            client=service.HDRLongService(None,None,None,root,check_setup=lambda *_:None)
            asset,check=client._asset({'source_kind':'output_image','output_ref':{'filename':path.name,'type':'output'}})
            self.assertEqual(asset['asset_kind'],'sdr_image');self.assertEqual(check(asset),path.resolve())
