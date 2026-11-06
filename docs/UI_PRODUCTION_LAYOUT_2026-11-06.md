# Studio layout audit · 6 November 2026

Product: an image and video editing workspace for production artists.
Character: calm, direct and precise.
World: a dark editing suite where the media carries the colour.
Moments: the source and result previews.
Signature: lime for the current step and primary action.

The existing charcoal, Manrope and lime direction remains in place. This is a
polish pass using the Unslop guidance by Damir Sokolovsky (@heydamir), CC BY
4.0, https://heydamir.design/unslop. The pass focuses on preview size and
control reachability; it does not replace the existing visual system.

## Finding

The shared minimum preview height was too small when the composer, setup card
or generation progress took space. In the isolated fixture, the main video
preview measured 199 px at 1280 × 720, and the Ripple render preview measured
240 px at 1280 × 800. The shared minimum is now 256 px to 360 px, scaling with
viewport height. These cases measured 257 px and 304 px respectively. When a
short window cannot fit everything, the workspace scrolls instead of
squeezing the preview or clipping the composer.

## Checks and limits

An isolated Chromium fixture loaded Studio's actual modules and styles with
API mutations blocked. It checked the image, main video, first/last frame,
reference video, paintout, watermark, frame extension, camera and HDR
workspaces at 1440 × 900, 1280 × 720, 900 × 700 and 600 × 800. Eleven
loaded-media and progress fixtures also covered Ripple and inpaint. All 75
tested floating menus fit within the viewport. At 1280 × 720, 900 × 700 and
600 × 800, every visible button, summary and select in the empty workspaces
could be scrolled into view. The Studio layout regression suite also passed.

The fixtures use synthetic media and model responses. These checks do not
establish generation quality, all possible plugin states, or accessibility on
every desktop configuration. Captures and measurements are kept outside the
package in the sibling `ui-production-layout-20261106` work folder.
