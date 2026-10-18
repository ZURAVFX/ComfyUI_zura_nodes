# Change camera angle

Status: local integration test completed, artist quality review still required. A two-second test delivered 48 frames at 768 × 448 with original audio. The view moved towards the source framing later in the take, so this mode remains labelled Preview.

A guided two-pass adaptation of the supplied distilled camera workflow. Choose a short source interval, select a camera preset or add direction, and optionally add identity or room references. Generate and review the camera still, or upload a finished still to skip the entire image model. Generate video only after approving that still. No segmentation pass or spatial mask is used.

The image pass preserves FLUX 3 Klein INT8, 16 Euler/simple steps, CFG 1 and a 1024 × 576 canvas. The video pass preserves H3 REF2VA INT8, its dedicated DMD REF2VA turbo LoRA at strength 1, Comfy Kitchen attention, sigma shifts 12/3, and eight res_multistep/simple steps. It receives the original RGB performance, original audio and the approved camera image. Native image/audio guides and separate start-frame/audio locks are preserved. Input padding is 5 + 17n frames; output is trimmed to the selected interval at 24 fps. Studio uses its normal final export path and restores the selected original soundtrack.

Start with a two-second 768 × 448 test. The supplied workflow describes tests up to five seconds. Larger canvases are configurable but have no measured speed or memory promise. Camera presets are approximate instructions. Inspect the middle and end for viewpoint drift, identity changes and performance timing; this is not a geometric reconstruction or a guarantee of identical motion. Silent input and replacement dialogue are not qualified for this specific camera recipe.

Only the still stage loads the image model. Only the video stage loads H3. Uploading a finished still loads neither image encoders nor image diffusion weights. Optional references are bounded proportionally using the supplied workflow’s original image-size bounds. No model purge or forced unload is inserted by this adapter.

The integration has CPU graph-contract coverage. New video output from this adapter has not yet received a local artist review. The user’s source paths, reference photographs and personal prompts are excluded from the shipped adapter.
