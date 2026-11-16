"""OCIO display-only previews of scoped float frames.

The returned PNG is a monitor preview. Source frames and exported masters are
never modified. Configurations are restricted to OCIO's built-in catalogue.
"""
from functools import lru_cache
from io import BytesIO
import hashlib
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image


DEFAULT_CONFIG = "ocio://studio-config-latest"
DEFAULT_DISPLAY = "sRGB - Display"
DEFAULT_VIEW = "Un-tone-mapped"
_SPACES = {
    "scene_linear_rec709": ("lin_rec709_srgb", "Linear Rec.709 (sRGB)", "Utility - Linear - sRGB",
                            "lin_srgb", "Utility - Linear - Rec.709", "lin_rec709"),
    "acescg": ("ACEScg", "lin_ap1", "ACES - ACEScg"),
    "acescct": ("ACEScct", "acescct_ap1", "ACES - ACEScct"),
    "srgb8": ("srgb_tx", "sRGB Encoded Rec.709 (sRGB)", "sRGB - Texture",
              "Utility - sRGB - Texture", "srgb_texture"),
}


def _ocio():
    try:
        import PyOpenColorIO as ocio
    except ImportError:
        raise ValueError("OpenColorIO is required for display previews") from None
    return ocio


def configurations():
    ocio = _ocio()
    entries = [(DEFAULT_CONFIG, "ACES studio config (latest)"),
               ("ocio://cg-config-latest", "ACES CG config (latest)")]
    entries.extend(("ocio://" + name, label) for name, label, *_ in ocio.BuiltinConfigRegistry().getBuiltinConfigs())
    entries.extend((item['name'], item['label']) for item in _adobe_records())
    return [{"name": name, "label": label} for name, label in dict(entries).items()]


@lru_cache(maxsize=32)
def _builtin_config(name):
    return _ocio().Config.CreateFromFile(name)


def _adobe_roots():
    roots = []
    for key in ('ProgramFiles', 'ProgramFiles(x86)'):
        base = os.environ.get(key)
        if base:
            root = Path(base) / 'Adobe' / 'Adobe After Effects 2026' / 'Support Files' / 'OpenColorIO-Configs'
            if root.is_dir():
                resolved = root.resolve(strict=True)
                if resolved not in roots:
                    roots.append(resolved)
    return tuple(str(root) for root in roots)


@lru_cache(maxsize=8)
def _scan_adobe_records(roots):
    records = []
    for root_text in roots:
        root = Path(root_text)
        for path in sorted(root.rglob('*.ocio')):
            if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 16 * 1024 * 1024:
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                continue
            relative = resolved.relative_to(root)
            digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
            identity = 'adobe-ae://' + digest + '/' + hashlib.sha256(str(relative).encode()).hexdigest()[:12]
            records.append({'name': identity, 'label': relative.parent.as_posix() or relative.stem,
                            'path': str(resolved), 'sha256': digest})
    return tuple(records)


def _adobe_records():
    return _scan_adobe_records(_adobe_roots())


def _config(name):
    if name not in {item["name"] for item in configurations()}:
        raise ValueError("Unknown display configuration")
    if name.startswith('adobe-ae://'):
        record = next(item for item in _adobe_records() if item['name'] == name)
        path = Path(record['path'])
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024 or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('The installed Adobe display configuration changed')
        return _builtin_config(str(path))
    return _builtin_config(name)


def _source_configuration(colour):
    records = _adobe_records()
    if colour and colour.get('management') == 'ocio':
        source_path = colour.get('ocioConfigPath')
        if isinstance(source_path, str):
            for record in records:
                if (os.path.normcase(os.path.normpath(record['path'])) == os.path.normcase(os.path.normpath(source_path))
                        and record['sha256'] == colour.get('ocioConfigFileSha256')):
                    return record['name']
    if records and colour and colour.get('management') == 'icc':
        return records[0]['name']
    return DEFAULT_CONFIG


def adobe_view_presets():
    """Every actual display/view tuple in the installed, pinned Adobe configs."""
    presets = []
    for record in _adobe_records():
        config = _config(record['name'])
        for display in config.getDisplays():
            for view in config.getViews(display):
                presets.append({'config': record['name'], 'display': display, 'view': view,
                                'configLabel': record['label'], 'label': view})
    for preset in presets:
        same_view = [item for item in presets if item['view'] == preset['view']]
        if len(same_view) > 1:
            preset['label'] += ' · ' + preset['display']
            if sum(item['display'] == preset['display'] for item in same_view) > 1:
                preset['label'] += ' · ' + preset['configLabel']
    return presets


