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

## LongCat speech runtime

[LongCat-AudioDiT](https://github.com/meituan-longcat/LongCat-AudioDiT) code and
[LongCat-AudioDiT-3.5B](https://huggingface.co/meituan-longcat/LongCat-AudioDiT-3.5B)
weights are provided separately by Meituan under MIT licences. They are downloaded
only by the explicit setup command; upstream notices are retained. Model dependencies
run in an isolated interpreter. This does not change the Zura Nodes licence.

## Qwen VoiceDesign

Qwen3-TTS source and the Qwen3-TTS-12Hz-1.7B-VoiceDesign weights are separately
installed under Apache-2.0. Neither is bundled in Zura Nodes. The explicit installer
pins qwen-tts 0.1.1 and model revision 5ecdb67327fd37bb2e042aab12ff7391903235d3.
Retain upstream notices when redistributing those separate components.
Sources: https://github.com/QwenLM/Qwen3-TTS and
https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign
The existing Zura Nodes licence is unchanged.

## Artist Studio

The character-replacement sequence is inspired by [Genjustsu Open Source Workflow](https://github.com/sirioberati/Genjustsu-Open-Source-Workflow) and uses ComfyUI native inference nodes. Artist Studio orchestration and Zura data adapters are distributed as part of Zura Nodes under its existing licence. ComfyUI-LTXVideo, ComfyUI-KJNodes, WanAnimatePreprocess, controlnet_aux and MelBandRoFormer remain separately installed dependencies. Native workflows and model weights retain their upstream terms; weights, source media and credentials are not bundled.

## Optional speech and graph layout

The separately downloaded [MuseTalk 1.5](https://github.com/TMElyralab/MuseTalk)
weights and published latent/audio interface are used for local mouth animation.
MuseTalk code and models are offered under MIT; its SD VAE and Whisper dependencies
retain their own upstream terms. No speech weights or private media are bundled.

The isolated LatentSync inference components are copied from
[ByteDance LatentSync](https://github.com/bytedance/LatentSync), revision
`a229c3948406bc2cf6eaf4873e662e70c6a04746`, under Apache-2.0. The audio encoder
and mel transforms derive from OpenAI Whisper under MIT. Original notices,
licences and modifications are recorded in `artist_studio/latentsync_vendor`.
The optional setup separately downloads the published LatentSync 1.6 checkpoint,
pinned to revision `c42c7e6c8e9c213626389fa7d9a3c444b8536353`.
No InsightFace model or new face detector is used by the shipped adapter;
it uses the existing native WanAnimatePreprocess landmarks.

The unmodified elkjs 0.12.0 layout distribution is included at
`web/vendor/elk.bundled.js` under Eclipse Public License 2.0. Its licence is
retained in `web/vendor/ELK-LICENSE.md`. Corresponding source is available at
https://github.com/kieler/elkjs/tree/v0.12.0 . Zura graph code calls ELK only to
calculate layout; native ComfyUI creates and serialises the workflow objects.
