# H3 attention and speed

In Studio, select **MiniMax H3 → More controls → H3 attention**. Native preserves existing projects. Comfy Kitchen changes dense attention; Sage + Sol is an experimental sparse-attention option that can change detail. Optional choices are disabled when their nodes are missing. Restart ComfyUI after installing the backend update, then reload Studio.

## Local measurements, 13 October 2026

RTX 4080 16 GB, Windows, 64 GB system RAM, ComfyUI 0.39.2 and Comfy Kitchen 0.2.37. Same reference, prompt and seed per comparison; reference encoding was cached. Native routes used the int8 ConvRot Ref2VA model with its matched eight-step DMD adapter. Two seconds requested at 1280 × 736, 24 fps; all engines sampled 56 internally padded frames. Native outputs were trimmed to 48; the installed FreeVideo exporter retained 56.

| Method | Measured job time | Notes |
| --- | ---: | --- |
| Native, warm repeat | 76.7 s | Baseline |
| Comfy Kitchen, warm repeat | 50.4 s | About 34% less elapsed time; two successful runs |
| Sage + Sol, warm repeat | 54.7 s | First run including kernel setup: 66.0 s; warm sampling about 38.5 s |
| Installed FreeVideo, single pass | 283.2 s | Worker restarted; successful sampling alone 84.3 s |
| Installed FreeVideo, two pass | 176.4 s | Eight smaller-canvas steps plus two full-size refinement steps; sampling 69.0 s |

FreeVideo also decoded generated audio, whereas these native benchmark graphs saved video only. Compare sampling costs as well as job times: Kitchen sampling was about 40 s. FreeVideo uses a different VDN model and its two-pass route changes generation geometry, so this is a practical engine comparison, not a numerical-equivalence test. No speech, face fidelity, source-motion retention or multi-reference quality qualification is implied by this one-reference speed test.

The installed FreeVideo FP8 runtime was pinned to 2026.9.16.41444. Current upstream offers newer hardware-specific int8 paths; these measurements do not establish their speed. FreeVideo is not exposed as a faster Studio backend because this tested installation was slower and does not carry all native motion/audio guidance paths. See [FreeVideo](https://github.com/FlashML-org/FreeVideo).

## Existing acceleration

- H3 already uses quantised weights, cached reference encoding and a matched eight-step adapter in Fast mode. Detailed mode uses more sampling steps. More reference images increase encoding and attention costs.
- Wan uses its accelerated six-step mode and Sage attention. Detailed sampling uses 40 steps.
- LTX 2.5 uses its distilled int8 model, an eight-interval base schedule and three-interval refinement. Its motion/layout adapters remain model-specific.

The supplied Spectrum settings use five warm-up steps and RES multistep protects at least the final three. At eight total steps, no forecast steps remain: the extra history/archive work cannot reduce denoiser calls. This conclusion comes from the installed implementation, not a Spectrum GPU benchmark. Stacking adapters trained for three, four and eight steps is not a lossless attention optimisation; the benchmark kept the matched Ref2VA adapter instead.

These are measured candidates, not an exhaustive claim that every possible optimisation is enabled. Check representative faces, motion and speech before making an approximate backend your production default.
