import asyncio
import importlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp import web
import test_artist_studio

jobs_module = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_jobs')


class OutpaintRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_generation_validates_and_only_queues_render(self):
        source = {'sha':'a'*64, 'file':'input.mp4', 'width':512, 'height':320,
                  'duration':10, 'fps_num':24, 'fps_den':1}
        fake = SimpleNamespace(lock=asyncio.Lock(), source=lambda _:source,
            submit=AsyncMock(return_value={'id':'render','kind':'render'}),
            submit_long=AsyncMock(return_value={'id':'long','kind':'render'}))
        routes = web.RouteTableDef()
        with patch.object(jobs_module, 'OutpaintJobs', return_value=fake):
            jobs_module.register(SimpleNamespace(), routes, lambda fn:fn)
        generate = next(r.handler for r in routes if r.path=='/zura/studio/outpaint/generate')
        body = {'source':'uploaded', 'start':1, 'duration':2, 'mode':'expand',
                'width':640, 'height':384, 'left':64, 'right':64, 'top':32, 'bottom':32,
                'black_threshold':2/255, 'prompt':'Extend the room'}
        ready = {'ready':True, 'missing_files':[], 'missing_nodes':[]}
        with patch.object(jobs_module,'probe_sdr_source',return_value=source), \
             patch.object(jobs_module,'short_dependencies',return_value=ready), \
             patch.object(jobs_module,'long_dependencies',return_value=ready):
            request = SimpleNamespace(json=AsyncMock(return_value=body))
            reply = await generate(request)
            self.assertEqual(json.loads(reply.body)['kind'], 'render')
            fake.submit.assert_awaited_once()
            kind, _, selected = fake.submit.await_args.args
            self.assertEqual((kind, selected['start'], selected['frames']), ('render',1,48))
            request.json.return_value = {**body, 'start':11}
            with self.assertRaisesRegex(ValueError,'past'):
                await generate(request)
            self.assertEqual(fake.submit.await_count, 1)
            request.json.return_value = {**body, 'start':0, 'duration':8}
            await generate(request)
            fake.submit_long.assert_awaited_once()
            self.assertEqual(fake.submit_long.await_args.args[0], 'render')
            self.assertIsNone(fake.submit_long.await_args.kwargs['reviewed'])

    async def test_terminal_failures_retry_once_and_active_or_complete_jobs_are_reused(self):
        for status in ('failed', 'cancelled', 'interrupted', 'running', 'queued', 'complete'):
            with self.subTest(status=status):
                review = {'id':'review', 'kind':'review', 'state':'complete', 'approved':True,
                          'source':{}, 'selection':{}, 'render_id':'old'}
                records = {'review':review, 'old':{'id':'old', 'kind':'render', 'state':status}}
                async def submit(*args, **kwargs):
                    # Represent a still-active submission when another click arrives.
                    await asyncio.sleep(0)
                    records['new'] = {'id':'new', 'kind':'render', 'state':'queued'}
                    return records['new']
                fake = SimpleNamespace(lock=asyncio.Lock(), state=records.__getitem__, public=lambda x:x,
                                       submit=AsyncMock(side_effect=submit))
                routes = web.RouteTableDef()
                with patch.object(jobs_module, 'OutpaintJobs', return_value=fake):
                    jobs_module.register(SimpleNamespace(), routes, lambda fn:fn)
                render = next(r.handler for r in routes if r.method=='POST' and r.path=='/zura/studio/outpaint/jobs/{identity}/render')
                request = SimpleNamespace(json=AsyncMock(return_value={'prompt':'office','seed':42}), match_info={'identity':'review'})
                replies = await asyncio.gather(render(request), render(request))
                ids = [json.loads(reply.body)['id'] for reply in replies]
                retryable = status in ('failed','cancelled','interrupted')
                self.assertEqual(ids, ['new','new'] if retryable else ['old','old'])
                self.assertEqual(fake.submit.await_count, int(retryable))
                self.assertEqual(review['render_id'], 'new' if retryable else 'old')


if __name__=='__main__':unittest.main()
