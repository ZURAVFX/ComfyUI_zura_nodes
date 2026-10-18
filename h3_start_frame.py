"""Data-only first-frame injection for native MiniMax H3 AV sampling.

Keep the visible native VAEEncode and sampler in the graph. A reference guide
is not a target noise mask: this adapter supplies the latter as well.
"""
import torch


class ZuraH3LockStartFrame:
    CATEGORY = 'Zura/video'
    FUNCTION = 'lock'
    RETURN_TYPES = ('LATENT',)
    RETURN_NAMES = ('anchored_av_latent',)
    DESCRIPTION = 'Preserve the encoded approved first frame during H3 sampling. Use alongside a native image guide, not instead of performance conditioning.'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'latent': ('LATENT',), 'start_frame_latent': ('LATENT',)}}

    def lock(self, latent, start_frame_latent):
        from comfy.nested_tensor import NestedTensor
        samples = latent.get('samples')
        if not isinstance(samples, NestedTensor) or len(samples.tensors) != 2:
            raise ValueError('Connect a native H3 joint video/audio latent.')
        video, audio = samples.tensors
        still = start_frame_latent.get('samples')
        if (not isinstance(video, torch.Tensor) or video.ndim != 5 or video.shape[:2] != (1, 24)
                or video.shape[2] < 1 or not isinstance(audio, torch.Tensor) or audio.ndim != 4
                or audio.shape[:3] != (1, 32, 2)):
            raise ValueError('Expected one MiniMax H3 video/audio take.')
        if (not isinstance(still, torch.Tensor) or still.ndim != 5
                or still.shape != video[:, :, :1].shape or not still.is_floating_point()
                or not torch.isfinite(still).all()):
            raise ValueError('Encode exactly one approved image at the target resolution using the H3 video VAE.')
        previous = latent.get('noise_mask')
        if previous is not None and (not isinstance(previous, NestedTensor) or len(previous.tensors) != 2):
            raise ValueError('Existing H3 masks must have separate video and audio streams.')
        if previous is None:
            video_mask, audio_mask = torch.ones_like(video), torch.ones_like(audio)
        else:
            try:
                video_mask = torch.broadcast_to(previous.tensors[0], video.shape).clone()
                audio_mask = torch.broadcast_to(previous.tensors[1], audio.shape).clone()
            except RuntimeError as exc:
                raise ValueError('Existing H3 masks do not match this take.') from exc
        anchored = video.clone()
        anchored[:, :, :1] = still.to(device=video.device, dtype=video.dtype)
        video_mask[:, :, :1] = 0
        return ({**latent, 'samples': NestedTensor((anchored, audio)),
                 'noise_mask': NestedTensor((video_mask, audio_mask))},)


NODE_CLASS_MAPPINGS = {'ZuraH3LockStartFrame': ZuraH3LockStartFrame}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraH3LockStartFrame': 'Zura · Anchor Approved H3 Start Frame'}
