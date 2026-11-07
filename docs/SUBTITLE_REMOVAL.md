# Subtitle removal

Open **Video → Watermark removal**, then choose **LTX 2.5 · Subtitles** in the method selector. **Zarxrax** is the default adapter; **JoyFox** remains available beside it. Switching adapters keeps the source, painted selection and prompt.

Paint around the subtitles. The selection defines a stable rectangular crop, with surrounding scene context. The workflow repairs the **whole crop**, not the painted contour, and blends that rectangle back into the original footage. Pixels outside the crop are retained before output encoding. A clean first-frame guide and object tracking are not required.

Choose 100%, 75%, 50% or 25% crop processing scale. Processing dimensions pad to the native two-stage grid; output returns to the source dimensions and frame rate. Any held tail frames used internally are removed, and delivery keeps the matching source audio. Results save under **ZURA STUDIO/subtitle removal** in the configured output folder.

Models setup offers the selected adapter and missing LTX 2.5 components through the shared installer. Both subtitle adapters retain “2.3” in their filenames because of their training base; this workflow uses LTX 2.5 and does not require a 2.3 base checkpoint.

The native recipe follows the supplied video IC-LoRA workflow: source-crop guides in both passes, Euler/CFG 1, an eight-step first pass, LTX 2.5 2× latent upscaling and three-step refinement. Zarxrax uses strength 1.5 and its `removetext` trigger; JoyFox uses strength 1.2. No masked-inpaint conditioning is substituted for that recipe. Graph view opens this same subtitle workflow.

Current delivery supports SDR. Large crops are checked against available system memory before frame batches are allocated; reduce the crop, scale or clip length when needed.

Both adapters completed LTX 2.5 GPU tests on a matched 25-frame, 512 × 384 captioned copy of a clean source clip. The clean original allowed comparison of changes beyond the added caption. Zarxrax was selected as the default after visual review. A further painted-crop test completed the full Studio delivery path: 23 selected frames, 512 × 384, 25 fps and matching 0.92-second audio. These short tests do not establish quality on every shot.

Sources: [Zarxrax RemoveText](https://huggingface.co/Zarxrax/removetext), [JoyFox ICEdit Insight](https://huggingface.co/joyfox/LTX2.3-ICEdit-Insight), [creator's workflow repository](https://github.com/Valiant-Cat/LTX2-ICEdit-Insight).
