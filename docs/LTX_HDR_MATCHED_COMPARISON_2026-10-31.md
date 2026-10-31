# Matched LTX HDR outpaint diagnostic

Both local graphs completed on the RTX 4080 using the same real PQ source,
first 17 frames at 24 fps, seed 42, output 1088 x 640, source placement and
64/32/64/32 canvas expansion. The native masked prototype is a composition of
existing native HDR and official masked two-stage techniques, not a verbatim
named official HDR-outpaint workflow. The accepted alternative uses black-video
SDR guidance followed by the existing SDR-to-HDR adapter.

| Actual result | Native HDR prototype | SDR outpaint then HDR |
| --- | ---: | ---: |
| Execution including loads/exports | 147.254 s | 143.052 s |
| Delivered frames, rate, duration | 17, 24 fps, 0.708333 s | 17, 24 fps, 0.708333 s |
| Video | 1088 x 640, 10-bit BT.2020 HLG | 1088 x 640, 10-bit BT.2020 HLG |
| EXR | 17 finite half-float ACEScg/AP1/D60 | 17 finite half-float ACEScg/AP1/D60 |
| Linear source-core relative RGB MAE | 19.535% | 35.668% |
| Border relative frame delta Y | 2.738% | 3.753% |

Both audio packet streams are identical; decoded inter-arm RMSE is zero. No
adjacent EXR frames are exact duplicates. The motion-uncompensated border
measure includes scene movement and is not an objective flicker/quality score.
The source-core measure includes intended SDR tone mapping and reconstruction;
neither route preserves original plate values exactly. Boundary-jump versus
local-gradient ratios were about 0.83 to 0.98 across these four edges, which
does not prove a visually seamless blend on other shots.

Under one common SDR viewing transform the SDR-guided version is brighter in
shadows and green areas. SDR contacts cannot qualify HDR-display appearance.
Models, adapter topology, VAE variants, audio conditioning and cached loaders
differ. One seed, short interval and test order do not establish a general
speed or quality winner. The native route stays experimental; the reviewed
artist layer export remains the fallback for manual level matching.

The SDR graph deliberately uses distinct conv-BF16 outpaint and non-conv
float32 HDR-conversion VAEs. Reusing a deduplicated VAE object would let the
float32 wrapper mutate the outpaint VAE and compromise the comparison.

Private evidence: `release-check-1.3.38/hdr-outpaint-matched-validation/analysis/`
contains source/output probes, decoded EXR analysis, common-transform and
saved-preview contacts, and `comparison.json`. Graphs and prompt histories
are retained beside it. No public model or route was promoted by this test.
