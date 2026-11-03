import base64,importlib,io,json,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[2];pkg=types.ModuleType('wm_test');pkg.__path__=[str(ROOT/'paintout')];sys.modules[pkg.__name__]=pkg
store=importlib.import_module('wm_test.editor_store');segments=importlib.import_module('wm_test.mask_segments');browser=types.ModuleType('wm_test.browser');browser.checked_path=Path;browser.grant=lambda x:x;sys.modules['wm_test.browser']=browser;routes=importlib.import_module('wm_test.editor_routes')
class StaticLayers(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name);self.p=patch.object(store,'project_root',return_value=self.root);self.p.start();self.addCleanup(self.p.stop);self.source=self.root/'shot.mkv';self.source.write_bytes(b'fixture');self.desc=dict(width=8,height=6,count=8);self.project=store.save_project(data={'workspace':'watermark','draft':{'source':str(self.source),'startFrame':0,'frameCount':8}})['id'];self.a=np.zeros((6,8),np.uint8);self.a[1:3,1:3]=255;self.b=np.zeros((6,8),np.uint8);self.b[3:5,4:6]=255
 def create(self,id,mask,start,end):
  buf=io.BytesIO();Image.fromarray(mask).save(buf,format='PNG');data='data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode();body=dict(project=self.project,source=str(self.source),segment_id=id*24,mask=data,clip_start=0,clip_end=7,layer_start=start,layer_end=end,expected_revision=store._read(self.project)['revision']);
  with patch.object(routes,'checked_path',side_effect=Path),patch.object(routes,'describe',return_value=self.desc):return routes.save_watermark_layer(body)
 def edit(self,id,start,end):
  browser=types.ModuleType('wm_test.browser');browser.checked_path=Path
  with patch.dict(sys.modules,{'wm_test.browser':browser}),patch('wm_test.paintout.describe',return_value=self.desc):return segments.edit_segment(dict(project=self.project,segment_id=id*24,start=start,end=end,expected_revision=store._read(self.project)['revision']))
 def test_layers_are_timed_composited_and_reversibly_trimmed(self):
  self.create('a',self.a,2,5);self.create('b',self.b,4,7)
  for frame in range(8):
   expected=np.maximum(self.a if 2<=frame<=5 else 0,self.b if 4<=frame<=7 else 0)/255
   np.testing.assert_array_equal(store.read_project_mask(self.project,frame),expected)
  self.edit('a',1,3)
  for frame in range(8):
   expected=np.maximum(self.a if 1<=frame<=3 else 0,self.b if 4<=frame<=7 else 0)/255
   np.testing.assert_array_equal(store.read_project_mask(self.project,frame),expected)
  self.assertEqual(store.mask_descriptor(self.project)['count'],8)
  with patch.object(routes,'checked_path',side_effect=Path),patch.object(routes,'describe',return_value=self.desc):
   result=routes.export_watermark_mask(dict(project=self.project,source=str(self.source),revision=store._read(self.project)['mask_revision'],start=0,count=8,grow=0,fps=25))
  import subprocess
  path=self.root/self.project/'exports'/result['filename'];raw=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-f','rawvideo','-pix_fmt','gray','-'],capture_output=True,check=True).stdout
  frames=np.frombuffer(raw,np.uint8).reshape(8,6,8)
  for frame in range(8):
   expected=np.maximum(self.a if 1<=frame<=3 else 0,self.b if 4<=frame<=7 else 0)
   np.testing.assert_array_equal(frames[frame],expected)

if __name__=='__main__':unittest.main()
