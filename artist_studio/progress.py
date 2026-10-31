"""Small, per-action adapter for ComfyUI's native node progress registry."""
from __future__ import annotations

import re
import threading
import time


def _friendly_node(class_type, stage=None):
    """Translate common model nodes to short artist-facing stage labels."""
    name = str(class_type or "").split(".")[-1]
    low = name.lower()
    if stage == "design":
        if "textencodeqwenimage21" in low or "textencodeqwenimageeditplus" in low:
            return "Preparing image references and prompt"
        if "unetloader" in low: return "Loading image model"
        if "cliploader" in low: return "Loading image text encoder"
        if "vaeloader" in low: return "Loading image decoder"
        if "loraloader" in low: return "Loading image adapter"
        if "vaedecode" in low or "decodeimage" in low: return "Decoding image"
        if "sampler" in low: return "Generating image"
    # Model loader classes are shared by Wan, LTX and image workflows. Only
    # name H3 when the active action is actually an H3 stage.
    is_h3=str(stage or '').startswith('h3')
    if not is_h3:
        if "unetloader" in low: return "Loading video model"
        if "cliploader" in low: return "Loading text encoder"
        if "vaeloader" in low: return "Loading video decoder"
        if "loraloader" in low: return "Loading video adapter"
    if "depthanything" in low:
        return "Building depth guidance"
    if "genjh3framepad" in low:
        return "Preparing H3 source frames"
    if "genjloadreviewedshot" in low:
        return "Preparing approved source video"
    if "imagefrombatch" in low:
        return "Selecting reference frames"
    if "modelpatchloader" in low:
        return "Loading H3 control model" if is_h3 else "Loading guidance model"
    if "unetloader" in low:
        return "Loading H3 video model"
    if "cliploader" in low:
        return "Loading H3 text encoder"
    if "vaeloader" in low:
        return "Loading H3 decoder"
    if "loraloader" in low:
        return "Loading H3 speed adapter"
    if any(token in low for token in ("textencode", "cliptext", "promptencode")):
        return "Preparing prompt"
    if "vaeencode" in low or "encodevideo" in low or "encodeimage" in low:
        return "Encoding guide"
    if "vaedecode" in low or "decodevideo" in low or "decodeimage" in low:
        return "Decoding video"
    if any(token in low for token in ("sampler", "hailuo", "videogenerate", "videodiffusion")):
        return "Generating video"
    if "upscale" in low:
        return "Upscaling video"
    if "load" in low:
        return "Loading inputs"
    # Keep unknown custom node names readable without exposing their node id.
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).replace("_", " ").strip()
    return (words[:1].upper() + words[1:]) if words else "Processing"


def _state_name(value):
    return str(getattr(value, "value", value)).lower()


def _number(value):
    try:
        value = float(value)
        return value if value >= 0 and value < float("inf") else None
    except (TypeError, ValueError, OverflowError):
        return None


