"""Neutral CPU progression through visible native preparation windows."""
import copy
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import torch
from torch._subclasses.fake_tensor import FakeTensorMode
# Initialise Torch's one-time library registrations outside module patches.
with FakeTensorMode():
    pass
import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT/"artist_studio")]
    sys.modules[NAME] = package
package = sys.modules[NAME]
wan = importlib.import_module(NAME+".wan")
studio = importlib.import_module(NAME+".studio")
speech = importlib.import_module(NAME+".wan_speech")
coordinator = importlib.import_module(NAME+".wan_parts")
runtime = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_runtime")
parts = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_parts")
windows = importlib.import_module("ComfyUI_zura_nodes.wan_preparation_windows")
KEY = "d"*64


class PreparationGraphTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.review = self.root/"genj"/"reviews"/"shot_0123456789abcdef"
        self.review.mkdir(parents=True)
        original = self.root/"original.mp4"
        original.write_bytes(b"neutral original source identity")
        self.total = 120
        self.details = {"review_shot_id":self.review.name,"source":str(original),
            "source_hash":hashlib.sha256(original.read_bytes()).hexdigest(),"frames":self.total,
            "fps":24,"start":0.0,"duration":self.total/24,"width":2,"height":2}
        files = {}
        for name in ("source.mp4","mask.mp4"):
            path = self.review/name
            path.write_bytes(("neutral approved "+name).encode())
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.manifest = {"shot_id":self.review.name,"clip":dict(self.details),"files":files}
        (self.review/"review.json").write_text(json.dumps(self.manifest),encoding="utf-8")
        self.project = {"id":"a"*32,"review":self.review.name,"audio":{"file":"neutral.wav"},
            "opening_key":"approved","opening_approval":"approved","opening_input":{"file":"opening.png"},
            "character":{"file":"character.png"},"config":{"background":"keep","engine":"wan",
            "lip_sync":False,"resolution":1280,"scope":"person","audio_start":.25}}
        self.addCleanup(patch.stopall)
        patch.object(sys.modules["folder_paths"],"get_output_directory",return_value=str(self.root),create=True).start()
        patch.object(package,"verify_review",return_value=(self.review,self.manifest),create=True).start()
        patch.object(studio,"assert_approved").start()
        patch.object(studio,"check_asset").start()
        patch.object(wan,"cache_key",side_effect=lambda project:KEY).start()
        patch.object(parts,"_interrupt",lambda:None).start()
        self.reference = torch.full((1,2,2,3),.5)

    def cold(self, speech_enabled=False):
        self.project["config"]["lip_sync"] = speech_enabled
        with patch.object(speech,"load_guide",return_value={"path":"neutral-guide.mp4","guide_key":"b"*64,
                "sha":"c"*64,"key_data":{"source":{"frames":self.total}}}):
            with patch.object(coordinator,"prepare_next_part_graph",side_effect=lambda project,graph,key:graph):
                return wan.build_wan_graph(self.project)

    def test_render_cache_pins_accept_current_loader_and_reject_wrong_resolution(self):
        for name in ('render_audio_v3_3840_x1_120f', 'render_audio_v3_3840_x1_120f_aspect'):
            folder = self.review / name
            folder.mkdir()
            pins = {}
            for label in ('source', 'mask'):
                path = folder / (label + '.mp4')
                path.write_bytes(label.encode())
                stat = path.stat()
                pins[label] = {'path':str(path), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                               'size':stat.st_size, 'mtime_ns':stat.st_mtime_ns}
            runtime.validate_render_cache_pin(pins, self.root, self.review.name, self.total, render_long_edge=3840)
            with self.assertRaisesRegex(ValueError, 'another render resolution'):
                runtime.validate_render_cache_pin(pins, self.root, self.review.name, self.total, render_long_edge=1920)

    def next_graph(self, cold):
        return coordinator.prepare_next_part_graph(self.project,cold,KEY)

    def save(self, start, count, metadata):
        scope = "head" if metadata["replacement_area"] == "Whole head" else "person"
        speech_pins = metadata.get("speech_provenance",{})
        key, sha = speech_pins.get("guide_key",""),speech_pins.get("guide_sha","")
        body = torch.zeros(20,3,dtype=torch.float32).numpy()
        body_sha = hashlib.sha256(body.tobytes()).hexdigest()
        edge = self.project["config"]["resolution"]
        derived = self.review/f"render_audio_v2_{edge}_x1_{self.total}f"
        derived.mkdir(exist_ok=True)
        render_pin = {}
        for label in ("source","mask"):
            path = derived/(label+".mp4")
            if not path.exists():
                path.write_bytes(("neutral derived "+label).encode())
            stamp = path.stat()
            render_pin[label] = {"path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                                 "size":stamp.st_size,"mtime_ns":stamp.st_mtime_ns}
        details = {**self.details,"render_long_edge":edge,"selected_path":str(derived/"source.mp4")}
        pins = parts._identity_pins(self.root,details,self.reference,metadata,KEY,render_pin)
        previous = runtime.NONE_CARRY_SHA
        if start:
            directory = self.root/"genj"/"wan_preparation_parts"/KEY
            carry = json.loads((directory/f"carry_{start:08d}.json").read_text())
            previous = carry["receipt_sha256"]
        state = {"schema":parts.CARRY_SCHEMA,"cache_key":KEY,"start":start,"count":count,
            "total_frames":self.total,**{k:v for k,v in pins.items() if k != "cache_key"},
            "carry_in_kind":"none" if start == 0 else "body",
            "carry_in_sha256":runtime.NONE_CARRY_SHA if start == 0 else body_sha,
            "carry_out_sha256":body_sha,"carry_out_body":body.tolist(),"previous_receipt_sha256":previous}
        state["render_cache_pin"] = copy.deepcopy(render_pin)
        window = {"schema":parts.WINDOW_SCHEMA,"start":start,"count":count,"total_frames":self.total,
                  "fps":24,"width":2,"height":2,"mask_width":2,"mask_height":2,"render_cache_pin":render_pin}
        frames = torch.arange(start*12,(start+count)*12,dtype=torch.float32).reshape(count,2,2,3)/4096
        receipt = parts.save_preparation_part(frames,torch.ones(count,2,2),frames.clone(),frames.clone(),
            self.reference,window,state,details,KEY,scope,key,sha,output_root=self.root,interrupt=lambda:None)
        return self.root/"genj"/"wan_preparation_parts"/KEY/f"part_{start:08d}_{count:05d}.receipt.json", receipt

    def test_first_next_merge_progress_uses_native_nodes_and_actual_part_saver(self):
        cold = self.cold()
        frozen_project, frozen_graph = copy.deepcopy(self.project),copy.deepcopy(cold)
        first = self.next_graph(cold)
        self.assertEqual(first["wan_frames"]["inputs"],{"source":["wan_shot",0],"mask_video":["wan_shot",1],
            "clip_details":["wan_shot",3],"start_frame":0,"frame_count":81})
        for name in ("wan_pose_detect","wan_block_mask","wan_pose_draw","wan_sam","wan_character_crop"):
            self.assertEqual(first[name]["class_type"],cold[name]["class_type"])
        self.assertEqual(first["wan_pose_detect"]["inputs"],cold["wan_pose_detect"]["inputs"])
        self.assertEqual(first["wan_pose_draw"]["inputs"]["pose_data"],["wan_pose_carry",0])
        self.assertEqual(first["wan_save"]["inputs"]["reference"],cold["wan_save"]["inputs"]["reference"])
        self.assertNotIn("wan_audio_selection",first)
        self.assertNotIn("wan_reference_audio",first)
        metadata = runtime.metadata_for_scope("person")
        self.save(0,81,metadata)
        second = self.next_graph(cold)
        self.assertEqual(second["wan_frames"]["inputs"]["start_frame"],81)
        self.assertEqual(second["wan_frames"]["inputs"]["frame_count"],39)
        self.save(81,39,metadata)
        graph = self.next_graph(cold)
        self.assertEqual(list(graph),["wan_save"])
        self.assertEqual(graph["wan_save"]["class_type"],"ZuraWanMergePreparation")
        model_management = types.ModuleType("comfy.model_management")
        model_management.throw_exception_if_processing_interrupted = lambda:None
        with patch.dict(sys.modules,{"comfy.model_management":model_management}):
            result = runtime.ZuraWanMergePreparation().merge(**graph["wan_save"]["inputs"])
        self.assertEqual(result["result"],(KEY,))
        reader = windows.WanPreparationWindows(self.root/"genj"/"wan_conditioning"/(KEY+".pt"),KEY,self.root)
        self.assertEqual(len(reader.arrays["frames"]),120)
        self.assertEqual(reader.arrays["frames"][80:83].numpy().tobytes(),
                         (torch.arange(80*12,83*12,dtype=torch.float32).reshape(3,2,2,3)/4096).numpy().tobytes())
        self.assertEqual(self.project,frozen_project)
        self.assertEqual(cold,frozen_graph)

    def test_1080_resolution_uses_41_frames_and_exact_remaining_length(self):
        self.project["config"]["resolution"] = 1920
        cold = self.cold()
        self.assertEqual(self.next_graph(cold)["wan_frames"]["inputs"]["frame_count"],41)
        self.save(0,41,runtime.metadata_for_scope("person"))
        second = self.next_graph(cold)
        self.assertEqual(second["wan_frames"]["inputs"]["start_frame"],41)
        self.assertEqual(second["wan_frames"]["inputs"]["frame_count"],41)
        self.save(41,41,runtime.metadata_for_scope("person"))
        self.assertEqual(self.next_graph(cold)["wan_frames"]["inputs"]["frame_count"],38)

    def test_public_cached_cold_builder_automatically_advances_parts_then_merge(self):
        first = wan.build_wan_graph(self.project)
        self.assertEqual(first["wan_save"]["class_type"],"ZuraWanSavePreparationPart")
        self.assertEqual(first["wan_frames"]["inputs"]["frame_count"],81)
        self.save(0,81,runtime.metadata_for_scope("person"))
        second = wan.build_wan_graph(self.project)
        self.assertEqual(second["wan_frames"]["inputs"]["start_frame"],81)
        self.assertEqual(second["wan_frames"]["inputs"]["frame_count"],39)
        self.save(81,39,runtime.metadata_for_scope("person"))
        last = wan.build_wan_graph(self.project)
        self.assertEqual(list(last),["wan_save"])
        self.assertEqual(last["wan_save"]["class_type"],"ZuraWanMergePreparation")

    def test_selected_speech_window_preserves_recipe_and_original_body_source(self):
        cold = self.cold(True)
        first = self.next_graph(cold)
        self.assertEqual(first["wan_speech_video"]["inputs"]["frame_load_cap"],81)
        metadata = runtime.metadata_for_scope("person","b"*64,"c"*64)
        self.assertEqual(metadata,parts._metadata("person","b"*64,"c"*64))
        self.save(0,81,metadata)
        second = self.next_graph(cold)
        video = second["wan_speech_video"]["inputs"]
        self.assertEqual(video["frame_load_cap"],39)
        self.assertEqual(video["start_time"],81/24)
        for field in ("video","force_rate","format","custom_width","custom_height"):
            self.assertEqual(video[field],cold["wan_speech_video"]["inputs"][field])
        self.assertEqual(second["wan_save"]["inputs"]["face"],["wan_speech_face_detect",1])
        self.assertEqual(second["wan_pose_carry"]["inputs"]["speech_guide_sha"],"c"*64)
        self.assertEqual(second["wan_frames"]["inputs"]["source"],["wan_shot",0])

    def test_progress_scan_does_not_read_large_tensor_parts(self):
        cold = self.cold()
        self.save(0,81,runtime.metadata_for_scope("person"))
        original_read = Path.read_bytes
        def bounded_read(path):
            if path.suffix == ".pt":
                raise AssertionError("UI coordinator must not hash or load tensor caches")
            return original_read(path)
        with patch.object(Path,"read_bytes",bounded_read):
            graph = self.next_graph(cold)
        self.assertEqual(graph["wan_frames"]["inputs"]["start_frame"],81)

    def test_worker_merge_rechecks_original_review_and_receipt_path_order(self):
        cold = self.cold()
        metadata = runtime.metadata_for_scope("person")
        self.save(0,81,metadata)
        self.save(81,39,metadata)
        inputs = self.next_graph(cold)["wan_save"]["inputs"]
        model_management = types.ModuleType("comfy.model_management")
        model_management.throw_exception_if_processing_interrupted = lambda:None
        with patch.dict(sys.modules,{"comfy.model_management":model_management}):
            swapped = {**inputs,"receipts_json":runtime.canonical(list(reversed(json.loads(inputs["receipts_json"]))))}
            with self.assertRaisesRegex(ValueError,"timeline"):
                runtime.ZuraWanMergePreparation().merge(**swapped)
            original = Path(self.details["source"])
            original.write_bytes(b"changed neutral original")
            with self.assertRaisesRegex(ValueError,"original Wan source changed"):
                runtime.ZuraWanMergePreparation().merge(**inputs)
        self.assertFalse((self.root/"genj"/"wan_conditioning"/(KEY+".pt")).exists())

    def test_orphan_part_receipt_or_checkpoint_is_recoverable_and_not_rewritten(self):
        for remove in ("receipt","part","carry"):
            with self.subTest(remove=remove):
                # Separate neutral timeline directories through new keys.
                key = hashlib.sha256(remove.encode()).hexdigest()
                with patch.dict(globals(),{"KEY":key}):
                    cold = self.cold()
                    receipt_path,value = self.save(0,81,runtime.metadata_for_scope("person"))
                    target = receipt_path if remove == "receipt" else (
                        Path(value["path"]) if remove == "part" else receipt_path.parent/"carry_00000081.json")
                    target.unlink()
                    before = {p.name:p.read_bytes() for p in receipt_path.parent.iterdir()}
                    with self.assertRaisesRegex(ValueError,"orphan|missing"):
                        self.next_graph(cold)
                    self.assertEqual(before,{p.name:p.read_bytes() for p in receipt_path.parent.iterdir()})

    def test_changed_source_review_metadata_carry_and_part_stamp_fail_before_next_job(self):
        cold = self.cold()
        receipt_path, _ = self.save(0,81,runtime.metadata_for_scope("person"))
        original = json.loads(receipt_path.read_text())
        changes = [lambda r:r["source_pin"].update(original_source_sha256="f"*64),
                   lambda r:r["review_pin"].update(mask_sha256="f"*64),
                   lambda r:r.update(footage_metadata_sha256="f"*64),
                   lambda r:r.update(carry_in_sha256="f"*64),
                   lambda r:r["render_cache_pin"]["source"].update(sha256="f"*64),
                   lambda r:r.update(size=r["size"]+1)]
        for change in changes:
            altered = copy.deepcopy(original)
            change(altered)
            receipt_path.write_text(runtime.canonical(altered))
            with self.assertRaises(ValueError):
                self.next_graph(cold)
        receipt_path.write_text(runtime.canonical(original))
        checkpoint = receipt_path.parent/"carry_00000081.json"
        state = json.loads(checkpoint.read_text())
        state["carry_body"][0][0] = .5
        checkpoint.write_text(runtime.canonical(state))
        with self.assertRaisesRegex(ValueError,"body digest|preceding receipt"):
            self.next_graph(cold)

    def test_small_json_namespace_and_unsupported_timeline_fail_closed(self):
        for text in ("[]"*runtime.MAX_JSON_BYTES,"{bad}",'{"a":1,"a":2}','{"a":NaN}'):
            with self.assertRaises(ValueError):
                runtime.parse_json(text)
        cold = self.cold()
        with self.assertRaisesRegex(ValueError,"Invalid"):
            runtime.digest_key("../escape")
        with self.assertRaisesRegex(ValueError,"different cache"):
            coordinator.prepare_next_part_graph(self.project,cold,"f"*64)
        self.manifest["clip"]["fps"] = 25
        with self.assertRaisesRegex(ValueError,"24-fps"):
            self.next_graph(cold)
        with tempfile.TemporaryDirectory() as outside:
            path = Path(outside)/"receipt.json"
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError,"outside"):
                runtime.read_json(path,self.root)

    def test_redirected_progress_and_aggregate_metadata_budget_are_refused(self):
        cold = self.cold()
        directory = self.root/"genj"/"wan_preparation_parts"/KEY
        directory.parent.mkdir(parents=True)
        with tempfile.TemporaryDirectory() as outside:
            try:
                directory.symlink_to(outside,target_is_directory=True)
            except OSError:
                self.skipTest("Platform cannot create a neutral directory symlink")
            with self.assertRaisesRegex(ValueError,"redirected"):
                self.next_graph(cold)
            self.assertEqual(list(Path(outside).iterdir()),[])
            directory.unlink()
        directory.mkdir()
        (directory/"part_00000000_00081.receipt.json").write_bytes(b"x"*(runtime.MAX_JSON_BYTES+1))
        with self.assertRaisesRegex(ValueError,"metadata budget"):
            self.next_graph(cold)


if __name__ == "__main__":
    unittest.main()
