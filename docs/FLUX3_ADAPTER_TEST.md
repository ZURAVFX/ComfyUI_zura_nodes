# FLUX.3 Klein adapter investigation

Two publisher-supported FLUX.3 Klein adapters were installed locally after
verifying their SHA-256 checksums and reading their licences:

- [Consistency LoRA](https://huggingface.co/ausboss/FLUX-3-Image-Klein-Consistency-LoRA),
  `flux-3-image-klein-consistency.safetensors`, 160,696,888 bytes,
  SHA-256 `abd03ed85d48f0b6d14c93a1fc150cd4ae1c3d71e06e518194ad873cc8660f14`.
  The author recommends distilled FLUX.3, strength 1, 16 steps, CFG 1,
  Euler/simple and reference-latent conditioning. This is a framing consistency
  adapter, not an identity lock; the author reports mixed results by edit type.
- [Restore LoRA](https://huggingface.co/ausboss/FLUX-3-Image-Klein-Restore-LoRA),
  `flux-3-image-klein-restore.safetensors`, 160,697,064 bytes,
  SHA-256 `7b758f5c1d494da7675dbebd8309f36c3dcaf4aa67a3349f667403c7a681187e`.
  It targets restoration and upscaling; the author reports a small identity and
  colour improvement in their limited face test and warns of overly textured
  skin on clean portraits.

Both are under the FLUX Kommunity License, detailed on their publisher pages.
Neither safetensors header declares a recognised base-family field; Studio's
custom LoRA UI correctly asks the user to confirm FLUX.3 compatibility.

One controlled local editing test compared the consistency adapter against
baseline FLUX.3 Klein: same approved character-and-studio source, 512 × 928,
seed 20261029, 16 steps, CFG 1, Euler/simple and one reference image. The prompt
asked for a brown leather jacket while preserving the face, pose and framing.
The baseline and adapter both kept the scene reasonably close and both changed
the face slightly. The adapter produced stronger skin detail but also changed
facial appearance. This single test does not establish improved identity or
natural skin and is insufficient to recommend enabling it by default.

Private evidence is in `work/openjutsu-benchmark/flux3-test/`: original/baseline/
adapter `source-comparison.jpg`, `face-comparison.jpg`, `comparison-results.json`
and the reproducible API-graph script. Timings (10.06 s baseline, 5.04 s adapter)
include different model warm-up and polling states; they are not a speed test.
No public distribution of model weights or private inputs is included.

## Controlled Restore comparison

The locally installed Restore adapter was subsequently tested on the same
source, prompt, 512 × 928 dimensions, seed, 16-step sampler and strength 1.0
as the original baseline and Consistency comparisons. The native Comfy graph
completed successfully and produced `restore_00001_.png`; private evidence is
in `work/openjutsu-benchmark/flux3-test/restore-four-faces.jpg`,
`restore-comparison.jpg`, `restore-results.json` and `compare_restore.py`.

In this one example Restore adds facial texture, but the face still differs
from the source and there is no clear visual proof that identity is better
preserved than the baseline. It also changes appearance compared with the
Consistency output. One portrait and one edit are insufficient to recommend
either adapter as an identity lock or enable it by default. The result took
10.07 seconds including a cold isolated-server load and polling; this is not
a controlled speed comparison with the earlier runs.
