"""Two-pass, source-audio-locked multicamera planning for local MiniMax H3.

The director expands to *native* ComfyUI warp, conditioning and sampler nodes.
Only angles referenced by the shot plan are expanded/evaluated.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import folder_paths
import torch
from PIL import Image, ImageDraw, ImageOps


# Column = camera side; row = framing. CrossView's current LoRA does not follow
# distance reliably, so shot size is a *visual proposal*, not a dolly command.
# Keep distance at the source plane and reserve vertical lens shift for safe
# headroom, especially on the close row.
ANGLES = (
    (1, "Left · wide", -30, 1.0, 1.5),
    (2, "Front · wide", 0, 1.0, 1.5),
    (3, "Right · wide", 30, 1.0, 1.5),
    (4, "Left · medium", -30, 1.0, 4.5),
    (5, "Front · medium", 0, 1.0, 4.5),
    (6, "Right · medium", 30, 1.0, 4.5),
    (7, "Left · close", -30, 1.0, 7.5),
    (8, "Front · close", 0, 1.0, 7.5),
    (9, "Right · close", 30, 1.0, 7.5),
)
ANGLE_BY_ID = {a[0]: a for a in ANGLES}


def _key(value):
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value).strip()).strip("-")[:48]
    if not value:
        raise ValueError("Set a project name before planning angles.")
    return value


def _signature(frames):
    if frames is None or frames.ndim != 4 or frames.shape[0] < 1:
        raise ValueError("Connect the trimmed source video frames.")
    digest = hashlib.sha256()
    digest.update(str(tuple(frames.shape)).encode())
    for i in {0, frames.shape[0] // 2, frames.shape[0] - 1}:
        sample = (frames[i, ::32, ::32, :3].detach().float().cpu().clamp(0, 1) * 255).byte()
        digest.update(sample.numpy().tobytes())
    return digest.hexdigest()[:16]


def _project_dir(project_name, signature):
    base = Path(folder_paths.get_output_directory()).resolve() / "zura_multicam_v3"
    path = (base / _key(project_name) / signature).resolve()
    if base not in path.parents:
        raise ValueError("Invalid angle project path.")
    return path


def _to_pil(image):
    if image.ndim == 4:
        image = image[0]
    array = (image.detach().float().cpu().clamp(0, 1).numpy() * 255).round().astype("uint8")
    return Image.fromarray(array[:, :, :3], "RGB")


def _load_image(path):
    import numpy as np
    with Image.open(path) as src:
        array = np.asarray(src.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def _shot_ids(raw, count):
    try:
        ids = json.loads(raw) if str(raw).lstrip().startswith("[") else [int(x.strip()) for x in str(raw).split(",") if x.strip()]
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Shot choices must be a comma-separated list of angle numbers 0–9.") from exc
    if not isinstance(ids, list) or any(type(v) is not int or v not in range(10) for v in ids):
        raise ValueError("Shot choices must contain only whole numbers 0–9 (0 = source).")
    if len(ids) != count:
        raise ValueError(f"This clip needs {count} shot choices; the planner currently has {len(ids)}. Re-run Plan angles, then assign every shot.")
    return ids


def _shot_prompts(raw, count, planning=False):
    try:
        prompts = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Shot prompts must be a JSON list of text prompts.") from exc
    if not isinstance(prompts, list) or any(not isinstance(p, str) for p in prompts):
        raise ValueError("Shot prompts must be a JSON list of text prompts.")
    if len(prompts) != count:
        if not planning and prompts:
            raise ValueError(f"This clip needs {count} shot prompts; re-run Plan angles.")
        prompts = (prompts + [""] * count)[:count]
    return [p.strip()[:1000] for p in prompts]


def _plan(project_name, frames, frames_per_shot, choices, planning=False, shot_prompts="[]"):
    n = int(frames.shape[0])
    f = int(frames_per_shot)
    if not 12 <= f <= 3600:
        raise ValueError("Frames per shot must be 12–3600 at 24 fps.")
    count = math.ceil(n / f)
    if count > 60:
        raise ValueError("This plan has over 60 shots. Increase frames per shot or trim the source.")
    try:
        ids = _shot_ids(choices, count)
    except ValueError:
        if not planning:
            raise
        # The artist may have just changed source length or shot duration.
        # Show the correct number of unassigned source slots instead of failing.
        ids = [0] * count
    return {
        "version": 3,
        "project": _key(project_name),
        "signature": _signature(frames),
        "frame_count": n,
        "frames_per_shot": f,
        "shot_count": count,
        "choices": ids,
        "shot_prompts": _shot_prompts(shot_prompts, count, planning),
    }


class ZuraSafeAnglePromptV3:
    """Add a camera-safe composition instruction to Qwen's angle token."""

    CATEGORY = "Zura/video/advanced"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "camera_prompt": ("STRING",),
            "shot_size": (["wide", "medium", "close"],),
        }}

    def build(self, camera_prompt, shot_size):
        prompt = str(camera_prompt).strip()
        if shot_size == "close":
            prompt = prompt.replace("close-up", "medium close-up")
            framing = "Upper chest and shoulders remain in frame."
        elif shot_size == "wide":
            framing = "Keep the whole upper body comfortably in frame."
        else:
            framing = "Keep the upper torso comfortably in frame."
        return (f"{prompt}. Keep the same person and room. {framing} "
                "Show the entire head and hair, with clear empty space above it. "
                "Centre the performer; do not crop the forehead, hair, chin or shoulders.",)


