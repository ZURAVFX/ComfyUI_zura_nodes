"""Persistent artist projects and orchestration of the native ComfyUI graphs."""
import asyncio
import copy
import hashlib
import json
import logging
import math
import re
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlparse

import av
from aiohttp import web
from PIL import Image

import folder_paths

HERE = Path(__file__).parent
STAGES = {
    "prepare": "01_Prepare_and_Review",
    "design": "01B_Design_Opening_Frame",
    "background": "02_LTX_Keep_Background",
    "restyle": "03_LTX_Depth_Restyle",
    "draft": "04_Seedance_Draft",
    "final": "05_Seedance_Accepted_Final",
    "h3": "06_H3_Character_Reference",
    "wan": "07_Wan_Character_Replacement",
    "wan_prepare": "07A_Wan_Motion_Preparation",
}
DEFAULTS = {"engine": "local", "background": "keep", "scope": "person", "prompt": "",
            "start": 0.0, "duration": 2.0, "size": 512, "performer": -1,
            "margin": 8, "pitch": False, "seed": 42, "render_size": 0, "h3_preset": "preview_quality", "remove_text": False,
            "resolution": 1280, "quality": "fast"}
PREP_KEYS = ("start", "duration", "size", "scope", "performer", "margin", "pitch")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def clean_config(value):
    c = {**DEFAULTS, **{k: v for k, v in value.items() if k in DEFAULTS}}
    # Older saved projects retain their selected render size. New artist
    # controls keep mask preparation at 512 and specify output size separately.
    if "resolution" not in value:
        c["resolution"] = int(value.get("render_size") or value.get("size", DEFAULTS["resolution"]))
    if "quality" in value or "resolution" in value:
        c["h3_preset"] = "take_fast" if c["quality"] == "fast" else "take_quality"
    from .h3 import H3_PRESETS
    for key, options in [("engine", ("local", "h3", "wan", "seedance")), ("background", ("keep", "restyle")),
                         ("quality", ("fast", "detailed")),
                         ("h3_preset", H3_PRESETS),
                         ("scope", ("person", "head"))]:
        if c[key] not in options:
            raise ValueError(f"Choose a valid {key} option.")
    for key in ("start", "duration"):
        c[key] = float(c[key])
        if not math.isfinite(c[key]):
            raise ValueError("Clip times must be finite numbers.")
    if not 0 <= c["start"] <= 86400 or not 0.1 <= c["duration"] <= 30:
        raise ValueError("Choose a start time and a duration between 0.1 and 30 seconds.")
    for key, low, high in [("size", 256, 960), ("performer", -1, 63), ("margin", 0, 128), ("seed", 0, 2**53 - 1)]:
        c[key] = int(c[key])
        if not low <= c[key] <= high:
            raise ValueError(f"{key.title()} is outside its supported range.")
    c["pitch"] = bool(c["pitch"])
    c["remove_text"] = bool(c["remove_text"])
    c["render_size"] = int(c["render_size"])
    if c["render_size"] not in (0, 1920):
        raise ValueError("This saved output setting is invalid. Choose an output resolution.")
    c["prompt"] = str(c["prompt"]).strip()[:5000]
    c["resolution"] = int(c["resolution"])
    if c["resolution"] not in (256, 512, 768, 960, 1280, 1920):
        raise ValueError("Choose a supported output resolution.")
    return c


