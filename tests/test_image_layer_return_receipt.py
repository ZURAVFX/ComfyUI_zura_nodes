"""Strict product RGB FLOAT receipt admission, without AE or GPU inference."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
import numpy as np
import OpenImageIO as oiio
import test_studio_image_layers as fixture
from comfylink import float_io

class ReceiptTests(unittest.TestCase):
    setUp=fixture.ImageLayersTests.setUp
    tearDown=fixture.ImageLayersTests.tearDown
    png=fixture.ImageLayersTests.png
    path=fixture.ImageLayersTests.path
    def product(self):
        result=fixture.layers.compose(self.body,self.roots)
        return result,self.path(result['master'])
    def read(self,path):return float_io.read_image_layer_exr(path,self.roots['output'])
    def update_hash(self,path):
        receipt=path.parent/'image-layers.json';value=json.loads(receipt.read_text())
        for entry in value['artifacts']:
            if entry['filename']==path.name:entry.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),byteLength=path.stat().st_size)
        receipt.write_text(json.dumps(value,sort_keys=True,separators=(',',':')),encoding='utf-8')
    def test_product_receipt_pins_master_preview_source_and_controls(self):
        result,path=self.product();rgba,side=self.read(path)
        self.assertEqual(rgba.shape,(8,12,4));self.assertTrue(np.all(rgba[...,3]==1));self.assertEqual(side['colour'],{'encoding':'unknown','sceneLinear':False})
        receipt=json.loads(side['productReceipt']);self.assertEqual(receipt['source']['sha256'],side['sourceImageSha256']);self.assertEqual(receipt['controls'][0]['id'],'layer-1')
        self.assertEqual(hashlib.sha256(side['productReceipt'].encode()).hexdigest(),side['receiptSha256'])
        original=path.read_bytes();self.read(path);self.assertEqual(path.read_bytes(),original)
    def test_missing_or_tampered_receipt_and_master_preview_fail_closed(self):
        for attack in ('missing','colour','source_hash','controls','master','preview','oversized'):
            result,path=self.product();receipt=path.parent/'image-layers.json'
            if attack=='missing':receipt.unlink()
            elif attack in ('master','preview'):
                target=path if attack=='master' else path.parent/'preview.png';target.write_bytes(target.read_bytes()+b'tamper')
            else:
                data=json.loads(receipt.read_text())
                if attack=='colour':data['colour']={'encoding':'acescg','sceneLinear':True}
                if attack=='source_hash':data['source']['sha256']='wrong'
                if attack=='controls':data['controls'][0]['opacity']=float('nan')
                if attack=='oversized':data['artifacts'][0]['width']=16385
                receipt.write_text(json.dumps(data),encoding='utf-8')
            with self.subTest(attack=attack),self.assertRaises((ValueError,OSError)):self.read(path)
    def test_unrecognised_headers_rgba_half_and_nonfinite_fail_even_with_matching_hash(self):
        for attack in ('unknown','half','rgba','nonfinite'):
            result,path=self.product();pixels=np.ones((8,12,4 if attack=='rgba' else 3),np.float32)
            if attack=='nonfinite':pixels[0,0,0]=np.inf
            spec=oiio.ImageSpec(12,8,pixels.shape[2],oiio.HALF if attack=='half' else oiio.FLOAT);spec.channelnames=('R','G','B','A') if attack=='rgba' else ('R','G','B')
            spec.attribute('oiio:ColorSpace','unknown' if attack=='unknown' else 'sRGB');spec.attribute('zura:encoding','srgb_display');spec.attribute('zura:dynamicRange','SDR')
            writer=oiio.ImageOutput.create(str(path));writer.open(str(path),spec);writer.write_image(pixels);writer.close();self.update_hash(path)
            with self.subTest(attack=attack),self.assertRaises(ValueError):self.read(path)
    def test_generic_exr_outside_product_namespace_is_never_admitted(self):
        path=self.roots['output']/'ordinary.exr';fixture.layers._write_master(path,np.ones((8,12,3),np.float32))
        with self.assertRaises(ValueError):self.read(path)

if __name__=='__main__':unittest.main()
