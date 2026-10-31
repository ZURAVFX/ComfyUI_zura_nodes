"""Bounded, research-only native-HDR variant of the official LTX 2.5 recipe.

This reuses the existing reviewed outpaint experiment; it does not register a
Studio route or change the approved SDR-guide render.  The official HDR
inpaint graph can outpaint an expanded canvas by using its white-to-generate
mask at the border.  Its Laplacian blender clamps the ACEScct tensor to [0,1]
and its pyramid spreads the blend beyond the mask, so the raw result does not
guarantee untouched source pixels or full out-of-range HDR values.

The optional native plate composite is a separate evaluation variant.  Both
outputs still need HDR-display review for colour, seams and temporal flicker.
"""
from __future__ import annotations

from .hdr_outpaint_experiment import build_reviewed_hdr_experiment, validate_hdr_selection


def build_native_hdr_outpaint_test(source, selection, *, review_key, colour_space='auto',
                                   has_audio=False, sequence_fps=24., prompt='', seed=42,
                                   prefix='genj/hdr_outpaint/native_official',
                                   preserve_source=False, check_asset=lambda asset: None):
    """Return a reviewed short-clip API graph for a matched HDR comparison.

    ``preserve_source=False`` delivers the official second Laplacian blend.
    Setting it to true adds Zura's existing HDR plate composite *after* that
    blend.  Reusing the same seed and inputs allows Comfy's execution cache to
    share the expensive samplers between the two separate graph variants.

    Selected frames are read before padding; the final source frame is held to
    an 8n+1 length. Audio guidance and output use the same duration, with only
    the held tail padded.  This graph is single-window and has no continuation
    anchor or claim of seamless long-clip operation.
    """
    if type(preserve_source) is not bool:
        raise ValueError('Choose whether to preserve the native source plate.')
    if type(has_audio) is not bool:
        raise ValueError('Audio selection must be explicit.')
    expected, expected_review, _ = validate_hdr_selection(
        source, selection, colour_space, sequence_fps, check_asset)
    if review_key != expected_review:
        raise ValueError('Review and approve the current HDR outpaint selection first.')
    g = build_reviewed_hdr_experiment(
        source, selection, review_key=review_key, has_audio=has_audio,
        colour_space=colour_space, sequence_fps=sequence_fps, prompt=prompt,
        seed=seed, prefix=prefix, check_asset=check_asset)

    # The official graph feeds SamplerCustomAdvanced's *denoised_output* into
    # separation, cropping and the first Laplacian blend.  Its second sampler
    # feeds the normal output to decoding.
    g['split']['inputs']['av_latent'] = ['sample', 1]

    # With no reference soundtrack, do not mark an empty audio latent as
    # frozen source audio.  Follow the requested optional-audio behaviour.
    if not has_audio:
        g['av']['inputs']['audio_latent'] = ['audio_encoded', 0]
        g['guider']['inputs'].update(positive=['guide', 0], negative=['guide', 1])
        g['crop_guides']['inputs'].update(positive=['guide', 0], negative=['guide', 1])
        g['av_high']['inputs']['audio_latent'] = ['split', 1]
        g.pop('audio_frozen', None)
        g.pop('freeze_high', None)

    if not preserve_source:
        g['hdr_trim']['inputs']['image'] = ['blend_high', 0]
        g.pop('hdr_composite', None)

    # The existing reviewed builder trims away inference-only padding. Restore
    # the user-requested delivery hold explicitly after cropping the result.
    result = ['hdr_unpad', 0] if 'hdr_unpad' in g else ['hdr_trim', 0]
    g['test_delivery_hold'] = {'class_type': 'GenjHoldImages', 'inputs': {
        'images': result, 'length': expected['padded_frames']}}
    for key, field in (('hdr_preview', 'image'), ('hdr_experiment_exr', 'images'),
                       ('hdr_experiment_hlg', 'image')):
        g[key]['inputs'][field] = ['test_delivery_hold', 0]
    if has_audio:
        for key in ('hdr_preview_video', 'hdr_experiment_video'):
            g[key]['inputs']['audio'] = ['hdr_audio_hold', 1]

    return g