class Store:
    def __init__(self, root=None):
        self.root = Path(root or Path(folder_paths.get_output_directory()) / "genj" / "studio")
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, project):
        project["updated"] = time.time()
        path = self.root / (project["id"] + ".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(project, indent=2), encoding="utf8")
        temporary.replace(path)

    def load(self, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", identity or ""):
            raise ValueError("Choose a saved shot or create a new one.")
        return json.loads((self.root / (identity + ".json")).read_text(encoding="utf8"))

    def list(self):
        result = []
        for path in self.root.glob("*.json"):
            try:
                p = json.loads(path.read_text(encoding="utf8"))
                if p.get("kind") == "project":
                    result.append(p)
            except (ValueError, OSError):
                logging.warning("Zura Studio: could not read a saved project record")
        return sorted(result, key=lambda p: p["updated"], reverse=True)


def check_asset(asset):
    path = Path(folder_paths.get_input_directory()) / asset["file"]
    root = (Path(folder_paths.get_input_directory()) / "genj_studio").resolve()
    if not path.resolve().is_relative_to(root) or sha(path) != asset["sha"]:
        raise ValueError("An uploaded reference has changed. Upload it again before continuing.")
    return path


def prep_key(project):
    settings = {"source": project["source"]["sha"], **{k: project["config"][k] for k in PREP_KEYS}}
    if project["config"].get("remove_text"):
        settings["remove_text"] = 1
    return hashlib.sha256(canonical(settings).encode()).hexdigest()


def assert_approved(project):
    from . import verify_review
    if not project.get("review") or project.get("approval") != prep_key(project):
        raise ValueError("Check the mask preview and choose Use this mask first.")
    check_asset(project["source"])
    verify_review(project["review"])


def text_cache_info(graph, stage):
    key = "5404" if stage == "background" else "5508"
    negative = "9008" if stage == "background" else "5509"
    prefix = "5407" if stage == "background" else "5004"
    encoder = graph[prefix + ":5606"]["inputs"]
    model = folder_paths.get_full_path("text_encoders", encoder["clip_name"])
    stamp = (Path(model).stat().st_size, Path(model).stat().st_mtime_ns) if model else None
    info = {"positive": graph[key]["inputs"]["value"], "negative": graph[negative]["inputs"]["value"],
            "encoder": encoder, "stamp": stamp, "format": 1}
    return hashlib.sha256(canonical(info).encode()).hexdigest(), info


def text_graph(info, cache_key):
    return {
        "encoder": {"class_type": "CLIPLoader", "inputs": info["encoder"]},
        "positive": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["encoder", 0], "text": info["positive"]}},
        "negative": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["encoder", 0], "text": info["negative"]}},
        "save": {"class_type": "GenjSaveTextConditioning", "inputs": {"positive": ["positive", 0],
                  "negative": ["negative", 0], "cache_key": cache_key}},
    }


