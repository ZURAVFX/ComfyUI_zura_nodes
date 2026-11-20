"""Direct OpenAI Images API access for native ComfyUI graphs."""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import ipaddress
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import aiohttp
from aiohttp import web
import numpy as np
from PIL import Image, ImageOps, ImageSequence
import torch


MODELS = [
    "gpt-image-2.6-sunburst", "gpt-image-2.6-flare",
    "gpt-image-2.5-sunburst", "gpt-image-2.5-flare",
    "gpt-image-2.5-sunburst-2026-09-08", "gpt-image-2.5-flare-2026-09-08",
    "gpt-image-2", "gpt-image-2-2026-04-21",
    "gpt-image-1.5", "gpt-image-1.5-2025-12-16", "gpt-image-1-mini", "chatgpt-image-latest",
]
MODEL_ID = re.compile(r"[A-Za-z0-9_.:-]{1,200}")
LEGACY_15 = ("gpt-image-1.5", "gpt-image-1.5-2025-12-16")
PRESET_SIZES = ["auto", "1024x1024", "1536x1024", "1024x1536"]
OUTPUT_FORMATS = ["png", "webp", "jpeg", "gif", "svg"]
API_ROOT = "https://api.openai.com/v1/images"
_session_key = ""


def _api_key():
    return _session_key or os.environ.get("OPENAI_API_KEY", "").strip()


def _is_loopback(host):
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
        return (getattr(address, "ipv4_mapped", None) or address).is_loopback
    except ValueError:
        return False


def _require_local_request(request):
    from comfy.cli_args import args

    try:
        host = urlsplit("//" + request.host).hostname
    except ValueError:
        host = None
    origin = request.headers.get("Origin")
    if (
        not request.remote or not _is_loopback(request.remote)
        or host is None or not _is_loopback(host)
        or not all(_is_loopback(address.strip(" []")) for address in args.listen.split(","))
        or request.headers.get("Sec-Fetch-Site") == "cross-site"
        or (origin and origin not in (f"http://{request.host}", f"https://{request.host}"))
        or (request.method in ("POST", "DELETE") and not origin)
    ):
        raise web.HTTPForbidden(text="Use the key dialog in a loopback-only ComfyUI session.")


def _model_choices(records):
    discovered = set()
    for record in records:
        model = record.get("id", "") if isinstance(record, dict) else ""
        if (
            isinstance(model, str) and MODEL_ID.fullmatch(model)
            and model.startswith(("gpt-image-", "chatgpt-image-"))
            and model != "gpt-image-1" and not re.fullmatch(r"gpt-image-1-\d{4}-\d{2}-\d{2}", model)
        ):
            discovered.add(model)
    return [*MODELS, *sorted(discovered.difference(MODELS))]


async def _list_project_models(key):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as session:
        async with session.get("https://api.openai.com/v1/models", allow_redirects=False,
                               headers={"Authorization": f"Bearer {key}"}) as response:
            response.raise_for_status()
            return _model_choices((await response.json())["data"])


def register_credentials(routes):
    @routes.view("/zura/openai_image/key")
    async def image_key(request):
        global _session_key
        _require_local_request(request)
        if request.method == "POST":
            if request.content_length is None or request.content_length > 2048:
                raise web.HTTPBadRequest(text="Invalid API key request.")
            try:
                body = await request.json()
                key = body["key"].strip()
            except (ValueError, KeyError, TypeError, AttributeError):
                raise web.HTTPBadRequest(text="Invalid API key request.") from None
            if not re.fullmatch(r"sk-[A-Za-z0-9_-]{12,500}", key):
                raise web.HTTPBadRequest(text="Enter a valid OpenAI API key.")
            _session_key = key
        elif request.method == "DELETE":
            _session_key = ""
        elif request.method != "GET":
            raise web.HTTPMethodNotAllowed(request.method, ["GET", "POST", "DELETE"])
        source = "session" if _session_key else "environment" if _api_key() else "none"
        return web.json_response({"source": source}, headers={"Cache-Control": "no-store"})

    @routes.get("/zura/openai_image/models")
    async def image_models(request):
        _require_local_request(request)
        key = _api_key()
        models = MODELS
        if key:
            try:
                models = await _list_project_models(key)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
                # Some restricted keys can create images without listing models.
                pass
        return web.json_response({"models": models}, headers={"Cache-Control": "no-store"})


