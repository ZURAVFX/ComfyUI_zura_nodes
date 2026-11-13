"""Owned, bounded SDR inference views of authorised original Studio media.

These files are model inputs. They never replace or become an HDR master.
"""
from __future__ import annotations

import asyncio
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
from urllib.parse import urlencode

import numpy as np
from aiohttp import web

MAX_FRAMES = 10000
MAX_PIXELS = 16 * 1024 * 1024
MAX_ENTRY_BYTES = 32 * 1024 ** 3
MAX_CACHE_BYTES = 64 * 1024 ** 3
CACHE_TTL = 24 * 60 * 60
_LOCAL_MEDIA = ['-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm,avi,mxf']
_writer = threading.Lock()


def _linked(path):
    return path.is_symlink() or bool(getattr(path,'is_junction',lambda:False)())


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _digest(path, cancel=None):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block := stream.read(1024 * 1024):
            _cancelled(cancel)
            digest.update(block)
    return digest.hexdigest()


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise ValueError('SDR model input preparation was cancelled. The original is retained.')


def _rate(value):
    if isinstance(value, dict) and set(value) == {'numerator', 'denominator'}:
        if any(type(value[key]) is not int or value[key] < 1 for key in value):
            raise ValueError('Choose a valid rational source frame rate.')
        result = Fraction(value['numerator'], value['denominator'])
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        result = Fraction(str(value)).limit_denominator(1000000)
    else:
        raise ValueError('Choose the source sequence frame rate.')
    if not 1 <= result <= 240:
        raise ValueError('The source frame rate must be between 1 and 240 fps.')
    return result


def _range(body, metadata):
    start = body.get('startFrame', 0)
    count = body.get('frameCount', metadata['frame_count'] - start if type(start) is int else 0)
    if (type(start) is not int or type(count) is not int or start < 0 or not 1 <= count <= MAX_FRAMES
            or start + count > metadata['frame_count']):
        raise ValueError('Choose a source interval containing 1–10000 existing frames.')
    actual = _rate(metadata['frame_rate']) if metadata.get('frame_rate') else None
    requested = body.get('frameRate', body.get('sequenceFps'))
    declared = _rate(requested) if requested is not None else None
    if actual is not None and declared is not None and actual != declared:
        raise ValueError('The model input must preserve the original rational frame rate.')
    rate = actual or declared
    if rate is None and metadata['kind'] != 'image':
        raise ValueError('Choose the sequence frame rate before preparing its model input.')
    return start, count, rate


def _source_hash(original, start, count, cancel):
    files = original.get('files')
    if files is None:
        return _digest(original['path'], cancel), 'whole_file'
    # A FLOAT manifest already contains independently verified frame checksums.
    manifest = original['metadata'].get('manifest')
    if manifest is not None:
        return hashlib.sha256(_canonical(manifest)).hexdigest(), 'source_manifest'
    selected = [{'frame': start + index, 'name': path.name, 'sha256': _digest(path, cancel)}
                for index, path in enumerate(files[start:start + count])]
    return hashlib.sha256(_canonical(selected)).hexdigest(), 'selected_sequence_frames'


def _processor(space):
    from . import display_view_routes as display
    from ..comfylink import display_view
    info = display_view.describe()
    config = display_view._config(info['config'])
    names = display._SPACES.get(space)
    source = next((config.getColorSpace(name).getName() for name in names or () if config.getColorSpace(name)), None)
    if source is None:
        raise ValueError('Choose the actual mapped source colour space before preparing an SDR model input.')
    if space in {'srgb_display','rec709_oetf','rec709_gamma24'}:
        target = next((config.getColorSpace(name).getName() for name in display._SPACES['srgb_display'] if config.getColorSpace(name)), None)
        if target is None:raise ValueError('The installed colour configuration has no sRGB model input space.')
        return config.getProcessor(source,target).getDefaultCPUProcessor(), {
            'config':info['config'],'transform':'colourspace','source':source,'target':target,
            'configCacheId':config.getCacheID()}
    transform = display_view._ocio().DisplayViewTransform(src=source, display=info['display'], view=info['view'])
    return config.getProcessor(transform).getDefaultCPUProcessor(), {
        'config': info['config'], 'display': info['display'], 'view': info['view'],
        'configCacheId': config.getCacheID()}


