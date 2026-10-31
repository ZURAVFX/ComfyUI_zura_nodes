"""Source-frame geometry for the official LTX 2.5 outpaint workflow.

The generated mask is white where the model should create pixels. Keep the
mask alongside the frames: LTXVInpaintPreprocess uses it *before* sampling,
and LTXVLaplacianPyramidBlend uses it again for final delivery.
"""
from __future__ import annotations

import math
import torch
import torch.nn.functional as F


def prepare_canvas(images, mode, width, height, left=0, top=0, right=0,
                   bottom=0, black_threshold=2 / 255):
    """Return expanded RGB frames and a frame-aligned white-to-generate mask.

    ``expand`` fits the whole source into an artist-defined rectangle, keeping
    its aspect ratio, without cropping or stretching. ``black`` accepts an
    already-padded video and explicitly selects all pixels at or below the
    threshold, including real dark content; the caller must display a mask
    preview for review before rendering.
    """
    if not isinstance(images, torch.Tensor) or images.ndim != 4 or images.shape[-1] != 3 or images.shape[0] < 1:
        raise ValueError('Expected one or more RGB video frames.')
    if not images.is_floating_point() or not bool(torch.isfinite(images).all()):
        raise ValueError('Video frames must contain finite floating-point RGB pixels.')
    if type(width) is not int or type(height) is not int or not (64 <= width <= 4096 and 64 <= height <= 4096) or width % 64 or height % 64:
        raise ValueError('Output width and height must be multiples of 64 between 64 and 4096.')
    if mode not in ('expand', 'black'):
        raise ValueError('Choose canvas expansion or an already black-padded video.')
    if mode == 'black':
        source_height, source_width = images.shape[1:3]
        if not (0 <= width - source_width < 64 and 0 <= height - source_height < 64):
            raise ValueError('Black-padded footage must match the output size, allowing only model-grid padding.')
        threshold = float(black_threshold)
        if not math.isfinite(threshold) or not 0 <= threshold <= 0.1:
            raise ValueError('Black threshold must be between 0 and 0.1.')
        mask = (images.amax(dim=-1) <= threshold).to(dtype=images.dtype)
        if not bool(mask.any()):
            raise ValueError('No black pixels were found at this threshold.')
        if bool(mask.all()):
            raise ValueError('The black-pixel selection covers the entire video.')
        # Add only internal right/bottom grid padding. This is generated and
        # cropped off after sampling, never stretched into the source image.
        if width != source_width or height != source_height:
            images = F.pad(images.permute(0, 3, 1, 2), (0, width-source_width, 0, height-source_height)).permute(0, 2, 3, 1)
            mask = F.pad(mask, (0, width-source_width, 0, height-source_height), value=1)
        return images, mask

    edges = (left, top, right, bottom)
    if any(type(value) is not int or value < 0 for value in edges):
        raise ValueError('Canvas margins must be non-negative whole pixels.')
    box_width, box_height = width - left - right, height - top - bottom
    if box_width < 1 or box_height < 1:
        raise ValueError('Canvas margins leave no room for the source.')
    source_height, source_width = images.shape[1:3]
    scale = min(box_width / source_width, box_height / source_height)
    fitted_width = min(box_width, max(1, round(source_width * scale)))
    fitted_height = min(box_height, max(1, round(source_height * scale)))
    x = left + (box_width - fitted_width) // 2
    y = top + (box_height - fitted_height) // 2
    if fitted_width == source_width and fitted_height == source_height:
        resized = images
    else:
        resized = F.interpolate(images.permute(0, 3, 1, 2), size=(fitted_height, fitted_width),
                                mode='bilinear', align_corners=False, antialias=True).permute(0, 2, 3, 1)
    canvas = images.new_zeros((len(images), height, width, 3))
    canvas[:, y:y + fitted_height, x:x + fitted_width] = resized
    mask = images.new_ones((len(images), height, width))
    mask[:, y:y + fitted_height, x:x + fitted_width] = 0
    if not bool(mask.any()):
        raise ValueError('Expand the canvas to select an area to generate.')
    return canvas, mask


