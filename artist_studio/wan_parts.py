"""Automatic native preparation progress, using the existing Studio handoff."""
from __future__ import annotations

import copy
from pathlib import Path

from ..wan_preparation_runtime import canonical, metadata_for_scope, read_json, scan_parts


def prepare_next_part_graph(project, cold_graph, cache_key):
    from . import verify_review
    import folder_paths
    directory, manifest = verify_review(project["review"])
    root = Path(folder_paths.get_output_directory()).resolve(strict=True)
    _, manifest_sha = read_json(Path(directory)/"review.json", root, 1024*1024)
    clip = manifest["clip"]
    total = clip.get("frames")
    if type(total) is not int or total < 1 or clip.get("fps") != 24:
        raise ValueError("Wan preparation needs the complete approved 24-fps timeline.")
    save = cold_graph.get("wan_save")
    if not isinstance(save, dict) or save.get("class_type") != "ZuraWanSavePreparation":
        raise ValueError("Open the native Wan preparation graph before preparing windows.")
    old = save["inputs"]
    if old.get("cache_key") != cache_key:
        raise ValueError("Wan preparation graph belongs to a different cache identity.")
    metadata = metadata_for_scope(old["scope"],old.get("speech_guide_key",""),old.get("speech_guide_sha",""))
    bound = 41 if int(project["config"]["resolution"]) == 1920 else 81
    source_pin = {"review_shot_id":project["review"],"original_source_sha256":clip["source_hash"]}
    review_pin = {"manifest_sha256":manifest_sha,"mask_sha256":manifest["files"]["mask.mp4"]}
    paths, receipts, start = scan_parts(root,cache_key,total,metadata,source_pin=source_pin,
        review_pin=review_pin,max_part_frames=bound,render_long_edge=int(project["config"]["resolution"]))
    if start == total:
        return {"wan_save":{"class_type":"ZuraWanMergePreparation","inputs":{
            "cache_key":cache_key,"total_frames":total,"receipts_json":canonical(paths),
            "metadata_json":canonical(metadata)}}}
    graph = copy.deepcopy(cold_graph)
    count = min(bound,total-start)
    for identity in ("wan_audio_selection","wan_reference_audio"):
        graph.pop(identity,None)
    graph["wan_frames"] = {"class_type":"ZuraWanPreparationWindow","inputs":{
        "source":["wan_shot",0],"mask_video":["wan_shot",1],"clip_details":["wan_shot",3],
        "start_frame":start,"frame_count":count}}
    carry_inputs = {"pose_data":["wan_pose_detect",0],"window":["wan_frames",4],
        "clip_details":["wan_shot",3],"reference":copy.deepcopy(old["reference"]),
        "cache_key":cache_key,"scope":old["scope"]}
    for key in ("speech_guide_key","speech_guide_sha"):
        if key in old:
            carry_inputs[key] = old[key]
    graph["wan_pose_carry"] = {"class_type":"ZuraWanCarryPoseWindow","inputs":carry_inputs}
    graph["wan_pose_draw"]["inputs"]["pose_data"] = ["wan_pose_carry",0]
    graph["wan_save"]["class_type"] = "ZuraWanSavePreparationPart"
    graph["wan_save"]["inputs"].update(window=["wan_frames",4],carry_state=["wan_pose_carry",1],
                                         clip_details=["wan_shot",3],cache_key=cache_key)
    if "wan_speech_video" in graph:
        graph["wan_speech_video"]["inputs"].update(frame_load_cap=count,start_time=start/24)
    return graph
