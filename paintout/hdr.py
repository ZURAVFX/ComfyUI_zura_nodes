"""HDR conversion adapters. Inference stays in the official native LTX graph."""
from pathlib import Path
from fractions import Fraction
import gc
import json
import math
import torch
from .paintout import (describe, frames, from_linear, native_colour, decode_ct,
                       resize, save_exr, frame_progress, is_hdr, selected_space, COLOUR_SPACES, CATEGORY)

MAX_HDR_FRAMES = 121
MAX_HDR_PIXEL_FRAMES = 40_000_000
MAX_HDR_GUIDE_BYTES = 8 * 1024**3
HDR_SAMPLING_MODES = ['whole_clip', 'tiled_fusion']
DEFAULT_HDR_MODEL = 'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors'


def checked_model_name(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError('Choose the HDR diffusion model before continuing.')
    return value.strip()


def conversion_shape(width, height, count, sampling_mode='whole_clip'):
    if any(type(v) is not int or v < 1 for v in (width, height, count)):
        raise ValueError('HDR conversion needs positive whole dimensions and frame count.')
    pw, ph = math.ceil(width/64)*64, math.ceil(height/64)*64
    length = max(9, math.ceil((count-1)/8)*8+1)
    if sampling_mode not in HDR_SAMPLING_MODES:
        raise ValueError('Choose whole-clip or tiled-fusion HDR sampling.')
    if sampling_mode == 'tiled_fusion':
        if count > MAX_HDR_FRAMES or max(pw, ph) > 4096:
            raise ValueError('Tiled HDR currently supports up to 121 source frames and 4096 pixels per side.')
        conversion_window(pw, ph)
        if pw*ph*length*3*4 > MAX_HDR_GUIDE_BYTES:
            raise ValueError('The full-resolution CPU HDR guide exceeds its 8 GiB allocation limit. Trim a shorter shot.')
    elif count > MAX_HDR_FRAMES or max(pw, ph) > 4096 or pw*ph*length > MAX_HDR_PIXEL_FRAMES:
        raise ValueError('SDR to HDR conversion is limited to 121 frames and 40 million padded pixel-frames. Trim a shorter shot; no smaller proxy is substituted.')
    return pw, ph, length


def conversion_window(width, height):
    """Bound the untiled full-resolution guide encode, not just denoise tiles."""
    available = MAX_HDR_PIXEL_FRAMES // (width*height)
    if available < 9:
        raise ValueError('Even a 9-frame untiled HDR guide exceeds 40 million pixel-frames at this raster. Use a smaller plate; spatial denoise tiling cannot fix guide-encode memory.')
    largest = min(33, 1+8*((available-1)//8))
    return min(17, largest)


def release_model_memory():
    """Release loaded weights at the queued boundary; execution caches may remain."""
    from comfy import model_management
    model_management.unload_all_models()
    gc.collect()
    model_management.soft_empty_cache()


def checkpoint_plate(saved_sequence):
    from .browser import checked_path
    directory = checked_path(saved_sequence)
    if not directory.is_dir():
        raise ValueError('Choose the completed SDR repair output folder containing paintout.json and EXR frames.')
    manifest = directory/'paintout.json'
    if not manifest.is_file() or manifest.stat().st_size > 16*1024**2:
        raise ValueError('The SDR repair checkpoint is missing or its metadata is too large.')
    try:
        metadata = json.loads(manifest.read_text(encoding='utf-8'))
        plate = metadata['plate']
        if not isinstance(plate, dict):raise ValueError()
        count, start = plate['count'], plate['start']
        original = plate['source']
        width, height = original['width'], original['height']
        rate = Fraction(str(plate['fps_rational']))
        fps = float(plate['fps'])
        if (type(count) is not int or not 1 <= count <= MAX_HDR_FRAMES or type(start) is not int or start < 0 or
            any(type(n) is not int or not 1 <= n <= 4096 for n in (width, height)) or
            isinstance(plate['fps'], bool) or not math.isfinite(fps) or not 1 <= rate <= 120 or
            not math.isclose(fps, float(rate), rel_tol=1e-8, abs_tol=1e-8)):
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError, OverflowError) as error:
        raise ValueError('The SDR repair checkpoint has invalid frame, raster or frame-rate metadata.') from error
    if plate.get('processing') != 'SDR (sRGB)' or plate.get('space') not in COLOUR_SPACES or plate['space'] == 'auto' or is_hdr(plate['space']):
        raise ValueError('Resume HDR from an SDR repair checkpoint, before the HDR conversion stage.')
    sequence = describe(str(directory))
    expected = [f'frame_{start+i:06d}.exr' for i in range(count)]
    if (sequence['kind'] != 'sequence' or sequence['count'] != count or
        (sequence['width'], sequence['height']) != (width, height) or
        [Path(file).name for file in sequence['files']] != expected or selected_space(sequence, 'auto') != 'acescg'):
        raise ValueError('The SDR checkpoint must contain every original-size ACEScg EXR frame, in its original numbering.')
    # A sequence checkpoint is self-contained. Video delivery still needs the
    # original video for its soundtrack and selected source interval.
    if original.get('kind') == 'video':
        try:
            path = checked_path(original['path'])
            current = describe(str(path))
            source_rate = Fraction(str(current.get('fps_rational', current['fps'])))
            if (current['kind'] != 'video' or (current['width'], current['height']) != (width, height) or
                current['count'] < start+count or source_rate != rate):
                raise ValueError()
        except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError) as error:
            raise ValueError('The original video is missing or its raster, range or frame rate changed. Restore it to preserve the source audio.') from error
        plate = dict(plate, source=current)
    elif original.get('kind') != 'sequence':
        raise ValueError('The SDR checkpoint has an unsupported original source type.')
    return str(directory), plate


class ZuraPaintoutHDRResume:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'saved_sequence': ('STRING', {'default': ''})},
                'optional': {'model_name': ('STRING', {'default': DEFAULT_HDR_MODEL})}}
    RETURN_TYPES = ('STRING', 'ZURA_PLATE', 'COMBO')
    RETURN_NAMES = ('saved_sequence', 'plate', 'model_name')
    FUNCTION = 'resume'
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float('nan')

    def resume(self, saved_sequence, model_name=DEFAULT_HDR_MODEL):
        model_name = checked_model_name(model_name)
        path, plate = checkpoint_plate(saved_sequence)
        release_model_memory()
        row = dict(saved_sequence=path, width=plate['source']['width'], height=plate['source']['height'],
                   frames=plate['count'], fps=plate['fps'], fps_rational=plate['fps_rational'])
        # Feed this string into native UNETLoader.unet_name to gate expensive
        # model loading on checkpoint validation and boundary release.
        return {'ui': {'zura_hdr_checkpoint': [row]}, 'result': (path, plate, model_name)}