def describe(name='', *, source_colour=None):
    name = name or _source_configuration(source_colour)
    config = _config(name)
    displays = [{"name": display, "views": list(config.getViews(display)), 'defaultView': config.getDefaultView(display)} for display in config.getDisplays()]
    if not displays:
        raise ValueError("Display configuration has no displays")
    display = DEFAULT_DISPLAY if any(item["name"] == DEFAULT_DISPLAY for item in displays) else config.getDefaultDisplay()
    views = next(item["views"] for item in displays if item["name"] == display)
    view = config.getDefaultView(display) if name.startswith('adobe-ae://') else DEFAULT_VIEW if DEFAULT_VIEW in views else config.getDefaultView(display)
    if view not in views:
        raise ValueError("Display configuration has no default view")
    return {"config": name, "configs": configurations(), "displays": displays, "display": display, "view": view,
            "presets": view_presets(), 'adobePresets': adobe_view_presets()}


@lru_cache(maxsize=1)
def view_presets():
    """Actual built-in display/view tuples, without duplicate config versions."""
    versions = {}
    for entry in configurations():
        match = re.fullmatch(r'ocio://studio-config-v([\d.]+)_aces-v(1\.3|2\.0)_ocio-v[\d.]+',entry['name'])
        if match:
            rank = tuple(int(value) for value in match[1].split('.'))
            if match[2] not in versions or rank > versions[match[2]][0]:
                versions[match[2]] = (rank,entry['name'])
    names = [DEFAULT_CONFIG] + [versions[key][1] for key in ('2.0','1.3') if key in versions]
    result,seen = [],set()
    for name in names:
        config = _config(name)
        for display in config.getDisplays():
            for view in config.getViews(display):
                # Common identity/video views are shared between these configs.
                key = (display,view)
                if key in seen:continue
                seen.add(key)
                short = display.removesuffix(' - Display')
                label = short if view == DEFAULT_VIEW else f'{short} · {view}'
                result.append({'config':name,'display':display,'view':view,'label':label})
    result.sort(key=lambda item:(item['display'] != DEFAULT_DISPLAY,item['view'] != DEFAULT_VIEW,item['display'],item['view']))
    return result


def _source(config, colour, source_depth):
    encoding = colour.get("encoding")
    if encoding == "unknown" and source_depth == 8 and colour.get("management") != "ocio":
        encoding = "srgb8"
    if encoding == "unknown" and colour.get("management") == "ocio":
        encoding = _verified_ocio_source(colour)
    if encoding not in _SPACES:
        raise ValueError("This source colour space is not yet mapped for preview")
    for name in _SPACES[encoding]:
        space = config.getColorSpace(name)
        if space is not None:
            return space.getName()
    raise ValueError("This display configuration does not contain the source colour space")


def _verified_ocio_source(colour):
    """Resolve an SDK-hashed Adobe built-in config, never a name alone."""
    path_text, expected, working = colour.get('ocioConfigPath'), colour.get('ocioConfigFileSha256'), colour.get('ocioWorkingSpace')
    if not isinstance(path_text, str) or not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected) or not isinstance(working, str):
        raise ValueError('The AE OCIO configuration has not been verified')
    path = Path(path_text)
    if not path.is_absolute() or path.suffix.lower() != '.ocio' or path.is_symlink() or not path.is_file():
        raise ValueError('The AE OCIO configuration is unavailable')
    resolved = path.resolve(strict=True)
    roots = []
    for key in ('ProgramFiles', 'ProgramFiles(x86)'):
        value = os.environ.get(key)
        if value:
            root = Path(value) / 'Adobe' / 'Adobe After Effects 2026' / 'Support Files' / 'OpenColorIO-Configs'
            if root.is_dir(): roots.append(root.resolve(strict=True))
    try:
        inside = any(os.path.commonpath((os.path.normcase(str(resolved)), os.path.normcase(str(root)))) == os.path.normcase(str(root)) for root in roots)
    except ValueError:
        inside = False
    if not inside or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('The AE OCIO configuration is not a qualified Adobe built-in')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('The AE OCIO configuration changed')
    actual = _ocio().Config.CreateFromFile(str(resolved))
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('The AE OCIO configuration changed')
    spaces = [space for space in actual.getColorSpaces() if space.getName() == working]
    if not spaces and '/' in working:
        family, name = working.rsplit('/', 1)
        spaces = [space for space in actual.getColorSpaces() if space.getName() == name
                  and space.getFamily().strip('/') == family.strip('/')]
    if len(spaces) != 1:
        raise ValueError('The AE working space is not uniquely mapped')
    if spaces[0].isData():
        raise ValueError('An OCIO data space does not identify RGB colour')
    space = spaces[0].getName()
    if any(view.lower().replace(' ', '') == 'srgb' and actual.getDisplayViewColorSpaceName(display, view) == space
           for display in actual.getDisplays() for view in actual.getViews(display)):
        return 'srgb8'  # Display-referred source, used only by the viewer.
    for encoding, names in _SPACES.items():
        if encoding != 'srgb8' and any(actual.getColorSpace(name) is not None and actual.getColorSpace(name).getName() == space for name in names):
            return encoding
    raise ValueError('The AE working space is not mapped for display')


