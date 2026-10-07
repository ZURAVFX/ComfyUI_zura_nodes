"""Qwen VoiceDesign for direct speech or reusable LongCat references."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import soundfile as sf
import torch
import comfy.model_management as model_management
from .longcat import project_directory, stop_worker
from .setup_voice_design import read_config, config_path

ROOT = Path(__file__).resolve().parent

class ZuraQwenVoiceDesign:
    CATEGORY = 'Zura/audio'
    FUNCTION = 'generate'
    RETURN_TYPES = ('AUDIO',)
    RETURN_NAMES = ('audio',)
    DESCRIPTION = 'Design an invented voice from a description. Outputs final speech directly, or a reference for LongCat. Start with a few sentences and check the final words. Saves WAV and generation details.'

    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {
            'voice_description': ('STRING', {'multiline': True, 'default': '', 'tooltip': 'Describe the voice, accent, tone and delivery. These instructions are not spoken.'}),
            'script': ('STRING', {'multiline': True, 'default': '', 'tooltip': 'Only the words you want spoken. Start with a few sentences and verify all final words.'}),
            'language': (['English','Chinese','French','German','Italian','Japanese','Korean','Portuguese','Russian','Spanish'],),
            'seed': ('INT', {'default': 147, 'min': 0, 'max': 4294967295, 'control_after_generate': True}),
            'project': ('STRING', {'default': 'Designed_Voice'}),
        }}

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # ComfyUI caches unchanged designed references when only the final script changes.
        path = config_path()
        config_bytes = path.read_bytes() if path.is_file() else b'not configured'
        worker = (ROOT/'voice_design_runtime/qwen_voice_worker.py').read_bytes()
        return hashlib.sha256(config_bytes + worker).hexdigest()

    def generate(self, voice_description, script, language, seed, project):
        if not voice_description.strip() or not script.strip():
            raise ValueError('Enter a voice description and the words to speak.')
        if language not in self.INPUT_TYPES()['required']['language'][0]:
            raise ValueError('Choose a supported language.')
        if not 0 <= seed < 2**32:
            raise ValueError('Seed must be between 0 and 4294967295.')
        config = read_config()
        directory = project_directory(project)
        job = {'voice_description': voice_description, 'script': script, 'language': language, 'seed': int(seed), 'runtime': config}
        (directory/'job.json').write_text(json.dumps(job, indent=2), encoding='utf-8')
        (directory/'script.txt').write_text(script, encoding='utf-8')
        (directory/'voice_description.txt').write_text(voice_description, encoding='utf-8')
        env = os.environ.copy()
        for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','CONDA_PREFIX','CONDA_DEFAULT_ENV'):
            env.pop(key, None)
        env.update(PYTHONUTF8='1', PYTHONUNBUFFERED='1', PYTHONNOUSERSITE='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
        model_management.throw_exception_if_processing_interrupted()
        model_management.unload_all_models()
        model_management.soft_empty_cache()
        process = None
        try:
            with (directory/'worker.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen([config['python'], '-u', str(ROOT/'voice_design_runtime/qwen_voice_worker.py'), '--job', str(directory/'job.json')],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=ROOT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                while process.poll() is None:
                    model_management.throw_exception_if_processing_interrupted()
                    time.sleep(0.25)
            report_path = directory/'report.json'
            report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
            if process.returncode or report.get('status') != 'complete':
                raise RuntimeError(f"Qwen VoiceDesign failed: {report.get('error', 'See worker.log')}\n{directory}")
        finally:
            if process is not None:
                stop_worker(process)
        # Return the original float samples for downstream cloning, not the PCM listening copy.
        wav, sr = sf.read(str(directory/'master_float32.wav'), dtype='float32', always_2d=True)
        print(f'[Zura Qwen VoiceDesign] Saved {directory}')
        return ({'waveform': torch.from_numpy(wav.T.copy()).unsqueeze(0), 'sample_rate': sr},)

NODE_CLASS_MAPPINGS = {'ZuraQwenVoiceDesign': ZuraQwenVoiceDesign}
NODE_DISPLAY_NAME_MAPPINGS = {'ZuraQwenVoiceDesign': 'Zura Qwen Voice Design'}
