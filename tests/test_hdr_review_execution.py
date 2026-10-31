"""CPU execution of the experimental HDR review using installed Comfy nodes."""
import importlib
import subprocess
import sys
import tempfile
import types
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import av
import v2_bootstrap

for name, folder in [('ComfyUI_zura_nodes.artist_studio', 'artist_studio'),
                     ('ComfyUI_zura_nodes.paintout', 'paintout')]:
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(v2_bootstrap.ROOT / folder)]
        sys.modules[name] = package
native = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_source')
canvas = importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx_outpaint')
outpaint = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')
exact = importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_exact_video')


class HDRReviewExecutionTests(unittest.TestCase):
    def test_review_saves_selected_tone_mapped_mask_at_exact_output_rate(self):
        import folder_paths
        root = Path(getattr(folder_paths, 'base_path', ''))
        ltx = root / 'custom_nodes' / 'ComfyUI-LTXVideo'
        if not (ltx / 'hdr_nodes.py').exists():
            self.skipTest('Requires installed ComfyUI-LTXVideo')
        name = 'zura_test_ltx_hdr'
        pkg = types.ModuleType(name); pkg.__path__ = [str(ltx)]; sys.modules[name] = pkg
        hdr = importlib.import_module(name + '.hdr_nodes')
        from comfy_extras.nodes_video import CreateVideo
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / 'source.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                            'testsrc2=s=96x64:r=60', '-frames:v', '90', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p10le', str(video)], check=True)
            images, fps = native.ZuraHDRSelectNativeTimeline().load(str(video), .5, 9, 24., 'hlg_rec2020', 24.)
            guide, mask = canvas.ZuraLTXOutpaintHDRCanvas().prepare(images, 'expand', 192, 128, 48, 32, 48, 32)
            preview, _ = hdr.LTXVHDRDecodePostprocess().postprocess(guide, transfer='acescct', save_exr=False)
            overlay, = outpaint.ZuraOutpaintReviewOverlay().make(preview, mask)
            self.assertEqual(tuple(overlay.shape), (9, 128, 192, 3))
            assembled = CreateVideo.execute(overlay, fps)[0]
            with patch.object(folder_paths, 'get_output_directory', return_value=tmp), \
                 patch.object(folder_paths, 'get_save_image_path', return_value=(tmp, 'review', 1, '', 'review')):
                saved = exact.ZuraHDRSaveExactRate().save(assembled, 'review', fps)
            path = Path(tmp) / saved['ui']['images'][0]['filename']
            with av.open(str(path)) as container:
                stream = container.streams.video[0]
                self.assertEqual(stream.average_rate, Fraction(24, 1))
                self.assertEqual((stream.width, stream.height), (192, 128))
                self.assertEqual(len(list(container.decode(video=0))), 9)


if __name__ == '__main__':
    unittest.main()
