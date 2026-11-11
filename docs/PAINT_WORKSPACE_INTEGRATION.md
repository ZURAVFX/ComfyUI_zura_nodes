# Shared paint workspace development

Design reference: [AInVFX Paint a Plate](https://github.com/AInVFX/ainvfx-paintaplate), inspected at d95292c1a96073a34bfec82d7462dbd2887d0000.

## Product direction

Use Paint a Plate's canvas-first interaction model as the direct layout reference: tool rail, one prompt, large picture, editable layer stack and compact feedback. Preserve Zura's thumbnail timeline, source-frame keyframes, H3/LTX choices and approved native Paintout removal method. The Paintout workspace owns the project across Paint, Remove and Replace. Public navigation has one entry; existing ComfyLink adapter IDs and saved workflow aliases remain valid.

Keyframe image editing is embedded into the same workbench with the source timeline retained. Regenerating a selected edit replaces that edit's layer and retains earlier versions. New edit starts a separate layer. Each edit is generated over the layers before it, then recomposed against the original source using its own mask. Visibility, opacity, layer order, edge blending and brightness are reversible CPU operations.

## Precision findings

Upstream separates source values, AI working values and viewing values. Its WebGL display uses OCIO source-to-linear and display/view transforms. Interactive EXR buffers are HALF; this is a preview choice, not proof of full FLOAT preservation. Its EXR writer copies original parts, channels, header metadata, overscan and untouched original samples before replacing selected RGB values.

Zura's layer compositor already works in float and preserves samples outside an active mask; new numeric checks include negative values, values above one, opacity and hidden layers. This does not establish preservation of arbitrary multipart EXR metadata or non-RGB channels through every Studio workflow. That needs a dedicated source-format-preserving writer and integration evidence.

Generic Image/Ripple handoff is currently an SDR PNG guide path. Paint/Replace must not silently use it on a native HDR plate. Native Remove/HDR Paintout remains available. Coordinate the shared OCIO preview with the ComfyLink display work; never bake viewer exposure or display transforms into the original or delivery master.

## Current validation and remaining work

Unit checks cover shared project/anchor identity, model-specific reference selection, source frame rate, area ownership, drawing regions, float layer blending, AE adapters and exact-frame contracts. Isolated browser tests exercise source import, trim, drawn guide uploads, edited-frame return as a layer and switching operations. These browser checks use a CPU-made image and do not prove generative quality.

The redesigned canvas layout is under visual verification. Current changes are in the development worktree, pending coordinated integration with ComfyLink's OCIO/Desktop checkpoint and installation. Do not present the development version as published or fully qualified. Full edited-shot quality, native HDR preservation across every route and source-format metadata retention remain separate checks.
