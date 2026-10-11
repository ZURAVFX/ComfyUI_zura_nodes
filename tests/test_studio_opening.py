import hashlib
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

from PIL import Image

import v2_bootstrap

NAME = "ComfyUI_zura_nodes.artist_studio"
if NAME not in sys.modules:
    package = types.ModuleType(NAME)
    package.__path__ = [str(v2_bootstrap.ROOT / "artist_studio")]
    sys.modules[NAME] = package
opening = importlib.import_module(NAME + ".opening")


class StartingImageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.input_root = Path(self.temporary.name)
        self.asset_root = self.input_root / "genj_studio"
        self.upload_path = self.asset_root / ("b" * 32) / "reference.png"
        self.upload_path.parent.mkdir(parents=True)
        Image.new("RGB", (8, 6), (82, 123, 201)).save(self.upload_path)
        self.upload_sha = self.sha(self.upload_path)
        self.uploaded = {
            "id": "b" * 32,
            "kind": "asset",
            "asset_kind": "image",
            "file": self.upload_path.relative_to(self.input_root).as_posix(),
            "sha": self.upload_sha,
            "name": "reference.png",
        }
        self.project = {
            "id": "a" * 32,
            "kind": "project",
            "source": {"id": "c" * 32, "sha": "source-sha", "file": "source.mp4"},
            "character": {"id": "d" * 32, "sha": "character-sha", "file": "character.png"},
            "audio": {"id": "e" * 32, "sha": "audio-sha", "file": "audio.wav"},
            "config": {"engine": "h3", "prompt": "Keep the approved look"},
            "review": "shot_0123456789abcdef",
            "approval": "approved-source-key",
            "opening_input": {"file": "genj_studio/old/opening.png", "sha": "old"},
            "opening_key": "old",
            "opening_url": "/old-opening",
            "opening_approval": "old",
            "phase": "approved",
            "actions": [{"id": "action-history", "state": "complete"}],
            "results": [{"stage": "h3", "sha256": "prior-result"}],
            "ltx25_run": {"stale": True},
            "draft_task": "stale-draft",
            "accepted_draft": "stale-accepted",
        }
        self.originals = {key: self.project[key] for key in ("source", "character", "audio", "config", "review", "approval", "actions", "results")}

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def check_asset(self, asset):
        path = (self.input_root / asset["file"]).resolve(strict=True)
        if not path.is_relative_to(self.asset_root.resolve()) or self.sha(path) != asset["sha"]:
            raise ValueError("An uploaded reference has changed or is outside Studio storage.")
        return path

    @staticmethod
    def assert_approved(project):
        if project.get("approval") != "approved-source-key" or project.get("review") != "shot_0123456789abcdef":
            raise ValueError("Check the mask preview and choose Use this mask first.")

    @staticmethod
    def media_url(asset):
        return f"/view?filename={asset['filename']}&subfolder={asset['subfolder']}&type={asset['type']}"

    def bind(self, project=None, uploaded=None, *, assert_approved=None, check_asset=None):
        return opening.bind_uploaded_opening(
            project or self.project,
            uploaded or self.uploaded,
            self.input_root,
            assert_approved=assert_approved or self.assert_approved,
            check_asset=check_asset or self.check_asset,
            media_url=self.media_url,
        )

    def test_copies_exact_uploaded_bytes_resets_approval_and_preserves_project_inputs(self):
        self.assertTrue(self.bind())
        expected_relative = f"genj_studio/{self.project['id']}/opening_uploaded_{self.upload_sha}.png"
        destination = self.input_root / expected_relative
        self.assertEqual(destination.read_bytes(), self.upload_path.read_bytes())
        self.assertEqual(self.project["opening_input"], {"file": expected_relative, "sha": self.upload_sha})
        self.assertEqual(self.project["opening_key"], self.upload_sha)
        self.assertIsNone(self.project["opening_approval"])
        self.assertEqual(self.project["phase"], "opening")
        self.assertEqual(self.project["opening_url"], f"/view?filename={destination.name}&subfolder=genj_studio/{self.project['id']}&type=input")
        self.assertNotIn("ltx25_run", self.project)
        self.assertIsNone(self.project["draft_task"])
        self.assertIsNone(self.project["accepted_draft"])
        for key, value in self.originals.items():
            self.assertEqual(self.project[key], value)

    def test_identical_upload_is_idempotent_and_does_not_revoke_existing_animate_approval(self):
        self.bind()
        self.project["opening_approval"] = self.upload_sha
        self.assertFalse(self.bind())
        self.assertEqual(self.project["opening_approval"], self.upload_sha)
        destination = self.input_root / self.project["opening_input"]["file"]
        self.assertEqual(self.sha(destination), self.upload_sha)

    def test_stale_review_or_approval_is_rejected(self):
        project = dict(self.project, approval=None)
        with self.assertRaisesRegex(ValueError, "Use this mask"):
            self.bind(project=project)
        self.assertFalse((self.input_root / "genj_studio" / project["id"]).exists())

    def test_changed_uploaded_bytes_are_rejected(self):
        self.upload_path.write_bytes(self.upload_path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.bind()
        self.assertFalse((self.input_root / "genj_studio" / self.project["id"]).exists())

    def test_active_action_rejects_without_review_or_file_mutation(self):
        project = dict(self.project, phase="working", actions=[{"state": "running"}])
        def must_not_check(_project):
            self.fail("Review approval should not be inspected while an action is active.")
        with self.assertRaisesRegex(ValueError, "current job"):
            self.bind(project=project, assert_approved=must_not_check)
        self.assertFalse((self.input_root / "genj_studio" / project["id"]).exists())

    def test_outside_upload_path_is_rejected_even_if_checker_returns_it(self):
        outside = self.input_root.parent / "outside.png"
        outside.write_bytes(self.upload_path.read_bytes())
        with self.assertRaisesRegex(ValueError, "outside Studio storage"):
            self.bind(check_asset=lambda _asset: outside)
        self.assertFalse((self.input_root / "genj_studio" / self.project["id"]).exists())
        outside.unlink(missing_ok=True)

    def test_non_image_asset_is_rejected(self):
        audio = dict(self.uploaded, asset_kind="audio")
        with self.assertRaisesRegex(ValueError, "uploaded image"):
            self.bind(uploaded=audio)


if __name__ == "__main__":
    unittest.main()
