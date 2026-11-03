# Studio 1.3.47 validation

The UI pass retains the existing charcoal palette, Manrope typography and lime primary action. Image and Video now share preview width, model/operation grouping, attachment protection and window-responsive prompt sizing. Large source/result images are contained within the image viewer. Long model and mask-layer lists retain local scrolling; the revised main workspaces do not gain page scrolling.

Seventeen focused code/DOM suites passed across Image, endpoint/reference video, Paintout, Watermark, HDR, Frame Extension, camera navigation, zoom/comparison, reset and model installation/access. The revised layout has not received final rendered visual sign-off across window sizes. No generation settings were altered by the visual pass.

## Resolution and conditioning

SDR endpoint workflows and H3 reference-to-video now share a maximum 4096-pixel side and 8,388,608-pixel canvas budget; the slider reaches 8.35 MP. This is an application ceiling, not a promise that every GPU can render it. Native HDR keeps its separate limits. Decimal slider values survive reopening, and Fast/two-stage LTX report their smaller sampling size.

LTX first-image conditioning uses `LTXVImgToVideoInplace` at strength 0.7, with an optional last-frame guide. The refinement pass restores first-frame conditioning at strength 1 and uses Euler. Initial sampling remains Euler ancestral with the fixed distilled schedule. Six graph variants passed installed-node schema checks. High-resolution GPU rendering was not qualified in this pass.

## Matched precision diagnostic

A comment-graphic example used the first/last-frame workflow with one starting image and no last image. INT8 and BF16 transformer runs used identical source pixels, prompt, seed, 1344 × 736 resolution, 49 frames at 24 fps, 8 steps, text encoder and VAEs. Fast and two-stage were off. Both runs had empty node caches.

INT8 completed in 45.5 seconds and BF16 in 73.3 seconds, including loading and decoding. BF16 was softer in this sample and did not clearly improve text or requested motion. The shared text encoder remained INT8, so this is a transformer-variant comparison, not an entirely BF16 pipeline. One seed is not a general quality ranking. INT8 remains the default.

For H3, the failed reference-only run did contain the uploaded reference conditioning. An otherwise matched Quality 40-step run with Picture 1 anchored removed the invented live-action scene, but still distorted text. The new Reference only label clarifies the distinction; it is not a typography-quality fix.

Official examples reviewed: [LTX 2.5 workflows](https://github.com/Lightricks/ComfyUI-LTXVideo/tree/master/example_workflows/2.5) and [MiniMax H3 model notes](https://huggingface.co/MiniMaxAI/MiniMax-H3).
