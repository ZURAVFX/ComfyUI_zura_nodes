"""Unqualified HDR outpainting experiment. Not exposed through Studio.

The outpaint adapter is not known to be HDR-trained. The default graph saves
only an SDR viewing proxy. Explicit internal options also save an EXR archive
or HLG video for colour evaluation, labelled as unverified.
"""
import hashlib
import math
import re

from .ltx_outpaint import build_test_graph
from .outpaint_studio import plan, build_studio_graph


def build_experimental_graph(source, *, start_frame, frame_count, fps, width, height,
                             mode, left=0, top=0, right=0, bottom=0,
                             colour_space='auto', has_audio=False, prompt='', seed=42,
                             prefix='genj/hdr_outpaint/experiment', unverified_exr=False,
                             unverified_hlg=False):
    if not isinstance(source, str) or not source.strip():
        raise ValueError('Choose an HDR video source.')
    if type(start_frame) is not int or start_frame < 0:
        raise ValueError('Choose a valid starting frame.')
    if type(frame_count) is not int or frame_count < 9 or frame_count > 121 or (frame_count - 1) % 8:
        raise ValueError('The experiment uses 9–121 frames in 8n+1 increments.')
    if colour_space not in ('auto', 'hlg_rec2020', 'pq_rec2020'):
        raise ValueError('Choose HLG or PQ video colour.')
    if type(has_audio) is not bool:
        raise ValueError('Audio selection must be explicit.')
    if type(unverified_exr) is not bool:
        raise ValueError('Experimental EXR evaluation must be explicitly selected.')
    if type(unverified_hlg) is not bool:
        raise ValueError('Experimental HLG evaluation must be explicitly selected.')
    if not re.fullmatch(r'genj/hdr_outpaint/[a-zA-Z0-9_-]{1,64}', prefix):
        raise ValueError('Choose a safe experiment output name.')
    g = build_test_graph(source, prefix, frame_count, fps, width, height, mode=mode,
                         left=left, top=top, right=right, bottom=bottom,
                         prompt=prompt, seed=seed)
    for name in ('source', 'components', 'assemble', 'save'):
        del g[name]
    # Use the full VAE used by the tested native HDR path; the SDR prototype's
    # conv-specific filename is not necessarily installed with that workflow.
    g['video_vae']['inputs']['vae_name'] = 'ltx-2.5-video-vae-bf16.safetensors'
    def node(kind, **inputs): return {'class_type': kind, 'inputs': inputs}
    g['hdr_source'] = node('ZuraHDRLoadNativeSource', source=source, start_frame=start_frame,
                           frame_count=frame_count, colour_space=colour_space, sequence_fps=float(fps))
    # For video the HDR loader reports the real source rate; keep conditioning,
    # audio selection and the preview clock tied to that same rate.
    source_fps = ['hdr_source', 1]
    g['conditioning']['inputs']['frame_rate'] = source_fps
    g['canvas']['class_type'] = 'ZuraLTXOutpaintHDRCanvas'
    g['canvas']['inputs']['images'] = ['hdr_source', 0]
    g['hdr_vae'] = node('LTXVVAEForceFloat32', vae=['video_vae', 0])
    for name, value in g.items():
        if name == 'hdr_vae':
            continue
        for key, link in value['inputs'].items():
            if link == ['video_vae', 0]:
                value['inputs'][key] = ['hdr_vae', 0]
    if has_audio:
        g['hdr_audio'] = node('ZuraHDRLoadAudioRange', source=source, start_frame=start_frame,
                              frame_count=frame_count, fps=source_fps)
        g['audio_encoded']['inputs']['audio'] = ['hdr_audio', 0]
    else:
        g['audio_encoded'] = node('LTXVEmptyLatentAudio', audio_vae=['audio_vae', 0],
                                  frames_number=frame_count, frame_rate=source_fps, batch_size=1)
    g['hdr_composite'] = node('ZuraHDRCompositeOutpaint', generated=['blend_high', 0], source=['canvas', 0],
                              mask=['canvas', 1], feather=16)
    g['hdr_preview'] = node('LTXVHDRDecodePostprocess', image=['hdr_composite', 0], transfer='acescct',
                            save_exr=False, exr_color_space='acescg', output_dir=prefix,
                            filename_prefix='preview', half_precision=True)
    preview = {'images': ['hdr_preview', 0], 'fps': source_fps}
    if has_audio:
        preview['audio'] = ['hdr_audio', 0]
    g['hdr_preview_video'] = node('CreateVideo', **preview)
    g['hdr_preview_save'] = node('ZuraHDRSaveExactRate', video=['hdr_preview_video', 0],
                                 filename_prefix=prefix + '_sdr_preview', fps=source_fps)
    if unverified_exr:
        g['hdr_experiment_exr'] = node('ZuraHDRPackageACEScct', images=['hdr_composite', 0],
                                       prefix='unverified_outpaint_' + prefix.rsplit('/', 1)[-1])
    if unverified_hlg:
        g['hdr_experiment_hlg'] = node('ImageColorSpace', image=['hdr_composite', 0],
                                       source='HDR ACEScct', destination='HDR')
        hlg_video = {'images': ['hdr_experiment_hlg', 0], 'fps': source_fps,
                     'bit_depth': 10, 'color_space': 'HDR', 'codec': 'none'}
        if has_audio:
            hlg_video['audio'] = ['hdr_audio', 0]
        g['hdr_experiment_video'] = node('CreateVideo', **hlg_video)
        g['hdr_experiment_save'] = node('ZuraHDRSaveExactRate', video=['hdr_experiment_video', 0],
                                        filename_prefix=prefix + '_unverified_hlg', fps=source_fps)
    return g


