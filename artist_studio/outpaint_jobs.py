"""Short, opt-in outpaint jobs. Review must finish and be approved first."""
from __future__ import annotations

import asyncio
import os
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


def hdr_outpaint_enabled():
    """Opt-in engineering route until Studio and GPU checks are complete."""
    return os.environ.get('ZURA_HDR_OUTPAINT_EXPERIMENT', '').strip() == '1'


def hdr_long_outpaint_enabled():
    return hdr_outpaint_enabled() and os.environ.get('ZURA_HDR_OUTPAINT_LONG_EXPERIMENT', '').strip() == '1'


def hdr_black_outpaint_enabled():
    """Black-padded HDR shares the opt-in preview gate."""
    return hdr_outpaint_enabled()


def source_has_audio(source):
    import av
    path = check_asset(source)
    with av.open(str(path)) as container:
        return bool(container.streams.audio)


def inspect_sdr_delivery(job):
    """Verify a finished render before another model consumes its output.

    Run off the event loop: exact frame counting decodes the actual video.
    A review overlay and an HDR viewing proxy are never conversion sources.
    """
    import folder_paths
    from .enhancement import inspect_video
    if job.get('state') != 'complete' or job.get('kind') != 'render':
        raise ValueError('Finish rendering the extended video before HDR delivery.')
    if job.get('hdr_review_key') or job.get('hdr_render') or job.get('hdr_files'):
        raise ValueError('This render already has HDR delivery. Use its HDR master.')
    asset = job.get('artifact') or {}
    name = asset.get('filename', '')
    subfolder = asset.get('subfolder')
    if (asset.get('type') != 'output' or not isinstance(subfolder, str)
            or subfolder.replace('\\', '/') != 'genj/outpaint'
            or not isinstance(name, str) or '/' in name or '\\' in name
            or not name.startswith(job['id'] + '_') or not name.lower().endswith('.mp4')):
        raise ValueError('The completed frame-extension output is invalid.')
    root = (Path(folder_paths.get_output_directory()) / 'genj' / 'outpaint').resolve()
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('The completed video is outside frame-extension storage.')
    selection = job['selection']
    count = selection['frames']
    if job.get('long') or job.get('pad_delivery'):
        count += (1 - count) % 8
    before = path.stat()
    raster = inspect_video(path, expected_frames=count, expected_width=selection['width'],
        expected_height=selection['height'], expected_fps=24,
        expected_audio_tracks=int(source_has_audio(job['source'])))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError('The completed video changed while checking it. Try again.')
    return {'artifact': dict(asset), 'output_raster': {
        'width': raster['width'], 'height': raster['height'], 'frames': raster['frames'],
        'fps': raster['fps'], 'has_audio': raster['audio_tracks'] == 1}}

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
    source = {'file': 'genj_studio/setup/source.mp4', 'sha': 'a' * 64,
              'duration': 1, 'width': 128, 'height': 128}
    selection = plan(source, start=0, duration=1, mode=mode, width=128, height=128)
    graphs = [build_review_graph(source, selection, output_prefix='genj/outpaint/setup'),
              build_studio_graph(source, selection, review_key=selection['review_key'],
                                 output_prefix='genj/outpaint/setup', pad_delivery=True)]
    return graph_dependencies(graphs)


def graph_dependencies(graphs):
    import folder_paths
    import nodes
    model_inputs = {'UNETLoader': ('diffusion_models', 'unet_name'),
                    'CLIPLoader': ('text_encoders', 'clip_name'),
                    'VAELoader': ('vae', 'vae_name'),
                    'LTXICLoRALoaderModelOnly': ('loras', 'lora_name'),
                    'LoraLoaderModelOnly': ('loras', 'lora_name'),
                    'LTXVLoadConditioning': ('embeddings', 'file_name')}
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


