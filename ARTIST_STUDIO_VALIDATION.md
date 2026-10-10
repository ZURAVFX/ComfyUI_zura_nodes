# Zura Studio validation

## 1.3.6 automatic Wan speech, 10 October 2026

The shared selector provides Original audio + performance and Reference audio +
new performance on Wan, MiniMax H3, LTX and Seedance. Original mode bypasses the
replacement face guide and optional mouth finish. Switching modes remembers the
reference locally while keeping it out of Original rendering. The switching,
reload, silence and soundtrack-only contracts pass for all four engines.

Wan reference speech now uses a native Wan 2.1 I2V / InfiniteTalk graph to create
the facial performance before Wan 2.2 Animate. Native detectors check and crop
the approved character opening. The original body pose remains the motion guide;
the new performance supplies the face guide. Original mode retains the source
face guide. The final renderer and character-replacement workflow remain Wan 2.2.

An ordinary Studio animation action completed the full cold route: memory
acknowledgement, speech generation, verified guide storage, another memory
acknowledgement, motion preparation, a final acknowledgement and rendering.
No manual prompt IDs, external performance composite or mouth finishing pass
was used. The guide contained 125 frames at 25 fps and 480 × 640; the finished
video contained 120 frames at 24 fps and 720 × 1280, with one selected audio
track. This five-second sample includes leading and trailing silence, rather
than five seconds of continuous speech. The final render took 467 seconds on
the test machine, in addition to guide generation and preparation.

Inspected frames showed consistent character appearance, visible mouth changes
during the spoken interval, a resting expression during the later silence and
retained body gestures. Captions did not return in the sampled frames. The
largest-motion and continuation frames remained coherent. These observations
are not a phoneme score or acceptance of arbitrary faces, long takes or
occlusion. Artist review is still required.

Guide reuse checks the actual selected waveform, approved mask and look, source
timeline, seed, model stamps, native executed recipe, exported video hash and
successful Comfy history. Failed, edited or mismatched jobs cannot silently
warm Studio. Collection accepts both native tuple history and JSON list history;
signatures tolerate lossless numeric formatting through Comfy FLOAT validation
and browser JSON, while retaining checks on changed values.

The 108 relevant CPU regressions pass, including 23 Wan speech/setup tests and
12 serial memory-transition tests. Seven offline tests of frontend 1.53.10 pass
for native subgraph conversion, export, reload and exposed seed changes. The
compiled native speech graph matches the declared render recipe, and saved root
layouts report zero wire crossings. Synthetic CPU checks cover graph-view
cache hand-offs; a separate GPU queue from the physical graph editor was not
performed. Browser and physical phone layout testing remain unavailable.

The newer H3 fixed-audio and background-guidance test is recorded below. Three
matched five-second LTX tests (existing settings, stronger modality guidance and
audio timestep override) did not resolve the motion and mouth problems; the
tested alternative settings are not shipped. LTX speech remains experimental.
Seedance was inspected without paid generation. Seven existing projects and
unrelated installed nodes were preserved. Private recordings, scripts, supplied
workflow examples, test projects and test media are excluded from publication.

## Fixed H3 reference speech, 10 October 2026

The earlier native previews failed the user's quality review: Wan retained good
visuals but weak speech performance, H3 expression was unconvincing, and LTX had
poor lip timing and arm warping. Their successful executions below are not an
acceptance of those results.

H3 selected audio now fills its target audio latent and sets that stream's
native noise mask to zero. Previously the track was reference conditioning while
the target audio remained free to change, despite exporting the selected voice.
The thin Zura adapter uses the native audio VAE and preserves the video stream,
its mask and latent metadata. It works after loading cached references as well.

Seven H3 adapter tests, 22 shared-engine tests, 24 speech tests, 12 audio-mode
tests and eight caption-mask tests pass.
They check real-waveform silence padding, trimming/resampling, invalid input,
video-mask preservation and cached sampling connections. These CPU checks do
not establish rendering quality.

A separate five-second H3 test of the fixed-audio method completed with the
installed Pixaroma node, compatible Ref2VA turbo LoRA and eight sampling steps:
720 × 1280, 120 frames at 24 fps, one selected audio track and no mouth finish.
A matched five-second test then completed with the installed Zura adapter itself,
with the same dimensions, frame count and selected soundtrack. The user accepted
the speech-lock method, then reported opening colour shift, movement edges and
caption leakage. Those remaining visual issues require separate validation.
No paid inference ran. Test media and supplied workflow examples remain private.

