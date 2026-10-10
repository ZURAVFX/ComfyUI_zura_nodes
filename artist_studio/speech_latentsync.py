"""Full-resolution local LatentSync 1.6 adapter for native face detections.

The licensed network is isolated in latentsync_vendor. Detection, project
selection, audio loading and video composition remain separate graph nodes.
"""
from __future__ import annotations

import gc
import json
import math
from pathlib import Path

import torch
import torch.nn.functional as F

MODEL = "LatentSync 1.6"
FILES = ("LatentSync-1.6/latentsync_unet.pt", "LatentSync-1.6/whisper/tiny.pt",
         "sd-vae-ft-mse/config.json", "sd-vae-ft-mse/diffusion_pytorch_model.safetensors")
VENDOR = Path(__file__).parent / "latentsync_vendor"


def audio_windows(features, count, fps):
    """The trained ten-step, five-layer Whisper window at the actual frame rate."""
    for i in range(count):
        centre = math.floor(i * 50 / fps)
        indices = torch.arange(centre - 4, centre + 6).clamp(0, len(features)-1)
        yield features[indices].flatten(0, 1)


def encode_audio(audio, checkpoint_path):
    """Use pre-normalisation intermediate embeddings, without text decoding."""
    import torchaudio.functional as AF
    import comfy.model_management as mm
    from .latentsync_vendor.audio.encoder import AudioEncoder
    from .latentsync_vendor.audio.mel import log_mel_spectrogram, pad_or_trim

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    dims = checkpoint["dims"]
    if (dims["n_audio_state"], dims["n_audio_layer"], dims["n_mels"]) != (384, 4, 80):
        raise ValueError("Install the published LatentSync tiny audio encoder.")
    encoder = AudioEncoder(dims["n_mels"], dims["n_audio_ctx"], dims["n_audio_state"],
                           dims["n_audio_head"], dims["n_audio_layer"]).eval()
    encoder.load_state_dict({key.removeprefix("encoder."): value
                            for key, value in checkpoint["model_state_dict"].items()
                            if key.startswith("encoder.")}, strict=True)
    del checkpoint
    wave = AF.resample(audio["waveform"][0].mean(0), audio["sample_rate"], 16000)
    # The published feature extractor decodes to signed 16-bit PCM before STFT.
    wave = (wave.clamp(-1, 1-1/32768) * 32768).round() / 32768
    mel = log_mel_spectrogram(F.pad(wave, (0, max(0, 400-len(wave)))))
    features = []
    with torch.inference_mode():
        for start in range(0, mel.shape[-1], 3000):
            mm.throw_exception_if_processing_interrupted()
            segment = mel[:, start:start+3000]
            _, embeddings = encoder(pad_or_trim(segment, 3000)[None], include_embeddings=True)
            # Upstream returns B,L,T,D; conditioning is T,L,D.
            features.append(torch.from_numpy(embeddings[0]).permute(1, 0, 2)[:segment.shape[-1]//2])
    return torch.cat(features)


def align_faces(neutral, pose_data, face_boxes):
    """Map native 68-point landmarks to LatentSync's published training crop."""
    import cv2
    import numpy as np
    from .speech import native_face_landmarks

    metas = (pose_data or {}).get("pose_metas_original", [])
    if len(metas) != len(neutral) or face_boxes is None or len(face_boxes) != len(neutral):
        raise ValueError("Connect the native pose data and face boxes for sharp lip sync.")
    template = np.array([[17, 20], [58, 20], [37.5, 40]], dtype=np.float64) * 5.6
    size = (420, 560)
    pixels, matrices = [], []
    for i, (meta, box) in enumerate(zip(metas, face_boxes)):
        points = native_face_landmarks(meta)
        if (points.ndim != 2 or points.shape[0] != 68 or points.shape[1] < 2
                or not torch.isfinite(points).all() or meta.get("width", 0) <= 0
                or meta.get("height", 0) <= 0 or (points.shape[1] >= 3 and points[27:, 2].mean() < .3)):
            raise ValueError(f"No clear face landmarks on frame {i+1}. Lip sync needs a visible human face.")
        x1, y1, x2, y2 = map(float, box)
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"No usable face crop on frame {i+1}.")
        height, width = neutral.shape[1:3]
        xy = points[:, :2].numpy() * [meta["width"], meta["height"]]
        xy = (xy - [x1, y1]) * [width/(x2-x1), height/(y2-y1)]
        # Upstream 106-point anchors are eyebrow centres and the nose tip.
        anchors = np.stack((xy[17:22].mean(0), xy[22:27].mean(0), xy[30]))
        a = anchors - anchors.mean(0); b = template - template.mean(0)
        s1, s2 = a.std(ddof=1), b.std(ddof=1)
        if s1 < 1 or not np.isfinite(s1):
            raise ValueError(f"Face landmarks are too small on frame {i+1}.")
        u, _, vt = np.linalg.svd((a/s1).T @ (b/s2))
        rotation = vt.T @ u.T
        if np.linalg.det(rotation) < 0:
            vt[-1] *= -1; rotation = vt.T @ u.T
        scale_rotation = (s2/s1) * rotation
        translation = template.mean(0) - scale_rotation @ anchors.mean(0)
        # Preserve upstream's small nose-bias stabilisation.
        bias = b[2]/s2 - a[2]/s1
        if i: bias = previous_bias*.2 + bias*.8
        previous_bias = bias
        matrix = np.column_stack((scale_rotation, translation+bias)).astype(np.float32)
        aligned = cv2.warpAffine(neutral[i].numpy(), matrix, size, flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(.5, .5, .5))
        pixels.append(torch.from_numpy(cv2.resize(aligned, (512, 512), interpolation=cv2.INTER_LANCZOS4).copy()))
        matrices.append(matrix)
    return torch.stack(pixels).permute(0, 3, 1, 2).clamp(0, 1)*2-1, matrices, size


def animate(faces, audio, model, fps, seed, pose_data, face_boxes):
    import cv2
    from diffusers import AutoencoderKL, DDIMScheduler
    from accelerate import init_empty_weights
    import comfy.model_management as mm
    from comfy.utils import ProgressBar
    from .latentsync_vendor.models.unet import UNet3DConditionModel
    from .speech import fit_speech, lower_face_mask, resting_faces, speech_activity

    audio = fit_speech(audio, len(faces), fps)
    activity = speech_activity(audio, len(faces), fps)
    neutral = resting_faces(faces, pose_data, face_boxes)
    if not activity.any(): return neutral
    base = Path(model["path"])
    if not all((base/name).is_file() for name in FILES):
        raise ValueError("Run Setup_Speech_Windows.cmd to install sharp local lip sync.")
    device = mm.get_torch_device()
    if device.type != "cuda":
        raise ValueError("Sharp lip sync needs a CUDA GPU. Select MuseTalk 1.5 for another device.")
    pixels, matrices, size = align_faces(neutral, pose_data, face_boxes)
    features = encode_audio(audio, base/"LatentSync-1.6/whisper/tiny.pt")
    windows = list(audio_windows(features, len(faces), fps))
    mm.free_memory(5*1024**3, device)
    unet = vae = None
    try:
        config = json.loads((VENDOR/"unet_config.json").read_text())
        with init_empty_weights():
            unet = UNet3DConditionModel.from_config(config)
        checkpoint = torch.load(base/"LatentSync-1.6/latentsync_unet.pt", map_location="cpu", weights_only=True)
        # The upstream override predates assign and can drop incompatible keys.
        # Use PyTorch's strict loader: every published weight must match.
        torch.nn.Module.load_state_dict(unet,checkpoint["state_dict"],strict=True,assign=True)
        del checkpoint
        unet = unet.to(device=device, dtype=torch.float16).eval()
        vae = AutoencoderKL.from_pretrained(str(base/"sd-vae-ft-mse"), local_files_only=True,
                                          torch_dtype=torch.float16).eval()
        vae.enable_slicing()
        scale, shift = vae.config.scaling_factor, getattr(vae.config, "shift_factor", None) or 0
        scheduler = DDIMScheduler.from_config(json.loads((VENDOR/"scheduler_config.json").read_text()))
        keep_image = cv2.cvtColor(cv2.imread(str(VENDOR/"mask.png")), cv2.COLOR_BGR2RGB)
        keep_image = cv2.resize(keep_image,(512,512),interpolation=cv2.INTER_LANCZOS4)
        keep = torch.from_numpy(keep_image.copy()).permute(2,0,1).float()/255
        keep_gpu = keep.to(device=device, dtype=torch.float16)
        generator = torch.Generator(device=device).manual_seed(int(seed))
        noise = torch.randn((1,4,1,64,64), device=device, dtype=torch.float16, generator=generator)
        progress = ProgressBar(math.ceil(len(faces)/16)*20)
        results = []
        lower_mask = lower_face_mask(faces.shape[1], faces.shape[2])
        with torch.inference_mode():
            for start in range(0, len(faces), 16):
                mm.throw_exception_if_processing_interrupted()
                stop = min(start+16, len(faces)); count = stop-start
                if not activity[start:stop].any():
                    results.append(neutral[start:stop]); progress.update(20); continue
                reference = pixels[start:stop]
                if count < 16: reference = torch.cat((reference, reference[-1:].repeat(16-count,1,1,1)))
                vae.to(device)
                masked, originals = [], []
                for frame in reference:
                    mm.throw_exception_if_processing_interrupted()
                    value = frame[None].to(device=device, dtype=torch.float16)
                    masked.append((vae.encode(value*keep_gpu).latent_dist.sample(generator=generator)-shift)*scale)
                    originals.append((vae.encode(value).latent_dist.sample(generator=generator)-shift)*scale)
                masked = torch.cat(masked).permute(1,0,2,3)[None]
                originals = torch.cat(originals).permute(1,0,2,3)[None]
                mask = F.interpolate(keep_gpu[:1][None], (64,64), mode="nearest")[:,:,None].repeat(1,1,16,1,1)
                vae.to("cpu"); mm.soft_empty_cache()
                embeds = torch.stack(windows[start:stop])
                if count < 16: embeds = torch.cat((embeds, embeds[-1:].repeat(16-count,1,1)))
                embeds = embeds.to(device=device, dtype=torch.float16)
                null = torch.zeros_like(embeds)
                scheduler.set_timesteps(20, device=device)
                latents = noise.repeat(1,1,16,1,1)*scheduler.init_noise_sigma
                for timestep in scheduler.timesteps:
                    mm.throw_exception_if_processing_interrupted()
                    value = torch.cat((scheduler.scale_model_input(latents,timestep), mask, masked, originals),dim=1)
                    unconditional = unet(value,timestep,encoder_hidden_states=null).sample
                    conditional = unet(value,timestep,encoder_hidden_states=embeds).sample
                    prediction = unconditional+1.5*(conditional-unconditional)
                    latents = scheduler.step(prediction,timestep,latents,eta=0).prev_sample
                    progress.update(1)
                vae.to(device)
                decoded = []
                for latent in latents[0].permute(1,0,2,3)[:count]:
                    mm.throw_exception_if_processing_interrupted()
                    decoded.append(vae.decode(latent[None]/scale+shift).sample[0].float().cpu())
                vae.to("cpu"); mm.soft_empty_cache()
                decoded = torch.stack(decoded)*(1-keep)+reference[:count]*keep
                decoded = (decoded/2+.5).clamp(0,1).permute(0,2,3,1)
                frames = []
                for offset, image in enumerate(decoded):
                    index = start+offset
                    if not activity[index]: frames.append(neutral[index]); continue
                    plane = cv2.resize(image.numpy(),size,interpolation=cv2.INTER_LANCZOS4)
                    restored = cv2.warpAffine(plane,cv2.invertAffineTransform(matrices[index]),
                        (faces.shape[2],faces.shape[1]),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
                    frames.append(faces[index].cpu().float()*(1-lower_mask)+torch.from_numpy(restored.copy())*lower_mask)
                results.append(torch.stack(frames).clamp(0,1))
        return torch.cat(results)
    finally:
        for item in (unet, vae):
            if item is not None and not any(p.is_meta for p in item.parameters()): item.to("cpu")
        del unet, vae
        gc.collect()
        mm.soft_empty_cache()