def build_graph(project, stage):
    """Fill known native node inputs; no new subgraph interfaces are fabricated."""
    if stage == "h3":
        from .h3 import build_h3_graph
        return build_h3_graph(project)
    if stage == "wan":
        from .wan import build_wan_graph
        return build_wan_graph(project)
    graph = json.loads((HERE / "graphs" / (STAGES[stage] + ".json")).read_text(encoding="utf8"))
    c = project["config"]
    if stage != "prepare":
        assert_approved(project)
        check_asset(project["character"])
    for node in graph.values():
        typ, inputs = node["class_type"], node["inputs"]
        if typ == "GenjLoadReviewedShot":
            inputs.update(shot_id=project["review"], approved_shot_id=project["review"])
        elif typ == "RandomNoise":
            inputs["noise_seed"] = c["seed"]
        elif typ == "GenjRestoreSoundtrack":
            inputs["take_name"] = "studio_" + project["id"][:8] + "_" + stage
    if stage == "prepare":
        check_asset(project["source"])
        graph["2"]["inputs"]["file"] = project["source"]["file"]
        graph["3"]["inputs"].update(start_seconds=c["start"], duration_seconds=c["duration"], long_edge=c["size"])
        graph["7"]["inputs"]["text"] = c["scope"]
        graph["8"]["inputs"].pop("bboxes", None)  # Text detection over the entire source, at any aspect ratio.
        graph["9"]["inputs"]["performer"] = c["performer"]
        graph["12"]["inputs"]["expand"] = c["margin"]
        graph["18"]["inputs"]["pitch_vocals"] = c["pitch"]
        if c.get("remove_text"):
            graph["text_prompt"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["6", 1], "text": "text:20"}}
            graph["text_detect"] = {"class_type": "SAM3_Detect", "inputs": {
                "model": ["6", 0], "image": ["4", 0], "conditioning": ["text_prompt", 0],
                "threshold": 0.25, "refine_iterations": 0, "individual_masks": False}}
            graph["text_removal"] = {"class_type": "GenjTextRemovalMask", "inputs": {
                "performer_mask": ["12", 0], "text_mask": ["text_detect", 0],
                "text_boxes": ["text_detect", 1], "clip_details": ["3", 1], "padding": 5}}
            graph["17"]["inputs"]["mask"] = ["text_removal", 0]
            graph["20"]["inputs"].update(mask=["text_removal", 0], clip_details=["text_removal", 1])
    elif stage == "design":
        graph["121"]["inputs"]["image"] = project["character"]["file"]
        if c["scope"] == "head":
            graph["127"]["inputs"]["value"] = (
                "In the first image, replace only the performer's head with the identity from the second image. "
                "Match the face and hairstyle. Keep the original body, clothing, pose, head angle, expression, "
                "camera framing, background, objects and lighting unchanged. Return one complete scene. "
                "Do not add text or extra people.")
        if c["prompt"]:
            graph["127"]["inputs"]["value"] += " Additional appearance direction: " + c["prompt"]
        if c.get("remove_text"):
            graph["127"]["inputs"]["value"] += " Remove all on-screen captions, subtitles, title banners and lettering. Fill their former areas naturally with the scene or clothing."
        graph["122"]["inputs"]["filename_prefix"] = "genj/studio_images/" + project["id"]
    elif stage in ("background", "restyle"):
        if project.get("opening_approval") != project.get("opening_key") or not project.get("opening_input"):
            raise ValueError("Check the character preview and choose Animate this look first.")
        check_asset(project["opening_input"])
        graph["2004"]["inputs"]["image"] = project["opening_input"]["file"]
        for node in graph.values():
            if node["class_type"] == "GenjLoadReviewedShot":
                node["inputs"]["render_long_edge"] = c.get("resolution", c.get("render_size") or c["size"])
                node["inputs"]["output_scale"] = 1 if stage == "background" else 2
                node["inputs"]["preview_seconds"] = 0
        if stage == "background":
            # The preview decoder may have rounded the aspect ratio differently.
            # Restore its normalised registration before I2V's implicit centre crop.
            graph["5408:5188"]["inputs"] = {"input": ["2004", 0], "resize_type": "match size",
                "scale_method": "lanczos", "resize_type.match": ["5408:5371", 0], "resize_type.crop": "disabled"}
            for mask_resize in ("5408:5373", "5408:5381"):
                graph[mask_resize]["inputs"]["resize_type.crop"] = "disabled"
            # Native square max-pooling is extremely slow on HD CPU masks.
            # Mask Fix uses the equivalent rectangular maximum filter; keep
            # the exact radius and >0.5 threshold with no blur or hole filling.
            for identity in ("5408:5379", "5408:5382"):
                inputs = graph[identity]["inputs"]
                kernel, grow = identity + "_kernel", identity + "_grow"
                graph[kernel] = {"class_type": "ComfyMathExpression", "inputs": {
                    "expression": "2*a+1", "values.a": inputs["spatial_radius"]}}
                graph[grow] = {"class_type": "MaskFix+", "inputs": {"mask": inputs["mask"],
                    "erode_dilate": [kernel, 1], "fill_holes": 0, "remove_isolated_pixels": 0,
                    "smooth": 0, "blur": 0}}
                graph[identity] = {"class_type": "ThresholdMask", "inputs": {"mask": [grow, 0], "value": 0.5}}
        # Replacement always uses the approved scene image. The CLI exporter can
        # ignore promoted native widgets and retain the inner T2V default instead.
        image_switch = "5408:9018" if stage == "background" else "5014:5506"
        graph[image_switch]["inputs"]["value"] = True
        for node in graph.values():
            if node["class_type"] == "LTXVImgToVideoInplace":
                node["inputs"]["bypass"] = False
        # Use the LTX-2.5 A2V template's zero-noise source-audio path.
        # Speaker-reference tokens are identity context, not timed speech.
        graph["zura_fixed_audio_mask"] = {"class_type": "SolidMask", "inputs": {
            "value": 0.0, "width": 1024, "height": 1024}}
        if stage == "background":
            first_cond, second_cond = "5409:5114", "5410:5013"
            guiders, concats = ("5410:4828", "5414:5209"), ("5409:5391", "5413:5396")
            audio_latents = (["5409:5389", 0], ["5410:5394", 1])
            graph["5410:5013"]["inputs"].update(positive=[first_cond, 0], negative=[first_cond, 1])
            graph.pop("5409:5390")
            graph.pop("5413:5395")
            audio_model = ["5407:5607", 0]
        else:
            graph["9002:3980"] = {"class_type": "VAEEncodeAudio", "inputs": {
                "audio": ["9006", 1], "vae": ["5004:5600", 0]}}
            first_cond, second_cond = "9002:5012", "5549"
            guiders, concats = ("5516:4828", "5517:4964"), ("9002:4528", "5517:4969")
            audio_latents = (["9002:3980", 0], ["5516:4845", 1])
            graph["5549"]["inputs"].update(positive=[first_cond, 0], negative=[first_cond, 1])
            audio_model = ["5004:5607", 0]
        graph["zura_av_coupling"] = {"class_type": "LTXVModalityGuidance", "inputs": {
            "model": audio_model, "modality_scale": 3.0, "start_percent": 0.0, "end_percent": 1.0}}
        for index, (guider, concat, cond, audio) in enumerate(zip(
                guiders, concats, (first_cond, second_cond), audio_latents)):
            frozen = "zura_frozen_audio_" + str(index)
            graph[frozen] = {"class_type": "SetLatentNoiseMask", "inputs": {
                "samples": audio, "mask": ["zura_fixed_audio_mask", 0]}}
            graph[concat]["inputs"]["audio_latent"] = [frozen, 0]
            graph[guider]["inputs"].update(model=["zura_av_coupling", 0],
                positive=[cond, 0], negative=[cond, 1])
        key = "5404" if stage == "background" else "5508"
        if c["prompt"]:
            graph[key]["inputs"]["value"] += " Appearance direction: " + c["prompt"]
        if c.get("remove_text"):
            graph[key]["inputs"]["value"] += " Remove the masked captions, subtitles and title banners completely. Fill those areas with clean background or character clothing. No overlaid text or lettering."
        from . import text_cache_path
        cache_key, _ = text_cache_info(graph, stage)
        if text_cache_path(cache_key).exists():
            prefix = "5408" if stage == "background" else "5014"
            replacements = {prefix + ":2483": 0, prefix + ":2612": 1}
            for node in graph.values():
                for name, value in node["inputs"].items():
                    if isinstance(value, list) and len(value) == 2 and value[0] in replacements:
                        node["inputs"][name] = ["genj_cached_text", replacements[value[0]]]
            for name in replacements:
                graph.pop(name)
            graph["genj_cached_text"] = {"class_type": "GenjLoadTextConditioning", "inputs": {"cache_key": cache_key}}
    elif stage == "draft":
        from . import verify_review
        _, manifest = verify_review(project["review"])
        if manifest["clip"]["duration"] < 1.8:
            raise ValueError("Seedance needs a clip of at least 1.8 seconds. Choose a longer clip and prepare it again.")
        if c["resolution"] not in (512, 1280, 1920):
            raise ValueError("Seedance supports 480p (the small 512 px option), 720p or 1080p. Choose one of those resolutions.")
        graph["100"]["inputs"]["model.resolution"] = {512: "480p", 1280: "720p", 1920: "1080p"}[c["resolution"]]
        graph["2"]["inputs"]["image"] = project["character"]["file"]
        if c.get("remove_text"):
            graph["100"]["inputs"]["model.prompt"] += " Remove all on-screen captions, subtitles and title banners. Fill their former areas naturally. Do not add text overlays."
        if c["scope"] == "head":
            graph["100"]["inputs"]["model.prompt"] = graph["100"]["inputs"]["model.prompt"].replace(
                "entire selected subject", "selected head only; keep the body and clothing unchanged")
        if c["background"] == "restyle":
            graph["100"]["inputs"]["model.prompt"] = graph["100"]["inputs"]["model.prompt"].replace(
                "Keep the original RGB background, framing, camera movement", "Restyle the background while retaining framing and camera movement").replace(
                "or change the background", "or change the camera timing")
        graph["100"]["inputs"]["model.prompt"] += " " + c["prompt"]
        graph["100"]["inputs"]["seed"] = c["seed"]
    elif stage == "final":
        task = project.get("draft_task")
        if not task or project.get("accepted_draft") != task:
            raise ValueError("Inspect the draft and choose Finish at 1080p first.")
        graph["2"]["inputs"].update(draft_task_id=task, accepted_draft_id=task)
    return graph


