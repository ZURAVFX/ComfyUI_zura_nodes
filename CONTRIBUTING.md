# Contributing

Use Python 3.10 or newer for the runtime. Repository metadata checks use Python 3.11 or newer (`tomllib`). CI uses Python 3.12. Run commands from the repository root.

## Layout

- Root Python modules register the native nodes and shared video/audio helpers.
- `artist_studio/` contains Studio orchestration and native graph recipes.
- `paintout/` contains masking, clean-frame and delivery tools.
- `web/` contains the ComfyUI extension and bundled runtime assets.
- `workflows/` contains reviewed templates listed in `template_catalogue.json`.
- `docs/` contains guides, dated evidence and historical notes.
- `tests/` contains Python CPU tests and Node.js UI/graph checks.
- `tools/` contains repository checks and frontend build sources.
- Speech runtime folders have their own optional environment requirements.

Keep saved node IDs, wire contracts and public routes compatible with existing workflows. Keep model/media downloads, credentials and machine-specific settings out of commits.

## Fast repository checks

These checks do not load models or install ComfyUI. The VoiceDesign boundary tests need `torch` and `soundfile` in the development environment; CI installs CPU-only Torch for them.

```sh
python tools/check_package.py
python tools/check_docs.py
python -m unittest discover -s tests -p test_template_catalogue.py
python -m unittest discover -s tests -p test_longcat_release.py
python -m unittest discover -s tests -p test_voice_design_release.py
```

The Repository checks workflow runs these on pushes and pull requests. It cannot publish a Registry version.

## Runtime regression checks

Install the test libraries listed in `.github/workflows/publish.yml` into a development environment and match that workflow's commands. Run Python test modules in separate processes: several suites install ComfyUI stubs that must not leak between modules.

The DOM tests use `linkedom@0.18.13` outside the distributable repository:

```sh
npm install --prefix ../ui-check --ignore-scripts --no-audit --no-fund linkedom@0.18.13
node tests/test_studio_upload_dom.mjs
```

Native preparation tests require the exact ComfyUI and preprocessing revisions recorded in the publish workflow. Those are qualified interfaces, rather than automatic upgrade targets. GPU render quality and fresh-machine installation still require manual checks.

## Frontend bundles

Edit source files under `tools/studio-ui/`, then run:

```sh
cd tools/studio-ui
npm ci --ignore-scripts
npm run build
```

Commit reviewed generated files under `web/vendor/` with their licence notices. Installed `node_modules/` and intermediate CSS are excluded.

## Versions and releases

`pyproject.toml` is the canonical package metadata. Keep `requirements.txt` aligned with its runtime dependencies and `__version__` aligned with its version. Optional speech environments remain separate.

See [RELEASING.md](RELEASING.md) before tagging a release. A cleanup or documentation push does not need a new Registry version.
