"""Thin media and latent adapters for local MiniMax H3 shot continuation."""
from fractions import Fraction

import torch

from .h3_windows import h3_video_token_count

FPS = 24
CATEGORY = 'Zura/Artist Studio/H3'


def _audio_window(audio, start, duration):
    from . import fit_audio
    if audio is None:
        return fit_audio(None, duration)
    rate = audio['sample_rate']
    return fit_audio({**audio, 'waveform': audio['waveform'][..., round(start * rate):]}, duration)


def _match_audio(audio, sample_rate, channels):
    from comfy.audio import resample
    waveform = audio['waveform']
    if audio['sample_rate'] != sample_rate:
        waveform = resample(waveform, audio['sample_rate'], sample_rate)
    if waveform.shape[1] == channels:
        return waveform
    if channels == 1:
        return waveform.mean(dim=1, keepdim=True)
    if waveform.shape[1] == 1:
        return waveform.expand(-1, channels, -1)
    if waveform.shape[1] > channels:
        return waveform[:, :channels]
    return torch.nn.functional.pad(waveform, (0, 0, 0, channels - waveform.shape[1]))


class ZuraH3ExtendContext:
    """Sample only the ending context at H3's clock. Keep the selected video intact."""

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'video': ('VIDEO',),
                             'context_frames': ('INT', {'default': 56, 'min': 5, 'max': 107})}}

    RETURN_TYPES = ('IMAGE', 'AUDIO', 'ZURA_H3_EXTEND_SOURCE')
    RETURN_NAMES = ('ending_frames', 'ending_audio', 'selected_clip')
    CATEGORY = CATEGORY
    FUNCTION = 'prepare'

    def prepare(self, video, context_frames):
        h3_video_token_count(context_frames)
        width, height = video.get_dimensions()
        duration = video.get_duration()
        if duration <= 0 or duration * 120 * width * height > 1_200_000_000:
            raise ValueError('This selection is too large. Trim closer to the point you want to extend.')
        source = video.get_components()
        frames = source.images[..., :3]
        fps = Fraction(source.frame_rate)
        if not len(frames) or not 1 <= fps <= 120:
            raise ValueError('Choose a video with a supported frame rate.')
        if len(frames) * width * height > 300_000_000:
            raise ValueError('This selection is too large. Trim closer to the point you want to extend.')
        # Anchor the last context frame on the exact selected cut. Hold the
        # first available frame for any context earlier than the selected clip.
        end = Fraction(len(frames), 1) / fps
        positions = torch.tensor([
            max(0, len(frames) - 1 - round(Fraction(i, FPS) * fps))
            for i in reversed(range(context_frames))
        ], device=frames.device)
        context_duration = Fraction(context_frames, FPS)
        available = min(end, context_duration)
        context_audio = _audio_window(source.audio, end - available, available)
        wave = context_audio['waveform']
        if wave.shape[1] == 1:
            wave = wave.expand(-1, 2, -1)
        elif wave.shape[1] > 2:
            wave = wave[:, :2]
        missing = max(0, round(context_duration * context_audio['sample_rate']) - wave.shape[-1])
        context_audio['waveform'] = torch.nn.functional.pad(wave, (missing, 0))
        return frames.index_select(0, positions), context_audio, source


