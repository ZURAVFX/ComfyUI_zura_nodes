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
