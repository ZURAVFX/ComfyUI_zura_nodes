# AInVFX Paint a plate

Upstream: https://github.com/AInVFX/ainvfx-paintaplate

Source revision: `d95292c1a96073a34bfec82d7462dbd2887d0000`

The upstream canvas helpers, pressure-aware stroke renderer and light-dab
algorithms are reused under the Apache License 2.0, included in `LICENSE`.
Their original comments and algorithms are retained. `stroke_logic.mjs`
contains selected pure functions from `web/logic.mjs`; `strokes.mjs` extracts
the renderer from `web/app.mjs`, adds ES-module imports and exports
`drawStroke`. These extraction changes are Zura adaptations.

`paintout_viewer.js` adapts those functions to Zura's source-coordinate mask
and guidance assets. Its opt-in mode retains vector strokes for replay and
undo/redo. Ordinary mask editing does not enable the adapter.