@lru_cache(maxsize=16)
def _processor(config_name, encoding, source_depth, display, view):
    config = _config(config_name)
    if display not in config.getDisplays() or view not in config.getViews(display):
        raise ValueError("Unknown display or view")
    source = _source(config, {"encoding": encoding}, source_depth)
    transform = _ocio().DisplayViewTransform(src=source, display=display, view=view)
    return config.getProcessor(transform).getDefaultCPUProcessor()


def render(payload, manifest, config_name=DEFAULT_CONFIG, display="", view="", max_side=960, *, profile=None):
    """Render one verified RGBA float frame to a bounded display-only PNG."""
    info = describe(config_name)
    display = display or info["display"]
    if display not in _config(info["config"]).getDisplays():
        raise ValueError("Unknown display")
    view = view or (info["view"] if display == info["display"] else _config(info["config"]).getDefaultView(display))
    if view not in _config(info['config']).getViews(display):
        raise ValueError('Unknown display view')
    width, height = manifest["width"], manifest["height"]
    dtype = "<f4" if manifest["sampleType"] == "float32" else "<u2"
    expected = width * height * 4 * np.dtype(dtype).itemsize
    if len(payload) != expected:
        raise ValueError("Preview frame size changed")
    image = np.frombuffer(payload, dtype=dtype).reshape(height, width, 4)
    # A source frame can be 256 MiB. Sample before materialising RGB so memory
    # scales with one source frame plus a bounded preview, not the whole shot.
    scale = max(1, int(np.ceil(max(width, height) / max_side)))
    sample = image[::scale, ::scale]
    rgb = np.array(sample[..., :3], dtype=np.float32, order="C")
    alpha = np.array(sample[..., 3], dtype=np.float32, order="C")
    if manifest["sampleType"] == "uint16_ae":
        rgb /= np.float32(32768)
        alpha /= np.float32(32768)
    if not np.isfinite(rgb).all() or not np.isfinite(alpha).all():
        raise ValueError("Preview source has non-finite samples")
    colour = manifest["colour"]
    if view == 'Raw':
        # The explicit None/Raw view displays the retained channel values. It
        # must bypass the ICC input transform too, not merely the output view.
        # Profile lineage remains checked even though no profile is applied.
        if colour.get('encoding') == 'ae_project_icc':
            if not isinstance(profile, bytes) or hashlib.sha256(profile).hexdigest() != colour.get('profileSha256'):
                raise ValueError('The captured display ICC profile is unavailable or changed')
        elif profile is not None:
            raise ValueError('Unexpected display ICC profile')
        processor = None
    elif colour.get('encoding') == 'ae_project_icc':
        from . import icc_display
        icc_display.validate_linear_profile(profile, colour)
        processor = icc_display.processor(profile, info['config'], display, view)
    else:
        if profile is not None:
            raise ValueError('Unexpected display ICC profile')
        encoding = _verified_ocio_source(colour) if colour.get('management') == 'ocio' else colour['encoding']
        processor = _processor(info["config"], encoding, manifest["sourceBitDepth"], display, view)
    if processor is not None:
        processor.applyRGB(rgb)
    if not np.isfinite(rgb).all():
        raise ValueError("Display transform returned non-finite values")
    # Clipping here is solely the 8-bit display surface, never the master.
    result = np.empty((*rgb.shape[:2], 4), dtype=np.uint8)
    result[..., :3] = np.rint(np.clip(rgb, 0, 1) * 255).astype(np.uint8)
    result[..., 3] = np.rint(np.clip(alpha, 0, 1) * 255).astype(np.uint8)
    output = BytesIO()
    Image.fromarray(result, "RGBA").save(output, format="PNG")
    return output.getvalue()
