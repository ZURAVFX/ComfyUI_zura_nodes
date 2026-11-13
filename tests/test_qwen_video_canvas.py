"""Video opening edits keep source, references and masks on one raster."""
import copy
import unittest
from unittest.mock import patch

import torch
import torch.nn.functional as functional
import test_artist_studio as fixture


class QwenVideoGraphTests(unittest.TestCase):
    def test_qwen21_grid_validation_prevents_a_separate_reference_canvas_mismatch(self):
        for width,height in ((512,512),(1024,1024),(1088,1920),(1920,1088)):
            p=fixture.SharedEngineTests().project()
            p['config']=fixture.studio.clean_config({**p['config'],'engine':'wan2','workflow_mode':'motion',
                'opening_model':'qwen21','opening_width':width,'opening_height':height,
                'image_prompt':'replace the centre character with my reference character'})
            with patch.object(fixture.studio,'assert_approved'),patch.object(fixture.studio,'check_asset'):
                graph=fixture.studio.build_graph(p,'design',use_cache=False)
            self.assertEqual(graph['92:109']['inputs']['resolution'],0)
            self.assertEqual(graph['92:127']['class_type'],'VAEEncode')
            self.assertEqual(graph['zura_opening_latent_mask']['inputs']['samples'],['92:127',0])
            self.assertEqual(graph['92:105']['class_type'],'SplitImageWithAlpha')
            self.assertEqual(width%32,0);self.assertEqual(height%32,0)
        with self.assertRaisesRegex(ValueError,'multiples of 32'):
            fixture.studio.clean_config({'opening_model':'qwen21','opening_width':1080,'opening_height':1920})

    def test_512_1024_portrait_landscape_edits_restore_working_raster_before_mask_stitch(self):
        for width, height in ((512,512), (1024,1024), (512,1024), (1024,512)):
            for workflow in ('swap', 'motion', 'viewport', 'relight'):
                with self.subTest(width=width, height=height, workflow=workflow):
                    p = fixture.SharedEngineTests().project()
                    p['config'] = fixture.studio.clean_config({**p['config'], 'engine':'h3',
                        'opening_model':'qwen2511', 'workflow_mode':workflow,
                        'opening_width':width, 'opening_height':height,
                        'image_prompt':'replace the centre character with my reference character'})
                    p['opening_input'] = {'file':'previous-result-must-not-be-used.png'}
                    original = copy.deepcopy(p)
                    with patch.object(fixture.studio,'assert_approved'), patch.object(fixture.studio,'check_asset'):
                        graph = fixture.studio.build_graph(p,'design',use_cache=False)
                    self.assertEqual(p, original)
                    self.assertNotIn('previous-result-must-not-be-used.png', str(graph))
                    self.assertEqual(graph['92:109']['inputs']['image1'], ['92:111',0])
                    self.assertEqual(graph['92:127']['class_type'], 'VAEEncode')
                    self.assertEqual(graph['92:127']['inputs'], {'pixels':['92:111',0], 'vae':['92:110',0]})
                    self.assertEqual(graph['92:127']['_meta']['title'], 'Encode reference 1 at source raster')
                    self.assertEqual(graph['zura_qwen_positive_reference_1']['class_type'], 'ReferenceLatent')
                    self.assertEqual(graph['zura_qwen_negative_reference_1']['class_type'], 'ReferenceLatent')
                    self.assertEqual(graph['zura_qwen_decoded']['inputs'], {'samples':['92:104',0], 'vae':['92:110',0]})
                    self.assertEqual(graph['92:105']['inputs'], {'image':['zura_qwen_decoded',0],
                        'width':['92:114',0], 'height':['92:114',1], 'upscale_method':'lanczos', 'crop':'disabled'})
                    if workflow in ('swap','motion','relight'):
                        fitted=graph['92:111']
                        self.assertEqual(fitted['class_type'],'ImageScale')
                        self.assertEqual(fitted['inputs']['image'],['125',0])
                        self.assertEqual((fitted['inputs']['width'],fitted['inputs']['height']),(width,height))
                        self.assertEqual(fitted['inputs']['crop'],'disabled')
                        if 'zura_look_source' in graph:
                            self.assertEqual(graph['zura_look_source']['inputs']['image'],['92:111',0])
                        if 'zura_masked_look' in graph:
                            self.assertEqual(graph['zura_masked_look']['inputs']['mask'],['zura_opening_inside_mask_working',0])
                            self.assertEqual(graph['zura_opening_preserve_source']['inputs']['mask'],['zura_opening_original_mask',0])
                            self.assertEqual(graph['zura_opening_original_mask_image']['inputs']['crop'],'disabled')
                    else:
                        self.assertEqual(graph['92:111']['class_type'],'ImageScale','Viewport authoring retains its explicit canvas policy')
                        self.assertEqual((graph['92:111']['inputs']['width'],graph['92:111']['inputs']['height']), (width,height))
                    if 'zura_opening_latent_mask' in graph:
                        self.assertEqual(graph['zura_opening_latent_mask']['inputs']['samples'], ['92:127',0])
                        self.assertEqual(graph['92:104']['inputs']['latent_image'], ['zura_opening_latent_mask',0])
                        self.assertEqual(graph['zura_opening_latent_mask']['inputs']['mask'],['zura_opening_sampling_mask_working',0])
                    else:
                        self.assertEqual(graph['92:104']['inputs']['latent_image'], ['92:127',0])
                    if 'zura_masked_look' in graph:
                        self.assertEqual(graph['zura_masked_look']['inputs']['source'], ['92:105',0])
                        self.assertEqual(graph['zura_opening_preserve_source']['inputs']['destination'], ['125',0])


class VideoRasterTensorTests(unittest.TestCase):
    def test_cpu_registration_stretches_and_restores_the_full_source_and_mask(self):
        # A coordinate raster catches accidental centre crops and padding.  The
        # production graph uses ImageScale with crop disabled for this same
        # working-raster registration and inverse restoration.
        for width, height, working_width, working_height in (
                (513, 257, 528, 272), (257, 513, 272, 528), (641, 359, 656, 368)):
            with self.subTest(source=(width, height), working=(working_width, working_height)):
                x = torch.linspace(0, 1, width)[None, :].expand(height, -1)
                y = torch.linspace(0, 1, height)[:, None].expand(-1, width)
                mask = torch.zeros((height, width))
                mask[height // 4:height // 2, width // 5:width // 2] = 1
                source = torch.stack((x, y, mask), dim=0)[None]
                working = functional.interpolate(source, size=(working_height, working_width),
                                                  mode='bilinear', align_corners=False)
                restored = functional.interpolate(working, size=(height, width),
                                                  mode='bilinear', align_corners=False)
                self.assertLess(float(restored[0, 0, 0, 0]), .02)
                self.assertGreater(float(restored[0, 0, -1, -1]), .98)
                self.assertGreater(float(restored[0, 1, -1, -1]), .98)
                yy, xx = torch.where(restored[0, 2] > .5)
                self.assertLessEqual(abs(int(xx.min()) - width // 5), 2)
                self.assertLessEqual(abs(int(xx.max()) - (width // 2 - 1)), 2)
                self.assertLessEqual(abs(int(yy.min()) - height // 4), 2)
                self.assertLessEqual(abs(int(yy.max()) - (height // 2 - 1)), 2)


if __name__=='__main__':unittest.main()
