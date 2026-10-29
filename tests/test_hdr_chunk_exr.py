"""Streaming EXR output publishes only complete, uncancelled results."""
import importlib
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import torch
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
chunk=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
storage=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')
export=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_exr')
paintout=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class HDRChunkEXRTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.plan=[chunk.HDRChunk(4,9,0),chunk.HDRChunk(9,9,4)]
        self.stage=storage.HDRChunkStore(self.tmp.name,'a'*32,self.plan,1,1,create=True)
        values=paintout.encode_ct(torch.ones((14,1,1,3))*2)
        self.stage.write(0,values[:9]);self.stage.write(1,values[5:])

    @staticmethod
    def fake_exr(path, data, space, half):
        assert space=='acescg' and half
        Path(path).write_text(str(float(data[0,0,0])))

    def test_complete_zip_and_no_overwrite(self):
        with patch.object(paintout,'save_exr',side_effect=self.fake_exr):
            path=export.export_exr_zip(self.stage,self.tmp.name,'finished')
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(len(archive.namelist()),14)
                self.assertAlmostEqual(float(archive.read('frame_00013.exr')),2.,places=4)
            with self.assertRaisesRegex(ValueError,'already exists'):
                export.export_exr_zip(self.stage,self.tmp.name,'finished')

    def test_cancel_does_not_publish_partial_zip(self):
        def stop(first,total):
            if first==3:self.stage.cancel()
        with patch.object(paintout,'save_exr',side_effect=self.fake_exr):
            with self.assertRaises(storage.HDRChunkCancelled):
                export.export_exr_zip(self.stage,self.tmp.name,'cancelled',progress=stop)
        parent=Path(self.tmp.name)/'genj'/'hdr'
        self.assertEqual(list(parent.iterdir()),[])

    def test_real_exr_retains_linear_highlights(self):
        import OpenImageIO as oiio
        path=export.export_exr_zip(self.stage,self.tmp.name,'real')
        with zipfile.ZipFile(path) as archive:
            frame=Path(self.tmp.name)/'check.exr'
            frame.write_bytes(archive.read('frame_00013.exr'))
        image=oiio.ImageInput.open(str(frame))
        self.assertTrue(image)
        try:
            # OIIO may canonicalise the ACEScg tag to its AP1 scene-linear alias.
            self.assertIn(image.spec().get_string_attribute('oiio:ColorSpace'),('ACEScg','lin_ap1_scene'))
            self.assertAlmostEqual(float(image.read_image()[0,0,0]),2.,places=3)
        finally:image.close()


if __name__=='__main__':unittest.main()
