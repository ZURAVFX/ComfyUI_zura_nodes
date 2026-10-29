"""Short, opt-in outpaint jobs. Review must finish and be approved first."""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from aiohttp import web

from .outpaint_studio import plan, build_review_graph, build_studio_graph
from .studio import check_asset, media_url


class OutpaintJobs:
    def __init__(self, studio):
        self.studio = studio
        self.jobs = {}
        self.lock = asyncio.Lock()

    def source(self, identity):
        asset = self.studio.store.load(identity)
        if asset.get('asset_kind') != 'video':
            raise ValueError('Choose a source video.')
        check_asset(asset)
        return asset

    def state(self, identity):
        job = self.jobs.get(identity)
        if not job:
            raise ValueError('This preview is no longer available. Review the selection again.')
        if job['state'] in ('cancelled', 'failed', 'complete'):
            return job
        queue = self.studio.server.prompt_queue
        entry = queue.get_history(identity).get(identity)
        if entry:
            if entry.get('status', {}).get('status_str') != 'success':
                errors = [item[1].get('exception_message', '') for item in entry.get('status', {}).get('messages', [])
                          if item[0] == 'execution_error']
                job.update(state='failed', error=(errors[-1] if errors else 'The render did not complete.')[:1200])
                return job
            files = entry.get('outputs', {}).get('save', {}).get('images', [])
            expected_prefix = identity + '_'
            video = next((f for f in files if f.get('type') == 'output' and
                          f.get('subfolder', '').replace('\\', '/') == 'genj/outpaint' and
                          Path(f.get('filename', '')).name.startswith(expected_prefix) and
                          f.get('filename', '').lower().endswith('.mp4')), None)
            if video is None:
                job.update(state='failed', error='The render did not return its expected video.')
            else:
                job.update(state='complete', url=media_url(video))
            return job
        running, pending = queue.get_current_queue_volatile()
        job['state'] = ('running' if any(item[1] == identity for item in running) else
                        'queued' if any(item[1] == identity for item in pending) else
                        'interrupted' if time.time() - job['created'] > 20 else 'queued')
        return job

    @staticmethod
    def public(job):
        return {k: job.get(k) for k in ('id', 'kind', 'state', 'url', 'error', 'selection', 'approved')}

    async def submit(self, kind, source, selection, prompt='', seed=42):
        import execution
        identity = uuid.uuid4().hex
        prefix = 'genj/outpaint/' + identity
        builder = build_review_graph if kind == 'review' else build_studio_graph
        kwargs = {'output_prefix': prefix, 'check_asset': check_asset}
        if kind == 'render':
            kwargs.update(review_key=selection['review_key'], prompt=prompt, seed=seed)
        graph = await asyncio.to_thread(builder, source, selection, **kwargs)
        server = self.studio.server
        submitted = server.trigger_on_prompt({'prompt': graph, 'prompt_id': identity, 'client_id': 'zura-outpaint'})
        graph = submitted['prompt']
        server.node_replace_manager.apply_replacements(graph)
        valid = await execution.validate_prompt(identity, graph, None)
        if not valid[0]:
            details = '; '.join(e.get('message', '') for n in valid[3].values() for e in n.get('errors', []))
            raise ValueError('ComfyUI needs attention: ' + (details or str(valid[1]))[:1200])
        job = {'id': identity, 'kind': kind, 'state': 'queued', 'source': source,
               'selection': selection, 'created': time.time(), 'approved': False}
        self.jobs[identity] = job
        number = server.number; server.number += 1
        server.prompt_queue.put((number, identity, graph,
                                 {'client_id': 'zura-outpaint', 'create_time': int(time.time()*1000),
                                  'comfy_usage_source': 'zura-studio'}, valid[2], {}))
        return self.public(job)


