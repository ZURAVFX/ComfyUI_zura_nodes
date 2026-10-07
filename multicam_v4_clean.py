"""Dynamic packaging of the tested clean H3 -> Klein -> Wan IDV2V recipe.

This expands native conditioning/sampling nodes; it does not composite generated
pixels with the source. Prepared MODEL inputs must carry the appropriate model
family's LoRA and sampling shift. Structural validation is not visual sign-off.
"""
from __future__ import annotations

import hashlib
import json
import math


MODEL_INPUTS = {
    "wan_model": "MODEL", "wan_clip": "CLIP", "wan_vae": "VAE",
    "wan_vision": "CLIP_VISION", "klein_model": "MODEL",
    "klein_clip": "CLIP", "klein_vae": "VAE",
}

# Exact wording from the approved reference-clip probe; kept selectable so a
# generic reusable prompt is never represented as an unchanged visual recipe.
APPROVED_PRESET = "Approved grey studio (reference clip)"
APPROVED_KLEIN_FRONT = (
    "Replace the entire bedroom with a clean, visibly lit neutral-grey photo studio. "
    "A grey seamless paper cyclorama curves onto the floor behind the single man; no bed or bedroom objects remain. "
    "Soft large key light from camera left and subtle rim light from behind, realistic light falling across his face and sweatshirt. "
    "Preserve the exact man from the input photo: face proportions, eyes, nose, beard, hair, sweatshirt, pose and medium-shot framing. "
    "Natural unretouched photographic skin, not CGI.")
APPROVED_KLEIN_SIDE = (
    "Replace the entire bedroom with the same clean neutral-grey photo studio as the approved frontal reference: "
    "grey seamless paper cyclorama curving onto the floor, soft large key light from camera left and subtle rim light. "
    "This is the wide left three-quarter camera of the same real man. Keep the whole head and hair inside the frame with comfortable headroom. "
    "Preserve his exact face proportions, eyes, nose, beard, hair, black sweatshirt, pose, expression and camera direction from this input frame. "
    "Natural unretouched photographic skin; no beauty filter, no CGI, no bedroom objects.")
APPROVED_WAN_FRONT = (
    "A realistic documentary video of the same young adult man from the source performance, short dark hair, beard, black sweatshirt, "
    "in a seamless neutral grey photography studio. Soft natural studio lighting, subtle rim light, realistic skin texture. "
    "Preserve his exact timing, mouth movements, facial expressions, gaze, head and body motion and gestures from the source video. "
    "Natural camera image, no retouching.")
APPROVED_WAN_SIDE = (
    "The same man from the source video, short dark hair, beard and black sweatshirt, performs his speech and gesture, "
    "filmed from a wide three-quarter left camera angle with his whole head in frame and comfortable headroom. "
    "Clean seamless grey studio with cyclorama and floor, natural soft professional lighting, subtle rim light, photographic realism. "
    "Follow the source guide's exact mouth openings, closures, expression, gaze, head and body movement frame by frame. "
    "Maintain the wide left framing throughout this shot.")
APPROVED_NEGATIVE = (
    "different person, different face, altered speech timing, frozen mouth, slow motion, beauty filter, plastic skin, "
    "duplicate face, deformed hands, bedroom, bed, extra person, cartoon")
APPROVED_SIDE_NEGATIVE = (
    "frontal camera angle, different person, altered speech timing, frozen mouth, slow motion, beauty filter, plastic skin, "
    "duplicate face, deformed hands, bedroom, bed, extra person, cartoon")


def _positive_int(value, name):
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive whole number.")
    return value


