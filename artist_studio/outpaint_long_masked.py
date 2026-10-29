"""Native masked LTX canvas-expansion window for the long-shot experiment."""
from __future__ import annotations

import re

from .ltx_outpaint import build_test_graph
from .outpaint_studio import FPS, plan


def build_masked_expand_graph(source, selection, *, review_key, prompt='', seed=42,
                              output_prefix, check_asset=lambda asset: None):
    """Inject the reviewed expansion mask before sampling, then restore audio.

    This graph is selected explicitly for anchored long canvas expansion. It
    does not replace the artist-approved black-guide short workflow.
    """
    if not isinstance(selection, dict) or selection.get('mode') != 'expand':
        raise ValueError('The anchored long workflow currently supports canvas expansion.')
    keys = ('start','duration','mode','width','height','left','top','right','bottom','black_threshold')
    expected = plan(source, **{key: selection[key] for key in keys})
    if not re.fullmatch(r'[a-f0-9]{64}', str(review_key)) or expected['review_key'] != review_key or selection.get('review_key') != review_key:
        raise ValueError('The source or canvas changed. Review the selection again.')
    if not re.fullmatch(r'genj/outpaint/[a-zA-Z0-9_-]{1,96}', str(output_prefix)):
        raise ValueError('Choose a safe outpaint output destination.')
    check_asset(source)
    g = build_test_graph(source['file'], output_prefix, expected['padded_frames'], FPS,
        expected['padded_width'], expected['padded_height'], mode='expand',
        left=expected['left'], top=expected['top'], right=expected['right'], bottom=expected['bottom'],
        prompt=prompt, seed=seed, black_threshold=expected['black_threshold'])
    g['source_range'] = {'class_type':'GenjSelectClip', 'inputs':{
        'video':['source',0], 'start_seconds':expected['start'],
        'duration_seconds':expected['duration'], 'long_edge':1920}}
    g['components']['inputs']['video'] = ['source_range',0]
    g['temporal_hold'] = {'class_type':'ZuraOutpaintTemporalHold', 'inputs':{
        'images':['components',0], 'audio':['components',1], 'expected_frames':expected['frames']}}
    g['canvas']['inputs']['images'] = ['temporal_hold',0]
    g['audio_encoded']['inputs']['audio'] = ['temporal_hold',1]
    g['trim_result'] = {'class_type':'ImageFromBatch', 'inputs':{
        'image':['blend_high',0], 'batch_index':0, 'length':expected['frames']}}
    g['assemble']['inputs'].update(images=['trim_result',0], audio=['components',1])
    return g
