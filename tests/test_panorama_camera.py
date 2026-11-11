import importlib.util
import json
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('camera_test',Path(__file__).resolve().parents[1]/'artist_studio/panorama_camera.py');camera=importlib.util.module_from_spec(spec);spec.loader.exec_module(camera)
class CameraTests(unittest.TestCase):
 source={'sha':'a'*64,'duration':10,'has_audio':True,'file':'source.mp4','fps':30}
 def test_replaces_independent_depth_with_overlapping_joint_solves(self):
  p=camera.plan(self.source,{'duration':2});g=camera.build_graph(self.source,p,None,'geometry')
  kinds=[n['class_type']for n in g.values()];self.assertNotIn('MoGeInference',kinds);self.assertIn('DA3Inference',kinds)
  self.assertEqual(g['da3']['inputs']['weight_dtype'],'fp32');self.assertEqual(g['solve_0']['inputs']['mode'],'multiview')
  self.assertEqual(g['views_1']['inputs']['batch_index'],9);self.assertEqual(g['align_1']['inputs']['previous'],['align_0',0]);self.assertEqual(g['panorama']['inputs']['state_json'],['scene',1])
 def test_ltx25_dual_guide_contract_and_exact_source_delivery(self):
  p=camera.plan(self.source,{'duration':.5,'width':1136,'height':1760});g=camera.build_graph(self.source,p,None,'render',warp='warp.mp4')
  self.assertEqual(p['frames'],15);self.assertEqual(p['padded'],17);self.assertTrue(g['model']['inputs']['unet_name'].startswith('ltx-2.5'))
  self.assertFalse(any('MiniMax' in n['class_type'] for n in g.values()))
  self.assertEqual(g['source_guide']['inputs']['positive'],['warp_guide',0]);self.assertEqual(g['source_guide']['inputs']['image'],['source_pad',0]);self.assertEqual(g['source_guide']['inputs']['latent_downscale_factor'],1.)
  self.assertEqual(g['trim']['inputs']['length'],15);self.assertEqual(g['video']['inputs']['fps'],30);self.assertEqual(g['video']['inputs']['audio'],['source',2]);self.assertEqual(g['restore_output']['inputs']['crop'],'disabled')
 def test_two_stage_uses_ltx25_upscaler_and_refine_schedule(self):
  p=camera.plan(self.source,{'duration':1,'two_stage':True});g=camera.build_graph(self.source,p,None,'render',warp='warp.mp4')
  self.assertIn('ltx-2.5',g['upscale_model']['inputs']['model_name']);self.assertEqual(g['refine_sigmas']['inputs']['sigmas'],'0.909375,0.725,0.421875,0.0')
 def test_silent_nonhuman_shot_does_not_need_fake_audio(self):
  src={**self.source,'has_audio':False};p=camera.plan(src,{'duration':1});g=camera.build_graph(src,p,None,'render',warp='warp.mp4');self.assertNotIn('audio',g['video']['inputs'])
 def test_old_geometry_modes_migrate_without_reusing_old_caches(self):
  a=camera.plan(self.source,{'duration':1,'geometry_mode':'stable_scene'});b=camera.plan(self.source,{'duration':1,'geometry_mode':'per_frame'});self.assertEqual(a['key'],b['key']);self.assertEqual(a['geometry_mode'],'temporal_scene')
 def test_4k_padding_and_optional_image_reference(self):
  p=camera.plan(self.source,{'duration':1,'width':3840,'height':2160});g=camera.build_graph(self.source,p,None,'render',warp='warp.mp4',look='look.png');self.assertEqual(p['render_height'],2176);self.assertEqual(g['look_guide']['inputs']['frame_idx'],-1)
 def test_source_time_and_camera_timeline_share_rate(self):
  p=camera.plan({**self.source,'fps':30000/1001},{'duration':1,'start':.5});state=json.loads(camera.camera_state(None,p));self.assertEqual(state['timeline']['fps'],30000/1001)
 def test_all_links_resolve_and_reject_cuts_or_invalid_raster(self):
  p=camera.plan(self.source,{'duration':1})
  for stage in ['geometry','warp','render']:
   graph=camera.build_graph(self.source,p,None,stage,warp='warp.mp4')
   for n in graph.values():
    for value in n['inputs'].values():
     if isinstance(value,list):self.assertIn(value[0],graph)
  for config in [{'duration':6},{'start':9,'duration':2},{'width':1919},{'width':4096,'height':4096}]:
   with self.assertRaises(ValueError):camera.plan(self.source,config)
if __name__=='__main__':unittest.main()
