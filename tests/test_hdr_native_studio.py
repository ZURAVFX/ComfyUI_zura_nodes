"""Bounded HLG preflight rejects inputs we have not qualified."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
native=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_studio')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class NativeStudioTests(unittest.TestCase):
    def test_hlg_range_builds_exact_video_and_audio(self):
        info={'kind':'video','count':25,'width':384,'height':224,'fps':24,'transfer':'arib-std-b67'}
        fake=types.SimpleNamespace(streams=types.SimpleNamespace(audio=[object()]))
        with patch.object(paintout,'describe',return_value=info),patch.object(paintout,'selected_space',return_value='hlg_rec2020'),patch('av.open') as opened:
            opened.return_value.__enter__.return_value=fake
            graph,details=native.build_asset_graph({'asset_kind':'video'},{'start_frame':5,'frame_count':9},lambda _: 'source.mp4')
        self.assertEqual((details['frames'],details['width'],details['height']),(9,384,224))
        self.assertEqual(graph['native_audio']['inputs']['start_frame'],5)
        self.assertEqual(graph['trim_raster']['inputs']['width'],384)
        self.assertEqual(graph['zura_hdr_video']['inputs']['audio'],['native_audio',0])

    def test_pq_and_sdr_refused_even_when_overridden(self):
        info={'kind':'video','count':25,'width':384,'height':224,'fps':24,'transfer':'smpte2084'}
        with patch.object(paintout,'describe',return_value=info),self.assertRaisesRegex(ValueError,'PQ'):
            native.build_asset_graph({'asset_kind':'video'},{'frame_count':9,'colour_space':'hlg_rec2020'},lambda _: 'source.mp4')
        info['transfer']='bt709'
        with patch.object(paintout,'describe',return_value=info),self.assertRaisesRegex(ValueError,'SDR'):
            native.build_asset_graph({'asset_kind':'video'},{'frame_count':9,'colour_space':'hlg_rec2020'},lambda _: 'source.mp4')


if __name__=='__main__': unittest.main()
