# Zura Studio: implementation checklist

Goal: preserve the approved character workflows while making the requested media,
generation and viewing controls dependable and easy to discover. Changes are local
until a release is explicitly requested and the relevant flows are verified.

- [x] Keep H3 OpenJutsu and Wan Animate 2 available for character plus background replacement; retain OpenJutsu's background-preserving route and existing approved workflows.
- [ ] Add LTX-only HDR and SDR processing and delivery following official 2.5 examples. Bounded SDR-to-HDR and HLG-to-HDR previews passed short engineering tests with HLG, EXR and audio. PQ/EXR input, longer clips and full-size visual review remain.
- [ ] Provide an in-app model setup flow showing missing files, dependencies, sizes and download progress, with explicit user initiation. The FLUX.2/3, OpenJutsu, Wan Animate 2 and partial LTX 2.5 packages are implemented; remaining routes still need catalogue coverage and bundled node setup.
- [x] Make ProRes MOV previews playable while retaining the original media for processing; synthetic ProRes/PCM playback-proxy and UI transition tests pass. Desktop visual confirmation is still useful.
- [ ] Find and fix opening-frame aspect changes and duration mismatches. The relight crop paths now match and the UI displays frame-aligned lengths. An exact one-frame shortfall at final mux is held to match the selected duration, with a real FFmpeg 23-to-24-frame test; larger shortfalls still fail visibly. LTX first/last audio now pads short references with silence to the selected video length. The real relight test was interrupted by another GPU job; other routes still need end-to-end duration checks.
- [ ] Implement LTX video outpainting with a simple extension/crop control or existing black-area input, and verify real output with both approaches. The preferred black-guide approach is integrated as a five-second preview and passed a 12-frame real upload-to-render test; black-area input still needs a GPU test and desktop review.
- [ ] Offer optional compatible installed LoRAs in advanced controls, with model-family validation; do not silently apply incompatible weights. Image, H3, Wan and staged LTX routes have graph tests; some special passes and video starting-frame image generation remain unsupported, and GPU quality checks remain.
- [x] Support zoom, pan and reset in the main video, image, first/last-frame and reference-video previews; interaction tests cover playback and seeking. Desktop visual confirmation remains.
- [ ] Confirm FLUX.2 Klein 9B is the image generation default, and investigate face-identity and realistic-skin LoRAs with credible compatibility evidence. The recipe is wired and tested structurally, but a real FLUX.2 render remains. A controlled FLUX.3 Consistency LoRA comparison showed additional skin detail but did not establish better identity; restoration adapter is untested.
- [ ] Run focused automated tests and representative local GPU/UI tests; identify any quality-sensitive feature still requiring artist review and keep unverified modes clearly gated.

Completion means each exposed control changes the actual rendered result, preserves
existing approved paths, and has truthful limits and actionable errors. Maintain
notes on unsupported model capabilities rather than claiming generic HDR, LoRA or
duration support without evidence.