class ZuraSceneAnglePromptV4(ZuraSafeAnglePromptV3):
    """Ask Qwen to orbit the entire lit set, not just turn the performer."""

    def build(self, camera_prompt, shot_size):
        base = super().build(camera_prompt, shot_size)[0]
        base = base.replace("Keep the same person and room.",
            "Move the physical camera around the same performer inside the same three-dimensional room. "
            "Rotate the perspective of BOTH the person and the entire environment together. "
            "Wall panels, furniture, lamps and their shadows must show coherent parallax and change their "
            "relative positions behind the person. Do not reuse a static background or rotate only the person. "
            "Keep the room's identity and objects consistent, with lighting that follows the new viewpoint.")
        return (base,)


class ZuraMulticamStageV3:
    """One artist-facing switch shared by planning and render branches."""
    CATEGORY = "Zura/video"
    FUNCTION = "select"
    RETURN_TYPES = ("ZURA_MULTICAM_STAGE",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"stage": (["1 · Plan angles", "2 · Render multicam"],)}}
    def select(self, stage):
        return (stage,)


class ZuraPlanOnlyImageV3:
    """Block the Qwen branch and its preview outputs in the render pass."""
    CATEGORY = "Zura/video/advanced"
    FUNCTION = "select"
    RETURN_TYPES = ("IMAGE",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"stage": ("ZURA_MULTICAM_STAGE",)},
                "optional": {"image": ("IMAGE", {"lazy": True})}}
    def check_lazy_status(self, stage, image=None):
        return ["image"] if stage.startswith("1") and image is None else []
    def select(self, stage, image=None):
        if stage.startswith("2"):
            from comfy_execution.graph_utils import ExecutionBlocker
            return (ExecutionBlocker(None),)
        if image is None:
            raise ValueError("Connect the look image for the planning pass.")
        return (image,)


