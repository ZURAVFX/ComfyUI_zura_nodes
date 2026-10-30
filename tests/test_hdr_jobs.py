"""A browser reconnect can inspect or cancel only its own HDR job."""
import asyncio
import importlib
import sys
import types
import unittest
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
jobs=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_jobs')
cancelled=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store').HDRChunkCancelled

class Job:
    def __init__(self):self.state='ready';self.entered=asyncio.Event();self.release=asyncio.Event();self.was_cancelled=False
    def snapshot(self):return {'state':self.state,'completed':0,'total':2,'active_prompt_id':None,'result':None,'error':None}
    async def run(self):
        self.state='rendering';self.entered.set();await self.release.wait()
        if self.was_cancelled:self.state='cancelled';raise cancelled('cancelled')
        self.state='complete'
    async def cancel(self):self.was_cancelled=True;self.release.set();return True

class HDRJobsTests(unittest.IsolatedAsyncioTestCase):
    async def test_reconnect_cancel_and_no_duplicate_submission(self):
        manager=jobs.HDRJobs();job=Job();identity='a'*32
        manager.start(job,{'id':identity,'frames':122});await job.entered.wait()
        self.assertEqual(manager.status(identity)['state'],'rendering')
        with self.assertRaisesRegex(ValueError,'already running'):manager.start(Job(),{'id':'b'*32})
        with self.assertRaisesRegex(ValueError,'not restarted'):manager.status('c'*32)
        await manager.cancel(identity);await manager.tasks[identity]
        self.assertEqual(manager.status(identity)['state'],'cancelled')
        self.assertEqual(manager.status(identity)['frames'],122)

    async def test_completed_job_can_be_followed_by_another(self):
        manager=jobs.HDRJobs(max_jobs=1);first=Job();manager.start(first,{'id':'d'*32})
        await first.entered.wait();first.release.set();await manager.tasks['d'*32]
        self.assertEqual(manager.status('d'*32)['state'],'complete')
        second=Job();manager.start(second,{'id':'e'*32});await second.entered.wait()
        with self.assertRaises(ValueError):manager.status('d'*32)
        await manager.cancel('e'*32);await manager.tasks['e'*32]

if __name__=='__main__':unittest.main()
