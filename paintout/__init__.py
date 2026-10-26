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