The shared Audio and performance selector defaults to original audio and source
performance guidance on all four engines. Reference mode enables new speech;
soundtrack-only mode disables the separate face guide and finishing pass.
Switching to Original remembers the uploaded or cloned reference locally without
feeding it to rendering. CPU checks cover switching, reload, legacy projects,
silence, offsets, original/refined graph routing and all four model choices.
Seedance graphs were inspected without submitting paid jobs.

Six fresh offline tests of frontend 1.53.10 passed after the held-caption and
source-latent changes, including the experimental H3 background adapter. Native
subgraph conversion, export, reload and changed exposed seed preserve the compiled
render inputs, with zero measured root wire crossings. This does not establish
browser rendering or video quality.

A further five-second H3 render completed with native source-video encoding,
background noise masking, held caption regions and cleaned depth guidance. It
delivered 120 frames at 24 fps, 720 × 1280 and the selected audio, with no mouth
finish or post-generation RGB composite. Inspected frames at the start, through
the shot and at the end showed no returning caption panels. The static upper
wall's opening-frame change fell from 1.816 to 0.409 mean absolute RGB units;
source-relative colour error also decreased across six sampled frames. This is
a local background-region measurement, not a whole-video quality or phoneme
score. Moving edges and facial performance still require artist review.

## Native speech paths, 10 October 2026

H3 and LTX now retain their native generated faces by default. The shared local
mouth finish runs only when Refine lips after generation is selected. Wan keeps
its separate audio-driven guide before generation. Native H3/LTX speech no longer
requires the optional mouth-correction models.

Two fresh local renders used replacement audio with no mouth finish: LTX at
1080 × 1920 and H3 at 720 × 1280 with 40 Euler steps. Both delivered 48 frames
at 24 fps, two seconds and one correctly aligned selected audio track. H3 used
124 frames of internal context, separate image references, native audio guidance
and depth ControlNet strength 1.0 without a duplicate video reference.

Frame inspection found a more consistent H3 face and visible hand gesture
transfer. LTX retained the opening appearance but changed gesture timing and
showed mouth movement during the quiet opening. Exact phoneme synchronisation
was not measured, and the user subsequently rejected these takes. Neither
successful rendering nor restored audio establishes good lip sync.

The 21 shared-engine and 24 speech tests pass. Six native frontend graph
export/reload tests pass, including changed root controls and zero root wire
crossings. DOM/mock checks cover optional refinement, native speech without
separate correction models, engine switching and the private mobile preview
selector. Browser and physical phone testing remain unavailable. Seven saved
projects and unrelated installed modules were preserved. No paid inference ran;
private recordings, scripts, test media and project data are excluded from GitHub.

## 1.3.2 audio, graph view and original clip length

Checked on 10 October 2026. Eight additional Python regressions exercise
silent audio on both LTX padding cases, reference audio offset and padding,
original-length selection, review invalidation, full native Wan graph export,
editable H3 conditioning and the added read-only graph route. Exporting a graph
does not modify project approval or queue jobs. Adding defaults to older saved
projects preserves their finished state. All 145 Python tests and six JavaScript
suites pass. The DOM/mock interaction test
also exercises the native graph hand-off, optional audio removal, audio offset,
original/custom length controls and the Wan audio limitation.

A separate local execution test uses real native Comfy video objects, PyAV and
FFmpeg. A silent 4-second source retains all 96 frames when Original clip length
is selected despite a 2-second custom value. Its high-resolution reread contains
valid silence audio. A separate reference track retains its 0.5-second offset,
is padded to 4 seconds and survives the high-resolution reread and final export
with zero-lag audio correlation 0.999998. The LTX padding node supplies valid
audio even when the input already has a valid 1+8n frame count.

No new diffusion generation, paid calls or successful lip-sync quality result
is implied by these audio plumbing checks. Native editable graph imports use
the installed frontend's loadApiJson and new workflow tab handling. Actual
browser visual testing remains unavailable; graph export and native input
validation are checked separately.

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

## Optional local speech and editable graphs (1.3.3)

Two private Wan speech tests completed on RTX 4080 with the existing fast model,
LoRA stack and background-preserving Animate route: 720 x 1280, 48 frames,
24 fps, two seconds and the selected replacement audio. The first used a local
MuseTalk 1.5 face guide; the second also completed the shared local lower-face
finish. The dedicated guide test preserved every upper-face pixel and changed
the lower face. These are real GPU executions, not just graph validation.
The private outputs remain local. No private sample, transcript or script is
included in the repository or release package. Review mouth timing and identity
on each take; a successful execution does not establish perfect phoneme accuracy.

