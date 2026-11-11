"""Float environment-map operations; previews never become the HDR master."""
from __future__ import annotations

import math
import numpy as np


def rotate_environment(image, degrees):
    width = image.shape[1]
    shift = float(degrees) * width / 360
    positions = np.arange(width) - shift
    left = np.floor(positions).astype(np.int64)
    fraction = (positions-left)[None, :, None]
    return (image[:, left % width]*(1-fraction) + image[:, (left+1) % width]*fraction).astype(np.float32)


def build_environment(linear_rgb, yaw=0, exposure=0, lights=()):
    image = np.asarray(linear_rgb, np.float32)
    if image.ndim != 3 or image.shape[-1] != 3 or image.shape[1] != 2*image.shape[0]:
        raise ValueError('An environment map must be a 2:1 equirectangular RGB image. Compose a panorama first.')
    if not np.isfinite(image).all() or not all(math.isfinite(float(v)) for v in (yaw, exposure)):
        raise ValueError('The environment contains invalid pixels or controls.')
    if not -20 <= float(exposure) <= 20 or len(lights) > 16:
        raise ValueError('Use exposure from -20 to 20 stops and at most 16 lights.')
    result = rotate_environment(image, yaw)
    height, width = image.shape[:2]
    azimuth = (np.arange(width)+.5)/width*2*np.pi-np.pi
    elevation = np.pi/2-(np.arange(height)+.5)/height*np.pi
    for light in lights:
        az, el, radius, stops = [float(light.get(k, default)) for k, default in
                                 [('azimuth',0),('elevation',30),('radius',5),('stops',6)]]
        color = np.asarray(light.get('color',[1,1,1]), np.float32)
        if (not np.isfinite([az,el,radius,stops]).all() or not .1 <= radius <= 90 or not -90 <= el <= 90
                or not -10 <= stops <= 24 or color.shape != (3,) or not np.isfinite(color).all() or (color<0).any()):
            raise ValueError('Choose valid light direction, size, intensity and RGB colour.')
        delta = azimuth-np.radians(az+float(yaw))
        cosine = np.sin(elevation)[:,None]*np.sin(np.radians(el)) + np.cos(elevation)[:,None]*np.cos(np.radians(el))*np.cos(delta)[None]
        angle = np.arccos(np.clip(cosine,-1,1))
        power = np.exp(-.5*(angle/max(np.radians(radius)/2,1e-6))**2) * 2**stops
        result += power[...,None].astype(np.float32)*color
    result *= 2**float(exposure)
    if not np.isfinite(result).all(): raise ValueError('The chosen lighting exceeds the float export range.')
    return result


def read_environment(path, color_space='auto'):
    import torch
    import OpenImageIO as oiio
    from ..paintout.paintout import read_image, to_linear, _exr_auto_space
    from pathlib import Path
    header = oiio.ImageInput.open(str(path))
    if not header: raise ValueError('Could not read the environment image.')
    try:
        spec = header.spec()
        if spec.width*spec.height > 8192*4096: raise ValueError('Use an environment up to 8K × 4K.')
    finally: header.close()
    pixels = read_image(str(path))
    if color_space == 'auto':
        color_space = _exr_auto_space(path) if Path(path).suffix.lower()=='.exr' else 'linear_rec709' if Path(path).suffix.lower()=='.hdr' else 'srgb_display'
    if color_space not in ('acescg','linear_rec709','srgb_display'):
        raise ValueError('Choose ACEScg, linear sRGB or sRGB for the environment.')
    linear = to_linear(torch.from_numpy(pixels.copy()),color_space).numpy()
    return linear, color_space


def preview_environment(linear_aces, view_exposure=0):
    import torch
    from ..paintout.paintout import from_linear
    if not math.isfinite(float(view_exposure)) or not -12 <= float(view_exposure) <= 12:
        raise ValueError('Choose a preview exposure from -12 to 12 stops.')
    linear = from_linear(torch.from_numpy(np.asarray(linear_aces,np.float32)), 'linear_rec709').numpy()*2**float(view_exposure)
    linear = np.maximum(linear,0)
    if np.max(linear)>1.0001:
        # Preserve ordinary midtones; only roll bright HDR highlights into
        # the display range. This curve is NEVER used by EXR export.
        high = np.maximum(linear-.8,0)
        linear = np.where(linear<=.8,linear,.8+.2*(1-np.exp(-high/.2)))
    return np.clip(np.where(linear<=.0031308,12.92*linear,1.055*np.power(linear,1/2.4)-.055),0,1).astype(np.float32)



def write_environment(path, linear_aces, color_space='acescg'):
    import torch
    import OpenImageIO as oiio
    from ..paintout.paintout import from_linear
    if color_space not in ('acescg','linear_rec709'):
        raise ValueError('HDR lighting exports must use a linear colour space.')
    result = from_linear(torch.from_numpy(np.asarray(linear_aces,np.float32)),color_space).numpy()
    spec = oiio.ImageSpec(result.shape[1],result.shape[0],3,oiio.FLOAT)
    spec.channelnames = ['R','G','B'];spec.attribute('oiio:ColorSpace','ACEScg' if color_space=='acescg' else 'Linear Rec.709')
    spec.attribute('compression','zip')
    out = oiio.ImageOutput.create(str(path))
    if out is None or not out.open(str(path),spec): raise ValueError('Could not create the float EXR environment.')
    try:
        if not out.write_image(np.ascontiguousarray(result)):raise ValueError('Could not save the environment pixels.')
    finally:out.close()


def summary(image):
    peak = float(np.max(image))
    return {'width':int(image.shape[1]),'height':int(image.shape[0]),'peak_linear':peak,'hdr_range':peak>1.0001}
