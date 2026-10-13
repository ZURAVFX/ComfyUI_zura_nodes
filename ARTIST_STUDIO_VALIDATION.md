# Zura Studio validation

## Timed finished-frame references, 13 October 2026

H3 and whole-scene LTX now accept First, Last or a 1-based output frame number.
LTX places a single still using native guide conditioning in both sampling
stages, removes guide latents before caching, and excludes temporal padding
from the Last selection. Generated scene plates retain their earlier untimed
appearance role. The native single-image resolver preserves arbitrary frame
indices. H3 uses its native keyframe guide. Wan Animate and masked LTX do not
offer arbitrary timed stills on their current routes. These changes are
structurally tested; no new GPU render or visual approval is claimed.

## Viewport guide comparison, 13 October 2026

The supplied train blockout is 15 seconds at 1920 Ã— 1080. A five-second
LTX 2.5 Layout-to-Render run generated 113 frames at 24 fps and 1920 Ã— 1080.
A second run added the LTX 2.3 Union Control depth guide at the same output
size. Both completed. In this scene, the raw Layout route kept the exterior
train composition closer to its reference. The depth-guided result softened
the image and shifted scene details, so depth was removed from the artist
controls. No Canny comparison was run; it is not a qualified release option.
Neither diagnostic is an artist-approved final. The source video and test
renders remain local and are not included in the package.

The supplied MiniMax API workflow uses five connected train reference images
and a text prompt. Its `LoadVideo` node is not connected to the model's
`reference_videos.video_1` input. It is therefore an image-reference example,
not evidence of hidden video Canny/depth preprocessing or viewport-video
conditioning. The local H3 route separately connects the blockout as a
reference video.

The same blockout was also run through all three local viewport routes at
1280 Ã— 720. Each returned exactly 120 frames at 24 fps (five seconds). LTX
pads its generation guide to the model's required frame count, then trims the
decoded result back to the exact selected interval. These were integration
tests, not artist sign-offs. The files and source media remain local and are
not included in the package. No Canny test was run.

## Current release qualification, 11 October 2026

The artist accepts all three five-second Wan 1080p examples and all three
five-second H3 Enhanced 1080p examples: original performance, selected speech
and genuinely silent footage. This is approval of the exact reviewed outputs.
Wan uses native 1080p generation; H3 generates at 720p and enhances its delivery
to 1080p. The full-length Wan 720p example is also accepted with section-to-section
detail degradation recorded as a known limitation.

All three exact five-second LTX 2.5 examples are also accepted, bringing the
short-example sign-offs to nine of nine. The new viewport integration has now
run on the current blockout through LTX, H3 and Wan; those exact viewport clips
still need separate artist review. Longer H3 speech continuation and actual
Desktop and mobile visual checks remain open. The diagnostic history below includes
earlier attempts with separate acceptance scopes. Private recordings, dialogue,
project identifiers and media remain outside the public repository.

A separate LTX 2.5 audio-to-video diagnostic completed native preparation,
refinement sampling and decoding as three jobs, preserving the native video
noise mask across the cache boundary. Its delivered five-second video contains
120 frames at 24 fps and 1408 Ã— 2560. The artist likes its appearance. This
diagnostic conditions on an opening image and selected audio, however, and does
not retain the source video's body performance or camera motion. Complete frame
review also found mouth opening before measured audio activity and limited
articulation during the speech tail. It is not qualified as the replacement
workflow or included among the six accepted release examples.

A separate motion-guided refinement completed native preparation, sampling and
decode using the saved body-guided first-stage video and selected-audio
refinement. The artist accepts its exact five-second, 120-frame 1408 Ã— 2560
selected-speech output for this release, bringing accepted examples to seven
of nine. Complete frame review finds improved source gesture preservation and
broadly coherent identity, with soft moving hands and early mouth closure
during the audio tail recorded as limitations. Longer clips and environment
replacement retain separate qualification scopes.

The artist subsequently accepts the exact five-second LTX silent example,
bringing accepted examples to eight of nine. It delivers 120 frames at 24 fps
and 1408 Ã— 2560, with no audio track. Complete frame review finds coherent
identity and retained source gestures; moving hand detail remains soft.

