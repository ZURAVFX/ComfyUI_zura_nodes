# LTX 2.5 outpaint: implementation handoff

Status: canvas and mask adapter tested on synthetic frames. A 25-frame
real-video test of the official two-stage recipe completed in 28.52 seconds
at 768 x 448 on the RTX 4080; the user found that preview poor. A second
1152 x 640 test completed in 34.02 seconds. These are short previews, not a
quality qualification for every shot.

The user preferred the black-video guidance method in the 1152 x 640
comparison. Studio now exposes that LTX 2.5 recipe as **Frame extension ·
preview**, with an explicit warning that it can redraw the original footage.
The preview is capped at five seconds / 24 fps. Canvas placement and black-area
selection require a full-clip preview and explicit approval; changes invalidate
the review. The real Studio upload → review → approve → render path produced
12 frames at 1152 x 640 with audio; internal temporal padding was trimmed back.
The black-padded, non-64-pixel path has synthetic and graph tests but still
requires a real GPU render, and desktop UI appearance still needs visual review.

The official Lightricks workflow is
`example_workflows/2.5/LTX-2.5_ICLoRA_Outpaint_Two_Stage_Distilled.json`,
revision `db476dacc1469b2f17ccc5735693916afcb6fac1`:
https://github.com/Lightricks/ComfyUI-LTXVideo/blob/db476dacc1469b2f17ccc5735693916afcb6fac1/example_workflows/2.5/LTX-2.5_ICLoRA_Outpaint_Two_Stage_Distilled.json

Unlike the older personal LTX 2.3 black-video guide workflow, the 2.5 recipe
uses the official 2.3 `ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors`
at strength 1, and a white-to-generate mask. It applies
`LTXVInpaintPreprocess` to provide the green masked cue before the
`LTXAddVideoICLoRAGuideAdvanced` guide, encodes and freezes source audio,
samples eight steps at half resolution and two refinement steps after resizing
and VAE encoding, and uses `LTXVLaplacianPyramidBlend` at both stages. It uses
Euler ancestral then Euler, CFG 1 and the sigma lists shown in the official
workflow. The source frame and mask must remain aligned throughout both stages.
The original official full-resolution decoder can be replaced by the official
convolutional VAE for less memory, but the result needs its own quality check.

`ZuraLTXOutpaintCanvas` in `artist_studio/ltx_outpaint.py` provides a black
canvas and matching per-frame mask using one of two explicit choices:

* **Expand canvas:** fit the entire video into a user-specified rectangle while
  retaining its aspect ratio; all outside pixels become white in the mask.
* **Use black areas:** retain an already padded video and select every pixel at
  or below an explicit threshold. Black clothing, shadows and text can be
  selected too. Preview the mask and allow correction before generation; do
  not silently infer that black means missing footage.

For the UI, show a draggable video rectangle against the target canvas, a
compact aspect/width/height control, and an alternate black-areas switch.
Make selection review compulsory in the black-areas route. Keep time, fps and
source audio unchanged. Padding to the model's 8n+1 temporal length must hold
the final frame internally, then trim the rendered output to the selected
duration. Use the user's existing source rather than a generated starting
frame. Avoid image resampling or stretching during geometry selection.

The canvas node is registered in the main node mappings. The accompanying
`build_test_graph` generates the same native two-stage graph used for the
short render, but it requires an already-trimmed input video containing an
audio stream and exactly 8n+1 frames. The separate Studio preview route uses
the user's preferred black-guide recipe with bounded range selection, audio,
temporal padding and a reviewed canvas. Model availability is checked when
Comfy validates the graph, and broader model/runtime and quality qualification
remains outstanding.
Do not substitute the old mask-free 2.3 recipe and claim it is the same
workflow. The required LoRA is installed on the test workstation.

The private comparison `work/openjutsu-benchmark/ltx25-outpaint-comparison.mp4`
shows the source on the left and generated expanded scene on the right. The
underlying output is `genj`-independent in ComfyUI's output folder at
`zura/outpaint_test/ltx25_street_00001_.mp4`. It needs user assessment and
tests on longer and more varied shots.

A second comparison tests both methods on the same LTX 2.5 INT8 base, source,
prompt, seed, 25 frames and 1152 x 640 output:
`work/openjutsu-benchmark/ltx25-black-guide-vs-mask-1152.mp4`. Left is the
user workflow's black-video guide, original outpaint LoRA, single-stage
8 steps (38.31 seconds). Right is the official masked 2.5 workflow with the
0.9 in/outpainting LoRA, low-resolution 8 steps plus 2-step refinement and
two blends (34.02 seconds). The single runs have different sampling paths;
the timings do not establish a general speed ranking. The black-guide route
can alter the source pixels, while the masked route blends source content back.
The user requested a 2.5-only test. An earlier 2.3 model download had already
completed before that request arrived; it was not used and was subsequently
deleted at the user's request. The user chose the black-guide result as the
basis for the Studio preview.
