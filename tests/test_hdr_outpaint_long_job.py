import asyncio
import importlib
import threading
import unittest

import test_artist_studio

module=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_long_job')


class LongJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_both_stages_and_cleans_intermediate(self):
        events=[]
        async def sdr(update):update('running',1,2);events.append('sdr');return 'owned.mp4'
        class Conversion:
            def snapshot(self):return {'state':'running'}
            async def run(self):events.append('hdr');return {'preview':'result.mp4'}
        def create(path):self.assertEqual(path,'owned.mp4');return Conversion(),{'id':'conversion'}
        async def cleanup(path):events.append(('cleanup',path))
        job=module.LongHDROutpaintJob(sdr,create,cleanup,'owned.mp4')
        self.assertEqual(await job.run(),{'preview':'result.mp4'})
        self.assertEqual(job.snapshot()['state'],'complete')
        self.assertEqual(job.conversion_details['id'], 'conversion')
        self.assertEqual(events,['sdr','hdr',('cleanup','owned.mp4')])

    async def test_cancel_hdr_waits_for_active_conversion(self):
        entered,release=asyncio.Event(),asyncio.Event();events=[]
        async def sdr(update):return 'owned.mp4'
        class Conversion:
            def snapshot(self):return {'state':'running'}
            async def run(self):entered.set();await release.wait();raise module.HDRChunkCancelled()
            async def cancel(self):events.append('cancel');release.set()
        async def cleanup(path):events.append(('cleanup',path))
        job=module.LongHDROutpaintJob(sdr,lambda path:(Conversion(),{}),cleanup,'owned.mp4')
        task=asyncio.create_task(job.run());await entered.wait();task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(events,['cancel',('cleanup','owned.mp4')]);self.assertEqual(job.state,'cancelled')

    async def test_cancel_during_preflight_cleans_created_staging(self):
        entered,release=threading.Event(),threading.Event();events=[]
        async def sdr(update):return 'owned.mp4'
        def create(path):
            entered.set();release.wait(5)
            return type('Conversion',(),{'store':type('Store',(),{'cleanup':lambda self:events.append('staging-clean')})()})(),{}
        async def cleanup(path):events.append(('cleanup',path))
        job=module.LongHDROutpaintJob(sdr,create,cleanup,'owned.mp4')
        task=asyncio.create_task(job.run());self.assertTrue(await asyncio.to_thread(entered.wait,2));task.cancel();release.set()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertEqual(events,['staging-clean',('cleanup','owned.mp4')])

    async def test_first_pass_failure_cleans_partial_file(self):
        events=[]
        async def sdr(update):raise RuntimeError('first pass failed')
        async def cleanup(path):events.append(path)
        job=module.LongHDROutpaintJob(sdr,lambda path:None,cleanup,'owned.mp4')
        with self.assertRaisesRegex(RuntimeError,'first pass failed'):await job.run()
        self.assertEqual(events,['owned.mp4']);self.assertEqual(job.state,'failed')
