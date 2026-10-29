"""Sequential HDR execution and cancellation races."""
import asyncio
import importlib
import sys
import tempfile
import types
import unittest

import torch
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
chunk=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
storage=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')
runner=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_runner')


class HDRChunkRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_once_and_stages_in_order(self):
        with tempfile.TemporaryDirectory() as root:
            plan=[chunk.HDRChunk(0,9,0),chunk.HDRChunk(5,9,4)]
            store=storage.HDRChunkStore(root,'a'*32,plan,1,1,create=True)
            seen=[]
            async def render(index,part):
                seen.append(index)
                async def completed():return torch.full((part.count,1,1,3),.2)
                return str(index),completed()
            async def export(staged):return len(torch.cat(list(staged.stitched())))
            async def cancel_prompt(prompt):self.fail('No prompt should be cancelled.')
            job=runner.HDRChunkRunner(store,render,export,cancel_prompt)
            self.assertEqual(await job.run(),14)
            self.assertEqual((seen,job.state,job.completed),([0,1],'complete',2))
            with self.assertRaises(ValueError):await job.run()

    async def test_cancel_during_submission_interrupts_its_prompt(self):
        with tempfile.TemporaryDirectory() as root:
            store=storage.HDRChunkStore(root,'b'*32,[chunk.HDRChunk(0,3,0)],1,1,create=True)
            entered=asyncio.Event();release=asyncio.Event();cancelled=[]
            async def render(index,part):
                entered.set();await release.wait()
                async def completion():return torch.zeros(part.count,1,1,3)
                return 'own-prompt',completion()
            async def cancel_prompt(prompt):cancelled.append(prompt)
            async def export(staged):self.fail('Cancelled job cannot export.')
            job=runner.HDRChunkRunner(store,render,export,cancel_prompt)
            task=asyncio.create_task(job.run());await entered.wait();await job.cancel();release.set()
            with self.assertRaises(storage.HDRChunkCancelled):await task
            self.assertEqual(cancelled,['own-prompt']);self.assertEqual(job.state,'cancelled')

    async def test_failed_render_does_not_export_or_submit_next(self):
        with tempfile.TemporaryDirectory() as root:
            plan=[chunk.HDRChunk(0,9,0),chunk.HDRChunk(5,9,4)]
            store=storage.HDRChunkStore(root,'c'*32,plan,1,1,create=True);submitted=[]
            async def render(index,part):
                submitted.append(index)
                async def completion():raise RuntimeError('sampler failed')
                return 'prompt',completion()
            async def cancel_prompt(prompt):pass
            async def export(staged):self.fail('Failed job cannot export.')
            job=runner.HDRChunkRunner(store,render,export,cancel_prompt)
            with self.assertRaisesRegex(RuntimeError,'sampler failed'):await job.run()
            self.assertEqual((submitted,job.state),([0],'failed'))


if __name__=='__main__':unittest.main()
