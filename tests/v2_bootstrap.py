"""Standalone bootstrap for Zura nodes tests.

Adds the package root and the Zura package directory to ``sys.path`` and
stubs the ComfyUI-only modules the pack imports at module scope, so the tests
run with a plain ``python tests/test_v2_*.py`` on any interpreter that has
torch.  No pytest or ComfyUI installation is required.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Tests live inside the standalone package, so the package root is the module
# directory.  This keeps the suite independent of a larger ComfyUI checkout.
V2_PACKAGE = ROOT
V2_NAME = "ComfyUI_zura_nodes"

if V2_NAME not in sys.modules:
    package = types.ModuleType(V2_NAME)
    package.__path__ = [str(V2_PACKAGE)]
    sys.modules[V2_NAME] = package


def _stub(name: str, **attributes):
    if name in sys.modules:
        return sys.modules[name]
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _require_real(name):
    """Import a real module if present; return None when unavailable."""
    try:
        return __import__(name)
    except ImportError:
        return None


def install_stubs():
    """Stub ComfyUI modules that the v2 pack imports at module scope."""
    _require_real("numpy")
    _require_real("torch")

    if _require_real("PIL") is None:
        pil = _stub("PIL")
        pil.__path__ = []

    # folder_paths: only get_filename_list is touched at import time (Driving
    # clip INPUT_TYPES).  Everything else is called lazily inside functions.
    if _require_real("folder_paths") is None:
        _stub("folder_paths",
              get_filename_list=lambda *a, **k: [],
              get_input_directory=lambda: str(ROOT / "outputs" / "_v2_test_input"),
              get_temp_directory=lambda: str(ROOT / "outputs" / "_v2_test_temp"),
              get_annotated_filepath=lambda name: name,
              exists_annotated_filepath=lambda name: True,
              models_dir=str(ROOT / "models"),
              get_full_path=lambda *a, **k: None)

    # comfy_api is imported lazily inside video.video_output; the fallback dict
    # path is exercised when it is absent, so no stub is needed.  Provide one
    # only if ComfyUI itself is absent, to keep behaviour deterministic.
    if _require_real("comfy_api") is None and _require_real("comfy") is None:
        comfy_api = _stub("comfy_api")
        comfy_api.__path__ = []

    # The render node imports comfy_extras.nodes_wan lazily; tests that exercise
    # it install their own fake.  A placeholder package keeps import machinery
    # predictable if a test forgets.
    if _require_real("comfy_extras") is None:
        extras = _stub("comfy_extras")
        extras.__path__ = []

    return sys.modules


install_stubs()