def build_black_guide_experiment(source, *, start_frame, frame_count, width, height,
                                 left=0, top=0, right=0, bottom=0,
                                 colour_space='auto', prompt='', seed=42,
                                 prefix='genj/hdr_outpaint/black_guide'):
    """Evaluate the approved SDR black-video guide using native HDR frames.

    This experimental short, silent 24-fps graph only produces an SDR viewing
    proxy and an unverified ACEScg archive. It is not a Studio delivery path.
    """
    if type(start_frame) is not int or start_frame < 0:
        raise ValueError('Choose a valid starting frame.')
    if type(frame_count) is not int or frame_count < 9 or frame_count > 113 or (frame_count - 1) % 8:
        raise ValueError('Choose 9–113 frames in 8n+1 increments.')
    if not isinstance(source, str) or not source.strip():
        raise ValueError('Choose an HDR source.')
    if colour_space not in ('auto', 'hlg_rec2020', 'pq_rec2020'):
        raise ValueError('Choose HLG or PQ video colour.')
    if not re.fullmatch(r'genj/hdr_outpaint/[a-zA-Z0-9_-]{1,64}', prefix):
        raise ValueError('Choose a safe experiment output name.')
    # The source is already bounded by the experimental HDR loader. The
    # synthetic source metadata only constructs the same reviewed SDR recipe.
    asset = {'sha': 'experiment', 'file': source, 'duration': frame_count / 24,
             'width': width-left-right, 'height': height-top-bottom}
    selection = plan(asset, start=0, duration=frame_count / 24, mode='expand',
                     width=width, height=height, left=left, top=top,
                     right=right, bottom=bottom)
    g = build_studio_graph(asset, selection, review_key=selection['review_key'],
                           prompt=prompt, seed=seed, output_prefix='genj/outpaint/hdr_experiment')
    for key in ('source', 'source_range', 'components', 'temporal_hold', 'assemble', 'save'):
        del g[key]
    def node(kind, **inputs): return {'class_type': kind, 'inputs': inputs}
    g['hdr_source'] = node('ZuraHDRLoadNativeSource', source=source, start_frame=start_frame,
                           frame_count=frame_count, colour_space=colour_space, sequence_fps=24.0)
    g['canvas']['class_type'] = 'ZuraLTXOutpaintHDRCanvas'
    g['canvas']['inputs']['images'] = ['hdr_source', 0]
    g['video_vae']['inputs']['vae_name'] = 'ltx-2.5-video-vae-bf16.safetensors'
    g['hdr_vae'] = node('LTXVVAEForceFloat32', vae=['video_vae', 0])
    for name, value in g.items():
        if name != 'hdr_vae':
            for key, link in value['inputs'].items():
                if link == ['video_vae', 0]: value['inputs'][key] = ['hdr_vae', 0]
    fps = ['hdr_source', 1]
    g['conditioning']['inputs']['frame_rate'] = fps
    g['audio_empty']['inputs']['frame_rate'] = fps
    g['hdr_preview'] = node('LTXVHDRDecodePostprocess', image=['trim_result', 0], transfer='acescct',
                            save_exr=False, exr_color_space='acescg', output_dir=prefix,
                            filename_prefix='preview', half_precision=True)
    g['hdr_preview_video'] = node('CreateVideo', images=['hdr_preview', 0], fps=fps)
    g['hdr_preview_save'] = node('ZuraHDRSaveExactRate', video=['hdr_preview_video', 0],
                                 filename_prefix=prefix+'_sdr_preview', fps=fps)
    g['hdr_experiment_exr'] = node('ZuraHDRPackageACEScct', images=['trim_result', 0],
                                   prefix='unverified_outpaint_'+prefix.rsplit('/', 1)[-1])
    return g


