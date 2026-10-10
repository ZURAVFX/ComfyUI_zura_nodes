"""Local MuseTalk speech guidance, exposed as editable Zura graph nodes.

Uses the published MuseTalk 1.5 latent/audio interface with diffusers and
transformers. Face detection stays in the existing native preprocessing nodes.
No TTS, voice conversion, remote inference or automatic model download occurs.
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import torch
import torch.nn.functional as F

FILES = ("MuseTalk/musetalkV15/musetalk.json", "MuseTalk/musetalkV15/unet.pth",
         "sd-vae-ft-mse/config.json", "sd-vae-ft-mse/diffusion_pytorch_model.safetensors",
         "whisper-tiny/config.json", "whisper-tiny/model.safetensors",
         "whisper-tiny/preprocessor_config.json")


def bundle_path():
    import folder_paths
    candidates = [Path(folder_paths.models_dir) / "zura_speech"]
    for path in getattr(folder_paths, "folder_names_and_paths", {}).get("vae", ([],))[0]:
        candidates.append(Path(path).parent / "zura_speech")
    return next((p for p in candidates if all((p / name).is_file() for name in FILES)), candidates[0])


def readiness():
    base = bundle_path()
    missing = [name for name in FILES if not (base / name).is_file()]
    packages = [name for name in ("diffusers", "transformers", "torchaudio", "safetensors")
                if importlib.util.find_spec(name) is None]
    return {"ready": not missing and not packages, "missing_files": missing,
            "missing_packages": packages, "model": "MuseTalk 1.5"}


def fit_speech(audio, frames, fps):
    if not math.isfinite(float(fps)) or not 1 <= fps <= 120:
        raise ValueError("Choose a frame rate between 1 and 120.")
    if not isinstance(audio, dict) or "waveform" not in audio:
        raise ValueError("Connect your generated speech or upload a reference audio track.")
    rate = int(audio["sample_rate"])
    x = audio["waveform"].detach().cpu().float()
    if rate <= 0 or x.ndim != 3 or x.shape[0] != 1 or x.shape[1] < 1 or not torch.isfinite(x).all():
        raise ValueError("Speech guidance requires one valid audio track.")
    count = round(frames / fps * rate)
    return {"waveform": F.pad(x[..., :count], (0, max(0, count - x.shape[-1]))), "sample_rate": rate}


def speech_windows(features, count, fps):
    """MuseTalk's 50 Hz, ten-step, all-layer Whisper conditioning at actual fps."""
    # Preserve its training padding convention; do not force 25 fps onto 24 fps.
    pad = math.ceil(50 / fps)
    padded = F.pad(features, (0, 0, 0, 0, 2 * pad, 6 * pad))
    for i in range(count):
        start = math.floor(i * 50 / fps)
        value = padded[start:start + 10]
        if value.shape[0] != 10:
            value = F.pad(value, (0, 0, 0, 0, 0, 10 - value.shape[0]))
        yield value.flatten(0, 1)


def lower_face_mask(height, width):
    """Feather the lower face only; leave the original eyes and crop border."""
    y, x = torch.meshgrid(torch.linspace(0, 1, height), torch.linspace(0, 1, width), indexing="ij")
    distance = ((x - .5) / .44).square() + ((y - .72) / .31).square()
    ellipse = ((1 - distance) / .2).clamp(0, 1)
    top = ((y - .48) / .08).clamp(0, 1)
    bottom = ((.98 - y) / .08).clamp(0, 1)
    return (ellipse * top * bottom)[..., None]


def positional_encoding(length, width, device, dtype):
    position = torch.arange(length, device=device, dtype=torch.float32)[:, None]
    frequency = torch.exp(torch.arange(0, width, 2, device=device).float() * (-math.log(10000) / width))
    result = torch.empty(length, width, device=device)
    result[:, 0::2] = torch.sin(position * frequency)
    result[:, 1::2] = torch.cos(position * frequency)
    return result.to(dtype)


