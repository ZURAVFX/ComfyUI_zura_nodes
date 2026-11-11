# UI refinement, 11 November 2026

User evidence: Paint/Remove/Replace displayed a full-width action, a crushed prompt, duplicate removal choices and an empty timeline before a source was loaded.

## Repaired

- Bound primary action widths independently of the prompt; responsive prompt rows retain usable typing space.
- Empty workspaces show source import, with editing actions and timeline appearing after footage loads.
- Inactive workspaces cannot be revealed by legacy layout overrides. This fixed Paintout fragments appearing above frame extension and other modes.
- Inline image-completion updates now reach the workbench. Use edited frame, Try again and New edit are available in the appropriate state.
- A visible cancel action routes to the owned image, mask or video job.
- Processing controls lock during runs; the small-screen settings panel closes with Escape/outside interaction.
- Removal scope has a visible label and the fixed Paintout model is presented as a value rather than a disabled selector.

## Evidence

- Isolated-browser sweep: 13 mode entries at 1920x1080, 1280x720 and 900x700. No visible horizontal control overflow or JavaScript errors after the fixes.
- Loaded frame-edit checks: prompt widths approximately1285/645/584px, action width127px, preview container heights711/391/319px at those sizes.
- Real source import, trim, drawing upload, CPU-made result handoff, retry action and operation switching checked without AI generation.
- Twelve targeted JavaScript suites passed, including layout, mode/reset navigation, model installation/access, starting-image controls, camera controls, image-area ownership, keyframe handoff and AE bridge.

This is a UI/data-flow check, not generative-quality qualification. Browser evidence is kept outside the distributable source under ui-integration-20261111.
