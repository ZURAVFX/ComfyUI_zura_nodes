# Local development checks, 24 October 2026

These are execution and preview checks, not new artist quality approvals.
Tests used the local RTX 4080, 512 x 288 output, seed 42 and short native
frame counts. Timings include loading/offloading for that run. They are not
720p/1080p speed estimates or a measured speedup over another configuration.

| Recipe | Frames / steps | Result | Stream updates | Elapsed |
| --- | --- | --- | --- | --- |
| H3 first frame | 39 / 8 | MP4 saved | 8 TAE | 35.81 s |
| Wan first frame | 49 / 4 | MP4 saved | 4 TAE | 24.22 s |
| LTX 2.5 first frame | 49 / 8 | MP4 saved | 8 latent RGB | 46.53 s |
| H3 image reference | 56 / 8 | MP4 saved | 8 TAE | 32.12 s |
| H3 image, trimmed video, paired and standalone audio | 56 / 8 | MP4 saved | 8 TAE | 33.36 s |
| Wan first and last frames | 49 / 4 | MP4 saved | 4 latent RGB | 23.02 s |
| LTX 2.5 first and last frames | 49 / 8 | MP4 saved | 8 latent RGB | 44.75 s |

The last-frame branch checks reused the same still at both endpoints. They
verify guide encoding and execution, not interpolation quality between
different images. The reference-video check decoded only the chosen two-second
window before H3 conditioning.

The FLUX Klein non-human replacement check used the actual failed source and
character reference. The corrected short replacement instruction produced one
complete replacement character, rather than retaining the source object or
copying the character sheet. This qualifies the starting-image correction;
non-human video replacement still needs a separate artist check.

DOM and recipe checks cover model switching, optional last-frame removal,
proportional cover/crop, model grids, media limits, job cancellation and recovery,
popup dismissal, prompt ownership and preview URL cleanup. Close/reopen checks
restore popup listeners, endpoint/reference sampling and owned-job polling.
Python checks cover subject selection, missing-mask protection, image direction,
preview selection and existing mask, camera, head and memory behaviour.

CLI schema checks matched the new video/audio trim inputs. Its file-enum check
does not list these test files in input subfolders; the actual local server
accepted those files and completed the mixed-reference run.

The local browser permission block prevented visual browser qualification.
Python changes require a ComfyUI restart; frontend changes require a refresh.
Longer continuation for the new workspaces remains pending, as recorded in
`VIDEO_CONTINUATION_STATUS.md`. No public release is implied by these checks.

## Fifteen-second endpoint limit

The first/last-frame controls now allow H3 through 362 frames (15.08 seconds)
and Wan/LTX through 361 frames (15.04 seconds), preserving each native temporal
grid at 24 fps. Short defaults remain unchanged; the last image is still
optional. Longer selections show a memory hint rather than blocking Generate.

All three maximum-length recipes completed real GPU checks at 256 x 256 with
both endpoints connected. Saved MP4 metadata confirms 362/361/361 frames at
24 fps. H3 took 38.61 seconds, Wan 44.62 seconds and LTX 49.71 seconds in these
particular low-resolution runs. These are execution checks using the same still
at both ends, not quality approvals, high-resolution speed estimates or proof
that 15 seconds at the maximum megapixel setting fits 16 GB.

Boundary/DOM tests cover selecting and building the maximum for all engines,
rejecting lengths above the limit, optional last frames, final LTX guide
indexing and reference-audio duration. This increases a single native window;
it does not implement constant-memory continuation.

## Reference-video vocal direction

The explicit Follow Audio option completed a real Ref2VA Turbo GPU check with
one appearance image and a speech recording: 124 frames at 512 x 288, eight
steps, 33.48 seconds, with eight TAE preview updates. Native audio keyframes
and unanchored references ran together successfully. The output contains the
uploaded vocal, not a decoded generated replacement. Comparing decoded mono
32 kHz waveforms gave correlation 0.9984 and zero sample lag; the 2.28-second
source was followed by silence in the 5.17-second video.

These checks establish execution, soundtrack routing and timing. Facial
performance is not newly artist-approved. The guide conditions generation but
does not freeze target audio latents. Reference-only remains the default.
Recipe and DOM tests cover both routes, native tag canonicalisation, stable
audio selection after removal, saved drafts, job locking, conditional node
availability, padding, and full-length vocal use beyond the ten-second
reference-context limit.
