"""Download the optional local speech bundle; never upload user media."""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-directory", type=Path,
                        default=Path(__file__).resolve().parents[2] / "models")
    args = parser.parse_args()
    subprocess.run([sys.executable, "-m", "pip", "install", "diffusers>=0.33.0,<0.39", "transformers>=4.45,<5",
                    "huggingface_hub>=0.34", "safetensors"], check=True)
    from huggingface_hub import snapshot_download
    bundles = [("TMElyralab/MuseTalk", "MuseTalk", ["musetalkV15/musetalk.json", "musetalkV15/unet.pth"]),
               ("stabilityai/sd-vae-ft-mse", "sd-vae-ft-mse", ["config.json", "diffusion_pytorch_model.safetensors"]),
               ("openai/whisper-tiny", "whisper-tiny", ["config.json", "model.safetensors", "preprocessor_config.json"])]
    for repo, name, files in bundles:
        snapshot_download(repo, allow_patterns=files, local_dir=args.models_directory / "zura_speech" / name)
    print("Zura speech lip sync is ready. Restart ComfyUI after its current jobs finish.")


if __name__ == "__main__":
    main()
