"""Constrain white-matte source structure within the H3 denoising trajectory."""

import math

import torch
import torch.nn.functional as F


class ZuraSwitchXProtectedLatent:
    """Use Character Replacement's source latent and its exact temporal mask bins."""

    CATEGORY = "Zura/SwitchX"
    FUNCTION = "prepare"
    RETURN_TYPES = ("LATENT",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "latent": ("LATENT",),
                "source": ("LATENT",),
                "replace": ("MASK",),
                "allow_relight": ("BOOLEAN", {"default": True}),
            }
        }

    def prepare(self, latent, source, replace, allow_relight=True):
        from .h3 import ZuraH3PreserveBackground
        from comfy.nested_tensor import NestedTensor

        (result,) = ZuraH3PreserveBackground().preserve(latent, source, replace)
        if allow_relight:
            video, audio = result["noise_mask"].unbind()
            # A zero edit mask fixes the original illumination. Allow the joint
            # prediction to relight protected interiors while retaining their structure.
            result = {**result, "noise_mask": NestedTensor((video.clamp_min(0.45), audio))}
        return (result,)


def latent_coverage(replace, shape):
    batch, channels, tokens, height, width = shape
    # Each native H3 VAE chunk has a one-frame bin followed by four four-frame bins.
    spans = [(1, 4, 4, 4, 4)[k % 5] for k in range(tokens)]
    if (
        batch != 1
        or channels != 24
        or tuple(replace.shape) != (sum(spans), height * 16, width * 16)
    ):
        raise ValueError("The padded matte must match the native H3 video latent.")
    area = F.avg_pool2d((1 - replace.float()).unsqueeze(1), 16, stride=16)[:, 0]
    return torch.stack([frames.mean(0) for frames in area.split(spans)])[None, None]


def mask_weights(coverage):
    # Feather mixed latent cells towards the network prediction at the silhouette.
    support = ((coverage - 0.40) / 0.57).clamp(0, 1)
    return support.square() * (3 - 2 * support)


def local_mean(value):
    return F.avg_pool3d(F.pad(value, (3, 3, 3, 3, 0, 0), mode="replicate"), (1, 7, 7), stride=1)


class ZuraH3SourceStructure:
    CATEGORY = "Zura/Switch X Remake"
    FUNCTION = "patch"
    RETURN_TYPES = ("MODEL",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "source": ("LATENT",),
                "replace": ("MASK",),
                "strength": ("FLOAT", {"default": 0.96, "min": 0.0, "max": 1.0}),
            }
        }

    def patch(self, model, source, replace, strength):
        if strength == 0:
            return (model,)
        video = source["samples"]
        if not isinstance(video, torch.Tensor) or video.ndim != 5:
            raise ValueError("Supply a source clip encoded with the H3 video VAE.")
        weights = mask_weights(latent_coverage(replace, video.shape))
        if not weights.any():
            return (model,)
        denominator = local_mean(weights).clamp_min(0.001)
        reference = model.get_model_object("latent_format").process_in(video.detach()).float()
        shape = tuple(reference.shape)
        video_elements = math.prod(shape[1:])

        def preserve_structure(args):
            # Comfy packs the video stream first and the audio stream second for H3.
            prediction = args["denoised"]
            if (
                prediction.ndim != 3
                or prediction.shape[:2] != (1, 1)
                or prediction.shape[-1] <= video_elements
            ):
                raise ValueError("Expected a packed H3 video and audio prediction.")
            estimate = prediction[:, :, :video_elements].reshape(shape).float()
            target = reference.to(estimate.device)
            weight = weights.to(estimate.device)
            light = local_mean((estimate - target) * weight) / denominator.to(estimate.device)
            guided = torch.lerp(estimate, target + light, weight * strength)
            result = prediction.clone()
            result[:, :, :video_elements] = guided.reshape(1, 1, -1)
            return result

        patched = model.clone()
        patched.set_model_sampler_post_cfg_function(preserve_structure)
        return (patched,)
