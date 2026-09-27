"""Foreground-on-grey video control for genuine ID-V2V scene restyling.

The result is conditioning, not a finished masked composite. ID-V2V generates
and relights every final video frame from this motion guide and a styled frame.
"""

import gc
import os

import cv2
import folder_paths
import numpy as np
import torch


def _segmentation_models():
    """Find YOLO weights even when their folder is supplied by extra_model_paths."""
    roots = {os.path.join(folder_paths.models_dir, "ultralytics")}
    for checkpoint_folder in folder_paths.get_folder_paths("checkpoints"):
        roots.add(os.path.join(os.path.dirname(checkpoint_folder), "ultralytics"))
    for root in sorted(roots):
        if os.path.isdir(root):
            folder_paths.add_model_folder_path("ultralytics", root)
    try:
        return [name for name in folder_paths.get_filename_list("ultralytics")
                if "seg" in name.lower()]
    except KeyError:
        return []

class ZuraMatchMouthMotion:
    """Correct a camera guide's mouth timing before generative relighting.

    The source pixels are never composited into the result. Only the generated
    angle guide's own mouth region is smoothly reshaped for control-video use.
    """

    _detector = None

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source_frames": ("IMAGE",),
            "angle_guide_frames": ("IMAGE",),
            "source_start_frame": ("INT", {"default": 0, "min": 0, "max": 100000}),
            "strength": ("FLOAT", {"default": 1.5, "min": 0.0, "max": 2.5, "step": 0.1}),
            "enabled": ("BOOLEAN", {"default": True}),
        }}

    RETURN_TYPES = ("IMAGE", "FLOAT")
    RETURN_NAMES = ("mouth_matched_guide", "mean_aperture_error_before")
    FUNCTION = "match"
    CATEGORY = "Zura/Video Control"

    @classmethod
    def _get_detector(cls):
        if cls._detector is None:
            try:
                import face_alignment
            except ImportError as exc:
                raise RuntimeError(
                    "Face-alignment is required for Zura Match Mouth Motion. "
                    "Install face-alignment==1.4.1 in this ComfyUI environment."
                ) from exc
            cache_dir = os.path.join(os.path.dirname(__file__), "model_cache", "hub")
            os.makedirs(cache_dir, exist_ok=True)
            previous_cache = torch.hub.get_dir()
            torch.hub.set_dir(cache_dir)
            # GPU FAN landmarks vary by a few mouth pixels between fresh runs;
            # ID-V2V amplifies that tiny difference. CPU was byte-repeatable.
            try:
                cls._detector = face_alignment.FaceAlignment(
                    face_alignment.LandmarksType.TWO_D, flip_input=False,
                    device="cpu")
            finally:
                torch.hub.set_dir(previous_cache)
        return cls._detector

    @staticmethod
    def _aperture_ratio(points):
        width = np.linalg.norm(points[54] - points[48])
        return float(np.linalg.norm(points[66] - points[62]) / max(width, 1.0))

    @staticmethod
    def _warp(frame, points, desired_ratio, strength):
        height, width = frame.shape[:2]
        mouth_width = float(np.linalg.norm(points[54] - points[48]))
        center = (points[62] + points[66]) / 2
        current_aperture = float(np.linalg.norm(points[66] - points[62]))
        half_change = strength * (desired_ratio * mouth_width - current_aperture) / 2
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        dx = (xx - center[0]) / max(0.8 * mouth_width, 1)
        dy = (yy - center[1]) / max(0.55 * mouth_width, 1)
        envelope = np.exp(-0.5 * dx**4 - 0.5 * dy**2)
        direction = np.tanh((yy - center[1]) / max(0.15 * mouth_width, 1))
        shift = half_change * direction * envelope
        return cv2.remap(frame, xx, yy - shift.astype(np.float32), cv2.INTER_CUBIC,
                         borderMode=cv2.BORDER_REPLICATE)

    def match(self, source_frames, angle_guide_frames, source_start_frame, strength, enabled):
        count = len(angle_guide_frames)
        if source_start_frame + count > len(source_frames):
            raise ValueError(
                f"Mouth guide needs {count} source frames starting at {source_start_frame}; "
                f"only {len(source_frames)} are available")
        if not enabled or strength == 0:
            return (angle_guide_frames, 0.0)
        previous_threads = torch.get_num_threads()
        try:
            # Four CPU threads gave the same deterministic guide in 39 s
            # rather than about 90 s for this 21-frame probe.
            torch.set_num_threads(4)
            return self._match_impl(source_frames, angle_guide_frames,
                                    source_start_frame, strength)
        finally:
            torch.set_num_threads(previous_threads)

    def _match_impl(self, source_frames, angle_guide_frames, source_start_frame, strength):
        detector = self._get_detector()
        output = []
        errors = []
        for index, angle_image in enumerate(angle_guide_frames):
            source_image = source_frames[source_start_frame + index]
            source_rgb = np.clip(source_image.detach().cpu().numpy() * 255, 0, 255).astype(np.uint8)
            angle_rgb = np.clip(angle_image.detach().cpu().numpy() * 255, 0, 255).astype(np.uint8)
            source_bgr = cv2.cvtColor(source_rgb, cv2.COLOR_RGB2BGR)
            angle_bgr = cv2.cvtColor(angle_rgb, cv2.COLOR_RGB2BGR)
            source_faces = detector.get_landmarks_from_image(source_bgr)
            angle_faces = detector.get_landmarks_from_image(angle_bgr)
            if not source_faces or not angle_faces:
                raise RuntimeError(f"Mouth landmark detection failed at frame {index}; guide not generated")
            desired = self._aperture_ratio(source_faces[0])
            observed = self._aperture_ratio(angle_faces[0])
            errors.append(abs(desired - observed))
            warped_bgr = self._warp(angle_bgr, angle_faces[0], desired, strength)
            warped_rgb = cv2.cvtColor(warped_bgr, cv2.COLOR_BGR2RGB)
            output.append(torch.from_numpy(warped_rgb.astype(np.float32) / 255.0))
        return (torch.stack(output), float(np.mean(errors)))