def prepare_hdr_canvas(acescct_images, mode, width, height, left=0, top=0,
                       right=0, bottom=0, black_threshold=2 / 255):
    """Experimental HDR canvas; the threshold is applied in linear ACEScg.

    In ACEScct, scene black is approximately 0.073 rather than zero. Decode
    before detecting black or resampling; padding must be encoded scene black
    before it is sent as an LTX HDR guide. This helper does not qualify the
    outpainting model or delivery path for HDR.
    """
    from ..paintout.paintout import decode_ct, encode_ct
    if not isinstance(acescct_images, torch.Tensor) or not acescct_images.is_floating_point() or not bool(torch.isfinite(acescct_images).all()):
        raise ValueError('Expected finite floating-point ACEScct frames.')
    linear = decode_ct(acescct_images)
    canvas, mask = prepare_canvas(linear, mode, width, height, left, top, right, bottom, black_threshold)
    return encode_ct(canvas), mask


class ZuraLTXOutpaintCanvas:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'images': ('IMAGE',),
                'mode': (['expand', 'black'],),
                'width': ('INT', {'default': 1152, 'min': 64, 'max': 4096, 'step': 64}),
                'height': ('INT', {'default': 640, 'min': 64, 'max': 4096, 'step': 64}),
                'left': ('INT', {'default': 0, 'min': 0, 'max': 4096}),
                'top': ('INT', {'default': 0, 'min': 0, 'max': 4096}),
                'right': ('INT', {'default': 0, 'min': 0, 'max': 4096}),
                'bottom': ('INT', {'default': 0, 'min': 0, 'max': 4096}),
                'black_threshold': ('FLOAT', {'default': 2 / 255, 'min': 0., 'max': .1, 'step': .001})}}

    RETURN_TYPES = ('IMAGE', 'MASK')
    RETURN_NAMES = ('outpaint_reference', 'generate_mask')
    FUNCTION = 'prepare'
    CATEGORY = 'Zura/Artist Studio'

    def prepare(self, images, mode, width, height, left=0, top=0, right=0,
                bottom=0, black_threshold=2 / 255):
        return prepare_canvas(images, mode, width, height, left, top, right,
                              bottom, black_threshold)


class ZuraLTXOutpaintHDRCanvas(ZuraLTXOutpaintCanvas):
    """Experimental ACEScct guide; not an HDR model or delivery guarantee."""
    def prepare(self, images, mode, width, height, left=0, top=0, right=0,
                bottom=0, black_threshold=2 / 255):
        return prepare_hdr_canvas(images, mode, width, height, left, top, right,
                                  bottom, black_threshold)


def match_hdr_outpaint_colour(generated, source, mask, feather=16, strength=1.0):
    """Match low-frequency colour near the plate, leaving distant pixels alone.

    Inputs are ACEScct. Only the difference sampled on the source side of the
    seam is propagated; black padding is never used as a colour reference.
    Correction is bounded in log exposure and tapers outside the plate.
    """
    import numpy as np
    from scipy.ndimage import distance_transform_edt, gaussian_filter
    if not strength or not feather:
        return generated
    frames = generated.detach().float().cpu().numpy()
    original = source.detach().float().cpu().numpy()
    masks = mask.detach().float().cpu().numpy()
    corrections = np.zeros_like(frames)
    fades = np.zeros(frames.shape[:3], dtype=np.float32)
    radius = max(8, feather * 5)
    sigma = max(2, feather / 2)
    for i, (image, plate, area) in enumerate(zip(frames, original, masks)):
        keep = area < .5
        if not keep.any() or keep.all():
            continue
        inside = distance_transform_edt(keep)
        ring = keep & (inside <= max(2, feather * 2))
        weights = gaussian_filter(ring.astype(np.float32), sigma=sigma)
        difference = np.clip(plate - image, -.15, .15)
        offset = np.stack([
            gaussian_filter(difference[..., channel] * ring, sigma=sigma)
            / np.maximum(weights, 1e-6) for channel in range(3)
        ], axis=-1)
        _, nearest = distance_transform_edt(~ring, return_indices=True)
        field = offset[nearest[0], nearest[1]]
        outside = distance_transform_edt(~keep)
        fade = np.maximum(0, 1 - outside / radius) ** 2
        corrections[i] = field
        fades[i] = fade
    # A three-frame symmetric filter suppresses flickering colour estimates.
    # It doesn't interpolate generated geometry or alter the source plate.
    if len(corrections) > 1:
        previous = corrections[0].copy()
        for i in range(len(corrections)):
            current = corrections[i].copy()
            following = corrections[min(i + 1, len(corrections) - 1)]
            corrections[i] = (previous + 2 * current + following) / 4
            previous = current
    corrections *= fades[..., None]
    correction = torch.from_numpy(corrections).to(device=generated.device, dtype=generated.dtype)
    return generated + correction * strength