class ZuraPaintoutColourCheck:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'source': ('STRING', {'default': ''}),
                'colour_space': (COLOUR_SPACES,),
                'pipeline': (['sdr_sdr', 'sdr_hdr', 'hdr_hdr'],),
                'frame_count': ('INT', {'default': 81, 'min': 1, 'max': 993})},
                'optional': {'sampling_mode': (HDR_SAMPLING_MODES,)}}
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('validated_source',)
    FUNCTION = 'check'
    CATEGORY = CATEGORY

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float('nan')

    def check(self, source, colour_space, pipeline, frame_count, sampling_mode='whole_clip'):
        from .browser import checked_path
        path = checked_path(source)
        description = describe(str(path))
        if colour_space not in COLOUR_SPACES or pipeline not in ('sdr_sdr', 'sdr_hdr', 'hdr_hdr'):
            raise ValueError('Choose a supported source colour space and colour pipeline.')
        space = selected_space(description, colour_space)
        if is_hdr(space) and pipeline != 'hdr_hdr':
            raise ValueError('This is HDR footage. Choose HDR to HDR to preserve its highlights.')
        if not is_hdr(space) and pipeline == 'hdr_hdr':
            raise ValueError('HDR to HDR needs HLG, PQ or a scene-linear/ACES source. Choose SDR to HDR for SDR footage.')
        if type(frame_count) is not int or not 1 <= frame_count <= 993:
            raise ValueError('Choose between 1 and 993 source frames.')
        if pipeline == 'sdr_hdr':
            conversion_shape(description['width'], description['height'], frame_count, sampling_mode)
        return (str(path),)


class ZuraPaintoutHDRPrepare:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'saved_sequence': ('STRING',), 'plate': ('ZURA_PLATE',)},
                'optional': {'sampling_mode': (HDR_SAMPLING_MODES,), 'release_models': ('BOOLEAN', {'default': False}),
                             'model_name': ('STRING', {'default': DEFAULT_HDR_MODEL})}}
    RETURN_TYPES = ('IMAGE', 'ZURA_HDR_TAKE', 'INT', 'INT', 'INT', 'FLOAT', 'INT', 'COMBO')
    RETURN_NAMES = ('acescct_guide', 'take', 'width', 'height', 'frames', 'fps', 'tile_frames', 'model_name')
    FUNCTION = 'prepare'
    CATEGORY = CATEGORY

    def prepare(self, saved_sequence, plate, sampling_mode='whole_clip', release_models=False, model_name=DEFAULT_HDR_MODEL):
        model_name = checked_model_name(model_name)
        if plate.get('processing') != 'SDR (sRGB)' or is_hdr(plate.get('space')):
            raise ValueError('SDR to HDR conversion expects an SDR paintout result.')
        source = describe(saved_sequence)
        count = plate['count']
        if source['count'] != count or (source['width'], source['height']) != (plate['source']['width'], plate['source']['height']):
            raise ValueError('The repaired sequence does not match the original plate raster and frame count.')
        pw, ph, length = conversion_shape(source['width'], source['height'], count, sampling_mode)
        window = conversion_window(pw, ph) if sampling_mode == 'tiled_fusion' else 0
        if release_models:release_model_memory()
        # Keep only one full CPU guide and per-frame transform temporaries.
        # A list + cat + whole-clip colour transform can multiply host memory.
        guide = torch.empty((length, ph, pw, 3), dtype=torch.float32, device='cpu')
        read = 0
        progress = frame_progress(count)
        for index, a in enumerate(frames(source, 0, count)):
            if tuple(a.shape) != (source['height'], source['width'], 3):
                raise ValueError('The repaired SDR sequence changes raster or RGB channels mid-shot.')
            srgb = from_linear(torch.from_numpy(a).float(), 'srgb_display')
            if not torch.isfinite(srgb).all() or srgb.min() < -.002 or srgb.max() > 1.002:
                raise ValueError('SDR conversion input contains invalid or extended-range pixels. Choose HDR to HDR for an HDR source.')
            image = resize(srgb.clamp(0, 1)[None], ph, pw)
            guide[index].copy_(native_colour(image, 'sRGB', 'HDR ACEScct')[0])
            read += 1
            progress(read)
        if read != count:raise ValueError('The repaired SDR sequence ended before its saved frame count.')
        if length > count:
            guide[count:].copy_(guide[count-1:count].expand(length-count, -1, -1, -1))
        # Official 2.5 SDR-to-HDR conditioning uses ACEScct, never JPEG/CRF.
        take = dict(plate=plate, width=source['width'], height=source['height'], count=count,
                    padded=[ph, pw], padded_count=length, sampling_mode=sampling_mode, tile_frames=window)
        # The official conversion schedule conditions high-rate sources at 60;
        # delivery retains the original rational clock in the untouched take.
        conditioning_fps = 60.0 if float(plate['fps']) > 30 else float(plate['fps'])
        return guide, take, pw, ph, length, conditioning_fps, window, model_name


