"""Wan 2.2 route for the shared artist project, using native visible inference."""
import hashlib
import json
from pathlib import Path
import re

WAN_MODELS = {
    "wan": ("diffusion_models", "Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors"),
    "wan_text": ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    "wan_vae": ("vae", "Wan2_1_VAE_bf16.safetensors"),
    "wan_vision": ("clip_vision", "clip_vision_h.safetensors"),
    "wan_pose": ("detection", "vitpose-l-wholebody.onnx"),
    "wan_detector": ("detection", "yolov10m.onnx"),
    "wan_relight": ("loras", "WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors"),
    "wan_realism": ("loras", "Wan14B_RealismBoost.safetensors"),
    "wan_turbo": ("loras", "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"),
}
WAN_NATIVE_NODES = ("WanAnimateToVideo", "OnnxDetectionModelLoader", "PoseAndFaceDetection",
    "DrawViTPose", "BlockifyMask", "ZuraWan22LoopedChunksSampler", "ZuraWanReviewedFrames",
    "ZuraWanSavePreparation", "ZuraWanLoadPreparation", "ZuraWanLoadMappedPreparation",
    "ZuraWanLoadWindowPreparation", "ZuraApplyBoundedReferenceAudio", "ZuraWan22StreamedSampler",
    "ZuraWanPreparationWindow", "ZuraWanCarryPoseWindow", "ZuraWanSavePreparationPart",
    "ZuraWanMergePreparation")


def cache_path(key):
    import folder_paths
    return Path(folder_paths.get_output_directory()) / "genj" / "wan_conditioning" / (key + ".pt")


def _chunk_frames_for_resolution(resolution):
    """Use the shorter Wan window at the public 1080p control only."""
    return 41 if int(resolution) == 1920 else 81


def _reject_viewport(project):
    config = project.get("config") or {}
    if config.get("subject_mode") == "objects":
        raise ValueError("Wan Animate needs a human performance. Choose H3 or LTX for objects and scenery.")
    if (project.get("viewport_render") or config.get("viewport_render") or
            config.get("workflow_mode") == "viewport"):
        raise ValueError(
            "Wan is not available for viewport-to-final. Choose H3 for this mode; "
            "LTX viewport-to-final is experimental.")


