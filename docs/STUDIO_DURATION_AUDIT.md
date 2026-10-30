# Studio duration audit

The current Studio source-selection paths normalise footage to 24 fps and use
the floor of the selected duration multiplied by 24 as their target frame count.
Head and face swap additionally caps its approved selection at 48 frames.
The first/last-frame controls use each model's supported frame grid: H3 17n+5,
Wan 2.2 4n+1, and LTX 2.5 8n+1. Their graph builders pass the chosen frame count
to the native model and assemble at 24 fps.

## Existing output evidence

MP4 stream metadata and the embedded native prompt were compared on existing
local generation results. The requested model frame counts and the delivered
video counts matched for these examples:

| Workflow | Model frame counts verified | Video rate | Audio duration |
| --- | --- | --- | --- |
| H3 first/last frame | 73, 124, 243 | 24 fps | Within 1 ms of video |
| LTX 2.5 first/last frame | 97 | 24 fps | Within 1 ms of video |
| Wan 2.2 first/last frame | 25 | 24 fps | Silent by design; audio references are unsupported |
| H3 reference to video | 192 | 24 fps | Matches to reported precision |
| FastH3 reference to video | 56 | 24 fps | 8 ms shorter than video |

These are representative rendered outputs, not proof that every offered frame
count fits every system or produces acceptable quality. The existing relight
validation documents a one-second Wan 2.1 render and other five-second model
renders; 23.976, 25 and 29.97 fps source-selection fixtures are also tested
with real FFmpeg, but not yet GPU-rendered at each input rate.

The full-resolution reviewed-shot reload previously dropped one frame on some
non-zero trims, even though the initial 24 fps selection had the correct count.
A 0.21-second trim reproduced this at 23.976, 25 and 29.97 fps. The reload now
resets timestamps, holds at most one final frame, uses a new cache version and
checks its actual frame count. Real FFmpeg loader tests confirm 30 frames for
each of those rates and reject a shortened cached render. GPU rendering across
these rates is still unqualified.

A fresh isolated GPU test of the Studio Wan 2.2 first/last recipe produced exactly
25 decoded frames at 24 fps, 256 × 256, lasting 1.04167 seconds, and correctly
contained no audio. First, middle and last frames maintained consistent cropping
in this still-camera test; it does not establish quality at higher resolution or
longer duration. Runtime was 16.13 seconds on the local system.

Remaining coverage includes the maximum-length and unusual-source-rate cases across modes,
and exact source/audio alignment across long multi-window outputs. Check each
model's embedded requested frame count, decoded frame count, frame rate and
audio duration or lag; a successful graph build alone is not sufficient.