class ZuraAngleGalleryV3:
    """Persist nine candidate stills and expose an interactive gallery/timeline."""

    CATEGORY = "Zura/video"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "IMAGE", "ZURA_MULTICAM_STAGE")
    RETURN_NAMES = ("shot_plan", "contact_sheet", "stage")
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source_frames": ("IMAGE",),
            "stage": ("ZURA_MULTICAM_STAGE",),
            "project_name": ("STRING", {"default": "performance-v3"}),
            "frames_per_shot": ("INT", {"default": 24, "min": 12, "max": 3600, "step": 1}),
            "shot_choices": ("STRING", {"default": "0,6,0,4", "multiline": False}),
            "shot_prompts": ("STRING", {"default": "[]", "multiline": False}),
        }, "optional": {
            **{f"candidate_{i}": ("IMAGE", {"lazy": True}) for i in range(1, 10)},
            "look_prompt": ("STRING",),
            "look_enabled": ("BOOLEAN", {"default": False}),
        }}

    def check_lazy_status(self, stage, **kwargs):
        if stage.startswith("1"):
            return [f"candidate_{i}" for i in range(1, 10) if kwargs.get(f"candidate_{i}") is None]
        return []

    def run(self, source_frames, stage, project_name, frames_per_shot, shot_choices, shot_prompts="[]", **kwargs):
        plan = _plan(project_name, source_frames, frames_per_shot, shot_choices,
                     planning=stage.startswith("1"), shot_prompts=shot_prompts)
        look_enabled = bool(kwargs.get("look_enabled", False))
        look_prompt = str(kwargs.get("look_prompt") or "") if look_enabled else "original"
        look_hash = hashlib.sha256(look_prompt.encode("utf-8")).hexdigest()[:16]
        directory = _project_dir(plan["project"], plan["signature"])
        if stage.startswith("1"):
            directory.mkdir(parents=True, exist_ok=True)
            _to_pil(source_frames[:1]).save(directory / "source.png")
            for angle_id in range(1, 10):
                image = kwargs.get(f"candidate_{angle_id}")
                if image is None:
                    raise ValueError(f"Connect candidate {angle_id} before running Plan angles.")
                _to_pil(image).save(directory / f"angle_{angle_id}.png")
            (directory / "manifest.json").write_text(json.dumps({
                "version": 3, "project": plan["project"], "signature": plan["signature"],
                "angles": [list(a) for a in ANGLES],
                "look_hash": look_hash,
            }, indent=2), encoding="utf-8")
        else:
            manifest_path = directory / "manifest.json"
            if not manifest_path.is_file():
                raise ValueError("No saved angle previews for this source. Switch to Plan angles and run it first.")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("look_hash") not in (None, look_hash):
                raise ValueError("The studio/scene settings changed since the angle previews. Run Plan angles again.")
        for angle_id in range(1, 10):
            if not (directory / f"angle_{angle_id}.png").is_file():
                raise ValueError(f"Angle {angle_id} is missing. Re-run Plan angles.")

        sheet = Image.new("RGB", (960, 645), "#171b24")
        draw = ImageDraw.Draw(sheet)
        for angle_id, label, _, _, _ in ANGLES:
            col, row = (angle_id - 1) % 3, (angle_id - 1) // 3
            picture = ImageOps.fit(Image.open(directory / f"angle_{angle_id}.png").convert("RGB"), (308, 185))
            x, y = 8 + col * 318, 8 + row * 212
            sheet.paste(picture, (x, y))
            draw.text((x + 5, y + 189), f"{angle_id} · {label}", fill="white")
        import numpy as np
        sheet_tensor = torch.from_numpy(np.asarray(sheet, dtype=np.float32) / 255.0).unsqueeze(0)
        subfolder = f"zura_multicam_v3/{plan['project']}/{plan['signature']}"
        ui = {"zura_angle_gallery": [{
            "project": plan["project"], "signature": plan["signature"],
            "frame_count": plan["frame_count"], "frames_per_shot": plan["frames_per_shot"],
            "shot_count": plan["shot_count"], "choices": plan["choices"],
            "shot_prompts": plan["shot_prompts"],
            "look_enabled": look_enabled,
            "source": {"filename": "source.png", "subfolder": subfolder},
            "angles": [{"id": a[0], "label": a[1], "azimuth": a[2],
                        "filename": f"angle_{a[0]}.png", "subfolder": subfolder} for a in ANGLES],
        }]}
        return {"ui": ui, "result": (json.dumps(plan, separators=(",", ":")), sheet_tensor, stage)}