def _encode(rgba, processor, alpha_association='straight'):
    if (rgba.ndim != 3 or rgba.shape[-1] != 4 or rgba.shape[0] * rgba.shape[1] > MAX_PIXELS
            or not np.isfinite(rgba).all() or np.any(rgba[..., 3] < 0) or np.any(rgba[..., 3] > 1)):
        raise ValueError('The original source has invalid samples, alpha or dimensions.')
    rgb = np.array(rgba[..., :3], dtype=np.float32, order='C')
    if alpha_association not in {'straight','premultiplied'}:raise ValueError('The source alpha interpretation is unknown.')
    if alpha_association=='premultiplied':
        alpha=rgba[...,3:4]
        np.divide(rgb,alpha,out=rgb,where=alpha>0)
        rgb[rgba[...,3]<=0]=0
    processor.applyRGB(rgb)
    if not np.isfinite(rgb).all():
        raise ValueError('The colour transform returned invalid model-input samples.')
    clipped = int(np.count_nonzero((rgb < 0) | (rgb > 1)))
    result = np.empty(rgba.shape, dtype=np.uint8)
    result[..., :3] = np.rint(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    result[..., 3] = np.rint(rgba[..., 3] * 255).astype(np.uint8)
    return result, clipped


def _validate_video_clock(info,start,count,cancel=None):
    """Verify selected PTS against the exact clock before any CFR renumbering.

    Encoded timestamps may round to their container time base (e.g. MKV's
    milliseconds), but must remain within half one actual tick of that clock.
    """
    import av
    rate=Fraction(info['fps_rational']);origin=previous=None;selected=0
    with av.open(info['path'],options={'protocol_whitelist':'file,pipe','format_whitelist':'mov,matroska,webm,avi,mxf'}) as clip:
        for index,frame in enumerate(clip.decode(video=0)):
            _cancelled(cancel)
            if frame.pts is None or frame.time_base is None:raise ValueError('The original video has missing frame timestamps. Conform it to a constant frame rate before importing.')
            tick=Fraction(frame.time_base);position=frame.pts*tick
            if tick<=0 or previous is not None and position<=previous:raise ValueError('The original video has duplicate or unordered frame timestamps.')
            if origin is None:origin=position
            if index>=start:
                expected=origin+Fraction(index,1)/rate
                if abs(position-expected)>tick/2:raise ValueError('The selected video has variable frame timing. Conform it to a constant frame rate before importing.')
                selected+=1
            previous=position
            if index+1>=start+count:break
    if selected!=count:raise ValueError('The original video ended before its selected frame interval.')
    _cancelled(cancel)


def _video_frames(info,start,count,cancel):
    """Decode selected encoded RGB as float planes, without a whole-clip cache."""
    from ..paintout.media_tools import find_media_tool
    _validate_video_clock(info,start,count,cancel)
    from .prores444 import selected_frames
    prores = selected_frames(info,start,count,lambda:_cancelled(cancel),max_pixels=MAX_PIXELS)
    if prores is not None:
        try:yield from prores
        finally:prores.close()
        return
    vf=f'trim=start_frame={start}:end_frame={start+count},setpts=PTS-STARTPTS'
    matrix={'bt2020nc':'bt2020','bt2020c':'bt2020','bt709':'bt709','smpte170m':'bt601'}.get(info.get('matrix'))
    if matrix:vf+=f',scale=in_color_matrix={matrix}:in_range={"pc" if info.get("range")=="pc" else "tv"}:out_range=pc'
    # Native RGB8 -> float through swscale can map 255 to 65280/65535.
    # Keep those integer codes exact; YUV/high-depth sources still decode to
    # float planes so their colour conversion and alpha are not quantised.
    rgb8=info.get('pixel_format') in {'rgb24','bgr24','rgb0','bgr0','0rgb','0bgr','rgba','bgra','argb','abgr','gbrp','gbrap'}
    command=[find_media_tool('ffmpeg'),'-v','error',*_LOCAL_MEDIA,'-i',info['path'],'-vf',vf,'-an','-sn',
        '-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgba' if rgb8 else 'gbrapf32le','-']
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    stopped=threading.Event()
    def watch():
        while not stopped.wait(.05):
            if cancel is not None and cancel.is_set():
                if process.poll() is None:process.terminate()
                return
    watcher=threading.Thread(target=watch,daemon=True);watcher.start()
    size=info['width']*info['height']*4*(1 if rgb8 else 4)
    try:
        for _ in range(count):
            data=bytearray()
            while len(data)<size:
                _cancelled(cancel)
                block=process.stdout.read(min(1024*1024,size-len(data)))
                if not block:
                    _cancelled(cancel)
                    raise ValueError('The original video ended before all selected model-input frames were decoded.')
                data.extend(block)
            if rgb8:rgba=np.frombuffer(data,dtype=np.uint8).reshape(info['height'],info['width'],4).astype(np.float32)/np.float32(255)
            else:
                planes=np.frombuffer(data,dtype='<f4').reshape(4,info['height'],info['width'])
                rgba=np.ascontiguousarray(planes[[2,0,1,3]].transpose(1,2,0))
                del planes
            del data
            yield rgba
    finally:
        stopped.set()
        if process.poll() is None:process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait()
        process.stdout.close();watcher.join(timeout=1)


def _frames(original, selector, start, count, colour, store, check_asset, roots,cancel=None):
    from . import display_view_routes as display
    if 'frame_time' in selector or 'imported_frame' in selector:
        rgba,space,_=display.read_original(selector,0,store,check_asset,roots,colour)
        yield rgba,space
    elif original['metadata']['kind'] == 'float_sequence':
        from ..comfylink import display_view,float_io
        manifest=original['metadata']['manifest'];source=manifest['colour']
        encoding=display_view._verified_ocio_source(source) if source.get('management')=='ocio' else source['encoding']
        space={'srgb8':'srgb_display','scene_linear_rec709':'linear_rec709'}.get(encoding,encoding)
        if space=='unknown':space='srgb_display' if manifest['sourceBitDepth']==8 else colour
        if space not in display._SPACES:raise ValueError('Choose the actual FLOAT source colour space.')
        for entry,path in zip(manifest['frames'][start:start+count],original['files'][start:start+count]):
            with float_io._locked_parents(path.parent):
                payload=float_io._read_private(path,entry['byteLength'],entry['byteLength'])
            if hashlib.sha256(payload).hexdigest()!=entry['sha256']:raise ValueError('An original FLOAT frame changed.')
            dtype='<f4' if manifest['sampleType']=='float32' else '<u2'
            rgba=np.frombuffer(payload,dtype=dtype).reshape(manifest['height'],manifest['width'],4).astype(np.float32)
            if manifest['sampleType']=='uint16_ae':rgba/=np.float32(32768)
            yield rgba,space
    elif original['metadata']['kind'] == 'video':
        from ..paintout.paintout import selected_space
        info = dict(original['metadata']['info'])
        space = selected_space(info, colour if colour != 'auto' else original['detectedColour'])
        for rgba in _video_frames(info,start,count,cancel):
            yield rgba, space
    elif original['metadata']['kind'] == 'sequence':
        for path in original['files'][start:start + count]:
            from ..paintout.paintout import _exr_auto_space
            space = (colour if colour != 'auto' else original['detectedColour'] if original['detectedColour'] != 'auto'
                     else _exr_auto_space(str(path)) if path.suffix.lower() == '.exr' else 'srgb_display')
            yield display._image(path), space
    else:
        for frame in range(start, start + count):
            rgba, space, _ = display.read_original(selector, frame, store, check_asset, roots, colour)
            yield rgba, space


def _audio(path):
    import av
    with av.open(str(path),options={'protocol_whitelist':'file,pipe','format_whitelist':'mov,matroska,webm,avi,mxf'}) as container:
        return bool(container.streams.audio)


def _mux_audio(silent, target, source, start, count, rate, cancel):
    from ..paintout.media_tools import find_media_tool
    command = [find_media_tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y',
               *_LOCAL_MEDIA,'-i', str(silent), '-ss', str(float(start / rate)), *_LOCAL_MEDIA,'-i', str(source),
               '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'pcm_f32le',
               '-t', str(float(count / rate)), '-map_metadata', '-1', str(target)]
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        while process.poll() is None:
            _cancelled(cancel)
            time.sleep(.05)
        if process.returncode:
            raise ValueError('The selected original audio could not be attached to the SDR model input.')
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        if process.stderr is not None: process.stderr.close()


def _queued_views():
    protected=set()
    try:
        from server import PromptServer
        queue=getattr(getattr(PromptServer,'instance',None),'prompt_queue',None)
        entries=queue.get_current_queue() if queue is not None else ()
        def visit(value):
            if isinstance(value,str):protected.update(re.findall(r'(?:^|/)zura_model_views/([a-f0-9]{64})(?:/|$)',value.replace('\\','/')))
            elif isinstance(value,dict):
                for item in value.values():visit(item)
            elif isinstance(value,(list,tuple)):
                for item in value:visit(item)
        visit(entries)
    except (ImportError,AttributeError,RuntimeError):pass
    return protected


def _prune(cache, keep=None):
    entries = []
    now = time.time()
    protected=_queued_views()
    for folder in cache.iterdir():
        if not folder.is_dir() or _linked(folder) or len(folder.name) != 64 or any(c not in '0123456789abcdef' for c in folder.name):
            continue
        files = list(folder.iterdir())
        if any(not path.is_file() or path.is_symlink() or path.name not in {'source.png','source.mkv','view.json'} for path in files):
            continue
        try:
            record=json.loads((folder/'view.json').read_text(encoding='utf-8'))
            if record.get('owner')!='zura_model_view' or record.get('cacheKey')!=folder.name:continue
        except (OSError,ValueError):continue
        entries.append((folder, max((path.stat().st_mtime for path in files), default=folder.stat().st_mtime), sum(path.stat().st_size for path in files)))
    total = sum(item[2] for item in entries)
    for folder, modified, size in sorted(entries, key=lambda item: item[1]):
        if folder == keep or folder.name in protected or now - modified < CACHE_TTL and total <= MAX_CACHE_BYTES:
            continue
        if folder.resolve().is_relative_to(cache.resolve()):
            shutil.rmtree(folder)
            total -= size
    return total


def _proxy_info(path, processing, rate, input_root,cancel=None):
    from ..paintout.browser import describe_media
    info=describe_media(str(path),cancel=cancel)
    info.pop('colour_error',None)
    info.update(resolved_colour='srgb_display',processingView={**processing,'inferencePath':str(path),'inferenceStartFrame':0},
        inputRef={'type':'input','filename':path.name,'subfolder':path.parent.relative_to(input_root).as_posix()},
        thumbnail_url='/zura/paintout/frame-preview?'+urlencode({'file':str(path),'space':'srgb_display','frame':0,'size':1280}))
    if rate:info.update(frameRate={'numerator':rate.numerator,'denominator':rate.denominator},fps=float(rate))
    elif info.get('kind')=='image':info.pop('fps',None)
    return info


def prepare(body, store, check_asset, roots, cancel=None):
    from . import display_view_routes as display
    from PIL import Image
    import av
    from .media_import import cancellation_checked_asset
    check_asset=cancellation_checked_asset(check_asset,roots,cancel)

    allowed = {'source', 'colour_space', 'startFrame', 'frameCount', 'frameRate', 'sequenceFps'}
    if not isinstance(body, dict) or set(body) - allowed or 'source' not in body:
        raise ValueError('Choose a valid source model-view request.')
    colour = body.get('colour_space', 'auto')
    if colour != 'auto' and colour not in display._SPACES:
        raise ValueError('Choose the actual source colour space.')
    original = display.resolve_original(body['source'], store, check_asset, roots,cancel=cancel)
    start, count, rate = _range(body, original['metadata'])
    original['revalidate']()
    source_hash, hash_scope = _source_hash(original, start, count, cancel)
    reader = _frames(original, body['source'], start, count, colour, store, check_asset, roots,cancel)
    try: first, space = next(reader)
    except StopIteration: raise ValueError('The original source has no selected frames.') from None
    processor, view = _processor(space)
    width, height = first.shape[1], first.shape[0]
    if not 1 <= width <= 16384 or not 1 <= height <= 16384 or width * height > MAX_PIXELS:
        raise ValueError('This source exceeds the model-view raster limit.')
    rate_json = {'numerator': rate.numerator, 'denominator': rate.denominator} if rate else None
    key = hashlib.sha256(_canonical({'version': 4, 'source': source_hash, 'sourcePath':str(original['path']), 'sourceTime':body['source'].get('frame_time'),'importedFrame':body['source'].get('imported_frame'), 'scope': hash_scope,
        'start': start, 'count': count, 'rate': rate_json, 'space': space, 'view': view})).hexdigest()
    input_root = Path(roots['input']).resolve()
    cache = input_root / 'zura_model_views'
    if _linked(cache):raise ValueError('The model-view cache cannot be a linked directory.')
    cache.mkdir(exist_ok=True)
    assert cache.resolve().is_relative_to(input_root)
    original_info = {'path': str(original['path']), 'name': original['path'].name,
        'kind': original['metadata']['kind'], 'width': width, 'height': height,
        'frames': original['metadata']['frame_count'], 'resolved_colour': space}
    if rate: original_info.update(fps=float(rate), frameRate=rate_json)
    if body['source'].get('source_token'): original_info['display_source'] = body['source']['source_token']
    if body['source'].get('asset_id'): original_info.update(studioAssetId=body['source']['asset_id'],id=body['source']['asset_id'])
    if 'frame_time' in body['source']:original_info['frame_time']=body['source']['frame_time']
    with _writer:
        _cancelled(cancel)
        target = cache / key
        remaining=_prune(cache,keep=target)
        if _linked(target): raise ValueError('The model-view cache is linked outside its owner.')
        info_path = target / 'view.json'
        if _linked(info_path):raise ValueError('The model-view cache metadata is linked.')
        if info_path.is_file():
            saved = json.loads(info_path.read_text(encoding='utf-8'))
            if saved.get('owner')!='zura_model_view' or saved.get('cacheKey')!=key or saved.get('proxyFilename') not in {'source.png','source.mkv'}:
                raise ValueError('The model-view cache does not belong to this request.')
            proxy = target / saved['proxyFilename']
            if proxy.is_file() and not _linked(proxy) and proxy.resolve().is_relative_to(cache.resolve()) and _digest(proxy, cancel) == saved['proxySha256']:
                original['revalidate']();reader.close()
                info_path.touch()
                return _proxy_info(proxy,{**saved['processingView'],'originalSource':original_info},rate,input_root,cancel)
            raise ValueError('A cached model input changed. Choose the source again before retrying.')
        if remaining>=MAX_CACHE_BYTES:raise ValueError('The model-input cache is in use. Finish the queued runs before preparing another large input.')
        partial = cache / (key + '-' + uuid.uuid4().hex + '.partial')
        partial.mkdir()
        filename = 'source.png' if original['metadata']['kind'] == 'image' or 'frame_time' in body['source'] or 'imported_frame' in body['source'] else 'source.mkv'
        output = partial / filename
        clipped = 0
        try:
            iterator = iter([(first, space)])
            def source_frames():
                yield from iterator
                yield from reader
            if filename.endswith('.png'):
                pixels, clipped = _encode(first, processor,original['metadata'].get('alpha_association','straight'));Image.fromarray(pixels, 'RGBA').save(output)
            else:
                silent = partial / 'silent.mkv'
                with av.open(str(silent), 'w') as container:
                    stream = container.add_stream('ffv1', rate=rate)
                    stream.width, stream.height, stream.pix_fmt = width, height, 'bgra'
                    stream.codec_context.color_primaries=1
                    stream.codec_context.color_trc=13
                    stream.codec_context.colorspace=0
                    actual_count = 0
                    for index, (rgba, actual_space) in enumerate(source_frames()):
                        _cancelled(cancel)
                        if actual_space != space or rgba.shape[:2] != (height, width):
                            raise ValueError('The source colour or raster changed during model-input preparation.')
                        pixels, outside = _encode(rgba, processor,original['metadata'].get('alpha_association','straight'));clipped += outside
                        frame = av.VideoFrame.from_ndarray(pixels, format='rgba');frame.pts=index;frame.time_base=1/rate
                        for packet in stream.encode(frame):container.mux(packet)
                        actual_count += 1
                        if silent.stat().st_size > MAX_ENTRY_BYTES:
                            raise ValueError('The selected model input exceeds the temporary cache limit. Choose a shorter range.')
                    for packet in stream.encode():container.mux(packet)
                if actual_count != count:raise ValueError('The decoded model input did not retain the complete selected range.')
                if original['metadata']['kind'] == 'video' and _audio(original['path']):
                    _mux_audio(silent, output, original['path'], start, count, rate, cancel)
                    silent.unlink()
                else:os.replace(silent, output)
                if output.stat().st_size>MAX_ENTRY_BYTES:raise ValueError('The selected model input exceeds the temporary cache limit. Choose a shorter range.')
                with av.open(str(output)) as media:
                    video=media.streams.video[0]
                    if video.average_rate != rate or video.width != width or video.height != height or sum(1 for _ in media.decode(video=0)) != count:
                        raise ValueError('The encoded SDR input changed its frame count, raster or rational rate.')
            _cancelled(cancel);original['revalidate']()
            processing = {'schemaVersion':1,'kind':'sdr8_inference','originalSource':original_info,
                'originalSourceSha256':source_hash,'sourceHashScope':hash_scope,'sourceColour':space,
                'originalStartFrame':start,'frameCount':count,'frameRate':rate_json,
                'boundedRGB':True,'clippedRGB':clipped>0,'clippedSampleCount':clipped,
                'modelBitDepth':8,'displayTransform':view,'inferenceStartFrame':0}
            saved={'owner':'zura_model_view','cacheKey':key,'proxyFilename':filename,'proxySha256':_digest(output,cancel),'processingView':processing}
            (partial/'view.json').write_bytes(_canonical(saved))
            if target.exists():raise ValueError('Another model-view writer changed this cache entry.')
            os.replace(partial,target)
            info=_proxy_info(target/filename,processing,rate,input_root,cancel)
            if _prune(cache,keep=target)>MAX_CACHE_BYTES:
                assert target.resolve().is_relative_to(cache.resolve())
                shutil.rmtree(target)
                raise ValueError('The model-input cache is in use. Finish the queued runs before preparing another large input.')
            return info
        finally:
            reader.close()
            if partial.exists() and partial.resolve().is_relative_to(cache.resolve()):shutil.rmtree(partial)


def register(studio, routes, response, check_asset):
    from .route_aliases import require_studio_alias_paths
    require_studio_alias_paths(routes,(('POST','model-view'),))
    import folder_paths
    limit=asyncio.Semaphore(1)

    @routes.post('/zura/studio/model-view')
    @routes.post('/genj/studio/model-view')
    @response
    async def model_view(request):
        from ..media_source import require_same_origin
        from ..comfylink.studio_sessions import _bounded_json
        require_same_origin(request)
        if request.content_length is not None and request.content_length>16384:
            raise ValueError('The model-view request is too large.')
        body=await _bounded_json(request.content,16384)
        roots={'input':folder_paths.get_input_directory(),'output':folder_paths.get_output_directory(),'temp':folder_paths.get_temp_directory()}
        cancel=threading.Event()
        async with limit:
            task=asyncio.create_task(asyncio.to_thread(prepare,body,studio.store,check_asset,roots,cancel))
            original_transport=getattr(request,'transport',None)
            try:
                while not task.done():
                    transport=getattr(request,'transport',None)
                    if original_transport is not None and (transport is None or transport.is_closing()):cancel.set()
                    await asyncio.wait({task},timeout=.2)
                return web.json_response(await task,headers={'Cache-Control':'no-store'})
            except asyncio.CancelledError:
                cancel.set()
                task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
                raise
