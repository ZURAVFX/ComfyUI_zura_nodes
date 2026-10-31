import asyncio
import importlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

import test_artist_studio

planner=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_plan')
comfy=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_comfy')


class FakeQueue:
    def __init__(self):self.history={}
    def get_history(self,identity):return {identity:self.history[identity]} if identity in self.history else {}
    def get_current_queue_volatile(self):return [],[]


class LongComfyTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_full_review_assembly_with_simulated_preview_children(self):
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:self.skipTest('FFmpeg required.')
        source={'file':'source.mp4','sha':'a'*64,'asset_kind':'video','duration':3,'width':1920,'height':1080}
        selection,parts,_=planner.plan_hdr_windows(source,start=.517,duration=1.,width=192,height=192,
            left=32,top=32,right=32,bottom=32,colour_space='pq_rec2020')
        queue=FakeQueue();server=types.SimpleNamespace(prompt_queue=queue);seen=[]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'output';out.mkdir()
            async def fake_submit(adapter,stage,graph):
                prefix=graph['save']['inputs']['filename_prefix'].split('/')[-1]
                dest=out/'genj'/'hdr_outpaint'/(prefix+'_00001_.mp4')
                count=graph['hdr_source']['inputs']['frame_count'];pid='review'+str(len(seen));seen.append(graph)
                subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=orange:s=192x192:r=24',
                    '-frames:v',str(count),'-c:v','libx264','-pix_fmt','yuv420p',str(dest)],check=True)
                queue.history[pid]={'status':{'status_str':'success'},'outputs':{'save':{'images':[{
                    'type':'output','subfolder':'genj/hdr_outpaint','filename':dest.name}]}}}
                adapter.on_prompt(pid);return pid
            with patch.object(comfy.ReviewedHDRQueue,'submit',fake_submit):
                job,details=comfy.create_long_hdr_review_job(server,source,selection,review_key=selection['review_key'],
                    output_root=out,check_asset=lambda _:None,ffmpeg=ffmpeg)
                result=await job.run()
            self.assertEqual(job.snapshot()['state'],'complete');self.assertEqual(details['frames'],24)
            self.assertEqual(len(seen),len(parts));self.assertTrue((out/result['subfolder']/result['filename']).is_file())
            self.assertEqual(len(list((out/'genj'/'hdr_outpaint').iterdir())),1,'only the assembled review remains')

    async def test_real_assembly_and_anchors_with_simulated_model_children(self):
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:self.skipTest('FFmpeg required.')
        source={'file':'source.mp4','sha':'a'*64,'asset_kind':'video','duration':3,'width':1920,'height':1080}
        selection,parts,_=planner.plan_hdr_windows(source,start=.517,duration=1.,width=192,height=192,
            left=32,top=32,right=32,bottom=32,colour_space='pq_rec2020')
        queue=FakeQueue();server=types.SimpleNamespace(prompt_queue=queue);seen=[]
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'output';inp=root/'input';out.mkdir();inp.mkdir()
            async def fake_submit(adapter,stage,graph):
                prefix=graph['stage_save']['inputs']['filename_prefix'].split('/')[-1]
                dest=out/'genj'/'hdr_outpaint'/(prefix+'_00001_.mp4')
                count=graph['trim_result']['inputs']['length'];pid='child'+str(len(seen));seen.append(graph)
                subprocess.run([ffmpeg,'-v','error','-f','lavfi','-i','color=c=blue:s=192x192:r=24',
                    '-frames:v',str(count),'-c:v','libx264','-pix_fmt','yuv420p',str(dest)],check=True)
                queue.history[pid]={'status':{'status_str':'success'},'outputs':{'stage_save':{'images':[{
                    'type':'output','subfolder':'genj/hdr_outpaint','filename':dest.name}]}}}
                adapter.on_prompt(pid);return pid
            class Conversion:
                def snapshot(self):return {'state':'ready'}
                async def run(self):return {'preview':'verified'}
            def make_conversion(server,asset,full,intermediate,**kwargs):
                self.assertTrue(Path(intermediate).is_file())
                return Conversion(),{}
            with patch.object(comfy.ReviewedHDRQueue,'submit',fake_submit), patch.object(comfy,'create_long_hdr_conversion',make_conversion), patch('ComfyUI_zura_nodes.artist_studio.hdr_chunk_comfy.staging_root',return_value=root/'stage'):
                job,details=comfy.create_long_hdr_outpaint_job(server,source,selection,review_key=selection['review_key'],
                    output_root=out,input_root=inp,check_asset=lambda _:None,ffmpeg=ffmpeg)
                result=await job.run()
            self.assertEqual(result,{'preview':'verified'});self.assertEqual(details['frames'],25)
            self.assertEqual(len(seen),len(parts));self.assertEqual(seen[1]['guide']['inputs']['latent'],['zura_anchor_i2v',0])
            self.assertEqual(list((out/'genj'/'hdr_outpaint').iterdir()),[],'all job-owned SDR files are removed')
            self.assertEqual(list((inp/'genj_studio').iterdir()),[],'generated anchor files are removed')

    async def test_cancel_targets_only_this_jobs_active_child(self):
        ffmpeg=shutil.which('ffmpeg')
        if not ffmpeg:self.skipTest('FFmpeg required.')
        source={'file':'source.mp4','sha':'a'*64,'asset_kind':'video','duration':3,'width':1920,'height':1080}
        selection,_,_=planner.plan_hdr_windows(source,start=.517,duration=1.,width=192,height=192,
            left=32,top=32,right=32,bottom=32,colour_space='pq_rec2020')
        class Queue:
            def __init__(self):self.running=[(0,'other',{})];self.pending=[];self.interrupted=[]
            def get_history(self,identity):return {}
            def get_current_queue_volatile(self):return self.running,self.pending
            def interrupt_if_running(self,identity):self.interrupted.append(identity);self.running=[v for v in self.running if v[1]!=identity]
            def delete_queue_item(self,predicate):self.pending=[v for v in self.pending if not predicate(v)]
        queue=Queue();server=types.SimpleNamespace(prompt_queue=queue);started=asyncio.Event()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'output';inp=root/'input';out.mkdir();inp.mkdir()
            async def fake_submit(adapter,stage,graph):
                queue.running.append((1,'ours',{}));adapter.on_prompt('ours');started.set();return 'ours'
            with patch.object(comfy.ReviewedHDRQueue,'submit',fake_submit), patch('ComfyUI_zura_nodes.artist_studio.hdr_chunk_comfy.staging_root',return_value=root/'stage'):
                job,_=comfy.create_long_hdr_outpaint_job(server,source,selection,review_key=selection['review_key'],
                    output_root=out,input_root=inp,check_asset=lambda _:None,ffmpeg=ffmpeg)
                task=asyncio.create_task(job.run());await started.wait();task.cancel()
                with self.assertRaises(asyncio.CancelledError):await task
            self.assertEqual(queue.interrupted,['ours']);self.assertEqual([v[1] for v in queue.running],['other'])
            self.assertEqual(job.snapshot()['state'],'cancelled');self.assertIsNone(job.snapshot()['active_prompt_id'])
            self.assertEqual(list((out/'genj'/'hdr_outpaint').iterdir()),[])
