# Zura Nodes for ComfyUI

Local video, image and audio tools, with a guided **Zura Studio** interface and editable native ComfyUI graphs.

- **Video:** character replacement, camera changes, reference-to-video, relighting and speech replacement.
- **Paintout:** tracked masks, painted clean frames, targeted removal and full-scene clean plates.
- **Image:** starting frames and image editing with source/reference controls.
- **Audio:** local speech, voice cloning, voice design and dialogue edits.

Model weights are separate downloads. Available routes and tested limits vary by model; see the [approved workflows](docs/APPROVED_WORKFLOWS.md) and [validation history](ARTIST_STUDIO_VALIDATION.md).

## Install and open

Install **Zura Nodes**, published by **ZURAVFX**, through ComfyUI Manager when an approved Registry version is available. Otherwise, use the official [GitHub release](https://github.com/ZURAVFX/ComfyUI_zura_nodes/releases/latest).

Follow the [installation and model guide](INSTALL_STUDIO.md) to install Python requirements into ComfyUI's environment and download the models for your chosen task. Restart ComfyUI and refresh the browser.

Click the visible **Zura Studio** or **Paintout Studio** button at the bottom-right of the graph. Both also remain available through the **Zura** menu and command search. Optional **Open Zura Studio** and **Open Paintout Studio** launcher nodes provide shortcuts inside a workflow. On the default local address:

- [Zura Studio](http://127.0.0.1:8188/?zura=1)
- [Paintout Studio](http://127.0.0.1:8188/?paintout=1)

Use your own ComfyUI host and port if they differ.

## Current release

**1.3.37** fixes Wan 2.1 Relight incorrectly showing an H3 limit and model label. Longer relight shots run in sections; review the joins on your footage. The optional FastH3 draft preset remains available beside normal H3 in **Video > Reference to video**; see its [tested limits and trade-offs](docs/FASTH3_DRAFT.md).

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
