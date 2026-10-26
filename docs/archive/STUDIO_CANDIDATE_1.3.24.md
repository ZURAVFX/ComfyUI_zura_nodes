# Zura Studio 1.3.24 release candidate, 17 October 2026

> Historical snapshot from 17 October 2026. This describes the 1.3.24 candidate. Use the [current README](../../README.md), [installation guide](../../INSTALL_STUDIO.md) and [changelog](../../CHANGELOG.md) for current instructions.

This candidate is on the development branch. It has not been published as a
stable release. The current stable release and this candidate are separate.

Zura Studio belongs to the official Zura Nodes package. Use the
[official release download](https://github.com/ZURAVFX/ComfyUI_zura_nodes/releases)
and [installation guide](../../INSTALL_STUDIO.md). Comfy Registry review is separate
from GitHub distribution; Manager availability requires Registry approval.

Start ComfyUI, refresh its interface and click **Zura Studio**. Choose Wan 2.2,
MiniMax H3 or LTX 2.5 in the same project. Original audio and performance,
reference audio with a new performance, and silent footage share the same
controls. Optional Seedance remains available; no paid Seedance tests were run.

Choose the task first:

- **Motion transfer** guides a new look with the source movement. With H3,
  **Keep original people** changes the surroundings while retaining the people.
- **Object swap** selects one or more people or objects to replace.
- **Viewport to final** turns a grey blockout into a finished scene. H3 is
  recommended; LTX is experimental and Wan is not offered for this task.
- **Relight** builds a lighting-frame preview from a prompt and optional
  reference images, then guides H3 with that approved frame.

Prepare the selection, approve it, then create an appearance preview or choose
**Use starting image**. Your character reference stays selected separately.
Choose **Animate this look**; preparation and file handoffs are automatic.
**Graph view** opens the current editable ComfyUI stage.

The interface includes model recommendations, measured speed and memory
guidance, and a checklist of required files for the selected model. Media
uploads stay within ComfyUI's input/output/temp folders. Download remote
clips yourself before uploading. Optional setup helpers print dependency
installation commands for you to run; they do not install Python packages.

All nine exact five-second model/audio examples have artist approval. A fresh
automatic LTX Studio run also completed all six native phases and delivered a
five-second 1080p portrait video with its original soundtrack. The earlier
approved starting image was preserved exactly. This integration result has
been screened separately from the approved prototype videos.

New two-second H3 renders cover a single object, multiple objects, a whole
scene and character, surroundings with protected people, viewport rendering
and sustained relighting. Sampled frames have been inspected; artist review
of these newer examples is pending. The final viewport test retains all 48
source frames and the exterior camera push-in. The corrected Relight
text-removal test keeps the lighting without the earlier returning title.
These short checks do not establish long-shot or arbitrary-subject reliability.

The latest regression checks pass 749 native CPU tests and all 27 JavaScript
test files. Setup checks follow the selected route's actual models and nodes.
The conditioning fixes and final three-file readiness/text-preparation patch
are installed locally after an idle shared-queue check, backup and normal
ComfyUI restart. Live graph exports, per-route setup status and served-script
hashes pass. These API checks do not replace the final visual interface review.

Remaining qualification limits:

- LTX whole-scene motion/audio generation supports up to five seconds at 24 fps.
  Masked LTX speech and longer continuation remain experimental.
- Replacing a viewport environment can lose its camera movement. Correct target
  scenery does not establish correct camera or ground geometry. The tested H3
  train example is a bounded success; the rejected Wan/LTX examples are not
  presented as qualified alternatives.
- Keep original people reconstructs moving boundaries generatively; it is not
  a pixel-exact cutout. Check hair, hands and occlusions.
- Relight can leave darker background patches when preserving source captions.
  Remove on-screen text has a separate successful short test, with artist
  review pending.
- Longer H3 speech is not qualified. H3's approved 1080p examples use enhancement
  after native 720p generation; native 1080p has a separate memory requirement.
- The accepted full-length Wan example has some detail degradation between chunks.
- Desktop/mobile visual checks and rendering from the edited Wan Graph namespace
  remain open. Manually queued Graph jobs do not automatically advance Studio.

The package includes code, neutral workflows and documentation. Private voice
recordings, test videos, transcripts, scripts and model weights are excluded.
See [validation details](../../ARTIST_STUDIO_VALIDATION.md) and [Studio guide](../../ARTIST_STUDIO.md).
