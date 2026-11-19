import base64,io,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
import test_studio_image_layers as bootstrap
import importlib,sys,types
sys.modules.setdefault("server",types.SimpleNamespace(PromptServer=types.SimpleNamespace(instance=None)))
static=importlib.import_module('ComfyUI_zura_nodes.paintout.mask_static')
store=importlib.import_module('ComfyUI_zura_nodes.paintout.editor_store')
segments=importlib.import_module('ComfyUI_zura_nodes.paintout.mask_segments')
render=importlib.import_module('ComfyUI_zura_nodes.paintout.paintout')
class StaticMasks(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.source=self.root/'source.mkv';self.source.write_bytes(b'source')
  self.info={'width':128,'height':64,'count':9,'kind':'video','path':str(self.source),'fps':24}
  self.patches=[patch.object(store,'project_root',return_value=self.root/'projects'),patch.object(static,'describe',side_effect=lambda _:self.info)]
  for p in self.patches:p.start();self.addCleanup(p.stop)
  self.project=store.save_project(data={'draft':{'source':str(self.source),'startFrame':2,'frameCount':5}})['id']
 def body(self):return {'project':self.project,'source':str(self.source),'expected_revision':store.load_project(self.project)['revision'],'startFrame':2,'frameCount':5}
 def data(self,pixels):
  stream=io.BytesIO();Image.fromarray(pixels).save(stream,format='PNG');return 'data:image/png;base64,'+base64.b64encode(stream.getvalue()).decode()
 def test_static_repeats_actual_gray_mask_without_tracking(self):
  mask=np.zeros((64,128),np.uint8);mask[10:20,20:40]=64;mask[0,0]=1
  body={**self.body(),'mask':self.data(mask)};started=time.monotonic()
  with patch.object(store,'_native_masks',side_effect=AssertionError('SAM must not run')):doc=static.save_static(body)
  self.assertLess(time.monotonic()-started,5);self.assertEqual(doc['mask_coverage'],list(range(2,7)));self.assertFalse(doc['mask_segments'][0]['tracked']);self.assertTrue(doc['mask_segments'][0]['ready'])
  descriptor=store.ZuraPaintoutMaskSource().load(self.project)[0];self.assertEqual(descriptor['width'],128)
  expected=mask.astype(np.float32)/255
  for frame in range(2,7):
   actual=store.read_project_mask(self.project,frame)
   self.assertTrue(np.array_equal(actual,expected));alpha,_=render.repair_matte(actual,0,0);self.assertTrue(np.array_equal(alpha,expected))
  summary=store.project_response(store.load_project(self.project));self.assertTrue(summary['mask_segments'][0]['ready'])
 def test_rgba_gray_times_alpha_and_transparent_white_keeps(self):
  pixels=np.zeros((64,128,4),np.uint8);pixels[...,3]=255;pixels[0,0]=[255,255,255,0];pixels[0,1]=[128,128,128,128];pixels[0,2]=[255,255,255,255]
  path=self.root/'mask.png';Image.fromarray(pixels).save(path);doc=static.import_still({**self.body(),'mask':str(path)});actual=store.read_project_mask(self.project,2)
  self.assertEqual(actual[0,0],0);self.assertAlmostEqual(float(actual[0,1]),64/255,places=6);self.assertEqual(actual[0,2],1);self.assertFalse(doc['mask_segments'][0]['tracked'])
 def test_palette_transparent_white_is_kept(self):
  image=Image.new('P',(128,64),0);image.putpalette([255,255,255,0,0,0]+[0]*762);image.info['transparency']=0;path=self.root/'palette.png';image.save(path)
  static.import_still({**self.body(),'mask':str(path)});self.assertFalse(store.read_project_mask(self.project,2).any())
 def test_original_portrait_dimensions_not_processing_grid(self):
  self.info.update(width=2160,height=3840);path=self.root/'portrait.png';Image.new('L',(2160,3840),255).save(path)
  with patch.object(static,'commit',return_value={'verified':True}) as commit:static.import_still({**self.body(),'mask':str(path)})
  self.assertEqual(commit.call_args.args[1].shape,(3840,2160))
  Image.new('L',(2176,3840),255).save(path)
  with self.assertRaisesRegex(ValueError,'original footage'):static.import_still({**self.body(),'mask':str(path)})
 def test_colour_wrong_range_and_source_change_reject_without_commit(self):
  path=self.root/'colour.png';Image.new('RGB',(128,64),'red').save(path)
  with self.assertRaisesRegex(ValueError,'grayscale'):static.import_still({**self.body(),'mask':str(path)})
  with self.assertRaises(ValueError):static.save_static({**self.body(),'frameCount':20,'mask':self.data(np.ones((64,128),np.uint8)*255)})
  identity=store.source_identity(str(self.source),self.info);self.source.write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'source changed'):static.commit(self.body(),np.ones((64,128),np.float32),'static_paint',expected_identity=identity)
  self.assertIsNone(store.load_project(self.project)['mask_revision'])
 def test_video_import_validates_original_clock_and_marks_ready_not_tracked(self):
  routes=importlib.import_module('ComfyUI_zura_nodes.paintout.editor_routes');path=self.root/'mask.mkv';path.write_bytes(b'mask')
  described={**self.info,'path':str(path),'fps_rational':'24/1'}
  def spool(info,directory):
   result={}
   for frame in range(info['count']):
    target=Path(directory)/f'{frame:08d}.png';Image.new('L',(128,64),64).save(target);result[frame]=str(target)
   return result
  with patch.object(routes,'describe',side_effect=lambda file:described if file==str(path) else self.info),patch.object(routes,'_spool_mask_video',side_effect=spool):
   doc=routes.import_mask_video({**self.body(),'mask':str(path)})
  self.assertFalse(doc['mask_segments'][0]['tracked']);self.assertTrue(doc['mask_segments'][0]['ready']);self.assertEqual(doc['segment_id'],doc['mask_segments'][0]['id']);self.assertAlmostEqual(float(store.read_project_mask(self.project,8)[0,0]),64/255)
  for key,value in [('fps_rational','25/1'),('count',8),('width',129)]:
   bad={**described,key:value}
   with patch.object(routes,'describe',side_effect=lambda file:bad if file==str(path) else self.info),self.assertRaises(ValueError):routes.import_mask_video({**self.body(),'mask':str(path)})
 def test_static_http_route_and_second_mask_union(self):
  import asyncio
  from aiohttp import web
  from aiohttp.test_utils import TestClient,TestServer
  routes=importlib.import_module('ComfyUI_zura_nodes.paintout.editor_routes')
  mask=np.zeros((64,128),np.uint8);mask[0,0]=64
  async def run():
   app=web.Application();app.router.add_post('/static',routes.static_mask)
   async with TestClient(TestServer(app)) as client:
    first=await client.post('/static',json={**self.body(),'mask':self.data(mask)});self.assertEqual(first.status,200);one=await first.json()
    secondMask=np.zeros_like(mask);secondMask[0,1]=128
    second=await client.post('/static',json={**self.body(),'mask':self.data(secondMask)});self.assertEqual(second.status,200);two=await second.json()
    self.assertNotEqual(one['segment_id'],two['segment_id']);self.assertEqual(two['segment_id'],two['mask_segments'][-1]['id'])
    actual=store.read_project_mask(self.project,2);self.assertAlmostEqual(float(actual[0,0]),64/255);self.assertAlmostEqual(float(actual[0,1]),128/255)
  asyncio.run(run())
 def test_eight_frame_static_cpu_timing(self):
  start=time.monotonic();static.save_static({**self.body(),'startFrame':0,'frameCount':8,'mask':self.data(np.ones((64,128),np.uint8)*255)})
  elapsed=time.monotonic()-start;self.assertLess(elapsed,5);print(f'Static CPU: 8 frames at 128x64 saved in {elapsed:.4f}s; no SAM/GPU')
if __name__=='__main__':unittest.main()
