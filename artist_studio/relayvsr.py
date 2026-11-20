"""Load the original LightX2V BF16 RelayVSR 2× weights into native ComfyUI."""
import re


_PROJECTIONS = {
    'condition_embedder.text_embedder.linear_1': 'text_embedding.0',
    'condition_embedder.text_embedder.linear_2': 'text_embedding.2',
    'condition_embedder.time_embedder.linear_1': 'time_embedding.0',
    'condition_embedder.time_embedder.linear_2': 'time_embedding.2',
    'condition_embedder.time_proj': 'time_projection.1',
    'lq_proj.out_proj': 'lq_proj_in.linear',
    'proj_out': 'head.head',
}

_BLOCK_PARTS = {
    'ffn.net.0.proj': 'ffn.0',
    'ffn.net.2': 'ffn.2',
    'norm2': 'norm3',
}
_ATTENTION = {'to_q': 'q', 'to_k': 'k', 'to_v': 'v', 'to_out.0': 'o'}


def native_relay_name(key):
    if key == 'prompt_embeds':
        return 'positive_conditioning'
    if key == 'scale_shift_table':
        return 'head.modulation'
    if key.startswith('patch_embedding.'):
        return key
    stem, _, parameter = key.rpartition('.')
    if stem in _PROJECTIONS:
        return f'{_PROJECTIONS[stem]}.{parameter}'
    if key.startswith('lq_proj.'):
        return 'lq_proj_in.' + key.removeprefix('lq_proj.')
    match = re.fullmatch(r'(blocks\.\d+)\.(.+)', key)
    if match:
        block, ending = match.groups()
        if ending == 'scale_shift_table':
            return f'{block}.modulation'
        part, _, parameter = ending.rpartition('.')
        if part in _BLOCK_PARTS:
            return f'{block}.{_BLOCK_PARTS[part]}.{parameter}'
        attention, _, projection = part.partition('.')
        if attention in ('attn1', 'attn2'):
            name = 'self_attn' if attention == 'attn1' else 'cross_attn'
            return f'{block}.{name}.{_ATTENTION.get(projection, projection)}.{parameter}'
    raise ValueError(f'Unrecognised RelayVSR parameter {key}.')


class ZuraRelayVSRLoadBF16:
    @classmethod
    def INPUT_TYPES(cls):
        import folder_paths
        return {'required': {'unet_name': (folder_paths.get_filename_list('diffusion_models'),)}}

    RETURN_TYPES = ('MODEL',)
    FUNCTION = 'load'
    CATEGORY = 'Zura/Artist Studio'

    def load(self, unet_name):
        import comfy.sd
        import comfy.utils
        import folder_paths
        from torch import bfloat16

        path = folder_paths.get_full_path_or_raise('diffusion_models', unet_name)
        weights, metadata = comfy.utils.load_torch_file(path, safe_load=True, return_metadata=True)
        if (metadata or {}).get('format') != 'relayvsr-wan-x2-v1' or weights.get('prompt_embeds') is None:
            raise ValueError('Choose the original LightX2V RelayVSR 2× BF16 checkpoint.')
        native = {}
        for key, tensor in weights.items():
            name = native_relay_name(key)
            if key in ('lq_proj.norm1.weight', 'lq_proj.norm2.weight'):
                tensor = tensor.flatten()
            elif key == 'prompt_embeds':
                tensor = tensor.squeeze(0)
            native[name] = tensor
        model = comfy.sd.load_diffusion_model_state_dict(native, model_options={'dtype': bfloat16})
        if model is None:
            raise ValueError('Update ComfyUI to a version with native RelayVSR support.')
        return (model,)
