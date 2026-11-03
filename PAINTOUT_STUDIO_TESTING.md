# Paintout Studio in Zura Nodes

Testing release, Zura Nodes 1.3.34. The updated Paintout tool is integrated into **Zura Studio > Video > Paintout / clean plate**. **Paintout Studio** is its separate showcase entry point for the contest. Both mount the same working page and controller, preserving the current project and edits when switching. Open **Zura > Open Paintout Studio** or **Zura > Open Zura Studio** from the ComfyUI menu, or search those commands. For a shortcut saved in a workflow, add the optional **Open Paintout Studio** or **Open Zura Studio** node and press its button. Visible Zura Studio and Paintout Studio buttons sit at the bottom-right of the graph; they hide while a Studio is open. No node is required. Direct links use your ComfyUI address with `?paintout=1` or `?zura=1`. Restart ComfyUI and refresh after updating.

The update refreshes the integrated `paintout/` backend and adds a scoped `web/paintout_studio/` interface. Small launcher modules and root registration expose the optional nodes and commands. The existing Studio launcher is changed to a menu command. Other node implementations, workflows, model paths and project media are preserved. Both Studio paintout interfaces use the same node IDs and local routes; this is a shared backend update.

For GitHub installs, update this repository, install its requirements using ComfyUI's Python, restart ComfyUI and refresh the browser. The separately supplied testing overlay also has an `Install.ps1` script that validates hashes and backs up replaced files before applying its launcher patch. Do not install the standalone Zura-Paintout package alongside this integration: the existing Zura pack owns these node IDs and routes.

Uses the same ComfyUI Python and local models as Zura Nodes, plus LTXVideo and KJNodes. Required Python libraries include NumPy, Pillow, SciPy, OpenImageIO and OpenCV. No models are bundled. See [model setup](docs/paintout-studio/MODEL_DOWNLOADS.md) and [manual checks](docs/paintout-studio/MANUAL_TESTING.md). Model licences and gated access remain separate from this code's licence.

## Targeted repair methods

Guided repair remains the default and uses the painted clean frames at their selected source-frame times. The existing guided LTX graph, mask handling and model settings are retained. In Settings, Automatic selects the experimental cropped single-pass LTX inpainting path; Light selects SDR ProPainter and requires the `ComfyUI_ProPainter_Nodes` custom nodes. ProPainter may download its own weights on first use. Full-scene clean plate remains separate.

SDR-to-SDR, SDR-to-HDR and HDR-to-HDR remain distinct. Automatic supports HDR-to-HDR; Light supports SDR inputs and can feed SDR-to-HDR conversion. Automatic and Light offer full, three-quarter, half and quarter AI processing scales, capped to a 768-pixel crop, then composite into the original frame. HDR-to-HDR should be reviewed with genuine HDR footage on an appropriate display. SDR-to-HDR generates an HDR interpretation, not the source's lost highlight information.

These modes currently process one continuous shot per run. Automatic shot detection and long-range chunking are not integrated in this Studio path. The separate SDR-to-HDR conversion is limited by frame count and memory. Check mask edges, motion and colour on your footage before delivery.

Test: open each Studio separately; import footage; preview a hard mask; scrub and paint/erase; repair tracking from a visible frame; add another segment; add a clean frame and adjust Expand mask; generate and accept/reject a FLUX result; render and check source dimensions, frame count and frame rate. Tracking after full occlusion may require a new seed. Saved projects in the isolated 8189 test instance remain there; the regular instance has its own project/output directory.

This is a public testing release submitted to Comfy Registry for processing. Registry approval and Manager availability must be checked separately. It does not submit a contest entry. Representative removal quality and a second-machine installation remain manual acceptance checks.