class ZuraIDV2VForegroundControl:
    @classmethod
    def INPUT_TYPES(cls):
        models = _segmentation_models()
        return {
            "required": {
                "images": ("IMAGE",),
                "segmentation_model": (models,),
                "background_colour": ("STRING", {"default": "#929398"}),
                "mask_erode_px": ("INT", {"default": 2, "min": 0, "max": 20}),
                "edge_softness_px": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0, "step": 0.25}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("control_frames", "person_masks")
    FUNCTION = "prepare"
    CATEGORY = "Zura/Video Control"

    def prepare(self, images, segmentation_model, background_colour, mask_erode_px, edge_softness_px):
        from ultralytics import YOLO

        _segmentation_models()
        model_path = folder_paths.get_full_path_or_raise("ultralytics", segmentation_model)
        colour = background_colour.lstrip("#")
        if len(colour) != 6:
            raise ValueError("Background colour must be a six-digit hex value, e.g. #929398")
        rgb = np.array([int(colour[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32)
        detector = YOLO(model_path)
        controls = []
        masks = []
        kernel = np.ones((3, 3), dtype=np.uint8)
        try:
            for index, image in enumerate(images):
                frame = np.clip(image.detach().cpu().numpy() * 255.0, 0, 255).astype(np.uint8)
                result = detector.predict(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), imgsz=960, conf=0.25, classes=[0], verbose=False)[0]
                if result.masks is None or len(result.masks.data) == 0:
                    raise RuntimeError(f"Person not detected in frame {index}; cannot safely preserve performance")
                candidates = result.masks.data.cpu().numpy()
                mask = candidates[np.argmax(candidates.sum(axis=(1, 2)))].astype(np.float32)
                mask = cv2.resize(mask, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_LINEAR)
                mask = (mask > 0.5).astype(np.uint8)
                count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
                if count > 2:
                    largest = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
                    mask = (labels == largest).astype(np.uint8)
                if mask_erode_px:
                    mask = cv2.erode(mask, kernel, iterations=mask_erode_px)
                mask = mask.astype(np.float32)
                if edge_softness_px:
                    mask = cv2.GaussianBlur(mask, (0, 0), edge_softness_px)
                mask = np.clip(mask, 0, 1)
                control = frame.astype(np.float32) * mask[..., None] + rgb * (1 - mask[..., None])
                controls.append(torch.from_numpy(np.clip(control / 255.0, 0, 1)))
                masks.append(torch.from_numpy(mask))
        finally:
            del detector
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        return torch.stack(controls), torch.stack(masks)


NODE_CLASS_MAPPINGS = {
    "ZuraIDV2VForegroundControl": ZuraIDV2VForegroundControl,
    "ZuraMatchMouthMotion": ZuraMatchMouthMotion,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ZuraIDV2VForegroundControl": "Zura · Person Motion Control",
    "ZuraMatchMouthMotion": "Zura · Match Mouth Motion",
}
