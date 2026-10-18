# Approved Studio workflows

Updated 18 October 2026 for Zura Nodes 1.3.24.

Approvals belong to a particular workflow and example. Rejecting one model's
viewport result does not revoke its separately approved character or audio work.
Keep this ledger when changing Studio availability.

## Character performance

The approved character routes below keep their own tested generation paths. Wan Animate 2 is a separate full-frame option whose local quality and speed are not yet qualified.

| Model | Original audio and acting | New dialogue drives facial performance | Silent footage | Preservation |
| --- | --- | --- | --- | --- |
| Wan 2.2 Animate | Approved | Approved | Approved | Precise masked replacement; best choice when surroundings must stay. |
| MiniMax H3 | Approved | Approved | Approved | Reviewed selection and depth guide replacement; surroundings may change. |
| LTX 2.5 | Approved | Approved | Approved | Body-guided whole-frame recreation; no precise edit mask. |

These nine approvals cover the exact five-second examples accepted on 11 October.
H3's approved 1080p delivery samples at 720p and then enhances. The LTX approvals
include source-motion guidance; the earlier first-frame-only speech test is not
the basis for enabling this route. Longer H3 speech and continuation remain
unqualified. LTX's bounded character pipeline supports up to five seconds.

Choose **Original audio + performance** to follow the source, including footage
without an audio track. Choose **Reference audio + new performance**, upload an
audio file or video, and enable **Create a new facial performance** for dubbing.
This guides generation with the selected dialogue, rather than only replacing
the exported soundtrack. The optional separate lip-refinement/compositing pass
remains unavailable.

The existing H3 route uses Ref2VA, the matching Turbo adapter, Union control,
depth and native audio guidance. It is not the newer maskless Character-Swap
LoRA experiment. The existing LTX route uses its qualified pose/Union guidance,
frozen audio and refinement pipeline. Do not replace either recipe because an
unrelated LoRA or viewport test failed.

## Wan recipe parity

Rechecked against the artist's Trend Studio Wan22 workflow on 18 October.
Both Fast and Detailed retain `Wan14B_RealismBoost.safetensors` at **1.0**
and `WanAnimate_relight_lora_fp16_resized_from_128_to_dynamic_22.safetensors`
at **1.0**. Fast additionally uses
`lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` at **0.6**.
The installed Studio reports all three files present, and its Wan builder and
chunk sampler match the development source.

The model, VAE, vision encoder, shift 8, Euler/simple sampling, Sage attention
and FP16 accumulation follow the reference path. Studio retains its qualified
6-step/CFG 1 Fast and 40-step/CFG 5 Detailed settings, motion guidance and native
replacement masks. The four existing Wan recipe regression checks pass.

Do not copy the reference's additional high-noise Wan2.2 I2V LoRA into this
Animate stack: the [official Wan guidance](https://github.com/Wan-Video/Wan2.2#3-run-in-replacement-mode)
warns that Wan2.2-trained LoRAs can cause unexpected behaviour with Animate.
Its removal was already reviewed in the compatible-fast tests. This parity
check required no generation changes or new GPU render.

## Other accepted work retained

- H3 viewport-to-final: the train example was approved on 13 October.
- Wan full-length original performance: the 23.75-second example was accepted
  with detail degradation between chunks recorded as a limitation.
- H3 on-screen text repair: the artist confirmed the repaired region was steady.
- Full-clip performer/text selection and the Wan starting appearance were
  approved for their respective examples. Keep per-shot review for new inputs.
- Finished starting-frame upload, generated-look review, prompts, original clip
  length, cancellation and editable Graph access remain part of the interface.

## Excluded development work

LTX viewport-to-final remains excluded: the latest train test was rejected for
distortion and weaker results than H3. Masked LTX editing, arbitrary object
replacement, H3 maskless Character-Swap LoRA, relighting and protected-person
background editing remain separate, unqualified work. The India environment
example did not pass camera-motion retention. Do not enable these from a partial
approval or from successful execution alone.

Private sign-off records, hashes and test media stay outside the distributed
package. New results still need their own review; historical approval is not a
promise that every input, length or setting will produce the same quality.

## Latest feedback and upload repair

The artist reconfirmed the nine examples on 18 October. Visible blending near Wan chunk joins remains accepted for now; its cause has not been established as VAE tiling. Investigate continuation, overlap/blending and decoding separately before changing the approved recipe.

Studio media drops now stop propagation to the Comfy graph importer and support file-item fallback. Empty or busy uploads report a visible message. The real MP4 upload endpoint and thumbnail response were checked; file-picker/drop handoff regressions pass. Actual Desktop drag/drop confirmation remains the artist-facing final check.

The upload path also bypasses Comfy frontend's default 60-second JSON-request
timeout, with its own five-minute abort and visible file size/elapsed feedback.
Files over the existing 2 GB backend limit are rejected before transfer.
Hashing happens during the upload copy, avoiding a second full-file read;
disk writes and thumbnail/media inspection run outside the server event loop.
Real multipart MP4, thumbnail/hash and server-responsiveness regressions cover
this path. Generation settings are unchanged.

## H3 Head & face, 18 October

The artist approved a two-second original-audio head replacement and requested Studio integration. This separate choice tracks a face crop, uses DW facial performance guidance and a portrait, samples a masked source latent, then composites the generated crop into the source. It uses the supplied eight-step adapter stack and Kitchen attention. Studio limits it to one portrait or character sheet, one performer, up to two seconds and original audio. It does not inherit replacement-speech, text-removal or enhancement approval from Full character. Temporal padding preserves the complete selected duration. Private test media and receipts remain local.
