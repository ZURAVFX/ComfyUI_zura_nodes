import importlib.util
import base64
from io import BytesIO
from pathlib import Path
from queue import Queue
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('live_preview',Path(__file__).resolve().parents[1]/'artist_studio/live_preview.py')
preview=importlib.util.module_from_spec(spec);spec.loader.exec_module(preview)

class LivePreviewTests(unittest.TestCase):
    def test_h3_uses_temporal_tae_only_when_exact_supported_decoder_exists(self):
        self.assertEqual(preview.preview_method({},'h3',['taeh3.safetensors']),'taesd')
        self.assertEqual(preview.preview_method({},'h3',['taeh3_2d_kijai.safetensors']),'auto')
        self.assertEqual(preview.preview_method({},'h3',[]),'auto')
    def test_wan_14b_and_relight_use_the_21_vae_family(self):
        for stage in ('wan','wan2','wan21_relight'):
            self.assertEqual(preview.preview_method({},stage,['lighttaew2_1.safetensors']),'taesd')
            self.assertEqual(preview.preview_method({},stage,['lighttaew2_2.safetensors']),'auto')
    def test_no_cross_family_tae_or_unsupported_ltx_core_override(self):
        for stage in ('design','prepare','background','restyle','h3_enhance'):
            self.assertEqual(preview.preview_method({},stage,['taeh3.safetensors','taeltx2_3.safetensors']),'auto')

    def test_motion_snapshot_spans_the_clip_and_respects_size_limits(self):
        import torch
        from PIL import Image

        latents = torch.linspace(-1, 1, 25).reshape(1, 1, 25, 1, 1).expand(1, 3, 25, 68, 120)
        sample, frames = preview._video_snapshot(latents, 3)
        self.assertEqual(frames, 25)
        self.assertEqual(tuple(sample.shape), (3, 8, 34, 60))
        self.assertEqual(sample[0, 0, 0, 0], -1)
        self.assertEqual(sample[0, -1, 0, 0], 1)
        self.assertIsNone(preview._video_snapshot(latents[:, :, :2], 3))
        webp = preview._encode_motion(sample, torch.eye(3).tolist(), None, 160)
        with Image.open(BytesIO(base64.b64decode(webp))) as image:
            self.assertEqual(image.n_frames, 8)
            self.assertEqual(image.size, (192, 109))
            self.assertLessEqual(max(image.getpixel((0, 0))), 3)
            image.seek(7)
            self.assertGreaterEqual(min(image.getpixel((0, 0))), 252)

    def test_only_studio_video_jobs_send_throttled_motion_to_their_client(self):
        import torch

        calls = []
        original = lambda *args, **kwargs: calls.append(args[0])
        comfy = SimpleNamespace(prepare_callback=lambda *args, **kwargs: original)
        context = SimpleNamespace(prompt_id="owned", node_id="sample")
        extra = {"client_id": "studio-browser"}
        queue = SimpleNamespace(get_current_queue_volatile=lambda: ([(0, "owned", {}, extra)], []))
        sent = Queue()
        server = SimpleNamespace(prompt_queue=queue, send_sync=lambda *args: sent.put(args))
        latent_format = SimpleNamespace(latent_dimensions=3, latent_rgb_factors=torch.eye(3).tolist())
        model = SimpleNamespace(model=SimpleNamespace(latent_format=latent_format))
        latents = torch.linspace(-1, 1, 4).reshape(1, 1, 4, 1, 1).expand(1, 3, 4, 2, 4)
        inline_worker = SimpleNamespace(submit=lambda fn, *args: fn(*args))
        with patch.object(preview, "ThreadPoolExecutor", return_value=inline_worker), patch.dict(sys.modules, {
            "latent_preview": comfy,
            "comfy_execution.utils": SimpleNamespace(get_executing_context=lambda: context),
        }):
            preview.register_motion_preview(server)
            self.assertIs(comfy.prepare_callback(model, 5), original)
            extra["zura_first_last"] = True
            sampler = comfy.prepare_callback(model, 5)
            with patch.object(preview, "monotonic", side_effect=(1, 2, 10, 20)):
                sampler(0, latents, None, 5)
                event, payload, client_id = sent.get(timeout=3)
                self.assertEqual((event, payload["prompt_id"], payload["node_id"], client_id),
                                 ("zura_motion_preview", "owned", "sample", "studio-browser"))
                sampler(1, latents, None, 5)
                self.assertTrue(sent.empty())
                sampler(2, latents, None, 5)
                self.assertEqual(sent.get(timeout=3)[1]["step"], 3)
                sampler(4, latents, None, 5)
                self.assertTrue(sent.empty())
            self.assertEqual(calls, [0, 1, 2, 4])

if __name__=='__main__':unittest.main()
