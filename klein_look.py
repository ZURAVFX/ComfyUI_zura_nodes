"""Small, reusable controls for optional FLUX.2 Klein image edits."""
from __future__ import annotations


LIGHTING = {
    "Keep source lighting": "Keep the original lighting and colour temperature.",
    "Soft studio": "Relight with a large, soft frontal studio key light and gentle fill; preserve natural skin texture.",
    "Cinematic contrast": "Relight with a controlled cinematic key light, gentle shadow falloff and natural contrast.",
    "Warm portrait": "Relight with warm, flattering portrait light and soft shadows, without changing skin tone.",
    "Cool editorial": "Relight with neutral-cool editorial light and restrained contrast, without changing skin tone.",
    "Three-point studio": "Relight with a large soft key light 45 degrees to camera, low-power fill on the opposite side and a subtle hair light. Keep realistic shadows and skin texture.",
    "Match new environment": "Relight the performer naturally to match the chosen environment, including its colour temperature and direction of light. Keep believable facial detail and skin tone.",
}

CAMERA_FINISH = {
    "Keep source camera": "Keep the source camera optics, exposure and photographic texture.",
    "Clean studio camera": "Give the image a polished professional studio-camera finish: natural 50 mm perspective, clean exposure, accurate white balance and realistic fine detail. Keep the source framing and do not beautify the face.",
    "Editorial portrait camera": "Give the image a high-quality editorial portrait-camera finish: natural 85 mm portrait rendering, subtle background separation, controlled highlights and realistic fine detail. Keep the source framing and do not beautify the face.",
}

BACKGROUNDS = (
    "Keep source background",
    "Clean white studio",
    "Neutral grey studio",
    "Solid colour",
    "Two-colour gradient",
    "Custom environment",
)


class ZuraKleinLookPresets:
    """Build one identity-safe edit prompt; no inference happens in this node."""

    CATEGORY = "Zura/image"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("edit_prompt", "edit_enabled", "background_mode")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "enable_edit": ("BOOLEAN", {
                "default": False,
                "label_on": "Edit source frame",
                "label_off": "Use original frame",
                "tooltip": "Use with Zura Optional Image Edit to bypass the edited branch when off.",
            }),
            "lighting": (list(LIGHTING), {"default": "Keep source lighting"}),
            "edge_light": ("BOOLEAN", {
                "default": False,
                "label_on": "Edge light on",
                "label_off": "Edge light off",
            }),
            "background": (list(BACKGROUNDS), {"default": "Keep source background"}),
            "background_colour": ("STRING", {
                "default": "warm grey",
                "tooltip": "Used only by Solid colour and Two-colour gradient.",
            }),
            "gradient_end_colour": ("STRING", {
                "default": "charcoal",
                "tooltip": "Used only by Two-colour gradient.",
            }),
            "custom_environment": ("STRING", {
                "default": "",
                "multiline": True,
                "tooltip": "Used only by Custom environment.",
            }),
            "extra_instructions": ("STRING", {
                "default": "",
                "multiline": True,
                "tooltip": "Optional short edit instructions; do not change the person's identity.",
            }),
            "camera_finish": (list(CAMERA_FINISH), {"default": "Keep source camera"}),
        }}

    @staticmethod
    def build(enable_edit=False, lighting="Keep source lighting", edge_light=False,
              background="Keep source background", background_colour="warm grey",
              gradient_end_colour="charcoal", custom_environment="",
              extra_instructions="", camera_finish="Keep source camera"):
        if lighting not in LIGHTING:
            raise ValueError(f"Unknown lighting preset: {lighting}")
        if background not in BACKGROUNDS:
            raise ValueError(f"Unknown background preset: {background}")
        if camera_finish not in CAMERA_FINISH:
            raise ValueError(f"Unknown camera finish: {camera_finish}")

        prompt = [
            "Edit the supplied photograph of one person. Preserve the exact person, "
            "face, age, hair, skin tone, clothing, pose, expression, camera perspective "
            "and framing. Keep the result photorealistic. Do not add another person, "
            "change the wardrobe or make a collage."
        ]
        prompt.append(LIGHTING[lighting])
        prompt.append(CAMERA_FINISH[camera_finish])
        if edge_light:
            prompt.append("Add a subtle rim light along the hair and shoulders; do not overexpose the face.")

        colour = str(background_colour).strip()[:80] or "warm grey"
        end_colour = str(gradient_end_colour).strip()[:80] or "charcoal"
        scene = str(custom_environment).strip()[:400]
        if background == "Keep source background":
            prompt.append("Keep the original background, room layout and objects unchanged.")
        elif background == "Clean white studio":
            prompt.append("Replace only the background with a seamless matte white studio cyclorama and a natural contact shadow.")
        elif background == "Neutral grey studio":
            prompt.append("Replace only the background with a seamless matte neutral-grey studio cyclorama and a natural contact shadow.")
        elif background == "Solid colour":
            prompt.append(f"Replace only the background with a seamless matte {colour} studio backdrop and a natural contact shadow.")
        elif background == "Two-colour gradient":
            prompt.append(f"Replace only the background with a smooth, subtle studio gradient from {colour} to {end_colour}; keep a natural contact shadow.")
        elif not scene and enable_edit:
            raise ValueError("Enter a custom environment or choose another background preset.")
        elif not scene:
            prompt.append("Keep the original background, room layout and objects unchanged.")
        else:
            prompt.append(f"Replace the entire original room and its objects with this new environment: {scene}. Keep the performer in the foreground, with plausible contact, scale, perspective and light interaction.")

        extra = str(extra_instructions).strip()[:500]
        if extra:
            prompt.append(extra)
        return " ".join(prompt), bool(enable_edit), background


class ZuraOptionalImageEdit:
    """Lazy switch: the unselected image branch is never evaluated."""

    CATEGORY = "Zura/image"
    FUNCTION = "select"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "original": ("IMAGE", {"lazy": True}),
            "edited": ("IMAGE", {"lazy": True}),
            "enable_edit": ("BOOLEAN", {"default": False}),
        }}

    def check_lazy_status(self, enable_edit=False, original=None, edited=None):
        name = "edited" if enable_edit else "original"
        return [name] if (edited if enable_edit else original) is None else []

    def select(self, enable_edit=False, original=None, edited=None):
        image = edited if enable_edit else original
        if image is None:
            raise ValueError("Connect the selected image branch before running.")
        return (image,)


NODE_CLASS_MAPPINGS = {
    "ZuraKleinLookPresets": ZuraKleinLookPresets,
    "ZuraOptionalImageEdit": ZuraOptionalImageEdit,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "ZuraKleinLookPresets": "Zura Klein Look Presets",
    "ZuraOptionalImageEdit": "Zura Optional Image Edit",
}