def _validate_size(size, model, is_gif=False):
    if size in PRESET_SIZES:
        return
    if model in (*LEGACY_15, "gpt-image-1-mini"):
        raise ValueError(f"{model} supports Auto and the three standard output sizes.")
    if not re.fullmatch(r"[0-9]{1,4}x[0-9]{1,4}", size):
        raise ValueError("Enter output dimensions as WIDTHxHEIGHT, such as 1920x1088.")
    width, height = map(int, size.split("x"))
    if not (width and height and width % 16 == height % 16 == 0
            and max(width, height) <= 3840 and max(width, height) <= 3 * min(width, height)
            and width * height <= 8_294_400 and (is_gif or width * height >= 655_360)):
        raise ValueError("Use edges divisible by 16, at most 3840 px, an aspect ratio up to 3:1, "
                         "and 655,360 to 8,294,400 pixels for stills.")


def _image_reference(value):
    if value.startswith("file-"):
        return {"file_id": value}
    if value.startswith(("https://", "data:image/png;base64,", "data:image/jpeg;base64,", "data:image/webp;base64,")):
        return {"image_url": value}
    raise ValueError("Use HTTPS URLs, PNG/JPEG/WebP data URLs or OpenAI file IDs for API references.")


def _pil_frame(tensor):
    array = (tensor.detach().cpu().numpy().clip(0, 1) * 255).round().astype(np.uint8)
    return Image.fromarray(array.squeeze(-1) if array.ndim == 3 and array.shape[-1] == 1 else array)


def _png(image):
    with io.BytesIO() as buffer:
        image.save(buffer, format="PNG")
        if buffer.tell() >= 50_000_000:
            raise ValueError("Each input PNG must be under 50 MB. Reduce the input dimensions.")
        return buffer.getvalue()


def _encode_inputs(references, mask, markup, markup_alpha, width, height):
    source_size = references[0].shape[2], references[0].shape[1]
    output_size = (width, height) if width else None
    files = []
    for batch in references:
        for frame in batch:
            image = _pil_frame(frame)
            if output_size and output_size != image.size:
                image = image.resize(output_size, Image.Resampling.LANCZOS)
            files.append(_png(image))
    if mask is None and markup is None:
        return files, None, None
    tensor = mask if mask is not None else markup
    if len(tensor) != 1:
        raise ValueError("Connect one mask or markup frame for the first reference.")
    image = _pil_frame(tensor[0])
    if image.size != source_size:
        raise ValueError(f"The mask or markup must match the first reference ({source_size[0]}x{source_size[1]}).")
    if mask is not None:
        # ComfyUI uses white for the editable area; OpenAI uses transparent pixels.
        alpha = ImageOps.invert(image.convert("L"))
        image = Image.new("RGBA", source_size, "white")
        image.putalpha(alpha)
    elif markup_alpha is not None:
        if len(markup_alpha) != 1 or _pil_frame(markup_alpha[0]).size != source_size:
            raise ValueError("Connect one markup alpha mask matching the overlay dimensions.")
        image.putalpha(ImageOps.invert(_pil_frame(markup_alpha[0]).convert("L")))
    elif image.mode != "RGBA":
        raise ValueError("Connect an RGBA markup overlay with a transparent background.")
    if output_size and output_size != image.size:
        image = image.resize(output_size, Image.Resampling.LANCZOS)
    if markup is not None and image.width * image.height > 16_777_216:
        raise ValueError("The first reference and markup are limited to 16,777,216 pixels each.")
    if image.getchannel("A").getextrema()[0] == 255:
        raise ValueError("The mask or markup needs at least one transparent pixel in the API upload.")
    return files, "mask" if mask is not None else "markup", _png(image)


def _data_url(data):
    url = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    if len(url) > 20_971_520:
        raise ValueError("A connected image is too large to mix with API references. Resize it or use file IDs for all inputs.")
    return {"image_url": url}


def _edit_body(payload, files, overlay_name, overlay, api_refs, api_overlay):
    if api_refs or api_overlay:
        body = {**payload, "images": [_data_url(data) for data in files] + api_refs}
        if overlay_name:
            body[overlay_name] = _data_url(overlay)
        if api_overlay:
            body.update(api_overlay)
        return {"json": body}
    form = aiohttp.FormData()
    for name, value in payload.items():
        form.add_field(name, str(value).lower() if isinstance(value, bool) else str(value))
    field = "image" if len(files) == 1 else "image[]"
    for index, data in enumerate(files, 1):
        form.add_field(field, data, filename=f"reference-{index}.png", content_type="image/png")
    if overlay_name:
        form.add_field(overlay_name, overlay, filename=f"{overlay_name}.png", content_type="image/png")
    return {"data": form}