class ZuraSavedAngleV3:
    CATEGORY = "Zura/video/advanced"
    FUNCTION = "load"
    RETURN_TYPES = ("IMAGE",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project": ("STRING",), "signature": ("STRING",),
                             "angle_id": ("INT", {"default": 1, "min": 1, "max": 9})}}
    def load(self, project, signature, angle_id):
        if not re.fullmatch(r"[0-9a-f]{16}", signature):
            raise ValueError("Invalid source signature.")
        path = _project_dir(project, signature) / f"angle_{angle_id}.png"
        if not path.is_file():
            raise ValueError(f"Missing saved angle {angle_id}. Run Plan angles first.")
        return (_load_image(path),)


class ZuraAssembleMulticamV3:
    CATEGORY = "Zura/video/advanced"
    FUNCTION = "assemble"
    RETURN_TYPES = ("IMAGE",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"source_frames": ("IMAGE",), "plan_json": ("STRING",)},
                "optional": {**{f"angle_{i}": ("IMAGE",) for i in range(1, 10)},
                             **{f"shot_{i}": ("IMAGE",) for i in range(1, 61)},
                             "scene_frames": ("IMAGE",)}}
    def assemble(self, source_frames, plan_json, scene_frames=None, **takes):
        plan = json.loads(plan_json)
        if plan["signature"] != _signature(source_frames) or plan["frame_count"] != len(source_frames):
            raise ValueError("The source changed after angle planning. Re-run Plan angles.")
        length, stride = plan["frame_count"], plan["frames_per_shot"]
        # Match the generated canvas before concatenation. The final output
        # resolution/aspect control remains downstream in native ImageScale.
        example = scene_frames if scene_frames is not None else next(
            (v for k, v in takes.items() if k.startswith(("angle_", "shot_")) and v is not None), None)
        if scene_frames is not None:
            if len(scene_frames) < length:
                raise ValueError("The new-scene guide is shorter than the source video.")
            base_frames = scene_frames
        else:
            base_frames = source_frames
        if example is not None and base_frames.shape[1:3] != example.shape[1:3]:
            import torch.nn.functional as F
            target_h, target_w = int(example.shape[1]), int(example.shape[2])
            src_h, src_w = int(base_frames.shape[1]), int(base_frames.shape[2])
            target_ratio = target_w / target_h
            if src_w / src_h > target_ratio:
                crop_w = round(src_h * target_ratio)
                x = (src_w - crop_w) // 2
                base_frames = base_frames[:, :, x:x + crop_w, :]
            else:
                crop_h = round(src_w / target_ratio)
                y = (src_h - crop_h) // 2
                base_frames = base_frames[:, y:y + crop_h, :, :]
            base_frames = F.interpolate(base_frames.permute(0, 3, 1, 2),
                                          size=(target_h, target_w), mode="bilinear",
                                          align_corners=False).permute(0, 2, 3, 1)
        chunks = []
        for index, angle_id in enumerate(plan["choices"]):
            start, stop = index * stride, min((index + 1) * stride, length)
            segment = takes.get(f"shot_{index + 1}")
            video = segment if segment is not None else base_frames if angle_id == 0 else takes.get(f"angle_{angle_id}")
            needed = stop - start if segment is not None else stop
            if video is None or len(video) < needed:
                raise ValueError(f"Angle {angle_id} did not render enough frames for shot {index + 1} ({start}:{stop}).")
            chunks.append(video[:needed] if segment is not None else video[start:stop])
        out = torch.cat(chunks, dim=0)
        if len(out) != length:
            raise ValueError("Shot assembly changed the frame count.")
        return (out,)


