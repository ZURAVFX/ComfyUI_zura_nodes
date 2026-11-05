# Zura Studio 1.3.48: mode model setup

5 November 2026. Public Zura Nodes update.

## User flow

Select a mode, review its setup card and install the missing files. Existing models are reused and the selected mode supplies the exact file list. Merely opening a mode does not download models or install extensions.

Change camera angle previously opened the Panorama workspace without an installer. MoGe 3 was missing from the download catalogue and readiness checked an abbreviated node list. This update supplies the pinned MoGe file, all six H3 render files, graph-derived node checks, Panorama Registry guidance and a Check setup action. Shared model folders now include `geometry_estimation`.

Gated downloads check the selected pinned files before transferring model data. The shared flow covers Image, Video, HDR, Paintout, Inpaint, Ripple and Watermark model panels. Sign in, review each model publisher's terms, then continue. Publisher approval is separate from signing in and cannot be bypassed. No terms are accepted automatically. Credentials stay on the ComfyUI server; access checks neither return them nor forward them to redirect destinations.

## Verification

- All 149 commands from the release regression step passed locally. Media-dependent checks were rerun after adding FFmpeg to the test process PATH.
- New Python tests cover complete camera file coverage, missing model categories, graph-derived node readiness, multiple gated repositories, network failures and rejection of files outside the catalogue.
- Real local HTTP route tests cover the new access-check action and its catalogue validation.
- New DOM tests cover entering camera mode on a fresh installation, one exact-file install, missing-extension blocking, readiness refresh and switching modes while an access check is pending.
- Existing DOM and graph checks cover the Image, character, viewport, relight, first/last-frame, reference-video, HDR, Paintout, Inpaint, Ripple, Watermark and frame-extension workspaces.
- All seven pinned camera model URLs returned download redirects and their expected published file sizes. No large model download was needed for this check.
- A browser preview using the actual camera workspace and setup components with synthetic missing-model responses verified the setup card and readable, scrollable dependency panel at 1280 x 720.

## Limits

This is an installation and readiness update. No fresh GPU generation, publisher approval, or multi-gigabyte model download was performed in this validation run. Existing recipe quality limits remain; see [verified scope](STUDIO_VERIFIED_SCOPE.md). Camera preview still requires original audio, supports up to five seconds and retains its existing output limits. Extensions are installed through ComfyUI Manager and may require a restart. The setup panel reports them separately from model files.

The release workflow reruns regression and qualified native CPU-interface checks before publishing to the Comfy Registry.
