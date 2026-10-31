"""Small plate/anchor/ROI adapters. Sampling stays in native LTX nodes."""
from .paintout import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from . import browser
from .attention import ZuraPaintoutGuideMemory
NODE_CLASS_MAPPINGS['ZuraPaintoutGuideMemory'] = ZuraPaintoutGuideMemory
NODE_DISPLAY_NAME_MAPPINGS['ZuraPaintoutGuideMemory'] = 'Bound LTX Guide Memory'
from .frame_editor import NODE_CLASS_MAPPINGS as FRAME_NODES, NODE_DISPLAY_NAME_MAPPINGS as FRAME_NAMES
from .editor_store import NODE_CLASS_MAPPINGS as EDITOR_NODES, NODE_DISPLAY_NAME_MAPPINGS as EDITOR_NAMES, register_routes
NODE_CLASS_MAPPINGS.update(FRAME_NODES)
NODE_CLASS_MAPPINGS.update(EDITOR_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(FRAME_NAMES)
NODE_DISPLAY_NAME_MAPPINGS.update(EDITOR_NAMES)
register_routes()
from . import editor_routes
editor_routes.register_routes()


from .hdr import NODE_CLASS_MAPPINGS as HDR_NODES, NODE_DISPLAY_NAME_MAPPINGS as HDR_NAMES
NODE_CLASS_MAPPINGS.update(HDR_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(HDR_NAMES)

from .hdr_conditioning import ZuraPaintoutHDRConditioning
NODE_CLASS_MAPPINGS["ZuraPaintoutHDRConditioning"] = ZuraPaintoutHDRConditioning
NODE_DISPLAY_NAME_MAPPINGS["ZuraPaintoutHDRConditioning"] = "Paintout HDR Scene Conditioning"

from .frame_target import NODE_CLASS_MAPPINGS as TARGET_NODES, NODE_DISPLAY_NAME_MAPPINGS as TARGET_NAMES
NODE_CLASS_MAPPINGS.update(TARGET_NODES)
NODE_DISPLAY_NAME_MAPPINGS.update(TARGET_NAMES)

from . import frame_layers
frame_layers.register_routes()

from . import model_downloads
model_downloads.register_routes()
