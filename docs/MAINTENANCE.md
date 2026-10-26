# Repository maintenance review

Reviewed 26 October 2026 against `main` at `029420e` (Zura Nodes 1.3.32 testing build).

## Corrected

- Replaced the overlapping README with an overview, install instructions and guide links. Detailed node controls remain in [the node guide](NODE_GUIDE.md).
- Archived the 1.3.24 release candidate, removed its obsolete install-version label, corrected the standalone Paintout candidate label and marked dated scope notes as historical evidence.
- Corrected the product notes: rejected LTX viewport results are excluded, rather than offered as an experimental route.
- Removed `pyproject.toml.template`, which contained placeholder publisher/repository values, optional-licence text and incomplete dependencies despite the live package already being configured.
- Moved release asset validation to `tools/check_package.py` and added dependency-manifest consistency and catalogue-wide embedded-media checks. Existing release regression and publication steps are preserved.
- Added repository and frontend CI, relative documentation-link checks, and exclusions for authoring settings, historical candidate notes and generated archives.
- Updated checkout/setup actions to verified official releases, pinned by commit.
- Updated PostCSS from 8.5.6 to 8.5.31. The npm audit reported zero advisories after updating; generated frontend bundles matched the committed runtime content.

## Compatibility updates to assess separately

The Python requirements mostly use lower bounds, which already allow newer versions. Raising every lower bound would not help an existing installation and could unnecessarily exclude compatible ComfyUI environments.

`face-alignment` remains pinned to **1.4.1**. [PyPI lists 1.5.0](https://pypi.org/project/face-alignment/1.5.0/); an upgrade needs landmark/control compatibility checks and representative mouth-motion renders before changing the pin.

The exact ComfyUI and WanAnimatePreprocess revisions in the publish workflow are qualified test interfaces. Preserve them until replacements pass the native preparation parity checks. Model filenames and recipes also require model-specific validation, rather than substitution based on a newer filename.

The main branch remains a GitHub testing build. Paintout shot quality and fresh-machine installation are manual checks; this maintenance pass does not establish new render approvals.
