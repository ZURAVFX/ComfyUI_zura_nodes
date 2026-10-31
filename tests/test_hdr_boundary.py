"""A colour boundary must not become a straight line through an HDR shot."""
import importlib
import sys
import types
import unittest
from unittest.mock import patch

import torch
import v2_bootstrap

for name, folder in [('ComfyUI_zura_nodes.artist_studio','artist_studio')]:
    if name not in sys.modules:
        package=types.ModuleType(name);package.__path__=[str(v2_bootstrap.ROOT/folder)];sys.modules[name]=package
boundary=importlib.import_module('ComfyUI_zura_nodes.artist_studio.hdr_boundary')


class BoundaryTests(unittest.TestCase):
    def tearDown(self):
        boundary._system.cache_clear()

    def fixture(self):
        x=torch.linspace(.25,.55,96)[None,:,None]
        image=x.expand(64,96,3)[None].clone()
        source=image+torch.tensor([.025,-.015,.04])
        mask=torch.ones(1,64,96);mask[:,12:52,16:80]=0
        # Padding has no valid scene colour and must never anchor the solve.
        source=torch.where(mask[...,None]>0,torch.full_like(source,.07290553),source)
        return image,source,mask

    def test_preserves_exact_native_plate_and_removes_colour_step(self):
        image,source,mask=self.fixture()
        result=boundary.refine_hdr_boundary(image,source,mask)
        self.assertTrue(torch.equal(result[mask==0],source[mask==0]))
        # Across the join, the underlying horizontal ramp remains a ramp.
        expected=image[0,32,16]-image[0,32,15]
        torch.testing.assert_close(result[0,32,16]-result[0,32,15],expected,rtol=0,atol=6e-5)
        torch.testing.assert_close(result[0,12,48]-result[0,11,48],torch.zeros(3),rtol=0,atol=6e-5)
        self.assertTrue(torch.isfinite(result).all())

    def test_does_not_create_a_new_falloff_ring(self):
        image,source,mask=self.fixture()
        result=boundary.refine_hdr_boundary(image,source,mask)
        # Smooth correction continues to the image edge rather than abruptly
        # vanishing at a fixed feather distance in a narrow generated border.
        correction=result-image
        self.assertGreater(float(correction[0,0,48,0]),.02)
        self.assertLess(float(torch.diff(correction[0,:12,48,0]).abs().max()),1e-4)

    def test_reference_is_frame_local_and_never_borrowed_across_a_cut(self):
        image,source,mask=self.fixture()
        images=image.repeat(3,1,1,1);sources=source.repeat(3,1,1,1);masks=mask.repeat(3,1,1)
        sources[1,:, :,0]+=.1;masks[2]=1
        result=boundary.refine_hdr_boundary(images,sources,masks)
        self.assertTrue(torch.equal(result[2],images[2]))
        torch.testing.assert_close(result[:2,32,16],sources[:2,32,16],rtol=0,atol=0)

    def test_large_canvas_iterative_solver_matches_direct(self):
        image,source,mask=self.fixture()
        expected=boundary.refine_hdr_boundary(image,source,mask)
        boundary._system.cache_clear()
        with patch.object(boundary,'_DIRECT_LIMIT',0):
            actual=boundary.refine_hdr_boundary(image,source,mask)
        torch.testing.assert_close(actual,expected,rtol=0,atol=2e-6)

    def test_empty_full_masks_and_disabled_correction(self):
        image,source,mask=self.fixture()
        self.assertTrue(torch.equal(boundary.refine_hdr_boundary(image,source,torch.ones_like(mask)),image))
        self.assertTrue(torch.equal(boundary.refine_hdr_boundary(image,source,torch.zeros_like(mask)),source))
        self.assertTrue(torch.equal(boundary.refine_hdr_boundary(image,source,mask,strength=0),image))

    def test_partial_strength_and_soft_masks_remain_predictable(self):
        image,source,mask=self.fixture()
        actual=boundary.refine_hdr_boundary(image,source,torch.zeros_like(mask),strength=.5)
        torch.testing.assert_close(actual,image+(source-image)*.5,rtol=0,atol=0)
        mask[:,12,16:80]=.25
        self.assertTrue(torch.equal(boundary.refine_hdr_boundary(image,source,mask),image))

    def test_owned_output_can_be_reused_without_mutating_other_inputs(self):
        image,source,mask=self.fixture()
        saved=image.clone();reference=source.clone();expected=boundary.refine_hdr_boundary(image,source,mask)
        self.assertTrue(torch.equal(image,saved))
        actual=boundary.refine_hdr_boundary(image,source,mask,inplace=True)
        self.assertEqual(actual.data_ptr(),image.data_ptr())
        torch.testing.assert_close(actual,expected,rtol=0,atol=0)
        self.assertTrue(torch.equal(source,reference))
        self.assertEqual(boundary._system.cache_info().currsize,0)


if __name__=='__main__':unittest.main()
