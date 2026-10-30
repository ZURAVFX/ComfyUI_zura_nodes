"""Validated adapter for long HDR jobs; deliberately not registered yet."""
from __future__ import annotations

import asyncio
from pathlib import Path

from .hdr_jobs import HDRJobs


class HDRLongService:
    def __init__(self, server, store, check_asset, output_root, *, create_sdr=None, create_native=None):
        from .hdr_chunk_native_job import create_sdr_job, create_native_job
        self.server=server;self.store=store;self.check_asset=check_asset
        self.output_root=Path(output_root).resolve()
        self.create_sdr=create_sdr or create_sdr_job
        self.create_native=create_native or create_native_job
        self.jobs=HDRJobs();self._preparing=asyncio.Lock()

    def _asset(self, body):
        kind=body.get('source_kind','upload')
        if kind in ('upload','sequence'):
            asset=self.store.load(body.get('source_id',''))
            if (kind=='sequence') != (asset.get('asset_kind')=='hdr_sequence'):
                raise ValueError('Choose the requested source type.')
            return asset,self.check_asset
        if kind=='result':
            project=self.store.load(body.get('project_id',''))
            if project.get('config',{}).get('engine')!='local' or not project.get('results'):
                raise ValueError('Generate an LTX video before choosing its result.')
            ref=project['results'][-1].get('asset') or {}
            path=(self.output_root/ref.get('subfolder','')/ref.get('filename','')).resolve()
            if (ref.get('type')!='output' or not path.is_relative_to(self.output_root)
                    or not path.is_file() or path.suffix.lower() not in ('.mp4','.mov','.mkv','.webm')):
                raise ValueError('The saved LTX result is unavailable.')
            return {'asset_kind':'video'},lambda _:path
        raise ValueError('Choose source footage or the latest LTX result.')

    async def start(self, body):
        if not isinstance(body,dict):raise ValueError('Choose HDR conversion settings.')
        mode=body.get('mode')
        if mode not in ('sdr','native'):raise ValueError('Choose SDR to HDR or HDR to HDR.')
        async with self._preparing:
            if any(not task.done() for task in self.jobs.tasks.values()):
                raise ValueError('An HDR conversion is already running.')
            asset,check=self._asset(body)
            factory=self.create_sdr if mode=='sdr' else self.create_native
            # A modest continuation anchor is deliberately fixed for this
            # private evaluation; no artist-facing quality claim is implied.
            job,details=await asyncio.to_thread(factory,self.server,asset,body,check,
                self.output_root,anchor_strength=0.75)
            identity=self.jobs.start(job,details)
            return self.status(identity)

    def status(self, identity):
        snapshot=self.jobs.status(identity)
        result=snapshot.get('result')
        if result:
            files=[]
            for name in result.get('files',[]):
                path=Path(name).resolve()
                if not path.is_relative_to(self.output_root) or not path.is_file():
                    raise ValueError('An HDR output is unavailable.')
                relative=path.relative_to(self.output_root)
                files.append({'filename':relative.name,'subfolder':relative.parent.as_posix(),'type':'output'})
            snapshot['result']={**result,'files':files}
        return snapshot

    async def cancel(self, identity):
        await self.jobs.cancel(identity)
        return self.status(identity)


def register(routes, response, service):
    """Register only when the long HDR flow has passed its release gate."""
    from aiohttp import web

    @routes.post('/zura/studio/hdr/jobs')
    @routes.post('/genj/studio/hdr/jobs')
    @response
    async def start(request):
        return web.json_response(await service.start(await request.json()))

    @routes.get('/zura/studio/hdr/jobs/{identity}')
    @routes.get('/genj/studio/hdr/jobs/{identity}')
    @response
    async def status(request):
        return web.json_response(service.status(request.match_info['identity']))

    @routes.post('/zura/studio/hdr/jobs/{identity}/cancel')
    @routes.post('/genj/studio/hdr/jobs/{identity}/cancel')
    @response
    async def cancel(request):
        return web.json_response(await service.cancel(request.match_info['identity']))
