# Install Zura Studio

Character performance offers Wan, MiniMax H3 and LTX 2.5, including the approved original-audio, replacement-dialogue and silent-footage paths. Wan offers precise masked replacement; H3 uses selection/depth guidance; LTX recreates the whole frame. Viewport to final offers H3. LTX viewport remains excluded after its separate rejected test. H3 Head & face is a separate two-second original-audio option. Download only the model for your chosen task. See [approved workflows](docs/APPROVED_WORKFLOWS.md) and the [current scope](docs/STUDIO_VERIFIED_SCOPE.md).

Zura Studio is included in the official **Zura Nodes** ComfyUI pack. The pack is code; video model weights are separate downloads and are not included.

## Install the pack

When an approved version is available, open **ComfyUI Manager > Install Custom Nodes**, search for **Zura Nodes**, and install the entry published by **ZURAVFX**. Manager installs the pack's Python requirements for you. If the release is still awaiting Registry review or Manager cannot install it, use the official GitHub ZIP below. Restart ComfyUI, then choose **Zura → Open Zura Studio** in the ComfyUI menu (or add the optional **Open Zura Studio** launcher node).

If Manager is unavailable, download the current ZIP from the official [Zura Nodes GitHub Releases](https://github.com/ZURAVFX/ComfyUI_zura_nodes/releases). Extract it to `ComfyUI/custom_nodes/ComfyUI_zura_nodes` so that `requirements.txt` is directly inside that folder.

For a Windows portable ComfyUI install, open Command Prompt in the portable folder and run:

```bat
python_embeded\python.exe -m pip install -r ComfyUI\custom_nodes\ComfyUI_zura_nodes\requirements.txt
```

For a virtual-environment install, use that installation's Python in place of `python_embeded\python.exe`. Restart ComfyUI after installation. Do not install a similarly named fork.

## Create a character replacement

1. Add your source video and character references. Choose the clip interval.
2. Describe the look under **Describe your starting image**, then select **Create starting frame**. Source tracking and image creation run automatically with progress for each stage.
3. Review the image. Choose **Edit image** and **Regenerate image** to revise it, or **Use image & continue** to approve it. Approval opens the next stage without starting a video render.
4. Add optional video direction under **Direct your video**. Choose video resolution, sampling and audio, then select **Generate video**. Use **Cancel run** to stop.

A finished frame skips image generation. H3 **Head & face** uses the portrait directly; H3 direct viewport uses appearance references directly. These routes show their own controls.

Wan Animate 2 is the separate **Character + background** engine choice. It regenerates the complete frame, without a spatial mask. See [its setup and limitations](docs/WAN_ANIMATE2.md); this local integration is not an artist-approved quality result yet.

For lighting changes, choose **Relight**: create and approve a Klein lighting image, then render with the supplied Wan 2.1 chained recipe. H3 is not required for this route.

For instruction-based still-image edits, open **Image > Edit image** and choose **Qwen Image Edit 2511** or **FLUX Klein 9B**. See [image editing](docs/IMAGE_EDIT.md) for the source/reference order, limits and validation status.

## Choose an engine and download its weights

Download only the engine you plan to try first. Put every file under the matching `ComfyUI/models/` folder shown here. Names must match exactly. These are the versions the current Studio graphs request; do not rename other model variants to make them appear installed.

**Shared Studio files** used for masking, starting-image previews and optional audio separation:

- `checkpoints/sam3.1_multiplex_fp16.safetensors` from [Comfy-Org SAM 3.1](https://huggingface.co/Comfy-Org/sam3.1/blob/main/sam3.1_multiplex_fp16.safetensors).
- `diffusion_models/flux-2-klein-9b-fp8.safetensors` from [Black Forest Labs](https://huggingface.co/black-forest-labs/FLUX.2-klein-9b-fp8/blob/main/flux-2-klein-9b-fp8.safetensors); `text_encoders/qwen_3_8b_fp8mixed.safetensors` from [Comfy-Org](https://huggingface.co/Comfy-Org/vae-text-encorder-for-flux-klein-9b/blob/main/split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors); and `vae/full_encoder_small_decoder.safetensors` from the [official FLUX.2 small decoder files](https://huggingface.co/black-forest-labs/FLUX.2-small-decoder/tree/main). The BFL model requires accepting its non-commercial terms.
- Optional source separation uses `diffusion_models/MelBandRoformer_fp16.safetensors` from [MelBand RoFormer](https://huggingface.co/bleedheart/melband_reformers/tree/main).

**LTX 2.5** files:

- Official Lightricks files: [`ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors`](https://huggingface.co/Lightricks/LTX-2.5/blob/main/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors), [`ltx-2.5-video-vae-conv-bf16.safetensors`](https://huggingface.co/Lightricks/LTX-2.5/blob/main/vae/ltx-2.5-video-vae-conv-bf16.safetensors), [`ltx-2.5-audio-vae-bf16.safetensors`](https://huggingface.co/Lightricks/LTX-2.5/blob/main/vae/ltx-2.5-audio-vae-bf16.safetensors), [`ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors`](https://huggingface.co/Lightricks/LTX-2.5/blob/main/latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors), and [`ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors`](https://huggingface.co/Lightricks/LTX-2.5/blob/main/loras/ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors).
- `text_encoders/gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors` is a community conversion by [DmitryDB](https://huggingface.co/DmitryDB/LTX-2.5-ComfyUI-Quants/blob/main/text_encoders/gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors), not an official Lightricks quantisation.
- Install [comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux) for body-motion guidance; its included detector files are `ckpts/yzd-v/DWPose/yolox_l.onnx` and `ckpts/hr16/DWPose-TorchScript-BatchSize5/dw-ll_ucoco_384_bs5.torchscript.pt`.

Add the files for the LTX route you intend to use:

- **Object swap / masked editing:** `vae/ltx-2.5-video-vae-bf16.safetensors` from the [official LTX 2.5 DiffVAE files](https://huggingface.co/Lightricks/LTX-2.5/blob/main/vae/ltx-2.5-video-vae-bf16.safetensors), plus `loras/ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors` from the [official In-Outpainting adapter](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting). This route requests the DiffVAE; the similarly named ConvVAE above does not replace it.
- **Viewport to final (experimental):** `loras/ltx-2.5-22b-ic-lora-layout-to-render-1.0.safetensors` from the [official Layout-to-Render adapter](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render). This route uses the ConvVAE above and raw blockout frames. It does not need the Union adapter or DWPose detectors. H3 remains the recommended viewport engine.

These adapter repositories can require access approval. Sign in to Hugging Face, review and accept their displayed terms if you agree, then download the exact named file to `models/loras/`.

**MiniMax H3** files:

- Official Comfy-Org files: [`minimax_h3_ref2va_pruned_int8_convrot.safetensors`](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/diffusion_models/minimax_h3_ref2va_pruned_int8_convrot.safetensors), [`qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors), [`minimax_h3_video_vae_int8_convrot.safetensors`](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/vae/minimax_h3_video_vae_int8_convrot.safetensors), [`minimax_h3_audio_vae_fp32.safetensors`](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/vae/minimax_h3_audio_vae_fp32.safetensors), and [`minimax_h3_fun_controlnet_union_2.0_pruned_int8_convrot.safetensors`](https://huggingface.co/Comfy-Org/MiniMax-H3/blob/main/model_patches/minimax_h3_fun_controlnet_union_2.0_pruned_int8_convrot.safetensors).
- H3 fast sampling uses [`minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors`](https://huggingface.co/drbaph/MiniMax-H3-Turbo-Lora-ComfyUI/blob/main/experimental/minimax_h3_dmd_ref2va_8step_turbo_pruned.safetensors), a community LoRA, not a Comfy-Org file.

Accept the H3 community licence and any terms shown before downloading. The H3 turbo LoRA has separate community licensing.

**Motion transfer, Object swap and Relight** also require [comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux) for `DepthAnythingV2Preprocessor`. Its first use can download `depth_anything_v2_vitl.pth` into that pack's checkpoint cache; allow internet access and time for this download. The direct H3 **Viewport to final** route uses the source video instead of this depth pass and does not require the H3 FunControl model. It does use ComfyUI-KJNodes for its frame-range node. The Studio checklist distinguishes these routes.

**Wan 2.2 Animate** files:

- `diffusion_models/Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors` from [Kijai's Wan Animate model](https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/blob/main/Wan22Animate/Wan2_2-Animate-14B_fp8_scaled_e4m3fn_KJ_v2.safetensors); `vae/Wan2_1_VAE_bf16.safetensors` from [Kijai](https://huggingface.co/Kijai/WanVideo_comfy/blob/main/Wan2_1_VAE_bf16.safetensors); and the [`WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors`](https://huggingface.co/Kijai/WanVideo_comfy/blob/main/LoRAs/Wan22_relight/WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors) and [`lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors`](https://huggingface.co/Kijai/WanVideo_comfy/blob/main/Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors) LoRAs.
- `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors` from [Comfy-Org](https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/blob/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors) and `clip_vision/clip_vision_h.safetensors` from [Comfy-Org](https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/blob/main/split_files/clip_vision/clip_vision_h.safetensors).
- `loras/Wan14B_RealismBoost.safetensors` from its [model author](https://huggingface.co/anthonyluu/Wan14B_RealismBoost/blob/main/Wan14B_RealismBoost.safetensors).
- `detection/vitpose-l-wholebody.onnx` from [JunkyByte ViTPose](https://huggingface.co/JunkyByte/easy_ViTPose/blob/main/onnx/wholebody/vitpose-l-wholebody.onnx) and `detection/yolov10m.onnx` from [Wan-AI](https://huggingface.co/Wan-AI/Wan2.2-Animate-14B/blob/main/process_checkpoint/det/yolov10m.onnx). Follow [ComfyUI-WanAnimatePreprocess instructions](https://github.com/kijai/ComfyUI-WanAnimatePreprocess) for their folder placement.

Some official model pages are gated. Sign in, review and accept the displayed licence or terms, then download only if you agree. Check file sizes and available disk space first; several individual weights are tens of gigabytes. Converted weights are labelled above and have their own licence terms.

Install the native dependencies through Manager when prompted: current ComfyUI, [ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite), [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes), [ComfyUI-WanAnimatePreprocess](https://github.com/kijai/ComfyUI-WanAnimatePreprocess), [comfyui_controlnet_aux](https://github.com/Fannovel16/comfyui_controlnet_aux), [ComfyUI-essentials](https://github.com/cubiq/ComfyUI_essentials) and [ComfyUI-MelBandRoFormer](https://github.com/kijai/ComfyUI-MelBandRoFormer). H3's optional **Remove on-screen text** also needs [ArtVenture](https://github.com/sipherxyz/comfyui-art-venture); its first use may download a LaMa inpainting weight. Video import/export needs FFmpeg available on your system. Restart after installing nodes or adding models.

## Optional features

Core video generation works without the optional speech and enhancement setups. Run only the helper for a feature you choose. The helpers do not install Python packages; if a download helper reports a missing package, it prints the manual command for the same ComfyUI Python environment. Its `--help` and `--check` options are read-only.

- `Setup_Wan_Speech_Windows.cmd` checks and downloads Wan's optional audio-driven performance guide. If `huggingface_hub` is missing, install it manually in the ComfyUI Python environment as the helper directs, then rerun.
- `Setup_Speech_Windows.cmd` checks and downloads optional LatentSync or MuseTalk model files. It requires `diffusers`, `transformers`, `huggingface_hub`, `safetensors`, `accelerate` and `einops` in the ComfyUI Python environment; if any are missing, the helper prints the manual install command and stops.
- `Setup_H3_Enhancement_Windows.cmd` installs the separate model for H3 Enhanced 1080p.
- `Setup_LongCat_Windows.cmd` sets up local LongCat voice generation; it uses a separate Python environment and downloads its own model.

These helpers are not run when the pack is installed. Read the prompts and licence terms before accepting any additional model download. H3 Native 1080p is memory intensive and has not completed the tested 16 GB GPU qualification.

## What to try first

Begin with a continuous, single-shot clip of up to five seconds and the lowest resolution that suits your review. H3 supports up to five seconds. LTX supports up to five seconds for regular shots and up to fifteen seconds in Viewport to final. Wan can process longer clips in sections; inspect joins and detail across sections. Camera changes while replacing an environment and masked LTX speech remain experimental. Generated models can alter scene details and do not guarantee exact camera or performance retention. See [tested limits](ARTIST_STUDIO_VALIDATION.md) before planning a longer or more complex shot.


## H3 Head & face

Choose Character performance, MiniMax H3, then Head & face. Upload a source video with audio and a portrait or character sheet as your first reference. Choose a clip up to two seconds. The portrait is used directly, without starting-image generation. This route keeps the source body and background through crop compositing. Use Full character for replacement dialogue or silent footage.

Studio lists each missing model and native node in About this workflow. The exact model/adapter names and strengths are listed in [the head-swap recipe](docs/H3_HEAD_SWAP_DEV.md). In addition to the H3 encoders/VAEs and SAM checkpoint, it requires the NKD Basic Tools and Sigmas Curve nodes, MaskVidExperiments subject crop/uncrop, DW pose preprocessing, the LayerStyle batch-padding node and Comfy core background removal/Kitchen attention. Install missing node packs through Manager and restart; do not substitute similarly named weights.

## H3 Head & face

Choose Character performance, MiniMax H3, then Head & face. Upload a source video with audio and a portrait or character sheet as your first reference. Choose a clip up to two seconds. The portrait is used directly, without starting-image generation. This route keeps the source body and background through crop compositing. Use Full character for replacement dialogue or silent footage.

Studio lists each missing model and native node in About this workflow. Exact model/adapter names and strengths are listed in [the head-swap recipe](docs/H3_HEAD_SWAP_DEV.md). In addition to the H3 encoders/VAEs and SAM checkpoint, it requires NKD Basic Tools and Sigmas Curve nodes, MaskVidExperiments subject crop/uncrop, DW pose preprocessing, the LayerStyle batch-padding node and Comfy core background removal/Kitchen attention. Install missing node packs through Manager and restart; do not substitute similarly named weights.