LTX, H3 and accepted Seedance finals use the same tested finish nodes after their
own video generation. Their new engine-to-finish paths were checked structurally;
new full LTX/H3/paid Seedance speech renders are not claimed here. MuseTalk's
internal 256 px face crop can soften detail and requires a visible human face.

The installed frontend 1.53.10 native graph code was exercised offline for all
six local stages. Conversion, export, reload and API compilation preserve the
original inference inputs after expanding the lossless stage adapters. Changing
the exposed seed changes the intended inner input and restoring it restores the
original prompt. The root graph has zero measured wire crossings. Complex
internal stages retain some crossings; their nodes and boundary ports are routed
with ELK. This is not a claim that every internal graph is planar.
The hand-off nodes also completed a real ComfyUI audio-to-audio execution:
sample rate, length and every decoded audio sample were unchanged.

Browser visual testing remains unavailable because Codex's saved browser policy
rejects the local ComfyUI origin. DOM interactions, backend uploads, native video
objects and offline native graph tests were checked separately. The native
runtime also checks compiled inputs when the user opens Graph view and falls
back to the original editable copy if conversion changes them.

The Studio voice endpoint completed real local LongCat text-to-speech and
voice-cloning jobs. Both returned an uploaded-style audio asset with a playable
URL. Resubmitting the same voice request returned the original job rather than
duplicating generation. Completed audio can be recovered even if a ComfyUI
restart clears its queue history. The UI contract selects the completed track
automatically, resets its offset and enables lip sync when its models are ready.

## Sharper speech and tidy nested graphs (1.3.4)

Automatic now selects the installed LatentSync 1.6 model at its trained 512 px
face resolution. Explicit MuseTalk selections retain the 256 px model. The
LatentSync checkpoint was matched strictly; its audio mel transform and
pre-normalisation encoder embeddings matched the published implementation.
The native detector's 69-point layout was corrected to exclude its leading
foot point before interpreting the 68 facial landmarks. The alignment uses
the published eyebrow-centre and nose-tip anchors.

A real 48-frame qualification used 20 diffusion steps, 16-frame windows,
sequential audio guidance and sliced VAE processing on RTX 4080. It retained
512 px inference and measured 3.419 GiB allocated / 3.861 GiB reserved by that
speech process. These figures are not the memory requirement for a complete
Wan, H3 or LTX generation, or for other applications running alongside it.

Four real sharp finishing tests completed on previously generated Wan, H3,
LTX background-preserving and LTX restyle videos. They reuse existing sampler
outputs rather than claiming four fresh full model renders. A separate fresh
Wan test completed the new sharp face guide and the unchanged fast Animate
sampler, followed by a separately tested sharp finish on that new take.
All six deliveries contained 48 frames at 24 fps, 720 x 1280 pixels and two
seconds of the chosen audio. Zero-lag audio correlation was 0.999945; its quiet
lead remained quiet. No paid Seedance or other API inference was submitted.

The sharper face model retains more lip texture than the previous guide.
The least open source mouth provides a stable visual reference during quiet
sections, reducing leakage from the old dialogue. Wan's guide-only take had
clear facial detail and reduced early movement, but restrained articulation.
The optional final mouth pass adds articulation. These short private tests do
not establish perfect phoneme accuracy. H3's base video quality and LTX's
underlying face motion remain experimental; a mouth finish cannot correct
their entire head performance. All private source clips, recordings, scripts,
transcripts and project data remain outside the repository and package.

The installed frontend 1.53.10 native subgraph implementation was tested
offline for preparation, look design, Wan, H3 and both LTX routes. Native
conversion, export, reload and exposed-seed changes preserve the compiled
inference inputs. Smaller nested groups keep each operation explorable.
Unneeded hand-off sockets are trimmed again after configuration. H3 uses a
native multiline text source to expose its existing prompt in Your inputs;
the prompt text and model settings are preserved.

Node sockets are arranged before layout. ELK routing is supplemented with a
bounded orthogonal wire router that avoids occupied nodes and unrelated wires.
Exported native positions were inspected separately from browser rendering.
The root and internal layouts have zero measured unrelated wire crossings
for all six tested stages. The crossing check also detects overlapping wires
and contacts at bends; branches sharing the same output are intentional
signal junctions. Other node versions or edited graphs may lay out differently.

DOM interaction checks cover the shared resolution and original/custom length
controls, direct audio, cloning, audio offsets, automatic review IDs and graph
handoff without queueing work. Browser visual testing remains unavailable
because Codex's saved browser setting rejects the local ComfyUI origin.
