"""Thin graph data hand-offs. They neither infer nor copy tensors/models."""
import json


class ZuraStudioSignals:
    CATEGORY = "Zura/Graph"
    FUNCTION = "pack"
    RETURN_TYPES = ("ZURA_STUDIO_SIGNALS",)
    RETURN_NAMES = ("stage_data",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"keys": ("STRING", {"default": "[]"})},
                "optional": {"previous": ("ZURA_STUDIO_SIGNALS",),
                             **{f"value_{i}": ("*",) for i in range(64)}}}
    def pack(self, keys, previous=None, **values):
        names = json.loads(keys)
        if not isinstance(names,list) or len(names)>64 or not all(isinstance(k,str) for k in names) or len(set(names))!=len(names):
            raise ValueError("The stage hand-off contains invalid signal names.")
        result = dict(previous or {})
        for i,name in enumerate(names):
            slot=f"value_{i}"
            if slot not in values:
                raise ValueError("Connect the stage signal: "+name)
            result[name]=values[slot]
        return (result,)


class ZuraStudioReadSignal:
    CATEGORY = "Zura/Graph"
    FUNCTION = "read"
    RETURN_TYPES = ("*",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"stage_data": ("ZURA_STUDIO_SIGNALS",), "key": ("STRING", {"default": ""})}}
    def read(self, stage_data, key):
        if key not in stage_data:
            raise ValueError("The previous stage has no signal named "+key)
        return (stage_data[key],)


NODE_CLASS_MAPPINGS={c.__name__:c for c in (ZuraStudioSignals,ZuraStudioReadSignal)}
NODE_DISPLAY_NAME_MAPPINGS={"ZuraStudioSignals":"Zura · Stage Hand-off","ZuraStudioReadSignal":"Zura · Read Stage Signal"}
