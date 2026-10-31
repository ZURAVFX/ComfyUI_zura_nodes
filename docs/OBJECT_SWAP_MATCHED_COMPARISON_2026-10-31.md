# Local object replacement comparison

All three actual graphs completed on the same microphone source and historical
edited first-frame anchor, first 17 frames at 24 fps, 512 x 896, seed 42. The
manual mask was identical for the two masked methods. H3's 32-pixel native mask
pooling expands it to x160..352, y256..448. This is a local prompt/reference
approximation of Kagami-style editing, not the hosted Kagami service.

| Actual result | H3 no mask | H3 native mask | LTX inpaint |
| --- | ---: | ---: | ---: |
| Execution including loads/saves | 54.613 s | 39.248 s | 94.697 s |
| Delivered frames | 22 | 22 | 17 |
| Compared source frames | 17 | 17 | 17 |
| Output raster | 512 x 896 | 512 x 896 | 512 x 896 |
| Encoded outside-envelope MAE, 8-bit | 9.568 | 7.173 | 2.374 |

H3 selected 17 frames, generated at its 22-frame native grid, trimmed back to
17 and held five final frames for delivery. LTX uses its native 17-frame grid.
All retain one audio track; same-time source correlations are 0.9970 for both
H3 outputs and 0.9988 for LTX. This is not a lip-sync qualification.

The H3 masked arm inserts OpenJutsu's native masked-regeneration core before
sampling. It does not use a character-specific adapter or RGB composite and
is not the full character Relay preset. It preserves source VAE latent outside
the editable cells; VAE/codec changes prevent a bit-exact RGB claim. LTX uses
its masked two-stage conditioning and final Laplacian blend. These architectural
differences and warm-loader caches make one-order timings incomparable as
general model-speed claims. Neither H3 sampler result was cached.

In first/middle/last images, both H3 arms replace the microphone with the gold
design, but its material/shape changes from the initial anchor towards the
middle. LTX follows the anchor's less saturated finish more closely in this
short interval, with some collar/edge deformation. All retain a single central
microphone. No route is promoted on the basis of a 0.708-second test. Outside
MAE measures encoded source changes, not object quality or tracking accuracy.

The historical anchor itself changes surrounding pixels. The fixed mask also
covers part of the collar and background. Longer moving-object/occlusion checks
and artist approval remain necessary; object swap stays hidden in Studio.
This completes the bounded three-way diagnostic, not object-swap qualification.

An initial submission was rejected before rendering because standard LoadVideo
and LoadImage inputs cannot use these external absolute paths. Fixtures were
staged into Comfy's input folder, and served bytes were SHA-256 checked. The
builder now rejects this path mistake before queueing.

Private evidence: `release-check-1.3.38/object-comparison-preflight/` contains
all three prompt histories, actual-results.json, contact sheets, native mask
audit, staged-input hashes and a CPU-only reproducer. No hosted provider calls,
model downloads, server restarts or product-route changes were made.
