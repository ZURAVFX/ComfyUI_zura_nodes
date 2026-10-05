"""One-time setup. Run --reuse-lab PATH on the audition PC, or --install on another PC.

Only this explicit setup command downloads software. Synthesis stays offline.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

PACK = Path(__file__).resolve().parent
SOURCE_REVISION = "12c76b51d2a8aa6b6c9af5b25cd5ff8f7aa8178a"
MODEL_REVISION = "5d3e6dc007872d756c3a69b44951598d7d9bdf6d"


def run(command):
    subprocess.run([str(x) for x in command], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--reuse-lab", type=Path)
    modes.add_argument("--install", action="store_true")
    modes.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.home() / "ZuraLongCat")
    args = parser.parse_args()
    target = PACK / "longcat.local.json"
    if args.check:
        config = json.loads(target.read_text(encoding="utf-8"))
    elif args.reuse_lab:
        registry = json.loads((args.reuse_lab / "registry.json").read_text(encoding="utf-8-sig"))
        entry = next(item for item in registry["systems"] if item["id"] == "longcat")
        config = {key: entry[key] for key in ("python", "repo_path", "model_path", "tokenizer_path")}
        config.update(source_revision=SOURCE_REVISION, model_revision=MODEL_REVISION, device_index=0)
    else:
        uv, git = shutil.which("uv"), shutil.which("git")
        if not uv or not git:
            raise SystemExit("Install uv and Git, reopen your terminal, then run this setup again. See LONGCAT.md.")
        root = args.root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        env = root / ".venv"
        python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            run([uv, "venv", "--python", "3.11", env])
        run([uv, "pip", "install", "--python", python, "torch==2.8.0", "torchaudio==2.8.0",
             "--index-url", "https://download.pytorch.org/whl/cu128"])
        run([uv, "pip", "install", "--python", python, "-r", PACK / "longcat_runtime/requirements.txt"])
        repo = root / "LongCat-AudioDiT"
        if not repo.exists():
            run([git, "clone", "https://github.com/meituan-longcat/LongCat-AudioDiT.git", repo])
        dirty = subprocess.check_output([git, "-C", str(repo), "status", "--porcelain"], text=True).strip()
        if dirty:
            raise SystemExit(f"There are local edits in {repo}; refusing to replace them.")
        run([git, "-C", repo, "checkout", "--detach", SOURCE_REVISION])
        model, tokenizer = root / "models/LongCat-AudioDiT-3.5B", root / "models/umt5-tokenizer"
        staging = """import json,os,sys
from pathlib import Path
from huggingface_hub import HfApi,snapshot_download
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
model,tokenizer,revision=sys.argv[1:]
snapshot_download('meituan-longcat/LongCat-AudioDiT-3.5B',revision=revision,local_dir=model,allow_patterns=['*.json','*.safetensors','LICENSE*','README.md'])
tokenizer_revision=HfApi().model_info('google/umt5-base').sha
snapshot_download('google/umt5-base',revision=tokenizer_revision,local_dir=tokenizer,allow_patterns=['*token*','spiece.model','special_tokens_map.json','config.json','LICENSE*','README.md'])
Path(tokenizer,'zura_source_revision.txt').write_text(tokenizer_revision)
"""
        run([python, "-c", staging, model, tokenizer, MODEL_REVISION])
        config = {"python": str(python), "repo_path": str(repo), "model_path": str(model),
                  "tokenizer_path": str(tokenizer), "source_revision": SOURCE_REVISION,
                  "model_revision": MODEL_REVISION, "device_index": 0,
                  "tokenizer_revision": (tokenizer / "zura_source_revision.txt").read_text().strip()}
    for key, suffix in (("python", ""), ("repo_path", "audiodit/modeling_audiodit.py"),
                        ("model_path", "config.json"), ("tokenizer_path", "tokenizer_config.json")):
        file = Path(config[key]) / suffix if suffix else Path(config[key])
        if not file.is_file():
            raise SystemExit(f"Missing {key}: {file}")
    check = "import sys;sys.path.insert(0,sys.argv[1]);import torch,soundfile,librosa,audiodit;assert torch.cuda.is_available(),'CUDA unavailable';assert torch.cuda.is_bf16_supported(),'BF16 GPU required';print('LongCat runtime OK:',torch.cuda.get_device_name(0))"
    run([config["python"], "-c", check, config["repo_path"]])
    if not args.check:
        if target.exists():
            shutil.copy2(target, target.with_name(target.name + ".backup-" + str(time.time_ns())))
        target.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Ready. Machine settings: {target}\nRestart ComfyUI and open Zura_LongCat_Voice_Clone.json.")


if __name__ == "__main__":
    main()
