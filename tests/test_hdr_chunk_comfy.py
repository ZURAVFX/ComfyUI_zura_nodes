"""Comfy HDR chunk adapter stages only its own validated prompts."""
import asyncio
import importlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import torch
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
chunks=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
storage=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')
adapter=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_comfy')
native=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_graph')


class Queue:
    def __init__(self):self.items=[];self.history={};self.interrupted=[]
    def put(self,item):self.items.append(item)
    def get_history(self,identity):return {identity:self.history[identity]} if identity in self.history else {}
    def get_current_queue_volatile(self):return [],self.items
    def interrupt_if_running(self,identity):self.interrupted.append(identity)
    def delete_queue_item(self,predicate):self.items=[item for item in self.items if not predicate(item)]


class HDRChunkComfyTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_graph_is_pruned_and_its_output_staged(self):
        with tempfile.TemporaryDirectory() as root:
            plan=chunks.plan_chunks(3,130,384,224)
            store=storage.HDRChunkStore(root,'a'*32,plan,384,224,create=True)
            graph=native.build_native_video_graph(source='input.mp4',start_frame=plan[0].start,
                frame_count=plan[0].count,fps=24,width=384,height=224,prefix='demo')
            prepared=adapter.chunk_graph(graph,store,0,'trim_raster')
            self.assertNotIn('zura_hdr_save_video',prepared)
            self.assertEqual(prepared['zura_hdr_stage_chunk']['inputs']['images'],['trim_raster',0])
            self.assertEqual(prepared['source']['inputs']['frame_count'],plan[0].count)
            inputs=prepared['zura_hdr_stage_chunk']['inputs'].copy();inputs.pop('images')
            with patch.object(adapter,'staging_root',return_value=root):
                result=adapter.ZuraHDRWriteChunk().write(torch.zeros(plan[0].count,224,384,3),**inputs)
            self.assertIn('text',result['ui']);self.assertEqual(len(store.read(0)),plan[0].count)
            following=native.build_native_video_graph(source='input.mp4',start_frame=plan[1].start,
                frame_count=plan[1].count,fps=24,width=384,height=224,prefix='demo')
            anchored=adapter.chunk_graph(following,store,1,'trim_raster',anchor_strength=1.)
            self.assertEqual(anchored['zura_hdr_anchor_guide1']['inputs']['positive'],['guide1',0])
            self.assertEqual(anchored['sample1']['inputs']['positive'],['zura_hdr_anchor_guide1',0])
            self.assertEqual(anchored['sample2']['inputs']['positive'],['zura_hdr_anchor_guide2',0])
            self.assertEqual(anchored['guide1']['inputs']['image'],['resize1',0])
            with patch.object(adapter,'staging_root',return_value=root):
                anchor=adapter.ZuraHDRReadChunkAnchor().read(**anchored['zura_hdr_previous_anchor']['inputs'])[0]
            self.assertEqual(tuple(anchor.shape),(1,224,384,3))
            i2v=adapter.chunk_graph(following,store,1,'trim_raster',anchor_strength=1.,anchor_mode='i2v')
            self.assertEqual(i2v['zura_hdr_anchor_guide1']['class_type'],'LTXVImgToVideoInplace')
            self.assertEqual(i2v['zura_hdr_anchor_guide1']['inputs']['latent'],['empty',0])
            self.assertEqual(i2v['guide1']['inputs']['latent'],['zura_hdr_anchor_guide1',0])
            self.assertEqual(i2v['zura_hdr_anchor_guide2']['inputs']['latent'],['upsample',0])
            self.assertEqual(i2v['guide2']['inputs']['latent'],['zura_hdr_anchor_guide2',0])
            self.assertEqual(i2v['sample1']['inputs']['positive'],['guide1',0])

    async def test_submits_once_and_reads_only_own_history(self):
        with tempfile.TemporaryDirectory() as root:
            plan=chunks.plan_chunks(0,2,32,32);store=storage.HDRChunkStore(root,'b'*32,plan,32,32,create=True)
            queue=Queue()
            server=types.SimpleNamespace(prompt_queue=queue,number=0,
                trigger_on_prompt=lambda value:value,
                node_replace_manager=types.SimpleNamespace(apply_replacements=lambda graph:None))
            async def validate(*args):return True,None,['zura_hdr_stage_chunk'],{}
            fake=types.SimpleNamespace(validate_prompt=validate)
            with patch.dict(sys.modules,{'execution':fake}):
                renderer=adapter.ComfyHDRRenderer(server,store,lambda part:{'trim':{'class_type':'stub','inputs':{}}},'trim')
                identity,completion=await renderer.submit(0,plan[0])
                self.assertEqual(queue.items[0][1],identity)
                queue.history[identity]={'status':{'status_str':'success'},'outputs':{'zura_hdr_stage_chunk':{'text':['ok']}}}
                self.assertIsNone(await completion)
                await renderer.cancel(identity)
                self.assertEqual(queue.interrupted,[identity]);self.assertEqual(queue.items,[])

    async def test_missing_staging_output_is_rejected(self):
        queue=Queue();identity='c'*32
        queue.history[identity]={'status':{'status_str':'success'},'outputs':{}}
        server=types.SimpleNamespace(prompt_queue=queue)
        store=types.SimpleNamespace(cancelled=asyncio.Event())
        with self.assertRaisesRegex(RuntimeError,'did not stage'):
            await adapter.ComfyHDRRenderer(server,store,None,None)._wait(identity)


if __name__=='__main__':unittest.main()
