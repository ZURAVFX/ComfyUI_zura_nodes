# Optional ComfyLink Studio session

ComfyLink can open the existing Zura Studio for a selected After Effects
layer and source interval. The separate After Effects plug-in is optional
and is not bundled with Zura Nodes. Normal Zura Studio is free to open and
use without a ComfyLink licence.

## Working in Studio

Start the session from the ComfyLink plug-in. Studio opens its normal mode
chooser with one compact AE strip showing the target, source status, result
transfer and **Leave**. Choose a mode, load the source and use that mode's
existing controls. **Send to AE** uses the selected finished master, rather
than the displayed preview. A retained result or pending import is not a
successful AE return.

**Leave** exits immediately, including while source loading is pending, and
returns to normal Studio. AE drafts use separate per-tab session storage;
they do not replace ordinary Studio drafts or another tab's work. Session
authority is cleared on departure or expiry. Leaving does not cancel a
running ComfyUI generation or delete its saved output.

The native adapter registry covers character replacement, Ripple, viewport
to final, camera angle, Relight, Paintout, watermark removal, alpha extraction,
frame extension, HDR conversion, Director, first/last frame, reference video
and Image. These 14 adapters connect to existing workspaces. Their presence
does not mean every engine, source format, frame rate or HDR combination has
been qualified end to end.

## Source interval and delivery limits

The AE source supplies the requested frame count **N**, dimensions and exact
rational frame rate. Supported graph preparation keeps N as the delivery
contract. A model may process a larger count **M** on its native frame grid,
for example LTX's 8n+1 grid, then trim internally to N before saving. Prepared
source and returned media must satisfy the active interval. A mismatch must
retain the result with an explanation rather than silently retime it, loop
it, extend it or claim a successful return.

- Main character/viewport and authored Director routes are limited to 24 fps
  for this integration. H3 routes with a fixed native cadence also reject
  incompatible rates. A general rational-rate transport does not make every
  model route compatible with that rate.
- Image mode needs a one-frame source interval. Choose **Current frame** in
  AE for a still return.
- Model frame limits and supported native saver interfaces still apply.
  Longer intervals need a supported long workflow.
- Native HDR conversion and SDR frame extension have frame-contract paths.
  HDR frame extension in an AE session is unsupported.
- High-depth input requires a compatible native media route and EXR support.
  A route that only accepts SDR must reject incompatible high-depth input.
- Unknown/custom ICC conversion remains unsupported. An available original
  master does not establish that AE can import it with the intended colour.

The separate AE client controls layer application and restoration. Its
native import, layer-pair behaviour and licence implementation are outside
this public package and need their own live qualification.

## Whole-shot transfer and resources

FLOAT RGBA transfers have a 16 GiB decoded payload limit. The existing
16,777,216-pixel per-frame limit and the separate AE client's configured frame
limit still apply. For example, 101 frames at 3840 Ã— 2160 need
13,403,750,400 raw bytes, about 12.48 GiB, before EXR caches and retained
copies. Source intervals are not shortened or resized to fit this budget.

Source validation and native FLOAT EXR caching read one frame at a time.
Large source intake needs at least 8 GiB of currently available physical RAM
for frame buffers and OS/AE headroom. Disk admission includes raw staging,
the EXR cache, the native uploader's own copy and safety headroom. Retained
originals and native import copies require further space on return. A resource
check can refuse the transfer rather than fill the disk or reduce precision.

An explicitly requested in-memory IMAGE batch is different from streamed
intake. Larger batches need additional available RAM for RGB, alpha and mask
copies. Model processing also has its own raster, frame, RAM and VRAM limits.
A source fitting the transfer budget does not establish that a model can
render the complete interval at that resolution.

A local synthetic qualification used 101 unique 3840 Ã— 2160 frames at 25 fps,
including negative, over-one, signed-zero and hidden RGB samples. It wrote
13.4 GB of raw FLOAT data, checked actual FLOAT EXRs and returned the same
raw frame hashes. Peak process working set was 1.87 GiB; elapsed time was
about 4 minutes 19 seconds. This did not run AE, a ComfyUI backend or a model.
The explicit disk test is available in
`tests/test_comfylink_large_shot.py`; ordinary test discovery does not run it.

Actual OCIO configuration and working-space strings and SDK handle hashes are
retained as bounded identity metadata when supplied. Their names do not turn
an unknown encoding into ACEScg or another known space. Native AE return with
an unverified OCIO input mapping remains unsupported. The separate client
retains the first inspected colour identity and can stop before capturing the
rest of a large shot. It does not change AE project colour settings.

## Local session boundary

The public adapter runs on the existing ComfyUI server under
`/zura/comfylink/v1/studio`. Discovery exposes a process nonce so the local
supervisor can bind its grant to the intended running instance. This nonce
does not replace authenticated authority. Session grants bind the ComfyUI
origin, target and source/transfer capabilities, with a maximum 15-minute
lifetime. Requests validate local peer, Host, Origin and session credentials.

The launch credential is consumed from the URL fragment and removed from the
address bar. The browser uses a separate ephemeral session capability;
supervisor profile credentials are not exposed to it. Source payloads and
selected original masters have bounded metadata and verified hashes.
Expired or departed sessions revoke access and clean up staged transfers.
Original finished ComfyUI output is retained. Tokens and private extension
binaries must not be put in workflows, screenshots, logs or public archives.

## What the checks establish

CPU tests cover real float I/O, OpenImageIO FLOAT/HALF readback, colour
conversion, native graph frame contracts, local HTTP authentication,
instance binding, departure/expiry and selected-master handling. JavaScript
tests cover adapter routing, isolated storage, exact-frame controls and
precision settings. These are boundary and numeric checks.

Full live GPU generation, After Effects import, fresh installation and
representative shot-quality review across all modes remain outstanding.
Consult the [release notes](../CHANGELOG.md) and
[adapter/high-depth guide](COMFYLINK.md) before relying on a particular route.

## Display-only source preview

In an AE session, **View source** opens a frame preview with OpenColorIO
configuration, display and view controls. The default is **sRGB - Display**
with **Un-tone-mapped** view. Select a frame to inspect it; the source and
exported masters are not changed by these controls. Untagged 8-bit sources
are labelled as an sRGB preview assumption. An unmapped high-depth source is
retained and reported rather than assigned a guessed colour space.

The preview requires the `opencolorio` Python dependency. Standard Studio
generation remains available when an AE session is not active.

## Reusing an open Comfy Desktop window

When the native plug-in is set to use the running Comfy Desktop, the AE
session opens in its verified window. A short one-use window challenge binds
the handoff to that exact Desktop connection; the session credential is not
broadcast to other ComfyUI tabs. Leave AE mode restores the normal Studio
workspace. If the window cannot be verified, choose the Studio window option.
