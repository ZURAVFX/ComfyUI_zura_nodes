import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("hdr_delivery", Path(__file__).resolve().parents[1] / "artist_studio" / "hdr_delivery.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ltx_hdr_delivery = module.ltx_hdr_delivery
ltx25_sdr_to_hdr_graph = module.ltx25_sdr_to_hdr_graph


class HDRDeliveryTest(unittest.TestCase):
    def test_high_fps_is_not_silently_clamped(self):
        graph = module.ltx25_sdr_to_hdr_dynamic_graph(['source',0],fps=59.94,
            model='model.safetensors',video_vae='video.safetensors',audio_vae='audio.safetensors',
            output='hlg_video',prefix='highfps',audio=['audio',0])
        self.assertEqual(graph['hdr_condition']['inputs']['frame_rate'],59.94)
        self.assertEqual(graph['hdr_empty_audio']['inputs']['frame_rate'],59.94)
        self.assertEqual(graph['zura_hdr_trim_audio']['inputs']['fps'],59.94)
        self.assertEqual(graph['zura_hdr_video']['inputs']['fps'],59.94)
    def test_dynamic_graph_trims_model_padding_and_preserves_audio(self):
        graph = module.ltx25_sdr_to_hdr_dynamic_graph(['source', 0],fps=24,
                model='model.safetensors',video_vae='video.safetensors',audio_vae='audio.safetensors',
                output='hlg_and_exr',prefix='run2',audio=['audio',0])
        self.assertEqual(graph['zura_hdr_prepare']['inputs']['images'], ['source',0])
        self.assertEqual(graph['hdr_empty_video']['inputs']['width'], ['zura_hdr_prepare',4])
        self.assertEqual(graph['hdr_empty_video']['inputs']['length'], ['zura_hdr_prepare',6])
        self.assertEqual(graph['hdr_unpad_frames']['inputs']['length'], ['zura_hdr_prepare',3])
        self.assertEqual(graph['hdr_unpad_raster']['inputs']['width'], ['zura_hdr_prepare',1])
        self.assertEqual(graph['zura_hdr_video']['inputs']['audio'], ['zura_hdr_trim_audio',0])
        self.assertEqual(graph['zura_hdr_trim_audio']['inputs']['audio'], ['audio',0])
        self.assertEqual(graph['zura_hdr_trim_audio']['inputs']['frames'], ['zura_hdr_prepare',3])
    def test_combined_output_preserves_working_space_audio_and_bit_depth(self):
        graph = ltx_hdr_delivery(["decode", 0], 24, output="hlg_and_exr", prefix="shot_1",
                                 working_space="ltx25_acescct_qualified", audio=["audio", 0])
        self.assertEqual(graph["zura_hdr_hlg"]["inputs"],
                         {"image": ["decode", 0], "source": "HDR ACEScct", "destination": "HDR"})
        self.assertEqual(graph["zura_hdr_video"]["inputs"]["bit_depth"], 10)
        self.assertEqual(graph["zura_hdr_video"]["inputs"]["audio"], ["audio", 0])
        self.assertEqual(graph["zura_hdr_exr"]["inputs"]["exr_color_space"], "acescg")
        self.assertFalse(graph["zura_hdr_exr"]["inputs"]["save_exr"])

    def test_rejects_unqualified_source_and_unsafe_output_paths(self):
        with self.assertRaises(ValueError):
            ltx_hdr_delivery(["decode", 0], 24, output="hlg_video", prefix="shot",
                             working_space="srgb")
        with self.assertRaises(ValueError):
            ltx_hdr_delivery(["decode", 0], 24, output="acescg_exr", prefix="../shot",
                             working_space="ltx25_acescct_qualified")

    def test_individual_output_does_not_create_the_other(self):
        graph = ltx_hdr_delivery(["decode", 0], 25, output="acescg_exr", prefix="shot",
                                 working_space="ltx25_acescct_qualified")
        self.assertEqual(set(graph), {"zura_hdr_exr"})

    def test_sdr_hdr_guide_flows_through_lora_float_vae_sampling_and_delivery(self):
        args = dict(width=640, height=384, frames=25, fps=24, model="model.safetensors",
                    video_vae="video.safetensors", audio_vae="audio.safetensors", output="hlg_and_exr", prefix="run1")
        g = ltx25_sdr_to_hdr_graph(["source", 0], **args)
        self.assertEqual(g["hdr_guide_input"]["inputs"]["destination"], "HDR ACEScct")
        self.assertEqual(g["hdr_guide"]["inputs"]["image"], ["hdr_guide_input", 0])
        self.assertEqual(g["hdr_guide"]["inputs"]["latent_downscale_factor"], ["hdr_lora", 1])
        self.assertEqual(g["hdr_decode"]["inputs"]["vae"], ["hdr_vae", 0])
        self.assertEqual(g["hdr_unpad_frames"]["inputs"]["image"], ["hdr_decode", 0])
        self.assertEqual(g["zura_hdr_exr"]["inputs"]["image"], ["hdr_unpad_raster", 0])
        self.assertEqual(g["hdr_condition"]["inputs"]["negative"], ["hdr_conditioning", 0])
        with self.assertRaises(ValueError):
            ltx25_sdr_to_hdr_graph(["source", 0], **{**args, "frames": 24})
        with self.assertRaises(ValueError):
            ltx25_sdr_to_hdr_graph(["source", 0], **{**args, "delivered_frames": 26})


if __name__ == "__main__":
    unittest.main()
