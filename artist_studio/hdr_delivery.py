"""Delivery graph for a qualified LTX 2.5 ACEScct HDR generation.

This is deliberately separate from model inference. Calling this adapter does
not make an SDR generation HDR: the preceding model must actually generate
ACEScct codes using a qualified native HDR or SDR-to-HDR workflow.
"""

import math
import re

SDR_HDR_LORA = "ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors"
SDR_HDR_EMBEDDINGS = "ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors"
DISTILLED_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"


def ltx25_sdr_to_hdr_dynamic_graph(images, *, fps, model, video_vae, audio_vae,
                                    output, prefix, seed=42, audio=None):
    """Build bounded SDR-to-HDR conversion with exact source-frame restoration.

    The source must already have been decoded to normalised sRGB. The caller
    must inspect the input's colour metadata, manage selection/clip duration,
    and reject HDR rather than passing it into this SDR route. This graph adds
    only model-internal reflect/last-frame padding, then crops back to the
    unpadded source width, height and frame count before output.
    """
    if not isinstance(images, (list, tuple)) or len(images) != 2:
        raise ValueError("Images must be a Comfy graph link.")
    audio_link=['zura_hdr_trim_audio',0] if audio is not None else None
    graph=ltx25_sdr_to_hdr_graph(['zura_hdr_prepare',0],width=64,height=64,
                                  frames=9,fps=fps,model=model,video_vae=video_vae,
                                  audio_vae=audio_vae,output=output,prefix=prefix,
                                  seed=seed,audio=audio_link)
    graph['zura_hdr_prepare']={'class_type':'ZuraLTXHDRPrepare','inputs':{'images':list(images)}}
    if audio is not None:
        if not isinstance(audio,(list,tuple)) or len(audio)!=2:
            raise ValueError('Audio input must be a Comfy node output link.')
        graph['zura_hdr_trim_audio']={'class_type':'ZuraHDRTrimAudio','inputs':{'audio':list(audio),'frames':['zura_hdr_prepare',3],'fps':float(fps)}}
    graph['hdr_empty_video']['inputs'].update(width=['zura_hdr_prepare',4],
                                               height=['zura_hdr_prepare',5],
                                               length=['zura_hdr_prepare',6])
    graph['hdr_empty_audio']['inputs']['frames_number']=['zura_hdr_prepare',6]
    graph['hdr_unpad_frames']['inputs']['length']=['zura_hdr_prepare',3]
    graph['hdr_unpad_raster']['inputs'].update(width=['zura_hdr_prepare',1],
                                                height=['zura_hdr_prepare',2])
    return graph


def ltx25_sdr_to_hdr_graph(images, *, width, height, frames, fps, model, video_vae,
                           audio_vae, output, prefix, seed=42, audio=None,
                           delivered_width=None, delivered_height=None, delivered_frames=None):
    """Construct the official single-stage LTX 2.5 SDR-to-HDR recipe.

    Caller supplies sRGB images already resized/padded to exactly width x height
    and 8n+1 frames, with an optional separately trimmed source audio link.
    Padding must be at the right/bottom and end of the clip; supplied delivery
    dimensions/frame count remove that padding after decode. This adapter is
    experimental until rendered and checked with the official gated adapter.
    """
    if not isinstance(images, (list, tuple)) or len(images) != 2:
        raise ValueError("Images must be a Comfy graph link.")
    if any(type(v) is not int or v < 64 or v % 32 for v in (width, height)):
        raise ValueError("Pad image dimensions to multiples of 32.")
    if type(frames) is not int or not 9 <= frames <= 1000 or (frames - 1) % 8:
        raise ValueError("Pad the guide to 8n+1 frames before HDR processing.")
    delivered_width = width if delivered_width is None else delivered_width
    delivered_height = height if delivered_height is None else delivered_height
    delivered_frames = frames if delivered_frames is None else delivered_frames
    if any(type(v) is not int or not 1 <= v <= limit for v, limit in
           ((delivered_width, width), (delivered_height, height), (delivered_frames, frames))):
        raise ValueError("Delivered dimensions and frames must fit the padded guide.")
    if not all(isinstance(x, str) and x for x in (model, video_vae, audio_vae)):
        raise ValueError("Install the compatible LTX 2.5 model and both VAEs first.")
    if type(seed) is not int or not 0 <= seed <= 2**53 - 1:
        raise ValueError("Choose a valid seed.")
    if not isinstance(fps, (float, int)) or isinstance(fps, bool) or not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError("Choose a frame rate between 1 and 120 fps.")
    def n(kind, **inputs): return {"class_type": kind, "inputs": inputs}
    graph = {
        "hdr_model": n("UNETLoader", unet_name=model, weight_dtype="default"),
        "hdr_lora": n("LTXICLoRALoaderModelOnly", model=["hdr_model", 0], lora_name=SDR_HDR_LORA, strength_model=1.0),
        "hdr_vae_loader": n("VAELoader", vae_name=video_vae),
        "hdr_vae": n("LTXVVAEForceFloat32", vae=["hdr_vae_loader", 0]),
        "hdr_audio_vae": n("VAELoader", vae_name=audio_vae),
        "hdr_conditioning": n("LTXVLoadConditioning", file_name=SDR_HDR_EMBEDDINGS, device="cpu"),
        "hdr_guide_input": n("ImageColorSpace", image=list(images), source="sRGB", destination="HDR ACEScct"),
        "hdr_condition": n("LTXVConditioning", positive=["hdr_conditioning", 0], negative=["hdr_conditioning", 0], frame_rate=float(fps)),
        "hdr_empty_video": n("EmptyLTXVLatentVideo", width=width, height=height, length=frames, batch_size=1),
        "hdr_empty_audio": n("LTXVEmptyLatentAudio", audio_vae=["hdr_audio_vae", 0], frames_number=frames, frame_rate=float(fps), batch_size=1),
        "hdr_guide": n("LTXAddVideoICLoRAGuide", positive=["hdr_condition", 0], negative=["hdr_condition", 1],
                       vae=["hdr_vae", 0], latent=["hdr_empty_video", 0], image=["hdr_guide_input", 0],
                       frame_idx=0, strength=1.0, latent_downscale_factor=["hdr_lora", 1], crop="disabled",
                       use_tiled_encode=False, tile_size=256, tile_overlap=64),
        "hdr_av": n("LTXVConcatAVLatent", video_latent=["hdr_guide", 2], audio_latent=["hdr_empty_audio", 0]),
        "hdr_guider": n("CFGGuider", model=["hdr_lora", 0], positive=["hdr_guide", 0], negative=["hdr_guide", 1], cfg=1.0),
        "hdr_noise": n("RandomNoise", noise_seed=seed),
        "hdr_sampler": n("KSamplerSelect", sampler_name="euler"),
        "hdr_sigmas": n("ManualSigmas", sigmas=DISTILLED_SIGMAS),
        "hdr_sample": n("SamplerCustomAdvanced", noise=["hdr_noise", 0], guider=["hdr_guider", 0], sampler=["hdr_sampler", 0], sigmas=["hdr_sigmas", 0], latent_image=["hdr_av", 0]),
        "hdr_separate": n("LTXVSeparateAVLatent", av_latent=["hdr_sample", 0]),
        "hdr_crop_guides": n("LTXVCropGuides", positive=["hdr_guide", 0], negative=["hdr_guide", 1], latent=["hdr_separate", 0]),
        "hdr_decode": n("VAEDecodeTiled", samples=["hdr_crop_guides", 2], vae=["hdr_vae", 0], tile_size=512, overlap=64, temporal_size=128, temporal_overlap=32),
    }
    graph["hdr_unpad_frames"] = n("ImageFromBatch", image=["hdr_decode", 0], batch_index=0, length=delivered_frames)
    graph["hdr_unpad_raster"] = n("ImageCrop", image=["hdr_unpad_frames", 0], width=delivered_width,
                                  height=delivered_height, x=0, y=0)
    graph.update(ltx_hdr_delivery(["hdr_unpad_raster", 0], fps, output=output, prefix=prefix,
                                  working_space="ltx25_acescct_qualified", audio=audio))
    return graph


