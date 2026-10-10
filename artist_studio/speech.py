"""Local speech guidance, exposed as editable Zura graph nodes.

Uses the published LatentSync 1.6 or MuseTalk 1.5 latent/audio interface.
Face detection stays in the existing native preprocessing nodes.
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
MODELS = ("Automatic", "LatentSync 1.6", "MuseTalk 1.5")


def model_files(model):
    if model == "LatentSync 1.6":
        from .speech_latentsync import FILES as latent_files
        return latent_files
    return FILES


def bundle_path(model="MuseTalk 1.5"):
    import folder_paths
    candidates = [Path(folder_paths.models_dir) / "zura_speech"]
    for path in getattr(folder_paths, "folder_names_and_paths", {}).get("vae", ([],))[0]:
        candidates.append(Path(path).parent / "zura_speech")
    return next((p for p in candidates if all((p / name).is_file() for name in model_files(model))), candidates[0])


def readiness(model="Automatic"):
    if model not in MODELS:
        raise ValueError("Choose Automatic, LatentSync 1.6 or MuseTalk 1.5 for lip sync.")
    if model == "Automatic":
        sharp = readiness("LatentSync 1.6")
        return sharp if sharp["ready"] else readiness("MuseTalk 1.5")
    base = bundle_path(model)
    missing = [name for name in model_files(model) if not (base / name).is_file()]
    dependencies = ("diffusers", "torchaudio", "safetensors", "accelerate", "einops", "cv2", "numpy")
    if model == "MuseTalk 1.5": dependencies += ("transformers",)
    packages = [name for name in dependencies
                if importlib.util.find_spec(name) is None]
    device_issue = model == "LatentSync 1.6" and not torch.cuda.is_available()
    return {"ready": not missing and not packages and not device_issue, "missing_files": missing,
            "missing_packages": packages, "model": model,
            "device_requirement": "CUDA GPU" if device_issue else ""}


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


def speech_activity(audio, frames, fps):
    """Quiet sections stay at rest, without looking ahead into future speech.

    Ten millisecond energy bins retain quiet voices and stereo tracks. A short
    release bridges consonants and pauses inside a word; it never advances an
    onset. This is a silence gate for dialogue, not a music/speech classifier.
    """
    audio = fit_speech(audio, frames, fps)
    rate = audio["sample_rate"]
    wave = audio["waveform"][0]
    step = max(1, round(rate / 100))
    padded = F.pad(wave, (0, (-wave.shape[-1]) % step))
    energy = padded.square().reshape(wave.shape[0], -1, step).mean((0, 2)).sqrt()
    threshold = max(1e-5, float(energy.max()) * .02)
    active = (energy >= threshold).float()
    # Causal 120 ms release: no mouth motion before the selected audio starts.
    active = F.max_pool1d(F.pad(active[None, None], (12, 0)), 13, stride=1)[0, 0]
    return torch.tensor([float(active[min(len(active) - 1, math.floor(i / fps * rate / step))])
                         for i in range(frames)])


def native_face_landmarks(meta):
    """Normalise the native detector's face layouts to the 68-point convention.

    WanAnimatePreprocess's split_kp2ds_for_aa returns 69 entries: its foot
    keypoint 22 precedes the 68 face landmarks. Other native paths return 68
    points or append the two body eye points after those 68 landmarks.
    """
    raw = meta.get("keypoints_face")
    value = torch.as_tensor(raw if raw is not None else [], dtype=torch.float32)
    if value.ndim == 2 and value.shape[0] == 69:
        value = value[1:]
    return value[:68] if value.ndim == 2 else value


def resting_faces(faces, pose_data=None, face_boxes=None):
    """Remove the old mouth performance, retaining each frame's head and eyes.

    Use the least open source mouth as a still visual reference. Native face
    landmarks align that reference using eyes/nose, never the moving lips. The
    speech network can then animate a stable identity reference instead of
    receiving the old dialogue in its unmasked latent input.
    """
    import cv2
    import numpy as np

    faces = faces.detach().cpu().float().clamp(0, 1)
    height, width = faces.shape[1:3]
    metas = (pose_data or {}).get("pose_metas_original", [])
    anchors, openness = [], []
    for i in range(len(faces)):
        meta = metas[i] if i < len(metas) else {}
        value = native_face_landmarks(meta)
        valid = (face_boxes is not None and i < len(face_boxes) and value.ndim == 2
                 and value.shape[0] >= 68 and value.shape[1] >= 2
                 and torch.isfinite(value).all() and meta.get("width", 0) > 0
                 and meta.get("height", 0) > 0)
        if valid and value.shape[1] >= 3:
            valid = float(value[27:68, 2].mean()) >= .3
        if not valid:
            anchors.append(None); openness.append(float("inf"))
            continue
        xy = value[:68, :2].clone() * torch.tensor([meta["width"], meta["height"]])
        x1, y1, x2, y2 = face_boxes[i]
        if not (x2 > x1 and y2 > y1):
            anchors.append(None); openness.append(float("inf"))
            continue
        xy = (xy - torch.tensor([x1, y1])) * torch.tensor([width / (x2-x1), height / (y2-y1)])
        eye_nose = torch.stack((xy[36:42].mean(0), xy[42:48].mean(0), xy[27:31].mean(0)))
        mouth_width = torch.linalg.vector_norm(xy[48] - xy[54]).clamp(min=1)
        gap = torch.linalg.vector_norm(xy[[61, 62, 63]] - xy[[67, 66, 65]], dim=1).mean()
        anchors.append(eye_nose); openness.append(float(gap / mouth_width))
    anchor = min(range(len(faces)), key=lambda i: openness[i])
    source = faces[anchor].numpy()
    mask = lower_face_mask(height, width)
    result = []
    for i, face in enumerate(faces):
        resting = source
        if anchors[anchor] is not None and anchors[i] is not None:
            # Solve a similarity transform, preserving the reference mouth shape.
            a = anchors[anchor].numpy(); b = anchors[i].numpy()
            rows = np.zeros((len(a)*2, 4), dtype=np.float64)
            rows[::2, 0], rows[::2, 1], rows[::2, 2] = a[:, 0], -a[:, 1], 1
            rows[1::2, 0], rows[1::2, 1], rows[1::2, 3] = a[:, 1], a[:, 0], 1
            if np.linalg.matrix_rank(rows) == 4:
                u, v, tx, ty = np.linalg.lstsq(rows, b.reshape(-1), rcond=None)[0]
                scale = math.hypot(u, v)
                if .5 <= scale <= 2:
                    matrix = np.array([[u, -v, tx], [v, u, ty]], dtype=np.float32)
                    resting = cv2.warpAffine(source, matrix, (width, height),
                                             flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
        result.append(face * (1-mask) + torch.from_numpy(resting.copy()) * mask)
    return torch.stack(result)


def mouth_finish_mask(height, width, box, image_shape, pose_meta=None):
    """Keep the generated cheeks/chin; feather only around the moving lips."""
    # Native ViTPose provides the 68-point face convention in image coordinates.
    # Older saved graphs can omit it and use a conservative crop-relative area.
    cx, cy, rx, ry = .5, .72, .30, .18
    if pose_meta is not None:
        points = native_face_landmarks(pose_meta)
        if points.ndim == 2 and points.shape[0] >= 68 and points.shape[1] >= 2:
            lips = points[48:68, :2].clone()
            full_height, full_width = image_shape[:2]
            lips *= torch.tensor([full_width, full_height])
            lips -= torch.tensor([box[0], box[1]])
            lips /= torch.tensor([width, height])
            if torch.isfinite(lips).all() and (lips >= 0).all() and (lips <= 1).all():
                low, high = lips.amin(0), lips.amax(0)
                centre = (low + high) / 2
                extent = high - low
                if extent[0] > .06:
                    cx, cy = map(float, centre)
                    rx = max(.18, min(.42, float(extent[0]) * .75))
                    # Leave room for the new voice to open the source mouth.
                    ry = max(.13, min(.25, float(extent[1]) * .85 + .055))
    y, x = torch.meshgrid(torch.linspace(0, 1, height), torch.linspace(0, 1, width), indexing="ij")
    distance = ((x - cx) / rx).square() + ((y - cy) / ry).square()
    mask = ((1 - distance) / .38).clamp(0, 1)
    # Always protect eyes and crop edges, including unreliable profile landmarks.
    return mask[..., None] * lower_face_mask(height, width)


def recover_mouth_detail(face, strength=.35):
    """A bounded unsharp filter, with no generated texture or original lip ghost."""
    strength = float(strength)
    if not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("Mouth detail must be between 0 and 1.")
    if strength == 0:
        return face
    pixels = face.permute(2, 0, 1)[None]
    kernel = face.new_tensor([1, 4, 6, 4, 1]) / 16
    kernel = (kernel[:, None] * kernel[None, :])[None, None].expand(3, 1, 5, 5)
    blurred = F.conv2d(F.pad(pixels, (2, 2, 2, 2), mode="replicate"), kernel, groups=3)
    detail = (pixels - blurred).clamp(-.04, .04)
    return (pixels + strength * detail).clamp(0, 1)[0].permute(1, 2, 0)


def positional_encoding(length, width, device, dtype):
    position = torch.arange(length, device=device, dtype=torch.float32)[:, None]
    frequency = torch.exp(torch.arange(0, width, 2, device=device).float() * (-math.log(10000) / width))
    result = torch.empty(length, width, device=device)
    result[:, 0::2] = torch.sin(position * frequency)
    result[:, 1::2] = torch.cos(position * frequency)
    return result.to(dtype)


def animate_faces(faces, audio, model, fps=24, seed=42, batch_size=4, pose_data=None, face_boxes=None):
    if faces.ndim != 4 or faces.shape[-1] != 3 or not len(faces) or not torch.isfinite(faces).all():
        raise ValueError("Speech guidance needs valid RGB face crops.")
    if model.get("model") == "LatentSync 1.6":
        from .speech_latentsync import animate
        return animate(faces, audio, model, fps, seed, pose_data, face_boxes)
    audio = fit_speech(audio, len(faces), fps)
    activity = speech_activity(audio, len(faces), fps)
    neutral = resting_faces(faces, pose_data, face_boxes)
    if not activity.any():
        return neutral
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
                reference = neutral[start:start + batch_size]
                pixels = F.interpolate(reference.permute(0, 3, 1, 2), (256, 256), mode="bicubic",
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
                speaking = activity[start:start + len(original), None, None, None]
                # Whisper has future context. Explicitly keep silence at rest.
                animated = original * (1 - mask) + rgb * mask
                results.append(speaking * animated + (1-speaking) * reference)
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
        return {"required": {"model": (list(MODELS), {"default": "Automatic"})}}
    def load(self, model):
        state = readiness(model)
        if not state["ready"]:
            if state.get("device_requirement"):
                raise ValueError("Sharp lip sync needs a CUDA GPU. Select MuseTalk 1.5 for another device.")
            raise ValueError("Speech lip sync is not installed. Run Setup_Speech_Windows.cmd. Missing: " +
                             ", ".join(state["missing_files"] + state["missing_packages"]))
        return ({"path": str(bundle_path(state["model"])), "model": state["model"]},)


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
            "batch_size": ("INT", {"default": 4, "min": 1, "max": 16,
                "tooltip": "MuseTalk batch size. Sharp lip sync uses fixed 16-frame windows."})},
            "optional": {"pose_data": ("POSEDATA",), "face_boxes": ("BBOX,",)}}
    def animate(self, model, face_images, audio, fps=24, seed=42, batch_size=4, pose_data=None, face_boxes=None):
        return (animate_faces(face_images, audio, model, fps, seed, batch_size, pose_data, face_boxes),)


class ZuraSpeechComposeVideo:
    CATEGORY = "Zura/Audio"
    FUNCTION = "compose"
    RETURN_TYPES = ("VIDEO",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"images": ("IMAGE",), "speech_faces": ("IMAGE",),
            # WanAnimatePreprocess's native socket includes this trailing comma.
            "face_boxes": ("BBOX,",), "reference_video": ("VIDEO",),
            "fps": ("FLOAT", {"default": 24, "min": 1, "max": 120})},
            "optional": {"pose_data": ("POSEDATA",),
                         "mouth_detail": ("FLOAT", {"default": .35, "min": 0, "max": 1, "step": .05})}}
    def compose(self, images, speech_faces, face_boxes, reference_video, fps=24, pose_data=None, mouth_detail=.35):
        from ..video import video_components, video_output
        if len(images) != len(speech_faces) or len(face_boxes) != len(images):
            raise ValueError("Speech faces and detections must cover every generated frame.")
        _, audio, _ = video_components(reference_video)
        audio = fit_speech(audio, len(images), fps)
        result = images.detach().cpu().float().clone()
        metas = (pose_data or {}).get("pose_metas_original", [])
        for i, box in enumerate(face_boxes):
            x1, y1, x2, y2 = map(int, box)
            if not (0 <= x1 < x2 <= images.shape[2] and 0 <= y1 < y2 <= images.shape[1]):
                raise ValueError(f"No usable face on frame {i + 1}. Lip sync needs a visible human face.")
            face = F.interpolate(speech_faces[i:i + 1].permute(0, 3, 1, 2), (y2 - y1, x2 - x1),
                                 mode="bicubic", align_corners=False)[0].permute(1, 2, 0).clamp(0, 1)
            face = recover_mouth_detail(face, mouth_detail)
            meta = metas[i] if i < len(metas) else None
            mask = mouth_finish_mask(y2 - y1, x2 - x1, box, images.shape[1:], meta)
            original = result[i, y1:y2, x1:x2]
            result[i, y1:y2, x1:x2] = original * (1 - mask) + face * mask
        return (video_output(result, audio, fps),)


def add_finish(graph, project, *, native_speech=False):
    """Common optional speech finish; no remote spending or engine substitution."""
    if not project.get("audio") or not project["config"].get("lip_sync"):
        return graph
    if native_speech and not project["config"].get("refine_lips"):
        return graph
    exports = [(key, n) for key, n in graph.items() if n["class_type"] == "GenjRestoreSoundtrack"]
    if not exports:
        return graph
    shot = next(key for key, n in graph.items() if n["class_type"] == "GenjLoadReviewedShot")
    from .wan import WAN_MODELS
    def node(key, typ, **inputs):
        graph[key] = {"class_type": typ, "inputs": inputs}
        return [key, 0]
    model = node("zura_speech_model", "ZuraSpeechModelLoader", model="Automatic")
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
                     fps=[prefix + "frames", 2], seed=project["config"]["seed"], batch_size=4,
                     pose_data=[prefix + "detect", 0], face_boxes=[prefix + "detect", 4])
        video = node(prefix + "video", "ZuraSpeechComposeVideo", images=images, speech_faces=faces,
                     face_boxes=[prefix + "detect", 4], pose_data=[prefix + "detect", 0],
                     reference_video=[shot, 0], fps=[prefix + "frames", 2], mouth_detail=.35)
        export["inputs"]["video"] = video
    return graph


NODE_CLASS_MAPPINGS = {c.__name__: c for c in (ZuraSpeechModelLoader, ZuraSpeechFaceGuide, ZuraSpeechComposeVideo)}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraSpeechModelLoader": "Zura · Speech Lip Sync Model",
    "ZuraSpeechFaceGuide": "Zura · Mouth Motion from Audio", "ZuraSpeechComposeVideo": "Zura · Finish Speech Lip Sync"}
