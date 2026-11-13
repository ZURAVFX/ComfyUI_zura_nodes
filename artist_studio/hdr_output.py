"""Resolve an explicitly selected local output video for HDR conversion."""
from pathlib import Path


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
