"""Short, opt-in outpaint jobs. Review must finish and be approved first."""
from __future__ import annotations

import asyncio
import shutil
import time
import uuid
from pathlib import Path

from aiohttp import web

from .outpaint_studio import plan, build_review_graph, build_studio_graph
from .studio import check_asset, media_url

# The long workflow is independently selectable after artist approval of the
# anchored/feathered prototype and targeted active-render cancellation.
# The existing short black-guide path is independent of this flag.
LONG_MODE_READY = True

LONG_REQUIRED_FILES = (
    ('diffusion_models', 'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors'),
    ('text_encoders', 'gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors'),
    ('vae', 'ltx-2.5-video-vae-conv-bf16.safetensors'),
    ('vae', 'ltx-2.5-audio-vae-bf16.safetensors'),
    ('loras', 'ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors'),
)
LONG_REQUIRED_NODES = ('LTXVInpaintPreprocess', 'LTXAddVideoICLoRAGuideAdvanced',
    'LTXICLoRALoaderModelOnly', 'LTXVLaplacianPyramidBlend', 'LTXVImgToVideoInplace',
    'GenjSelectClip', 'ZuraOutpaintTemporalHold', 'ZuraLTXOutpaintCanvas',
    'LoadVideo', 'GetVideoComponents', 'MaskToImage', 'ImageScale', 'ImageToMask',
    'CLIPLoader', 'CLIPTextEncode', 'LTXVConditioning', 'VAELoader', 'UNETLoader',
    'EmptyLTXVLatentVideo', 'VAEEncodeAudio', 'LTXVSetAudioRefTokens',
    'LTXVConcatAVLatent', 'CFGGuider', 'RandomNoise', 'KSamplerSelect', 'ManualSigmas',
    'SamplerCustomAdvanced', 'LTXVSeparateAVLatent', 'LTXVCropGuides',
    'VAEDecodeTiled', 'VAEEncodeTiled', 'ImageFromBatch', 'LoadImage',
    'CreateVideo', 'SaveVideo')


def long_dependencies():
    """Check actual configured model locations and loaded Comfy node types."""
    import folder_paths
    import nodes
    missing_files = [name for folder, name in LONG_REQUIRED_FILES if not folder_paths.get_full_path(folder, name)]
    missing_nodes = [name for name in LONG_REQUIRED_NODES if name not in nodes.NODE_CLASS_MAPPINGS]
    return {'ready': not missing_files and not missing_nodes, 'missing_files': missing_files,
            'missing_nodes': missing_nodes,
            'packages': ['ltx25_core', 'ltx25_text_encoder', 'ltx25_in_outpaint']}


