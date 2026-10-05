"""Isolated CUDA LongCat runner. Launched by ZuraLongCatVoice, not imported by ComfyUI.

Uses the upstream model without editing its checkout. The precision adapter
matches the 16 GB blind-test configuration: BF16 DiT/text, FP16 VAE, FP32 ODE.
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import random
import sys
import time
import traceback

from text import split_script


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run(job, directory, report):
    # No downloads during synthesis; the separate installer stages all assets.
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    import numpy as np
    import soundfile as sf
    import torch
    config = job["runtime"]
    sys.path.insert(0, config["repo_path"])
    from audiodit import AudioDiTModel
    from transformers import AutoTokenizer
    spec = importlib.util.spec_from_file_location("longcat_upstream_utils", Path(config["repo_path"]) / "utils.py")
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("LongCat requires a CUDA GPU with BF16 support (RTX 30-series or newer).")
    device = f"cuda:{int(config.get('device_index', 0))}"
    torch.cuda.set_device(device)
    torch.backends.cudnn.benchmark = False
    torch.set_grad_enabled(False)
    t = time.perf_counter()
    model = AudioDiTModel.from_pretrained(config["model_path"], dtype=torch.float32, local_files_only=True).eval()
    model.text_encoder.to(dtype=torch.bfloat16)
    model.transformer.to(dtype=torch.bfloat16)
    model.vae.to_half()
    model.to(device)
    tokenizer = AutoTokenizer.from_pretrained(config["tokenizer_path"], local_files_only=True)
    original_forward = model.transformer.forward

    def mixed_precision_forward(*args, **kwargs):
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            result = original_forward(*args, **kwargs)
        result["last_hidden_state"] = result["last_hidden_state"].float()
        return result

    # Compute policy lives here in the external runner, never in ComfyUI's model code.
    model.transformer.forward = mixed_precision_forward
    torch.cuda.synchronize()
    sr, hop = int(model.config.sampling_rate), int(model.config.latent_hop)
    maximum = float(model.config.max_wav_duration)
    report.update(model_load_seconds=time.perf_counter() - t,
                  gpu=torch.cuda.get_device_name(device), native_sample_rate=sr,
                  precision="BF16 DiT/text encoder; FP16 VAE; FP32 ODE state",
                  source_revision=config.get("source_revision", "local checkout"),
                  model_revision=config.get("model_revision", "local checkpoint"))
    prompt_audio, prompt_frames, ratio, prompt_text = None, 0, 1.0, ""
    if job["mode"] == "Clone a voice":
        prompt_text = upstream.normalize_text(job["reference_transcript"])
        prompt_audio = upstream.load_audio(str(directory / "reference.wav"), sr).unsqueeze(0).to(device)
        if prompt_audio.shape[-1] / sr >= maximum - hop / sr:
            raise ValueError(f"LongCat's combined window is {maximum:g}s. Trim the reference to leave space for speech.")
        _, prompt_frames = model.encode_prompt_audio(prompt_audio)
        ratio = float(np.clip((prompt_frames * hop / sr) / max(upstream.approx_duration_from_text(prompt_text, maximum), 1e-9), 1.0, 1.5))
    text = upstream.normalize_text(job["script"]).strip()
    remaining_seconds = maximum - prompt_frames * hop / sr - hop / sr
    # Match the tested duration heuristic at pace=1; split instead of silently capping a long script.
    def duration_for(piece):
        return upstream.approx_duration_from_text(piece, float("inf")) * ratio / job["pace"]
    chunks = split_script(text, duration_for, min(25.0, remaining_seconds))
    report.update(normalized_script=text, reference_rate_ratio=ratio, chunks=[], status="generating")
    if prompt_audio is None and len(chunks) > 1:
        report["notice"] = "Unconditioned TTS can change speaker between chunks. Use a generated short sample as a reference to lock the voice."
    write_json(directory / "report.json", report)
    waves = []
    for index, piece in enumerate(chunks):
        seed = (job["seed"] + index) % 2**32
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        # As in the audition adapter, encode after reseeding before duration planning.
        if prompt_audio is not None:
            _, current_prompt_frames = model.encode_prompt_audio(prompt_audio)
            if current_prompt_frames != prompt_frames:
                raise RuntimeError("The reference frame count changed unexpectedly.")
        inputs = tokenizer([f"{prompt_text} {piece}" if prompt_text else piece], padding="longest", return_tensors="pt")
        generation_frames = max(1, int(duration_for(piece) * sr // hop))
        total_frames = prompt_frames + generation_frames
        if total_frames > int(maximum * sr // hop):
            raise RuntimeError("The planned chunk exceeds the model window; no speech was truncated.")
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        started = time.perf_counter()
        result = model(input_ids=inputs.input_ids.to(device), attention_mask=inputs.attention_mask.to(device),
                       prompt_audio=prompt_audio, duration=total_frames, steps=16,
                       cfg_strength=4.0, guidance_method="apg")
        wav = result.waveform.squeeze().detach().float().cpu().numpy()
        torch.cuda.synchronize()
        if wav.ndim != 1 or not wav.size or not np.isfinite(wav).all():
            raise RuntimeError(f"Chunk {index + 1} returned invalid audio; inspect worker.log.")
        file = f"chunk_{index + 1:03d}.wav"
        sf.write(str(directory / file), wav, sr, subtype="FLOAT")
        report["chunks"].append({"file": file, "text": piece, "seed": seed,
                                 "duration_seconds": len(wav) / sr,
                                 "generation_seconds": time.perf_counter() - started,
                                 "torch_peak_allocated_mib": torch.cuda.max_memory_allocated() / 2**20,
                                 "peak_absolute": float(np.abs(wav).max())})
        write_json(directory / "report.json", report)
        print(f"ZURA_PROGRESS {index + 1} {len(chunks)}", flush=True)
        if waves:
            waves.append(np.zeros(round(0.15 * sr), dtype=np.float32))
        waves.append(wav)
        del result
    combined = np.concatenate(waves)
    # Float master preserves model output. A single gain reduction prevents integer WAV clipping.
    sf.write(str(directory / "master_float32.wav"), combined, sr, subtype="FLOAT")
    peak = float(np.abs(combined).max())
    gain = min(1.0, 0.999 / peak) if peak else 1.0
    sf.write(str(directory / "voice.wav"), combined * gain, sr, subtype="PCM_24")
    report.update(status="complete", duration_seconds=len(combined) / sr,
                  pcm_export_gain_db=20 * math.log10(gain), chunk_gap_seconds=0.15,
                  output="voice.wav", float_master="master_float32.wav",
                  postprocessing="Concatenation; 150 ms between chunks; PCM copy reduced only if needed to avoid clipping. No EQ, denoising or time stretch.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args()
    directory = args.job.resolve().parent
    job = json.loads(args.job.read_text(encoding="utf-8"))
    report = {"version": 1, "status": "loading", "model": "LongCat-AudioDiT-3.5B",
              "script": job["script"], "mode": job["mode"], "seed": job["seed"], "pace": job["pace"],
              "reference_transcript": job["reference_transcript"],
              "settings": {"steps": 16, "guidance_method": "apg", "cfg_strength": 4.0},
              "seed_note": "Same seed reproduces sampling on this stack, not necessarily across hardware or versions."}
    write_json(directory / "report.json", report)
    try:
        run(job, directory, report)
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        traceback.print_exc()
    finally:
        write_json(directory / "report.json", report)
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
