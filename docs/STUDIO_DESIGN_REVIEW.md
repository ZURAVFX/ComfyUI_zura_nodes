# Studio design review: composer and canvas

The approved direction is a neutral, canvas-first workspace with attachments, prompt, settings and the primary action grouped in that order. This pass inspected the image, guided video, first/last frame, reference-to-video, frame extension and integrated paintout layout sources, plus desktop and narrow browser renders of the reference-video composer.

The main issue was a series of fixed textarea heights, including 44–56 px overrides on short screens and image mode. Long directions could be clipped and the field could not be expanded. The shared composers now show multiple lines, do not shrink inside flex layouts and can be resized vertically. Keyboard focus has a visible outline. Frame extension and paintout use the same writing-space principle.

At narrower widths, settings and the action wrap together and reference-video controls use the same bounded panel behaviour as first/last frame, retaining access to long content and controls. The preview remains the primary area on desktop. A real working Studio session, media attachments and generation states still need visual review in ComfyUI; the static browser fixture does not prove all application states or native desktop sizing.

The implementation leaves the existing charcoal palette, theme, model choices, generation behaviour and order of controls intact. Impeccable context reported that PRODUCT.md uses an older schema and its generated design sidecar predates DESIGN.md. Refresh these separately with Impeccable init/document if desired; they were not changed during this pass.
