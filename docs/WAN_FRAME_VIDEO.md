# Wan 2.2 first and last frames

This recipe uses native `WanFirstLastFrameToVideo`, the matched Wan 2.2 I2V
high/low-noise FP8-scaled models, their Lightx2v four-step LoRAs at strength 1,
Euler/simple, CFG 1 and shift 5. High noise runs steps 0–2 and passes its noisy
latent to low noise for steps 2–4 without adding noise again.

The supplied reference workflow's 360-turn adapter and its trigger are specific
to that example. They are not part of general image-to-video generation.

Both image inputs are scaled proportionally and centre-cropped before encoding.
The first frame is required; the last is optional. Wan does not condition on
audio in this recipe and outputs silent video. Use H3 or LTX when the sound
must guide generation. A saved, disabled audio upload is never sent into Wan.

## Precision and speed

The installed compatible I2V high/low pair is FP8 scaled, not INT8. The recipe
keeps that matched pair instead of substituting an incompatible INT8 model.
Native fast FP8 loading and Comfy Kitchen's INT8 attention are enabled. These
are different from INT8 model weights. Four-step acceleration comes from the
matched Lightx2v adapters, not from an unrelated family or subject adapter.

Full VAE decode matches the supplied graph. Low-memory tiled decode is opt-in
because spatial or temporal tiles can affect consistency. Native Comfy's full
decoder also has its own out-of-memory fallback. No new GPU speed or quality
claim is made from schema validation alone.

## Length and continuation

The preset renders at 24 fps with `4n + 1` frames. Each section is bounded to
9–81 frames here, not the native node's much larger theoretical length limit.
The default reference size is 736 × 416. The interface may choose a smaller
frame or section size to reduce memory use; even a short 14B clip can offload
on a 16 GB GPU, so these limits are not a guarantee of VRAM-only execution.

The native endpoint node accepts an image batch as its starting context. A
future continuation runner can carry generated trailing frames into the next
section and use the user's final image only for the final section. It must
remove the carried overlap exactly once, preserve 24 fps, reset at shot cuts,
and visually check joins and identity drift. There is no automatic native
unbounded loop in this recipe, and repeated independent endpoint graphs must
not be advertised as seamless continuation. Longer output is not enabled by
increasing this builder's per-section frame cap.

The native implementation is `comfy_extras/nodes_wan.py` in ComfyUI. The
[official Wan 2.2 guide](https://docs.comfy.org/tutorials/video/wan/wan2_2)
describes the matched high/low models and four-step adapters.