def media_url(asset):
    return "/view?" + urlencode({k: asset[k] for k in ("filename", "subfolder", "type") if k in asset})


def public_project(project):
    p = copy.deepcopy(project)
    for key in ("source", "character", "opening_input"):
        if p.get(key):
            a = p[key]
            a["url"] = media_url({"filename": Path(a["file"]).name, "subfolder": str(Path(a["file"]).parent).replace("\\", "/"), "type": "input"})
    for action in p.get("actions", []):
        action.pop("graph", None)
    return p


class Studio:
    def __init__(self, server, store=None):
        self.server = server
        self.store = store or Store()
        self.lock = asyncio.Lock()
        self.watcher = None
        from comfy.cli_args import args
        self.server_address = f"{args.listen}:{args.port}"

    def start_watcher(self):
        if self.watcher is None or self.watcher.done():
            self.watcher = asyncio.create_task(self.watch())

    async def watch(self):
        while True:
            await asyncio.sleep(2)
            async with self.lock:
                for p in self.store.list():
                    try:
                        self.collect(p)
                    except Exception:
                        logging.exception("Zura Studio: could not collect a project result")

    async def resume_text(self, identity, action_id):
        async with self.lock:
            p = self.store.load(identity)
            action = p["actions"][-1]
            if (action["id"] != action_id or action["state"] != "complete" or p["phase"] != "working"
                    or action.get("server_address", self.server_address) != self.server_address):
                return
            try:
                await self.action(p, action["next_stage"], {"request_key": str(uuid.uuid5(uuid.NAMESPACE_URL, action_id))})
            except Exception as e:
                p.update(phase="error", error="Could not start the video after encoding its prompt: " + str(e)[:1600])
                self.store.save(p)

    def collect(self, p):
        try:
            return self._collect(p)
        except Exception as e:
            if p.get("actions"):
                p["actions"][-1]["state"] = "failed"
            p["phase"] = "error"
            p["error"] = "Could not read this job's output: " + (str(e) or type(e).__name__)[:1600]
            self.store.save(p)
            return p

    def _collect(self, p):
        actions = p.get("actions", [])
        if (actions and actions[-1]["stage"] in ("video_text", "h3_references", "wan_prepare") and actions[-1]["state"] == "complete"
                and p["phase"] == "working"
                and actions[-1].get("server_address", self.server_address) == self.server_address):
            asyncio.create_task(self.resume_text(p["id"], actions[-1]["id"]))
            return p
        if not actions or actions[-1]["state"] not in ("submitting", "queued", "running", "interrupted"):
            return p
        action = actions[-1]
        if action.get("server_address", self.server_address) != self.server_address:
            return p  # Shared output folders can be used by another ComfyUI instance.
        history = self.server.prompt_queue.get_history(action["id"]).get(action["id"])
        if not history:
            if action["state"] == "interrupted":
                running, pending = self.server.prompt_queue.get_current_queue_volatile()
                if any(item[1] == action["id"] for item in running + pending):
                    action["state"] = "running" if any(item[1] == action["id"] for item in running) else "queued"
                    p.update(phase="working", error=None)
                else:
                    return p  # Reconcile late completion, never resubmit an ambiguous job.
            running, pending = self.server.prompt_queue.get_current_queue_volatile()
            if (any(item[1] == action["id"] for item in running)
                    or getattr(self.server, "last_prompt_id", None) == action["id"]):
                action["state"] = "running"
                action.pop("absent_since", None)
            elif not any(item[1] == action["id"] for item in pending) and time.time() - action["created"] > 20:
                # History and queue are separate snapshots. The worker can finish
                # between them; check again before declaring the job absent.
                if self.server.prompt_queue.get_history(action["id"]).get(action["id"]):
                    return self._collect(p)
                action.setdefault("absent_since", time.time())
                if time.time() - action["absent_since"] > 90:
                    action["state"] = "interrupted"
                    p["phase"] = "error"
                    p["error"] = "ComfyUI restarted or this job is no longer in its queue. It has not been resubmitted. Check the Comfy job before repeating a paid render."
            else:
                action.pop("absent_since", None)
            self.store.save(p)
            return p
        status = history["status"]
        if status.get("status_str") != "success":
            action["state"] = "failed"
            p["phase"] = "error"
            errors = [m[1].get("exception_message", "") for m in status.get("messages", []) if m[0] == "execution_error"]
            p["error"] = (errors[-1] if errors else "The job stopped before completing. Check the Comfy job for details.")[:1800]
            self.store.save(p)
            return p
        outputs = history.get("outputs", {})
        stage = action["stage"]
        if stage in ("video_text", "h3_references", "wan_prepare"):
            action["state"] = "complete"
            self.store.save(p)
            asyncio.create_task(self.resume_text(p["id"], action["id"]))
            return p
        elif stage == "prepare":
            text = "\n".join(s for value in outputs.values() for s in value.get("text", []))
            match = re.search(r"shot_[a-f0-9]{16}", text)
            if not match:
                raise ValueError("Preparation returned no review. Check the Comfy job.")
            p["review"] = match.group()
            p.update(approval=None, opening_input=None, opening_key=None, opening_url=None,
                     opening_approval=None, draft_task=None, accepted_draft=None)
            p["prepared_key"] = prep_key(p)
            p["phase"] = "review"
            folder = "genj/reviews/" + p["review"]
            p["mask_url"] = media_url({"filename": "mask_review.mp4", "subfolder": folder, "type": "output"})
            p["guide_url"] = media_url({"filename": "guide.mp4", "subfolder": folder, "type": "output"})
            p["selected_url"] = media_url({"filename": "source.mp4", "subfolder": folder, "type": "output"})
        elif stage == "design":
            image = next(a for value in outputs.values() for a in value.get("images", []) if a.get("type") == "output")
            source = Path(folder_paths.get_output_directory()) / image.get("subfolder", "") / image["filename"]
            if not source.resolve().is_relative_to(Path(folder_paths.get_output_directory()).resolve()):
                raise ValueError("The image output is outside ComfyUI's output folder.")
            relative = "genj_studio/" + p["id"] + "/opening_" + action["id"] + ".png"
            target = Path(folder_paths.get_input_directory()) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            p["opening_input"] = {"file": relative, "sha": sha(target)}
            p["opening_key"] = p["opening_input"]["sha"]
            p["opening_approval"] = None
            p["opening_url"] = media_url(image)
            p["phase"] = "opening"
        else:
            video = next(a for value in outputs.values() for a in value.get("gifs", []) if a.get("subfolder") == "genj/final")
            item = {"stage": stage, "url": media_url(video), "asset": video, "created": time.time(),
                    "render_size": action.get("render_size", 0), "h3_preset": action.get("h3_preset"),
                    "resolution": action.get("resolution"), "duration": action.get("duration"), "quality": action.get("quality")}
            p.setdefault("results", []).append(item)
            if stage == "draft":
                text = "\n".join(s for value in outputs.values() for s in value.get("text", []))
                match = re.search(r"Draft task ID: ([^\s]+)", text)
                if not match:
                    raise ValueError("The draft returned no completion ID. Inspect its Comfy job before submitting again.")
                p["draft_task"] = match.group(1)
                p["accepted_draft"] = None
                p["phase"] = "draft"
            else:
                p["phase"] = "done"
        action["state"] = "complete"
        p["error"] = None
        self.store.save(p)
        return p

    def configure(self, p, value):
        self.collect(p)
        if p["phase"] == "working":
            raise ValueError("Wait for the current job before changing its settings.")
        old_key, prior = prep_key(p), p["config"]
        p["config"] = clean_config(value)
        if old_key != prep_key(p):
            p.update(phase="new", review=None, approval=None, opening_input=None,
                     opening_key=None, opening_url=None, opening_approval=None,
                     draft_task=None, accepted_draft=None)
        elif prior != p["config"]:
            p.update(draft_task=None, accepted_draft=None)
            if prior["prompt"] != p["config"]["prompt"]:
                p.update(opening_input=None, opening_key=None, opening_url=None, opening_approval=None)
            p["phase"] = ("opening" if p.get("opening_input") and p["config"]["engine"] in ("local", "h3", "wan")
                          else "approved" if p.get("approval") else "review" if p.get("review") else "new")
        self.store.save(p)
        return p

    async def action(self, p, stage, body):
        self.collect(p)
        if p.get("actions") and p["actions"][-1]["state"] in ("submitting", "queued", "running"):
            return p  # A double-click/reconnect never queues another job.
        if stage == "approve":
            from . import verify_review
            if p.get("prepared_key") != prep_key(p):
                raise ValueError("The source settings changed. Prepare the updated shot first.")
            check_asset(p["source"])
            verify_review(p["review"])
            p["approval"] = prep_key(p)
            p["phase"] = "approved"
            self.store.save(p)
            return p
        if stage == "animate":
            if not p.get("opening_input"):
                raise ValueError("Create the character preview first.")
            p["opening_approval"] = p["opening_key"]
            stage = (p["config"]["engine"] if p["config"]["engine"] in ("h3", "wan")
                     else "background" if p["config"]["background"] == "keep" else "restyle")
        if stage == "final":
            p["accepted_draft"] = p.get("draft_task")
        if stage not in STAGES:
            raise ValueError("Choose an available action.")
        # Prevent replay of a completed request caused by duplicate network delivery.
        request_key = str(body.get("request_key", ""))
        if not re.fullmatch(r"[a-f0-9-]{36}", request_key):
            raise ValueError("Reload Zura Studio before continuing.")
        if any(a.get("request_key") == request_key for a in p.get("actions", [])):
            return p
        auth = {k: body.get(k) for k in ("auth_token_comfy_org", "api_key_comfy_org") if body.get(k)}
        if stage in ("draft", "final") and not auth:
            raise ValueError("Sign in to your Comfy account in ComfyUI before using Seedance. Local generation needs no sign-in.")
        graph = build_graph(p, stage)
        next_stage = None
        if stage in ("background", "restyle") and "genj_cached_text" not in graph:
            cache_key, info = text_cache_info(graph, stage)
            next_stage, stage = stage, "video_text"
            graph = text_graph(info, cache_key)
        elif stage == "h3" and "h3_cached" not in graph:
            from .h3 import cache_key as h3_cache_key, reference_graph
            next_stage, stage = stage, "h3_references"
            graph = reference_graph(graph, h3_cache_key(p))
        elif stage == "wan" and "wan_save" in graph:
            next_stage, stage = "wan", "wan_prepare"
        import execution
        prompt_id = str(uuid.uuid4())
        data = self.server.trigger_on_prompt({"prompt": graph, "prompt_id": prompt_id,
                                             "client_id": body.get("client_id", "genj-studio")})
        graph = data["prompt"]
        self.server.node_replace_manager.apply_replacements(graph)
        valid = await execution.validate_prompt(prompt_id, graph, None)
        if not valid[0]:
            details = "; ".join(e.get("message", "") for n in valid[3].values() for e in n.get("errors", []))
            raise ValueError("ComfyUI needs attention before this can run: " + (details or str(valid[1]))[:1800])
        action = {"id": prompt_id, "stage": stage, "state": "submitting", "created": time.time(),
                  "request_key": request_key, "paid": stage in ("draft", "final"),
                  "render_size": p["config"].get("render_size", 0), "server_address": self.server_address,
                  "resolution": 1920 if stage == "final" else p["config"].get("resolution"), "duration": p["config"]["duration"], "quality": p["config"]["quality"]}
        if stage in ("h3", "h3_references"):
            action["render_size"] = 0
            action["h3_preset"] = p["config"]["h3_preset"]
        if next_stage:
            action["next_stage"] = next_stage
        p.setdefault("actions", []).append(action)
        p["phase"] = "working"
        p["error"] = None
        self.store.save(p)  # Persist BEFORE queueing; ambiguity is never retried automatically.
        extra = {"client_id": data.get("client_id", "genj-studio"), "create_time": int(time.time() * 1000),
                 "comfy_usage_source": "zura-studio"}
        number = self.server.number
        self.server.number += 1
        self.server.prompt_queue.put((number, prompt_id, graph, extra, valid[2], auth))
        action["state"] = "queued"
        self.store.save(p)
        self.start_watcher()
        return p