class ZuraPaintoutHDRSave:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',), 'take': ('ZURA_HDR_TAKE',),
                'output_name': ('STRING', {'default': 'paintout/hdr'}),
                'precision': (['float32', 'float16'],),
                'export_format': (['HLG video', 'EXR sequence', 'EXR + HLG video'],)}}
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('saved_sequence',)
    OUTPUT_NODE = True
    FUNCTION = 'save'
    CATEGORY = CATEGORY

    def save(self, images, take, output_name, precision, export_format):
        import folder_paths
        from .media import Delivery
        if images.ndim != 4 or images.shape[-1] != 3 or len(images) < take['count'] or tuple(images.shape[1:3]) != tuple(take['padded']):
            raise ValueError('HDR decode does not match the internal frame/raster padding.')
        if precision not in ('float32', 'float16') or export_format not in ('HLG video', 'EXR sequence', 'EXR + HLG video'):
            raise ValueError('Choose a supported HDR export format and EXR precision.')
        if not torch.isfinite(images).all():
            raise ValueError('HDR decode contains invalid pixels. No master was exported.')
        base = Path(folder_paths.get_output_directory()).resolve()
        relative = Path(output_name)
        if relative.is_absolute() or '..' in relative.parts or not str(relative).strip():
            raise ValueError('Use an output folder inside ComfyUI output.')
        root = base/relative
        root.parent.mkdir(parents=True, exist_ok=True)
        for index in range(1, 100000):
            target = root.parent/f'{root.name}_hdr_{index:04d}'
            try: target.mkdir(); break
            except FileExistsError: continue
        else: raise ValueError('No free HDR output directory.')
        plate = dict(take['plate'], space='acescg', processing='HDR (ACEScct)')
        delivery = Delivery(target, plate, export_format, True)
        progress = frame_progress(take['count'])
        for index in range(take['count']):
            linear = resize(decode_ct(images[index:index+1].detach().float().cpu()), take['height'], take['width'])[0]
            if not torch.isfinite(linear).all():
                raise ValueError('HDR decode exceeds finite scene-linear range. No usable master was exported.')
            if precision == 'float16' and export_format != 'HLG video' and linear.abs().max() > 65504:
                raise ValueError('HDR pixels exceed half-float EXR range. Choose float32 precision.')
            if export_format != 'HLG video':
                save_exr(target/f"frame_{plate['start']+index:06d}.exr", linear.numpy(), 'acescg', precision=='float16')
            delivery.append(linear)
            progress(index+1)
        (target/'paintout.json').write_text(json.dumps(dict(pipeline='sdr_hdr', plate={k:v for k,v in plate.items() if not k.startswith('_')},
            notes='Official LTX SDR-to-HDR conversion after SDR repair. Full-frame generative conversion can change unmasked pixels. Original raster, frame count, rate and source audio restored.'), indent=2), encoding='utf-8')
        return {'ui': {'text': [f"Saved {take['count']} HDR frames: {target}"], **delivery.finish()}, 'result': (str(target),)}


NODE_CLASS_MAPPINGS = {c.__name__: c for c in (ZuraPaintoutColourCheck, ZuraPaintoutHDRResume, ZuraPaintoutHDRPrepare, ZuraPaintoutHDRSave)}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraPaintoutColourCheck': 'Check SDR / HDR Colour Pipeline', 'ZuraPaintoutHDRResume': 'Resume HDR from Saved SDR Repair', 'ZuraPaintoutHDRPrepare': 'Prepare Repaired SDR for HDR', 'ZuraPaintoutHDRSave': 'Save HDR at Original Plate Size / Rate'}