def hdr_expand_dependencies():
    """Check all three actual graphs, including both LTX generation passes."""
    from .hdr_outpaint_experiment import (build_hdr_review_experiment, hdr_review_key,
        build_reviewed_sdr_first_stage, build_reviewed_sdr_first_composite)
    source = {'file': 'genj_studio/setup/source.mp4', 'sha': 'a' * 64,
              'duration': 1, 'width': 128, 'height': 128, 'asset_kind': 'video'}
    selection = plan(source, start=0, duration=.5, mode='expand', width=192, height=192,
                     left=32, top=32, right=32, bottom=32)
    key = hdr_review_key(selection, 'auto')
    review, _ = build_hdr_review_experiment(source, selection)
    stage = build_reviewed_sdr_first_stage(source, selection, review_key=key)
    final = build_reviewed_sdr_first_composite(source, selection, 'intermediate.mp4', review_key=key, has_audio=True)
    return graph_dependencies([review, stage, final])


def hdr_black_dependencies():
    """Inspect the actual black-mask review and both soundtrack variants."""
    from .hdr_outpaint_experiment import (build_hdr_review_experiment, hdr_review_key,
        build_reviewed_sdr_first_stage, build_reviewed_sdr_first_composite)
    source = {'file':'genj_studio/setup/source.mp4', 'sha':'a'*64, 'duration':1,
              'width':128, 'height':128, 'asset_kind':'video', 'has_audio':True}
    selection = plan(source,start=0,duration=.5,mode='black',width=128,height=128)
    key = hdr_review_key(selection,'auto')
    review,_ = build_hdr_review_experiment(source,selection)
    stages = [build_reviewed_sdr_first_stage({**source,'has_audio':audio},selection,review_key=key)
              for audio in (False,True)]
    finals = [build_reviewed_sdr_first_composite(source,selection,'intermediate.mp4',review_key=key,has_audio=audio)
              for audio in (False,True)]
    return graph_dependencies([review,*stages,*finals])


