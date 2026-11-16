"""Receipted SDR FLOAT Image Layers EXR supplies an HDR model PNG, not a return substitute."""
import hashlib
import importlib
import json
from pathlib import Path
import unittest

import numpy as np
from PIL import Image
import test_studio_image_layers as fixture

output=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_output')
service=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_long_service')
float_io=importlib.import_module('ComfyUI_zura_nodes.comfylink.float_io')


class ReceiptedHDRImageTests(unittest.TestCase):
    setUp=fixture.ImageLayersTests.setUp
    tearDown=fixture.ImageLayersTests.tearDown
    png=fixture.ImageLayersTests.png
    path=fixture.ImageLayersTests.path

    def test_master_exr_retained_while_hdr_model_gets_explicit_sdr_png(self):
        product=fixture.layers.compose(self.body,self.roots)
        master=self.path(product['master']);original_sha=hashlib.sha256(master.read_bytes()).hexdigest()
        result=output.selected_hdr_model_image(self.roots['output'],product['master'])
        self.assertEqual(result.suffix,'.png')
        rgba,_=float_io.read_image_layer_exr(master,self.roots['output'])
        expected=np.rint(np.clip(rgba[...,:3],0,1)*255).astype(np.uint8)
        with Image.open(result) as image:
            self.assertEqual(image.mode,'RGB');np.testing.assert_array_equal(np.array(image),expected)
        lineage=json.loads(result.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual(lineage['kind'],'sdr8_model_view_from_image_layers_exr')
        self.assertEqual(lineage['originalMasterSha256'],original_sha)
        self.assertEqual(hashlib.sha256(master.read_bytes()).hexdigest(),original_sha,'The FLOAT return master is unchanged')
        self.assertEqual(output.selected_hdr_model_image(self.roots['output'],product['master']),result,'Repeated preflight reuses exact derivative')
        client=service.HDRLongService(None,None,None,self.roots['output'],check_setup=lambda *_:None)
        asset,check=client._asset({'source_kind':'output_image','output_ref':product['master']})
        self.assertEqual(asset['asset_kind'],'sdr_image')
        self.assertEqual(check(asset),result)
        with self.assertRaises(ValueError):
            output.selected_hdr_model_image(self.roots['output'],{'filename':'other.exr','type':'output'})


if __name__=='__main__':unittest.main()
