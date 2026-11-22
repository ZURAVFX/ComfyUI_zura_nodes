"""Frame-indexed SDR plate preparation and source-resolution relighting."""

from contextlib import ExitStack, contextmanager
from fractions import Fraction
from pathlib import Path

import av
import cv2
import numpy as np

STILLS = {".png", ".bmp", ".tif", ".tiff", ".jpg", ".jpeg", ".webp"}


def input_path(name):
    import folder_paths

    root = Path(folder_paths.get_input_directory()).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Choose a file in the ComfyUI input directory.")
    return path


def opened(path):
    return av.open(
        str(path),
        options={
            "protocol_whitelist": "file,pipe",
            "format_whitelist": "mov,matroska,webm,avi,mxf,mp4,mpegts,gif,image2,png_pipe,jpeg_pipe,tiff_pipe,bmp_pipe,webp_pipe",
        },
    )


def source_info(path):
    with opened(path) as container:
        stream = container.streams.video[0]
        count = stream.frames or sum(1 for _ in container.decode(stream))
        if stream.codec_context.color_trc in (16, 18):
            raise ValueError("Convert HDR footage to an SDR working plate for H3.")
        if stream.sample_aspect_ratio not in (None, 0, 1):
            raise ValueError("Convert anamorphic footage to square pixels before generating.")
        return stream.width, stream.height, count, stream.average_rate or Fraction(24)


@contextmanager
def paired_frames(source, matte, start=0, count=None):
    with ExitStack() as stack:
        plate = stack.enter_context(opened(source))
        alpha = stack.enter_context(opened(matte))
        source_frames = plate.decode(video=0)
        masks = alpha.decode(video=0)
        still = next(masks) if matte.suffix.lower() in STILLS else None

        def frames():
            # Character Replacement pairs an equal-length matte by source frame index.
            for index, frame in enumerate(source_frames):
                mask = still or next(masks, None)
                if mask is None or (frame.width, frame.height) != (mask.width, mask.height):
                    raise ValueError(
                        "Use a matte matching every source frame and its pixel dimensions."
                    )
                if index >= start:
                    if count is not None and index >= start + count:
                        return
                    yield frame, mask
            if still is None and next(masks, None) is not None:
                raise ValueError("The animated matte has more frames than the source.")

        yield frames()


def rgb(frame):
    return frame.to_ndarray(format="rgb48le").astype(np.float32) / 65535.0


def alpha_image(frame, channel="luma"):
    from .character_mask import selection_luminance

    if channel == "alpha":
        if not any(component.is_alpha for component in frame.format.components):
            raise ValueError("This matte has no embedded alpha. Choose Black and white.")
        return frame.to_ndarray(format="rgba64le")[:, :, 3].astype(np.float32) / 65535
    if channel != "luma":
        raise ValueError("Choose Black and white or Embedded alpha.")
    # Decoding RGB expands video-range black and white, including limited-range mattes.
    return selection_luminance(rgb(frame))


def canvas(w, h, side):
    scale = min(1.0, side / max(w, h))
    fw, fh = max(1, round(w * scale)), max(1, round(h * scale))
    return fw, fh, ((fw + 31) // 32) * 32, ((fh + 31) // 32) * 32


def fit(image, dims):
    fw, fh, w, h = dims
    resized = cv2.resize(image, (fw, fh), interpolation=cv2.INTER_AREA)
    x, y = (w - fw) // 2, (h - fh) // 2
    return cv2.copyMakeBorder(resized, y, h - fh - y, x, w - fw - x, cv2.BORDER_REPLICATE)