def composite_hdr_outpaint(generated, source, mask, feather=16, colour_match=0.0):
    """Preserve the source away from the seam, blending in linear ACEScg."""
    from ..paintout.paintout import decode_ct, encode_ct
    if not isinstance(generated, torch.Tensor) or not isinstance(source, torch.Tensor) or not isinstance(mask, torch.Tensor):
        raise ValueError('Expected generated frames, HDR source frames and a mask.')
    if generated.ndim != 4 or generated.shape[-1] != 3 or generated.shape != source.shape or mask.shape != generated.shape[:3]:
        raise ValueError('HDR source, generated frames and mask must have matching dimensions.')
    if not all(x.is_floating_point() and bool(torch.isfinite(x).all()) for x in (generated, source, mask)):
        raise ValueError('HDR frames and mask must be finite floating-point values.')
    if type(feather) is not int or not 0 <= feather <= 128:
        raise ValueError('Feather must be between 0 and 128 pixels.')
    if isinstance(colour_match, bool) or not isinstance(colour_match, (int, float)) or not math.isfinite(colour_match) or not 0 <= colour_match <= 1:
        raise ValueError('Colour matching must be between zero and one.')
    alpha = mask.to(device=generated.device, dtype=generated.dtype).clamp(0, 1).unsqueeze(1)
    generated_area = alpha
    source = source.to(device=generated.device, dtype=generated.dtype)
    if colour_match:
        generated = match_hdr_outpaint_colour(generated, source, mask, feather, colour_match)
    if feather:
        window = 2 * feather + 1
        alpha = F.avg_pool2d(alpha, (1, window), stride=1, padding=(0, feather), count_include_pad=False)
        alpha = F.avg_pool2d(alpha, (window, 1), stride=1, padding=(feather, 0), count_include_pad=False)
        # The source canvas is black outside the plate. Blend only inside it,
        # but bring alpha to one at the inner edge. A plain blurred mask reaches
        # roughly 0.5 there and jumps to one outside, creating a visible seam.
        alpha = (alpha * (window / feather)).clamp(max=1)
        alpha = torch.maximum(alpha, generated_area)
    alpha = alpha.permute(0, 2, 3, 1)
    mixed = encode_ct(decode_ct(source) * (1 - alpha) + decode_ct(generated) * alpha)
    # Avoid even a colour-transform round trip in untouched pixels.
    composited = torch.where(alpha <= 0, source, torch.where(alpha >= 1, generated, mixed))
    if colour_match and feather:
        from .hdr_boundary import refine_hdr_boundary
        composited = refine_hdr_boundary(composited, source, mask, feather, colour_match, inplace=True)
    return composited


class ZuraHDRCompositeOutpaint:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'generated': ('IMAGE',), 'source': ('IMAGE',), 'mask': ('MASK',),
                             'feather': ('INT', {'default': 16, 'min': 0, 'max': 128})},
                'optional': {'colour_match': ('FLOAT', {'default': 0.0, 'min': 0.0, 'max': 1.0, 'step': .05})}}
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'composite'
    CATEGORY = 'Zura/Artist Studio'
    def composite(self, generated, source, mask, feather=16, colour_match=0.0):
        return (composite_hdr_outpaint(generated, source, mask, feather, colour_match),)


