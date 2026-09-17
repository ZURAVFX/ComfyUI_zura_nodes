"""Zura nodes · Zura Wan 2.2 Looped Chunks Sampler.

Renders the prepared driving clip in 4n+1-frame windows using the native
``WanAnimateToVideo`` continuation mechanism: every chunk after a shot's first
is handed the predecessor's real output frames as ``continue_motion``, samples a
window that starts on those frames, and cross-fades its own rendition of them
against the predecessor's pixels.  The model therefore continues real motion
instead of inventing a fresh take that has to be faded in.  Continuation resets
at detected or manual cuts, so a new shot begins unconditioned and the cut stays
a cut.  Original audio and exact clip timing are assembled into a real
``VIDEO`` output, so no separate finish node is needed.
"""
from __future__ import annotations

import json
import logging
import math
import time

from .planning import ShotChunk, hold_last, plan_chunks, sampling_frames, parse_cut_frames, detect_cuts, validate_plan
from .video import video_output


def _send_wan22_progress(**payload):
    """Send optional UI progress without making the node depend on a server."""
    try:
        from server import PromptServer
        server = PromptServer.instance
        if server is not None:
            server.send_sync("zura_progress", payload)
    except Exception:
        # Unit tests and API-only Comfy workers may not have a PromptServer.
        pass


def _blend_weights(count: int, device="cpu"):
    """Hann-window cross-fade ramp: exactly 0 at the start, 1 at the end.

    The zone it weights holds two renditions of the same absolute frames: the
    predecessor's real pixels (weight 0) and this chunk's rendition of them,
    generated with those very pixels given as ``continue_motion`` (weight 1).
    The cosine's derivative vanishes at both ends, so the transition into and
    out of the zone is flat: the zone's first frame is exactly the neighbour's
    frame and its last frame is exactly this chunk's own continuation, which
    the next frame continues in the same pass.  Nothing steps anywhere; any
    residual difference is spread across the whole zone instead.  A
    half-sample-offset ramp would leave a small snap at the zone edges; this
    form does not.
    """
    import torch
    if count <= 1:
        return torch.ones((count, 1, 1, 1), device=device)
    positions = torch.arange(count, device=device, dtype=torch.float32)
    return (0.5 - 0.5 * torch.cos(math.pi * positions / (count - 1))).view(-1, 1, 1, 1)


