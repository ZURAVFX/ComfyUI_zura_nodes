"""Explicit download setup for native Wan speech. No user media is read or sent."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

KIJAI = ("Kijai/WanVideo_comfy", "8260d429d19fd7a72304cad059160b95d843913f")
CORE = ("Comfy-Org/Wan_2.1_ComfyUI_repackaged", "123acf1cc74bccbb9bfff8ac1ee72edc08c2341d")
# folder, local basename, repository, pinned revision, remote file, size, SHA256
MODELS = [
    ("diffusion_models", "Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors", *KIJAI,
     "Wan2_1-I2V-14B-480P_fp8_e4m3fn.safetensors", 16993877896,
     "996dbad030df09b0b3c8e764f0fb5a81b98b220ab89524d6a9369e9ed882791f"),
    ("diffusion_models", "Wan2_1-InfiniteTalk-Single_fp16.safetensors", *KIJAI,
     "InfiniteTalk/Wan2_1-InfiniTetalk-Single_fp16.safetensors", 5125258232,
     "bf212c5c647eaf1c019b2158d2edf4a360d97e38b746c4bac994fee485e09fc3"),
    ("loras", "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", *KIJAI,
     "Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors", 738005744,
     "85c4a61c30e0497aa44b91d93a893b624708461a56fe5485183b28fa07e2dfb3"),
    ("vae", "Wan2_1_VAE_bf16.safetensors", *KIJAI, "Wan2_1_VAE_bf16.safetensors", 253806278,
     "1ab9a32cc2c740f6e39d80d367ce5dcc28db8c71b79b28670546b8973e9d75f9"),
    ("wav2vec2", "chinese-wav2vec2-base.bin", "TencentGameMate/chinese-wav2vec2-base",
     "3991242c806928916fff4a8c0e4f76acf661b743", "pytorch_model.bin", 380261837,
     "be2da40c9e7ae26bfc904a3ed79ebb9e8f060bec6dba85d6a6ae86114bc38901"),
    ("text_encoders", "umt5_xxl_fp8_e4m3fn_scaled.safetensors", *CORE,
     "split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors", 6735906897,
     "c3355d30191f1f066b26d93fba017ae9809dce6c627dda5f6a66eaa651204f68"),
    ("clip_vision", "clip_vision_h.safetensors", *CORE, "split_files/clip_vision/clip_vision_h.safetensors", 1264219396,
     "64a7ef761bfccbadbaa3da77366aac4185a6c58fa5de5f589b42a65bcc21f161"),
    ("detection", "vitpose-l-wholebody.onnx", "JunkyByte/easy_ViTPose",
     "e83805274e89428969355ec4afffcbc413e79188", "onnx/wholebody/vitpose-l-wholebody.onnx", 1234579166,
     "89bdf6692d9224dbd5004dcef23a9ba2d54c5776212b359d5a5b5068ac14fd08"),
    ("detection", "yolov10m.onnx", "Wan-AI/Wan2.2-Animate-14B",
     "cb93a225fbaf1ca100f54e79da8f994995b689b3", "process_checkpoint/det/yolov10m.onnx", 61659339,
     "89b526498a6d55f869a6ab52e3a2eb20ad45b3711c1f7de3dd9ca0b399dfd6d7"),
]
ALIASES = {"Wan2_1-InfiniteTalk-Single_fp16.safetensors": ["Wan2_1-InfiniTetalk-Single_fp16.safetensors"]}
NODE_PACKS = [
    "https://github.com/kijai/ComfyUI-WanVideoWrapper",
    "https://github.com/kijai/ComfyUI-WanAnimatePreprocess",
    "https://github.com/kijai/ComfyUI-KJNodes",
    "https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite",
]


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def desktop_configs():
    """Bounded discovery of model-path YAML only, without reading account data."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    directory = Path(appdata) / "Comfy Desktop" / "instance-model-paths"
    files = sorted(directory.glob("inst-*.yaml")) if directory.is_dir() else []
    if len(files) > 64:
        raise ValueError("There are many Desktop instances. Select one with --extra-model-paths-config.")
    return files