def _selected_start_seconds(start_frame, source_fps, start_seconds):
    if type(start_frame) is not int or start_frame < 0:
        raise ValueError('Choose a valid starting frame.')
    if isinstance(source_fps, bool) or not isinstance(source_fps, (int, float)) or not math.isfinite(source_fps) or not 1 <= source_fps <= 120:
        raise ValueError('Choose a valid source frame rate.')
    if start_seconds is None:
        return start_frame / source_fps
    if isinstance(start_seconds, bool) or not isinstance(start_seconds, (int, float)) or not math.isfinite(start_seconds) or start_seconds < 0:
        raise ValueError('Choose a valid source start time.')
    return float(start_seconds)


def build_sdr_first_stage(source, *, start_frame, frame_count, width, height,
                          left=0, top=0, right=0, bottom=0, colour_space='auto',
                          prompt='', seed=42, prefix='genj/hdr_outpaint/sdr_first', source_fps=24., start_seconds=None):
    """Internal HDR-to-SDR guide experiment; produces no HDR claim by itself.

    Preserve the original native source separately for the later composite.
    This model-generated SDR border cannot recover lost source highlights.
    """
    selected_start = _selected_start_seconds(start_frame, source_fps, start_seconds)
    graph = build_black_guide_experiment(source, start_frame=start_frame, frame_count=frame_count,
        width=width, height=height, left=left, top=top, right=right, bottom=bottom,
        colour_space=colour_space, prompt=prompt, seed=seed, prefix=prefix)
    graph['hdr_source'] = {'class_type': 'ZuraHDRSelectNativeTimeline', 'inputs': {
        'source': source, 'start_seconds': selected_start, 'frame_count': frame_count,
        'output_fps': 24., 'colour_space': colour_space, 'sequence_fps': 24.}}
    for key in ('hdr_vae', 'hdr_preview', 'hdr_preview_video', 'hdr_preview_save', 'hdr_experiment_exr'):
        graph.pop(key, None)
    graph['video_vae']['inputs']['vae_name'] = 'ltx-2.5-video-vae-conv-bf16.safetensors'
    for node in graph.values():
        for field, value in node['inputs'].items():
            if value == ['hdr_vae', 0]:
                node['inputs'][field] = ['video_vae', 0]
    graph['tone_map_source'] = {'class_type': 'LTXVHDRDecodePostprocess', 'inputs': {
        'image': ['hdr_source', 0], 'transfer': 'acescct', 'save_exr': False,
        'exr_color_space': 'acescg', 'output_dir': prefix, 'filename_prefix': 'source',
        'half_precision': True}}
    graph['canvas']['class_type'] = 'ZuraLTXOutpaintCanvas'
    graph['canvas']['inputs']['images'] = ['tone_map_source', 0]
    graph['stage_video'] = {'class_type': 'CreateVideo', 'inputs': {
        'images': ['trim_result', 0], 'fps': ['hdr_source', 1]}}
    graph['stage_save'] = {'class_type': 'SaveVideo', 'inputs': {
        'video': ['stage_video', 0], 'filename_prefix': prefix, 'format': 'mp4', 'format.codec': 'h264'}}
    return graph


