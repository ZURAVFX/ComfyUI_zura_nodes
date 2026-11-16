import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('native_hdr_paintout',Path(__file__).parents[1]/'artist_studio'/'native_hdr_paintout.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)


class NativeHDRPaintoutTests(unittest.TestCase):
    def test_sequence_keeps_native_colour_and_requested_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'hdr_sequence.json';path.write_text(json.dumps({'frames':[{'name':'000001.exr'},{'name':'000002.exr'}]}))
            (path.parent/'frames').mkdir()
            for name in ['000001.exr','000002.exr']:(path.parent/'frames'/name).write_bytes(b'EXR fixture')
            asset={'asset_kind':'hdr_sequence','count':2,'nativeInputColour':{'encoding':'scene_linear_rec709','sceneLinear':True}}
            seen=[]
            def describe(source):seen.append(source);return {'path':source,'width':512,'height':320,'frames':2,'fps':24}
            result=native.native_paintout_source_info(asset,lambda _:path,describe,fps=30000/1001)
            self.assertEqual(seen,[str(path.parent/'frames')]);self.assertEqual(result['resolved_colour'],'linear_rec709');self.assertAlmostEqual(result['fps'],30000/1001)
            self.assertEqual(result['nativeInputColour'],asset['nativeInputColour']);self.assertEqual(result['frames'],2)
            with self.assertRaisesRegex(ValueError,'frame rate'):
                native.native_paintout_source_info(asset,lambda _:path,describe,fps=float('nan'))
            with self.assertRaisesRegex(ValueError,'colour space'):
                native.native_paintout_source_info(asset,lambda _:path,describe,colour_space='srgb_display')

    def test_sdr_assets_cannot_enter_native_exr_route(self):
        with self.assertRaisesRegex(ValueError,'EXR sequence'):
            native.native_paintout_source_info({'asset_kind':'video'},None,None)


if __name__=='__main__':unittest.main()
