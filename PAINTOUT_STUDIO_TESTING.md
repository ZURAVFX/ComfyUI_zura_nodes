# Paintout Studio in Zura Nodes

Testing release, Zura Nodes 1.3.34. The updated Paintout tool is integrated into **Zura Studio > Video > Paintout / clean plate**. **Paintout Studio** is its separate showcase entry point for the contest. Both mount the same working page and controller, preserving the current project and edits when switching. Open **Zura > Open Paintout Studio** or **Zura > Open Zura Studio** from the ComfyUI menu, or search those commands. For a shortcut saved in a workflow, add the optional **Open Paintout Studio** or **Open Zura Studio** node and press its button. Visible Zura Studio and Paintout Studio buttons sit at the bottom-right of the graph; they hide while a Studio is open. No node is required. Direct links use your ComfyUI address with `?paintout=1` or `?zura=1`. Restart ComfyUI and refresh after updating.

The update refreshes the integrated `paintout/` backend and adds a scoped `web/paintout_studio/` interface. Small launcher modules and root registration expose the optional nodes and commands. The existing Studio launcher is changed to a menu command. Other node implementations, workflows, model paths and project media are preserved. Both Studio paintout interfaces use the same node IDs and local routes; this is a shared backend update.

For GitHub installs, update this repository, install its requirements using ComfyUI's Python, restart ComfyUI and refresh the browser. The separately supplied testing overlay also has an `Install.ps1` script that validates hashes and backs up replaced files before applying its launcher patch. Do not install the standalone Zura-Paintout package alongside this integration: the existing Zura pack owns these node IDs and routes.

Uses the same ComfyUI Python and local models as Zura Nodes, plus LTXVideo and KJNodes. Required Python libraries include NumPy, Pillow, SciPy, OpenImageIO and OpenCV. No models are bundled. See [model setup](docs/paintout-studio/MODEL_DOWNLOADS.md) and [manual checks](docs/paintout-studio/MANUAL_TESTING.md). Model licences and gated access remain separate from this code's licence.

## Watermark Removal

Watermark Removal is a separate Video workspace. Paint and save each static mask layer, then drag the ends of its timeline bar to set the active frame range. Add more layers for different marks or timings. Prepare and download the full-frame lossless mask from the Workspace menu for use in a compositor. Quality uses the cropped single-pass LTX path; Light uses ProPainter for SDR footage. Colour options are SDR to SDR, SDR to HDR and HDR to HDR. The original Paintout workspace continues to use its guided clean-frame anchors.

The current implementation processes one continuous shot at a time, with a maximum of 993 frames per clip. Automatic shot detection and long-range chunking are not integrated. HDR results should be checked on the source footage.


## Watermark integration, 3 November 2026

Watermark Removal remains separate from anchor-guided Paintout. Its mask tools use static, trimmable layers; tracking settings and duplicate segment history are hidden. The shared model/workflow footer remains available from the empty state onwards.

Quality offers an optional **Clean first-frame guide**. Choose a cleaned full-size image corresponding to the first selected source frame. This uses the original `LTXVImgToVideoConditionOnly` approach at 0.7 strength before video guidance, rather than treating the image as a timed appended guide. The image passes through the same crop, resize, padding and colour conversion as the footage. Light/ProPainter ignores this option. Guided Paintout keeps its original timed anchors.

HDR Quality uses the full HDR video VAE. EXR guides can specify ACEScg/ACEScct; high-bit-depth TIFFs need their actual colour space selected. The compatible official adapter is named `ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors`. Official LTX 2.5 examples use this adapter; it does not require a 2.3 base model.

Gated files offer **Download in browser** followed by **Install downloaded file**. Accept terms and sign in on Hugging Face yourself. Studio does not borrow browser cookies. The install uses the shared catalogue, SHA-256 and safetensors checks, selected model destination, progress/cancellation and no-overwrite publishing. Existing browser downloads are kept. The native file chooser selects a download on the ComfyUI computer; remote clients must transfer that file to the host first. An optional read-token route remains under Advanced.

Actual isolated ComfyUI tests: 17-frame SDR source at 640 × 384 / 29.97 fps, with and without a clean reference; both delivered all frames at the original dimensions/rate. A 9-frame ACEScg/HLG reference test also ran. Render evidence is in the local `2026-11-03/watermark-integration` output folder. Automated browser inspection was unavailable due to the Windows browser-policy limitation. Elliot viewed the test Studio and approved the layout: “it looks good i can see”.

Setup recovery: missing extensions are distinguished from missing model files, with shared node-pack guidance and an enabled Back to workflow action when files are ready. Empty ProPainter packages explain that the extension fetches its weights on first use. The regular ComfyUI on port 8188 reports Quality and Light ready. The restricted port-8354 instance omits ProPainter; this is not an end-user installation fault. Regression checks cover returning without a download, extension-only setup and lost download responses.
