"""Artist image choices and native multi-reference opening-frame conditioning."""
import copy

MAX_REFERENCES = 9  # H3 accepts nine still references; Klein uses the first three for its opening plate.
REFERENCE_ROLES = ("auto", "environment", "character", "object", "detail", "style")


def resolve_appearance(body, load_asset, check_asset):
    mode = body.get("look_mode", "build")
    if mode not in ("build", "ready"):
        raise ValueError("Choose a finished starting image or build one from references.")
    identities = body.get("references", [body["character"]] if body.get("character") else [])
    if not isinstance(identities, list) or len(identities) > MAX_REFERENCES:
        raise ValueError("Use up to nine appearance reference images.")
    roles = body.get("reference_roles", [])
    if not isinstance(roles, list) or len(roles) > MAX_REFERENCES or (roles and len(roles) != len(identities)):
        raise ValueError("Reference image roles must match the uploaded images.")
    references = []
    seen = set()
    def image(identity):
        if not isinstance(identity, str) or not identity:
            raise ValueError("Choose an uploaded image.")
        asset = load_asset(identity)
        if asset.get("kind") != "asset" or asset.get("asset_kind") != "image":
            raise ValueError("Choose an image for the starting frame or appearance reference.")
        check_asset(asset)
        return copy.deepcopy(asset)
    for index, identity in enumerate(identities):
        asset = image(identity)
        role = roles[index] if index < len(roles) else "auto"
        if role not in REFERENCE_ROLES:
            raise ValueError("Choose a valid role for each reference image.")
        if roles:
            asset["role"] = role
        if identity not in seen:
            references.append(asset)
            seen.add(identity)
    starting = image(body.get("starting_image")) if mode == "ready" else None
    if mode == "build" and not references:
        raise ValueError("Add at least one reference image to build your starting frame.")
    return {"look_mode": mode, "references": references, "starting_asset": starting,
            "character": copy.deepcopy(references[0] if references else starting)}


def add_design_references(graph, references, check_asset):
    """Append genuine per-image ReferenceLatent nodes; never make a collage."""
    references = references or []
    if len(references) > 3:
        raise ValueError("The opening-frame builder supports up to three references. H3 can use up to nine directly.")
    for asset in references:
        check_asset(asset)
    if references:
        graph["121"]["inputs"]["image"] = references[0]["file"]
    positive, negative = ["92:131", 0], ["92:129", 0]
    for index, asset in enumerate(references[1:], 2):
        prefix = f"zura_reference_{index}"
        graph[prefix] = {"class_type": "LoadImage", "inputs": {"image": asset["file"]},
                         "_meta": {"title": f"Appearance reference {index}"}}
        graph[prefix + "_scale"] = copy.deepcopy(graph["92:85"])
        graph[prefix + "_scale"]["inputs"]["image"] = [prefix, 0]
        graph[prefix + "_encode"] = {"class_type": "VAEEncode", "inputs": {
            "pixels": [prefix + "_scale", 0], "vae": ["92:110", 0]}}
        for side, previous in (("positive", positive), ("negative", negative)):
            graph[prefix + "_" + side] = {"class_type": "ReferenceLatent", "inputs": {
                "conditioning": previous, "latent": [prefix + "_encode", 0]}}
        positive, negative = [prefix + "_positive", 0], [prefix + "_negative", 0]
    graph["92:103"]["inputs"].update(positive=positive, negative=negative)
    if len(references) > 1:
        prompt = graph["127"]["inputs"]["value"]
        prompt = prompt.replace("the second image", "the appearance reference images")
        prompt = prompt.replace("second image's", "appearance references'")
        graph["127"]["inputs"]["value"] = prompt + (
            " Image 1 is the source composition. Images 2 onwards are appearance references. "
            "Use all references for the selected subject, object, materials or environment, "
            "following the additional appearance direction. Return one finished frame, not a collage.")