class ZuraH3MulticamV3:
    """Lazy two-stage switch; render expands to native per-angle H3 chains."""
    CATEGORY = "Zura/video"
    FUNCTION = "render"
    RETURN_TYPES = ("IMAGE", "AUDIO")
    RETURN_NAMES = ("multicam_frames", "original_audio")

    @classmethod
    def INPUT_TYPES(cls):
        lazy = {name: (typ, {"lazy": True}) for name, typ in {
            "reference_video": "IMAGE", "moge_geometry": "MOGE_GEOMETRY", "model": "MODEL",
            "clip": "CLIP", "video_vae": "VAE", "audio_vae": "VAE",
            "scene_video": "IMAGE"}.items()}
        return {"required": {"source_frames": ("IMAGE",), "source_audio": ("AUDIO",),
                             "shot_plan": ("STRING",),
                             "stage": ("ZURA_MULTICAM_STAGE",),
                             "seed": ("INT", {"default": 42, "min": 0, "max": 0xffffffffffffffff}),
                             "steps": ("INT", {"default": 8, "min": 1, "max": 60}),
                             "prompt": ("STRING", {"multiline": True, "default":
                                 "crossview. <Picture 1> defines only the selected camera angle. "
                                 "Keep the exact performer, face, clothes, gestures and speaking performance "
                                 "from <Video 1>, with lips faithful to its original speech. Do not replace the performer."})},
                "optional": {**lazy, "look_enabled": ("BOOLEAN", {"default": False}),
                             "render_selected_intervals_only": ("BOOLEAN", {"default": False}),
                             "use_camera_warp_guide": ("BOOLEAN", {"default": True}),
                             "background_mode": ("STRING", {"default": "Keep source background"})}}

    def check_lazy_status(self, stage, shot_plan=None, **kwargs):
        if stage.startswith("1"):
            return []
        plan = json.loads(shot_plan) if shot_plan else {}
        scene_mode = bool(kwargs.get("look_enabled", False)) and kwargs.get("background_mode") != "Keep source background"
        if scene_mode and not getattr(self, "SCENE_START_GUIDE", False):
            raise ValueError("V3 preserves the source environment. Use V4 for a generated scene swap.")
        if scene_mode and any(v == 0 for v in plan.get("choices", [])):
            raise ValueError("Choose a generated angle for every V4 scene-swap shot; Original would reintroduce the source room.")
        if not any(v > 0 for v in plan.get("choices", [])):
            return []
        names = ["reference_video", "moge_geometry", "model", "clip", "video_vae", "audio_vae"]
        if scene_mode:
            names.remove("moge_geometry")
            names.extend(["pose_video", "model_patch"])
        elif not kwargs.get("use_camera_warp_guide", True):
            names.remove("moge_geometry")
        return [name for name in names
                if kwargs.get(name) is None]

    def render(self, source_frames, source_audio, shot_plan, stage, seed, steps, prompt,
               reference_video=None, moge_geometry=None, model=None, clip=None,
               video_vae=None, audio_vae=None, scene_video=None,
               pose_video=None, model_patch=None,
               look_enabled=False, background_mode="Keep source background",
               render_selected_intervals_only=False,
               use_camera_warp_guide=True,
               pose_strength=0.45, pose_end_percent=0.55):
        plan = json.loads(shot_plan)
        if plan["signature"] != _signature(source_frames) or plan["frame_count"] != len(source_frames):
            raise ValueError("The source video changed. Re-run angle planning.")
        # Plan mode ends here. None of the expensive model/warp inputs is requested.
        if stage.startswith("1"):
            from comfy_execution.graph_utils import ExecutionBlocker
            return (ExecutionBlocker(None), ExecutionBlocker(None))
        scene_mode = bool(look_enabled) and background_mode != "Keep source background"
        if scene_mode and not getattr(self, "SCENE_START_GUIDE", False):
            raise ValueError("V3 preserves the source environment. Use V4 for a generated scene swap.")
        if scene_mode and any(v == 0 for v in plan["choices"]):
            raise ValueError("Choose a generated angle for every V4 scene-swap shot; Original would reintroduce the source room.")
        if not any(v > 0 for v in plan["choices"]):
            from comfy_execution.graph_utils import GraphBuilder
            graph = GraphBuilder()
            audio = graph.node("TrimAudioDuration", start_index=0.0,
                               duration=len(source_frames) / 24.0,
                               audio=source_audio).out(0)
            return {"result": (source_frames, audio), "expand": graph.finalize()}
        needed = ((reference_video, pose_video, model_patch, model, clip, video_vae, audio_vae)
                  if scene_mode else
                  (reference_video, moge_geometry, model, clip, video_vae, audio_vae)
                  if use_camera_warp_guide else
                  (reference_video, model, clip, video_vae, audio_vae))
        if any(v is None for v in needed):
            raise ValueError("Connect H3 model setup and warp preparation for Render multicam.")
        if len(reference_video) < len(source_frames):
            raise ValueError("The resized reference video is shorter than the shot plan.")
        if scene_mode and len(pose_video) < len(source_frames):
            raise ValueError("The pose-control video is shorter than the source.")
        shot_prompts = plan.get("shot_prompts", [""] * plan["shot_count"])
        for index, (angle_id, motion) in enumerate(zip(plan["choices"], shot_prompts)):
            if angle_id == 0 and motion:
                raise ValueError(f"Shot {index + 1} uses the original camera. Select a generated angle to use a motion prompt.")
        from comfy_execution.graph_utils import GraphBuilder
        graph = GraphBuilder()
        n = len(source_frames)
        h, w = int(reference_video.shape[1]), int(reference_video.shape[2])
        length = n + ((5 - n % 17) % 17)
        if length < 5:
            length = 5
        audio = graph.node("TrimAudioDuration", start_index=0.0, duration=n / 24.0,
                           audio=source_audio).out(0)
        if scene_mode:
            prompt += (" The first and last keyframes define the same physical set and relit "
                       "performer. Stay in this exact environment for the whole shot. "
                       "Follow the supplied body, hand and face pose control and the original speech audio.")
        elif look_enabled:
            prompt += (" <Picture 1> defines the updated lighting and camera finish. "
                       "Keep the room layout and performance from <Video 1>.")
        takes = {}
        warped = {}
        pictures = {}
        def render_take(angle_id, first, count, motion="", shot_index=None):
            _, _, azimuth, distance, _ = ANGLE_BY_ID[angle_id]
            framing_row = (angle_id - 1) // 3
            headroom_shift = (0.0, 0.04, 0.12)[framing_row]
            if angle_id not in pictures:
                pictures[angle_id] = graph.node("ZuraSavedAngleV3", project=plan["project"],
                    signature=plan["signature"], angle_id=angle_id).out(0)
            if not scene_mode and use_camera_warp_guide and angle_id not in warped:
                warped[angle_id] = graph.node("CrossViewWarp", frames=reference_video,
                    moge_geometry=moge_geometry, azimuth=float(azimuth), elevation=0.0,
                    distance=float(distance), hfov=50.0, vertical_shift=headroom_shift,
                    depth_ratio=6.0, smooth_depth=False, invert_depth=False, roll_lock=True,
                    pivot_override=True, pivot_x=0.1, pivot_y=0.1, pivot_z=1.0,
                    keep_source_aim=True, preview_size=512, frame_index=1).out(0)
            picture = pictures[angle_id]
            warp = picture if scene_mode else warped.get(angle_id)
            ref = reference_video
            shot_audio = audio
            shot_pose = pose_video
            if shot_index is not None:
                ref = graph.node("GetImageRangeFromBatch", images=reference_video,
                    start_index=first, num_frames=count).out(0)
                if not scene_mode and use_camera_warp_guide:
                    warp = graph.node("GetImageRangeFromBatch", images=warp,
                        start_index=first, num_frames=count).out(0)
                shot_audio = graph.node("TrimAudioDuration", audio=source_audio,
                    start_index=first / 24.0, duration=count / 24.0).out(0)
                if scene_mode:
                    shot_pose = graph.node("GetImageRangeFromBatch", images=pose_video,
                        start_index=first, num_frames=count).out(0)
            take_length = count + ((5 - count % 17) % 17)
            # MiniMax's reference and guide nodes silently crop an invalid
            # frame count down to the previous 17k+5 boundary. A 21-frame
            # shot therefore became a *five-frame* performance reference even
            # though its target latent was padded to 22. Repeat only the final
            # frame of each temporal guide so all conditioning keeps the real
            # first `count` frames and the model receives a valid clip length.
            if take_length > count:
                def pad_last(frames):
                    last = graph.node("ImageFromBatch", image=frames,
                                      batch_index=count - 1, length=1).out(0)
                    tail = graph.node("RepeatImageBatch", image=last,
                                      amount=take_length - count).out(0)
                    return graph.node("ImageBatch", image1=frames,
                                      image2=tail).out(0)
                ref = pad_last(ref)
                if scene_mode:
                    shot_pose = pad_last(shot_pose)
                elif use_camera_warp_guide:
                    warp = pad_last(warp)
            take_prompt = prompt
            if motion:
                take_prompt += (f" For this shot only, apply this subtle camera/focus action: {motion}. "
                                "Do not alter the performer, speaking rhythm or lip sync.")
            if scene_mode:
                condition = graph.node("MiniMaxH3ImageToVideo", clip=clip,
                    vae=video_vae, prompt=take_prompt, width=w, height=h,
                    length=take_length, first_frame=picture, last_frame=picture)
                guided = graph.node("MiniMaxH3AddGuide", positive=condition.out(0),
                    latent=condition.out(1), audio=shot_audio,
                    audio_vae=audio_vae, frame_idx=0).out(0)
            else:
                condition = graph.node("MiniMaxH3ReferenceToVideo", clip=clip,
                    vae=video_vae, audio_vae=audio_vae, prompt=take_prompt,
                    width=w, height=h, length=take_length, ref_image_size="match",
                    **{"ref_images.ref_image_0": picture,
                       "ref_videos.ref_video_0": ref,
                       "ref_video_audios.ref_video_audio_0": shot_audio})
                guided = condition.out(0)
                if use_camera_warp_guide:
                    guided = graph.node("MiniMaxH3AddGuide", positive=guided,
                        latent=condition.out(1), vae=video_vae, image=warp,
                        frame_idx=0).out(0)
                # Reference-video audio is only a *reference* token. Anchor
                # the same trimmed source audio in the target AV latent too,
                # so H3 cannot freely invent a different spoken take.
                guided = graph.node("MiniMaxH3AddGuide", positive=guided,
                    latent=condition.out(1), audio=shot_audio,
                    audio_vae=audio_vae, frame_idx=0).out(0)
            take_model = model
            if scene_mode:
                take_model = graph.node("MiniMaxH3FunControlNetApply", model=model,
                    model_patch=model_patch, vae=video_vae,
                    strength=float(pose_strength), start_percent=0.0,
                    end_percent=float(pose_end_percent),
                    control_video=shot_pose).out(0)
            guider = graph.node("BasicGuider", model=take_model, conditioning=guided).out(0)
            noise = graph.node("RandomNoise", noise_seed=int(seed) + angle_id +
                               (shot_index or 0) * 1009).out(0)
            scheduler = graph.node("BasicScheduler", model=take_model, scheduler="simple",
                                   steps=steps, denoise=1.0).out(0)
            sampler = graph.node("KSamplerSelect", sampler_name="res_multistep").out(0)
            sampled = graph.node("SamplerCustomAdvanced", noise=noise, guider=guider,
                                 sampler=sampler, sigmas=scheduler,
                                 latent_image=condition.out(1)).out(0)
            take = graph.node("VAEDecode", samples=sampled, vae=video_vae).out(0)
            if framing_row == 2:
                # CrossView's dolly distance is currently unreliable. A
                # conservative *native* crop gives the close row a repeatable
                # shot size without asking H3 to invent missing head pixels.
                crop_w, crop_h = round(w / 1.2), round(h / 1.2)
                crop_x, crop_y = (w - crop_w) // 2, round(h * 0.03)
                cropped = graph.node("ImageCrop", image=take, width=crop_w,
                                     height=crop_h, x=crop_x, y=crop_y).out(0)
                take = graph.node("ImageScale", image=cropped,
                                  upscale_method="lanczos", width=w, height=h,
                                  crop="center").out(0)
            return take
        plain_angles = {angle_id for angle_id, motion in zip(plan["choices"], shot_prompts)
                        if angle_id > 0 and not motion and not scene_mode
                        and not render_selected_intervals_only}
        for angle_id in sorted(plain_angles):
            takes[f"angle_{angle_id}"] = render_take(angle_id, 0, n)
        for index, (angle_id, motion) in enumerate(zip(plan["choices"], shot_prompts)):
            if angle_id > 0 and (motion or scene_mode or render_selected_intervals_only):
                first = index * plan["frames_per_shot"]
                count = min(plan["frames_per_shot"], n - first)
                takes[f"shot_{index + 1}"] = render_take(angle_id, first, count,
                                                          motion=motion, shot_index=index + 1)
        assembled = graph.node("ZuraAssembleMulticamV3", source_frames=source_frames,
                               plan_json=shot_plan,
                               **takes).out(0)
        return {"result": (assembled, audio), "expand": graph.finalize()}