def short_dependencies(mode):
    """Report dependencies from the actual graph used by the chosen method."""
    import folder_paths
    import nodes
    source = {'file': 'genj_studio/setup/source.mp4', 'sha': 'a' * 64,
              'duration': 1, 'width': 128, 'height': 128}
    selection = plan(source, start=0, duration=1, mode=mode, width=128, height=128)
    graphs = [build_review_graph(source, selection, output_prefix='genj/outpaint/setup'),
              build_studio_graph(source, selection, review_key=selection['review_key'],
                                 output_prefix='genj/outpaint/setup')]
    model_inputs = {'UNETLoader': ('diffusion_models', 'unet_name'),
                    'CLIPLoader': ('text_encoders', 'clip_name'),
                    'VAELoader': ('vae', 'vae_name'),
                    'LTXICLoRALoaderModelOnly': ('loras', 'lora_name')}
    required_files, required_nodes = set(), set()
    for graph in graphs:
        for node in graph.values():
            kind = node['class_type']
            required_nodes.add(kind)
            if kind in model_inputs:
                folder, name = model_inputs[kind]
                required_files.add((folder, node['inputs'][name]))
    missing_files = [name for folder, name in sorted(required_files) if not folder_paths.get_full_path(folder, name)]
    missing_nodes = sorted(name for name in required_nodes if name not in nodes.NODE_CLASS_MAPPINGS)
    return {'ready': not missing_files and not missing_nodes, 'missing_files': missing_files,
            'missing_nodes': missing_nodes}

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
        if job.get('long'):
            # A long job is driven by its bounded child prompts, not by a
            # Comfy queue entry bearing the parent job ID.
            return job
        queue = self.studio.server.prompt_queue
        if job['state'] == 'cancelling':
            running, pending = queue.get_current_queue_volatile()
            if not any(item[1] == identity for item in (*running, *pending)):
                job.update(state='cancelled', error='Stopped this outpaint job.')
            return job
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
                job.update(state='complete', url=media_url(video), artifact=video)
            return job
        running, pending = queue.get_current_queue_volatile()
        job['state'] = ('running' if any(item[1] == identity for item in running) else
                        'queued' if any(item[1] == identity for item in pending) else
                        'interrupted' if time.time() - job['created'] > 20 else 'queued')
        return job

    @staticmethod
    def public(job):
        return {k: job.get(k) for k in ('id', 'kind', 'state', 'url', 'artifact', 'error', 'selection', 'approved', 'window', 'windows', 'active_prompt_id', 'estimated_bytes')}

    async def submit_long(self, kind, source, selection, *, reviewed=None, prompt='', seed=42, client_id=None, anchor=False, custom_loras=None):
        """Private bounded executor, not yet exposed by the Studio routes.

        Full-range review and generated-window continuity must be verified on
        representative footage before removing the existing public limit.
        """
        import folder_paths
        from .outpaint_long_runner import plan_long, run_windows
        from .enhancement import inspect_video
        keys = ('start', 'duration', 'mode', 'width', 'height', 'left', 'top', 'right', 'bottom', 'black_threshold')
        current, parts, subplans = plan_long(source, **{k: selection[k] for k in keys},
            overlap=selection.get('overlap', 12), strategy=selection.get('strategy'))
        if current['review_key'] != selection.get('review_key'):
            raise ValueError('The source or canvas changed. Review the full selection again.')
        if kind not in ('review', 'render'):
            raise ValueError('Choose a valid outpaint job.')
        if kind == 'render' and custom_loras:
            from .custom_loras import apply_installed_ltx_loras
            sentinel = {'model': {'class_type': 'UNETLoader', 'inputs': {'unet_name': 'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors'}}}
            await asyncio.to_thread(apply_installed_ltx_loras, sentinel, custom_loras)
        if client_id is not None and (not isinstance(client_id, str) or not client_id or len(client_id) > 128):
            raise ValueError('Invalid Studio connection. Reload Studio and try again.')
        if current.get('strategy') == 'anchored_masked' and not anchor:
            raise ValueError('The approved anchored workflow requires its reference frame.')
        if kind == 'render' and (not reviewed or reviewed.get('kind') != 'review'
                or reviewed.get('state') != 'complete' or not reviewed.get('approved')
                or reviewed.get('selection', {}).get('review_key') != current['review_key']):
            raise ValueError('Review and approve the full outpaint selection before generating.')
        executable = shutil.which('ffmpeg')
        if not executable:
            raise ValueError('FFmpeg is required to assemble long outpaint jobs.')
        identity = uuid.uuid4().hex
        output_root = (Path(folder_paths.get_output_directory()) / 'genj' / 'outpaint').resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        input_root = Path(folder_paths.get_input_directory()).resolve()
        from .outpaint_chunks import disk_requirements
        output_bytes, input_bytes = disk_requirements(current['width'], current['height'], parts,
                                                      anchor=anchor and kind == 'render')
        output_free, input_free = shutil.disk_usage(output_root).free, shutil.disk_usage(input_root).free
        if output_root.stat().st_dev == input_root.stat().st_dev:
            enough = output_free >= output_bytes + input_bytes
        else:
            enough = output_free >= output_bytes and input_free >= input_bytes
        if not enough:
            need = (output_bytes + input_bytes) / 1024**3
            raise ValueError(f'This selection needs approximately {need:.1f} GiB of free working space across the input and output drives. Free space or trim the clip.')
        output = output_root / (identity + '_assembled.mp4')
        if output.exists():
            raise ValueError('The output already exists. Try again.')
        job = {'id': identity, 'kind': kind, 'state': 'queued', 'source': source,
               'selection': current, 'created': time.time(), 'approved': False,
               'long': True, 'window': 0, 'windows': len(parts), 'estimated_bytes': output_bytes + input_bytes}
        self.jobs[identity] = job

        anchor_dir = None
        anchor_files = []

        async def submit_child(child_kind, asset, subplan, previous):
            nonlocal anchor_dir
            anchor_file = None
            if previous is not None:
                from .outpaint_anchor import extract_frame
                input_root = (Path(folder_paths.get_input_directory()) / 'genj_studio').resolve()
                if anchor_dir is None:
                    anchor_dir = input_root / ('outpaint-anchor-' + identity)
                    anchor_dir.mkdir(parents=True, exist_ok=False)
                frame_path = anchor_dir / f'frame-{len(anchor_files):04d}.png'
                # Track the destination before extraction so failure/cancellation
                # cleanup can remove a partially written file.
                anchor_files.append(frame_path)
                await asyncio.to_thread(extract_frame, previous[0], frame_path, previous[1])
                anchor_file = frame_path.relative_to(Path(folder_paths.get_input_directory())).as_posix()
            args = (child_kind, asset, subplan, prompt, seed, client_id, anchor_file)
            options = {}
            if current.get('strategy'):
                options['strategy'] = current['strategy']
            if child_kind == 'render' and custom_loras:
                options['custom_loras'] = custom_loras
            child = await self.submit(*args, **options)
            job['active_prompt_id'] = child['id']
            return child['id']

        async def wait_child(child_id):
            while True:
                child = self.state(child_id)
                if child['state'] == 'complete':
                    job['active_prompt_id'] = None
                    artifact = child['artifact']
                    file = (output_root / artifact['filename']).resolve()
                    if file.parent != output_root or not file.is_file():
                        raise ValueError('A generated window is unavailable.')
                    expected = child['selection']
                    await asyncio.to_thread(inspect_video, file, expected_frames=expected['frames'],
                        expected_width=expected['width'], expected_height=expected['height'], expected_fps=24)
                    return file
                if child['state'] in ('failed', 'cancelled', 'interrupted'):
                    raise ValueError(child.get('error') or 'An outpaint window did not finish.')
                await asyncio.sleep(.5)

        async def cancel_child(child_id):
            queue = self.studio.server.prompt_queue
            queue.interrupt_if_running(child_id)
            queue.delete_queue_item(lambda item: item[1] == child_id)
            child = self.jobs.get(child_id)
            if child:
                child.update(state='cancelling')
            # Interrupt is cooperative: wait for this specific prompt to leave
            # the queue before reporting that the long job has stopped.
            while True:
                running, pending = queue.get_current_queue_volatile()
                if not any(item[1] == child_id for item in (*running, *pending)):
                    break
                await asyncio.sleep(.25)
            if child:
                child.update(state='cancelled', error='Stopped this outpaint job.')

        def update(state, index, total):
            job.update(state=state, window=min(index + 1, total), windows=total)

        async def execute():
            try:
                await asyncio.to_thread(check_asset, source)
                audio = await asyncio.to_thread(check_asset, source) if kind == 'render' else None
                await run_windows(kind=kind, source=source, selection=current, parts=parts, subplans=subplans,
                    submit=submit_child, wait=wait_child, cancel=cancel_child, update=update,
                    ffmpeg=executable, output=output, source_audio=audio, anchor=anchor)
                await asyncio.to_thread(inspect_video, output, expected_frames=current['frames'],
                    expected_width=current['width'], expected_height=current['height'], expected_fps=24)
                asset = {'type': 'output', 'subfolder': 'genj/outpaint', 'filename': output.name}
                job.update(state='complete', url=media_url(asset), artifact=asset)
            except asyncio.CancelledError:
                job.update(state='cancelled', active_prompt_id=None, error='Stopped this outpaint job.')
                output.unlink(missing_ok=True)
                raise
            except Exception as exc:
                job.update(state='failed', active_prompt_id=None, error=str(exc)[:1200])
                output.unlink(missing_ok=True)
            finally:
                for file in anchor_files:
                    file.unlink(missing_ok=True)
                if anchor_dir is not None:
                    try:
                        anchor_dir.rmdir()
                    except OSError:
                        pass

        job['task'] = asyncio.create_task(execute())
        return self.public(job)

    async def submit(self, kind, source, selection, prompt='', seed=42, client_id=None, anchor_file=None, strategy=None, custom_loras=None):
        import execution
        identity = uuid.uuid4().hex
        prefix = 'genj/outpaint/' + identity
        builder = build_review_graph if kind == 'review' else build_studio_graph
        if kind == 'render' and strategy == 'anchored_masked':
            from .outpaint_long_masked import build_masked_expand_graph
            builder = build_masked_expand_graph
        elif strategy not in (None, 'anchored_masked'):
            raise ValueError('Choose a supported outpaint strategy.')
        kwargs = {'output_prefix': prefix, 'check_asset': check_asset}
        if kind == 'render':
            kwargs.update(review_key=selection['review_key'], prompt=prompt, seed=seed)
        graph = await asyncio.to_thread(builder, source, selection, **kwargs)
        if kind == 'render' and custom_loras:
            from .custom_loras import apply_installed_ltx_loras
            graph = await asyncio.to_thread(apply_installed_ltx_loras, graph, custom_loras)
        if anchor_file is not None:
            if kind != 'render':
                raise ValueError('Image anchors apply only to rendering.')
            from .outpaint_anchor import attach_first_frame
            graph = attach_first_frame(graph, anchor_file)
        server = self.studio.server
        # Comfy routes execution and progress events to this websocket client.
        # A hard-coded client ID leaves the requesting Studio unable to see them.
        if client_id is not None and (not isinstance(client_id, str) or not client_id or len(client_id) > 128):
            raise ValueError('Invalid Studio connection. Reload Studio and try again.')
        event_client = client_id or 'zura-outpaint'
        submitted = server.trigger_on_prompt({'prompt': graph, 'prompt_id': identity, 'client_id': event_client})
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
                                 {'client_id': event_client, 'create_time': int(time.time()*1000),
                                  'comfy_usage_source': 'zura-studio'}, valid[2], {}))
        return self.public(job)