def cache_key(project):
    _reject_viewport(project)
    import folder_paths
    from .studio import canonical
    stamps = {}
    for identity in ("wan_pose", "wan_detector"):
        folder, name = WAN_MODELS[identity]
        filename = folder_paths.get_full_path(folder, name)
        if not filename:
            raise ValueError("A Wan preparation model is missing: " + name)
        stat = Path(filename).stat()
        stamps[identity] = [name, stat.st_size, stat.st_mtime_ns]
    c = project["config"]
    from . import wan_speech
    viewport_render = bool(project.get("viewport_render") or c.get("viewport_render"))
    character = project.get("character") or {}
    data = {"version": 7 if viewport_render else (6 if wan_speech.enabled(project) else 5),
        "review": project["review"], "character": character.get("sha"),
        "resolution": c["resolution"], "scope": "person" if viewport_render else c["scope"], "models": stamps,
        "performance_mode": "reference" if wan_speech.enabled(project) else "original"}
    if viewport_render:
        # Native Wan Animate accepts one still appearance reference. In this
        # route the approved full-scene opening consolidates the chosen look.
        data["viewport_render"] = True
        data["opening_sha"] = project["opening_input"]["sha"]
    elif not data["character"]:
        raise ValueError("A Wan character reference is required outside viewport mode.")
    if c.get("edit_area", "mask") == "scene" or c.get("mask_method", "auto") != "auto":
        data["scope"] = "person"
        data["selection"] = "scene" if c.get("edit_area") == "scene" else "selected_area"
    if wan_speech.enabled(project):
        guide = wan_speech.load_guide(project)
        data["speech"] = {"guide_key": guide["guide_key"], "guide_sha": guide["sha"],
                          "opening_sha": project["opening_input"]["sha"]}
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def build_wan_graph(project, use_cache=True, *, cache_key_override=None, preparation_controls=None):
    # Fail before preparation or loading assets, including saved graph requests.
    _reject_viewport(project)
    from .studio import assert_approved, check_asset
    assert_approved(project)
    c = dict(project["config"])
    viewport_render = bool(project.get("viewport_render") or c.get("viewport_render"))
    custom_selection = (viewport_render or c.get("edit_area", "mask") == "scene" or
                        c.get("mask_method", "auto") != "auto")
    if c["background"] != "keep" and not viewport_render:
        raise ValueError("Wan currently keeps the original background. Choose LTX for scene restyling.")
    if project.get("opening_approval") != project.get("opening_key") or not project.get("opening_input"):
        raise ValueError("Approve the character preview before animating.")
    check_asset(project["opening_input"])
    if not viewport_render:
        check_asset(project["character"])
    if cache_key_override is not None:
        if (not use_cache or not isinstance(cache_key_override, str) or
                not re.fullmatch(r"[a-f0-9]{64}", cache_key_override)):
            raise ValueError("Manual Wan motion needs a valid bounded preparation key.")
    key = cache_key(project) if cache_key_override is None else cache_key_override
    if preparation_controls is not None:
        # Graph motion controls belong to the already reviewed source. Check
        # that original approval above, then use the completed manual cache's
        # scope and size without rewriting or reapproving the Studio project.
        if (cache_key_override is None or type(preparation_controls) is not dict or
                set(preparation_controls) != {"resolution", "scope"} or
                type(preparation_controls["resolution"]) is not int or
                preparation_controls["resolution"] not in (256, 512, 768, 960, 1280, 1920) or
                preparation_controls["scope"] not in ("person", "head") or
                (custom_selection and preparation_controls["scope"] != "person") or
                not cache_path(key).is_file()):
            raise ValueError("Finish the edited Wan motion preparation before opening its render.")
        c.update(preparation_controls)
    streamed = use_cache and cache_path(key).exists()
    graph = {}

    def node(identity, typ, **inputs):
        graph[identity] = {"class_type": typ, "inputs": inputs}
        return [identity, 0]

    shot = node("wan_shot", "GenjLoadReviewedShot", shot_id=project["review"],
        approved_shot_id=project["review"], render_long_edge=c["resolution"], output_scale=1, preview_seconds=0)
    details = ["wan_shot", 3]
    if project.get("audio"):
        audio = node("wan_reference_audio", "LoadAudio", audio=project["audio"]["file"])
        shot = node("wan_audio_selection", "ZuraApplyBoundedReferenceAudio" if streamed else "GenjApplyReferenceAudio",
            video=shot, clip_details=details,
            audio=audio, audio_start_seconds=c["audio_start"])
        details = ["wan_audio_selection", 1]
    if not use_cache or not cache_path(key).exists():
        frames = node("wan_frames", "ZuraWanReviewedFrames", source=shot, mask_video=["wan_shot", 1])
        mask = node("wan_block_mask", "BlockifyMask", masks=["wan_frames", 1], block_size=32, device="cpu")
        detector = node("wan_pose_model", "OnnxDetectionModelLoader", vitpose_model=WAN_MODELS["wan_pose"][1],
            yolo_model=WAN_MODELS["wan_detector"][1], onnx_device="CPUExecutionProvider")
        pose_data = node("wan_pose_detect", "PoseAndFaceDetection", model=detector, images=frames,
            width=["wan_frames", 2], height=["wan_frames", 3], face_padding=0)
        pose = node("wan_pose_draw", "DrawViTPose", pose_data=pose_data, width=["wan_frames", 2],
            height=["wan_frames", 3], retarget_padding=0, body_stick_width=-1, hand_stick_width=-1, draw_head=True)
        # Wan Animate has one reference-image input. Use the approved whole
        # scene look rather than treating an environment or object ref as a
        # character crop. Multiple still refs must be consolidated upstream.
        reference_asset = project["opening_input"] if viewport_render else project["character"]
        character = node("wan_character", "LoadImage", image=reference_asset["file"])
        sam = node("wan_sam", "CheckpointLoaderSimple", ckpt_name="sam3.1_multiplex_fp16.safetensors")
        prompt = node("wan_person_prompt", "CLIPTextEncode", clip=["wan_sam", 1], text="person:10")
        detection = node("wan_character_detect", "SAM3_Detect", model=sam, image=character, conditioning=prompt,
            threshold=.3, refine_iterations=2, individual_masks=True)
        chosen = node("wan_character_mask", "GenjChoosePerformer", masks=detection, performer=-1)
        chosen = node("wan_character_mask_size", "ResizeImageMaskNode", input=chosen,
            resize_type="match size", scale_method="nearest-exact", **{
                "resize_type.match": character, "resize_type.crop": "disabled"})
        reference = node("wan_character_crop", "ImageCropByMaskAndResize", image=character, mask=chosen,
            base_resolution=1024, padding=32, min_crop_resolution=128, max_crop_resolution=16384)
        size = node("wan_character_size", "GetImageSize", image=reference)
        neutral = node("wan_character_background", "EmptyImage", width=size, height=["wan_character_size", 1],
            batch_size=1, color=0x808080)
        reference = node("wan_character_isolated", "ImageCompositeMasked", destination=neutral, source=reference,
            x=0, y=0, resize_source=False, mask=["wan_character_crop", 1])
        if custom_selection:
            # A selected object or whole scene need not contain a character.
            # Keep its complete appearance reference instead of a person crop.
            for identity in ("wan_sam", "wan_person_prompt", "wan_character_detect", "wan_character_mask",
                             "wan_character_mask_size", "wan_character_crop", "wan_character_size",
                             "wan_character_background", "wan_character_isolated"):
                graph.pop(identity)
            reference = character
        face = ["wan_pose_detect", 1]
        from . import wan_speech
        if wan_speech.enabled(project):
            guide = wan_speech.load_guide(project)
            # Decode the native25fps guide onto the exact24fps source timeline.
            # VHS's Wan preset would change it to16fps and trim4n+1 frames.
            speech_frames = node("wan_speech_video", "VHS_LoadVideoFFmpegPath", video=guide["path"],
                force_rate=24.0, custom_width=0, custom_height=0,
                frame_load_cap=guide["key_data"]["source"]["frames"], start_time=0.0, format="None")
            node("wan_speech_size", "GetImageSizeAndCount", image=speech_frames)
            node("wan_speech_face_detect", "PoseAndFaceDetection", model=detector, images=speech_frames,
                width=["wan_speech_size", 1], height=["wan_speech_size", 2], face_padding=0)
            face = ["wan_speech_face_detect", 1]
        inputs = dict(frames=frames, mask=mask, pose=pose, face=face, reference=reference,
                      scope="person" if custom_selection else c["scope"])
        if wan_speech.enabled(project):
            inputs.update(speech_guide_key=guide["guide_key"], speech_guide_sha=guide["sha"])
        if use_cache:
            node("wan_save", "ZuraWanSavePreparation", **inputs, cache_key=key)
            from .wan_parts import prepare_next_part_graph
            return prepare_next_part_graph(project, graph, key)
        footage = node("wan_cached", "ZuraWanPackPreparation", **inputs)
    else:
        footage = node("wan_cached", "ZuraWanLoadWindowPreparation", cache_key=key,
            max_window_frames=_chunk_frames_for_resolution(c["resolution"]))
    opening = node("wan_opening", "LoadImage", image=project["opening_input"]["file"])
    seed = c["seed"]
    from . import wan_speech
    if wan_speech.enabled(project):
        guide = wan_speech.load_guide(project)
        seed = node("wan_performance_seed", "PrimitiveInt", value=c["seed"])
        graph["wan_performance_seed"]["_meta"] = {"title": "Performance seed"}
        footage = node("wan_speech_guard", "ZuraWanSpeechGuard", footage=footage,
            selected_video=shot, clip_details=details, opening=opening, seed=seed,
            approved_opening_file=project["opening_input"]["file"], guide_key=guide["guide_key"])
        opening, seed = ["wan_speech_guard", 1], ["wan_speech_guard", 2]
    opening = node("wan_opening_size", "ImageScale", image=opening, upscale_method="lanczos",
        width=["wan_cached", 2], height=["wan_cached", 3], crop="disabled")
    # Current core expands this older KJ scaled checkpoint to fp16 on default.
    # Explicit native FP8 preserves the intended small model storage on RTX.
    model = node("wan_model", "UNETLoader", unet_name=WAN_MODELS["wan"][1], weight_dtype="fp8_e4m3fn_fast")
    fast = c["quality"] == "fast"
    # Wan2.2 Animate does not support the Wan2.2 I2V high-noise LightX2V
    # adapter. Keep only the matching Wan2.1 low-noise adapter on the fast route.
    for identity, strength in (("wan_turbo", .6),) if fast else ():
        model = node(identity, "LoraLoaderModelOnly", model=model, lora_name=WAN_MODELS[identity][1], strength_model=strength)
    for identity in ("wan_relight", "wan_realism"):
        model = node(identity, "LoraLoaderModelOnly", model=model, lora_name=WAN_MODELS[identity][1], strength_model=1.0)
    model = node("wan_shift", "ModelSamplingSD3", model=model, shift=8.0)
    model = node("wan_torch", "ModelPatchTorchSettings", model=model, enable_fp16_accumulation=True)
    model = node("wan_attention", "PathchSageAttentionKJ", model=model, sage_attention="auto", allow_compile=False)
    clip = node("wan_clip", "CLIPLoader", clip_name=WAN_MODELS["wan_text"][1], type="wan", device="cpu")
    vae = node("wan_vae", "VAELoader", vae_name=WAN_MODELS["wan_vae"][1])
    vision = node("wan_vision", "CLIPVisionLoader", clip_name=WAN_MODELS["wan_vision"][1])
    if viewport_render:
        prompt = (
            "Convert the entire grey 3D viewport/blockout into one coherent finished scene. "
            "Treat the source video as the authoritative guide for exact camera path, perspective, framing, "
            "timing, object placement, scale, scene layout and motion. Replace the untextured viewport look "
            "throughout the frame while preserving source camera movement, parallax, geometry, subject positions, "
            "ground plane and contact with the ground. Use the approved opening image as the single consolidated "
            "appearance reference. Keep the result visually consistent across frames; do not switch back to grey "
            "viewport shading, add duplicate subjects, or reproduce a reference sheet. " + c["prompt"]
        )
    else:
        prompt = "The selected performer matches the reference character. Keep the driving video action, expressions, hand gestures, camera angle, framing and scene. Natural motion and consistent identity. Do not reproduce a reference sheet, collage or multiple views. " + c["prompt"]
    if custom_selection and not viewport_render:
        area = "the whole scene" if c.get("edit_area") == "scene" else "only the reviewed masked area"
        prompt = ("Transform " + area + " to match the approved opening image and appearance reference. "
                  "Keep the driving video action, expressions, hand gestures and changing camera perspective. "
                  "Retain object positions, the ground plane and foot contact. " +
                  ("Preserve all unselected surroundings. " if c.get("edit_area") != "scene" else "") +
                  "Natural motion and consistent appearance. Do not reproduce a reference sheet, collage or multiple views. " + c["prompt"])
    if c["remove_text"]:
        prompt += " Remove masked captions and title panels entirely, replacing them with natural background or clothing. No on-screen text overlays."
    if project.get("audio") and c.get("lip_sync"):
        prompt = prompt.replace("action, expressions, hand gestures", "action, head direction, eye expressions, hand gestures")
        prompt += " Follow the speech-driven face guide precisely for mouth movements. The performer speaks only when the replacement audio contains speech, with a resting closed mouth during silence. Ignore the original dialogue and its mouth movements."
    steps, cfg = (6, 1.0) if fast else (40, 5.0)
    if wan_speech.enabled(project):
        # Keep all editable sampler controls on the same native stage bus as
        # the verified seed, avoiding interleaved boundary wires in graph view.
        prompt = node("wan_direction", "PrimitiveStringMultiline", value=prompt)
        graph["wan_direction"]["_meta"] = {"title": "Animation direction"}
        steps = node("wan_steps", "PrimitiveInt", value=steps)
        graph["wan_steps"]["_meta"] = {"title": "Sampling steps"}
        cfg = node("wan_cfg", "PrimitiveFloat", value=cfg)
        graph["wan_cfg"]["_meta"] = {"title": "Guidance strength"}
    delivery_inputs = {}
    if streamed:
        # This neutral digest binds delivery to the exact saved motion, look
        # and artist settings. The writer publishes a fresh atomic file.
        delivery_inputs["delivery_key"] = hashlib.sha256(json.dumps({
            "version": 1, "cache_key": key, "opening_sha": project["opening_input"]["sha"],
            "config": c}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    node("wan_render", "ZuraWan22StreamedSampler" if streamed else "ZuraWan22LoopedChunksSampler", model=model, clip=clip, vae=vae, clip_vision=vision,
        reference_image=opening, vision_reference=["wan_cached", 1], footage=footage,
        prompt=prompt, negative_prompt="flicker, warped hands, extra limbs, identity drift, text overlays, collage",
        steps=steps, cfg=cfg, seed=seed, chunk_frames=_chunk_frames_for_resolution(c["resolution"]),
        overlap_frames=5, max_side=c["resolution"], shot_mode="Detect cuts", cut_threshold=.2, cut_frames="",
        join_mode="Native continuation", viewport_render=viewport_render, **delivery_inputs)
    node("wan_export", "GenjRestoreSoundtrack", video=["wan_render", 0 if streamed else 1], clip_details=details,
        model_stride=4, take_name="studio_" + project["id"][:8] + "_wan")
    # Wan renders facial detail from the audio-driven guide. A second mouth
    # pass is an explicit option because its small face decoder can soften detail.
    from .speech import add_finish
    add_finish(graph, project, native_speech=True, reference_video=shot)
    return graph