def build_sdr_first_hdr_composite(source, intermediate, *, start_frame, frame_count, width, height,
                                  left=0, top=0, right=0, bottom=0, colour_space='auto',
                                  prefix='sdr_first_composite', seed=42, feather=16, source_fps=24., has_audio=False,
                                  start_seconds=None, mode='expand', black_threshold=2/255):
    """Internal two-stage test, not yet a Studio route or a quality claim."""
    if colour_space not in ('auto', 'hlg_rec2020', 'pq_rec2020'):
        raise ValueError('Choose a supported HDR video colour space.')
    if type(feather) is not int or not 0 <= feather <= 128:
        raise ValueError('Choose a valid HDR composite feather.')
    selected_start = _selected_start_seconds(start_frame, source_fps, start_seconds)
    if type(has_audio) is not bool:
        raise ValueError('Audio selection must be explicit.')
    if mode not in ('expand', 'black'):
        raise ValueError('Choose canvas expansion or black areas.')
    if (isinstance(black_threshold, bool) or not isinstance(black_threshold, (int,float)) or
            not math.isfinite(black_threshold) or not 0 <= black_threshold <= .1):
        raise ValueError('Black threshold must be between 0 and 0.1.')
    # Reuse the validated native-canvas builder to check dimensions, length and
    # paths against the same constraints as the actual outpaint stage.
    checked = build_black_guide_experiment(source, start_frame=start_frame, frame_count=frame_count,
        width=width, height=height, left=left, top=top, right=right, bottom=bottom,
        colour_space=colour_space, prefix='genj/hdr_outpaint/composite_setup')
    from .hdr_studio import build_hdr_graph
    graph = build_hdr_graph(source=intermediate, start_frame=0, frame_count=frame_count, fps=24.,
        colour_space='srgb_display', output='hlg_and_exr', prefix=prefix, has_audio=False, seed=seed)
    graph['native_original'] = {'class_type': 'ZuraHDRSelectNativeTimeline', 'inputs': {
        'source': source, 'start_seconds': selected_start, 'frame_count': frame_count,
        'output_fps': 24., 'colour_space': colour_space, 'sequence_fps': 24.}}
    graph['native_canvas'] = checked['canvas']
    graph['native_canvas']['inputs']['images'] = ['native_original', 0]
    if mode == 'black':
        graph['native_canvas']['inputs'].update(mode='black', black_threshold=float(black_threshold))
    graph['final_hdr_composite'] = {'class_type': 'ZuraHDRCompositeOutpaint', 'inputs': {
        'generated': ['hdr_unpad_raster', 0], 'source': ['native_canvas', 0],
        'mask': ['native_canvas', 1], 'feather': feather, 'colour_match': 1.0}}
    if has_audio:
        graph['original_audio'] = {'class_type': 'ZuraHDRLoadTimedAudio', 'inputs': {
            'source': source, 'start_seconds': selected_start, 'frame_count': frame_count,
            'fps': 24., 'allow_tail_hold': True}}
        graph['zura_hdr_video']['inputs']['audio'] = ['original_audio', 0]
        graph['zura_hdr_preview_video']['inputs']['audio'] = ['original_audio', 0]
    for key, node in graph.items():
        if key == 'final_hdr_composite':
            continue
        for field, value in node['inputs'].items():
            if value == ['hdr_unpad_raster', 0]:
                node['inputs'][field] = ['final_hdr_composite', 0]
    return graph


def hdr_review_key(selection, colour_space, sequence_fps=24):
    if not isinstance(selection, dict) or not re.fullmatch(r'[a-f0-9]{64}', str(selection.get('review_key', ''))):
        raise ValueError('Create an outpaint selection first.')
    if colour_space not in ('auto', 'hlg_rec2020', 'pq_rec2020', 'acescg', 'acescct', 'linear_rec709'):
        raise ValueError('Choose a supported HDR colour space.')
    if isinstance(sequence_fps, bool) or not isinstance(sequence_fps, (int, float)) or not math.isfinite(sequence_fps) or not 1 <= sequence_fps <= 120:
        raise ValueError('Choose an EXR sequence frame rate between 1 and 120 fps.')
    return hashlib.sha256(('hdr-review-v2|' + selection['review_key'] + '|' + colour_space + '|' + str(float(sequence_fps))).encode()).hexdigest()


