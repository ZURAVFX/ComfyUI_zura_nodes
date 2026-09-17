# Third-party notices

Zura Nodes' original code is licensed under AGPL-3.0-only. Copyright (c) 2026 ZURAVFX.

## KJNodes BlockifyMask

The `_blockify_internal` implementation in `mask_performer.py` is adapted from
the BlockifyMask implementation in [ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes),
by kijai and contributors. Reference source: `nodes/mask_nodes.py`, commit
`996b010ae4613ae0743121ace5975830dcf8e6af`.

The adaptation runs a bounding-box block grid on CPU, removes the upstream node
UI/device-selection wrapper, and integrates the result into Zura's performer
masking pipeline. This modified version is distributed as part of Zura Nodes
on 17 September 2026.

This component remains under GNU GPL version 3; its licence text is included in
`licenses/KJNodes-GPL-3.0.txt`. The combined work is distributed subject to the
GPLv3/AGPLv3 combination provisions in section 13 of those licences. No upstream
endorsement is implied.

## Runtime dependencies and model weights

- [Ultralytics](https://github.com/ultralytics/ultralytics) is a separately installed
  dependency under AGPL-3.0, with separate enterprise licensing available from
  its authors. Its package and model weights are not bundled here.
- [ComfyUI-WanAnimatePreprocess](https://github.com/kijai/ComfyUI-WanAnimatePreprocess)
  is a separately installed node pack used for pose and face conditioning.
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI) provides the host, native video
  APIs and WanAnimateToVideo sampler conditioning.
- [rgthree-comfy](https://github.com/rgthree/rgthree-comfy) provides the Power Lora
  Loader used by the example workflow.

All downloaded model weights and third-party packages retain their respective
licences. No model weights or example source media are included in this release.
