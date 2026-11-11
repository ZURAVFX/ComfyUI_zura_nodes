"""Request-to-graph-to-real-EXR precision regression without model execution."""
import importlib, sys, tempfile, types, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
import v2_bootstrap
for name, path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'), ('ComfyUI_zura_nodes.paintout','paintout')]:
    mod=types.ModuleType(name); mod.__path__=[str(v2_bootstrap.ROOT/path)]; sys.modules[name]=mod
native=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_native_studio')
paint=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
package=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_package')
result=importlib.import_module('ComfyUI_zura_nodes.artist_studio.ltx25_hdr_result')
import torch, OpenImageIO as oiio

class PrecisionTests(unittest.TestCase):
    def test_hashed_native_plan_binds_storage(self):
        from test_ltx25_hdr_plan import HDRPerformanceTests, hdr
        project, kwargs = HDRPerformanceTests().config()
        half=hdr.build_native_hdr_plan(project, **kwargs)
        full=hdr.build_native_hdr_plan(project, exr_storage='float32', **kwargs)
        self.assertNotEqual(half['key'],full['key'])
        self.assertEqual(full['basis']['native_hdr']['exr_storage'],'float32')
        self.assertEqual(full['phases']['decode']['zura_hdr_archive']['inputs']['exr_storage'],'float32')
        self.assertFalse(full['phases']['decode']['zura_hdr_exr']['inputs']['half_precision'])
        self.assertEqual(full['hdr_delivery']['exr_storage'],'float32')
        with self.assertRaises(ValueError): hdr.build_native_hdr_plan(project, exr_storage='wrong', **kwargs)

    def test_request_graph_and_real_writer(self):
        info={'kind':'video','count':25,'width':384,'height':224,'fps':24,'transfer':'arib-std-b67'}
        fake=types.SimpleNamespace(streams=types.SimpleNamespace(audio=[]))
        with tempfile.TemporaryDirectory() as root, patch.object(paint,'describe',return_value=info), patch.object(paint,'selected_space',return_value='hlg_rec2020'), patch('av.open') as opened:
            opened.return_value.__enter__.return_value=fake
            for storage in ('half','float32'):
                request={'start_frame':0,'frame_count':1, 'exr_storage':storage}
                graph,details=native.build_asset_graph({'asset_kind':'video'},request,lambda _: 'source.mp4')
                self.assertEqual(details['exr_storage'],storage)
                self.assertEqual(graph['zura_hdr_exr']['inputs']['half_precision'],storage=='half')
                writer=graph['zura_hdr_archive']['inputs']
                self.assertEqual(writer.get('exr_storage','half'),storage)
                folders=types.SimpleNamespace(get_output_directory=lambda:root)
                rgb=torch.tensor([[[[-.003,.180123,2.12345]]]])
                with patch.dict(sys.modules,{'folder_paths':folders}):
                    archive=package.ZuraHDRPackageACEScct().package(paint.encode_ct(rgb), writer['prefix'], writer.get('exr_storage','half'))['result'][0]
                result._check_archive(archive,1,1,1,exr_storage=storage)
                with self.assertRaises(ValueError): result._check_archive(archive,1,1,1,exr_storage='float32' if storage=='half' else 'half')
                with zipfile.ZipFile(archive) as z: Path(root,'read.exr').write_bytes(z.read('frame_00000.exr'))
                image=oiio.ImageInput.open(str(Path(root,'read.exr')))
                try:
                    self.assertEqual(image.spec().format, oiio.HALF if storage=='half' else oiio.FLOAT)
                    values=image.read_image()[0,0]
                    self.assertAlmostEqual(float(values[1]), .180123, places=3 if storage=='half' else 6)
                    self.assertAlmostEqual(float(values[2]), 2.12345, places=2 if storage=='half' else 5)
                    self.assertLess(float(values[0]),0)
                finally: image.close()
            with self.assertRaises(ValueError): native.build_asset_graph({'asset_kind':'video'},{'frame_count':1,'exr_storage':'bad'},lambda _: 'source.mp4')

if __name__ == '__main__': unittest.main()
