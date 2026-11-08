# Director

Choose **Video > Director**. Add image anchors, direction cues and audio to one timeline, then choose LTX 2.5 or MiniMax H3 in the composer. Switching engines retains the timeline. Clips outside the new duration remain saved and must be moved inside the render range before generating.

Click the timeline to set the playhead. Double-click to add an image there. Select a thumbnail or cue to change its frame range, prompt or guide strength, or remove it. Frame ranges use an inclusive start and exclusive end: 24–25 occupies frame 24 only.

The main prompt describes the whole shot. Direction cues apply to their section of the timeline. Audio clips provide timed sound guidance. Both engines run at their native 24 fps and round duration upwards to a supported frame count. Resolution offers source-image proportions, megapixels and custom dimensions.

## Native dependencies

Studio builds native graphs using these upstream extensions rather than reproducing their inference logic:

- LTX: [WhatDreamsCost-ComfyUI](https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI), `LTXDirector` and `LTXDirectorGuide`.
- H3: [ComfyUI-MiniMaxH3-Director](https://github.com/seesee75-commits/ComfyUI-MiniMaxH3-Director), `MiniMaxH3DirectorCS`.

Missing model weights use Studio's shared installer and selected download folder. Missing extensions are listed with setup links; restart ComfyUI after installing or updating one. Graph view exports the editable native sampling graph.

The initial LTX path uses the distilled eight-step schedule. H3 uses FL2VA and its matching eight-step Turbo LoRA. Timeline conditioning stays in the native Director nodes. The integration's structural and UI checks do not establish generation quality; representative LTX and H3 shots still need artist review.

## Functional validation, 8 November 2026

Both graphs passed live node, enum and connection checks, then completed native inference using an image anchor, a timed direction cue and an audio clip. H3 saved 22 frames and LTX saved 25 frames, both at 512 × 288, 24 fps, with audio. File metadata was checked with ffprobe. These short synthetic-room tests verify timeline execution, decoding and saving rather than shot quality.

The installed WhatDreamsCost extension matches upstream 2.0.5. H3 Director was backed up and updated from 0.2.2 to 1.0.1, then the H3 test was repeated successfully after restarting ComfyUI. The integration uses its compatible legacy `MiniMaxH3DirectorCS` node; the updated node's inputs were checked against the running server.
