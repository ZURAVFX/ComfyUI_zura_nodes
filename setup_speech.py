"""Check or explicitly download optional local speech models; never upload user media."""
import argparse
import importlib.util
import sys
from pathlib import Path


DEPENDENCIES = (
    "diffusers>=0.33.0,<0.39", "transformers>=4.45,<5", "huggingface_hub>=0.34",
    "safetensors", "accelerate>=0.30,<2", "einops>=0.8",
)


def required_files(models_directory, fast_only):
    files = [
        models_directory / "zura_speech" / "sd-vae-ft-mse" / "config.json",
        models_directory / "zura_speech" / "sd-vae-ft-mse" / "diffusion_pytorch_model.safetensors",
    ]
    if fast_only:
        files.extend((
            models_directory / "zura_speech" / "MuseTalk" / "musetalkV15" / "musetalk.json",
            models_directory / "zura_speech" / "MuseTalk" / "musetalkV15" / "unet.pth",
            models_directory / "zura_speech" / "whisper-tiny" / "config.json",
            models_directory / "zura_speech" / "whisper-tiny" / "model.safetensors",
            models_directory / "zura_speech" / "whisper-tiny" / "preprocessor_config.json",
        ))
    else:
        files.extend((
            models_directory / "zura_speech" / "LatentSync-1.6" / "latentsync_unet.pt",
            models_directory / "zura_speech" / "LatentSync-1.6" / "whisper" / "tiny.pt",
        ))
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-directory", type=Path,
                        default=Path(__file__).resolve().parents[2] / "models")
    parser.add_argument("--fast-only", action="store_true", help="Select the smaller 256 px MuseTalk option.")
    parser.add_argument("--check", action="store_true", help="Check required local model files without downloading.")
    args = parser.parse_args()
    missing = [path for path in required_files(args.models_directory, args.fast_only) if not path.is_file()]
    print("Speech model files: " + ("ready" if not missing else "missing"))
    for path in missing:
        print("Missing: " + str(path))
    if args.check:
        return 0 if not missing else 1
    modules = ("diffusers", "transformers", "huggingface_hub", "safetensors", "accelerate", "einops")
    absent = [name for name in modules if importlib.util.find_spec(name) is None]
    if absent:
        print("Missing optional Python packages: " + ", ".join(absent))
        print("Install the optional dependencies manually in this ComfyUI Python environment, then rerun setup:")
        packages = " ".join('"' + package + '"' for package in DEPENDENCIES)
        print('"' + sys.executable + '" -m pip install ' + packages)
        return 2
    from huggingface_hub import snapshot_download
    bundles = [("stabilityai/sd-vae-ft-mse", "sd-vae-ft-mse", ["config.json", "diffusion_pytorch_model.safetensors"], None)]
    if args.fast_only:
        bundles += [("TMElyralab/MuseTalk", "MuseTalk", ["musetalkV15/musetalk.json", "musetalkV15/unet.pth"], None),
                    ("openai/whisper-tiny", "whisper-tiny", ["config.json", "model.safetensors", "preprocessor_config.json"], None)]
    else:
        bundles += [("ByteDance/LatentSync-1.6", "LatentSync-1.6", ["latentsync_unet.pt", "whisper/tiny.pt"],
                     "c42c7e6c8e9c213626389fa7d9a3c444b8536353")]
    for repo, name, files, revision in bundles:
        snapshot_download(repo, revision=revision, allow_patterns=files,
                          local_dir=args.models_directory / "zura_speech" / name)
    print("Zura speech lip sync model files are ready. Automatic selects sharp 512 px lip sync when installed.")
    print("Restart ComfyUI after its current jobs finish.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
