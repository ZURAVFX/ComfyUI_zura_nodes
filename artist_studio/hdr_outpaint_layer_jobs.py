"""User-requested compositing layers from a finished native HDR outpaint.

CPU export only: it never queues inference, changes the finished take, or
interrupts a Comfy prompt. The reviewed source and immutable result own all
paths and geometry; the HTTP client supplies only the existing job ID.
"""
import asyncio
from pathlib import Path
import re
import threading

from aiohttp import web


class HDRLayerExports:
    def __init__(self, jobs):
        self.jobs = jobs
        self.exports = {}

    def _finished(self, identity):
        if not isinstance(identity, str) or not re.fullmatch(r'[a-f0-9]{32}', identity):
            raise ValueError('Choose a completed HDR frame-extension result.')
        job = self.jobs.state(identity)
        if (job.get('kind') != 'render' or job.get('state') != 'complete' or
                not (job.get('hdr_review_key') or job.get('hdr_render')) or
                not isinstance(job.get('hdr_files'), dict) or not job['hdr_files'].get('exr')):
            raise ValueError('Finish native HDR frame extension before exporting its border layers.')
        return job

    @staticmethod
    def public(record):
        return {key: record.get(key) for key in ('state', 'completed', 'total', 'artifact', 'error')}

    def state(self, identity):
        self._finished(identity)
        return self.public(self.exports.get(identity, {'state':'idle', 'completed':0, 'total':0}))

    async def submit(self, identity):
        job = self._finished(identity)
        current = self.exports.get(identity)
        if current and current['state'] in ('running', 'cancelling', 'complete'):
            return self.public(current)
        record = {'state':'running', 'completed':0, 'total':0, 'artifact':None,
                  'error':None, 'cancelled':threading.Event()}
        self.exports[identity] = record
        loop = asyncio.get_running_loop()

        def update(completed, total):
            def apply():
                if self.exports.get(identity) is record and record['state'] in ('running','cancelling'):
                    record.update(completed=int(completed), total=int(total))
            loop.call_soon_threadsafe(apply)

        def export():
            import folder_paths
            from .hdr_outpaint_artifacts import _owned_file
            from .hdr_outpaint_layers import export_hdr_outpaint_layers
            from .studio import check_asset
            root = Path(folder_paths.get_output_directory()).resolve()
            archive = _owned_file(root, job['hdr_files']['exr'], 'genj/hdr', r'hdr_outpaint_[a-f0-9]{32}\.zip')
            source = check_asset(job['source'])
            selection = dict(job['selection'])
            selection['colour_space'] = job.get('hdr_colour_space') or selection.get('colour_space', 'auto')
            return export_hdr_outpaint_layers(archive, source, selection, root,
                'hdr_outpaint_layers_' + identity, cancelled=record['cancelled'], progress=update)

        async def execute():
            path = None
            try:
                path = await asyncio.to_thread(export)
                if record['cancelled'].is_set():
                    # The exporter atomically created this path for this call.
                    await asyncio.to_thread(Path(path).unlink, missing_ok=True)
                    record.update(state='cancelled', artifact=None, error=None)
                    return
                import folder_paths
                root = Path(folder_paths.get_output_directory()).resolve()
                relative = Path(path).resolve().relative_to(root)
                record.update(state='complete', completed=record['total'], artifact={
                    'type':'output','subfolder':relative.parent.as_posix(),'filename':relative.name})
            except Exception as exc:
                record.update(state='cancelled' if record['cancelled'].is_set() else 'failed',
                              error=None if record['cancelled'].is_set() else str(exc)[:1200], artifact=None)

        record['task'] = asyncio.create_task(execute())
        return self.public(record)

    def cancel(self, identity):
        self._finished(identity)
        record = self.exports.get(identity)
        if record and record['state'] in ('running','cancelling'):
            record['cancelled'].set()
            record['state'] = 'cancelling'
        return self.state(identity)


def register(jobs, routes, response):
    exports = HDRLayerExports(jobs)
    jobs.layer_exports = exports

    @routes.get('/zura/studio/outpaint/jobs/{identity}/layers')
    @routes.get('/genj/studio/outpaint/jobs/{identity}/layers')
    @response
    async def status(request):
        return web.json_response(exports.state(request.match_info['identity']))

    @routes.post('/zura/studio/outpaint/jobs/{identity}/layers')
    @routes.post('/genj/studio/outpaint/jobs/{identity}/layers')
    @response
    async def start(request):
        return web.json_response(await exports.submit(request.match_info['identity']))

    @routes.post('/zura/studio/outpaint/jobs/{identity}/layers/cancel')
    @routes.post('/genj/studio/outpaint/jobs/{identity}/layers/cancel')
    @response
    async def cancel(request):
        return web.json_response(exports.cancel(request.match_info['identity']))