The artist also accepts the exact five-second original-performance LTX example.
It uses source facial landmarks and frozen original audio, followed by native
refinement and decode. All 120 face and body frames were reviewed. Native
CreateVideo receives the original soundtrack directly, preserving the
1408 Ã— 2560 output raster; the earlier downscaled diagnostic is not this
accepted example. Moving hand detail remains soft. This sign-off covers the
exact prototype video rather than longer continuation or Studio integration.

The final native Studio candidate passed 34 focused CPU planner, runtime and
uploaded-opening checks, plus independent read-only validation against 47
installed node schemas. All 12 shared audio-mode checks also pass. A fresh
project completed normal preparation and opening design, but its first sampler
stopped at the system-memory reserve before generating frames. Its regenerated
appearance also failed artist review. The starting-image option now allows
an already approved frame to be used exactly, alongside the character reference.

The revised automatic pipeline separates text, motion/audio preparation,
first sampling, upscaling, refinement and decode into six native phases.
Each new take gets its own files automatically; repeated requests retain the
same run. A fresh ordinary Studio run subsequently completed all six phases
and automatic handoffs, delivering 120 frames at 24 fps, 1080 Ã— 1920, with
the original audio track and the previously approved opening image unchanged.
All 120 body and face frames were screened: the adult character is coherent,
the source gestures remain visible and moving hand detail is soft. This is
runtime and frame-screening evidence; the new integration video retains a
separate artist-approval scope from the nine accepted prototypes.

The successful run kept Premiere open and retained at least 12.46 GiB of
sampled commit headroom and 16.65 GiB of available physical memory. An earlier
retry was cancelled by the test harness's conservative reserve threshold;
that interruption was not a native model error. These figures describe this
one workstation/run, not a guarantee on other machines. Masked inpainting
continues to use its separate route. The body-guided pipeline changes the
whole scene and supports intervals up to five seconds at 24 fps.

H3's new preparation adapters passed 13 CPU differential tests against the
installed native control calculation and a fresh independent review. Their live
node schemas are verified locally. These checks use a stub VAE; production VAE
parity, memory savings and longer-render quality remain unqualified. Sampling
from prepared control data is staged separately from native encoding and decode.
Native control preparation subsequently completed; successful sampling and
longer-render qualification are still required.
The first sampler using those prepared controls stopped at the system-memory
reserve after three of eight steps and produced no video. The approved short
examples retain their separate acceptance.

The separate environment-replacement diagnostic now completes native sampling
and decode. A later native guide-dilation correction removes the performer
colour cast, and the artist confirms the target environment is correct.
The source camera move is missing. An earlier full-frame Layout comparison
also generated the target environment with static architecture, so changing
the reference alone does not establish a remedy. Whole-scene viewport camera
preservation remains unqualified.

The edited full-length Wan preparation matches the approved preparation bitwise
across source frames, performer masks, pose, face and reference tensors. Its
render graph uses automatic cuts where the approved render used a marked cut.
No render from that edited namespace or actual interface review is established
by the cache comparison.

A subsequent bounded CPU check ran the actual automatic cut detector on the
prepared source thumbnails. It found the same marked cut and produced the same
nine-section plan as the approved render. This resolves the planning difference
for this source without establishing a new render or interface test.

## Unreleased selection and text cleanup checks, 11 October 2026

Masked-area and whole-scene preparation now share the same Studio flow. Text
and point selections use native tracking, and whole-scene preparation skips
segmentation. CPU checks cover selection limits, stale-review invalidation,
opening-frame registration and the independent tracked performer mask.

Automatic and described selections now reset the visible native SAM detector
and tracker at camera cuts, then rejoin their masks in source-frame order. A
native full-length Prepare test completed all 570 frames at 24 fps, with a
288 Ã— 512 selection raster and two independently tracked shots. The performer
remained selected through the cut and all final 93 frames, where the previous
continuous tracker had lost its mask. All 570 overview frames and native-size
cut and tail examples were inspected. There were no near-empty masks or
full-frame text-removal masks. This verifies preparation, rather than a finished
long video or artist approval of the selection.

