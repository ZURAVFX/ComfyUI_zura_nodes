# MiniMax H3 Reference to Video

The Ref2Video mode runs the native local H3 `MiniMaxH3ReferenceToVideo` node.
References provide identity, appearance, scene, motion cues and audio. They are
not frame anchors.

## Inputs

- Up to nine reference images for identity, clothing, objects and visual style.
- Up to three reference videos for scene, appearance and motion cues. Each video
  uses a 2 to 15 second window controlled by `start` and `duration`.
- A reference video can include its own soundtrack through `audioFile`. The
  soundtrack is paired with the same video and its duration follows the video
  window.
- Up to three standalone audio references. Each is limited to ten seconds so
  reference tokens do not slow every sampling step.
- Images have no target-frame setting. Use the separate first and last frame
  workflow when exact frame anchoring is required.

Prompt tags follow the native presentation order. Images use `<Picture 1>`,
videos use `<Video 1>`, and audio uses `<Audio 1>`. A paired video soundtrack
receives its audio number before the video tag. Standalone audio continues the
audio number sequence after the paired tracks.

## Sampling

The Fast profile pairs the installed INT8 Ref2VA checkpoint with the verified
eight-step DMD Ref2VA LoRA. It uses Comfy Kitchen attention, the supplied H3
video and audio shifts, `res_multistep` and `simple`.

The Quality profile uses the standard INT8 checkpoint without the Turbo LoRA,
40 steps, and the `beta` scheduler.

The Viggle INT8 checkpoint is available as a separate quality profile. It does
not use the standard Turbo LoRA because a compatible Viggle Turbo adapter is not
verified.

The Spectrum patch is optional and uses the exact settings from the supplied
Kitchen workflow. It is enabled only with the Turbo profile.

## Limits

- 24 fps.
- The trained output range is 124 to 362 frames, about 5.17 to 15.08 seconds.
- Valid output frame counts follow H3's `17k + 5` grid.
- Width and height are multiples of 32.
- Output is capped at 1344 x 768 pixels, or 1.03 megapixels.
