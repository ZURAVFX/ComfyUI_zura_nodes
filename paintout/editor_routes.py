"""Local full-resolution overlay previews and validated edited-frame imports."""
from .media_tools import find_media_tool
import asyncio
import io
import re
import secrets
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image
from aiohttp import web

from .browser import checked_path, grant
from .editor_store import (_decode_paint, effective_mask, project_dir, load_project, mask_descriptor, source_identity,
                           commit_mask_pass, project_response, RevisionConflict, choose_mask_candidate)
from .paintout import describe, read_image, selected_space, COLOUR_SPACES, protection_mask
from .frame_editor import validate_edit_orientation


async def effective_preview(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        body = await request.json()
        width, height = int(body['width']), int(body['height'])
        if not 1 <= width <= 16384 or not 1 <= height <= 16384 or width * height > 40_000_000:
            raise ValueError('Source dimensions are too large for an interactive mask.')
        def render():
            mask = _decode_paint(body['mask'], width, height)
            protection = None
            if body.get('project'):
                descriptor = mask_descriptor(body['project'], int(body['revision']))
                source = str(checked_path(body['source']))
                if descriptor['source'] != source_identity(source, describe(source)):
                    raise ValueError('This protection belongs to different or modified footage.')
                protection = protection_mask(descriptor, int(body['frame']))
            alpha = effective_mask(mask, int(body.get('grow', 0)), int(body.get('feather', 0)), protection)
            stream = io.BytesIO()
            Image.fromarray(np.round(alpha * 255).astype(np.uint8)).save(stream, format='PNG')
            return stream.getvalue()
        return web.Response(body=await asyncio.to_thread(render), content_type='image/png', headers={'Cache-Control': 'no-store'})
    except (ValueError, KeyError, TypeError, OSError) as error:
        return web.json_response({'error': str(error)}, status=400)


def _validated_frame_result(target, description, frame, colour):
    """Validate the owned snapshot, so later external edits cannot alter a guide."""
    validate_edit_orientation(target)
    pixels = read_image(str(target))
    if pixels.shape[:2] != (description['height'], description['width']):
        raise ValueError('Edited frame dimensions must match the original source exactly.')
    if not np.isfinite(pixels).all():
        raise ValueError('The edited frame contains invalid pixel values. Export a finite image before importing.')
    if colour not in COLOUR_SPACES:
        raise ValueError('Choose the edited image colour space.')
    if colour == 'auto':
        colour = selected_space(description, colour)
    return dict(file=str(target), frame=frame, colour_space=colour, url=grant(target),
                width=description['width'], height=description['height'])


def import_local_image(body):
    document = load_project(body['project'])
    source = checked_path(body['source'])
    saved_source = document.get('data', {}).get('draft', {}).get('source')
    if not saved_source or checked_path(saved_source) != source:
        raise ValueError('Import the edited frame into its original shot project.')
    description = describe(str(source))
    frame = int(body.get('frame', -1))
    if not 0 <= frame < description['count']:
        raise ValueError('Choose a frame inside the original source.')
    original = checked_path(body['file'])
    if not original.is_file() or original.suffix.lower() not in ('.png', '.tif', '.tiff', '.exr'):
        raise ValueError('Choose an edited PNG, TIFF or EXR frame.')
    limit = 100 * 1024 * 1024
    if original.stat().st_size > limit:
        raise ValueError('The edited frame exceeds 100 MB.')
    target = project_dir(body['project']) / 'imports' / (secrets.token_hex(12) + original.suffix.lower())
    target.parent.mkdir(exist_ok=True)
    created = False
    try:
        # Bound the copy too, in case another app changes the source during import.
        with original.open('rb') as source_stream, target.open('xb') as owned_stream:
            created = True
            copied = 0
            while True:
                chunk = source_stream.read(1024 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > limit:
                    raise ValueError('The edited frame exceeds 100 MB.')
                owned_stream.write(chunk)
        return _validated_frame_result(target, description, frame, body.get('colour_space', 'srgb_display'))
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


async def import_local_frame(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Choose an edited frame to import.')
        return web.json_response(await asyncio.to_thread(import_local_image, body))
    except (ValueError, KeyError, TypeError, OSError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def import_frame(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    target = None
    try:
        reader = await request.multipart()
        fields = {}
        upload = None
        async for part in reader:
            if part.filename:
                suffix = Path(part.filename).suffix.lower()
                if suffix not in ('.png', '.exr', '.tif', '.tiff'):
                    raise ValueError('Choose an edited PNG, TIFF or EXR frame.')
                if upload is not None:
                    raise ValueError('Import one edited frame at a time.')
                content = bytearray()
                while True:
                    chunk = await part.read_chunk()
                    if not chunk:
                        break
                    content.extend(chunk)
                    if len(content) > 100 * 1024 * 1024:
                        raise ValueError('The edited frame exceeds 100 MB.')
                upload = (suffix, content)
            else:
                fields[part.name] = await part.text()
        if not upload:
            raise ValueError('Choose an edited frame.')
        project = fields.get('project')
        document = load_project(project)
        source = checked_path(fields.get('source'))
        saved_source = document.get('data', {}).get('draft', {}).get('source')
        if not saved_source or checked_path(saved_source) != source:
            raise ValueError('Import the edited frame into its original shot project.')
        description = await asyncio.to_thread(describe, str(source))
        frame = int(fields.get('frame', -1))
        if not 0 <= frame < description['count']:
            raise ValueError('Choose a frame inside the original source.')
        target = project_dir(project) / 'imports' / (secrets.token_hex(12) + upload[0])
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(upload[1])
        result = await asyncio.to_thread(_validated_frame_result, target, description, frame, fields.get('colour_space', 'srgb_display'))
        return web.json_response(result)
    except (ValueError, OSError, TypeError) as error:
        if target and target.exists():
            target.unlink()
        return web.json_response({'error': str(error)}, status=400)


def save_painted_frame(body):
    """Commit one binary frame without inference; adjacent masks remain immutable."""
    project = body['project']
    document = load_project(project)
    expected = body.get('expected_revision')
    if expected is None or int(expected) < 0 or int(expected) != document['revision']:
        raise RevisionConflict('This mask changed. Reload the latest edit before saving your correction.')
    if 'expected_mask_revision' in body and body['expected_mask_revision'] != document['mask_revision']:
        raise RevisionConflict('The selected mask changed. Reload the latest edit before saving your correction.')
    source = checked_path(body['source'])
    saved_source = document.get('data', {}).get('draft', {}).get('source')
    if not saved_source or checked_path(saved_source) != source:
        raise ValueError('Paint the mask in its original shot project.')
    description = describe(str(source))
    frame = int(body['frame'])
    if not 0 <= frame < description['count']:
        raise ValueError('Choose a frame inside the original source.')
    width, height = description['width'], description['height']
    if not 1 <= width <= 16384 or not 1 <= height <= 16384 or width * height > 40_000_000:
        raise ValueError('Source dimensions are too large for an interactive mask.')
    if body.get('colour_space', 'srgb_display') not in COLOUR_SPACES:
        raise ValueError('Choose the source colour space.')
    # Zero is a valid edit: erasing the whole mask marks this frame explicitly clear.
    mask = (_decode_paint(body['mask'], width, height) >= .5).astype(np.float32)
    commit_mask_pass(project, source_identity(str(source), description), {frame: mask}, 'replace', int(expected),
                     metadata={'frame': frame, 'method': 'manual', 'manual_correction': True, 'segment_id': body.get('segment_id', '')}, preserve_protection=True)
    return project_response(load_project(project))


def _spool_mask_video(description, directory):
    """Decode in source frame order, retaining only one grayscale frame in memory."""
    width, height, count = description['width'], description['height'], description['count']
    command = [find_media_tool('ffmpeg'), '-v', 'error', '-i', description['path'], '-map', '0:v:0', '-an', '-sn',
               '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    result = {}
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
        try:
            for frame in range(count):
                pixels = bytearray()
                while len(pixels) < width * height:
                    chunk = process.stdout.read(width * height - len(pixels))
                    if not chunk:
                        raise ValueError('The mask video ended before all source frames were decoded.')
                    pixels.extend(chunk)
                binary = (np.frombuffer(pixels, np.uint8).reshape(height, width) >= 128).astype(np.uint8) * 255
                path = Path(directory) / f'{frame:08d}.png'
                Image.fromarray(binary).save(path)
                result[frame] = str(path)
            if process.stdout.read(1):
                raise ValueError('The mask video contains more frames than the source.')
            if process.wait() != 0:
                raise ValueError('The mask video could not be decoded. Export a constant-frame-rate black-and-white video.')
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.terminate()
            process.wait()
    return result


def import_mask_video(body):
    project = body['project']
    document = load_project(project)
    expected = body.get('expected_revision')
    if expected is None or int(expected) < 0 or int(expected) != document['revision']:
        raise RevisionConflict('This project changed. Reload the latest edit before importing a mask.')
    source, mask = checked_path(body['source']), checked_path(body['mask'])
    draft = document.get('data', {}).get('draft', {})
    if not draft.get('source') or checked_path(draft['source']) != source:
        raise ValueError('Import the mask into its original shot project.')
    description, mask_description = describe(str(source)), describe(str(mask))
    if mask_description['kind'] != 'video':
        raise ValueError('Choose a black-and-white mask video. White removes; black keeps.')
    if (mask_description['width'], mask_description['height']) != (description['width'], description['height']):
        raise ValueError('The mask video dimensions must match the original source exactly.')
    if mask_description['count'] != description['count']:
        raise ValueError('The mask video must contain exactly the same number of frames as the source.')
    def clock(value, fallback):
        return Fraction(str(value.get('fps_rational') or value.get('fps') or fallback))
    if clock(mask_description, 0) != clock(description, draft.get('sequenceFps', 25)):
        raise ValueError('The mask video frame rate must match the original source exactly.')
    width, height = description['width'], description['height']
    if not 1 <= width <= 16384 or not 1 <= height <= 16384 or width * height > 40_000_000:
        raise ValueError('Source dimensions are too large for an interactive mask.')
    identity = source_identity(str(source), description)
    mask_identity = source_identity(str(mask), mask_description)
    with tempfile.TemporaryDirectory(prefix='pending_import_', dir=project_dir(project)) as pending:
        masks = _spool_mask_video(mask_description, pending)
        if source_identity(str(source), describe(str(source))) != identity or source_identity(str(mask), describe(str(mask))) != mask_identity:
            raise ValueError('The footage or mask changed during import. Reload the files before importing again.')
        commit_mask_pass(project, identity, masks, 'replace', int(expected),
                         metadata={'method': 'import', 'mask_source': str(mask), 'segment_id': secrets.token_hex(12), 'tracked': True}, preserve_protection=True)
    return project_response(load_project(project))


async def import_mask(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Provide a mask video to import.')
        document = await asyncio.to_thread(import_mask_video, body)
        return web.json_response(document, headers={'Cache-Control': 'no-store'})
    except RevisionConflict as error:
        return web.json_response({'error': str(error)}, status=409)
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError, ZeroDivisionError) as error:
        return web.json_response({'error': str(error)}, status=400)



def save_watermark_layer(body):
    """Persist one painted static mask over the selected clip, with a trimmable active range."""
    from .mask_segments import commit_segment
    project = body['project']
    document = load_project(project)
    expected = body.get('expected_revision')
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != document['revision']:
        raise RevisionConflict('This layer changed. Reload the project and retry.')
    if document.get('data', {}).get('workspace') != 'watermark':
        raise ValueError('Paint watermark layers in a Watermark Removal project.')
    source = checked_path(body['source'])
    draft = document.get('data', {}).get('draft', {})
    if not draft.get('source') or checked_path(draft['source']) != source:
        raise ValueError('This layer belongs to different footage.')
    desc = describe(str(source))
    numbers = [body[k] for k in ('clip_start','clip_end','layer_start','layer_end')]
    if any(isinstance(v,bool) or not isinstance(v,int) for v in numbers):
        raise ValueError('Layer timing must use whole frame numbers.')
    clip_start, clip_end, start, end = numbers
    if not 0 <= clip_start <= start <= end <= clip_end < desc['count']:
        raise ValueError('Choose a layer range inside the clip.')
    if (clip_start,clip_end)!=(draft.get('startFrame'),draft.get('startFrame')+draft.get('frameCount')-1):
        raise ValueError('The clip range changed. Reload before saving this layer.')
    mask = (_decode_paint(body['mask'],desc['width'],desc['height']) >= .5).astype(np.float32)
    if not np.any(mask): raise ValueError('Paint the watermark before saving the layer.')
    metadata = dict(segment_id=body['segment_id'],method='watermark_static',tracked=True,layer_start=start,layer_end=end,frame=start)
    commit_segment(project,source_identity(str(source),desc),{i:mask for i in range(clip_start,clip_end+1)},'replace',expected,metadata)
    return project_response(load_project(project))



def export_watermark_mask(body):
    from .editor_store import read_project_mask
    project=body['project'];document=load_project(project);data=document.get('data',{})
    if data.get('workspace')!='watermark':raise ValueError('Choose a Watermark Removal project.')
    draft=data.get('draft',{});source=checked_path(body['source'])
    if not draft.get('source') or checked_path(draft['source'])!=source:raise ValueError('This mask belongs to different footage.')
    desc=describe(str(source));revision=body['revision'];start=body['start'];count=body['count'];grow=body.get('grow',0)
    if any(isinstance(v,bool) or not isinstance(v,int) for v in (revision,start,count,grow)) or not 0<=start<desc['count'] or not 1<=count<=desc['count']-start or not 0<=grow<=256:
        raise ValueError('Choose a valid mask revision, clip range and expansion.')
    descriptor=mask_descriptor(project,revision)
    if descriptor['source']!=source_identity(str(source),desc):raise ValueError('The source changed. Reload the footage.')
    if any(i not in descriptor['covered_frames'] for i in range(start,start+count)):raise ValueError('The mask does not cover the selected clip.')
    rate=Fraction(desc['fps_rational']) if desc.get('fps_rational') else Fraction(str(body.get('fps',25))).limit_denominator(100000)
    if rate<=0:raise ValueError('Choose a valid frame rate.')
    directory=project_dir(project)/'exports';directory.mkdir(exist_ok=True);filename='watermark_mask_'+secrets.token_hex(12)+'.mkv';target=directory/filename
    cmd=[find_media_tool('ffmpeg'),'-v','error','-y','-f','rawvideo','-pix_fmt','gray','-s',f"{desc['width']}x{desc['height']}",'-r',str(rate),'-i','-','-frames:v',str(count),'-an','-c:v','ffv1','-level','3','-pix_fmt','gray',str(target)]
    process=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for frame in range(start,start+count):
            mask=read_project_mask(project,frame,revision,grow,0);process.stdin.write(np.rint(mask*255).astype(np.uint8).tobytes())
        process.stdin.close();error=process.stderr.read().decode('utf8','replace');code=process.wait()
        if code:raise RuntimeError('Mask export failed: '+error[-1000:])
    except BaseException:
        if process.poll() is None:process.kill();process.wait()
        target.unlink(missing_ok=True);raise
    finally:
        if process.stdin and not process.stdin.closed:
            try:process.stdin.close()
            except OSError:pass
        if process.stderr:process.stderr.close()
    return {'filename':filename,'frames':count,'fps':str(rate)}


async def watermark_mask_export(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        body=await request.json();return web.json_response(await asyncio.to_thread(export_watermark_mask,body),headers={'Cache-Control':'no-store'})
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as error:
        return web.json_response({'error':str(error)},status=400)


async def watermark_mask_file(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        project=request.query['project'];filename=request.query['file'];document=load_project(project)
        if document.get('data',{}).get('workspace')!='watermark' or not re.fullmatch(r'watermark_mask_[0-9a-f]{24}\.mkv',filename):raise ValueError('Choose a saved watermark mask.')
        path=project_dir(project)/'exports'/filename
        if not path.is_file():raise ValueError('The mask export is unavailable.')
        return web.FileResponse(path,headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store'})
    except (ValueError,KeyError,OSError) as error:
        return web.json_response({'error':str(error)},status=400)

async def watermark_layer(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        body=await request.json()
        if not isinstance(body,dict): raise ValueError('Provide a painted watermark layer.')
        return web.json_response(await asyncio.to_thread(save_watermark_layer,body),headers={'Cache-Control':'no-store'})
    except RevisionConflict as error:
        return web.json_response({'error':str(error)},status=409)
    except (ValueError,KeyError,TypeError,OSError) as error:
        return web.json_response({'error':str(error)},status=400)

async def paint_mask(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Provide a painted-frame correction.')
        document = await asyncio.to_thread(save_painted_frame, body)
        return web.json_response(document, headers={'Cache-Control': 'no-store'})
    except RevisionConflict as error:
        return web.json_response({'error': str(error)}, status=409)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return web.json_response({'error': str(error)}, status=400)


async def select_mask_candidate(request):
    from ..media_source import require_same_origin
    require_same_origin(request)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('Choose a detected subject.')
        document = await asyncio.to_thread(choose_mask_candidate, body)
        return web.json_response(document, headers={'Cache-Control':'no-store'})
    except RevisionConflict as error:
        return web.json_response({'error':str(error)}, status=409)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return web.json_response({'error':str(error)}, status=400)


async def segment_range(request):
    from ..media_source import require_same_origin
    from .mask_segments import edit_segment
    require_same_origin(request)
    try:
        body = await request.json()
        return web.json_response(await asyncio.to_thread(edit_segment, body), headers={'Cache-Control': 'no-store'})
    except RevisionConflict as error:
        return web.json_response({'error': str(error)}, status=409)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return web.json_response({'error': str(error)}, status=400)


def register_routes():
    from server import PromptServer
    server = getattr(PromptServer, 'instance', None)
    if server is None:
        return
    existing = {(route.method, route.path) for route in server.routes}
    if ('GET','/zura/paintout/editor/watermark-mask-file') not in existing:
        server.routes.get('/zura/paintout/editor/watermark-mask-file')(watermark_mask_file)
    for path, handler in (('/zura/paintout/editor/watermark-mask-export', watermark_mask_export), ('/zura/paintout/editor/watermark-layer', watermark_layer), ('/zura/paintout/editor/segment-range', segment_range), ('/zura/paintout/editor/select-mask-candidate', select_mask_candidate), ('/zura/paintout/editor/effective-mask', effective_preview), ('/zura/paintout/editor/import-frame', import_frame), ('/zura/paintout/editor/import-local-frame', import_local_frame), ('/zura/paintout/editor/paint-mask', paint_mask), ('/zura/paintout/editor/import-mask', import_mask)):
        if ('POST', path) not in existing:
            server.routes.post(path)(handler)
    from . import import_review
    import_review.register_routes()
