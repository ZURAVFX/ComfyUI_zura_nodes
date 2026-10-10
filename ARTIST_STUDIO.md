# Zura Studio

Zura Studio is included in the official **Zura Nodes** pack, published by
**ZURAVFX** at https://github.com/ZURAVFX/ComfyUI_zura_nodes.
Start ComfyUI and click **Zura Studio**, or use `Open_Zura_Studio.url` on a
default local installation. The direct studio link is
`http://127.0.0.1:8188/?zura=1`.

Open **Zura Studio** in ComfyUI, upload the performance video and a character
image, optionally add **Reference audio**, then choose a model, **Resolution**
and **Clip length** (original video or a custom length). Prepare the shot,
check the mask, create the character preview, then animate the approved look.
Job IDs, reference copies, model preparation and cache hand-offs are automatic.
Existing saved projects and media remain readable on the same computer. Legacy
storage paths and node IDs remain compatible; public names use Zura branding.

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

Wan's exported animation graph contains native pose detection, SAM character
segmentation, reference cropping and the selected sampler together. H3 and LTX
exports contain editable prompts and conditioning rather than frozen Studio
conditioning caches. Native subgraphs form a single left-to-right chain with
labelled stage hand-offs. These small Zura data adapters carry existing model,
image and audio objects without changing or copying them. Open a stage to see
the native inference nodes and their routed connections. Common source, prompt,
seed and sampling controls are exposed on the graph. Technical settings remain
editable inside each stage. Graph conversion checks the compiled render inputs
and restores the original editable graph if conversion changes them.

## Optional reference audio

**Reference audio** accepts WAV, MP3, M4A, FLAC, OGG, AAC and AIFF, or audio from
an MP4, MOV, MKV or WebM. Video uploads in this field use only their audio. It replaces
the source soundtrack for both guidance and the finished video. By default it
starts at zero at the beginning of your selected video interval. Adjust its
own **Reference audio start** in More controls if needed. It is trimmed to the
selected clip length; shorter tracks are padded with silence. Remove it with
**Use video's audio instead**. Changing audio requires a fresh guidance review.

Silent source videos receive valid silence for audio encoders, including the
full-resolution reread and LTX temporal padding. The final video stays quiet
when there is no source audio and no reference track.

With an uploaded track, **Lip sync to this audio** adds optional local MuseTalk
1.5 mouth animation. Wan receives a speech-driven face guide before its existing
Animate sampler, then a local mouth refinement on the generated character.
LTX, H3 and the accepted Seedance final use the same local mouth refinement.
It changes the generated lower face, preserving the rest of the generated scene.
Untick it for music or sound design; the audio is then only a soundtrack.
Native LTX/H3 speech conditioning remains experimental, so this separate local
finish provides the new articulation rather than relying on those models alone.

Run **Setup_Speech_Windows.cmd** once for the optional local models and Python
dependencies. There is no paid speech call or automatic download during renders.
Lip sync needs one visible human face. Profiles, occlusion, stylised characters
and multi-person shots may fail or lose detail. MuseTalk works at a 256 px face
crop internally, even when the finished video is HD. Review every talking take.

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

## One project, several models

| Model | Current behaviour |
| --- | --- |
| LTX 2.5 | Local masked replacement; original background or depth-guided scene restyling. Uses the approved opening scene. Speech timing remains experimental after failed talking tests. |
| MiniMax H3 | Experimental local replacement with separate opening and character references, depth control and source audio. The earlier 512 px test failed user quality review: motion transfer remains weak. |
| Wan 2.2 Animate | Local pose and face-driven replacement with the approved background mask. Uses the approved opening scene for the latent reference and an isolated character view for CLIP Vision. |
| Seedance | Paid draft and accepted-final route through Comfy. Requires explicit paid action and Comfy sign-in. No paid calls were used during this update. |

Switching model, output resolution, sampling effort or seed retains the approved
mask and look. Changing the source interval, performer, replacement scope, mask
margin, text removal or guidance audio requires a fresh mask review. Changing
appearance direction requires a fresh look preview. Jobs are never duplicated
by repeated clicks or automatically retried after an ambiguous paid submission.

## Size and timing

There is one output resolution selector: small 512 px tests, 768 px, 720p HD
(1280 px long edge) and 1080p Full HD (1920 px long edge). Landscape and portrait
source proportions are preserved. Native models require dimensions in multiples
of 16/32/64; the final export restores the source aspect ratio at the chosen size.
Generation and mask review have separate internal sizes: the 512 px review stays
light, while rendering rereads the original footage at the selected resolution.

**Clip length** governs the selected source interval and delivered audio/video.
There is no hidden two-second preview limit. Native temporal padding is trimmed.
H3 currently supports 0.21–5 seconds; use one continuous shot with H3 or LTX.
Wan uses bounded 81-frame windows, real-frame continuation and automatic cut
detection. Two-second previews render in one pass. Native joins retain the
previous frames and discard repeated context instead of cross-fading faces.
Each chunk decodes in one temporal tile, retaining spatial tiles for memory.
Continuation resets at cuts. Review joins and facial motion visually.
The tested Wan source contains one central performer. Explicit pose targeting
in multi-person shots has not been validated.
Seedance supports model-specific output sizes; its final paid step is 1080p.
Unsupported choices fail before submission rather than silently changing size.

**Fast/Detailed** changes denoising effort, not resolution or clip length. Wan
uses the supplied workflow's shift 8, Euler/simple, relight and realism LoRAs.
Fast adds the two supplied LightX2V LoRAs at 0.7/0.6 with 6 steps and CFG 1;
Detailed removes those two acceleration LoRAs and uses 40 steps with CFG 5.
The native loader explicitly uses `fp8_e4m3fn_fast` for the supplied KJ-scaled
Wan checkpoint; current core otherwise expands it to FP16 and renders much slower.
H3 has its own compatible 8-step acceleration / 40-step route. LTX keeps its
existing distilled schedule and adds native audio/video modality guidance.
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
original RGB background and combined mask condition each supported local model
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
ComfyUI-KJNodes, ComfyUI-WanAnimatePreprocess, comfyui_controlnet_aux,
ComfyUI-MelBandRoFormer, ComfyUI-essentials (Mask Fix) and the LTX native nodes
used by the bundled graphs.
FFmpeg must be available on PATH. The interface doesn't download weights silently.

Model filenames are defined in `artist_studio/wan.py`, `artist_studio/h3.py` and
the model-status section of `artist_studio/studio.py`. No models, uploaded
references, project records or credentials are included in the release.

## Verification

Shared-engine tests check approval retention, legacy resolution migration,
native preparation, family-specific model stacks, exact mask/frame alignment,
safe cache roundtrip and the single resolution/length interface. Existing Wan,
multicam, camera, audio and voice regression suites were rerun. Live render
results and limitations are recorded separately in `ARTIST_STUDIO_VALIDATION.md`.
DOM interaction checks are separate from browser visual checks, which remain
unavailable because of the saved local-origin browser permission.
