# Image Studio

Open Zura Studio and choose **Image** or **Video**. Switching workspaces keeps
the current video shot and image prompt. Home returns to the two choices.

For images, choose a model and shape, write a prompt, then select **Generate
image**. Results save in `ComfyUI/output/zura_images`. Download opens the saved
PNG; Reuse prompt restores its model, shape, prompt and seed. New prompt clears
only the image prompt. The last 30 result links and an active run are remembered
in this browser. The PNG files remain on disk even if browser storage is cleared.

Generation uses native ComfyUI nodes and its existing queue, model cache and
memory offloading. No extra inference service, repeated VRAM purge, paid API or
background model download is involved. Cancel targets the image job, leaving
other ComfyUI jobs alone. Requires current ComfyUI with Flux 3 and targeted
interruption support (qualified against 0.41.3).

## Qualified recipes

All three completed and were visually checked at 1024 × 1024 on an RTX 4080
16 GB, with 64 GB system RAM, on 19 October 2026. These are single-run smoke
tests, not universal timing or VRAM guarantees. Loading/offloading, other apps,
prompt length and image shape affect speed. Other shapes use approximately
the same pixel budget; larger and batch outputs are deliberately not exposed.

| Model | Installed recipe | Steps | Observed execution time |
| --- | --- | --- | --- |
| Flux 3 Klein | INT8 convrot; Qwen3-VL 4B INT8; Flux 2 VAE | 16 | 7.3 s |
| Flux 2 Klein 4B | FP8; Qwen3 4B; Flux 2 VAE | 4 | 5.1 s |
| Z-Image Turbo | BF16; Qwen3 4B; AE VAE; AuraFlow shift 3 | 9 | 40.0 s |

All use Euler/simple, CFG 1, one image. This initial image workspace is
text-to-image. Reference editing remains in Video's starting-frame workflow;
the image workspace does not imply support for masks or reference uploads.

Model readiness is checked against ComfyUI's actual node and filename catalogue.
Missing models stay disabled with the missing files and official setup link
under **Models & setup**. No account or licence is accepted automatically.

Sources:
- [Flux 3 Klein Comfy weights](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy)
- [Flux 2 Klein 4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)
- [Z-Image Turbo Comfy weights](https://huggingface.co/Comfy-Org/z_image_turbo)

## Video workspace

Approved video recipes are unchanged. The existing primary stage action now
sits beside the persistent prompt. Frame prompt and Motion prompt remain
separate. Model, quality and audio controls live under **Generation settings**.
Open **Trim footage** for the existing draggable timeline and precision fields.
The composer remains below the preview instead of scrolling with the gallery.

Native Graph view remains available for both images and videos.

## Validation limits

Native generation and DOM interaction tests pass. Live local browser visual
verification was unavailable due to the browser tool's existing access block.
The installed Desktop layout still needs a visual check at the user's window
size before this overhaul is treated as visually approved.
