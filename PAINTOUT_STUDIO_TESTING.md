# Paintout Studio in Zura Nodes

Testing release, Zura Nodes 1.3.34. The updated Paintout tool is integrated into **Zura Studio > Video > Paintout / clean plate**. **Paintout Studio** is its separate showcase entry point for the contest. Both mount the same working page and controller, preserving the current project and edits when switching. Open **Zura > Open Paintout Studio** or **Zura > Open Zura Studio** from the ComfyUI menu, or search those commands. For a shortcut saved in a workflow, add the optional **Open Paintout Studio** or **Open Zura Studio** node and press its button. Visible Zura Studio and Paintout Studio buttons sit at the bottom-right of the graph; they hide while a Studio is open. No node is required. Direct links use your ComfyUI address with `?paintout=1` or `?zura=1`. Restart ComfyUI and refresh after updating.

The update refreshes the integrated `paintout/` backend and adds a scoped `web/paintout_studio/` interface. Small launcher modules and root registration expose the optional nodes and commands. The existing Studio launcher is changed to a menu command. Other node implementations, workflows, model paths and project media are preserved. Both Studio paintout interfaces use the same node IDs and local routes; this is a shared backend update.

For GitHub installs, update this repository, install its requirements using ComfyUI's Python, restart ComfyUI and refresh the browser. The separately supplied testing overlay also has an `Install.ps1` script that validates hashes and backs up replaced files before applying its launcher patch. Do not install the standalone Zura-Paintout package alongside this integration: the existing Zura pack owns these node IDs and routes.

Uses the same ComfyUI Python and local models as Zura Nodes, plus LTXVideo and KJNodes. Required Python libraries include NumPy, Pillow, SciPy, OpenImageIO and OpenCV. No models are bundled. See [model setup](docs/paintout-studio/MODEL_DOWNLOADS.md) and [manual checks](docs/paintout-studio/MANUAL_TESTING.md). Model licences and gated access remain separate from this code's licence.

## Watermark Removal

Watermark Removal is a separate Video workspace. Paint and save each static mask layer, then drag the ends of its timeline bar to set the active frame range. Add more layers for different marks or timings. Prepare and download the full-frame lossless mask from the Workspace menu for use in a compositor. Quality uses the cropped single-pass LTX path; Light uses ProPainter for SDR footage. Colour options are SDR to SDR, SDR to HDR and HDR to HDR. The original Paintout workspace continues to use its guided clean-frame anchors.

The current implementation processes one continuous shot at a time, with a maximum of 993 frames per clip. Automatic shot detection and long-range chunking are not integrated. HDR results should be checked on the source footage.
