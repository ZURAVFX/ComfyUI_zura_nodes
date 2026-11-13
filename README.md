# Zura Nodes for ComfyUI

Local video, image and audio tools, with a guided **Zura Studio** interface and editable native ComfyUI graphs.

For first-frame object edits, choose **Video > Object replacement · Ripple**. See the [Ripple guide](docs/RIPPLE_OBJECT_REPLACEMENT.md) for masking, image review and model setup.

- **Video:** character replacement, camera changes, reference-to-video, relighting and speech replacement.
- **Extract alpha:** automatic LTX video matting with transparent ProRes 4444 and 16-bit matte exports. See the [alpha guide](docs/LTX_ALPHA.md).
- **Paintout:** tracked masks, painted clean frames, targeted removal and full-scene clean plates.
- **Image:** starting frames and image editing with source/reference controls.
- **Audio:** local speech, voice cloning, voice design and dialogue edits.

Model weights are separate downloads. Available routes and tested limits vary by model; see the [approved workflows](docs/APPROVED_WORKFLOWS.md) and [validation history](ARTIST_STUDIO_VALIDATION.md).

The Image workspace supports FLUX.2 Klein 9B and Flux 3 Klein for both creation
and editing. ChatGPT Image and Gemini Image are also available through your
browser account, with no Zura or paid API credits. Website plan limits apply.
See [browser image setup](docs/STUDIO_BROWSER_IMAGES.md).

## Install and open

Install **Zura Nodes**, published by **ZURAVFX**, through ComfyUI Manager when an approved Registry version is available. Otherwise, use the official [GitHub release](https://github.com/ZURAVFX/ComfyUI_zura_nodes/releases/latest).

Follow the [installation and model guide](INSTALL_STUDIO.md) to install Python requirements into ComfyUI's environment and download the models for your chosen task. Restart ComfyUI and refresh the browser.

Click **Zura Studio** at the bottom-right of the graph, or open it through the **Zura** menu, command search or the optional **Open Zura Studio** node. For paintout, choose **Video > Paintout / clean plate** inside Studio. On the default local address:

- [Zura Studio](http://127.0.0.1:8188/?zura=1)
- [Paintout inside Zura Studio](http://127.0.0.1:8188/?zura=1&workspace=paintout)

Use your own ComfyUI host and port if they differ.

## Current release

**1.3.65** adds PyAV 19 compatibility for exact 10-bit video clocks and includes the 1.3.64 improvements to shared SDR/HDR controls, high-depth source import, display-only OCIO views, source-sized image editing and the native ComfyLink handoff. It fixes LTX edit propagation and Camera source cadence while retaining the original guided removal flow and ordinary Studio drafts. Normal Studio remains free and independent of the separate native AE plug-in. Mode-specific GPU and AE acceptance is still in progress. See the [release notes](CHANGELOG.md) for tested scope and limits.

Zura Studio remains free to open and use normally, without a ComfyLink licence. The separate ComfyLink After Effects extension is optional and is not bundled here. Existing [Relight](docs/RELIGHT_MODELS.md), [Director](docs/DIRECTOR_STUDIO.md), [Paintout](PAINTOUT.md), [alpha extraction](docs/LTX_ALPHA.md), [Ripple editing](docs/RIPPLE_STUDIO.md) and [painted image edits](docs/IMAGE_EDIT_AREA.md) remain available.

The previous update adds complete camera-angle model setup, including MoGe 3, and checks gated-model access before large downloads. Choose a mode to see its missing files and extension guidance. Restart ComfyUI and refresh Studio after updating. See the [model setup notes](docs/STUDIO_1348_VALIDATION.md).

The [GitHub release](https://github.com/ZURAVFX/ComfyUI_zura_nodes/releases/latest) is available separately. Registry submission does not mean approval or immediate availability through Manager.

Paintout lives in **Studio > Video > Paintout / clean plate**. The standalone contest application is retired; its masks, layered clean-frame repairs, saved projects, model setup and SDR/HDR routes are already integrated. Existing Paintout links, commands and saved launcher nodes still open the integrated workspace. Disable an earlier standalone Zura Paintout installation to avoid duplicate nodes and routes. See the [consolidation notes](docs/PAINTOUT_CONSOLIDATION.md).

Read the [testing notes](PAINTOUT_STUDIO_TESTING.md), [model setup](docs/paintout-studio/MODEL_DOWNLOADS.md) and [manual checks](docs/paintout-studio/MANUAL_TESTING.md). Representative shot quality and a fresh-machine installation still need feedback. Version changes are recorded in the [changelog](CHANGELOG.md).

## Workflows

Open **Browse Templates > Zura Nodes**. Templates are grouped as Audio, Video, Image, Utility and Reference. The [template catalogue](TEMPLATES.md) lists each example and its setup requirements.

Examples include Wan character replacement, H3 camera changes, LTX paintout, LongCat dialogue editing, Qwen voice design, Gemma prompt enhancement and the original SAM3/H3 reference workflows. Their layouts and model selections remain editable.

Examples use placeholder media. Personal reference images, videos, voice recordings and model weights are not bundled.

## Guides

| Task | Guide |
| --- | --- |
| Install and select model files | [Installation](INSTALL_STUDIO.md) |
| Use the guided interface and Graph view | [Zura Studio](ARTIST_STUDIO.md) |
| Use an optional After Effects session | [ComfyLink Studio](docs/COMFYLINK_STUDIO.md) |
| Direct LTX or H3 with a shared timeline | [Director](docs/DIRECTOR_STUDIO.md) |
| Use standalone nodes and Wan continuation | [Node and workflow guide](docs/NODE_GUIDE.md) |
| Mask, remove objects and create clean plates | [Paintout](PAINTOUT.md) |
| Replace words in audio or video | [Dialogue editing](DIALOGUE_EDITING.md) |
| Clone a voice or generate speech | [LongCat](LONGCAT.md) |
| Design a voice with Qwen | [Voice design](VOICE_DESIGN.md) |
| Set up H3 attention options | [H3 speed comparisons](H3_SPEED.md) |
| Find detailed technical and historical notes | [Documentation index](docs/README.md) |

## Updates and development

Install available updates through ComfyUI Manager, or update your Git checkout, then restart ComfyUI and refresh the browser. Registry publication makes an update discoverable; users control when it is installed.

See [contributing and checks](CONTRIBUTING.md) for the repository layout and local validation, and [releasing](RELEASING.md) for GitHub-to-Registry publishing.

## Licence

Original Zura code is **AGPL-3.0-only**. The ComfyLink adapter includes MIT-licensed files with their original notices; see [the adapter guide](docs/COMFYLINK.md) and [MIT licence](comfylink/MIT-LICENSE.txt). See [LICENSE](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md) and the bundled licences for upstream components. Model weights retain their own licences.