def validate_hdr_selection(source, selection, colour_space, sequence_fps, check_asset):
    if not isinstance(selection, dict):
        raise ValueError('Create an outpaint selection first.')
    expected = plan(source, start=selection['start'], duration=selection.get('requested_duration', selection['duration']), mode=selection['mode'],
                    width=selection['width'], height=selection['height'], left=selection['left'],
                    top=selection['top'], right=selection['right'], bottom=selection['bottom'],
                    black_threshold=selection['black_threshold'], allow_partial_end=True)
    if expected['review_key'] != selection.get('review_key'):
        raise ValueError('The source or canvas changed. Review the selection again.')
    from .hdr_source import MAX_PIXEL_FRAMES
    if expected['padded_width'] * expected['padded_height'] * expected['padded_frames'] > MAX_PIXEL_FRAMES:
        raise ValueError('The padded HDR canvas exceeds the experimental memory budget. Select fewer frames or a smaller canvas.')
    source_width, source_height = source.get('width'), source.get('height')
    if (type(source_width) is not int or type(source_height) is not int or
            source_width < 1 or source_height < 1):
        raise ValueError('The HDR source dimensions are unavailable. Reload the source.')
    if source_width * source_height * expected['padded_frames'] > MAX_PIXEL_FRAMES:
        raise ValueError('The padded HDR source selection exceeds the experimental memory budget. Select fewer frames.')
    is_sequence = source.get('asset_kind') == 'hdr_sequence'
    allowed = ('auto', 'acescg', 'acescct', 'linear_rec709') if is_sequence else ('auto', 'hlg_rec2020', 'pq_rec2020')
    if colour_space not in allowed:
        raise ValueError('Choose a supported colour space for this HDR source.')
    path = check_asset(source) or source['file']
    return expected, hdr_review_key(expected, colour_space, sequence_fps if is_sequence else 24), str(path)


def _reviewed_sdr_first_selection(source, selection, review_key, colour_space, check_asset):
    expected, approved, path = validate_hdr_selection(source, selection, colour_space, 24, check_asset)
    if review_key != approved:
        raise ValueError('Review and approve the current HDR outpaint selection first.')
    if source.get('asset_kind') == 'hdr_sequence':
        raise ValueError('This experimental two-stage path currently needs an HDR video.')
    if expected['padded_frames'] > 113:
        raise ValueError('This experimental path supports up to 113 padded frames.')
    return expected, path


def build_reviewed_sdr_first_stage(source, selection, *, review_key, colour_space='auto',
                                   prompt='', seed=42, prefix='genj/hdr_outpaint/sdr_first_reviewed',
                                   check_asset=lambda asset: None):
    """Build the approved bounded HDR canvas using the SDR black-guide pass."""
    expected, path = _reviewed_sdr_first_selection(source, selection, review_key, colour_space, check_asset)
    if expected['mode'] == 'black':
        return _black_sdr_first_stage(source, expected, path, colour_space=colour_space,
                                      prompt=prompt, seed=seed, prefix=prefix)
    graph = build_sdr_first_stage(path, start_frame=0, start_seconds=expected['start'],
        frame_count=expected['padded_frames'], width=expected['padded_width'], height=expected['padded_height'],
        left=expected['left'], top=expected['top'], right=expected['right'], bottom=expected['bottom'],
        colour_space=colour_space, prompt=prompt, seed=seed, prefix=prefix)
    graph['hdr_source']['inputs']['frame_count'] = expected['frames']
    graph['hdr_input_hold'] = {'class_type': 'ZuraHDRTemporalHold', 'inputs': {'images': ['hdr_source', 0]}}
    graph['tone_map_source']['inputs']['image'] = ['hdr_input_hold', 0]
    return graph


