"""Download the optional local speech bundle; never upload user media."""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-directory", type=Path,
                        default=Path(__file__).resolve().parents[2] / "models")
    parser.add_argument("--fast-only", action="store_true", help="Install the smaller 256 px MuseTalk option.")
    args = parser.parse_args()
    subprocess.run([sys.executable, "-m", "pip", "install", "diffusers>=0.33.0,<0.39", "transformers>=4.45,<5",
                    "huggingface_hub>=0.34", "safetensors", "accelerate>=0.30,<2", "einops>=0.8"], check=True)
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
    print("Zura speech lip sync is ready. Automatic selects sharp 512 px lip sync when installed.")
    print("Restart ComfyUI after its current jobs finish.")


if __name__ == "__main__":
    main()