def directories(comfy_directory, models_directory=None, extra_configs=None):
    """Honour Comfy's configured shared model directories without loading nodes."""
    result = {item[0]: [] for item in MODELS}
    if models_directory is not None:
        return {name: [Path(models_directory) / name] for name in result}
    comfy_directory = Path(comfy_directory)
    if (comfy_directory / "folder_paths.py").is_file():
        sys.path.insert(0, str(comfy_directory))
        folder_paths = importlib.import_module("folder_paths")
        from utils.extra_config import load_extra_path_config
        configuration = comfy_directory / "extra_model_paths.yaml"
        configurations = ([configuration] if configuration.is_file() else []) + list(extra_configs if extra_configs is not None else desktop_configs())
        for configuration in dict.fromkeys(Path(path).resolve() for path in configurations):
            if not configuration.is_file():
                raise ValueError("Missing model-path configuration: " + str(configuration))
            load_extra_path_config(str(configuration))
        for name in result:
            result[name] = [Path(p) for p in folder_paths.folder_names_and_paths.get(name, ([],))[0]]
    for name in result:
        # Custom packs register some local folders only when their nodes load
        # (notably wav2vec2). Discover those without importing GPU node modules.
        local = comfy_directory / "models" / name
        if local not in result[name]:
            result[name].append(local)
    return result


def existing(spec, locations, verify=False):
    folder, name, _, _, _, size, sha = spec
    for directory in locations[folder]:
        if not directory.is_dir():
            continue
        for basename in (name, *ALIASES.get(name, [])):
            for path in directory.rglob(basename):
                if path.is_file() and path.stat().st_size == size and (not verify or digest(path) == sha):
                    return path
    return None


def install(spec, locations, download):
    folder, name, repository, revision, remote, size, sha = spec
    cached = Path(download(repo_id=repository, revision=revision, filename=remote))
    if cached.stat().st_size != size or digest(cached) != sha:
        raise ValueError("Downloaded model failed verification: " + name)
    destination = locations[folder][0] / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("An existing model has the wrong size or hash: " + str(destination) + ". Move it aside before rerunning setup.")
    temporary = destination.with_name(name + "." + uuid.uuid4().hex + ".part")
    try:
        shutil.copyfile(cached, temporary)
        if temporary.stat().st_size != size or digest(temporary) != sha:
            raise ValueError("Copied model failed verification: " + name)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy-directory", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--models-directory", type=Path, help="Explicit shared models root; otherwise use Comfy's configured paths.")
    parser.add_argument("--extra-model-paths-config", action="append", type=Path,
                        help="Additional Comfy model-path YAML; repeat for multiple files. Defaults to discovered Desktop instance model-path YAML.")
    parser.add_argument("--check", action="store_true", help="Check model files without downloads or installation.")
    parser.add_argument("--verify", action="store_true", help="Also hash every existing model; this reads several large files.")
    args = parser.parse_args(argv)
    locations = directories(args.comfy_directory, args.models_directory, args.extra_model_paths_config)
    missing = [item for item in MODELS if existing(item, locations, args.verify) is None]
    print("Wan speech models: " + str(len(MODELS) - len(missing)) + "/" + str(len(MODELS)) + " ready.")
    for spec in missing:
        print("Missing: " + spec[0] + "/" + spec[1])
    print("Install these native packs through Comfy Manager if they are missing:")
    for url in NODE_PACKS:
        print(url)
    if args.check:
        return 1 if missing else 0
    if missing:
        try:
            from huggingface_hub import hf_hub_download
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install", "huggingface_hub>=0.34,<2"], check=True)
            from huggingface_hub import hf_hub_download
        for spec in missing:
            print("Downloading and verifying " + spec[1])
            install(spec, locations, hf_hub_download)
    print("Model files are ready. Restart ComfyUI after its current jobs finish, then check Wan speech readiness in Zura Studio.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