def _source_signature(frames):
    digest = hashlib.sha256()
    digest.update(str(tuple(frames.shape)).encode())
    for index in {0, len(frames) // 2, len(frames) - 1}:
        sample = (frames[index, ::32, ::32, :3].detach().float().cpu().clamp(0, 1) * 255).byte()
        digest.update(sample.numpy().tobytes())
    return digest.hexdigest()[:16]


def parse_shots(raw, frame_count):
    """Read V3 gallery plans or explicit contiguous V4 shot intervals."""
    try:
        plan = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Connect the camera gallery's shot plan JSON.") from exc
    if (not isinstance(plan, dict) or type(plan.get("frame_count")) is not int
            or plan["frame_count"] != frame_count):
        raise ValueError("The shot plan must match the selected source frame count. Re-plan angles.")
    if "shots" in plan:
        shots = plan["shots"]
        if not isinstance(shots, list) or not shots:
            raise ValueError("The plan needs at least one shot.")
    else:
        per_shot = _positive_int(plan.get("frames_per_shot"), "Frames per shot")
        choices = plan.get("choices")
        count = math.ceil(frame_count / per_shot)
        if not isinstance(choices, list) or len(choices) != count or plan.get("shot_count", count) != count:
            raise ValueError("Assign an angle to every shot before rendering.")
        prompts = plan.get("shot_prompts", [""] * count)
        if not isinstance(prompts, list) or len(prompts) != count:
            raise ValueError("The number of shot prompts must match the number of shots.")
        shots = [{"start": i * per_shot, "count": min(per_shot, frame_count - i * per_shot),
                  "angle": angle, "prompt": prompts[i]} for i, angle in enumerate(choices)]
    if len(shots) > 60:
        raise ValueError("This renderer supports at most 60 shots per clip.")
    checked, cursor = [], 0
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict) or type(shot.get("start")) is not int or shot["start"] != cursor:
            raise ValueError(f"Shot {index + 1} must start at frame {cursor}; no gaps or overlaps are allowed.")
        count = _positive_int(shot.get("count"), f"Shot {index + 1} frame count")
        angle, motion = shot.get("angle"), shot.get("prompt", "")
        if type(angle) is not int or not 0 <= angle <= 9:
            raise ValueError(f"Shot {index + 1} needs an angle from 0 to 9.")
        if not isinstance(motion, str) or len(motion) > 1000:
            raise ValueError(f"Shot {index + 1} prompt must be text up to 1000 characters.")
        checked.append({"start": cursor, "count": count, "angle": angle, "prompt": motion.strip()})
        cursor += count
    if cursor != frame_count:
        raise ValueError(f"Shots cover {cursor} frames but the source contains {frame_count}.")
    return plan, checked


