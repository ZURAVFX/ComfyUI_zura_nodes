"""Artist-supplied selection masks and reuse of reviewed character selections."""

def add_custom_mask(graph, project, check_asset):
    asset = project.get("selection_mask")
    if not asset or asset.get("id") != project["config"].get("mask_video"):
        raise ValueError("Choose the custom mask video again before preparing the subject.")
    check_asset(asset)
    graph["zura_character_mask_video"] = {"class_type": "LoadVideo", "inputs": {"file": asset["file"]}}
    graph["zura_character_mask_frames"] = {"class_type": "ZuraCharacterMaskFrames", "inputs": {
        "mask_video": ["zura_character_mask_video", 0], "images": ["4", 0],
        "start_seconds": float(project["config"].get("start", 0)) if project["config"].get("length_mode") != "original" else 0.0}}
    for key in ("6", "7", "8", "9", "10", "11", "zura_split_tracking_shots", "zura_join_tracking_masks"):
        graph.pop(key, None)
    graph["12"]["inputs"]["mask"] = ["zura_character_mask_frames", 0]
    graph["20"]["inputs"].pop("tracking_coverage", None)


class ZuraCharacterMaskFrames:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"mask_video": ("VIDEO",), "images": ("IMAGE",),
            "start_seconds": ("FLOAT", {"default": 0, "min": 0})}}
    RETURN_TYPES = ("MASK",)
    FUNCTION = "match"
    CATEGORY = "Zura/Studio"

    def match(self, mask_video, images, start_seconds=0):
        import torch
        import torch.nn.functional as F
        components = mask_video.get_components()
        frames, rate = components.images, float(components.frame_rate)
        if len(frames) == 0 or rate <= 0:
            raise ValueError("The custom mask video has no readable frames.")
        count, height, width = images.shape[:3]
        # The artist can supply the complete source mask or an already trimmed mask.
        paired=len(frames)==count and not start_seconds
        duration, needed = len(frames) / rate, count / 24.0
        offset = float(start_seconds) if duration + 1/24 >= float(start_seconds) + needed else 0.0
        if not paired and duration + 1/24 < offset + needed:
            raise ValueError("The mask video is shorter than the selected clip. Supply the full source mask or a matching trimmed mask.")
        times = torch.arange(count, device=frames.device, dtype=torch.float64) / 24 + offset
        indices = torch.arange(count,device=frames.device) if paired else torch.floor(times * rate + 1e-6).long().clamp(max=len(frames)-1)
        gray = frames[indices, :, :, :3].float().mean(dim=-1).clamp(0, 1)
        masks = F.interpolate(gray[:, None], size=(height, width), mode="bilinear", align_corners=False)[:, 0]
        if not torch.any(masks > 0.01):
            raise ValueError("The custom mask is black throughout. White must mark the subject to replace.")
        return (masks,)

NODE_CLASS_MAPPINGS = {"ZuraCharacterMaskFrames": ZuraCharacterMaskFrames}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraCharacterMaskFrames": "Zura Character Mask · Match Source"}