class ZuraH3ExtendLatent:
    """Insert and freeze the encoded video and audio prefixes before denoising."""

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'latent': ('LATENT',), 'ending_video': ('LATENT',),
                             'ending_audio': ('LATENT',),
                             'context_frames': ('INT', {'default': 56, 'min': 5, 'max': 107})}}

    RETURN_TYPES = ('LATENT',)
    CATEGORY = CATEGORY
    FUNCTION = 'seed'

    def seed(self, latent, ending_video, ending_audio, context_frames):
        from .h3_windows import _h3_pair
        nested, video, audio = _h3_pair(latent, 'samples')
        video_count = h3_video_token_count(context_frames)
        audio_count = round(Fraction(context_frames * 5, 3))
        video_prefix, audio_prefix = ending_video['samples'], ending_audio['samples']
        if video_prefix.shape[:2] != video.shape[:2] or video_prefix.shape[3:] != video.shape[3:] or video_prefix.shape[2] < video_count or video_count >= video.shape[2]:
            raise ValueError('The encoded context does not match the MiniMax H3 video canvas.')
        if audio_prefix.shape[:-1] != audio.shape[:-1] or audio_count >= audio.shape[-1]:
            raise ValueError('The encoded context does not match the MiniMax H3 audio timeline.')
        audio_count = min(audio_count, audio_prefix.shape[-1])
        video, audio = video.clone(), audio.clone()
        video[:, :, :video_count] = video_prefix[:, :, -video_count:].to(video)
        if audio_count:
            audio[..., :audio_count] = audio_prefix[..., -audio_count:].to(audio)
        video_mask, audio_mask = torch.ones_like(video), torch.ones_like(audio)
        video_mask[:, :, :video_count] = 0
        audio_mask[..., :audio_count] = 0
        return ({**latent, 'samples': type(nested)((video, audio)),
                 'noise_mask': type(nested)((video_mask, audio_mask))},)


class ZuraH3ExtendDelivery:
    """Append the generated tail after the original cut and retain the source clock."""

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'source': ('ZURA_H3_EXTEND_SOURCE',), 'generated': ('IMAGE',),
                             'context_frames': ('INT', {'default': 56, 'min': 5, 'max': 107}),
                             'seconds': ('FLOAT', {'default': 2., 'min': .25, 'max': 10.})},
                'optional': {'generated_audio': ('AUDIO',)}}

    RETURN_TYPES = ('VIDEO', 'VIDEO')
    RETURN_NAMES = ('extended_clip', 'generated_tail')
    CATEGORY = CATEGORY
    FUNCTION = 'assemble'

    def assemble(self, source, generated, context_frames, seconds, generated_audio=None):
        import comfy.utils
        from comfy_api.latest import InputImpl, Types
        from . import fit_audio

        original = source.images[..., :3]
        fps = Fraction(source.frame_rate)
        tail_count = max(1, round(Fraction(str(seconds)) * fps))
        tail = generated[context_frames:, ..., :3]
        if len(tail) < round(Fraction(str(seconds)) * FPS):
            raise ValueError('MiniMax H3 did not return the requested continuation.')
        indices = torch.tensor([min(len(tail) - 1, round(Fraction(i * FPS, 1) / fps))
                                for i in range(tail_count)], device=tail.device)
        tail = tail.index_select(0, indices)
        if tail.shape[1:3] != original.shape[1:3]:
            tail = comfy.utils.common_upscale(tail.movedim(-1, 1), original.shape[2],
                                              original.shape[1], 'lanczos', 'disabled').movedim(1, -1)
        tail = tail.to(original)
        original_audio = fit_audio(source.audio, Fraction(len(original), 1) / fps) if source.audio or generated_audio else None
        tail_audio = None
        if original_audio is not None:
            rate = original_audio['sample_rate']
            duration = Fraction(tail_count, 1) / fps
            channels = original_audio['waveform'].shape[1]
            if generated_audio:
                generated_audio = _audio_window(generated_audio, Fraction(context_frames, FPS), duration)
                waveform = _match_audio(generated_audio, rate, channels)
                tail_audio = fit_audio({'waveform': waveform, 'sample_rate': rate}, duration)
            else:
                tail_audio = {'sample_rate': rate, 'waveform': original_audio['waveform'].new_zeros(
                    (1, channels, round(duration * rate)))}
            original_audio = {**original_audio, 'waveform': torch.cat(
                (original_audio['waveform'], tail_audio['waveform']), dim=-1)}
        def video(frames, audio):
            return InputImpl.VideoFromComponents(Types.VideoComponents(images=frames, audio=audio, frame_rate=fps))
        return video(torch.cat((original, tail), 0), original_audio), video(tail, tail_audio)


NODE_CLASS_MAPPINGS = {node.__name__: node for node in
                       (ZuraH3ExtendContext, ZuraH3ExtendLatent, ZuraH3ExtendDelivery)}
