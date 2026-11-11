"""Exact AE delivery contracts and narrowly typed native graph finalisation.

No contract means no copy and no changes. This module never alters model,
adapter, seed or precision settings, and never manufactures missing frames.
"""
from __future__ import annotations

import copy
import json
import re
from fractions import Fraction


def ltx_model_frames(count):
    if type(count) is not int or count < 1:
        raise ValueError('The AE frame count must be a positive integer.')
    return 1 + 8 * ((count - 1 + 7) // 8)


def normalise_frame_contract(value):
    if not isinstance(value, dict) or type(value.get('schemaVersion')) is not int or value.get('schemaVersion') != 1:
        raise ValueError('Choose a valid AE frame contract.')
    result = copy.deepcopy(value)
    for name in ('frameCount', 'width', 'height', 'modelFrames', 'trimFrames'):
        if type(value.get(name)) is not int or value[name] < 1:
            raise ValueError('The AE frame contract requires positive integer ' + name + '.')
    rate = value.get('frameRate')
    if not isinstance(rate, dict) or any(type(rate.get(k)) is not int or rate[k] < 1 for k in ('numerator', 'denominator')):
        raise ValueError('The AE frame rate must be an exact positive rational.')
    fps = Fraction(rate['numerator'], rate['denominator'])
    if not 1 <= fps <= 120:
        raise ValueError('This Studio route supports AE frame rates from 1 to 120 fps.')
    if value['trimFrames'] != value['frameCount'] or value['modelFrames'] < value['frameCount']:
        raise ValueError('AE delivery must retain the exact source frame count.')
    if not isinstance(value.get('sessionId'), str) or not re.fullmatch('[a-f0-9]{32}', value['sessionId']):
        raise ValueError('The AE frame contract needs its active session ID.')
    result['frameRate'] = {'numerator': fps.numerator, 'denominator': fps.denominator}
    return result


def contract_rate(contract):
    rate = contract['frameRate']
    return Fraction(rate['numerator'], rate['denominator'])


def validate_interval(contract, *, frames, fps, width=None, height=None):
    """Verify the actual prepared source interval, never a display label."""
    if contract is None:
        return None
    contract = normalise_frame_contract(contract)
    if frames != contract['frameCount'] or abs(float(fps) - float(contract_rate(contract))) > 1e-9:
        raise ValueError('The prepared clip must match all AE source frames at their original frame rate. Prepare the complete AE interval again.')
    if width is not None and height is not None and (width, height) != (contract['width'], contract['height']):
        raise ValueError('This mode changes the source raster and cannot return a strictly matching AE layer. Use the AE source dimensions.')
    return contract


def _link(value, graph):
    return isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], str) and value[0] in graph and type(value[1]) is int


def _ancestors(graph, roots):
    seen, pending = set(), list(roots)
    while pending:
        identity = pending.pop()
        if identity in seen:
            continue
        if identity not in graph:
            raise ValueError('The selected Studio output is missing.')
        seen.add(identity)
        pending.extend(value[0] for value in graph[identity].get('inputs', {}).values() if _link(value, graph))
    return seen


def _known_raster(graph, source):
    seen=set()
    while _link(source,graph) and source[0] not in seen:
        seen.add(source[0])
        node=graph[source[0]]
        kind,inputs=node.get('class_type'),node.get('inputs',{})
        if kind in ('ImageScale','ImageCrop','ZuraComfyLinkMatchFrames'):
            if all(type(inputs.get(side)) is int for side in ('width','height')):
                return inputs['width'],inputs['height']
            return None
        field={'GenjHoldToModelLength':'images','ImageFromBatch':'image',
               'GetImageRangeFromBatch':'images'}.get(kind)
        if field is None:
            return None
        source=inputs.get(field)
    return None


# Only real IMAGE-bearing saver interfaces belong here. Container encoders are
# traversed through VIDEO to CreateVideo rather than treating VIDEO as IMAGE.
IMAGE_SAVERS = {'SaveImage': 'images', 'PreviewImage': 'images',
    'VHS_VideoCombine': 'images', 'ZuraHDRPackageACEScct': 'images',
    'ZuraHDRPackage': 'images'}
NATIVE_SAVERS = {'ZuraPaintoutUncrop', 'ZuraAlphaVideoOutput'}
VIDEO_SAVERS = {'SaveVideo', 'ZuraHDRSaveExactRate', 'GenjRestoreSoundtrack', 'GenjRecordDraft'}


