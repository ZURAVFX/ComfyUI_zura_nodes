"""Explicit, one-time setup for local Qwen VoiceDesign. Never run on node import."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

PACK = Path(__file__).resolve().parent
MODEL_ID = 'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign'
MODEL_REVISION = '5ecdb67327fd37bb2e042aab12ff7391903235d3'


def config_path():
    return Path(os.environ.get('ZURA_QWEN_VOICE_DESIGN_CONFIG', str(PACK/'qwen_voice_design.local.json'))).expanduser().resolve()


def read_config(path=None):
    path = Path(path).expanduser().resolve() if path is not None else config_path()
    if not path.is_file():
        raise RuntimeError('Qwen VoiceDesign is not set up. Run Setup_Voice_Design_Windows.cmd once; see VOICE_DESIGN.md.')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    for key in ('python', 'model_path'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f'Missing {key} in VoiceDesign configuration: {path}')
        value = Path(data[key]).expanduser()
        data[key] = str((value if value.is_absolute() else path.parent/value).resolve())
    if not Path(data['python']).is_file():
        raise FileNotFoundError('VoiceDesign Python is missing. Run Setup_Voice_Design_Windows.cmd again.')
    model = Path(data['model_path'])
    for file in ('config.json', 'model.safetensors', 'tokenizer_config.json', 'vocab.json',
                 'merges.txt', 'preprocessor_config.json', 'speech_tokenizer/config.json',
                 'speech_tokenizer/model.safetensors', 'speech_tokenizer/preprocessor_config.json'):
        if not (model/file).is_file():
            raise FileNotFoundError(f'VoiceDesign model asset missing: {model/file}. Run the installer to complete the download.')
    metadata = json.loads((model/'config.json').read_text(encoding='utf-8'))
    if metadata.get('tts_model_type') != 'voice_design':
        raise ValueError('Select the Qwen VoiceDesign checkpoint, not Base or CustomVoice.')
    data['device_index'] = int(data.get('device_index', 0))
    if data['device_index'] < 0:
        raise ValueError('device_index must be a non-negative CUDA device number.')
    return data


def isolated_environment(offline=False):
    env = os.environ.copy()
    for name in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV'):
        env.pop(name, None)
    env.update(PYTHONUTF8='1', PYTHONNOUSERSITE='1', HF_HUB_DISABLE_TELEMETRY='1')
    if offline:
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    return env


def probe(config):
    code = """import sys,torch
from qwen_tts import Qwen3TTSModel
from transformers import AutoConfig,AutoTokenizer
assert torch.cuda.is_available(), 'CUDA is unavailable in the VoiceDesign environment'
torch.cuda.set_device(int(sys.argv[2]))
assert torch.cuda.is_bf16_supported(), 'Selected GPU requires BF16 support'
assert callable(Qwen3TTSModel.generate_voice_design)
AutoTokenizer.from_pretrained(sys.argv[1],local_files_only=True,fix_mistral_regex=True)
print('VoiceDesign runtime OK:',torch.cuda.get_device_name())
"""
    subprocess.run([config['python'], '-c', code, config['model_path'], str(config['device_index'])],
                   env=isolated_environment(offline=True), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--install', action='store_true')
    modes.add_argument('--check', action='store_true')
    modes.add_argument('--reuse-config', type=Path, help='Reuse an existing local VoiceDesign runtime without downloading.')
    parser.add_argument('--root', type=Path, default=Path.home()/'ZuraVoiceDesign')
    parser.add_argument('--config', type=Path, help='Optional machine-config destination; use the environment override to select it at runtime.')
    args = parser.parse_args()
    target = args.config.expanduser().resolve() if args.config else config_path()
    if args.check:
        data = read_config(target)
    elif args.reuse_config:
        data = read_config(args.reuse_config)
    else:
        uv = shutil.which('uv')
        if not uv:
            raise SystemExit('Install uv, then reopen the terminal and run setup again. See VOICE_DESIGN.md.')
        root = args.root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        environment = root/'.venv'
        python = environment/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        env = isolated_environment()
        def run(command):
            subprocess.run([str(item) for item in command], env=env, check=True)
        if not python.is_file():
            run([uv, 'venv', '--python', '3.11', environment])
        run([uv, 'pip', 'install', '--python', python, 'torch==2.8.0', 'torchaudio==2.8.0',
             '--index-url', 'https://download.pytorch.org/whl/cu128'])
        run([uv, 'pip', 'install', '--python', python, '-r', PACK/'voice_design_runtime/requirements.txt'])
        receipt = root/'model_snapshot.json'
        # The shared Hugging Face cache avoids duplicating weights already downloaded by other workflows.
        staging = """import json,sys
from pathlib import Path
from huggingface_hub import snapshot_download
model=snapshot_download(sys.argv[1],revision=sys.argv[2],allow_patterns=['*.json','*.txt','*.safetensors','README.md','LICENSE*'])
Path(sys.argv[3]).write_text(json.dumps({'path':model,'revision':sys.argv[2]}),encoding='utf-8')
"""
        run([python, '-c', staging, MODEL_ID, MODEL_REVISION, receipt])
        snapshot = json.loads(receipt.read_text(encoding='utf-8'))
        data = {'python':str(python), 'model_path':snapshot['path'], 'revision':MODEL_REVISION, 'device_index':0}
    probe(data)
    if not args.check:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            shutil.copy2(target, target.with_name(target.name+'.backup-'+str(time.time_ns())))
        target.write_text(json.dumps(data, indent=2), encoding='utf-8')
        read_config(target)
    print('VoiceDesign ready. Machine configuration:', target)
    print('Restart ComfyUI. Open Zura_Voice_Design_Qwen_Direct.json or Zura_Voice_Design_Qwen_to_LongCat.json.')


if __name__ == '__main__':
    main()
