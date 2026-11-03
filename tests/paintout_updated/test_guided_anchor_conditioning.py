"""The guided method maps source-frame anchors into LTX's temporal guide."""
import importlib, json, sys, tempfile, types, unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
package=types.ModuleType('guided_anchor_test');package.__path__=[str(ROOT/'paintout')];sys.modules[package.__name__]=package
core=importlib.import_module('guided_anchor_test.paintout')

class GuidedAnchors(unittest.TestCase):
    def test_timed_anchors_are_mapped_sorted_and_applied_with_strengths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();mask=root/'mask.png';a=root/'a.png';b=root/'b.png'
            frame=np.full((64,64,3),80,np.uint8)
            for i in range(27):Image.fromarray(frame).save(source/f'{i:03}.png')
            matte=np.zeros((64,64),np.uint8);matte[24:40,24:40]=255;Image.fromarray(matte).save(mask)
            Image.fromarray(frame).save(a);Image.fromarray(frame+10).save(b)
            _,_,plate,*_=core.ZuraPaintoutCrop().prepare(str(source),str(mask),'srgb_display',10,17,25,32,768,0,0,processing_mode='SDR (sRGB)',framing_mode='Plate resolution (stretch to next grid)',render_width=64,render_height=64)
            rows=[dict(file=str(b),frame=26,strength=.55),dict(file=str(a),frame=10,strength=.75)]
            anchors,report=core.ZuraPaintoutAnchors().load(plate,json.dumps(rows));self.assertEqual([(i,s) for i,_,s in anchors],[(0,.75),(16,.55)])
            self.assertIn('Source 10 -> local 0',report);self.assertIn('Source 26 -> local 16',report)
            calls=[]
            class Guide:
                @staticmethod
                def execute(**kw):
                    calls.append(kw);n=len(calls);return (f'positive{n}',f'negative{n}',f'latent{n}')
            with patch.dict(sys.modules,{'nodes':types.SimpleNamespace(NODE_CLASS_MAPPINGS={'LTXAddVideoICLoRAGuide':Guide})}):
                out=core.ZuraPaintoutApplyAnchors().apply('p0','n0','vae','l0',anchors)
            self.assertEqual([(x['frame_idx'],x['strength']) for x in calls],[(0,.75),(16,.55)])
            self.assertEqual((calls[1]['positive'],calls[1]['negative'],calls[1]['latent']),('positive1','negative1','latent1'))
            self.assertEqual(out,('positive2','negative2','latent2'))
            rows[0]['frame']=27
            with self.assertRaisesRegex(ValueError,'outside selected source range'):core.ZuraPaintoutAnchors().load(plate,json.dumps(rows))

if __name__=='__main__':unittest.main()
