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

## Direct the performance with audio

After adding audio, use the **Audio direction** selector beside clip length:

- **Reference only** keeps the existing behaviour: H3 generates a new soundtrack
  using the uploaded audio as a reference.
- **Follow Audio 1** uses that vocal as a timeline guide during generation and
  keeps it as the output soundtrack. With several clips, choose which one to follow.

For example, upload a character image and a vocal, choose **Follow Audio 1**, then
write `The character in <Picture 1> says <audio 1>.` Tags are case-insensitive in
Studio and are converted to H3's native spelling before submission. Mentioning an
audio tag alone does not enable follow mode.

Follow mode starts standalone audio at zero. A paired video soundtrack follows
that video's selected start. It trims the vocal to the output clip length and
pads a shorter vocal with silence, without looping. The ten-second reference
context limit does not cut off the followed vocal in a longer output.

The editable graph uses native `MiniMaxH3AddGuide` audio conditioning with the
reference AV latent. It does not simply replace the soundtrack after sampling.
The soundtrack comes from the uploaded audio, while facial timing remains a
model-generated performance and should be reviewed. This is not a frozen target
audio latent or a guarantee of exact lip synchronisation.

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
