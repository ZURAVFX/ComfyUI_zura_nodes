# Studio scope snapshot

Historical scope recorded on 22 October 2026 for Zura Nodes 1.3.28. Later additions are in the [changelog](../CHANGELOG.md); use the [current README](../README.md) for entry points.

Relight now uses Klein to create the lighting image and Wan 2.1 for video. H3 relight video is removed from Studio. Wan 2.1 uses the artist-supplied Switch X recipe after the lighting frame is reviewed: fixed four-step sampling, 81-frame sections, source-matched framing up to a 1280-pixel long edge, 24 fps and restored original soundtrack. The recipe is checked against the running Comfy node schemas and private workflow paths/media are removed. Its parent workflow was artist-confirmed as working well; no new full Studio render is claimed for this integration. Review section joins on long clips.

The Image workspace includes local model readiness, prompt-first generation, native reference conditioning, exact dimensions, saved themes and clearable generation history. These additions preserve existing approved video paths.

Historical approval audit restored **Character performance** with Wan, H3 and LTX, alongside **Viewport to final** with H3. All three character engines retain their approved original-performance, replacement-dialogue and silent-footage paths. See [Approved workflows](APPROVED_WORKFLOWS.md) for the durable acceptance ledger and limitations.

Wan provides precise masked replacement. H3 uses its original reviewed-mask/depth/audio-guided character recipe; surroundings can change. LTX uses the approved whole-scene body-guided character pipeline, not masked inpainting. The common character task dispatches to each native path without rewriting saved projects. H3 Enhanced 1080p remains available for full-character delivery. A separate **H3 → Head & face** choice was approved on 18 October: one portrait or character sheet, one performer, original audio and up to two seconds. It uses tracked crop compositing and the supplied eight-step recipe, preserving the source body and surroundings through compositing. It bypasses starting-image generation.

The latest rejection applies specifically to LTX viewport-to-final. It does not invalidate the three approved LTX character/audio examples. LTX viewport remains hidden. The unapproved H3 maskless Character-Swap LoRA, arbitrary object editing, protected-person background editing and optional post-generation lip compositing stay excluded.

H3 viewport still defaults to Kitchen when supported: the identical train workload took 348 seconds with native attention and 208 seconds with Kitchen. TeaCache remains a private experiment. This speed comparison does not alter the approved character recipes.

The previous reduced-scope audit below is historical and superseded by this capability-specific restoration. Private acceptance records and media remain local.

---

# Previous reduced-scope audit

18 October 2026. Local development change, not a release announcement.

## Available in Studio

**Characters â†’ Character replacement â†’ Wan 2.2 Animate.** Review the tracked person, supply or build the starting look, then animate. Original audio/performance, silent input and uploaded replacement speech remain available through the existing native Wan path. Replacing the soundtrack without creating a new facial performance remains a separate audio choice.

This retains the previously reviewed examples and inference recipes. It does not guarantee arbitrary footage. Long Wan clips can lose detail between sections. No new GPU render or visual acceptance is claimed for this UI restriction.

New shots default to this task and Fast sampling. Native graph access, source previews, reference uploads, prompts, cancellation and comparison stay available. Experimental model choices, object selection, whole-scene tasks and optional lip refinement are removed from the selectable interface. Voice generation is hidden; upload an existing voice track instead. An existing unsupported project stays readable, but cannot submit another job through Studio. Start over to create a verified shot. Existing files are not deleted and recipes are not silently converted.

## Mode-by-mode disposition

| Previous task | Evidence / present concern | Studio disposition |
| --- | --- | --- |
| Wan character replacement | Artist-approved short original/speech/silent examples and longer original-performance take; long-clip degradation accepted | Retained |
| H3 masked character/object edits | Short examples previously accepted, but current user reports mask artefacts; current route differs from character-swap LoRA recipe | Removed pending repair and repeatable Studio validation |
| LTX masked object edits | Separate inpainting template, not approved body-guided pipeline; user reports output mask problems | Removed pending exact-version qualification |
| Whole-scene recreation, H3/LTX | Some approved speech prototypes; current Studio routes and camera retention have separate incomplete qualification | Removed pending task-specific validation |
| Object replacement, one/multiple | Short H3 videos completed and sampled; no conclusive current artist acceptance, plus reported masking failure | Removed pending qualification |
| Viewport to final | Earlier H3 approval; latest adapter awaits review; Wan/LTX viewport results rejected for the test scene | Removed pending validation of the exact current recipe |
| Keep original people / replace background | Latest short result completed; artist review pending and earlier halo failures | Removed pending validation |
| Relight | Latest keep/remove-text videos completed; artist review pending; keep-text can leave darker protection patches | Removed pending validation |
| Seedance | Paid route deliberately not tested | Removed; no API credits spent |
| Extra post-generation lip correction / built-in voice creation | Separate optional tools, not required for approved Wan native speech | Hidden pending a separately agreed scope |

Builders and historical graphs remain in source for development. Studio availability is enforced at HTTP submission/export boundaries as well as in the interface. Installed files or weights do not count as quality approval.

## Mask research findings

