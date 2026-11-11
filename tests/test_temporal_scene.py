import importlib.util
from pathlib import Path
import unittest
import numpy as np
import torch
spec=importlib.util.spec_from_file_location('temporal_scene_test',Path(__file__).resolve().parents[1]/'artist_studio/temporal_scene.py')
scene=importlib.util.module_from_spec(spec);spec.loader.exec_module(scene)

def geometry(count=8, offset=0, scale=1., transform=None):
 h,w=24,32;k=np.array([[32.,0,15.5],[0,32.,11.5],[0,0,1]])
 depth=np.full((count,h,w),3.,np.float32);rgb=np.full((count,h,w,3),.25,np.float32)
 poses=[]
 for i in range(count):
  x=2+(i+offset)*2;depth[i,8:14,x:x+4]=1.2;rgb[i,8:14,x:x+4]=[1,0,0]
  pose=np.eye(4)
  if transform is not None:pose[:3,:3]=transform[:3,:3];pose[:3,3]=transform[:3,3]
  poses.append(np.linalg.inv(pose)[:3])
 return {'mode':'multiview','depth':torch.from_numpy(depth*scale),'image':torch.from_numpy(rgb),'intrinsics':torch.from_numpy(np.repeat(k[None,None],count,1)).float(),'extrinsics':torch.tensor(np.array(poses)[None]).float()}

class TemporalSceneTests(unittest.TestCase):
 def test_bounded_shared_windows_cover_every_source_frame(self):
  for count in [2,12,13,49,150,361]:
   ranges=scene.windows(count);self.assertEqual(ranges[0][0],0);self.assertEqual(ranges[-1][1],count)
   self.assertTrue(all(b-a<=12 and b-a>=2 for a,b in ranges))
   for (a,b),(c,d) in zip(ranges,ranges[1:]):self.assertEqual(b-c,3)
 def test_joint_solve_is_required_not_monocular(self):
  with self.assertRaises(ValueError):scene.append_views({'mode':'mono'},0)
 def test_similarity_restores_scale_rotation_and_translation(self):
  rng=np.random.default_rng(4);a=rng.normal(size=(500,3));angle=.4;r=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]])
  b=a@r.T*2.3+[1,2,-.4];s,rotation,t,error=scene.fit_similarity(a,b)
  np.testing.assert_allclose(a@rotation.T*s+t,b,atol=1e-6);self.assertLess(error,1e-6)
 def test_overlapping_views_share_one_world_without_freezing_performance(self):
  first=geometry(8);packet=scene.append_views(first,0)
  second=geometry(5,offset=5,scale=2.)
  # A different gauge: the local camera sits at a translated world origin.
  second['extrinsics'][0,:,:,3]=torch.tensor([-2.,-1.,.5])
  joined=scene.append_views(second,5,packet)
  self.assertEqual(len(joined['points']),10);self.assertLess(joined['alignment_errors'][-1],.05)
  self.assertFalse(np.array_equal(joined['points'][0],joined['points'][6]))
 def test_static_scenery_has_zero_geometry_flicker_and_actor_stays_dynamic(self):
  packet=scene.append_views(geometry(),0);mesh,report=scene.scene_tensors(packet)
  n=report['background_vertices'];self.assertGreater(n,300)
  for vertices in mesh['vertices']:torch.testing.assert_close(vertices[:n],mesh['vertices'][0,:n])
  self.assertTrue(torch.all(mesh['vertex_counts']>n))
  means=[]
  for i in range(8):means.append(mesh['vertices'][i,n:int(mesh['vertex_counts'][i]),0].mean().item())
  self.assertGreater(max(means)-min(means),.2)
  self.assertAlmostEqual(report['reference_hfov'],53.130102,places=4)
 def test_occluding_actor_does_not_remove_static_wall(self):
  packet=scene.append_views(geometry(),0);wall=np.array([[0.,0.,3.]],np.float32)
  self.assertTrue(scene.static_support(wall,packet,np.arange(8))[0])
 def test_padding_holds_end_and_never_rounds_down(self):
  frames=torch.arange(3.).reshape(3,1,1,1);result,=scene.ZuraCameraPadFrames().pad(frames,9)
  self.assertEqual(len(result),9);self.assertTrue(torch.equal(result[3:],frames[-1:].expand(6,-1,-1,-1)))
 def test_model_padding_cannot_hide_missing_source_frames(self):
  frames=torch.zeros(3,2,2,3)
  with self.assertRaisesRegex(ValueError,'shorter than the requested interval'):
   scene.ZuraCameraPadFrames().pad(frames,9,required_source_frames=4)
  padded,=scene.ZuraCameraPadFrames().pad(frames,9,required_source_frames=3)
  self.assertEqual(len(padded),9)
 def test_vertex_colours_follow_native_linear_convention(self):
  self.assertAlmostEqual(float(scene.srgb_to_linear(np.array([.5]))[0]),.214041,places=5)
if __name__=='__main__':unittest.main()
