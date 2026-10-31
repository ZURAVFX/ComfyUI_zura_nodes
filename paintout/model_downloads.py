"""User-initiated, pinned Paintout model downloads, independent of Zura Studio.

Catalogue sizes and LFS SHA-256 were checked through Hugging Face's official
model API at the pinned publisher revisions on 30 October 2026. Discovery is
offline. Existing model readiness is a size/header check, not a full hash scan.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import threading
import uuid

CATALOG = {'targeted': {'name': 'Targeted video repair',
              'files': [{'folder': 'diffusion_models',
                         'filename': 'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
                         'repo': 'Lightricks/LTX-2.5',
                         'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                         'remote_path': 'diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
                         'size_bytes': 21504034224,
                         'sha256': 'c4279eeff115cbeaca494bd2183e7d768c38fe85a184dc6afbb7159157c44334',
                         'gated': True,
                         'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                        {'folder': 'text_encoders',
                         'filename': 'gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
                         'repo': 'Lightricks/LTX-2.5',
                         'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                         'remote_path': 'text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
                         'size_bytes': 15372969374,
                         'sha256': '6ce688a0aa98a5fa36a9f1e6c3f42152a498cc2b53ee8c15674c64244f91487f',
                         'gated': True,
                         'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                        {'folder': 'vae',
                         'filename': 'ltx-2.5-audio-vae-bf16.safetensors',
                         'repo': 'Lightricks/LTX-2.5',
                         'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                         'remote_path': 'vae/ltx-2.5-audio-vae-bf16.safetensors',
                         'size_bytes': 364866540,
                         'sha256': 'c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5',
                         'gated': True,
                         'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                        {'folder': 'vae',
                         'filename': 'ltx-2.5-video-vae-conv-bf16.safetensors',
                         'repo': 'Lightricks/LTX-2.5',
                         'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                         'remote_path': 'vae/ltx-2.5-video-vae-conv-bf16.safetensors',
                         'size_bytes': 1452269922,
                         'sha256': '685b06ee3d9b2039647698fc4ea33175112462fc374e2777312c907897dfce8d',
                         'gated': True,
                         'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                        {'filename': 'LTX23_Obscura_Remova_v1.safetensors',
                         'repo': 'WepeNerd/Obscura_Remova',
                         'revision': '907f5d25e0b1d8fcc15936a064fd85b4609e7d2b',
                         'remote_path': 'LTX23_Obscura_Remova_v1.safetensors',
                         'folder': 'loras',
                         'size_bytes': 327344864,
                         'sha256': 'e58ff6e1076caf40707b9b890aeae1d1c0bd26f285f7666aafc052a06d35f22a',
                         'gated': False,
                         'model_card': 'https://huggingface.co/WepeNerd/Obscura_Remova'}],
              'note': 'LTX 2.5 and the object-removal adapter for an SDR repair.',
              'license_url': 'https://huggingface.co/Lightricks/LTX-2.5'},
 'full': {'name': 'Full-scene clean plate',
          'files': [{'folder': 'diffusion_models',
                     'filename': 'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
                     'repo': 'Lightricks/LTX-2.5',
                     'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                     'remote_path': 'diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
                     'size_bytes': 21504034224,
                     'sha256': 'c4279eeff115cbeaca494bd2183e7d768c38fe85a184dc6afbb7159157c44334',
                     'gated': True,
                     'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                    {'folder': 'text_encoders',
                     'filename': 'gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
                     'repo': 'Lightricks/LTX-2.5',
                     'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                     'remote_path': 'text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
                     'size_bytes': 15372969374,
                     'sha256': '6ce688a0aa98a5fa36a9f1e6c3f42152a498cc2b53ee8c15674c64244f91487f',
                     'gated': True,
                     'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                    {'folder': 'vae',
                     'filename': 'ltx-2.5-audio-vae-bf16.safetensors',
                     'repo': 'Lightricks/LTX-2.5',
                     'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                     'remote_path': 'vae/ltx-2.5-audio-vae-bf16.safetensors',
                     'size_bytes': 364866540,
                     'sha256': 'c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5',
                     'gated': True,
                     'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                    {'folder': 'vae',
                     'filename': 'ltx-2.5-video-vae-conv-bf16.safetensors',
                     'repo': 'Lightricks/LTX-2.5',
                     'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                     'remote_path': 'vae/ltx-2.5-video-vae-conv-bf16.safetensors',
                     'size_bytes': 1452269922,
                     'sha256': '685b06ee3d9b2039647698fc4ea33175112462fc374e2777312c907897dfce8d',
                     'gated': True,
                     'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                    {'folder': 'loras',
                     'filename': 'ltx-2.5-22b-ic-lora-clean-plate-1.0.safetensors',
                     'repo': 'Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate',
                     'revision': '5cdacad3ee33574ecb11120b873dec320de79b37',
                     'remote_path': 'ltx-2.5-22b-ic-lora-clean-plate-1.0.safetensors',
                     'size_bytes': 327318439,
                     'sha256': '27f4f7ba552d3bf7273dd817291123a5934f17e7698ca9cd8945b079a5358393',
                     'gated': True,
                     'model_card': 'https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate'}],
          'note': 'LTX 2.5 and the clean-plate adapter for a full-scene SDR repair.',
          'license_url': 'https://huggingface.co/Lightricks/LTX-2.5'},
 'targeted_hdr': {'name': 'Targeted HDR video repair',
                  'files': [{'folder': 'diffusion_models',
                             'filename': 'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
                             'repo': 'Lightricks/LTX-2.5',
                             'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                             'remote_path': 'diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
                             'size_bytes': 21504034224,
                             'sha256': 'c4279eeff115cbeaca494bd2183e7d768c38fe85a184dc6afbb7159157c44334',
                             'gated': True,
                             'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                            {'folder': 'text_encoders',
                             'filename': 'gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
                             'repo': 'Lightricks/LTX-2.5',
                             'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                             'remote_path': 'text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
                             'size_bytes': 15372969374,
                             'sha256': '6ce688a0aa98a5fa36a9f1e6c3f42152a498cc2b53ee8c15674c64244f91487f',
                             'gated': True,
                             'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                            {'folder': 'vae',
                             'filename': 'ltx-2.5-audio-vae-bf16.safetensors',
                             'repo': 'Lightricks/LTX-2.5',
                             'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                             'remote_path': 'vae/ltx-2.5-audio-vae-bf16.safetensors',
                             'size_bytes': 364866540,
                             'sha256': 'c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5',
                             'gated': True,
                             'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                            {'folder': 'vae',
                             'filename': 'ltx-2.5-video-vae-bf16.safetensors',
                             'repo': 'Lightricks/LTX-2.5',
                             'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                             'remote_path': 'vae/ltx-2.5-video-vae-bf16.safetensors',
                             'size_bytes': 1472223346,
                             'sha256': '847e14ca7f3355debca0cea4eaa24ac0fbcdf0061da054ac89ca638a869ddba3',
                             'gated': True,
                             'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                            {'filename': 'LTX23_Obscura_Remova_v1.safetensors',
                             'repo': 'WepeNerd/Obscura_Remova',
                             'revision': '907f5d25e0b1d8fcc15936a064fd85b4609e7d2b',
                             'remote_path': 'LTX23_Obscura_Remova_v1.safetensors',
                             'folder': 'loras',
                             'size_bytes': 327344864,
                             'sha256': 'e58ff6e1076caf40707b9b890aeae1d1c0bd26f285f7666aafc052a06d35f22a',
                             'gated': False,
                             'model_card': 'https://huggingface.co/WepeNerd/Obscura_Remova'}],
                  'note': 'Uses the full HDR video VAE; the SDR-only VAE is not downloaded.',
                  'license_url': 'https://huggingface.co/Lightricks/LTX-2.5'},
 'full_hdr': {'name': 'Full-scene HDR clean plate',
              'files': [{'folder': 'diffusion_models',
                         'filename': 'ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
                         'repo': 'Lightricks/LTX-2.5',
                         'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                         'remote_path': 'diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors',
                         'size_bytes': 21504034224,
                         'sha256': 'c4279eeff115cbeaca494bd2183e7d768c38fe85a184dc6afbb7159157c44334',
                         'gated': True,
                         'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                        {'folder': 'text_encoders',
                         'filename': 'gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
                         'repo': 'Lightricks/LTX-2.5',
                         'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                         'remote_path': 'text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors',
                         'size_bytes': 15372969374,
                         'sha256': '6ce688a0aa98a5fa36a9f1e6c3f42152a498cc2b53ee8c15674c64244f91487f',
                         'gated': True,
                         'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                        {'folder': 'vae',
                         'filename': 'ltx-2.5-audio-vae-bf16.safetensors',
                         'repo': 'Lightricks/LTX-2.5',
                         'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                         'remote_path': 'vae/ltx-2.5-audio-vae-bf16.safetensors',
                         'size_bytes': 364866540,
                         'sha256': 'c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5',
                         'gated': True,
                         'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                        {'folder': 'vae',
                         'filename': 'ltx-2.5-video-vae-bf16.safetensors',
                         'repo': 'Lightricks/LTX-2.5',
                         'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                         'remote_path': 'vae/ltx-2.5-video-vae-bf16.safetensors',
                         'size_bytes': 1472223346,
                         'sha256': '847e14ca7f3355debca0cea4eaa24ac0fbcdf0061da054ac89ca638a869ddba3',
                         'gated': True,
                         'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                        {'folder': 'loras',
                         'filename': 'ltx-2.5-22b-ic-lora-clean-plate-1.0.safetensors',
                         'repo': 'Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate',
                         'revision': '5cdacad3ee33574ecb11120b873dec320de79b37',
                         'remote_path': 'ltx-2.5-22b-ic-lora-clean-plate-1.0.safetensors',
                         'size_bytes': 327318439,
                         'sha256': '27f4f7ba552d3bf7273dd817291123a5934f17e7698ca9cd8945b079a5358393',
                         'gated': True,
                         'model_card': 'https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate'}],
              'note': 'Uses the full HDR video VAE; the SDR-only VAE is not downloaded.',
              'license_url': 'https://huggingface.co/Lightricks/LTX-2.5'},
 'mask': {'name': 'Point masking (SAM 3)',
          'files': [{'filename': 'sam3.1_multiplex_fp16.safetensors',
                     'repo': 'Comfy-Org/sam3.1',
                     'revision': '7bb8374780a725b4353ed31f3a9395c9742b5621',
                     'remote_path': 'checkpoints/sam3.1_multiplex_fp16.safetensors',
                     'folder': 'checkpoints',
                     'size_bytes': 1745546848,
                     'sha256': '9ba99c92703c2e8b4f47de2d34a539bb8e18923049e238b780d70dbe6368eb03',
                     'gated': False,
                     'model_card': 'https://huggingface.co/Comfy-Org/sam3.1'}],
          'note': 'Needed for point selection and automatic tracking. Manual painting and imported masks can be '
                  'used without this download.',
          'license_url': 'https://huggingface.co/Comfy-Org/sam3.1'},
 'clean': {'name': 'Clean-frame painting (FLUX 3)',
           'files': [{'folder': 'diffusion_models',
                      'filename': 'flux3-image-klein-int8-convrot.safetensors',
                      'repo': 'black-forest-labs/flux-3-image-klein-comfy',
                      'revision': 'feef60b0aaf63a4773ace96636ebbcf43b881312',
                      'remote_path': 'diffusion_models/flux3-image-klein-int8-convrot.safetensors',
                      'size_bytes': 5827874779,
                      'sha256': '847d8933548afd93df4af2cac2498e70891bf28d9dae06d695f536992e168fe2',
                      'gated': True,
                      'model_card': 'https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy'},
                     {'folder': 'text_encoders',
                      'filename': 'qwen3vl_4b_int8_convrot.safetensors',
                      'repo': 'black-forest-labs/flux-3-image-klein-comfy',
                      'revision': 'feef60b0aaf63a4773ace96636ebbcf43b881312',
                      'remote_path': 'text_encoders/qwen3vl_4b_int8_convrot.safetensors',
                      'size_bytes': 4858559240,
                      'sha256': '32de113cbf8282b02cbff0794b637b9d6676da09314a1db5a30bcea9bf4ee01c',
                      'gated': True,
                      'model_card': 'https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy'},
                     {'folder': 'vae',
                      'filename': 'flux2-vae.safetensors',
                      'repo': 'Comfy-Org/flux2-klein-9B',
                      'revision': '1138ce884c8e977cdacacbe779784fec4426bb3f',
                      'remote_path': 'split_files/vae/flux2-vae.safetensors',
                      'size_bytes': 336211292,
                      'sha256': '868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3',
                      'existing_variants': [{'repo': 'Comfy-Org/flux2-dev',
                                             'revision': '9630c1b4b6e690497ae0c19bb6b1b35d4ebedcb7',
                                             'remote_path': 'split_files/vae/flux2-vae.safetensors',
                                             'size_bytes': 336213556,
                                             'sha256': 'd64f3a68e1cc4f9f4e29b6e0da38a0204fe9a49f2d4053f0ec1fa1ca02f9c4b5'}],
                      'gated': False,
                      'model_card': 'https://huggingface.co/Comfy-Org/flux2-klein-9B'}],
           'note': 'Needed for Clean with FLUX 3. You can import manually edited frames instead.',
           'license_url': 'https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy'},
 'hdr_conversion': {'name': 'SDR to HDR conversion',
                    'files': [{'folder': 'vae',
                               'filename': 'ltx-2.5-video-vae-bf16.safetensors',
                               'repo': 'Lightricks/LTX-2.5',
                               'revision': '49b093a39c19169a8a81721dcc541e07e945232f',
                               'remote_path': 'vae/ltx-2.5-video-vae-bf16.safetensors',
                               'size_bytes': 1472223346,
                               'sha256': '847e14ca7f3355debca0cea4eaa24ac0fbcdf0061da054ac89ca638a869ddba3',
                               'gated': True,
                               'model_card': 'https://huggingface.co/Lightricks/LTX-2.5'},
                              {'folder': 'loras',
                               'filename': 'ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors',
                               'repo': 'Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR',
                               'revision': 'c7578ebddb54f4210e534e4d8cad698a5a520692',
                               'remote_path': 'ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors',
                               'size_bytes': 1308787472,
                               'sha256': '0b39eac09672c18d0d10f401d5e71a68a73225f1169df826b092b7e5ef489675',
                               'gated': True,
                               'model_card': 'https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR'},
                              {'folder': 'embeddings',
                               'filename': 'ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors',
                               'repo': 'Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR',
                               'revision': 'c7578ebddb54f4210e534e4d8cad698a5a520692',
                               'remote_path': 'ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors',
                               'size_bytes': 12614165,
                               'sha256': '63c03987a1984f6d4b3d3440c15deee66b0310c01950496329f983f5dc8c88bd',
                               'gated': True,
                               'model_card': 'https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR'}],
                    'note': 'Only needed when converting an SDR repair to HDR.',
                    'license_url': 'https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR'}}


class DownloadError(RuntimeError):
    """Only controlled messages from this exception may reach the browser."""
    def __init__(self, message, *, auth_required=False):
        super().__init__(message)
        self.auth_required = auth_required


class Cancelled(Exception):
    pass


def _safe_item(item):
    filename = item.get('filename', '')
    if not isinstance(filename, str) or not filename or Path(filename).name != filename or '/' in filename or '\\' in filename or filename in ('.', '..'):
        raise ValueError('Invalid model catalogue filename.')
    if item.get('folder') not in {'diffusion_models', 'text_encoders', 'vae', 'loras', 'checkpoints', 'embeddings'}:
        raise ValueError('Invalid model catalogue category.')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', item.get('repo', '')) or not re.fullmatch(r'[0-9a-f]{40}', item.get('revision', '')):
        raise ValueError('Invalid pinned model repository.')
    remote = PurePosixPath(item.get('remote_path', ''))
    if remote.is_absolute() or '..' in remote.parts or '\\' in str(remote) or not remote.parts:
        raise ValueError('Invalid model catalogue source.')
    if type(item.get('size_bytes')) is not int or item['size_bytes'] < 16 or not re.fullmatch(r'[0-9a-f]{64}', item.get('sha256', '')):
        raise ValueError('Invalid model integrity metadata.')
    variants = item.get('existing_variants', [])
    if not isinstance(variants, list):
        raise ValueError('Invalid existing model variants.')
    for variant in variants:
        if not isinstance(variant, dict):
            raise ValueError('Invalid existing model variant.')
        _safe_item({**item, **variant, 'existing_variants': []})
    return item


def safetensors_header(path, size):
    """Reject HTML, pickle and malformed containers without loading tensors."""
    with Path(path).open('rb') as source:
        prefix = source.read(8)
        if len(prefix) != 8:
            raise DownloadError('This file is not a valid safetensors model.')
        length = struct.unpack('<Q', prefix)[0]
        if not 2 <= length <= min(100 * 1024 * 1024, size - 8):
            raise DownloadError('This file is not a valid safetensors model.')
        try:
            header = json.loads(source.read(length))
        except (ValueError, UnicodeError) as error:
            raise DownloadError('This file is not a valid safetensors model.') from error
    if not isinstance(header, dict):
        raise DownloadError('This file has an invalid model header.')
    spans = []
    for name, tensor in header.items():
        if name == '__metadata__':
            continue
        if not isinstance(tensor, dict) or not isinstance(tensor.get('dtype'), str) or not isinstance(tensor.get('shape'), list):
            raise DownloadError('This file has an invalid model header.')
        offsets = tensor.get('data_offsets')
        if not isinstance(offsets, list) or len(offsets) != 2 or any(type(value) is not int for value in offsets) or not 0 <= offsets[0] <= offsets[1] <= size - length - 8:
            raise DownloadError('This file has invalid tensor data offsets.')
        if offsets[1] > offsets[0]:
            spans.append(tuple(offsets))
    cursor = 0
    for start, end in sorted(spans):
        if start != cursor:
            raise DownloadError('This file has incomplete or overlapping model data.')
        cursor = end
    if not spans or cursor != size - length - 8:
        raise DownloadError('This file has incomplete model data.')


@lru_cache(maxsize=128)
def _existing_sha256(path, size, modified_ns, changed_ns, inode):
    """Hash narrow alternate layouts once per file identity, never every poll.

    Comfy supports the original FLUX VAE and its published diffusers key layout.
    An alternate size alone is insufficient; its full published hash must match.
    """
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    current = Path(path).stat()
    if (current.st_size, current.st_mtime_ns, current.st_ctime_ns, current.st_ino) != (size, modified_ns, changed_ns, inode):
        raise DownloadError('The existing model changed while it was being checked. Refresh and retry.')
    return digest.hexdigest()


def _candidate_index(locations, filenames=None):
    """Index basenames once, including registered roots and their subfolders."""
    wanted = {item['filename'] for recipe in CATALOG.values() for item in recipe['files']}
    result = {}
    for folder, roots in locations.items():
        entries = filenames.get(folder, ()) if filenames is not None else None
        for root in roots:
            root = Path(root).resolve()
            candidates = (root / entry for entry in entries) if entries is not None else root.rglob('*.safetensors') if root.exists() else ()
            for candidate in candidates:
                # Existing model symlinks are readable; they are never written.
                if candidate.name in wanted and candidate.is_file():
                    result.setdefault((folder, candidate.name), []).append(candidate)
            for name in wanted:
                candidate = root / name
                if candidate.is_file():
                    result.setdefault((folder, name), []).append(candidate)
    ordered = {}
    for key, paths in result.items():
        roots = [Path(root).resolve() for root in locations[key[0]]]
        def choice_order(path):
            choices = [(path.relative_to(root).as_posix(), number)
                       for number, root in enumerate(roots) if path.is_relative_to(root)]
            relative, number = min(choices, key=lambda choice: (len(PurePosixPath(choice[0]).parts), choice[1]))
            # Native recipes prefer the exact root filename, then the first
            # relative filename. Comfy resolves that choice in root order.
            return ('/' in relative, relative, number)
        ordered[key] = sorted(dict.fromkeys(paths), key=choice_order)
    return ordered


def inspect(model_id, locations, index=None, checked=None):
    if not isinstance(model_id, str) or model_id not in CATALOG:
        raise ValueError('Choose a model package from the download list.')
    index = _candidate_index(locations) if index is None else index
    checked = {} if checked is None else checked
    recipe = CATALOG[model_id]
    files = []
    for raw in recipe['files']:
        item = _safe_item(raw)
        roots = locations.get(item['folder'], [])
        if not roots:
            raise ValueError('ComfyUI has no configured folder for ' + item['folder'] + '. Restart ComfyUI after installing its required node packs.')
        candidates = index.get((item['folder'], item['filename']), ())
        usable = None
        for candidate in candidates:
            stat = candidate.stat()
            key = (str(candidate), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino)
            if key not in checked:
                try:
                    if stat.st_size != item['size_bytes']:
                        variants = [variant for variant in item.get('existing_variants', []) if variant['size_bytes'] == stat.st_size]
                        if not variants or _existing_sha256(*key) not in {variant['sha256'] for variant in variants}:
                            raise DownloadError('Wrong size or unrecognised existing variant.')
                    safetensors_header(candidate, stat.st_size)
                    checked[key] = True
                except (DownloadError, OSError):
                    checked[key] = False
            if checked[key]:
                usable = candidate
            # Never fall through to a healthy duplicate after a broken copy:
            # the native loader would still resolve the earlier chosen name.
            break
        destination = Path(roots[0]).resolve() / item['filename']
        if not destination.resolve().is_relative_to(Path(roots[0]).resolve()):
            raise ValueError('The model destination is outside its configured folder.')
        conflict = bool(candidates) and usable is None
        partial = destination.parent / ('.zura-paintout-' + item['sha256'] + '.part')
        partial_bytes = partial.stat().st_size if partial.is_file() else 0
        files.append({**item, 'installed': usable is not None, 'incomplete': conflict,
                      'destination_root': str(Path(roots[0]).resolve()),
                      'destination': str(usable or destination), 'partial_bytes': min(partial_bytes, item['size_bytes'])})
    return dict(id=model_id, name=recipe['name'], gated=any(item.get('gated') for item in recipe['files']),
                note=recipe.get('note', ''), license_url=recipe['license_url'], files=files,
                remaining_bytes=sum(item['size_bytes'] for item in files if not item['installed']))


def _public_recipe(recipe):
    return {**recipe, 'files': [{key: value for key, value in item.items() if key not in {'destination', 'destination_root', 'repo', 'revision', 'remote_path', 'existing_variants'}} for item in recipe['files']]}


def _rename_noreplace(source, destination):
    if os.name == 'nt':
        os.rename(source, destination)
        return
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise OSError(errno.ENOTSUP, 'Atomic installation is unavailable')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def _publish_verified(source, destination):
    try:
        os.link(source, destination)
    except FileExistsError:
        raise
    except OSError:
        _rename_noreplace(source, destination)


def _check_publish_supported(directory):
    stem = '.zura-paintout-probe-' + uuid.uuid4().hex
    source, destination = directory / stem, directory / (stem + '-installed')
    try:
        source.touch(exist_ok=False)
        _publish_verified(source, destination)
    except OSError as error:
        raise DownloadError('This model folder does not support safe atomic installation. Choose another ComfyUI model folder.') from error
    finally:
        source.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)


@contextmanager
def _partial_lock(path):
    """An OS lock is released after a crash; a stale empty lock file is harmless."""
    with Path(path).open('a+b') as lock:
        try:
            if os.name == 'nt':
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise DownloadError('Another ComfyUI instance is downloading this file. Wait for it to finish.') from error
        try:
            yield
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _cached_token():
    try:
        from huggingface_hub import get_token
        return get_token()
    except (ImportError, OSError):
        return None


class DownloadManager:
    """One background download at a time, shared across the local Paintout UI."""
    def __init__(self, locations, *, fetch=None, on_installed=None):
        self.locations = locations
        self._fetch = fetch
        self.on_installed = on_installed or (lambda: None)
        self._lock = threading.Lock()
        self._jobs = {}
        self._active = None
        self.filenames = None

    def catalogue(self):
        index, checked = _candidate_index(self.locations, self.filenames), {}
        models = []
        for model_id, recipe in CATALOG.items():
            try:
                models.append(_public_recipe(inspect(model_id, self.locations, index, checked)))
            except (ValueError, OSError):
                models.append(dict(id=model_id, name=recipe['name'], files=[], error='The configured model folder is unavailable. Check ComfyUI model paths and refresh.'))
        return dict(models=models, active=self.active())

    def status(self, job_id):
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError('Unknown model download. Refresh the download list.')
            return {key: value for key, value in self._jobs[job_id].items() if key != 'cancel'}

    def active(self):
        with self._lock:
            job = self._jobs.get(self._active)
            return {key: value for key, value in job.items() if key != 'cancel'} if job else None

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ValueError('Unknown model download. Refresh the download list.')
            if job['phase'] not in ('done', 'failed', 'cancelled'):
                job['cancel'].set()
                job['phase'] = 'cancelling'

    def start(self, model_ids, token=None):
        if isinstance(model_ids, str):
            model_ids = [model_ids]
        if not isinstance(model_ids, list) or not model_ids or len(model_ids) > len(CATALOG) or any(not isinstance(value, str) or value not in CATALOG for value in model_ids):
            raise ValueError('Choose model packages from the download list.')
        if token is not None and (not isinstance(token, str) or len(token.strip()) > 512 or (token.strip() and not re.fullmatch(r'hf_[A-Za-z0-9]+', token.strip()))):
            raise ValueError('Enter a Hugging Face read token, or leave the token field empty.')
        token = token.strip() if token else None
        model_ids = list(dict.fromkeys(model_ids))
        index, checked, files = _candidate_index(self.locations, self.filenames), {}, {}
        for model_id in model_ids:
            for item in inspect(model_id, self.locations, index, checked)['files']:
                if item['incomplete']:
                    raise ValueError('The copy of ' + item['filename'] + ' selected by ComfyUI has a different size or invalid header, and may hide another valid copy. It will not be overwritten. Move the broken copy out of ComfyUI’s model folders, then refresh and retry.')
                files[(item['folder'], item['filename'])] = item
        missing = [item for item in files.values() if not item['installed']]
        with self._lock:
            if self._active is not None:
                raise ValueError('A model download is already running. Wait for it or cancel it first.')
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = dict(id=job_id, model_id=model_ids[0], model_ids=model_ids,
                phase='queued', done_bytes=0, total_bytes=sum(item['size_bytes'] for item in missing),
                current_file='', error='', auth_required=False, cancel=threading.Event())
            self._active = job_id
        threading.Thread(target=self._run, args=(job_id, missing, token), daemon=True).start()
        return job_id

    def _update(self, job_id, **values):
        with self._lock:
            self._jobs[job_id].update(values)

    def _cancelled(self, job_id):
        if self._jobs[job_id]['cancel'].is_set():
            raise Cancelled()

    def _download(self, job_id, item, token, base):
        import requests
        destination = Path(item['destination'])
        root = destination.parent.resolve()
        if root != Path(item['destination_root']) or destination.name != item['filename'] or destination.resolve().parent != root:
            raise DownloadError('The model destination changed. Refresh the download list.')
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / ('.zura-paintout-' + item['sha256'] + '.part')
        lock_file = root / ('.zura-paintout-' + item['sha256'] + '.lock')
        if temporary.is_symlink() or lock_file.is_symlink() or temporary.resolve().parent != root or lock_file.resolve().parent != root:
            raise DownloadError('The temporary model path is not safe. Choose another model folder.')
        url = 'https://huggingface.co/' + item['repo'] + '/resolve/' + item['revision'] + '/' + item['remote_path']
        fetch = self._fetch or requests.get
        with _partial_lock(lock_file):
            _check_publish_supported(root)
            if temporary.exists() and temporary.stat().st_size > item['size_bytes']:
                temporary.unlink()
            for attempt in range(3):
                self._cancelled(job_id)
                offset = temporary.stat().st_size if temporary.exists() else 0
                if offset == item['size_bytes']:
                    break
                if shutil.disk_usage(root).free < item['size_bytes'] - offset:
                    raise DownloadError('There is not enough free disk space for ' + item['filename'] + '.')
                headers = {'Accept-Encoding': 'identity'}
                if token:
                    headers['Authorization'] = 'Bearer ' + token
                if offset:
                    headers['Range'] = 'bytes=' + str(offset) + '-'
                self._update(job_id, phase='downloading', current_file=item['filename'], done_bytes=base + offset)
                try:
                    with fetch(url, headers=headers, stream=True, timeout=(10, 15)) as response:
                        if response.status_code in (401, 403):
                            raise DownloadError('Hugging Face access is required. Open the model licence, accept its terms, then enter a Hugging Face read token and retry.', auth_required=True)
                        if response.status_code >= 400:
                            raise DownloadError('The model server could not provide this file. Check the connection and retry.')
                        if 'text/html' in response.headers.get('Content-Type', '').lower():
                            raise DownloadError('The model server returned a sign-in page. Accept the licence and retry with a Hugging Face read token.', auth_required=True)
                        if response.status_code == 206:
                            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                            if not match or tuple(map(int, match.groups())) != (offset, item['size_bytes'] - 1, item['size_bytes']):
                                raise DownloadError('The resumed download did not match the expected file. Retry the download.')
                        elif response.status_code == 200:
                            offset = 0  # Range ignored: replace the partial, never append.
                        else:
                            raise DownloadError('The model server returned an unsupported download response.')
                        length = response.headers.get('Content-Length')
                        if length is not None and (not length.isdigit() or int(length) != item['size_bytes'] - offset):
                            raise DownloadError('The download size does not match the published model.')
                        count = offset
                        self._update(job_id, done_bytes=base + count)
                        with temporary.open('ab' if offset else 'wb') as output:
                            for chunk in response.iter_content(chunk_size=1024 * 1024):
                                self._cancelled(job_id)
                                if not chunk:
                                    continue
                                count += len(chunk)
                                if count > item['size_bytes']:
                                    raise DownloadError('The download is larger than the published model.')
                                output.write(chunk)
                                self._update(job_id, done_bytes=base + count)
                    if count != item['size_bytes']:
                        raise requests.exceptions.ConnectionError('Interrupted model download')
                    break
                except requests.RequestException:
                    if attempt == 2:
                        raise DownloadError('The download was interrupted. Retry to resume the saved partial file.') from None
                    if self._jobs[job_id]['cancel'].wait(.5 * (attempt + 1)):
                        raise Cancelled()
            self._cancelled(job_id)
            self._update(job_id, phase='verifying')
            try:
                safetensors_header(temporary, item['size_bytes'])
                digest = hashlib.sha256()
                with temporary.open('rb') as source:
                    while chunk := source.read(1024 * 1024):
                        self._cancelled(job_id)
                        digest.update(chunk)
                if digest.hexdigest() != item['sha256']:
                    raise DownloadError('The model failed its integrity check. Retry to download a fresh copy.')
            except DownloadError:
                temporary.unlink(missing_ok=True)
                raise
            # A cancellation accepted before this lock cannot publish the model.
            with self._lock:
                self._cancelled(job_id)
                try:
                    _publish_verified(temporary, destination)
                except FileExistsError:
                    raise DownloadError('A model with this name was installed while downloading. Refresh the model list; the existing file was not overwritten.') from None
                temporary.unlink(missing_ok=True)
            self.on_installed()

    def _run(self, job_id, files, token):
        try:
            token = token or _cached_token()
            base = 0
            for item in files:
                self._cancelled(job_id)
                self._download(job_id, item, token, base)
                base += item['size_bytes']
            self._cancelled(job_id)
            self._update(job_id, phase='done', current_file='')
        except Cancelled:
            self._update(job_id, phase='cancelled', error='Download cancelled. Downloaded files are kept; retry resumes any partial file.')
        except Exception as error:
            if self._jobs[job_id]['cancel'].is_set():
                self._update(job_id, phase='cancelled', error='Download cancelled. Retry to resume.')
            else:
                self._update(job_id, phase='failed', error=str(error) if isinstance(error, DownloadError) else 'The download could not finish. Check the connection, free disk space and model folder, then retry.', auth_required=bool(isinstance(error, DownloadError) and error.auth_required))
        finally:
            token = None
            with self._lock:
                if self._active == job_id:
                    self._active = None


def _locations(folder_paths):
    locations, filenames = {}, {}
    for folder in {item['folder'] for recipe in CATALOG.values() for item in recipe['files']}:
        try:
            roots = list(folder_paths.get_folder_paths(folder))
        except KeyError:
            roots = []
        # Embeddings may not yet be registered when an extension is imported.
        if not roots and folder == 'embeddings' and getattr(folder_paths, 'models_dir', None):
            roots = [str(Path(folder_paths.models_dir) / 'embeddings')]
        locations[folder] = roots
        try:
            filenames[folder] = folder_paths.get_filename_list(folder)
        except (KeyError, OSError):
            filenames[folder] = []
    return locations, filenames


def register_routes():
    try:
        from server import PromptServer
    except ImportError:
        return
    server = getattr(PromptServer, 'instance', None)
    if server is None:
        return
    import asyncio
    import folder_paths
    from aiohttp import web
    from ..media_source import require_same_origin
    locations, names = _locations(folder_paths)
    def installed():
        cache = getattr(folder_paths, 'filename_list_cache', None)
        if isinstance(cache, dict):
            for category in locations:
                cache.pop(category, None)
    manager = DownloadManager(locations, on_installed=installed)
    manager.filenames = names

    async def catalogue(request):
        require_same_origin(request)
        manager.locations, manager.filenames = await asyncio.to_thread(_locations, folder_paths)
        return web.json_response(await asyncio.to_thread(manager.catalogue), headers={'Cache-Control': 'no-store'})

    async def start(request):
        require_same_origin(request)
        try:
            data = await request.json()
            if not isinstance(data, dict) or set(data) - {'model_id', 'model_ids', 'token'}:
                raise ValueError('Choose a model package from the download list.')
            manager.locations, manager.filenames = await asyncio.to_thread(_locations, folder_paths)
            identity = await asyncio.to_thread(manager.start, data.get('model_ids', data.get('model_id')), data.get('token'))
            return web.json_response({'id': identity}, headers={'Cache-Control': 'no-store'})
        except (ValueError, OSError) as error:
            # Controlled validation errors are safe, but filesystem errors may
            # contain local paths and must not be reflected into the browser.
            return web.json_response({'error': str(error) if isinstance(error, ValueError) else 'The model folder is unavailable. Check its permissions and retry.'}, status=400, headers={'Cache-Control': 'no-store'})

    async def status(request):
        require_same_origin(request)
        try:
            return web.json_response(manager.status(request.match_info['identity']), headers={'Cache-Control': 'no-store'})
        except ValueError as error:
            return web.json_response({'error': str(error)}, status=404)

    async def cancel(request):
        require_same_origin(request)
        try:
            manager.cancel(request.match_info['identity'])
            return web.json_response({'ok': True}, headers={'Cache-Control': 'no-store'})
        except ValueError as error:
            return web.json_response({'error': str(error)}, status=404)

    existing = {(route.method, route.path) for route in server.routes}
    base = '/zura/paintout/model-downloads'
    for method, path, handler in [('GET', base, catalogue), ('POST', base, start), ('GET', base + '/{identity}', status), ('POST', base + '/{identity}/cancel', cancel)]:
        if (method, path) not in existing:
            getattr(server.routes, method.lower())(path)(handler)