def register(studio, routes, response):
    jobs = OutpaintJobs(studio)

    @routes.get('/zura/studio/outpaint/capabilities')
    @routes.get('/genj/studio/outpaint/capabilities')
    @response
    async def capabilities(request):
        from .outpaint_chunks import MAX_PIXEL_FRAMES, MAX_WINDOWS
        short = {mode: short_dependencies(mode) for mode in ('expand', 'black')}
        return web.json_response({'anchored_masked': LONG_MODE_READY, 'min_frames': 3,
                                  'fps': 24, 'max_window_pixel_frames': MAX_PIXEL_FRAMES,
                                  'max_windows': MAX_WINDOWS, 'dependencies': long_dependencies(),
                                  'short_dependencies': short})

    @routes.post('/zura/studio/outpaint/review')
    @routes.post('/genj/studio/outpaint/review')
    @response
    async def review(request):
        body = await request.json()
        async with jobs.lock:
            source = await asyncio.to_thread(jobs.source, body.get('source'))
            fields = {k: body.get(k) for k in ('start', 'duration', 'mode', 'width', 'height', 'left', 'top', 'right', 'bottom', 'black_threshold')}
            strategy = body.get('strategy')
            if strategy == 'anchored_masked':
                if not LONG_MODE_READY:
                    raise ValueError('Long frame extension is not available in this version yet.')
                dependencies = await asyncio.to_thread(long_dependencies)
                if not dependencies['ready']:
                    missing = dependencies['missing_files'] + dependencies['missing_nodes']
                    raise ValueError('Long frame extension needs these models or nodes: ' + ', '.join(missing) + '. Use model setup and install missing node packs.')
                from .outpaint_long_runner import plan_long
                selection, _, _ = plan_long(source, **fields, overlap=9, strategy=strategy)
                return web.json_response(await jobs.submit_long('review', source, selection,
                    client_id=body.get('client_id'), anchor=True))
            if strategy not in (None, 'black_guide'):
                raise ValueError('Choose a supported frame-extension method.')
            selection = plan(source, **fields)
            return web.json_response(await jobs.submit('review', source, selection, client_id=body.get('client_id')))

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
            if review_job.get('long'):
                if not LONG_MODE_READY or review_job['selection'].get('strategy') != 'anchored_masked':
                    raise ValueError('Long frame extension is not available in this version yet.')
                result = await jobs.submit_long('render', review_job['source'], review_job['selection'],
                    reviewed=review_job, prompt=body.get('prompt', ''), seed=seed,
                    client_id=body.get('client_id'), anchor=True, custom_loras=body.get('custom_loras', []))
            else:
                result = await jobs.submit('render', review_job['source'], review_job['selection'], body.get('prompt', ''), seed,
                                           client_id=body.get('client_id'), custom_loras=body.get('custom_loras', []))
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
            if review_job.get('long'):
                raise ValueError('Long frame extension uses multiple linked renders and cannot be opened as one graph yet.')
            prompt, seed = body.get('prompt', ''), body.get('seed', 42)
            if not isinstance(prompt, str) or len(prompt) > 4000 or type(seed) is not int or not 0 <= seed <= 2**53-1:
                raise ValueError('Choose a valid prompt and seed.')
            graph = await asyncio.to_thread(build_studio_graph, review_job['source'], review_job['selection'],
                review_key=review_job['selection']['review_key'], prompt=prompt, seed=seed,
                output_prefix='genj/outpaint/' + uuid.uuid4().hex, check_asset=check_asset)
            from .custom_loras import apply_installed_ltx_loras
            graph = await asyncio.to_thread(apply_installed_ltx_loras, graph, body.get('custom_loras', []))
            return web.json_response({'graph': graph})

    @routes.post('/zura/studio/outpaint/jobs/{identity}/cancel')
    @routes.post('/genj/studio/outpaint/jobs/{identity}/cancel')
    @response
    async def cancel(request):
        async with jobs.lock:
            job = jobs.state(request.match_info['identity'])
            if job['state'] in ('queued', 'running', 'assembling'):
                job.update(state='cancelling', error=None)
                if job.get('long') and job.get('task'):
                    job['task'].cancel()
                else:
                    queue = studio.server.prompt_queue
                    queue.interrupt_if_running(job['id'])
                    queue.delete_queue_item(lambda item: item[1] == job['id'])
            return web.json_response(jobs.public(jobs.state(job['id'])))