def animate_faces(faces, audio, model, fps=24, seed=42, batch_size=4):
    if faces.ndim != 4 or faces.shape[-1] != 3 or not len(faces) or not torch.isfinite(faces).all():
        raise ValueError("Speech guidance needs valid RGB face crops.")
    audio = fit_speech(audio, len(faces), fps)
    from diffusers import AutoencoderKL, UNet2DConditionModel
    from transformers import WhisperFeatureExtractor, WhisperModel
    import torchaudio.functional as AF
    import comfy.model_management as mm
    from comfy.utils import ProgressBar

    base = Path(model["path"])
    if not all((base / name).is_file() for name in FILES):
        raise ValueError("Install Zura speech models with Setup_Speech_Windows.cmd, then try again.")
    device = mm.get_torch_device()
    dtype = torch.float16 if device.type == "cuda" else torch.float32
    mm.free_memory(5 * 1024 ** 3, device)
    vae = unet = whisper = None
    try:
        vae = AutoencoderKL.from_pretrained(str(base / "sd-vae-ft-mse"), local_files_only=True,
                torch_dtype=dtype).to(device).eval()
        config = json.loads((base / "MuseTalk/musetalkV15/musetalk.json").read_text())
        unet = UNet2DConditionModel(**config)
        unet.load_state_dict(torch.load(base / "MuseTalk/musetalkV15/unet.pth", map_location="cpu", weights_only=True))
        unet = unet.to(device=device, dtype=dtype).eval()
        whisper = WhisperModel.from_pretrained(str(base / "whisper-tiny"), local_files_only=True,
                torch_dtype=dtype).to(device).eval()
        extractor = WhisperFeatureExtractor.from_pretrained(str(base / "whisper-tiny"), local_files_only=True)
        wave = AF.resample(audio["waveform"][0].mean(0), audio["sample_rate"], 16000)
        features = []
        with torch.inference_mode():
            for start in range(0, len(wave), 30 * 16000):
                mm.throw_exception_if_processing_interrupted()
                mel = extractor(wave[start:start + 30 * 16000].numpy(), sampling_rate=16000,
                                return_tensors="pt").input_features.to(device=device, dtype=dtype)
                layers = whisper.encoder(mel, output_hidden_states=True).hidden_states
                features.append(torch.stack(layers, dim=2)[0].cpu())
            features = torch.cat(features)[:max(1, math.floor(len(wave) / 16000 * 50))]
            whisper.to("cpu")
            windows = iter(speech_windows(features, len(faces), fps))
            pe = positional_encoding(50, 384, device, dtype)
            generator = torch.Generator(device=device).manual_seed(seed)
            progress = ProgressBar(len(faces))
            results = []
            mask = lower_face_mask(int(faces.shape[1]), int(faces.shape[2]))
            for start in range(0, len(faces), batch_size):
                mm.throw_exception_if_processing_interrupted()
                original = faces[start:start + batch_size].detach().cpu().float().clamp(0, 1)
                pixels = F.interpolate(original.permute(0, 3, 1, 2), (256, 256), mode="bicubic",
                                       align_corners=False).clamp(0, 1).to(device=device, dtype=dtype)
                hidden = pixels.clone()
                hidden[:, :, 128:] = 0
                scale = vae.config.scaling_factor
                latent = torch.cat([vae.encode(hidden * 2 - 1).latent_dist.sample(generator=generator) * scale,
                                    vae.encode(pixels * 2 - 1).latent_dist.sample(generator=generator) * scale], dim=1)
                speech = torch.stack([next(windows) for _ in range(len(original))]).to(device=device, dtype=dtype)
                prediction = unet(latent, torch.zeros(1, device=device, dtype=torch.long),
                                  encoder_hidden_states=speech + pe).sample
                rgb = (vae.decode(prediction / scale).sample / 2 + .5).clamp(0, 1).float().cpu()
                rgb = F.interpolate(rgb, original.shape[1:3], mode="bicubic", align_corners=False)
                rgb = rgb.permute(0, 2, 3, 1).clamp(0, 1)
                results.append(original * (1 - mask) + rgb * mask)
                progress.update(len(original))
            return torch.cat(results)
    finally:
        for item in (vae, unet, whisper):
            if item is not None:
                item.to("cpu")
        # Avoid holding unmanaged speech models on the GPU during Wan sampling.
        del vae, unet, whisper
        mm.soft_empty_cache()


class ZuraSpeechModelLoader:
    CATEGORY = "Zura/Audio"
    FUNCTION = "load"
    RETURN_TYPES = ("ZURA_SPEECH_MODEL",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": (["MuseTalk 1.5"],)}}
    def load(self, model):
        state = readiness()
        if not state["ready"]:
            raise ValueError("Speech lip sync is not installed. Run Setup_Speech_Windows.cmd. Missing: " +
                             ", ".join(state["missing_files"] + state["missing_packages"]))
        return ({"path": str(bundle_path()), "model": model},)


class ZuraSpeechFaceGuide:
    CATEGORY = "Zura/Audio"
    FUNCTION = "animate"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("speech_faces",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("ZURA_SPEECH_MODEL",), "face_images": ("IMAGE",), "audio": ("AUDIO",),
            "fps": ("FLOAT", {"default": 24, "min": 1, "max": 120}),
            "seed": ("INT", {"default": 42, "min": 0, "max": 0xffffffffffffffff}),
            "batch_size": ("INT", {"default": 4, "min": 1, "max": 16})}}
    def animate(self, model, face_images, audio, fps=24, seed=42, batch_size=4):
        return (animate_faces(face_images, audio, model, fps, seed, batch_size),)


