"""The native HDR coordinator carries the retained FLOAT alpha to publication."""
import asyncio,importlib,json,sys,tempfile,types,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import v2_bootstrap
from test_hdr_chunk_native_job import SimulatedQueue

for name,folder in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/folder)];sys.modules[name]=package
native=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_native_job')
adapter=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_comfy')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
sdr=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_studio')
matte=importlib.import_module('ComfyUI_zura_nodes.artist_studio.alpha_matte')
service=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_long_service')

class AlphaHDRPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_source_selector_native_job_and_real_exr_keep_alpha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'beauty.mov';source.write_bytes(b'RGB source is inspected by the test fixture')
            writer=matte.AlphaFloatWriter(root,{'frame_count':9,'width':32,'height':32,'start_frame':0,'fps_rational':'25'})
            for i in range(9):writer.write(i,np.full((32,32),.31415927,dtype=np.float32))
            ref=writer.finish();body={'source_kind':'output','output_ref':{'filename':source.name,'type':'output'},'alpha_ref':ref,'mode':'sdr','frame_count':9,'output':'acescg_exr','exr_storage':'half'}
            client=service.HDRLongService(None,None,None,root,check_setup=lambda *_:None)
            asset,check=client._asset(body);self.assertEqual(asset['hdr_alpha_ref'],ref)
            queue=SimulatedQueue();server=types.SimpleNamespace(prompt_queue=queue,number=0,trigger_on_prompt=lambda value:value,node_replace_manager=types.SimpleNamespace(apply_replacements=lambda graph:None))
            async def validate(*_):return True,None,['zura_hdr_stage_chunk'],{}
            def graph(asset,body,check):return {'hdr_unpad_raster':{'class_type':'stub','inputs':{}}},{'width':32,'height':32,'fps':25.,'has_audio':False,'output':body['output'],'exr_storage':body['exr_storage']}
            with patch.object(native,'staging_root',return_value=root/'stage'),patch.object(adapter,'staging_root',return_value=root/'stage'),patch.object(sdr,'build_asset_graph',side_effect=graph),patch.object(paintout,'describe',return_value={'kind':'video','count':9,'width':32,'height':32,'fps':25.,'fps_rational':'25'}),patch.dict(sys.modules,{'execution':types.SimpleNamespace(validate_prompt=validate)}):
                job,summary=native.create_sdr_job(server,asset,body,check,root);result=await job.run()
            self.assertEqual(queue.submissions,1);self.assertEqual(result['alphaAssociation'],'straight');self.assertEqual(result['layout'],'RGBA');self.assertEqual(result['exr_storage'],'float32');self.assertEqual(summary['exr_storage'],'float32')
            with zipfile.ZipFile(result['files'][0]) as archive:
                proof=json.loads(archive.read('zura_hdr_delivery.json'));self.assertEqual(proof['frameCount'],9);self.assertEqual(proof['frameRate'],{'numerator':25,'denominator':1})
                self.assertEqual(proof['alphaSource']['kind'],'alpha_float32');self.assertEqual(len(proof['frames']),9)
            self.assertTrue((root/ref['subfolder']/ref['filename']).exists(),'Conversion never removes the retained source alpha')
