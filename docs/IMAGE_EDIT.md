# Image editing in Zura Studio

Open **Image > Edit image**. Choose the model from the settings button or the model name below the prompt. Drop or paste the image to change first. Add optional reference images after it, describe the change, choose the output dimensions, then select **Apply edit**.

| Model | Imported workflow settings | Images |
| --- | --- | --- |
| Qwen Image Edit 2511 | Installed INT8 model, Lightning adapter at 1.0, 4 steps, CFG 4, shift 3.1, CFGNorm 1, index-timestep-zero references | 1 source + up to 2 references |
| FLUX Klein 9B | FP8 model, FP4 mixed text encoder, 4-step native Flux 2 schedule, Euler, reference KV cache | 1 source + up to 3 references |

These are full-frame instruction edits. The Klein crop/stitch, outpainting and specialist detailer branches are not exposed by this compact interface. No private prompts or example media from the source workflows are bundled.

Qwen uses the installed INT8 model because the source workflow's Q5 GGUF is not installed in the running ComfyUI. Qwen can offload on a 16 GB card; loading time and system RAM still matter. Both recipes passed validation against the local ComfyUI nodes and installed files. New GPU render quality and speed are not yet verified.

Image 1 is the source. The Qwen source is resized to the selected output dimensions before encoding. Refer to the extra inputs as Image 2 and Image 3 in the prompt. Reorder or remove references before submitting. The interface retains the model's image limit and never silently discards extra images.

The current result fills the canvas. **History** opens earlier images without changing the canvas size. Clearing history hides its entries without deleting output files; **Undo clear** restores the entries in the current session. **Graph view** opens the same recipe with the same references, dimensions and prompt.