def ltx_hdr_delivery(images, fps, *, output, prefix, working_space, audio=None):
    """Build native Comfy delivery nodes for already-qualified ACEScct frames.

    ``images`` and ``audio`` are Comfy API graph links. The return value is a
    new graph fragment; callers must merge it into their graph and collect the
    resulting video and/or EXR directory. No implicit SDR->HDR conversion or
    claiming existing SDR samples are ACEScct is allowed.
    """
    if working_space != "ltx25_acescct_qualified":
        raise ValueError("HDR delivery requires a qualified LTX 2.5 ACEScct generation.")
    if output not in ("hlg_video", "acescg_exr", "hlg_and_exr"):
        raise ValueError("Choose HLG video, ACEScg EXR, or both.")
    if not isinstance(images, (list, tuple)) or len(images) != 2:
        raise ValueError("Image input must be a Comfy node output link.")
    if audio is not None and (not isinstance(audio, (list, tuple)) or len(audio) != 2):
        raise ValueError("Audio input must be a Comfy node output link.")
    if not isinstance(fps, (float, int)) or isinstance(fps, bool) or not math.isfinite(fps) or not 1 <= fps <= 120:
        raise ValueError("Choose a frame rate between 1 and 120 fps.")
    if not isinstance(prefix, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", prefix):
        raise ValueError("Use a simple output name without path separators.")

    graph = {}
    # Official LTX-2.5 examples use ACEScct -> native Comfy HLG, CreateVideo
    # at 10 bits, plus LTXVHDRDecodePostprocess for ACEScg float EXRs.
    if output in ("hlg_video", "hlg_and_exr"):
        graph["zura_hdr_hlg"] = {"class_type": "ImageColorSpace", "inputs": {
            "image": list(images), "source": "HDR ACEScct", "destination": "HDR"}}
        video = {"images": ["zura_hdr_hlg", 0], "fps": float(fps),
                 "bit_depth": 10, "color_space": "HDR", "codec": "none"}
        if audio is not None:
            video["audio"] = list(audio)
        graph["zura_hdr_video"] = {"class_type": "CreateVideo", "inputs": video}
        graph["zura_hdr_save_video"] = {"class_type": "ZuraHDRSaveExactRate", "inputs": {
            "video": ["zura_hdr_video", 0], "filename_prefix": "genj/hdr/" + prefix,
            "fps": float(fps)}}
    if output in ("acescg_exr", "hlg_and_exr"):
        graph["zura_hdr_exr"] = {"class_type": "LTXVHDRDecodePostprocess", "inputs": {
            "image": list(images), "transfer": "acescct", "save_exr": True,
            "exr_color_space": "acescg", "output_dir": "genj/hdr/" + prefix,
            "filename_prefix": "frame", "half_precision": True}}
    return graph
