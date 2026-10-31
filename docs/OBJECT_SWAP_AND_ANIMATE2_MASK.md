# Object replacement and Wan Animate 2 spatial masks

Development investigation, 31 October 2026. Experimental nodes are not approved
Studio routes. Keep the approved full-frame Animate 2 and masked H3 routes.

## Kagami compared with Zura

Inspected [demoncase/kagami](https://github.com/demoncase/kagami) at tree
`c1ae55b88e48f5b60c469e8e9eb468764fedd75d`.

| Area | Kagami | Current Zura |
| --- | --- | --- |
| Engine | Hosted MiniMax H3 via Comfy Router or the paid partner node | Local INT8 H3, Wan and LTX workflows |
| Object constraint | Source video, object reference, explicit target prompt, optional approved still | Experimental H3 microphone test has a tracked mask and edited anchor; LTX inpaint uses a native mask and painted anchors |
| Preservation | Full-frame generation with a request to preserve everything else | Masked H3 and LTX condition the selected region before sampling |
| Timing | Measures whole-frame motion energy, fits a global time scale and offset, restores source audio | Native source/audio conditioning and exact frame bookkeeping; no equivalent automatic motion-drift measurement |
| Evidence | Demo and hosted route; not run against user's account | Existing gold microphone test was rejected for movement/stability |

Kagami does not introduce an object-specific checkpoint, mask encoder or tracking
algorithm. Its `engine.py` says copy and swap send the same reference inputs and
differ in prompt. `workflow.py` exports `MinimaxHailuo03ReferenceNode`; it is not
a local H3 implementation. A local prompt adaptation is not a hosted benchmark.

Useful experiments: explicit target/reference roles, shape/material/markings
constraints and an approved object placement still. Zura already has the still
mechanism; compare rather than duplicate the UI.

Its `sync.py` correlates small whole-frame motion-energy curves and trusts a
score >=0.45. That can align a dominant dancer but cannot establish microphone
stability, hand contact or lip sync. Camera motion/cuts can mislead the match.
Start with diagnostics and never silently retime a masked result against a
frozen source plate. Retiming can repeat/drop frames; padding is not alignment.

## How the older models use masks

Primary sources: [nodes_wan.py](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_wan.py)
and [model_base.py](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/model_base.py).

- **Wan 2.1 VACE:** a trained control branch receives separately encoded
  inactive/reactive regions, a packed mask and references (`vace_frames`,
  `vace_mask`). This requires VACE-specific weights.
- **Wan 2.2 Animate:** `WanAnimateToVideo` accepts `background_video` and
  `character_mask`, encodes the background and supplies four packed mask
  channels alongside reference/continuation, pose and face conditioning.
- **Generic Wan I2V:** sampler noise masks can constrain source latents. This
  does not add the trained VACE/Animate replacement capability to any checkpoint.
- **Wan Animate 2:** the official node accepts pose/reference/continuation but
  no arbitrary spatial mask. The official pipeline uses uniform known/unknown
  masks for reference/continuation. Its model inherits Wan's image/mask handling
  and has 36 input channels, permitting a spatial-conditioning experiment.
  This is not evidence of spatial replacement training or clean seams.

Checked the official Wan-Animate-2 repository (tree
`3ad2fef7d61d6200c9c653e0fe47be7616b323f3`), current Comfy implementation,
FeiHou-WanAnimate2-Plus, SW-WanAnimate2 and the Wan Animate 2 loop sampler.
No demonstrated equivalent of the older native masked replacement was found
there. This is a bounded search, not proof nobody has one. FeiHou's loop path
explicitly rejects a denoise mask; its reference mask is not spatial masking.

## Zura prototype

`wan_animate2_mask.py` adds developer node `ZuraWanAnimate2SpatialMask` between
native `WanAnimate2ToVideo` and the unchanged sampler. White edits; black keeps.

1. Apply matching proportional centre crops to source and tracked mask.
2. Grow the mask and conservatively pack it: first frame, then groups of four.
   Optional solid-hole filling, max-occupancy blocks (8–64 output pixels) and a
   short temporal margin create a more generous edit envelope.
3. Encode the masked background and attach it to both conditioning branches,
   preserving reference, pose and known continuation cells.
4. Optionally seed from original source latents and constrain the background
   with `noise_mask` at every sampler step.
5. Trim the reference and decode normally. No output RGB compositor.

An alternative leaves the official conditioning untouched and constrains only
the sampler. This avoids passing unfamiliar spatial mask edges into the model.
Both variants retain the native character reference and pose conditioning.

Latent locking preserves encoded background, not exact RGB. The lossy VAE can
mix boundaries. Compare a source VAE round trip and inspect moving edges,
wider replacement shapes and foreground occlusions. Unit tests cannot qualify
these visually. No unverified Studio option is enabled.

## Checklist

- [x] Audit Kagami's engine, prompts, timing and workflow export.
- [x] Compare with existing local object-swap/inpaint implementation.
- [x] Inspect old Wan masks and Animate 2 conditioning/model internals.
- [x] Search selected community extensions for spatial-mask support.
- [x] Add isolated spatial-conditioning/background-lock node.
- [x] Eleven tests: causal masks, source/reference preservation, continuation,
  held tails, immutable metadata, static masks and mismatched input rejection.
  Includes conservative blocks, enclosed holes, bounded temporal margins and
  sampler-only conditioning with one source VAE encode.
- [x] CPU integration with real Comfy native conditioning, concatenated mask
  channels, mask preparation, sampler constraints and reference trimming.
  VAE and denoiser are deterministic test doubles; this is not visual evidence.
- [x] Complete same-seed baseline, conditioning-only and background-lock GPU test.
- [x] Compare source/VAE/raw outputs: motion, seams, drift, boundary flicker.
  User approved the displayed sampler-only full-character comparison on
  31 October 2026: “Looks acceptable.” This approval covers that preview.
- [ ] Qualify occlusions, camera motion and wider replacement on a second shot.
- [ ] Compare anchored masked local H3, Kagami-style unmasked local H3 and LTX
  inpaint with matched source/target/size and measured speed.
- [ ] Hosted Kagami comparison requires a separately authorised paid run.
- [ ] Enable Studio only after visual qualification; do not promise flawless
  blending or trained replacement merely because the model accepts a mask.

Fetched code, search results and test artifacts:
`work/zura-release/work/openjutsu-benchmark/kagami-mask-research` in the workspace.

## Real GPU results, 31 October 2026

The initial memory issue was resolved by separate preparation, sampling and
decoding processes, preserving the native model/settings and leaving WSL alone.
Three real 49-frame, 512×896 tests completed at 24 fps, seed 20261027, distilled
INT8 ConvRot, 10 LCM steps, CFG 1, shift 5, native CPU/int8 pose cache:

| Method | Sampling job | Result |
|---|---:|---|
| Native full-frame baseline | 110.49 s | Clean reference character, regenerated background |
| Spatial background conditioning | 109.50 s | Strong coloured fringe; background not constrained |
| Spatial conditioning + sampler lock | 108.62 s | Background latents retained, but coloured fringe remains |

The locked latent maximum absolute error outside the edit envelope was
9.54e-7. This proves the constraint operates, not that decoded pixels are
identical. A source VAE round trip and raw decoded outputs were saved. The
conditioning variant is not suitable for Studio in this state.

Two follow-up renders completed with a 32-pixel-grown, 32-pixel-blockified,
hole-filled mask and one-frame temporal margin:

| Method | Sampling job | Result in inspected first/middle/last frames |
|---|---:|---|
| Expanded envelope, spatial conditioning + lock | 109.69 s | Coloured fringe follows the larger block boundary |
| Expanded envelope, sampler lock only | 109.49 s | Clean character and no coloured fringe; background retained |

The node now defaults to the sampler-only method. The far-background mean
absolute RGB difference (8-bit levels) is 2.84 versus source, compared with
2.74 for the source VAE round trip and 32.19 for the full-frame baseline.
The common measurement region excludes an 80-pixel source-mask margin and
covers only 13.7% of this shot; these are not boundary or identity scores.
The maximum frozen-latent error remains 9.54e-7. Decoding took about 6 seconds;
these sampling timings exclude separate preparation, server start and decode.

Artifacts and timings are in `staged-envelope/report.json`; the playable
side-by-side is `source-vs-masked-animate2.mp4`. A tight head-region scope test
is recorded separately in `staged-head`: 108.71 seconds sampling and 7.13
seconds decode. It uses a coarse head-region envelope (16-pixel growth/blocks),
not a newly tracked face mask. Inspected frames retain the original outfit
and replace the head without the coloured fringe. Frozen-latent error is
again 9.54e-7; the outfit region below output row 400 differs from its VAE
round trip by 2.61 levels on average. This is another scope on the same shot,
not independent validation on a different camera or occlusion.

The experimental developer node is installed locally with backup
`installed-mask-node-20261031-134324`; normal ComfyUI needs a restart to load
it. The installed root file was preserved and only the new registration was
appended. Nothing has been publicly released. The full-character mask route is now
integrated locally as a preview beside the existing whole-frame route. The user approved the
displayed sampler-only full-character comparison on 31 October 2026 (“Looks
acceptable”). Use this exact recipe as the Studio integration baseline.
Wider silhouette, occlusion and different-camera tests remain separate
verification tasks. The Studio adapter uses the already-reviewed interval,
not another SAM pass or a second seek into the selected clip. Source and mask
share the same transform, their final frame is held to the model grid, and
the exporter explicitly keeps the model dimensions. The head-region test has not received
separate user approval.

### Reproduction

`Wan_Animate_2_Masked_Replacement.api.json` in the artifact directory is a
debug/reproduction API graph using the exact native model, source, reference,
mask and sampling settings. It is not an artist-layout workflow. The source,
tracked FFV1 mask and approved starting image are in `test-base/input`; copy
or upload them into the running server's input directory before using that
API graph. White changes, black preserves. At the node, leave background
locking on and experimental background conditioning off. Preserve the normal
reference trim after sampling. Both source and mask must have matching frame
timing and proportional crop; do not independently stretch either.

## Body Double masking lessons

Reviewed [Body Double's mask/media code](https://github.com/lucataco/open-source-higgsfield/blob/864c8de28d4a9e29bebc0529c434f7855e5cb04b/bodydouble/media.py)
and [generation/assembly runner](https://github.com/lucataco/open-source-higgsfield/blob/864c8de28d4a9e29bebc0529c434f7855e5cb04b/bodydouble/runner.py),
plus the repository's demonstration. The X video endpoint could not be fetched
by the video tool; the linked repository demo was accessible.

The generation model is SCAIL-2. Much of the background preservation is an
explicit final RGB composite into the original plate. Useful ideas include:

- Union source and generated-character masks, covering wider hair/clothing.
- Close short tracking dropouts in source coordinates, rather than the moving crop.
- Align generated frames to the original background before comparing masks.
- Extend the generated matte through nearby connected image differences.
- Dilate/feather the composite boundary, colour-match and filter fine flicker.

These techniques do not establish native Animate 2 mask training. The bounded
temporal edit envelope and broader mask coverage can be used before sampling;
generated-mask union and RGB feathering belong to a separate final-composite
option, not a claim of native latent masking. Avoid silently applying its long
24-frame mask holds across foreground occlusions or deflickering moving detail.

## Local Studio integration verification (31 October)

Animate 2 now offers Keep original background (preview) and Replace character +
background. Existing whole-frame saved shots retain their choice. The masked
route uses automatic full-character selection, the already-reviewed source and
mask, and the approved sampler-only recipe. Head-only and object scopes are not
exposed by this new route. Missing mask-node readiness is separate from the
existing whole-frame model check.

The real installed Studio graph completed a 49-frame, 464×832, 24 fps GPU test
with original audio in 111.73 seconds from submission through export, excluding
server startup. The output dimensions/frame count/audio track were probed and
first/middle/last frames inspected. This is an integration check on the approved
shot, not independent approval on another shot. The exporter pins native model
dimensions so reviewed-source export metadata cannot stretch the generated image.

Validation: 26 Animate 2 CPU tests, 11 shared availability tests and the existing
and new JavaScript route/control checks pass. The new checks cover both background
choices, retained saved whole-frame selections, mask readiness, disallowed scopes,
reviewed-interval reuse, held tails and sampler connections. The owned test server
was stopped; WSL and the user's other Comfy instances were left running.

Artifacts: `kagami-mask-research/studio-integration/report.json`,
`studio-mask.api.json`, and `output/genj/final/studio_mask_stu_wan2_00001.mp4`.
Selective installation backed up the three changed production files under
`studio-mask-install-20261031-164549`. The installed root and extra browser-image
routes were preserved. Restart normal ComfyUI to load the local update. There has
been no public release.
