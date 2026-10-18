# H3 head and face swap: development comparison

Adapted from the artist's v3 head/face workflow. The artist approved the final
two-second original-audio comparison on 18 October. Studio offers this as
**Character performance → MiniMax H3 → Head & face**, alongside Full character.
It is not a replacement for the approved H3 full-character/audio pipeline.

## What is different

1. SAM tracks `face, glasses`; tracked crop planning follows the face with
   padding and a stable crop size. It does not generate the whole scene.
2. DW face/body landmarks from that crop supply `<Video 1>`. The replacement
   portrait, with its background replaced by white, supplies `<Picture 1>`.
   Original face pixels are not the video appearance reference.
3. The original crop is VAE-encoded with a model/VAE-aligned latent noise mask.
   NKD AV Latent keeps source audio fixed. This is source-latent masked
   sampling, not a dedicated H3 inpainting ControlNet.
4. The decoded crop is blended back into the source using the tracked boxes
   and a separately softened mask. Preservation outside the face therefore
   depends on explicit compositing. This does not establish H3 as equivalent
   to Wan's native background/mask conditioning.

The active stack contains no dedicated face-swap/identity LoRA:

| Adapter | Strength |
| --- | ---: |
| MiniMax-H3-FL2VA-Acc-8Step | 0.75 |
| minimax_h3_taomate_3step_lora_avg_rank_19_bf16 | 0.5 |
| minimax_h3_fl2v_turbo_4step_v1.0_768p_comfyui_bf16 | 0.5 |
| camera_motion_h3_lora_v1_1000_pruned | 0.5 |

The comparison preserves Ref2VA INT8 ConvRot, Kitchen attention, shifts
12/1.5, BasicGuider, `sa_solver_pece`, and the supplied eight-step NKD curve.
Do not replace the curve with Euler/simple or assume the stacked adapters
are faster than a single Turbo without a matched quality/timing comparison.

## Adaptation and controls

`artist_studio/h3_head_swap.py` builds an API graph without queueing anything.
`HeadSwapRequest` takes a source, portrait, source-audio confirmation, selected
interval, seed, selection text, optional tracked-object indices and prompt.
Reference sizing defaults to the supplied `max`; `match` is an explicit
comparison option, not an automatic quality downgrade.

The selected source is normalised to 24 fps and a 1024-pixel long edge. Actual
crop dimensions and frame count drive conditioning. The source is padded by
repeating its last frame to H3's `17n+5` temporal grid, then trimmed to the real
selection after uncropping. Without this, a 48-frame source encoded to only
39 decoded frames in the first live test. The portrait is reduced by half, matching the supplied
recipe. Crop upscaling targets at least 0.35 megapixels; it is not a 1080p
full-frame generation claim. The supplied graph's body landmarks remain enabled
alongside face landmarks, with hand detection disabled.

The development builder accepts original-audio comparisons up to five seconds;
Studio restricts the approved option to two seconds, one appearance reference,
one visible performer and original source audio. Silent input, replacement
dialogue, text removal and enhancement are not enabled for this option.
Existing approved full-character routes retain their capabilities.
Face selection must be checked, particularly with multiple people, occlusion,
glasses or a head turn. Empty object indices select all SAM tracks, as in the
supplied workflow; specify indices when reviewing a multi-face clip.

Selection, crop and generated-face previews are separate from the final
composite, so a plausible blend cannot hide poor generated identity.

## Qualification

CPU tests check the inference mask, landmark reference, crop-box reassembly,
audio contract, trim timing and all node edges/required inputs against a caller
supplied Comfy schema snapshot. The initial live preflight found all ten model
files and returned no graph errors or warnings. This is not visual approval.

The first live generation exposed visible landmark dots in the generated face
and weak portrait identity. Its export also correctly rejected the shortened
video rather than shortening the soundtrack. Padding repaired export: 48 frames
at 24 fps, exactly two seconds with source audio. A prompt comparison using the
supplied performance-transfer wording, with the inconsistent image label fixed,
removed the visible landmark overlay in inspected frames and improved identity.
Do not describe landmark graphics as part of the requested appearance. This
comparison retains the same seed, model stack and conditioning inputs.

The final short render passes execution and frame/audio timing checks. The
artist accepted identity, facial performance and blending and requested Studio
integration. These results do not qualify longer shots, multiple faces or
replacement speech.

Studio uses the reference directly and queues the native head-swap graph without
a generated opening or the full-character preparation/reference-cache stages.
Kitchen attention and the eight-step stack are fixed to the accepted recipe.
The complete graph remains available for editing. Future comparisons should
check longer shots, occlusion, head turns and the value of the camera LoRA and
combined acceleration stack. Keep the full-body and viewport recipes unchanged.

Source media, the original workflow's private inputs, test prompts and render
receipts remain outside the distributable package. No publication is performed.