def apply_frame_contract(graph, contract, descriptor):
    """Apply a *trusted caller's* descriptor to its selected native saver paths.

    descriptor: output_nodes, family, optional max_model_frames and native_fps.
    Model inputs are handled by class-specific handlers, never fuzzy key names.
    """
    if contract is None:
        return graph
    contract = normalise_frame_contract(contract)
    if not isinstance(graph, dict) or not graph or not isinstance(descriptor, dict):
        raise ValueError('Choose a native Studio graph and supported delivery mode.')
    roots = descriptor.get('output_nodes')
    if not isinstance(roots, (list, tuple)) or not roots:
        raise ValueError('This Studio mode has no supported AE output branch.')
    reachable = _ancestors(graph, roots)
    fps = contract_rate(contract)
    native_fps = descriptor.get('native_fps')
    if native_fps is not None and Fraction(str(native_fps)) != fps:
        raise ValueError('This native model route requires ' + str(native_fps) + ' fps and cannot preserve this AE source cadence.')
    count = contract['frameCount']
    family = descriptor.get('family')
    model_frames = contract['modelFrames']
    if family == 'ltx' and (model_frames < ltx_model_frames(count) or (model_frames - 1) % 8):
        raise ValueError('The LTX model frame count must use its native 8n+1 time grid.')
    if family == 'wan' and ((model_frames - 1) % 4 or model_frames < 9):
        raise ValueError('The Wan model frame count must use its native 4n+1 time grid.')
    maximum = descriptor.get('max_model_frames')
    if maximum is not None and model_frames > maximum:
        raise ValueError(f'This native Studio mode supports at most {maximum} model frames. The complete {count}-frame AE interval needs a supported long workflow.')
    result = copy.deepcopy(graph)
    image_edges, create_nodes = [], set()
    video_pending = [root for root in roots if result[root].get('class_type') in VIDEO_SAVERS]
    output_encoders, video_seen = set(), set()
    while video_pending:
        identity = video_pending.pop()
        if identity in video_seen:
            continue
        video_seen.add(identity)
        node = result[identity]
        if node.get('class_type') in ('CreateVideo', 'ZuraOutpaintExactVideo'):
            output_encoders.add(identity)
            continue
        value = node.get('inputs', {}).get('video')
        if _link(value, result):
            video_pending.append(value[0])
    for identity in reachable:
        node = result[identity]
        kind, inputs = node.get('class_type'), node.get('inputs', {})
        if identity in output_encoders:
            create_nodes.add(identity)
            image_edges.append((identity, 'images'))
        elif identity in roots and kind in IMAGE_SAVERS:
            image_edges.append((identity, IMAGE_SAVERS[kind]))
        elif identity in roots and kind in NATIVE_SAVERS:
            inputs['ae_frame_contract'] = json.dumps(contract, sort_keys=True, separators=(',', ':'))
        elif identity in roots and kind not in VIDEO_SAVERS:
            raise ValueError('This Studio output does not expose a supported native AE frame delivery path.')
        # Explicit native model handlers. Linked lengths already come from the
        # source-aware native preparation node and must retain that bookkeeping.
        if family == 'ltx' and kind == 'EmptyLTXVLatentVideo' and not _link(inputs.get('length'), result):
            inputs['length'] = model_frames
        elif family == 'ltx' and kind == 'LTXVEmptyLatentAudio' and not _link(inputs.get('frames_number'), result):
            inputs['frames_number'] = model_frames
        elif family == 'wan' and kind in ('WanFirstLastFrameToVideo', 'WanImageToVideo') and not _link(inputs.get('length'), result):
            inputs['length'] = model_frames
        elif descriptor.get('authored_h3') and kind in ('MiniMaxH3ImageToVideo', 'MiniMaxH3ReferenceToVideo', 'EmptyMiniMaxH3LatentAV') and not _link(inputs.get('length'), result):
            inputs['length'] = model_frames
        elif kind in ('LTXDirector', 'MiniMaxH3DirectorCS'):
            start = inputs.get('start_frame', 0)
            rate = inputs.get('frame_rate', 24)
            if type(start) is not int or not isinstance(rate, (int, float)) or rate <= 0:
                raise ValueError('The authored Director timing is invalid.')
            inputs.update(duration_frames=model_frames, end_frame=start+model_frames,
                duration_seconds=model_frames/rate, end_second=(start+model_frames)/rate)
        if kind == 'GenjRestoreSoundtrack':
            # Its native exporter otherwise intentionally restores padded length.
            inputs['target_frames'], inputs['model_stride'] = count, 0
            inputs['ae_frame_contract'] = json.dumps(contract, sort_keys=True, separators=(',', ':'))
    if not image_edges and not any(result[key].get('class_type') in NATIVE_SAVERS | {'GenjRestoreSoundtrack'} for key in roots):
        raise ValueError('This Studio output has no reachable decoded image batch. Exact AE delivery is unsupported.')
    for index, (identity, field) in enumerate(sorted(set(image_edges))):
        inputs = result[identity]['inputs']
        source = inputs.get(field)
        if not _link(source, result):
            raise ValueError('The selected native saver has no decoded frame source.')
        raster=_known_raster(result,source)
        if raster is not None and raster != (contract['width'],contract['height']):
            raise ValueError('This native output raster differs from the AE source. Use the source dimensions before generating.')
        name = 'zura_ae_match_frames_' + str(index)
        while name in result:
            name += '_'
        result[name] = {'class_type': 'ZuraComfyLinkMatchFrames', 'inputs': {
            'images': source, 'frame_count': count, 'width': contract['width'],
            'height': contract['height'], 'metadata': json.dumps(contract, sort_keys=True, separators=(',', ':'))}}
        inputs[field] = [name, 0]
        if result[identity]['class_type'] == 'VHS_VideoCombine':
            inputs['frame_rate'] = float(fps)
        if identity in create_nodes and result[identity]['class_type'] == 'CreateVideo':
            inputs['fps'] = float(fps)
        elif identity in create_nodes:
            inputs['fps_num'], inputs['fps_den'] = fps.numerator, fps.denominator
        if 'audio' in inputs and _link(inputs['audio'], result):
            audio_name = name + '_audio'
            result[audio_name] = {'class_type': 'TrimAudioDuration', 'inputs': {
                'audio': inputs['audio'], 'start_index': 0.0, 'duration': float(count / fps)}}
            inputs['audio'] = [audio_name, 0]
    for identity in roots:
        if result[identity].get('class_type') == 'ZuraHDRSaveExactRate':
            result[identity]['inputs']['fps'] = float(fps)
    return result


