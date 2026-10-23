# Zura Studio

Zura Studio is included in the official **Zura Nodes** pack, published by
**ZURAVFX** at https://github.com/ZURAVFX/ComfyUI_zura_nodes.
Start ComfyUI and click **Zura Studio**, or use `Open_Zura_Studio.url` on a
default local installation. The direct studio link is
`http://127.0.0.1:8188/?zura=1`.

Open **Zura Studio** in ComfyUI, choose a workflow, then drop a source video.
Its thumbnail confirms the upload.

The prompt composer contains **Add video**, **References** and the workflow
selector. Model, resolution, clip length and audio sit below the writing area.
The settings button opens advanced controls. **Controls** opens selection and
look tools; the current image or video keeps the full central canvas.

For **First & last frame**, choose that workflow in the composer. Upload the
two endpoint images, describe the transition, then generate. No additional
reference images are used. Switch **Audio reference** on to supply a track,
or off for H3-generated audio. Switching off keeps the uploaded file locally
but does not send it into the graph. The approved recipe uses the H3 FL2VA
INT8 model, Turbo at strength 1.0, eight steps, Comfy Kitchen attention and
res_multistep/simple. Lengths show H3's actual 24 fps frame grid, preserving
the final anchor. Width and height accept multiples of 32 up to 1.03 MP.
Both audio variants pass installed-node validation; this integration still
needs a visual GPU render check.

- **Motion transfer** rebuilds the full frame around the source movement.
  With H3, **Keep original people** edits the surroundings while protecting
  the people and their original facial performance. Build the look from
  references; replacement audio can change the soundtrack, but cannot animate
  the protected mouths.
- **Object swap** changes a selected person or object and keeps the surrounding
  shot as the guide.
- **Viewport to final** turns a grey 3D blockout into a finished whole scene.
  H3 is recommended. LTX remains experimental; Wan is available in the other
  editing modes.
- **Relight** changes the scene lighting while retaining the source composition.
  Video generation uses the supplied Wan 2.1 chained workflow, replacing the
  H3 relight video option. Create and review a lighting image first, then run
  fixed four-step sampling in 81-frame sections, at 720p-class output.
  The original soundtrack is restored. Check
  joins on longer Wan clips and inspect the result for identity, material and
  temporal changes.

Keep original people passed a short scene-replacement render; artist review
is pending. Moving boundaries are reconstructed generatively, so inspect hair,
hands and occlusions. Relight passed a short lighting-consistency render;
artist review is pending. Preserving subtitles can leave darker patches around
their text. The updated conditioning requires a normal ComfyUI restart after updating
Zura Nodes. See the [render evidence and limits](ARTIST_STUDIO_VALIDATION.md).

Choose **Starting look**:

- **Build from references:** add one to three images of people, objects,
  materials or environments. Describe the change if needed. All references
  guide the creation of one starting frame; they are not pasted into a collage.
- **Use finished frame:** upload an already-composed image. This skips
  image generation. Extra appearance references are optional; the first is the
  separate appearance input for video routes that support it.

For a finished image, **Frame position** offers First, Last or Frame number
with H3 and whole-scene LTX. Frame numbers start at 1 in the selected **24 fps
output clip**, rather than in the untrimmed source. Last means the final
delivered frame, excluding internal model padding. These are native timed
conditioning guides, not a promise of pixel-perfect reconstruction. One timed
finished image is supported; additional images remain appearance references.
Wan Animate and masked LTX edits retain their existing reference behaviour.
Timed H3/LTX paths have structural and native-node tests; their visual quality
has not yet been qualified with a new render.

Whole-frame reviews open on **Guidance**. You can still switch to Original or
Mask. **Start over** clears uploads, settings and stale frontend state and
returns to Source. It cancels only the current Studio shot when necessary;
saved shots and their output files stay in your local library.

In **Viewport to final** with MiniMax H3, **Use references directly** is the
recommended starting point. Review the source motion, then generate using
the blockout video and up to nine look references without an image-generation
stage. This is the artist-approved blockout route. **Build starting frame**
lets you generate, review and regenerate a scene image first; check its camera
carefully before animating. **Use finished frame** accepts your own composed
image. Saved shots keep their previous choice.

