"""Small crop and source-audio adapters for the subtitle-removal workflow.

Sampling, IC-LoRA conditioning, decoding and upscaling remain native LTX nodes.
"""

import math
import subprocess

import numpy as np
import torch
import torch.nn.functional as F

from .media_tools import find_media_tool


def ensure_subtitle_memory(needed_bytes):
    """Leave room for the application and weights before allocating crop batches."""
    try:
        import psutil
        memory = psutil.virtual_memory()
        available, total = int(memory.available), int(memory.total)
        if total <= 0 or not 0 <= available <= total:
            raise ValueError('invalid memory information')
    except Exception as error:
        if needed_bytes > 512 * 1024**2:
            raise ValueError('Could not check free system memory for this large subtitle crop. Reduce the crop, scale or clip length and try again.') from error
        return
    system_reserve = max(1024**3, min(8 * 1024**3, int(total * .12)))
    # Cached models can reduce available RAM even for a tiny crop. Keep a
    # sensible fraction of what remains without blocking every small edit.
    reserve = min(system_reserve, max(512 * 1024**2, int(available * .2)))
    if needed_bytes + reserve > available:
        raise ValueError(f'This subtitle crop needs about {needed_bytes/1024**3:.1f} GB of free system memory for frame preparation. Reduce the crop, processing scale or clip length and try again.')


class ZuraSubtitlePrepareCrop:
    """Pad the chosen full-resolution crop to the two-stage 128 px grid."""

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'plate': ('ZURA_PLATE',)}}

    RETURN_TYPES = ('ZURA_PLATE', 'IMAGE', 'INT', 'INT')
    RETURN_NAMES = ('plate', 'low_guide', 'low_width', 'low_height')
    FUNCTION = 'prepare'
    CATEGORY = 'Zura/Paintout'

    def prepare(self, plate):
        image = plate['_work_images']
        mask = plate['_work_mask']
        if image.ndim != 4 or mask.ndim != 3 or image.shape[:3] != mask.shape:
            raise ValueError('Could not prepare the subtitle crop and its selection.')
        height, width = image.shape[1:3]
        padded_h, padded_w = math.ceil(height / 128) * 128, math.ceil(width / 128) * 128
        if max(padded_h, padded_w) > 4096:
            raise ValueError('The crop is larger than 4096 px. Choose a smaller processing scale.')
        # The original source batch remains cached while the padded full and
        # half-size guide batches are created. Check only new allocations here.
        new_full = len(image) * padded_h * padded_w * 4 * 4 if (padded_h,padded_w)!=(height,width) else 0
        low_guide = len(image) * (padded_h//2) * (padded_w//2) * 3 * 4
        ensure_subtitle_memory(new_full + low_guide * 2)
        if (padded_h, padded_w) != (height, width):
            image = F.pad(image.permute(0, 3, 1, 2), (0, padded_w-width, 0, padded_h-height), mode='replicate').permute(0, 2, 3, 1)
            mask = F.pad(mask.unsqueeze(1), (0, padded_w-width, 0, padded_h-height), mode='replicate').squeeze(1)
        low = F.interpolate(image.permute(0, 3, 1, 2), size=(padded_h//2, padded_w//2), mode='area').permute(0, 2, 3, 1)
        prepared = dict(plate, padded=[padded_h, padded_w], _work_images=image, _work_mask=mask,
                        subtitle_full_crop=True, subtitle_feather=16)
        return prepared, low, padded_w//2, padded_h//2


class ZuraSubtitleSourceAudio:
    """Load the selected source audio or equivalent silence for an audio-free plate."""

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'plate': ('ZURA_PLATE',)}}

    RETURN_TYPES = ('AUDIO',)
    FUNCTION = 'load'
    CATEGORY = 'Zura/Paintout'

    def load(self, plate):
        fps = float(plate['fps'])
        frame_count = len(plate['_work_images'])
        if not math.isfinite(fps) or fps <= 0 or frame_count < 1:
            raise ValueError('The source audio timing is invalid.')
        samples = round(frame_count / fps * 48000)
        source = plate.get('source', {})
        if source.get('kind') != 'video':
            return ({'waveform': torch.zeros((1, 2, samples)), 'sample_rate': 48000},)
        source_path = source['path']
        probe = subprocess.run([find_media_tool('ffprobe'), '-v', 'error', '-select_streams', 'a:0',
                                '-show_entries', 'stream=index', '-of', 'csv=p=0', source_path],
                               check=True, capture_output=True, text=True)
        if not probe.stdout.strip():
            return ({'waveform': torch.zeros((1, 2, samples)), 'sample_rate': 48000},)
        result = subprocess.run([find_media_tool('ffmpeg'), '-v', 'error', '-ss', str(plate['start']/fps),
                                 '-i', source_path, '-t', str(plate['count']/fps), '-map', '0:a:0', '-vn',
                                 '-ac', '2', '-ar', '48000', '-f', 'f32le', 'pipe:1'],
                                check=True, capture_output=True)
        raw = np.frombuffer(result.stdout, dtype='<f4')
        if raw.size % 2:
            raise ValueError('The source audio has an incomplete sample.')
        waveform = torch.from_numpy(raw.reshape(-1, 2).T.copy()).unsqueeze(0)
        waveform = F.pad(waveform[..., :samples], (0, max(0, samples-waveform.shape[-1])))
        return ({'waveform': waveform, 'sample_rate': 48000},)


NODE_CLASS_MAPPINGS = {'ZuraSubtitlePrepareCrop': ZuraSubtitlePrepareCrop,
                       'ZuraSubtitleSourceAudio': ZuraSubtitleSourceAudio}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraSubtitlePrepareCrop': 'Zura · Prepare Subtitle Crop',
                              'ZuraSubtitleSourceAudio': 'Zura · Load Source Audio for Subtitle Repair'}
