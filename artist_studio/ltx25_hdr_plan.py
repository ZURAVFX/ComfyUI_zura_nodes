"""Internal HDR appearance experiment for the staged LTX performance route.

The reviewed source drives pose/edges and audio. A caller-verified EXR supplies
native HDR appearance. This is not an official Union/HDR recipe or a qualified
Studio default. Its separate import route is enabled only for development.
"""
from __future__ import annotations

import copy

from . import ltx25
from .hdr_delivery import ltx_hdr_delivery
from .ltx_hdr_endpoints import VIDEO_VAE, MAX_PIXEL_FRAMES, endpoint_source


def build_native_hdr_plan(project, *, hdr_endpoint, hdr_source=None, output="hlg_and_exr", **kwargs):
    """Adapt an approved native plan without sharing SDR caches or thumbnails.

    The caller must resolve/check the EXR manifest and every model pin, and
    associate that EXR with the approved opening. Its PNG is display-only.
    Existing signed Union masks and frozen soundtrack semantics stay intact.
    """
    if project.get("config", {}).get("viewport_render"):
        raise ValueError("Native HDR performance is not a viewport recipe.")
    if output not in ("hlg_video", "hlg_and_exr", "acescg_exr"):
        raise ValueError("Choose an HDR output for the native HDR opening.")
    if hdr_endpoint.get('kind') == 'video':
        if (not hdr_source or hdr_endpoint.get('source_sha') != hdr_source.get('sha')
                or hdr_endpoint.get('path') != hdr_source.get('path')
                or hdr_endpoint.get('start_seconds') != hdr_source.get('start_seconds')
                or hdr_endpoint.get('colour_space') != hdr_source.get('colour_space')):
            raise ValueError('The HDR appearance must match the approved HDR video interval.')
        opening = {'class_type': 'ZuraHDRSelectNativeTimeline', 'inputs': {
            'source': hdr_endpoint['path'], 'start_seconds': hdr_endpoint['start_seconds'],
            'frame_count': 1, 'output_fps': 24., 'colour_space': hdr_endpoint['colour_space'], 'sequence_fps': 24.}}
    else:
        opening = endpoint_source(hdr_endpoint)
    if hdr_endpoint.get("opening_key") != project.get("opening_key") or not project.get("opening_key"):
        raise ValueError("The HDR endpoint must match the approved opening.")
    models = copy.deepcopy(kwargs.get("models", {}))
    if models.get("video_vae") != VIDEO_VAE:
        raise ValueError("Native HDR requires the full LTX 2.5 video VAE.")
    # Reuse the proven timing/approval/guide validation and graph topology.
    # Only this temporary template uses the SDR VAE name; the final plan and
    # model pins name the caller's actual full HDR VAE before hashing.
    template_args = copy.deepcopy(kwargs)
    template_args["models"]["video_vae"] = ltx25.QUALIFIED_MODELS["video_vae"]
    plan = ltx25.build_plan(project, **template_args)
    basis = plan["basis"]
    if basis["native"][0] * basis["native"][1] * basis["padded"] > MAX_PIXEL_FRAMES:
        raise ValueError("This native HDR selection exceeds the software memory budget.")
    basis["models"] = models
    basis["native_hdr"] = {
        "recipe": "union_hdr_appearance_experiment_v1",
        "endpoint": copy.deepcopy(opening["inputs"]),
        "approved_opening": project["opening_key"],
        "output": output,
        "guide_space": "ACEScct",
        "resize_space": "linear ACEScg",
    }
    from .ltx_hdr_performance import marker as hdr_video_marker
    source_marker = hdr_video_marker(project.get("source"))
    if bool(source_marker) != bool(hdr_source):
        raise ValueError("The original HDR video and selected interval must be verified together.")
    if hdr_source:
        timeline = basis["timeline"]
        if (hdr_source.get("asset_id") != source_marker["asset_id"] or
                hdr_source.get("sha") != source_marker["sha"] or
                hdr_source.get("colour_space") != source_marker["colour_space"] or
                hdr_source.get("file") != project["source"]["file"] or
                hdr_source.get("start_seconds") != timeline.get("start") or
                hdr_source.get("frames") != basis["frames"] or hdr_source.get("fps") != timeline.get("fps")):
            raise ValueError("The HDR video does not match the approved source interval.")
        # The original is retained for provenance and audio; the approved SDR
        # review drives the Union pose/edge control. The EXR is the native HDR
        # appearance anchor. Never describe the proxy as native conditioning.
        basis["native_hdr"]["source"] = {key: value for key, value in hdr_source.items() if key != "path"}
    old_key = plan["key"]
    new_key = ltx25.digest(basis)
    replacements = {old_key: new_key}
    for name, spec in plan["artifacts"].items():
        if "key" in spec:
            replacements[spec["key"]] = ltx25.digest({"plan": new_key, "artifact": name})

    # Do not rewrite arbitrary prompt strings or verified file identities.
    def new_prefix(value):
        return value.replace("zura/ltx25/" + old_key + "/", "zura/ltx25/" + new_key + "/", 1)

    for graph in plan["phases"].values():
        for node in graph.values():
            fields = node["inputs"]
            if "cache_key" in fields:
                fields["cache_key"] = replacements[fields["cache_key"]]
            if "filename_prefix" in fields:
                fields["filename_prefix"] = new_prefix(fields["filename_prefix"])
    for spec in plan["artifacts"].values():
        if "key" in spec:
            spec["key"] = replacements[spec["key"]]
        if "prefix" in spec:
            spec["prefix"] = new_prefix(spec["prefix"])
    plan["key"] = new_key
    phases = plan["phases"]

    def n(kind, **inputs):
        return {"class_type": kind, "inputs": inputs}

    def fit_linear(graph, image, width, height, prefix, crop):
        graph[prefix + "_linear"] = n("ImageColorSpace", image=image,
            source="HDR ACEScct", destination="linear ACEScg")
        graph[prefix + "_size"] = n("ImageScale", image=[prefix + "_linear", 0],
            width=width, height=height, upscale_method="bilinear", crop=crop)
        graph[prefix] = n("ImageColorSpace", image=[prefix + "_size", 0],
            source="linear ACEScg", destination="HDR ACEScct")
        return [prefix, 0]

    for phase, graph in phases.items():
        if "video_vae" in graph:
            graph["video_vae_load"] = n("VAELoader", vae_name=VIDEO_VAE)
            graph["video_vae"] = n("LTXVVAEForceFloat32", vae=["video_vae_load", 0])
        if "opening" in graph:
            graph["opening"] = copy.deepcopy(opening)
            size = basis["base"] if phase == "stage1" else basis["native"]
            # Preserve the existing consumer link while removing JPEG entirely.
            fit_linear(graph, ["opening", 0], *size, "preprocess", "center")
    # The full HDR VAE expects the control image in the same working encoding.
    # Pose/edge extraction itself still uses the reviewed SDR viewing source.
    guide = phases["stage1"]["guide"]["inputs"]
    phases["stage1"]["guide_colour"] = n("ImageColorSpace", image=guide["image"],
        source="sRGB", destination="HDR ACEScct")
    guide["image"] = ["guide_colour", 0]

    graph = phases["decode"]
    graph.pop("create_video")
    graph.pop("save_video")
    images = fit_linear(graph, ["trim_frames", 0], *basis["delivery"], "delivery_size", "disabled")
    audio = ["trim_audio", 0] if "trim_audio" in graph else None
    prefix = "performance_" + new_key[:32]
    graph.update(ltx_hdr_delivery(images, basis["timeline"]["fps"], output=output,
        prefix=prefix, working_space="ltx25_acescct_qualified", audio=audio))
    if output in ("hlg_and_exr", "acescg_exr"):
        graph["zura_hdr_archive"] = n("ZuraHDRPackageACEScct", images=images, prefix=prefix)
        preview = ["zura_hdr_exr", 0]
    else:
        graph["tonemap"] = n("LTXVHDRDecodePostprocess", image=images, transfer="acescct",
            save_exr=False, exr_color_space="acescg", output_dir="genj/hdr/" + prefix,
            filename_prefix="frame", half_precision=True)
        preview = ["tonemap", 0]
    inputs = {"images": preview, "fps": basis["timeline"]["fps"]}
    if audio is not None:
        inputs["audio"] = audio
    graph["preview_video"] = n("CreateVideo", **inputs)
    graph["save_preview"] = n("ZuraHDRSaveExactRate", video=["preview_video", 0],
        filename_prefix="genj/hdr/" + prefix + "_preview", fps=basis["timeline"]["fps"])
    titles = {"opening": "Read original HDR appearance reference",
        "video_vae_load": "Load full HDR VAE", "video_vae": "Prepare float32 HDR VAE",
        "sample": "Generate HDR performance", "decode": "Decode HDR performance",
        "save_preview": "Save SDR viewing preview", "zura_hdr_save_video": "Save HLG master",
        "zura_hdr_archive": "Package ACEScg EXR frames"}
    for graph in phases.values():
        for name, title in titles.items():
            if name in graph:
                graph[name]["_meta"] = {"title": title}
    plan["graph_hashes"] = {phase: ltx25.digest(graph) for phase, graph in phases.items()}
    plan["hdr_delivery"] = {"output": output, "prefix": prefix,
        "preview_node": "save_preview", "video_node": "zura_hdr_save_video" if output != "acescg_exr" else None,
        "archive_node": "zura_hdr_archive" if output != "hlg_video" else None}
    plan["qualification"] = "Internal native HDR Union experiment. Not enabled in Studio by default; representative HDR/artist qualification required."
    return plan
