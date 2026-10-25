"""Bound the memory of native LTX guide attention without changing its weights."""
import types
import torch


class CompactGuideMask:
    def __init__(self, total_tokens, guide_start, tracked_count, tracked_weights):
        self.total_tokens = total_tokens
        self.guide_start = guide_start
        self.tracked_count = tracked_count
        limits = torch.finfo(tracked_weights.dtype)
        tracked_weights = tracked_weights.reshape(-1)
        self.log_weights = torch.full_like(tracked_weights, limits.min)
        positive = tracked_weights > 0
        self.log_weights[positive] = tracked_weights[positive].clamp(min=limits.tiny).log()
        self.noisy_mask = tracked_weights.new_zeros((1, 1, 1, total_tokens))
        self.noisy_mask[..., guide_start:guide_start + tracked_count] = self.log_weights

    def rows(self, start, end):
        if end <= self.guide_start:
            return self.noisy_mask
        tracked_end = self.guide_start + self.tracked_count
        if start >= tracked_end:
            return None
        if start < self.guide_start or end > tracked_end:
            raise ValueError('Attention chunks must respect native guide boundaries.')
        result = self.log_weights.new_zeros((1, 1, end - start, self.total_tokens))
        result[..., :self.guide_start] = self.log_weights[start-self.guide_start:end-self.guide_start].view(1, 1, -1, 1)
        return result


def chunked_guide_attention(function, q, k, v, heads, mask=None, chunk_size=256, **kwargs):
    if not isinstance(mask, CompactGuideMask):
        return function(q, k, v, heads, mask=mask, **kwargs)
    if q.ndim != 3 or kwargs.get('skip_reshape') or kwargs.get('skip_output_reshape'):
        raise RuntimeError('Memory-bounded LTX guidance requires the native three-dimensional Q/K/V layout.')
    if q.shape[1] != mask.total_tokens or k.shape[1] != mask.total_tokens:
        raise RuntimeError('LTX guide token counts changed; refusing to apply a misaligned mask.')
    # Queries are independent. Keep the same K/V and bias for every query.
    output = torch.empty_like(q)
    kwargs['low_precision_attention'] = False
    boundaries = (0, mask.guide_start, mask.guide_start + mask.tracked_count, q.shape[1])
    for left, right in zip(boundaries, boundaries[1:]):
        for start in range(left, right, chunk_size):
            end = min(start + chunk_size, right)
            output[:, start:end] = function(q[:, start:end], k, v, heads,
                                           mask=mask.rows(start, end), **kwargs)
    return output


class ZuraPaintoutGuideMemory:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'model': ('MODEL',), 'query_chunk': ('INT', {'default': 256, 'min': 64, 'max': 2048, 'step': 64})}}

    RETURN_TYPES = ('MODEL',)
    FUNCTION = 'patch'
    CATEGORY = 'Zura/Paintout'
    DESCRIPTION = 'Preserves native LTX guide attention while building only a small part of its mask at once.'

    def patch(self, model, query_chunk):
        original = model.get_model_object('diffusion_model._build_guide_self_attention_mask')
        if not isinstance(original, types.MethodType) or 'GuideAttentionMask' not in original.__func__.__code__.co_names:
            raise RuntimeError('This LTX installation does not expose the supported native guide-mask builder.')
        function = original.__func__
        globals_copy = dict(function.__globals__, GuideAttentionMask=CompactGuideMask)
        private_builder = types.FunctionType(function.__code__, globals_copy, function.__name__, function.__defaults__, function.__closure__)
        private_builder.__kwdefaults__ = function.__kwdefaults__
        cloned = model.clone()
        cloned.add_object_patch('diffusion_model._build_guide_self_attention_mask', types.MethodType(private_builder, original.__self__))
        options = cloned.model_options.setdefault('transformer_options', {})
        previous = options.get('optimized_attention_override')

        def override(backend, q, k, v, heads, mask=None, **kwargs):
            if isinstance(mask, CompactGuideMask):
                # Native masked guidance disables low precision attention. Use
                # the installed native PyTorch backend, including its SDPA path.
                from comfy.ldm.modules.attention import attention_pytorch
                kwargs['_inside_attn_wrapper'] = True
                return chunked_guide_attention(attention_pytorch, q, k, v, heads,
                                               mask=mask, chunk_size=query_chunk, **kwargs)
            if previous is not None:
                return previous(backend, q, k, v, heads, mask=mask, **kwargs)
            return backend(q, k, v, heads, mask=mask, **kwargs)

        options['optimized_attention_override'] = override
        return (cloned,)
