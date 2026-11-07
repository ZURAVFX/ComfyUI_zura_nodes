# Inference backends

Studio retains the acceleration settings in its approved model recipes. ComfyUI also dispatches supported quantised operations through Comfy Kitchen automatically; a graph attention patch is separate from those kernels.

Routes that already use Kitchen attention check the running ComfyUI's advertised choices. Kitchen is retained when available; PyTorch attention is selected otherwise. If the optional patch node is absent, the model keeps ComfyUI's native attention backend. This applies to H3/LTX first and last frames, H3 reference video, Wan first and last frames, Ripple and the matching Python camera/HDR graph builders.

Kitchen attention uses INT8 arithmetic and can affect results. It is not forced into other approved quality recipes. Two-stage generation, fast adapters, lower-precision weights and sparse attention remain specific to compatible model paths. They are quality choices, not interchangeable global switches.

VAE tiles and temporal windows bound memory. Smaller tiles can add work; broader model caching can increase memory pressure. Studio keeps its existing tested tile, cache and chunk policies instead of changing launcher settings or installing a new attention package automatically.

Backend compatibility tests do not establish a speed improvement. Compare cold and warm runs with the same model, source, seed, LoRAs, dimensions and sampling settings before drawing timing or quality conclusions.

Primary references: [Comfy Kitchen](https://github.com/Comfy-Org/comfy-kitchen), [ComfyUI attention](https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/ldm/modules/attention.py), [LTX 2.5 workflows](https://github.com/Lightricks/ComfyUI-LTXVideo/tree/master/example_workflows/2.5).
