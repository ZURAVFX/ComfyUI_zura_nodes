# Zura Studio 1.3.0 validation

Checked on 9 October 2026 with ComfyUI 0.39.2, frontend 1.53.10, a 16 GB
RTX 4080 and 64 GB system RAM. Successful execution is recorded separately
from visual quality. No paid provider generations were submitted.

## Shared controls

There is one Resolution selector and one Clip length control. Tests exercise
switching LTX, H3, Wan and Seedance while retaining the approved mask and look.
Changing the selected source interval requires a new review. Rendering reads
the source at the selected output size; mask review stays internally smaller.
H3 and LTX graph checks confirm the old two-second cap is disabled. H3 supports
at most five seconds. Wan continues through bounded frame windows.

Six shared-contract tests and the existing 126 Python regression tests passed,
along with all six existing JavaScript regression suites. A separate DOM/mock
API check exercises prepare, approve, design and animate, single output controls,
engine switching, stage labels and duplicate-job protection. A separate 25-check
local orchestration test covers recovery, ownership and paid credential gates.
Actual browser appearance and responsive layout were not inspected because the
local ComfyUI origin remains unavailable to browser control.

## Live native renders

| Route | Executed output | Result and limits |
| --- | --- | --- |
| Wan 2.2 Fast | 720 × 1280, 48 frames at 24 fps, 2 seconds | Native pose/face control, approved opening latent reference, isolated character CLIP Vision reference and approved background mask. Two windows, six steps each. Visible hand gesture transfers; hat, jacket and overall appearance remain consistent. Title and subtitle overlays are absent in all 48 inspected frames. Original audio is restored. Exact lip synchronisation and identity similarity were not measured. |
| LTX 2.5 | 1080 × 1920, 48 frames at 24 fps, 2 seconds | Corrected image-to-video conditioning and source registration. Appearance and text removal passed visual inspection. Motion transfer is understated; exact performance matching was not measured. |
| MiniMax H3 | 288 × 512, 48 frames at 24 fps, 2 seconds, 40 steps | Native depth control with separate opening and character references executed and restored audio. The user rejected its quality: motion was nearly static. H3 remains experimental. Higher resolution and longer graph settings are supported but were not quality-validated by a new GPU render. |
| Seedance | Mocked orchestration and credential checks | No paid draft or final render was performed. The native accepted-final node outputs 1080p; this is explicit in its paid action label and result metadata. |

The Wan test generated natively at 704 × 1280, then exported at the source
aspect ratio of 720 × 1280. Native video execution took 320.226 seconds;
preparation took 81.375 seconds and is reusable. Original-source audio correlation
at zero lag was 0.999993. The run used the supplied Wan checkpoint, native
FP8 fast loader, relight/realism LoRAs and both Fast-mode acceleration LoRAs.
The final native preparation and cached video graphs were preflighted against
the running server and the complete video graph executed successfully.

The source contained one central interview performer. Multi-person pose
targeting, long clips, more demanding motion and Wan Detailed mode still need
their own visual review. These observations do not guarantee every take will
preserve identity, hands or speech accurately. Each finished take remains
reviewable and downloadable before the artist decides to use it.
