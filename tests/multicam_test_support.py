"""Use real ComfyUI when installed, or a small expansion stub for release CI."""
from __future__ import annotations

import sys
import types
from pathlib import Path


def prepare_comfy_imports():
    root = next((parent for parent in Path(__file__).resolve().parents
                 if (parent / "comfy_execution" / "graph_utils.py").is_file()), None)
    if root is not None:
        sys.path.insert(0, str(root))
        return
    if "folder_paths" not in sys.modules:
        sys.modules["folder_paths"] = types.ModuleType("folder_paths")
    if "comfy_execution.graph_utils" in sys.modules:
        return
    package = sys.modules.setdefault("comfy_execution", types.ModuleType("comfy_execution"))
    package.__path__ = []
    graph_utils = types.ModuleType("comfy_execution.graph_utils")

    class ExecutionBlocker:
        def __init__(self, message):
            self.message = message

    class GraphBuilder:
        def __init__(self):
            self.nodes = {}

        def node(self, class_type, **inputs):
            identifier = str(len(self.nodes) + 1)
            self.nodes[identifier] = {"class_type": class_type, "inputs": inputs}
            return types.SimpleNamespace(out=lambda index: [identifier, index])

        def finalize(self):
            return self.nodes

    graph_utils.ExecutionBlocker = ExecutionBlocker
    graph_utils.GraphBuilder = GraphBuilder
    sys.modules["comfy_execution.graph_utils"] = graph_utils
