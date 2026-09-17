# Publishing updates

This repository is the source for the `comfyui-zura-nodes` package in the
[Comfy Registry](https://registry.comfy.org/nodes/comfyui-zura-nodes).

To release an update:

1. Commit and push your changes to `main`.
2. Choose a new version, for example `1.0.1`. Update `project.version` in
   `pyproject.toml` and `__version__` in `__init__.py`. If the example workflow
   changes, update the four Zura nodes' `properties.ver` values too.
3. On GitHub, create and publish a release with the matching tag, for example
   `v1.0.1`, targeting the updated commit.
4. Check **Actions > Publish to Comfy Registry**. It checks the version,
   runs the regression tests and publishes the package automatically.
5. Wait for Registry processing and verify the new version on the package page.

Ordinary code pushes do not publish a stable Registry version. This keeps
unfinished changes out of users' installs. Do not reuse a published version
number. The workflow can also be started manually for a version that has not
yet been published.

The publishing key is stored in the encrypted GitHub Actions repository secret
`REGISTRY_ACCESS_TOKEN`. It must belong to the `zuravfx` publisher. If it is
revoked or replaced, update that secret before publishing another release.
Never commit the key to this repository.

ComfyUI Manager can discover Registry updates. Users choose when to install
them, or use their own update settings. Publishing does not silently overwrite
their machines. Registry availability also does not guarantee inclusion in
Comfy Cloud's curated node environment.
