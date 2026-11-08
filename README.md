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

Click the visible **Zura Studio** or **Paintout Studio** button at the bottom-right of the graph. Both also remain available through the **Zura** menu and command search. Optional **Open Zura Studio** and **Open Paintout Studio** launcher nodes provide shortcuts inside a workflow. On the default local address:

- [Zura Studio](http://127.0.0.1:8188/?zura=1)
- [Paintout Studio](http://127.0.0.1:8188/?paintout=1)

Use your own ComfyUI host and port if they differ.

## Current release

**1.3.58** adds [LTX and H3 Relight options](docs/RELIGHT_MODELS.md) alongside Wan 2.1, with shared lighting frames and a separate Relight draft. It also includes a shared visual mode picker, compact browser sign-in controls and the native LTX/H3 [Director timeline](docs/DIRECTOR_STUDIO.md), including clip dragging, resizing and preserved source audio. First/last-frame video can match image 1 dimensions or scale its aspect ratio with the megapixel slider. Camera editing gains optional [locked scene geometry](docs/PANORAMA_STUDIO_INTEGRATION.md). Existing Paintout retries, [alpha extraction](docs/LTX_ALPHA.md), [Ripple editing](docs/RIPPLE_STUDIO.md) and [painted image edits](docs/IMAGE_EDIT_AREA.md) remain included. See the [release notes](CHANGELOG.md) for validation and remaining limits.

The previous update adds complete camera-angle model setup, including MoGe 3, and checks gated-model access before large downloads. Choose a mode to see its missing files and extension guidance. Restart ComfyUI and refresh Studio after updating. See the [model setup notes](docs/STUDIO_1348_VALIDATION.md).

The [GitHub release](https://github.com/ZURAVFX/ComfyUI_zura_nodes/releases/latest) is available separately. Registry submission does not mean approval or immediate availability through Manager.

Paintout is integrated into **Studio > Video > Paintout / clean plate**. Its separate Paintout Studio entry opens the same working page and controller. Disable an earlier standalone Zura Paintout installation before using this integration to avoid duplicate nodes and routes.

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

Original Zura code is **AGPL-3.0-only**. See [LICENSE](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md) and the bundled licences for upstream components. Model weights retain their own licences.