NODE_CLASS_MAPPINGS = {'ZuraLTXOutpaintCanvas': ZuraLTXOutpaintCanvas,
                       'ZuraLTXOutpaintHDRCanvas': ZuraLTXOutpaintHDRCanvas,
                       'ZuraHDRCompositeOutpaint': ZuraHDRCompositeOutpaint}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraLTXOutpaintCanvas': 'Zura · Prepare Outpaint Canvas',
                              'ZuraLTXOutpaintHDRCanvas': 'Zura · Prepare HDR Outpaint Canvas (experimental)',
                              'ZuraHDRCompositeOutpaint': 'Zura · Composite HDR Outpaint (experimental)'}


def build_test_graph(source_file, output_prefix, frame_count, fps, width, height,
                     *, mode='expand', left=0, top=0, right=0, bottom=0,
                     prompt='', seed=42, black_threshold=2 / 255):
    """Build the tested native single-graph LTX 2.5 outpaint prototype.

    The supplied source must already contain exactly ``frame_count`` frames,
    in the desired time range, and a valid audio stream. 8n+1 frame counts are
    required here; Studio must explicitly pad and trim arbitrary selections.
    """
    if not source_file or not output_prefix:
        raise ValueError('Select a source clip and output destination.')
    if type(frame_count) is not int or frame_count < 1 or (frame_count - 1) % 8:
        raise ValueError('This prototype requires an 8n+1 frame source clip.')
    if not math.isfinite(float(fps)) or not 1 <= float(fps) <= 120:
        raise ValueError('Choose a valid source frame rate.')
    if type(width) is not int or type(height) is not int or min(width, height) < 128 or max(width, height) > 4096 or width % 64 or height % 64:
        raise ValueError('Output dimensions must be multiples of 64 between 128 and 4096.')
    if mode not in ('expand', 'black') or any(type(v) is not int or v < 0 for v in (left, top, right, bottom)):
        raise ValueError('Choose valid canvas mode and margins.')
    if width - left - right < 1 or height - top - bottom < 1:
        raise ValueError('Canvas margins leave no room for the source.')
    if not 0 <= float(black_threshold) <= .1:
        raise ValueError('Black threshold must be between 0 and 0.1.')

    g = {}
    def node(key, typ, **inputs):
        g[key] = {'class_type': typ, 'inputs': inputs}
        return [key, 0]
    def port(link, index):
        return [link[0], index]
    video = node('source', 'LoadVideo', file=source_file)
    components = node('components', 'GetVideoComponents', video=video)
    canvas = node('canvas', 'ZuraLTXOutpaintCanvas', images=components, mode=mode, width=width, height=height,
                  left=left, top=top, right=right, bottom=bottom, black_threshold=black_threshold)
    mask_image = node('mask_image', 'MaskToImage', mask=port(canvas, 1))
    low_mask_image = node('low_mask_image', 'ImageScale', image=mask_image, upscale_method='area', width=width//2, height=height//2, crop='disabled')
    low_mask = node('low_mask', 'ImageToMask', image=low_mask_image, channel='red')
    low_reference = node('low_reference', 'ImageScale', image=canvas, upscale_method='lanczos', width=width//2, height=height//2, crop='disabled')
    guide_pixels = node('inpaint', 'LTXVInpaintPreprocess', images=low_reference, mask=low_mask)
    encoder = node('encoder', 'CLIPLoader', clip_name='gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors', type='ltxv', device='default')
    positive = node('positive', 'CLIPTextEncode', clip=encoder, text=str(prompt))
    negative = node('negative', 'CLIPTextEncode', clip=encoder, text='pc game, console game, video game, cartoon, childish, ugly')
    cond = node('conditioning', 'LTXVConditioning', positive=positive, negative=negative, frame_rate=float(fps))
    vae = node('video_vae', 'VAELoader', vae_name='ltx-2.5-video-vae-conv-bf16.safetensors')
    audio_vae = node('audio_vae', 'VAELoader', vae_name='ltx-2.5-audio-vae-bf16.safetensors')
    model = node('model', 'UNETLoader', unet_name='ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors', weight_dtype='default')
    adapter = node('adapter', 'LTXICLoRALoaderModelOnly', model=model, lora_name='ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors', strength_model=1.0)
    latent = node('empty', 'EmptyLTXVLatentVideo', width=width//2, height=height//2, length=frame_count, batch_size=1)
    guide = node('guide', 'LTXAddVideoICLoRAGuideAdvanced', positive=cond, negative=port(cond,1), vae=vae, latent=latent, image=guide_pixels,
                 frame_idx=0, strength=1.0, latent_downscale_factor=port(adapter,1), crop='disabled', use_tiled_encode=False,
                 tile_size=256, tile_overlap=64, attention_strength=1.0)
    audio = node('audio_encoded', 'VAEEncodeAudio', audio=port(components,1), vae=audio_vae)
    frozen = node('audio_frozen', 'LTXVSetAudioRefTokens', positive=guide, negative=port(guide,1), audio_latent=audio)
    av = node('av', 'LTXVConcatAVLatent', video_latent=port(guide,2), audio_latent=port(frozen,2))
    guider = node('guider', 'CFGGuider', model=adapter, positive=frozen, negative=port(frozen,1), cfg=1.0)
    noise = node('noise', 'RandomNoise', noise_seed=int(seed))
    sampler = node('sampler', 'KSamplerSelect', sampler_name='euler_ancestral')
    sigmas = node('sigmas', 'ManualSigmas', sigmas='1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0')
    sample = node('sample', 'SamplerCustomAdvanced', noise=noise, guider=guider, sampler=sampler, sigmas=sigmas, latent_image=av)
    split = node('split', 'LTXVSeparateAVLatent', av_latent=sample)
    crop = node('crop_guides', 'LTXVCropGuides', positive=frozen, negative=port(frozen,1), latent=split)
    decode = node('decode_low', 'VAEDecodeTiled', samples=port(crop,2), vae=vae, tile_size=512, overlap=64, temporal_size=128, temporal_overlap=32)
    blend = node('blend_low', 'LTXVLaplacianPyramidBlend', image_a=decode, image_b=low_reference, mask=low_mask, trim_to_shortest=True, mask_low_res_dilation=5)
    upsized = node('upsize', 'ImageScale', image=blend, upscale_method='lanczos', width=width, height=height, crop='disabled')
    encoded = node('encode_high', 'VAEEncodeTiled', pixels=upsized, vae=vae, tile_size=512, overlap=64, temporal_size=128, temporal_overlap=32)
    frozen2 = node('freeze_high', 'LTXVSetAudioRefTokens', positive=cond, negative=port(cond,1), audio_latent=port(split,1))
    av2 = node('av_high', 'LTXVConcatAVLatent', video_latent=encoded, audio_latent=port(frozen2,2))
    guider2 = node('guider_high', 'CFGGuider', model=adapter, positive=cond, negative=port(cond,1), cfg=1.0)
    noise2 = node('noise_high', 'RandomNoise', noise_seed=int(seed))
    sampler2 = node('sampler_high', 'KSamplerSelect', sampler_name='euler')
    sigmas2 = node('sigmas_high', 'ManualSigmas', sigmas='0.7250, 0.4219, 0.0')
    sample2 = node('sample_high', 'SamplerCustomAdvanced', noise=noise2, guider=guider2, sampler=sampler2, sigmas=sigmas2, latent_image=av2)
    split2 = node('split_high', 'LTXVSeparateAVLatent', av_latent=sample2)
    decode2 = node('decode_high', 'VAEDecodeTiled', samples=split2, vae=vae, tile_size=512, overlap=64, temporal_size=128, temporal_overlap=32)
    green2 = node('green_high', 'LTXVInpaintPreprocess', images=canvas, mask=port(canvas,1))
    final = node('blend_high', 'LTXVLaplacianPyramidBlend', image_a=decode2, image_b=green2, mask=port(canvas,1), trim_to_shortest=True, mask_low_res_dilation=6)
    video_out = node('assemble', 'CreateVideo', images=final, fps=float(fps), audio=port(components,1), bit_depth=8, color_space='sRGB', codec='none')
    node('save', 'SaveVideo', video=video_out, filename_prefix=output_prefix, format='mp4',
         **{'format.codec':'h264', 'format.codec.encoding':'re-encode', 'format.codec.encoding.crf':16.0})
    return g
