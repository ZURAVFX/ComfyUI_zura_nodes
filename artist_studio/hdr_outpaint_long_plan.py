"""Bounded planning for a future anchored HDR frame-extension workflow.

Planning does not expose the route or establish visual continuity. Both native
source decoding and the padded output canvas must fit the HDR frame budget.
"""
import hashlib
import json
import math

from .hdr_source import MAX_PIXEL_FRAMES
from .hdr_chunks import MAX_TOTAL_FRAMES
from .outpaint_chunks import FPS, MAX_WINDOWS, Window
from .outpaint_studio import plan


def plan_hdr_windows(source, *, start, duration, width, height, left, top, right, bottom,
                     colour_space='auto', overlap=9, mode='expand', black_threshold=2/255):
    if not isinstance(source, dict) or source.get('asset_kind') != 'video' or not source.get('sha'):
        raise ValueError('Choose an HDR video source.')
    if colour_space not in ('auto', 'pq_rec2020', 'hlg_rec2020'):
        raise ValueError('Choose a supported HDR video colour space.')
    if (isinstance(start, bool) or isinstance(duration, bool) or
            not isinstance(start, (int, float)) or not isinstance(duration, (int, float)) or
            not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0):
        raise ValueError('Choose a valid source range.')
    total = math.ceil(duration * FPS - 1e-6)
    available = source.get('duration')
    if (not isinstance(available, (int, float)) or not math.isfinite(available) or
            total < 3 or total > MAX_TOTAL_FRAMES or start + duration > available + 1e-4):
        raise ValueError('Choose a valid range within the HDR source.')
    sw, sh = source.get('width'), source.get('height')
    if any(type(v) is not int or v < 1 for v in (sw, sh, width, height)):
        raise ValueError('Choose valid source and canvas dimensions.')
    if type(overlap) is not int or overlap < 2:
        raise ValueError('Choose a valid blended overlap.')
    pw, ph = (width + 63)//64*64, (height + 63)//64*64
    # The existing HDR chunk writer reconstructs its plan with a minimum
    # 512-pixel padded canvas on each side. Match that bound exactly.
    canvas_budget = MAX_PIXEL_FRAMES // (max(512, pw) * max(512, ph))
    padded_capacity = min(113, 1 + 8 * ((canvas_budget - 1) // 8))
    source_budget = MAX_PIXEL_FRAMES // (sw * sh)
    source_capacity = 1 + 8 * ((source_budget - 1)//8)
    capacity = min(padded_capacity, source_capacity, 113)
    if capacity < 9:
        raise ValueError('This source and canvas exceed the HDR memory budget. Select a smaller source.')
    overlap = min(overlap, (capacity - 1)//2)
    number = 1 + max(0, math.ceil((total - capacity)/(capacity - overlap)))
    if number > MAX_WINDOWS:
        raise ValueError('This selection needs too many HDR sections. Trim the clip.')
    parts = [Window(0, min(total, capacity), 0)]
    while parts[-1].start + parts[-1].count < total:
        next_start = parts[-1].start + parts[-1].count - overlap
        parts.append(Window(next_start, min(capacity, total-next_start), overlap))
    subplans = [plan(source, start=start + part.start/FPS, duration=part.count/FPS,
                     mode=mode, width=width, height=height, left=left, top=top,
                     right=right, bottom=bottom, black_threshold=black_threshold,
                     allow_partial_end=True) for part in parts]
    values = {'source_sha':source['sha'], 'start':float(start), 'frames':total, 'requested_duration':float(duration), 'width':width,
              'height':height, 'left':left, 'top':top, 'right':right, 'bottom':bottom,
              'colour_space':colour_space, 'overlap':overlap, 'capacity':capacity}
    # Preserve older expanded-shot approvals at the default threshold. New
    # black masks and non-default thresholds are bound to their own review.
    if mode != 'expand' or black_threshold != 2/255:
        values.update(mode=mode, black_threshold=float(black_threshold))
    key = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {**values, 'mode':mode, 'black_threshold':float(black_threshold),
            'duration':total/FPS, 'review_key':key}, parts, subplans


def long_plan_values(selection):
    """Resolve old expanded reviews and explicitly bound new black selections."""
    fields = ('start','width','height','left','top','right','bottom','colour_space','overlap')
    if not isinstance(selection,dict) or any(key not in selection for key in (*fields,'requested_duration')):
        raise ValueError('Review the full HDR selection first.')
    return {**{key:selection[key] for key in fields}, 'mode':selection.get('mode','expand'),
            'black_threshold':selection.get('black_threshold',2/255)}


def build_long_hdr_sdr_window(source, full_selection, sub_selection, *, review_key,
                              anchor_file=None, prompt='', seed=42,
                              prefix='genj/hdr_outpaint/long_window', check_asset=lambda asset: None):
    """Build one bounded SDR guide with the exact approved HDR source time.

    The optional anchor must represent this window's first source timestamp.
    The caller owns extraction, blending and validation of the full result.
    """
    from .hdr_outpaint_experiment import build_reviewed_sdr_first_stage, hdr_review_key
    from .outpaint_anchor import attach_first_frame
    values = long_plan_values(full_selection)
    expected, _, subplans = plan_hdr_windows(source, duration=full_selection['requested_duration'], **values)
    if review_key != expected['review_key'] or full_selection.get('review_key') != expected['review_key']:
        raise ValueError('The full HDR selection changed. Review it again.')
    if not isinstance(sub_selection, dict) or not any(sub == sub_selection for sub in subplans):
        raise ValueError('This section does not belong to the reviewed HDR selection.')
    graph = build_reviewed_sdr_first_stage(source, sub_selection,
        review_key=hdr_review_key(sub_selection, expected['colour_space']), colour_space=expected['colour_space'],
        prompt=prompt, seed=seed, prefix=prefix, check_asset=check_asset)
    # Inference holds the source to 8n+1; the assembler needs exact overlap
    # lengths and adds the final delivery hold only after the joins are blended.
    graph['trim_result']['inputs']['length'] = sub_selection['frames']
    if expected['mode'] == 'black':
        graph['stage_unpad'] = {'class_type':'ImageCrop','inputs':{
            'image':['trim_result',0], 'width':expected['width'], 'height':expected['height'], 'x':0, 'y':0}}
        graph['stage_video']['inputs']['images'] = ['stage_unpad',0]
    if anchor_file is not None:
        graph = attach_first_frame(graph, anchor_file)
        if expected['mode'] == 'black':
            # The prior section's deliverable is cropped to the real source
            # raster. Restore only its right/bottom model-grid padding before
            # I2V; resizing that frame would deform every continuation anchor.
            graph['zura_anchor_canvas'] = {'class_type':'EmptyImage','inputs':{
                'width':sub_selection['padded_width'], 'height':sub_selection['padded_height'],
                'batch_size':1, 'color':0}}
            graph['zura_anchor_pad'] = {'class_type':'ImageCompositeMasked','inputs':{
                'destination':['zura_anchor_canvas',0], 'source':['zura_anchor_image',0],
                'x':0, 'y':0, 'resize_source':False}}
            graph['zura_anchor_i2v']['inputs']['image'] = ['zura_anchor_pad',0]
    return graph


def build_long_hdr_review_window(source, full_selection, sub_selection, *, review_key,
                                 prefix='genj/hdr_outpaint/long_review', check_asset=lambda asset: None):
    """Build one preview section tied to the same full-range approval."""
    from .hdr_outpaint_experiment import build_hdr_review_experiment
    values=long_plan_values(full_selection)
    expected,_,subplans=plan_hdr_windows(source,duration=full_selection['requested_duration'], **values)
    if review_key!=expected['review_key'] or full_selection.get('review_key')!=expected['review_key']:
        raise ValueError('The full HDR selection changed. Review it again.')
    if not isinstance(sub_selection,dict) or not any(sub==sub_selection for sub in subplans):
        raise ValueError('This section does not belong to the reviewed HDR selection.')
    graph,_=build_hdr_review_experiment(source,sub_selection,colour_space=expected['colour_space'],
                                         prefix=prefix,check_asset=check_asset)
    return graph


def build_long_hdr_conversion_window(source, full_selection, sub_selection, intermediate, *, review_key,
                                     prompt_start_frame, seed=42, prefix='hdr_outpaint_long',
                                     check_asset=lambda asset: None):
    """Convert one assembled SDR range and restore its native HDR centre.

    The range starts at an output-relative frame. A separate chunk coordinator
    stages and blends the resulting ACEScct frames before final export.
    """
    from .hdr_studio import build_hdr_graph
    from .hdr_outpaint_experiment import _reviewed_sdr_first_selection, hdr_review_key
    values=long_plan_values(full_selection)
    expected, parts, subplans = plan_hdr_windows(source, duration=full_selection['requested_duration'], **values)
    if review_key != expected['review_key'] or full_selection.get('review_key') != expected['review_key']:
        raise ValueError('The full HDR selection changed. Review it again.')
    if type(prompt_start_frame) is not int or not isinstance(sub_selection, dict):
        raise ValueError('Choose a valid HDR section.')
    index = next((i for i, sub in enumerate(subplans) if sub == sub_selection), None)
    if index is None or parts[index].start != prompt_start_frame:
        raise ValueError('This section does not belong to the reviewed HDR selection.')
    validated, path = _reviewed_sdr_first_selection(source, sub_selection,
        hdr_review_key(sub_selection, expected['colour_space']), expected['colour_space'], check_asset)
    graph = build_hdr_graph(source=intermediate, start_frame=prompt_start_frame,
        frame_count=validated['frames'], fps=24., colour_space='srgb_display',
        output='hlg_and_exr', prefix=prefix, has_audio=False, seed=seed)
    graph['native_original'] = {'class_type':'ZuraHDRSelectNativeTimeline','inputs':{
        'source':path, 'start_seconds':validated['start'], 'frame_count':validated['frames'],
        'output_fps':24., 'colour_space':expected['colour_space'], 'sequence_fps':24.}}
    graph['native_canvas'] = {'class_type':'ZuraLTXOutpaintHDRCanvas','inputs':{
        'images':['native_original',0], 'mode':validated['mode'], 'width':validated['padded_width'],
        'height':validated['padded_height'], 'left':validated['left'], 'top':validated['top'],
        'right':validated['right'], 'bottom':validated['bottom'], 'black_threshold':validated['black_threshold']}}
    graph['final_hdr_composite'] = {'class_type':'ZuraHDRCompositeOutpaint','inputs':{
        'generated':['hdr_unpad_raster',0], 'source':['native_canvas',0], 'mask':['native_canvas',1],
        'feather':16, 'colour_match':1.0}}
    if validated['mode'] == 'black':
        from .hdr_outpaint_experiment import crop_black_hdr_composite
        crop_black_hdr_composite(graph, validated['width'], validated['height'])
    return graph