Text removal uses the native detector's default confidence and holds its exact
pixel regions within each tracked shot. Text panels no longer carry across
cuts, and compact region metadata cannot paint extra mask pixels. A small
text-like face detection remained in the test; this is not a guarantee of OCR
accuracy or automatic identity matching between different people. The review
asks the artist to check selection after each cut. Point selections retain
their existing tracking route.

The actual updated Prepare graph also passed an offline export, reload and
API-compilation check using frontend 1.53.10's native subgraph code. Render
inputs were preserved, with zero measured unrelated wire crossings. This is
separate from Desktop or mobile visual testing.

H3's automatic background-text cleanup completed a native five-second render
at 24 fps and 720 Ã— 1280. All 120 repaired-area and face crops were inspected:
the repaired background was materially steadier, with slight softness, while
visible articulation and body gestures remained. This is a local review;
artist acceptance of this exact repaired take is pending. The native LaMa path
repairs eligible source background before generation and protects the genuine
performer outline. It adds no performer composite after generation.

The artist clarified that the earlier title defect is a fading or colour-changing
repair region, rather than returning text. The new repair is materially steadier
in the inspected take; its remaining softness and artist acceptance are still open.

A native 1080 Ã— 1920 H3 delivery test was interrupted before completing its first
sampling step after system memory commitment reached 99.3% on a machine with
16 GB GPU memory and 64 GB RAM. Its internal generation raster was 1088 Ã— 1920.
This attempt establishes a practical memory limit for that configuration, with
no completed 1080p video or quality pass.

A separate same-raster H3 comparison first saved and verified native 1080p
conditioning, then released about 20 GB of system commitment before rendering.
It still reached near-full system commitment without a completed sampling step
and was targeted-interrupted after about 13 minutes. Native history records an
interruption, not an out-of-memory exception. This configuration remains
unsuitable as a validated native 1080p route on that machine.

A separately labelled enhanced-1080p comparison completed all 120 native
framewise upscale batches from the working 720p H3 original-audio take.
Both learned-enhancement and plain-resize deliveries contain 120 frames at
24 fps and 1080 Ã— 1920. Their source AAC packet payloads were copied unchanged.
All paired native face and repaired-area crops and body overviews were inspected.
Learned enhancement gives modestly sharper facial and fabric detail, with
remaining softness. The repaired area stayed materially steady in the inspected
frames. This is post-generation enhancement, not native 1080p diffusion or a
new speech performance. Artist acceptance of that comparison is pending.

The automatic Studio route separately completed a selected-audio test from one
launch: fresh matching reference preparation, 720p H3 generation, idle-safe model
release and all 120 framewise enhancement jobs. It recorded one final result at
1080 Ã— 1920, 24 fps and five seconds, with the selected soundtrack. The 720p
intermediate was not displayed as a finished 1080p take. All 120 delivered face,
repaired-area and body views were inspected. No conspicuous repaired-panel
colour flash, fading rectangle or replacement-character discontinuity was
identified. Open-mouth detail remains soft; audiovisual review of the final
words around 2.5â€“2.9 seconds was subsequently accepted by the artist in the
exact final five-second example. Soundtrack
correlation checks fidelity and mux timing, not phoneme synchrony. The same
automatic route also completed original-audio and genuinely silent tests, each
with all 120 enhancement jobs and one final five-second 1080p result. Original
audio delivery has zero measured lag; the silent source and delivery both have
zero audio tracks. All original-audio face, repaired-area and body frames were
inspected with no conspicuous repair-region colour pump or abrupt character
change. All silent-delivery face, repaired-area and body frames were also
inspected, with coherent gestures and no conspicuous repair-region colour pump.
Mouth detail and fast hands remain soft, and some silent facial expressions
are prolonged. A sampled original-source comparison found changes in blink,
head-tilt and mouth-opening timing, so exact performance retention is not
certified. These runtime checks preserve the distinction between enhanced delivery and native
1080p diffusion. The artist now accepts all three exact final five-second files
for this release. Longer speech continuation retains its separate qualification.
CPU checks also cover continuation failure, interruption, output provenance and
soundtrack selection. Mid-enhancement process restart is not a resumable batch;
the collector reports interruption without silently replaying the generation.