class ProgressEstimator:
    """Estimate only the active node, requiring two measured progress intervals."""

    def __init__(self, clock=time.monotonic, max_actions=64):
        self._clock = clock
        self._max_actions = max_actions
        self._samples = {}
        self._lock = threading.Lock()

    def update(self, server_address, action_id, node_id, label, value, maximum,
               state="running", queue_position=None):
        key = (str(server_address), str(action_id))
        value, maximum = _number(value), _number(maximum)
        if not node_id or value is None or maximum is None or maximum <= 0:
            return self.indeterminate("preparing", label, queue_position)
        now = self._clock()
        node_key = str(node_id)
        with self._lock:
            prior = self._samples.get(key)
            if prior is None or prior["node_id"] != node_key or prior["maximum"] != maximum:
                prior = {"node_id": node_key, "maximum": maximum, "last_value": None,
                         "points": [], "elapsed_start": now}
            last_value = prior["last_value"]
            # A rewind means native progress restarted this node; discard its rate history.
            rewound = last_value is not None and value < last_value
            if rewound:
                prior["points"] = []
                prior["elapsed_start"] = now
            if last_value is None or value > last_value or rewound:
                # The first positive value is the baseline, not a timed interval:
                # it may include model warmup before useful work began.
                if value > 0:
                    prior["points"].append((now, value))
                    prior["points"] = prior["points"][-4:]
            prior["last_value"] = value
            self._samples[key] = prior
            # Bound memory if many projects are rendered in one Comfy session.
            while len(self._samples) > self._max_actions:
                self._samples.pop(next(iter(self._samples)))
            points = prior["points"]
            intervals = [(t1 - t0, v1 - v0) for (t0, v0), (t1, v1) in zip(points, points[1:])
                         if t1 > t0 and v1 > v0]
            elapsed = max(0.0, now - prior["elapsed_start"]) if prior["elapsed_start"] is not None else 0.0
            remaining = None
            confidence = "estimating"
            unknown_loader = maximum == 1 and value == 0
            if len(intervals) >= 2:
                seconds, steps = zip(*intervals[-2:])
                rate = sum(steps) / sum(seconds) if sum(seconds) > 0 else 0
                if rate > 0:
                    remaining = max(0.0, (maximum - value) / rate)
                    confidence = "measured"
            if unknown_loader:
                loading_label = str(label or "Loading")
                if loading_label == "LoadImage":
                    loading_label = "Loading"
                return {"state": "preparing", "stage_label": loading_label,
                        "stage_percent": None, "stage_elapsed_seconds": elapsed,
                        "stage_remaining_seconds": None, "eta_confidence": "estimating",
                        "step": None, "total_steps": None, "queue_position": queue_position}
        return {
            "state": "running" if state == "running" else "preparing",
            "stage_label": str(label or "Processing"),
            "stage_percent": min(100.0, max(0.0, value / maximum * 100.0)),
            "stage_elapsed_seconds": elapsed,
            "stage_remaining_seconds": remaining,
            "eta_confidence": confidence,
            "step": value,
            "total_steps": maximum,
            "queue_position": queue_position,
        }

    @staticmethod
    def indeterminate(state="preparing", label="Preparing", queue_position=None):
        return {"state": state if state in ("queued", "preparing", "running", "complete") else "preparing",
                "stage_label": label or "Preparing", "stage_percent": None,
                "stage_elapsed_seconds": 0.0, "stage_remaining_seconds": None,
                "eta_confidence": "estimating", "step": None, "total_steps": None,
                "queue_position": queue_position}


class NativeProgressAdapter:
    """Read the pinned ComfyUI core snapshot without patching its execution path."""

    def __init__(self, estimator=None, registry_getter=None):
        self.estimator = estimator or ProgressEstimator()
        self._registry_getter = registry_getter

    def _registry(self):
        if self._registry_getter:
            return self._registry_getter()
        try:
            from comfy_execution.progress import get_progress_state
            return get_progress_state()
        except (ImportError, AttributeError):
            return None

    def project_progress(self, server, server_address, action, queue_position=None):
        action_id = str(action.get("id") or "")
        if not action_id or action.get("server_address", server_address) != server_address:
            return None
        action_state = action.get("state")
        if action_state == "complete":
            return {**self.estimator.indeterminate("complete", "Complete"),
                    "stage_percent": 100.0, "stage_elapsed_seconds": 0.0}
        if action_state == "queued":
            return self.estimator.indeterminate("queued", "Waiting in queue", queue_position)
        if action_state not in ("running", "interrupted", "submitting"):
            return None
        registry = self._registry()
        if registry is None or getattr(registry, "prompt_id", None) != action_id:
            return self.estimator.indeterminate("preparing", _stage_fallback(action), queue_position)
        nodes = getattr(registry, "nodes", None)
        dynprompt = getattr(registry, "dynprompt", None)
        if not isinstance(nodes, dict) or dynprompt is None:
            return self.estimator.indeterminate("preparing", _stage_fallback(action), queue_position)
        active = [(node_id, item) for node_id, item in nodes.items()
                  if _state_name(item.get("state")) == "running"]
        if not active:
            return self.estimator.indeterminate("preparing", _stage_fallback(action), queue_position)
        node_id, item = active[-1]
        try:
            class_type = dynprompt.get_node(node_id).get("class_type")
        except (KeyError, TypeError, AttributeError):
            class_type = ""
        label = _friendly_node(class_type, action.get("stage"))
        return self.estimator.update(server_address, action_id, node_id, label,
                                     item.get("value"), item.get("max"), "running", queue_position)


def _stage_fallback(action):
    stage = str(action.get("stage") or "")
    if stage.startswith("ltx25_"):
        phase = stage.removeprefix("ltx25_")
        phases = {"text": "Preparing prompt", "motion": "Preparing motion guidance",
                  "stage1": "Generating video · pass 1 of 2",
                  "upscale": "Upscaling video", "refine": "Refining video · pass 2 of 2",
                  "decode": "Decoding and saving video", "cleanup": "Preparing the next step"}
        return "LTX 2.5 · " + phases.get(phase, "Preparing video")
    labels = {"h3": "Generating video", "wan": "Generating video", "local": "Generating video",
              "h3_enhance": "Enhancing video", "prepare": "Preparing video", "design": "Building scene"}
    return labels.get(stage, stage.replace("_", " ").title() or "Preparing")
