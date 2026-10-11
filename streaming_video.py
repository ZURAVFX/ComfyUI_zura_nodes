"""Incremental, atomic video delivery. No inference or whole-clip tensors."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import os
from pathlib import Path
import re
import uuid


def confined_directory(output_root):
    root = Path(output_root).resolve(strict=True)
    directory = root / "genj" / "wan_streams"
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Video output directory leaves the Comfy output folder.")
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve(strict=True).is_relative_to(root):
        raise ValueError("Video output directory leaves the Comfy output folder.")
    return directory.resolve(strict=True)


def file_sha256(path, interrupt=None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            if interrupt is not None:
                interrupt()
            digest.update(block)
    return digest.hexdigest()


def verify_preparation_file(path, provenance, interrupt=None):
    """Recheck bytes as well as stamps at both generation boundaries."""
    path = Path(path)
    expected_stamp = provenance["size"], provenance["mtime_ns"]
    before = path.stat()
    if (before.st_size, before.st_mtime_ns) != expected_stamp:
        raise ValueError("Wan preparation changed after memory-map validation.")
    sha = file_sha256(path, interrupt=interrupt)
    after = path.stat()
    if sha != provenance["sha256"] or (after.st_size, after.st_mtime_ns) != expected_stamp:
        raise ValueError("Wan preparation bytes changed after memory-map validation.")


class AtomicVideoWriter:
    """Write one owned frame at a time, publish only a verified complete MP4.

    H.264 CRF 18 is an explicit delivery encode, not a lossless tensor cache.
    Source preparation remains exact FP32. No audio is encoded here: the
    existing soundtrack node restores the global approved audio once.
    """
    def __init__(self, output_root, key, count, width, height, fps=24, interrupt=None):
        import av
        if not isinstance(key, str) or not re.fullmatch(r"[a-f0-9]{64}", key):
            raise ValueError("Video delivery key must be a SHA-256 digest.")
        if any(type(value) is not int or value < 1 for value in (count, width, height)):
            raise ValueError("Video frame count and raster must be positive integers.")
        if width % 2 or height % 2 or fps != 24:
            raise ValueError("Wan streaming requires an even raster at exactly 24 fps.")
        self.directory = confined_directory(output_root)
        identity = key + "_" + uuid.uuid4().hex
        self.path = self.directory / (identity + ".mp4")
        self.temporary = self.directory / (identity + ".partial.mp4")
        self.expected, self.width, self.height = count, width, height
        self.fps, self.count = Fraction(24), 0
        self.interrupt = interrupt or (lambda: None)
        self.container = None
        self.complete = False
        try:
            self.container = av.open(str(self.temporary), mode="w", format="mp4")
            self.stream = self.container.add_stream("libx264", rate=self.fps)
            self.stream.width, self.stream.height = width, height
            self.stream.pix_fmt = "yuv420p"
            self.stream.time_base = Fraction(1, 24)
            self.stream.options = {"crf": "18", "preset": "medium"}
        except BaseException:
            self.abort()
            raise

    def write(self, images, start):
        import av
        import torch
        if self.complete or self.container is None:
            raise RuntimeError("The video writer is closed.")
        if type(start) is not int or start != self.count:
            raise ValueError("Video spans must own each timestamp exactly once.")
        if (not isinstance(images, torch.Tensor) or images.device.type != "cpu" or
                images.ndim != 4 or tuple(images.shape[1:]) != (self.height, self.width, 3) or
                len(images) < 1 or not images.is_floating_point() or
                self.count + len(images) > self.expected):
            raise ValueError("Decoded span has an invalid frame count, raster or device.")
        for image in images:
            self.interrupt()
            if not torch.isfinite(image).all():
                raise ValueError("Decoded video contains invalid pixels.")
            pixels = image.clamp(0, 1).mul(255).round().to(torch.uint8).numpy()
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts, frame.time_base = self.count, Fraction(1, 24)
            for packet in self.stream.encode(frame):
                self.container.mux(packet)
            self.count += 1

    def finish(self, before_publish=None):
        import av
        self.interrupt()
        if self.container is None or self.complete or self.count != self.expected:
            raise ValueError("Cannot publish an incomplete video.")
        for packet in self.stream.encode():
            self.container.mux(packet)
        self.container.close()
        self.container = None
        # Read back incrementally; encoder buffering or timestamp corruption
        # must not turn a partial clip into a successful production receipt.
        actual = 0
        with av.open(str(self.temporary)) as container:
            if len(container.streams.video) != 1 or len(container.streams.audio) != 0:
                raise ValueError("Streaming base video has unexpected tracks.")
            stream = container.streams.video[0]
            if stream.average_rate != self.fps:
                raise ValueError("Encoded video frame rate differs from 24 fps.")
            for frame in container.decode(stream):
                self.interrupt()
                if (frame.width, frame.height) != (self.width, self.height):
                    raise ValueError("Encoded video raster changed.")
                if frame.pts is None or frame.pts * frame.time_base != Fraction(actual, 24):
                    raise ValueError("Encoded video timestamps are not contiguous.")
                actual += 1
        if actual != self.expected:
            raise ValueError("Encoded video frame count differs from the approved timeline.")
        sha = file_sha256(self.temporary)
        self.interrupt()
        if before_publish is not None:
            before_publish()
        self.interrupt()
        os.replace(self.temporary, self.path)
        self.complete = True
        return {"path": str(self.path), "sha256": sha, "frames": actual,
                "fps": 24, "width": self.width, "height": self.height,
                "audio_tracks": 0, "codec": "h264", "crf": 18}

    def abort(self):
        try:
            if self.container is not None:
                self.container.close()
        finally:
            self.container = None
            # Both names were generated here, never supplied by a caller.
            if self.temporary.parent == self.directory and self.temporary.exists():
                self.temporary.unlink()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if not self.complete:
            self.abort()


def file_video(path):
    """A streaming node promises a real file-backed native VIDEO, no fallback."""
    from comfy_api.latest import InputImpl
    return InputImpl.VideoFromFile(str(path))