def hdr_long_dependencies(mode='expand'):
    import nodes
    if mode not in ('expand','black'):
        raise ValueError('Choose canvas expansion or black areas.')
    result=hdr_black_dependencies() if mode=='black' else hdr_expand_dependencies()
    extra=('LTXVImgToVideoInplace','ZuraHDRWriteChunk','ZuraHDRReadChunkAnchor','ZuraHDRPadSDRAnchor')
    result['missing_nodes']=sorted(set(result['missing_nodes'])|{name for name in extra if name not in nodes.NODE_CLASS_MAPPINGS})
    result['ready']=not result['missing_files'] and not result['missing_nodes']
    return result

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
            controller = job.get('hdr_controller')
            if controller and job['state'] != 'cancelling':
                current = controller.snapshot()
                progress = (current.get('hdr') if current.get('stage')=='converting_hdr' else
                            current.get('progress') or current.get('sdr')) or {}
                total = progress.get('windows') or progress.get('total') or job.get('windows')
                window = progress.get('window')
                if current.get('stage') == 'converting_hdr' and type(progress.get('completed')) is int and type(total) is int:
                    window = min(total, progress['completed'] + 1)
                job.update(stage=current.get('stage'), active_prompt_id=current.get('active_prompt_id'),
                           window=window, windows=total)
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
            folder = 'genj/hdr_outpaint' if job.get('hdr_review_key') else 'genj/outpaint'
            video = next((f for f in files if f.get('type') == 'output' and
                          f.get('subfolder', '').replace('\\', '/') == folder and
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
        result = {k: job.get(k) for k in ('id', 'kind', 'state', 'url', 'artifact', 'error', 'selection', 'approved', 'window', 'windows', 'active_prompt_id', 'estimated_bytes', 'stage', 'hdr_files', 'output_raster')}
        result['hdr'] = bool(job.get('hdr_review_key') or job.get('hdr_render'))
        return result

    async def delivery(self, identity):
        job = self.state(identity)
        result = await asyncio.to_thread(inspect_sdr_delivery, job)
        job['output_raster'] = result['output_raster']
        return result

    async def submit_hdr_review(self, source, selection, *, colour_space, client_id=None):
        """Internal HDR geometry review; not registered as a public route yet."""
        import execution
        from .hdr_outpaint_experiment import build_hdr_review_experiment
        if client_id is not None and (not isinstance(client_id, str) or not client_id or len(client_id) > 128):
            raise ValueError('Invalid Studio connection. Reload Studio and try again.')
        identity = uuid.uuid4().hex
        graph, review_key = await asyncio.to_thread(build_hdr_review_experiment, source, selection,
            colour_space=colour_space, prefix='genj/hdr_outpaint/' + identity, check_asset=check_asset)
        server = self.studio.server
        event_client = client_id or 'zura-hdr-outpaint'
        submitted = server.trigger_on_prompt({'prompt': graph, 'prompt_id': identity, 'client_id': event_client})
        graph = submitted['prompt']
        server.node_replace_manager.apply_replacements(graph)
        valid = await execution.validate_prompt(identity, graph, None)
        if not valid[0]:
            details = '; '.join(e.get('message', '') for node in valid[3].values() for e in node.get('errors', []))
            raise ValueError('ComfyUI needs attention: ' + (details or str(valid[1]))[:1200])
        job = {'id': identity, 'kind': 'review', 'state': 'queued', 'source': source,
               'selection': selection, 'created': time.time(), 'approved': False,
               'hdr_review_key': review_key, 'hdr_colour_space': colour_space}
        self.jobs[identity] = job
        number = server.number; server.number += 1
        server.prompt_queue.put((number, identity, graph, {'client_id': event_client,
            'create_time': int(time.time()*1000), 'comfy_usage_source':'zura-studio'}, valid[2], {}))
        return self.public(job)

    async def submit_reviewed_hdr(self, source, selection, reviewed, *, colour_space, has_audio,
                                  prompt='', seed=42, client_id=None):
        """Internal bounded HDR render; not registered as a public route yet."""
        from .hdr_outpaint_experiment import _reviewed_sdr_first_selection
        from .hdr_outpaint_queue import ReviewedHDRQueue
        if (not reviewed or reviewed.get('kind') != 'review' or reviewed.get('state') != 'complete'
                or not reviewed.get('approved') or reviewed.get('source', {}).get('sha') != source.get('sha')):
            raise ValueError('Review and approve the HDR selection before generating.')
        key = reviewed.get('hdr_review_key')
        await asyncio.to_thread(_reviewed_sdr_first_selection, source, selection, key, colour_space, check_asset)
        if not isinstance(prompt, str) or len(prompt) > 4000 or type(seed) is not int or not 0 <= seed <= 2**53-1:
            raise ValueError('Choose a valid prompt and seed.')
        if type(has_audio) is not bool:
            raise ValueError('Audio selection must be explicit.')
        import folder_paths
        root = Path(folder_paths.get_output_directory()).resolve()
        identity = uuid.uuid4().hex
        job = {'id': identity, 'kind': 'render', 'state': 'queued', 'source': source,
               'selection': selection, 'created': time.time(), 'approved': False,
               'long': True, 'hdr_render': True, 'stage': 'preparing', 'active_prompt_id': None}
        def update(stage):
            job.update(state='running', stage=stage)
        def on_prompt(prompt_id):
            job['active_prompt_id'] = prompt_id
        adapter = ReviewedHDRQueue(self.studio.server, root, client_id='zura-hdr-outpaint' if client_id is None else client_id,
            identity=identity, selection=selection, has_audio=has_audio, update=update, on_prompt=on_prompt)
        self.jobs[identity] = job

        async def execute():
            try:
                files = await adapter.run(source=source, review_key=key, colour_space=colour_space,
                                          prompt=prompt, seed=seed, check_asset=check_asset)
                def reference(path):
                    relative = Path(path).resolve().relative_to(root)
                    return {'type': 'output', 'subfolder': relative.parent.as_posix(), 'filename': relative.name}
                result = {name: reference(path) for name, path in files.items()}
                job.update(state='complete', stage='complete', active_prompt_id=None,
                           url=media_url(result['preview']), artifact=result['hlg'], hdr_files=result)
            except asyncio.CancelledError:
                job.update(state='cancelled', active_prompt_id=None, error='Stopped this HDR frame-extension job.')
                raise
            except Exception as exc:
                job.update(state='failed', active_prompt_id=None, error=str(exc)[:1200])
        job['task'] = asyncio.create_task(execute())
        return self.public(job)

    async def submit_long_hdr(self, kind, source, selection, *, reviewed=None, prompt='', seed=42, client_id=None):
        """Internal full-range review or render; gated from normal Studio."""
        import folder_paths
        from .hdr_outpaint_long_comfy import create_long_hdr_review_job, create_long_hdr_outpaint_job
        if kind not in ('review','render'):
            raise ValueError('Choose a valid HDR frame-extension job.')
        if kind=='render' and (not reviewed or reviewed.get('kind')!='review' or
                reviewed.get('state')!='complete' or not reviewed.get('approved') or
                not reviewed.get('hdr_long') or reviewed.get('source',{}).get('sha')!=source.get('sha') or
                reviewed.get('selection',{}).get('review_key')!=selection.get('review_key')):
            raise ValueError('Review and approve the full HDR selection before generating.')
        root=Path(folder_paths.get_output_directory()).resolve()
        args={'review_key':selection.get('review_key'), 'output_root':root,
              'check_asset':check_asset, 'client_id':client_id or 'zura-hdr-outpaint'}
        if kind=='review':
            controller,details=await asyncio.to_thread(create_long_hdr_review_job,self.studio.server,source,selection,**args)
        else:
            controller,details=await asyncio.to_thread(create_long_hdr_outpaint_job,self.studio.server,source,selection,
                input_root=folder_paths.get_input_directory(),prompt=prompt,seed=seed,**args)
        identity=details['id']
        job={'id':identity,'kind':kind,'state':'queued','source':source,'selection':selection,
             'created':time.time(),'approved':False,'long':True,'hdr_long':True,
             'hdr_review_key':selection['review_key'],'hdr_colour_space':selection['colour_space'],
             'hdr_controller':controller,'windows':details['sections']}
        self.jobs[identity]=job
        async def execute():
            try:
                job['state']='running';result=await controller.run()
                if kind=='review':
                    job.update(state='complete',stage='complete',active_prompt_id=None,url=media_url(result),artifact=result)
                else:
                    from .hdr_outpaint_artifacts import checked_long_delivery
                    details=controller.conversion_details
                    if not isinstance(details, dict):
                        raise ValueError('The HDR conversion metadata is unavailable.')
                    validated=await asyncio.to_thread(checked_long_delivery, root, result, details['id'],
                        width=details['width'], height=details['height'], frames=details['frames'],
                        has_audio=details['has_audio'])
                    def ref(path):
                        relative=path.relative_to(root)
                        return {'type':'output','subfolder':relative.parent.as_posix(),'filename':relative.name}
                    result_files={key:ref(path) for key,path in validated.items()}
                    job.update(state='complete',stage='complete',active_prompt_id=None,url=media_url(result_files['preview']),artifact=result_files['hlg'],hdr_files=result_files)
            except asyncio.CancelledError:
                job.update(state='cancelled',error='Stopped this HDR frame-extension job.');raise
            except Exception as exc:
                job.update(state='failed',error=str(exc)[:1200])
        job['task']=asyncio.create_task(execute())
        return self.public(job)

    async def submit_long(self, kind, source, selection, *, reviewed=None, prompt='', seed=42, client_id=None, anchor=False, custom_loras=None):
        """Private bounded executor, not yet exposed by the Studio routes.

        Full-range review and generated-window continuity must be verified on
        representative footage before removing the existing public limit.
        """
        import folder_paths
        from .outpaint_long_runner import plan_long, run_windows
        from .enhancement import inspect_video
        keys = ('start', 'duration', 'mode', 'width', 'height', 'left', 'top', 'right', 'bottom', 'black_threshold')
        options = {k: selection[k] for k in keys}
        options['duration'] = selection.get('requested_duration', selection['duration'])
        current, parts, subplans = plan_long(source, **options,
            overlap=selection.get('overlap', 12), strategy=selection.get('strategy'), allow_partial_end=True)
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
                await asyncio.to_thread(inspect_video, output, expected_frames=(current['frames'] + (1 - current['frames']) % 8 if kind == 'render' else current['frames']),
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

    async def submit(self, kind, source, selection, prompt='', seed=42, client_id=None, anchor_file=None, strategy=None, custom_loras=None, pad_delivery=False):
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
            if pad_delivery and builder == build_studio_graph:
                kwargs['pad_delivery'] = True
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
               'selection': selection, 'created': time.time(), 'approved': False,
               'pad_delivery': bool(kind == 'render' and pad_delivery and builder == build_studio_graph)}
        self.jobs[identity] = job
        number = server.number; server.number += 1
        server.prompt_queue.put((number, identity, graph,
                                 {'client_id': event_client, 'create_time': int(time.time()*1000),
                                  'comfy_usage_source': 'zura-studio'}, valid[2], {}))
        return self.public(job)


def register(studio, routes, response):
    jobs = OutpaintJobs(studio)
    from .hdr_outpaint_layer_jobs import register as register_hdr_layer_exports
    register_hdr_layer_exports(jobs, routes, response)

    @routes.get('/zura/studio/outpaint/capabilities')
    @routes.get('/genj/studio/outpaint/capabilities')
    @response
    async def capabilities(request):
        from .outpaint_chunks import MAX_PIXEL_FRAMES, MAX_WINDOWS
        short = {mode: short_dependencies(mode) for mode in ('expand', 'black')}
        hdr_enabled = hdr_outpaint_enabled()
        hdr_long_enabled = hdr_long_outpaint_enabled()
        hdr_black_enabled = hdr_black_outpaint_enabled()
        return web.json_response({'anchored_masked': LONG_MODE_READY, 'min_frames': 3,
                                  'fps': 24, 'max_window_pixel_frames': MAX_PIXEL_FRAMES,
                                  'max_windows': MAX_WINDOWS, 'dependencies': long_dependencies(),
                                  'short_dependencies': short, 'hdr_expand_experiment': hdr_enabled,
                                  'hdr_expand_dependencies': await asyncio.to_thread(hdr_expand_dependencies) if hdr_enabled else None,
                                  'hdr_expand_long_experiment': hdr_long_enabled,
                                  'hdr_expand_long_dependencies': await asyncio.to_thread(hdr_long_dependencies) if hdr_long_enabled else None,
                                  'hdr_black_experiment': hdr_black_enabled,
                                  'hdr_black_dependencies': await asyncio.to_thread(hdr_black_dependencies) if hdr_black_enabled else None,
                                  'hdr_black_long_experiment': hdr_black_enabled and hdr_long_enabled,
                                  'hdr_black_long_dependencies': await asyncio.to_thread(hdr_long_dependencies,'black') if hdr_black_enabled and hdr_long_enabled else None})

    @routes.post('/zura/studio/outpaint/review')
    @routes.post('/genj/studio/outpaint/review')
    @response
    async def review(request):
        body = await request.json()
        async with jobs.lock:
            source = await asyncio.to_thread(jobs.source, body.get('source'))
            fields = {k: body.get(k) for k in ('start', 'duration', 'mode', 'width', 'height', 'left', 'top', 'right', 'bottom', 'black_threshold')}
            strategy = body.get('strategy')
            hdr = body.get('hdr', False)
            if type(hdr) is not bool:
                raise ValueError('Choose a valid HDR option.')
            if hdr:
                if not hdr_outpaint_enabled():
                    raise ValueError('HDR frame extension is not available in this version yet.')
                if fields['mode'] not in ('expand','black'):
                    raise ValueError('Choose canvas expansion or black areas.')
                black = fields['mode']=='black'
                if black and not hdr_black_outpaint_enabled():
                    raise ValueError('HDR black-area preview is not available in this version yet.')
                if strategy=='hdr_long':
                    if not hdr_long_outpaint_enabled():
                        raise ValueError('Long HDR frame extension is not available in this version yet.')
                    dependencies=await asyncio.to_thread(hdr_long_dependencies,'black') if black else await asyncio.to_thread(hdr_long_dependencies)
                    if not dependencies['ready']:
                        raise ValueError('Long HDR frame extension needs these models or nodes: '+', '.join(dependencies['missing_files']+dependencies['missing_nodes']))
                    from .hdr_outpaint_long_plan import plan_hdr_windows
                    selection,_,_=plan_hdr_windows(source,**fields,
                        colour_space=body.get('colour_space','auto'))
                    return web.json_response(await jobs.submit_long_hdr('review',source,selection,client_id=body.get('client_id')))
                if strategy not in (None, 'black_guide'):
                    raise ValueError('Choose a supported HDR frame-extension preview.')
                dependencies = await asyncio.to_thread(hdr_black_dependencies if black else hdr_expand_dependencies)
                if not dependencies['ready']:
                    missing = dependencies['missing_files'] + dependencies['missing_nodes']
                    raise ValueError('HDR frame extension needs these models or nodes: ' + ', '.join(missing) + '. Open model setup for guidance.')
                selection = plan(source, **fields)
                return web.json_response(await jobs.submit_hdr_review(source, selection,
                    colour_space=body.get('colour_space', 'auto'), client_id=body.get('client_id')))
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

    @routes.get('/zura/studio/outpaint/jobs/{identity}/delivery')
    @routes.get('/genj/studio/outpaint/jobs/{identity}/delivery')
    @response
    async def delivery(request):
        # No global job lock during video decoding: progress/cancellation for
        # other jobs must remain responsive while a long output is checked.
        return web.json_response(await jobs.delivery(request.match_info['identity']))

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
            if review_job.get('hdr_long'):
                if not hdr_long_outpaint_enabled():
                    raise ValueError('Long HDR frame extension is not available in this version yet.')
                if review_job['selection'].get('mode')=='black' and not hdr_black_outpaint_enabled():
                    raise ValueError('HDR black-area preview is not available in this version yet.')
                if body.get('custom_loras'):
                    raise ValueError('Custom LoRAs are not supported by the long HDR preview yet.')
                result=await jobs.submit_long_hdr('render',review_job['source'],review_job['selection'],
                    reviewed=review_job,prompt=body.get('prompt',''),seed=seed,client_id=body.get('client_id'))
            elif review_job.get('hdr_review_key'):
                if not hdr_outpaint_enabled():
                    raise ValueError('HDR frame extension is not available in this version yet.')
                if review_job['selection'].get('mode')=='black' and not hdr_black_outpaint_enabled():
                    raise ValueError('HDR black-area preview is not available in this version yet.')
                if body.get('custom_loras'):
                    raise ValueError('Custom LoRAs are not supported by the HDR frame-extension preview yet.')
                has_audio = await asyncio.to_thread(source_has_audio, review_job['source'])
                result = await jobs.submit_reviewed_hdr(review_job['source'], review_job['selection'], review_job,
                    colour_space=review_job['hdr_colour_space'], has_audio=has_audio,
                    prompt=body.get('prompt', ''), seed=seed, client_id=body.get('client_id'))
            elif review_job.get('long'):
                if not LONG_MODE_READY or review_job['selection'].get('strategy') != 'anchored_masked':
                    raise ValueError('Long frame extension is not available in this version yet.')
                result = await jobs.submit_long('render', review_job['source'], review_job['selection'],
                    reviewed=review_job, prompt=body.get('prompt', ''), seed=seed,
                    client_id=body.get('client_id'), anchor=True, custom_loras=body.get('custom_loras', []))
            else:
                result = await jobs.submit('render', review_job['source'], review_job['selection'], body.get('prompt', ''), seed,
                                           client_id=body.get('client_id'), custom_loras=body.get('custom_loras', []), pad_delivery=True)
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
            if review_job.get('hdr_review_key'):
                raise ValueError('HDR frame extension uses two linked renders and cannot be opened as one graph yet.')
            if review_job.get('long'):
                raise ValueError('Long frame extension uses multiple linked renders and cannot be opened as one graph yet.')
            prompt, seed = body.get('prompt', ''), body.get('seed', 42)
            if not isinstance(prompt, str) or len(prompt) > 4000 or type(seed) is not int or not 0 <= seed <= 2**53-1:
                raise ValueError('Choose a valid prompt and seed.')
            graph = await asyncio.to_thread(build_studio_graph, review_job['source'], review_job['selection'],
                review_key=review_job['selection']['review_key'], prompt=prompt, seed=seed,
                output_prefix='genj/outpaint/' + uuid.uuid4().hex, check_asset=check_asset, pad_delivery=True)
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
