"""Build one source-video-conditioned H3 graph for a whole Studio shot."""

import asyncio

from aiohttp import web

from .switch_x_graph import CONTROL, generation_graph
from .switch_x_media import STILLS, canvas, input_path, opened, source_info


def processing_size(width, height, config):
    scale = config.get("scale", "legacy")
    if scale == "legacy":
        side = int(config.get("side", 1024))
        if side not in (512, 768, 1024, 1280, 1920, 3840):
            raise ValueError("Choose a supported H3 processing resolution.")
    else:
        scale = float(scale)
        if scale not in (1, 0.75, 0.5, 0.25):
            raise ValueError("Choose Full, 75%, 50% or 25% resolution.")
        side = max(32, round(max(width, height) * scale))
    _, _, gw, gh = canvas(width, height, side)
    if max(gw, gh) > 4096 or gw * gh > 8_388_608:
        raise ValueError("This size exceeds the H3 canvas. Choose a lower processing resolution.")
    return side, gw, gh


def build(config):
    source, matte = config["source"], config["matte"]
    w, h, total, rate = source_info(input_path(source))
    mask_file = input_path(matte)
    mw, mh, mcount, mrate = source_info(mask_file)
    if (mw, mh) != (w, h) or mask_file.suffix.lower() not in STILLS and mcount != total:
        raise ValueError(
            "Match the source dimensions and frame count, or use a single still matte."
        )
    if total < 1 or total / rate > 20.05:
        raise ValueError("Choose a shot up to 20 seconds long.")
    side, gw, gh = processing_size(w, h, config)
    guidance = float(config.get("structureStrength", 0.96))
    if not 0 <= guidance <= 1:
        raise ValueError("Source detail strength must be between zero and one.")
    refs = config.get("refs", [])
    for ref in refs:
        input_path(ref)
    pins = config.get("pinnedFrames", {})
    if not isinstance(pins, dict) or any(
        path not in refs or type(number) is not int or not 0 <= number < total
        for path, number in pins.items()
    ):
        raise ValueError(f"Pin each look to a source frame between 0 and {total - 1}.")
    seed = int(config.get("seed", 42))
    steps = int(config.get("steps", 8))
    if steps not in (8, 40):
        raise ValueError("Choose the eight-step or forty-step H3 pass.")
    if len(set(pins.values())) != len(pins):
        raise ValueError("Pin one appearance reference per source frame.")
    instruction = config.get("prompt", "").strip()
    if not instruction and refs:
        instruction = "Use the references to change the scene around the filmed performance."
    if not instruction:
        raise ValueError("Describe the requested change or choose a reference image.")
    graph = generation_graph(refs, instruction, gw, gh, total, seed, steps, guidance)
    role = config.get("whiteMeans", "keep")
    channel = config.get("maskChannel", "luma")
    if role not in ("keep", "replace") or channel not in ("luma", "alpha"):
        raise ValueError("Choose a valid matte meaning and channel.")
    graph["plates"] = {
        "class_type": "ZuraSwitchXGuide",
        "inputs": dict(
            source=source,
            matte=matte,
            start=0,
            count=total,
            side=side,
            white_means=role,
            mask_channel=channel,
        ),
    }
    graph["protected_latent"] = {
        "class_type": "ZuraSwitchXProtectedLatent",
        "inputs": {
            "latent": ["scene", 1],
            "source": ["source_latent", 0],
            "replace": ["plates", 1],
            "allow_relight": role == "keep",
        },
    }
    graph["sample"]["inputs"]["latent_image"] = ["protected_latent", 0]
    depth = config.get("depthGuide", False)
    if role == "replace" or depth:
        graph["control_weights"] = {"class_type": "ModelPatchLoader", "inputs": {"name": CONTROL}}
        graph["edit_region"] = {
            "class_type": "MiniMaxH3FunControlNetApply",
            "inputs": {
                "model": ["shift", 0],
                "model_patch": ["control_weights", 0],
                "vae": ["vae", 0],
                "strength": 0.85,
                "start_percent": 0.0,
                "end_percent": 0.9,
            },
        }
        graph["structure"]["inputs"]["model"] = ["edit_region", 0]
    if role == "replace":
        graph["plates"]["inputs"]["neutralize_replacement"] = True
        margin = int(config.get("replacementMargin", 8))
        if not 0 <= margin <= 128:
            raise ValueError("Choose an edit margin from 0 to 128 pixels.")
        edit = ["plates", 1]
        if margin:
            graph["edit_margin"] = {
                "class_type": "GrowMask",
                "inputs": {"mask": edit, "expand": margin, "tapered_corners": True},
            }
            edit = ["edit_margin", 0]
        graph["edit_region"]["inputs"].update(source_video=["plates", 0], mask=edit)
        graph["protected_latent"]["inputs"]["replace"] = edit
        graph["structure"]["inputs"]["replace"] = edit
    if depth:
        graph["depth"] = {
            "class_type": "DepthAnythingV2Preprocessor",
            "inputs": {
                "image": ["plates", 0],
                "ckpt_name": "depth_anything_v2_vitl.pth",
                "resolution": 512,
            },
        }
        graph["edit_region"]["inputs"]["control_video"] = ["depth", 0]
    positive = ["scene", 0]
    for path, number in sorted(pins.items(), key=lambda pair: pair[1]):
        slot = refs.index(path)
        key = f"look_{slot}"
        graph[key] = {
            "class_type": "ZuraSwitchXLookFrame",
            "inputs": {
                "image": [f"ref_{slot}", 0],
                "source": source,
                "frame": number,
                "side": side,
            },
        }
        graph[key + "_pin"] = {
            "class_type": "MiniMaxH3AddGuide",
            "inputs": {
                "positive": positive,
                "vae": ["vae", 0],
                "latent": ["scene", 1],
                "image": [key, 0],
                "frame_idx": number,
            },
        }
        positive = [key + "_pin", 0]
    graph["guide"]["inputs"]["conditioning"] = positive
    audio_file = config.get("selectedAudio")
    if audio_file:
        input_path(audio_file)
        graph["source_audio"] = {"class_type": "LoadAudio", "inputs": {"audio": audio_file}}
        graph["shot_audio"] = {
            "class_type": "TrimAudioDuration",
            "inputs": {
                "audio": ["source_audio", 0],
                "start_index": 0,
                "duration": float(total / rate),
            },
        }
        audio = ["shot_audio", 0]
        if rate != 24:
            graph["audio_clock"] = {
                "class_type": "ZuraComfyLinkRateAudio",
                "inputs": {"audio": audio, "speed": 24 / float(rate)},
            }
            audio = ["audio_clock", 0]
        graph["vocal_lock"] = {
            "class_type": "ZuraH3LockReferenceAudio",
            "inputs": {
                "latent": ["protected_latent", 0],
                "audio_vae": ["audio_vae", 0],
                "audio": audio,
            },
        }
        graph["sample"]["inputs"]["latent_image"] = ["vocal_lock", 0]
    graph["finish"] = {
        "class_type": "ZuraSwitchXDeliver",
        "inputs": {
            "images": ["decode", 0],
            "source": source,
            "side": side,
            "lossless": bool(config.get("lossless", False)),
        },
    }
    if "selectedAudio" in config:
        graph["finish"]["inputs"]["audio_file"] = audio_file or ""
        graph["finish"]["inputs"]["mute"] = not bool(audio_file)
    return graph


