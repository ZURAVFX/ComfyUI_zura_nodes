# Director

Choose **Video > Director**. Add image anchors, direction cues and audio to one timeline, then choose LTX 2.5 or MiniMax H3 in the composer. Switching engines retains the timeline. Clips outside the new duration remain saved and must be moved inside the render range before generating.

Drag a clip to move it. Drag either visible edge to change its length, including image clips. Edits snap to whole frames, nearby cue edges and the playhead; hold Alt to bypass nearby-edge snapping. Images stop at neighbouring images rather than overlapping. Press Escape during a drag to cancel it. Exact start and end fields remain in the selected clip inspector.

Click the timeline to set the playhead. Double-click to add an image there. Select a thumbnail or cue to change its frame range, prompt or guide strength, or remove it. Frame ranges use an inclusive start and exclusive end: 24–25 occupies frame 24 only.

The main prompt describes the whole shot. Direction cues apply to their section of the timeline. Audio uploads use their actual duration, limited by the shot length. Moving sound preserves the source offset; trimming its left edge trims the source audio too. When sound is present, Studio uses the same audio conditioning as first/last-frame mode: H3's native audio guide, or LTX's encoded audio with a zero noise mask. The original timeline mix is saved with the video, including silent gaps, instead of regenerated audio. Visual performance remains model-guided and may still need artist review. Both engines run at their native 24 fps and round duration upwards to a supported frame count. Resolution offers source-image proportions, megapixels and custom dimensions.

## Native dependencies

Studio builds native graphs using these upstream extensions rather than reproducing their inference logic:

- LTX: [WhatDreamsCost-ComfyUI](https://github.com/WhatDreamsCost/WhatDreamsCost-ComfyUI), `LTXDirector` and `LTXDirectorGuide`.
- H3: [ComfyUI-MiniMaxH3-Director](https://github.com/seesee75-commits/ComfyUI-MiniMaxH3-Director), `MiniMaxH3DirectorCS`.

Missing model weights use Studio's shared installer and selected download folder. Missing extensions are listed with setup links; restart ComfyUI after installing or updating one. Graph view exports the editable native sampling graph.

The initial LTX path uses the distilled eight-step schedule. H3 uses FL2VA and its matching eight-step Turbo LoRA. Timeline conditioning stays in the native Director nodes. The integration's structural and UI checks do not establish generation quality; representative LTX and H3 shots still need artist review.

## Functional validation, 8 November 2026

Both graphs passed live node, enum and connection checks, then completed native inference using an image anchor, a timed direction cue and an audio clip. H3 saved 22 frames and LTX saved 25 frames, both at 512 × 288, 24 fps, with audio. File metadata was checked with ffprobe. These short synthetic-room tests verify timeline execution, decoding and saving rather than shot quality.

The installed WhatDreamsCost extension matches upstream 2.0.5. H3 Director was backed up and updated from 0.2.2 to 1.0.1, then the H3 test was repeated successfully after restarting ComfyUI. The integration uses its compatible legacy `MiniMaxH3DirectorCS` node; the updated node's inputs were checked against the running server.

## Timeline and soundtrack checks, 8 November 2026

Mouse tests at 1280 × 720 and 1920 × 1080 exercised moving images and direction clips, resizing both image edges and trimming sound. Regression checks also cover collision bounds, cancelled drags, saved durations and audio source offsets. Short H3 and LTX renders with sound starting four frames into the shot and trimmed by two source frames both completed. Decoded output audio correlated above 0.99999 with the source segment, with silence before and after. These checks establish soundtrack placement and export preservation; they do not establish speech or performance quality.
