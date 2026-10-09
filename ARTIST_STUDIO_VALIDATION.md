# Zura Studio validation

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

The 1.3.1 checks include 137 Python regression tests and six JavaScript regression
suites. A separate DOM/mock
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

## 1.3.1 studio update

The complete interface, launch link, user messages, node display names and take
downloads use Zura branding and are distributed by the official Zura Nodes pack.
The canonical `/zura/studio` routes cover all eight studio operations. Matching
legacy routes and project storage remain available to preserve existing shots.
The launcher uses `?zura=1`; older launch links also remain supported.

The update adds tests for source-speech conditioning in both LTX passes, native
Wan joins without repeated or cross-faded frames, and one temporal VAE tile per
bounded window. The separate DOM interaction check uses canonical routes, checks
Zura download names and retains older 960 px project settings in the single
Resolution selector. The 25 orchestration checks also passed.

The active ComfyUI Desktop instance was on port 8189 and still held the retired
standalone extension in memory. Its queue was checked before a Manager restart.
It now loads the official Zura pack and accepts Wan, LTX and H3 settings. This
fix was verified against Desktop's actual backend, rather than the separate
portable test instance on 8188. Existing saved reviews and looks were preserved.

A new native Wan 720p test rendered all 48 frames in one pass, using the new
81-frame window setting and native join mode. All frames were inspected: hat,
jacket, speech and hand movement remain visible; text is absent; the former
1.5–1.7 second cross-fade is absent. Original audio correlation is 0.999993.
Execution took 487.518 seconds in Desktop's current dynamic-memory mode.

The user reported missing lip sync in the earlier LTX tests. Those tests do not
prove speech synchronisation. The update routes frozen source audio through both
sampling passes, including the previously silent restyle route, and adds native
modality guidance. The official LTX-2.5 A2V zero-noise-mask path is used;
speaker-reference tokens are identity context and are not a substitute for timed
input audio.

A second native Wan render deliberately used 41-frame windows to exercise a
real continuation boundary at frame 41 (1.708 seconds). All 48 frames and the
enlarged boundary region were inspected. The earlier frames remain intact,
without the former double-image fade; hat, jacket, hand and mouth motion remain
present and text stays absent. Execution took 439.074 seconds. Audio timing and
correlation match the single-pass preview. Small appearance changes can still
occur between generated windows. This validates one short boundary, not every
long clip or a full 81-frame GPU window.

An HD mask bottleneck in the original native square max-pooling took about
12 minutes 47 seconds before sampling. The revised path uses native Mask Fix
with the same rectangular dilation radius and threshold. Regression checks
match the original at mask borders and threshold values; a synthetic 49-frame
1088 × 1920 mask batch with radius 30 processed in 0.907 seconds. No blur, hole
filling or mask-area reduction is introduced. The slow attempt was interrupted
and is not recorded as a completed render.

Two new 1080 × 1920 LTX tests each exported 48 frames at 24 fps, with two seconds
of source audio and zero-lag audio correlation 0.999993. The reference-token
attempt took 206.117 seconds; the final native fixed-audio path took 187.814
seconds. Appearance and text removal remain usable, but both fail the speech
motion review: the mouth moves too weakly or changes expression without matching
the spoken performance. Neither is labelled as successful lip sync. The final
path holds the correct source audio fixed rather than adding speaker-reference
tokens; the studio explicitly marks LTX speech timing as experimental. Wan is
the better tested route for this talking source. A dedicated, version-compatible
speech correction model would need its own integration and quality validation.
