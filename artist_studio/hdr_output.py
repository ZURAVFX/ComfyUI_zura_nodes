"""Resolve an explicitly selected local output video for HDR conversion."""
from pathlib import Path
import hashlib
import io
import json


def selected_output(root, ref):
    if not isinstance(ref, dict) or ref.get('type') != 'output':
        raise ValueError('Choose an available output video.')
    filename, subfolder = ref.get('filename'), ref.get('subfolder', '')
    if (not isinstance(filename, str) or not filename or Path(filename).name != filename
            or not isinstance(subfolder, str)):
        raise ValueError('Choose an available output video.')
    base = Path(root).resolve()
    path = (base / subfolder / filename).resolve()
    if not path.is_relative_to(base) or not path.is_file() or path.suffix.lower() not in ('.mp4', '.mov', '.mkv', '.webm'):
        raise ValueError('The selected output video is unavailable.')
    return path


def selected_image_output(root, ref, *, allow_transparency=False):
    """Resolve one explicit SDR still master without accepting arbitrary paths."""
    if not isinstance(ref, dict) or ref.get('type') != 'output':
        raise ValueError('Choose an available output image.')
    filename, subfolder = ref.get('filename'), ref.get('subfolder', '')
    if (not isinstance(filename, str) or not filename or Path(filename).name != filename
            or not isinstance(subfolder, str)):
        raise ValueError('Choose an available output image.')
    base = Path(root).resolve()
    path = (base / subfolder / filename).resolve()
    if (not path.is_relative_to(base) or not path.is_file()
            or path.suffix.lower() not in ('.png', '.tif', '.tiff')):
        raise ValueError('HDR image delivery needs an available PNG or TIFF master.')
    # The current HDR converter is RGB. Never discard a transparent layer's
    # alpha by quietly treating it as an ordinary colour image.
    from PIL import Image, ImageCms
    import io
    with Image.open(path) as image:
        profile=image.info.get('icc_profile')
        if profile:
            try:description=ImageCms.getProfileDescription(ImageCms.getOpenProfile(io.BytesIO(profile)))
            except Exception as exc:raise ValueError('The image colour profile cannot be verified as sRGB.') from exc
            if 'srgb' not in description.lower():
                raise ValueError('Convert this image master to sRGB before SDR-to-HDR delivery. Its embedded profile is retained.')
        if not allow_transparency and 'A' in image.getbands() and image.getchannel('A').getextrema() != (255, 255):
            raise ValueError('This image needs alpha-preserving HDR delivery. Its original master is retained.')
    return path


def selected_hdr_model_image(root, ref):
    """Use a separate SDR8 model copy of a receipted Image Layers EXR.

    The FLOAT EXR remains the selected return master and is never rewritten.
    Ordinary PNG/TIFF sources retain their existing path.
    """
    filename = ref.get('filename') if isinstance(ref, dict) else None
    if not isinstance(filename, str) or Path(filename).suffix.lower() != '.exr':
        return selected_image_output(root, ref, allow_transparency=True)
    if ref.get('type') != 'output' or Path(filename).name != filename or not isinstance(ref.get('subfolder',''), str):
        raise ValueError('Choose a receipted Image Layers EXR master.')
    base = Path(root).resolve()
    candidate = base / ref.get('subfolder','') / filename
    if candidate.is_symlink():
        raise ValueError('The Image Layers EXR master cannot be a link.')
    path = candidate.resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise ValueError('The Image Layers EXR master is unavailable.')
    from ..comfylink import float_io
    import numpy as np
    from PIL import Image
    rgba, proof = float_io.read_image_layer_exr(path, base)
    pixels = np.rint(np.clip(rgba[..., :3], 0, 1) * 255).astype(np.uint8)
    output = io.BytesIO()
    Image.fromarray(pixels, 'RGB').save(output, format='PNG')
    encoded = output.getvalue()
    original_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    identity = original_sha[:32] + '-' + proof['receiptSha256'][:16]
    parent = base / 'ZURA STUDIO'
    with float_io._locked_parents(base):
        if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
            raise ValueError('The HDR model-view parent is unsafe.')
        parent.mkdir(exist_ok=True)
    directory = parent / 'hdr-model-views'
    with float_io._locked_parents(parent):
        if directory.exists() and (directory.is_symlink() or not directory.is_dir()):
            raise ValueError('The HDR model-view directory is unsafe.')
        directory.mkdir(exist_ok=True)
    image = directory / (identity + '.png')
    receipt = directory / (identity + '.json')
    lineage = {'schemaVersion':1,'kind':'sdr8_model_view_from_image_layers_exr',
               'originalMasterSha256':original_sha,'productReceiptSha256':proof['receiptSha256'],
               'sourceImageSha256':proof['sourceImageSha256'],
               'processingRepresentation':'sdr8_code_values','samplePolicy':'clamp_round_unorm8',
               'colour':{'encoding':'srgb_display','sceneLinear':False},
               'width':pixels.shape[1],'height':pixels.shape[0],
               'modelPNG16Source':False,'modelPNG8Sha256':hashlib.sha256(encoded).hexdigest()}
    record = json.dumps(lineage, sort_keys=True, separators=(',', ':')).encode('utf-8')
    with float_io._locked_parents(directory):
        if image.exists():
            if image.is_symlink() or image.read_bytes() != encoded:
                raise ValueError('The saved HDR model view changed.')
        else:
            float_io._exclusive_write(image, encoded)
        if receipt.exists():
            if receipt.is_symlink() or receipt.read_bytes() != record:
                raise ValueError('The HDR model-view lineage changed.')
        else:
            float_io._exclusive_write(receipt, record)
    return image
