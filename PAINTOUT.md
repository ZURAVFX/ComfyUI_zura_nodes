# LTX 2.5 paintout and clean plates

Paintout is included in Zura Nodes from **1.3.30**. These are native ComfyUI graph templates, separate from Studio's character-performance modes.

## Studio

In **Video**, choose **Paintout / clean plate** beside the model. Choose **Targeted repair** for a masked paintout, or **Full-scene clean plate** to generate an empty scene without masks or painted frames.

For targeted repair, add footage, a matching removal mask and full-resolution painted frames. Each painted image has a thumbnail, an editable **Frame** number and a corner remove button. Frame numbers refer to the original source, starting at **0**, even after trimming. Exported `paint_000042` filenames prefill frame 42. Duplicate and out-of-range anchors block generation with an explanation.

Click a painted thumbnail to inspect it. Its **Painted frame** menu offers first selected frame, playhead and last selected frame shortcuts, plus optional strength and colour controls. **Save frame to paint** exports the selected source frame at full resolution: 16-bit sRGB PNG for SDR or float32 ACEScg EXR for HDR. Paint it externally, then add the finished image to the strip.

Range, colour and delivery settings open above the composer. The native recipe stays at eight steps and processes one continuous shot, up to 993 frames, without chunking. Longer ranges require more memory. MP4 results include source/result comparison; EXR exports show the saved folder and a downloadable motion preview. Graph view keeps the native footage/mask picker and painted-frame controls exposed.

Restart ComfyUI after updating to load the new browser helpers, then refresh Studio. Studio integration has recipe/schema, CPU export and interaction-test coverage; a new GPU acceptance render and an on-screen layout check remain pending.

## Choose an example

- [Video - Targeted Paintout (LTX 2.5)](workflows/Video%20-%20Targeted%20Paintout%20%28LTX%202.5%29.json): Obscura Remova, manually painted clean frames and a required removal mask. White marks the objects to remove; black keeps the original. The repaired area is blended into the original-resolution plate.
- [Video - Full Scene Clean Plate (LTX 2.5)](workflows/Video%20-%20Full%20Scene%20Clean%20Plate%20%28LTX%202.5%29.json): the official Lightricks Clean Plate LoRA generates an empty scene. No removal mask or painted frames are required. Put the original above the clean plate in After Effects and mask back anything you want to retain.

Both use the LTX 2.5 distilled INT8 transformer, eight Euler ancestral steps and CFG 1. The targeted graph uses Obscura strength 1.25, painted-anchor strength 0.75, 32-pixel mask expansion and 32-pixel attention blocks. Source-guide streaming stays off for the whole-clip sampler. The sampler and model/guide nodes remain accessible inside native subgraphs.

## Install

1. Update **Zura Nodes** in ComfyUI Manager, or install the source from this repository. Install its `requirements.txt` into the Python environment used by ComfyUI.
2. Install current **ComfyUI-LTXVideo** and **ComfyUI-KJNodes**. Use a current ComfyUI with LTX 2.5, Gemma 4, native HDR colour conversion and 10-bit video interfaces. FFmpeg and FFprobe must be on PATH. The file-picker buttons currently require a local Windows server.
3. Install the model files below. Model weights are separate downloads and keep their own licences/access terms.
4. Restart ComfyUI and refresh the browser. Load either example from `workflows/`, or the Zura template catalogue.

If you installed the earlier standalone `ComfyUI-Zura-Paintout`, disable or remove that copy after updating Zura Nodes. Keep your saved workflows. The integrated nodes use the same class IDs, but there should be one active copy of the pack and its browser extension.

## Models

| Folder | Filename used by the examples |
| --- | --- |
| `models/diffusion_models` | `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` |
| `models/text_encoders` | `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` |
| `models/vae` | `ltx-2.5-video-vae-conv-bf16.safetensors` |
| `models/vae` | `ltx-2.5-audio-vae-bf16.safetensors` |
| `models/loras`, targeted graph | `LTX23_Obscura_Remova_v1.safetensors` |
| `models/loras`, full-scene graph | `ltx-2.5-22b-ic-lora-clean-plate-1.0.safetensors` |

