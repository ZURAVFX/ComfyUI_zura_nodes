"""SDR-to-HDR reconstruction using LTX lighting and registered source detail.

The source is sRGB, the prediction is LTX ACEScct, and the final master is
unclipped FLOAT ACEScg. Native creative HDR graphs do not use this node.
"""
from functools import lru_cache
import json

import numpy as np

_LUMA = np.array((.2722287168, .6740817658, .0536895174), dtype=np.float32)
_FLOOR = np.float32(1e-6)


def _check_interrupted():
    # Standalone CPU colour tools can use this module without Comfy installed.
    # In Comfy, always propagate its normal processing-interrupted exception.
    try:
        from comfy.model_management import throw_exception_if_processing_interrupted
    except ModuleNotFoundError as exc:
        if exc.name not in ('comfy', 'comfy.model_management'):
            raise
        return
    throw_exception_if_processing_interrupted()


@lru_cache(maxsize=1)
def _source_processor():
    from ..comfylink.display_view import _config, _source, DEFAULT_CONFIG
    config = _config(DEFAULT_CONFIG)
    return config.getProcessor(_source(config, {'encoding': 'srgb8'}, 8),
                               _source(config, {'encoding': 'acescg'}, 32)).getDefaultCPUProcessor()


def filter_parameters(width, height):
    """Frozen 512-pixel proof settings scaled to the delivered raster."""
    scale = max(width, height) / 512.0
    return {'gaussianSigmaPixels': 16.0 * scale,
            'guidedRadiusPixels': max(1, round(32 * scale)),
            'guidedRegularizationStopsSquared': 1.0}


def decode_prediction(codes):
    """Inverse ACEScct once, preserving extended and signed linear samples."""
    codes = np.asarray(codes, dtype=np.float32)
    result = np.empty_like(codes)
    log = codes > .155251141552511
    result[log] = np.exp2(codes[log] * np.float32(17.52) - np.float32(9.72))
    result[~log] = (codes[~log] - np.float32(.0729055341958355)) / np.float32(10.5402377416545)
    if not np.isfinite(result).all():
        raise ValueError('LTX HDR prediction decodes to non-finite ACEScg samples.')
    return result


def reconstruct_acescg(source, prediction):
    """One HWC ACEScg frame; scalar exposure preserves source RGB and alpha.

    No resampling, colour clipping or sharpening. Intermediates are bounded to
    one frame. The returned gain is useful for verification, not a new control.
    """
    import cv2
    source = np.asarray(source, dtype=np.float32)
    prediction = np.asarray(prediction, dtype=np.float32)
    if (source.ndim != 3 or source.shape[-1] not in (3, 4) or not source.size or
            prediction.shape != (*source.shape[:2], 3) or
            not np.isfinite(source).all() or not np.isfinite(prediction).all()):
        raise ValueError('HDR reconstruction requires matching finite HWC source and prediction frames.')
    height, width = source.shape[:2]
    params = filter_parameters(width, height)
    sigma = params['gaussianSigmaPixels']; radius = params['guidedRadiusPixels']
    def blur(value):
        return cv2.GaussianBlur(value, (0, 0), sigma, borderType=cv2.BORDER_REFLECT_101)
    def mean(value):
        return cv2.boxFilter(value, -1, (2 * radius + 1, 2 * radius + 1), borderType=cv2.BORDER_REFLECT_101)
    source_y = source[..., :3] @ _LUMA
    prediction_y = prediction @ _LUMA
    guide = np.log2(np.maximum(source_y, _FLOOR))
    target = np.log2(np.maximum(blur(prediction_y), _FLOOR) / np.maximum(blur(source_y), _FLOOR))
    mi, mp = mean(guide), mean(target)
    variance = np.maximum(mean(guide * guide) - mi * mi, 0)
    a = (mean(guide * target) - mi * mp) / (variance + np.float32(1.0))
    b = mp - a * mi
    gain = np.exp2(mean(a) * guide + mean(b)).astype(np.float32, copy=False)
    result = source.copy()
    result[..., :3] *= gain[..., None]
    if not np.isfinite(result).all() or not np.isfinite(gain).all() or np.any(gain <= 0):
        raise ValueError('The inferred HDR exposure is outside finite float32 range.')
    return result, gain


