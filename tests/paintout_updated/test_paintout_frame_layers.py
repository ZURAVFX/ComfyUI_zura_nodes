"""Clean-frame layers remain independent when earlier cumulative edits are deleted."""
import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import numpy as np
import torch
from PIL import Image
from test_paintout_frame_editor import ROOT, editor, png_mask
spec=importlib.util.spec_from_file_location('zura_frame_test.frame_layers', ROOT/'paintout/frame_layers.py')
layers=importlib.util.module_from_spec(spec);sys.modules[spec.name]=layers;spec.loader.exec_module(layers)


class PaintLayerTests(unittest.TestCase):
    def test_inward_blend_has_expected_pixel_ramp_and_wider_edge(self):
        mask=np.zeros((20,24),np.float32);mask[2:18,2:22]=1
        original_mask=mask.copy()
        hard=layers.inward_layer_alpha(mask,0)
        narrow=layers.inward_layer_alpha(mask,2)
        wide=layers.inward_layer_alpha(mask,4)
        np.testing.assert_array_equal(hard,mask)
        np.testing.assert_array_equal(mask,original_mask)
        np.testing.assert_allclose(wide[10,2:7],[.125,.375,.625,.875,1])
        self.assertTrue(np.all(wide<=narrow))
        self.assertTrue(np.all(np.diff(wide[10,2:7])>=0))
        np.testing.assert_array_equal(wide[mask==0],0)
        self.assertEqual(wide[10,12],1)

    def test_full_frame_mask_does_not_blend_back_the_original_at_image_edges(self):
        mask=np.ones((20,24),np.float32)
        for width in (1,4,100):
            np.testing.assert_array_equal(layers.inward_layer_alpha(mask,width),mask)

    def test_thin_clipped_masks_stay_opaque_at_each_frame_border(self):
        for turns in range(4):
            mask=np.zeros((20,24),np.float32);mask[4:16,-3:]=1
            mask[6:9,5:8]=1  # A separate in-frame part should retain its blend.
            mask=np.rot90(mask,turns).copy()
            alpha=layers.inward_layer_alpha(mask,100)
            edge=np.zeros_like(mask,dtype=bool);edge[0]=True;edge[-1]=True;edge[:,0]=True;edge[:,-1]=True
            np.testing.assert_array_equal(alpha[edge & (mask>0)],mask[edge & (mask>0)])
            np.testing.assert_array_equal(alpha[mask==0],0)
            self.assertGreater(int(np.count_nonzero((alpha>0)&(alpha<.02))),0)
            original=np.full((*mask.shape,3),8,np.float32)
            candidate=np.full_like(original,.25)
            result=layers.compose_pixels(original,[(candidate,mask,100)],linear=True)
            np.testing.assert_array_equal(result[edge & (mask>0)],candidate[edge & (mask>0)])

    def test_manual_brightness_is_exposure_in_linear_light_and_unclipped_hdr(self):
        original=np.zeros((8,9,3),np.float32);candidate=np.full_like(original,.5)
        mask=np.zeros((8,9),np.float32);mask[2:6,2:7]=1
        brighter=layers.compose_pixels(original,[(candidate,mask,0,1.)])
        expected=.68583612
        np.testing.assert_allclose(brighter[mask>0],expected,atol=2e-7)
        np.testing.assert_array_equal(brighter[mask==0],original[mask==0])
        np.testing.assert_array_equal(layers.compose_pixels(original,[(candidate,mask,0,0)]),layers.compose_pixels(original,[(candidate,mask)]))
        hdr=np.empty_like(candidate);hdr[:]=[-.25,3.,20.]
        protected=np.zeros_like(mask);protected[3,3]=1
        result=layers.compose_pixels(original,[(hdr,mask,0,2.)],protected,linear=True)
        np.testing.assert_array_equal(result[(mask>0)&(protected==0)],hdr[(mask>0)&(protected==0)]*4)
        np.testing.assert_array_equal(result[(mask==0)|(protected>0)],original[(mask==0)|(protected>0)])

    def test_brightness_validation_rejects_non_finite_or_unsupported_controls(self):
        original=np.zeros((4,5,3),np.float32);mask=np.ones((4,5),np.float32)
        for value in (-2.01,2.01,True,False,'1',None,float('nan'),float('inf')):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'stops'):
                layers.compose_pixels(original,[(original,mask,0,value)])
        for value in (-2,0,1.25,2):self.assertEqual(layers.validate_brightness_ev(value),float(value))

    def test_blended_overlap_reorders_and_deletes_against_current_underlying_layers(self):
        original=np.zeros((14,14,3),np.float32)
        first_mask=np.zeros((14,14),np.float32);first_mask[1:9,1:9]=1
        second_mask=np.zeros_like(first_mask);second_mask[4:12,4:12]=1
        first=original.copy();first[first_mask>0]=[8,0,0]
        cumulative=first.copy();cumulative[second_mask>0]=[0,12,0]
        both=layers.compose_pixels(original,[(first,first_mask,0),(cumulative,second_mask,2)])
        deleted=layers.compose_pixels(original,[(cumulative,second_mask,2)])
        reordered=layers.compose_pixels(original,[(cumulative,second_mask,2),(first,first_mask,0)])
        # The later edge is 25% green over the current underlying pixels.
        np.testing.assert_array_equal(both[4,5],[6,3,0])
        np.testing.assert_array_equal(deleted[4,5],[0,3,0])
        np.testing.assert_array_equal(reordered[4,5],[8,0,0])
        np.testing.assert_array_equal(deleted[second_mask==0],original[second_mask==0])
        np.testing.assert_array_equal(both[(first_mask==0)&(second_mask==0)],original[(first_mask==0)&(second_mask==0)])

    def test_blended_hdr_preserves_outside_and_protected_samples_exactly(self):
        original=np.linspace(-3,32,20*24*3,dtype=np.float32).reshape(20,24,3)
        mask=np.zeros((20,24),np.float32);mask[3:17,4:20]=1
        protection=np.zeros_like(mask);protection[7:12,8:13]=1
        candidate=np.full_like(original,100)
        result=layers.compose_pixels(original,[(candidate,mask,4)],protection)
        unchanged=(mask==0)|(protection>.001)
        np.testing.assert_array_equal(result[unchanged],original[unchanged])
        self.assertTrue(np.isfinite(result).all())
        np.testing.assert_allclose(result[3,4],original[3,4]*.875+candidate[3,4]*.125)
        self.assertGreater(float(result[unchanged].max()),1)
        self.assertLess(float(result[unchanged].min()),0)

    def test_default_zero_blend_retains_existing_fractional_alpha_behaviour(self):
        original=np.full((4,5,3),.3,np.float32)
        mask=np.full((4,5),.25,np.float32)
        candidate=np.full_like(original,.9)
        old=layers.compose_pixels(original,[(candidate,mask)])
        explicit=layers.compose_pixels(original,[(candidate,mask,0)])
        np.testing.assert_array_equal(old,explicit)
        np.testing.assert_array_equal(old,original*.75+candidate*.25)

    def test_blend_edge_only_accepts_whole_pixels_in_supported_range(self):
        original=np.zeros((4,5,3),np.float32);mask=np.ones((4,5),np.float32)
        for value in [-1,101,True,False,1.,0.,float('nan'),float('inf'),'2',None,np.int64(2)]:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'0 to 100'):
                layers.compose_pixels(original,[(original,mask,value)])
        for value in (0,100):
            self.assertEqual(layers.validate_blend_pixels(value),value)

    def test_delete_earlier_layer_does_not_restore_it_from_cumulative_later_file(self):
        original=np.zeros((12,16,3),np.float32)
        first_mask=np.zeros((12,16),np.float32);first_mask[2:7,2:8]=1
        second_mask=np.zeros_like(first_mask);second_mask[5:10,6:13]=1
        first=original.copy();first[first_mask>0]=[1,0,0]
        cumulative=first.copy();cumulative[second_mask>0]=[0,1,0]
        both=layers.compose_pixels(original,[(first,first_mask),(cumulative,second_mask)])
        deleted=layers.compose_pixels(original,[(cumulative,second_mask)])
        np.testing.assert_array_equal(deleted[second_mask==0],original[second_mask==0])
        np.testing.assert_array_equal(deleted[second_mask>0],cumulative[second_mask>0])
        self.assertTrue(np.any(both!=deleted))
        np.testing.assert_array_equal(layers.compose_pixels(original,[(first,first_mask)]),first)

    def test_hdr_negative_and_highlight_values_outside_masks_are_exact(self):
        original=np.linspace(-3,32,12*16*3,dtype=np.float32).reshape(12,16,3)
        mask=np.zeros((12,16),np.float32);mask[3:8,4:12]=1
        protection=np.zeros_like(mask);protection[5:7,7:9]=1
        result=layers.compose_pixels(original,[(np.full_like(original,15),mask)],protection)
        unchanged=(mask==0)|(protection>0)
        np.testing.assert_array_equal(result[unchanged],original[unchanged])
        self.assertEqual(result[3,4,0],15)

    def test_invalid_layer_dimensions_or_pixels_fail(self):
        original=np.zeros((12,16,3),np.float32);mask=np.ones((12,16),np.float32)
        for pixels,badmask in [(original[:3],mask),(original,mask[:2]),(original,np.full_like(mask,np.nan)),(np.full_like(original,np.inf),mask),(original,mask*2)]:
            with self.assertRaises(ValueError):layers.compose_pixels(original,[(pixels,badmask)])

    def test_layer_mask_round_trip(self):
        mask=np.zeros((12,16),np.float32);mask[2:6,4:9]=1
        np.testing.assert_array_equal(editor.decode_mask(layers.encode_layer_mask(mask),16,12),mask)

    def test_frame_crop_uses_current_base_without_changing_original_source_identity(self):
        mask=np.zeros((73,125),np.float32);mask[25:38,50:66]=1
        with tempfile.TemporaryDirectory() as directory:
            source=pathlib.Path(directory)/'source.png';Image.new('RGB',(125,73),(64,64,64)).save(source)
            base=np.full((73,125,3),.75,np.float32)
            browser=types.SimpleNamespace(checked_path=lambda path: pathlib.Path(path))
            with patch.dict(sys.modules,{'zura_frame_test.browser':browser}),patch.object(layers,'load_layer_image',return_value=(base,'srgb_display')):
                output=editor.ZuraPaintoutFrameCrop().prepare(str(source),0,'srgb_display',png_mask(mask),0,0,20,256,base_file='current.exr',base_colour_space='srgb_display')
            np.testing.assert_array_equal(output[2]['delivery_original'],base)
            self.assertEqual(output[2]['source'],str(source))
            self.assertEqual(output[2]['identity'],editor.source_identity(editor.describe(str(source))))

    def test_compose_api_saves_standard_result_and_checks_project_revision(self):
        class Conflict(ValueError): pass
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);source=root/'source.png';candidate=root/'candidate.png'
            Image.new('RGB',(16,12),(20,20,20)).save(source);Image.new('RGB',(16,12),(200,50,20)).save(candidate)
            document={'revision':4,'data':{'draft':{'source':str(source)}}}
            store=types.SimpleNamespace(load_project=lambda project:document, source_identity=lambda *args:{'source':'same'},
                                       mask_descriptor=lambda *args:(_ for _ in ()).throw(ValueError('Create a removal mask before rendering.')),RevisionConflict=Conflict)
            browser=types.SimpleNamespace(checked_path=lambda path:pathlib.Path(path),grant=lambda path:str(path))
            folders=types.SimpleNamespace(get_output_directory=lambda:str(root/'output'))
            mask=np.zeros((12,16),np.float32);mask[3:6,4:8]=1
            body=dict(project='test',source=str(source),frame=0,colour_space='srgb_display',expected_revision=4,
                      layers=[dict(file=str(candidate),colour_space='srgb_display',mask=png_mask(mask))])
            with patch.dict(sys.modules,{'zura_frame_test.browser':browser,'zura_frame_test.editor_store':store,'folder_paths':folders}):
                row=layers.compose_layers(body)
                self.assertTrue(pathlib.Path(row['file']).is_file());self.assertTrue(pathlib.Path(row['png_file']).is_file())
                self.assertEqual((row['width'],row['height'],row['frame']),(16,12,0))
                self.assertEqual(row['blend_widths'],[0]);self.assertEqual(row['brightness_values'],[0.0])
                blended=layers.compose_layers(dict(body,layers=[dict(body['layers'][0],blend_pixels=2)]))
                self.assertEqual(blended['blend_widths'],[2])
                brightened=layers.compose_layers(dict(body,layers=[dict(body['layers'][0],brightness_ev=.5)]))
                self.assertEqual(brightened['brightness_values'],[.5])
                self.assertEqual(body['layers'][0].get('brightness_ev'),None)
                pixels=layers.read_image(blended['file'])
                expected=np.array([20,20,20],np.float32)/255*.75+np.array([200,50,20],np.float32)/255*.25
                np.testing.assert_allclose(pixels[3,4],expected,atol=1e-6)
                for invalid in (True,2.5,101):
                    with self.subTest(blend_pixels=invalid),self.assertRaisesRegex(ValueError,'0 to 100'):
                        layers.compose_layers(dict(body,layers=[dict(body['layers'][0],blend_pixels=invalid)]))
                with self.assertRaises(Conflict):layers.compose_layers(dict(body,expected_revision=3))
                with self.assertRaisesRegex(ValueError,'1 and 32'):layers.compose_layers(dict(body,layers=[]))
                other=root/'other.png';Image.new('RGB',(16,12)).save(other)
                with self.assertRaisesRegex(ValueError,'original shot'):layers.compose_layers(dict(body,source=str(other)))

    def test_base_dimension_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            file=pathlib.Path(directory)/'base.png';Image.new('RGB',(10,8)).save(file)
            browser=types.SimpleNamespace(checked_path=lambda path:pathlib.Path(path))
            with patch.dict(sys.modules,{'zura_frame_test.browser':browser}):
                with self.assertRaisesRegex(ValueError,'dimensions'):
                    layers.load_layer_image(str(file),'srgb_display',(12,16))


if __name__=='__main__':unittest.main()
