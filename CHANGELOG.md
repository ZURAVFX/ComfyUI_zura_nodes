# Release notes

## 1.3.19

- Save the four-stage LongCat editor with manual IN/OUT selection as the default.
- Clear the example actor dialogue and test cuts from the tracked LTX INT8 template.
- Both dialogue templates remain available through ComfyUI Browse Templates.

## 1.3.18

- Fix OUT handles at the end of audio: a half-millisecond rounding tolerance snaps to the final sample.
- Keep larger out-of-range selections invalid, and pass sample-aligned cuts from the selection editor to the final blend.


## 1.3.17

- Select the original and replacement sections together on two labelled waveforms.
- Separate final audio node with highlighted insert, playback, Download WAV and Update final audio.
- Reuse the retained LongCat take for cut and blend changes; hide stale final previews.
- Refuse final export when automatic selection fails, and retain the combined editor for older workflows.


## 1.3.16

- Adds a direct Download WAV action for successfully blended audio.
- Hides original-reference trim controls when only the additional recording is used.
- Clarifies that changing the take requires Run and shows immediate feedback.
- Recognises the standard Windows Parakeet runtime when LOCALAPPDATA is absent, with clearer launch errors.

## 1.3.13

- Adds **Viewport to final** for turning a grey 3D blockout into a finished
  scene, with an optional mask to limit the changed area.
- Routes the source through each engine's own guidance: LTX 2.5 uses its raw
  layout adapter, MiniMax H3 uses the source as a reference video, and Wan 2.2
  prepares pose guidance.
- LTX preserves the exact selected duration by padding the guide for sampling
  and trimming the decoded result back to the source frame count.
- Supports up to fifteen seconds for LTX Viewport to final. Other LTX Studio
  routes and MiniMax H3 remain limited to five seconds; Wan processes longer
  clips in sections.
- Does not add a blanket Canny or depth pass. In the tested LTX scene, depth
  guidance softened the image and shifted details. The raw layout route stays
  the default; Canny has not been qualified.

Install or update **Zura Nodes** through ComfyUI Manager by searching for
**Zura Nodes** from **ZURAVFX**, then restart ComfyUI. Model weights are separate
downloads. See [the Studio install guide](INSTALL_STUDIO.md) for the exact files
and setup steps.

The three local viewport routes completed five-second, 720p integration runs.
The exact viewport outputs still need separate artist review; they are not
included with the package. No private source media or audio is included.