class ZuraCleanMulticamV4:
    CATEGORY = "Zura/video"
    FUNCTION = "render"
    RETURN_TYPES = ("IMAGE", "AUDIO")
    RETURN_NAMES = ("multicam_frames", "original_audio")
    DESCRIPTION = ("Optional AI relight of the V3 H3 camera result. Uses Klein start frames and "
                   "Wan IDV2V performance conditioning. Supply 24 fps source frames and the same "
                   "source audio. Wan and Klein MODEL inputs must already include their tested LoRAs.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source_frames": ("IMAGE",), "source_audio": ("AUDIO",),
            "h3_frames": ("IMAGE", {"lazy": True}), "shot_plan": ("STRING",),
            "look_enabled": ("BOOLEAN", {"default": False,
                "tooltip": "Off: deliver the H3 camera result. On: AI relight or replace the scene using your Look prompt."}),
            "look_prompt": ("STRING", {"multiline": True, "default":
                "A clean neutral-grey photography studio with a seamless cyclorama and floor, "
                "soft large key light from camera left and subtle rim light."}),
            "width": ("INT", {"default": 832, "min": 128, "max": 2048, "step": 16}),
            "height": ("INT", {"default": 480, "min": 128, "max": 2048, "step": 16}),
            "seed": ("INT", {"default": 314159, "min": 0, "max": 0xffffffffffffffff,
                "control_after_generate": False, "tooltip": "Fixed video seed for repeatable results."}),
            "klein_seed": ("INT", {"default": 33874211, "min": 0, "max": 0xffffffffffffffff,
                "control_after_generate": False, "tooltip": "Fixed seed for the edited start-frame image."}),
            "wan_steps": ("INT", {"default": 4, "min": 1, "max": 60}),
            "klein_steps": ("INT", {"default": 4, "min": 1, "max": 60}),
        }, "optional": {
            **{name: (kind, {"lazy": True}) for name, kind in MODEL_INPUTS.items()},
            "prompt_preset": (["Custom look", APPROVED_PRESET], {"default": "Custom look",
                "tooltip": "Custom look uses your prompt for any performer. Approved grey studio restores the exact test-clip wording, including man/sweatshirt and wide-left camera; it ignores Look prompt."}),
            "wan_cfg": ("FLOAT", {"default": 3.0, "min": 1.0, "max": 10.0}),
            "mouth_strength": ("FLOAT", {"default": 1.5, "min": 0.0, "max": 2.5}),
            "control_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0}),
            "klein_width": ("INT", {"default": 1024, "min": 128, "max": 2048, "step": 16}),
            "klein_height": ("INT", {"default": 576, "min": 128, "max": 2048, "step": 16}),
            "background_colour": ("STRING", {"default": "#929398"}),
            "remove_from_source": ("STRING", {"default": "",
                "tooltip": "Old-scene objects to exclude from a new location. For this reference clip: bedroom, bed. Change it for other footage."}),
            "segmentation_model": ("STRING", {"default": "segm\\person_yolov8m-seg.pt"}),
            "max_take_frames": ("INT", {"default": 120, "min": 12, "max": 240}),
        }}

    def check_lazy_status(self, look_enabled, h3_frames=None, shot_plan=None, **kwargs):
        required = []
        if h3_frames is None:
            required.append("h3_frames")
        if look_enabled:
            required.extend(name for name in MODEL_INPUTS if kwargs.get(name) is None)
        return required

    def render(self, source_frames, source_audio, shot_plan, look_enabled, look_prompt,
               width=832, height=480, seed=314159, klein_seed=33874211, wan_steps=4,
               klein_steps=4, h3_frames=None, wan_model=None, wan_clip=None, wan_vae=None,
               wan_vision=None, klein_model=None, klein_clip=None, klein_vae=None,
               wan_cfg=3.0, mouth_strength=1.5, control_strength=1.0, klein_width=1024, klein_height=576,
               background_colour="#929398", remove_from_source="",
               segmentation_model="segm\\person_yolov8m-seg.pt",
               max_take_frames=120, prompt_preset="Custom look"):
        if getattr(source_frames, "ndim", None) != 4 or len(source_frames) < 1:
            raise ValueError("Connect nonempty source video frames at 24 fps.")
        n = len(source_frames)
        plan, shots = parse_shots(shot_plan, n)
        if plan.get("signature") and plan["signature"] != _source_signature(source_frames):
            raise ValueError("The source changed since camera planning. Re-run Plan angles.")
        if getattr(h3_frames, "ndim", None) != 4 or len(h3_frames) != n:
            raise ValueError("Connect the assembled V3 H3 result with exactly the source frame count.")
        from comfy_execution.graph_utils import GraphBuilder
        graph = GraphBuilder()
        audio = graph.node("TrimAudioDuration", audio=source_audio, start_index=0.0, duration=n / 24.0).out(0)
        if not look_enabled:
            return {"result": (h3_frames, audio), "expand": graph.finalize()}
        if prompt_preset not in ("Custom look", APPROVED_PRESET):
            raise ValueError("Choose a supported prompt preset.")
        if prompt_preset == APPROVED_PRESET and any(s["angle"] not in (0, 1) for s in shots):
            raise ValueError("The approved grey-studio wording supports source and angle 1 only. Choose Custom look for other angles.")
        if prompt_preset == "Custom look" and not str(look_prompt).strip():
            raise ValueError("Describe the lighting or environment, or turn Look off.")
        if any(value is None for value in (wan_model, wan_clip, wan_vae, wan_vision, klein_model, klein_clip, klein_vae)):
            raise ValueError("Connect the prepared Wan IDV2V and Flux Klein model setup for Look on.")
        for label, w, h in (("Output", width, height), ("Klein", klein_width, klein_height)):
            if type(w) is not int or type(h) is not int or w % 16 or h % 16 or min(w, h) < 128 or max(w, h) > 2048:
                raise ValueError(f"{label} width and height must be multiples of 16 from 128 to 2048.")
        _positive_int(max_take_frames, "Maximum take frames")
        continuous_front_needed = any(shot["angle"] == 0 and not shot["prompt"] for shot in shots)
        if any(shot["count"] > max_take_frames for shot in shots):
            raise ValueError("A generated camera shot exceeds Maximum take frames. Shorten that shot.")
        kw, kh = klein_width, klein_height
        old_scene = str(remove_from_source).strip()
        removal = (f"No original-scene objects remain, especially {old_scene}." if old_scene
                   else "No objects or background from the original setting remain.")
        # Native chains below preserve the tested four-step Klein/Wan schedules.
        sampler = graph.node("KSamplerSelect", sampler_name="er_sde").out(0)
        sigmas = graph.node("BasicScheduler", model=wan_model, scheduler="simple", steps=wan_steps, denoise=1.0).out(0)
        klein_sampler = graph.node("KSamplerSelect", sampler_name="euler").out(0)
        klein_sigmas = graph.node("Flux2Scheduler", steps=klein_steps, width=kw, height=kh).out(0)

        def cut(frames, start, count):
            return graph.node("ImageFromBatch", image=frames, batch_index=start, length=count).out(0)

        def pad(frames, count, length):
            if length == count:
                return frames
            last = cut(frames, count - 1, 1)
            tail = graph.node("RepeatImageBatch", image=last, amount=length - count).out(0)
            return graph.node("ImageBatch", image1=frames, image2=tail).out(0)

        def scale(image, w, h):
            return graph.node("ImageScale", image=image, upscale_method="lanczos", width=w, height=h, crop="center").out(0)

        def take(start, count, angle, motion, noise_offset):
            length = count + ((1 - count) % 4)
            source = cut(source_frames, start, count)
            guide = source if angle == 0 else cut(h3_frames, start, count)
            first = scale(cut(guide, 0, 1), kw, kh)
            camera = ("Keep the source camera viewpoint and framing." if angle == 0 else
                      "Keep this input frame's camera viewpoint and framing. Show the entire head with comfortable headroom.")
            edit_prompt = (f"Replace the entire source environment with a real physical setting: {look_prompt.strip()} "
                           f"{removal} Relight the performer naturally for this setting, including credible shadow falloff "
                           f"on face and clothing. {camera} Preserve the exact person's face proportions, eyes, nose, hair, "
                           "clothing, pose and expression. The same physical set must change perspective with this camera view. "
                           "Unretouched live-action photograph; no beauty filter or CGI.")
            if prompt_preset == APPROVED_PRESET:
                edit_prompt = APPROVED_KLEIN_FRONT if angle == 0 else APPROVED_KLEIN_SIDE
            encoded = graph.node("VAEEncode", pixels=first, vae=klein_vae).out(0)
            positive = graph.node("CLIPTextEncode", clip=klein_clip, text=edit_prompt).out(0)
            negative = graph.node("ConditioningZeroOut", conditioning=positive).out(0)
            positive = graph.node("ReferenceLatent", conditioning=positive, latent=encoded).out(0)
            negative = graph.node("ReferenceLatent", conditioning=negative, latent=encoded).out(0)
            guider = graph.node("CFGGuider", model=klein_model, positive=positive, negative=negative, cfg=1.0).out(0)
            noise = graph.node("RandomNoise", noise_seed=int(klein_seed)).out(0)
            latent = graph.node("EmptyFlux2LatentImage", width=kw, height=kh, batch_size=1).out(0)
            sampled = graph.node("SamplerCustomAdvanced", noise=noise, guider=guider, sampler=klein_sampler,
                                 sigmas=klein_sigmas, latent_image=latent).out(0)
            anchor = scale(graph.node("VAEDecode", samples=sampled, vae=klein_vae).out(0), width, height)
            vision = graph.node("CLIPVisionEncode", clip_vision=wan_vision, image=anchor, crop="none").out(0)
            guide = pad(guide, count, length)
            if angle != 0:
                guide = graph.node("ZuraMatchMouthMotion", source_frames=pad(source, count, length),
                                   angle_guide_frames=guide, source_start_frame=0,
                                   strength=mouth_strength, enabled=mouth_strength > 0).out(0)
            # This mask removes old-room information only from pre-generation VACE
            # conditioning. The delivered frames are always the full VAE decode.
            control = graph.node("ZuraIDV2VForegroundControl", images=scale(guide, width, height),
                                 segmentation_model=segmentation_model, background_colour=background_colour,
                                 mask_erode_px=2, edge_softness_px=1.0).out(0)
            video_prompt = (f"Live-action footage of the exact same performer in this new setting: {look_prompt.strip()} "
                            f"Maintain the location, relighting and clothing established by the start frame throughout this shot. "
                            f"{removal} {camera} Preserve the guide's exact speaking timing, mouth openings and closures, "
                            "facial expressions, gaze, head and body motion and gestures frame by frame. "
                            "Photographic realism, natural skin.")
            negative_prompt = ("different person, different face, altered speech timing, frozen mouth, slow motion, beauty filter, "
                               f"plastic skin, duplicate face, deformed hands, extra person, cartoon, source background, {old_scene}")
            if prompt_preset == APPROVED_PRESET:
                video_prompt = APPROVED_WAN_FRONT if angle == 0 else APPROVED_WAN_SIDE
                negative_prompt = APPROVED_NEGATIVE if angle == 0 else APPROVED_SIDE_NEGATIVE
            if motion:
                video_prompt += f" For this shot only: {motion} Keep the same performance and speech timing."
            positive = graph.node("CLIPTextEncode", clip=wan_clip, text=video_prompt).out(0)
            negative = graph.node("CLIPTextEncode", clip=wan_clip, text=negative_prompt).out(0)
            conditioning = graph.node("WanImageToVideo", positive=positive, negative=negative, vae=wan_vae,
                                      width=width, height=height, length=length, batch_size=1,
                                      clip_vision_output=vision, start_image=anchor, ref_pad_image=anchor)
            vace = graph.node("WanVaceToVideo", positive=conditioning.out(0), negative=conditioning.out(1),
                              vae=wan_vae, width=width, height=height, length=length, batch_size=1,
                              strength=control_strength, control_video=control)
            sampled = graph.node("SamplerCustom", model=wan_model, add_noise=True,
                                 noise_seed=(int(seed) + noise_offset) % (1 << 64), cfg=wan_cfg,
                                 positive=vace.out(0), negative=vace.out(1), sampler=sampler,
                                 sigmas=sigmas, latent_image=vace.out(2)).out(0)
            decoded = graph.node("VAEDecode", samples=sampled, vae=wan_vae).out(0)
            return cut(decoded, 0, count)

        # Keep the approved short-clip path as one continuous take. Longer
        # sources are split into bounded takes so the artist never has to
        # raise the GPU-capacity limit just to process the complete clip.
        front = None
        if continuous_front_needed:
            for chunk_index, start in enumerate(range(0, n, max_take_frames)):
                count = min(max_take_frames, n - start)
                chunk = take(start, count, 0, "", chunk_index)
                front = chunk if front is None else graph.node(
                    "ImageBatch", image1=front, image2=chunk).out(0)
        assembled = None
        generated_index = 0
        for shot in shots:
            if shot["angle"] == 0 and not shot["prompt"]:
                chunk = cut(front, shot["start"], shot["count"])
            else:
                generated_index += 1
                chunk = take(shot["start"], shot["count"], shot["angle"], shot["prompt"], generated_index)
            assembled = chunk if assembled is None else graph.node("ImageBatch", image1=assembled, image2=chunk).out(0)
        return {"result": (assembled, audio), "expand": graph.finalize()}


NODE_CLASS_MAPPINGS = {"ZuraCleanMulticamV4": ZuraCleanMulticamV4}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraCleanMulticamV4": "Clean relight · multicam V4"}