class ZuraSpeechComposeVideo:
    CATEGORY = "Zura/Audio"
    FUNCTION = "compose"
    RETURN_TYPES = ("VIDEO",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "speech_faces": ("IMAGE",),
            # WanAnimatePreprocess's native socket includes this trailing comma.
            "face_boxes": ("BBOX,",), "reference_video": ("VIDEO",),
            "fps": ("FLOAT", {"default": 24, "min": 1, "max": 120})}}
    def compose(self, images, speech_faces, face_boxes, reference_video, fps=24):
        from ..video import video_components, video_output
        if len(images) != len(speech_faces) or len(face_boxes) != len(images):
            raise ValueError("Speech faces and detections must cover every generated frame.")
        _, audio, _ = video_components(reference_video)
        audio = fit_speech(audio, len(images), fps)
        result = images.detach().cpu().float().clone()
        for i, box in enumerate(face_boxes):
            x1, y1, x2, y2 = map(int, box)
            if not (0 <= x1 < x2 <= images.shape[2] and 0 <= y1 < y2 <= images.shape[1]):
                raise ValueError(f"No usable face on frame {i + 1}. Lip sync needs a visible human face.")
            face = F.interpolate(speech_faces[i:i + 1].permute(0, 3, 1, 2), (y2 - y1, x2 - x1),
                                 mode="bicubic", align_corners=False)[0].permute(1, 2, 0).clamp(0, 1)
            # The crop already retains its border and eyes. A second feather
            # confines the finish to this generated character's lower face.
            mask = lower_face_mask(y2 - y1, x2 - x1)
            original = result[i, y1:y2, x1:x2]
            result[i, y1:y2, x1:x2] = original * (1 - mask) + face * mask
        return (video_output(result, audio, fps),)


def add_finish(graph, project):
    """Common optional speech finish; no remote spending or engine substitution."""
    if not project.get("audio") or not project["config"].get("lip_sync"):
        return graph
    exports = [(key, n) for key, n in graph.items() if n["class_type"] == "GenjRestoreSoundtrack"]
    if not exports:
        return graph
    shot = next(key for key, n in graph.items() if n["class_type"] == "GenjLoadReviewedShot")
    from .wan import WAN_MODELS
    def node(key, typ, **inputs):
        graph[key] = {"class_type": typ, "inputs": inputs}
        return [key, 0]
    model = node("zura_speech_model", "ZuraSpeechModelLoader", model="MuseTalk 1.5")
    reference = node("zura_speech_reference", "GetVideoComponents", video=[shot, 0])
    detector = node("zura_speech_detector", "OnnxDetectionModelLoader", vitpose_model=WAN_MODELS["wan_pose"][1],
                    yolo_model=WAN_MODELS["wan_detector"][1], onnx_device="CPUExecutionProvider")
    for index, (_, export) in enumerate(exports):
        prefix = "zura_speech_" + str(index)
        images = node(prefix + "frames", "GetVideoComponents", video=export["inputs"]["video"])
        size = node(prefix + "size", "GetImageSize", image=images)
        detection = node(prefix + "detect", "PoseAndFaceDetection", model=detector, images=images,
                         width=size, height=[prefix + "size", 1], face_padding=0)
        faces = node(prefix + "faces", "ZuraSpeechFaceGuide", model=model,
                     face_images=[prefix + "detect", 1], audio=["zura_speech_reference", 1],
                     fps=[prefix + "frames", 2], seed=project["config"]["seed"], batch_size=4)
        video = node(prefix + "video", "ZuraSpeechComposeVideo", images=images, speech_faces=faces,
                     face_boxes=[prefix + "detect", 4], reference_video=[shot, 0], fps=[prefix + "frames", 2])
        export["inputs"]["video"] = video
    return graph


NODE_CLASS_MAPPINGS = {c.__name__: c for c in (ZuraSpeechModelLoader, ZuraSpeechFaceGuide, ZuraSpeechComposeVideo)}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraSpeechModelLoader": "Zura · Speech Lip Sync Model",
    "ZuraSpeechFaceGuide": "Zura · Mouth Motion from Audio", "ZuraSpeechComposeVideo": "Zura · Finish Speech Lip Sync"}