Start with the [official LTX 2.5 model collection](https://huggingface.co/Lightricks/LTX-2.5) and [official Clean Plate LoRA](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Clean-Plate). The examples use the listed Comfy INT8/ConvRot conversions; choose matching installed files in the model subgraph if your distribution names them differently. The Obscura filename still contains 2.3 because that is the adapter used in the successful 2.5 tests. Do not replace it with an unrelated inpainting LoRA.

The video VAE is forced to **float32** before every guide/anchor encode and final decode. The Conv VAE's weights match the earlier 2.3 Conv VAE numerically; HDR handling comes from the matched working-space conversion and float32 execution, not the filename alone. The separate non-Conv `ltx-2.5-video-vae-bf16.safetensors` can be selected inside the VAE subgraph, but it was not the VAE used for the reported performance tests.

## Load footage and clean frames

Choose **Load as: Video file**, then **Choose video file** for MOV/ProRes or other footage. Video timing is detected automatically.

For EXRs, choose **Load as: Image sequence**, then **Choose sequence folder**. Select a folder containing one EXR, TIFF or PNG sequence. Frames load in numeric filename order. Enter **Sequence frame rate (fps)**, which is visible only in sequence mode: individual images do not define playback speed. Mask sequences follow the source timing.

Set the actual **Source colour space**, **Start frame** and **Frames to process**. The examples open with empty media pickers and an 81-frame range; adjust it to your shot. They do not contain sample media. A video without usable colour tags needs an explicit colour-space choice. Camera log footage needs the correct colour transform before import.

For targeted paintout, choose a matching full-resolution removal mask. Browse to the manually painted, full-size clean frames in the anchor cards. Add or replace files, enable/disable frames, and set frame numbers and strengths alongside their thumbnails. Frame numbers refer to the original footage, starting at 0. `-1` means the last selected frame. Use matching scene-linear EXRs for HDR anchors where possible; frames painted through a different display transform can introduce a mismatch that cannot reliably be inferred later.

Describe the intended clean scene in the prompt, and keep the seed fixed while comparing settings. Run one continuous shot at a time. These whole-clip examples do not implement long-shot chunking or cut resets.

## SDR, HDR and output

- **SDR (sRGB)** is the default processing mode.
- **HDR (ACEScct)** converts the plate and all anchors to the same HDR working space. It accepts HLG/PQ video, scene-linear EXRs and correctly declared SDR inputs.
- **Save as** offers SDR video, HLG video, EXR sequence, or either video together with EXRs. EXRs are scene-linear ACEScg with float32 or float16 precision. HLG video is 10-bit BT.2020. Video exports include trimmed source audio as AAC when present; EXR sequences have no audio.
- The export node provides a playable SDR motion preview after decoding. Sampling-step previews remain still images.

SDR-to-HDR processing/export is a colour-managed conversion. It does not recover highlights already clipped in SDR footage. The preview uses a fixed viewing transform for HDR sources.

The targeted graph defaults to the original workflow's **1152 x 640 centre framing**. A mask outside that crop raises an error instead of silently missing an object. The repair returns to the original plate size and blends in linear light, using one surrounding-colour correction across the shot. Outside the final repair support, original pixels are retained before delivery conversion. Float32 ACEScg EXRs can preserve untouched source values; float16 and video compression cannot make the same exact-value guarantee.

The full-scene graph fits the whole frame into the generation canvas with padding, then delivers the generated scene at source resolution. **Smart crop** remains experimental in the targeted loader: it can save inference area, but the cropped test did not match the original framing's removal quality, so it is not the default.

## Validation and limits

The integrated source uses the previously tested inference path. On an RTX 4080 with 16 GB VRAM and 64 GB RAM, the native targeted 301-frame control completed in 8m21s. High-bit-depth loading, compositing and export add work. The newer 49-frame integration tests took 102s targeted SDR, 83s full-scene SDR, 114s targeted SDR-to-HDR and 104s full-scene SDR-to-HDR. Loading/cache state differed; these are measured examples, not guaranteed timings.

The inspected targeted frames removed the selected couple while keeping surrounding subjects. The full-scene samples showed an empty street with people, cyclists and cars removed. HLG exports were checked for 10-bit BT.2020/HLG tags, exact 59.94 fps timing and source audio. Targeted float32 EXRs matched the source converted to the same linear space outside the repair support in five sampled frames, with zero difference. Synthetic HDR EXR and tagged 10-bit ProRes fixtures checked source/anchor alignment, crop/fit geometry, HDR precision and untouched high/negative source values.

Real HDR camera footage was not supplied for these tests. Generative repairs can still change textures, shadows, structure or subjects. Judge the result in motion before committing it to a shot. Output contains RGB, not original alpha, AOVs or EXR header metadata.
