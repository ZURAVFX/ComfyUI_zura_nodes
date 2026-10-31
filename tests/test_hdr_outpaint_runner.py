import asyncio
import importlib
import threading
import unittest

import test_artist_studio  # Initialise the local custom-node package.

runner = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_runner')
experiment = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_experiment')
outpaint = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')


class ReviewedHDRRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.source = {'sha': 'a' * 64, 'file': 'source.mp4', 'duration': 4,
                       'width': 128, 'height': 128, 'asset_kind': 'video'}
        self.selection = outpaint.plan(self.source, start=.517, duration=.5, mode='expand',
            width=192, height=192, left=32, top=32, right=32, bottom=32)
        self.key = experiment.hdr_review_key(self.selection, 'pq_rec2020')
        self.events = []

    async def submit(self, name, graph):
        self.events.append(('submit', name, graph))
        return name + '-job'

    async def wait(self, name, identity):
        self.events.append(('wait', name, identity))
        return 'intermediate.mp4' if name == 'outpaint' else {'hlg': 'final.mp4', 'exr': 'frames.zip'}

    async def cancel(self, identity): self.events.append(('cancel', identity))
    async def cleanup(self, path): self.events.append(('cleanup', path))
    def update(self, stage): self.events.append(('update', stage))

    def args(self):
        return dict(source=self.source, selection=self.selection, review_key=self.key,
            colour_space='pq_rec2020', has_audio=True, prompt='Extend the scene', seed=42,
            identity='test123', check_asset=lambda asset: None, submit=self.submit,
            wait=self.wait, cancel=self.cancel, update=self.update, cleanup=self.cleanup)

    async def test_order_and_approved_selection_flow_to_both_passes(self):
        result = await runner.run_reviewed_hdr_outpaint(**self.args())
        self.assertEqual(result, {'hlg': 'final.mp4', 'exr': 'frames.zip'})
        submissions = [e for e in self.events if e[0] == 'submit']
        self.assertEqual([e[1] for e in submissions], ['outpaint', 'hdr'])
        self.assertEqual(submissions[0][2]['hdr_source']['inputs']['start_seconds'], .517)
        self.assertEqual(submissions[1][2]['native_original']['inputs']['start_seconds'], .517)
        self.assertEqual(submissions[1][2]['zura_hdr_source']['inputs']['source'], 'intermediate.mp4')
        self.assertEqual(self.events[-1], ('cleanup', 'intermediate.mp4'))

    async def test_cancel_only_active_pass_and_clean_intermediate(self):
        started = asyncio.Event()
        async def wait(name, identity):
            if name == 'outpaint': return 'intermediate.mp4'
            started.set()
            await asyncio.Future()
        task = asyncio.create_task(runner.run_reviewed_hdr_outpaint(**{**self.args(), 'wait': wait}))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertIn(('cancel', 'hdr-job'), self.events)
        self.assertNotIn(('cancel', 'outpaint-job'), self.events)
        self.assertEqual(self.events[-1], ('cleanup', 'intermediate.mp4'))

    async def test_invalid_review_never_submits(self):
        with self.assertRaisesRegex(ValueError, 'approve'):
            await runner.run_reviewed_hdr_outpaint(**{**self.args(), 'review_key': 'wrong'})
        self.assertFalse(self.events)

    async def test_source_change_after_first_pass_cannot_reuse_approval(self):
        async def wait(name, identity):
            self.selection['left'] = 31
            return 'intermediate.mp4'
        with self.assertRaisesRegex(ValueError, 'Review the selection again'):
            await runner.run_reviewed_hdr_outpaint(**{**self.args(), 'wait': wait})
        self.assertEqual([e[1] for e in self.events if e[0] == 'submit'], ['outpaint'])
        self.assertEqual(self.events[-1], ('cleanup', 'intermediate.mp4'))

    async def test_failed_status_cancels_current_job_and_cleans_intermediate(self):
        async def wait(name, identity):
            if name == 'outpaint': return 'intermediate.mp4'
            raise RuntimeError('Connection failed')
        with self.assertRaisesRegex(RuntimeError, 'Connection failed'):
            await runner.run_reviewed_hdr_outpaint(**{**self.args(), 'wait': wait})
        self.assertIn(('cancel', 'hdr-job'), self.events)
        self.assertEqual(self.events[-1], ('cleanup', 'intermediate.mp4'))

    async def test_cancel_during_submission_waits_for_job_id(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def submit(name, graph):
            started.set()
            await release.wait()
            return 'submitted-job'
        task = asyncio.create_task(runner.run_reviewed_hdr_outpaint(**{**self.args(), 'submit': submit}))
        await started.wait()
        task.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertIn(('cancel', 'submitted-job'), self.events)

    async def test_asset_check_does_not_block_cancellation(self):
        entered, release = threading.Event(), threading.Event()
        def slow_check(asset):
            entered.set()
            release.wait(5)
        task = asyncio.create_task(runner.run_reviewed_hdr_outpaint(**{**self.args(), 'check_asset': slow_check}))
        try:
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
            self.assertFalse(any(event[0] == 'submit' for event in self.events))
        finally:
            release.set()