def _decode_image(item):
    try:
        return base64.b64decode(item["b64_json"], validate=True)
    except (KeyError, TypeError, binascii.Error):
        raise RuntimeError("OpenAI returned invalid image data.") from None


def _error_message(error, key, request_id="", status=None):
    if isinstance(error, dict):
        message = str(error.get("message") or "Request failed.")
    else:
        message = "Request failed."
    message = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", message.replace(key, "[redacted]"))
    prefix = f"OpenAI HTTP {status}" if status else "OpenAI image stream"
    return f"{prefix}: {message[:1200]}" + (f" (request {request_id})" if request_id else "")


async def _stream_events(content):
    # Stream lines in chunks: a single base64 event can exceed aiohttp's line limit.
    buffer = bytearray()
    data_lines = []
    async for chunk in content.iter_any():
        lines = chunk.split(b"\n")
        if len(lines) == 1:
            buffer.extend(chunk)
            continue
        buffer.extend(lines[0])
        for line in [bytes(buffer), *lines[1:-1]]:
            line = line.rstrip(b"\r")
            if line.startswith(b"data:"):
                data_lines.append(line[5:].lstrip(b" "))
            elif not line and data_lines:
                data = b"\n".join(data_lines)
                data_lines.clear()
                if data != b"[DONE]":
                    yield json.loads(data)
        buffer = bytearray(lines[-1])


async def _call_images(key, edit, body, n, streaming, timeout, preview):
    endpoint = f"{API_ROOT}/{'edits' if edit else 'generations'}"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.post(endpoint, **body, allow_redirects=False,
                                    headers={"Authorization": f"Bearer {key}"}) as response:
                request_id = response.headers.get("x-request-id", "")
                if not 200 <= response.status < 300:
                    try:
                        error = (await response.json(content_type=None)).get("error")
                    except (ValueError, AttributeError):
                        error = None
                    raise RuntimeError(_error_message(error, key, request_id, response.status))
                if not streaming:
                    result = await response.json()
                    items = result.get("data") or []
                    metadata = {name: value for name, value in result.items() if name != "data"}
                else:
                    items, metadata = [], {}
                    async for event in _stream_events(response.content):
                        kind = event.get("type", "")
                        if kind == "error" or event.get("error"):
                            raise RuntimeError(_error_message(event.get("error", event), key, request_id))
                        if kind.endswith(".partial_image"):
                            await preview(event)
                        if kind.endswith(".completed"):
                            items.append(event)
                            metadata = {name: value for name, value in event.items() if name != "b64_json"}
                    if items and all(isinstance(item.get("output_index"), int) for item in items):
                        items.sort(key=lambda item: item["output_index"])
                if len(items) != n:
                    raise RuntimeError(f"OpenAI returned {len(items)} of {n} requested images (request {request_id or 'unavailable'}).")
                return [_decode_image(item) for item in items], {**metadata, "request_id": request_id}
    except asyncio.TimeoutError:
        raise RuntimeError("The OpenAI image request timed out. Check API usage before retrying.") from None
    except aiohttp.ClientError as exc:
        raise RuntimeError(f"OpenAI Images connection failed ({type(exc).__name__}). Check API usage before retrying.") from None


def _preview_image(data):
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((512, 512))
        return image.convert("RGB")


def _results(images, output_format, expected_size, save_original):
    output_images, masks, sizes, paths = [], [], [], []
    if output_format != "svg":
        for data in images:
            frames, alpha_masks = [], []
            with Image.open(io.BytesIO(data)) as image:
                actual = f"{image.width}x{image.height}"
                if expected_size != "auto" and actual != expected_size:
                    raise RuntimeError(f"OpenAI returned {actual}; requested {expected_size}.")
                for frame in ImageSequence.Iterator(image):
                    rgba = np.asarray(frame.convert("RGBA"), dtype=np.float32) / 255.0
                    frames.append(torch.from_numpy(rgba))
                    alpha_masks.append(torch.from_numpy(1 - rgba[..., 3]))
            alpha = torch.stack(alpha_masks)
            # Keep the API's straight RGBA so native Save Image can write the
            # same cutout. Ordinary opaque output remains a ComfyUI RGB tensor.
            channels = 4 if torch.any(alpha) else 3
            output_images.append(torch.stack([frame[..., :channels] for frame in frames]))
            masks.append(alpha)
            sizes.append(actual)
    if save_original or output_format in ("gif", "svg"):
        import folder_paths

        directory = Path(folder_paths.get_output_directory()) / "zura_openai"
        directory.mkdir(parents=True, exist_ok=True)
        stem = uuid4().hex
        for index, data in enumerate(images, 1):
            path = directory / f"{stem}_{index:02d}.{output_format}"
            path.write_bytes(data)
            paths.append(str(path))
    return output_images, masks, sizes, paths


