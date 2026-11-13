"""CPU structural/media proof for true-N1 full-resolution LTX HDR stills."""
import asyncio,importlib,json,sys,tempfile,types,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import torch
import v2_bootstrap

for name,folder in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/folder)];sys.modules[name]=module
prepare=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_prepare')
sdr=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_studio')
native=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_native_job')
adapter=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_comfy')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
storage=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')

class StillN1Tests(unittest.TestCase):
    def test_uhd_still_spatial_pad_is_exact_and_does_not_hold_nine_frames(self):
        self.assertEqual(prepare.sdr_frame_limit(3840,2160),0,'The video padding budget remains unchanged')
        self.assertEqual(prepare.sdr_still_limit(3840,2160),1)
        readiness=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_readiness')
        self.assertEqual(readiness.frame_limit('sdr',3840,2160),0)
        self.assertEqual(readiness.frame_limit('sdr',3840,2160,single_frame=True),1)
        source=torch.full((1,2160,3840,3),.5,dtype=torch.float32);source[:,0,0]=.25;source[:,-1,-1]=.75
        result,w,h,n,pw,ph,pn=prepare.pad_sdr_guide(source,single_frame=True)
        self.assertEqual((w,h,n,pw,ph,pn),(3840,2160,1,3840,2176,1));self.assertEqual(result.shape,(1,2176,3840,3))
        self.assertTrue(torch.equal(result[:,:h,:w],source));self.assertLess(pw*ph*pn,prepare.MAX_PIXEL_FRAMES)
        with self.assertRaises(ValueError):prepare.pad_sdr_guide(torch.zeros((2,32,32,3)),single_frame=True)
        with patch.object(prepare,'MAX_PIXEL_FRAMES',1000),self.assertRaises(ValueError):prepare.pad_sdr_guide(torch.zeros((1,32,32,3)),single_frame=True)
    def test_still_graph_has_one_video_latent_tiled_encode_and_nonempty_dummy_audio(self):
        for fps in (1,24,25,30000/1001,60,120):
            info={'kind':'sequence','count':1,'width':3840,'height':2160,'files':['still.png']}
            with patch.object(paintout,'describe',return_value=info),patch.object(paintout,'selected_space',return_value='srgb_display'):
                graph,details=sdr.build_asset_graph({'asset_kind':'sdr_image'},{'frame_count':1,'sequence_fps':fps,'colour_space':'srgb_display','output':'acescg_exr','exr_storage':'float32'},lambda _:'still.png')
            self.assertEqual(graph['zura_hdr_prepare']['inputs']['single_frame'],True);self.assertEqual(graph['hdr_empty_video']['inputs']['length'],['zura_hdr_prepare',6])
            self.assertEqual(graph['hdr_guide']['inputs']['use_tiled_encode'],True);self.assertEqual(graph['hdr_guide']['inputs']['tile_size'],512)
            self.assertEqual(graph['hdr_empty_audio']['inputs']['frames_number'],9);self.assertGreater(round(9/fps*25),0)
            self.assertEqual(details['frames'],1);self.assertEqual(details['fps'],fps);self.assertFalse(details['has_audio'])
            self.assertNotIn('zura_hdr_audio_source',graph)
        video=sdr.build_hdr_graph(source='video.mp4',start_frame=0,frame_count=1,fps=25,prefix='video')
        self.assertNotIn('single_frame',video['zura_hdr_prepare']['inputs']);self.assertFalse(video['hdr_guide']['inputs']['use_tiled_encode'])
    def test_still_chunk_requires_explicit_flag_and_exactly_one_frame(self):
        with tempfile.TemporaryDirectory() as root,patch.object(adapter,'staging_root',return_value=Path(root)):
            plan=[importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks').HDRChunk(0,1,0)]
            stored=storage.HDRChunkStore(root,'a'*32,plan,64,64,create=True)
            adapter.ZuraHDRWriteChunk().write(torch.zeros((1,64,64,3)),'a'*32,0,1,64,64,121,8,0,single_frame=True)
            self.assertEqual(stored.read(0).shape,(1,64,64,3))
            for patch_args in ({'total_frames':2},{'start_frame':1},{'chunk_index':1}):
                args={'images':torch.zeros((1,64,64,3)),'job_id':'b'*32,'start_frame':0,'total_frames':1,'width':64,'height':64,'max_frames':121,'overlap':8,'chunk_index':0,'single_frame':True}|patch_args
                with self.assertRaises(ValueError):adapter.ZuraHDRWriteChunk().write(**args)

class Queue:
    def __init__(self):self.items=[];self.history={};self.graphs=[]
    def put(self,item):self.items.append(item);self.graphs.append(item[2]);asyncio.get_running_loop().call_soon(self.complete,item)
    def complete(self,item):
        inputs=item[2]['zura_hdr_stage_chunk']['inputs'].copy();inputs.pop('images')
        assert inputs['single_frame'] is True
        adapter.ZuraHDRWriteChunk().write(torch.full((1,inputs['height'],inputs['width'],3),.3),**inputs)
        self.items.remove(item);self.history[item[1]]={'status':{'status_str':'success'},'outputs':{'zura_hdr_stage_chunk':{'text':['done']}}}
    def get_history(self,identity):return {identity:self.history[identity]} if identity in self.history else {}
    def get_current_queue_volatile(self):return [],self.items
    def interrupt_if_running(self,identity):pass
    def delete_queue_item(self,predicate):self.items=[item for item in self.items if not predicate(item)]

class StillN1CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_uhd_one_frame_coordinator_and_actual_exr_preview_codec(self):
        import av,OpenImageIO as oiio
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);queue=Queue();server=types.SimpleNamespace(prompt_queue=queue,number=0,trigger_on_prompt=lambda value:value,node_replace_manager=types.SimpleNamespace(apply_replacements=lambda graph:None))
            async def validate(*args):return True,None,['zura_hdr_stage_chunk'],{}
            info={'kind':'sequence','count':1,'width':3840,'height':2160,'files':['still.png']}
            body={'mode':'sdr','frame_count':1,'sequence_fps':25,'colour_space':'srgb_display','output':'acescg_exr','exr_storage':'float32'}
            with patch.object(native,'staging_root',return_value=root/'stage'),patch.object(adapter,'staging_root',return_value=root/'stage'),patch.object(paintout,'describe',return_value=info),patch.object(paintout,'selected_space',return_value='srgb_display'),patch.dict(sys.modules,{'execution':types.SimpleNamespace(validate_prompt=validate)}):
                job,summary=native.create_sdr_job(server,{'asset_kind':'sdr_image'},body,lambda _:'still.png',root);result=await job.run()
            self.assertEqual(len(queue.graphs),1);self.assertEqual(summary['frames'],1);self.assertEqual(result['frames'],1);self.assertEqual(result['fps'],25)
            with zipfile.ZipFile(result['files'][0]) as archive:
                self.assertEqual(archive.namelist(),['frame_00000.exr']);frame=root/'check.exr';frame.write_bytes(archive.read('frame_00000.exr'))
            inp=oiio.ImageInput.open(str(frame));self.assertEqual((inp.spec().width,inp.spec().height),(3840,2160));inp.close()
            with av.open(result['preview']) as media:
                stream=media.streams.video[0];self.assertEqual((stream.width,stream.height),(3840,2160));self.assertEqual(str(stream.average_rate),'25');self.assertEqual(sum(1 for _ in media.decode(stream)),1)
