"""Optional local Studio speech creation; scripts and samples stay on this PC."""
import hashlib
import math
import re
import time
import uuid
from pathlib import Path

import torch


def voice_graph(body, store, identity):
    from .studio import check_asset
    mode = body.get("mode", "Clone a voice")
    if mode not in ("Clone a voice", "Text to speech"):
        raise ValueError("Choose voice cloning or text to speech.")
    script = str(body.get("script", "")).strip()
    transcript = str(body.get("reference_transcript", "")).strip()
    if not script or len(script) > 20000:
        raise ValueError("Enter the words you want your character to say (up to 20,000 characters).")
    pace, seed = float(body.get("pace", 1)), int(body.get("seed", 42))
    if not math.isfinite(pace) or not .5 <= pace <= 2 or not 0 <= seed <= 4294967295:
        raise ValueError("Choose a valid voice pace and seed.")
    inputs = dict(mode=mode, script=script, reference_transcript=transcript if mode == "Clone a voice" else "",
                  pace=pace, seed=seed, project="Zura_Studio")
    graph = {"voice": {"class_type": "ZuraLongCatVoice", "inputs": inputs},
             "audio": {"class_type": "ZuraStudioSaveVoice", "inputs": {"audio": ["voice", 0], "asset_id": identity}}}
    if mode == "Clone a voice":
        if not transcript:
            raise ValueError("Enter the exact words spoken in your voice sample.")
        sample = store.load(body.get("reference_id", ""))
        if sample.get("asset_kind") != "audio":
            raise ValueError("Choose a voice sample with audio.")
        check_asset(sample)
        graph["sample"] = {"class_type": "LoadAudio", "inputs": {"audio": sample["file"]}}
        inputs["reference_audio"] = ["sample", 0]
    return graph


class ZuraStudioSaveVoice:
    CATEGORY = "Zura/Audio"
    FUNCTION = "save"
    OUTPUT_NODE = True
    RETURN_TYPES = ("AUDIO",)
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"audio": ("AUDIO",), "asset_id": ("STRING", {"default": ""})}}
    def save(self, audio, asset_id):
        import folder_paths
        import soundfile as sf
        from .studio import Store
        if not re.fullmatch(r"[a-f0-9]{32}", asset_id):
            raise ValueError("Create this voice track from Zura Studio.")
        wave = audio["waveform"].detach().cpu().float()
        if wave.ndim != 3 or wave.shape[0] != 1 or not wave.shape[-1] or not torch.isfinite(wave).all():
            raise ValueError("The speech model returned invalid audio.")
        rate = int(audio["sample_rate"])
        if rate <= 0:
            raise ValueError("The speech model returned an invalid sample rate.")
        relative = Path("genj_studio") / asset_id / "speech.wav"
        path = Path(folder_paths.get_input_directory()) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, wave[0].T.numpy(), rate, subtype="PCM_24")
        asset = {"id": asset_id, "kind": "asset", "asset_kind": "audio", "file": relative.as_posix(),
                 "sha": hashlib.sha256(path.read_bytes()).hexdigest(), "name": "Generated speech.wav",
                 "duration": wave.shape[-1] / rate}
        Store().save(asset)
        return {"ui": {"text": ["ZURA_AUDIO:" + asset_id]}, "result": (audio,)}


async def create_voice(studio, body):
    import execution
    key = str(body.get("request_key", ""))
    if not re.fullmatch(r"[a-f0-9-]{36}", key):
        raise ValueError("Reload Studio before creating a voice track.")
    identity = uuid.UUID(key).hex
    jobfile = studio.store.root / (identity + ".json")
    if jobfile.exists():
        job = studio.store.load(identity)
        if job.get("kind") != "voice_job":
            raise ValueError("Create a new voice request.")
        return job  # Never duplicate a submitted or interrupted request.
    try:
        from ..longcat import runtime_config
        runtime_config()
    except (RuntimeError, OSError, KeyError) as e:
        raise ValueError("Set up Zura LongCat with Setup_LongCat_Windows.cmd first. " + str(e)) from e
    asset_id = uuid.uuid4().hex
    graph = voice_graph(body, studio.store, asset_id)
    prompt_id = str(uuid.uuid4())
    data = studio.server.trigger_on_prompt({"prompt": graph, "prompt_id": prompt_id,
                                          "client_id": body.get("client_id", "zura-studio")})
    graph = data["prompt"]
    studio.server.node_replace_manager.apply_replacements(graph)
    valid = await execution.validate_prompt(prompt_id, graph, None)
    if not valid[0]:
        raise ValueError("ComfyUI could not prepare this voice track: " + str(valid[1])[:1600])
    job = {"id": identity, "kind": "voice_job", "prompt_id": prompt_id, "asset_id": asset_id,
           "state": "queued", "created": time.time(), "server_address": studio.server_address}
    studio.store.save(job)
    number = studio.server.number
    studio.server.number += 1
    studio.server.prompt_queue.put((number, prompt_id, graph, {"client_id": data.get("client_id", "zura-studio"),
                                   "create_time": int(time.time()*1000)}, valid[2], {}))
    return job


def collect_voice(studio, identity):
    job = studio.store.load(identity)
    if job.get("kind") != "voice_job":
        raise ValueError("Choose a Studio voice job.")
    if job.get("server_address") != studio.server_address:
        return job
    # The output node persists the audio before Comfy writes queue history.
    # Recover completed speech even after a Comfy restart clears that history.
    if (studio.store.root / (job["asset_id"] + ".json")).is_file():
        from .studio import check_asset
        asset = studio.store.load(job["asset_id"])
        check_asset(asset)
        job.update(state="complete", audio=asset)
        studio.store.save(job)
        return job
    history = studio.server.prompt_queue.get_history(job["prompt_id"]).get(job["prompt_id"])
    if history:
        if history["status"].get("status_str") == "success":
            asset = studio.store.load(job["asset_id"])
            job.update(state="complete", audio=asset)
        else:
            errors = [m[1].get("exception_message", "") for m in history["status"].get("messages", []) if m[0] == "execution_error"]
            job.update(state="error", error=(errors[-1] if errors else "The voice job stopped before completing.")[:1600])
    else:
        running, pending = studio.server.prompt_queue.get_current_queue_volatile()
        if any(item[1] == job["prompt_id"] for item in running):
            job["state"] = "running"
        elif not any(item[1] == job["prompt_id"] for item in pending) and time.time() - job["created"] > 30:
            job.update(state="error", error="This voice job is no longer in the queue. Check ComfyUI before creating another take.")
    studio.store.save(job)
    return job


NODE_CLASS_MAPPINGS = {"ZuraStudioSaveVoice": ZuraStudioSaveVoice}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraStudioSaveVoice": "Zura · Use Generated Speech in Studio"}