def _choice(values, tooltip):
    return values, {"default": values[0], "tooltip": tooltip}


def _int(default, low, high, tooltip):
    return "INT", {"default": default, "min": low, "max": high, "tooltip": tooltip}


def _string(tooltip, multiline=False):
    return "STRING", {"default": "", "multiline": multiline, "tooltip": tooltip}


class ZuraOpenAIImage:
    CATEGORY = "Zura/Image"
    FUNCTION = "generate"
    OUTPUT_NODE = True
    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("images", "alpha mask", "actual size", "original file", "API receipt")
    OUTPUT_IS_LIST = (True, True, True, True, False)
    DESCRIPTION = "Generate or edit images with the OpenAI Images API. Each execution uses your project’s API credits."

    @classmethod
    def INPUT_TYPES(cls):
        schema = {
            "required": {
                "prompt": _string("Describe the image or edit.", multiline=True),
                "model": _choice(MODELS, "Exact OpenAI model ID."),
                "task": _choice(["Auto", "Generate", "Edit"], "Auto edits when references are connected."),
                "size": _choice(PRESET_SIZES + ["1920x1088", "3840x2160", "Custom"], "Native OpenAI output dimensions."),
                "output_width": _int(1536, 16, 3840, "Native width with Custom output size."),
                "output_height": _int(864, 16, 3840, "Native height with Custom output size."),
                "quality": _choice(["auto", "low", "medium", "high", "xhigh", "max"], "Rendering quality, independent of complexity."),
            },
            "optional": {
                "reference": ("IMAGE", {"tooltip": "First image or image batch. Masks and markup apply to its first frame."}),
                "reference_2": ("IMAGE", {"tooltip": "Additional reference or image batch. Up to 16 total frames."}),
                "edit_mask": ("MASK", {"tooltip": "White marks the area to edit. Match the dimensions of the first reference."}),
                "markup_overlay": ("IMAGE", {"tooltip": "RGBA annotation overlay. Use the API markup reference for a PNG file ID or URL."}),
                "markup_alpha": ("MASK", {"tooltip": "Optional transparency for the markup overlay. Connect the MASK output from Load Image."}),
                "custom_model": _string("Model ID saved by earlier versions of this node."),
                "input_width": _int(0, 0, 16384, "Upload width. Set both input dimensions to 0 to preserve original pixels."),
                "input_height": _int(0, 0, 16384, "Upload height. Explicit dimensions stretch the reference and its overlay together."),
                "input_fidelity": _choice(["default", "low", "high"], "Legacy edit control. New models manage input fidelity."),
                "background": _choice(["auto", "opaque", "transparent"], "Transparent requires PNG or WebP."),
                "output_format": _choice(OUTPUT_FORMATS, "Encoding of the original API output."),
                "output_compression": _int(-1, -1, 100, "JPEG/WebP compression. -1 uses the API default."),
                "n": _int(1, 1, 10, "Number of images or animations in one request."),
                "complexity": _choice(["default", "low", "medium", "high"], "Planning effort on GPT-Image-2.6."),
                "moderation": _choice(["auto", "low"], "OpenAI moderation setting."),
                "stream": ("BOOLEAN", {"default": False, "tooltip": "Stream progress through ComfyUI’s live preview."}),
                "partial_images": _int(0, 0, 3, "Number of streamed previews. Additional previews use image output tokens."),
                "frame_count": _int(9, 2, 16, "Frames per GIF animation."),
                "frame_duration_ms": _int(200, 20, 2000, "Requested delay per GIF frame."),
                "svg_model": _string("Optional SVG author model ID, where enabled for your project."),
                "svg_reasoning": _choice(["default", "none", "minimal", "low", "medium", "high", "xhigh", "max"], "SVG author reasoning effort."),
                "api_references": _string("One HTTPS URL, data URL or OpenAI file ID per line. Appended after connected images.", multiline=True),
                "api_mask": _string("HTTPS URL, data URL or OpenAI file ID for a transparent PNG mask."),
                "api_markup": _string("HTTPS URL, data URL or OpenAI file ID for a transparent PNG markup overlay."),
                "safety_identifier": _string("Optional stable, non-identifying end-user ID, up to 128 characters."),
                "legacy_user": _string("Deprecated API user identifier. Use safety_identifier for new workflows."),
                "save_original": ("BOOLEAN", {"default": True, "tooltip": "Save the exact encoded output in ComfyUI/output/zura_openai. Always enabled for GIF and SVG."}),
                "timeout_seconds": _int(600, 30, 1800, "Maximum time to wait for the API response."),
            },
        }
        artist_controls = {
            "prompt": "Prompt", "model": "Model", "size": "Output size",
            "output_width": "Width", "output_height": "Height", "quality": "Quality",
            "background": "Background",
        }
        sockets = {
            "reference": "Reference 1", "reference_2": "Reference 2", "edit_mask": "Edit mask",
            "markup_overlay": "Markup overlay", "markup_alpha": "Markup alpha",
        }
        advanced_labels = {"n": "Image count", "api_references": "API references",
                           "api_mask": "API mask", "api_markup": "API markup",
                           "svg_model": "SVG author model", "svg_reasoning": "SVG reasoning"}
        for inputs in schema.values():
            for name, (_, options) in inputs.items():
                options["display_name"] = (
                    artist_controls.get(name) or sockets.get(name) or advanced_labels.get(name)
                    or name.replace("_", " ").capitalize()
                )
                if name not in artist_controls and name not in sockets:
                    options["advanced"] = True
        schema["optional"]["custom_model"][1]["hidden"] = True
        for index in range(3, 17):
            schema["optional"][f"reference_{index}"] = ("IMAGE", {"display_name": f"Reference {index}"})
        return schema

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    @classmethod
    def VALIDATE_INPUTS(cls, model=None):
        # ComfyUI's static combo list cannot see models discovered after key setup.
        if model is None or model == "Custom ID" or isinstance(model, str) and MODEL_ID.fullmatch(model):
            return True
        return "Choose a valid OpenAI image model."

    async def generate(self, prompt, model, task, size, output_width, output_height, quality,
                       reference=None, reference_2=None, edit_mask=None, markup_overlay=None, markup_alpha=None,
                       custom_model="", input_width=0, input_height=0, input_fidelity="default",
                       background="auto", output_format="png", output_compression=-1, n=1,
                       complexity="default", moderation="auto", stream=False, partial_images=0,
                       frame_count=9, frame_duration_ms=200, svg_model="", svg_reasoning="default",
                       api_references="", api_mask="", api_markup="", safety_identifier="", legacy_user="",
                       save_original=True, timeout_seconds=600, **extra_references):
        from comfy.model_management import throw_exception_if_processing_interrupted
        from comfy.utils import ProgressBar

        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 32000:
            raise ValueError("Enter an image prompt of 1 to 32,000 characters.")
        if model == "Custom ID":
            model = custom_model.strip()
        if not MODEL_ID.fullmatch(model):
            raise ValueError("Choose a valid OpenAI image model.")
        if size == "Custom":
            size = f"{output_width}x{output_height}"
        _validate_size(size, model, output_format == "gif")

        references = [
            images for images in (reference, reference_2, *(extra_references.get(f"reference_{i}") for i in range(3, 17)))
            if images is not None
        ]
        api_refs = [_image_reference(line.strip()) for line in api_references.splitlines() if line.strip()]
        count = sum(len(images) for images in references) + len(api_refs)
        edit = task == "Edit" or (task == "Auto" and count > 0)
        if count > 16 or (edit and not count):
            raise ValueError("An edit needs 1–16 images. Connect a reference or add an API reference.")
        if not edit and count:
            raise ValueError("Choose Auto or Edit to use references.")
        api_overlay = {name: _image_reference(value.strip())
                       for name, value in (("mask", api_mask), ("markup", api_markup)) if value.strip()}
        overlays = len(api_overlay) + (edit_mask is not None) + (markup_overlay is not None)
        if overlays > 1 or (overlays and not edit):
            raise ValueError("Use one mask or one markup overlay with an edit.")
        if (edit_mask is not None or markup_overlay is not None) and not references:
            raise ValueError("A connected mask or markup needs a connected first reference.")
        if markup_alpha is not None and markup_overlay is None:
            raise ValueError("Connect the markup image alongside its alpha mask.")
        if bool(input_width) != bool(input_height) or (input_width and not references):
            raise ValueError("Set both input dimensions to 0 or connect a reference and enter both dimensions.")
        if input_width and api_overlay:
            raise ValueError("Resize a remote mask or markup separately to match the resized first reference.")
        if background == "transparent" and output_format not in ("png", "webp"):
            raise ValueError("Select PNG or WebP for a transparent background.")
        if output_format == "svg" and (edit or n != 1):
            raise ValueError("SVG requires text-to-image generation and a single output.")
        if output_format == "gif" and (edit_mask is not None or "mask" in api_overlay):
            raise ValueError("GIF output does not support edit masks.")
        stream = stream and output_format not in ("svg", "gif")
        partial_images = partial_images if stream else 0
        if edit and input_fidelity != "default" and model in MODELS and (
                model not in (*LEGACY_15, "gpt-image-1-mini") or
                model == "gpt-image-1-mini" and input_fidelity == "high"):
            raise ValueError("Input fidelity is adjustable on GPT-Image-1.5 edits, and low is available on GPT-Image-1-mini.")
        if complexity != "default" and model in MODELS and not model.startswith("gpt-image-2.6-"):
            raise ValueError("Select GPT-Image-2.6 for complexity control, or use its default setting.")
        if quality in ("xhigh", "max") and model in MODELS and not model.startswith(("gpt-image-2.5-", "gpt-image-2.6-")):
            raise ValueError("Select GPT-Image-2.5 or 2.6 for xhigh or max quality.")
        if len(safety_identifier.strip()) > 128:
            raise ValueError("The safety identifier must be 128 characters or fewer.")
        svg_model = svg_model.strip()
        if svg_reasoning != "default" and not svg_model and output_format == "svg":
            raise ValueError("Enter the SVG author model ID to set SVG reasoning.")

        key = _api_key()
        if not key:
            raise RuntimeError("Use OpenAI API key on the node or set OPENAI_API_KEY for ComfyUI.")
        payload = dict(model=model, prompt=prompt, size=size, quality=quality, n=n,
                       background=background, output_format=output_format, moderation=moderation)
        if stream:
            payload.update(stream=True, partial_images=partial_images)
        if output_format in ("jpeg", "webp") and output_compression != -1:
            payload["output_compression"] = output_compression
        if complexity != "default":
            payload["complexity"] = complexity
        if edit and input_fidelity != "default":
            payload["input_fidelity"] = input_fidelity
        if safety_identifier.strip():
            payload["safety_identifier"] = safety_identifier.strip()
        if legacy_user.strip():
            payload["user"] = legacy_user.strip()
        if output_format == "gif":
            payload.update(frame_count=frame_count, frame_duration_ms=frame_duration_ms)
        if output_format == "svg" and svg_model:
            payload["svg"] = {"model": svg_model}
            if svg_reasoning != "default":
                payload["svg"]["reasoning"] = {"effort": svg_reasoning}
        body = {"json": payload}
        if edit:
            encoded = await asyncio.to_thread(_encode_inputs, references, edit_mask, markup_overlay,
                                              markup_alpha, input_width, input_height) if references else ([], None, None)
            body = _edit_body(payload, *encoded, api_refs, api_overlay)

        total = max(1, partial_images * n + 1)
        progress = ProgressBar(total)
        previews = 0

        async def preview(event):
            nonlocal previews
            image = await asyncio.to_thread(_preview_image, _decode_image(event))
            previews += 1
            progress.update_absolute(min(previews, total - 1), total, ("JPEG", image, 512))

        throw_exception_if_processing_interrupted()
        request = asyncio.create_task(_call_images(key, edit, body, n, stream, timeout_seconds, preview))
        try:
            while not request.done():
                await asyncio.wait((request,), timeout=0.5)
                throw_exception_if_processing_interrupted()
            images, metadata = request.result()
        finally:
            if not request.done():
                request.cancel()
            await asyncio.gather(request, return_exceptions=True)

        outputs = await asyncio.to_thread(_results, images, output_format, size, save_original)
        progress.update_absolute(total)
        receipt = json.dumps({**metadata, "model": model, "task": "edit" if edit else "generate",
                              "requested_size": size, "actual_sizes": outputs[2], "files": outputs[3]},
                             ensure_ascii=False)
        ui = {"text": [receipt]}
        if outputs[3] and output_format != "svg":
            ui["images"] = [{"filename": Path(path).name, "subfolder": "zura_openai", "type": "output"}
                            for path in outputs[3]]
        return {"ui": ui, "result": (*outputs, receipt)}


NODE_CLASS_MAPPINGS = {"ZuraOpenAIImage": ZuraOpenAIImage}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraOpenAIImage": "Zura · ChatGPT Image (API Key)"}
