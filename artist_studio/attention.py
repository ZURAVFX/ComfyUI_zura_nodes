"""Select a model attention patch supported by the running ComfyUI."""


def available_attention(node_mappings):
    cls = node_mappings.get("ModelAttentionBackend")
    if cls is None:
        return None
    try:
        field = cls.INPUT_TYPES()["required"]["attention"]
        if isinstance(field[0], (list, tuple)):
            choices = field[0]
        elif field[0] == "COMBO":
            choices = field[1].get("options", ())
        else:
            choices = ()
    except (AttributeError, KeyError, TypeError, IndexError):
        return None
    if "comfy kitchen attention" in choices:
        return "comfy kitchen attention"
    if "pytorch attention" in choices:
        return "pytorch attention"
    return None


def adapt_attention(graph, node_mappings=None):
    """Preserve advertised attention, or reconnect the unpatched model.

    Unit/offline graph construction retains the authored graph when Comfy is
    not importable. In a running server the live node schema is authoritative.
    """
    if node_mappings is None:
        try:
            import nodes
            node_mappings = nodes.NODE_CLASS_MAPPINGS
        except (ImportError, AttributeError):
            return graph
    backend = available_attention(node_mappings)
    for identity, node in list(graph.items()):
        if node.get("class_type") != "ModelAttentionBackend":
            continue
        if backend:
            node["inputs"]["attention"] = backend
            continue
        upstream = node["inputs"]["model"]
        for consumer in graph.values():
            for key, value in consumer.get("inputs", {}).items():
                if value == [identity, 0]:
                    consumer["inputs"][key] = list(upstream)
        del graph[identity]
    return graph
