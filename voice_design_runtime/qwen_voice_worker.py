"""Local Qwen VoiceDesign worker. No downloads during generation."""
import argparse
import json
import math
import os
from pathlib import Path
import random
import time
import traceback
os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True, type=Path)
    args = parser.parse_args()
    job = json.loads(args.job.read_text(encoding='utf-8'))
    folder = args.job.resolve().parent
    report = {'status':'loading', 'model':'Qwen3-TTS-12Hz-1.7B-VoiceDesign', 'settings': job, 'max_new_tokens':2048, 'precision':'BF16 / SDPA'}
    (folder/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    try:
        import numpy as np
        import soundfile as sf
        import torch
        from qwen_tts import Qwen3TTSModel
        if not torch.cuda.is_available():
            raise RuntimeError('A CUDA GPU is required for this tested runtime.')
        device = f"cuda:{int(job['runtime'].get('device_index',0))}"
        torch.cuda.set_device(device)
        if not torch.cuda.is_bf16_supported():
            raise RuntimeError('This runtime requires BF16 support on the selected CUDA GPU.')
        torch.set_grad_enabled(False)
        t = time.perf_counter()
        model = Qwen3TTSModel.from_pretrained(job['runtime']['model_path'], device_map=device, dtype=torch.bfloat16, attn_implementation='sdpa', local_files_only=True)
        report['model_load_seconds'] = time.perf_counter()-t
        seed = int(job['seed'])
        random.seed(seed); np.random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
        torch.cuda.reset_peak_memory_stats(); torch.cuda.synchronize(); t = time.perf_counter()
        wavs, sr = model.generate_voice_design(text=job['script'], instruct=job['voice_description'], language=job['language'], non_streaming_mode=True, max_new_tokens=2048)
        torch.cuda.synchronize()
        report['generation_seconds'] = time.perf_counter()-t
        wav = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
        if not wav.size or not np.isfinite(wav).all() or np.max(np.abs(wav)) == 0:
            raise RuntimeError('Qwen returned invalid or silent audio.')
        sf.write(str(folder/'master_float32.wav'), wav, sr, subtype='FLOAT')
        gain = min(1.0, 0.999 / float(np.abs(wav).max()))
        sf.write(str(folder/'voice.wav'), wav*gain, sr, subtype='PCM_24')
        report.update(status='complete', sample_rate=sr, duration_seconds=len(wav)/sr, pcm_export_gain_db=20*math.log10(gain), torch_peak_allocated_mib=torch.cuda.max_memory_allocated()/2**20,
                      note='Short-form generation. Check the final words; output has a 2048-token generation cap. No EQ, denoising, pitch change or time stretch.')
    except Exception as error:
        report.update(status='failed', error=f'{type(error).__name__}: {error}')
        traceback.print_exc()
    (folder/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report['status']=='complete' else 1

if __name__ == '__main__':
    raise SystemExit(main())
