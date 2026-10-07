"""One selected camera view, with native H3 sampling and source-audio anchoring."""
from __future__ import annotations

from math import ceil


def _valid_length(count: int) -> int:
    return 5 + 17 * max(0, ceil((count - 5) / 17))


def _chunks(frame_count: int, maximum: int = 124) -> list[tuple[int, int]]:
    if frame_count < 5:
        raise ValueError("The performance must contain at least five frames at 24 fps.")
    if frame_count > maximum * 12:
        raise ValueError("Trim the source to 62 seconds or less before this H3 workflow.")
    sizes = [maximum] * (frame_count // maximum)
    if frame_count % maximum:
        sizes.append(frame_count % maximum)
    if len(sizes) > 1 and sizes[-1] < 22:
        needed = 22 - sizes[-1]
        sizes[-2] -= needed
        sizes[-1] += needed
    start = 0
    result = []
    for size in sizes:
        result.append((start, size))
        start += size
    return result


class ZuraH3SingleAngle:
    """Use a Qwen AnyAngle still as the camera target while H3 follows source AV."""

    CATEGORY = "Zura/video"
    FUNCTION = "render"
    RETURN_TYPES = ("IMAGE", "AUDIO")
    RETURN_NAMES = ("new_angle_frames", "original_audio")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source_frames": ("IMAGE",),
                "source_audio": ("AUDIO",),
                "angle_frame": ("IMAGE",),
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "video_vae": ("VAE",),
                "audio_vae": ("VAE",),
                "seed": ("INT", {"default": 42, "min": 0, "max": 0xffffffffffffffff,
                                  "control_after_generate": False}),
                "steps": ("INT", {"default": 16, "min": 1, "max": 60}),
                "prompt": ("STRING", {"multiline": True, "default":
                    "crossview. <Picture 1> defines the selected camera position and framing. "
                    "<Video 1> defines the exact same performer's identity, face, clothes, "
                    "gestures, expression, and speech timing. Recreate the performance from "
                    "the new angle without changing the person or dialogue. Keep the full "
                    "head in frame and lips faithful to the original speech."}),
            }
        }

    def render(self, source_frames, source_audio, angle_frame, model, clip,
               video_vae, audio_vae, seed, steps, prompt):
        from comfy_execution.graph_utils import GraphBuilder

        frame_count = int(source_frames.shape[0])
        height, width = map(int, source_frames.shape[1:3])
        if width % 32 or height % 32:
            raise ValueError("Resize source frames to a width and height divisible by 32.")
        if len(angle_frame) < 1:
            raise ValueError("Choose and apply a camera in AnyAngle Studio first.")
        if not str(prompt).strip():
            raise ValueError("The H3 performance prompt cannot be empty.")

        graph = GraphBuilder()
        picture = graph.node("ImageFromBatch", image=angle_frame,
                             batch_index=0, length=1).out(0)
        picture = graph.node("ImageScale", image=picture,
                             upscale_method="lanczos", width=width,
                             height=height, crop="center").out(0)
        takes = []
        for part, (start, count) in enumerate(_chunks(frame_count)):
            length = _valid_length(count)
            video = graph.node("GetImageRangeFromBatch", images=source_frames,
                               start_index=start, num_frames=count).out(0)
            if length > count:
                last = graph.node("ImageFromBatch", image=video,
                                  batch_index=count - 1, length=1).out(0)
                tail = graph.node("RepeatImageBatch", image=last,
                                  amount=length - count).out(0)
                video = graph.node("ImageBatch", image1=video, image2=tail).out(0)
            speech = graph.node("TrimAudioDuration", audio=source_audio,
                                start_index=start / 24.0,
                                duration=count / 24.0).out(0)
            condition = graph.node("MiniMaxH3ReferenceToVideo", clip=clip,
                vae=video_vae, audio_vae=audio_vae, prompt=prompt,
                width=width, height=height, length=length, ref_image_size="match",
                **{"ref_images.ref_image_0": picture,
                   "ref_videos.ref_video_0": video,
                   "ref_video_audios.ref_video_audio_0": speech})
            guided = graph.node("MiniMaxH3AddGuide", positive=condition.out(0),
                latent=condition.out(1), vae=video_vae, image=picture,
                frame_idx=0).out(0)
            guided = graph.node("MiniMaxH3AddGuide", positive=guided,
                latent=condition.out(1), audio=speech,
                audio_vae=audio_vae, frame_idx=0).out(0)
            guider = graph.node("BasicGuider", model=model,
                                conditioning=guided).out(0)
            noise = graph.node("RandomNoise", noise_seed=(int(seed) + part) % (1 << 64)).out(0)
            sigmas = graph.node("BasicScheduler", model=model,
                                scheduler="simple", steps=int(steps),
                                denoise=1.0).out(0)
            sampler = graph.node("KSamplerSelect", sampler_name="res_multistep").out(0)
            latent = graph.node("SamplerCustomAdvanced", noise=noise,
                                guider=guider, sampler=sampler, sigmas=sigmas,
                                latent_image=condition.out(1)).out(0)
            images = graph.node("VAEDecode", samples=latent, vae=video_vae).out(0)
            if length != count:
                images = graph.node("GetImageRangeFromBatch", images=images,
                                    start_index=0, num_frames=count).out(0)
            takes.append(images)

        output = takes[0]
        for take in takes[1:]:
            output = graph.node("ImageBatch", image1=output, image2=take).out(0)
        original_audio = graph.node("TrimAudioDuration", audio=source_audio,
                                    start_index=0.0,
                                    duration=frame_count / 24.0).out(0)
        return {"result": (output, original_audio), "expand": graph.finalize()}


NODE_CLASS_MAPPINGS = {"ZuraH3SingleAngle": ZuraH3SingleAngle}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraH3SingleAngle": "H3 · Render selected camera angle"}
