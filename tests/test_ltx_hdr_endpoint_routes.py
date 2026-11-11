import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=package
routes=importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx_hdr_endpoint_routes')
native=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_source')
core=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class EndpointAssetTests(unittest.TestCase):
    def setUp(self):
        import OpenImageIO as oiio
        # Ownership/preview fixtures run without importing Comfy's GPU runtime.
        # These are the actual native nodes_images primary-transform constants
        # (Rec.709 D65 -> Rec.2020 D65 -> AP1 D60, Bradford adapted), not an
        # identity colour substitute. Pixel I/O remains real OpenImageIO.
        matrices=types.ModuleType('comfy_extras.nodes_images')
        matrices._REC709_TO_REC2020=(
            (0.6274038959346991,0.3292830383778837,0.0433130656874172),
            (0.0690972893582320,0.9195403950754587,0.0113623155663092),
            (0.0163914388751503,0.0880133078772259,0.8955952532476238))
        matrices._REC2020_TO_ACESCG=(
            (0.9748949779244186,0.0195991086370050,0.0055059134385761),
            (0.0021795627977041,0.9955354688932213,0.0022849683090752),
            (0.0047972396837727,0.0245320166345895,0.9706707436816380))
        colour_patch=patch.dict(sys.modules,{'comfy_extras.nodes_images':matrices})
        colour_patch.start();self.addCleanup(colour_patch.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        directory=self.root/'genj_studio'/'endpoint'
        self.frames=directory/'frames';self.frames.mkdir(parents=True)
        self.file=self.frames/'first.exr';self.pixels=np.full((16,32,3),4.,dtype=np.float32)
        spec=oiio.ImageSpec(32,16,3,oiio.FLOAT);spec.attribute('oiio:ColorSpace','ACEScg')
        writer=oiio.ImageOutput.create(str(self.file));self.assertTrue(writer.open(str(self.file),spec));self.assertTrue(writer.write_image(self.pixels));writer.close()
        self.original_sha=hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.manifest=directory/'hdr_sequence.json';self.manifest.write_text(json.dumps({'frames':[{'name':'first.exr','sha256':self.original_sha}]}))
        self.asset={'id':'endpoint','asset_kind':'hdr_sequence','count':1,'sha':hashlib.sha256(self.manifest.read_bytes()).hexdigest()}
        self.store=types.SimpleNamespace(load=lambda identity:self.asset)
        self.check=lambda asset:self.manifest
        self.input_patch=patch('folder_paths.get_input_directory',return_value=str(self.root));self.input_patch.start();self.addCleanup(self.input_patch.stop)

    def test_preview_keeps_scene_linear_hdr_reference(self):
        result=routes.endpoint_preview(self.store,self.check,'endpoint')
        self.assertEqual(result['asset_kind'],'hdr_endpoint')
        self.assertEqual((result['width'],result['height']),(32,16))
        self.assertTrue((self.root/result['preview']['subfolder']/result['preview']['filename']).is_file())
        self.assertEqual(hashlib.sha256(self.file.read_bytes()).hexdigest(),self.original_sha)
        descriptor,_=routes.resolve_endpoint(self.store,self.check,'endpoint')
        self.assertEqual(descriptor['manifest'],str(self.manifest))
        working,_=native.load_native_hdr_frames(self.frames,0,1,'auto',24.)
        restored=core.decode_ct(working).numpy()
        np.testing.assert_allclose(restored,self.pixels[None],rtol=1e-5)
        self.assertGreater(float(restored.max()),1.,'A preview must never replace the HDR reference used by generation')

    def test_rejects_modified_reference_and_sequence_instead_of_still(self):
        self.file.write_bytes(self.file.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):routes.resolve_endpoint(self.store,self.check,'endpoint')
        self.asset['count']=2
        with self.assertRaisesRegex(ValueError,'one uploaded EXR'):routes.resolve_endpoint(self.store,self.check,'endpoint')

    def test_colour_and_audio_validation_precedes_graph_submission(self):
        with self.assertRaisesRegex(ValueError,'colour'):routes.resolve_endpoint(self.store,self.check,'endpoint','srgb_display')
        with self.assertRaisesRegex(ValueError,'uploaded audio'):
            routes.prepare_graph(self.store,self.check,{'first_id':'endpoint','audio_enabled':True,'audio_file':'../outside.wav'})

    def test_setup_comes_from_native_graph_including_both_audio_paths(self):
        asset={'manifest':'readiness','sha':'0'*64}
        graphs=[routes.build_native_endpoint_graph(first=asset,last=asset,width=512,height=512,
            frames=9,prompt='Setup',prefix='setup',audio_file=audio) for audio in (None,'setup.wav')]
        mappings={node['class_type']:object() for graph in graphs for node in graph.values()}
        with patch.dict('os.environ',{'ZURA_LTX_HDR_ENDPOINTS':'1'}):
            result=routes.readiness(lambda *args:'installed',mappings)
            self.assertTrue(result['enabled']);self.assertTrue(result['ready'])
            files={item['filename'] for item in result['files']}
            self.assertIn('ltx-2.5-video-vae-bf16.safetensors',files)
            self.assertNotIn('ltx-2.5-video-vae-conv-bf16.safetensors',files)
            self.assertEqual(result['limits']['maxPixelFrames'],40_000_000)
            del mappings['LTXVVAEForceFloat32']
            missing=routes.readiness(lambda *args:None,mappings)
            self.assertFalse(missing['ready']);self.assertIn('LTXVVAEForceFloat32',missing['missingNodes'])


if __name__=='__main__':unittest.main()
