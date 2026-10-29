"""Bounded HLG preflight rejects inputs we have not qualified."""
import importlib
import sys
import types
import unittest
import tempfile
import json
from pathlib import Path
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

    def test_pq_uses_native_route_and_rejects_wrong_override(self):
        info={'kind':'video','count':25,'width':384,'height':224,'fps':24,'transfer':'smpte2084'}
        with patch.object(paintout,'describe',return_value=info),self.assertRaisesRegex(ValueError,'conflicts'):
            native.build_asset_graph({'asset_kind':'video'},{'frame_count':9,'colour_space':'hlg_rec2020'},lambda _: 'source.mp4')
        fake=types.SimpleNamespace(streams=types.SimpleNamespace(audio=[object()]))
        with patch.object(paintout,'describe',return_value=info),patch.object(paintout,'selected_space',return_value='pq_rec2020'),patch('av.open') as opened:
            opened.return_value.__enter__.return_value=fake
            graph,details=native.build_asset_graph({'asset_kind':'video'},{'frame_count':9,'colour_space':'pq_rec2020'},lambda _: 'source.mp4')
        self.assertEqual(graph['source']['inputs']['colour_space'],'pq_rec2020')
        self.assertEqual(details['frames'],9)

    def test_exr_sequence_is_verified_and_uses_supplied_frame_rate(self):
        sequence=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_sequence')
        info={'kind':'sequence','count':25,'width':384,'height':224,'files':['a.exr']*25}
        asset={'asset_kind':'hdr_sequence','sha':'abc'}
        with patch.object(sequence,'validate_manifest',return_value=('/input/frames',[])) as verify, \
             patch.object(paintout,'describe',return_value=info),patch.object(paintout,'selected_space',return_value='acescg'):
            graph,details=native.build_asset_graph(asset,{'start_frame':2,'frame_count':9,'sequence_fps':25,'colour_space':'acescg'},lambda _: '/input/hdr_sequence.json')
        verify.assert_called_once_with('/input/hdr_sequence.json','abc',2,9)
        self.assertEqual(graph['source']['inputs']['manifest_sha'],'abc')
        self.assertEqual(graph['source']['inputs']['sequence_fps'],25)
        self.assertNotIn('native_audio',graph)
        self.assertEqual(details['fps'],25)

    def test_sdr_refused_even_when_overridden(self):
        info={'kind':'video','count':25,'width':384,'height':224,'fps':24,'transfer':'bt709'}
        with patch.object(paintout,'describe',return_value=info),self.assertRaisesRegex(ValueError,'SDR'):
            native.build_asset_graph({'asset_kind':'video'},{'frame_count':9,'colour_space':'hlg_rec2020'},lambda _: 'source.mp4')

    def test_exr_manifest_detects_changed_frames_and_extra_files(self):
        sequence=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_sequence')
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);frames=root/'genj_studio'/'test'/'frames';frames.mkdir(parents=True)
            frame=frames/'frame_001.exr';frame.write_bytes(b'original')
            manifest=frames.parent/'hdr_sequence.json'
            manifest.write_text(json.dumps({'frames':[{'name':frame.name,'sha256':sequence._sha(frame)}]}))
            digest=sequence._sha(manifest)
            with patch('folder_paths.get_input_directory',return_value=str(root)):
                sequence.validate_manifest(manifest,digest,0,1)
                frame.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'changed'):sequence.validate_manifest(manifest,digest,0,1)
                frame.write_bytes(b'original');(frames/'extra.png').write_bytes(b'extra')
                with self.assertRaisesRegex(ValueError,'changed'):sequence.validate_manifest(manifest,digest,0,1)


if __name__=='__main__': unittest.main()
