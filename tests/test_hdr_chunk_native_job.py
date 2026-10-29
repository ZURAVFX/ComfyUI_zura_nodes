"""Internal multi-prompt job integration using a simulated Comfy worker."""
import asyncio
import importlib
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import av
import torch
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
native=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_native_job')
adapter=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_comfy')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class SimulatedQueue:
    def __init__(self):self.queue=[];self.history={};self.submissions=0
    def put(self,item):
        self.queue.append(item);self.submissions+=1
        asyncio.get_running_loop().call_soon(self.complete,item)
    def complete(self,item):
        identity=item[1];inputs=item[2]['zura_hdr_stage_chunk']['inputs'].copy();inputs.pop('images')
        plan=adapter.plan_chunks(inputs['start_frame'],inputs['total_frames'],inputs['width'],inputs['height'],overlap=inputs['overlap'],max_frames=inputs['max_frames'])
        adapter.ZuraHDRWriteChunk().write(torch.full((plan[inputs['chunk_index']].count,32,32,3),.3),**inputs)
        self.queue.remove(item)
        self.history[identity]={'status':{'status_str':'success'},'outputs':{'zura_hdr_stage_chunk':{'text':['done']}}}
    def get_history(self,identity):return {identity:self.history[identity]} if identity in self.history else {}
    def get_current_queue_volatile(self):return [],self.queue
    def interrupt_if_running(self,identity):pass
    def delete_queue_item(self,predicate):self.queue=[item for item in self.queue if not predicate(item)]


class HDRNativeLongJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_insufficient_staging_disk_fails_before_queueing(self):
        with tempfile.TemporaryDirectory() as root:
            queue=SimulatedQueue();server=types.SimpleNamespace(prompt_queue=queue)
            details={'width':32,'height':32,'fps':24.,'has_audio':False,'output':'acescg_exr'}
            with patch.object(native,'staging_root',return_value=Path(root)/'stage'), \
                 patch.object(native,'build_asset_graph',return_value=({},details)), \
                 patch.object(native.shutil,'disk_usage',return_value=types.SimpleNamespace(free=0)), \
                 patch.object(paintout,'describe',return_value={'count':122,'width':32,'height':32}):
                with self.assertRaisesRegex(ValueError,'disk space'):
                    native.create_native_job(server,{'asset_kind':'video'},
                        {'start_frame':0,'frame_count':122},lambda _:Path(root)/'source.mp4',root)
            self.assertEqual(queue.submissions,0)

    async def test_two_prompts_produce_one_complete_video_and_exr_archive(self):
        ffmpeg=shutil.which('ffmpeg') or 'D:/ComfyUI/python_embeded/ffmpeg-bin/ffmpeg.exe'
        if not Path(ffmpeg).exists():self.skipTest('FFmpeg not installed')
        with tempfile.TemporaryDirectory() as root:
            queue=SimulatedQueue()
            server=types.SimpleNamespace(prompt_queue=queue,number=0,trigger_on_prompt=lambda value:value,
                node_replace_manager=types.SimpleNamespace(apply_replacements=lambda graph:None))
            async def validate(*args):return True,None,['zura_hdr_stage_chunk'],{}
            fake=types.SimpleNamespace(validate_prompt=validate)
            details={'width':32,'height':32,'fps':24.,'has_audio':False,'output':'hlg_and_exr'}
            def graph(asset,body,check):
                return {'trim_raster':{'class_type':'stub','inputs':{}},'zura_hdr_save_video':{'class_type':'stub','inputs':{}}},details
            with patch.object(native,'staging_root',return_value=Path(root)/'stage'), \
                 patch.object(adapter,'staging_root',return_value=Path(root)/'stage'), \
                 patch.object(native,'build_asset_graph',side_effect=graph), \
                 patch.object(paintout,'describe',return_value={'count':122,'width':32,'height':32}), \
                 patch.object(paintout,'native_colour',side_effect=lambda frames,*args:frames), \
                 patch.dict(sys.modules,{'execution':fake}):
                job,summary=native.create_native_job(server,{'asset_kind':'video'},
                    {'start_frame':0,'frame_count':122},lambda _:Path(root)/'source.mp4',root,ffmpeg=ffmpeg)
                result=await job.run()
            self.assertEqual((summary['chunks'],queue.submissions,job.state),(2,2,'complete'))
            paths=[Path(path) for path in result['files']]
            with zipfile.ZipFile(next(path for path in paths if path.suffix=='.zip')) as archive:
                self.assertEqual(len(archive.namelist()),122)
            with av.open(str(next(path for path in paths if path.suffix=='.mp4'))) as container:
                self.assertEqual(sum(1 for _ in container.decode(video=0)),122)


if __name__=='__main__':unittest.main()
