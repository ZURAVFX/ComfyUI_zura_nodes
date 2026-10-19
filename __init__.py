"""Zura nodes (ComfyUI_zura_nodes) · artist controls for ComfyUI workflows.

Nodes:
- Zura Load Video: uploaded local file -> trimmed 24 fps VIDEO + decoded frames.
- Zura Mask: takes any VIDEO wire; replacement-area masks (whole character /
  whole head / face only), user-controlled blockify, pose/face conditioning,
  mask preview video and the replacement mask itself.
- Zura Wan 2.2 Looped Chunks Sampler: native WanAnimateToVideo loop with cut
  handling and built-in original-audio assembly.
- Zura Wan 2.2 Turbo Switch: lazy base/accelerated model selector.
- Zura Klein Look Presets and Optional Image Edit: scene and lighting controls.
- Zura multicam: camera planning, H3 takes, and optional Klein/Wan relight.
- Zura H3 Single Angle: a selected camera still, performance video, and original audio.
- Zura LongCat Voice: local voice cloning and text-to-speech with WAV export.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import folder_paths
from aiohttp import web
from server import PromptServer

from .longcat import NODE_CLASS_MAPPINGS as LONGCAT_NODES, NODE_DISPLAY_NAME_MAPPINGS as LONGCAT_NAMES
from .qwen_voice_design import NODE_CLASS_MAPPINGS as QWEN_DESIGN_NODES, NODE_DISPLAY_NAME_MAPPINGS as QWEN_DESIGN_NAMES
from .driving_clip import NODE_CLASS_MAPPINGS as DRIVING_NODES, NODE_DISPLAY_NAME_MAPPINGS as DRIVING_NAMES
from .mask_performer import NODE_CLASS_MAPPINGS as MASK_NODES, NODE_DISPLAY_NAME_MAPPINGS as MASK_NAMES
from .render import NODE_CLASS_MAPPINGS as RENDER_NODES, NODE_DISPLAY_NAME_MAPPINGS as RENDER_NAMES
from .speed import NODE_CLASS_MAPPINGS as SPEED_NODES, NODE_DISPLAY_NAME_MAPPINGS as SPEED_NAMES
from .klein_look import NODE_CLASS_MAPPINGS as KLEIN_NODES, NODE_DISPLAY_NAME_MAPPINGS as KLEIN_NAMES
from .multicam_v3 import NODE_CLASS_MAPPINGS as MULTICAM_NODES, NODE_DISPLAY_NAME_MAPPINGS as MULTICAM_NAMES
from .multicam_v4_clean import NODE_CLASS_MAPPINGS as CLEAN_NODES, NODE_DISPLAY_NAME_MAPPINGS as CLEAN_NAMES
from .idv2v_control import NODE_CLASS_MAPPINGS as CONTROL_NODES, NODE_DISPLAY_NAME_MAPPINGS as CONTROL_NAMES
from .h3_single_angle import NODE_CLASS_MAPPINGS as SINGLE_ANGLE_NODES, NODE_DISPLAY_NAME_MAPPINGS as SINGLE_ANGLE_NAMES

NODE_CLASS_MAPPINGS = {}
NODE_CLASS_MAPPINGS.update(DRIVING_NODES)
NODE_CLASS_MAPPINGS.update(MASK_NODES)
NODE_CLASS_MAPPINGS.update(RENDER_NODES)
NODE_CLASS_MAPPINGS.update(SPEED_NODES)
NODE_CLASS_MAPPINGS.update(KLEIN_NODES)
NODE_CLASS_MAPPINGS.update(MULTICAM_NODES)
NODE_CLASS_MAPPINGS.update(CLEAN_NODES)
NODE_CLASS_MAPPINGS.update(CONTROL_NODES)
NODE_CLASS_MAPPINGS.update(SINGLE_ANGLE_NODES)
NODE_CLASS_MAPPINGS.update(LONGCAT_NODES)
NODE_CLASS_MAPPINGS.update(QWEN_DESIGN_NODES)

NODE_DISPLAY_NAME_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS.update(DRIVING_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(MASK_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(RENDER_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(SPEED_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(KLEIN_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(MULTICAM_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(CLEAN_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(CONTROL_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(SINGLE_ANGLE_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(LONGCAT_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(QWEN_DESIGN_NAMES)

WEB_DIRECTORY = "./web"
PACKAGE_ROOT = Path(__file__).resolve().parent
__version__ = "1.3.26"


def _register_routes():
    """Register UI routes only after ComfyUI has created PromptServer.instance."""
    server = getattr(PromptServer, "instance", None)
    if server is None:
        return

    @server.routes.post('/zura/video_candidates')
    async def zura_video_candidates(request):
        from .media_source import discover_video, require_same_origin
        require_same_origin(request)
        data = await request.json()
        keyword = str(data.get('keyword', '')).strip()[:160]
        hint = str(data.get('hint', 'live dance')).strip()[:160]
        views = max(0, min(int(data.get('minimum_views', 10000)), 1000000000))
        youtube_mode = str(data.get('youtube_mode', 'Any YouTube video'))
        shorts_only = youtube_mode == 'YouTube Shorts only (vertical)'
        duration = float(data.get('duration', 10))
        try:
            _, receipt = await asyncio.to_thread(discover_video, keyword, hint, 0, views, shorts_only)
            receipt['context'] = [keyword, hint, views, youtube_mode, duration]
            return web.json_response(receipt)
        except Exception as exc:
            return web.json_response({'error': str(exc)}, status=400)

    @server.routes.post('/zura/preview_video')
    async def zura_preview_video(request):
        from .media_source import preview_clip, require_same_origin
        require_same_origin(request)
        data = await request.json()
        try:
            result = await asyncio.to_thread(
                preview_clip, str(data.get('url', '')), float(data.get('start', 0)),
                bool(data.get('automatic', True)),
                str(data.get('youtube_mode', 'Any YouTube video')) == 'YouTube Shorts only (vertical)',
                float(data.get('duration', 10)), int(data.get('source_max_side', 1280)))
            return web.json_response(result)
        except Exception as exc:
            return web.json_response({'error': str(exc)}, status=400)


_register_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

# Shared character-replacement interface and native Wan preparation adapters.
from .wan_artist import NODE_CLASS_MAPPINGS as WAN_ARTIST_NODES, NODE_DISPLAY_NAME_MAPPINGS as WAN_ARTIST_NAMES
from .wan_artist import ZuraWanLoadMappedPreparation
from .wan_preparation_windows import ZuraWanLoadWindowPreparation
from .bounded_video_audio import ZuraApplyBoundedReferenceAudio
from .wan_preparation_parts import ZuraWanPreparationWindow, ZuraWanCarryPoseWindow, ZuraWanSavePreparationPart
from .wan_preparation_runtime import ZuraWanMergePreparation
from .artist_studio.wan_graph_guard import ZuraWanGraphQueueGuard
from .render import ZuraWan22StreamedSampler
from .artist_studio import NODE_CLASS_MAPPINGS as STUDIO_NODES, NODE_DISPLAY_NAME_MAPPINGS as STUDIO_NAMES
from .studio_mask_cleanup import NODE_CLASS_MAPPINGS as MASK_CLEANUP_NODES, NODE_DISPLAY_NAME_MAPPINGS as MASK_CLEANUP_NAMES
from .video_latent_data import NODE_CLASS_MAPPINGS as VIDEO_DATA_NODES, NODE_DISPLAY_NAME_MAPPINGS as VIDEO_DATA_NAMES
from .h3_reference_data import NODE_CLASS_MAPPINGS as H3_REFERENCE_DATA_NODES, NODE_DISPLAY_NAME_MAPPINGS as H3_REFERENCE_DATA_NAMES
from .h3_control_data import NODE_CLASS_MAPPINGS as H3_CONTROL_DATA_NODES, NODE_DISPLAY_NAME_MAPPINGS as H3_CONTROL_DATA_NAMES
from .h3_start_frame import NODE_CLASS_MAPPINGS as H3_START_NODES, NODE_DISPLAY_NAME_MAPPINGS as H3_START_NAMES
NODE_CLASS_MAPPINGS.update(H3_START_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(H3_START_NAMES)
NODE_CLASS_MAPPINGS.update(WAN_ARTIST_NODES)
NODE_CLASS_MAPPINGS.update(STUDIO_NODES)
NODE_CLASS_MAPPINGS.update(MASK_CLEANUP_NODES)
NODE_CLASS_MAPPINGS.update(VIDEO_DATA_NODES)
NODE_CLASS_MAPPINGS.update(H3_REFERENCE_DATA_NODES)
NODE_CLASS_MAPPINGS.update(H3_CONTROL_DATA_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(WAN_ARTIST_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(STUDIO_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(MASK_CLEANUP_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(VIDEO_DATA_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(H3_REFERENCE_DATA_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(H3_CONTROL_DATA_NAMES)
NODE_CLASS_MAPPINGS.update({
    "ZuraWanLoadMappedPreparation": ZuraWanLoadMappedPreparation,
    "ZuraWanLoadWindowPreparation": ZuraWanLoadWindowPreparation,
    "ZuraApplyBoundedReferenceAudio": ZuraApplyBoundedReferenceAudio,
    "ZuraWan22StreamedSampler": ZuraWan22StreamedSampler,
    "ZuraWanPreparationWindow": ZuraWanPreparationWindow,
    "ZuraWanCarryPoseWindow": ZuraWanCarryPoseWindow,
    "ZuraWanSavePreparationPart": ZuraWanSavePreparationPart,
    "ZuraWanMergePreparation": ZuraWanMergePreparation,
    "ZuraWanGraphQueueGuard": ZuraWanGraphQueueGuard,
})
NODE_DISPLAY_NAME_MAPPINGS.update({
    "ZuraWanLoadMappedPreparation": "Zura · Load File-Backed Wan Motion",
    "ZuraWanLoadWindowPreparation": "Zura · Load Wan Motion in Sections",
    "ZuraApplyBoundedReferenceAudio": "Zura · Reference Audio for Video",
    "ZuraWan22StreamedSampler": "Zura · Wan Video Render",
    "ZuraWanPreparationWindow": "Zura · Prepare Motion Section",
    "ZuraWanCarryPoseWindow": "Zura · Continue Motion Preparation",
    "ZuraWanSavePreparationPart": "Zura · Save Motion Section",
    "ZuraWanMergePreparation": "Zura · Finish Motion Preparation",
    "ZuraWanGraphQueueGuard": "Zura · Check Motion Section",
})
for _name in STUDIO_NODES:
    _display_name = NODE_DISPLAY_NAME_MAPPINGS.get(_name, _name)
    NODE_DISPLAY_NAME_MAPPINGS[_name] = _display_name if _display_name.startswith("Zura · ") else "Zura · " + _display_name


from .dialogue_signals import NODE_CLASS_MAPPINGS as DIALOGUE_SIGNALS
for _dialogue_name, _dialogue_class in DIALOGUE_SIGNALS.items():
    NODE_CLASS_MAPPINGS.setdefault(_dialogue_name, _dialogue_class)
from .dialogue_edit import NODE_CLASS_MAPPINGS as DIALOGUE_NODES, NODE_DISPLAY_NAME_MAPPINGS as DIALOGUE_NAMES
from .dialogue_edit import register_routes as register_dialogue_routes
NODE_CLASS_MAPPINGS.update(DIALOGUE_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(DIALOGUE_NAMES)
from .audio_dialogue import NODE_CLASS_MAPPINGS as AUDIO_DIALOGUE_NODES, NODE_DISPLAY_NAME_MAPPINGS as AUDIO_DIALOGUE_NAMES
from .audio_dialogue import register_routes as register_audio_dialogue_routes
NODE_CLASS_MAPPINGS.update(AUDIO_DIALOGUE_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(AUDIO_DIALOGUE_NAMES)
if getattr(PromptServer, "instance", None) is not None:
    register_dialogue_routes(PromptServer.instance)
    register_audio_dialogue_routes(PromptServer.instance)
