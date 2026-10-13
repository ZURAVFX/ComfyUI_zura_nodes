# Release notes

## Unreleased

- Add a visible H3 sampling-step control, saved with each shot and passed to both native H3 schedulers. Preserve legacy 8/40 defaults and label custom counts unbenchmarked.


- Rebuild Studio around source/look, real preview and shot-settings panels with the user-approved navy/violet styling.
- Make oversized original-length recovery actionable without queuing a render, and expose Cancel run beside live progress.
- Preserve visible native image loaders and their exact file paths when opening an editable graph.
- Explain H3 Fast 8-step versus Detailed 40-step costs, retaining reference detail and explicit quality choices.


- Show native sampling steps, stage progress, elapsed time and measured stage estimates; unknown loading stages remain indeterminate.
- Simplify Studio controls and keep progress below the preview on mobile.
- Add local CPU subject checks and manual People / Objects overrides. Explicit LTX objects use Canny guidance; Wan Animate explains its human-performance requirement.


- Recommend H3 for Viewport to final and select it when entering that mode.
- Remove Wan from viewport choices after the whole-scene quality review;
  preserve its motion-transfer, swap and speech routes.
- Mark LTX viewport quality experimental. Match the official ancestral
  refinement sampler and full-canvas guide encoding, with fresh cache keys.
- H3's viewport example is artist-approved. Wan and LTX's earlier viewport
  integration renders were rejected; successful execution was not approval.

## 1.3.13

- Adds **Viewport to final** for turning a grey 3D blockout into a finished
  scene, with an optional mask to limit the changed area.
- Routes the source through each engine's own guidance: LTX 2.5 uses its raw
  layout adapter, MiniMax H3 uses the source as a reference video, and Wan 2.2
  prepares pose guidance.
- LTX preserves the exact selected duration by padding the guide for sampling
  and trimming the decoded result back to the source frame count.
- Supports up to fifteen seconds for LTX Viewport to final. Other LTX Studio
  routes and MiniMax H3 remain limited to five seconds; Wan processes longer
  clips in sections.
- Does not add a blanket Canny or depth pass. In the tested LTX scene, depth
  guidance softened the image and shifted details. The raw layout route stays
  the default; Canny has not been qualified.

Install or update **Zura Nodes** through ComfyUI Manager by searching for
**Zura Nodes** from **ZURAVFX**, then restart ComfyUI. Model weights are separate
downloads. See [the Studio install guide](INSTALL_STUDIO.md) for the exact files
and setup steps.

The three local viewport routes completed five-second, 720p integration runs.
The exact viewport outputs still need separate artist review; they are not
included with the package. No private source media or audio is included.