Each viewport route uses its model's own guidance: LTX reads the raw blockout
with its Layout-to-Render adapter and H3 receives the source as a reference video.
Wan's human pose route did not retain whole-scene blockout motion and is no
longer offered for viewport renders. Zura does not add a blanket Canny or depth
pass. In the tested LTX scene, adding depth softened the image and shifted
details, so the raw layout remains the default.

The optional shared **Prompt** is passed to LTX, H3, Wan and Seedance. When
building a starting frame, it also guides that image.

Choose a model, **Resolution** and **Clip length**. Audio keeps the original
performance by default; expand **Audio** for a replacement track or voice.
Prepare the shot, review the selection, then review the starting frame before
choosing **Animate this look**. People, object edits and viewport renders use
the same controls. Wan and H3 are strongest for people; object edits need their
own quality review. Changing a whole environment may lose the source camera move.
Job IDs, reference copies, model preparation and cache hand-offs are automatic.
Uploading a finished starting frame preserves its bytes. **Replace starting
frame** swaps it after selection review without regenerating the image.
Existing saved projects and media remain readable on the same computer. Legacy
storage paths and node IDs remain compatible; public names use Zura branding.

## Select the area

The workflow choice controls what changes. **Motion transfer** rebuilds the
whole frame around source movement. **Object swap** changes the selected area
and uses the rest of the shot as a guide. **Viewport to final** uses the grey
render as the camera and layout guide for the whole scene. The model routes differ,
so check the result for camera movement, contact and scene consistency.

For a masked edit, expand the selection settings for automatic person selection,
**Describe the area** (for example, a person in a red coat or a chair), and
**Click to select**. Click on the selected opening frame to include an area;
use Exclude to reject unwanted parts. Zura tracks the selection through the
clip. Changing the source or selected start frame clears old points. Review
the complete tracked mask before continuing.

New shots leave extra room around the selection for hair and clothing. This
padding is visible in the mask preview; adjust **Room around the selection**
when needed. Existing shots retain their saved margin. A different silhouette,
such as taller headwear, still needs enough room inside the reviewed mask.

The character or scene preview keeps the source framing. For a masked edit,
the approved mask also limits the opening-image change before animation.
The opening edge is lightly softened inside that boundary. This does not expand
a mask that has already been reviewed.
Movement, ground contact and camera fidelity still need review in the generated
video, especially with LTX. Whole-scene selection does not make a generative
model an exact camera or animation solver.

## Studio and graph view

Click **Graph view** at the top to open the current stage as an editable native
ComfyUI workflow in a new tab. Preparation, character preview and animation
follow the current project state. Animation uses the character look you can see
in Studio. **More controls > Open in graph view** lets you select a different
stage. Opening a graph does not queue a render or spend credits. With no shot
uploaded, Graph view simply returns to the current ComfyUI canvas.

Click **Zura Studio** at the bottom left to return. Studio retains its saved
project; graph edits stay in the new workflow and are not imported back into
Studio. Save that workflow normally in ComfyUI to retain your edits. Closing
Studio with the cross also returns directly to your existing canvas.

Wan's editable motion graph contains native pose detection, SAM character
segmentation and reference cropping. Motion preparation runs in bounded
sections: Queue the current section, then click **Next section**. After the
last section, choose **Finish motion**, Queue the merge, then **Open render**.
The section controls carry the reviewed shot and cache references automatically;
there is no need to copy IDs. **Edit motion** returns to the preparation graph.
The render graph uses the completed preparation with its editable native sampler.
H3 and LTX
exports contain editable prompts and conditioning rather than frozen Studio
conditioning caches. Native subgraphs form a single left-to-right chain with
labelled stage hand-offs. These small Zura data adapters carry existing model,
image and audio objects without changing or copying them. Open a stage to see
the native inference nodes and their routed connections. Common source, prompt,
seed and sampling controls are exposed on the graph. Technical settings remain
editable inside each stage. Graph conversion checks the compiled render inputs
and restores the original editable graph if conversion changes them.

### Starting images without Studio

Open **Zura Build Starting Frame** or **Zura Build Starting Frame 3 References**
from Zura Nodes templates. Choose the source opening image and each appearance
reference in Inputs, edit the prompt and queue normally. The output is a starting
image for Studio's **Use finished frame** route or your own video graph. These
workflows require no Studio project, approval or copied IDs. The three-reference
version expects all three inputs; use the single-reference version for one image.