class ZuraWan22LoopedChunksSampler:
    CATEGORY = "Zura"
    FUNCTION = "render"
    RETURN_TYPES = ("IMAGE", "VIDEO", "STRING")
    RETURN_NAMES = ("images", "video", "receipt")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",), "clip": ("CLIP",), "vae": ("VAE",), "clip_vision": ("CLIP_VISION",),
            "reference_image": ("IMAGE",),
            "footage": ("ZURA_FOOTAGE", {"tooltip": "Prepared footage from the Zura Mask node."}),
            "prompt": ("STRING", {"multiline": True, "default": "Preserve the character appearance and scene."}),
            "negative_prompt": ("STRING", {"multiline": True, "default": "flicker, warped hands, extra limbs, identity drift"}),
            "steps": ("INT", {"default": 6, "min": 1, "max": 200,
                              "tooltip": "Sampler steps. The Turbo Switch node overrides this when connected."}),
            "cfg": ("FLOAT", {"default": 1.0, "min": 0, "max": 30, "step": 0.1,
                              "tooltip": "Guidance scale. The Turbo Switch node overrides this when connected."}),
            "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "chunk_frames": ("INT", {"default": 41, "min": 5, "max": 409, "step": 4,
                                      "tooltip": "Frames rendered per loop, in one pass of the sampler. "
                                                 "Must be 4n+1 and at least twice the continuation frames."}),
            "overlap_frames": ("INT", {"default": 5, "min": 5, "max": 405, "step": 4,
                                        "tooltip": "Continuation frames: the real tail of the previous chunk that the "
                                                   "next chunk is told to carry on from, then cross-fades its own take "
                                                   "onto. Deeper context holds motion tighter through fast movement "
                                                   "(9 helps on quick dance); must be 4n+1."}),
            "max_side": ("INT", {"default": 1280, "min": 256, "max": 1920, "step": 32}),
            "shot_mode": (["Detect cuts", "Continuous", "Manual cuts"],
                          {"default": "Detect cuts",
                           "tooltip": "Where continuation restarts. Detect cuts (auto) and Manual cuts split the "
                                      "clip into shots: a new shot starts unconditioned, so the cut stays hard. "
                                      "Continuous treats the whole clip as a single shot."}),
            "cut_threshold": ("FLOAT", {"default": .2, "min": .01, "max": 1, "step": .01,
                                        "tooltip": "Lower values detect more cuts. Raise this if flashes or fast movements are mistaken for edits."}),
            "cut_frames": ("STRING", {"default": "", "multiline": False,
                                      "tooltip": "Manual cuts: comma-separated frame numbers where a new shot begins. At 24 fps, frame 96 is 4 seconds."}),
        }, "hidden": {"unique_id": "UNIQUE_ID"}}

    @staticmethod
    def _size(frames, max_side):
        h, w = int(frames.shape[1]), int(frames.shape[2])
        scale = min(1., float(max_side) / max(h, w))
        return max(16, round(w * scale / 16) * 16), max(16, round(h * scale / 16) * 16)

    def render(self, model, clip, vae, clip_vision, reference_image, footage, prompt,
               negative_prompt, steps=6, cfg=1.0, seed=0, chunk_frames=41, overlap_frames=5,
               max_side=1280, shot_mode="Detect cuts", cut_threshold=.2, cut_frames="", unique_id=None):
        # Fail fast on missing conditioning before importing ComfyUI internals.
        media = footage
        if not isinstance(media, dict):
            raise ValueError("Wan 2.2 requires the prepared footage payload from the Zura Mask node")
        frames = media.get("frames")
        if frames is None or int(frames.shape[0]) < 1:
            raise ValueError("Wan 2.2 requires footage frames from the Zura Mask node")
        total = int(frames.shape[0])
        if frames.ndim != 4 or int(frames.shape[-1]) != 3:
            raise ValueError("footage frames must have shape [frames,height,width,3]")
        pose, face = media.get("pose_video"), media.get("face_video")
        mask = media.get("character_mask")
        if pose is None or face is None or mask is None:
            raise ValueError("Wan 2.2 requires pose_video, face_video, and character_mask from the Zura Mask node")
        if any(not hasattr(x, "shape") or int(x.shape[0]) < total for x in (pose, face, mask)):
            raise ValueError("pose_video, face_video, and character_mask must cover all footage frames")
        if pose.ndim != 4 or face.ndim != 4 or int(pose.shape[-1]) != 3 or int(face.shape[-1]) != 3:
            raise ValueError("pose_video and face_video must have shape [frames,height,width,3]")
        if int(mask.ndim) not in (3, 4):
            raise ValueError("character_mask must have shape [frames,height,width] or [frames,height,width,1]")
        frame_size = (int(frames.shape[1]), int(frames.shape[2]))
        # Native WanAnimateToVideo upscales pose_video to the render size and
        # face_video to its own 512x512 face-crop resolution, so neither is
        # required to match the clip resolution (WanAnimatePreprocess always
        # returns face crops at 512x512 regardless of clip size).  The mask,
        # however, is combined with the frames arithmetically below and must
        # match the clip exactly.
        if tuple(mask.shape[1:3]) != frame_size:
            raise ValueError("character_mask must match the footage height and width")
        if mask.ndim == 4 and int(mask.shape[-1]) != 1:
            raise ValueError("character_mask's fourth dimension must be 1")
        import torch
        import nodes
        from comfy_extras.nodes_wan import WanAnimateToVideo

        source_bg = frames
        # Wan's background conditioning must not contain the performer pixels.
        # Keep the tensor shape intact while blacking out the masked region.
        m = mask.float()
        if m.ndim == 3:
            m = m.unsqueeze(-1)
        if m.shape[-1] != 1:
            m = m[..., :1]
        if m.max() > 1.5:
            m = m / 255.0
        source_bg = source_bg * (1.0 - m.clamp(0, 1))
        cuts = [] if shot_mode == "Continuous" else (parse_cut_frames(cut_frames, total) if shot_mode == "Manual cuts" else detect_cuts(frames, cut_threshold))
        plan = plan_chunks(total, chunk_frames, overlap_frames, cuts, continuation=True)
        validate_plan(plan, total)
        total_chunks = len(plan)
        total_shots = len({part.shot_index for part in plan})
        shot_bounds = list(zip([0] + cuts + [total], cuts + [total]))
        node_id = str(unique_id) if unique_id is not None else None
        completed_frames = 0

        def progress_event(state, **extra):
            _send_wan22_progress(state=state, node=node_id, chunks=total_chunks,
                                 completed_chunks=extra.pop("completed_chunks", 0),
                                 completed_frames=completed_frames, total_frames=total, **extra)

        progress_event("started", shot=0, shots=total_shots, chunk=0)
        width, height = self._size(frames, max_side)
        if media.get("replacement_area") in ("Whole head", "Face only"):
            prompt = "Replace only the performer's head, face and hair with the reference identity. Preserve the original body, outfit, limbs, pose and background. " + prompt
        decoded: list[torch.Tensor] = []
        # Real frames of the previous window, waiting to be both the next
        # chunk's continuation anchor and its cross-fade partner.  Cleared at
        # every shot boundary so a cut is never continued across.
        pending_blend = None
        native = WanAnimateToVideo()
        chunk_timings = []
        preparation_timings = {}
        current_shot = current_chunk = completed_chunks = 0
        try:
            def prepare(stage, operation):
                progress_event("preparing", stage=stage, stage_started_at=time.time(), elapsed_seconds=0,
                               shot=0, shots=total_shots, chunk=0)
                logging.info("Wan 2.2 preparation: %s", stage)
                started = time.monotonic()
                result = operation()
                preparation_timings[stage] = round(time.monotonic() - started, 3)
                logging.info("Wan 2.2 preparation: %s completed in %.2fs", stage, preparation_timings[stage])
                return result

            device = getattr(getattr(clip, "patcher", None), "load_device", "unknown")
            logging.info("Wan 2.2 text encoder device: %s", device)
            positive = prepare("Encoding prompt", lambda: nodes.CLIPTextEncode().encode(clip, prompt)[0])
            negative = prepare("Encoding negative prompt", lambda: nodes.CLIPTextEncode().encode(clip, negative_prompt)[0])
            clip_out = prepare("Encoding character reference", lambda: nodes.CLIPVisionEncode().encode(clip_vision, reference_image[:1], "none")[0])
            try:
                progress = __import__("comfy.utils", fromlist=["ProgressBar"]).ProgressBar(total_chunks)
            except Exception:
                progress = None
            for part in plan:
                current_shot, current_chunk = part.shot_index + 1, part.index + 1
                progress_event("chunk_started", shot=part.shot_index + 1, shots=total_shots,
                               chunk=part.index + 1, completed_chunks=part.index,
                               shot_start=shot_bounds[part.shot_index][0], shot_end=shot_bounds[part.shot_index][1])
                try:
                    __import__("comfy.model_management", fromlist=["throw_exception_if_processing_interrupted"]).throw_exception_if_processing_interrupted()
                except ImportError:
                    pass
                # Native continuation, the way Wan 2.2 Animate is designed to
                # be looped: the predecessor's real output tail is handed over
                # as ``continue_motion``, the window starts on those frames, and
                # the source conditioning (pose/face/background/mask) is aligned
                # to the same absolute frames.  The model samples the window
                # with those real pixels in its context, so the frames it emits
                # continue motion it has actually seen.
                length = sampling_frames(part)
                anchor = None
                if part.anchor_frames:
                    if pending_blend is not None:
                        anchor = pending_blend["tail"]
                        if int(anchor.shape[0]) != part.anchor_frames:
                            anchor = (anchor[-part.anchor_frames:]
                                      if int(anchor.shape[0]) > part.anchor_frames
                                      else hold_last(anchor, part.anchor_frames))
                    else:
                        # Only reachable if a plan ever anchors across a shot
                        # boundary, which it must not: render the window fresh.
                        logging.warning("Wan 2.2 loop %s: no predecessor tail to continue from",
                                        part.index + 1)
                logging.info("Wan 2.2 loop %s/%s: shot %s/%s, sampling %s frames for window %s..%s "
                             "(output %s..%s), continuing from %s real frames",
                             part.index + 1, total_chunks, part.shot_index + 1, total_shots, length,
                             part.window_start, part.window_start + part.window_count,
                             part.output_start, part.output_start + part.output_count,
                             0 if anchor is None else int(anchor.shape[0]))
                started = time.monotonic()
                wsl = slice(part.window_start, part.window_start + part.window_count)
                ppose, pface, pbg, pmask = [hold_last(x[wsl] if x is not None else None, length)
                                            for x in (pose, face, source_bg, mask)]
                result = native.execute(positive, negative, vae, width, height, length, 1,
                                        int(part.anchor_frames) or 1, 0,
                                        reference_image=reference_image,
                                        clip_vision_output=clip_out, face_video=pface, pose_video=ppose,
                                        continue_motion=anchor, background_video=pbg, character_mask=pmask)
                p, n, latent, trim_latent, trim_image, _ = result
                if int(trim_image) != int(part.anchor_frames):
                    logging.warning("Wan 2.2 loop %s: native reported trim_image=%s for %s continuation frames",
                                    part.index + 1, trim_image, part.anchor_frames)
                prepared = time.monotonic()
                sampled = nodes.common_ksampler(model, int(seed), int(steps), float(cfg), "euler", "simple", p, n, latent)[0]
                sampled_at = time.monotonic()
                sampled = dict(sampled)
                sampled["samples"] = sampled["samples"][:, :, int(trim_latent):]
                window = nodes.VAEDecodeTiled().decode(vae, sampled, tile_size=512, overlap=64, temporal_size=64, temporal_overlap=8)[0]
                # A ComfyUI graph loop drops the frames the native node reports
                # as trim_image, because in a loop they merely repeat output it
                # already emitted.  Here they are kept on purpose: they are the
                # model's own rendition of the continuation frames, and the
                # assembly below cross-fades them against the real pixels the
                # predecessor emitted, which is what removes the step at the
                # join instead of just relocating it.
                # Pad a tail-window to the planned count so the blend zone
                # always exists even when the source runs out mid-window.
                if int(window.shape[0]) < part.window_count:
                    pad = window[-1:].repeat((part.window_count - int(window.shape[0]),) + (1,) * (window.ndim - 1))
                    window = torch.cat((window, pad), dim=0)
                window = window[:part.window_count].detach().cpu()
                images = window[part.output_start - part.window_start:part.output_start - part.window_start + part.output_count]
                if int(images.shape[0]) != part.output_count:
                    raise RuntimeError("native returned an incorrect visible frame count")
                timing = {"loop": part.index + 1, "sampling_frames": length,
                          "continue_frames": int(part.anchor_frames),
                          "prepare_seconds": round(prepared - started, 3),
                          "sample_seconds": round(sampled_at - prepared, 3),
                          "decode_seconds": round(time.monotonic() - sampled_at, 3)}
                if anchor is not None:
                    # How faithfully the model reproduced the frames it was
                    # asked to continue from.  Near zero means the join is a
                    # true continuation and the cross-fade has almost nothing
                    # to hide; a large value means the chunks disagree and the
                    # continuation frames deserve raising.
                    context = int(anchor.shape[0])
                    timing["continuation_delta"] = round(float((anchor - window[:context]).abs().mean()), 5)
                    logging.info("Wan 2.2 loop %s continuation: %s frames, mean |real - rendition| %.4f",
                                 part.index + 1, context, timing["continuation_delta"])
                chunk_timings.append(timing)
                logging.info("Wan 2.2 loop %s timing: prepare %.2fs, sample %.2fs, decode %.2fs",
                             timing['loop'], timing['prepare_seconds'], timing['sample_seconds'], timing['decode_seconds'])
                completed_frames += part.output_count

                # ---- cross-faded continuation assembly ----
                # The window's first ``overlap`` frames are this chunk's own
                # rendition of the continuum it was handed: the same absolute
                # frames the predecessor emitted.  Both renditions therefore
                # agree closely by construction, and a flat-ended ramp spreads
                # whatever difference is left over the whole zone instead of
                # stepping at one frame boundary.
                if pending_blend is not None and pending_blend["frames"] > 0:
                    blend = pending_blend["frames"]
                    weights = _blend_weights(blend, device=window.device)
                    zone = pending_blend["tail"].to(window.device) * (1.0 - weights) + window[:blend] * weights
                    decoded.append(zone.cpu())
                    pending_blend = None
                # Emit only this chunk's own output span: skip the context
                # prefix (frames before output_start, already covered by the
                # predecessor's blend zone) and the blend tail (re-rendered by
                # the successor).
                context = part.output_start - part.window_start
                keep = window[context:part.window_count - part.blend_frames]
                decoded.append(keep.cpu())
                if part.blend_frames > 0:
                    pending_blend = {"tail": window[-part.blend_frames:], "frames": part.blend_frames}
                del sampled, latent, p, n, ppose, pface, pbg, pmask, window, images, result
                completed_chunks = part.index + 1
                if progress is not None:
                    progress.update(1)
                progress_event("chunk_completed", shot=part.shot_index + 1, shots=total_shots,
                               chunk=part.index + 1, completed_chunks=completed_chunks)
            output = torch.cat(decoded, dim=0)
            if int(output.shape[0]) != total:
                raise RuntimeError(f"continuation assembly produced {int(output.shape[0])} frames for a {total}-frame clip")
            receipt = {"model": "Wan 2.2 Animate", "chunks": len(plan), "cuts": cuts, "shot_mode": shot_mode,
                       "shots": [[lo, hi] for lo, hi in shot_bounds],
                       "continuation": {"frames": int(overlap_frames),
                                        "max_delta": max([t.get("continuation_delta", 0.0)
                                                          for t in chunk_timings] or [0.0])},
                       "native_inputs": {"pose_video": pose is not None, "face_video": face is not None,
                                         "background_video": True, "character_mask": True},
                       "requested_frames": total, "generated_frames": int(output.shape[0]),
                       "frame_plan": [p._asdict() for p in plan]}
            receipt['chunk_timings'] = chunk_timings
            receipt['preparation_timings'] = preparation_timings
            progress_event("completed", shot=total_shots, shots=total_shots, chunk=total_chunks,
                           completed_chunks=total_chunks)
            # Assemble the finished clip with the original audio and exact
            # timing; the audio is trimmed or silent-padded to frame count.
            info = media.get("video_info", {})
            fps = float(info.get("fps", 24))
            audio = media.get("audio") if media.get("keep_audio", True) else None
            if audio is not None:
                audio = dict(audio)
                target_samples = round(len(output) / fps * audio['sample_rate'])
                waveform = audio['waveform']
                if waveform.shape[-1] < target_samples:
                    import torch
                    waveform = torch.nn.functional.pad(waveform, (0, target_samples - waveform.shape[-1]))
                audio['waveform'] = waveform[..., :target_samples]
            return output, video_output(output, audio, fps), json.dumps(receipt, ensure_ascii=False)
        except Exception as exc:
            progress_event("error", shot=current_shot, shots=total_shots, chunk=current_chunk,
                           completed_chunks=completed_chunks, error=str(exc))
            raise


# Class IDs are the workflow contract: these keys are kept from the pack's
# previous name so graphs saved before the Zura rename still load.
NODE_CLASS_MAPPINGS = {"TrendStudioV2Render": ZuraWan22LoopedChunksSampler}
NODE_DISPLAY_NAME_MAPPINGS = {"TrendStudioV2Render": "Zura Wan 2.2 Looped Chunks Sampler"}
