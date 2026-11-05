# Studio UI cohesion audit · 5 November 2026

Direction: a calm editing workspace centred on the user's footage. Preserve the charcoal/Manrope/lime identity. Use the same model, workflow and output control order. Put review tools alongside the preview and the primary action with the prompt. Keep explanations only where they affect a decision.

Craft guidance: Unslop by Damir Sokolovsky (@heydamir), CC BY 4.0, https://heydamir.design/unslop.

## Findings and changes

- Preview collapse: a missing-model card could reduce the main video preview to 24 px at 1280 × 720 in the browser fixture. Shared minimum preview space and non-shrinking composers now prevent that collapse. At small sizes or with expanded controls, one workspace scroll area keeps everything reachable.
- Nested scroll areas: removed integrated Paintout/Ripple/Watermark composer and mask-tool height caps. Timeline/history lists retain scrolling where content is inherently variable.
- Progress overlay: image, main video, first/last frame, reference-video, HDR and camera progress now sit outside the image. Paintout already used an external progress row. Live samples continue to use the full preview.
- Inconsistent headings/actions: aligned workspace headings to the 1200 px preview/composer width; standardised Start over; moved image review tools to the right; placed Clear history inside History; removed duplicate generic composer headings.
- Cramped model labels and attachment names: widened the shared model slot; allowed the optional last-frame attachment to size to its label; kept model/workflow order intact.
- Overloaded setup: retained install size, install action, setup details and model folders; removed duplicate refresh actions and unused spacing; made primary/disabled contrast consistent.
- Dropdown clipping: position floating controls within the actual window, choose above/below according to space, and recalculate after resize, scroll and panel resize. Preserve DOM ownership, keyboard operation, Escape and outside-click dismissal. Reset inherited panel margins so tall Models menus remain inside the window.
- Repeated HDR copy: removed the second visible title and shortened the Rec.709 explanation, retaining colour/export limitations.

## Validation

No AI generations or user-desktop automation. An isolated headless Chromium fixture loads the real Studio modules and styles. API mutations are blocked.

- Nine main workspaces checked at 1440 × 900, 1280 × 720, 900 × 700 and 600 × 800.
- Loaded-media/stage fixtures cover image, main video, first/last frame, references, paintout, watermark, Ripple, inpaint, frame extension, camera and HDR. Synthetic progress tests presentation, not renderer quality.
- 75 floating-menu placements passed viewport bounds checks, including light theme, with no off-window panels.
- 15 targeted Node regression suites passed: navigation/state, shared layout, menus/keyboard placement, reset, model setup, HDR, camera navigation, Ripple/Paintout, previews/zoom and image recipes.
- Small-window and expanded-setup layouts may require page scrolling. This is deliberate: controls remain reachable instead of compressing the preview into a strip. Not every possible plugin, operating-system scale or data-dependent state is covered.

The local browser fixture, measurements and before/after captures are in the sibling `ui-audit-20261105` work folder. They are test evidence, not real generated results.

## Separate model integration

Qwen Image 2.1 and full FLUX.2 dev are optional Preview entries in Image → Edit image, using the installed INT8/CPU-cache and NVFP4 recipes respectively. Graph regression and catalogue tests pass. No quality comparison or GPU generation was run in this UI pass. ComfyUI was offline during final deployment, so live backend validation remains for the model testing phase.