**Zura Use Finished Starting Frame** loads and previews an existing image without
sampling. All three are saved native workflows. Open the subgraphs to edit the
underlying nodes, then save and reopen normally in ComfyUI.

## Audio and performance

The same selector is available for Wan, MiniMax H3, LTX and Seedance:

- **Original audio + performance** is the default. It keeps the video's
  soundtrack and source-performance guidance. No replacement speech guide or
  mouth finishing pass is added.
- **Reference audio + new performance** uses an uploaded or locally created
  voice track. **Create a new facial performance** is enabled automatically.
  Untick it to use the track as music or sound design instead.

Switching back to Original retains the reference track on this computer so
you can select it again without uploading it. An inactive reference never
feeds the renderer. These modes select the appropriate guidance; they do not
guarantee exact expression or phoneme reproduction by every model.

**Reference audio** accepts WAV, MP3, M4A, FLAC, OGG, AAC and AIFF, or audio from
an MP4, MOV, MKV or WebM. Video uploads in this field use only their audio. It replaces
the source soundtrack for both guidance and the finished video. By default it
starts at zero at the beginning of your selected video interval. Adjust its
own **Reference audio start** in More controls if needed. It is trimmed to the
selected clip length; shorter tracks are padded with silence. Remove it with
**Use original audio and performance**, or select **Original audio + performance**.
Changing audio requires a fresh guidance review.

Silent source videos receive valid silence for audio encoders, including the
full-resolution reread and LTX temporal padding. The final video stays quiet
when there is no source audio and no reference track.

With an uploaded track, **Create a new facial performance** selects the engine's
speech route. H3 encodes and holds the selected audio fixed during sampling,
including the original soundtrack in Original mode, alongside
its native audio guide; LTX conditions video directly on the selected audio.
Both keep their generated faces by default. Wan uses a native InfiniteTalk
speech-performance guide before Wan 2.2 Animate. Run
**Setup_Wan_Speech_Windows.cmd** once for its separate Wan 2.1 I2V base,
InfiniteTalk patch and wav2vec2 weights. Setup reports any missing native node
packs. The guide runs at 480 x 640 and 25 fps, then native face detection supplies
the facial performance to Wan 2.2 at the shot's 24 fps. Wan 2.1 weights are used
only for this guide; the final renderer remains Wan 2.2 Animate.
H3 and LTX do not need these separate speech models unless lip refinement is
selected. With speech disabled, the selected track still reaches their native
audio conditioning for music or sound design and can influence movement.
The speech reference is cropped automatically from the approved character look,
with native source and opening-face checks. Wan retains the original body pose,
camera and masked background. Reference speech supplies a new face performance;
it can change head and eye expression. Original mode and soundtrack-only mode
keep Wan's unmodified source face guide. Review large head turns and occlusions.

Studio creates, validates and caches the guide, clears the previous model at an
idle queue boundary, prepares Wan's conditioning and renders automatically.
Changing final resolution or sampling quality can reuse the same verified guide;
changing the speech, its offset, seed, source or approved look creates a new one.
The extra guide takes several minutes and needs substantial system memory.
Reference speech currently supports a maximum of 30 seconds and one visible
human face. Longer takes and complex faces have not been quality validated.

**More controls > Open in graph view > Wan speech performance** opens its native
loaders, audio conditioning, sampler and export as editable subgraphs. Queuing
that unmodified graph can save a guide for Studio to reuse after successful
completion. Edited sampling or reference inputs are not silently adopted as
the original Studio recipe. Opening a graph alone does not generate anything.

The Wan animation graph verifies that its connected audio, timing, look and seed
still match the saved facial performance before sampling. If you change them,
update the shot in Studio, regenerate the facial performance and reopen the
animation graph. Studio handles that regeneration automatically. Advanced graph
users can instead connect their own native face-motion guide deliberately.

**More controls > Refine lips after generation** is off by default for Wan,
H3 and LTX. It optionally adds a second pass if articulation needs help. That
pass blends only around the detected mouth, with a mild bounded detail filter,
preserving the surrounding cheeks, beard and chin before video compression.
Review both timing and detail. The accepted Seedance final can use the same local
mouth refinement. Native LTX/H3 speech quality remains experimental; a completed
render does not establish good identity, motion or lip sync.

