# Zura Studio: implementation checklist

Goal: preserve the approved character workflows while making the requested media,
generation and viewing controls dependable and easy to discover. Changes are local
until a release is explicitly requested and the relevant flows are verified.

- [x] Keep H3 OpenJutsu and Wan Animate 2 available for character plus background replacement; retain OpenJutsu's background-preserving route and existing approved workflows.
- [ ] Add LTX-only HDR and SDR processing and delivery following official 2.5 examples. Bounded SDR-to-HDR and HLG-to-HDR previews passed short engineering tests with HLG, EXR and audio. PQ video and ACEScg EXR input each passed a nine-frame GPU test; longer clips and representative HDR visual review remain. HDR previews currently cap runs at 121 frames.
- [ ] Provide an in-app model setup flow showing missing files, dependencies, sizes and download progress, with explicit user initiation. The FLUX.2/3, OpenJutsu, Wan Animate 2 and partial LTX 2.5 packages are implemented; remaining routes still need catalogue coverage and bundled node setup.
- [x] Make ProRes MOV previews playable while retaining the original media for processing; synthetic ProRes/PCM playback-proxy and UI transition tests pass. Desktop visual confirmation is still useful.
- [ ] Find and fix opening-frame aspect changes and duration mismatches. The relight crop paths now match and the UI displays frame-aligned lengths. An exact one-frame shortfall at final mux is held to match the selected duration, with a real FFmpeg 23-to-24-frame test; larger shortfalls still fail visibly. LTX first/last audio now pads short references with silence to the selected video length. A one-second relight GPU test produced 24 frames at 24 fps with aligned original audio and no obvious framing jump. Longer clips, unusual frame rates and other routes still need end-to-end checks.
- [ ] Implement LTX video outpainting with a simple extension/crop control or existing black-area input, and verify real output with both approaches. The preferred black-guide approach is integrated as a five-second preview and passed a 12-frame real upload-to-render test; Already-black input now uses a reviewed masked fallback: a 12-frame GPU test filled the border and preserved dimensions and audio; longer temporal quality and desktop review remain.
- [ ] Offer optional compatible installed LoRAs in advanced controls, with model-family validation; do not silently apply incompatible weights. Image, H3, Wan and staged LTX routes have graph tests; starting-frame image generation now has separate LoRA controls and graph coverage. Some special passes remain unsupported, and third-party LoRA GPU quality checks remain.
- [x] Support zoom, pan and reset in the main video, image, first/last-frame and reference-video previews; interaction tests cover playback and seeking. Desktop zoom and reset were checked; additional media types still need desktop visual confirmation.
- [ ] Confirm FLUX.2 Klein 9B is the image generation default, and investigate face-identity and realistic-skin LoRAs with credible compatibility evidence. FLUX.2 Klein 9B produced a real 512 × 512 render in 12 seconds including model loading. A controlled FLUX.3 Consistency LoRA comparison showed additional skin detail but did not establish better identity; restoration adapter is untested.
- [ ] Run focused automated tests and representative local GPU/UI tests; identify any quality-sensitive feature still requiring artist review and keep unverified modes clearly gated.

Completion means each exposed control changes the actual rendered result, preserves
existing approved paths, and has truthful limits and actionable errors. Maintain
notes on unsupported model capabilities rather than claiming generic HDR, LoRA or
duration support without evidence.
