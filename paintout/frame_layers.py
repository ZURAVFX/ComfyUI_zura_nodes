"""Independent clean-frame paint layers and reversible CPU recomposition."""
import asyncio
import base64
import io
import secrets
from pathlib import Path
import numpy as np
import torch
from PIL import Image
from aiohttp import web
from scipy.ndimage import distance_transform_edt, label
from .paintout import COLOUR_SPACES, describe, frames, selected_space, read_image, is_hdr, to_linear, working, sdr_view, save_exr, protection_mask


def encode_layer_mask(mask):
    stream = io.BytesIO()
    Image.fromarray(np.round(np.clip(mask, 0, 1)*255).astype(np.uint8)).save(stream, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode('ascii')


def load_layer_image(file, colour_space, shape):
    from .browser import checked_path
    from .frame_editor import validate_edit_orientation
    path = checked_path(file)
    if not path.is_file() or path.suffix.lower() not in ('.png', '.tif', '.tiff', '.exr') or path.stat().st_size > 512*1024*1024:
        raise ValueError('Choose a clean PNG, TIFF or EXR frame smaller than 512 MB.')
    if colour_space not in COLOUR_SPACES or colour_space == 'auto':
        raise ValueError('Choose the saved clean frame colour space explicitly.')
    validate_edit_orientation(path)
    pixels = read_image(str(path))
    if pixels.shape != (*shape, 3) or not np.isfinite(pixels).all():
        raise ValueError('The clean frame must contain finite RGB pixels matching the original plate dimensions.')
    return pixels, colour_space


def validate_blend_pixels(value):
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError('Layer blend edge must be a whole number from 0 to 100 pixels.')
    return value


def validate_brightness_ev(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or not -2 <= value <= 2:
        raise ValueError('Layer brightness must be a number from -2 to +2 stops.')
    return float(value)


def adjust_brightness(pixels, brightness_ev, linear=False):
    """An unclipped exposure change, in scene-linear or decoded sRGB light."""
    brightness_ev = validate_brightness_ev(brightness_ev)
    if brightness_ev == 0:
        return pixels
    if linear:
        return pixels * np.float32(2.0**brightness_ev)
    source = np.asarray(pixels, dtype=np.float32)
    decoded = np.where(source <= .04045, source/12.92, ((np.maximum(source, 0)+.055)/1.055)**2.4)
    decoded *= np.float32(2.0**brightness_ev)
    return np.where(decoded <= .0031308, decoded*12.92, 1.055*np.maximum(decoded, 0)**(1/2.4)-.055).astype(np.float32)


def inward_layer_alpha(mask, blend_pixels=0):
    """Blend real joins in-frame, while keeping an off-screen repair opaque."""
    blend_pixels = validate_blend_pixels(blend_pixels)
    support = mask > .001
    if not blend_pixels or support.all() or not support.any():
        return mask.copy()
    # Image boundaries are not a join to original pixels. Extend edge coverage
    # instead of introducing an artificial zero border around the image.
    distance = distance_transform_edt(np.pad(support, 1, mode='edge'))[1:-1, 1:-1]
    ramp = np.clip((distance-.5)/blend_pixels, 0, 1).astype(np.float32)
    contact = np.zeros_like(support)
    contact[0] = support[0]; contact[-1] = support[-1]
    contact[:, 0] = support[:, 0]; contact[:, -1] = support[:, -1]
    if contact.any():
        # Even a thin clipped object must not return at the frame boundary.
        # Fade this continuation smoothly inward, only on edge-connected pieces.
        components, _ = label(support)
        edge_components = np.unique(components[contact])
        continued = np.clip(1-distance_transform_edt(~contact)/blend_pixels, 0, 1)
        continued *= np.isin(components, edge_components)
        ramp = np.maximum(ramp, continued)
    return mask * ramp


def compose_pixels(original, layers, protection=None, linear=False):
    """Each cumulative candidate contributes only its own independent paint mask."""
    result = original.copy()
    for layer in layers:
        if not isinstance(layer, (tuple, list)) or len(layer) not in (2, 3, 4):
            raise ValueError('Each clean-frame layer needs pixels, a mask and optional blend and brightness controls.')
        pixels, mask = layer[:2]
        brightness_ev = validate_brightness_ev(layer[3] if len(layer) == 4 else 0)
        blend_pixels = validate_blend_pixels(layer[2] if len(layer) >= 3 else 0)
        if pixels.shape != original.shape or mask.shape != original.shape[:2] or not np.isfinite(pixels).all() or not np.isfinite(mask).all() or np.any((mask < 0) | (mask > 1)):
            raise ValueError('Each layer and mask must match the finite original frame.')
        alpha = inward_layer_alpha(mask, blend_pixels)
        if protection is not None:
            if protection.shape != mask.shape or not np.isfinite(protection).all():
                raise ValueError('The protection mask must match the frame.')
            alpha[protection > .001] = 0
        active = alpha > 0
        result[active] = result[active]*(1-alpha[active,None]) + adjust_brightness(pixels[active], brightness_ev, linear)*alpha[active,None]
    return result


def compose_layers(body):
    from .browser import checked_path, grant
    from .editor_store import load_project, source_identity, mask_descriptor, RevisionConflict
    from .frame_editor import decode_mask, save_png16
    import folder_paths
    if not isinstance(body, dict):
        raise ValueError('Choose clean-frame layers to compose.')
    layers = body.get('layers')
    if not isinstance(layers, list) or not 1 <= len(layers) <= 32:
        raise ValueError('Compose between 1 and 32 clean-frame layers.')
    document = load_project(body['project'])
    expected = body.get('expected_revision')
    if expected is not None and int(expected) != document['revision']:
        raise RevisionConflict('This project changed. Reload its latest edit before composing layers.')
    source = checked_path(body['source'])
    saved_source = document.get('data', {}).get('draft', {}).get('source')
    if not saved_source or checked_path(saved_source) != source:
        raise ValueError('Compose clean frames in their original shot project.')
    description = describe(str(source))
    frame = body['frame']
    if isinstance(frame, bool) or not isinstance(frame, int) or not 0 <= frame < description['count']:
        raise ValueError('Choose a frame inside the original source.')
    if description['width']*description['height'] > 40_000_000:
        raise ValueError('The source frame is too large for interactive paint layers.')
    before = source_identity(str(source), description)
    space = selected_space(description, body.get('colour_space', 'auto'))
    encoded = next(frames(description, frame, 1))
    hdr = is_hdr(space) or any(isinstance(layer, dict) and is_hdr(layer.get('colour_space', '')) for layer in layers)
    original = to_linear(torch.from_numpy(encoded.copy()).float(), space).numpy() if hdr else working(torch.from_numpy(encoded.copy())[None].float(), space, 'SDR (sRGB)')[0].numpy()
    if not np.isfinite(original).all():
        raise ValueError('The source contains invalid pixels.')
    protection = None
    try:
        descriptor = mask_descriptor(body['project'])
    except ValueError as error:
        if 'Create a removal mask' not in str(error): raise
    else:
        if descriptor['source'] != before:
            raise ValueError('The saved protection belongs to different or modified footage.')
        protection = protection_mask(descriptor, frame)
    def prepared_layers():
        for layer in layers:
            if not isinstance(layer, dict): raise ValueError('Each clean-frame layer needs a saved file and mask.')
            blend_pixels = validate_blend_pixels(layer.get('blend_pixels', 0))
            brightness_ev = validate_brightness_ev(layer.get('brightness_ev', 0))
            pixels, colour = load_layer_image(layer['file'], layer.get('colour_space', 'srgb_display'), original.shape[:2])
            pixels = to_linear(torch.from_numpy(pixels.copy()).float(), colour).numpy() if hdr else working(torch.from_numpy(pixels.copy())[None].float(), colour, 'SDR (sRGB)')[0].numpy()
            yield pixels, decode_mask(layer['mask'], description['width'], description['height']), blend_pixels, brightness_ev
    result = compose_pixels(original, prepared_layers(), protection, linear=hdr)
    if source_identity(str(source), describe(str(source))) != before:
        raise ValueError('The source changed while composing. Reload the footage.')
    directory = Path(folder_paths.get_output_directory())/'paintout'/'clean_frames'; directory.mkdir(parents=True, exist_ok=True)
    stem = f'layers_{frame:06d}_{secrets.token_hex(6)}'; master = directory/(stem+'.exr'); png = directory/(stem+'.png')
    colour = 'acescg' if hdr else 'srgb_display'
    save_exr(str(master), result, colour, False)
    preview = sdr_view(torch.from_numpy(result), True).numpy() if hdr else result
    save_png16(png, preview)
    return dict(file=str(master), png_file=str(png), url=grant(png), master_url=grant(master), frame=frame, colour_space=colour, preview_colour_space='srgb_display', width=result.shape[1], height=result.shape[0],
                blend_widths=[layer.get('blend_pixels', 0) for layer in layers],
                brightness_values=[validate_brightness_ev(layer.get('brightness_ev', 0)) for layer in layers])


async def compose_layers_route(request):
    from ..media_source import require_same_origin
    from .editor_store import RevisionConflict
    require_same_origin(request)
    try:
        if request.content_length is not None and request.content_length > 128*1024*1024:
            raise ValueError('The clean-frame layer request is too large.')
        body = await request.json()
        return web.json_response(await asyncio.to_thread(compose_layers, body))
    except RevisionConflict as error:
        return web.json_response({'error': str(error)}, status=409)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return web.json_response({'error': str(error)}, status=400)


def register_routes():
    from server import PromptServer
    server = getattr(PromptServer, 'instance', None)
    if server is not None and ('POST', '/zura/paintout/editor/compose-layers') not in {(route.method, route.path) for route in server.routes}:
        server.routes.post('/zura/paintout/editor/compose-layers')(compose_layers_route)
