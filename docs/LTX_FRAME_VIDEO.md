# LTX 2.5 first / last frame recipe

`web/ltx_frame_video_recipes.js` builds an ordinary native Comfy API graph. The first image is required; the last is optional. Each image is fitted proportionally to the output and centre-cropped, then anchored with `LTXVAddGuide` at its actual frame index. `LTXVCropGuides` removes appended conditioning tokens before decoding. Neither prompt frame numbers nor a reference-image LoRA substitutes for timed endpoints.

The default uses the installed official distilled INT8 + convrot transformer, Gemma4 INT8 text encoder, Comfy Kitchen attention, CFG 1 and the official fixed eight-step Euler ancestral schedule. The convolutional video VAE is the faster, lower-memory decoder; the newer diffusion decoder trades more time and memory for quality. No LTX 2.3 control LoRA is loaded into 2.5.

With Audio reference on, the graph trims the supplied waveform to the selected clip, encodes it into audio tokens, freezes those tokens with a zero noise mask, and supplies them alongside the video latent. The original trimmed waveform becomes the output soundtrack. This is performance/audio conditioning, not speaker identity transfer. With Audio reference off, the model generates its own soundtrack. Muting the final output is a separate UI/output concern. Very short reference audio is not silently repeated or padded by this recipe.

The recipe uses 24 fps, dimensions divisible by 32, and frame counts of `8n + 1`. Its single-window ceiling is 361 frames (15.04 seconds) and 1.03 megapixels, with 49 frames as the starting default. These are recipe limits, not a measured VRAM guarantee. The upper corner of this range has not been qualified on 16 GB. Longer clips show a hint to start at 0.25 MP on a 16 GB GPU. The last guide stays at the actual final frame, and reference audio follows the native duration.

## Verification

`node tests/test_ltx_frame_video_recipes.mjs` checks timed first/last guides, proportional fitting, guide removal, INT8 selection, the distilled schedule, source-audio freezing/muxing, generated audio, invalid inputs and availability detection.

On 24 October 2026, live Comfy validation passed first-only, first/last, and first/last plus reference audio with no errors or warnings. An additional live-schema check confirmed all required inputs and linked output types. This is graph validation only. No GPU quality, runtime or maximum-memory claim follows from it.

## Longer-shot continuation

Native `LTXVAddGuide` accepts an image batch representing a short video, so a bounded continuation can use the previous window's final nine decoded frames as a real guide at the next window's beginning. Keep model/text encoders cached between windows, apply the final requested endpoint only to the final window, and discard the repeated nine frames from each following output. A nine-frame overlap preserves the 8n+1 temporal grid when 8n+1 windows are joined. Reference-audio offsets must advance by the number of newly delivered frames, not by the full overlapping window length.

This is a feasible mechanism, not an implemented or visually qualified seamless-loop feature. It needs two-window tests for velocity, identity, audio boundaries and VAE reconstruction differences before Studio offers it. A previous last still alone gives no velocity history and is insufficient evidence for seamless continuation. Never advertise longer shots as preserving identical quality or constant total runtime.

## Primary references

- [LTX 2.5 model card](https://huggingface.co/Lightricks/LTX-2.5): distilled schedule, INT8 Comfy compatibility and spatial/temporal grids.
- [Official single-stage distilled workflow](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/master/example_workflows/2.5/LTX-2.5_T2V_I2V_Single_Stage_Distilled.json): native sampler, AV path and decoder options.
- [Official audio-to-video distilled workflow](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/master/example_workflows/2.5/LTX-2.5_A2V_Two_Stage_Distilled.json): frozen input-audio latents and original-waveform output.
- Installed ComfyUI `comfy_extras/nodes_lt.py`: exact guide indexing, guide cropping, AV concatenation and guide-video support.