Run **Setup_Speech_Windows.cmd** once for the optional sharp local models and Python
dependencies. There is no paid speech call or automatic download during renders.
The sharp model uses 20 diffusion steps, 16-frame windows, sequential audio
guidance and sliced VAE processing to bound GPU memory while retaining 512 px
inference. Setup pins the published LatentSync 1.6 weights. Add `--fast-only`
to setup for just the smaller MuseTalk bundle. Existing graphs that explicitly
select MuseTalk retain that choice; newly created Studio graphs use Automatic.
Lip sync needs one visible human face. Profiles, occlusion, stylised characters
and multi-person shots may fail or lose detail. MuseTalk works at a 256 px face
crop internally, even when the finished video is HD. Sharp lip sync needs a CUDA
GPU. Review every talking take.
The optional mouth finish expects dialogue and a clearly visible face. Music,
noise, breathing, occlusion and large head turns can give weaker results.
The local LTX graphs use the installed text encoder; unused cloud text-encoding
branches from the source templates are removed.

**Create a voice track** expands the optional local Zura LongCat controls. Choose
voice cloning, provide a clear sample and its exact transcript, and enter the
new words. Or choose text to speech without a sample. The generated track is
selected and previewed automatically. Setup uses **Setup_LongCat_Windows.cmd**.
Existing audio files do not require voice cloning. In graph view, a native
**LoadAudio** or **Zura LongCat Voice** AUDIO output can feed the Reference Audio
adapter or Mouth Motion from Audio node directly.

Samples, scripts, generated audio and project records remain in local ComfyUI
input/output folders. They are never uploaded to GitHub or included in releases.
The optional paid Seedance route sends its guidance to the selected service
when you explicitly queue a paid action.

**Original clip length** selects the entire source from the beginning at 24 fps,
rounded down to a whole frame. **Custom length** enables Seconds and the video
Start control. Model duration limits still apply (H3 supports up to 5 seconds).
The original-length option never silently substitutes the custom duration.
Unsupported H3 and Wan speech lengths are reported before preparation, so you
can change the length or model without spending time tracking an unusable clip.

## One project, several models

| Model | Current behaviour |
| --- | --- |
| LTX 2.5 | Original, replacement-speech and silent five-second whole-scene examples accepted. Source body guidance and native audio conditioning use the approved opening scene. Masked speech, longer clips and camera retention with a changed environment remain experimental. |
| MiniMax H3 | Local replacement with separate opening and character references, native audio guidance and depth control. Review face fidelity, gesture transfer and speech timing. |
| Wan 2.2 Animate | Local pose and face-driven replacement with the approved background mask. Uses the approved opening scene for the latent reference and an isolated character view for CLIP Vision. |
| Seedance | Paid draft and accepted-final route through Comfy. Requires explicit paid action and Comfy sign-in. No paid calls were used during this update. |

Switching model, output resolution, sampling effort or seed retains the approved
mask and look. Changing the source interval, performer, replacement scope, mask
margin, text removal or guidance audio requires a fresh mask review. Changing
appearance direction requires a fresh look preview. Jobs are never duplicated
by repeated clicks or automatically retried after an ambiguous paid submission.

## Size and timing

There is one output resolution selector. LTX and Wan offer small 512 px tests,
768 px, 720p HD and 1080p Full HD. H3 offers **720p**, **1080p Enhanced H3** and
**1080p Native H3**. Enhanced H3 generates at 720p, releases its generation
models, then automatically enhances each frame to 1080p. Only the completed
enhanced video appears as a finished take. It keeps the selected soundtrack;
silent footage stays silent. Native H3 1080p is a separate, demanding render
and has not completed on the tested 16 GB GPU. It does not silently switch to
enhancement. Older saved 1080p projects retain their native setting.

If Enhanced H3 reports missing setup, run **Setup_H3_Enhancement_Windows.cmd**
once and install VideoHelperSuite through Comfy Manager. The setup verifies the
separate 34 MB Nomos model. Rendering does not download models. In Graph view,
**H3 base render** opens the generation stage; after it completes,
**H3 1080p enhancement** opens the editable native enhancement stage.

720p uses a 1280 px long edge and 1080p uses 1920 px. Landscape and portrait
source proportions are preserved. Native models require dimensions in multiples
of 16/32/64; the final export restores the source aspect ratio at the chosen size.
Generation and mask review have separate internal sizes: the 512 px review stays
light, while rendering rereads the original footage at the selected resolution.