def _black_sdr_first_stage(source, expected, path, *, colour_space, prompt, seed, prefix):
    """Use one native linear-black mask for review, SDR guidance and HDR repair."""
    if not re.fullmatch(r'genj/hdr_outpaint/[a-zA-Z0-9_-]{1,64}', prefix):
        raise ValueError('Choose a safe experiment output name.')
    if type(source.get('has_audio')) is not bool:
        raise ValueError('Verify whether the HDR source has audio before rendering.')
    graph = build_studio_graph(source, expected, review_key=expected['review_key'],
        prompt=prompt, seed=seed, output_prefix='genj/outpaint/hdr_experiment')
    # Use the established in/outpaint graph for explicit black-pixel masks.
    # Its VIDEO source and output nodes are replaced by native HDR input and a
    # bounded silent intermediate. Audio guides remain available where present.
    for name in ('source', 'source_range', 'components', 'temporal_hold', 'assemble', 'save', 'unpad_result'):
        graph.pop(name, None)
    for name, node in graph.items():
        if name != 'canvas':
            for key, value in node['inputs'].items():
                if value == ['canvas', 0]:
                    node['inputs'][key] = ['masked_sdr_guide', 0]
    graph['hdr_source'] = {'class_type':'ZuraHDRSelectNativeTimeline', 'inputs':{
        'source':path, 'start_seconds':expected['start'], 'frame_count':expected['frames'],
        'output_fps':24., 'colour_space':colour_space, 'sequence_fps':24.}}
    graph['hdr_input_hold'] = {'class_type':'ZuraHDRTemporalHold', 'inputs':{'images':['hdr_source',0]}}
    graph['canvas']['class_type'] = 'ZuraLTXOutpaintHDRCanvas'
    graph['canvas']['inputs']['images'] = ['hdr_input_hold', 0]
    graph['tone_map_source'] = {'class_type':'LTXVHDRDecodePostprocess', 'inputs':{
        'image':['canvas',0], 'transfer':'acescct', 'save_exr':False,
        'exr_color_space':'acescg', 'output_dir':prefix, 'filename_prefix':'source', 'half_precision':True}}
    graph['black_fill'] = {'class_type':'EmptyImage', 'inputs':{'width':expected['padded_width'],
        'height':expected['padded_height'], 'batch_size':1, 'color':0}}
    graph['masked_sdr_guide'] = {'class_type':'ImageCompositeMasked', 'inputs':{
        'destination':['tone_map_source',0], 'source':['black_fill',0], 'x':0, 'y':0,
        'resize_source':False, 'mask':['canvas',1]}}
    if source['has_audio']:
        graph['source_audio'] = {'class_type':'ZuraHDRLoadTimedAudio', 'inputs':{
            'source':path, 'start_seconds':expected['start'], 'frame_count':expected['frames'],
            'fps':24., 'allow_tail_hold':True, 'source_duration':expected['requested_duration']}}
        graph['stage_audio'] = {'class_type':'GenjPadAudioToFrames', 'inputs':{
            'audio':['source_audio',0], 'frames':expected['padded_frames'], 'fps':24.}}
    else:
        graph['stage_audio'] = {'class_type':'EmptyAudio', 'inputs':{
            'duration':expected['padded_frames']/24., 'sample_rate':48000, 'channels':2}}
    graph['audio_encoded']['inputs']['audio'] = ['stage_audio',0]
    graph['trim_result']['inputs']['length'] = expected['padded_frames']
    graph['stage_video'] = {'class_type':'CreateVideo', 'inputs':{
        'images':['trim_result',0], 'fps':24.}}
    graph['stage_save'] = {'class_type':'SaveVideo', 'inputs':{
        'video':['stage_video',0], 'filename_prefix':prefix, 'format':'mp4', 'format.codec':'h264'}}
    return graph


def crop_black_hdr_composite(graph, width, height):
    """Remove internal model padding before blending an already-padded plate."""
    image_crop = lambda image: {'class_type':'ImageCrop','inputs':{
        'image':image, 'width':width, 'height':height, 'x':0, 'y':0}}
    graph['native_source_crop'] = image_crop(['native_canvas',0])
    graph['native_mask_crop'] = {'class_type':'CropMask','inputs':{
        'mask':['native_canvas',1], 'width':width, 'height':height, 'x':0, 'y':0}}
    graph['hdr_generated_crop'] = image_crop(['hdr_unpad_raster',0])
    graph['final_hdr_composite']['inputs'].update(generated=['hdr_generated_crop',0],
        source=['native_source_crop',0], mask=['native_mask_crop',0])


