# Image Studio

Open Zura Studio and choose **Image** or **Video**. Switching workspaces keeps
the current video shot and image prompt. Home returns to the two choices.

Use the header Light mode / Dark mode toggle to change appearance. The choice is saved in this browser and shared across Home, Image and Video.

For images, choose a model and shape, or enter width and height (256–2048 pixels in increments of 16). Swap exchanges the dimensions. Sizes above the tested 1 MP range display a memory notice; they are not guaranteed to fit every 16 GB setup. Dimensions are saved with the prompt and restored by Reuse prompt. Write a prompt, then select **Generate
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
prompt length and image shape affect speed. Preset shapes use approximately
the same pixel budget. Custom dimensions up to 2048 per side are available; these larger sizes have not been performance-qualified. Batch outputs are not exposed.

| Model | Installed recipe | Steps | Observed execution time |
| --- | --- | --- | --- |
| Flux 3 Klein | INT8 convrot; Qwen3-VL 4B INT8; Flux 2 VAE | 16 | 7.3 s |
| Flux 2 Klein 4B | FP8; Qwen3 4B; Flux 2 VAE | 4 | 5.1 s |
| Z-Image Turbo | BF16; Qwen3 4B; AE VAE; AuraFlow shift 3 | 9 | 40.0 s |

All use Euler/simple, CFG 1, one image. Drag PNG, JPEG or WebP files onto the reference strip beside the prompt, or
select Reference images. You can also paste a copied image with Ctrl+V (Cmd+V on macOS) anywhere inside the Image workspace, including while the prompt is focused. Normal text pasting is unchanged. Flux 3 Klein supports up to 10 references; Flux 2 Klein
supports 4. Z-Image Turbo remains text-only. Switching to an incompatible model
retains the references and blocks generation until the mismatch is resolved.
Thumbnails are numbered in conditioning order, with remove and move-earlier
controls. Refer to Image 1, Image 2, etc. in the prompt. Reuse prompt restores
the references as well as the original dimensions and seed.

Reference images use native LoadImage / ReferenceMultiLatent nodes, with each
reference capped at 1 MP and a combined 2 MP preparation budget. Above two
references, the UI discloses this resize. The originals remain unchanged.
Two-reference Flux 3 and four-reference Flux 2 edits were rendered and visually
checked at 768 × 512: red upholstery replaced the teal upholstery in the supplied
train views. Ten-reference Flux 3 performance has not been qualified.

Clear history empties the image gallery and saves that choice across reloads.
It does not delete output files or reference uploads. Undo clear restores the
previous gallery during the current session. A run already in progress can
still add its new result after the history is cleared.

Reference limits follow the [Flux 3 model card](https://huggingface.co/black-forest-labs/flux-3-image-klein)
and [BFL's Klein guide](https://help.bfl.ai/articles/7592221790-how-do-i-generate-quickly-with-flux-2-klein).

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

Native recipe and DOM interaction tests pass. The current changes still need a
live visual check in the installed Comfy Desktop window at the user's display
size before this overhaul is treated as visually approved.
