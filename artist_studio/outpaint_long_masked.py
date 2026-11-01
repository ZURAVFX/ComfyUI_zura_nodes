"""The approved original LTX outpaint recipe for each long-shot section."""
from __future__ import annotations


def build_masked_expand_graph(source, selection, *, review_key, prompt='', seed=42,
                              output_prefix, check_asset=lambda asset: None):
    """Use the reviewed canvas and the approved full-resolution source guide."""
    if not isinstance(selection, dict) or selection.get('mode') not in ('expand', 'black'):
        raise ValueError('Choose a supported canvas expansion or black-area fill.')
    from .outpaint_studio import build_studio_graph
    return build_studio_graph(source, selection, review_key=review_key, prompt=prompt,
        seed=seed, output_prefix=output_prefix, check_asset=check_asset)
