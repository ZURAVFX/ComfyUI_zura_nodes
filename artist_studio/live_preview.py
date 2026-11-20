"""Keep Studio's still and motion previews independent of graph settings."""

import base64
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from io import BytesIO
import logging
from threading import BoundedSemaphore
from time import monotonic


MAX_FRAMES = 8
MAX_LATENT_EDGE = 64
PREVIEW_INTERVAL = 8.0


def preview_method(config, stage, filenames=None):
    if filenames is None:
        try:
            import folder_paths
            filenames = folder_paths.get_filename_list("vae_approx")
        except (ImportError, AttributeError, KeyError):
            filenames = []
    files = {str(name).replace("\\", "/").rsplit("/", 1)[-1].lower() for name in filenames}
    # Wan 14B uses the 2.1 VAE. The 2.2 tiny decoder is for the 5B VAE.
    decoder = ("taeh3.safetensors" if stage == "h3" else
               "lighttaew2_1.safetensors" if stage in ("wan", "wan2", "wan21_relight") else None)
    return "taesd" if decoder and decoder in files else "auto"


def _video_snapshot(x0, channels):
    import torch

    if x0.is_nested:
        x0 = x0.tensors[0]
    if x0.ndim != 5 or x0.shape[1] != channels or x0.shape[2] < 3:
        return None
    _, _, frames, height, width = x0.shape
    count = min(frames, MAX_FRAMES)
    indices = torch.tensor([round(i * (frames - 1) / (count - 1)) for i in range(count)], device=x0.device)
    stride = (max(height, width) + MAX_LATENT_EDGE - 1) // MAX_LATENT_EDGE
    sample = x0.detach()[0, :, :, ::stride, ::stride].index_select(1, indices)
    # Keep a small independent CPU snapshot. The worker never holds a GPU tensor.
    return sample.to(device="cpu"), frames


def _encode_motion(sample, factors, bias, duration_ms):
    import numpy as np
    from PIL import Image

    latents = sample.float().numpy()
    rgb = np.einsum("cthw,cr->thwr", latents, np.asarray(factors, dtype=np.float32))
    if bias is not None:
        rgb += np.asarray(bias, dtype=np.float32)
    pixels = (np.clip((rgb + 1) * 0.5, 0, 1) * 255).astype(np.uint8)
    # Keep interpolation and compression off the sampler thread.
    height, width = pixels.shape[1:3]
    size = tuple(max(1, round(edge * 192 / max(height, width))) for edge in (width, height))
    images = [Image.fromarray(frame).resize(size, Image.Resampling.BILINEAR) for frame in pixels]
    with BytesIO() as output:
        images[0].save(output, "WEBP", save_all=True, append_images=images[1:],
                       duration=duration_ms, loop=0, quality=62, method=0)
        return base64.b64encode(output.getvalue()).decode("ascii")


def register_motion_preview(server):
    read_queue = getattr(getattr(server, "prompt_queue", None), "get_current_queue_volatile", None)
    if read_queue is None:
        return
    try:
        import latent_preview
        from comfy_execution.utils import get_executing_context
    except ImportError:
        return

    original = latent_preview.prepare_callback
    if getattr(original, "_zura_motion_preview", False):
        return
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="zura-motion-preview")
    available = BoundedSemaphore(1)
    last_prompt = None
    last_preview = float("-inf")

    def finish(sample, factors, bias, duration_ms, context, client_id, step, total_steps):
        try:
            webp = _encode_motion(sample, factors, bias, duration_ms)
            server.send_sync("zura_motion_preview", {
                "prompt_id": context.prompt_id, "node_id": context.node_id,
                "step": step, "total_steps": total_steps, "webp": webp,
            }, client_id)
        except Exception:
            logging.debug("Zura motion preview encoding failed", exc_info=True)
        finally:
            available.release()

    @wraps(original)
    def prepare_callback(model, steps, *args, **kwargs):
        callback = original(model, steps, *args, **kwargs)
        context = get_executing_context()
        if context is None or steps < 2:
            return callback
        running, _ = read_queue()
        data = next((item[3] for item in running if item[1] == context.prompt_id), {})
        client_id = data.get("client_id")
        studio = data.get("comfy_usage_source") == "zura-studio" or any(
            data.get(key) for key in ("zura_first_last", "zura_reference_video", "zura_paintout")
        )
        if not client_id or not studio or data.get("preview_method") == "none":
            return callback
        latent_format = model.model.latent_format
        factors = getattr(latent_format, "latent_rgb_factors", None)
        if getattr(latent_format, "latent_dimensions", None) != 3 or factors is None or getattr(latent_format, "latent_rgb_factors_reshape", None):
            return callback
        bias = getattr(latent_format, "latent_rgb_factors_bias", None)

        def with_motion(step, x0, x, total_steps):
            nonlocal last_prompt, last_preview
            callback(step, x0, x, total_steps)
            now = monotonic()
            if context.prompt_id != last_prompt:
                last_prompt = context.prompt_id
                last_preview = float("-inf")
            if step + 1 >= total_steps or now - last_preview < PREVIEW_INTERVAL or not available.acquire(False):
                return
            try:
                snapshot = _video_snapshot(x0, len(factors))
                if snapshot is not None:
                    sample, frames = snapshot
                    ratio = getattr(latent_format, "temporal_downscale_ratio", 4)
                    duration_ms = min(700, max(100, round(
                        (1 + (frames - 1) * ratio) * 1000 / (24 * sample.shape[1]))))
                    worker.submit(finish, sample, factors, bias, duration_ms, context, client_id, step + 1, total_steps)
                    last_preview = now
                    return
            except Exception:
                logging.debug("Zura motion preview capture failed", exc_info=True)
            available.release()

        return with_motion

    prepare_callback._zura_motion_preview = True
    latent_preview.prepare_callback = prepare_callback