def register(routes):
    from .switch_x_selection import preview_selection, reviewed_inputs

    @routes.post("/zura/studio/switch-x/review")
    async def import_review(request):
        from ..media_source import require_same_origin

        require_same_origin(request)
        try:
            config = await request.json()
            result = await asyncio.to_thread(reviewed_inputs, config["project"])
            return web.json_response(result)
        except (ValueError, KeyError, OSError, TypeError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    @routes.get("/zura/studio/switch-x/selection")
    async def selection(request):
        try:
            body = await asyncio.to_thread(preview_selection, dict(request.query))
            return web.Response(
                body=body, content_type="image/jpeg", headers={"Cache-Control": "no-store"}
            )
        except (ValueError, KeyError, OSError, TypeError, StopIteration) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    @routes.post("/zura/studio/switch-x/source")
    async def native_source(request):
        try:
            config = await request.json()
            path = input_path(config["source"])
            width, height, count, rate = await asyncio.to_thread(source_info, path)
            with opened(path) as media:
                has_audio = bool(media.streams.audio)
            _, gw, gh = processing_size(width, height, config)
            return web.json_response(
                {
                    "width": gw,
                    "height": gh,
                    "sourceWidth": width,
                    "sourceHeight": height,
                    "frames": count,
                    "fps": float(rate),
                    "duration": float(count / rate),
                    "hasAudio": has_audio,
                }
            )
        except (ValueError, KeyError, OSError, TypeError, IndexError) as exc:
            return web.json_response({"error": str(exc)}, status=400)

    @routes.post("/zura/studio/switch-x/graph")
    async def graph(request):
        try:
            config = await request.json()
            return web.json_response({"graph": await asyncio.to_thread(build, config)})
        except (ValueError, KeyError, OSError, TypeError, IndexError) as exc:
            return web.json_response({"error": str(exc)}, status=400)
