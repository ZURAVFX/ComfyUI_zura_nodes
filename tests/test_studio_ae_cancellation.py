"""AE cancellation races exercise the real middleware and queue fence on CPU."""
import asyncio
import copy
from pathlib import Path
import sys
import threading
import time
import types
import unittest

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfylink.studio_sessions import StudioSessions, Session, SESSION_HEADER
from comfylink.studio_cancel import SessionWork, SESSION_ID_HEADER, claim_work, claim_project, project_extra


class Queue:
    def __init__(self):
        self.mutex = threading.RLock()
        self.running, self.pending, self.interrupted = [], [], []

    def put(self, item):
        with self.mutex:
            self.pending.append(item)

    def get_current_queue_volatile(self):
        return self.running[:], self.pending[:]

    def interrupt_if_running(self, identity):
        with self.mutex:
            if any(item[1] == identity for item in self.running):
                self.interrupted.append(identity)

    def delete_queue_item(self, predicate):
        for index, entry in enumerate(self.pending):
            if predicate(entry):
                self.pending.pop(index)
                return True
        return False


def item(identity, extra=None):
    return (0, identity, {}, extra or {}, [])


class AEWorkTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.queue = Queue()
        self.server = types.SimpleNamespace(prompt_queue=self.queue)
        self.service = StudioSessions()
        self.work = self.service.work = SessionWork(self.service, self.server)
        self.server._zura_comfylink_studio_sessions = self.service
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.cancelled = []
        self.project = {'id': 'project-owned', 'phase': 'working', 'actions': [{'id': 'stage', 'state': 'waiting'}], 'results': [{'file': 'saved.exr'}]}
        self.saved = {}
        store = types.SimpleNamespace(load=lambda key: copy.deepcopy(self.saved[key]), save=lambda value: self.saved.update({value['id']: copy.deepcopy(value)}))
        self.studio = types.SimpleNamespace(server=self.server, lock=asyncio.Lock(), store=store)
        app = web.Application(middlewares=[self.work.middleware])

        async def submit(request):
            claim_work(self.server, ('hdr', 'owned-hdr'), lambda: self.cancelled.append('owned-hdr'))
            claim_work(self.server, ('outpaint', 'owned-outpaint'), lambda: self.cancelled.append('owned-outpaint'))
            self.queue.put(item('owned-prompt'))
            # Child tasks retain authenticated scope, including an in-flight
            # submission whose response arrives after Cancel was pressed.
            async def later():
                self.entered.set()
                await self.release.wait()
                try:
                    self.queue.put(item('late-child'))
                except ValueError:
                    self.cancelled.append('late-fenced')
            self.child = asyncio.create_task(later())
            claim_project(self.studio, self.project)
            self.saved[self.project['id']] = copy.deepcopy(self.project)
            return web.json_response({'ok': True})

        async def normal(request):
            self.queue.put(item('normal-prompt'))
            return web.json_response({'ok': True})

        app.router.add_post('/submit', submit)
        app.router.add_post('/normal', normal)
        app.router.add_post('/interrupt', normal)
        app.router.add_post('/queue', normal)
        app.router.add_post('/zura/studio/projects/{id}/cancel', normal)
        for prefix in ('', '/api'):
            app.router.add_post(prefix + '/prompt', normal)
            app.router.add_post(prefix + '/interrupt', normal) if prefix else None
            for family in ('zura', 'genj'):
                for kind in ('hdr', 'outpaint'):
                    for action in ('cancel', 'render', 'approve', 'graph', 'layers/cancel'):
                        app.router.add_post(prefix + '/' + family + '/studio/' + kind + '/jobs/{id}/' + action, normal)
        app.router.add_post('/api/jobs/cancel', normal)
        app.router.add_post('/api/api/jobs/cancel', normal)
        app.router.add_get('/sessions/{id}/status', self.service.status)
        self.client = TestClient(TestServer(app, host='127.0.0.1'))
        await self.client.start_server()
        self.origin = str(self.client.make_url('/')).rstrip('/')
        self.session = Session('a' * 32, 'b' * 64, 'http://127.0.0.1:1234/studio-bridge/' + 'c' * 32,
                               'd' * 64, self.origin, {'target': {'label': 'QA'}, 'capabilities': {}}, time.time() + 600)
        self.service.sessions[self.session.id] = self.session
        self.headers = {SESSION_ID_HEADER: self.session.id, SESSION_HEADER: self.session.capability}

    async def asyncTearDown(self):
        self.release.set()
        if hasattr(self, 'child'):
            await self.child
        await asyncio.gather(*self.work.tasks, return_exceptions=True)
        await self.client.close()

    async def test_cancel_stops_only_bound_family_and_late_continuations(self):
        self.assertEqual((await self.client.post('/normal')).status, 200)
        self.assertEqual((await self.client.post('/submit', headers=self.headers)).status, 200)
        await self.entered.wait()
        owned = next(entry for entry in self.queue.pending if entry[1] == 'owned-prompt')
        self.assertNotIn(self.session.capability, repr(owned), 'Capabilities never enter queue/history metadata')
        self.queue.running = [owned]
        self.queue.pending = [entry for entry in self.queue.pending if entry is not owned]
        # A VHS-style continuation copies only opaque ownership metadata.
        self.queue.put(item('owned-vhs-child', owned[3].copy()))
        self.queue.put(item('owned-vhs-child-2', owned[3].copy()))
        self.session.closed = True
        await self.work.cancel(self.session)
        self.release.set()
        await self.child
        self.assertEqual(self.queue.interrupted, ['owned-prompt'])
        self.assertEqual([entry[1] for entry in self.queue.pending], ['normal-prompt'])
        self.assertIn('owned-hdr', self.cancelled)
        self.assertIn('late-fenced', self.cancelled)
        self.assertEqual(self.saved['project-owned']['actions'][0]['state'], 'cancelled')
        self.assertEqual(self.saved['project-owned']['results'], [{'file': 'saved.exr'}])
        with self.assertRaises(ValueError):
            self.queue.put(item('late-vhs', owned[3].copy()))
        with self.assertRaises(ValueError):
            project_extra(self.server, self.saved['project-owned'])

    async def test_foreign_running_job_is_never_interrupted(self):
        await self.client.post('/submit', headers=self.headers)
        self.queue.running = [item('foreign-running')]
        self.session.closed = True
        await self.work.cancel(self.session)
        self.assertEqual(self.queue.interrupted, [])
        self.assertEqual(self.queue.running[0][1], 'foreign-running')

    async def test_spoofed_scope_cannot_claim_normal_work(self):
        bad = {**self.headers, SESSION_HEADER: '0' * 64}
        self.assertEqual((await self.client.post('/submit', headers=bad)).status, 403)
        self.assertEqual(self.queue.pending, [])
        self.assertEqual(self.work.claims, {})

    async def test_scoped_frontend_cannot_interrupt_or_delete_foreign_jobs(self):
        await self.client.post('/submit', headers=self.headers)
        for path, body in [('/interrupt', {}), ('/interrupt', {'prompt_id': 'foreign-running'}),
                           ('/queue', {'clear': True}), ('/queue', {'delete': ['normal-prompt']}),
                           ('/zura/studio/projects/foreign/cancel', {})]:
            response = await self.client.post(path, json=body, headers=self.headers)
            self.assertEqual(response.status, 403, path)
        self.assertEqual(self.queue.interrupted, [])

    async def test_all_coordinator_mutations_require_recorded_ownership(self):
        await self.client.post('/submit', headers=self.headers)
        for prefix in ('', '/api'):
            for family in ('zura', 'genj'):
                for kind in ('hdr', 'outpaint'):
                    for action in ('cancel', 'render', 'approve', 'graph', 'layers/cancel'):
                        path = prefix + '/' + family + '/studio/' + kind + '/jobs/'
                        denied = await self.client.post(path + 'foreign/' + action + '?source=owned', json={}, headers=self.headers)
                        self.assertEqual(denied.status, 403, path + action)
                        allowed = await self.client.post(path + 'owned-' + kind + '/' + action, json={}, headers=self.headers)
                        self.assertEqual(allowed.status, 200, path + action)
        for path in ('/api/interrupt', '/api/jobs/cancel', '/api/api/jobs/cancel'):
            self.assertEqual((await self.client.post(path, json={}, headers=self.headers)).status, 403)

    async def test_public_session_id_is_not_prompt_ownership_authority(self):
        await self.client.post('/submit', headers=self.headers)
        for path in ('/prompt', '/api/prompt'):
            response = await self.client.post(path, json={'extra_data': {'zura_comfylink_session': self.session.id}})
            self.assertEqual(response.status, 403)
            self.assertEqual((await self.client.post(path, json={'extra_data': {}})).status, 200)
        normal = [entry for entry in self.queue.pending if entry[1] == 'normal-prompt']
        self.assertEqual(len(normal), 2)
        self.assertTrue(all('zura_comfylink_session' not in entry[3] for entry in normal))

    async def test_host_revoke_status_cancels_before_reporting_closed(self):
        await self.client.post('/submit', headers=self.headers)
        async def revoked(*args):
            raise web.HTTPGone()
        self.service.broker_json = revoked
        response = await self.client.get('/sessions/' + self.session.id + '/status', headers={SESSION_HEADER: self.session.capability})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())['status'], 'cancelled')
        self.assertTrue(self.session.closed)
        self.assertEqual(self.queue.pending, [])
        self.assertIn('owned-hdr', self.cancelled)

    async def test_hidden_browser_does_not_prevent_host_cancellation(self):
        await self.client.post('/submit', headers=self.headers)
        async def revoked(*args):
            raise web.HTTPGone()
        self.service.broker_json = revoked
        watcher = self.work.watch(self.session, delay=.001)
        await asyncio.wait_for(watcher, 1)
        self.assertTrue(self.session.closed)
        self.assertEqual(self.queue.pending, [])
        self.assertIn('owned-hdr', self.cancelled)


if __name__ == '__main__':
    unittest.main()