def prepare_frame_contract_graph(graph, contract, mode, *, output_nodes=None):
    """Server-owned mode policy for the scoped bridge preparation endpoint."""
    if contract is None:
        return graph
    modes = {'image', 'frames', 'references', 'director', 'alpha', 'ripple',
        'relight', 'paintout', 'watermark', 'hdr', 'outpaint',
        'camera', 'viewport', 'swap'}
    if mode not in modes:
        raise ValueError('Choose a supported AE Studio mode.')
    # These IDs are the native Studio builders' delivery interfaces. Do not
    # touch SaveImage reference/cache branches that happen to share the graph.
    canonical_roots = ('save', 'save_video', 'save_preview', 'h3_export', 'h3_enhance_export', 'wan_export', 'wan2_export', 'wan21_export', 'export', 'final',
        'zura_hdr_archive', 'zura_hdr_save_preview', 'zura_hdr_save',
        'zura_hdr_save_video', 'save_alpha', 'save_matte', 'save_sequence')
    roots = output_nodes or [key for key in canonical_roots if key in graph and
        graph[key].get('class_type') in set(IMAGE_SAVERS) | VIDEO_SAVERS | NATIVE_SAVERS]
    kinds = {node.get('class_type') for node in graph.values()}
    family = 'ltx' if kinds & {'EmptyLTXVLatentVideo', 'LTXDirector'} else 'wan' if kinds & {'WanFirstLastFrameToVideo', 'WanImageToVideo'} else 'native'
    descriptor = {'family': family, 'output_nodes': roots}
    if kinds & {'EmptyMiniMaxH3LatentAV', 'MiniMaxH3ImageToVideo', 'MiniMaxH3ReferenceToVideo', 'MiniMaxH3DirectorCS'}:
        descriptor['native_fps'] = 24
        descriptor['authored_h3']=mode in ('frames','references','director')
        checked=normalise_frame_contract(contract)
        if mode in ('frames','references','director') and ((checked['modelFrames']-5)%17 or not 5<=checked['modelFrames']<=362):
            raise ValueError('The authored H3 model frame count must use its native 17n+5 time grid, up to 362 frames.')
    # Existing short source-preparation nodes own their documented hard bounds.
    if mode in ('frames', 'director') and family == 'ltx':
        descriptor['max_model_frames'] = 361
    return apply_frame_contract(graph, contract, descriptor)