Separate H3 original-audio and silent-input renders also completed at the same
five-second size and frame rate. All 120 native face and repaired-area crops,
plus body overviews, were inspected for each. Replacement identity and gestures
remained coherent, and the title repair stayed materially steady. Original
soundtrack delivery was checked; the silent output has zero audio tracks.
Generated expressions and mouth shapes differ from the source, so these checks
do not establish exact facial performance or phoneme accuracy. Artist acceptance
of both examples is pending.

The updated Wan fast recipe excludes the Wan2.2 high-noise I2V adapter. Its
five-second native test exercised the Studio's 81-frame continuation windows.
All 120 face frames were inspected with no obvious double-image blend at the
join. Artist feedback on the earlier 41-frame diagnostic is positive; acceptance
of the new 81-frame take and longer clips remains separate.

A separate five-second Wan original-audio take also completed at 720 Ã— 1280
and 24 fps. All 120 native face and repaired-area crops, plus body overviews,
were inspected. Mouth changes, blinks and head movement broadly followed the
source, with no obvious jump at the 81-frame continuation boundary. The title
repair appeared steady through the source title fade. Fast-moving hands remain
soft. Original soundtrack delivery was checked; exact speech and performance
acceptance by the artist is pending.

A native 1080 Ã— 1920 Wan test using 81-frame windows was interrupted before
its first completed sampling step under sustained system-memory pressure.
The separate 41-frame-window comparison completed in about 25 minutes on the
same 16 GB GPU and 64 GB RAM machine, with the same 1088 Ã— 1920 internal raster
and conditioning. All 120 native delivered face and repaired-title-area crops
and body overviews were inspected: replacement identity remained coherent,
with no obvious double-image blend at the three window joins. The former title
area stayed materially steady through the source fade, with soft texture.
Original soundtrack delivery was checked separately. Fast movement still
softens. The artist now accepts this exact original-audio example for release.
This does not validate longer clips or the other audio scenarios at 1080p.
The Studio now selects the tested 41-frame windows automatically at its 1080p
resolution setting, while lower resolution settings retain 81-frame windows.
Both cached and inline graph builders use this policy without another artist
control. Fifteen focused builder, recipe and provenance checks passed.

Matching five-second Wan selected-speech and silent-source tests also completed
at 1080 Ã— 1920, 24 fps and 120 frames using 41-frame windows. All delivered face,
repaired-area and body frames were inspected independently, including the three
joins. Character identity and broad gestures remained coherent, with soft fast
hand movement and no conspicuous top-repair colour flash or hard join seam.
The selected soundtrack was checked separately; early mouth posture during its
quiet lead was included in the subsequent artist review request. The silent
delivery contains zero audio tracks. The artist accepts both exact five-second
files for release. Longer selected-speech and silent clips remain separate tests.

A separate Wan render from a genuinely silent source also completed at the
same five-second size and frame rate. All 120 native face and repaired-area
crops, plus body overviews, were inspected. Identity and gestures remained
coherent, with no obvious 81-frame join jump. The repaired title area appeared
steady through the source fade, with soft texture. The delivered video contains
zero audio tracks. Artist acceptance of this example is pending.

Thirteen offline native graph tests passed conversion, export, reload and
exposed-control changes, including automatic H3 text cleanup. Computed root
and internal wire crossings are zero. Actual Desktop and phone interface
testing remains unverified. Saved Studio records and unrelated installed
modules were preserved by the local update.

A five-second LTX 2.5 original-audio test also completed, but failed motion
review: the replacement missed the source's large hand gestures and changed
the facial expression. Original soundtrack delivery was verified separately.
The matching silent test is staged; motion conditioning needs correction before
further testing of that route. A successful render alone is not a quality pass.

A separate native partial-source comparison retained the broad gestures, but
failed identity and text cleanup: the replacement morphed back into the original
performer within the opening frames and retained source captions. Its native
masked video and fixed-audio checks passed, which establishes preserved latent
context rather than a valid replacement. This recipe is rejected and is not
included in the public Studio builder.

