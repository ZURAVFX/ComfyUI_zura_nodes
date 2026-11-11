# Paintout in Zura Studio

The standalone Paintout contest app is retired. Install Zura Nodes and open **Zura Studio > Video > Paintout / clean plate**.

## Features retained

The integrated editor already contains the useful standalone functionality and subsequent Studio improvements. Consolidation keeps that newer implementation rather than replacing it with the older contest UI.

| Feature | Location |
| --- | --- |
| Export trim, original frame numbering and independent tracking range | Paintout timeline and Trim clip |
| Automatic point previews, painting, erasing and custom mask import | Mask |
| Additive mask segments, duration handles and deletion | Mask timeline |
| Clean-frame cards at any source frame, manual import and export | Clean frames |
| Layered FLUX repairs, individual deletion, retry, blend and brightness | Clean-frame editor |
| Saved projects, model setup and download recovery | Shared Studio/Paintout controls |
| SDR/HDR processing and original-raster delivery | Paintout render settings |
| Editable ComfyUI graphs, owned cancellation and shared previews | Shared Studio infrastructure |

The main application uses `web/paintout_studio/paintout_shared.js` to mount its existing editor. The retained folder name is an internal asset path, not another application. No missing standalone feature was found that required copying an older module over the integrated version. Experimental latent upscaling remains outside this consolidation.

## Existing work

- Old `?paintout=1` links and the `zura.paintout.open` command open Paintout inside Zura Studio.
- The saved `ZuraPaintoutStudioLauncher` node ID still works, but is deprecated for new graphs. Its button opens Zura Studio.
- Saved project formats, browser storage keys, backend routes, masks, paint layers and output files are unchanged by consolidation. Keep the same ComfyUI data folders and browser profile/origin to access existing work.
- Disable an independently installed Zura Paintout pack before enabling Zura Nodes. Do not delete project folders, input footage or output files. Installations using another ComfyUI base directory may need their existing project data copied separately; no automatic cross-install migration is claimed.

The historical contest repository is retained for provenance and points users here. This change does not publish a new Registry version or alter model inference settings.
