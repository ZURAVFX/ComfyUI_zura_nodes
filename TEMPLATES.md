# Zura Nodes templates

Open **Browse Templates > Zura Nodes**. These are the public examples included with the pack. Each model workflow needs its own installed weights and the custom-node dependencies visible inside its graph.

## Speech replacement

- [Audio - Replace Speech (LongCat)](<workflows/Audio - Replace Speech (LongCat).json>): four stages, two waveform selections, optional speaker reference, and a downloadable final WAV.
- [Video - Replace Speech (LTX INT8)](<workflows/Video - Replace Speech (LTX INT8).json>): tracked face selection, full replacement phrase, 512 to 1024 quality crop, and a blended final clip. The approved local Dub-It 2.3 / LTX 2.5 combination remains experimental.

See [Dialogue editing](DIALOGUE_EDITING.md) for the complete steps, setup and supported limits.

## Audio

| Template | Purpose |
| --- | --- |
| [Audio - Replace Speech (LongCat)](<workflows/Audio - Replace Speech (LongCat).json>) | Select original and replacement waveform sections, then blend the new words into the source. |
| [Audio - Clone a Voice (LongCat)](<workflows/Audio - Clone a Voice (LongCat).json>) | Generate speech from an existing voice reference and its exact transcript. |
| [Audio - Text to Speech (LongCat)](<workflows/Audio - Text to Speech (LongCat).json>) | Generate speech without a voice reference. |
| [Audio - Design a Voice (Qwen)](<workflows/Audio - Design a Voice (Qwen).json>) | Describe a voice and generate speech directly with Qwen. |
| [Audio - Design a Voice (Qwen to LongCat)](<workflows/Audio - Design a Voice (Qwen to LongCat).json>) | Design a Qwen voice reference, then speak the final script with LongCat. |

## Video

| Template | Purpose |
| --- | --- |
| [Video - Replace Speech (LTX INT8)](<workflows/Video - Replace Speech (LTX INT8).json>) | Replace selected speech and mouth movement with the tracked 512 to 1024 face crop. |
| [Video - Change Camera (H3)](<workflows/Video - Change Camera (H3).json>) | Plan one camera angle for a short performance, then render with the original audio. |
| [Video - Multicam (H3 Advanced)](<workflows/Video - Multicam (H3 Advanced).json>) | Plan several camera intervals and render the selected cuts. |
| [Video - Replace a Character (Wan 2.2)](<workflows/Video - Replace a Character (Wan 2.2).json>) | Select the performer and replacement scope, then render in bounded chunks. |

## Image

| Template | Purpose |
| --- | --- |
| [Image - Build a Starting Frame](<workflows/Image - Build a Starting Frame.json>) | Build an opening image with one appearance reference. |
| [Image - Build a Starting Frame (3 References)](<workflows/Image - Build a Starting Frame (3 References).json>) | Build an opening image with three appearance references. |
| [Image - Use a Finished Starting Frame](<workflows/Image - Use a Finished Starting Frame.json>) | Load a finished opening image without generating a new one. |

## Utility

| Template | Purpose |
| --- | --- |
| [Utility - Improve a Prompt (Gemma 4)](<workflows/Utility - Improve a Prompt (Gemma 4).json>) | Expand a prompt, optionally guided by an image. |

## Reference

| Template | Purpose |
| --- | --- |
| [Reference - Mask and Roto (SAM3)](<workflows/Reference - Mask and Roto (SAM3).json>) | Imported reference graph for text-prompt masking and roto. |
| [Reference - Head and Face Swap (H3)](<workflows/Reference - Head and Face Swap (H3).json>) | Imported reference graph for H3 replacement with SAM3 masking. |
| [Reference - Speedboost Comparison (H3)](<workflows/Reference - Speedboost Comparison (H3).json>) | Imported reference graph comparing H3 acceleration and LoRA branches. |

Reference graphs preserve their imported layouts and may require several additional node packs. They are examples to inspect and adapt, rather than the simplified speech editors.

## Release policy

`template_catalogue.json` is the reviewed public allowlist. Release checks reject extra JSON templates, missing catalogue entries, local media paths, embedded media and audition/test names. `.comfyignore` also only includes the listed workflow files.

Local audition copies and the experimental AnyAngle template are archived privately outside this package. Renaming templates does not remove any node classes or change existing user-saved workflows. Previous website download URLs remain available.