A separate five-second LTX 2.5 Union-pose comparison completed at 720 Ã— 1280
and 24 fps. The lossless source pose sequence was inspected before sampling;
all 120 delivered face and title-area crops and body overviews were then
reviewed. Replacement identity and broad hand gestures remained coherent,
and the source title stayed removed through its fade. Facial expression and
some mouth shapes differed from the original performance, with softness
during movement. Native frozen-background and audio tensor checks passed;
these do not certify decoded pixels or exact speech timing. Artist feedback
is pending. The same-resolution refinement and background-mask composition
remain experimental and are not included in the public Studio builder.

The matching five-second silent-source Union-pose test also completed with
zero delivered audio tracks. All 120 native face and repaired-area crops and
body overviews were inspected. Identity and broad gestures remained coherent,
but mouth movement followed the original silent visual performance too weakly.
That facial-performance result fails review and is not a production pass.

A separate five-second replacement-speech Union-pose test completed with a
body-and-hands motion guide and native LTX audio conditioning. An independent
review inspected all 120 face crops, repaired-area strips and body overviews;
the root inspected selected speaking and fast-motion frames. Character and
broad gestures remained coherent, but fast movement introduced facial softness
and coloured fringing. The selected audio was delivered at zero lag, and saved
audio latents were exactly preserved through both sampling passes. These are
audio-handling checks, not lip-sync certification. Artist speech assessment
and final-resolution quality remain pending. The recipe remains private and
experimental rather than a change to the public Studio builder.

A controlled native audio/video coupling comparison changed only modality scale
from 1 to 3, plus output names. All 120 face, top, full-frame and lower-torso
views were inspected. Mouth movement became larger but less natural, with lip
and cheek colour fringes; a new caption-like overlay appeared over the clothing.
Fast hand and face softness remained. The selected soundtrack and frozen audio
latents passed their checks, but the visual result fails review. This setting
remains exploratory and is not promoted to the public default.

LTX whole-scene camera transfer remains experimental. The video-derived scene
guide retained broad body timing, but its native comparison still warped
architecture and changed clothing. A separate native temporal-depth comparison
improved architecture and outfit continuity, but left the camera largely static
and apparent hovering after the intended jump. A controlled comparison using
the author's signed reference-position correction also retained an unwanted
late lift and a largely stationary street camera. These experiments are not
included in the shipped Studio route. Corrected LTX original/silent scenarios,
final-resolution quality and artist video signoffs remain required before
calling all three routes production ready.
Private inputs, dialogue, generated media and machine paths are excluded from
the public package.

## 1.3.7 editable speech checks, 10 October 2026

Original audio + performance remains the default for all engines. Reference
speech is separate, and inactive uploaded or cloned audio stays out of Original
generation. Wan's graph now selects the reference audio once and verifies the
actual waveform, interval, source frames, reviewed mask, character opening,
guide file and performance seed before sampling. Its final soundtrack and
optional mouth finish use that same selected track. Studio rebuilds mismatched
guides automatically; an edited standalone graph reports what needs rebuilding.

Unsupported H3 and Wan speech intervals are rejected before tracking or
reference encoding. H3 remains limited to 0.21â€“5 seconds in the current Studio
route, and Wan replacement speech to 30 seconds. Original-length selection still
uses the actual source duration, with these limits explained before preparation.

H3 conditioning caches are read as safe CPU tensor data, checked for compatible
paired streams, matched to the take's required context and pinned by file digest.
Healthy historical caches with shorter contexts rebuild for the current take.
Missing or damaged caches select the
existing native reference-rebuild stage without deleting other caches or saved
projects. All four existing healthy native caches pass the new validator.

Eight offline tests of frontend 1.53.10 pass conversion, export, reload and
changes to the exposed seed. They include the new Wan reference-speech graph.
Both root and internal layouts have zero measured wire crossings. Browser and
physical phone testing remain unavailable.