class ZuraH3MulticamV4(ZuraH3MulticamV3):
    """Experimental scene swap with relit start guides and source pose control."""
    SCENE_START_GUIDE = True

    @classmethod
    def INPUT_TYPES(cls):
        schema = super().INPUT_TYPES()
        schema["optional"]["pose_video"] = ("IMAGE", {"lazy": True})
        schema["optional"]["model_patch"] = ("MODEL_PATCH", {"lazy": True})
        schema["optional"]["pose_strength"] = ("FLOAT", {"default": 0.45,
            "min": 0.0, "max": 2.0, "step": 0.05,
            "tooltip": "Lower this if pose skeleton lines show in the output."})
        schema["optional"]["pose_end_percent"] = ("FLOAT", {"default": 0.55,
            "min": 0.0, "max": 1.0, "step": 0.05,
            "tooltip": "Stop pose control partway through sampling to let the scene clean up."})
        return schema


NODE_CLASS_MAPPINGS = {
    "ZuraMulticamStageV3": ZuraMulticamStageV3,
    "ZuraPlanOnlyImageV3": ZuraPlanOnlyImageV3,
    "ZuraSafeAnglePromptV3": ZuraSafeAnglePromptV3,
    "ZuraSceneAnglePromptV4": ZuraSceneAnglePromptV4,
    "ZuraAngleGalleryV3": ZuraAngleGalleryV3,
    "ZuraSavedAngleV3": ZuraSavedAngleV3,
    "ZuraAssembleMulticamV3": ZuraAssembleMulticamV3,
    "ZuraH3MulticamV3": ZuraH3MulticamV3,
    "ZuraH3MulticamV4": ZuraH3MulticamV4,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ZuraMulticamStageV3": "Zura V3 · Choose pass",
    "ZuraPlanOnlyImageV3": "Zura V3 · Plan-only images",
    "ZuraSafeAnglePromptV3": "Zura V3 · Safe camera framing",
    "ZuraSceneAnglePromptV4": "Zura V4 · Orbit whole scene with parallax",
    "ZuraAngleGalleryV3": "Zura V3 · Pick camera angles",
    "ZuraSavedAngleV3": "Zura V3 · Saved angle",
    "ZuraAssembleMulticamV3": "Zura V3 · Assemble shots",
    "ZuraH3MulticamV3": "Zura V3 · H3 multicam render",
    "ZuraH3MulticamV4": "Zura V4 · Generative scene-aware multicam (experimental)",
}
