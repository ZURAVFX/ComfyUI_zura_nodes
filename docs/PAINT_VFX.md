# Paint VFX conditioning contract

Paint VFX is a separate Create a shot workflow. It generates an SDR RGB effect shot from painted keyframes and a prompt. It does not use Add/Replace's edited-frame Ripple propagation or regular image-to-video endpoint conditioning.

## Reference and model

The reference is [AInVFX Paint a plate](https://github.com/AInVFX/ainvfx-paintaplate), inspected at `d95292c1a96073a34bfec82d7462dbd2887d0000`: `web/logic.mjs` (`FLUID`, `keySlots`, `fluidPrompt`), `web/app.mjs` (`generateFluid`), `web/workflows/fluid.json`, `nodes.py` (`KeyframeVideo`) and `mathops.py` (`keyframe_video`). The current [official ainvfx-fluid model card](https://huggingface.co/AInVFX/ainvfx-fluid) supplies the model and control rules. It describes a retrained model using synthetic clips from 1 November 2026; older copies are not interchangeable for provenance purposes.

The official adapter is `AInVFX/ainvfx-fluid/ltx-2.5/ainvfx-fluid.safetensors`, revision `6acb88df82c38a1f288a8f94fbd8b70eb5f975fb`, size 654446320 bytes, SHA-256 `167b4ccfd3ed5e95c7973a0233f8fbd8edb5e9182ecb3998bd972661c861ebaa`. These values were read from the publisher's Hugging Face repository API. It uses the [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x).

Setup package `ltx_paint_vfx` reuses Studio's pinned LTX 2.5 distilled transformer, Gemma4 INT8 text encoder, video VAE and audio VAE. Only the additional fluid adapter needs installing when those files are already present. Catalogue inspection never starts a download; the existing explicit Setup models flow handles access, publisher terms, download and hash verification.

## Source and control images

Each key is an opaque, display-referred sRGB image containing flat painted colours, optionally over a background image or colour. Flattening a background into a key is a model input operation. It does not replace, convert or reclassify the artist's original file, HDR source, raster or bit depth. Keep the original background asset separately.

`ZuraPaintKeyframeVideo` takes `width`, `height`, `frames` and `keys`, a JSON list of `{frame: integer, image: "input-relative/path.png"}`. Its output at slot 0 is an `IMAGE` batch, CPU float32 RGB `[T,H,W,3]`. Every unkeyed frame is exactly black. A key image is scaled to the selected control raster with nearest-neighbour interpolation, without hidden cropping or frame interpolation.

Frame 0 and the last frame are required. Intermediate keys use `1 + 8n`, matching the LTX first-frame special case and the reference's `keySlots`; this is not a grid of frame indices divisible by eight. For 121 frames, examples are 0, 1, 9, 17, ..., 113, 120. Up to 33 selected keys are allowed. Dimensions are 256–1920 pixels, in multiples of 64. Length is 9–321 frames with `8n+1` total frames. Rates are 24, 25 or 50 fps. Default is 512 × 512, 121 frames, 24 fps. The sparse control tensor has a 512 MiB CPU allocation ceiling, computed before allocation. For example, 960 × 512 at 81 frames is also within this ceiling.

The backend validates input-folder confinement, image decoding, opaque eight-bit image formats, dimensions, key ownership, content changes and resource limits. A normal model-view image is not a native float/HDR master.

## Exact inference graph

`studio_paint_vfx_recipes.js` uses the same pinned transformer/text/VAEs and distilled eight-step schedule as Studio's normal LTX 2.5 first/last-frame recipe. It changes the conditioning path:

1. Load the sparse RGB control batch through `ZuraPaintKeyframeVideo`.
2. Apply `LTXICLoRALoaderModelOnly` with the fluid adapter at strength 1.0. Use its output 1 as `latent_downscale_factor`; the publisher's adapter is expected to report factor 2.
3. Feed the whole control batch to `LTXAddVideoICLoRAGuide` at frame index 0, strength 1, crop disabled, using the matching empty video latent and video VAE.
4. Prefix the prompt with exactly one `ainvfxfluid` trigger. Use the reference negative prompt, CFG 1, `euler_ancestral`, and the standard distilled eight-step sigma list.
5. Generate audio tokens, concatenate AV latents, sample once, separate AV latents, crop conditioning frames, decode with the normal Studio video/audio VAEs and save through `CreateVideo` / `SaveVideo`.

The first implementation deliberately has no Fast, two-stage, reference-audio or alpha branch. Those controls must not silently alter this recipe. It uses optional Comfy Kitchen attention when advertised, otherwise the normal PyTorch/native fallback.

## Delivery

The generated result is ordinary SDR RGB sRGB video with generated audio. It remains compatible with Studio's existing output/delivery handling. The workflow does not promise a transparent explosion, native HDR generation, preservation of a background's source pixels, or float EXR generation. Alpha extraction is the separate explicit LTX Alpha operation. HDR delivery, when explicitly selected, must use Studio's existing SDR-to-HDR postpass and preserve its generated provenance. Keep a review preview distinct from any later HDR or alpha derivative. No painted display outline, cursor, editor tint or ROI overlay is part of a saved control key.

## Validation

`tests/test_studio_paint_vfx_recipes.mjs` checks the conditioning route, adapter factor connection, typed graph edges, pinned model readiness, sampler/decode baseline, input immutability, prompt trigger, key grid and memory guards. `tests/test_paint_vfx_keyframes.py` covers the backend control tensor and asset validation. Graph tests do not claim generated effect quality or GPU success.

## Workspace

Choose **Create a shot → Paint VFX** in the video-mode picker. The canvas opens in Draw, with separate first and last painted-key cards. Add intermediate cards from the allowed frame list. Draw, erase, undo, brush colour/size, pan and fit reuse the same source-space viewer as Add/Remove/Replace. An optional SDR background image or background colour is composed beneath the sketch. Changing the background or raster invalidates the flattened controls and rebuilds all painted keys before the next submission, while retaining the editable sketches.

Workspace storage contains file references and settings, not full canvas PNG strings. Key commits upload an editable sketch and a separate opaque model-control image. Clear paint invalidates that key until repainted. Submissions retain their own immutable key and prompt snapshot; later drafts cannot change a queued run. Refresh models retries a failed viewer load without overwriting saved paint. Results retain exact width, height, frame count and frame rate in the shared output descriptor. The normal global HDR delivery binder can create an explicit postpass while retaining the SDR take.

This initial independent-asset mode explicitly rejects an active AE source session or source ingestion. It does not fabricate an AE range, resize a source or promise a qualified AE roundtrip. Leave the AE source session to create the asset. Existing AE editing modes remain unchanged.

`tests/test_studio_paint_vfx_ui.mjs` exercises painting, asset-only persistence, key ownership, background rebuild, queued snapshots, result descriptors, navigation and AE guards. `tests/check_paint_vfx_geometry.py` uses an isolated intercepted HTTP fixture with the real canvas at 1280 and 760 pixels, without connecting to the user's running app or model server.
