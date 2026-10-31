"""Validated adapter for explicitly labelled long HDR preview jobs."""
from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path

from .hdr_jobs import HDRJobs


def preview_enabled():
    """Make the artist-approved preview available; administrators can disable it."""
    return os.environ.get('ZURA_HDR_LONG_PREVIEW', '1').strip() == '1'


def check_long_setup(mode, output):
    """Fail before any chunk runs when continuation dependencies are absent."""
    import folder_paths
    import nodes
    from .hdr_readiness import readiness
    setup=readiness(mode,output,folder_paths.get_full_path,nodes.NODE_CLASS_MAPPINGS,longer=True)
    missing_files=[file['filename'] for file in setup['files'] if not file['ready']]
    missing_nodes=setup['missingNodes']
    if missing_files or missing_nodes:
        parts=[]
        if missing_files:parts.append('Missing models: '+', '.join(missing_files))
        if missing_nodes:parts.append('Missing nodes: '+', '.join(missing_nodes))
        raise ValueError('Longer HDR setup is incomplete. '+'. '.join(parts)+'. Open HDR model setup for installation guidance.')


class HDRLongService:
    def __init__(self, server, store, check_asset, output_root, *, create_sdr=None, create_native=None, check_setup=None):
        from .hdr_chunk_native_job import create_sdr_job, create_native_job
        self.server=server;self.store=store;self.check_asset=check_asset
        self.output_root=Path(output_root).resolve()
        self.create_sdr=create_sdr or create_sdr_job
        self.create_native=create_native or create_native_job
        self.check_setup=check_setup or check_long_setup
        self.jobs=HDRJobs();self._preparing=asyncio.Lock();self._requests={}

    def _asset(self, body):
        kind=body.get('source_kind','upload')
        if kind in ('upload','sequence'):
            asset=self.store.load(body.get('source_id',''))
            if (kind=='sequence') != (asset.get('asset_kind')=='hdr_sequence'):
                raise ValueError('Choose the requested source type.')
            return asset,self.check_asset
        if kind=='output':
            from .hdr_output import selected_output
            path=selected_output(self.output_root,body.get('output_ref'))
            return {'asset_kind':'video'},lambda _:path
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
        section_frames=body.get('section_frames',121)
        if type(section_frames) is not int or section_frames not in ((25,121) if mode=='native' else (121,)):
            raise ValueError('Choose an available HDR section setting.')
        request_id=body.get('request_id')
        if request_id is not None and (not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9]{32}',request_id)):
            raise ValueError('Invalid HDR request ID.')
        fingerprint=json.dumps(body,sort_keys=True,separators=(',',':'))
        async with self._preparing:
            old=self._requests.get(request_id) if request_id else None
            if old:
                if old['fingerprint']!=fingerprint:raise ValueError('This HDR request ID belongs to different settings.')
                return self.status(old['id'])
            if any(not task.done() for task in self.jobs.tasks.values()):
                raise ValueError('An HDR conversion is already running.')
            asset,check=self._asset(body)
            await asyncio.to_thread(self.check_setup,mode,body.get('output','hlg_and_exr'))
            factory=self.create_sdr if mode=='sdr' else self.create_native
            # A modest continuation anchor is deliberately fixed for this
            # private evaluation; no artist-facing quality claim is implied.
            if request_id:self._requests[request_id]={'fingerprint':fingerprint,'id':None}
            try:
                job,details=await asyncio.to_thread(factory,self.server,asset,body,check,
                    self.output_root,anchor_strength=0.75,max_chunk_frames=section_frames)
                identity=self.jobs.start(job,details)
            except Exception:
                if request_id:self._requests.pop(request_id,None)
                raise
            if request_id:self._requests[request_id]['id']=identity
            self._requests={key:value for key,value in self._requests.items() if value['id'] is None or value['id'] in self.jobs.jobs}
            return self.status(identity)

    def request_status(self, request_id):
        record=self._requests.get(request_id)
        if not record:raise ValueError('HDR submission is unavailable. Check the ComfyUI queue before starting again.')
        if record['id'] is None:return {'state':'preparing','request_id':request_id}
        return self.status(record['id'])

    def status(self, identity):
        snapshot=self.jobs.status(identity)
        result=snapshot.get('result')
        if result:
            def file_reference(name):
                path=Path(name).resolve()
                if not path.is_relative_to(self.output_root) or not path.is_file():
                    raise ValueError('An HDR output is unavailable.')
                relative=path.relative_to(self.output_root)
                return {'filename':relative.name,'subfolder':relative.parent.as_posix(),'type':'output'}
            files=[file_reference(name) for name in result.get('files',[])]
            preview=file_reference(result['preview']) if result.get('preview') else None
            snapshot['result']={**result,'files':files,'preview':preview}
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

    @routes.get('/zura/studio/hdr/requests/{identity}')
    @routes.get('/genj/studio/hdr/requests/{identity}')
    @response
    async def request_status(request):
        return web.json_response(service.request_status(request.match_info['identity']))

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