A new original-performance Wan render completed with two native continuation
windows: 48 delivered frames at 24 fps, 1280 Ã— 720 and one original audio track.
Inspected frames retained the replacement character through the source body
motion. This mannequin-source test does not establish human mouth accuracy or
long-clip quality.

Two matched H3 original-performance tests completed but failed visual review:
the replacement character was lost after the opening frame. Removing the source
latent initialisation did not resolve this. Those diagnostic changes are not
shipped. The previously accepted H3 reference-speech sample remains separate
evidence, and LTX speech remains experimental. Seedance was not submitted.
Private test recordings, scripts, workflows and render evidence are excluded
from publication.

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
was used. The guide contained 125 frames at 25 fps and 480 Ã— 640; the finished
video contained 120 frames at 24 fps and 720 Ã— 1280, with one selected audio
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
720 Ã— 1280, 120 frames at 24 fps, one selected audio track and no mouth finish.
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
delivered 120 frames at 24 fps, 720 Ã— 1280 and the selected audio, with no mouth
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
1080 Ã— 1920 and H3 at 720 Ã— 1280 with 40 Euler steps. Both delivered 48 frames
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
at most five seconds. LTX supports up to fifteen seconds in Viewport to final
and five seconds in its other Studio routes. Wan continues through bounded
frame windows.

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
| Wan 2.2 Fast | 720 Ã— 1280, 48 frames at 24 fps, 2 seconds | Native pose/face control, approved opening latent reference, isolated character CLIP Vision reference and approved background mask. Two windows, six steps each. Visible hand gesture transfers; hat, jacket and overall appearance remain consistent. Title and subtitle overlays are absent in all 48 inspected frames. Original audio is restored. Exact lip synchronisation and identity similarity were not measured. |
| LTX 2.5 | 1080 Ã— 1920, 48 frames at 24 fps, 2 seconds | Corrected image-to-video conditioning and source registration. Appearance and text removal passed visual inspection. Motion transfer is understated; exact performance matching was not measured. |
| MiniMax H3 | 288 Ã— 512, 48 frames at 24 fps, 2 seconds, 40 steps | Native depth control with separate opening and character references executed and restored audio. The user rejected its quality: motion was nearly static. H3 remains experimental. Higher resolution and longer graph settings are supported but were not quality-validated by a new GPU render. |
| Seedance | Mocked orchestration and credential checks | No paid draft or final render was performed. The native accepted-final node outputs 1080p; this is explicit in its paid action label and result metadata. |

The Wan test generated natively at 704 Ã— 1280, then exported at the source
aspect ratio of 720 Ã— 1280. Native video execution took 320.226 seconds;
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
1.5â€“1.7 second cross-fade is absent. Original audio correlation is 0.999993.
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
1088 Ã— 1920 mask batch with radius 30 processed in 0.907 seconds. No blur, hole
filling or mask-area reduction is introduced. The slow attempt was interrupted
and is not recorded as a completed render.

Two new 1080 Ã— 1920 LTX tests each exported 48 frames at 24 fps, with two seconds
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
offline for preparation, look design, Wan, H3, H3 enhancement and both LTX routes. Native
conversion, export, reload and exposed-control changes preserve the compiled
inference inputs. Smaller nested groups keep each operation explorable.
Unneeded hand-off sockets are trimmed again after configuration. H3 uses a
native multiline text source to expose its existing prompt in Your inputs;
the prompt text and model settings are preserved.

Node sockets are arranged before layout. ELK routing is supplemented with a
bounded orthogonal wire router that avoids occupied nodes and unrelated wires.
Exported native positions were inspected separately from browser rendering.
The root and internal layouts have zero measured unrelated wire crossings
for all seven tested stages. The crossing check also detects overlapping wires
and contacts at bends; branches sharing the same output are intentional
signal junctions. Other node versions or edited graphs may lay out differently.

DOM interaction checks cover the shared resolution and original/custom length
controls, direct audio, cloning, audio offsets, automatic review IDs and graph
handoff without queueing work. Browser visual testing remains unavailable
because Codex's saved browser setting rejects the local ComfyUI origin.

## Full-length Wan qualification, 11 October 2026

