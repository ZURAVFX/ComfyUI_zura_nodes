"""Small plate/anchor/ROI adapters. Sampling stays in native LTX nodes."""
from .paintout import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from . import browser
from .attention import ZuraPaintoutGuideMemory
NODE_CLASS_MAPPINGS['ZuraPaintoutGuideMemory'] = ZuraPaintoutGuideMemory
NODE_DISPLAY_NAME_MAPPINGS['ZuraPaintoutGuideMemory'] = 'Bound LTX Guide Memory'