def build_reviewed_sdr_first_composite(source, selection, intermediate, *, review_key,
                                       colour_space='auto', has_audio=False, seed=42,
                                       prefix='sdr_first_reviewed', check_asset=lambda asset: None):
    """Build the HDR delivery pass for the same approved bounded selection."""
    expected, path = _reviewed_sdr_first_selection(source, selection, review_key, colour_space, check_asset)
    if type(has_audio) is not bool:
        raise ValueError('Audio selection must be explicit.')
    graph = build_sdr_first_hdr_composite(path, intermediate, start_frame=0, start_seconds=expected['start'],
        frame_count=expected['padded_frames'], width=expected['padded_width'], height=expected['padded_height'],
        left=expected['left'], top=expected['top'], right=expected['right'], bottom=expected['bottom'],
        colour_space=colour_space, has_audio=False, seed=seed, prefix=prefix,
        mode=expected['mode'], black_threshold=expected['black_threshold'])
    graph['native_original']['inputs']['frame_count'] = expected['frames']
    graph['hdr_input_hold'] = {'class_type': 'ZuraHDRTemporalHold', 'inputs': {'images': ['native_original', 0]}}
    graph['native_canvas']['inputs']['images'] = ['hdr_input_hold', 0]
    if expected['mode'] == 'black':
        crop_black_hdr_composite(graph, expected['width'], expected['height'])
    graph['hdr_original_length'] = {'class_type': 'ImageFromBatch', 'inputs': {'image': ['final_hdr_composite', 0], 'batch_index': 0, 'length': expected['frames']}}
    graph['hdr_delivery_hold'] = {'class_type': 'GenjHoldToModelLength', 'inputs': {'images': ['hdr_original_length', 0], 'stride': 8}}
    for key, node in graph.items():
        if key == 'hdr_original_length':
            continue
        for field, value in node['inputs'].items():
            if value == ['final_hdr_composite', 0]:
                node['inputs'][field] = ['hdr_delivery_hold', 0]
    if has_audio:
        graph['original_audio'] = {'class_type': 'ZuraHDRLoadTimedAudio', 'inputs': {
            'source': path, 'start_seconds': expected['start'], 'frame_count': expected['frames'],
            'fps': 24., 'allow_tail_hold': True, 'source_duration': expected['requested_duration']}}
        graph['hdr_audio_hold'] = {'class_type': 'GenjPadAudioToFrames', 'inputs': {
            'audio': ['original_audio', 0], 'frames': ['hdr_delivery_hold', 1], 'fps': 24.}}
        graph['zura_hdr_video']['inputs']['audio'] = ['hdr_audio_hold', 0]
        graph['zura_hdr_preview_video']['inputs']['audio'] = ['hdr_audio_hold', 0]
    return graph


def build_hdr_review_experiment(source, selection, *, colour_space='auto',
                                sequence_fps=24, prefix='genj/hdr_outpaint/review', check_asset=lambda asset: None):
    """Build the exact HDR source and mask preview used by the experimental render."""
    expected, review_key, path = validate_hdr_selection(source, selection, colour_space, sequence_fps, check_asset)
    if not re.fullmatch(r'genj/hdr_outpaint/[a-zA-Z0-9_-]{1,64}', prefix):
        raise ValueError('Choose a safe experiment output name.')
    def node(kind, **inputs): return {'class_type': kind, 'inputs': inputs}
    g = {
        'hdr_source': node('ZuraHDRSelectNativeTimeline', source=source['file'],
                           start_seconds=expected['start'], frame_count=expected['frames'],
                           output_fps=24., colour_space=colour_space, sequence_fps=sequence_fps),
        'canvas': node('ZuraLTXOutpaintHDRCanvas', images=['hdr_source', 0], mode=expected['mode'],
                       width=expected['padded_width'], height=expected['padded_height'],
                       left=expected['left'], top=expected['top'], right=expected['right'],
                       bottom=expected['bottom'], black_threshold=expected['black_threshold']),
        'hdr_preview': node('LTXVHDRDecodePostprocess', image=['canvas', 0], transfer='acescct',
                            save_exr=False, exr_color_space='acescg', output_dir=prefix,
                            filename_prefix='review', half_precision=True),
        'overlay': node('ZuraOutpaintReviewOverlay', images=['hdr_preview', 0], mask=['canvas', 1]),
        'video': node('CreateVideo', images=['overlay', 0], fps=['hdr_source', 1]),
        'save': node('ZuraHDRSaveExactRate', video=['video', 0], filename_prefix=prefix, fps=['hdr_source', 1]),
    }
    if source.get('asset_kind') == 'hdr_sequence':
        g['hdr_source']['inputs'].update(manifest=path, manifest_sha=source['sha'])
    if (expected['width'], expected['height']) != (expected['padded_width'], expected['padded_height']):
        g['unpad'] = node('ImageCrop', image=['overlay', 0], width=expected['width'], height=expected['height'], x=0, y=0)
        g['video']['inputs']['images'] = ['unpad', 0]
    return g, review_key


