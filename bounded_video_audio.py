"""File VIDEO/audio IO without full RGB batches or lossy soundtrack codecs.

The original compressed video and its active native trim remain intact.
Audio is timeline-normalised once, written as exact PCM float32, and verified
before atomic publication. This module neither runs models nor registers nodes.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
import os
from pathlib import Path
import uuid

import av
import numpy as np
import torch


def file_digest(path, interrupt=lambda: None):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            interrupt()
            digest.update(block)
    return digest.hexdigest()


def identity(path):
    value = Path(path).stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def verify_file(path, stamp, digest, interrupt=lambda: None):
    if identity(path) != stamp or file_digest(path, interrupt) != digest or identity(path) != stamp:
        raise ValueError("The selected source changed during bounded verification.")


@dataclass(frozen=True)
class VideoTimeline:
    path: Path
    start: Fraction
    duration: Fraction
    frames: int
    width: int
    height: int
    total_frames: int
    fps: Fraction = Fraction(24)


def _native_path(video):
    from comfy_api.latest import InputImpl
    if not isinstance(video, InputImpl.VideoFromFile):
        raise ValueError("Bounded audio requires a native file-backed VIDEO.")
    source = video.get_stream_source()
    if not isinstance(source, (str, os.PathLike)):
        raise ValueError("Bounded audio requires a local VIDEO file, not a memory buffer.")
    path = Path(source).resolve(strict=True)
    if not path.is_file():
        raise ValueError("The selected VIDEO file is unavailable.")
    return path


def _aligned(value, label):
    try:
        seconds = Fraction(str(value))
    except (ValueError, TypeError, ZeroDivisionError) as error:
        raise ValueError("The native VIDEO trim is invalid.") from error
    frames = seconds * 24
    index = round(frames)
    if seconds < 0 or abs(frames - index) > Fraction(1, 1_000_000):
        raise ValueError(label + " must be non-negative and frame-aligned at 24 fps.")
    return Fraction(index, 24)


def inspect_video(video, interrupt=lambda: None):
    """Count/validate decoded timestamps; retain no RGB frames."""
    path = _native_path(video)
    trim_start, trim_duration = video.get_active_trim_window()
    start, requested = _aligned(trim_start, "Trim start"), _aligned(trim_duration, "Trim duration")
    if start > 86400:
        raise ValueError("The selected trim starts beyond the supported timeline.")
    with av.open(str(path)) as container:
        if len(container.streams.video) != 1:
            raise ValueError("Bounded VIDEO IO requires exactly one video stream.")
        stream = container.streams.video[0]
        if stream.average_rate != 24 or not stream.time_base:
            raise ValueError("Prepare the selected video at constant 24 fps.")
        raster = int(stream.width), int(stream.height)
        if tuple(video.get_dimensions()) != raster:
            raise ValueError("Bake native spatial cropping before bounded audio attachment.")
        total = 0
        for frame in container.decode(stream):
            interrupt()
            if frame.rotation or (frame.width, frame.height) != raster or frame.pts is None:
                raise ValueError("Bake rotation or raster changes before bounded VIDEO IO.")
            if Fraction(frame.pts) * frame.time_base != Fraction(total, 24):
                raise ValueError("The VIDEO has missing, duplicate or variable-rate presentation timestamps.")
            total += 1
    count = total - int(start * 24) if not requested else int(requested * 24)
    if count < 1 or int(start * 24) + count > total:
        raise ValueError("The selected native trim exceeds the real video timeline.")
    return VideoTimeline(path, start, Fraction(count, 24), count, *raster, total)


def iter_native_frames(video, timeline=None, interrupt=lambda: None):
    """Replicate native Comfy RGB conversion one frame at a time.

    Float GBR conversion is essential: rgb24 rounding would change approved
    source tensors. The native alignment-pad fix is preserved for narrow widths.
    Cropped/rotated inputs are rejected by inspect_video instead of approximated.
    """
    info = timeline or inspect_video(video, interrupt)
    with av.open(str(info.path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        start = int(info.start / stream.time_base)
        if start:
            container.seek(start, stream=stream, backward=True, any_frame=False)
        count, graph = 0, None
        for frame in container.decode(stream):
            interrupt()
            time = Fraction(frame.pts) * frame.time_base
            if time < info.start:
                continue
            if time >= info.start + info.duration:
                break
            if time != info.start + Fraction(count, 24):
                raise ValueError("The selected video changed its frame timeline during comparison.")
            if frame.rotation or (frame.width, frame.height) != (info.width, info.height):
                raise ValueError("The selected video changed its raster during comparison.")
            if frame.format.name in ("yuvj420p", "yuvj422p", "yuvj444p", "rgb24"):
                rgb = torch.from_numpy(frame.to_ndarray(format="rgb24")).float() / 255.0
            else:
                if any(component.is_alpha for component in frame.format.components):
                    raise ValueError("Bake alpha before bounded Wan source comparison.")
                if frame.width % 32:
                    if graph is None:
                        width = ((frame.width + 31) // 32) * 32
                        height = ((frame.height + 31) // 32) * 32
                        g = av.filter.Graph()
                        source = g.add_buffer(width=frame.width, height=frame.height,
                            format=frame.format.name, time_base=stream.time_base)
                        pad = g.add("pad", f"{width}:{height}:0:0")
                        smear = g.add("fillborders", f"left=0:right={width-frame.width}:top=0:bottom={height-frame.height}:mode=smear")
                        sink = g.add("buffersink")
                        source.link_to(pad); pad.link_to(smear); smear.link_to(sink)
                        g.configure()
                        graph = source, sink
                    graph[0].push(frame)
                    data = np.ascontiguousarray(graph[1].pull().to_ndarray(format="gbrpf32le")[:frame.height, :frame.width])
                else:
                    data = frame.to_ndarray(format="gbrpf32le")
                rgb = torch.from_numpy(data)
            yield count, rgb
            count += 1
        if count != info.frames:
            raise ValueError("The selected video ended before its reviewed frame count.")


def audio_signature(audio):
    """Exact existing Wan speech signature, including planar channel order."""
    wave = audio["waveform"].detach().cpu().float().contiguous()
    rate = int(audio["sample_rate"])
    if wave.ndim != 3 or wave.shape[0] != 1 or wave.shape[1] not in (1, 2):
        raise ValueError("Choose one mono or stereo speech track.")
    if not 1 <= rate <= 192000 or not torch.isfinite(wave).all():
        raise ValueError("Choose a valid reference speech track.")
    return {"sha": hashlib.sha256(wave.numpy().tobytes()).hexdigest(), "sample_rate": rate,
            "channels": int(wave.shape[1]), "samples": int(wave.shape[-1])}


def fit_selected_audio(audio, seconds, start=0, interrupt=lambda: None):
    """Apply selected reference offset once, then exact legacy crop/tail pad."""
    if not math.isfinite(float(seconds)) or not 0 < float(seconds) <= 30:
        raise ValueError("Bounded selected audio currently supports clips up to 30 seconds.")
    if audio is None:
        if start:
            raise ValueError("An audio offset requires a separate reference track.")
        return {"sample_rate": 48000, "waveform": torch.zeros(1, 2, round(float(seconds) * 48000))}
    original = audio["waveform"]
    rate = int(audio["sample_rate"])
    if (not isinstance(original, torch.Tensor) or original.ndim != 3 or original.shape[0] != 1 or
            original.shape[1] not in (1, 2) or not 1 <= rate <= 192000):
        raise ValueError("Choose one valid mono or stereo reference track.")
    if not math.isfinite(float(start)) or start < 0 or start * rate >= original.shape[-1]:
        raise ValueError("The audio start must be within the reference track.")
    samples = round(float(seconds) * rate)
    first = round(start * rate)
    # Legacy fit_audio rejects invalid values anywhere in the post-offset
    # reference tail. Retain that invariant without copying/hashing the whole
    # possibly long reference track into another contiguous CPU allocation.
    for position in range(first, original.shape[-1], 65536):
        interrupt()
        block = original[..., position:position + 65536].detach().cpu().float()
        if not torch.isfinite(block).all():
            raise ValueError("Choose a finite reference audio track.")
    wave = original[..., first:first + samples].detach().cpu().float()
    selected = {"sample_rate": rate, "waveform": torch.nn.functional.pad(wave, (0, max(0, samples-wave.shape[-1])))}
    audio_signature(selected)
    return selected


def decode_selected_audio(video, timeline=None, interrupt=lambda: None):
    """Decode AUDIO alone onto its real timestamp timeline, retaining no RGB."""
    info = timeline or inspect_video(video, interrupt)
    if info.duration > 30:
        raise ValueError("Bounded selected audio currently supports clips up to 30 seconds.")
    with av.open(str(info.path)) as container:
        stream = next((s for s in reversed(container.streams.audio) if s.codec_context is not None), None)
        if stream is None:
            return None
        rate, channels = stream.codec_context.sample_rate, stream.codec_context.channels
        if not 1 <= rate <= 192000 or channels not in (1, 2):
            raise ValueError("The selected soundtrack must have a known mono/stereo sample rate.")
        size = round(float(info.duration) * rate)
        wave = np.zeros((channels, size), dtype=np.float32)
        occupied = 0
        resampler = av.AudioResampler(format="fltp", rate=rate, layout="mono" if channels == 1 else "stereo")
        if info.start:
            container.seek(int(info.start / stream.time_base), stream=stream, backward=True, any_frame=False)
        # Decode audio packets only. Timestamps retain initial delay and tail
        # silence, instead of collapsing gaps as get_components historically did.
        done = False
        for packet in container.demux(stream):
            interrupt()
            for decoded in packet.decode():
                for frame in resampler.resample(decoded):
                    if frame.pts is None or not frame.time_base:
                        raise ValueError("The selected soundtrack lacks exact audio timestamps.")
                    position = round((Fraction(frame.pts) * frame.time_base - info.start) * rate)
                    if position >= size:
                        done = True
                        break
                    lo, hi = max(0, position), min(size, position + frame.samples)
                    if lo >= hi:
                        continue
                    if lo < occupied:
                        raise ValueError("The selected soundtrack contains overlapping sample timestamps.")
                    data = frame.to_ndarray()
                    wave[:, lo:hi] = data[:, lo-position:hi-position]
                    occupied = hi
                if done:
                    break
            if done:
                break
        result = {"waveform": torch.from_numpy(wave)[None], "sample_rate": rate}
        audio_signature(result)
        return result


def _directory(root, name):
    root = Path(root).resolve(strict=True)
    directory = root / "genj" / name
    if not directory.resolve().is_relative_to(root):
        raise ValueError("The audio output directory leaves its configured root.")
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve(strict=True).is_relative_to(root):
        raise ValueError("The audio output directory leaves its configured root.")
    return directory.resolve(strict=True)


def _audio_packets(stream, audio, prefix, interrupt, timestamp_offset=0):
    wave, rate = audio["waveform"][0], audio["sample_rate"]
    total = prefix + wave.shape[-1]
    for start in range(0, total, 4096):
        interrupt()
        count = min(4096, total - start)
        values = np.zeros((count, wave.shape[0]), dtype=np.float32)
        lo, hi = max(start, prefix), min(start + count, total)
        if lo < hi:
            values[lo-start:hi-start] = wave[:, lo-prefix:hi-prefix].numpy().T
        frame = av.AudioFrame.from_ndarray(values.reshape(1, -1), format="flt",
                                          layout="mono" if wave.shape[0] == 1 else "stereo")
        frame.sample_rate, frame.pts, frame.time_base = rate, start + timestamp_offset, Fraction(1, rate)
        yield from stream.encode(frame)
    yield from stream.encode()


def _packet_signature(path, interrupt=lambda: None):
    digest = hashlib.sha256()
    count = 0
    with av.open(str(path)) as container:
        if len(container.streams.video) != 1:
            raise ValueError("The remuxed video stream count changed.")
        for packet in container.demux(container.streams.video[0]):
            interrupt()
            if packet.dts is None:
                continue
            times = tuple(str(Fraction(value) * packet.time_base) if value is not None else None
                          for value in (packet.pts, packet.dts, packet.duration))
            digest.update(repr((times, packet.is_keyframe, packet.size)).encode())
            digest.update(bytes(packet))
            count += 1
    return count, digest.hexdigest()


def attach_selected_audio(video, clip_details, output_root, audio=None, audio_start_seconds=0,
                          interrupt=lambda: None):
    """Return actual native VIDEO + details; publish only exact validated files."""
    from comfy_api.latest import InputImpl
    info = inspect_video(video, interrupt)
    active_duration = float(video.get_active_trim_window()[1])
    details = dict(clip_details)
    supplied_duration = float(details.get("duration", -1))
    if (details.get("frames") != info.frames or details.get("fps") != 24 or
            not math.isfinite(supplied_duration) or abs(supplied_duration - float(info.duration)) > 1e-9 or
            details.get("width", info.width) != info.width or details.get("height", info.height) != info.height):
        raise ValueError("The selected clip metadata differs from its actual native VIDEO.")
    stamp, source_sha = identity(info.path), file_digest(info.path, interrupt)
    selected = (fit_selected_audio(audio, float(info.duration), audio_start_seconds, interrupt) if audio is not None else
                fit_selected_audio(decode_selected_audio(video, info, interrupt), float(info.duration), interrupt=interrupt))
    if audio is None and audio_start_seconds:
        raise ValueError("An audio offset requires a separate reference track.")
    signature = audio_signature(selected)
    if active_duration and int(active_duration * selected["sample_rate"]) != signature["samples"]:
        raise ValueError("This explicit native trim cannot retain the exact rounded audio sample count. Bake the selected clip first.")
    recipe = repr((source_sha, str(info.start), str(info.duration), signature)).encode()
    key = hashlib.sha256(recipe).hexdigest()
    directory = _directory(output_root, "reference_video")
    name = key + "_" + uuid.uuid4().hex
    partial, final = directory / (name + ".partial.mov"), directory / (name + ".mov")
    audio_partial = audio_final = None
    try:
        # Keep full encoded video dependencies, including leading B-frame DTS;
        # only the native active trim determines selected presentation frames.
        with av.open(str(info.path)) as source, av.open(str(partial), "w", format="mov",
                options={"avoid_negative_ts": "disabled"}) as output:
            original = source.streams.video[0]
            if original.codec_context.name != "h264":
                raise ValueError("Bounded lossless audio attachment currently requires a prepared H.264 clip.")
            vout = output.add_stream_from_template(original)
            aout = output.add_stream("pcm_f32le", rate=selected["sample_rate"])
            aout.layout = "mono" if signature["channels"] == 1 else "stereo"
            aout.format = "flt"
            vout.time_base = original.time_base
            # Delay the PCM track to the active trim rather than encoding
            # leading silence packets. Native get_components floors a float
            # trim offset inside a packet and can retain one prefix sample.
            # An exact selected-track start avoids that native rounding bug.
            audio_offset = round(info.start * selected["sample_rate"])
            video_packets = (packet for packet in source.demux(original) if packet.dts is not None)
            audio_packets = iter(_audio_packets(aout, selected, 0, interrupt, audio_offset))
            vp, ap = next(video_packets, None), next(audio_packets, None)
            while vp is not None or ap is not None:
                interrupt()
                if ap is None or (vp is not None and Fraction(vp.dts)*vp.time_base <= Fraction(ap.dts)*ap.time_base):
                    vp.stream = vout
                    output.mux(vp)
                    vp = next(video_packets, None)
                else:
                    output.mux(ap)
                    ap = next(audio_packets, None)
        result = InputImpl.VideoFromFile(str(partial), start_time=float(info.start), duration=active_duration)
        actual_info = inspect_video(result, interrupt)
        if actual_info != VideoTimeline(partial.resolve(), info.start, info.duration, info.frames,
                                        info.width, info.height, info.total_frames):
            raise ValueError("The lossless remux changed the selected VIDEO timeline.")
        if _packet_signature(info.path, interrupt) != _packet_signature(partial, interrupt):
            raise ValueError("The lossless remux changed encoded video bytes or packet timing.")
        if audio_signature(decode_selected_audio(result, actual_info, interrupt)) != signature:
            raise ValueError("PCM audio readback differs from the exact selected soundtrack.")
        if audio is not None:
            audio_dir = _directory(output_root, "reference_audio")
            audio_partial = audio_dir / (name + ".partial.wav")
            audio_final = audio_dir / (name + ".wav")
            with av.open(str(audio_partial), "w", format="wav") as output:
                stream = output.add_stream("pcm_f32le", rate=selected["sample_rate"])
                stream.layout = "mono" if signature["channels"] == 1 else "stereo"
                stream.format = "flt"
                for packet in _audio_packets(stream, selected, 0, interrupt):
                    output.mux(packet)
            # Read only AUDIO and verify its exact PCM value/shape/rate.
            with av.open(str(audio_partial)) as source:
                values = []
                resampler = av.AudioResampler(format="fltp")
                for frame in source.decode(audio=0):
                    interrupt()
                    values.extend(f.to_ndarray() for f in resampler.resample(frame))
                wave = torch.from_numpy(np.concatenate(values, axis=1))[None]
            if audio_signature({"waveform": wave, "sample_rate": selected["sample_rate"]}) != signature:
                raise ValueError("The final reference WAV differs from selected PCM audio.")
        verify_file(info.path, stamp, source_sha, interrupt)
        interrupt()
        approved_root = Path(output_root).resolve(strict=True)
        if (directory.resolve(strict=True) != directory or not directory.is_relative_to(approved_root) or
                (audio_final is not None and (audio_final.parent.resolve(strict=True) != audio_final.parent or
                    not audio_final.parent.is_relative_to(approved_root)))):
            raise ValueError("The audio output directory changed before publication.")
        if audio_final is not None:
            os.replace(audio_partial, audio_final)
        os.replace(partial, final)
        details["selected_path"] = str(final)
        details["bounded_audio"] = {"version": 1, "source_sha": source_sha, "sha": file_digest(final, interrupt),
            "selected_audio": signature, "trim_start": float(info.start), "trim_duration": float(info.duration)}
        details["bounded_audio"]["active_trim_duration"] = active_duration
        if audio_final is not None:
            details.update(audio_source=str(audio_final), audio_hash=file_digest(audio_final, interrupt),
                           audio_mode="reference", has_audio=True)
        return InputImpl.VideoFromFile(str(final), start_time=float(info.start), duration=active_duration), details
    except BaseException:
        partial.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        if audio_partial is not None:
            audio_partial.unlink(missing_ok=True)
        if audio_final is not None:
            audio_final.unlink(missing_ok=True)
        raise


class ZuraApplyBoundedReferenceAudio:
    CATEGORY = "Zura/Artist Studio"
    FUNCTION = "apply"
    RETURN_TYPES = ("VIDEO", "GENJ_CLIP")
    RETURN_NAMES = ("video_with_reference_audio", "clip_details")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"video": ("VIDEO",), "clip_details": ("GENJ_CLIP",),
                "audio_start_seconds": ("FLOAT", {"default": 0, "min": 0, "max": 86400, "step": .1})},
                "optional": {"audio": ("AUDIO",)}}

    def apply(self, video, clip_details, audio_start_seconds=0, audio=None):
        import folder_paths
        from comfy.model_management import throw_exception_if_processing_interrupted
        return attach_selected_audio(video, clip_details, folder_paths.get_output_directory(), audio,
                                     audio_start_seconds, throw_exception_if_processing_interrupted)
