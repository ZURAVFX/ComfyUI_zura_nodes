"""Local LongCat speech node. TTS dependencies stay in a separate interpreter."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

import folder_paths
import numpy as np
import soundfile as sf
import torch
import comfy.model_management as model_management
from comfy.utils import ProgressBar

PACK_ROOT = Path(__file__).resolve().parent


def runtime_config():
    path = Path(os.environ.get("ZURA_LONGCAT_CONFIG", str(PACK_ROOT / "longcat.local.json"))).expanduser()
    if not path.is_file():
        raise RuntimeError("LongCat is not set up on this machine. Run setup_longcat.py once; see LONGCAT.md in zura_nodes.")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    for key, required in (("python", None), ("repo_path", "audiodit/modeling_audiodit.py"),
                          ("model_path", "config.json"), ("tokenizer_path", "tokenizer_config.json")):
        value = Path(data[key]).expanduser()
        if not value.is_absolute():
            value = path.parent / value
        value = value.resolve()
        target = value / required if required else value
        if not target.is_file():
            raise FileNotFoundError(f"LongCat {key} is missing: {target}. Run setup_longcat.py or correct longcat.local.json.")
        data[key] = str(value)
    return data


def project_directory(project):
    name = project.strip() or "untitled"
    # This field is deliberately a label, not a freely writable filesystem path.
    if len(name) > 120 or any(c in name for c in '<>:"/\\|?*') or name in {".", ".."} or any(ord(c) < 32 for c in name):
        raise ValueError("Use a project label, not a path (for example: Client_Campaign_EN).")
    root = (Path(folder_paths.get_output_directory()) / "zura_voice").resolve()
    run = (root / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}").resolve()
    if not run.is_relative_to(root):
        raise ValueError("The project must stay inside the ComfyUI output directory.")
    run.mkdir(parents=True, exist_ok=False)
    return run


def stop_worker(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class ZuraLongCatVoice:
    CATEGORY = "Zura/audio"
    FUNCTION = "generate"
    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("audio", "run_report")
    DESCRIPTION = "Local LongCat 3.5B: clone a reference voice or generate TTS. Saves 24-bit WAV, float master, chunks and settings under output/zura_voice. English and Chinese."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mode": (["Clone a voice", "Text to speech"],),
            "script": ("STRING", {"multiline": True, "default": "", "tooltip": "The words to generate. Long scripts are split at natural boundaries, never cut to fit the model window."}),
            "reference_transcript": ("STRING", {"multiline": True, "default": "", "tooltip": "Exact words in the reference audio, including any fillers. Not used in Text to speech mode."}),
            "pace": ("FLOAT", {"default": 1.0, "min": 0.5, "max": 2.0, "step": 0.05, "tooltip": "1.0 matches the tested duration estimate. Above 1 is faster; below 1 is slower. Changes synthesis duration, not playback pitch; not an exact duration guarantee."}),
            "seed": ("INT", {"default": 8923, "min": 0, "max": 4294967295, "control_after_generate": True, "tooltip": "Keep fixed for repeatable takes. Randomise for a new performance. The following chunks use consecutive seeds."}),
            "project": ("STRING", {"default": "Client_Project_EN", "tooltip": "Output label. Each run gets a new folder so existing audio is never overwritten."}),
        }, "optional": {
            "reference_audio": ("AUDIO", {"lazy": True, "tooltip": "One clean speaker. Start with a prepared 8–20 second excerpt. TTS mode does not evaluate this branch."}),
        }}

    def check_lazy_status(self, mode, reference_audio=None, **kwargs):
        return ["reference_audio"] if mode == "Clone a voice" and reference_audio is None else []

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Each Run creates a retained take even when the seed remains fixed.
        return float("nan")

    def generate(self, mode, script, reference_transcript, pace, seed, project, reference_audio=None):
        if mode not in ("Clone a voice", "Text to speech"):
            raise ValueError("Choose Clone a voice or Text to speech.")
        if not script.strip():
            raise ValueError("Enter the words to generate in script.")
        if not np.isfinite(pace) or pace <= 0:
            raise ValueError("Pace must be a positive number.")
        if not 0 <= seed < 2**32:
            raise ValueError("Seed must be between 0 and 4294967295.")
        config = runtime_config()
        if mode == "Clone a voice":
            if reference_audio is None:
                raise ValueError("Connect a reference recording, or choose Text to speech.")
            if not reference_transcript.strip():
                raise ValueError("Paste the exact words spoken in the reference clip into reference_transcript.")
            waveform = reference_audio["waveform"]
            sr = int(reference_audio["sample_rate"])
            if waveform.ndim != 3 or waveform.shape[0] != 1 or waveform.shape[-1] == 0 or sr <= 0:
                raise ValueError("Use one nonempty reference audio clip, not an audio batch.")
            mono = waveform[0].detach().float().cpu().mean(dim=0).numpy()
            if not np.isfinite(mono).all():
                raise ValueError("The reference contains invalid audio samples.")
        directory = project_directory(project)
        job = {"mode": mode, "script": script, "reference_transcript": reference_transcript if mode == "Clone a voice" else "",
               "pace": float(pace), "seed": int(seed), "runtime": config}
        if mode == "Clone a voice":
            sf.write(str(directory / "reference.wav"), mono, sr, subtype="FLOAT")
            job["reference_sha256"] = hashlib.sha256((directory / "reference.wav").read_bytes()).hexdigest()
        (directory / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        (directory / "script.txt").write_text(script, encoding="utf-8")
        env = os.environ.copy()
        for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"):
            env.pop(key, None)
        env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1", PYTHONNOUSERSITE="1",
                   HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
        command = [config["python"], "-u", str(PACK_ROOT / "longcat_runtime" / "worker.py"), "--job", str(directory / "job.json")]
        model_management.throw_exception_if_processing_interrupted()
        model_management.unload_all_models()
        model_management.soft_empty_cache()
        progress = ProgressBar(1)
        print(f"[Zura LongCat] Generating in {directory}")
        process = None
        try:
            with (directory / "worker.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                           cwd=config["repo_path"], env=env,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                while process.poll() is None:
                    model_management.throw_exception_if_processing_interrupted()
                    time.sleep(0.25)
            report = json.loads((directory / "report.json").read_text(encoding="utf-8")) if (directory / "report.json").is_file() else {}
            if process.returncode or report.get("status") != "complete":
                raise RuntimeError(f"LongCat failed: {report.get('error', 'See worker.log for details.')}\nRun folder: {directory}")
        finally:
            if process is not None:
                stop_worker(process)
        wav, output_sr = sf.read(str(directory / "voice.wav"), dtype="float32", always_2d=True)
        progress.update_absolute(1, 1)
        info = {"folder": str(directory), "wav": str(directory / "voice.wav"), **report}
        print(f"[Zura LongCat] Saved {directory / 'voice.wav'}")
        return ({"waveform": torch.from_numpy(wav.T.copy()).unsqueeze(0), "sample_rate": output_sr},
                json.dumps(info, ensure_ascii=False, indent=2))


NODE_CLASS_MAPPINGS = {"ZuraLongCatVoice": ZuraLongCatVoice}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraLongCatVoice": "Zura LongCat Voice"}
