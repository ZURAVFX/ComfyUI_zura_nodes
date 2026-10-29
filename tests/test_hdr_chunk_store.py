"""Disk-backed HDR staging validates boundaries, corruption and cancellation."""
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

import torch
import v2_bootstrap

for name,path in [('ComfyUI_zura_nodes.artist_studio','artist_studio'),('ComfyUI_zura_nodes.paintout','paintout')]:
    if name not in sys.modules:
        module=types.ModuleType(name);module.__path__=[str(v2_bootstrap.ROOT/path)];sys.modules[name]=module
chunk=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunks')
store=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_chunk_store')
colour=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')


class HDRChunkStoreTests(unittest.TestCase):
    def test_staging_and_streaming_two_overlapping_chunks(self):
        plan=[chunk.HDRChunk(0,9,0),chunk.HDRChunk(5,9,4)]
        source=colour.encode_ct(torch.arange(14,dtype=torch.float32).reshape(14,1,1,1).expand(14,2,2,3)/10)
        with tempfile.TemporaryDirectory() as root:
            staged=store.HDRChunkStore(root,'a'*32,plan,2,2,create=True)
            staged.write(0,source[:9]);staged.write(1,source[5:])
            reopened=store.HDRChunkStore(root,'a'*32,plan,2,2)
            result=torch.cat(list(reopened.stitched()))
            self.assertEqual(len(result),14)
            self.assertTrue(torch.allclose(result,source,atol=1e-6))
            with self.assertRaisesRegex(ValueError,'already staged'):staged.write(0,source[:9])

    def test_corruption_and_invalid_job_rejected(self):
        plan=[chunk.HDRChunk(0,3,0)]
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):store.HDRChunkStore(root,'../escape',plan,1,1,create=True)
            staged=store.HDRChunkStore(root,'b'*32,plan,1,1,create=True)
            staged.write(0,torch.zeros(3,1,1,3))
            with (Path(root)/('b'*32)/'000000.npy').open('ab') as stream:stream.write(b'bad')
            with self.assertRaisesRegex(ValueError,'changed'):staged.read(0)

    def test_cancellation_stops_streaming_and_preserves_existing_chunks(self):
        plan=[chunk.HDRChunk(0,3,0)]
        with tempfile.TemporaryDirectory() as root:
            staged=store.HDRChunkStore(root,'c'*32,plan,1,1,create=True)
            staged.write(0,torch.zeros(3,1,1,3));staged.cancel()
            with self.assertRaises(store.HDRChunkCancelled):list(staged.stitched())
            self.assertTrue((Path(root)/('c'*32)/'000000.npy').is_file())

    def test_malformed_and_missing_chunks_rejected(self):
        plan=[chunk.HDRChunk(0,3,0)]
        with tempfile.TemporaryDirectory() as root:
            staged=store.HDRChunkStore(root,'d'*32,plan,1,1,create=True)
            with self.assertRaisesRegex(ValueError,'missing'):staged.read(0)
            with self.assertRaisesRegex(ValueError,'frame count'):staged.write(0,torch.zeros(2,1,1,3))
            with self.assertRaisesRegex(ValueError,'non-finite'):staged.write(0,torch.full((3,1,1,3),float('nan')))
            with self.assertRaisesRegex(ValueError,'index'):staged.write(4,torch.zeros(3,1,1,3))


if __name__=='__main__':unittest.main()