H3 character swap and masked inpainting are different routes. The [akatz character adapter](https://huggingface.co/akatz-ai/MiniMax-H3-Character-Swap-LoRA) publishes source-video plus replacement-image conditioning; that recipe does not require an artist mask. Its newer surrounding workflows may use segmentation without making masks intrinsic to the adapter. It is a character recipe, not evidence of arbitrary object editing.

[Fun ControlNet Union 2.0](https://huggingface.co/alibaba-pai/MiniMax-H3-Fun-Controlnet-Union-2.0) supports mask-conditioned video editing. Studio's H3 route uses that control path, not the akatz adapter. Its custom temporal/patch mask expansion can enlarge moving boundaries. Installed Union2.0 metadata and Comfy handling were checked: the simple old/new normalisation mismatch was ruled out. No single cause or completed fix for the user's current artefact is claimed.

The official [LTX in/outpainting adapter](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting) is a 2.3 model. Compare the [official two-stage workflow](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/master/example_workflows/2.3/LTX-2.3_ICLoRA_Inpaint_Two_Stage_Distilled.json) before treating a 2.3-adapter/2.5-base mix as qualified. Studio's legacy template includes boundary/Laplacian handling but also a green masked reference. The separate LTX2.5 body-guided implementation explicitly rejects masked preservation. A coloured boundary could be conditioning leakage; it is not yet a reproduced diagnosis of the user's exact clip.

## Why Studio may be slower

These are code-backed workload differences, not a new timed benchmark:

- Legacy masked H3 pads even a two-second selection to at least124 internal frames, then trims delivery. The published short speed comparison used56 internal frames and cannot predict that route's timing.
- LTX2.5 uses six file-backed phases and frees models between them for memory headroom. Reloads and disk handoffs cost time compared with a warm single graph.
- A fresh LTX run namespace prevents ordinary cross-take reuse of some preparation artifacts, even for seed-only changes.
- H3 references are encoded at matching generation dimensions. Up to nine references can increase workload.
- Old saved Detailed settings can mean40 steps instead of8 for H3 or6 for Wan Fast.
- Replacement speech adds a facial guide stage; enhancement and optional lip correction add other inference stages. Two-second polling delays explain small handoff gaps, not a thirty-minute sampler.

The reduced Studio removes the unused human/object classification preflight for the explicitly people-focused task and hides optional post-processing. It does not change validated model settings or claim a measured speedup. Before optimising a returned mode, compare identical API graphs, internal frame counts, references, steps, precision, attention and cold/warm state.

## Reintroduction checklist

Agree one priority with the artist, then restore only that task after:

1. A minimal model-specific baseline succeeds with the loaded source and references.
2. The intended mask/background, identity, motion/camera, duration and audio survive the complete clip.
3. A Studio render matches the validated graph recipe, with no unexplained extra workload.
4. The artist accepts the actual result and the UI explains the task plainly.
5. Tests, measured timings and limitations are recorded. A failed or pending route remains outside Studio.

Potential next tasks: H3 reference-video character swap without a mandatory mask; dedicated object editing with native mask conditioning; whole-frame character/background recreation; H3 viewport; Relight/background editing; LTX exact-version inpainting; local voice generation.

The artist selected **H3 character replacement without a mask** as the next priority. The isolated `artist_studio/h3_character_swap.py` builder uses the source video, one character image, V1.5 character LoRA and the exact author-tested FL2V Turbo8 adapter. Its seven CPU contract tests pass, including the installed native reference consumer and refreshed live node schemas. Two two-second local renders completed in266.06 and254.62 seconds, but both retained too much of the original face and failed identity qualification. It remains outside Studio and has no arbitrary object-editing claim. Explicit head-and-body prompt wording is now in the developer builder; that final wording has not been rendered.

Wan Animate 2 is now exposed separately as **Character + background**, at the artist's request. It follows Comfy's distilled whole-frame recipe and offers no arbitrary spatial edit mask. Its model setup, native graph and clip limits are checked; local visual quality and speed are still unqualified. It must not inherit the Wan 2.2 approvals. See [setup and current limits](WAN_ANIMATE2.md).

References: [official Animate2](https://github.com/Wan-Video/Wan-Animate-2), [Comfy distilled blueprint](https://github.com/Comfy-Org/workflow_templates/blob/main/blueprints/motion_transfer_wan_animate_2_distilled.json), [native Comfy implementation](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_wan.py).

Historical note: H3 Relight was restored as an explicitly labelled preview on 20 October 2026. It uses original audio and requires review of the lighting frame before animation. The Wan 2.1 route above replaced it on 22 October. Lighting-image generation uses Klein independently of H3.


### Local UI and relight readiness checks (20 October 2026)

The local UI uses bundled daisyUI controls and Web Awesome tooltips/actions, with Source, Look and Settings inspector panels and a bottom prompt composer. Relight hides character replacement controls; lighting prompt input refreshes readiness immediately without requiring references. Overlong H3 sources offer an enabled trim recovery action. DOM regression checks cover these states, upload recovery, native generation handoffs, theme persistence and image references. JavaScript syntax, component build and 23 backend availability/relight checks pass. Installed files were hash-verified. Live Comfy Desktop visual review remains outstanding; no new generation quality approval is claimed. These changes are local and unreleased.
