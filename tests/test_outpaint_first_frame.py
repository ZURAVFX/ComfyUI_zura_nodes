import importlib
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
import test_artist_studio

guide = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_first_frame')
timing = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_studio')
anchor = importlib.import_module('ComfyUI_zura_nodes.artist_studio.outpaint_anchor')


class FirstFrameGuideTests(unittest.TestCase):
    def test_uploaded_guides_require_exact_final_dimensions_and_validated_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'guide.png';Image.new('RGB',(256,128)).save(path)
            asset={'asset_kind':'image','file':'genj_studio/a/guide.png'}
            studio=SimpleNamespace(store=SimpleNamespace(load=lambda _:asset))
            check=lambda value:path
            self.assertIs(guide.guide_asset(studio,'a',{'width':256,'height':128},check),asset)
            with self.assertRaisesRegex(ValueError,'256 × 256'):
                guide.guide_asset(studio,'a',{'width':256,'height':256},check)
            def changed(_):raise ValueError('changed')
            with self.assertRaisesRegex(ValueError,'changed'):
                guide.guide_asset(studio,'a',{'width':256,'height':128},changed)

    def test_native_padding_keeps_original_pixels_and_both_sampler_guides(self):
        import folder_paths
        with tempfile.TemporaryDirectory() as tmp,patch.object(folder_paths,'get_input_directory',return_value=tmp):
            path=Path(tmp)/'image.png';image=Image.new('RGB',(256,270),(30,60,90));image.putpixel((12,13),(255,0,0));image.save(path)
            relative=guide.prepare_anchor({'file':'image.png'},{'width':256,'height':270},lambda _:path)
            with Image.open(Path(tmp)/relative) as result:
                self.assertEqual(result.size,(256,320));self.assertEqual(result.getpixel((12,13)),(255,0,0));self.assertEqual(result.getpixel((12,319)),(30,60,90))
            source={'file':'genj_studio/a/source.mp4','sha':'a'*64,'duration':2,'width':128,'height':128}
            selection=timing.plan(source,start=0,duration=1,mode='expand',width=256,height=256,left=64,top=64,right=64,bottom=64)
            graph=timing.build_studio_graph(source,selection,review_key=selection['review_key'],output_prefix='genj/outpaint/guide')
            result=anchor.attach_first_frame(graph,relative)
            self.assertEqual(result['guide']['inputs']['latent'],['zura_anchor_i2v',0])
            self.assertEqual(result['guide']['inputs']['image'],graph['guide']['inputs']['image'])

    @unittest.skipUnless(shutil.which('ffmpeg'),'FFmpeg required')
    def test_canvas_matches_crop_and_margin_geometry_without_loading_a_model(self):
        import folder_paths
        with tempfile.TemporaryDirectory() as tmp,patch.object(folder_paths,'get_input_directory',return_value=tmp):
            path=Path(tmp)/'source.png';Image.new('RGB',(128,128),(255,0,0)).save(path)
            saved=[];studio=SimpleNamespace(store=SimpleNamespace(save=saved.append))
            source={'file':'genj_studio/a/source.png','sha':'a'*64,'duration':1,'width':128,'height':128}
            body={'start':0,'duration':1,'mode':'expand','width':256,'height':256,'left':64,'top':64,'right':64,'bottom':64}
            asset=guide.create_canvas(studio,source,body,lambda _:path)
            with Image.open(Path(tmp)/asset['file']) as result:
                self.assertEqual(result.size,(256,256));self.assertEqual(result.getpixel((0,0)),(0,0,0));self.assertEqual(result.getpixel((80,80)),(255,0,0))
            self.assertEqual(saved,[asset])
            # Enlarged footage is cropped within the output, never allocated
            # as a massive intermediate for the 1000% scale setting.
            body.update(left=-1024,right=-1024,top=-1024,bottom=-1024)
            asset=guide.create_canvas(studio,source,body,lambda _:path)
            with Image.open(Path(tmp)/asset['file']) as result:
                self.assertEqual(result.size,(256,256));self.assertEqual(result.getpixel((0,0)),(255,0,0))

if __name__=='__main__':unittest.main()
