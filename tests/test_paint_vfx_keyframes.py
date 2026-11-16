"""Sparse paint controls retain exact key positions and honest CPU bounds."""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import torch
import v2_bootstrap

if 'ComfyUI_zura_nodes.artist_studio' not in sys.modules:
    package=types.ModuleType('ComfyUI_zura_nodes.artist_studio');package.__path__=[str(v2_bootstrap.ROOT/'artist_studio')];sys.modules[package.__name__]=package
paint=importlib.import_module('ComfyUI_zura_nodes.artist_studio.paint_vfx')
import folder_paths


class PaintedKeyframeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.folder=patch.object(folder_paths,'get_input_directory',lambda:str(self.root));self.folder.start()
        self.colours={'red.png':(255,0,0),'green.png':(0,255,0),'blue.png':(0,0,255)}
        for name,colour in self.colours.items():Image.new('RGB',(4,4),colour).save(self.root/name)
        self.keys=json.dumps([{'frame':0,'image':'red.png'},{'frame':1,'image':'green.png'},{'frame':9,'image':'blue.png'},{'frame':16,'image':'red.png'}])

    def tearDown(self):self.folder.stop();self.temp.cleanup()

    def test_first_middle_last_are_sparse_rgb_on_primary_vae_group_slots(self):
        video,=paint.ZuraPaintKeyframeVideo().build(256,256,17,self.keys)
        self.assertEqual(tuple(video.shape),(17,256,256,3));self.assertEqual(video.dtype,torch.float32);self.assertEqual(video.device.type,'cpu')
        for frame,colour in [(0,[1,0,0]),(1,[0,1,0]),(9,[0,0,1]),(16,[1,0,0])]:
            self.assertTrue(torch.equal(video[frame],torch.tensor(colour,dtype=torch.float32).expand(256,256,3)))
        self.assertEqual(float(video[[2,3,4,5,6,7,8,10,11,12,13,14,15]].abs().sum()),0)
        self.assertEqual(paint.key_slots(17),[0,1,9,16])

    def test_explicit_nearest_canvas_stretch_keeps_flat_blobs_and_input_bytes(self):
        pixels=np.array([[[255,0,0],[0,255,0]],[[0,0,255],[255,255,255]]],np.uint8)
        Image.fromarray(pixels).save(self.root/'blobs.png');before=(self.root/'blobs.png').read_bytes()
        keys=json.dumps([{'frame':0,'image':'blobs.png'},{'frame':8,'image':'blobs.png'}])
        video,=paint.ZuraPaintKeyframeVideo().build(320,256,9,keys)
        self.assertEqual(len(torch.unique(video[0].reshape(-1,3),dim=0)),4)
        self.assertTrue(torch.equal(video[0,0,0],torch.tensor([1.,0,0])))
        self.assertTrue(torch.equal(video[0,-1,-1],torch.ones(3)))
        self.assertEqual((self.root/'blobs.png').read_bytes(),before)

    def test_geometry_memory_and_key_grid_reject_before_allocating(self):
        self.assertEqual(paint._geometry(512,512,121),121*512*512*3*4)
        self.assertLess(paint._geometry(960,512,81),paint.MAX_TENSOR_BYTES)
        bad=[(512,512,10),(255,256,9),(256,257,9),(True,256,9),(1984,256,9),(1920,1920,321)]
        with patch.object(paint.torch,'zeros',side_effect=AssertionError('allocated before validating')):
            for width,height,frames in bad:
                with self.subTest(width=width,height=height,frames=frames),self.assertRaises(ValueError):
                    paint.ZuraPaintKeyframeVideo().build(width,height,frames,self.keys)
            for keys in [[],[{'frame':0,'image':'red.png'}],
                         [{'frame':0,'image':'red.png'},{'frame':8,'image':'red.png'}],
                         [{'frame':0,'image':'red.png'},{'frame':0,'image':'red.png'},{'frame':16,'image':'red.png'}],
                         [{'frame':0,'image':'red.png'},{'frame':2,'image':'red.png'},{'frame':16,'image':'red.png'}],
                         [{'frame':True,'image':'red.png'},{'frame':16,'image':'red.png'}]]:
                with self.subTest(keys=keys),self.assertRaises(ValueError):paint.ZuraPaintKeyframeVideo().build(256,256,17,json.dumps(keys))

    def test_paths_transparency_orientation_and_oversized_headers_are_rejected(self):
        for name in ['../red.png','/red.png','C:/red.png','folder\\red.png','red.png [output]']:
            keys=json.dumps([{'frame':0,'image':name},{'frame':8,'image':'red.png'}])
            with self.subTest(name=name),self.assertRaises((ValueError,OSError)):paint.ZuraPaintKeyframeVideo().build(256,256,9,keys)
        Image.new('RGBA',(4,4),(255,0,0,128)).save(self.root/'alpha.png')
        keys=json.dumps([{'frame':0,'image':'alpha.png'},{'frame':8,'image':'red.png'}])
        with self.assertRaisesRegex(ValueError,'Flatten'):paint.ZuraPaintKeyframeVideo().build(256,256,9,keys)
        exif=Image.Exif();exif[274]=6;Image.new('RGB',(4,4)).save(self.root/'orientation.jpg',exif=exif)
        keys=json.dumps([{'frame':0,'image':'orientation.jpg'},{'frame':8,'image':'red.png'}])
        with self.assertRaisesRegex(ValueError,'oriented'):paint.ZuraPaintKeyframeVideo().build(256,256,9,keys)
        os.link(self.root/'blue.png',self.root/'linked.png')
        keys=json.dumps([{'frame':0,'image':'linked.png'},{'frame':8,'image':'red.png'}])
        with self.assertRaisesRegex(ValueError,'owned image'):paint.ZuraPaintKeyframeVideo().build(256,256,9,keys)

    def test_content_fingerprint_changes_even_with_identical_name_and_timestamp(self):
        cls=paint.ZuraPaintKeyframeVideo
        before=cls.IS_CHANGED(256,256,17,self.keys);stamp=(self.root/'red.png').stat()
        Image.new('RGB',(4,4),(0,0,0)).save(self.root/'red.png');os.utime(self.root/'red.png',ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        self.assertNotEqual(before,cls.IS_CHANGED(256,256,17,self.keys))


if __name__=='__main__':unittest.main()
