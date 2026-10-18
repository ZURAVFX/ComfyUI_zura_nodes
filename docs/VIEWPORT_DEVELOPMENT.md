# Viewport to final: local development evidence

18 October 2026. No release or new artist acceptance is implied.

## H3 speed comparison

Same anime train source, five appearance references, two seconds at720p,56 internal frames, seed42, Ref2VAINT8ConvRot and DMDRef2VATurbo8. All histories reported zero cached graph nodes. Times include preparation, sampling and export; small polling overhead is included in the three new comparisons.

| Settings | Seconds |
| --- | ---: |
| Native attention, res_multistep |348.3|
| Kitchen attention, res_multistep |208.4|
| Kitchen + TeaCache .15, steps2 through5, res_multistep |154.1|
| Kitchen + same TeaCache, Euler |153.2|

Kitchen saved about40% against this native baseline. Sampled frames retained the scene and camera progression closely. New viewport selections choose Kitchen when the running server reports support; saved configurations retain their explicit attention choice. Artist review of the actual video remains separate.

TeaCache is approximate and changed details/framing in sampled frames. It remains a private experiment, not a Studio default. Its installed implementation also retains per-node state, so repeated-run/cache behaviour needs a separate check before shipping. Euler showed no meaningful further speed gain here. These tests do not establish a universal fastest recipe.

The FL2VA plus FL2VTurbo8 recipe belongs to first/last-frame generation. The viewport uses Ref2VA video and multiple-image conditioning. Do not substitute the FL2VA weights simply to match a single-still benchmark.

## LTX findings

The corrected Layout-to-Render plan uses video-only sampling, version-matched2.5adapter, INT8ConvRot distilled base, CFG1, Eulerancestral,8steps at960x544 then3steps at1920x1088, cropped to1920x1080. Source audio is restored separately when present. Its six phases are file-backed to fit16GBVRAM; loading and handoffs add time over a warm monolithic graph.

The first corrected five-second test completed but retained the blocky driver. It is a failed visual qualification. It used an aligned opening still from the previously artist-approved H3 train render. A first-frame reference alone provided no clear view of the interior driver.

The [official model card](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-Layout-To-Render) recommends a finished first frame at temporal position-1 and additional middle/last keyframes, applied in both stages. A completed private test added aligned frames72and119 and Kitchen attention. It delivered120frames at1920x1080 in280.3seconds, including all six phases. The driver changed from the block figure into an anime character. Sampled later frames still show distortion around windows/doors. Refinement took124.3seconds compared with182.0seconds in the single-opening native-attention run, but the added keyframes mean this is not a pure attention-only comparison. This is independently sampled LTX output with H3 frames used as image guides. Do not describe it as LTX reconstructing those appearances from the opening image alone.

Artist review, 18 October: the multi-keyframe result is substantially worse than H3. The artist requested LTX viewport be removed from Studio for now. LTX viewport remains a local development prototype only; further geometry repairs and multi-keyframe UI work are deferred. Do not restore it to Studio without fresh visual qualification and artist agreement.