**Clip length** governs the selected source interval and delivered audio/video.
There is no hidden two-second preview limit. Native temporal padding is trimmed.
H3 currently supports 0.21–5 seconds; use one continuous shot with H3 or LTX.
Short H3 takes use a full 124-frame model context internally, with the requested
video and audio length restored at export. Padding cannot create missing motion;
the longer context is a model setup correction, not a quality guarantee.
Wan uses bounded 41-frame windows at 1080p and 81-frame windows at lower
resolutions, with real-frame continuation and automatic cut detection.
Native joins retain the previous frames and discard repeated context instead
of cross-fading faces.
Each chunk decodes in one temporal tile, retaining spatial tiles for memory.
Continuation resets at cuts. Review joins and facial motion visually.
Longer Wan clips can show changes in sharpness and fine detail between sections.
This remains a known release limitation.
The tested Wan source contains one central performer. Explicit pose targeting
in multi-person shots has not been validated.
Seedance supports model-specific output sizes; its final paid step is 1080p.
Unsupported choices fail before submission rather than silently changing size.

**Fast/Detailed** changes denoising effort, not resolution or clip length. Wan
uses shift 8, Euler/simple, and the relight and realism LoRAs at strength 1.0.
Fast adds the Wan2.1 I2V LightX2V adapter at strength 0.6, with 6 steps and
CFG 1. Detailed removes that acceleration adapter and uses 40 steps with CFG 5,
while retaining relight and realism.
The native loader explicitly uses `fp8_e4m3fn_fast` for the supplied KJ-scaled
Wan checkpoint; current core otherwise expands it to FP16 and renders much slower.
H3 has its own compatible 8-step acceleration / 40-step Euler route. Its native
depth ControlNet carries source motion; separate image references carry appearance
and an audio guide carries speech timing. In both audio modes,
the selected waveform also replaces the audio latent with a zero-noise mask.
This prevents H3 from generating different audio beneath the finished soundtrack.
Real silence pads the waveform to the internal duration before encoding; export
still uses the selected clip length and original track. This uses the native H3
sampling contract demonstrated by [Pixaroma's audio-sync node](https://github.com/pixaroma/ComfyUI-Pixaroma/blob/main/nodes/node_h3_audio_sync.py).
It does not also attach the source as a
video reference. Short takes retain 124 frames of internal model context and trim
back to the selected duration. This increases memory and render time for previews.
Untouched background cells retain native source-video latents during sampling.
The editable area is expanded conservatively across each VAE chunk and DiT
patch to cover moving character edges. This reduces colour drift without a
post-render RGB composite, but VAE decoding can still change fine detail.
In Graph view, bypass **Zura · Preserve H3 Background Latents** to use the
earlier full-video sampling path while retaining fixed audio.
LTX keeps its existing distilled schedule and neutral audio/video modality guidance.
Both LTX passes receive frozen source audio with the zero-noise mask used in
the official LTX-2.5 Audio-to-Video workflow;
the restyle route no longer generates silent audio and merely restores the
soundtrack afterwards. Earlier LTX previews failed the user's lip-sync review.
Review mouth timing on new takes; speech conditioning does not guarantee exact
phoneme matching. LoRAs are never transferred between families.
Speaker-reference tokens are identity context and are not used as the speech
timing signal. See the [official workflow compatibility guide](https://docs.ltx.io/open-source-model/reference/workflow-asset-compatibility).

## Preparation and masking

**Remove on-screen text** adds detected title panels and subtitles to the
pre-generation removal mask. Check the orange coverage before approval. The
detected text panels are held across the selected clip so intermittent OCR or
changing captions do not briefly uncover the old text. Performer tracking stays
per frame. Moving titles or cuts can require a larger removal area; review it.
H3 also clears these regions in its depth guidance before sampling. When
background preservation and text removal are enabled, H3 first repairs eligible
background text with LaMa before sampling. It uses the saved genuine performer
outline separately from the expanded edit mask, and conservatively skips a text
panel if it touches or comes close to the performer. The generated character
then fills the approved edit area over the cleaned source. This runs
automatically, with no extra mask or cleanup controls.
The original RGB background and combined mask condition each supported local model
before sampling. There is no post-render performer paste or text cover-up.

Wan preparation uses native `PoseAndFaceDetection`, `DrawViTPose`, SAM 3 and
`ImageCropByMaskAndResize`.
The character crop includes its detected head and is isolated onto a neutral
background before CLIP Vision encoding, preventing a multi-view sheet from
being used as the complete scene reference.
Three new Zura adapters decode the reviewed source
and mask, validate and save prepared CPU tensors, then load them with
`weights_only=True`. The updated Zura renderer retains its legacy class ID and
adds the `ZuraWan22LoopedChunksSampler` ID. Trend Studio is not a runtime
dependency of this interface. Its topic-search/director helpers are unnecessary
for the user's selected, uploaded source.

## Installation

Update the official `ComfyUI_zura_nodes` pack, install its declared requirements,
then restart ComfyUI and refresh the page. The interface reports missing models.
ComfyUI Desktop can assign a different port. Its Zura Studio button uses the
active instance automatically; the default-port launcher may need that port.
The local installation preserves the former standalone Genj extension in the
disabled backup folder to avoid duplicate interfaces; keep only one active
Studio extension. Existing Zura nodes and workflows continue using their old IDs.

Native dependencies: current ComfyUI (including H3/Union 2.0 and SAM 3 support),
[ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes),
[ComfyUI-ArtVenture](https://github.com/sipherxyz/comfyui-art-venture),
ComfyUI-WanAnimatePreprocess, comfyui_controlnet_aux,
ComfyUI-MelBandRoFormer, ComfyUI-essentials (Mask Fix) and the LTX native nodes
used by the bundled graphs.
[ComfyUI-ArtVenture](https://github.com/sipherxyz/comfyui-art-venture) supplies
LaMa inpainting, and KJNodes supplies the lazy switch used to run that repair
only when selected. The first H3 background-text
cleanup may download `big-lama.pt` (about 196 MB) through ArtVenture's native
loader if it is missing. Other optional speech models still use their separate
setup steps. FFmpeg must be available on PATH.

Model filenames are defined in `artist_studio/wan.py`, `artist_studio/h3.py` and
the model-status section of `artist_studio/studio.py`. No models, uploaded
references, project records or credentials are included in the release.

## Verification

Automatic and description-based masks restart tracking at camera cuts, then
rejoin the original timeline. Check that each shot selects the intended person
or object in the mask preview. A cutaway to another subject can require a
selection correction. Missing selections are flagged for review rather than
filled with an invented mask. Point selections retain their original tracking
path. Text-removal locations are held within each tracked shot, so a title in
one shot does not select its former location in a later shot.

For different object categories, separate descriptions with commas, for example
`microphone, chair`. SAM treats each as a separate category; a phrase such as
`microphone and chair` can select only one. Review both regions before continuing.
The H3 Keep original people option requests up to 20 people for its joint
protection mask; detection can still miss small or occluded people, so inspect
the full selection preview.

These selection changes require a fresh mask review for an older project;
the saved source, character and previous renders remain available.

Shared-engine tests check approval retention, legacy resolution migration,
native preparation, family-specific model stacks, exact mask/frame alignment,
safe cache roundtrip and the single resolution/length interface. Existing Wan,
multicam, camera, audio and voice regression suites were rerun. Live render
results and limitations are recorded separately in `ARTIST_STUDIO_VALIDATION.md`.
DOM interaction checks are separate from browser visual checks, which remain
unavailable because of the saved local-origin browser permission.

### Progress and subject guidance

Studio shows the active stage, elapsed time and native sampling steps where available. Once several steps have completed, it estimates the remaining time for that stage. Loading, encoding, decoding and saving use an indeterminate bar when ComfyUI reports no measurable total. Queue position is separate from render progress; this is not a whole-job completion estimate.

More controls includes Auto, People and Objects & scenery. Auto samples five frames locally on CPU using an already-installed optional YOLOv10 detector. Detection is advisory, and missing detectors or grey viewport figures return an uncertain result. Explicit Objects uses Canny with LTX's existing Union adapter, avoiding pose estimation; H3 retains its native scene controls. Wan Animate requires a human performance. Auto and People preserve the previously validated human routes.

H3 shot settings expose Sampling mode and H3 sampling steps directly. Turbo recommends eight steps; Standard defaults to 40. You can set an integer count from four to 80 for the next render. Changing mode restores its default count. Custom counts are unbenchmarked and extra steps do not guarantee better quality. The step count does not change a render that is already running.