A native original-performance render delivered all 570 frames at 24 fps,
720 Ã— 1280, including a camera cut. Bounded preparation and rendering completed
within the monitored memory reserves using the saved loading policy. Every
frame and section boundary was inspected. Original audio packets and decoded
audio match the delivered source prefix; the omitted final 6 ms is a near-silent
codec tail. Removed text stayed clean throughout.

The artist accepted this full-length result for this release while noting
quality degradation between chunks. Changes in sharpness and fine detail
between sections remain a known limitation. This approval covers this 720p
original-performance qualification; final 1080p and other audio scenarios
retain their separate validation requirements.

## Native Wan Graph continuation, 11 October 2026

The installed native subgraph export completed all 570 frames in eight motion
preparation sections, including the camera cut, followed by a separate native
merge. Next retained the same preparation recipe and motion cache key through
every section. Finish returned the prepared render graph without manual IDs.
Planning did not queue jobs or alter any of the 35 saved Studio projects.
The merge exceeded the initial three-minute monitoring window and later
completed successfully; it was not resubmitted. Rendering from this edited
namespace remains a separate check.

Two native compatibility failures were repaired and independently reviewed:
Comfy's injected runtime cache marker is excluded from recipe identity, and
six specific omitted optional inputs retain the same identity when native
import adds their empty-string defaults. Nonempty values and other edits still
require a new plan. All 29 focused planner checks and 21 integration/provenance
checks pass. These native execution and identity checks supplement the existing
frontend save/reload tests; they do not establish Desktop or mobile visual
interface readiness.
## Viewport artist review, 13 October 2026

The artist approved the five-second H3 train viewport result. The equivalent
Wan and LTX results were rejected. Wan did not retain the scene or camera;
LTX retained the crude blockout character shape and showed severe warping.
Successful execution of those two routes is not visual qualification. Their
viewport quality remains unresolved; earlier performance-edit approvals apply
only to those separate workflows. New viewport recipes require fresh renders
and artist review before being presented as qualified.

After this review, the artist agreed to remove Wan from viewport mode. H3 is
the recommended viewport route; Wan's approved performance-edit routes remain
available. LTX's official-recipe retry retained the crude character, and adding
interior appearance keyframes restored the character but did not resolve
warping between keyframes. Those diagnostic retries are not artist-approved.

### Progress and subject UX verification

The full Python regression suite passes 636 tests. JavaScript stage-progress, subject debounce/stale reply, artist graph and Wan graph checks pass. A real local CPU YOLOv10 probe detects the performer in four of five sampled source frames. Explicit LTX object Canny routing is graph-tested; it has not yet received a new artist quality approval.

The design detector reports three source-less image warnings on intentionally hidden upload/starting-frame placeholders. Their source is assigned from the uploaded media before display. No placeholder is intentionally shown. Live browser visual checks remain unavailable because the browser tool rejects the local ComfyUI address; responsive CSS and behaviour checks do not substitute for visual approval.

### Artist editor redesign and recovery

The navy/violet three-panel layout follows the supplied artist-approved design direction while retaining actual model resolution options, original/custom audio, masks and native graph access. Source footage previews before preparation. Oversized original-length selection exposes an enabled trim-recovery action, including before look assets exist; behavioural tests confirm it returns before project creation or queue submission. Cancel run is beside live progress and delegates to the existing prompt-scoped cancellation endpoint.

Graph conversion leaves native Load Image inputs visible and restores exact selected filenames through the native preview callback. Multiple references, colon-ID remapping and equivalent compiled render inputs pass offline tests. Full Python regression: 637 tests pass; six JavaScript suites and module syntax checks pass. The fresh static review resolved its responsive cascade, recovery-test and ready-frame navigation findings. Live browser visual and preview lifecycle verification remains unavailable, so static checks do not imply visual approval.

H3 Detailed uses 40 steps versus the approved Fast Turbo route's eight. Native Match reference sizing is already used; reducing reference detail is not assumed lossless. No fresh multi-reference timing benchmark is claimed. An idle test-server model release was requested after verifying its queue empty; the active Desktop instance was not interrupted.
