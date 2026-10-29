"""Allowlisted, user-initiated downloads for Studio model packages.

URLs, sizes and SHA-256 are pinned to publisher revisions. Callers choose a
catalogue ID, never a URL or destination; no downloads start during discovery.
"""
from __future__ import annotations

import hashlib
import errno
import os
from pathlib import Path
import shutil
import threading
import uuid

FLUX2 = "black-forest-labs/FLUX.2-klein-9b-fp8"
FLUX3 = "black-forest-labs/flux-3-image-klein-comfy"
SHARED = "Comfy-Org/flux2-klein-9B"

def _file(folder, name, repo, revision, path, size, sha):
    return dict(folder=folder, filename=name, repo=repo, revision=revision,
                remote_path=path, size_bytes=size, sha256=sha)

CATALOG = {
    "openjutsu_h3": dict(name="OpenJutsu · H3 character replacement", gated=False,
        license_url="https://huggingface.co/Comfy-Org/MiniMax-H3",
        note="Requires the separate h3_character_swap node pack. Review the licences for all component repositories before downloading.",
        files=[
            _file("diffusion_models", "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "Comfy-Org/MiniMax-H3", "1c41cfca8ebba91d0af792a05c5761fb2c3a7975", "diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors", 20970379616, "9255f52b6677845ad238f20dfaafa94727053694127ab7f255c048f0f9365779"),
            _file("text_encoders", "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "Comfy-Org/MiniMax-H3", "1c41cfca8ebba91d0af792a05c5761fb2c3a7975", "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", 15687142551, "35a88d51044231fe332301d7a62aa81e3f2cba62febeb446e2c1e3e0ef76f2c6"),
            _file("vae", "minimax_h3_video_vae_fp16.safetensors", "Comfy-Org/MiniMax-H3", "1c41cfca8ebba91d0af792a05c5761fb2c3a7975", "vae/minimax_h3_video_vae_fp16.safetensors", 5207808496, "7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522"),
            _file("vae", "minimax_h3_audio_vae_fp32.safetensors", "Comfy-Org/MiniMax-H3", "1c41cfca8ebba91d0af792a05c5761fb2c3a7975", "vae/minimax_h3_audio_vae_fp32.safetensors", 605254808, "8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48"),
            _file("checkpoints", "sam3.1_multiplex_fp16.safetensors", "Comfy-Org/sam3.1", "7bb8374780a725b4353ed31f3a9395c9742b5621", "checkpoints/sam3.1_multiplex_fp16.safetensors", 1745546848, "9ba99c92703c2e8b4f47de2d34a539bb8e18923049e238b780d70dbe6368eb03"),
            _file("loras", "h3_character_swap_v1.5.safetensors", "akatz-ai/MiniMax-H3-Character-Swap-LoRA", "d06323b7c8e70e97cdab48b78a1e05f786c8cba9", "h3_character_swap_v1.5.safetensors", 155110792, "8f2c3c3eba161df8d0c6099598b4730f641f5ce01e04cd16d2427cff8a35218f"),
            _file("loras", "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors", "lightx2v/Minimax-h3-Turbo", "3ec17a324ced54151364f24f8b5fb6bf7e26414f", "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors", 1956193000, "08cfe946033af7d27719b964b6e0a0e50c32138daabbd6ce4137e23df6bf9980"),
        ]),
    "wan_animate_2": dict(name="Wan Animate 2 · distilled", gated=False,
        license_url="https://huggingface.co/Comfy-Org/Wan-Animate-2",
        note="This installs the model, text encoder, vision encoder and VAE. Pose preprocessing nodes are installed separately.",
        files=[
            _file("diffusion_models", "wan_animate_2_distill_int8_convrot.safetensors", "Comfy-Org/Wan-Animate-2", "e7181fe1896b7f2ce34120d1a3663413548240d7", "diffusion_models/wan_animate_2_distill_int8_convrot.safetensors", 16653175528, "d2e566ecac3f164cb1a6b63dc7d868d6678c9affa49fbceb3abe4f9458f89c8a"),
            _file("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "Comfy-Org/Wan-Animate-2", "e7181fe1896b7f2ce34120d1a3663413548240d7", "text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", 6735906897, "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68"),
            _file("clip_vision", "clip_vision_h.safetensors", "Comfy-Org/Wan-Animate-2", "e7181fe1896b7f2ce34120d1a3663413548240d7", "clip_vision/clip_vision_h.safetensors", 1264219396, "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161"),
            _file("vae", "Wan2_1_VAE_bf16.safetensors", "Comfy-Org/Wan-Animate-2", "e7181fe1896b7f2ce34120d1a3663413548240d7", "vae/Wan2_1_VAE_bf16.safetensors", 253806278, "1ab9a32cc2c740f6e39d80d367ce5dcc28db8c71b79b28670546b8973e9d75f9"),
        ]),
    "ltx25_core": dict(name="LTX 2.5 · core files", gated=True,
        license_url="https://huggingface.co/Lightricks/LTX-2.5",
        note="Core model, VAEs and upscaler only. Your chosen workflow may also require its specific text encoder, LoRAs and custom nodes; check the workflow's setup list.",
        files=[
            _file("diffusion_models", "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", "Lightricks/LTX-2.5", "49b093a39c19169a8a81721dcc541e07e945232f", "diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", 21504034224, "c4279eeff115cbeaca494bd2183e7d768c38fe85a184dc6afbb7159157c44334"),
            _file("vae", "ltx-2.5-video-vae-conv-bf16.safetensors", "Lightricks/LTX-2.5", "49b093a39c19169a8a81721dcc541e07e945232f", "vae/ltx-2.5-video-vae-conv-bf16.safetensors", 1452269922, "685b06ee3d9b2039647698fc4ea33175112462fc374e2777312c907897dfce8d"),
            _file("vae", "ltx-2.5-audio-vae-bf16.safetensors", "Lightricks/LTX-2.5", "49b093a39c19169a8a81721dcc541e07e945232f", "vae/ltx-2.5-audio-vae-bf16.safetensors", 364866540, "c52733d37f6a7fb7949c3dc0fb468c6cb2169e4d836983a73babb9f0d54837a5"),
            _file("latent_upscale_models", "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors", "Lightricks/LTX-2.5", "49b093a39c19169a8a81721dcc541e07e945232f", "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors", 995778752, "eb5a71fe4068ee87ccdb1c3aa635e547ca76bd2d30ae20ae889f2c325c0677e8"),
        ]),
    "flux2_klein_9b": dict(name="FLUX.2 Klein 9B", gated=True,
        license_url="https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8",
        files=[
            _file("diffusion_models", "flux-2-klein-9b-fp8.safetensors", FLUX2, "902d9d510b51533e07729f19211414a3648b77d2", "flux-2-klein-9b-fp8.safetensors", 9433061528, "865ba09f5b4c3cbd3468a4bd3acb9fcb2f8740c54317482f0bcd4ed1d3655cee"),
            _file("text_encoders", "qwen_3_8b_fp4mixed.safetensors", SHARED, "1138ce884c8e977cdacacbe779784fec4426bb3f", "split_files/text_encoders/qwen_3_8b_fp4mixed.safetensors", 6802593327, "bbf16f981d98e16d080c566134814c4e9f6aadd0d0e1383c60bc44ba939d760d"),
            _file("vae", "flux2-vae.safetensors", SHARED, "1138ce884c8e977cdacacbe779784fec4426bb3f", "split_files/vae/flux2-vae.safetensors", 336211292, "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3"),
        ]),
    "flux3_klein": dict(name="FLUX.3 Image Klein", gated=True,
        license_url="https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy",
        files=[
            _file("diffusion_models", "flux3-image-klein-int8-convrot.safetensors", FLUX3, "feef60b0aaf63a4773ace96636ebbcf43b881312", "diffusion_models/flux3-image-klein-int8-convrot.safetensors", 5827874779, "847d8933548afd93df4af2cac2498e70891bf28d9dae06d695f536992e168fe2"),
            _file("text_encoders", "qwen3vl_4b_int8_convrot.safetensors", FLUX3, "feef60b0aaf63a4773ace96636ebbcf43b881312", "text_encoders/qwen3vl_4b_int8_convrot.safetensors", 4858559240, "32de113cbf8282b02cbff0794b637b9d6676da09314a1db5a30bcea9bf4ee01c"),
            _file("vae", "flux2-vae.safetensors", SHARED, "1138ce884c8e977cdacacbe779784fec4426bb3f", "split_files/vae/flux2-vae.safetensors", 336211292, "868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3"),
        ]),
}

CATALOG.update({
    "flux2_klein_start": dict(name="FLUX.2 Klein 9B · video starting frame", gated=True,
        license_url="https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8",
        note="Starting-frame workflow files; its text encoder and VAE differ from the image workspace. Review each source's terms.",
        files=[
            CATALOG["flux2_klein_9b"]["files"][0],
            _file("text_encoders", "qwen_3_8b_fp8mixed.safetensors", SHARED, "1138ce884c8e977cdacacbe779784fec4426bb3f", "split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors", 8664848742, "abad16806e0cbabc54e0325d6565847443fe396d5f0be38bb3cd3fe75a1201d6"),
            _file("vae", "full_encoder_small_decoder.safetensors", "black-forest-labs/FLUX.2-small-decoder", "a3efc24f613ef42d9428af62fdbd6f5fd8856c4a", "full_encoder_small_decoder.safetensors", 249519092, "ea4273f02d1fafbf8e1d1c2cf6018ed8748652eb0bf34f2dd91171f16f15ab62"),
        ]),
    "ltx25_full_vae": dict(name="LTX 2.5 · full video VAE", gated=True,
        license_url="https://huggingface.co/Lightricks/LTX-2.5",
        note="Full video VAE used by the native HDR workflow. The LTX 2.5 core model and workflow-specific files are also required.",
        files=[_file("vae", "ltx-2.5-video-vae-bf16.safetensors", "Lightricks/LTX-2.5", "49b093a39c19169a8a81721dcc541e07e945232f", "vae/ltx-2.5-video-vae-bf16.safetensors", 1472223346, "847e14ca7f3355debca0cea4eaa24ac0fbcdf0061da054ac89ca638a869ddba3")]),
    "ltx25_refine": dict(name="LTX 2.5 · HDR detail adapter", gated=True,
        license_url="https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details",
        note="Native HDR detail adapter. Also install the full VAE and the other files required by the HDR workflow.",
        files=[_file("loras", "ltx-2.5-22b-ic-lora-refine-details-1.0.safetensors", "Lightricks/LTX-2.5-22b-IC-LoRA-Refine-Details", "4912c478b35dd96b6cdcc5f7c7ff9d72c2c57929", "ltx-2.5-22b-ic-lora-refine-details-1.0.safetensors", 1308787534, "771a84f70e143af89867fc714ebbf7bd6edcaa4974c0360cba4a2d292a99f0e6")]),
    "ltx25_sdr_hdr": dict(name="LTX 2.5 · SDR to HDR adapter", gated=True,
        license_url="https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR",
        note="SDR-to-HDR adapter and its conditioning. LTX 2.5 core and other workflow dependencies are separate.",
        files=[
            _file("loras", "ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors", "Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR", "c7578ebddb54f4210e534e4d8cad698a5a520692", "ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors", 1308787472, "0b39eac09672c18d0d10f401d5e71a68a73225f1169df826b092b7e5ef489675"),
            _file("embeddings", "ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors", "Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR", "c7578ebddb54f4210e534e4d8cad698a5a520692", "ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors", 12614165, "63c03987a1984f6d4b3d3440c15deee66b0310c01950496329f983f5dc8c88bd"),
        ]),
})

def inspect(model_id, locations):
    """Return required files and exact remaining bytes, including shared files."""
    if model_id not in CATALOG:
        raise ValueError("This model has no verified download recipe yet.")
    recipe = CATALOG[model_id]
    files = []
    for item in recipe['files']:
        roots = locations.get(item['folder'], [])
        if not roots:
            raise ValueError("ComfyUI has no configured model folder for " + item['folder'])
        existing = next((Path(root) / item['filename'] for root in roots
                         if (Path(root) / item['filename']).is_file()), None)
        incomplete = bool(existing and existing.stat().st_size != item['size_bytes'])
        files.append({**item, 'installed': bool(existing) and not incomplete, 'incomplete': incomplete,
                      'destination': str(existing or (Path(roots[0]) / item['filename']))})
    return dict(id=model_id, name=recipe['name'], gated=recipe['gated'], note=recipe.get('note', ''),
                license_url=recipe['license_url'], files=files,
                remaining_bytes=sum(f['size_bytes'] for f in files if not f['installed']))


def _rename_noreplace(source, destination):
    """Atomically publish without replacing an existing file on Windows or Linux.

    Windows' os.rename refuses an existing destination. Linux renameat2 with
    RENAME_NOREPLACE provides the same guarantee, including on filesystems
    which do not implement hard links. Other POSIX platforms must use hard links
    until they offer an equivalent verified atomic operation.
    """
    if os.name == 'nt':
        os.rename(source, destination)
        return
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise OSError(errno.ENOTSUP, 'Atomic no-overwrite rename is unavailable')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def _publish_verified(source, destination):
    """Publish only a completed file; never expose a partial or overwrite."""
    try:
        os.link(source, destination)
    except FileExistsError:
        raise
    except OSError:
        _rename_noreplace(source, destination)


def _check_publish_supported(directory, job_id):
    """Test the exact target filesystem before a potentially multi-GB download."""
    source = directory / ('.zura-' + job_id + '.probe')
    destination = directory / ('.zura-' + job_id + '.probe-installed')
    try:
        with source.open('xb'):
            pass
        _publish_verified(source, destination)
    except OSError as exc:
        raise RuntimeError('This model folder does not support safe, atomic installation. Choose another ComfyUI model folder.') from exc
    finally:
        source.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)

class DownloadManager:
    """One explicit job at a time; streamed, cancellable and verified on disk."""
    def __init__(self, locations):
        self.locations = locations
        self._lock = threading.Lock()
        self._jobs = {}
        self._active = None

    def status(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ValueError('Unknown model download.')
            return {key: value for key, value in job.items() if key != 'cancel'}

    def cancel(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ValueError('Unknown model download.')
            job['cancel'].set()

    def start(self, model_id):
        recipe = inspect(model_id, self.locations)
        incomplete = next((item for item in recipe['files'] if item['incomplete']), None)
        if incomplete:
            raise ValueError('An existing model file has the wrong size: ' + incomplete['filename'] + '. Check or move it before downloading; it will not be overwritten.')
        with self._lock:
            if self._active is not None:
                raise ValueError('Another model download is already running.')
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = dict(id=job_id, model_id=model_id, phase='queued',
                done_bytes=0, total_bytes=recipe['remaining_bytes'], current_file='',
                error='', cancel=threading.Event())
            self._active = job_id
        threading.Thread(target=self._run, args=(job_id, recipe), daemon=True).start()
        return job_id

    def _run(self, job_id, recipe):
        import requests
        try:
            try:
                from huggingface_hub import get_token
                token = get_token()
            except (ImportError, OSError):
                token = None
            for item in recipe['files']:
                if item['installed']:
                    continue
                with self._lock:
                    job = self._jobs[job_id]
                    if job['cancel'].is_set():
                        job['phase'] = 'cancelled'
                        return
                    job.update(phase='downloading', current_file=item['filename'])
                destination = Path(item['destination'])
                destination.parent.mkdir(parents=True, exist_ok=True)
                _check_publish_supported(destination.parent, job_id)
                if shutil.disk_usage(destination.parent).free < item['size_bytes']:
                    raise RuntimeError('Not enough free disk space for ' + item['filename'])
                temporary = destination.parent / ('.zura-' + job_id + '.part')
                url = 'https://huggingface.co/' + item['repo'] + '/resolve/' + item['revision'] + '/' + item['remote_path']
                try:
                    digest = hashlib.sha256()
                    count = 0
                    headers = {'Authorization': 'Bearer ' + token} if token else {}
                    with requests.get(url, headers=headers, stream=True, timeout=(15, 60)) as response:
                        if response.status_code in (401, 403):
                            raise RuntimeError('Access denied. Sign in to Hugging Face and accept the model licence, then retry.')
                        response.raise_for_status()
                        with temporary.open('xb') as output:
                            for chunk in response.iter_content(chunk_size=1024*1024):
                                if self._jobs[job_id]['cancel'].is_set():
                                    with self._lock:
                                        self._jobs[job_id]['phase'] = 'cancelled'
                                    return
                                if not chunk:
                                    continue
                                count += len(chunk)
                                if count > item['size_bytes']:
                                    raise RuntimeError('Download size did not match the expected model file.')
                                output.write(chunk)
                                digest.update(chunk)
                                with self._lock:
                                    self._jobs[job_id]['done_bytes'] += len(chunk)
                    if count != item['size_bytes'] or digest.hexdigest() != item['sha256']:
                        raise RuntimeError('Download failed its size or integrity check.')
                    # Hard link or exclusive rename publishes a verified file
                    # atomically and refuses to replace a concurrent install.
                    _publish_verified(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
            with self._lock:
                self._jobs[job_id].update(phase='done', current_file='')
        except Exception as exc:
            with self._lock:
                # Avoid exposing request URLs, tokens or machine paths to the UI.
                message = str(exc) if isinstance(exc, RuntimeError) else 'Download failed. Check the connection and try again.'
                self._jobs[job_id].update(phase='failed', error=message)
        finally:
            with self._lock:
                self._active = None


def register(routes, response):
    """Register same-origin Studio endpoints; no network call until POST start."""
    import folder_paths
    from aiohttp import web
    folders = {item['folder'] for model in CATALOG.values() for item in model['files']}
    manager = DownloadManager({folder: folder_paths.get_folder_paths(folder) for folder in folders})

    @routes.get('/zura/studio/model-downloads')
    @routes.get('/genj/studio/model-downloads')
    @response
    async def catalogue(request):
        models = []
        for name, recipe in CATALOG.items():
            try:
                models.append(inspect(name, manager.locations))
            except ValueError as exc:
                models.append({'id': name, 'name': recipe['name'], 'error': str(exc), 'files': []})
        return web.json_response({'models': models})

    @routes.post('/zura/studio/model-downloads')
    @routes.post('/genj/studio/model-downloads')
    @response
    async def start(request):
        data = await request.json()
        return web.json_response({'id': manager.start(data.get('model_id'))})

    @routes.get('/zura/studio/model-downloads/{identity}')
    @routes.get('/genj/studio/model-downloads/{identity}')
    @response
    async def status(request):
        return web.json_response(manager.status(request.match_info['identity']))

    @routes.post('/zura/studio/model-downloads/{identity}/cancel')
    @routes.post('/genj/studio/model-downloads/{identity}/cancel')
    @response
    async def cancel(request):
        manager.cancel(request.match_info['identity'])
        return web.json_response({'ok': True})
