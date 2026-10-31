# LTX 2.5 two-stage capability matrix

This matrix is limited to the official LTX 2.5 examples and the graphs and
capabilities present in the Zura repository. It separates what the backend can
build from what Studio currently exposes. LTX defines two-stage generation as a
base-resolution sample followed by a 2x spatial upscale and a short refine
pass. Inpaint and native outpaint have a mandatory masked two-stage topology.
Those workflows should not be presented as optional “fast/slow” toggles.

Official references:

- `ComfyUI-LTXVideo/example_workflows/2.5/README.md:5`
- `ComfyUI-LTXVideo/example_workflows/2.5/README.md:32`
- `ComfyUI-LTXVideo/example_workflows/2.5/README.md:48`
- `ComfyUI-LTXVideo/example_workflows/2.5/README.md:50`
- `ComfyUI-LTXVideo/example_workflows/2.5/README.md:116`
- `ComfyUI-LTXVideo/example_workflows/2.5/README.md:118`

| LTX path | Official capability | Implementation in the repository | Exposure decision |
| --- | --- | --- | --- |
| First/last frame and optional audio conditioning | Optional single or two-stage. | `web/ltx_frame_video_recipes.js` now provides a half-resolution base sample, x2 latent upscale, endpoint re-anchoring and the official 3-step refine schedule. Reference audio remains frozen. Fast keeps its separate single-pass-plus-upscale behaviour. | Exposed in advanced settings as **Two-stage · preview**, default off and mutually exclusive with Fast. Live render validation is recorded in `LTX_FRAME_TWO_STAGE_AUDIT.md`. |
| Backend reference-to-video phased graph | Two-stage is preferred for spatial detail. | The phased graph in `artist_studio/ltx25.py` performs stage 1, latent upscale at line 439 or 643, and a second refine sample before decode. | Backend capability only. Studio currently exposes reference-to-video through H3, so this must not be advertised as a selectable LTX Studio mode. A single-stage option would require a separate tested phase graph because it changes cache artifacts and dependencies. |
| SDR inpaint | Mandatory two-stage. | `web/paintout_studio/inpaint_recipes.js:45` prepares masked low-resolution guidance, lines 58-60 blend and upscale pass one, and lines 63-71 refine and blend pass two. | Label as mandatory two-stage. Never offer a one-stage toggle. Stage 2 should get its own noise seed; line 66 currently reuses the pass-one noise link. |
| HDR inpaint | Mandatory two-stage. | It follows the same inpaint topology, with HDR inputs and delivery. | Label as mandatory two-stage. Keep HDR input on its native route. |
| SDR outpaint, native black-mask route | Mandatory two-stage. | `artist_studio/outpaint_studio.py:169-186` delegates native black-mask work to `build_test_graph`; `artist_studio/ltx_outpaint.py:305-322` performs low-resolution sample and blend, pixel upscale and encode, then a short refine and final blend. | Label as mandatory two-stage. |
| SDR outpaint, expand/black-video guidance route | Official reference is two-stage; the currently accepted Studio preview is single-stage. | `artist_studio/outpaint_studio.py:188-233` builds the approved black-video guidance graph with one sample and decode path. | Keep the accepted single-stage route labelled as a preview. Do not expose a two-stage toggle until the official graph has passed real quality and continuity review. |
| SDR-to-HDR conversion | Official recipe is single-stage. | `artist_studio/hdr_delivery.py:48-103` builds one `hdr_sample` and tiled decode. | No two-stage toggle. Long clips use bounded overlapping chunks, not an extra refine pass. |
| Native HDR-to-HDR | Separate tiled/refine workflow, not the SDR-to-HDR recipe. | `artist_studio/hdr_native_graph.py:52-62` has two tiled-fusion samplers with a latent upscale between them. | Keep this as a distinct native HDR capability. Do not map it to the SDR long-conversion toggle. |

## Long SDR-to-HDR admission

The single-pass SDR-to-HDR graph remains bounded by the shared 40-million
pixel-frame budget. `artist_studio/hdr_chunks.py:24` computes the legal
capacity, and `artist_studio/hdr_chunks.py:39` plans overlapping source ranges.
At 1920 by 1080 the capacity is 17 source frames, so a 25-frame request is
split into exact 17-frame and 16-frame ranges with an eight-frame overlap. The
stored delivery remains exactly 25 frames and retains the selected source
audio.

`artist_studio/hdr_chunk_native_job.py:120` is the bounded SDR job entry point.
It rejects Native HDR mode, so an HDR source cannot be accepted by the SDR
conversion runner. Studio should automatically submit SDR selections above the
reported `frameLimit.maxFrames` to that job route. Native HDR selections should
continue through their native HDR readiness and workflow gates.

## Capacity consistency

SDR section planning calls `hdr_prepare.sdr_frame_limit`, the same 32-pixel
raster and budget helper used by readiness. Tests cover non-standard dimensions,
portrait footage and sources wider than 2048 pixels. Native HDR retains its
separate 64-pixel raster and admission rules. No pixel-frame budget was raised.