def build_reviewed_hdr_experiment(source, selection, *, review_key, has_audio=False,
                                  colour_space='auto', sequence_fps=24, prompt='', seed=42,
                                  prefix='genj/hdr_outpaint/reviewed', check_asset=lambda asset: None):
    """Internal short HDR graph bound to the artist's reviewed HDR geometry.

    The colour-managed result remains unqualified; this is not a Studio route.
    """
    expected, expected_review, path = validate_hdr_selection(source, selection, colour_space, sequence_fps, check_asset)
    if review_key != expected_review:
        raise ValueError('Review and approve the current HDR outpaint selection first.')
    if source.get('asset_kind') == 'hdr_sequence' and has_audio:
        raise ValueError('An EXR sequence has no embedded audio.')
    g = build_experimental_graph(source['file'], start_frame=0, frame_count=expected['padded_frames'],
        fps=24, width=expected['padded_width'], height=expected['padded_height'], mode=expected['mode'],
        left=expected['left'], top=expected['top'], right=expected['right'], bottom=expected['bottom'],
        colour_space='auto' if source.get('asset_kind') == 'hdr_sequence' else colour_space,
        has_audio=has_audio, prompt=prompt, seed=seed, prefix=prefix,
        unverified_exr=True, unverified_hlg=True)
    def node(kind, **inputs): return {'class_type': kind, 'inputs': inputs}
    g['hdr_source'] = node('ZuraHDRSelectNativeTimeline', source=source['file'],
                           start_seconds=expected['start'], frame_count=expected['frames'],
                           output_fps=24., colour_space=colour_space, sequence_fps=sequence_fps)
    if source.get('asset_kind') == 'hdr_sequence':
        g['hdr_source']['inputs'].update(manifest=path, manifest_sha=source['sha'])
    g['hdr_hold'] = node('ZuraHDRTemporalHold', images=['hdr_source', 0])
    g['canvas']['inputs']['images'] = ['hdr_hold', 0]
    g['canvas']['inputs']['black_threshold'] = expected['black_threshold']
    if has_audio:
        g['hdr_audio'] = node('ZuraHDRLoadTimedAudio', source=source['file'], start_seconds=expected['start'],
                              frame_count=expected['frames'], fps=['hdr_source', 1], allow_tail_hold=True,
                              source_duration=expected['requested_duration'])
        g['hdr_audio_hold'] = node('ZuraOutpaintTemporalHold', images=['hdr_source', 0],
                                   audio=['hdr_audio', 0], expected_frames=expected['frames'])
        g['audio_encoded']['inputs']['audio'] = ['hdr_audio_hold', 1]
    g['hdr_trim'] = node('ImageFromBatch', image=['hdr_composite', 0], batch_index=0, length=expected['frames'])
    final = ['hdr_trim', 0]
    if (expected['width'], expected['height']) != (expected['padded_width'], expected['padded_height']):
        g['hdr_unpad'] = node('ImageCrop', image=final, width=expected['width'], height=expected['height'], x=0, y=0)
        final = ['hdr_unpad', 0]
    g['hdr_preview']['inputs']['image'] = final
    g['hdr_experiment_exr']['inputs']['images'] = final
    g['hdr_experiment_hlg']['inputs']['image'] = final
    return g
