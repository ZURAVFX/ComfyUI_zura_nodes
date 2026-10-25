# Starting images for video

The model picker beside the prompt selects the starting-image generator. It also offers **Use finished image**, which uploads an existing frame without loading an image model. Image approval remains separate from video generation.

| Generator | Appearance references, excluding the original frame | Recipe |
| --- | --- | --- |
| Flux 3 Klein | 9 | Existing Image workspace INT8 reference recipe, 16 steps |
| FLUX Klein 9B | 3 | Existing FP8 four-step edit recipe |
| Qwen Image Edit 2511 | 2 | INT8, dedicated Qwen encoder/VAE, four-step Lightning |
| Qwen Image 2.1 | 9 | Experimental INT8 base, native 2.1 encoder/VAE, lossless CPU reference cache, 40 steps |

Qwen 2.1 uses its own native conditioning. It does not use the older Edit 2511 Lightning LoRA. Its menu identifies it as experimental. Installed node and model choices have been checked, but GPU quality, speed and 16 GB memory use for the new model branches still need local testing. Additional references can increase memory use substantially.

## Relight

Choose either to create a lighting image from a prompt and optional lighting references, or to upload a finished lighting image. Uploading one does not require a lighting prompt or an installed image generator. Review the lighting image before rendering the video with Wan 2.1.

Wan 2.1 Relight does not load SAM or Depth Anything while preparing or generating the lighting image. The previous text-protection detection was unused by this video recipe. Character replacement still uses a mask where it is needed to target one performer.

## Retry and targeting

Regenerating a starting image always reads the original video at the selected trim start. It never edits the previous generated result. The saved image returns to the original video dimensions. Explicit centre/left/right performer replacements use individual person masks to constrain the image edit and retain the surrounding source pixels. These corrections still require an artist check on the failing multi-person shot.

Camera still generation uses its dedicated workflow. Direct-reference H3 viewport mode and the head-swap workflow retain their existing paths.

Python changes require a ComfyUI restart. Refresh the Studio after restarting. Existing running renders should be allowed to finish first.

## Before and after

The viewer's **Compare** control is available after a starting image is created or uploaded, including lighting images, camera stills and viewport scene plates. Drag the divider to compare with the original frame at the selected clip start. Image comparisons stay paused and hide video playback controls. Finished video comparisons retain synchronised playback against the selected source clip, including its trim offset. Comparison closes during a new render so progress and cancellation remain visible.

Image-stage progress describes image sampling, model loading and decoding. Video stages keep their own progress wording. Flux 3 Klein remains in the standalone Image workspace and is also available from the starting-image picker; it is distinct from Klein 9B.
