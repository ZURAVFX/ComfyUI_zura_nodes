# Extract alpha

Choose **Video > Extract alpha**, add a video and trim the range. LTX Alpha Gen automatically separates the foreground from its background. It does not use a prompt or painted selection to choose a subject.

Use **Install missing models** if setup is needed. The adapter is a separate 1.31 GB download alongside the shared LTX 2.5 model, text encoder and VAEs. For gated files, Studio opens the existing Hugging Face browser sign-in and licence acceptance flow. Existing compatible files and your selected model folders are reused.

## Processing and delivery

- The official recipe uses the Alpha Gen adapter at strength 1, empty positive and negative prompts, and one distilled eight-step sampling stage. Two-stage refinement and unrelated LoRAs are not used.
- Select up to **145 source frames**. Longer ranges need separate runs. Shorter ranges are padded with held end frames internally; delivered files contain only the selected range.
- Processing resolution defaults to **50%**. Choose 25%, 50%, 75% or full resolution to balance detail and memory. Processing dimensions are padded upwards to multiples of 32 without stretching. The maximum working raster is 1920 × 1088, including portrait orientation. Full-resolution long ranges require substantially more memory than a desktop GPU may have.
- The matte is restored to the original source dimensions and rational frame rate. The transparent export combines it with the original source RGB, retaining the selected audio interval when present.
- This initial route accepts constant-frame-rate SDR sources. Convert a viewing copy of HDR footage to SDR before using this route.

The viewer switches between **Source**, **Matte** and a checkerboard **Cutout** preview. Download the transparent **ProRes 4444 MOV**, the grayscale matte video or a ZIP of **16-bit PNG matte frames**. White means opaque and black means transparent. The checkerboard preview is a viewing file; it has no transparency. For odd source dimensions the browser MP4 previews have an extra edge pixel for codec compatibility; MOV and PNG frames retain the exact source raster.

Alpha quality depends on the shot. Review fine edges and translucent objects before using the matte in a final composite.

## Sources and validation

Based on the [official Alpha Gen model card](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Alpha-Gen) and [official single-stage IC-LoRA workflow](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/master/example_workflows/2.5/LTX-2.5_V2V_ICLoRA_Single_Stage_Distilled.json).

Two short local inference checks delivered 9 and 8 selected frames at the source 704 × 416 raster and 24000/1001 fps. The 8-frame check held the last source frame internally to reach 9 model frames, then removed the extra frame from every export. The transparent MOV decoded with a non-opaque alpha channel. These checks used 50% processing resolution.

Measured headless layout checks covered landscape and portrait footage, four window sizes and loaded, running, result and missing-model states. The preview and primary controls remained visible.

CPU media tests cover source padding, held end frames, delivery frame count, original dimensions, fractional frame rates, audio and decoded ProRes alpha polarity. Graph and UI checks cover the native sampling path, model readiness, trim validation, result recovery and cancellation ownership. These checks do not establish matte quality for every shot or guarantee that every full-resolution range fits in VRAM.
