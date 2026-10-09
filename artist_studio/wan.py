"""Wan 2.2 route for the shared artist project, using native visible inference."""
import hashlib
import json
from pathlib import Path

WAN_MODELS = {
    "wan": ("diffusion_models", "Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors"),
    "wan_text": ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
    "wan_vae": ("vae", "Wan2_1_VAE_bf16.safetensors"),
    "wan_vision": ("clip_vision", "clip_vision_h.safetensors"),
    "wan_pose": ("detection", "vitpose-l-wholebody.onnx"),
    "wan_detector": ("detection", "yolov10m.onnx"),
    "wan_relight": ("loras", "WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors"),
    "wan_realism": ("loras", "Wan14B_RealismBoost.safetensors"),
    "wan_turbo_high": ("loras", "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"),
    "wan_turbo": ("loras", "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"),
}
WAN_NATIVE_NODES = ("WanAnimateToVideo", "OnnxDetectionModelLoader", "PoseAndFaceDetection",
    "DrawViTPose", "BlockifyMask", "ZuraWan22LoopedChunksSampler", "ZuraWanReviewedFrames",
    "ZuraWanSavePreparation", "ZuraWanLoadPreparation")


def cache_path(key):
    import folder_paths
    return Path(folder_paths.get_output_directory()) / "genj" / "wan_conditioning" / (key + ".pt")


def cache_key(project):
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
    data = {"version": 4, "review": project["review"], "character": project["character"]["sha"],
        "resolution": c["resolution"], "scope": c["scope"], "models": stamps}
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def build_wan_graph(project):
    from .studio import assert_approved, check_asset
    assert_approved(project)
    c = project["config"]
    if c["background"] != "keep":
        raise ValueError("Wan currently keeps the original background. Choose LTX for scene restyling.")
    if project.get("opening_approval") != project.get("opening_key") or not project.get("opening_input"):
        raise ValueError("Approve the character preview before animating.")
    check_asset(project["opening_input"])
    check_asset(project["character"])
    graph = {}

    def node(identity, typ, **inputs):
        graph[identity] = {"class_type": typ, "inputs": inputs}
        return [identity, 0]

    shot = node("wan_shot", "GenjLoadReviewedShot", shot_id=project["review"],
        approved_shot_id=project["review"], render_long_edge=c["resolution"], output_scale=1, preview_seconds=0)
    key = cache_key(project)
    if not cache_path(key).exists():
        frames = node("wan_frames", "ZuraWanReviewedFrames", source=shot, mask_video=["wan_shot", 1])
        mask = node("wan_block_mask", "BlockifyMask", masks=["wan_frames", 1], block_size=32, device="cpu")
        detector = node("wan_pose_model", "OnnxDetectionModelLoader", vitpose_model=WAN_MODELS["wan_pose"][1],
            yolo_model=WAN_MODELS["wan_detector"][1], onnx_device="CPUExecutionProvider")
        pose_data = node("wan_pose_detect", "PoseAndFaceDetection", model=detector, images=frames,
            width=["wan_frames", 2], height=["wan_frames", 3], face_padding=0)
        pose = node("wan_pose_draw", "DrawViTPose", pose_data=pose_data, width=["wan_frames", 2],
            height=["wan_frames", 3], retarget_padding=0, body_stick_width=-1, hand_stick_width=-1, draw_head=True)
        character = node("wan_character", "LoadImage", image=project["character"]["file"])
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
        node("wan_save", "ZuraWanSavePreparation", frames=frames, mask=mask, pose=pose,
            face=["wan_pose_detect", 1], reference=reference, cache_key=key, scope=c["scope"])
        return graph
    footage = node("wan_cached", "ZuraWanLoadPreparation", cache_key=key)
    opening = node("wan_opening", "LoadImage", image=project["opening_input"]["file"])
    opening = node("wan_opening_size", "ImageScale", image=opening, upscale_method="lanczos",
        width=["wan_cached", 2], height=["wan_cached", 3], crop="disabled")
    # Current core expands this older KJ scaled checkpoint to fp16 on default.
    # Explicit native FP8 preserves the intended small model storage on RTX.
    model = node("wan_model", "UNETLoader", unet_name=WAN_MODELS["wan"][1], weight_dtype="fp8_e4m3fn_fast")
    fast = c["quality"] == "fast"
    for identity, strength in (("wan_turbo_high", .7), ("wan_turbo", .6)) if fast else ():
        model = node(identity, "LoraLoaderModelOnly", model=model, lora_name=WAN_MODELS[identity][1], strength_model=strength)
    for identity in ("wan_relight", "wan_realism"):
        model = node(identity, "LoraLoaderModelOnly", model=model, lora_name=WAN_MODELS[identity][1], strength_model=1.0)
    model = node("wan_shift", "ModelSamplingSD3", model=model, shift=8.0)
    model = node("wan_torch", "ModelPatchTorchSettings", model=model, enable_fp16_accumulation=True)
    model = node("wan_attention", "PathchSageAttentionKJ", model=model, sage_attention="auto", allow_compile=False)
    clip = node("wan_clip", "CLIPLoader", clip_name=WAN_MODELS["wan_text"][1], type="wan", device="cpu")
    vae = node("wan_vae", "VAELoader", vae_name=WAN_MODELS["wan_vae"][1])
    vision = node("wan_vision", "CLIPVisionLoader", clip_name=WAN_MODELS["wan_vision"][1])
    prompt = "The selected performer matches the reference character. Keep the driving video action, expressions, hand gestures, camera angle, framing and scene. Natural motion and consistent identity. Do not reproduce a reference sheet, collage or multiple views. " + c["prompt"]
    if c["remove_text"]:
        prompt += " Remove masked captions and title panels entirely, replacing them with natural background or clothing. No on-screen text overlays."
    node("wan_render", "ZuraWan22LoopedChunksSampler", model=model, clip=clip, vae=vae, clip_vision=vision,
        reference_image=opening, vision_reference=["wan_cached", 1], footage=footage,
        prompt=prompt, negative_prompt="flicker, warped hands, extra limbs, identity drift, text overlays, collage",
        steps=6 if fast else 40, cfg=1.0 if fast else 5.0, seed=c["seed"], chunk_frames=81,
        overlap_frames=5, max_side=c["resolution"], shot_mode="Detect cuts", cut_threshold=.2, cut_frames="",
        join_mode="Native continuation")
    node("wan_export", "GenjRestoreSoundtrack", video=["wan_render", 1], clip_details=["wan_shot", 3],
        take_name="studio_" + project["id"][:8] + "_wan")
    return graph
