"""Optional, exact-canvas SDR image guides for LTX frame extension."""
from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

from PIL import Image, ImageOps


def guide_asset(studio, identity, selection, check_asset):
    asset = studio.store.load(identity)
    if asset.get('asset_kind') != 'image':
        raise ValueError('Choose an uploaded first-frame image.')
    path = check_asset(asset)
    with Image.open(path) as image:
        actual = ImageOps.exif_transpose(image).size
    expected = (selection['width'], selection['height'])
    if actual != expected:
        raise ValueError(f'The first-frame guide is {actual[0]} × {actual[1]} px. Supply the complete expanded frame at {expected[0]} × {expected[1]} px.')
    return asset


def prepare_anchor(asset, selection, check_asset):
    """Pad only the model grid, never stretch or crop the artist's image."""
    import folder_paths
    from .studio import sha
    path = check_asset(asset)
    width, height = selection['width'], selection['height']
    padded = ((width + 63) // 64 * 64, (height + 63) // 64 * 64)
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        if image.size != (width, height):
            raise ValueError('The first-frame guide dimensions changed. Upload it again.')
        if padded == image.size:
            return asset['file']
        result = Image.new('RGB', padded)
        result.paste(image, (0, 0))
        # Extend border pixels through the invisible model-only padding.
        if padded[0] > width:
            result.paste(image.crop((width-1, 0, width, height)).resize((padded[0]-width, height)), (width, 0))
        if padded[1] > height:
            result.paste(result.crop((0, height-1, padded[0], height)).resize((padded[0], padded[1]-height)), (0, height))
        relative = f'genj_studio/outpaint-guides/{sha(path)}-{padded[0]}x{padded[1]}.png'
        target = Path(folder_paths.get_input_directory()) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        result.save(target, format='PNG')
    return relative


def create_canvas(studio, source, body, check_asset):
    """Extract the selected first source frame and reproduce the visible canvas."""
    import folder_paths
    from .outpaint_studio import plan
    from .studio import sha
    fields = {key: body[key] for key in ('start', 'mode', 'width', 'height', 'left', 'top', 'right', 'bottom')}
    selection = plan(source, duration=min(.125, float(body['duration'])), **fields)
    source_path = check_asset(source)
    executable = shutil.which('ffmpeg')
    if not executable:
        raise ValueError('FFmpeg is needed to prepare the first-frame image.')
    identity = uuid.uuid4().hex
    folder = Path(folder_paths.get_input_directory()) / 'genj_studio' / identity
    folder.mkdir(parents=True, exist_ok=False)
    extracted = folder / 'source.png'
    try:
        process = subprocess.run([executable, '-v', 'error', '-ss', str(selection['start']),
            '-i', str(source_path), '-frames:v', '1', '-update', '1', str(extracted)],
            capture_output=True, timeout=60)
        if process.returncode or not extracted.is_file():
            raise ValueError('Could not read the selected first frame. Check the source video and trim range.')
        with Image.open(extracted) as image:
            image = image.convert('RGB')
            width, height = selection['width'], selection['height']
            canvas = Image.new('RGB', (width, height))
            if selection['mode'] == 'black':
                if image.size != canvas.size:
                    raise ValueError('The black-padded source dimensions changed. Reload the video.')
            else:
                box_width = width-selection['left']-selection['right']
                box_height = height-selection['top']-selection['bottom']
                scale = min(box_width/image.width, box_height/image.height)
                fitted_width = min(box_width, max(1, round(image.width*scale)))
                fitted_height = min(box_height, max(1, round(image.height*scale)))
                x = selection['left']+(box_width-fitted_width)//2
                y = selection['top']+(box_height-fitted_height)//2
                scale_x, scale_y = image.width/fitted_width, image.height/fitted_height
                image = image.transform((width, height), Image.Transform.AFFINE,
                    (scale_x, 0, -x*scale_x, 0, scale_y, -y*scale_y),
                    resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0))
                bounds = (max(0,x),max(0,y),min(width,x+fitted_width),min(height,y+fitted_height))
                if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                    raise ValueError('The footage falls outside the output canvas. Reposition it first.')
                canvas.paste(image.crop(bounds), bounds[:2])
            if selection['mode'] == 'black':
                canvas.paste(image, (0, 0))
            output = folder / 'canvas.png'
            canvas.save(output, format='PNG')
        asset = {'id': identity, 'kind': 'asset', 'asset_kind': 'image',
                 'file': f'genj_studio/{identity}/canvas.png', 'sha': sha(output),
                 'name': 'Expanded first frame.png', 'width': width, 'height': height}
        studio.store.save(asset)
        return asset
    finally:
        extracted.unlink(missing_ok=True)
