"""Queue-time consistency barrier for an artist-edited bounded Wan graph.

The node reads only its small plan JSON, the expanded API prompt, reviewed
metadata and preparation receipts. It never opens tensor caches or media and
does not approve source assets; existing native loaders and workers retain
those checks.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from . import wan_graph


class ZuraWanGraphQueueGuard:
    CATEGORY = "Zura/Artist Studio/Graph"
    FUNCTION = "validate"
    RETURN_TYPES = ("STRING", "INT", "INT", "FLOAT")
    RETURN_NAMES = ("motion_key", "section_start", "section_length", "guide_start_time")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"plan_json": ("STRING", {"default": "", "multiline": True})},
            "hidden": {"prompt": "PROMPT", "unique_id": "UNIQUE_ID"},
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # The cursor must be checked against receipts for every Queue action.
        return float("nan")

    @staticmethod
    def _error(reason: str):
        raise ValueError("Update section before queuing. " + reason)

    @staticmethod
    def _pins(value: Any) -> dict[str, Any]:
        if type(value) is not dict:
            ZuraWanGraphQueueGuard._error("The saved motion pins are malformed.")
        required = {
            "project_id", "review", "source_sha", "source_file", "approval",
            "character_sha", "character_file", "opening_sha", "opening_key",
            "opening_approval", "audio_sha", "audio_start", "lip_sync",
            "start", "duration", "length_mode", "resolution", "scope",
        }
        # Older saved Graph View plans predate the viewport flag. Treat those
        # as the existing motion-transfer route while pinning the flag for all
        # newly generated plans.
        allowed = required | {"viewport_render"}
        if not required <= set(value) or set(value) - allowed:
            ZuraWanGraphQueueGuard._error("The saved motion pins are incomplete.")
        value = dict(value)
        value.setdefault("viewport_render", False)
        if type(value["viewport_render"]) is not bool:
            ZuraWanGraphQueueGuard._error("The saved viewport mode pin is malformed.")
        for key in ("source_sha", "approval", "character_sha", "opening_sha", "opening_key"):
            try:
                wan_graph._sha(value.get(key), key.replace("_", " "))
            except wan_graph.WanGraphPlanError as error:
                ZuraWanGraphQueueGuard._error(str(error))
        if (type(value["review"]) is not str or not wan_graph.SHOT_RE.fullmatch(value["review"]) or
                value["opening_approval"] != value["opening_key"]):
            ZuraWanGraphQueueGuard._error("The reviewed shot or opening approval changed.")
        if (type(value["project_id"]) is not str or
                not re.fullmatch(r"[a-f0-9]{32}", value["project_id"])):
            ZuraWanGraphQueueGuard._error("The saved project identity is malformed.")
        if (type(value["source_file"]) is not str or not value["source_file"] or
                type(value["character_file"]) is not str or not value["character_file"]):
            ZuraWanGraphQueueGuard._error("The approved source or character reference is missing.")
        audio_sha = value["audio_sha"]
        if audio_sha:
            try:
                wan_graph._sha(audio_sha, "audio")
            except wan_graph.WanGraphPlanError as error:
                ZuraWanGraphQueueGuard._error(str(error))
        if (type(value["audio_start"]) not in (int, float) or
                not math.isfinite(value["audio_start"]) or value["audio_start"] < 0 or
                type(value["lip_sync"]) is not bool or
                (value["lip_sync"] and not value["audio_sha"]) or
                type(value["start"]) not in (int, float) or
                not math.isfinite(value["start"]) or value["start"] < 0 or
                type(value["duration"]) not in (int, float) or
                not math.isfinite(value["duration"]) or value["duration"] <= 0 or
                value["length_mode"] not in ("custom", "original") or
                type(value["resolution"]) is not int or value["resolution"] not in wan_graph.RESOLUTIONS or
                value["scope"] not in ("person", "head")):
            ZuraWanGraphQueueGuard._error("The current output settings are invalid.")
        return value

    @staticmethod
    def _check_key_plan(plan: Any) -> dict[str, Any]:
        fields = {
            "schema", "context_key", "recipe_sha256", "key_payload", "project_pins",
            "source_pin", "review_pin", "metadata", "total_frames", "max_part_frames",
            "render_long_edge", "scope", "start_frame", "frame_count", "guide_pin",
            "render_cache_stamps",
        }
        if type(plan) is not dict or set(plan) != fields or plan.get("schema") != wan_graph.PLAN_SCHEMA:
            ZuraWanGraphQueueGuard._error("The section plan is malformed or out of date.")
        try:
            wan_graph._sha(plan["context_key"], "motion key")
            wan_graph._sha(plan["recipe_sha256"], "preparation recipe")
            payload_sha = hashlib.sha256(wan_graph.canonical_key_payload(plan["key_payload"]).encode("utf-8")).hexdigest()
        except (KeyError, TypeError, ValueError, RecursionError) as error:
            ZuraWanGraphQueueGuard._error("The section plan has an invalid motion key.")
        if payload_sha != plan["context_key"]:
            ZuraWanGraphQueueGuard._error("The section plan key no longer matches its provenance.")
        pins = ZuraWanGraphQueueGuard._pins(plan["project_pins"])
        total, bound, start, count = (plan[k] for k in ("total_frames", "max_part_frames", "start_frame", "frame_count"))
        expected_bound = 41 if pins["resolution"] == 1920 else 81
        if (type(total) is not int or not 1 <= total <= 1_000_000 or
                type(bound) is not int or bound != expected_bound or
                plan["render_long_edge"] != pins["resolution"] or plan["scope"] != pins["scope"] or
                type(start) is not int or type(count) is not int or
                not 0 <= start < total or start % bound != 0 or
                count != min(bound, total - start)):
            ZuraWanGraphQueueGuard._error("The section is not the next canonical range in this approved shot.")

        source_pin = plan["source_pin"]
        review_pin = plan["review_pin"]
        guide = plan["guide_pin"]
        if (type(source_pin) is not dict or set(source_pin) != {"review_shot_id", "original_source_sha256"} or
                source_pin.get("review_shot_id") != pins["review"] or
                source_pin.get("original_source_sha256") != pins["source_sha"] or
                type(review_pin) is not dict or set(review_pin) != {"manifest_sha256", "mask_sha256"}):
            ZuraWanGraphQueueGuard._error("The section source or mask provenance changed.")
        for digest in review_pin.values():
            try:
                wan_graph._sha(digest, "review")
            except wan_graph.WanGraphPlanError as error:
                ZuraWanGraphQueueGuard._error(str(error))
        if guide is not None and (type(guide) is not dict or
                set(guide) != {"guide_key", "guide_sha", "path", "size", "mtime_ns", "manifest_sha256"}):
            ZuraWanGraphQueueGuard._error("The facial guide pin is malformed.")
        expected_guide = ({key: guide[key] for key in ("guide_key", "guide_sha", "path", "manifest_sha256")}
                          if guide else None)
        expected_payload = {
            "schema": wan_graph.SCHEMA,
            "project_pins": pins,
            "review_pin": review_pin,
            "recipe_sha256": plan["recipe_sha256"],
            "resolution": pins["resolution"],
            "scope": pins["scope"],
            "guide_pin": expected_guide,
        }
        if plan["key_payload"] != expected_payload:
            ZuraWanGraphQueueGuard._error("The section key does not match its approved source, review or appearance.")
        return plan

    @staticmethod
    def _validate_saved_project(root: Path, pins: dict[str, Any]) -> None:
        """Recheck the current small Studio record without inspecting assets."""
        from ..wan_preparation_runtime import read_json
        path = root / "genj" / "studio" / (pins["project_id"] + ".json")
        saved, _ = read_json(path, root, 2 * 1024 * 1024)
        if type(saved) is not dict or saved.get("id") != pins["project_id"]:
            ZuraWanGraphQueueGuard._error("The saved Studio shot identity changed.")
        from .studio import clean_config
        current_project = dict(saved)
        current_project["config"] = clean_config(saved.get("config", {}))
        if (current_project.get("opening_key") != pins["opening_key"] or
                type(current_project.get("opening_input")) is not dict or
                current_project["opening_input"].get("sha") != pins["opening_sha"]):
            ZuraWanGraphQueueGuard._error("The saved opening appearance changed.")
        # Some graph-stage approvals are intentionally held in the active
        # workflow instead of being written back to the project record. Accept
        # that visible approval only when its exact key and image SHA still
        # match the planned pins; never persist this in-memory normalization.
        if current_project.get("opening_approval") in (None, ""):
            current_project["opening_approval"] = current_project["opening_key"]
        current = wan_graph._project_pins(current_project)
        if current["approval"] != pins["approval"]:
            ZuraWanGraphQueueGuard._error("The saved mask approval changed. Review the shot again.")
        # Graph view deliberately owns its own source render resolution and
        # person/head scope. All other project pins, including the reviewed
        # source interval and selected speech asset/in-point, stay approved.
        ignored = {"resolution", "scope"}
        if ({key: value for key, value in current.items() if key not in ignored} !=
                {key: value for key, value in pins.items() if key not in ignored}):
            ZuraWanGraphQueueGuard._error("The saved source, appearance, interval or speech settings changed.")

    def validate(self, plan_json, prompt, unique_id):
        try:
            if type(plan_json) is not str or not 1 <= len(plan_json.encode("utf-8")) <= 2 * 1024 * 1024:
                self._error("The section plan is missing or exceeds its metadata limit.")
            from ..wan_preparation_runtime import parse_json, metadata_for_scope, scan_parts
            plan = self._check_key_plan(parse_json(plan_json))
            graph = wan_graph.expand_stage_signals(prompt)
            identity = str(unique_id)
            node = graph.get(identity)
            if (node is None or node["class_type"] != wan_graph.GRAPH_GUARD or
                    node["inputs"].get("plan_json") != plan_json):
                self._error("The section guard was moved or its plan changed.")

            pins = plan["project_pins"]
            project = {
                "approval": pins["approval"],
                "opening_input": {"sha": pins["opening_sha"]},
                "opening_approval": pins["opening_approval"],
                "opening_key": pins["opening_key"],
                "review": pins["review"],
                "source": {"sha": pins["source_sha"], "file": pins["source_file"]},
                "character": {"sha": pins["character_sha"], "file": pins["character_file"]},
                "audio": ({"sha": pins["audio_sha"]} if pins["audio_sha"] else None),
                "config": {"lip_sync": pins["lip_sync"], "audio_start": pins["audio_start"],
                           "start": pins["start"], "duration": pins["duration"],
                           "length_mode": pins["length_mode"]},
            }
            root = wan_graph._root(None)
            self._validate_saved_project(root, pins)
            clip, review_pin, _ = wan_graph._review_metadata(root, pins)
            if review_pin != plan["review_pin"] or clip["frames"] != plan["total_frames"]:
                self._error("The reviewed shot changed after the section was planned.")
            info = wan_graph._validate_roles(prompt, project, pins, clip, root, require_guard_wires=True)
            if info["guide_pin"] != plan["guide_pin"]:
                self._error("The approved speech guide changed after the section was planned.")
            recipe_sha = wan_graph.preparation_fingerprint(
                prompt, guide_loader_id=info["guide_loader_id"])
            if recipe_sha != plan["recipe_sha256"]:
                self._error("Native preparation settings changed. Update section before queuing.")

            render_paths = wan_graph._render_cache_paths(root, pins["review"], pins["resolution"], plan["total_frames"])
            current_stamps = wan_graph._render_cache_stamps(render_paths)
            expected_stamps = plan["render_cache_stamps"]
            if type(expected_stamps) is not dict or set(expected_stamps) != {"source", "mask"}:
                self._error("The approved source/mask cache pins are malformed.")
            for name in ("source", "mask"):
                expected, current = expected_stamps[name], current_stamps[name]
                if (type(expected) is not dict or expected.get("path") != current.get("path") or
                        expected.get("size") is not None and
                        (expected.get("size"), expected.get("mtime_ns")) !=
                        (current.get("size"), current.get("mtime_ns"))):
                    self._error("The approved rendered source or mask changed. Update section before queuing.")

            guide_key = plan["guide_pin"]["guide_key"] if plan["guide_pin"] else ""
            guide_sha = plan["guide_pin"]["guide_sha"] if plan["guide_pin"] else ""
            metadata = metadata_for_scope(plan["scope"], guide_key, guide_sha)
            if metadata != plan["metadata"]:
                self._error("The section metadata does not match its approved speech and scope.")
            paths, receipts, next_start = scan_parts(
                root, plan["context_key"], plan["total_frames"], metadata,
                source_pin=plan["source_pin"], review_pin=plan["review_pin"],
                max_part_frames=plan["max_part_frames"], render_long_edge=plan["render_long_edge"])
            if next_start != plan["start_frame"]:
                self._error("Preparation progress changed. Update section before queuing.")
            return (plan["context_key"], plan["start_frame"], plan["frame_count"],
                    plan["start_frame"] / 24.0)
        except ValueError as error:
            if str(error).startswith("Update section before queuing."):
                raise
            self._error(str(error))
        except Exception as error:
            self._error("The approved section could not be checked: " + str(error))


NODE_CLASS_MAPPINGS = {"ZuraWanGraphQueueGuard": ZuraWanGraphQueueGuard}
NODE_DISPLAY_NAME_MAPPINGS = {"ZuraWanGraphQueueGuard": "Zura · Validate Wan Graph Section"}
