"""Real encoded output, not requested settings, governs the HDR handoff."""
import asyncio
import copy
import importlib
import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import test_artist_studio as shared

jobs = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_jobs')
import folder_paths


class OutpaintDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.identity = 'a' * 32
        self.folder = self.root / 'genj' / 'outpaint'
        self.folder.mkdir(parents=True)
        self.path = self.folder / (self.identity + '_00001_.mp4')
        self.job = {'id': self.identity, 'kind': 'render', 'state': 'complete',
            'source': {'file': 'source.mp4'}, 'pad_delivery': True,
            'selection': {'width': 128, 'height': 128, 'frames': 6},
            'artifact': {'type': 'output', 'subfolder': 'genj/outpaint', 'filename': self.path.name}}
        self.generate()
        for target, name, value in ((folder_paths, 'get_output_directory', str(self.root)),
                                     (jobs, 'check_asset', self.path)):
            p = patch.object(target, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def generate(self, frames=9, width=128, audio=True):
        args = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c=blue:s={width}x128:r=24']
        if audio:
            args += ['-f', 'lavfi', '-i', 'sine=frequency=997:sample_rate=48000:duration=1']
        args += ['-frames:v', str(frames), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(self.path)]
        subprocess.run(args, check=True, capture_output=True)

    def test_inspects_padded_output_and_audio_from_actual_file(self):
        result = jobs.inspect_sdr_delivery(self.job)
        self.assertEqual(result['artifact'], self.job['artifact'])
        self.assertEqual(result['output_raster'], {'width': 128, 'height': 128,
                         'frames': 9, 'fps': 24, 'has_audio': True})
        controller = jobs.OutpaintJobs(types.SimpleNamespace())
        controller.jobs[self.identity] = self.job
        self.assertEqual(asyncio.run(controller.delivery(self.identity)), result)
        self.assertEqual(controller.public(self.job)['output_raster'], result['output_raster'])
        self.assertIs(controller.public(self.job)['hdr'], False)
        self.job['hdr_render'] = True
        self.assertIs(controller.public(self.job)['hdr'], True)

    def test_short_unpadded_and_long_padded_counts_are_distinct(self):
        self.job['pad_delivery'] = False
        self.generate(frames=6)
        self.assertEqual(jobs.inspect_sdr_delivery(self.job)['output_raster']['frames'], 6)
        self.job['long'] = True
        with self.assertRaisesRegex(ValueError, 'number of frames'):
            jobs.inspect_sdr_delivery(self.job)

    def test_windows_save_video_subfolder_is_accepted_without_changing_reference(self):
        self.job['artifact']['subfolder'] = 'genj\\outpaint'
        result = jobs.inspect_sdr_delivery(self.job)
        self.assertEqual(result['artifact'], self.job['artifact'])
        self.assertEqual(result['output_raster']['frames'], 9)

    def test_wrong_raster_and_short_video_are_rejected(self):
        self.generate(width=192)
        with self.assertRaisesRegex(ValueError, 'width'):
            jobs.inspect_sdr_delivery(self.job)
        self.generate(frames=8)
        with self.assertRaisesRegex(ValueError, 'number of frames'):
            jobs.inspect_sdr_delivery(self.job)

    def test_missing_original_audio_is_not_silently_accepted(self):
        self.generate(audio=False)
        with patch.object(jobs, 'source_has_audio', return_value=True):
            with self.assertRaisesRegex(ValueError, 'soundtrack'):
                jobs.inspect_sdr_delivery(self.job)
        self.assertFalse(jobs.inspect_sdr_delivery(self.job)['output_raster']['has_audio'])

    def test_overlays_native_hdr_and_unsafe_paths_are_never_conversion_sources(self):
        for changes in ({'kind': 'review'}, {'state': 'running'}, {'hdr_render': True},
                        {'hdr_review_key': 'review'}, {'hdr_files': {'hlg': 'master'}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                jobs.inspect_sdr_delivery({**self.job, **changes})
        for name in ('../escape.mp4', '..\\escape.mp4', 'foreign_00001_.mp4'):
            job = copy.deepcopy(self.job)
            job['artifact']['filename'] = name
            with self.subTest(name=name), self.assertRaises(ValueError):
                jobs.inspect_sdr_delivery(job)


if __name__ == '__main__':
    unittest.main()