def register(studio, routes, response):
    jobs = OutpaintJobs(studio)

    @routes.post('/zura/studio/outpaint/review')
    @routes.post('/genj/studio/outpaint/review')
    @response
    async def review(request):
        body = await request.json()
        async with jobs.lock:
            source = await asyncio.to_thread(jobs.source, body.get('source'))
            fields = {k: body.get(k) for k in ('start', 'duration', 'mode', 'width', 'height', 'left', 'top', 'right', 'bottom', 'black_threshold')}
            selection = plan(source, **fields)
            return web.json_response(await jobs.submit('review', source, selection))

    @routes.get('/zura/studio/outpaint/jobs/{identity}')
    @routes.get('/genj/studio/outpaint/jobs/{identity}')
    @response
    async def status(request):
        async with jobs.lock:
            return web.json_response(jobs.public(jobs.state(request.match_info['identity'])))

    @routes.post('/zura/studio/outpaint/jobs/{identity}/approve')
    @routes.post('/genj/studio/outpaint/jobs/{identity}/approve')
    @response
    async def approve(request):
        async with jobs.lock:
            job = jobs.state(request.match_info['identity'])
            if job['kind'] != 'review' or job['state'] != 'complete':
                raise ValueError('Wait for the selection preview before approving it.')
            await asyncio.to_thread(check_asset, job['source'])
            job['approved'] = True
            return web.json_response(jobs.public(job))

    @routes.post('/zura/studio/outpaint/jobs/{identity}/render')
    @routes.post('/genj/studio/outpaint/jobs/{identity}/render')
    @response
    async def render(request):
        body = await request.json()
        async with jobs.lock:
            review_job = jobs.state(request.match_info['identity'])
            if review_job['kind'] != 'review' or review_job['state'] != 'complete' or not review_job['approved']:
                raise ValueError('Review and approve the selection before generating.')
            if review_job.get('render_id'):
                return web.json_response(jobs.public(jobs.state(review_job['render_id'])))
            if not isinstance(body.get('prompt', ''), str) or len(body.get('prompt', '')) > 4000:
                raise ValueError('Enter a prompt up to 4,000 characters.')
            seed = body.get('seed', 42)
            if type(seed) is not int or not 0 <= seed <= 2**53-1:
                raise ValueError('Choose a valid seed.')
            result = await jobs.submit('render', review_job['source'], review_job['selection'], body.get('prompt', ''), seed)
            review_job['render_id'] = result['id']
            return web.json_response(result)

    @routes.post('/zura/studio/outpaint/jobs/{identity}/graph')
    @routes.post('/genj/studio/outpaint/jobs/{identity}/graph')
    @response
    async def export_graph(request):
        body = await request.json()
        async with jobs.lock:
            review_job = jobs.state(request.match_info['identity'])
            if review_job['kind'] != 'review' or review_job['state'] != 'complete' or not review_job['approved']:
                raise ValueError('Review and approve the selection before opening its graph.')
            prompt, seed = body.get('prompt', ''), body.get('seed', 42)
            if not isinstance(prompt, str) or len(prompt) > 4000 or type(seed) is not int or not 0 <= seed <= 2**53-1:
                raise ValueError('Choose a valid prompt and seed.')
            graph = await asyncio.to_thread(build_studio_graph, review_job['source'], review_job['selection'],
                review_key=review_job['selection']['review_key'], prompt=prompt, seed=seed,
                output_prefix='genj/outpaint/' + uuid.uuid4().hex, check_asset=check_asset)
            return web.json_response({'graph': graph})

    @routes.post('/zura/studio/outpaint/jobs/{identity}/cancel')
    @routes.post('/genj/studio/outpaint/jobs/{identity}/cancel')
    @response
    async def cancel(request):
        async with jobs.lock:
            job = jobs.state(request.match_info['identity'])
            if job['state'] in ('queued', 'running'):
                queue = studio.server.prompt_queue
                queue.interrupt_if_running(job['id'])
                queue.delete_queue_item(lambda item: item[1] == job['id'])
                job.update(state='cancelled', error='Stopped this outpaint job.')
            return web.json_response(jobs.public(job))
