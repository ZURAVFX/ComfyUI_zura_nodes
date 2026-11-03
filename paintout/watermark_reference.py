"""Optional first-frame guide; shares footage crop and colour transforms."""
import json
from .paintout import ZuraPaintoutAnchors, string
class ZuraWatermarkReference:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'plate': ('ZURA_PLATE',), 'file': string(), 'colour_space': (['srgb_display','acescg','acescct','hlg_rec2020','pq_rec2020','linear_rec709','rec709_gamma24','rec709_oetf'],)}}
    RETURN_TYPES = ('IMAGE',)
    FUNCTION = 'load'
    CATEGORY = 'Zura/Paintout'
    @classmethod
    def IS_CHANGED(cls, **kwargs): return float('nan')
    def load(self, plate, file, colour_space):
        anchors, _ = ZuraPaintoutAnchors().load(plate, json.dumps([dict(file=file,frame=plate['start'],strength=.7,colour_space=colour_space)]))
        return (anchors[0][1],)
