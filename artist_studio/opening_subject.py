"""Subject-neutral opening edits and missing-selection checks, without inference."""
import re


def directed_source_subject(config):
    """Use an explicit 'replace X with Y' target, never guess from other prose.

    Manual text/point choices and specialist modes always take precedence.
    Unrecognised or ambiguous wording retains the existing person selection.
    """
    if (config.get("workflow_mode") != "swap" or config.get("edit_area") != "mask"
            or config.get("mask_method") != "auto" or config.get("scope") == "head"
            or config.get("preserve_people")):
        return None
    direction = config.get("image_prompt") or config.get("prompt") or ""
    match = re.match(r"\s*(?:replace|swap)\s+(?:the\s+)?([^\n.!?;]{1,100}?)\s+(?:with|for)\s+\S", direction, re.I)
    if not match:
        return None
    target = match.group(1).strip(" \"'")
    from .opening_edit import target_position
    if target_position(target) != 'auto':
        return None  # Spatial people are selected individually, not as a SAM category.
    if target.lower() in {"it", "this", "that", "him", "her", "them", "subject", "character", "person", "performer", "man", "woman", "guy", "bloke"}:
        return None
    # 'X and Y' needs the artist's explicit multi-subject selection, as do
    # spatial instructions. Keep the existing picker in those cases.
    if re.search(r"\b(?:and|or|except|background|everything)\b", target, re.I):
        return None
    return target


def missing_opening_selection(project):
    """Only recorded tracking coverage can establish an unusable first mask."""
    config = project.get("config", {})
    if (config.get("workflow_mode") != "swap" or config.get("edit_area") != "mask"
            or config.get("preserve_people")):
        return False
    coverage = project.get("tracking_coverage") or {}
    shots = coverage.get("shots") or []
    if not shots or not isinstance(shots[0], dict):
        return False
    first = shots[0]
    if first.get("start") != 0:
        return False
    return any(isinstance(span, dict) and span.get("start") == 0 and span.get("end", 0) > 0
               for span in first.get("near_empty_ranges", []))


def replacement_direction(target=None):
    subject = target or "selected source subject"
    return (
        f"Edit image 1. Remove the {subject} completely and put the main front-facing character or object "
        "from the second image in its place. One replacement only, with its complete body and its own silhouette, "
        "same scene position and similar height as the original subject. Match the reference identity, proportions, "
        "clothing and materials. Keep the source background, camera framing and unrelated objects. "
        "Do not copy a reference sheet, back view or multiple views. None of the original target remains. "
        "The source does not need to be human.")
