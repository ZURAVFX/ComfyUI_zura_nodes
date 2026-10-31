import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import test_artist_studio

artifacts = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_outpaint_artifacts')


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'genj' / 'hdr'
        self.folder.mkdir(parents=True)
        self.hlg = self.folder / 'hdr_outpaint_abc_00001_.mp4'
        self.preview = self.folder / 'hdr_outpaint_abc_preview_00001_.mp4'
        self.zip = self.folder / 'hdr_outpaint_abc.zip'
        self.hlg.write_bytes(b'video')
        self.preview.write_bytes(b'video')
        with zipfile.ZipFile(self.zip, 'w') as z:
            for i in range(9): z.writestr(f'frame_{i:05d}.exr', b'frame')
        def ref(path): return {'type': 'output', 'subfolder': 'genj/hdr', 'filename': path.name}
        self.outputs = {'zura_hdr_save_video': {'images': [ref(self.hlg)]},
                        'zura_hdr_save_preview': {'images': [ref(self.preview)]},
                        'zura_hdr_archive': {'files': [ref(self.zip)]}}
        self.metadata = {'streams': [{'pix_fmt': 'yuv420p10le', 'color_transfer': 'arib-std-b67',
                                     'color_space': 'bt2020nc', 'color_primaries': 'bt2020'}]}
        self.video = patch.object(artifacts, 'inspect_video').start()
        self.probe = patch.object(artifacts.shutil, 'which', return_value='ffprobe').start()
        self.run = patch.object(artifacts.subprocess, 'run').start()
        self.run.return_value.stdout = json.dumps(self.metadata)

    def tearDown(self):
        patch.stopall()
        self.tmp.cleanup()

    def checked(self):
        return artifacts.checked_delivery(self.root, self.outputs, 'abc', width=192, height=128, frames=9, has_audio=True)

    def test_validates_all_owned_deliverables_and_audio(self):
        result = self.checked()
        self.assertEqual(result['hlg'], self.hlg)
        self.assertEqual(self.video.call_count, 2)
        self.assertTrue(all(call.kwargs['expected_audio_tracks'] == 1 for call in self.video.call_args_list))

    def test_rejects_different_job_and_unexpected_path(self):
        self.outputs['zura_hdr_save_video']['images'][0]['filename'] = '../hdr_outpaint_abc_00001_.mp4'
        with self.assertRaisesRegex(ValueError, 'unexpected output path'): self.checked()

    def test_rejects_sdr_or_missing_exr(self):
        self.metadata['streams'][0]['color_transfer'] = 'bt709'
        self.run.return_value.stdout = json.dumps(self.metadata)
        with self.assertRaisesRegex(ValueError, 'HLG'): self.checked()
        self.metadata['streams'][0]['color_transfer'] = 'arib-std-b67'
        self.run.return_value.stdout = json.dumps(self.metadata)
        with zipfile.ZipFile(self.zip, 'w') as z: z.writestr('frame_00000.exr', b'frame')
        with self.assertRaisesRegex(ValueError, 'unexpected frame sequence'): self.checked()

    def test_long_delivery_checks_identity_and_media(self):
        hlg = self.folder / 'hdr_outpaint_abc.mp4'
        preview = self.folder / 'hdr_outpaint_abc_preview.mp4'
        self.hlg.rename(hlg); self.preview.rename(preview)
        result = {'files': [str(self.zip), str(hlg)], 'preview': str(preview)}
        checked = artifacts.checked_long_delivery(self.root, result, 'abc', width=192, height=128, frames=9, has_audio=True)
        self.assertEqual(checked['hlg'], hlg)
        self.assertEqual(self.video.call_count, 2)
        with self.assertRaisesRegex(ValueError, 'unexpected output path'):
            artifacts.checked_long_delivery(self.root, result, 'another', width=192, height=128, frames=9, has_audio=True)
        with zipfile.ZipFile(self.zip, 'w') as z: z.writestr('frame_00000.exr', b'frame')
        with self.assertRaisesRegex(ValueError, 'unexpected frame sequence'):
            artifacts.checked_long_delivery(self.root, result, 'abc', width=192, height=128, frames=9, has_audio=True)

    def test_rejects_wrong_stage_identity(self):
        folder = self.root / 'genj' / 'hdr_outpaint'
        folder.mkdir()
        (folder / 'other_00001_.mp4').write_bytes(b'video')
        ref = {'type': 'output', 'subfolder': 'genj/hdr_outpaint', 'filename': 'other_00001_.mp4'}
        with self.assertRaisesRegex(ValueError, 'unexpected output path'):
            artifacts.checked_stage(self.root, ref, 'abc', width=192, height=128, frames=9)