def register():
    from server import PromptServer
    if not getattr(PromptServer, "instance", None):
        return
    server = PromptServer.instance
    if getattr(server, "_zura_artist_studio_registered", False):
        return
    server._zura_artist_studio_registered = True
    studio = Studio(server)
    routes = server.routes

    def same_origin(request):
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            raise web.HTTPForbidden(text="Open Zura Studio inside this ComfyUI instance.")

    def response(fn):
        async def wrapped(request):
            try:
                same_origin(request)
                studio.start_watcher()
                return await fn(request)
            except (ValueError, KeyError, TypeError, OSError, av.error.FFmpegError) as e:
                return web.json_response({"error": str(e)}, status=400)
        return wrapped

    @routes.get("/zura/studio/status")
    @routes.get("/genj/studio/status")
    @response
    async def status(request):
        required = {
            "inpaint": ("loras", "ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors"),
            "ltx": ("diffusion_models", "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"),
            "klein": ("diffusion_models", "flux-2-klein-9b-fp8.safetensors"),
            "sam": ("checkpoints", "sam3.1_multiplex_fp16.safetensors"),
            "vocals": ("diffusion_models", "MelBandRoformer_fp16.safetensors"),
            "ltx_text": ("text_encoders", "gemma4-12b-with-proj-ltx-2.5-nvfp4.safetensors"),
            "ltx_video_vae": ("vae", "ltx-2.5-video-vae-bf16.safetensors"),
            "ltx_audio_vae": ("vae", "ltx-2.5-audio-vae-bf16.safetensors"),
            "ltx_upscaler": ("latent_upscale_models", "ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"),
            "klein_text": ("text_encoders", "qwen_3_8b_fp8mixed.safetensors"),
            "klein_vae": ("vae", "full_encoder_small_decoder.safetensors"),
            "depth_control": ("loras", "ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors"),
        }
        models = {key: bool(folder_paths.get_full_path(folder, name)) for key, (folder, name) in required.items()}
        from .h3 import H3_MODELS, H3_NATIVE_NODES
        import nodes
        h3_models = {key: bool(folder_paths.get_full_path(folder, name)) for key, (folder, name) in H3_MODELS.items()}
        missing_h3_nodes = [name for name in H3_NATIVE_NODES if name not in nodes.NODE_CLASS_MAPPINGS]
        from .wan import WAN_MODELS, WAN_NATIVE_NODES
        missing_ltx_nodes = [name for name in ("LTXVModalityGuidance", "SolidMask", "SetLatentNoiseMask",
                                              "MaskFix+", "ThresholdMask", "ComfyMathExpression")
                             if name not in nodes.NODE_CLASS_MAPPINGS]
        wan_models = {key: bool(folder_paths.get_full_path(folder, name)) for key, (folder, name) in WAN_MODELS.items()}
        missing_wan_nodes = [name for name in WAN_NATIVE_NODES if name not in nodes.NODE_CLASS_MAPPINGS]
        return web.json_response({"models": models, "h3_models": h3_models, "wan_models": wan_models,
            "engine_ready": {"local": all(models.values()) and not missing_ltx_nodes, "h3": all(h3_models.values()) and not missing_h3_nodes,
                             "wan": all(wan_models.values()) and not missing_wan_nodes},
            "engine_quality": {"local": "experimental speech timing: current talking test failed lip-sync review",
                               "h3": "experimental: current motion transfer failed user review",
                               "wan": "Native continuation without decoded-frame cross-fades; review each take"},
            "missing_ltx_nodes": missing_ltx_nodes,
            "missing_wan_nodes": missing_wan_nodes,
            "missing_h3_nodes": missing_h3_nodes, "ready": all(models.values()) and not missing_ltx_nodes, "version": 5, "brand": "Zura Studio", "package": "comfyui-zura-nodes",
            "runtime": {"source": str(HERE), "prompt_id": getattr(server, "last_prompt_id", None),
                        "running": [item[1] for item in server.prompt_queue.get_current_queue_volatile()[0]]}})

    @routes.post("/zura/studio/upload")
    @routes.post("/genj/studio/upload")
    @response
    async def upload(request):
        reader = await request.multipart()
        part = await reader.next()
        if part is None or not part.filename:
            raise ValueError("Choose a video or a character image.")
        kind = request.query.get("kind", "")
        suffix = Path(part.filename).suffix.lower()
        supported = {"video": (".mp4", ".mov", ".mkv", ".webm"), "image": (".png", ".jpg", ".jpeg", ".webp")}
        if kind not in supported or suffix not in supported[kind]:
            raise ValueError("Use an MP4/MOV video or a PNG/JPG/WebP character image.")
        identity = uuid.uuid4().hex
        relative = "genj_studio/" + identity + "/reference" + suffix
        path = Path(folder_paths.get_input_directory()) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with path.open("wb") as f:
            while chunk := await part.read_chunk(1024 * 1024):
                size += len(chunk)
                if size > 2 * 1024**3:
                    raise ValueError("Use a source video smaller than 2 GB.")
                f.write(chunk)
        details = {}
        if kind == "video":
            with av.open(str(path)) as video:
                if not video.streams.video:
                    raise ValueError("This file contains no video. Choose a performance clip.")
                stream = video.streams.video[0]
                duration = float(stream.duration * stream.time_base) if stream.duration else float((video.duration or 0) / av.time_base)
                if not math.isfinite(duration) or duration <= 0:
                    raise ValueError("The clip length could not be read. Export an MP4 and upload it again.")
                details = {"duration": duration, "width": stream.width, "height": stream.height}
        else:
            with Image.open(path) as image:
                image.verify()
        asset = {"id": identity, "kind": "asset", "asset_kind": kind, "file": relative,
                 "sha": sha(path), "name": Path(part.filename).name, **details}
        studio.store.save(asset)
        return web.json_response(public_project(asset))

    @routes.get("/zura/studio/projects")
    @routes.get("/genj/studio/projects")
    @response
    async def list_projects(request):
        async with studio.lock:
            return web.json_response([public_project(studio.collect(p)) for p in studio.store.list()])

    @routes.post("/zura/studio/projects")
    @routes.post("/genj/studio/projects")
    @response
    async def create_project(request):
        body = await request.json()
        source, character = studio.store.load(body["source"]), studio.store.load(body["character"])
        if source.get("asset_kind") != "video" or character.get("asset_kind") != "image":
            raise ValueError("Choose both a performance video and a character image.")
        p = {"id": uuid.uuid4().hex, "kind": "project", "name": source["name"], "source": source,
             "character": character, "config": clean_config(body.get("config", {})), "phase": "new",
             "actions": [], "results": [], "created": time.time()}
        studio.store.save(p)
        return web.json_response(public_project(p))

    @routes.get("/zura/studio/projects/{identity}")
    @routes.get("/genj/studio/projects/{identity}")
    @response
    async def get_project(request):
        async with studio.lock:
            return web.json_response(public_project(studio.collect(studio.store.load(request.match_info["identity"]))))

    @routes.post("/zura/studio/projects/{identity}/config")
    @routes.post("/genj/studio/projects/{identity}/config")
    @response
    async def configure(request):
        async with studio.lock:
            p = studio.store.load(request.match_info["identity"])
            body = await request.json()
            p = studio.configure(p, body.get("config", {}))
            return web.json_response(public_project(p))

    @routes.post("/zura/studio/projects/{identity}/action")
    @routes.post("/genj/studio/projects/{identity}/action")
    @response
    async def action(request):
        async with studio.lock:
            p = studio.store.load(request.match_info["identity"])
            body = await request.json()
            p = await studio.action(p, body.get("action"), body)
            return web.json_response(public_project(p))

    @routes.post("/zura/studio/projects/{identity}/cancel")
    @routes.post("/genj/studio/projects/{identity}/cancel")
    @response
    async def cancel(request):
        async with studio.lock:
            p = studio.collect(studio.store.load(request.match_info["identity"]))
            if p["phase"] == "working":
                identity = p["actions"][-1]["id"]
                # Atomic and scoped: never interrupt the user's other Comfy jobs.
                server.prompt_queue.interrupt_if_running(identity)
                server.prompt_queue.delete_queue_item(lambda item: item[1] == identity)
                p["actions"][-1]["state"] = "cancelled"
                p["phase"] = "error"
                p["error"] = ("Stopped this job. A provider request that already started may still be billed; it was not resubmitted."
                              if p["actions"][-1].get("paid") else "Stopped this local job.")
                studio.store.save(p)
            return web.json_response(public_project(p))
