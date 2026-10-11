"""Explicit setup for H3 Enhanced 1080p; no media is read or uploaded."""
from __future__ import annotations

import argparse
import importlib
import os
import shutil
import sys
import uuid
from pathlib import Path

import requests

from setup_wan_speech import desktop_configs, digest

MODEL = "2xNomosUni_esrgan_multijpg.pth"
MODEL_BYTES = 33701468
MODEL_SHA256 = "65c8fe23425e0bca96f23dc8fa484763cc2af08647df575407d1947de89b8529"
MODEL_URL = (
    "https://github.com/Phhofm/models/releases/download/"
    "2xNomosUni_esrgan_multijpg/2xNomosUni_esrgan_multijpg.pth"
)


def model_directories(comfy_directory, models_directory=None, extra_configs=None):
    if models_directory is not None:
        return [Path(models_directory) / "upscale_models"]
    comfy_directory = Path(comfy_directory).resolve()
    if not (comfy_directory / "folder_paths.py").is_file():
        raise ValueError("Select your ComfyUI folder with --comfy-directory.")
    sys.path.insert(0, str(comfy_directory))
    folder_paths = importlib.import_module("folder_paths")
    from utils.extra_config import load_extra_path_config
    local_config = comfy_directory / "extra_model_paths.yaml"
    configurations = ([local_config] if local_config.is_file() else []) + list(
        extra_configs if extra_configs is not None else desktop_configs())
    for configuration in dict.fromkeys(Path(value).resolve() for value in configurations):
        if not configuration.is_file():
            raise ValueError("Missing model-path configuration: " + str(configuration))
        load_extra_path_config(str(configuration))
    paths = [Path(value) for value in folder_paths.get_folder_paths("upscale_models")]
    local_models = comfy_directory / "models" / "upscale_models"
    return list(dict.fromkeys(paths + [local_models]))


def checked_model(locations):
    for directory in locations:
        if not directory.is_dir():
            continue
        for path in directory.rglob(MODEL):
            if path.is_file():
                if path.stat().st_size != MODEL_BYTES or digest(path) != MODEL_SHA256:
                    raise ValueError("An existing enhancement model failed verification: " + str(path)
                                     + ". Move it aside before running setup again.")
                return path
    return None


def install(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / MODEL
    if destination.exists():
        raise ValueError("The destination already exists; setup will not overwrite it.")
    temporary = destination.with_name(MODEL + "." + uuid.uuid4().hex + ".part")
    try:
        with requests.get(MODEL_URL, stream=True, timeout=(30, 120)) as response:
            response.raise_for_status()
            with temporary.open("xb") as output:
                shutil.copyfileobj(response.raw, output)
        if temporary.stat().st_size != MODEL_BYTES or digest(temporary) != MODEL_SHA256:
            raise ValueError("The downloaded enhancement model failed verification.")
        if destination.exists():
            raise ValueError("A model appeared during setup; it has not been overwritten.")
        # Atomic creation on the same volume; never replace an existing file.
        os.link(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comfy-directory", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--models-directory", type=Path, help="Optional shared models root.")
    parser.add_argument("--extra-model-paths-config", action="append", type=Path)
    parser.add_argument("--check", action="store_true", help="Verify the model without downloading.")
    args = parser.parse_args(argv)
    locations = model_directories(args.comfy_directory, args.models_directory, args.extra_model_paths_config)
    found = checked_model(locations)
    print("H3 enhancement model: " + ("verified" if found else "missing"))
    print("Install VideoHelperSuite through Comfy Manager if its native nodes are missing:")
    print("https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite")
    print("Separate model by Philip Hofmann, CC BY 4.0; weights are not bundled with Zura Nodes.")
    if args.check:
        return 0 if found else 1
    if not found:
        print("Downloading and verifying the 34 MB enhancement model.")
        install(locations[0])
    print("Ready. Restart ComfyUI after its current jobs finish to refresh model choices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