class ZuraHDRSourceDetail:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'source': ('IMAGE',), 'prediction': ('IMAGE',)}}
    RETURN_TYPES = ('IMAGE', 'IMAGE', 'STRING')
    RETURN_NAMES = ('final_acescg', 'raw_ltx_acescct', 'reconstruction_info')
    FUNCTION = 'reconstruct'
    CATEGORY = 'Zura/Artist Studio'
    DESCRIPTION = 'SDR-to-HDR only. Retains source detail and colour with smooth LTX-inferred lighting. Unclipped FLOAT ACEScg output; raw LTX prediction remains available unchanged.'

    def reconstruct(self, source, prediction):
        import torch
        if (not isinstance(source, torch.Tensor) or not isinstance(prediction, torch.Tensor) or
                source.ndim != 4 or prediction.ndim != 4 or source.shape[-1] not in (3, 4) or
                prediction.shape[-1] != 3 or tuple(source.shape[:3]) != tuple(prediction.shape[:3]) or
                not source.is_floating_point() or not prediction.is_floating_point()):
            raise ValueError('HDR reconstruction needs matching NHWC SDR source and ACEScct prediction frames.')
        # Both inputs must already describe the same exact delivered interval.
        # Static graph adapters explicitly remove their known guide padding;
        # the node must never silently accept a larger/crossed source range.
        count, height, width, _ = prediction.shape
        if not 1 <= count <= 121 or min(width, height) < 1 or max(width, height) > 4096 or count * width * height > 40_000_000:
            raise ValueError('HDR reconstruction exceeds the bounded source frame budget.')
        # Allocate only the required final batch. Never materialise source and
        # prediction as additional float32 CPU batches at 4K/long clip sizes.
        output = torch.empty((count, height, width, source.shape[-1]), dtype=torch.float32, device='cpu')
        gain_min, gain_max = float('inf'), 0.0
        for index in range(count):
            _check_interrupted()
            src = source[index].detach().to(device='cpu', dtype=torch.float32).numpy()
            pred = prediction[index].detach().to(device='cpu', dtype=torch.float32).numpy()
            if not np.isfinite(src).all() or np.any(src[..., :3] < 0) or np.any(src[..., :3] > 1):
                raise ValueError('SDR source must contain finite normalised sRGB pixels.')
            linear = np.array(src[..., :3], dtype=np.float32, order='C', copy=True)
            _source_processor().applyRGB(linear)
            if source.shape[-1] == 4:
                linear = np.dstack((linear, src[..., 3]))
            final, gain = reconstruct_acescg(linear, decode_prediction(pred))
            output[index].numpy()[:] = final
            gain_min = min(gain_min, float(gain.min())); gain_max = max(gain_max, float(gain.max()))
        _check_interrupted()
        info = {'version': 1, 'method': 'ltx_luminance_source_detail', 'mode': 'sdr',
                'sourceColour': 'srgb8', 'predictionColour': 'acescct',
                'colour': {'encoding': 'acescg', 'sceneLinear': True}, 'sampleType': 'float32',
                'width': width, 'height': height, 'frames': count,
                'parameters': filter_parameters(width, height), 'luminanceFloor': float(_FLOOR),
                'gainMin': gain_min, 'gainMax': gain_max, 'rawPredictionPreserved': True,
                'temporalQuality': 'pending validation'}
        return output, prediction, json.dumps(info, separators=(',', ':'))


NODE_CLASS_MAPPINGS = {'ZuraHDRSourceDetail': ZuraHDRSourceDetail}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraHDRSourceDetail': 'Zura · Preserve SDR Detail in HDR'}
