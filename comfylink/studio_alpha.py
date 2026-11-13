"""Source-bound AE alpha delivery, before preview/container quantisation."""
from fractions import Fraction
import hashlib
import re
import secrets

import numpy as np
import torch
import torch.nn.functional as F

from . import float_io
from .frame_contract import normalise_frame_contract


def alpha_source_contract(input_root, contract, info):
    contract = normalise_frame_contract(contract)
    fingerprint = contract.get('sourceManifestSha256')
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[a-f0-9]{64}', fingerprint):
        raise ValueError('The AE alpha source has no verified manifest identity')
    relative = 'ComfyLink/' + contract['sessionId'] + '/manifest.json'
    manifest = float_io.read_manifest(input_root, relative)
    actual = hashlib.sha256(float_io.canonical_manifest_bytes(manifest)).hexdigest()
    rate = lambda value: Fraction(value['numerator'], value['denominator'])
    if (actual != fingerprint or manifest['sampleType'] != 'float32'
            or manifest['sourceBitDepth'] != 32 or manifest['alphaAssociation'] != 'straight'
            or manifest['width'] != contract['width'] or manifest['height'] != contract['height']
            or len(manifest['frames']) != contract['frameCount']
            or rate(manifest['frameRate']) != rate(contract['frameRate'])
            or info['width'] != manifest['width'] or info['height'] != manifest['height']
            or info['frame_count'] != len(manifest['frames']) or info['start_frame'] != 0
            or Fraction(info['fps_rational']) != rate(manifest['frameRate'])):
        raise ValueError('The alpha output no longer matches its captured AE source')
    return manifest, relative


def write_ae_alpha(input_root, output_root, contract, info, images, *, check_cancelled=None):
    manifest, relative = alpha_source_contract(input_root, contract, info)
    count, width, height = len(manifest['frames']), manifest['width'], manifest['height']
    if len(images) < count:
        raise ValueError('The generated matte is shorter than the AE source')

    def frames():
        for index, original in enumerate(float_io.iter_transfer(input_root, relative)):
            if check_cancelled is not None:
                check_cancelled()
            matte = images[index, :info['content_height'], :info['content_width'], :3].detach().to(device='cpu', dtype=torch.float32)
            if not torch.isfinite(matte).all():
                raise ValueError('The generated matte contains invalid pixels')
            matte = matte.mean(dim=-1)[None, None]
            if tuple(matte.shape[-2:]) != (height, width):
                matte = F.interpolate(matte, size=(height, width), mode='bilinear', align_corners=False)
            mask = matte[0, 0].clamp(0, 1).numpy()
            if np.any(original[..., 3] < 0) or np.any(original[..., 3] > 1):
                raise ValueError('The captured AE source alpha is outside 0–1')
            result = original.copy()
            # Preserve RGB bits, including hidden RGB and values beyond SDR.
            result[..., 3] = original[..., 3] * mask
            yield result

    return float_io.write_transfer_frames(output_root, 'ComfyLink/' + secrets.token_hex(16), frames(),
        colour=manifest['colour'], frame_rate=manifest['frameRate'], source_bit_depth=32,
        alpha_association='straight', source_start=manifest.get('sourceStart'), expected_count=count)
