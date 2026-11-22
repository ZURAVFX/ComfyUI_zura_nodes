"""Reuse approved Studio selection assets and show the exact matte sent to H3."""

from pathlib import Path
from tempfile import TemporaryDirectory
import shutil
import cv2
import numpy as np

from .switch_x_media import alpha_image, input_path, paired_frames, source_info


def reviewed_inputs(project_id):
    import folder_paths
    from . import verify_review, digest_file
    from .studio import Store, assert_approved

    project = Store().load(project_id)
    if project.get("config", {}).get("workflow_mode") != "swap":
        raise ValueError("Select a Character Replacement project with an approved mask.")
    assert_approved(project)
    review = project["review"]
    directory, manifest = verify_review(review)
    genuine = "performer_mask.mp4" in manifest["files"]
    matte = "performer_mask.mp4" if genuine else "mask.mp4"
    input_root = Path(folder_paths.get_input_directory()).resolve()
    target = input_root / "switch_x_reviews" / review
    target.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=target) as temp:
        for name in ("source.mp4", matte):
            dst = target / name
            if not dst.exists() or digest_file(dst) != manifest["files"][name]:
                staged = Path(temp) / name
                shutil.copyfile(directory / name, staged)
                if digest_file(staged) != manifest["files"][name]:
                    raise ValueError("The reviewed clip changed during import.")
                staged.replace(dst)
    inverted = project["config"].get("preserve_people") and not genuine
    return {
        "source": (target / "source.mp4").relative_to(input_root).as_posix(),
        "matte": (target / matte).relative_to(input_root).as_posix(),
        "whiteMeans": "replace" if inverted else "keep",
        "frames": manifest["clip"]["frames"],
        "fps": manifest["clip"]["fps"],
    }


def preview_selection(config):
    source, matte = input_path(config["source"]), input_path(config["matte"])
    _, _, count, _ = source_info(source)
    index = int(config.get("frame", 0))
    if not 0 <= index < count:
        raise ValueError("Choose a frame inside the shot.")
    with paired_frames(source, matte, index, 1) as frames:
        pair = next(frames, None)
        if pair is None:
            raise ValueError("The reviewed source frame could not be decoded.")
        frame, mask = pair
        image = frame.to_ndarray(format="rgb24").astype(np.float32)
        alpha = alpha_image(mask, config.get("maskChannel", "luma"))
        tint = np.float32(
            [202, 255, 0] if config.get("whiteMeans", "keep") == "keep" else [255, 129, 49]
        )
        overlay = image + (tint - image) * (0.50 * alpha[..., None])
        w = min(1280, frame.width)
        h = max(1, round(w * frame.height / frame.width))
        pixels = cv2.resize(overlay, (w, h), interpolation=cv2.INTER_AREA)
        ok, jpeg = cv2.imencode(
            ".jpg", np.rint(pixels[..., ::-1]).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 92]
        )
        if not ok:
            raise ValueError("Could not display the selection.")
        return jpeg.tobytes()
